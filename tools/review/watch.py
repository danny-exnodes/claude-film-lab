#!/usr/bin/env python3
"""Watch a project's work folders and publish work in progress to the review dashboard (tools/review/README.md).

  python tools/review/watch.py <project> [--episode q01t03] [--dir characters --dir locations ...] [--interval 5]
                               [--since 12] [--blender PATH] [--no-glb] [--max-glb-mb 60] [--decimate R] [--once]

Agents write files; nobody calls the review client. This process scans <main checkout>/out/<project>/ every --interval
seconds (`review.py watch <project>` runs it detached, pid in out/_review/watch-<project>.pid):
  characters/<slug>/, locations/<slug>/   one build per slug (<project>-<slug>, kind model): every new or changed
                                          image (png/jpg/webp, any depth) is a step (a JPEG preview, 1280 px q82, when
                                          Pillow is importable); an mp4 is a render; when <slug>.blend (or
                                          <slug>_vNN.blend) has been saved and left alone for 20 s, headless Blender
                                          (CPU, no render) exports it as GLB (bpy_export_glb.py) -> a GLB step, so
                                          "Bản vẽ dựng" and "Xem model" follow the model live
  <episode>/renders3d/<shot>*/            one build per shot (<project>-<episode>-s21, kind render): images are steps,
                                          mp4s are renders
Frame sequences are skipped: folders named beauty, frames, passes, depth, normal(s), mask(s), control*, canny, pose...,
and any folder with 8 or more numbered frames (0001.png); a folder with fewer numbered frames may be a sequence that is
still being rendered: its numbered frames wait until the folder has not changed for SEQ_SETTLE seconds. A GLB bigger
than --max-glb-mb is exported again with a Decimate ratio that fits (--decimate R forces one). Tags of each build:
kind, engine blender, project, episode, subject (the slug) or shot, stage lookdev (characters/locations).
State: out/_review/watch-<project>.json (what was published; a restart publishes nothing twice). First run: only files
changed in the last --since hours (default 12) are published, older ones are marked as seen. A file is published once
two consecutive scans saw the same size and mtime and that mtime is 3 s old (a .blend: 20 s); a publish that the server
did not take is tried again on the next scan. Only folders and files inside out/<project>/ are read: --dir must be
relative without '..', and symlinks, junctions and anything whose real path leads outside are skipped.
Offline-safe like every publisher: without a server it keeps scanning and retries.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import client  # noqa: E402

EXPORT_SCRIPT = os.path.join(HERE, "bpy_export_glb.py")
BLENDER_PY = os.path.join(LAB, "tools", "blender", "blender.py")
IMAGES = (".png", ".jpg", ".jpeg", ".webp")
VIDEOS = (".mp4", ".m4v", ".webm", ".mov")
SKIP_DIRS = re.compile(r"^(?:beauty|frames?|passes|pass|depth|z|normals?|masks?|matte|control\w*|canny|lineart|"
                       r"openpose|pose|cryptomatte|ao|mist|__pycache__|\..*)$", re.I)
FRAME = re.compile(r"(?:^|[_.-])\d{3,6}\.(?:png|jpe?g|exr|tiff?|webp)$", re.I)
SEQUENCE_MIN = 8
SETTLE = 3.0                      # seconds since the last write before an image/video is published (and the same
                                  # size + mtime on two consecutive scans)
SEQ_SETTLE = 180.0                # a folder with a few numbered frames: how long it must stay unchanged (a sequence
                                  # still rendering is skipped once it has SEQUENCE_MIN frames)
BLEND_SETTLE = 20.0               # ... before a saved .blend is exported
DEFAULT_DIRS = ("characters", "locations")
MAX_PER_SCAN = 40                 # publishes per scan (a big first run is spread over a few scans)
EXPORT_TIMEOUT = 1800


def say(msg):
    try:
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} watch: {msg}", flush=True)
    except Exception:
        pass


def build_id(*parts):
    """'son-hai-kinh', 'phuong-hoang' -> 'son-hai-kinh-phuong-hoang' (a valid build id, at most 64 characters)."""
    raw = "-".join(re.sub(r"[^A-Za-z0-9._-]+", "-", p).strip("-._") for p in parts if p)
    raw = re.sub(r"-{2,}", "-", raw).strip("-._")[:64].rstrip("-._")
    return raw if client.BUILD_ID.match(raw or "") else None


def bad_dir(d):
    """Why a watched folder is refused (absolute, a drive, '..'), else None: it must stay inside out/<project>/."""
    s = str(d or "").strip()
    if not s or os.path.isabs(s) or re.match(r"^(?:[A-Za-z]:|[\\/])", s):
        return "must be a folder relative to out/<project>/"
    if ".." in re.split(r"[\\/]+", s):
        return "must not contain '..'"
    return None


def is_link(path):
    """A symlink or a Windows junction (never followed: it may lead out of the project folder)."""
    try:
        if os.path.islink(path):
            return True
        isj = getattr(os.path, "isjunction", None)
        return bool(isj and isj(path))
    except OSError:
        return True


def find_blender(explicit=None):
    """--blender, else tools/blender/blender.py find() (FILM_BLENDER, PATH, Program Files), else None."""
    if explicit:
        return explicit if os.path.isfile(explicit) or shutil.which(explicit) else None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("film_blender_for_watch", BLENDER_PY)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        path, _ = mod.find()
        return path
    except Exception:
        return shutil.which("blender")


def mp4_duration(path):
    try:
        import review
        return review.mp4_duration(path)
    except Exception:
        return None


def glb_stats(path):
    try:
        import review
        return review.glb_stats(path) or {}
    except Exception:
        return {}


class Unit:
    """One build: a slug folder (model) or a shot of renders3d (render)."""

    def __init__(self, bid, title, kind, root, folders, tags, slug=None):
        self.bid, self.title, self.kind, self.root, self.folders = bid, title, kind, root, folders
        self.tags, self.slug = tags, slug


class Watcher:
    def __init__(self, project, *, episode=None, dirs=None, out_root=None, state_file=None, make_review=None,
                 blender=None, glb=True, max_glb_mb=60.0, decimate=None, since=12.0, clock=time.time,
                 runner=subprocess.run, registry=None):
        self.project, self.episode = project, episode
        self.root = os.path.abspath(out_root or client.lab_out(project))
        self.real_root = os.path.realpath(self.root)
        self.dirs = list(dirs) if dirs else list(DEFAULT_DIRS) + ([os.path.join(episode, "renders3d")] if episode
                                                                  else ["*/renders3d"])
        for d in [d for d in self.dirs if bad_dir(d)]:
            say(f"--dir {d!r} skipped: {bad_dir(d)}")
            self.dirs.remove(d)
        self.state_file = state_file or client.lab_out("_review", f"watch-{project}.json")
        self.make_review = make_review or (lambda bid, title, kind, tags: client.Review(
            bid, title, kind, project=project, tags=tags, append=True))
        self.blender_arg, self.blender = blender, None
        self.glb, self.max_glb_mb, self.decimate = glb, max_glb_mb, decimate
        self.since, self.clock, self.runner = since, clock, runner
        self.labels = ((registry if registry is not None else client.load_registry()).get("subject") or {}).get(
            "values") or {}
        self.reviews = {}
        self.prev = {}                 # path -> (size, mtime) of the previous scan: a file must look the same twice
        self.prev_seq = {}             # folder -> (frames, newest mtime) of the previous scan (a possible sequence)
        self.state = self.load()

    # ------------------------------------------------------------------ state
    def load(self):
        try:
            with open(self.state_file, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("files"), dict):
                d.setdefault("blends", {})
                d["first"] = False
                return d
        except (OSError, ValueError):
            pass
        return {"files": {}, "blends": {}, "first": True}

    def save(self):
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        tmp = self.state_file + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in self.state.items() if k != "first"}, f)
        os.replace(tmp, self.state_file)

    # ------------------------------------------------------------------ what to watch
    def inside(self, path):
        """True when path is no link and its real path stays under the real out/<project>/ folder."""
        if is_link(path):
            return False
        real = os.path.realpath(path)
        return real == self.real_root or real.startswith(self.real_root.rstrip(os.sep) + os.sep)

    def watched_dirs(self):
        out = []
        for d in self.dirs:
            if "*" in d:
                import glob
                found = sorted(p for p in glob.glob(os.path.join(self.root, d)) if os.path.isdir(p))
            else:
                found = [os.path.join(self.root, d)] if os.path.isdir(os.path.join(self.root, d)) else []
            out += [p for p in found if self.inside(p)]
        return out

    def units(self):
        units = []
        for d in self.watched_dirs():
            try:
                subs = sorted(e for e in os.listdir(d) if not e.startswith(".") and os.path.isdir(os.path.join(d, e))
                              and self.inside(os.path.join(d, e)))
            except OSError:
                continue
            if os.path.basename(d) == "renders3d":
                episode = os.path.basename(os.path.dirname(d))
                shots = {}
                for e in subs:
                    m = re.match(r"(s\d{2,3})(?![0-9])", e, re.I)
                    shots.setdefault(m.group(1).lower() if m else e, []).append(os.path.join(d, e))
                for shot, folders in shots.items():
                    bid = build_id(self.project, episode, shot)
                    if not bid:
                        continue
                    tags = {"kind": "render", "engine": "blender", "project": self.project, "episode": episode}
                    if re.fullmatch(r"s\d{2,3}", shot):
                        tags["shot"] = shot
                    units.append(Unit(bid, f"{shot.upper()} · renders3d", "render", d, folders, tags))
            else:
                for slug in subs:
                    bid = build_id(self.project, slug)
                    if not bid:
                        continue
                    tags = {"kind": "model", "engine": "blender", "project": self.project, "subject": slug,
                            "stage": "lookdev"}
                    if self.episode:
                        tags["episode"] = self.episode
                    title = self.labels.get(slug) or slug.replace("-", " ").replace("_", " ").capitalize()
                    units.append(Unit(bid, title, "model", d, [os.path.join(d, slug)], tags, slug=slug))
        return units

    def files(self, folder):
        """(path, kind, seq) of the images and videos under folder, frame sequences and pass folders left out (and
        links, and whatever leads outside out/<project>/). seq: (folder, frames, newest mtime) for a numbered frame
        in a folder with fewer than SEQUENCE_MIN of them (it may be a sequence still being rendered), else None."""
        out = []
        if not self.inside(folder):
            return out
        for cur, dirs, names in os.walk(folder):
            dirs[:] = sorted(x for x in dirs if not SKIP_DIRS.match(x) and self.inside(os.path.join(cur, x)))
            frames = [n for n in names if FRAME.search(n)]
            if len(frames) >= SEQUENCE_MIN:
                continue                                         # a frame sequence: its images are not steps
            seq = None
            if frames:
                newest = 0.0
                for n in frames:
                    try:
                        newest = max(newest, os.stat(os.path.join(cur, n)).st_mtime)
                    except OSError:
                        pass
                seq = (cur, len(frames), newest)
            for n in sorted(names):
                ext = os.path.splitext(n)[1].lower()
                kind = "image" if ext in IMAGES else "video" if ext in VIDEOS else None
                path = os.path.join(cur, n)
                if kind and self.inside(path):
                    out.append((path, kind, seq if n in frames else None))
        return out

    def blends(self, unit):
        """The newest <slug>.blend / <slug>_vNN.blend directly in the slug folder, or None."""
        if not unit.slug:
            return None
        folder = unit.folders[0]
        pat = re.compile(r"^" + re.escape(unit.slug) + r"(?:_v\d+)?\.blend$", re.I)
        try:
            found = [os.path.join(folder, n) for n in os.listdir(folder) if pat.match(n)]
        except OSError:
            return None
        found = [p for p in found if os.path.isfile(p)]
        return max(found, key=lambda p: os.path.getmtime(p)) if found else None

    # ------------------------------------------------------------------ one scan
    def review(self, unit):
        rv = self.reviews.get(unit.bid)
        if rv is None:
            rv = self.reviews[unit.bid] = self.make_review(unit.bid, unit.title, unit.kind, unit.tags)
        return rv

    def rel(self, path):
        return os.path.relpath(path, self.root).replace("\\", "/")

    def scan(self):
        """One pass over every unit. -> {"published": n, "exported": n, "pending": n}. A new or changed file is
        published on the scan after the one that first saw it with this size and mtime (settled)."""
        now = self.clock()
        first = self.state.get("first", False)          # cleared only once a scan's state is saved
        cutoff = now - self.since * 3600 if first else None
        files, budget = self.state["files"], MAX_PER_SCAN
        report = {"published": 0, "exported": 0, "pending": 0}
        seen, seen_seq = {}, {}
        for unit in self.units():
            posted = 0
            for folder in unit.folders:
                for path, kind, seq in self.files(folder):
                    try:
                        st = os.stat(path)
                    except OSError:
                        continue
                    key = self.rel(path)
                    sig = [st.st_mtime, st.st_size]
                    seen[key] = (st.st_size, st.st_mtime)
                    if seq:
                        seen_seq[seq[0]] = seq[1:]
                    old = files.get(key)
                    if old and old[:2] == sig and old[2]:
                        continue                                  # published already
                    if cutoff is not None and st.st_mtime < cutoff:
                        files[key] = sig + [True]                 # first run: old work is only marked as seen
                        continue
                    if now - st.st_mtime < SETTLE or self.prev.get(key) != seen[key]:
                        report["pending"] += 1                    # still written, or not seen like this before
                        continue
                    if seq and (self.prev_seq.get(seq[0]) != seq[1:] or now - seq[2] < SEQ_SETTLE):
                        report["pending"] += 1                    # maybe a sequence that is still rendering
                        continue
                    if budget <= 0:
                        report["pending"] += 1
                        continue
                    budget -= 1
                    ok = self.publish(unit, path, kind, folder)
                    files[key] = sig + [bool(ok)]
                    if ok:
                        posted += 1
                    else:
                        report["pending"] += 1
            if self.glb and unit.slug:
                done = self.export_if_saved(unit, now, first)
                report["exported"] += done
                posted += done
            if posted:
                report["published"] += posted
                self.review(unit).done(f"{posted} file mới")
        self.prev, self.prev_seq = seen, seen_seq
        self.save()
        self.state.pop("first", None)
        return report

    def publish(self, unit, path, kind, folder):
        rv = self.review(unit)
        base = unit.folders[0] if unit.slug else os.path.dirname(folder)
        label = os.path.splitext(os.path.relpath(path, base).replace("\\", "/"))[0][:200]
        if kind == "image":
            return rv.step(label, image=path)
        return rv.render(label, video=path, duration=mp4_duration(path), engine="blender")

    # ------------------------------------------------------------------ .blend -> GLB
    def export_if_saved(self, unit, now, first):
        blend = self.blends(unit)
        if not blend:
            return 0
        try:
            st = os.stat(blend)
        except OSError:
            return 0
        key = self.rel(blend)
        rec = self.state["blends"].get(key) or {}
        if rec.get("mtime") == st.st_mtime and rec.get("posted"):
            return 0
        if first and st.st_mtime < now - self.since * 3600:
            self.state["blends"][key] = {"mtime": st.st_mtime, "posted": True}
            return 0
        if now - st.st_mtime < BLEND_SETTLE:
            return 0
        rv = self.review(unit)
        if rec.get("mtime") != st.st_mtime or not rec.get("glb") or not os.path.isfile(rec["glb"]):
            glb = self.export(unit, blend, rv)
            if not glb:
                self.state["blends"][key] = {"mtime": st.st_mtime, "posted": True, "failed": True}
                return 0
            rec = {"mtime": st.st_mtime, "glb": glb, "posted": False}
            self.state["blends"][key] = rec
        stats = dict(glb_stats(rec["glb"]), glb_bytes=os.path.getsize(rec["glb"]))
        if os.path.isfile(rec["glb"] + ".json"):
            try:
                with open(rec["glb"] + ".json", encoding="utf-8") as f:
                    stats.update({k: v for k, v in json.load(f).items() if k in ("verts", "faces", "decimate")})
            except (OSError, ValueError):
                pass
        ok = rv.step(f"{os.path.basename(blend)} · GLB", glb=rec["glb"], stats=stats)
        rec["posted"] = bool(ok)
        return 1 if ok else 0

    def export(self, unit, blend, rv):
        """Headless Blender exports blend into the build's media folder (no copy). -> the GLB path or None."""
        if self.blender is None:
            self.blender = find_blender(self.blender_arg) or ""
        if not self.blender:
            say(f"no Blender found (FILM_BLENDER or --blender): {os.path.basename(blend)} not exported")
            return None
        folder = rv.media_dir()
        stem = f"{unit.slug}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(self.clock()))}"
        key = f"watch-glb-{stem}"[:100]
        rv.job("blender", "running", 0.0, message=f"xuất GLB {os.path.basename(blend)}", job=key)
        t0 = time.monotonic()
        ratio = self.decimate
        out = self.run_export(blend, os.path.join(folder, stem + ".glb"), ratio)
        if out and ratio is None and self.max_glb_mb and os.path.getsize(out) > self.max_glb_mb * 2 ** 20:
            size_mb = os.path.getsize(out) / 2 ** 20
            ratio = max(0.05, min(0.9, self.max_glb_mb / size_mb * 0.85))
            say(f"{os.path.basename(out)} is {size_mb:.0f} MB > {self.max_glb_mb:g} MB: decimating to {ratio:.2f}")
            small = self.run_export(blend, os.path.join(folder, stem + "-lite.glb"), ratio)
            if small:
                for p in (out, out + ".json"):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
                out = small
        gpu = round(time.monotonic() - t0, 1)
        if out:
            rv.job("blender", "done", 1.0, gpu_s=gpu, message="GLB xong", job=key)
            say(f"exported {os.path.basename(blend)} -> {os.path.basename(out)} ({os.path.getsize(out) / 2 ** 20:.1f} MB)")
        else:
            rv.job("blender", "failed", gpu_s=gpu, message="xuất GLB lỗi", job=key)   # a fixed category: public page
        return out

    def run_export(self, blend, out, ratio):
        cmd = [self.blender, "-b", "--factory-startup", blend, "--python-exit-code", "1", "-P", EXPORT_SCRIPT, "--",
               out]
        if ratio is not None and ratio < 1:
            cmd += ["--decimate", f"{ratio:.3f}"]
        try:
            r = self.runner(cmd, capture_output=True, timeout=EXPORT_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as e:
            say(f"Blender export failed ({type(e).__name__}: {e})")
            return None
        if r.returncode or not os.path.isfile(out):
            tail = (r.stderr or b"")[-600:]
            say(f"Blender export failed (exit {r.returncode}): "
                f"{tail.decode('utf-8', 'replace') if isinstance(tail, bytes) else tail}")
            return None
        return out

    def run(self, interval):
        say(f"watching {self.root} ({', '.join(self.dirs)}) every {interval:g} s; state {self.state_file}")
        while True:
            t0 = time.monotonic()
            try:
                r = self.scan()
                if r["published"] or r["exported"]:
                    say(f"published {r['published']} (GLB {r['exported']}); {r['pending']} waiting")
            except Exception as e:              # never exit on one bad scan
                say(f"scan failed: {type(e).__name__}: {e}")
            time.sleep(max(0.5, interval - (time.monotonic() - t0)))


def main(argv=None):
    p = argparse.ArgumentParser(prog="watch.py", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("project")
    p.add_argument("--episode", default=None)
    p.add_argument("--dir", action="append", default=None,
                   help="folder relative to out/<project>/ (repeatable; no absolute path, no '..')")
    p.add_argument("--interval", type=float, default=5.0)
    p.add_argument("--since", type=float, default=12.0)
    p.add_argument("--blender", default=None)
    p.add_argument("--no-glb", action="store_true")
    p.add_argument("--max-glb-mb", type=float, default=60.0)
    p.add_argument("--decimate", type=float, default=None)
    p.add_argument("--once", action="store_true")
    a = p.parse_args(argv)
    if not client.BUILD_ID.match(a.project) or (a.episode and not client.BUILD_ID.match(a.episode)):
        print("watch: refused: project/episode must be folder names ([A-Za-z0-9][A-Za-z0-9._-]*)", file=sys.stderr)
        return 2
    for d in a.dir or []:
        if bad_dir(d):
            print(f"watch: refused: --dir {d!r} {bad_dir(d)}", file=sys.stderr)
            return 2
    if a.decimate is not None and not 0.01 <= a.decimate <= 1:
        print("watch: refused: --decimate must be 0.01..1", file=sys.stderr)
        return 2
    w = Watcher(a.project, episode=a.episode, dirs=a.dir, blender=a.blender, glb=not a.no_glb,
                max_glb_mb=a.max_glb_mb, decimate=a.decimate, since=a.since)
    if not os.path.isdir(w.root):
        print(f"watch: refused: no folder {w.root}", file=sys.stderr)
        return 2
    if a.once:                         # two scans: a file is published once it looked the same twice
        r1 = w.scan()
        time.sleep(SETTLE)
        r = w.scan()
        r["published"] += r1["published"]
        r["exported"] += r1["exported"]
        say(f"published {r['published']} (GLB {r['exported']}); {r['pending']} waiting")
        return 0
    try:
        w.run(max(1.0, a.interval))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
