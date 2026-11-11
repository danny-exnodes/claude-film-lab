#!/usr/bin/env python3
"""Pull an alpha matte from a generated layer image (docs/CONVENTIONS.md §3 matte).

  python3 tools/layers/matte.py IN [OUT] --method none|luminance|chroma|rembg
          [--key #FF00FF] [--paper auto|#FFFFFF] [--low N --high N]
          [--style styles/<id> --layer L2] [--preview PREVIEW.png] [--overwrite]
          [--rembg-model NAME] [--allow-download]

OUT may be left out: the matte is then written to <IN dir>/matte/<IN stem>.png (plates/matte/ for a plate,
same file name). The source image is never overwritten: OUT equal to IN is always refused, an existing
OUT is refused unless --overwrite is given, and --preview may not name IN or OUT.
A rembg model that is not in the local model folder is refused instead of downloaded (some models are
1 GB and need 9 GB of RAM); --allow-download lets rembg fetch it.
Alpha the input already has is kept: the new matte is multiplied by it (method none keeps it as it is).

Methods
  none       keep the image's own alpha (opaque if it has none)
  luminance  ink on flat paper: alpha = how much darker (or lighter) than the paper colour a pixel is;
             colour = the un-mixed ink colour stored un-premultiplied, so soft washes stay soft and the
             layer composited over the paper colour reproduces the original exactly.
             --paper auto (the default unless --paper #RRGGBB is given) estimates the paper colour from the
             image border (per-channel median over a band of BORDER_FRAC of the short edge), because
             Seedream "white" backgrounds are often ivory or a soft gradient (#F5F1EE, #EAE5DF); the estimate
             is printed, and on a light estimated paper pixels lighter than it count as paper. style.yaml
             paper_bg is only a hint then; an explicit --paper colour still wins.
  chroma     flat key background: alpha = RGB distance to the key colour with a soft ramp, then despill
             (the key's tint is removed from edge pixels only)
  rembg      rembg.remove with an explicit model: --rembg-model, else $FILM_REMBG_MODEL, else u2net (the
             model the session hook prefetches); slow on first use while the model loads. ~1 GB RAM per process, so runs
             take a machine-wide lock (REMBG_LOCK, /tmp/film-lab-rembg.lock): parallel agents queue, not OOM
Then cleanup: alpha < low -> 0, alpha > high -> 255, linear in between.

With --style/--layer the method, low/high and the key colour come from style.yaml matte.per_layer
(layer codes P1-x map to P). Explicit flags override the style. Without --layer the code is read from
the IN file name when it follows ep<NN>_s<NN>_<layer>_... or q<NN>t<NN>_s<NN>_<layer>_... . --preview composites the
result over pure red for checking edges. OUT is always an RGBA PNG. A WARNING is printed when an L2/L3
result is under 10% transparent (paper not removed: try --paper auto or a higher --low).
"""
import argparse, contextlib, fcntl, os, re, sys, time

import numpy as np
from PIL import Image, ImageFilter, ImageOps

METHODS = ("none", "luminance", "chroma", "rembg")
CHROMA_FULL = 160.0   # RGB distance from the key at which a pixel is fully opaque (before cleanup)
DESPILL_RADIUS = 3    # px: despill pixels within this distance of a non-opaque pixel
BORDER_FRAC = 0.03    # --paper auto: border band width as a fraction of the short edge (>= 2 px)
REMBG_LOCK = os.environ.get("FILM_REMBG_LOCK", "/tmp/film-lab-rembg.lock")
LOW_TRANSPARENCY = 10.0   # % transparent below which an L2/L3 matte is flagged
RE_LAYER = re.compile(r"^(?:ep\d{2}|q\d{2}t\d{2})_s\d{2}_(L[1-4]|P\d+-[a-z0-9-]+|FX)_")


def hex_rgb(s):
    s = s.strip().lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", s):
        raise ValueError(f"not a #RRGGBB colour: {s!r}")
    return np.array([int(s[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)


def hex_text(s):
    """'f4efe4' / '#f4efe4' -> '#F4EFE4' (ValueError when it is not a colour)."""
    return "#%02X%02X%02X" % tuple(int(c) for c in hex_rgb(str(s)))


def estimate_paper(rgb, frac=BORDER_FRAC):
    """rgb float HxWx3 -> paper colour (float32 x3): per-channel median of a border band. The median
    ignores ink that touches the edge as long as most of the band is paper; a gradient gives its mid tone."""
    h, w = rgb.shape[:2]
    b = max(2, int(round(min(h, w) * frac)))
    b = min(b, max(1, min(h, w) // 2))
    band = np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3),
                           rgb[b:-b, :b].reshape(-1, 3), rgb[b:-b, -b:].reshape(-1, 3)])
    return np.median(band, axis=0).astype(np.float32)


def rgb_hex(c):
    return "#" + "".join(f"{int(round(float(v))):02X}" for v in c)


@contextlib.contextmanager
def rembg_lock(path=None, log=sys.stderr):
    """Machine-wide exclusive lock around rembg (u2net needs ~1 GB RAM per process)."""
    path = path or REMBG_LOCK
    with open(path, "a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"matte: waiting for another rembg run ({path}) ...", file=log, flush=True)
            t0 = time.time()
            fcntl.flock(f, fcntl.LOCK_EX)
            print(f"matte: got rembg lock after {time.time() - t0:.0f} s", file=log, flush=True)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def style_key(layer):
    """Layer code -> per_layer key in style.yaml (P1-duoi -> P)."""
    return "P" if re.fullmatch(r"P\d+-[a-z0-9-]+", layer) else layer


def style_settings(style_dir, layer):
    """Matte settings of one layer: method, low, high, bg (the layer's own flat background, optional)
    and the style-wide key / paper colours."""
    import yaml
    path = os.path.join(style_dir, "style.yaml")
    try:
        with open(path, encoding="utf-8") as f:
            y = yaml.safe_load(f) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        reason = e.strerror if isinstance(e, OSError) and e.strerror else " ".join(str(e).split())
        raise SystemExit(f"matte: cannot read {path} ({reason})")
    m = y.get("matte") if isinstance(y, dict) else None
    m = {} if m is None else m
    per = m.get("per_layer") if isinstance(m, dict) else None
    per = {} if per is None else per
    if not isinstance(m, dict) or not isinstance(per, dict):
        raise SystemExit(f"matte: {path}: matte and matte.per_layer must be mappings")
    key = style_key(layer)
    name = layer if per.get(layer) else key
    spec = per.get(name)
    if spec is None:
        raise SystemExit(f"{style_dir}/style.yaml: matte.per_layer has no entry for {layer} ({key})")
    if not isinstance(spec, dict):
        raise SystemExit(f"matte: {path}: matte.per_layer.{name} must be a mapping "
                         f"{{method, low, high, bg}}, not {spec!r}")
    return {"method": spec.get("method"), "low": spec.get("low"), "high": spec.get("high"), "bg": spec.get("bg"),
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


def matte_luminance(rgb, paper, dark_only=False):
    """rgb float32 HxWx3. Returns (colour, alpha 0..255). dark_only: pixels lighter than the paper count
    as paper (used with an estimated light paper: on ivory, 255 - paper is tiny and the 'lighter' term
    would turn the bright half of a gradient into ink)."""
    p = paper.reshape(1, 1, 3)
    dark = np.where(p > 0, (p - rgb) / np.maximum(p, 1e-6), 0)          # needs alpha so ink >= 0
    light = np.where(p < 255, (rgb - p) / np.maximum(255 - p, 1e-6), 0)  # needs alpha so ink <= 255
    if dark_only:
        light = np.zeros_like(light)
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


REMBG_MODEL = "u2net"  # default rembg model: the one doctor.sh checks and the session hook prefetches
_REMBG_SESSIONS = {}   # model name -> rembg session, one per process


def rembg_model_files(model):
    """Where rembg 2.x looks for <model>.onnx: its model folder, then the legacy ~/.u2net folder."""
    env = os.environ.get
    xdg = env("XDG_DATA_HOME")
    home = env("U2NET_HOME") or env("REMBG_HOME") or (os.path.join(xdg, "rembg") if xdg else os.path.join("~", ".rembg"))
    legacy = env("U2NET_HOME") or os.path.join(xdg or "~", ".u2net")
    return [os.path.join(os.path.expanduser(home), "models", model, model + ".onnx"),
            os.path.join(os.path.expanduser(legacy), model + ".onnx")]


def rembg_model_cached(model):
    return any(os.path.isfile(f) for f in rembg_model_files(model))


def matte_rembg(im, model=REMBG_MODEL):
    """The session is always explicit: rembg.remove() without one picks its own default model
    (bria-rmbg in rembg 2.0.87: a 1 GB download and about 9 GB of RAM per 2K image)."""
    from rembg import new_session, remove
    with rembg_lock():
        session = _REMBG_SESSIONS.get(model)
        if session is None:
            session = _REMBG_SESSIONS[model] = new_session(model)
        cut = remove(im.convert("RGB"), session=session)
    a = np.asarray(cut.convert("RGBA"), dtype=np.float32)[..., 3]
    return np.asarray(im.convert("RGB"), dtype=np.float32), a


def resolve_paper(rgb, paper):
    """'auto' (or None) -> estimate from the border; '#RRGGBB' -> that colour."""
    if paper is None or str(paper).strip().lower() == "auto":
        return estimate_paper(rgb)
    return hex_rgb(paper)


def run(src, method, key="#FF00FF", paper="#FFFFFF", low=None, high=None, info=None, *, rembg_model=REMBG_MODEL):
    """PIL image -> RGBA PIL image. paper may be 'auto'. If info is a dict, the paper used is stored
    there as info['paper'] ('#RRGGBB')."""
    if method not in METHODS:
        raise ValueError(f"method must be one of {', '.join(METHODS)}")
    rgba = np.asarray(src.convert("RGBA"), dtype=np.float32)
    rgb = rgba[..., :3]
    if method == "none":
        col, a = rgb, rgba[..., 3]
    elif method == "luminance":
        pc = resolve_paper(rgb, paper)
        auto = paper is None or str(paper).strip().lower() == "auto"
        if info is not None:
            info["paper"] = rgb_hex(pc)
        col, a = matte_luminance(rgb, pc, dark_only=auto and float(pc.mean()) >= 128)
    elif method == "chroma":
        col, a = matte_chroma(rgb, hex_rgb(key))
    else:
        col, a = matte_rembg(src, rembg_model)
    a = cleanup(a, low, high)
    src_a = rgba[..., 3]
    if method != "none" and (src_a < 255).any():
        # alpha channel or palette transparency of the source: what was transparent stays transparent
        a = a * (src_a / 255.0)
        print("note: input already has alpha: combined with the new matte", file=sys.stderr)
    out = np.dstack([col, a])
    return Image.fromarray(np.round(out).astype(np.uint8), "RGBA")


def preview(rgba):
    red = Image.new("RGBA", rgba.size, (255, 0, 0, 255))
    return Image.alpha_composite(red, rgba).convert("RGB")


def same_file(a, b):
    """True when two paths name one file: by inode when both exist, else by normalised absolute path."""
    if os.path.exists(a) and os.path.exists(b):
        return os.path.samefile(a, b)
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("inp", metavar="IN")
    p.add_argument("out", metavar="OUT", nargs="?", help="RGBA .png to write (default <IN dir>/matte/<IN stem>.png)")
    p.add_argument("--method", choices=METHODS)
    p.add_argument("--key", help="key colour for chroma (default style key_bg or #FF00FF)")
    p.add_argument("--paper", help="paper colour for luminance: auto (default; estimated from the image border) "
                                   "or #RRGGBB. style.yaml paper_bg is only printed as a hint; pass it here to force it")
    p.add_argument("--low", type=int); p.add_argument("--high", type=int)
    p.add_argument("--style", help="styles/<id>: read matte settings from style.yaml")
    p.add_argument("--layer", help="layer code (L1-L4, P<n>-<part>, FX); default from IN file name")
    p.add_argument("--preview", help="also write the result composited over pure red")
    p.add_argument("--overwrite", action="store_true", help="replace an existing OUT (never IN)")
    p.add_argument("--rembg-model", metavar="NAME",
                   help=f"rembg model for method rembg (default $FILM_REMBG_MODEL, else {REMBG_MODEL})")
    p.add_argument("--allow-download", action="store_true",
                   help="let rembg download a model that is not cached locally")
    a = p.parse_args(argv)

    if a.out is None:
        a.out = os.path.join(os.path.dirname(a.inp), "matte", os.path.splitext(os.path.basename(a.inp))[0] + ".png")
    cfg = {"method": None, "low": None, "high": None, "key": None, "paper": None, "bg": None}
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
    method = cfg["method"]
    # nothing is written before these checks pass: a mistyped path must not cost a paid image
    if same_file(a.inp, a.out):
        p.error("OUT is the same file as IN: the source image is never overwritten")
    if os.path.lexists(a.out) and not a.overwrite:
        p.error("OUT exists (versions only go up; --overwrite replaces a matte)")
    if a.preview and (same_file(a.preview, a.inp) or same_file(a.preview, a.out)):
        p.error("--preview is the same file as IN or OUT")
    model = a.rembg_model or os.environ.get("FILM_REMBG_MODEL") or REMBG_MODEL
    if method == "rembg":
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", model):
            p.error(f"--rembg-model must be a rembg model name, not {model!r}")
        if not a.allow_download and not rembg_model_cached(model):
            print(f"matte: rembg model {model} is not cached (run tools/doctor.sh or the session hook, "
                  "or pass --allow-download)", file=sys.stderr)
            sys.exit(2)
    try:
        # the layer's own background (per_layer.<code>.bg) beats the style-wide colour; a flag beats both
        # (only the colour the method reads is checked: the other one never stopped a matte)
        key = hex_text(a.key or cfg["bg"] or cfg["key"] or "#FF00FF") if method == "chroma" else "#FF00FF"
        # luminance: only an explicit --paper colour is used as is. style.yaml paper_bg and a per-layer bg (often
        # "#FFFFFF" while Seedream paints ivory or a gradient) both mean auto: estimated from the image border.
        explicit_paper = bool(a.paper) and a.paper.strip().lower() != "auto"
        paper = hex_text(a.paper) if explicit_paper and method == "luminance" else "auto"
    except ValueError as e:
        sys.exit(f"matte: {e}")
    try:
        with Image.open(a.inp) as src:
            src.load()
            src = ImageOps.exif_transpose(src) or src
    except (OSError, SyntaxError, ValueError) as e:
        reason = e.strerror if isinstance(e, OSError) and e.strerror else " ".join(str(e).split())
        sys.exit(f"matte: cannot read {a.inp} ({reason})")
    try:
        info = {}
        out = run(src, method, key=key, paper=paper, low=cfg["low"], high=cfg["high"], info=info, rembg_model=model)
    except ValueError as e:
        sys.exit(f"matte: {e}")
    if "paper" in info:
        how = "explicit" if explicit_paper else "auto, from the image border"
        style_paper = cfg["bg"] or cfg["paper"]
        hint = f"; style paper_bg {style_paper}" if style_paper and not explicit_paper else ""
        paper = info["paper"]
        print(f"paper {info['paper']} ({how}{hint})")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    out.save(a.out, "PNG")
    al = np.asarray(out)[..., 3]
    how = {"chroma": f"chroma key {key}", "luminance": f"luminance paper {paper}", "rembg": f"rembg({model})"}.get(method, method)
    print(f"saved {a.out} ({out.width}x{out.height} RGBA, method {how}, low {cfg['low']}, high {cfg['high']}); "
          f"transparent {np.mean(al == 0) * 100:.1f}%, opaque {np.mean(al == 255) * 100:.1f}%")
    m = RE_LAYER.match(os.path.basename(a.inp))
    layer = a.layer or (m.group(1) if m else None)
    transparent = np.mean(al == 0) * 100
    if layer in ("L2", "L3") and cfg["method"] != "none" and transparent < LOW_TRANSPARENCY:
        print(f"WARNING: {layer} is only {transparent:.1f}% transparent (< {LOW_TRANSPARENCY:.0f}%): the background "
              "was probably not removed. Try --paper auto (luminance) and/or a higher --low; check --preview.",
              file=sys.stderr)
    if a.preview:
        preview(out).save(a.preview, "PNG")
        print("preview", a.preview)


if __name__ == "__main__":
    main()
