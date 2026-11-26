"""Publish build/render progress to the Film Lab review server (tools/review/server.py). Standard library only.

Runs on the host (Windows or Linux, Python 3.10+) and inside Blender's Python 3.13:

    from client import Review                      # or load tools/review/client.py by path
    rv = Review("giot-demo", "Giọt", "demo", project="lab", expected_steps=10,
                tags={"engine": "blender", "look": "toon-ink", "episode": "q01t03", "subject": "giot"})
    rv.step("body", glb="out/step_01.glb", stats={"verts": 930})
    rv.step("concept 2/4", image="out/c2.png", meta={"prompt": "...", "seed": 42, "model": "qwen-image-2512",
                                                     "sampler_steps": 30, "seconds": 135.2, "item": 2, "items": 4})
    rv.progress(0.4, "frame 48/120")
    rv.job("blender", "running", progress=0.4, message="frame 48/120", step=48, steps=120)
    rv.render("beauty", video="out/beauty.mp4", frames=120, fps=24, duration=5.0)
    rv.done()                                       # or rv.fail("why")

Files given to step()/render() are hard-linked (else copied) into <media>/<build>/ (never overwritten: a different file
with the same name gets a -2, -3 ... suffix), then the event is POSTed to FILM_REVIEW_URL (default
http://127.0.0.1:8791/ingest/event). <media> is FILM_REVIEW_MEDIA, else out/_review/media of the lab's MAIN checkout
(main_checkout(): from a git worktree too, so client and server always agree; review.py up mounts the same folder).
A large PNG/WebP image is published as a JPEG preview (1280 px, q82, preview.py; needs Pillow, else the original goes).

Tags (tags.json, README "Chip"): {group: value or [values]}; values are normalised to slugs ("Q01T03" -> "q01t03");
an unknown group or value only prints a warning (never an error, never raises); a value that cannot be a slug is dropped.

Every POST carries the header X-Film-Review: 1 (the server refuses a POST without it: a web page cannot send it
cross-origin, so DNS rebinding cannot write). Text fields are scrubbed before they leave (an absolute path becomes its
base name; the server scrubs again): the dashboard is public.

Offline-safe: every call returns True/False and never raises into the caller. A request waits at most 2 s; after a
timeout the client stays quiet for 15 s (progress/job/step events are skipped; build, render, done and fail are
always tried) so a render never slows down because the review server is gone.

Env: FILM_REVIEW_URL (base URL of the ingest port; "off" disables publishing), FILM_REVIEW_MEDIA (media folder),
FILM_REVIEW_PREVIEW=off (publish images as they are).
"""
import functools
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(os.path.dirname(HERE))
DEFAULT_URL = "http://127.0.0.1:8791"
BUILD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
TIMEOUT = 2.0
QUIET_AFTER_TIMEOUT = 15.0
ALWAYS = ("build", "render", "done", "fail")
TEXT_FIELDS = {"title": 200, "label": 200, "message": 500, "project": 100, "engine": 60, "prompt": 2000,
               "model": 120, "workflow": 60}                                                # server.py MAX_STR
NAME_BAD = re.compile(r"[^A-Za-z0-9._-]+")
# The same as server.py (a test keeps them equal): tags, image metadata of a step, detail of a job.
TAG_GROUP = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
TAG_VALUE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
MAX_TAG_GROUPS = 16
MAX_TAG_VALUES = 8
STEP_META = {"prompt": str, "seed": int, "model": str, "sampler_steps": int, "seconds": float, "width": int,
             "height": int, "workflow": str, "item": int, "items": int, "chosen": bool}
JOB_DETAIL = {"label": str, "step": int, "steps": int, "item": int, "items": int, "eta": float}
RANGES = {"seed": (0, 2 ** 64 - 1), "sampler_steps": (1, 10000), "seconds": (0, 1e7), "width": (1, 65535),
          "height": (1, 65535), "item": (1, 100000), "items": (1, 100000), "step": (0, 10 ** 7),
          "steps": (1, 10 ** 7), "eta": (0, 1e8)}
TAGS_FILE = os.path.join(HERE, "tags.json")
PREVIEW_EXT = (".png", ".webp", ".tif", ".tiff", ".bmp")
PREVIEW_MIN = 256 * 1024          # smaller images go as they are

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


@functools.lru_cache(maxsize=8)
def main_checkout(path=LAB):
    """The main checkout of the git repository at `path`: a linked worktree (its .git is a file 'gitdir: <main>/.git/
    worktrees/<name>' with a 'commondir' inside) -> the checkout that owns <main>/.git, the same answer as
    `git rev-parse --git-common-dir` (asked only when the .git file cannot be read; never in Blender otherwise).
    Not a git tree, or a bare/submodule layout: `path` itself. The lab's out/ (media, pid files, ComfyUI work folder)
    lives in the main checkout."""
    path = os.path.abspath(path)
    dotgit = os.path.join(path, ".git")
    if os.path.isdir(dotgit):
        return path
    if not os.path.isfile(dotgit):
        return path
    common = None
    try:
        with open(dotgit, encoding="utf-8") as f:
            line = f.read().strip()
        if line.startswith("gitdir:"):
            gitdir = os.path.normpath(os.path.join(path, line[len("gitdir:"):].strip()))
            common = gitdir
            cf = os.path.join(gitdir, "commondir")
            if os.path.isfile(cf):
                with open(cf, encoding="utf-8") as f:
                    common = os.path.normpath(os.path.join(gitdir, f.read().strip()))
    except OSError:
        common = None
    if common is None:
        try:
            r = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=path, capture_output=True, timeout=10,
                               text=True)
            common = os.path.normpath(os.path.join(path, r.stdout.strip())) if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            common = None
    if common and os.path.basename(common).lower() == ".git":
        return os.path.dirname(common)
    return path


def lab_out(*parts):
    """<main checkout>/out/<parts>: the lab's working folder, the same from every worktree."""
    return os.path.join(main_checkout(), "out", *parts)


def default_media():
    return lab_out("_review", "media")


def media_root(path=None):
    return os.path.abspath(path or os.environ.get("FILM_REVIEW_MEDIA") or default_media())


# ------------------------------------------------------------------ tags
def fold(text):
    """Lower case ASCII: 'Phượng hoàng' -> 'phuong hoang' (accents and đ folded)."""
    text = str(text).replace("\u0111", "d").replace("\u0110", "D")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def slug(value):
    """A tag value as a slug: 'Q01T03' -> 'q01t03', 'Phượng hoàng' -> 'phuong-hoang'; None when nothing is left."""
    s = re.sub(r"[^a-z0-9._-]+", "-", fold(value).strip()).strip("-._")[:48].strip("-._")
    return s if s and TAG_VALUE.match(s) else None


def load_registry(media=None):
    """{group: {...}} of tags.json merged with <media>/_tags.json (project labels). {} when unreadable."""
    groups = {}
    for path in (TAGS_FILE, os.path.join(media_root(media), "_tags.json")):
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        for name, g in ((doc or {}).get("groups") or {}).items() if isinstance(doc, dict) else ():
            if isinstance(g, dict):
                cur = groups.setdefault(name, {"values": {}})
                cur["values"].update(g.get("values") or {})
                for k in ("open", "pattern"):
                    if k in g:
                        cur[k] = g[k]
    return groups


_TAG_WARNED = set()


def warn_once(msg):
    """One line on stderr, once per message (never an error, never raises)."""
    if msg in _TAG_WARNED or len(_TAG_WARNED) > 200:
        return
    _TAG_WARNED.add(msg)
    try:
        print(f"review: WARN {msg}", file=sys.stderr, flush=True)
    except Exception:
        pass


def tag_warn(msg):
    warn_once(f"tag {msg} (tools/review/tags.json)")


def normalize_tags(tags, registry=None):
    """{group: value | [values]} -> {group: [slugs]} for the server. Unknown groups and values are kept with a warning;
    a group or value that cannot be a slug is dropped with a warning; [] (or None) is kept: it clears that group.
    Never raises."""
    out = {}
    if not tags:
        return out
    if not isinstance(tags, dict):
        tag_warn(f"tags must be a dict, got {type(tags).__name__}: ignored")
        return out
    reg = load_registry() if registry is None else registry
    for group, vals in tags.items():
        g = re.sub(r"[^a-z0-9_]+", "_", fold(group).strip()).strip("_")[:24]
        if not g or not TAG_GROUP.match(g):
            tag_warn(f"group {str(group)[:30]!r} is not a valid group name: dropped")
            continue
        if reg and g not in reg:
            tag_warn(f"unknown group {g!r}")
        if len(out) >= MAX_TAG_GROUPS:
            tag_warn(f"more than {MAX_TAG_GROUPS} groups: {g!r} dropped")
            continue
        if vals is None:
            vals = []
        elif isinstance(vals, (str, int, float)):
            vals = [vals]
        clean = []
        for v in list(vals)[:MAX_TAG_VALUES * 2]:
            s = slug(v)
            if not s:
                tag_warn(f"{g}: value {str(v)[:30]!r} is not a valid slug: dropped")
                continue
            spec = reg.get(g) if reg else None
            if spec and not spec.get("open") and s not in (spec.get("values") or {}) and not (
                    spec.get("pattern") and re.match(spec["pattern"], s)):
                tag_warn(f"unknown value {g}={s!r}")
            if s not in clean:
                clean.append(s)
        if vals and not clean:          # every value was dropped: keep the group as it is (an explicit [] clears it)
            continue
        if len(clean) > MAX_TAG_VALUES:
            tag_warn(f"{g}: more than {MAX_TAG_VALUES} values, the rest dropped")
        out[g] = clean[:MAX_TAG_VALUES]
    return out


def clean_fields(given, schema, what):
    """Optional typed fields (STEP_META, JOB_DETAIL) inside the server's ranges; anything else dropped with a warning
    (the server would refuse the whole event)."""
    out = {}
    for k, v in (given or {}).items():
        typ = schema.get(k)
        if typ is None:
            warn_once(f"{what}: unknown field {k!r} dropped")
            continue
        if v is None:
            continue
        try:
            if typ is bool:
                v = bool(v)
            elif typ is int:
                if isinstance(v, bool) or int(v) != float(v):
                    raise ValueError
                v = int(v)
            elif typ is float:
                v = float(v)
                if v != v or v in (float("inf"), float("-inf")):
                    raise ValueError
            else:
                v = str(v)
        except (TypeError, ValueError, OverflowError):
            warn_once(f"{what}: {k}={str(v)[:20]!r} is not a {typ.__name__}: dropped")
            continue
        if k in RANGES and not RANGES[k][0] <= v <= RANGES[k][1]:
            warn_once(f"{what}: {k}={v!r} out of range: dropped")
            continue
        out[k] = v
    if "item" in out and "items" in out and out["item"] > out["items"]:
        out.pop("item")
    if "step" in out and "steps" in out and out["step"] > out["steps"]:
        out.pop("step")
    return out


def _load_preview():
    try:
        spec = importlib.util.spec_from_file_location("film_review_preview", os.path.join(HERE, "preview.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


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
                 media=None, status=None, restart=False, announce=True, tags=None, append=False, preview=None):
        self.build = str(build_id)
        self.title = title             # None: not sent (an existing build keeps its title; a new one is named by its id)
        self.kind = kind
        self.project = project
        self.expected_steps = expected_steps
        self.status = status
        self.restart = bool(restart)
        self.url = ingest_url(url)
        self.media = media_root(media)
        # tags: sent with every announce; given groups replace the build's, other groups stay (server merge_tags)
        self.tags = normalize_tags(tags, load_registry(self.media)) if tags else None
        self.append = bool(append)     # steps carry no n: the server numbers them (a watcher that restarts)
        env_preview = (os.environ.get("FILM_REVIEW_PREVIEW") or "").strip().lower() not in ("off", "0", "no", "false")
        self.preview = env_preview if preview is None else bool(preview)
        self._preview_note = False
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
        if self.tags is not None:
            ev["tags"] = self.tags
        ok = self._post(ev)
        self._announced = self._announced or ok
        return ok

    def media_dir(self):
        """<media>/<build>/ (created): write files straight here to skip the copy."""
        d = os.path.join(self.media, self.build)
        os.makedirs(d, exist_ok=True)
        return d

    def step(self, label, glb=None, image=None, stats=None, n=None, *, meta=None, preview=None):
        """One step: a GLB and/or an image (+ stats, + image metadata `meta`: prompt, seed, model, sampler_steps,
        seconds, width, height, workflow, item, items, chosen). preview: publish a large image as a JPEG preview
        (default: on unless FILM_REVIEW_PREVIEW=off)."""
        try:
            self.n = int(n) if n else self.n + 1
            ev = {"type": "step", "label": str(label)}
            if not self.append or n:
                ev["n"] = self.n
            if glb:
                rel = self.publish_file(glb)
                if rel:
                    ev["glb"] = rel
            if image:
                rel = self.publish_image(image, preview)
                if rel:
                    ev["image"] = rel
            if stats:
                ev["stats"] = _jsonable(stats)
            ev.update(clean_fields(meta, STEP_META, "step meta"))
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
               seconds_per_frame=None, preview=None):
        try:
            ev = {"type": "render", "label": str(label)}
            for key, path in (("video", video), ("image", image)):
                rel = (self.publish_image(path, preview) if key == "image" else self.publish_file(path)) if path else None
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

    def job(self, tool, status, progress=None, gpu_s=None, message=None, job=None, **detail):
        """A render/generation job of the build. detail: label (workflow name, e.g. "qwen-t2i"), step/steps (sampler
        step i/n), item/items (image k/N of a batch), eta (seconds left)."""
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
            ev.update(clean_fields(detail, JOB_DETAIL, "job"))
            return self._post(ev)
        except Exception as e:
            return self._failed(e)

    def done(self, message=None):
        return self._post({"type": "done", **({"message": str(message)} if message else {})})

    def fail(self, msg=None):
        return self._post({"type": "fail", "message": str(msg or "failed")[:500]})

    # ------------------------------------------------------------------ files
    def publish_image(self, path, preview=None):
        """publish_file() of an image; a large PNG/WebP/TIFF/BMP goes as a JPEG preview (1280 px, q82) when Pillow
        is importable (the original is published otherwise, with one note on stderr)."""
        want = self.preview if preview is None else bool(preview)
        try:
            big = os.path.splitext(str(path))[1].lower() in PREVIEW_EXT and os.path.getsize(path) >= PREVIEW_MIN
        except OSError:
            big = False
        if want and big:
            mod = _load_preview()
            tmp = tempfile.mkdtemp(prefix="review-preview-")
            try:
                out = os.path.join(tmp, os.path.splitext(os.path.basename(str(path)))[0] + ".jpg")
                done = mod.jpeg_preview(str(path), out) if mod else None
                if done:
                    return self.publish_file(done)
            except Exception:
                pass
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            if not self._preview_note:
                self._preview_note = True
                try:
                    print("review: Pillow not importable: images are published as they are (no JPEG preview)",
                          file=sys.stderr, flush=True)
                except Exception:
                    pass
        return self.publish_file(path)

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
    """A render/generation job of tools/blender/blender.py or tools/comfy/comfy.py on a review build: start, throttled
    progress (at most one event per `every` seconds), images as steps (image()), finish (job done + renders + build
    done) or failed. label: the workflow name shown on the dashboard's ComfyUI card (e.g. "qwen-t2i")."""

    def __init__(self, review, tool, every=2.0, label=None):
        self.rv, self.tool, self.every, self.label = review, tool, every, label
        self.key = f"{tool}-{time.strftime('%Y%m%d-%H%M%S')}"
        self.t0 = time.monotonic()
        self.last = 0.0

    def _detail(self, detail):
        return dict({"label": self.label} if self.label else {}, **detail)

    def start(self, message, **detail):
        self.t0 = self.last = time.monotonic()
        return self.rv.job(self.tool, "running", 0.0, message=message, job=self.key, **self._detail(detail))

    def update(self, x, message, force=False, **detail):
        """detail: step/steps (sampler step i/n), item/items (image k/N), eta (s). Throttled unless force."""
        now = time.monotonic()
        if not force and now - self.last < self.every:
            return False
        self.last = now
        return self.rv.job(self.tool, "running", x, message=message, job=self.key, **self._detail(detail))

    def image(self, path, label=None, **meta):
        """One output image of the job as a step of the build (the gallery). meta: prompt, seed, model,
        sampler_steps, seconds, width, height, item, items (workflow defaults to the hook's label)."""
        if self.label and "workflow" not in meta:
            meta["workflow"] = self.label
        return self.rv.step(label or os.path.splitext(os.path.basename(str(path)))[0], image=path, meta=meta)

    def finish(self, renders=(), gpu_s=None, message=None, done=True):
        gpu = round(time.monotonic() - self.t0, 1) if gpu_s is None else gpu_s
        ok = self.rv.job(self.tool, "done", 1.0, gpu_s=gpu, message=message or "done", job=self.key,
                         **self._detail({}))
        for r in renders or ():
            ok = self.rv.render(**r) and ok
        if done:
            ok = self.rv.done(message) and ok
        return ok

    def failed(self, message):
        gpu = round(time.monotonic() - self.t0, 1)
        self.rv.job(self.tool, "failed", gpu_s=gpu, message=str(message)[:500], job=self.key, **self._detail({}))
        return self.rv.fail(message)


def job_hook(build, tool, kind="render", title=None, tags=None, label=None, **kw):
    """A JobHook for --review BUILD or $FILM_REVIEW_BUILD, else None (never raises). title/tags: as Review();
    label: the workflow name (JobHook.label)."""
    bid = (build or os.environ.get("FILM_REVIEW_BUILD") or "").strip()
    if not bid:
        return None
    try:
        rv = Review(bid, title, kind, status="rendering", tags=tags, **kw)
        return JobHook(rv, tool, label=label) if rv.enabled else None
    except Exception:
        return None
