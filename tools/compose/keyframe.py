#!/usr/bin/env python3
"""Start frame for a Seedance clip that becomes a layer: the character plate on a flat key colour, at exactly the place
and size it has on the 1920x1080 stage (camera at rest). Free (Pillow); no API call.

  python3 tools/compose/keyframe.py out/<s>/ep01/plates/ep01_s03_L4_bac-thi_v02.png out/<s>/ep01/clips/ep01_s03_start_v01.png \
      --x 860 --y 905 --h 640 --pivot feet --anchors series/<s>/ep01-<slug>/anchors.json --key "#00FF00"

--x/--y/--h/--pivot are the plate's `place` in PLATES (pivot: center | bottom | top | an anchor point name).
--key: style.yaml matte.key_bg (a colour far from the character's own: green for ink, magenta for green creatures).
The frame is 16:9, so Seedance returns 16:9 (a square input gives a square clip; pass --ratio 16:9 to ark.py anyway).
Keyed back to PNG frames (tools/layers/matte.py chroma), the clip goes into PLATES with seq and NO place: it then
covers the stage exactly like this frame, and lines up with the plate it replaces.
"""
import argparse
import json
from pathlib import Path

from PIL import Image

STAGE = (1920, 1080)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plate"); ap.add_argument("out")
    ap.add_argument("--x", type=float, default=960); ap.add_argument("--y", type=float, default=540)
    ap.add_argument("--h", type=float, help="height on the stage in px (default: the plate's own height)")
    ap.add_argument("--pivot", default="center")
    ap.add_argument("--anchors", help="anchors.json, when the pivot is an anchor point")
    ap.add_argument("--key", default="#00FF00", help="flat key colour (style.yaml matte.key_bg)")
    a = ap.parse_args()

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
    frame.paste(scaled, (round(a.x - pv[0] * s), round(a.y - pv[1] * s)), scaled)   # works past the frame edge too
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    frame.convert("RGB").save(a.out)
    print(f"{a.out}: 1920x1080, plate at scale {s:.4f}, key {a.key}")


if __name__ == "__main__":
    main()
