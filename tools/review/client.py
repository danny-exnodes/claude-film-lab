"""Publish build/render progress to the Film Lab review server (tools/review/server.py). Standard library only.

Runs on the host (Windows or Linux, Python 3.10+) and inside Blender's Python 3.13:

    from client import Review                      # or load tools/review/client.py by path
    rv = Review("giot-demo", "Giọt từng bước", "demo", project="lab", expected_steps=10)
    rv.step("body", glb="out/step_01.glb", stats={"verts": 930})
    rv.progress(0.4, "frame 48/120")
    rv.job("blender", "running", progress=0.4, message="frame 48/120")
    rv.render("beauty", video="out/beauty.mp4", frames=120, fps=24, duration=5.0)
    rv.done()                                       # or rv.fail("why")

Files given to step()/render() are hard-linked (else copied) into <lab>/out/_review/media/<build>/ (never overwritten:
a different file with the same name gets a -2, -3 ... suffix), then the event is POSTed to FILM_REVIEW_URL
(default http://127.0.0.1:8791/ingest/event).

Every POST carries the header X-Film-Review: 1 (the server refuses a POST without it: a web page cannot send it
cross-origin, so DNS rebinding cannot write). Text fields are scrubbed before they leave (an absolute path becomes its
base name; the server scrubs again): the dashboard is public.

Offline-safe: every call returns True/False and never raises into the caller. A request waits at most 2 s; after a
timeout the client stays quiet for 15 s (progress/job/step events are skipped; build, render, done and fail are
always tried) so a render never slows down because the review server is gone.

Env: FILM_REVIEW_URL (base URL of the ingest port; "off" disables publishing), FILM_REVIEW_MEDIA (media folder).
"""
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(os.path.dirname(HERE))
DEFAULT_URL = "http://127.0.0.1:8791"
DEFAULT_MEDIA = os.path.join(LAB, "out", "_review", "media")
BUILD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
TIMEOUT = 2.0
QUIET_AFTER_TIMEOUT = 15.0
ALWAYS = ("build", "render", "done", "fail")
TEXT_FIELDS = {"title": 200, "label": 200, "message": 500, "project": 100, "engine": 60}     # server.py MAX_STR
NAME_BAD = re.compile(r"[^A-Za-z0-9._-]+")

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # never through a system proxy
# Every publisher (this client, monitor.py) sends these; server.py refuses a POST without X-Film-Review: 1.
INGEST_HEADERS = {"Content-Type": "application/json", "X-Film-Review": "1"}
# The same pattern as server.py PATHLIKE (a test keeps the two equal): an absolute path -> its base name.
PATHLIKE = re.compile(r"(?:\\\\|(?<![A-Za-z0-9])[A-Za-z]:[\\/]|(?<![\w.:/~-])~?/(?=[^\s/]))"
                      r"(?:[^\\/\"'<>|\r\n]*[\\/])*[^\s\\/\"'<>|]*")
CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def _basename(m):
    parts = [p.strip() for p in re.split(r"[\\/]", m.group(0)) if p.strip()]
    last = parts[-1] if parts else ""
    return "…" if not last or re.fullmatch(r"[A-Za-z]:|~", last) else last


def scrub(text, limit=500):
    """Text for the public dashboard: absolute paths -> base names, no control characters, at most `limit` chars."""
    return PATHLIKE.sub(_basename, CONTROL.sub(" ", str(text))).strip()[:limit]


def ingest_url(base=None):
    base = (base or os.environ.get("FILM_REVIEW_URL") or DEFAULT_URL).strip().rstrip("/")
    if base.lower() in ("off", "0", "no", "false"):
        return None
    if base.endswith("/ingest/event"):
        return base
    return base + "/ingest/event"


def media_root(path=None):
    return os.path.abspath(path or os.environ.get("FILM_REVIEW_MEDIA") or DEFAULT_MEDIA)


def safe_name(name):
    stem, ext = os.path.splitext(os.path.basename(name))
    stem = NAME_BAD.sub("_", stem).strip("._") or "file"
    ext = NAME_BAD.sub("", ext)
    return (stem[:80] + ext.lower()[:10]) if ext else stem[:80]


def _same_content(a, b):
    try:
        if os.path.samefile(a, b):
            return True
        if os.path.getsize(a) != os.path.getsize(b):
            return False
    except OSError:
        return False
    return _sha(a) == _sha(b)


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Review:
    """One build on the review server. Every method returns True when the event was delivered."""

    def __init__(self, build_id, title=None, kind="model", project=None, expected_steps=None, *, url=None,
                 media=None, status=None, restart=False, announce=True):
        self.build = str(build_id)
        self.title = title             # None: not sent (an existing build keeps its title; a new one is named by its id)
        self.kind = kind
        self.project = project
        self.expected_steps = expected_steps
        self.status = status
        self.restart = bool(restart)
        self.url = ingest_url(url)
        self.media = media_root(media)
        self.enabled = bool(self.url) and bool(BUILD_ID.match(self.build))
        self.n = 0
        self.last_error = None
        self._quiet_until = 0.0
        self._announced = False
        self._warned = False
        if not BUILD_ID.match(self.build):
            self._warn(f"build id {self.build!r} is not valid ([A-Za-z0-9][A-Za-z0-9._-]{{0,63}}): publishing is off")
        if announce:
            self.announce()

    # ------------------------------------------------------------------ public API
    def announce(self, status=None):
        ev = {"type": "build"}
        if self.title:
            ev["title"] = str(self.title)
        if self.kind:
            ev["kind"] = self.kind
        if self.project:
            ev["project"] = self.project
        if self.expected_steps:
            ev["expected_steps"] = int(self.expected_steps)
        if status or self.status:
            ev["status"] = status or self.status
        if self.restart and not self._announced:
            ev["restart"] = True
        ok = self._post(ev)
        self._announced = self._announced or ok
        return ok

    def media_dir(self):
        """<media>/<build>/ (created): write files straight here to skip the copy."""
        d = os.path.join(self.media, self.build)
        os.makedirs(d, exist_ok=True)
        return d

    def step(self, label, glb=None, image=None, stats=None, n=None):
        try:
            self.n = int(n) if n else self.n + 1
            ev = {"type": "step", "label": str(label), "n": self.n}
            for key, path in (("glb", glb), ("image", image)):
                rel = self.publish_file(path) if path else None
                if rel:
                    ev[key] = rel
            if stats:
                ev["stats"] = _jsonable(stats)
            return self._post(ev)
        except Exception as e:                       # never into the caller
            return self._failed(e)

    def progress(self, x, message=None, status=None):
        try:
            ev = {"type": "progress", "progress": max(0.0, min(1.0, float(x)))}
            if message:
                ev["message"] = str(message)
            if status:
                ev["status"] = status
            return self._post(ev)
        except Exception as e:
            return self._failed(e)

    def render(self, label, video=None, image=None, frames=None, fps=None, duration=None, engine=None,
               seconds_per_frame=None):
        try:
            ev = {"type": "render", "label": str(label)}
            for key, path in (("video", video), ("image", image)):
                rel = self.publish_file(path) if path else None
                if rel:
                    ev[key] = rel
            if "video" not in ev and "image" not in ev:
                return self._failed(ValueError("render: no file could be published"))
            for key, val, conv in (("frames", frames, int), ("fps", fps, float), ("duration", duration, float),
                                   ("seconds_per_frame", seconds_per_frame, float)):
                if val is not None:
                    ev[key] = conv(val)
            if engine:
                ev["engine"] = str(engine)
            return self._post(ev)
        except Exception as e:
            return self._failed(e)

    def job(self, tool, status, progress=None, gpu_s=None, message=None, job=None):
        try:
            ev = {"type": "job", "tool": tool, "status": status}
            if job:
                ev["job"] = str(job)
            if progress is not None:
                ev["progress"] = max(0.0, min(1.0, float(progress)))
            if gpu_s is not None:
                ev["gpu_s"] = round(float(gpu_s), 1)
            if message:
                ev["message"] = str(message)
            return self._post(ev)
        except Exception as e:
            return self._failed(e)

    def done(self, message=None):
        return self._post({"type": "done", **({"message": str(message)} if message else {})})

    def fail(self, msg=None):
        return self._post({"type": "fail", "message": str(msg or "failed")[:500]})

    # ------------------------------------------------------------------ files
    def publish_file(self, path):
        """Hard-link or copy path into <media>/<build>/ -> the media-relative path, or None."""
        try:
            src = os.path.abspath(path)
            if not os.path.isfile(src):
                self._warn(f"no such file: {path}")
                return None
            folder = self.media_dir()
            if os.path.dirname(src) == os.path.abspath(folder):     # already in place (e.g. bpy_snapshot)
                return f"{self.build}/{os.path.basename(src)}"
            name = safe_name(src)
            stem, ext = os.path.splitext(name)
            k = 1
            while True:
                dest = os.path.join(folder, name)
                if not os.path.exists(dest):
                    break
                if _same_content(src, dest):
                    return f"{self.build}/{name}"
                k += 1
                name = f"{stem}-{k}{ext}"
            tmp = dest + ".part"
            try:
                os.link(src, dest)
            except OSError:
                shutil.copyfile(src, tmp)
                os.replace(tmp, dest)
            return f"{self.build}/{name}"
        except Exception as e:
            self._failed(e)
            return None

    # ------------------------------------------------------------------ transport
    def _post(self, ev):
        if not self.enabled:
            return False
        try:
            kind = ev["type"]
            now = time.monotonic()
            if kind not in ALWAYS and now < self._quiet_until:
                return False
            if kind != "build" and not self._announced:
                if not self.announce() and now < self._quiet_until:
                    return False
            ev = dict(ev, build=self.build)
            for key, limit in TEXT_FIELDS.items():
                if isinstance(ev.get(key), str):
                    ev[key] = scrub(ev[key], limit)
            body = json.dumps(ev, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(self.url, data=body, method="POST", headers=dict(INGEST_HEADERS))
            with _OPENER.open(req, timeout=TIMEOUT) as r:
                r.read()
            self.last_error = None
            return True
        except urllib.error.HTTPError as e:            # the server answered: a bad event, not an outage
            try:
                detail = json.loads(e.read().decode("utf-8")).get("error")
            except Exception:
                detail = e.reason
            return self._failed(RuntimeError(f"HTTP {e.code}: {detail}"))
        except Exception as e:
            reason = getattr(e, "reason", e)
            if isinstance(e, TimeoutError) or isinstance(reason, TimeoutError) or "timed out" in str(e):
                self._quiet_until = time.monotonic() + QUIET_AFTER_TIMEOUT
            return self._failed(e)

    def _failed(self, e):
        self.last_error = f"{type(e).__name__}: {e}"
        self._warn(f"not published ({self.last_error})")
        return False

    def _warn(self, msg):
        if not self._warned:                         # once per build: never floods a render log
            self._warned = True
            try:
                print(f"review: {msg} (further review warnings are silent)", file=sys.stderr, flush=True)
            except Exception:
                pass


def _jsonable(obj):
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return json.loads(json.dumps(obj, default=str))


class JobHook:
    """A render job of tools/blender/blender.py or tools/comfy/comfy.py on a review build: start, throttled progress
    (at most one event per `every` seconds), finish (job done + renders + build done) or failed."""

    def __init__(self, review, tool, every=2.0):
        self.rv, self.tool, self.every = review, tool, every
        self.key = f"{tool}-{time.strftime('%Y%m%d-%H%M%S')}"
        self.t0 = time.monotonic()
        self.last = 0.0

    def start(self, message):
        self.t0 = self.last = time.monotonic()
        return self.rv.job(self.tool, "running", 0.0, message=message, job=self.key)

    def update(self, x, message, force=False):
        now = time.monotonic()
        if not force and now - self.last < self.every:
            return False
        self.last = now
        return self.rv.job(self.tool, "running", x, message=message, job=self.key)

    def finish(self, renders=(), gpu_s=None, message=None, done=True):
        gpu = round(time.monotonic() - self.t0, 1) if gpu_s is None else gpu_s
        ok = self.rv.job(self.tool, "done", 1.0, gpu_s=gpu, message=message or "done", job=self.key)
        for r in renders or ():
            ok = self.rv.render(**r) and ok
        if done:
            ok = self.rv.done(message) and ok
        return ok

    def failed(self, message):
        gpu = round(time.monotonic() - self.t0, 1)
        self.rv.job(self.tool, "failed", gpu_s=gpu, message=str(message)[:500], job=self.key)
        return self.rv.fail(message)


def job_hook(build, tool, kind="render", **kw):
    """A JobHook for --review BUILD or $FILM_REVIEW_BUILD, else None (never raises)."""
    bid = (build or os.environ.get("FILM_REVIEW_BUILD") or "").strip()
    if not bid:
        return None
    try:
        rv = Review(bid, None, kind, status="rendering", **kw)
        return JobHook(rv, tool) if rv.enabled else None
    except Exception:
        return None
