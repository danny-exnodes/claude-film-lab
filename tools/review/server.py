#!/usr/bin/env python3
"""Film Lab review server: live status of 3D builds and renders, a model viewer and a video timeline (tools/review/).

Runs in the film-lab-review container (tools/review/docker-compose.yml); standard library only.

  python server.py --db /data/review.db --media /media --web /app/web [--public-port 8790] [--ingest-port 8791]

Two listeners:
  public 8790 (read-only: GET/HEAD only, every other method is 405)
      /                      the web app (tools/review/web/), no directory listing
      /api/health            {"ok": true, ...}
      /api/builds            every build, newest first (summary rows, with tags and a display name)
      /api/builds/<id>       one build with its steps, renders and jobs
      /api/builds/<id>/steps | /renders | /jobs
      /api/renders           every render of every build (the timeline's library)
      /api/tags              the tag registry (tags.json, merged with <media>/_tags.json): groups, colours, labels
      /api/metrics?window=10m|24h   machine metrics from monitor.py: 2 s samples (10 min, memory) or 1 min averages
                             (24 h, SQLite), plus the latest full sample
      /api/comfy             ComfyUI state from monitor.py: up, queue, current job's steps, last 10 jobs (+ linked build)
      /api/stream            Server-Sent Events: build, step, progress, render, job, done, fail, metrics, comfy
                             (metrics and comfy: at most one each per 2 s, not replayed) + heartbeat; at most
                             MAX_SSE streams at once (503 above), each closed after SSE_LIFETIME (EventSource reconnects)
      /media/<path>          files under the read-only media mount, HTTP Range (206/416), allowlisted types only
  ingest 8791 (write)
      POST /ingest/event     one JSON event (types above); unknown types and fields are refused (400); metrics and
                             comfy events carry no build. The Host header must be 127.0.0.1|localhost|[::1]:<port> and
                             every POST needs the header X-Film-Review: 1 (403 otherwise): a web page cannot send it
                             cross-origin without a CORS preflight, which this server never approves (DNS rebinding).
Public text: every stored string is scrubbed (an absolute path becomes its base name) and capped; old builds, steps,
renders, jobs and history rows are pruned (MAX_BUILDS, MAX_STEPS, ...). A slow client cannot hold a thread: socket
timeouts, a deadline for the request head, a bounded SSE lifetime.
The compose file publishes both ports on 127.0.0.1 only; ngrok tunnels 8790. This process is the only one that opens
the SQLite database (a named Docker volume): nothing else may share the .db file.
"""
import argparse
import base64
import collections
import email.utils
import hashlib
import json
import mimetypes
import os
import posixpath
import queue
import re
import socket
import sqlite3
import sys
import threading
import time
import unicodedata
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.2.0"
SCHEMA_VERSION = 2               # PRAGMA user_version; Store._migrate() brings an older database up to it
BUILD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
KINDS = ("model", "render", "clip", "demo", "image", "concept")     # image/concept: a gallery of generated images
TAG_GROUP = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
TAG_VALUE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
# Group names that are keys of every JavaScript object ({}.constructor ...): refused, the page keys objects by group.
RESERVED_GROUPS = frozenset({"constructor", "prototype", "__proto__", "tostring", "valueof", "hasownproperty",
                             "isprototypeof", "tolocalestring"})
MAX_TAG_GROUPS = 16
MAX_TAG_VALUES = 8               # per group
STATUSES = ("queued", "building", "rendering", "done", "failed")
JOB_TOOLS = ("blender", "comfy")
JOB_STATUSES = ("queued", "running", "done", "failed")
MAX_BODY = 256 * 1024
HEARTBEAT = 15.0
REPLAY = 500                     # events kept for SSE reconnects (Last-Event-ID)
CHUNK = 64 * 1024
METRICS_RING = 300               # 10 min of 2 s samples, in memory
MINUTE = 60.0                    # the 24 h history: one averaged row per minute in SQLite
KEEP_HISTORY = 24 * 3600.0
PUSH_EVERY = 2.0                 # SSE: at most one metrics and one comfy event per 2 s (the newest one wins)
MONITOR_STALE = 10.0             # no sample for this long: the monitor is shown as offline
MAX_SSE = 64                     # concurrent SSE streams; more answer 503
SSE_LIFETIME = 600.0             # an SSE stream ends after 10 min (the browser's EventSource reconnects at once)
SSE_SEND_TIMEOUT = 30.0          # a stalled SSE reader is dropped after this long
PUBLIC_TIMEOUT = 15.0            # socket timeout while a request is read (and of an idle keep-alive connection)
REQUEST_DEADLINE = 20.0          # the whole request head (line + headers) must arrive within this (slow loris)
SEND_TIMEOUT = 60.0              # one 64 KB chunk of a file must be taken by the client within this
MAX_BUILDS = 500                 # retention: the oldest builds (by updated) go, with their steps, renders and jobs
MAX_STEPS = 2000                 # per build: the lowest step numbers go
MAX_RENDERS = 500                # per build: the oldest go
MAX_JOBS = 200                   # per build: the oldest go
MAX_MINUTES = int(KEEP_HISTORY // MINUTE) + 60      # metrics_min rows, besides the 24 h age limit
INGEST_HEADER = "X-Film-Review"

MEDIA_TYPES = {
    ".glb": "model/gltf-binary", ".gltf": "model/gltf+json", ".bin": "application/octet-stream",
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".flac": "audio/flac",
    ".json": "application/json",
}
WEB_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml", ".png": "image/png", ".json": "application/json", ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}

# Event schema: type -> {field: (kind, required)}. "build" is implied for every type.
STR, NUM, INT, OBJ, PATH, BOOL, TAGS = "str", "num", "int", "obj", "path", "bool", "tags"
# Image metadata of a step (a ComfyUI/Seedream image): stored in steps.meta, shown by the gallery (web/gallery.js).
STEP_META = {"prompt": STR, "seed": INT, "model": STR, "sampler_steps": INT, "seconds": NUM, "width": INT,
             "height": INT, "workflow": STR, "item": INT, "items": INT, "chosen": BOOL}
JOB_DETAIL = {"label": STR, "step": INT, "steps": INT, "item": INT, "items": INT, "eta": NUM}
EVENTS = {
    "build": {"title": (STR, False), "kind": (STR, False), "project": (STR, False), "expected_steps": (INT, False),
              "status": (STR, False), "restart": (BOOL, False), "tags": (TAGS, False)},
    "step": dict({"label": (STR, True), "n": (INT, False), "glb": (PATH, False), "image": (PATH, False),
                  "stats": (OBJ, False)}, **{k: (t, False) for k, t in STEP_META.items()}),
    "progress": {"progress": (NUM, True), "message": (STR, False), "status": (STR, False)},
    "render": {"label": (STR, True), "video": (PATH, False), "image": (PATH, False), "frames": (INT, False),
               "fps": (NUM, False), "duration": (NUM, False), "engine": (STR, False),
               "seconds_per_frame": (NUM, False)},
    "job": dict({"job": (STR, False), "tool": (STR, True), "status": (STR, True), "progress": (NUM, False),
                 "gpu_s": (NUM, False), "message": (STR, False)}, **{k: (t, False) for k, t in JOB_DETAIL.items()}),
    "done": {"message": (STR, False)},
    "fail": {"message": (STR, False)},
}
MAX_STR = {"title": 200, "label": 200, "message": 500, "project": 100, "engine": 60, "job": 100, "kind": 20,
           "status": 20, "tool": 20, "prompt": 2000, "model": 120, "workflow": 60}
# Integer/number ranges of the optional fields (inclusive); the lower bound 0 also covers "must be >= 0".
RANGES = {"seed": (0, 2 ** 64 - 1), "sampler_steps": (1, 10000), "seconds": (0, 1e7), "width": (1, 65535),
          "height": (1, 65535), "item": (1, 100000), "items": (1, 100000), "step": (0, 10 ** 7),
          "steps": (1, 10 ** 7), "eta": (0, 1e8)}

# Anything that looks like an absolute path: UNC (\\server\share\...), a drive (C:\..., D:/...), POSIX (/home/x/...,
# ~/x/...). A segment before a separator may hold spaces ("C:\Program Files\..."), the last one may not. Stored and
# public text keeps the base name only. client.py has the same pattern (a test keeps the two equal).
PATHLIKE = re.compile(r"(?:\\\\|(?<![A-Za-z0-9])[A-Za-z]:[\\/]|(?<![\w.:/~-])~?/(?=[^\s/]))"
                      r"(?:[^\\/\"'<>|\r\n]*[\\/])*[^\s\\/\"'<>|]*")
CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def _basename(m):
    parts = [p.strip() for p in re.split(r"[\\/]", m.group(0)) if p.strip()]
    last = parts[-1] if parts else ""
    return "\u2026" if not last or re.fullmatch(r"[A-Za-z]:|~", last) else last


def scrub(text, limit=500):
    """Public text: every absolute path -> its base name ('…' when it has none), control characters -> one space,
    at most `limit` characters."""
    if not isinstance(text, str):
        return text
    return PATHLIKE.sub(_basename, CONTROL.sub(" ", text)).strip()[:limit]


def scrub_obj(v, depth=0):
    """scrub() every string (keys too) of a JSON value (the stats of a step)."""
    if isinstance(v, str):
        return scrub(v, 200)
    if isinstance(v, dict) and depth < 8:
        return {scrub(str(k), 60): scrub_obj(x, depth + 1) for k, x in v.items()}
    if isinstance(v, list) and depth < 8:
        return [scrub_obj(x, depth + 1) for x in v]
    return v

# kind is checked in validate() (KINDS), not by the table: a new kind never needs a table rebuild again.
BUILDS_TABLE = """
CREATE TABLE IF NOT EXISTS {name} (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  kind TEXT NOT NULL,
  project TEXT,
  status TEXT NOT NULL CHECK (status IN ('queued','building','rendering','done','failed')),
  progress REAL NOT NULL DEFAULT 0 CHECK (progress >= 0 AND progress <= 1),
  expected_steps INTEGER,
  current TEXT,
  message TEXT,
  thumb TEXT,
  started REAL NOT NULL,
  updated REAL NOT NULL,
  finished REAL,
  tags TEXT
);
"""
BUILD_COLS = ("id", "title", "kind", "project", "status", "progress", "expected_steps", "current", "message", "thumb",
              "started", "updated", "finished")
SCHEMA = BUILDS_TABLE.format(name="builds") + """
CREATE TABLE IF NOT EXISTS steps (
  id INTEGER PRIMARY KEY,
  build TEXT NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
  n INTEGER NOT NULL,
  label TEXT NOT NULL,
  stats TEXT,
  glb TEXT,
  image TEXT,
  t REAL NOT NULL,
  meta TEXT,
  UNIQUE (build, n)
);
CREATE TABLE IF NOT EXISTS renders (
  id INTEGER PRIMARY KEY,
  build TEXT NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  video TEXT,
  image TEXT,
  frames INTEGER,
  fps REAL,
  duration REAL,
  engine TEXT,
  seconds_per_frame REAL,
  t REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  build TEXT NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
  job TEXT NOT NULL,
  tool TEXT NOT NULL CHECK (tool IN ('blender','comfy')),
  status TEXT NOT NULL CHECK (status IN ('queued','running','done','failed')),
  progress REAL,
  gpu_s REAL,
  message TEXT,
  started REAL NOT NULL,
  t REAL NOT NULL,
  label TEXT,
  step INTEGER,
  steps INTEGER,
  item INTEGER,
  items INTEGER,
  eta REAL,
  UNIQUE (build, job)
);
CREATE TABLE IF NOT EXISTS metrics_min (
  t INTEGER PRIMARY KEY,
  data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS steps_build ON steps(build, n);
CREATE INDEX IF NOT EXISTS renders_build ON renders(build, t);
CREATE INDEX IF NOT EXISTS jobs_build ON jobs(build, t);
"""


class BadEvent(ValueError):
    """400: the event does not match the schema."""


# ------------------------------------------------------------------ validation
def safe_rel(path):
    """A media path relative to the media root ('build/file.glb') or None when it could leave the root."""
    if not isinstance(path, str) or not path or len(path) > 400 or "\x00" in path or "\\" in path:
        return None
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        return None
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return None
    return path


def validate(ev):
    """-> (type, build id, clean fields). Raises BadEvent."""
    if not isinstance(ev, dict):
        raise BadEvent("the body must be a JSON object")
    kind = ev.get("type")
    if kind not in EVENTS:
        raise BadEvent(f"unknown event type {kind!r} (one of {', '.join(EVENTS)})")
    bid = ev.get("build")
    if not isinstance(bid, str) or not BUILD_ID.match(bid):
        raise BadEvent("build must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}")
    schema = EVENTS[kind]
    extra = sorted(set(ev) - set(schema) - {"type", "build"})
    if extra:
        raise BadEvent(f"{kind}: unknown field(s) {', '.join(extra)}")
    out = {}
    for name, (ftype, required) in schema.items():
        v = ev.get(name)
        if v is None:
            if required:
                raise BadEvent(f"{kind}: {name} is required")
            continue
        if ftype == STR:
            if not isinstance(v, str):
                raise BadEvent(f"{kind}: {name} must be a string")
            v = scrub(v, MAX_STR.get(name, 200))
        elif ftype in (NUM, INT):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
                raise BadEvent(f"{kind}: {name} must be a number")
            if ftype == INT:
                if int(v) != v:
                    raise BadEvent(f"{kind}: {name} must be an integer")
                v = int(v)
        elif ftype == BOOL:
            if not isinstance(v, bool):
                raise BadEvent(f"{kind}: {name} must be true or false")
        elif ftype == OBJ:
            if not isinstance(v, dict):
                raise BadEvent(f"{kind}: {name} must be an object")
            if len(json.dumps(v)) > 8192:
                raise BadEvent(f"{kind}: {name} is too large (8 KB)")
            v = scrub_obj(v)
        elif ftype == PATH:
            if safe_rel(v) is None or not v.startswith(bid + "/"):
                raise BadEvent(f"{kind}: {name} must be a media path under '{bid}/' (no '..', no absolute path)")
        elif ftype == TAGS:
            v = clean_tags(v, f"{kind}: {name}")
        if name in RANGES and not RANGES[name][0] <= v <= RANGES[name][1]:
            lo, hi = RANGES[name]
            raise BadEvent(f"{kind}: {name} must be {lo:g}..{hi:g}")
        out[name] = v
    if kind == "build":
        if "kind" in out and out["kind"] not in KINDS:
            raise BadEvent(f"build: kind must be one of {', '.join(KINDS)}")
        if "status" in out and out["status"] not in STATUSES:
            raise BadEvent(f"build: status must be one of {', '.join(STATUSES)}")
        if "expected_steps" in out and not 0 < out["expected_steps"] <= 100000:
            raise BadEvent("build: expected_steps must be 1..100000")
    if kind == "progress":
        if not 0 <= out["progress"] <= 1:
            raise BadEvent("progress: progress must be 0..1")
        if "status" in out and out["status"] not in ("queued", "building", "rendering"):
            raise BadEvent("progress: status must be queued, building or rendering")
    if kind == "step" and "n" in out and not 0 < out["n"] <= 100000:
        raise BadEvent("step: n must be 1..100000")
    if kind == "render" and not (out.get("video") or out.get("image")):
        raise BadEvent("render: video or image is required")
    if kind == "job":
        if out["tool"] not in JOB_TOOLS:
            raise BadEvent(f"job: tool must be one of {', '.join(JOB_TOOLS)}")
        if out["status"] not in JOB_STATUSES:
            raise BadEvent(f"job: status must be one of {', '.join(JOB_STATUSES)}")
        if "progress" in out and not 0 <= out["progress"] <= 1:
            raise BadEvent("job: progress must be 0..1")
        if "step" in out and "steps" in out and out["step"] > out["steps"]:
            raise BadEvent("job: step must be <= steps")
    if "item" in out and "items" in out and out["item"] > out["items"]:
        raise BadEvent(f"{kind}: item must be <= items")
    for name in ("fps", "duration", "seconds_per_frame", "gpu_s", "frames"):
        if name in out and out[name] < 0:
            raise BadEvent(f"{kind}: {name} must be >= 0")
    return kind, bid, out


def clean_tags(v, where="tags"):
    """{group: value | [values]} -> {group: [values]} (deduplicated, order kept). Group and value must be slugs (the
    client normalises them first): nothing but [a-z0-9._-] ever reaches the public page. An empty list removes the
    group when it is merged into a build's tags. Raises BadEvent."""
    if not isinstance(v, dict):
        raise BadEvent(f"{where} must be an object {{group: value or [values]}}")
    if len(v) > MAX_TAG_GROUPS:
        raise BadEvent(f"{where}: at most {MAX_TAG_GROUPS} groups")
    out = {}
    for group, vals in v.items():
        if not isinstance(group, str) or not TAG_GROUP.match(group) or group in RESERVED_GROUPS:
            raise BadEvent(f"{where}: group {str(group)[:30]!r} must match {TAG_GROUP.pattern} "
                           f"(and not be {', '.join(sorted(RESERVED_GROUPS))})")
        if isinstance(vals, str):
            vals = [vals]
        if not isinstance(vals, list) or len(vals) > MAX_TAG_VALUES:
            raise BadEvent(f"{where}.{group}: a value or a list of at most {MAX_TAG_VALUES}")
        clean = []
        for x in vals:
            if not isinstance(x, str) or not TAG_VALUE.match(x):
                raise BadEvent(f"{where}.{group}: value {str(x)[:30]!r} must match {TAG_VALUE.pattern}")
            if x not in clean:
                clean.append(x)
        out[group] = clean
    return out


def public_meta(meta):
    """Step metadata for the API: `seed` is also given as the string `seed_str` (exact: a browser parses JSON numbers
    as doubles, which round a seed above 2**53)."""
    meta = dict(meta or {})
    if isinstance(meta.get("seed"), int) and not isinstance(meta["seed"], bool):
        meta["seed_str"] = str(meta["seed"])
    return meta


def merge_tags(stored, given):
    """The build's tags after an event: each given group replaces the stored one; an empty list removes it."""
    out = {g: list(v) for g, v in (stored or {}).items()}
    for g, vals in (given or {}).items():
        if vals:
            out[g] = list(vals)
        else:
            out.pop(g, None)
    return dict(list(out.items())[:MAX_TAG_GROUPS])


# ------------------------------------------------------------------ tag registry and inference (old builds)
def fold(text):
    """Lower case ASCII: 'Phượng hoàng Đỏ' -> 'phuong hoang do' (accents and đ folded)."""
    text = str(text or "").replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def slugify(text, most=48):
    s = re.sub(r"[^a-z0-9._-]+", "-", fold(text)).strip("-._")[:most].strip("-._")
    return s if s and TAG_VALUE.match(s) else None


class Registry:
    """tags.json (shipped with the server) merged with the optional <media>/_tags.json (project labels, e.g. the subjects
    of a series, kept out of the repo); re-read when either file changes. Never raises: a broken file counts as empty.
    Labels are public text: scrubbed like every other string."""

    def __init__(self, path, overlay=None):
        self.paths = [p for p in (path, overlay) if p]
        self.sig = None
        self.data = {"version": 1, "groups": {}}
        self.lock = threading.Lock()

    def get(self):
        sig = []
        for p in self.paths:
            try:
                st = os.stat(p)
                sig.append((p, st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append((p, None, None))
        with self.lock:
            if sig != self.sig:
                self.sig = sig
                self.data = {"version": 1, "groups": read_registry([p for p, m, _ in sig if m is not None])}
            return self.data


def read_registry(paths):
    """Groups of the registry files, later files merged over earlier ones (values added or relabelled)."""
    groups = {}
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("groups"), dict):
            continue
        for name, g in doc["groups"].items():
            if not isinstance(g, dict) or not TAG_GROUP.match(str(name)) or name in RESERVED_GROUPS:
                continue
            cur = groups.setdefault(name, {"label": name, "color": "#8d9ab2", "values": {}})
            if isinstance(g.get("values"), dict):
                cur["values"].update({str(a): scrub(str(b), 60) for a, b in g["values"].items()
                                      if TAG_VALUE.match(str(a))})
            for k in ("label", "color"):
                if isinstance(g.get(k), str):
                    cur[k] = scrub(g[k], 60)
            if isinstance(g.get("open"), bool):
                cur["open"] = g["open"]
            if isinstance(g.get("pattern"), str):
                cur["pattern"] = g["pattern"][:200]
            if isinstance(g.get("labels_re"), list):
                cur["labels_re"] = [[str(x[0])[:200], scrub(str(x[1]), 60)] for x in g["labels_re"]
                                    if isinstance(x, list) and len(x) == 2][:10]
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", cur["color"]):
                cur["color"] = "#8d9ab2"
    return groups


ENGINE_RULES = ((r"blender", "blender"), (r"qwen", "comfy-qwen"), (r"(?<![a-z0-9])h3(?![a-z0-9])|minimax", "comfy-h3"),
                (r"seedance", "seedance"), (r"seedream", "seedream"), (r"(?<![a-z-])toon(?![a-z-])", "toon"),
                (r"three\.?js", "three"), (r"(?<![a-z])tts(?![a-z])|vieneu", "tts"))
LOOK_RULES = ((r"realistic|ta thuc|chan thuc|chan-thuc", "realistic"), (r"ink[- ]?wash|thuy[- ]mac", "ink-wash"),
              (r"toon[- ]ink", "toon-ink"), (r"(?<![a-z])clay(?![a-z])|dat set", "clay"),
              (r"gr[ae]y[- ]?layout|layout xam", "grey-layout"))
STAGE_RULES = ((r"lookdev", "lookdev"), (r"(?<![a-z0-9])g2(?![0-9])", "g2"), (r"(?<![a-z0-9])g3(?![0-9])", "g3"),
               (r"(?<![a-z])final(?![a-z])|ban cuoi", "final"))
KIND_RULES = ((r"(?<![a-z])concept(?![a-z])", "concept"), (r"turntable|(?<![a-z0-9])tt(?![a-z0-9])", "turntable"))
EPISODE = re.compile(r"(?<![a-z0-9])q\s*0*(\d{1,2})\s*[·.\-_ ]?\s*t\s*0*(\d{1,2})(?![0-9])"
                     r"|(?<![a-z0-9])ep\s*0*(\d{1,3})(?![0-9])")
SHOT = re.compile(r"(?<![a-z0-9])s(\d{2,3})(?![0-9])")


def infer_tags(bid, title, kind, project, registry=None):
    """Tags of a build that was published without any (old builds, old callers), guessed from its id, title, kind and
    project: kind, engine, look, stage, episode, shot, project and the registry's subjects. Only what is recognised."""
    text = fold(f"{bid} {title or ''}").replace("_", " ")
    tags = {}
    k = kind if kind in KINDS else None
    for pat, val in KIND_RULES:
        if re.search(pat, text):
            k = val
            break
    if k:
        tags["kind"] = [k]
    for group, rules in (("engine", ENGINE_RULES), ("look", LOOK_RULES), ("stage", STAGE_RULES)):
        vals = list(dict.fromkeys(v for pat, v in rules if re.search(pat, text)))
        if group == "look" and "grey-layout" in vals:
            vals = ["grey-layout"]
        if vals:
            tags[group] = vals[:MAX_TAG_VALUES]
    m = EPISODE.search(text)
    if m:
        tags["episode"] = [f"q{int(m.group(1)):02d}t{int(m.group(2)):02d}" if m.group(1) else f"ep{int(m.group(3)):02d}"]
    shots = list(dict.fromkeys(f"s{int(x):02d}" for x in SHOT.findall(text)))
    if shots:
        tags["shot"] = shots[:MAX_TAG_VALUES]
    if project and slugify(project):
        tags["project"] = [slugify(project)]
    groups = (registry.get() if registry else {}).get("groups") or {}
    subs = []
    for slug, label in ((groups.get("subject") or {}).get("values") or {}).items():
        words = [slug.replace("-", " ").replace("_", " ")] + ([fold(label)] if label else [])
        if any(w and re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", text.replace("-", " "))
               for w in words):
            subs.append(slug)
    if subs:
        tags["subject"] = subs[:MAX_TAG_VALUES]
    return tags


def _tag_like(part):
    p = fold(part).strip()
    if not p or len(p.split()) > 3:
        return False
    if EPISODE.fullmatch(p) or SHOT.fullmatch(p) or p in ("image", "render", "model", "clip"):
        return True
    return any(re.search(pat, p) for pat, _ in ENGINE_RULES + LOOK_RULES + STAGE_RULES + KIND_RULES)


def display_name(title):
    """The title without the annotations that are chips now: '(Blender, realistic)', '(Qwen-Image)', ' · Q1·T3'.
    An annotation goes only when every part of it is recognised; never empty."""
    t = str(title or "")
    t2 = re.sub(r"\s*\(([^()]{1,80})\)",
                lambda m: "" if all(_tag_like(x) for x in m.group(1).split(",")) else m.group(0), t)
    parts = re.split(r"\s+·\s+", t2)
    if len(parts) > 1:
        parts = [parts[0]] + [p for p in parts[1:] if not _tag_like(p)]
    out = " · ".join(parts).strip(" ·-")
    return out or t


# --- machine metrics and ComfyUI state (monitor.py). The public page shows them: names are tightly limited so a path,
# a command line or a user name can never get through, whatever the sender puts in.
SYS_EVENTS = ("metrics", "comfy")
# Job labels: exactly the labels of monitor.py's allow list (HEAVY + "ComfyUI (python)"; a test keeps both equal).
PROC_LABELS = frozenset({"blender", "ComfyUI Desktop", "ComfyUI (python)", "ffmpeg", "DaVinci Resolve", "Unreal Editor",
                         "Houdini", "Maya", "ollama", "llama.cpp"})
DISK_NAME = re.compile(r"^(?:[A-Z]:|/)$")
GPU_NAME = re.compile(r"^[A-Za-z0-9 ._()+-]{1,60}$")
PROMPT_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
GPU_OWNER = re.compile(r"^[A-Za-z0-9 _.:/-]{1,60}$")     # monitor.py's gpu_owner_label() gives exactly this
BIG = 1e16
GPU_FIELDS = {"util": (0, 100), "mem_used": (0, BIG), "mem_total": (0, BIG), "temp": (-50, 200), "power": (0, 5000)}
CURRENT_FIELDS = {"step": (0, 1e7), "total": (1, 1e7), "pct": (0, 100), "s_per_step": (0, 1e7), "elapsed": (0, 1e8),
                  "eta": (0, 1e8), "bar": (1, 1e4), "job_elapsed": (0, 1e8)}
HISTORY_FIELDS = {"t": (0, 1e11), "duration": (0, 1e8), "steps": (0, 1e7), "s_per_step": (0, 1e7), "bars": (0, 1e4)}
HISTORY_STATUS = ("ok", "failed", "interrupted")


def _sys_num(where, v, lo, hi, integer=False):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        raise BadEvent(f"{where} must be a number")
    if not lo <= v <= hi:
        raise BadEvent(f"{where} must be {lo:g}..{hi:g}")
    if integer:
        if int(v) != v:
            raise BadEvent(f"{where} must be an integer")
        return int(v)
    return round(float(v), 3)


def _sys_keys(where, obj, allowed):
    if not isinstance(obj, dict):
        raise BadEvent(f"{where} must be an object")
    extra = sorted(set(obj) - set(allowed))
    if extra:
        raise BadEvent(f"{where}: unknown field(s) {', '.join(map(str, extra))}")


def _sys_list(where, v, most):
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > most:
        raise BadEvent(f"{where} must be a list of at most {most}")
    return v


def validate_sys(ev):
    """A metrics or comfy event of monitor.py -> (type, clean dict). Raises BadEvent."""
    kind = ev.get("type")
    if kind == "metrics":
        _sys_keys("metrics", ev, ("type", "t", "cpu", "ram_used", "ram_total", "gpus", "disks", "procs", "gpu_owner"))
        out = {"cpu": _sys_num("metrics: cpu", ev.get("cpu"), 0, 100),
               "ram_used": _sys_num("metrics: ram_used", ev.get("ram_used"), 0, BIG, True),
               "ram_total": _sys_num("metrics: ram_total", ev.get("ram_total"), 0, BIG, True),
               "gpus": [], "disks": [], "procs": [], "gpu_owner": None}
        owner = ev.get("gpu_owner")
        if owner is not None:           # who holds the GPU lock (tools/gpu_run.py): a free-text label, tightly limited
            _sys_keys("metrics: gpu_owner", owner, ("label", "since"))
            label = owner.get("label")
            if not isinstance(label, str) or not GPU_OWNER.fullmatch(label):
                raise BadEvent(f"metrics: gpu_owner.label must match {GPU_OWNER.pattern}")
            out["gpu_owner"] = {"label": scrub(label, 60),
                                "since": _sys_num("metrics: gpu_owner.since", owner.get("since"), 0, 1e11)}
        for i, g in enumerate(_sys_list("metrics: gpus", ev.get("gpus"), 8)):
            _sys_keys(f"metrics: gpus[{i}]", g, ("name",) + tuple(GPU_FIELDS))
            name = g.get("name")
            if name is not None and (not isinstance(name, str) or not GPU_NAME.fullmatch(name)):
                raise BadEvent(f"metrics: gpus[{i}].name must match {GPU_NAME.pattern}")
            d = {"name": name}
            for f, (lo, hi) in GPU_FIELDS.items():
                d[f] = _sys_num(f"metrics: gpus[{i}].{f}", g.get(f), lo, hi, f.startswith("mem_"))
            out["gpus"].append(d)
        for i, d in enumerate(_sys_list("metrics: disks", ev.get("disks"), 26)):
            _sys_keys(f"metrics: disks[{i}]", d, ("name", "free", "total"))
            if not isinstance(d.get("name"), str) or not DISK_NAME.fullmatch(d["name"]):
                raise BadEvent(f"metrics: disks[{i}].name must be a drive letter like C: (or /)")
            out["disks"].append({"name": d["name"],
                                 "free": _sys_num(f"metrics: disks[{i}].free", d.get("free"), 0, BIG, True),
                                 "total": _sys_num(f"metrics: disks[{i}].total", d.get("total"), 0, BIG, True)})
        for i, p in enumerate(_sys_list("metrics: procs", ev.get("procs"), 20)):
            _sys_keys(f"metrics: procs[{i}]", p, ("name", "count"))
            if not isinstance(p.get("name"), str) or p["name"] not in PROC_LABELS:
                raise BadEvent(f"metrics: procs[{i}].name must be one of the allow-listed job labels")
            cnt = _sys_num(f"metrics: procs[{i}].count", p.get("count"), 1, 9999, True)
            out["procs"].append({"name": p["name"], "count": cnt or 1})
        return kind, out
    if kind == "comfy":
        _sys_keys("comfy", ev, ("type", "t", "up", "running", "pending", "prompt_id", "log", "current", "history"))
        if not isinstance(ev.get("up"), bool):
            raise BadEvent("comfy: up (true/false) is required")
        if ev.get("log") is not None and not isinstance(ev["log"], bool):
            raise BadEvent("comfy: log must be true or false")
        out = {"up": ev["up"], "log": bool(ev.get("log")),
               "running": _sys_num("comfy: running", ev.get("running"), 0, 100000, True),
               "pending": _sys_num("comfy: pending", ev.get("pending"), 0, 100000, True),
               "prompt_id": _prompt_id("comfy: prompt_id", ev.get("prompt_id")), "current": None, "history": []}
        cur = ev.get("current")
        if cur is not None:
            _sys_keys("comfy: current", cur, CURRENT_FIELDS)
            out["current"] = {f: _sys_num(f"comfy: current.{f}", cur.get(f), lo, hi, f in ("step", "total", "bar"))
                              for f, (lo, hi) in CURRENT_FIELDS.items()}
            if out["current"]["step"] is None or out["current"]["total"] is None:
                raise BadEvent("comfy: current needs step and total")
        for i, h in enumerate(_sys_list("comfy: history", ev.get("history"), 10)):
            _sys_keys(f"comfy: history[{i}]", h, tuple(HISTORY_FIELDS) + ("status", "prompt_id"))
            d = {f: _sys_num(f"comfy: history[{i}].{f}", h.get(f), lo, hi, f in ("steps", "bars"))
                 for f, (lo, hi) in HISTORY_FIELDS.items()}
            st = h.get("status") or "ok"
            if st not in HISTORY_STATUS:
                raise BadEvent(f"comfy: history[{i}].status must be one of {', '.join(HISTORY_STATUS)}")
            d["status"] = st
            d["prompt_id"] = _prompt_id(f"comfy: history[{i}].prompt_id", h.get("prompt_id"))
            out["history"].append(d)
        return kind, out
    raise BadEvent(f"unknown event type {kind!r}")


def _prompt_id(where, v):
    if v is None:
        return None
    if not isinstance(v, str) or not PROMPT_ID.fullmatch(v):
        raise BadEvent(f"{where} must match {PROMPT_ID.pattern}")
    return v


def flat_sample(s):
    """A full metrics sample -> the chart row {t, cpu, ram_used, ram_total, gpu_util, vram_used, vram_total, gpu_temp,
    gpu_power} (the first GPU)."""
    g = (s.get("gpus") or [{}])[0]
    return {"t": s["t"], "cpu": s.get("cpu"), "ram_used": s.get("ram_used"), "ram_total": s.get("ram_total"),
            "gpu_util": g.get("util"), "vram_used": g.get("mem_used"), "vram_total": g.get("mem_total"),
            "gpu_temp": g.get("temp"), "gpu_power": g.get("power")}


FLAT_FIELDS = ("cpu", "ram_used", "ram_total", "gpu_util", "vram_used", "vram_total", "gpu_temp", "gpu_power")


def downsample(rows, bucket=MINUTE):
    """Chart rows -> one row per bucket (t = bucket start): the mean of every field (None ignored), the peak GPU
    temperature and VRAM, the sample count, and the disks of the bucket's last sample."""
    groups = {}
    for r in rows:
        groups.setdefault(int(r["t"] // bucket * bucket), []).append(r)
    out = []
    for t in sorted(groups):
        g = groups[t]
        row = {"t": t, "n": len(g)}
        for f in FLAT_FIELDS:
            vals = [r[f] for r in g if r.get(f) is not None]
            row[f] = round(sum(vals) / len(vals), 2) if vals else None
        temps = [r["gpu_temp"] for r in g if r.get("gpu_temp") is not None]
        vram = [r["vram_used"] for r in g if r.get("vram_used") is not None]
        row["gpu_temp_max"] = max(temps) if temps else None
        row["vram_max"] = max(vram) if vram else None
        disks = [r["disks"] for r in g if r.get("disks")]
        row["disks"] = disks[-1] if disks else []
        out.append(row)
    return out


# ------------------------------------------------------------------ storage
def load_tags(text):
    try:
        d = json.loads(text) if text else {}
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def effective_tags(b):
    """The tags of a build row for the API: the stored tags, plus kind and project from their columns when the tags do
    not name them (every card gets a kind chip)."""
    tags = load_tags(b.get("tags"))
    if not tags.get("kind") and b.get("kind"):
        tags = dict({"kind": [b["kind"]]}, **tags)
    if not tags.get("project") and b.get("project") and slugify(b["project"]):
        tags["project"] = [slugify(b["project"])]
    return tags


class Store:
    """The SQLite database (one connection, one lock: this process is its only user)."""

    def __init__(self, path, registry=None):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.registry = registry
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA busy_timeout=5000")
            self.db.executescript(SCHEMA)
            self._migrate()
            self.db.execute("PRAGMA foreign_keys=ON")

    def _migrate(self):
        """Bring a database of an older server up to SCHEMA_VERSION (idempotent, one transaction).
        v2: builds loses the CHECK on kind (new kinds image/concept) and gains tags, back-filled by infer_tags() from
        the id, title, kind and project; steps gains meta; jobs gains label/step/steps/item/items/eta.
        Foreign keys are off while builds is rebuilt (its steps, renders and jobs must not cascade away)."""
        db = self.db
        if db.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
            return

        def cols(table):
            return {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("BEGIN IMMEDIATE")
        try:
            sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='builds'").fetchone()[0]
            if "kind IN" in sql or "tags" not in cols("builds"):
                keep = ", ".join(c for c in BUILD_COLS if c in cols("builds"))
                db.execute("DROP TABLE IF EXISTS builds_v2")
                db.execute(BUILDS_TABLE.format(name="builds_v2"))
                db.execute(f"INSERT INTO builds_v2 ({keep}) SELECT {keep} FROM builds")
                db.execute("DROP TABLE builds")
                db.execute("ALTER TABLE builds_v2 RENAME TO builds")
            if "meta" not in cols("steps"):
                db.execute("ALTER TABLE steps ADD COLUMN meta TEXT")
            have = cols("jobs")
            for col, typ in (("label", "TEXT"), ("step", "INTEGER"), ("steps", "INTEGER"), ("item", "INTEGER"),
                             ("items", "INTEGER"), ("eta", "REAL")):
                if col not in have:
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}")
            for r in db.execute("SELECT id, title, kind, project FROM builds WHERE tags IS NULL").fetchall():
                tags = infer_tags(r["id"], r["title"], r["kind"], r["project"], self.registry)
                db.execute("UPDATE builds SET tags=? WHERE id=?", (json.dumps(tags), r["id"]))
            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise

    def close(self):
        with self.lock:
            self.db.close()

    # --- reads
    def _summary(self, row):
        b = dict(row)
        bid = b["id"]
        b["tags"] = effective_tags(b)
        b["name"] = display_name(b["title"])
        b["steps"] = self.db.execute("SELECT COUNT(*) FROM steps WHERE build=?", (bid,)).fetchone()[0]
        b["images"] = self.db.execute("SELECT COUNT(*) FROM steps WHERE build=? AND image IS NOT NULL",
                                      (bid,)).fetchone()[0]
        b["renders"] = self.db.execute("SELECT COUNT(*) FROM renders WHERE build=?", (bid,)).fetchone()[0]
        last = self.db.execute("SELECT glb FROM steps WHERE build=? AND glb IS NOT NULL ORDER BY n DESC LIMIT 1",
                               (bid,)).fetchone()
        b["last_glb"] = last[0] if last else None
        job = self.db.execute("SELECT * FROM jobs WHERE build=? ORDER BY t DESC LIMIT 1", (bid,)).fetchone()
        b["job"] = dict(job) if job else None
        return b

    def builds(self):
        with self.lock:
            rows = self.db.execute("SELECT * FROM builds ORDER BY updated DESC, rowid DESC").fetchall()
            return [self._summary(r) for r in rows]

    def build(self, bid):
        with self.lock:
            row = self.db.execute("SELECT * FROM builds WHERE id=?", (bid,)).fetchone()
            return self._summary(row) if row else None

    def rows(self, table, bid=None):
        order = {"steps": "n", "renders": "t, id", "jobs": "t, id"}[table]
        with self.lock:
            if bid is None:
                rows = self.db.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
            else:
                rows = self.db.execute(f"SELECT * FROM {table} WHERE build=? ORDER BY {order}", (bid,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for col in ("stats", "meta"):
                if col in d:
                    try:
                        d[col] = json.loads(d[col]) if d[col] else {}
                    except ValueError:
                        d[col] = {}
            if isinstance(d.get("meta"), dict):
                d["meta"] = public_meta(d["meta"])
            out.append(d)
        return out

    # --- writes
    def _ensure(self, bid, now, kind="model"):
        row = self.db.execute("SELECT id FROM builds WHERE id=?", (bid,)).fetchone()
        if not row:
            tags = json.dumps(infer_tags(bid, bid, kind, None, self.registry))
            self.db.execute("INSERT INTO builds (id, title, kind, status, progress, started, updated, tags) "
                            "VALUES (?, ?, ?, 'building', 0, ?, ?, ?)", (bid, bid, kind, now, now, tags))
            self._prune_builds(bid)

    def _prune_builds(self, keep):
        """Retention: at most MAX_BUILDS builds; the least recently updated go (their rows cascade). Never `keep`."""
        self.db.execute("DELETE FROM builds WHERE id IN (SELECT id FROM builds WHERE id != ? ORDER BY updated DESC, "
                        "rowid DESC LIMIT -1 OFFSET ?)", (keep, max(0, MAX_BUILDS - 1)))

    def _prune_rows(self, table, bid, newest_first, most):
        """Retention: at most `most` rows of one build in steps/renders/jobs (the rest of `newest_first` go)."""
        self.db.execute(f"DELETE FROM {table} WHERE id IN (SELECT id FROM {table} WHERE build=? "
                        f"ORDER BY {newest_first} LIMIT -1 OFFSET ?)", (bid, most))

    def apply(self, kind, bid, f, now=None):
        """Store one validated event. -> the stored row (dict) for the SSE payload."""
        now = time.time() if now is None else now
        with self.lock:
            db = self.db
            db.execute("BEGIN IMMEDIATE")
            try:
                data = self._apply(db, kind, bid, f, now)
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
            return data

    def _apply(self, db, kind, bid, f, now):
        if kind == "build":
            row = db.execute("SELECT * FROM builds WHERE id=?", (bid,)).fetchone()
            if row is None:
                title, kind = f.get("title") or bid, f.get("kind") or "model"
                if "tags" in f:
                    tags = merge_tags({}, f["tags"])
                else:               # an old caller: guess them (kind, engine, look, episode... from id and title)
                    tags = infer_tags(bid, title, kind, f.get("project"), self.registry)
                db.execute("INSERT INTO builds (id, title, kind, project, status, progress, expected_steps, started, "
                           "updated, tags) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
                           (bid, title, kind, f.get("project"), f.get("status") or "building",
                            f.get("expected_steps"), now, now, json.dumps(tags)))
                self._prune_builds(bid)
            else:
                sets, vals = ["updated=?"], [now]
                for col in ("title", "kind", "project", "expected_steps", "status"):
                    if col in f:
                        sets.append(f"{col}=?")
                        vals.append(f[col])
                if "tags" in f:
                    sets.append("tags=?")
                    vals.append(json.dumps(merge_tags(load_tags(row["tags"]), f["tags"])))
                if f.get("status") in ("queued", "building", "rendering"):
                    sets.append("finished=NULL")
                if f.get("restart"):            # a new run of the same build: its old steps and jobs go
                    db.execute("DELETE FROM steps WHERE build=?", (bid,))
                    db.execute("DELETE FROM jobs WHERE build=?", (bid,))
                    sets += ["started=?", "progress=0", "current=NULL", "message=NULL", "thumb=NULL", "finished=NULL"]
                    vals.append(now)
                    if "status" not in f:
                        sets.append("status='building'")
                db.execute(f"UPDATE builds SET {', '.join(sets)} WHERE id=?", vals + [bid])
            return dict(f)
        self._ensure(bid, now, "render" if kind in ("render", "job") else "model")
        if kind == "step":
            n = f.get("n")
            if n is None:
                n = db.execute("SELECT COALESCE(MAX(n), 0) + 1 FROM steps WHERE build=?", (bid,)).fetchone()[0]
            stats = json.dumps(f.get("stats") or {}, ensure_ascii=False)
            meta = {k: f[k] for k in STEP_META if k in f}
            db.execute("INSERT INTO steps (build, n, label, stats, glb, image, t, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                       "ON CONFLICT(build, n) DO UPDATE SET label=excluded.label, stats=excluded.stats, "
                       "glb=excluded.glb, image=excluded.image, t=excluded.t, meta=excluded.meta",
                       (bid, n, f["label"], stats, f.get("glb"), f.get("image"), now,
                        json.dumps(meta, ensure_ascii=False) if meta else None))
            self._prune_rows("steps", bid, "n DESC", MAX_STEPS)
            exp = db.execute("SELECT expected_steps FROM builds WHERE id=?", (bid,)).fetchone()[0]
            prog = min(1.0, n / exp) if exp else None
            sets = ["current=?", "updated=?", "status=CASE WHEN status IN ('queued','done','failed') "
                                              "THEN 'building' ELSE status END", "finished=NULL"]
            vals = [f["label"], now]
            if prog is not None:
                sets.append("progress=?")
                vals.append(prog)
            if f.get("image"):
                sets.append("thumb=?")
                vals.append(f["image"])
            db.execute(f"UPDATE builds SET {', '.join(sets)} WHERE id=?", vals + [bid])
            return {"build": bid, "n": n, "label": f["label"], "stats": f.get("stats") or {}, "glb": f.get("glb"),
                    "image": f.get("image"), "t": now, "meta": public_meta(meta)}
        if kind == "progress":
            sets, vals = ["progress=?", "updated=?"], [f["progress"], now]
            if "message" in f:
                sets.append("current=?")
                vals.append(f["message"])
            if "status" in f:
                sets += ["status=?", "finished=NULL"]
                vals.append(f["status"])
            db.execute(f"UPDATE builds SET {', '.join(sets)} WHERE id=?", vals + [bid])
            return dict(f, t=now)
        if kind == "render":
            cols = ("label", "video", "image", "frames", "fps", "duration", "engine", "seconds_per_frame")
            same = db.execute("SELECT id FROM renders WHERE build=? AND video IS ? AND image IS ?",
                              (bid, f.get("video"), f.get("image"))).fetchone()
            if same:            # the same file published again: one row, newest metadata
                db.execute(f"UPDATE renders SET {', '.join(c + '=?' for c in cols)}, t=? WHERE id=?",
                           [f.get(c) for c in cols] + [now, same[0]])
                rid = same[0]
            else:
                rid = db.execute(f"INSERT INTO renders (build, {', '.join(cols)}, t) "
                                 f"VALUES (?, {', '.join('?' * len(cols))}, ?)",
                                 [bid] + [f.get(c) for c in cols] + [now]).lastrowid
                self._prune_rows("renders", bid, "t DESC, id DESC", MAX_RENDERS)
            sets, vals = ["updated=?"], [now]
            if f.get("image"):
                sets.append("thumb=COALESCE(thumb, ?)")
                vals.append(f["image"])
            db.execute(f"UPDATE builds SET {', '.join(sets)} WHERE id=?", vals + [bid])
            return dict({c: f.get(c) for c in cols}, id=rid, build=bid, t=now)
        if kind == "job":
            key = f.get("job") or f["tool"]
            detail = tuple(JOB_DETAIL)
            db.execute(f"INSERT INTO jobs (build, job, tool, status, progress, gpu_s, message, started, t, "
                       f"{', '.join(detail)}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, {', '.join('?' * len(detail))}) "
                       "ON CONFLICT(build, job) DO UPDATE SET "
                       "tool=excluded.tool, status=excluded.status, progress=COALESCE(excluded.progress, progress), "
                       "gpu_s=COALESCE(excluded.gpu_s, gpu_s), message=COALESCE(excluded.message, message), "
                       "t=excluded.t, " + ", ".join(f"{c}=COALESCE(excluded.{c}, {c})" for c in detail),
                       (bid, key, f["tool"], f["status"], f.get("progress"), f.get("gpu_s"), f.get("message"),
                        now, now) + tuple(f.get(c) for c in detail))
            self._prune_rows("jobs", bid, "t DESC, id DESC", MAX_JOBS)
            sets, vals = ["updated=?"], [now]
            if f["status"] == "running":
                sets += ["status=CASE WHEN status='building' THEN status ELSE 'rendering' END", "finished=NULL"]
                if f.get("progress") is not None:
                    sets.append("progress=?")
                    vals.append(f["progress"])
                if f.get("message"):
                    sets.append("current=?")
                    vals.append(f["message"])
            db.execute(f"UPDATE builds SET {', '.join(sets)} WHERE id=?", vals + [bid])
            row = db.execute("SELECT * FROM jobs WHERE build=? AND job=?", (bid, key)).fetchone()
            return dict(row)
        if kind == "done":
            db.execute("UPDATE builds SET status='done', progress=1, finished=?, updated=?, "
                       "message=COALESCE(?, message) WHERE id=?", (now, now, f.get("message"), bid))
            return dict(f, t=now)
        if kind == "fail":
            db.execute("UPDATE builds SET status='failed', finished=?, updated=?, message=? WHERE id=?",
                       (now, now, f.get("message") or "failed", bid))
            return dict(f, t=now)
        raise BadEvent(kind)

    # --- machine metrics history (1-min rows) and ComfyUI links
    def save_minutes(self, rows, prune_before):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                for r in rows:
                    self.db.execute("INSERT OR REPLACE INTO metrics_min (t, data) VALUES (?, ?)",
                                    (int(r["t"]), json.dumps(r, separators=(",", ":"))))
                self.db.execute("DELETE FROM metrics_min WHERE t < ?", (int(prune_before),))
                self.db.execute("DELETE FROM metrics_min WHERE t IN (SELECT t FROM metrics_min ORDER BY t DESC "
                                "LIMIT -1 OFFSET ?)", (MAX_MINUTES,))
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def minutes(self, since):
        with self.lock:
            rows = self.db.execute("SELECT data FROM metrics_min WHERE t >= ? ORDER BY t", (int(since),)).fetchall()
        out = []
        for (data,) in rows:
            try:
                out.append(json.loads(data))
            except ValueError:
                pass
        return out

    def comfy_build(self, prompt_id):
        """The build whose comfy.py job ran this prompt (comfy.py --review names the job comfy-<prompt id>), with the
        job's workflow label and batch position (image k/N) when comfy.py sent them."""
        with self.lock:
            row = self.db.execute("SELECT j.build, b.title, b.kind, j.label, j.item, j.items, j.step, j.steps "
                                  "FROM jobs j JOIN builds b ON b.id = j.build "
                                  "WHERE j.tool = 'comfy' AND j.job = ? ORDER BY j.t DESC LIMIT 1",
                                  ("comfy-" + prompt_id,)).fetchone()
        if not row:
            return None
        return {"id": row[0], "title": display_name(row[1]), "kind": row[2], "workflow": row[3], "item": row[4],
                "items": row[5], "step": row[6], "steps": row[7]}


# ------------------------------------------------------------------ live events
class Hub:
    """Fan-out of stored events to the SSE clients, with a replay buffer for Last-Event-ID."""

    def __init__(self):
        self.lock = threading.Lock()
        self.clients = set()
        self.seq = 0
        self.recent = []
        self.closed = threading.Event()

    def publish(self, kind, payload, keep=True):
        with self.lock:
            self.seq += 1
            item = (self.seq, kind, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            if keep:
                self.recent = (self.recent + [item])[-REPLAY:]
            for q in list(self.clients):
                try:
                    q.put_nowait(item)
                except queue.Full:          # a stalled client: drop it (its stream ends; the browser reconnects)
                    self.clients.discard(q)
            return self.seq

    def subscribe(self, last_id=None):
        """-> (queue, backlog), or (None, []) when MAX_SSE streams are open already."""
        q = queue.Queue(maxsize=1000)
        with self.lock:
            if len(self.clients) >= MAX_SSE:
                return None, []
            backlog = [it for it in self.recent if last_id is not None and it[0] > last_id]
            self.clients.add(q)
        return q, backlog

    def unsubscribe(self, q):
        with self.lock:
            self.clients.discard(q)


class Throttle:
    """At most one publish per `every` seconds. A value offered too soon is held and the newest held value goes out when
    the interval ends, so viewers are never flooded and the last state always arrives."""

    def __init__(self, publish, every=None, clock=time.monotonic):
        self.publish, self.every, self.clock = publish, PUSH_EVERY if every is None else every, clock
        self.lock = threading.Lock()
        self.last = None
        self.pending = None
        self.timer = None
        self.closed = False

    def offer(self, payload):
        with self.lock:
            if self.closed:
                return False
            now = self.clock()
            wait = 0.0 if self.last is None else self.last + self.every - now
            if wait <= 0 and self.timer is None:
                self.last = now
                send = True
            else:
                self.pending = payload
                if self.timer is None:
                    self.timer = threading.Timer(max(0.0, wait), self._flush)
                    self.timer.daemon = True
                    self.timer.start()
                send = False
        if send:
            self.publish(payload)
        return send

    def _flush(self):
        with self.lock:
            payload, self.pending, self.timer = self.pending, None, None
            if payload is None or self.closed:
                return
            self.last = self.clock()
        self.publish(payload)

    def close(self):
        with self.lock:
            self.closed = True
            if self.timer:
                self.timer.cancel()
                self.timer = None


class Machine:
    """monitor.py's samples: a ring of 2 s samples (10 min) in memory, 1-min averages in SQLite (24 h), the newest
    ComfyUI state."""

    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock
        self.lock = threading.Lock()
        self.ring = collections.deque(maxlen=METRICS_RING)
        self.latest = None
        self.bucket = []            # chart rows of the minute in progress
        self.comfy = None
        self.links = {}             # prompt id -> build (positive answers only)

    def add_metrics(self, sample, now=None):
        now = self.clock() if now is None else now
        sample = dict(sample, t=round(now, 2))
        row = dict(flat_sample(sample), disks=sample.get("disks") or [])
        flush = []
        with self.lock:
            self.ring.append(sample)
            self.latest = sample
            if self.bucket and int(self.bucket[0]["t"] // MINUTE) != int(now // MINUTE):
                flush, self.bucket = downsample(self.bucket), []
            self.bucket.append(row)
        if flush:
            self.store.save_minutes(flush, now - KEEP_HISTORY)
        return sample

    def window(self, name, now=None):
        now = self.clock() if now is None else now
        with self.lock:
            if name == "10m":
                rows = [flat_sample(s) for s in self.ring if s["t"] >= now - 600]
                return {"interval": 2, "samples": rows}
            live = downsample(self.bucket) if self.bucket else []
        rows = self.store.minutes(now - KEEP_HISTORY) + live
        for r in rows:
            r.pop("disks", None)
        return {"interval": 60, "samples": rows}

    def set_comfy(self, state, now=None):
        now = self.clock() if now is None else now
        state = dict(state, t=round(now, 2))
        state["build"] = self.link(state.get("prompt_id"), fresh=True)
        for h in state.get("history") or []:
            h["build"] = self.link(h.get("prompt_id"))
        with self.lock:
            self.comfy = state
        return state

    def link(self, pid, fresh=False):
        """The build of a prompt. fresh: the running prompt, read again each time (its image k/N moves on); finished
        prompts come from the cache."""
        if not pid:
            return None
        if pid in self.links and not fresh:
            return self.links[pid]
        b = self.store.comfy_build(pid)
        if b:
            if len(self.links) > 500:
                self.links.clear()
            self.links[pid] = b
        return b

    def status(self, now=None):
        now = self.clock() if now is None else now
        with self.lock:
            latest, comfy = self.latest, self.comfy
        m_age = round(now - latest["t"], 1) if latest else None
        c_age = round(now - comfy["t"], 1) if comfy else None
        return {"latest": latest, "age": m_age, "online": m_age is not None and m_age < MONITOR_STALE,
                "comfy": comfy, "comfy_age": c_age, "comfy_online": c_age is not None and c_age < MONITOR_STALE}


# ------------------------------------------------------------------ files
def resolve_under(root, rel):
    """Absolute path of rel under root, or None when it escapes (.., absolute, symlink out) or is not a file."""
    rel = safe_rel(rel)
    if rel is None:
        return None
    root_real = os.path.realpath(root)
    full = os.path.realpath(os.path.join(root_real, *rel.split("/")))
    if os.path.commonpath([root_real, full]) != root_real or full == root_real:
        return None
    return full


def etag_of(st):
    return '"%x-%x"' % (int(st.st_mtime_ns), st.st_size)


def parse_range(header, size):
    """-> None (no/ignored range), (start, end) inclusive, or 'bad' (416)."""
    if not header:
        return None
    m = re.fullmatch(r"\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*", header)
    if not m:
        if header.strip().startswith("bytes=") and "," in header:
            return None                      # several ranges: answer 200 with the whole file (RFC 9110 allows it)
        return "bad"
    a, b = m.group(1), m.group(2)
    if a == "" and b == "":
        return "bad"
    if a == "":
        n = int(b)
        if n == 0:
            return "bad"
        return (max(0, size - n), size - 1) if size else "bad"
    start = int(a)
    end = int(b) if b else size - 1
    if start >= size or end < start:
        return "bad"
    return start, min(end, size - 1)


def importmap_hashes(web_root):
    """CSP hashes of the inline import maps of the web app's pages ('sha256-...')."""
    out = []
    if not web_root or not os.path.isdir(web_root):
        return out
    for name in sorted(os.listdir(web_root)):
        if not name.endswith(".html"):
            continue
        with open(os.path.join(web_root, name), encoding="utf-8") as fh:
            html = fh.read()
        for m in re.finditer(r'<script type="importmap">(.*?)</script>', html, re.S):
            digest = hashlib.sha256(m.group(1).encode("utf-8")).digest()
            out.append("'sha256-%s'" % base64.b64encode(digest).decode())
    return out


def csp_header(hashes):
    """connect-src needs blob: too: three.js's GLTFLoader fetch()es the blob: URLs of a GLB's embedded textures."""
    script = " ".join(["'self'"] + hashes)
    return ("default-src 'none'; script-src %s; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "media-src 'self' blob:; connect-src 'self' blob:; font-src 'self'; worker-src 'self' blob:; "
            "manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'" % script)


# ------------------------------------------------------------------ HTTP
class Reaper:
    """Shuts down connections whose request head did not arrive within REQUEST_DEADLINE (a slow-loris client that
    sends one byte now and then never trips the per-read socket timeout)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.watch = {}
        self.stopped = threading.Event()

    def arm(self, key, sock, seconds):
        with self.lock:
            self.watch[key] = (time.monotonic() + seconds, sock)

    def disarm(self, key):
        """-> False when the deadline had already fired for key."""
        with self.lock:
            return self.watch.pop(key, None) is not None

    def run(self):
        while not self.stopped.wait(0.2):
            now = time.monotonic()
            with self.lock:
                late = [k for k, (t, _) in self.watch.items() if t <= now]
                socks = [self.watch.pop(k)[1] for k in late]
            for s in socks:
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass


DEFAULT_TAGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tags.json")
OVERLAY_TAGS = "_tags.json"        # in the media root: project labels (never a build folder: ids start [A-Za-z0-9])


class App:
    def __init__(self, db, media, web, host="0.0.0.0", public_port=8790, ingest_port=8791, quiet=False,
                 ingest_hosts=(), tags=None):
        self.registry = Registry(tags or DEFAULT_TAGS, os.path.join(os.path.abspath(media), OVERLAY_TAGS))
        self.store = Store(db, self.registry)
        self.hub = Hub()
        self.reaper = Reaper()
        self.ingest_hosts = {h.strip().lower() for h in ingest_hosts if h.strip()}
        self.machine = Machine(self.store)
        self.push = {k: Throttle(lambda p, k=k: self.hub.publish(k, p, keep=False)) for k in SYS_EVENTS}
        self.media = os.path.abspath(media)
        self.web = os.path.abspath(web) if web else None
        self.csp = csp_header(importmap_hashes(self.web))
        self.quiet = quiet
        self.started = time.time()
        self.public = ThreadingHTTPServer((host, public_port), make_public(self))
        self.ingest = ThreadingHTTPServer((host, ingest_port), make_ingest(self))
        for s in (self.public, self.ingest):
            s.daemon_threads = True
        self.threads = []

    @property
    def public_port(self):
        return self.public.server_address[1]

    @property
    def ingest_port(self):
        return self.ingest.server_address[1]

    def start(self):
        for s in (self.public, self.ingest):
            t = threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
            t.start()
            self.threads.append(t)
        threading.Thread(target=self._heartbeat, daemon=True).start()
        threading.Thread(target=self.reaper.run, daemon=True).start()
        return self

    def _heartbeat(self):
        while not self.hub.closed.wait(HEARTBEAT):
            self.hub.publish("heartbeat", {"t": time.time()}, keep=False)

    def stop(self):
        self.hub.closed.set()
        self.reaper.stopped.set()
        for t in self.push.values():
            t.close()
        for s in (self.public, self.ingest):
            s.shutdown()
            s.server_close()
        self.store.close()

    def ingest_event(self, ev):
        if isinstance(ev, dict) and ev.get("type") in SYS_EVENTS:
            return self.ingest_sys(ev)
        kind, bid, fields = validate(ev)
        data = self.store.apply(kind, bid, fields)
        summary = self.store.build(bid)
        seq = self.hub.publish(kind, {"type": kind, "build": summary, "data": data})
        return {"ok": True, "id": seq, "build": summary}

    def ingest_sys(self, ev):
        kind, fields = validate_sys(ev)
        if kind == "metrics":
            sample = self.machine.add_metrics(fields)
            self.push[kind].offer({"type": kind, "sample": sample})
        else:
            state = self.machine.set_comfy(fields)
            self.push[kind].offer({"type": kind, "comfy": state})
        return {"ok": True}


class Base(BaseHTTPRequestHandler):
    server_version = "film-lab-review/" + VERSION
    sys_version = ""
    protocol_version = "HTTP/1.1"
    app = None

    def log_message(self, fmt, *args):
        if not self.app.quiet:
            sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    # --- slow clients: a socket timeout for every read (and an idle keep-alive), a deadline for the request head
    def setup(self):
        self.timeout = PUBLIC_TIMEOUT
        super().setup()

    def handle_one_request(self):
        try:
            self.connection.settimeout(PUBLIC_TIMEOUT)      # a file or stream before may have set a longer one
        except OSError:
            pass
        key = id(self)
        self.app.reaper.arm(key, self.connection, REQUEST_DEADLINE)
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            self.close_connection = True
        finally:
            self.app.reaper.disarm(key)

    def parse_request(self):
        ok = super().parse_request()
        if not self.app.reaper.disarm(id(self)):            # too slow: the socket is shut already
            self.close_connection = True
            return False
        return ok

    def send_json(self, obj, code=200, extra=None):
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.common_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def common_headers(self):
        pass

    def not_allowed(self, allow):
        self.close_connection = True            # the request body (if any) is not read
        self.send_json({"error": f"method {self.command} not allowed"}, 405, {"Allow": allow})


class PublicHandler(Base):
    """Read-only: GET and HEAD. Every other method answers 405."""

    def __getattr__(self, name):
        if name.startswith("do_"):
            return lambda: self.not_allowed("GET, HEAD")
        raise AttributeError(name)

    def common_headers(self):
        self.send_header("Content-Security-Policy", self.app.csp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        try:
            url = urllib.parse.urlsplit(self.path)
            raw = url.path
            if raw.startswith("/media/"):
                return self.serve_media(raw[len("/media/"):])
            if raw == "/api/stream":
                return self.stream()
            if raw.startswith("/api/"):
                return self.api(raw[len("/api/"):], urllib.parse.parse_qs(url.query))
            return self.serve_web(raw)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True

    # --- API
    def api(self, path, qs):
        store = self.app.store
        parts = [urllib.parse.unquote(p) for p in path.strip("/").split("/")]
        if parts == ["health"]:
            return self.send_json({"ok": True, "version": VERSION, "uptime": round(time.time() - self.app.started, 1),
                                   "clients": len(self.app.hub.clients),
                                   "monitor": self.app.machine.status()["online"]})
        if parts == ["metrics"]:
            win = (qs.get("window") or ["10m"])[0]
            if win not in ("10m", "24h"):
                return self.send_json({"error": "window must be 10m or 24h"}, 400)
            st = self.app.machine.status()
            out = {"window": win, "now": round(time.time(), 2), "latest": st["latest"], "age": st["age"],
                   "online": st["online"]}
            out.update(self.app.machine.window(win))
            return self.send_json(out)
        if parts == ["comfy"]:
            st = self.app.machine.status()
            return self.send_json({"comfy": st["comfy"], "age": st["comfy_age"], "online": st["comfy_online"]})
        if parts == ["builds"]:
            return self.send_json({"builds": store.builds()})
        if parts == ["tags"]:
            return self.send_json(self.app.registry.get())
        if parts == ["renders"]:
            builds = {b["id"]: b for b in store.builds()}
            rows = store.rows("renders")
            for r in rows:
                b = builds.get(r["build"]) or {}
                r["build_title"] = b.get("title")
                r["project"] = b.get("project")
            return self.send_json({"renders": rows})
        if len(parts) >= 2 and parts[0] == "builds" and BUILD_ID.match(parts[1]):
            b = store.build(parts[1])
            if not b:
                return self.send_json({"error": "no such build"}, 404)
            if len(parts) == 2:
                return self.send_json({"build": b, "steps": store.rows("steps", parts[1]),
                                       "renders": store.rows("renders", parts[1]),
                                       "jobs": store.rows("jobs", parts[1])})
            if len(parts) == 3 and parts[2] in ("steps", "renders", "jobs"):
                return self.send_json({parts[2]: store.rows(parts[2], parts[1])})
        return self.send_json({"error": "not found"}, 404)

    # --- SSE
    def stream(self):
        if self.command == "HEAD":
            return self.send_json({}, 200)
        last = self.headers.get("Last-Event-ID")
        try:
            last = int(last) if last else None
        except ValueError:
            last = None
        q, backlog = self.app.hub.subscribe(last)
        if q is None:
            self.close_connection = True
            return self.send_json({"error": "too many live viewers, try again soon"}, 503, {"Retry-After": "10"})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "keep-alive")
        self.common_headers()
        self.end_headers()
        self.close_connection = True
        end = time.monotonic() + SSE_LIFETIME            # then the browser's EventSource reconnects (Last-Event-ID)
        try:
            self.connection.settimeout(SSE_SEND_TIMEOUT)
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.write(("event: hello\ndata: %s\n\n" % json.dumps({"t": time.time(), "version": VERSION})).encode())
            for item in backlog:
                self.write_event(item)
            self.wfile.flush()
            while not self.app.hub.closed.is_set() and time.monotonic() < end:
                try:
                    item = q.get(timeout=max(0.01, min(1.0, end - time.monotonic())))
                except queue.Empty:
                    if q not in self.app.hub.clients:       # dropped as too slow
                        break
                    continue
                self.write_event(item)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            self.app.hub.unsubscribe(q)

    def write_event(self, item):
        seq, kind, data = item
        self.wfile.write(("id: %d\nevent: %s\ndata: %s\n\n" % (seq, kind, data)).encode("utf-8"))

    # --- files
    def serve_web(self, raw):
        if not self.app.web:
            return self.send_json({"error": "not found"}, 404)
        rel = urllib.parse.unquote(raw).lstrip("/") or "index.html"
        if rel.endswith("/"):
            rel += "index.html"
        full = resolve_under(self.app.web, rel)
        if full is None:
            return self.send_json({"error": "forbidden"}, 403)
        ext = os.path.splitext(full)[1].lower()
        if ext not in WEB_TYPES or not os.path.isfile(full):
            return self.send_json({"error": "not found"}, 404)
        cache = "public, max-age=86400" if "/vendor/" in "/" + rel else "no-cache"
        return self.send_file(full, WEB_TYPES[ext], cache, ranges=False)

    def serve_media(self, rel_raw):
        rel = urllib.parse.unquote(rel_raw)
        full = resolve_under(self.app.media, rel)
        if full is None:
            return self.send_json({"error": "forbidden"}, 403)
        ext = os.path.splitext(full)[1].lower()
        if ext not in MEDIA_TYPES or not os.path.isfile(full):
            return self.send_json({"error": "not found"}, 404)
        return self.send_file(full, MEDIA_TYPES[ext], "public, max-age=300", ranges=True)

    def send_file(self, full, ctype, cache, ranges):
        try:
            fh = open(full, "rb")
        except OSError:
            return self.send_json({"error": "not found"}, 404)
        with fh:
            st = os.fstat(fh.fileno())
            size, tag = st.st_size, etag_of(st)
            if self.headers.get("If-None-Match") == tag:
                self.send_response(304)
                self.send_header("ETag", tag)
                self.send_header("Content-Length", "0")
                self.common_headers()
                self.end_headers()
                return
            rng = parse_range(self.headers.get("Range"), size) if ranges else None
            if ranges and self.headers.get("If-Range") and self.headers.get("If-Range") != tag:
                rng = None
            if rng == "bad":
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.common_headers()
                self.end_headers()
                return
            start, end = rng if rng else (0, size - 1)
            length = max(0, end - start + 1)
            self.send_response(206 if rng else 200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("ETag", tag)
            self.send_header("Last-Modified", email.utils.formatdate(st.st_mtime, usegmt=True))
            self.send_header("Cache-Control", cache)
            if ranges:
                self.send_header("Accept-Ranges", "bytes")
            if rng:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.common_headers()
            self.end_headers()
            if self.command == "HEAD" or not length:
                return
            self.connection.settimeout(SEND_TIMEOUT)
            fh.seek(start)
            left = length
            while left > 0:
                buf = fh.read(min(CHUNK, left))
                if not buf:
                    break
                self.wfile.write(buf)
                left -= len(buf)


class IngestHandler(Base):
    """Write side: POST /ingest/event only (plus GET /ingest/health for the clients' probes)."""

    def __getattr__(self, name):
        if name.startswith("do_"):
            return lambda: self.not_allowed("POST")
        raise AttributeError(name)

    def host_ok(self):
        """DNS rebinding: a page of evil.example that resolves to 127.0.0.1 still sends Host: evil.example."""
        hosts = self.headers.get_all("Host") or []
        if len(hosts) != 1:
            return False
        host = hosts[0].strip().lower()
        port = self.server.server_address[1]
        ok = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"} | self.app.ingest_hosts
        return host in ok

    def refuse(self, why):
        self.close_connection = True                # the request body (if any) is not read
        return self.send_json({"error": why}, 403)

    def do_GET(self):
        if not self.host_ok():
            return self.refuse("Host must be 127.0.0.1 or localhost with the ingest port")
        if self.path == "/ingest/health":
            return self.send_json({"ok": True, "version": VERSION})
        return self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        if not self.host_ok():
            return self.refuse("Host must be 127.0.0.1 or localhost with the ingest port")
        if self.headers.get(INGEST_HEADER, "").strip() != "1":
            return self.refuse(f"the header {INGEST_HEADER}: 1 is required (tools/review/client.py sends it)")
        if self.path != "/ingest/event":
            self.close_connection = True
            return self.send_json({"error": "not found"}, 404)
        try:
            n = int(self.headers.get("Content-Length") or "-1")
        except ValueError:
            n = -1
        if n < 0:
            return self.send_json({"error": "Content-Length is required"}, 411)
        if n > MAX_BODY:
            self.close_connection = True
            return self.send_json({"error": "body too large"}, 413)
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        body = self.rfile.read(n)
        if ctype != "application/json":
            return self.send_json({"error": "Content-Type must be application/json"}, 415)
        try:
            ev = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return self.send_json({"error": "invalid JSON"}, 400)
        try:
            return self.send_json(self.app.ingest_event(ev))
        except BadEvent as e:
            return self.send_json({"error": str(e)}, 400)
        except sqlite3.Error as e:
            return self.send_json({"error": f"database: {e}"}, 500)


def make_public(app):
    return type("Public", (PublicHandler,), {"app": app})


def make_ingest(app):
    return type("Ingest", (IngestHandler,), {"app": app})


def main(argv=None):
    p = argparse.ArgumentParser(prog="server.py", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--db", default=os.environ.get("REVIEW_DB", "/data/review.db"))
    p.add_argument("--media", default=os.environ.get("REVIEW_MEDIA", "/media"))
    p.add_argument("--web", default=os.environ.get("REVIEW_WEB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")))
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--public-port", type=int, default=8790)
    p.add_argument("--ingest-port", type=int, default=8791)
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--tags", default=os.environ.get("REVIEW_TAGS", DEFAULT_TAGS),
                   help="tag registry (default tags.json next to server.py); <media>/_tags.json is merged over it")
    p.add_argument("--ingest-host", action="append", default=(os.environ.get("REVIEW_INGEST_HOSTS") or "").split(","),
                   help="another accepted Host of the ingest port (host:port), e.g. when it is published on another "
                        "port; 127.0.0.1|localhost|[::1]:<ingest port> are always accepted")
    a = p.parse_args(argv)
    mimetypes.init()
    app = App(a.db, a.media, a.web, a.host, a.public_port, a.ingest_port, a.quiet, a.ingest_host, a.tags).start()
    print(f"film-lab-review {VERSION}: public :{app.public_port} (read-only) · ingest :{app.ingest_port} · "
          f"db {a.db} · media {a.media}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        app.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
