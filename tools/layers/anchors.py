#!/usr/bin/env python3
"""Anchor points for layer images (series/<series>/ep<NN>-<slug>/anchors.json, docs/CONVENTIONS.md §4).

  python3 tools/layers/anchors.py set  ANCHORS_JSON FILE NAME X Y     add or update a point (pixel coords)
  python3 tools/layers/anchors.py mark IMAGE ANCHORS_JSON OUT         draw labelled crosshairs for IMAGE's points

JSON shape: {"<layer file name>": {"<point name>": [x, y], ...}, ...}. FILE/IMAGE are matched by base name.
Transparent layers are drawn over a grey checkerboard so the crosshairs and edges are visible.
"""
import argparse, json, os, re, sys, tempfile

from PIL import Image, ImageDraw, ImageFont

RE_LAYER_FILE = re.compile(r"^ep\d{2}_s\d{2}_(L[1-4]|P\d+-[a-z0-9-]+|FX)_[a-z0-9-]+_v\d{2}\.(png|jpg)$")


def load(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: expected an object {{file: {{point: [x, y]}}}}")
    return data


def save(path, data):
    """Atomic write, keys sorted so diffs stay small."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".anchors-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def num(s):
    x = float(s)
    return int(x) if x.is_integer() else round(x, 2)


def set_point(path, file, name, x, y):
    key = os.path.basename(file)
    if not RE_LAYER_FILE.match(key):
        print(f"warning: {key} does not follow the layer naming convention (docs/CONVENTIONS.md §2)", file=sys.stderr)
    data = load(path)
    pts = data.setdefault(key, {})
    old = pts.get(name)
    pts[name] = [num(x), num(y)]
    save(path, data)
    return old, pts[name]


def checker(size, cell=16):
    w, h = size
    im = Image.new("RGB", size, (200, 200, 200))
    d = ImageDraw.Draw(im)
    for yy in range(0, h, cell):
        for xx in range((yy // cell) % 2 * cell, w, 2 * cell):
            d.rectangle([xx, yy, xx + cell - 1, yy + cell - 1], fill=(150, 150, 150))
    return im


def font(px):
    try:
        return ImageFont.load_default(size=px)
    except TypeError:   # Pillow < 10.1
        return ImageFont.load_default()


def mark(image, anchors, out):
    key = os.path.basename(image)
    pts = load(anchors).get(key)
    if not pts:
        raise SystemExit(f"{anchors}: no points stored for {key}")
    with Image.open(image) as src:
        rgba = src.convert("RGBA")
    base = checker(rgba.size)
    base.paste(rgba, mask=rgba.getchannel("A"))
    d = ImageDraw.Draw(base)
    long_edge = max(base.size)
    arm = max(8, long_edge // 60)
    lw = max(1, long_edge // 600)
    f = font(max(12, long_edge // 70))
    for name, xy in sorted(pts.items()):
        x, y = float(xy[0]), float(xy[1])
        if not (0 <= x < base.width and 0 <= y < base.height):
            print(f"warning: {name} ({x:g}, {y:g}) is outside the {base.width}x{base.height} image", file=sys.stderr)
        for colour, width in (((0, 0, 0), lw + 2), ((255, 230, 0), lw)):
            d.line([(x - arm, y), (x + arm, y)], fill=colour, width=width)
            d.line([(x, y - arm), (x, y + arm)], fill=colour, width=width)
            d.ellipse([x - arm / 2, y - arm / 2, x + arm / 2, y + arm / 2], outline=colour, width=width)
        label = f"{name} ({x:g},{y:g})"
        d.text((x + arm + 4, y - arm - 2), label, fill=(255, 230, 0), font=f, stroke_width=2, stroke_fill=(0, 0, 0))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    base.save(out)
    return len(pts)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("set", help="add/update a point")
    s.add_argument("anchors"); s.add_argument("file"); s.add_argument("name"); s.add_argument("x"); s.add_argument("y")
    m = sp.add_parser("mark", help="draw the points stored for IMAGE")
    m.add_argument("image"); m.add_argument("anchors"); m.add_argument("out")
    a = p.parse_args(argv)
    if a.cmd == "set":
        try:
            old, new = set_point(a.anchors, a.file, a.name, a.x, a.y)
        except ValueError:
            p.error("X and Y must be numbers (pixels)")
        print(f"{'updated' if old else 'added'} {os.path.basename(a.file)} {a.name} = {new}" + (f" (was {old})" if old else ""))
    else:
        n = mark(a.image, a.anchors, a.out)
        print(f"saved {a.out} ({n} point(s))")


if __name__ == "__main__":
    main()
