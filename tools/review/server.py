#!/usr/bin/env python3
"""Film Lab review server: live status of 3D builds and renders, a model viewer and a video timeline (tools/review/).

Runs in the film-lab-review container (tools/review/docker-compose.yml); standard library only.

  python server.py --db /data/review.db --media /media --web /app/web [--public-port 8790] [--ingest-port 8791]

Two listeners:
  public 8790 (read-only: GET/HEAD only, every other method is 405)
      /                      the web app (tools/review/web/), no directory listing
      /api/health            {"ok": true, ...}
      /api/builds            every build, newest first (summary rows)
      /api/builds/<id>       one build with its steps, renders and jobs
      /api/builds/<id>/steps | /renders | /jobs
      /api/renders           every render of every build (the timeline's library)
      /api/metrics?window=10m|24h   machine metrics from monitor.py: 2 s samples (10 min, memory) or 1 min averages
                             (24 h, SQLite), plus the latest full sample
      /api/comfy             ComfyUI state from monitor.py: up, queue, current job's steps, last 10 jobs (+ linked build)
      /api/stream            Server-Sent Events: build, step, progress, render, job, done, fail, metrics, comfy
                             (metrics and comfy: at most one each per 2 s, not replayed) + heartbeat
      /media/<path>          files under the read-only media mount, HTTP Range (206/416), allowlisted types only
  ingest 8791 (write)
      POST /ingest/event     one JSON event (types above); unknown types and fields are refused (400); metrics and
                             comfy events carry no build
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
import sqlite3
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.1.0"
BUILD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
KINDS = ("model", "render", "clip", "demo")
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
STR, NUM, INT, OBJ, PATH, BOOL = "str", "num", "int", "obj", "path", "bool"
EVENTS = {
    "build": {"title": (STR, False), "kind": (STR, False), "project": (STR, False), "expected_steps": (INT, False),
              "status": (STR, False), "restart": (BOOL, False)},
    "step": {"label": (STR, True), "n": (INT, False), "glb": (PATH, False), "image": (PATH, False),
             "stats": (OBJ, False)},
    "progress": {"progress": (NUM, True), "message": (STR, False), "status": (STR, False)},
    "render": {"label": (STR, True), "video": (PATH, False), "image": (PATH, False), "frames": (INT, False),
               "fps": (NUM, False), "duration": (NUM, False), "engine": (STR, False),
               "seconds_per_frame": (NUM, False)},
    "job": {"job": (STR, False), "tool": (STR, True), "status": (STR, True), "progress": (NUM, False),
            "gpu_s": (NUM, False), "message": (STR, False)},
    "done": {"message": (STR, False)},
    "fail": {"message": (STR, False)},
}
MAX_STR = {"title": 200, "label": 200, "message": 500, "project": 100, "engine": 60, "job": 100, "kind": 20,
           "status": 20, "tool": 20}

SCHEMA = """
CREATE TABLE IF NOT EXISTS builds (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('model','render','clip','demo')),
  project TEXT,
  status TEXT NOT NULL CHECK (status IN ('queued','building','rendering','done','failed')),
  progress REAL NOT NULL DEFAULT 0 CHECK (progress >= 0 AND progress <= 1),
  expected_steps INTEGER,
  current TEXT,
  message TEXT,
  thumb TEXT,
  started REAL NOT NULL,
  updated REAL NOT NULL,
  finished REAL
);
CREATE TABLE IF NOT EXISTS steps (
  id INTEGER PRIMARY KEY,
  build TEXT NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
  n INTEGER NOT NULL,
  label TEXT NOT NULL,
  stats TEXT,
  glb TEXT,
  image TEXT,
  t REAL NOT NULL,
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
            v = v.strip()[:MAX_STR.get(name, 200)]
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
        elif ftype == PATH:
            if safe_rel(v) is None or not v.startswith(bid + "/"):
                raise BadEvent(f"{kind}: {name} must be a media path under '{bid}/' (no '..', no absolute path)")
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
    for name in ("fps", "duration", "seconds_per_frame", "gpu_s", "frames"):
        if name in out and out[name] < 0:
            raise BadEvent(f"{kind}: {name} must be >= 0")
    return kind, bid, out


# --- machine metrics and ComfyUI state (monitor.py). The public page shows them: names are tightly limited so a path,
# a command line or a user name can never get through, whatever the sender puts in.
SYS_EVENTS = ("metrics", "comfy")
# Job labels: exactly the labels of monitor.py's allow list (HEAVY + "ComfyUI (python)"; a test keeps both equal).
PROC_LABELS = frozenset({"blender", "ComfyUI Desktop", "ComfyUI (python)", "ffmpeg", "DaVinci Resolve", "Unreal Editor",
                         "Houdini", "Maya", "ollama", "llama.cpp"})
DISK_NAME = re.compile(r"^(?:[A-Z]:|/)$")
GPU_NAME = re.compile(r"^[A-Za-z0-9 ._()+-]{1,60}$")
PROMPT_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
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
        _sys_keys("metrics", ev, ("type", "t", "cpu", "ram_used", "ram_total", "gpus", "disks", "procs"))
        out = {"cpu": _sys_num("metrics: cpu", ev.get("cpu"), 0, 100),
               "ram_used": _sys_num("metrics: ram_used", ev.get("ram_used"), 0, BIG, True),
               "ram_total": _sys_num("metrics: ram_total", ev.get("ram_total"), 0, BIG, True),
               "gpus": [], "disks": [], "procs": []}
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
class Store:
    """The SQLite database (one connection, one lock: this process is its only user)."""

    def __init__(self, path):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA busy_timeout=5000")
            self.db.executescript(SCHEMA)

    def close(self):
        with self.lock:
            self.db.close()

    # --- reads
    def _summary(self, row):
        b = dict(row)
        bid = b["id"]
        b["steps"] = self.db.execute("SELECT COUNT(*) FROM steps WHERE build=?", (bid,)).fetchone()[0]
        b["renders"] = self.db.execute("SELECT COUNT(*) FROM renders WHERE build=?", (bid,)).fetchone()[0]
        last = self.db.execute("SELECT glb FROM steps WHERE build=? AND glb IS NOT NULL ORDER BY n DESC LIMIT 1",
                               (bid,)).fetchone()
        b["last_glb"] = last[0] if last else None
        job = self.db.execute("SELECT * FROM jobs WHERE build=? ORDER BY t DESC LIMIT 1", (bid,)).fetchone()
        b["job"] = dict(job) if job else None
        return b

    def builds(self):
        with self.lock:
            rows = self.db.execute("SELECT * FROM builds ORDER BY updated DESC").fetchall()
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
            if "stats" in d:
                try:
                    d["stats"] = json.loads(d["stats"]) if d["stats"] else {}
                except ValueError:
                    d["stats"] = {}
            out.append(d)
        return out

    # --- writes
    def _ensure(self, bid, now, kind="model"):
        row = self.db.execute("SELECT id FROM builds WHERE id=?", (bid,)).fetchone()
        if not row:
            self.db.execute("INSERT INTO builds (id, title, kind, status, progress, started, updated) "
                            "VALUES (?, ?, ?, 'building', 0, ?, ?)", (bid, bid, kind, now, now))

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
                db.execute("INSERT INTO builds (id, title, kind, project, status, progress, expected_steps, started, "
                           "updated) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)",
                           (bid, f.get("title") or bid, f.get("kind") or "model", f.get("project"),
                            f.get("status") or "building", f.get("expected_steps"), now, now))
            else:
                sets, vals = ["updated=?"], [now]
                for col in ("title", "kind", "project", "expected_steps", "status"):
                    if col in f:
                        sets.append(f"{col}=?")
                        vals.append(f[col])
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
            db.execute("INSERT INTO steps (build, n, label, stats, glb, image, t) VALUES (?, ?, ?, ?, ?, ?, ?) "
                       "ON CONFLICT(build, n) DO UPDATE SET label=excluded.label, stats=excluded.stats, "
                       "glb=excluded.glb, image=excluded.image, t=excluded.t",
                       (bid, n, f["label"], stats, f.get("glb"), f.get("image"), now))
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
                    "image": f.get("image"), "t": now}
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
            sets, vals = ["updated=?"], [now]
            if f.get("image"):
                sets.append("thumb=COALESCE(thumb, ?)")
                vals.append(f["image"])
            db.execute(f"UPDATE builds SET {', '.join(sets)} WHERE id=?", vals + [bid])
            return dict({c: f.get(c) for c in cols}, id=rid, build=bid, t=now)
        if kind == "job":
            key = f.get("job") or f["tool"]
            db.execute("INSERT INTO jobs (build, job, tool, status, progress, gpu_s, message, started, t) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(build, job) DO UPDATE SET "
                       "tool=excluded.tool, status=excluded.status, progress=COALESCE(excluded.progress, progress), "
                       "gpu_s=COALESCE(excluded.gpu_s, gpu_s), message=COALESCE(excluded.message, message), "
                       "t=excluded.t",
                       (bid, key, f["tool"], f["status"], f.get("progress"), f.get("gpu_s"), f.get("message"),
                        now, now))
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
        """The build whose comfy.py job ran this prompt (comfy.py --review names the job comfy-<prompt id>)."""
        with self.lock:
            row = self.db.execute("SELECT j.build, b.title FROM jobs j JOIN builds b ON b.id = j.build "
                                  "WHERE j.tool = 'comfy' AND j.job = ? ORDER BY j.t DESC LIMIT 1",
                                  ("comfy-" + prompt_id,)).fetchone()
        return {"id": row[0], "title": row[1]} if row else None


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
        q = queue.Queue(maxsize=1000)
        with self.lock:
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
        state["build"] = self.link(state.get("prompt_id"))
        for h in state.get("history") or []:
            h["build"] = self.link(h.get("prompt_id"))
        with self.lock:
            self.comfy = state
        return state

    def link(self, pid):
        if not pid:
            return None
        if pid in self.links:
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
    script = " ".join(["'self'"] + hashes)
    return ("default-src 'none'; script-src %s; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "media-src 'self' blob:; connect-src 'self'; font-src 'self'; worker-src 'self' blob:; "
            "manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'" % script)


# ------------------------------------------------------------------ HTTP
class App:
    def __init__(self, db, media, web, host="0.0.0.0", public_port=8790, ingest_port=8791, quiet=False):
        self.store = Store(db)
        self.hub = Hub()
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
        return self

    def _heartbeat(self):
        while not self.hub.closed.wait(HEARTBEAT):
            self.hub.publish("heartbeat", {"t": time.time()}, keep=False)

    def stop(self):
        self.hub.closed.set()
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
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "keep-alive")
        self.common_headers()
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.write(("event: hello\ndata: %s\n\n" % json.dumps({"t": time.time(), "version": VERSION})).encode())
            for item in backlog:
                self.write_event(item)
            self.wfile.flush()
            while not self.app.hub.closed.is_set():
                try:
                    item = q.get(timeout=1.0)
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

    def do_GET(self):
        if self.path == "/ingest/health":
            return self.send_json({"ok": True, "version": VERSION})
        return self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/ingest/event":
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
    a = p.parse_args(argv)
    mimetypes.init()
    app = App(a.db, a.media, a.web, a.host, a.public_port, a.ingest_port, a.quiet).start()
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
