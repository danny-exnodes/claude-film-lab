#!/usr/bin/env python3
"""Free previews of the TOON kit (characters drawn in code, `method: code`): stills, turntables, clips, lookbook.

  python3 tools/toon/toon.py still <style|look> [--character C.json] [--t 1.5] [--size 1920x1080] --out still.png
  python3 tools/toon/toon.py turntable [--character C.json] [--style hoat-hinh-phang] --out turntable.png
  python3 tools/toon/toon.py clip <style|look> [--character C.json] [--seconds 4.5] [--draft] --out clip.mp4
  python3 tools/toon/toon.py lookbook [--out out/_lab/lookbook] [--seconds 4.5] [--draft] [--only 1,6,10] [--size WxH]
  python3 tools/toon/toon.py reel SPEC.json --out reel.mp4 [--draft]

<style> is a style pack with `engine: code` (styles/<id>/style.yaml, its render block); <look> is a look id of
tools/toon/looks.json (a geometry look, optionally +post: `flat-toon+riso`). The default character is the lab mascot
tools/toon/demo/giot.json. Rendering runs tools/toon/page.html in headless Chromium (tools/toon/shoot.cjs, Playwright,
software WebGL); clips and the lookbook are encoded with ffmpeg (H.264, yuv420p, no audio). No API call, no cost.

Exit codes: 0 ok · 1 render failed · 2 bad arguments.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
STYLES = REPO / "styles"
DEMO = HERE / "demo" / "giot.json"
LOOKS = json.loads((HERE / "looks.json").read_text(encoding="utf-8"))
THREE_DEFAULT = "/opt/film-lab/vendor/three/build/three.module.js"

# The lookbook: the ten code styles in the order of the style index (issue #38), then the pop-up book (11)
LOOKBOOK = ["dat-nan-3d", "hoat-hinh-phang", "ban-ve-ky-thuat", "in-riso", "pixel-16bit",
            "bong-muc", "ong-cao-su", "chu-ascii", "bia-cat-dan", "low-poly-90", "sach-pop-up"]

# One action for every style: walk in, turn to the camera, wave, turn and walk out.
ACTION = {
    "start": {"at": [-2.3, 0], "face": "right"},
    "clips": [
        {"do": "walk", "t": [0.0, 1.7], "to": [0, 0]},
        {"do": "turn", "t": [1.7, 2.05], "face": "camera"},
        {"do": "wave", "t": [2.05, 3.25], "hand": "R"},
        {"do": "turn", "t": [3.25, 3.55], "face": "right"},
        {"do": "walk", "t": [3.55, 4.5], "to": [1.6, 0]},
    ],
}
CAMERA = {"pos": [0, 0.78, 4.2], "target": [0, 0.56, 0], "fov": 32,
          "move": {"t": [0, 4.5], "pos": [0.25, 0.74, 3.7], "target": [0.15, 0.56, 0], "ease": "inOut"}}


def fail(msg, code=1):
    print(f"toon: {msg}", file=sys.stderr)
    sys.exit(code)


def size_of(text):
    try:
        w, h = (int(x) for x in text.lower().split("x"))
        assert w > 0 and h > 0
        return w, h
    except Exception:
        fail(f"--size must be WxH (got {text!r})", 2)


def load_yaml(path):
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def style_render(name):
    """A style id or a look id -> (render block, display name, vi name)."""
    sdir = STYLES / name
    if (sdir / "style.yaml").is_file():
        y = load_yaml(sdir / "style.yaml")
        if y.get("engine") != "code" or not isinstance(y.get("render"), dict):
            fail(f"styles/{name} is not an engine: code style pack (no render block)", 2)
        r = dict(y["render"])
        posts = [q["id"] if isinstance(q, dict) else q for q in (r.get("post") or [])]
        info = (LOOKS["posts"].get(posts[-1]) if posts else None) or LOOKS["looks"].get(r.get("look"), {})
        return r, y.get("name_en") or info.get("name") or name, y.get("name") or info.get("name_vi") or name
    look, _, post = name.partition("+")
    if look not in LOOKS["looks"]:
        fail(f"'{name}' is neither a style pack (styles/<id>/style.yaml) nor a look of tools/toon/looks.json", 2)
    if post and post not in LOOKS["posts"]:
        fail(f"post '{post}' is not in tools/toon/looks.json", 2)
    r = {"engine": LOOKS["looks"][look]["engine"], "look": look, "post": [post] if post else []}
    info = LOOKS["posts"][post] if post else LOOKS["looks"][look]
    return r, info["name"], info["name_vi"]


def scene_for(render, character, timeline=None, camera=None, seed=7):
    post = [p if isinstance(p, (str, dict)) else str(p) for p in (render.get("post") or [])]
    return {"look": render["look"], "post": post, "hold": render.get("hold"), "seed": render.get("seed", seed),
            "cast": [{"character": character, "timeline": timeline or ACTION}],
            "camera": camera or render.get("camera") or CAMERA, "env": render.get("env") or {},
            "pal": render.get("palette") or {}, "opts": render.get("opts") or {}}


def character_of(path):
    p = Path(path) if path else DEMO
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        fail(f"character {p}: {e}", 2)


def three_url():
    p = os.environ.get("FILM_THREE", THREE_DEFAULT)
    return "file://" + p if not p.startswith("file://") else p


def shoot(spec, out_dir, frames="all", jpg=False):
    node = shutil.which("node")
    if not node:
        fail("node is not installed")
    spec = dict(spec, three=three_url())
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)
        sp = f.name
    try:
        cmd = [node, str(HERE / "shoot.cjs"), "--spec", sp, "--out", str(out_dir), "--frames", frames] + (["--jpg"] if jpg else [])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    finally:
        os.unlink(sp)
    if r.returncode != 0:
        fail("render failed:\n" + (r.stderr or r.stdout)[-4000:])
    info = json.loads(r.stdout.strip().splitlines()[-1])
    for w in info.get("warnings") or []:
        print(f"WARN {w}")
    return info


def encode(frames_dir, fps, out, ext):
    ff = shutil.which("ffmpeg")
    if not ff:
        fail("ffmpeg is not installed")
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ff, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(Path(frames_dir) / f"%06d.{ext}"),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium", "-movflags", "+faststart", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        fail("ffmpeg failed: " + r.stderr[-2000:])


def contact_sheet(images, cols, out, cell_w=640):
    from PIL import Image
    ims = [Image.open(p).convert("RGB") for p in images]
    w, h = ims[0].size
    ch = int(cell_w * h / w)
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w + (cols + 1) * 8, rows * ch + (rows + 1) * 8), (24, 24, 24))
    for i, im in enumerate(ims):
        r, c = divmod(i, cols)
        sheet.paste(im.resize((cell_w, ch), Image.LANCZOS), (8 + c * (cell_w + 8), 8 + r * (ch + 8)))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)


def guard_out(path, overwrite):
    if path.exists() and not overwrite:
        fail(f"{path} exists (pass --overwrite to replace it)", 2)


# ------------------------------------------------------------------ commands
def cmd_still(a):
    w, h = size_of(a.size)
    out = Path(a.out)
    guard_out(out, a.overwrite)
    render, name, vi = style_render(a.style)
    spec = {"w": w, "h": h, "fps": 24, "segments": [{"dur": max(a.t + 0.1, 0.5), "scene": scene_for(render, character_of(a.character))}]}
    with tempfile.TemporaryDirectory() as d:
        info = shoot(spec, d, frames=str(int(round(a.t * 24))))
        src = next(Path(d).glob("*.png"))
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out)
    print(f"still {name} ({vi}) t={a.t}s -> {out} · {info['ms_per_frame']} ms/frame · webgl {info.get('webgl')}")


def cmd_turntable(a):
    w, h = size_of(a.size)
    out = Path(a.out)
    guard_out(out, a.overwrite)
    render, name, vi = style_render(a.style)
    ch = character_of(a.character)
    cam = {"pos": [0, 0.62, 3.0], "target": [0, 0.5, 0], "fov": 30}
    segs = [{"dur": 0.5, "scene": scene_for(render, ch, {"start": {"at": [0, 0], "face": f}, "blink": False}, cam)}
            for f in (0, 0.7854, 1.5708, 3.1416)]
    spec = {"w": w, "h": h, "fps": 24, "segments": segs}
    with tempfile.TemporaryDirectory() as d:
        info = shoot(spec, d, frames=",".join(str(i * 12) for i in range(4)))
        contact_sheet(sorted(Path(d).glob("*.png")), 4, out, cell_w=min(w, 720))
    print(f"turntable {ch.get('name', '?')} in {name} ({vi}): front, 3/4, side, back -> {out} · {info['ms_per_frame']} ms/frame")


def cmd_clip(a):
    w, h = (960, 540) if a.draft else size_of(a.size)
    out = Path(a.out)
    guard_out(out, a.overwrite)
    render, name, vi = style_render(a.style)
    spec = {"w": w, "h": h, "fps": 24, "segments": [{"dur": a.seconds, "scene": scene_for(render, character_of(a.character))}]}
    with tempfile.TemporaryDirectory() as d:
        info = shoot(spec, d, jpg=True)
        encode(d, 24, out, "jpg")
    print(f"clip {name} ({vi}) {a.seconds}s {w}x{h} -> {out} · {info['ms_per_frame']} ms/frame")


def cmd_reel(a):
    out = Path(a.out)
    guard_out(out, a.overwrite)
    try:
        spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        fail(f"{a.spec}: {e}", 2)
    if a.draft:
        spec["w"], spec["h"] = 960, 540
    with tempfile.TemporaryDirectory() as d:
        info = shoot(spec, d, jpg=True)
        encode(d, spec.get("fps", 24), out, "jpg")
    print(f"reel {info['frames']} frames -> {out} · {info['ms_per_frame']} ms/frame")


def cmd_lookbook(a):
    w, h = (960, 540) if a.draft else size_of(a.size)
    out = Path(a.out)
    ids = LOOKBOOK
    picks = list(range(1, len(ids) + 1))
    if a.only:
        try:
            picks = [int(x) for x in a.only.split(",") if x.strip()]
            assert all(1 <= n <= len(ids) for n in picks)
        except Exception:
            fail(f"--only takes numbers 1-{len(ids)} (got {a.only!r})", 2)
    ch = character_of(a.character)
    segs = []
    for n in picks:
        render, name, vi = style_render(ids[n - 1])
        segs.append({"dur": a.seconds, "scene": scene_for(render, ch), "label": {"n": n, "name": name, "vi": vi}})
    spec = {"w": w, "h": h, "fps": 24, "segments": segs}
    frames = out / "frames"
    if frames.exists():
        shutil.rmtree(frames)
    frames.mkdir(parents=True)
    info = shoot(spec, frames, jpg=True)
    video = out / ("lookbook-draft.mp4" if a.draft else "lookbook.mp4")
    encode(frames, 24, video, "jpg")
    per = int(round(a.seconds * 24))
    mids = [frames / f"{i * per + int(per * 0.55):06d}.jpg" for i in range(len(segs))]
    contact_sheet(mids, 5 if len(mids) > 4 else len(mids), out / "sheet.png", cell_w=640)
    shutil.rmtree(frames)
    print(f"lookbook {len(segs)} style(s) x {a.seconds}s {w}x{h} -> {video}, {out / 'sheet.png'} · {info['ms_per_frame']} ms/frame")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__.split("\n\n", 1)[1])
    sp = p.add_subparsers(dest="cmd", required=True)

    def common(q, size="1920x1080"):
        q.add_argument("--character", default=None, help="character.json (default: tools/toon/demo/giot.json)")
        q.add_argument("--size", default=size)
        q.add_argument("--out", required=True)
        q.add_argument("--overwrite", action="store_true")

    s = sp.add_parser("still"); s.add_argument("style"); s.add_argument("--t", type=float, default=2.6); common(s)
    s = sp.add_parser("turntable"); s.add_argument("--style", default="hoat-hinh-phang"); common(s, "960x720")
    s = sp.add_parser("clip"); s.add_argument("style"); s.add_argument("--seconds", type=float, default=4.5)
    s.add_argument("--draft", action="store_true"); common(s)
    s = sp.add_parser("reel"); s.add_argument("spec"); s.add_argument("--out", required=True)
    s.add_argument("--draft", action="store_true"); s.add_argument("--overwrite", action="store_true")
    s = sp.add_parser("lookbook"); s.add_argument("--out", default=str(REPO / "out" / "_lab" / "lookbook"))
    s.add_argument("--seconds", type=float, default=4.5); s.add_argument("--draft", action="store_true")
    s.add_argument("--only", default=None); s.add_argument("--size", default="1920x1080")
    s.add_argument("--character", default=None)
    a = p.parse_args(argv)
    {"still": cmd_still, "turntable": cmd_turntable, "clip": cmd_clip, "reel": cmd_reel, "lookbook": cmd_lookbook}[a.cmd](a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
