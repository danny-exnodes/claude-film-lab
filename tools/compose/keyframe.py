#!/usr/bin/env python3
"""Start frame for a Seedance clip that becomes a layer: the character plate on a flat key colour, at exactly the place
and size it has on the 1920x1080 stage (camera at rest). Free (Pillow); no API call.

  python3 tools/compose/keyframe.py out/<p>/ep01/plates/ep01_s03_L4_bac-thi_v02.png out/<p>/ep01/clips/ep01_s03_start_v01.png \
      --x 860 --y 905 --h 640 --pivot feet --anchors projects/<p>/ep01-<slug>/anchors.json --key "#00FF00"
  # project split into books: out/<p>/q01t01/plates/q01t01_s03_L4_bac-di_v02.png, projects/<p>/q01-t01-<slug>/anchors.json

--x/--y/--h/--pivot are the plate's `place` in PLATES (pivot: center | bottom | top | an anchor point name).
--key: style.yaml matte.key_bg (a colour far from the character's own: green for ink, magenta for green creatures).
The frame is 16:9, so Seedance returns 16:9 (a square input gives a square clip; do not pass --ratio with --image: Seedance 2.5 rejects it).
Keyed back to PNG frames (python3 tools/layers/matte_seq.py <clip>.mp4 --start-frame <this frame> --strict), the
clip goes into PLATES with seq and NO place: it then covers the stage exactly like this frame, and lines up with the
plate it replaces.
While writing the frame, a WARN on stderr (exit code unchanged) says when the figure is cut by the frame edge and
when the plate has opaque pixels close to the key colour (WARN KEY NEAR SUBJECT: pick the other key colour).

Before every paid clip, check the frame that is about to be sent (free, never writes):

  python3 tools/compose/keyframe.py --check out/<p>/ep01/clips/ep01_s03_start_v01.png --key "#00FF00"

Exit 1 unless the image is 1920x1080, has no alpha channel and at least 98% of its 16 px border ring is the key
colour; the message names the test that failed. On success it prints the bounding box of the figure, with a WARN
(exit 0) when the box touches a frame edge. A frame with no figure at all (every pixel is the key colour) is
exit 1 too: there is nothing to animate.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor

STAGE = (1920, 1080)
RING = 16             # px: width of the border ring that must be the key colour
KEY_TOL = 12.0        # RGB distance from the key that still counts as the key colour
RING_MIN = 0.98       # share of the border ring that must be the key colour
NEAR_KEY = 60.0       # an opaque plate pixel this close to the key (RGB distance) will be keyed out of the clip
OPAQUE = 128          # plate alpha from which a pixel counts as part of the figure


def to_hex(key):
    return "#%02X%02X%02X" % tuple(key)


def key_distance(rgb, key):
    """rgb uint8 HxWx3 -> RGB distance of every pixel from the key colour."""
    d = rgb.astype(np.float32) - np.asarray(key, np.float32).reshape(1, 1, 3)
    return np.sqrt((d * d).sum(axis=2))


def check(path, key):
    """The free guard before a paid clip. Returns the exit code; writes nothing."""
    def fail(msg):
        print(f"keyframe --check FAIL {path}: {msg}", file=sys.stderr)
        return 1

    try:
        with Image.open(path) as im:
            im.load()
            size, mode = im.size, im.mode
            has_alpha = "A" in im.getbands() or "transparency" in im.info
            rgb = np.asarray(im.convert("RGB"))
    except (OSError, ValueError) as e:
        return fail(f"cannot read the image ({e})")
    if size != STAGE:
        return fail(f"size is {size[0]}x{size[1]}, need {STAGE[0]}x{STAGE[1]} (16:9): a start frame of another "
                    f"shape returns a clip of that shape. Make it with keyframe.py, never a file from plates/")
    if has_alpha:
        return fail(f"the image has an alpha channel (mode {mode}): the start frame is a flat RGB picture on the "
                    f"key colour, not a matted plate")
    near = key_distance(rgb, key) <= KEY_TOL
    ring = np.ones(near.shape, bool)
    ring[RING:-RING, RING:-RING] = False
    share = float(near[ring].mean())
    if share < RING_MIN:
        return fail(f"border is not the key colour: {share * 100:.1f}% of the {RING} px border ring is within "
                    f"{KEY_TOL:g} of {to_hex(key)}, need {RING_MIN * 100:.0f}% (wrong --key, a background that is "
                    f"not flat, or a figure cut by the frame)")
    ys, xs = np.nonzero(~near)
    if not len(xs):
        return fail(f"no figure: every pixel is within {KEY_TOL:g} of the key colour {to_hex(key)} (plate placed "
                    f"off the stage, an empty plate, or a plate of the key colour)")
    print(f"keyframe --check ok {path}: {STAGE[0]}x{STAGE[1]} RGB, border {share * 100:.1f}% key {to_hex(key)}")
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    print(f"figure bbox {x0},{y0}-{x1},{y1} ({x1 - x0}x{y1 - y0})")
    sides = [n for n, hit in (("left", x0 == 0), ("top", y0 == 0), ("right", x1 == STAGE[0]),
                              ("bottom", y1 == STAGE[1])) if hit]
    if sides:
        print(f"WARN FIGURE AT THE EDGE: the figure touches the {', '.join(sides)} frame edge; "
              f"Seedance cannot draw what is outside the frame")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plate", nargs="?"); ap.add_argument("out", nargs="?")
    ap.add_argument("--x", type=float, default=960); ap.add_argument("--y", type=float, default=540)
    ap.add_argument("--h", type=float, help="height on the stage in px (default: the plate's own height)")
    ap.add_argument("--pivot", default="center")
    ap.add_argument("--anchors", help="anchors.json, when the pivot is an anchor point")
    ap.add_argument("--key", default="#00FF00", help="flat key colour (style.yaml matte.key_bg)")
    ap.add_argument("--check", metavar="START.png",
                    help="check an existing start frame against --key instead of writing one (exit 1 when unusable)")
    a = ap.parse_args()
    try:
        key = ImageColor.getrgb(a.key)[:3]
    except ValueError:
        ap.error(f"--key {a.key!r} is not a colour (use #RRGGBB)")
    if a.check:
        if a.plate or a.out:
            ap.error("--check takes only the start frame and --key (no PLATE/OUT: it never writes)")
        sys.exit(check(a.check, key))
    if not a.plate or not a.out:
        ap.error("the following arguments are required: plate, out (or --check START.png)")
    if Path(a.out).resolve() == Path(a.plate).resolve():
        ap.error(f"OUT is the plate itself ({a.plate}): the start frame would replace it")

    plate = Image.open(a.plate).convert("RGBA")
    w, h = plate.size
    if a.pivot in ("center", "bottom", "top"):
        pv = {"center": (w / 2, h / 2), "bottom": (w / 2, h), "top": (w / 2, 0)}[a.pivot]
    else:
        if not a.anchors:
            raise SystemExit(f"pivot {a.pivot!r} is an anchor name: pass --anchors")
        data = json.loads(Path(a.anchors).read_text(encoding="utf-8"))
        entry = data.get("plates", data).get(Path(a.plate).name) or {}
        points = entry.get("points", entry)          # tools/layers/anchors.py writes the points flat
        if a.pivot not in points:
            raise SystemExit(f"no point {a.pivot!r} for {Path(a.plate).name} in {a.anchors}")
        sx, sy = entry.get("size") or entry.get("_size") or [w, h]
        px, py = points[a.pivot]
        pv = (px * w / sx, py * h / sy)
    s = (a.h / h) if a.h else 1.0
    frame = Image.new("RGBA", STAGE, a.key)
    scaled = plate.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
    left, top = round(a.x - pv[0] * s), round(a.y - pv[1] * s)
    frame.paste(scaled, (left, top), scaled)                                        # works past the frame edge too
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    frame.convert("RGB").save(a.out)
    print(f"{a.out}: 1920x1080, plate at scale {s:.4f}, key {a.key}")

    # Warnings only (stderr, exit code unchanged): both make the paid clip hard to key or to line up.
    box = scaled.getchannel("A").point(lambda v: 255 if v >= OPAQUE else 0).getbbox()
    if box:
        cut = [n for n, hit in (("left", left + box[0] < 0), ("top", top + box[1] < 0),
                                ("right", left + box[2] > STAGE[0]), ("bottom", top + box[3] > STAGE[1])) if hit]
        if cut:
            print(f"WARN FIGURE CUT: the figure is cut by the frame edge ({', '.join(cut)}); Seedance cannot draw "
                  f"what is outside the frame, and --check fails when more than 2% of the border is covered",
                  file=sys.stderr)
    px = np.asarray(plate)
    near = int(((px[..., 3] >= OPAQUE) & (key_distance(px[..., :3], key) <= NEAR_KEY)).sum())
    if near:
        print(f"WARN KEY NEAR SUBJECT: pick the other key colour ({near} opaque plate pixels are within "
              f"{NEAR_KEY:g} of {to_hex(key)} and would be keyed out of the clip)", file=sys.stderr)


if __name__ == "__main__":
    main()
