#!/usr/bin/env python3
"""Local 3D renders with Blender 5.x headless (method: blender). Free: no API, no ledger cost; runs on the owner's PC.

  python tools/blender/blender.py find                                   # path + version (1 = not found, 3 = broken)
  python tools/blender/blender.py check <shot3d.json> [--preview]        # validate the spec only, no Blender
  python tools/blender/blender.py render <shot3d.json> --out <dir> [--frames A:B] [--preview] [--engine eevee|cycles]
                                         [--passes depth normal line mask | none] [--look L] [--samples N] [--no-mp4]
  python tools/blender/blender.py still <shot3d.json> --frame N --out <png> [--size WxH] [--preview] [--look L]
  python tools/blender/blender.py turntable <asset.glb|preset:id> --out <dir> [--look L] [--seconds 4] [--preview]
  python tools/blender/blender.py keyframes <shot3d.json> --out <dir> [--size 1344x768] [--look L]
  python tools/blender/blender.py lookbook --out <dir> [--spec S] [--frame N] [--size 960x540]

Every render command also takes --engine, --dry-run (print the Blender command, render nothing) and --timeout S.
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

Exit codes: 0 ok · 1 Blender not found or the render failed · 2 refused before rendering (bad spec, arguments, --out)
· 3 (find only) a Blender was found but `blender --version` failed or printed no version (broken install).
"""
import argparse
import glob
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE = os.path.join(HERE, "scene.py")
DEMO = os.path.join(HERE, "demo")
LOOKBOOK_SPEC = os.path.join(DEMO, "lookbook.json")
KEYFRAME_SIZE = "1344x768"
BROKEN = 3          # `find`: a Blender exists but `--version` fails (tools/doctor.sh WARNs; 1 = none found)


def _load_spec():
    sp = importlib.util.spec_from_file_location("film_blender_spec", os.path.join(HERE, "spec.py"))
    mod = importlib.util.module_from_spec(sp)
    sys.modules.setdefault(sp.name, mod)
    sp.loader.exec_module(mod)
    return mod


spec = _load_spec()


class Refused(Exception):
    """Exit 2: nothing was rendered."""


class Failed(Exception):
    """Exit 1."""


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


def run_blender(cmd, timeout=None):
    """Run Blender, echo its film-blender: lines. -> (returncode, scene built?, tail of the output)."""
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
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise Failed(f"Blender did not finish in {timeout} s (killed)")
    return rc, built, tail


def _clear(path):
    for name in os.listdir(path):
        p = os.path.join(path, name)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)


def render_into(spec_path, out, extra, engine, a, keep=()):
    """Render into an (empty) folder with the EEVEE -> Cycles fallback. -> render.json dict."""
    blender = blender_or_fail(a.dry_run)
    cmd = command(blender, spec_path, out, extra + ["--engine", engine])
    if a.dry_run:
        print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
        return None
    os.makedirs(out, exist_ok=True)
    rc, built, tail = run_blender(cmd, a.timeout)
    fallback = None
    if rc != 0 and engine == "eevee" and built and not glob.glob(os.path.join(out, "beauty", "*.png")):
        last = next((l for l in reversed(tail) if l.strip()), "")
        fallback = f"EEVEE failed ({last.strip()[:200]}); rendered with Cycles"
        print(f"blender: {fallback}", flush=True)
        for name in os.listdir(out):
            if name not in keep:
                p = os.path.join(out, name)
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        cmd = command(blender, spec_path, out, extra + ["--engine", "cycles"])
        rc, built, tail = run_blender(cmd, a.timeout)
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
    check_out_dir(a.out)
    engine = a.engine or shot["engine"]
    ff = None if a.no_mp4 else ffmpeg_path()
    mp4 = os.path.join(os.path.abspath(a.out), "beauty.mp4")
    if not a.no_mp4 and not ff and _contiguous(frames) and len(frames) > 1:
        extra += ["--mp4", mp4]                              # Blender's own encoder
    info = render_into(a.spec, a.out, extra, engine, a)
    if info is None:
        return 0
    if ff and _contiguous(frames) and len(frames) > 1:
        encode_ffmpeg(ff, os.path.join(a.out, "beauty"), frames[0], info["fps"], mp4)
        info["mp4"] = {"file": "beauty.mp4", "encoder": "ffmpeg"}
        write_json(os.path.join(a.out, "render.json"), info)
    elif not info.get("mp4"):
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
        shutil.move(os.path.join(work, "beauty", f"{a.frame:04d}.png"), a.out)
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
    if not a.dry_run:
        os.makedirs(a.out, exist_ok=True)
    work = os.path.join(a.out, ".work")
    try:
        info = render_into(a.spec, work, extra, a.engine or shot["engine"], a)
        if info is None:
            return 0
        shutil.move(os.path.join(work, "beauty", f"{frames[0]:04d}.png"), os.path.join(a.out, "first.png"))
        shutil.move(os.path.join(work, "beauty", f"{frames[-1]:04d}.png"), os.path.join(a.out, "last.png"))
    finally:
        shutil.rmtree(work, ignore_errors=True)
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


def turntable_spec(src, look, seconds, base):
    """A shot3d.json that turns the camera once around an asset fitted to 2 m on a floor."""
    if not src.startswith(("preset:", "prim:")):
        src = os.path.abspath(src)
    return {
        "version": 1, "title": f"turntable {os.path.basename(src)}", "size": [1920, 1080], "fps": 24,
        "seconds": seconds, "seed": 0, "look": look, "engine": "eevee",
        "world": {"mist": 0.0, "sun": [40, 225]},
        "assets": [
            {"id": "floor", "src": "preset:ground", "params": {"width": 40, "depth": 40, "relief": 0}, "mask": False},
            {"id": "asset", "src": src, "fit": 2.0}],
        "camera": {"move": "orbit", "from": [0, -6.2, 1.7], "target": "asset", "degrees": 360, "ease": "linear",
                   "lens": 50},
        "passes": [], "depth_range": [0.5, 40]}


def cmd_turntable(a):
    look = a.look or "clay"
    if look not in spec.look_ids():
        raise Refused(f"--look {look!r} is not one of {', '.join(spec.look_ids())}")
    check_out_dir(a.out)
    data = turntable_spec(a.asset, look, a.seconds, a.out)
    errors = spec.validate(data, os.getcwd())
    if errors:
        raise Refused("turntable: " + "; ".join(errors))
    if a.dry_run:
        path = os.path.join(tempfile.gettempdir(), "turntable.json")
    else:
        os.makedirs(a.out, exist_ok=True)
        path = os.path.join(a.out, "turntable.json")
    write_json(path, data)
    extra = ["--preview"] if a.preview else []
    if a.size:
        extra += ["--size", "%dx%d" % size_of(a.size)]
    ff = ffmpeg_path()
    mp4 = os.path.join(os.path.abspath(a.out), "beauty.mp4")
    if not ff:
        extra += ["--mp4", mp4]
    info = render_into(path, a.out, extra, a.engine or "eevee", a, keep=("turntable.json",))
    if info is None:
        return 0
    if ff:
        encode_ffmpeg(ff, os.path.join(a.out, "beauty"), 1, info["fps"], mp4)
        info["mp4"] = {"file": "beauty.mp4", "encoder": "ffmpeg"}
        write_json(os.path.join(a.out, "render.json"), info)
    print(f"turntable {a.asset} ({look}) {info['frame_count']} frames · {info['mean_seconds_per_frame']} s/frame -> {a.out}")
    return 0


def cmd_lookbook(a):
    spec_path = a.spec or LOOKBOOK_SPEC
    shot = load_shot(spec_path)
    size = size_of(a.size)
    W, H, fps, n = spec.timeline(shot, False)
    frame = a.frame or (n + 1) // 2
    if not 1 <= frame <= n:
        raise Refused(f"--frame {frame} is outside 1..{n}")
    check_out_dir(a.out)
    if not a.dry_run:
        os.makedirs(a.out, exist_ok=True)
    book = {"tool": "tools/blender/blender.py lookbook", "spec": os.path.abspath(spec_path),
            "spec_sha256": sha256(spec_path), "frame": frame, "size": list(size), "looks": {}}
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
    if not a.dry_run:
        write_json(os.path.join(a.out, "lookbook.json"), book)
    return 0


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
    q = sp.add_parser("still", help="one beauty frame as a png")
    q.add_argument("spec")
    q.add_argument("--frame", type=int, required=True)
    q.add_argument("--out", required=True)
    q.add_argument("--size", default=None, help="WxH, same vertical field of view")
    q.add_argument("--samples", type=int, default=None)
    common(q)
    q = sp.add_parser("turntable", help="one camera turn around an asset (.glb/.gltf or preset:<id>)")
    q.add_argument("asset")
    q.add_argument("--out", required=True)
    q.add_argument("--seconds", type=float, default=4.0)
    q.add_argument("--size", default=None)
    common(q)
    q = sp.add_parser("keyframes", help="first.png + last.png + keyframes.json (for the local video model)")
    q.add_argument("spec")
    q.add_argument("--out", required=True)
    q.add_argument("--size", default=KEYFRAME_SIZE, help=f"WxH (default {KEYFRAME_SIZE}; draft 864x480)")
    q.add_argument("--samples", type=int, default=None)
    common(q, preview=False)
    q = sp.add_parser("lookbook", help="one still per look of tools/blender/looks.json")
    q.add_argument("--out", required=True)
    q.add_argument("--spec", default=None, help="default tools/blender/demo/lookbook.json")
    q.add_argument("--frame", type=int, default=None, help="default: the middle frame")
    q.add_argument("--size", default="960x540")
    q.add_argument("--engine", choices=spec.ENGINES, default=None)
    q.add_argument("--dry-run", action="store_true")
    q.add_argument("--timeout", type=float, default=None)
    a = p.parse_args(argv)
    fn = {"find": cmd_find, "check": cmd_check, "render": cmd_render, "still": cmd_still, "turntable": cmd_turntable,
          "keyframes": cmd_keyframes, "lookbook": cmd_lookbook}[a.cmd]
    try:
        return fn(a)
    except Refused as e:
        print(f"blender: refused: {e}", file=sys.stderr)
        return 2
    except Failed as e:
        print(f"blender: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
