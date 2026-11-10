#!/usr/bin/env python3
"""Lanczos upscale of a layer image, alpha preserved.

  python3 tools/layers/upscale.py IN OUT --factor 2
  python3 tools/layers/upscale.py IN OUT --long-edge 3840

PLACEHOLDER: this is plain Lanczos resampling (Pillow), not super-resolution; it adds no detail.
Replace it with a real super-resolution model (e.g. Real-ESRGAN) when one is available; keep this CLI
so callers do not change. RGBA is resampled premultiplied (Pillow does this for RGBA), so transparent
pixels do not bleed dark fringes into edges.
"""
import argparse, os, sys

from PIL import Image


def target_size(size, factor=None, long_edge=None):
    w, h = size
    if factor is not None:
        if factor <= 0:
            raise ValueError("--factor must be > 0")
        s = factor
    else:
        if long_edge <= 0:
            raise ValueError("--long-edge must be > 0")
        s = long_edge / max(w, h)
    return max(1, round(w * s)), max(1, round(h * s))


def upscale(im, factor=None, long_edge=None):
    size = target_size(im.size, factor, long_edge)
    if im.mode not in ("RGB", "RGBA", "L", "LA"):
        im = im.convert("RGBA" if "A" in im.getbands() or "transparency" in im.info else "RGB")
    return im.resize(size, Image.LANCZOS)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("inp", metavar="IN"); p.add_argument("out", metavar="OUT")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--factor", type=float, help="scale factor, e.g. 2")
    g.add_argument("--long-edge", type=int, help="target long edge in px")
    a = p.parse_args(argv)
    with Image.open(a.inp) as src:
        src.load()
        try:
            out = upscale(src, a.factor, a.long_edge)
        except ValueError as e:
            p.error(str(e))
    if out.size[0] < src.size[0]:
        print("warning: this downscales the image", file=sys.stderr)
    if out.mode in ("RGBA", "LA") and os.path.splitext(a.out)[1].lower() in (".jpg", ".jpeg"):
        p.error("OUT is JPEG but the image has alpha: use .png")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    out.save(a.out)
    print(f"saved {a.out} {src.size[0]}x{src.size[1]} -> {out.size[0]}x{out.size[1]} {out.mode} (Lanczos placeholder)")


if __name__ == "__main__":
    main()
