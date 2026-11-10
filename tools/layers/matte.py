#!/usr/bin/env python3
"""Pull an alpha matte from a generated layer image (docs/CONVENTIONS.md §3 matte).

  python3 tools/layers/matte.py IN OUT --method none|luminance|chroma|rembg
          [--key #FF00FF] [--paper #FFFFFF] [--low N --high N]
          [--style styles/<id> --layer L2] [--preview PREVIEW.png]

Methods
  none       keep the image's own alpha (opaque if it has none)
  luminance  ink on flat paper: alpha = how much darker (or lighter) than the paper colour a pixel is;
             colour = the un-mixed ink colour stored un-premultiplied, so soft washes stay soft and the
             layer composited over the paper colour reproduces the original exactly
  chroma     flat key background: alpha = RGB distance to the key colour with a soft ramp, then despill
             (the key's tint is removed from edge pixels only)
  rembg      rembg.remove (u2net); slow on first use while the model loads
Then cleanup: alpha < low -> 0, alpha > high -> 255, linear in between.

With --style/--layer the method, low/high and key/paper colours come from style.yaml matte.per_layer
(layer codes P1-x map to P). Explicit flags override the style. Without --layer the code is read from
the IN file name when it follows ep<NN>_s<NN>_<layer>_... or q<NN>t<NN>_s<NN>_<layer>_... . --preview composites the
result over pure red for checking edges. OUT is always an RGBA PNG.
"""
import argparse, os, re, sys

import numpy as np
from PIL import Image, ImageFilter

METHODS = ("none", "luminance", "chroma", "rembg")
CHROMA_FULL = 160.0   # RGB distance from the key at which a pixel is fully opaque (before cleanup)
DESPILL_RADIUS = 3    # px: despill pixels within this distance of a non-opaque pixel
RE_LAYER = re.compile(r"^(?:ep\d{2}|q\d{2}t\d{2})_s\d{2}_(L[1-4]|P\d+-[a-z0-9-]+|FX)_")


def hex_rgb(s):
    s = s.strip().lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", s):
        raise ValueError(f"not a #RRGGBB colour: {s!r}")
    return np.array([int(s[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)


def style_key(layer):
    """Layer code -> per_layer key in style.yaml (P1-duoi -> P)."""
    return "P" if re.fullmatch(r"P\d+-[a-z0-9-]+", layer) else layer


def style_settings(style_dir, layer):
    import yaml
    with open(os.path.join(style_dir, "style.yaml"), encoding="utf-8") as f:
        y = yaml.safe_load(f) or {}
    m = y.get("matte") or {}
    per = m.get("per_layer") or {}
    key = style_key(layer)
    spec = per.get(layer) or per.get(key)
    if spec is None:
        raise SystemExit(f"{style_dir}/style.yaml: matte.per_layer has no entry for {layer} ({key})")
    return {"method": spec.get("method"), "low": spec.get("low"), "high": spec.get("high"),
            "key": m.get("key_bg"), "paper": m.get("paper_bg")}


def cleanup(alpha, low, high):
    """alpha float 0..255: < low -> 0, > high -> 255, linear in between."""
    if low is None and high is None:
        return alpha
    low = 0 if low is None else low
    high = 255 if high is None else high
    if not 0 <= low < high <= 255:
        raise ValueError(f"need 0 <= low < high <= 255 (got {low}, {high})")
    ramp = (alpha.astype(np.float64) - low) * (255.0 / (high - low))
    return np.where(alpha <= low, 0.0, np.where(alpha >= high, 255.0, np.clip(ramp, 0, 255)))


def matte_luminance(rgb, paper):
    """rgb float32 HxWx3. Returns (colour, alpha 0..255)."""
    p = paper.reshape(1, 1, 3)
    dark = np.where(p > 0, (p - rgb) / np.maximum(p, 1e-6), 0)          # needs alpha so ink >= 0
    light = np.where(p < 255, (rgb - p) / np.maximum(255 - p, 1e-6), 0)  # needs alpha so ink <= 255
    a = np.clip(np.maximum(dark, light).max(axis=2), 0, 1)
    safe = np.maximum(a, 1e-6)[..., None]
    ink = (rgb - (1 - a[..., None]) * p) / safe
    ink = np.where(a[..., None] > 1e-3, ink, rgb)   # fully transparent: keep original colour
    return np.clip(ink, 0, 255), a * 255.0


def matte_chroma(rgb, key, despill=True):
    d = np.sqrt(((rgb - key.reshape(1, 1, 3)) ** 2).sum(axis=2))
    alpha = np.clip(d * (255.0 / CHROMA_FULL), 0, 255)
    return (despill_key(rgb, key, alpha) if despill else rgb), alpha


def despill_key(rgb, key, alpha):
    """Remove the key's tint near the edges: for channels where the key is high (H) vs low (L),
    s = max(0, min(H) - max(L)) is subtracted from H (classic green-screen despill, generalised)."""
    hi = key > 127
    if hi.all() or not hi.any():
        return rgb
    s = np.clip(rgb[..., hi].min(axis=2) - rgb[..., ~hi].max(axis=2), 0, None)
    edge = Image.fromarray(((alpha < 255) * 255).astype(np.uint8), "L")
    edge = np.asarray(edge.filter(ImageFilter.MaxFilter(2 * DESPILL_RADIUS + 1))) > 0
    out = rgb.copy()
    out[..., hi] -= (s * edge)[..., None]
    return np.clip(out, 0, 255)


def matte_rembg(im):
    from rembg import remove
    cut = remove(im.convert("RGB"))
    a = np.asarray(cut.convert("RGBA"), dtype=np.float32)[..., 3]
    return np.asarray(im.convert("RGB"), dtype=np.float32), a


def run(src, method, key="#FF00FF", paper="#FFFFFF", low=None, high=None):
    """PIL image -> RGBA PIL image."""
    if method not in METHODS:
        raise ValueError(f"method must be one of {', '.join(METHODS)}")
    rgba = np.asarray(src.convert("RGBA"), dtype=np.float32)
    rgb = rgba[..., :3]
    if method == "none":
        col, a = rgb, rgba[..., 3]
    elif method == "luminance":
        col, a = matte_luminance(rgb, hex_rgb(paper))
    elif method == "chroma":
        col, a = matte_chroma(rgb, hex_rgb(key))
    else:
        col, a = matte_rembg(src)
    a = cleanup(a, low, high)
    out = np.dstack([col, a])
    return Image.fromarray(np.round(out).astype(np.uint8), "RGBA")


def preview(rgba):
    red = Image.new("RGBA", rgba.size, (255, 0, 0, 255))
    return Image.alpha_composite(red, rgba).convert("RGB")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("inp", metavar="IN"); p.add_argument("out", metavar="OUT")
    p.add_argument("--method", choices=METHODS)
    p.add_argument("--key", help="key colour for chroma (default style key_bg or #FF00FF)")
    p.add_argument("--paper", help="paper colour for luminance (default style paper_bg or #FFFFFF)")
    p.add_argument("--low", type=int); p.add_argument("--high", type=int)
    p.add_argument("--style", help="styles/<id>: read matte settings from style.yaml")
    p.add_argument("--layer", help="layer code (L1-L4, P<n>-<part>, FX); default from IN file name")
    p.add_argument("--preview", help="also write the result composited over pure red")
    a = p.parse_args(argv)

    cfg = {"method": None, "low": None, "high": None, "key": None, "paper": None}
    if a.style:
        layer = a.layer
        if not layer:
            m = RE_LAYER.match(os.path.basename(a.inp))
            if not m:
                p.error("--style needs --layer (IN name does not show the layer code)")
            layer = m.group(1)
        cfg.update(style_settings(a.style, layer))
    for k in ("method", "low", "high", "key", "paper"):
        if getattr(a, k) is not None:
            cfg[k] = getattr(a, k)
    if os.path.splitext(a.out)[1].lower() != ".png":
        p.error("OUT must be a .png file (RGBA)")
    if not cfg["method"]:
        p.error("--method is required (or --style with --layer)")
    try:
        with Image.open(a.inp) as src:
            src.load()
            out = run(src, cfg["method"], key=cfg["key"] or "#FF00FF", paper=cfg["paper"] or "#FFFFFF",
                      low=cfg["low"], high=cfg["high"])
    except ValueError as e:
        sys.exit(f"matte: {e}")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    out.save(a.out, "PNG")
    al = np.asarray(out)[..., 3]
    print(f"saved {a.out} ({out.width}x{out.height} RGBA, method {cfg['method']}, low {cfg['low']}, high {cfg['high']}); "
          f"transparent {np.mean(al == 0) * 100:.1f}%, opaque {np.mean(al == 255) * 100:.1f}%")
    if a.preview:
        preview(out).save(a.preview, "PNG")
        print("preview", a.preview)


if __name__ == "__main__":
    main()
