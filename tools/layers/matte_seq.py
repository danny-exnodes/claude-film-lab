#!/usr/bin/env python3
"""Key a Seedance clip (or a folder of its raw frames) into RGBA frames for a `seq` layer, in one process, and
measure whether the result is usable. Free (Pillow, numpy, ffmpeg); no API call.

  python3 tools/layers/matte_seq.py IN [OUT_DIR] [--method chroma|rembg] [--key auto|#RRGGBB] [--low 40] [--high 200]
          [--every N] [--max-frames N] [--fps F] [--start-frame PNG] [--strip PNG] [--json FILE]
          [--rembg-model u2net] [--overwrite] [--strict]

IN is a clip (.mp4): it is decoded to OUT_DIR/raw/%06d.png, OUT_DIR defaults to <clip dir>/<clip stem>/ and the
  frame rate is read with ffprobe.
IN is a folder: only files named ^\\d{6}\\.png$ are read, the frame rate is --fps (default 24), OUT_DIR is required.
Keyed frames are written as RGBA PNG under the same names directly in OUT_DIR. With --every N only every Nth frame
is keyed, renumbered from 000001, and the reported frame rate is fps/N.

Methods
  chroma  flat key background (tools/layers/matte.py matte_chroma with despill, then cleanup low/high).
          --key auto = per-channel median of a 16 px border ring over the first, middle and last frame.
  rembg   one model session for the whole sequence, then cleanup low/high. Only for a background that is not
          flat: the edges of a per-frame model flicker. Refused when the model file is not on disk already.

Numbers (also in --json)
  bg_flat      largest per-channel standard deviation of the border ring (first, middle, last frame)
  bg_dirty     % of samples with alpha > 0 among pixels whose alpha is below 128 in every frame
  flicker      mean |alpha_t - alpha_(t-1)| over pixels whose raw RGB changed by less than 8 on every channel
  area_jitter  mean |A_t - A_(t-1)| / median A, A = number of pixels with alpha >= 128
  coverage     A as % of the frame: min/median/max
  edge frames  frames where a pixel with alpha >= 128 lies on the outermost row or column
  empty frames frames with A = 0
  start IoU    with --start-frame: frame 1's alpha >= 128 mask against the start frame keyed the same way

The last stdout line is the PLATES row for the shot. Run it once with --method chroma and once with --method rembg
into two folders to compare the two methods on the same clip.
Exit: 0 ok, 1 no frames or an ffmpeg failure, 2 usage, 4 --strict with any WARN (the frames are still written).
"""
import argparse, importlib.util, json, os, re, shutil, subprocess, sys
from pathlib import Path

import numpy as np
from PIL import Image

RE_FRAME = re.compile(r"^\d{6}\.png$")
RING = 16                 # px: width of the border ring sampled for the key colour and bg_flat
STATIC_RGB = 8            # a raw pixel is "static" when every channel changed by less than this between two frames
SOLID = 128               # alpha >= SOLID counts as subject
KEY_REFS = ("#00FF00", "#FF00FF")
PAPER = (0xEF, 0xE6, 0xD3)
STRIP_TILE_W = 640

# WARN thresholds. Calibrated on synthetic frames through libx264 only: re-check every one of them on the first
# real Seedance clip (its H.264 edges are softer) before trusting a silent run.
HAZE_MAX = 1.0            # bg_dirty, %
FLICKER_MAX = 2.0         # flicker, alpha levels
BG_FLAT_MAX = 12.0        # bg_flat, RGB levels
IOU_MIN = 0.8             # start IoU


def _load_matte():
    spec = importlib.util.spec_from_file_location("film_matte_for_seq", Path(__file__).resolve().parent / "matte.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


matte = _load_matte()     # only hex_rgb, cleanup and matte_chroma are used


def to_hex(rgb):
    return "#" + "".join(f"{int(round(float(v))):02X}" for v in rgb)


def num(x, digits):
    """Rounded for the report; whole numbers print without a decimal point only for fps."""
    return round(float(x), digits)


def fps_num(x):
    x = round(float(x), 3)
    return int(x) if x == int(x) else x


def frame_names(folder):
    return sorted(p.name for p in folder.iterdir() if RE_FRAME.match(p.name)) if folder.is_dir() else []


def load_rgb(path):
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.float32)


def ring_pixels(rgb):
    h, w = rgb.shape[:2]
    r = max(1, min(RING, h // 4, w // 4))
    return np.concatenate([rgb[:r].reshape(-1, 3), rgb[-r:].reshape(-1, 3),
                           rgb[r:-r, :r].reshape(-1, 3), rgb[r:-r, -r:].reshape(-1, 3)])


def rembg_model_file(model):
    """The model file when it is already on disk, else None (rembg would download it: no surprise download)."""
    home = Path(os.path.expanduser("~"))
    places = [home / ".rembg" / "models" / model, home / ".u2net"]
    env = os.environ.get("U2NET_HOME")
    if env:
        places = [Path(env) / "models" / model, Path(env)] + places
    for d in places:
        if (d / f"{model}.onnx").is_file():
            return d / f"{model}.onnx"
    return None


class Keyer:
    """rgb float32 HxWx3 -> (colour float HxWx3, alpha uint8 HxW)."""

    def __init__(self, method, key, low, high, model):
        self.method, self.key, self.low, self.high = method, key, low, high
        self.session = None
        if method == "rembg":
            from rembg import new_session
            self.session = new_session(model)

    def __call__(self, rgb):
        if self.method == "chroma":
            col, a = matte.matte_chroma(rgb, self.key, despill=True)
        else:
            from rembg import remove
            cut = remove(Image.fromarray(rgb.astype(np.uint8), "RGB"), session=self.session)
            col, a = rgb, np.asarray(cut.convert("RGBA"), dtype=np.float32)[..., 3]
        a = matte.cleanup(a, self.low, self.high)
        return col, np.round(a).astype(np.uint8)


def decode(clip, raw):
    """ffmpeg: clip -> raw/%06d.png. Returns an error text or None."""
    raw.mkdir(parents=True, exist_ok=True)
    for name in frame_names(raw):
        (raw / name).unlink()
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), str(raw / "%06d.png")],
                           capture_output=True, text=True)
    except FileNotFoundError:
        return "ffmpeg is not installed"
    if r.returncode != 0:
        return "ffmpeg could not decode the clip: " + (r.stderr.strip().splitlines() or ["?"])[-1]
    return None


def probe_fps(clip):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=r_frame_rate", "-of", "csv=p=0", str(clip)], capture_output=True, text=True)
    except FileNotFoundError:
        return None
    m = re.match(r"\s*(\d+)(?:/(\d+))?", r.stdout or "")
    if r.returncode != 0 or not m or int(m[1]) == 0 or (m[2] is not None and int(m[2]) == 0):
        return None
    return int(m[1]) / int(m[2] or 1)


def write_strip(path, files):
    """First, middle and last keyed frame over a checkerboard (top row) and over paper colour (bottom row)."""
    tiles = [Image.open(f).convert("RGBA") for f in files]
    w, h = tiles[0].size
    if w > STRIP_TILE_W:
        w, h = STRIP_TILE_W, max(1, round(h * STRIP_TILE_W / w))
        tiles = [t.resize((w, h), Image.LANCZOS) for t in tiles]
    yy, xx = np.mgrid[0:h, 0:w]
    check = np.where(((xx // 16 + yy // 16) % 2 == 0)[..., None], 255, 190).astype(np.uint8).repeat(3, axis=2)
    backs = [Image.fromarray(check, "RGB").convert("RGBA"), Image.new("RGBA", (w, h), PAPER + (255,))]
    sheet = Image.new("RGB", (w * len(tiles), h * 2))
    for row, back in enumerate(backs):
        for col, t in enumerate(tiles):
            sheet.paste(Image.alpha_composite(back, t).convert("RGB"), (col * w, row * h))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=__doc__.split("\n\n", 1)[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inp", metavar="IN", help="a clip (.mp4) or a folder of raw frames 000001.png ...")
    ap.add_argument("out_dir", metavar="OUT_DIR", nargs="?", help="default for a clip: <clip dir>/<clip stem>/")
    ap.add_argument("--method", choices=("chroma", "rembg"), default="chroma")
    ap.add_argument("--key", default="auto", help="auto (default) or #RRGGBB (the value given to keyframe.py --key)")
    ap.add_argument("--low", type=int, default=40); ap.add_argument("--high", type=int, default=200)
    ap.add_argument("--every", type=int, default=1, metavar="N", help="key every Nth frame only")
    ap.add_argument("--max-frames", type=int, metavar="N", help="stop after N keyed frames")
    ap.add_argument("--fps", type=float, help="frame rate of the raw frames (folder: default 24; clip: ffprobe)")
    ap.add_argument("--start-frame", metavar="PNG", help="the clip's start frame: reports the IoU with frame 1")
    ap.add_argument("--strip", metavar="PNG", help="write first/middle/last frame over checkerboard and paper")
    ap.add_argument("--json", metavar="FILE", help="write the report as JSON")
    ap.add_argument("--rembg-model", default="u2net")
    ap.add_argument("--overwrite", action="store_true", help="replace keyed frames already in OUT_DIR")
    ap.add_argument("--strict", action="store_true", help="exit 4 when there is any WARN")
    a = ap.parse_args(argv)

    def usage(msg):
        print(f"matte_seq: {msg}", file=sys.stderr)
        return 2

    def fail(msg):
        print(f"matte_seq: {msg}", file=sys.stderr)
        return 1

    # ---- arguments (nothing is written before these pass)
    if not 0 <= a.low < a.high <= 255:
        return usage(f"need 0 <= --low < --high <= 255 (got {a.low}, {a.high})")
    if a.every < 1 or (a.max_frames is not None and a.max_frames < 1) or (a.fps is not None and a.fps <= 0):
        return usage("--every, --max-frames and --fps must be positive")
    key = None
    if a.key.lower() != "auto":
        try:
            key = matte.hex_rgb(a.key)
        except ValueError as e:
            return usage(f"--key: {e} (or 'auto')")
    src = Path(a.inp)
    is_clip = src.is_file()
    if not is_clip and not src.is_dir():
        return usage(f"IN {src} is neither a clip nor a folder of frames")
    if is_clip:
        out = Path(a.out_dir) if a.out_dir else src.parent / src.stem
        raw = out / "raw"
    else:
        if not a.out_dir:
            return usage("IN is a folder of frames: OUT_DIR is required")
        out, raw = Path(a.out_dir), src
    if out.resolve() == raw.resolve():
        return usage(f"OUT_DIR is the raw folder {raw}: the keyed frames would replace the raw ones")
    if out.exists() and not out.is_dir():
        return usage(f"OUT_DIR {out} is not a folder")
    stale = frame_names(out)
    if stale and not a.overwrite:
        return usage(f"OUT_DIR {out} already holds {len(stale)} keyed frames: pass --overwrite or another folder")
    if a.start_frame and not Path(a.start_frame).is_file():
        return usage(f"--start-frame {a.start_frame} not found")
    if a.method == "rembg" and not rembg_model_file(a.rembg_model):
        return usage(f"rembg model {a.rembg_model}.onnx is not on disk (looked in ~/.rembg/models/{a.rembg_model}/, "
                     f"$U2NET_HOME and ~/.u2net/): not downloading it here. Install it first "
                     f"(.claude/hooks/session-start.sh does) or use --method chroma")

    # ---- frames
    if is_clip:
        fps = a.fps or probe_fps(src)
        if not fps:
            return fail(f"ffprobe/ffmpeg cannot read a video stream from {src}")
        err = decode(src, raw)
        if err:
            return fail(err)
    else:
        fps = a.fps or 24.0
    names = frame_names(raw)[::a.every]
    if a.max_frames:
        names = names[:a.max_frames]
    if not names:
        return fail(f"no frames named 000001.png ... in {raw}")
    n = len(names)
    fps_out = fps / a.every

    # ---- key colour and background flatness from the border ring of the first, middle and last frame
    ring = np.concatenate([ring_pixels(load_rgb(raw / names[i])) for i in sorted({0, n // 2, n - 1})])
    bg_flat = float(ring.std(axis=0).max())
    key_source = "given"
    if key is None:
        key, key_source = np.round(np.median(ring, axis=0)).astype(np.float32), "auto"
    dists = [float(np.sqrt(((key - matte.hex_rgb(ref)) ** 2).sum())) for ref in KEY_REFS]
    key_near = KEY_REFS[int(np.argmin(dists))]

    keyer = Keyer(a.method, key, a.low, a.high, a.rembg_model)
    out.mkdir(parents=True, exist_ok=True)
    for name in stale:
        (out / name).unlink()

    # ---- one pass: only the previous frame and the running masks stay in memory
    prev_rgb = prev_alpha = None
    always_bg = dirty = None
    flick_sum = flick_px = 0.0
    areas, edge_frames, size = [], 0, None
    for i, name in enumerate(names, 1):
        rgb = load_rgb(raw / name)
        if size is None:
            size = (rgb.shape[1], rgb.shape[0])
            always_bg = np.ones(rgb.shape[:2], bool)
            dirty = np.zeros(rgb.shape[:2], np.uint32)
        elif (rgb.shape[1], rgb.shape[0]) != size:
            return fail(f"{raw / name} is {rgb.shape[1]}x{rgb.shape[0]}, the first frame is {size[0]}x{size[1]}")
        col, alpha = keyer(rgb)
        rgba = np.dstack([np.round(np.clip(col, 0, 255)).astype(np.uint8), alpha])
        rgba[alpha == 0] = 0      # colour under alpha 0 is never drawn: dropping the key's noise makes small files
        Image.fromarray(rgba, "RGBA").save(out / f"{i:06d}.png", compress_level=3)
        solid = alpha >= SOLID
        always_bg &= ~solid
        dirty += alpha > 0
        areas.append(int(solid.sum()))
        if solid[0].any() or solid[-1].any() or solid[:, 0].any() or solid[:, -1].any():
            edge_frames += 1
        if prev_rgb is not None:
            static = (np.abs(rgb - prev_rgb) < STATIC_RGB).all(axis=2)
            flick_px += int(static.sum())
            flick_sum += float(np.abs(alpha.astype(np.int16) - prev_alpha)[static].sum())
        prev_rgb, prev_alpha = rgb, alpha.astype(np.int16)

    # ---- numbers
    px = size[0] * size[1]
    bg_px = int(always_bg.sum())
    area = np.asarray(areas, np.float64)
    med = float(np.median(area))
    iou = None
    if a.start_frame:
        _, sa = keyer(load_rgb(a.start_frame))
        sm = np.asarray(Image.fromarray(((sa >= SOLID) * 255).astype(np.uint8), "L").resize(size, Image.NEAREST)) > 0
        with Image.open(out / "000001.png") as im:
            first = np.asarray(im)[..., 3] >= SOLID
        union = int((sm | first).sum())
        iou = num((sm & first).sum() / union, 3) if union else 1.0
    rep = {
        "input": str(src), "out_dir": str(out), "method": a.method,
        "rembg_model": a.rembg_model if a.method == "rembg" else None,
        "frames": n, "fps": fps_num(fps_out), "size": list(size), "is_16_9": size[0] * 9 == size[1] * 16,
        "key": to_hex(key), "key_source": key_source, "key_distance": num(min(dists), 1), "key_nearest": key_near,
        "low": a.low, "high": a.high,
        "bg_flat": num(bg_flat, 1),
        "bg_dirty": num(100.0 * float(dirty[always_bg].sum()) / (bg_px * n), 2) if bg_px else 0.0,
        "flicker": num(flick_sum / flick_px, 3) if flick_px else 0.0,
        "area_jitter": num(np.abs(np.diff(area)).mean() / med, 4) if n > 1 and med > 0 else 0.0,
        "coverage": {k: num(100.0 * v / px, 2) for k, v in
                     (("min", area.min()), ("median", med), ("max", area.max()))},
        "edge_frames": edge_frames, "empty_frames": int((area == 0).sum()), "start_iou": iou,
    }
    w = []
    if rep["bg_dirty"] > HAZE_MAX:
        w.append(f"WARN HAZE: bg_dirty {rep['bg_dirty']} % > {HAZE_MAX} (a veil over the background; raise --low)")
    if rep["flicker"] > FLICKER_MAX:
        w.append(f"WARN FLICKER: flicker {rep['flicker']} > {FLICKER_MAX} on pixels that do not move")
    if edge_frames:
        w.append(f"WARN CROPPED: the subject touches the frame edge in {edge_frames} of {n} frames")
    if rep["empty_frames"]:
        w.append(f"WARN EMPTY: {rep['empty_frames']} of {n} frames have no subject")
    if a.method == "chroma" and rep["bg_flat"] > BG_FLAT_MAX:
        w.append(f"WARN BACKGROUND NOT FLAT: bg_flat {rep['bg_flat']} > {BG_FLAT_MAX}; "
                 f"compare with --method rembg into another folder")
    if iou is not None and iou < IOU_MIN:
        w.append(f"WARN REFRAMED: start IoU {iou} < {IOU_MIN} (frame 1 does not sit where the start frame does)")
    if not rep["is_16_9"]:
        w.append(f"WARN NOT 16:9: frames are {size[0]}x{size[1]}; a seq layer without place is stretched to the stage")
    rep["warnings"] = w
    rep["plates_row"] = (f"L4b: {{ seq: {{ pattern: '../../clips/{out.resolve().name}/{{n}}.png', digits: 6, start: 1, "
                         f"count: {n}, fps: {rep['fps']}, at: <t>, end: 'hold' }}, depth: 1.0, cover: false }},")

    # ---- report: at most 4 lines, the WARN lines, then the PLATES row
    how = (f"chroma key {rep['key']} ({key_source}, {rep['key_distance']} from {key_near})" if a.method == "chroma"
           else f"rembg {a.rembg_model}, border {rep['key']} ({rep['key_distance']} from {key_near})")
    print(f"matte_seq: {n} frames {size[0]}x{size[1]} ({'16:9' if rep['is_16_9'] else 'not 16:9'}) @ {rep['fps']} fps, "
          f"{how}, low {a.low} high {a.high} -> {out}")
    print(f"bg_flat {rep['bg_flat']}  bg_dirty {rep['bg_dirty']} %  flicker {rep['flicker']}  "
          f"area_jitter {rep['area_jitter']}")
    c = rep["coverage"]
    print(f"coverage {c['min']}/{c['median']}/{c['max']} % (min/median/max)  edge frames {edge_frames}  "
          f"empty frames {rep['empty_frames']}" + (f"  start IoU {iou}" if iou is not None else ""))
    extra = []
    if a.strip:
        write_strip(a.strip, [out / f"{i:06d}.png" for i in (1, n // 2 + 1, n)])
        extra.append(f"strip {a.strip}")
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        extra.append(f"json {a.json}")
    if extra:
        print("  ".join(extra))
    for line in w:
        print(line)
    print(rep["plates_row"])
    return 4 if (a.strict and w) else 0


if __name__ == "__main__":
    sys.exit(main())
