#!/usr/bin/env python3
"""Anchor points for layer images (projects/<project>/<episode folder>/anchors.json, docs/CONVENTIONS.md §4).

  python3 tools/layers/anchors.py set  ANCHORS_JSON FILE NAME X Y     add or update a point (pixel coords)
  python3 tools/layers/anchors.py mark IMAGE ANCHORS_JSON OUT         draw labelled crosshairs for IMAGE's points

JSON shape: {"<layer file name>": {"<point name>": [x, y], ...}, ...}. FILE/IMAGE are matched by base name.
Transparent layers are drawn over a grey checkerboard so the crosshairs and edges are visible.
`set` holds an exclusive fcntl.flock on a hidden sidecar next to the JSON (`.anchors.json.lock`: a dotfile,
so Drive sync does not offer it for upload) for the whole read-modify-write (up to 3 plate-makers run in
parallel, CONVENTIONS §10), then replaces the JSON atomically.
Point names are ASCII letters, digits, `_` and `-`; X and Y must be finite numbers (the file stays strict JSON).
"""
import argparse, contextlib, fcntl, json, math, os, re, sys, tempfile

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import episode_id  # noqa: E402  (tools/episode_id.py: episode ids, shot ids and layer codes, CONVENTIONS §2)

RE_LAYER_FILE = episode_id.RE_LAYER_FILE   # pose plates (L4b...) and s<NNN> shots included


def load(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise SystemExit(f"{path}: not valid JSON ({e})")
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: expected an object {{file: {{point: [x, y]}}}}")
    return data


def save(path, data):
    """Atomic write, keys sorted so diffs stay small."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".anchors-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)   # NaN is not JSON
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def locked(path):
    """Exclusive lock on the sidecar `.<basename>.lock` in the same folder (the JSON itself is replaced, so
    it cannot carry the lock; a dotfile, because drive_sync uploads every other file of the episode folder)."""
    d, base = os.path.split(os.path.abspath(path))
    lock = os.path.join(d, "." + base + ".lock")
    os.makedirs(d, exist_ok=True)
    with open(lock, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def num(s):
    """Pixel coordinate; ValueError for anything that is not a finite number."""
    x = float(s)
    if not math.isfinite(x):
        raise ValueError(f"not a finite number: {s!r}")
    return int(x) if x.is_integer() else round(x, 2)


RE_POINT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$", re.ASCII)
RESERVED_NAMES = ("size", "_size", "points", "boxes", "version")   # keys with a meaning of their own


def check_name(name):
    if not RE_POINT_NAME.fullmatch(name):     # fullmatch: `$` alone would let a trailing newline through
        raise ValueError(f"point name {name!r} must be ASCII letters, digits, _ or - and start with a letter or digit")
    if name in RESERVED_NAMES:
        raise ValueError(f"point name {name!r} is reserved ({', '.join(RESERVED_NAMES)})")


def set_point(path, file, name, x, y):
    key = os.path.basename(file)
    if not RE_LAYER_FILE.match(key):
        print(f"warning: {key} does not follow the layer naming convention (docs/CONVENTIONS.md §2)", file=sys.stderr)
    check_name(name)
    point = [num(x), num(y)]          # validate before taking the lock
    with locked(path):
        data = load(path)
        pts = data.setdefault(key, {})
        old = pts.get(name)
        pts[name] = point
        save(path, data)
    return old, point


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
            x, y = num(a.x), num(a.y)
        except ValueError:
            p.error("X and Y must be finite numbers (pixels)")
        try:
            check_name(a.name)
        except ValueError as e:
            p.error(str(e))
        old, new = set_point(a.anchors, a.file, a.name, x, y)
        print(f"{'updated' if old else 'added'} {os.path.basename(a.file)} {a.name} = {new}" + (f" (was {old})" if old else ""))
    else:
        n = mark(a.image, a.anchors, a.out)
        print(f"saved {a.out} ({n} point(s))")


if __name__ == "__main__":
    main()
