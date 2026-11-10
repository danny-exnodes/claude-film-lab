#!/usr/bin/env python3
"""Lanczos upscale of a layer image, alpha preserved.

  python3 tools/layers/upscale.py IN OUT --factor 2
  python3 tools/layers/upscale.py IN OUT --long-edge 3840

The source image is never overwritten: OUT equal to IN is always refused, and an existing OUT is refused
unless --overwrite is given.

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


def same_file(a, b):
    """True when two paths name one file: by inode when both exist, else by normalised absolute path."""
    if os.path.exists(a) and os.path.exists(b):
        return os.path.samefile(a, b)
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("inp", metavar="IN"); p.add_argument("out", metavar="OUT")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--factor", type=float, help="scale factor, e.g. 2")
    g.add_argument("--long-edge", type=int, help="target long edge in px")
    p.add_argument("--overwrite", action="store_true", help="replace an existing OUT (never IN)")
    a = p.parse_args(argv)
    # nothing is written before these checks pass: a mistyped path must not cost a paid image
    if same_file(a.inp, a.out):
        p.error("OUT is the same file as IN: the source image is never overwritten")
    if os.path.lexists(a.out) and not a.overwrite:
        p.error("OUT exists (versions only go up; --overwrite replaces an upscale)")
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
