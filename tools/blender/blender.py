#!/usr/bin/env python3
"""Local 3D renders with Blender 5.x headless (method: blender). Free: no API, no ledger cost; runs on the owner's PC.

  python tools/blender/blender.py find                                   # path + version (1 = not found, 3 = broken)
  python tools/blender/blender.py check <shot3d.json> [--preview]        # validate the spec only, no Blender
  python tools/blender/blender.py render <shot3d.json> --out <dir> [--frames A:B] [--preview] [--engine eevee|cycles]
                                         [--passes depth normal line mask | none] [--look L] [--samples N] [--no-mp4]
  python tools/blender/blender.py still <shot3d.json> --frame N --out <png> [--size WxH] [--preview] [--look L]
  python tools/blender/blender.py turntable <asset.glb|file.blend[#Collection]|preset:id> --out <dir> [--look L]
                                         [--frames 72 | --seconds 4] [--samples N] [--fill 0.7] [--front DEG]
                                         [--stills front,34,side,head|none] [--backdrop cyc|none] [--head-bone head]
                                         [--lens 50] [--fit M] [--hdri F.hdr] [--size WxH] [--preview]
        the asset turns once in place (own size, or --fit metres) in front of a fixed camera framed on its bounding
        box (--fill of the frame height), seamless cyc behind; -> beauty/ + beauty.mp4 + still_<view>.png + render.json
        (look realistic: Cycles, three studio lamps on a grey sky, or --hdri)
  python tools/blender/blender.py keyframes <shot3d.json> --out <dir> [--size 1344x768] [--look L]
  python tools/blender/blender.py lookbook --out <dir> [--spec S] [--frame N] [--size 960x540]
  python tools/blender/blender.py mesh-prep <raw.glb> --out <dir> [--concept concept.png] [--voxel auto|SIZE|0]
                                         [--quad-faces 20000 | --decimate N] [--min-island 0.002] [--no-turntable]
                                         [--stills front,34,side] [--frames N] [--front DEG] [--preview] [--samples N]
        an image-to-3D blank (tools/comfy/comfy.py run hunyuan3d) -> a sculpt base: mesh report of the raw GLB (holes,
        non-manifold edges, loose parts), voxel remesh + loose debris removed + QuadriFlow quads (or decimate) ->
        <name>_prep.glb + <name>_prep.blend (raw mesh kept hidden as bake source) + prep.json, a clay turntable of it
        (turntable/), silhouettes from the concept's view and their IoU against --concept, compare.png,
        mesh_report.json. Blender runs (meshprep.py, then the turntable) under one GPU turn.
  python tools/blender/blender.py mesh-check <mesh.glb> [--concept concept.png] [--view front|side|back]
                                         [--sheet compare.png] [--json report.json]
        the same mesh report and silhouette IoU without Blender or GPU (numpy + Pillow, tools/blender/meshcheck.py)

Every render command (and mesh-prep) also takes --engine, --dry-run (print the Blender command, render nothing) and --timeout S.
render, turntable and keyframes take --review BUILD (or env FILM_REVIEW_BUILD): publish the job's start, progress
(at most every 2 s) and end, with the mp4/keyframes as renders, to the review server (tools/review/; offline-safe).
--out must not exist or be an empty folder (still: the png must not exist): nothing is ever overwritten.
--preview = 960 wide (the spec's aspect), 12 fps, low samples. --size WxH renders another frame size with the same
vertical field of view (the camera's sensor fit, not a crop): keyframes default to 1344x768 (the local video model's
canvas; 864x480 for drafts).

Blender: $FILM_BLENDER, else `blender` on PATH, else the newest C:\\Program Files\\Blender Foundation\\Blender */blender.exe,
else /Applications/Blender.app/Contents/MacOS/Blender, else /usr/bin/blender. It runs as
  blender -b --factory-startup --python-exit-code 1 -P tools/blender/scene.py -- --spec S --out D [...]
EEVEE needs a GPU session (a logged-in desktop); when an EEVEE render fails after the scene was built and wrote no frame,
the render runs again with Cycles (OptiX, CUDA, else CPU) and render.json says so. beauty.mp4: ffmpeg when it is on PATH,
else Blender's own FFmpeg encoder (--no-mp4 skips it).

GPU queue: render, still, turntable, keyframes and lookbook hold the lab's GPU lock (tools/gpu_run.py) while Blender
runs, waiting while another job holds it (never for --dry-run, check, find). FILM_GPU_WAIT=S gives up after S seconds
(exit 2, nothing rendered); FILM_GPU_QUEUE=0 turns the queue off.

Exit codes: 0 ok · 1 Blender not found or the render failed · 2 refused before rendering (bad spec, arguments, --out,
the GPU stayed busy) · 3 (find only) a Blender was found but `blender --version` failed or printed no version.
"""
import argparse
import contextlib
import glob
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE = os.path.join(HERE, "scene.py")
MESHPREP = os.path.join(HERE, "meshprep.py")
DEMO = os.path.join(HERE, "demo")
LOOKBOOK_SPEC = os.path.join(DEMO, "lookbook.json")
KEYFRAME_SIZE = "1344x768"
BROKEN = 3          # `find`: a Blender exists but `--version` fails (tools/doctor.sh WARNs; 1 = none found)
REVIEW_CLIENT = os.path.join(os.path.dirname(HERE), "review", "client.py")
FRAME_LINE = re.compile(r"^frame (\d+) \((\d+)/(\d+)\)")


def _load_spec():
    sp = importlib.util.spec_from_file_location("film_blender_spec", os.path.join(HERE, "spec.py"))
    mod = importlib.util.module_from_spec(sp)
    sys.modules.setdefault(sp.name, mod)
    sp.loader.exec_module(mod)
    return mod


spec = _load_spec()


def _load_gpu():
    """tools/gpu_run.py: the lab-wide GPU lock (one GPU job at a time)."""
    sp = importlib.util.spec_from_file_location("film_gpu_run", os.path.join(os.path.dirname(HERE), "gpu_run.py"))
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    return mod


gpu = _load_gpu()


class Refused(Exception):
    """Exit 2: nothing was rendered."""


class Failed(Exception):
    """Exit 1."""


class Stopped(BaseException):
    """SIGTERM/SIGHUP (Ctrl+Break on Windows) for blender.py: Blender is killed before the GPU lock is released."""

    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


CLAIM = ".film-claim"          # in an --out folder while a job owns it (from before the GPU wait to the end)


# ------------------------------------------------------------------ finding Blender
def _version_key(path):
    """(5, 3) from .../Blender 5.3/blender.exe, so 5.10 sorts after 5.9."""
    folder = os.path.basename(os.path.dirname(path.replace("\\", "/")))
    m = re.search(r"(\d+(?:\.\d+)*)", folder)
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def candidates(env=None, system=None, which=shutil.which):
    """[(path, source)] in search order (FILM_BLENDER is handled by find())."""
    env = os.environ if env is None else env
    system = system or platform.system()
    out = []
    w = which("blender")
    if w:
        out.append((w, "PATH"))
    if system == "Windows":
        pf = env.get("ProgramFiles") or r"C:\Program Files"
        found = glob.glob(os.path.join(pf, "Blender Foundation", "Blender*", "blender.exe"))
        for p in sorted(found, key=_version_key, reverse=True):
            out.append((p, "Program Files"))
    if system == "Darwin":
        out.append(("/Applications/Blender.app/Contents/MacOS/Blender", "Applications"))
    out.append(("/usr/bin/blender", "/usr/bin"))
    return out


def find(env=None, system=None, which=shutil.which):
    """-> (path, source) or (None, reason). An explicit FILM_BLENDER that does not exist is an error, not skipped."""
    env = os.environ if env is None else env
    explicit = (env.get("FILM_BLENDER") or "").strip()
    if explicit:
        if os.path.isfile(explicit):
            return explicit, "FILM_BLENDER"
        return None, f"FILM_BLENDER={explicit} does not exist"
    for path, source in candidates(env, system, which):
        if os.path.isfile(path):
            return path, source
    return None, "not on PATH nor in the usual install folders (set FILM_BLENDER)"


def version(path, timeout=120):
    """'5.3.0' from `blender --version`, or None."""
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"Blender (\d+\.\d+(?:\.\d+)?)", r.stdout or "")
    return m.group(1) if m else None


# ------------------------------------------------------------------ helpers
def size_of(text):
    m = re.fullmatch(r"\s*(\d+)\s*[xX]\s*(\d+)\s*", str(text))
    if not m:
        raise Refused(f"--size must be WxH (got {text!r})")
    w, h = int(m.group(1)), int(m.group(2))
    if not (16 <= w <= 8192 and 16 <= h <= 8192) or w % 2 or h % 2:
        raise Refused(f"--size {text}: width and height must be even, 16..8192")
    return w, h


def check_out_dir(path):
    """--out must not exist or be an empty folder."""
    if os.path.isfile(path):
        raise Refused(f"--out {path} is a file (it must be a folder that does not exist or is empty)")
    if os.path.isdir(path) and os.listdir(path):
        raise Refused(f"--out {path} is not empty (nothing is overwritten; pick a new folder, e.g. _v02)")


@contextlib.contextmanager
def claim_out(path, dry_run=False):
    """check_out_dir, then an exclusive claim file in the folder, taken BEFORE the GPU wait: a second job with the same
    --out is refused at once (the folder is not empty), or, when it checked in the same instant, by the exclusive
    create; it never renders into this job's folder. The claim is removed at the end; a job killed hard leaves it
    (the folder then reads as not empty: pick a new one). --dry-run: the check only."""
    check_out_dir(path)
    if dry_run:
        yield
        return
    os.makedirs(path, exist_ok=True)
    claim = os.path.join(path, CLAIM)
    try:
        fd = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise Refused(f"--out {path} is taken by another job ({CLAIM}); pick a new folder, e.g. _v02") from None
    with os.fdopen(fd, "w") as f:
        f.write(f"{os.getpid()}\n")
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            os.remove(claim)


def move_new(src, dst):
    """Move a file to dst, never replacing one that appeared meanwhile (Failed): hard link + unlink, else check +
    rename (src and dst are on the same disk)."""
    try:
        os.link(src, dst)
    except FileExistsError:
        raise Failed(f"{dst} appeared while this job ran (another job with the same --out?): not replaced") from None
    except OSError:
        if os.path.exists(dst):
            raise Failed(f"{dst} appeared while this job ran (another job with the same --out?): not replaced")
        os.rename(src, dst)
        return
    os.remove(src)


def load_shot(path):
    data, errors = spec.load(path)
    if errors:
        raise Refused(f"{path}: {len(errors)} error(s)\n" + "\n".join(f"  {e}" for e in errors))
    return spec.normalize(data)


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def passes_arg(values):
    """--passes depth normal | depth,normal | none -> 'depth,normal' or 'none'."""
    names = [p for v in values for p in v.split(",") if p]
    if names == ["none"]:
        return "none"
    bad = [p for p in names if p not in spec.PASSES]
    if bad:
        raise Refused(f"--passes: {bad[0]!r} is not one of {', '.join(spec.PASSES)} (or none)")
    return ",".join(dict.fromkeys(names))


def blender_or_fail(dry):
    path, why = find()
    if path:
        return path
    if dry:
        return "<blender>"
    raise Failed(f"Blender not found: {why}")


def command(blender, spec_path, out, extra):
    return [blender, "-b", "--factory-startup", "--python-exit-code", "1", "-P", SCENE, "--",
            "--spec", os.path.abspath(spec_path), "--out", os.path.abspath(out)] + extra


def run_blender(cmd, timeout=None, hook=None):
    """Run Blender, echo its film-blender: lines. -> (returncode, scene built?, tail of the output).
    hook: a review JobHook told about each `frame F (i/n)` line (it throttles itself)."""
    tail, built = [], False
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace")
    except OSError as e:
        raise Failed(f"cannot start Blender: {e}")
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            tail = (tail + [line])[-40:]
            if line.startswith("film-blender: "):
                msg = line[len("film-blender: "):]
                built = built or msg.startswith("scene built")
                print(f"blender: {msg}", flush=True)
                m = FRAME_LINE.match(msg) if hook else None
                if m:
                    i, n = int(m.group(2)), int(m.group(3))
                    hook.update(i / n if n else 0.0, f"frame {m.group(1)} · {i}/{n}")
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        stop_process(proc)
        raise Failed(f"Blender did not finish in {timeout} s (killed)")
    except BaseException:           # Ctrl+C, SIGTERM (Interrupted), a hook error: Blender never outlives the GPU lock
        stop_process(proc)
        raise
    return rc, built, tail


def stop_process(proc):
    """Kill Blender and wait until it is gone (before the GPU lock is released)."""
    with contextlib.suppress(OSError):
        proc.kill()
    while True:
        try:
            proc.wait()
            break
        except KeyboardInterrupt:       # a second Ctrl+C: Blender is already killed, keep waiting for it
            continue
    if proc.stdout:
        with contextlib.suppress(OSError):
            proc.stdout.close()


def _clear(path):
    for name in os.listdir(path):
        p = os.path.join(path, name)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)


def gpu_label(a):
    """Short job name for the GPU lock and the review page: never a path or a command line."""
    what = {"render": lambda: os.path.splitext(os.path.basename(a.spec))[0],
            "still": lambda: os.path.splitext(os.path.basename(a.spec))[0],
            "keyframes": lambda: os.path.splitext(os.path.basename(a.spec))[0],
            "turntable": lambda: asset_label(a.asset),
            "mesh-prep": lambda: os.path.splitext(os.path.basename(a.glb))[0],
            "lookbook": lambda: ""}.get(a.cmd, lambda: "")()
    agent = (os.environ.get("FILM_AGENT") or "").strip()
    return gpu.clean_label(f"{agent + ': ' if agent else ''}blender {a.cmd} {what}")


@contextlib.contextmanager
def gpu_turn(a, hook=None):
    """Hold the lab's GPU lock (tools/gpu_run.py) for a Blender run; Refused (exit 2, nothing rendered) when it stays
    busy for FILM_GPU_WAIT seconds. Re-entrant: lookbook holds it across its looks, a gpu_run.py parent is honoured."""
    def waiting(owner):
        who = gpu.clean_label((owner or {}).get("label") or "another job")
        print(f"blender: waiting for the GPU (held by {who})", flush=True)
        if hook:
            hook.update(0.0, f"waiting for the GPU ({who})", force=True)
    try:
        with gpu.gpu_lock(gpu_label(a), gpu.default_wait(), on_wait=waiting, quiet=True):
            yield
    except gpu.GpuBusy as e:
        raise Refused(f"{e} (FILM_GPU_WAIT); nothing rendered")


def render_into(spec_path, out, extra, engine, a, keep=(), hook=None):
    """Render into an (empty) folder with the EEVEE -> Cycles fallback, holding the GPU lock. -> render.json dict."""
    blender = blender_or_fail(a.dry_run)
    cmd = command(blender, spec_path, out, extra + ["--engine", engine])
    if a.dry_run:
        print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
        return None
    os.makedirs(out, exist_ok=True)
    with gpu_turn(a, hook):
        return _render_locked(blender, spec_path, out, extra, engine, a, keep, hook, cmd)


def _render_locked(blender, spec_path, out, extra, engine, a, keep, hook, cmd):
    rc, built, tail = run_blender(cmd, a.timeout, hook)
    fallback = None
    if rc != 0 and engine == "eevee" and built and not glob.glob(os.path.join(out, "beauty", "*.png")):
        last = next((l for l in reversed(tail) if l.strip()), "")
        fallback = f"EEVEE failed ({last.strip()[:200]}); rendered with Cycles"
        print(f"blender: {fallback}", flush=True)
        if hook:
            hook.update(0.0, "EEVEE failed: rendering with Cycles", force=True)
        for name in os.listdir(out):
            if name not in keep and name != CLAIM:
                p = os.path.join(out, name)
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        cmd = command(blender, spec_path, out, extra + ["--engine", "cycles"])
        rc, built, tail = run_blender(cmd, a.timeout, hook)
    if rc != 0:
        raise Failed(f"Blender exited with {rc}:\n" + "\n".join(tail[-15:]))
    info_path = os.path.join(out, "render.json")
    try:
        with open(info_path, encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        raise Failed(f"Blender finished but wrote no readable {info_path}")
    if fallback:
        info["fallback"] = fallback
        write_json(info_path, info)
    return info


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def ffmpeg_path():
    p = (os.environ.get("FILM_FFMPEG") or "").strip()
    return p if p and os.path.isfile(p) else shutil.which("ffmpeg")


def encode_ffmpeg(ff, frames_dir, first, fps, out_mp4):
    cmd = [ff, "-y", "-loglevel", "error", "-framerate", str(fps), "-start_number", str(first), "-i",
           os.path.join(frames_dir, "%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
           "-preset", "medium", "-movflags", "+faststart", out_mp4]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise Failed("ffmpeg failed: " + r.stderr[-2000:])


def _contiguous(frames):
    return frames == list(range(frames[0], frames[-1] + 1))


# ------------------------------------------------------------------ review hook (tools/review/client.py)
def review_hook(a, **extra_tags):
    """A JobHook when --review BUILD or $FILM_REVIEW_BUILD is set (never on --dry-run), else None. Never raises.
    Tags (tools/review/tags.json): engine blender, the --look, project/episode/shot from the spec and --out paths,
    plus extra_tags (turntable: kind turntable, subject <asset>)."""
    bid = (getattr(a, "review", None) or os.environ.get("FILM_REVIEW_BUILD") or "").strip()
    if not bid or getattr(a, "dry_run", False):
        return None
    try:
        sp = importlib.util.spec_from_file_location("film_review_client", REVIEW_CLIENT)
        mod = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(mod)
        tags = dict(getattr(mod, "path_tags", lambda *_: {})(getattr(a, "spec", None), getattr(a, "out", None)),
                    engine="blender")
        if getattr(a, "look", None):
            tags["look"] = a.look
        tags.update({k: v for k, v in extra_tags.items() if v})
        return mod.job_hook(bid, "blender", "render", tags=tags)
    except Exception as e:
        print(f"blender: review publishing off ({type(e).__name__}: {e})", file=sys.stderr)
        return None


def render_entry(out, info, label):
    """A review render for a finished render folder: beauty.mp4 (if any) + the first beauty frame."""
    frames = info.get("frames") or []
    first = os.path.join(out, "beauty", f"{frames[0]:04d}.png") if frames else None
    mp4 = os.path.join(out, "beauty.mp4")
    fps = info.get("fps") or None
    return {"label": label, "video": mp4 if os.path.isfile(mp4) else None,
            "image": first if first and os.path.isfile(first) else None, "frames": len(frames) or None, "fps": fps,
            "duration": round(len(frames) / fps, 3) if fps and frames else None,
            "engine": f"blender {info.get('engine', '')}".strip(),
            "seconds_per_frame": info.get("mean_seconds_per_frame")}


def failure_category(e):
    """A fixed text for the public review page: never the exception text (paths, Blender's output tail)."""
    if isinstance(e, KeyboardInterrupt):
        return "interrupted"
    if isinstance(e, Refused):
        return "refused"
    if isinstance(e, Failed):
        text = str(e)
        if text.startswith("cannot start Blender"):
            return "blender did not start"
        if "did not finish" in text:
            return "timeout"
        if text.startswith("ffmpeg failed"):
            return "encode failed"
        if text.startswith("Blender exited"):
            return "blender error"
        return "render failed"
    return f"error ({type(e).__name__})"


def asset_label(asset):
    """'preset:giot' as is, a file as its base name only (the review page is public)."""
    s = str(asset)
    return s if s.startswith("preset:") else os.path.basename(s.replace("\\", "/"))


def with_review(hook, start_msg, work):
    """Run work() -> (result, renders) with the hook's start / failed / finish around it. -> result.
    The review server gets a fixed failure category; the full error stays on stderr (raised to the caller)."""
    if hook:
        hook.start(start_msg)
    try:
        result, renders = work()
    except BaseException as e:
        if hook:
            hook.failed(f"failed: {failure_category(e)}")
        raise
    if hook and result is not None:
        hook.finish([r for r in renders if r.get("video") or r.get("image")])
    return result


# ------------------------------------------------------------------ commands
def cmd_find(a):
    path, why = find()
    if not path:
        print(f"blender: not found: {why}", file=sys.stderr)
        return 1
    v = version(path)
    if not v:
        print(f"blender: found {path} via {why}, but `--version` failed or printed no version "
              f"(broken or incomplete install)", file=sys.stderr)
        return BROKEN
    print(f"blender {path} ({v}) via {why}")
    return 0


def cmd_check(a):
    shot = load_shot(a.spec)
    print(f"ok {a.spec}: {spec.summary(shot, a.preview)}")
    return 0


def _render_args(a, shot):
    extra = []
    if getattr(a, "preview", False):
        extra.append("--preview")
    if getattr(a, "look", None):
        if a.look not in spec.look_ids():
            raise Refused(f"--look {a.look!r} is not one of {', '.join(spec.look_ids())}")
        extra += ["--look", a.look]
    if getattr(a, "samples", None):
        extra += ["--samples", str(a.samples)]
    return extra


def cmd_render(a):
    shot = load_shot(a.spec)
    W, H, fps, n = spec.timeline(shot, a.preview)
    frames = list(range(1, n + 1))
    extra = _render_args(a, shot)
    if a.frames:
        try:
            frames = spec.parse_frames(a.frames, n)
        except ValueError as e:
            raise Refused(str(e))
        extra += ["--frames", a.frames]
    if a.passes:
        extra += ["--passes", passes_arg(a.passes)]
    check_out_dir(a.out)                    # early refusal; claim_out checks again and claims the folder
    engine = a.engine or shot["engine"]
    ff = None if a.no_mp4 else ffmpeg_path()
    mp4 = os.path.join(os.path.abspath(a.out), "beauty.mp4")
    if not a.no_mp4 and not ff and _contiguous(frames) and len(frames) > 1:
        extra += ["--mp4", mp4]                              # Blender's own encoder
    hook = review_hook(a)

    def work():
        info = render_into(a.spec, a.out, extra, engine, a, hook=hook)
        if info is None:
            return None, []
        if ff and _contiguous(frames) and len(frames) > 1:
            encode_ffmpeg(ff, os.path.join(a.out, "beauty"), frames[0], info["fps"], mp4)
            info["mp4"] = {"file": "beauty.mp4", "encoder": "ffmpeg"}
            write_json(os.path.join(a.out, "render.json"), info)
        return info, [render_entry(a.out, info, os.path.splitext(os.path.basename(a.spec))[0])]

    with claim_out(a.out, a.dry_run):
        info = with_review(hook, f"render {os.path.basename(a.spec)} · {len(frames)} frames", work)
    if info is None:
        return 0
    if not info.get("mp4"):
        why = "--no-mp4" if a.no_mp4 else ("one frame" if len(frames) == 1 else "frames are not contiguous")
        print(f"blender: no beauty.mp4 ({why})")
    print(f"rendered {len(frames)} frames {info['size'][0]}x{info['size'][1]} {info['engine']} on {info['device']} · "
          f"{info['mean_seconds_per_frame']} s/frame -> {a.out}")
    return 0


def cmd_still(a):
    shot = load_shot(a.spec)
    W, H, fps, n = spec.timeline(shot, a.preview)
    if not 1 <= a.frame <= n:
        raise Refused(f"--frame {a.frame} is outside 1..{n}")
    if os.path.exists(a.out):
        raise Refused(f"{a.out} exists (nothing is overwritten; use a new name, e.g. _v02)")
    extra = _render_args(a, shot) + ["--frames", str(a.frame), "--passes", "none"]
    if a.size:
        extra += ["--size", "%dx%d" % size_of(a.size)]
    parent = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(parent, exist_ok=True)
    work = tempfile.mkdtemp(prefix=".blender-still-", dir=parent)
    try:
        info = render_into(a.spec, work, extra, a.engine or shot["engine"], a)
        if info is None:
            return 0
        move_new(os.path.join(work, "beauty", f"{a.frame:04d}.png"), a.out)
        side = os.path.splitext(a.out)[0] + ".render.json"
        if not os.path.exists(side):
            write_json(side, info)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"still frame {a.frame} {info['size'][0]}x{info['size'][1]} {info['engine']} · "
          f"{info['mean_seconds_per_frame']} s -> {a.out}")
    return 0


def cmd_keyframes(a):
    shot = load_shot(a.spec)
    W, H, fps, n = spec.timeline(shot, False)
    size = size_of(a.size)
    check_out_dir(a.out)
    frames = [1, n] if n > 1 else [1]
    extra = _render_args(a, shot) + ["--frames", ",".join(map(str, frames)), "--passes", "none",
                                     "--size", "%dx%d" % size]
    work = os.path.join(a.out, ".work")
    hook = review_hook(a)

    def render_keyframes():
        try:
            info = render_into(a.spec, work, extra, a.engine or shot["engine"], a, hook=hook)
            if info is None:
                return None, []
            shutil.move(os.path.join(work, "beauty", f"{frames[0]:04d}.png"), os.path.join(a.out, "first.png"))
            shutil.move(os.path.join(work, "beauty", f"{frames[-1]:04d}.png"), os.path.join(a.out, "last.png"))
        finally:
            shutil.rmtree(work, ignore_errors=True)
        stem = os.path.splitext(os.path.basename(a.spec))[0]
        eng = f"blender {info.get('engine', '')}".strip()
        return info, [{"label": f"{stem} {name}", "image": os.path.join(a.out, f"{name}.png"), "engine": eng}
                      for name in ("first", "last")]

    with claim_out(a.out, a.dry_run):
        info = with_review(hook, f"keyframes {os.path.basename(a.spec)} · {size[0]}x{size[1]}", render_keyframes)
    if info is None:
        return 0
    kf = {"tool": "tools/blender/blender.py keyframes", "spec": os.path.abspath(a.spec), "spec_sha256": sha256(a.spec),
          "size": list(size), "spec_size": shot["size"], "fps": fps, "frames": frames,
          "times": [round(spec.frame_time(f, fps), 4) for f in frames], "seconds": shot["seconds"],
          "files": {"first": "first.png", "last": "last.png"}, "look": info["look"], "engine": info["engine"],
          "device": info["device"], "blender": info["blender"], "seconds_per_frame": info["seconds_per_frame"]}
    if info.get("fallback"):
        kf["fallback"] = info["fallback"]
    write_json(os.path.join(a.out, "keyframes.json"), kf)
    print(f"keyframes {size[0]}x{size[1]} frames {frames[0]} and {frames[-1]} ({shot['seconds']} s) -> "
          f"{os.path.join(a.out, 'first.png')}, last.png, keyframes.json")
    return 0


TURNTABLE_STILLS = "front,34,side,head"
TURNTABLE_FPS = 24


def stills_arg(text):
    """--stills front,34,side,head | none -> list of views."""
    names = [s.strip() for s in str(text).split(",") if s.strip()]
    if names == ["none"]:
        return []
    bad = [s for s in names if s not in spec.TURNTABLE_VIEWS]
    if bad:
        raise Refused(f"--stills: {bad[0]!r} is not one of {', '.join(spec.TURNTABLE_VIEWS)} (or none)")
    return list(dict.fromkeys(names))


def turntable_spec(src, look, seconds, *, fill=0.7, stills=(), front=0.0, backdrop="cyc", head_bone="head",
                   lens=50.0, fit=None, hdri=None, engine=None):
    """A shot3d.json for one turn of an asset in place (`turntable`): it stands centred on the turn axis at its own
    size (or `fit` metres), a fixed camera frames its bounding box (`fill` of the frame height), a seamless cyc behind
    it; look realistic (Cycles) gets three studio lamps on a grey sky or a dim HDRI."""
    if not src.startswith(("preset:", "prim:")):
        src = os.path.abspath(src)                     # keeps a .blend's #Collection
    realistic = look == "realistic"
    world = {"mist": 0.0, "sun": [40, 225]}
    if realistic:
        world["sun_strength"] = 0                      # the studio lamps light it
        if hdri:
            world["hdri"], world["hdri_strength"] = os.path.abspath(hdri), 0.5
    asset = {"id": "asset", "src": src}
    if fit:
        asset["fit"] = float(fit)
    return {
        "version": 1, "title": f"turntable {asset_label(src)}", "size": [1920, 1080], "fps": TURNTABLE_FPS,
        "seconds": seconds, "seed": 0, "look": look, "engine": engine or ("cycles" if realistic else "eevee"),
        "world": world, "assets": [asset],
        "camera": {"move": "static", "from": [0, -6, 1], "target": "asset", "lens": float(lens)},
        "passes": [], "depth_range": [0.1, 400],
        "turntable": {"asset": "asset", "fill": float(fill), "stills": list(stills), "front": float(front),
                      "backdrop": backdrop, "head_bone": head_bone, "lens": float(lens), "studio": realistic}}


def cmd_turntable(a):
    look = a.look or "clay"
    if look not in spec.look_ids():
        raise Refused(f"--look {look!r} is not one of {', '.join(spec.look_ids())}")
    if a.frames is not None and a.frames < 2:
        raise Refused("--frames must be at least 2")
    seconds = a.frames / TURNTABLE_FPS if a.frames is not None else (a.seconds or 4.0)
    if a.hdri and look != "realistic":
        raise Refused("--hdri is for --look realistic")
    if a.hdri and not os.path.isfile(a.hdri):
        raise Refused(f"--hdri {a.hdri}: no such file")
    stills = stills_arg(a.stills)
    check_out_dir(a.out)
    data = turntable_spec(a.asset, look, seconds, fill=a.fill, stills=stills, front=a.front, backdrop=a.backdrop,
                          head_bone=a.head_bone, lens=a.lens, fit=a.fit, hdri=a.hdri, engine=a.engine)
    errors = spec.validate(data, os.getcwd())
    if errors:
        raise Refused("turntable: " + "; ".join(errors))
    with claim_out(a.out, a.dry_run):
        return _turntable_claimed(a, look, stills, data)


def _turntable_claimed(a, look, stills, data):
    path, extra, ff, mp4 = _turntable_files(a, data)
    stem = os.path.splitext(asset_label(a.asset).replace("preset:", "").split("#")[0])[0]
    hook = review_hook(a, kind="turntable", subject=stem)
    info = with_review(hook, f"turntable {asset_label(a.asset)} ({look})",
                       lambda: _turntable_render(a, look, stills, path, data["engine"], extra, ff, mp4, stem, hook))
    if info is None:
        return 0
    tt = info.get("turntable") or {}
    print(f"turntable {asset_label(a.asset)} ({look}) {info['frame_count']} frames · "
          f"{info['mean_seconds_per_frame']} s/frame"
          + (f" · camera {tt['camera_distance_m']} m, {tt.get('height_m')} m tall" if tt.get("camera_distance_m") else "")
          + (f" · stills {', '.join(stills)}" if stills else "") + f" -> {a.out}")
    return 0


def _turntable_files(a, data):
    """turntable.json in the (claimed) --out, the scene.py flags, ffmpeg (or Blender's encoder) and the mp4 path."""
    path = os.path.join(tempfile.gettempdir() if a.dry_run else a.out, "turntable.json")
    write_json(path, data)
    extra = ["--preview"] if a.preview else []
    if a.size:
        extra += ["--size", "%dx%d" % size_of(a.size)]
    if a.samples:
        extra += ["--samples", str(a.samples)]
    ff = ffmpeg_path()
    mp4 = os.path.join(os.path.abspath(a.out), "beauty.mp4")
    if not ff:
        extra += ["--mp4", mp4]
    return path, extra, ff, mp4


def _turntable_render(a, look, stills, path, engine, extra, ff, mp4, stem, hook):
    """Render a turntable spec into a.out (GPU lock inside render_into). -> (render.json dict, review renders)."""
    info = render_into(path, a.out, extra, engine, a, keep=("turntable.json",), hook=hook)
    if info is None:
        return None, []
    missing = [v for v in stills if not os.path.isfile(os.path.join(a.out, f"still_{v}.png"))]
    if missing:
        raise Failed(f"Blender finished without still_{missing[0]}.png")
    if ff:
        encode_ffmpeg(ff, os.path.join(a.out, "beauty"), 1, info["fps"], mp4)
        info["mp4"] = {"file": "beauty.mp4", "encoder": "ffmpeg"}
        write_json(os.path.join(a.out, "render.json"), info)
    eng = f"blender {info.get('engine', '')}".strip()
    renders = [render_entry(a.out, info, f"turntable {stem} ({look})")]
    renders += [{"label": f"{stem} {v}", "image": os.path.join(a.out, f"still_{v}.png"), "engine": eng}
                for v in stills]
    return info, renders


def cmd_lookbook(a):
    spec_path = a.spec or LOOKBOOK_SPEC
    shot = load_shot(spec_path)
    size = size_of(a.size)
    W, H, fps, n = spec.timeline(shot, False)
    frame = a.frame or (n + 1) // 2
    if not 1 <= frame <= n:
        raise Refused(f"--frame {frame} is outside 1..{n}")
    book = {"tool": "tools/blender/blender.py lookbook", "spec": os.path.abspath(spec_path),
            "spec_sha256": sha256(spec_path), "frame": frame, "size": list(size), "looks": {}}
    with claim_out(a.out, a.dry_run), (contextlib.nullcontext() if a.dry_run else gpu_turn(a)):   # one GPU turn
        _lookbook_looks(a, spec_path, shot, frame, size, book)
    if not a.dry_run:
        write_json(os.path.join(a.out, "lookbook.json"), book)
    return 0


def _lookbook_looks(a, spec_path, shot, frame, size, book):
    for look in spec.look_ids():
        work = os.path.join(a.out, f".work-{look}")
        extra = ["--look", look, "--frames", str(frame), "--passes", "none", "--size", "%dx%d" % size]
        try:
            info = render_into(spec_path, work, extra, a.engine or shot["engine"], a)
            if info is None:
                continue
            shutil.move(os.path.join(work, "beauty", f"{frame:04d}.png"), os.path.join(a.out, f"{look}.png"))
        finally:
            shutil.rmtree(work, ignore_errors=True)
        book["looks"][look] = {"file": f"{look}.png", "engine": info["engine"], "device": info["device"],
                               "seconds": info["seconds_per_frame"][0], "fallback": info.get("fallback")}
        print(f"lookbook {look} -> {os.path.join(a.out, look + '.png')} ({info['seconds_per_frame'][0]} s)")


# ------------------------------------------------------------------ image-to-3D blanks (mesh-prep, mesh-check)
MESH_STILLS = "front,34,side"
MESH_VIEW = "front"             # Hunyuan3D: the concept is the view from +Z in glTF (from -Y in Blender)


def _load_meshcheck():
    """tools/blender/meshcheck.py (numpy + Pillow), loaded on use: find/check/render never need numpy."""
    try:
        sp = importlib.util.spec_from_file_location("film_blender_meshcheck", os.path.join(HERE, "meshcheck.py"))
        mod = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(mod)
        return mod
    except ImportError as e:
        raise Refused(f"mesh-check/mesh-prep need numpy and Pillow ({e}): pip install numpy Pillow")


def read_mesh(mc, path):
    if not os.path.isfile(path):
        raise Refused(f"no such file: {path}")
    try:
        return mc.read_glb(path)
    except mc.GlbError as e:
        raise Refused(f"{path}: {e}")


def concept_arg(mc, path):
    """The subject mask of --concept (None without it); Refused when it cannot be read or is empty."""
    if not path:
        return None
    if not os.path.isfile(path):
        raise Refused(f"--concept {path}: no such file")
    try:
        mask = mc.concept_mask(path)
    except Exception as e:          # Pillow: not an image
        raise Refused(f"--concept {path}: not an image ({type(e).__name__})")
    if not mask.any():
        raise Refused(f"--concept {path}: no subject found (the image is near-white)")
    return mask


def mesh_line(label, st):
    return (f"{label}: {st['tris']} tris, {st['verts']} verts, {st['islands']} island(s), {st['boundary_edges']} "
            f"boundary + {st['overshared_edges']} over-shared edges -> "
            + ("watertight" if st["watertight"] else "NOT watertight"))


def iou_line(label, cmp):
    return (f"{label} vs concept: silhouette IoU {cmp['iou']:.3f}" + (" (mirrored)" if cmp["mirrored"] else "")
            + f" · proportions {cmp['aspect_drift']:+.1%}")


def save_mask(mask, path):
    from PIL import Image
    Image.fromarray((mask * 255).astype("uint8")).save(path, "PNG")


def prep_name(glb):
    """'ho-giao_raw_v01.glb' -> 'ho-giao_v01' (the prep files are <name>_prep.glb/.blend)."""
    stem = os.path.splitext(os.path.basename(glb))[0]
    return re.sub(r"_raw(?=(_v\d+)?$)", "", stem) or stem


def voxel_arg(text):
    t = str(text).strip().lower()
    if t == "auto":
        return "auto"
    try:
        v = float(t)
    except ValueError:
        v = -1.0
    if not 0 <= v < 1e6:
        raise Refused(f"--voxel {text!r}: auto, 0 (no voxel remesh) or a size in the mesh's units (> 0)")
    return f"{v:g}"


def cmd_mesh_check(a):
    mc = _load_meshcheck()
    for p in (a.sheet, a.json):
        if p and os.path.exists(p):
            raise Refused(f"{p} exists (nothing is overwritten; use a new name, e.g. _v02)")
    V, F, info = read_mesh(mc, a.glb)
    concept = concept_arg(mc, a.concept)
    st = mc.mesh_stats(V, F)
    print(mesh_line(os.path.basename(a.glb), st))
    sil = mc.silhouette(V, F, a.view)
    cmp = mc.compare(concept, sil) if concept is not None else None
    if cmp:
        print(iou_line(f"view {a.view}", cmp))
    warns = mc.warnings(st, cmp)
    for w in warns:
        print(f"WARNING: {w}")
    if a.json:
        write_json(a.json, {"tool": "tools/blender/blender.py mesh-check", "glb": os.path.abspath(a.glb),
                            "glb_sha256": sha256(a.glb), "glb_info": info, "stats": st, "view": a.view,
                            "concept": os.path.abspath(a.concept) if a.concept else None, "silhouette": cmp,
                            "warnings": warns})
    if a.sheet:
        tiles = ([("concept", a.concept)] if concept is not None else []) + [(f"silhouette ({a.view})", sil)]
        if cmp:
            tiles.append((f"overlay IoU {cmp['iou']:.3f}", mc.overlay(concept, sil, mirrored=cmp["mirrored"])))
        os.makedirs(os.path.dirname(os.path.abspath(a.sheet)), exist_ok=True)
        mc.compare_sheet(a.sheet, tiles, title=f"{os.path.basename(a.glb)} · {st['tris']} tris")
        print(f"sheet -> {a.sheet}")
    return 0


def mesh_prep_command(blender, a, name):
    cmd = [blender, "-b", "--factory-startup", "--python-exit-code", "1", "-P", MESHPREP, "--",
           "--glb", os.path.abspath(a.glb), "--out", os.path.abspath(a.out), "--name", name,
           "--voxel", voxel_arg(a.voxel), "--quad-faces", str(a.quad_faces), "--min-island", f"{a.min_island:g}"]
    if a.decimate:
        cmd += ["--decimate", str(a.decimate)]
    return cmd


def cmd_mesh_prep(a):
    mc = _load_meshcheck()
    voxel_arg(a.voxel)
    if not (a.quad_faces == 0 or 100 <= a.quad_faces <= 1000000):
        raise Refused("--quad-faces must be 0 (no quad remesh) or 100..1000000")
    if a.decimate is not None and not 100 <= a.decimate <= 10000000:
        raise Refused("--decimate must be 100..10000000 triangles")
    if not 0 <= a.min_island < 0.5:
        raise Refused("--min-island must be 0 (keep every loose part) .. 0.5 (share of the vertices)")
    if a.frames is not None and a.frames < 2:
        raise Refused("--frames must be at least 2")
    look = a.look or "clay"
    if look not in spec.look_ids():
        raise Refused(f"--look {look!r} is not one of {', '.join(spec.look_ids())}")
    stills = stills_arg(a.stills)
    V, F, info = read_mesh(mc, a.glb)
    concept = concept_arg(mc, a.concept)
    check_out_dir(a.out)
    name = prep_name(a.glb)
    blender = blender_or_fail(a.dry_run)
    cmd = mesh_prep_command(blender, a, name)
    tt_out = os.path.join(a.out, "turntable")
    if a.dry_run:
        print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
        if not a.no_turntable:
            print(f"then: turntable {os.path.join(a.out, name + '_prep.glb')} --look {look} --stills "
                  f"{','.join(stills) or 'none'} --out {tt_out}")
        print(f"then (CPU): mesh_report.json, silhouette_raw.png, silhouette_prep.png, compare.png in {a.out}")
        return 0
    raw = mc.mesh_stats(V, F)
    print(mesh_line("raw", raw))
    hook = review_hook(a, kind="model", subject=name)
    with claim_out(a.out):
        rep = with_review(hook, f"mesh-prep {name}",
                          lambda: _mesh_prep_claimed(a, mc, cmd, name, look, stills, (V, F, info, raw), concept,
                                                     tt_out, hook))
    prep = rep["prep"]
    print(mesh_line("prep", prep["stats"]) + f" · {prep['blender'].get('retopo', {}).get('method')}")
    for k in ("raw", "prep"):
        if rep["silhouette"].get(k):
            print(iou_line(k, rep["silhouette"][k]))
    for w in rep["warnings"]:
        print(f"WARNING: {w}")
    print(f"mesh-prep {name} -> {a.out} (mesh_report.json, {prep['glb']}, {prep['blend']}, compare.png"
          + ("" if a.no_turntable else ", turntable/") + ")")
    return 0


def _mesh_prep_claimed(a, mc, cmd, name, look, stills, raw_mesh, concept, tt_out, hook):
    V, F, info, raw = raw_mesh
    tt = None
    with gpu_turn(a, hook):             # meshprep.py and the turntable under one GPU turn (re-entrant lock)
        if hook:
            hook.update(0.05, "remesh in Blender", force=True)
        rc, _, tail = run_blender(cmd, a.timeout)
        if rc != 0:
            raise Failed(f"Blender exited with {rc}:\n" + "\n".join(tail[-15:]))
        try:
            with open(os.path.join(a.out, "prep.json"), encoding="utf-8") as f:
                prep = json.load(f)
            prep_glb = os.path.join(a.out, prep["files"]["glb"])
        except (OSError, ValueError, KeyError, TypeError):
            raise Failed(f"Blender finished but wrote no readable {os.path.join(a.out, 'prep.json')}")
        if not a.no_turntable:
            if hook:
                hook.update(0.3, "clay turntable", force=True)
            seconds = a.frames / TURNTABLE_FPS if a.frames is not None else 4.0
            data = turntable_spec(prep_glb, look, seconds, stills=stills, front=a.front, engine=a.engine)
            errors = spec.validate(data, os.getcwd())
            if errors:
                raise Failed("turntable: " + "; ".join(errors))
            os.makedirs(tt_out)
            ns = argparse.Namespace(cmd="turntable", asset=prep_glb, out=tt_out, dry_run=False, preview=a.preview,
                                    size=None, samples=a.samples, timeout=a.timeout)
            path, extra, ff, mp4 = _turntable_files(ns, data)
            tt = _turntable_render(ns, look, stills, path, data["engine"], extra, ff, mp4, name + "_prep", None)
    try:
        pV, pF, _ = mc.read_glb(prep_glb)
    except mc.GlbError as e:
        raise Failed(f"{prep_glb}: {e}")
    pstats = mc.mesh_stats(pV, pF)
    sil_raw, sil_prep = mc.silhouette(V, F, MESH_VIEW), mc.silhouette(pV, pF, MESH_VIEW)
    save_mask(sil_raw, os.path.join(a.out, "silhouette_raw.png"))
    save_mask(sil_prep, os.path.join(a.out, "silhouette_prep.png"))
    cmp = {k: (mc.compare(concept, m) if concept is not None else None) for k, m in (("raw", sil_raw), ("prep", sil_prep))}
    tiles = [("concept", a.concept)] if concept is not None else []
    tiles.append(("raw silhouette", sil_raw))
    for k, m in (("raw", sil_raw), ("prep", sil_prep)):
        if cmp[k]:
            tiles.append((f"{k} vs concept IoU {cmp[k]['iou']:.3f}", mc.overlay(concept, m, mirrored=cmp[k]["mirrored"])))
    if not cmp["prep"]:
        tiles.append(("prep silhouette", sil_prep))
    tiles += [(f"clay {v}", os.path.join(tt_out, f"still_{v}.png")) for v in stills if tt]
    fin = prep.get("stages", {}).get("final", {})
    mc.compare_sheet(os.path.join(a.out, "compare.png"), tiles,
                     title=f"{name}: raw {raw['tris']} tris -> prep {fin.get('faces', '?')} faces "
                           f"({fin.get('quads', '?')} quads, {prep.get('retopo', {}).get('method', '?')})")
    warns = [f"raw: {w}" for w in mc.warnings(raw, cmp["raw"])] + [f"prep: {w}" for w in mc.warnings(pstats, cmp["prep"])]
    warns += [f"blender: {n}" for n in prep.get("notes") or []]
    tt_info = tt[0] if tt else None
    report = {
        "tool": "tools/blender/blender.py mesh-prep", "name": name,
        "raw": {"glb": os.path.abspath(a.glb), "glb_sha256": sha256(a.glb), "glb_info": info, "stats": raw},
        "prep": {"glb": prep["files"]["glb"], "blend": prep["files"]["blend"], "stats": pstats, "blender": prep},
        "params": {"voxel": voxel_arg(a.voxel), "quad_faces": a.quad_faces, "decimate": a.decimate,
                   "min_island": a.min_island, "look": look, "view": MESH_VIEW},
        "concept": os.path.abspath(a.concept) if a.concept else None, "silhouette": cmp,
        "files": {"silhouette_raw": "silhouette_raw.png", "silhouette_prep": "silhouette_prep.png",
                  "sheet": "compare.png", "turntable": "turntable/" if tt else None},
        "turntable": ({"mp4": (tt_info.get("mp4") or {}).get("file"), "stills": [f"still_{v}.png" for v in stills],
                       "engine": tt_info.get("engine"), "seconds_per_frame": tt_info.get("mean_seconds_per_frame")}
                      if tt_info else None),
        "warnings": warns,
        "next": "sculpt/retopo by hand where needed, rebuild thin parts (fins, hair, antlers) by script, then rig "
                "(.claude/skills/film-compose-shot/references/blender-method.md)",
    }
    write_json(os.path.join(a.out, "mesh_report.json"), report)
    renders = list(tt[1]) if tt else []
    renders.append({"label": f"{name} compare", "image": os.path.join(a.out, "compare.png"), "engine": "blender"})
    if hook:
        hook.rv.step(f"{name}_prep", glb=prep_glb, stats={"verts": pstats["verts"], "tris": pstats["tris"]})
    return report, renders


def main(argv=None):
    p = argparse.ArgumentParser(prog="blender.py", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sp = p.add_subparsers(dest="cmd", required=True)

    def common(q, preview=True):
        q.add_argument("--engine", choices=spec.ENGINES, default=None, help="default: the spec's engine (eevee)")
        q.add_argument("--look", default=None, help="override the spec's look (tools/blender/looks.json)")
        q.add_argument("--dry-run", action="store_true", help="print the Blender command, render nothing")
        q.add_argument("--timeout", type=float, default=None, help="kill Blender after S seconds")
        if preview:
            q.add_argument("--preview", action="store_true", help="960 wide, 12 fps, low samples")

    def review_arg(q):
        q.add_argument("--review", default=None, metavar="BUILD",
                       help="publish progress + output to the review server (env FILM_REVIEW_BUILD; tools/review/)")

    sp.add_parser("find", help="where Blender is and its version")
    q = sp.add_parser("check", help="validate a shot3d.json (no Blender)")
    q.add_argument("spec")
    q.add_argument("--preview", action="store_true")
    q = sp.add_parser("render", help="PNG sequence + passes + render.json (+ beauty.mp4)")
    q.add_argument("spec")
    q.add_argument("--out", required=True)
    q.add_argument("--frames", default=None, help="A:B (1-based, inclusive) or A,B,C")
    q.add_argument("--passes", nargs="+", default=None, help="depth normal line mask | none (default: the spec's)")
    q.add_argument("--samples", type=int, default=None)
    q.add_argument("--no-mp4", action="store_true")
    common(q)
    review_arg(q)
    q = sp.add_parser("still", help="one beauty frame as a png")
    q.add_argument("spec")
    q.add_argument("--frame", type=int, required=True)
    q.add_argument("--out", required=True)
    q.add_argument("--size", default=None, help="WxH, same vertical field of view")
    q.add_argument("--samples", type=int, default=None)
    common(q)
    q = sp.add_parser("turntable", help="one turn of an asset (.glb/.gltf, <file>.blend[#Collection], preset:<id>) "
                                        "in front of a fixed camera, + review stills")
    q.add_argument("asset")
    q.add_argument("--out", required=True)
    q.add_argument("--seconds", type=float, default=None, help="length of the turn (default 4; --frames wins)")
    q.add_argument("--frames", type=int, default=None, help=f"frames of the turn at {TURNTABLE_FPS} fps (e.g. 72)")
    q.add_argument("--size", default=None, help="WxH (default 1920x1080), same vertical field of view")
    q.add_argument("--samples", type=int, default=None, help="render samples (default: the look's)")
    q.add_argument("--fill", type=float, default=0.7, help="share of the frame height the asset fills (default 0.7)")
    q.add_argument("--stills", default=TURNTABLE_STILLS,
                   help=f"review stills, of {','.join(spec.TURNTABLE_VIEWS)} or none (default {TURNTABLE_STILLS})")
    q.add_argument("--front", type=float, default=0.0,
                   help="degrees that turn the asset's front to the camera (a model facing +Y: 180)")
    q.add_argument("--backdrop", choices=spec.BACKDROPS, default="cyc", help="seamless studio cyc (default) or none")
    q.add_argument("--head-bone", default="head", help="bone of the head close-up (default head; else bbox top)")
    q.add_argument("--lens", type=float, default=50.0, help="focal length mm (default 50)")
    q.add_argument("--fit", type=float, default=None, help="scale the asset to this many metres (default: own size)")
    q.add_argument("--hdri", default=None, help="look realistic: .hdr/.exr for soft fill (default: grey studio sky)")
    common(q)
    review_arg(q)
    q = sp.add_parser("keyframes", help="first.png + last.png + keyframes.json (for the local video model)")
    q.add_argument("spec")
    q.add_argument("--out", required=True)
    q.add_argument("--size", default=KEYFRAME_SIZE, help=f"WxH (default {KEYFRAME_SIZE}; draft 864x480)")
    q.add_argument("--samples", type=int, default=None)
    common(q, preview=False)
    review_arg(q)
    q = sp.add_parser("lookbook", help="one still per look of tools/blender/looks.json")
    q.add_argument("--out", required=True)
    q.add_argument("--spec", default=None, help="default tools/blender/demo/lookbook.json")
    q.add_argument("--frame", type=int, default=None, help="default: the middle frame")
    q.add_argument("--size", default="960x540")
    q.add_argument("--engine", choices=spec.ENGINES, default=None)
    q.add_argument("--dry-run", action="store_true")
    q.add_argument("--timeout", type=float, default=None)
    q = sp.add_parser("mesh-prep", help="image-to-3D blank (.glb) -> sculpt base: mesh report, voxel + quad remesh, "
                                        "clay turntable, silhouette IoU vs the concept")
    q.add_argument("glb")
    q.add_argument("--out", required=True)
    q.add_argument("--concept", default=None, help="the concept image the mesh came from (silhouette IoU, sheet)")
    q.add_argument("--voxel", default="auto",
                   help="voxel remesh size in the mesh's units: auto (longest side / 300, default) or 0 (none)")
    q.add_argument("--quad-faces", type=int, default=20000, help="QuadriFlow target quads (default 20000; 0 = none)")
    q.add_argument("--decimate", type=int, default=None, help="decimate to N triangles instead of QuadriFlow")
    q.add_argument("--min-island", type=float, default=0.002,
                   help="drop loose parts under this share of the vertices (default 0.002; 0 keeps all)")
    q.add_argument("--no-turntable", action="store_true", help="skip the clay turntable")
    q.add_argument("--stills", default=MESH_STILLS,
                   help=f"turntable stills, of {','.join(spec.TURNTABLE_VIEWS)} or none (default {MESH_STILLS})")
    q.add_argument("--frames", type=int, default=None, help=f"turntable frames at {TURNTABLE_FPS} fps (default 96)")
    q.add_argument("--front", type=float, default=0.0, help="turntable: degrees that turn the front to the camera")
    q.add_argument("--samples", type=int, default=None)
    common(q)
    review_arg(q)
    q = sp.add_parser("mesh-check", help="mesh report + silhouette IoU of a .glb without Blender (CPU)")
    q.add_argument("glb")
    q.add_argument("--concept", default=None, help="the concept image (silhouette IoU)")
    q.add_argument("--view", choices=("front", "side", "back"), default=MESH_VIEW,
                   help="silhouette view (front = from +Z in glTF, the concept's view for Hunyuan3D)")
    q.add_argument("--sheet", default=None, help="write a comparison PNG here (must not exist)")
    q.add_argument("--json", default=None, help="write the report here (must not exist)")
    a = p.parse_args(argv)
    fn = {"find": cmd_find, "check": cmd_check, "render": cmd_render, "still": cmd_still, "turntable": cmd_turntable,
          "keyframes": cmd_keyframes, "lookbook": cmd_lookbook, "mesh-prep": cmd_mesh_prep,
          "mesh-check": cmd_mesh_check}[a.cmd]
    fired = []

    def on_stop(signum, frame):
        if not fired:                   # once: a second signal must not break the cleanup (kill + wait Blender)
            fired.append(signum)
            raise Stopped(signum)

    prev = {}
    for name in ("SIGTERM", "SIGHUP", "SIGBREAK"):
        if hasattr(signal, name):
            with contextlib.suppress(ValueError, OSError):      # ValueError: not the main thread
                prev[getattr(signal, name)] = signal.signal(getattr(signal, name), on_stop)
    try:
        return fn(a)
    except Refused as e:
        print(f"blender: refused: {e}", file=sys.stderr)
        return 2
    except Failed as e:
        print(f"blender: {e}", file=sys.stderr)
        return 1
    except Stopped as e:
        print(f"blender: stopped by signal {e.signum} (Blender was stopped before the GPU lock was released)",
              file=sys.stderr)
        return 128 + e.signum
    finally:
        for sig, h in prev.items():
            with contextlib.suppress(ValueError, OSError):
                signal.signal(sig, h)


if __name__ == "__main__":
    sys.exit(main())
