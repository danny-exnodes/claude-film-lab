#!/usr/bin/env python3
"""Two-layer ink-wash grade (thuỷ mặc) for rendered frames: the scene pale and misty, the subject (a creature, from a
mask pass) deeper and more saturated so it stands out, plus a .cube LUT of the colour part. numpy + Pillow (+ PyYAML
for --style); no network, no API; ffmpeg only for video in or out. Free.

  python3 tools/compose/grade.py IN OUT --style styles/chan-thuc-blender [--params shot.json] \
      [--depth D] [--depth-range NEAR FAR] [--mask M ...] [--subject ASSET ...] [--fps N]
  python3 tools/compose/grade.py IN --preview before-after.png --style ... [--frame N]
  python3 tools/compose/grade.py --export-lut scene.cube --style ... [--layer scene|subject] [--lut-size 33]
  python3 tools/compose/grade.py --check --style ... [--params shot.json]          # only validate the parameters

IN is one image (OUT = a .png), a folder of PNG frames (OUT = a new folder, same file names, or a .mp4; a .png when
it holds one frame, e.g. a style frame rendered with `blender.py render --frames N --passes depth mask`), a video
(.mp4/.mov/.mkv/.webm, decoded with ffmpeg; OUT = a .mp4/.mov/.mkv or a folder) or a Blender render folder
(renders3d/s<NN>/ of `tools/blender/blender.py render`): then the frames are beauty/, the depth pass depth/ and
depth_range / fps come from render.json, and --subject <asset> picks mask/<asset>/ (several: their union).
Explicit --depth / --mask (a PNG or a folder) win. Pass files are matched to frames by file name (a missing one is an
error), else, when no name matches (video frames), by order. OUT is written as <OUT>.part (folder) or <stem>.part.<ext>
and renamed when every frame is done: a run that fails leaves nothing behind and can simply run again.

Passes (the format of `blender.py render`, tools/blender/README.md):
  depth  16-bit grey, depth_range [near, far] mapped linearly, near = white, far and sky = black; metres =
         near + (1 - v) * (far - near). Without a depth pass there is no mist.
  mask   8-bit grey, 255 = the asset. Feathered here by subject.layer.edge px (at 1080p) for a soft edge.

Parameters: style.yaml key `grade:` (or a JSON file with the same shape; --params is deep-merged over --style):
  grade:
    seed: 7                       # paper grain; same input + same parameters -> same bytes
    scene:   {saturation, keep_red, hue_pull, tone, split, mist, paper, vignette}
    subject: {saturation, keep_red, hue_pull, tone, split, mist, layer}   # overrides of scene, inside the mask
With --style, --params may change part of a style's hue_pull (only its amount); the merge is checked in full.
Every key is optional; a missing key does nothing (the defaults are neutral: an empty grade returns the input). Keys,
ranges and meanings: SCHEMA below and .claude/skills/film-compose-shot/references/blender-method.md §7.

Pipeline (display-referred sRGB 0..1, i.e. after Blender's view transform):
  colour, per pixel, one 3D LUT per layer (exactly what --export-lut writes, sampled at 65 points here):
    1. saturation per hue band (red, orange, yellow, green, cyan, blue, purple) times global; keep_red spares saturated
       cinnabar reds from it; 2. hue_pull toward palette colours; 3. soft tone curve (black/white points, contrast
       around a pivot, gamma); 4. split tone: shadows toward one colour, highlights toward another.
  spatial (not in a LUT: a .cube cannot hold them, other editors need this script for them):
    5. mist from the depth pass (start/falloff metres, sky, more toward the bottom of the frame);
    6. layers: subject = its own colour + mist_keep of the mist, blended by the feathered mask, then a thin mist rim
       just outside the mask edge so the subject still sits in the air;
    7. paper grain (value noise + fibres, seeded, the same on every frame) and a warm vignette, once over both layers.

Exit: 0 done · 1 ffmpeg missing/failed or a file cannot be read · 2 refused before writing anything (bad parameters,
style.yaml error, OUT already exists, wrong combination of arguments; with --export-lut and IN, the .cube is written
only after IN and OUT are checked).

Adapted from an in-house style-frame script of the lab (grade_thuymac.py, same owner, numpy/Pillow/scipy): the hue-band
saturation, palette hue pulls, tone curve, split tone, depth mist, paper texture, vignette and the scene/subject layer
blend. Changed: scipy replaced by numpy box blurs, the colour step runs through a Pillow 3D LUT, Blender pass formats,
sequences and video, a validated schema with neutral defaults (the look lives in the style pack).
"""
import argparse
import copy
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

LAB = Path(__file__).resolve().parents[2]
LUT_INTERNAL = 65            # LUT points per axis used for grading (Pillow trilinear)
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
VIDEO_OUT_EXT = {".mp4", ".mov", ".mkv", ".m4v"}       # libx264 + yuv420p
IMAGE_EXT = {".png", ".jpg", ".jpeg"}
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
REF_H = 1080.0               # pixel sizes in the parameters are at 1080p

# Hue bands for saturation (centre, width in degrees): generic colour wheel, not a look.
BANDS = {"red": (3, 16), "orange": (28, 12), "yellow": (52, 14), "green": (105, 40), "cyan": (185, 22),
         "blue": (218, 30), "purple": (285, 35)}

# block -> key -> (kind, lo, hi, default). kind: num | hex. Defaults are neutral (no change).
SCHEMA = {
    "saturation": {"global": ("num", 0, 3, 1.0), **{b: ("num", 0, 3, 1.0) for b in BANDS}},
    "keep_red": {"amount": ("num", 0, 1, 0.0), "min_sat": ("num", 0, 1, 0.3), "gain": ("num", 0, 3, 1.0)},
    "tone": {"black": ("num", 0, 0.5, 0.0), "white": ("num", 0.5, 1, 1.0), "pivot": ("num", 0.05, 0.95, 0.5),
             "contrast": ("num", 0.2, 3, 1.0), "gamma": ("num", 0.2, 5, 1.0)},
    "split": {"shadow": ("hex", None, None, "#000000"), "shadow_amount": ("num", 0, 1, 0.0),
              "highlight": ("hex", None, None, "#FFFFFF"), "highlight_amount": ("num", 0, 1, 0.0)},
    "mist": {"color": ("hex", None, None, "#FFFFFF"), "amount": ("num", 0, 1, 0.0), "start": ("num", 0, 1e6, 0.0),
             "falloff": ("num", 0.01, 1e6, 50.0), "sky": ("num", 0, 1, 0.0), "max": ("num", 0, 1, 1.0),
             "low": ("num", 0, 3, 0.0), "low_from": ("num", 0, 1, 0.5)},
    "paper": {"amount": ("num", 0, 1, 0.0), "fibres": ("num", 0, 20000, 900), "fibre_amount": ("num", 0, 3, 0.6),
              "dark": ("num", 0, 1, 0.4), "tint": ("num", 0, 1, 0.0), "color": ("hex", None, None, "#FFFFFF")},
    "vignette": {"amount": ("num", 0, 1, 0.0), "radius": ("num", 0, 1.5, 0.55), "color": ("hex", None, None, "#5A4630")},
    "layer": {"opacity": ("num", 0, 1, 1.0), "mist_keep": ("num", 0, 1, 0.3), "edge": ("num", 0, 200, 3.0),
              "rim": ("num", 0, 1, 0.0), "rim_width": ("num", 0, 400, 18.0)},
    # hue_pull: name -> {to, centre, width, amount}; checked in validate()
}
HUE_PULL = {"to": ("hex", None, None, None), "centre": ("num", 0, 360, None), "width": ("num", 1, 180, 25.0),
            "amount": ("num", 0, 1, 0.0)}
SCENE_BLOCKS = ("saturation", "keep_red", "hue_pull", "tone", "split", "mist", "paper", "vignette")
SUBJECT_BLOCKS = ("saturation", "keep_red", "hue_pull", "tone", "split", "mist", "layer")


class Refused(Exception):
    """Exit 2: nothing was written."""


class Failed(Exception):
    """Exit 1: a tool or a file failed."""


# ============================================================================ parameters
def merge(a, b):
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def _check_value(where, v, kind, lo, hi, errs):
    if kind == "hex":
        if not isinstance(v, str) or not HEX.match(v):
            errs.append(f"{where}: {v!r} is not \"#RRGGBB\"")
    elif isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        errs.append(f"{where}: {v!r} must be a number {lo:g}-{hi:g}")
    elif not lo <= v <= hi:
        errs.append(f"{where}: {v!r} is out of range {lo:g}-{hi:g}")


def _check_block(where, block, name, errs, partial=False):
    if not isinstance(block, dict):
        errs.append(f"{where}: must be a mapping")
        return
    if name == "hue_pull":
        for pname, pull in block.items():
            w = f"{where}.{pname}"
            if not isinstance(pull, dict):
                errs.append(f"{w}: must be a mapping {{to, centre, width, amount}}")
                continue
            if "to" not in pull and not partial:
                errs.append(f"{w}: 'to' (\"#RRGGBB\") is required")
            for k, v in pull.items():
                if k not in HUE_PULL:
                    errs.append(f"{w}: unknown key '{k}' (known: {', '.join(HUE_PULL)})")
                else:
                    _check_value(f"{w}.{k}", v, *HUE_PULL[k][:3], errs)
        return
    keys = SCHEMA[name]
    for k, v in block.items():
        if k not in keys:
            errs.append(f"{where}: unknown key '{k}' (known: {', '.join(keys)})")
        else:
            _check_value(f"{where}.{k}", v, *keys[k][:3], errs)


def validate(g, where="grade", partial=False):
    """Errors (strings 'grade.scene.tone.black: ...') of a grade block; [] when it is usable.
    partial: an override merged over a style afterwards (a hue_pull may change only its amount; the merge is
    validated again in full)."""
    errs = []
    if not isinstance(g, dict):
        return [f"{where}: must be a mapping {{seed, scene, subject}}"]
    for k in g:
        if k not in ("seed", "scene", "subject"):
            errs.append(f"{where}: unknown key '{k}' (known: seed, scene, subject)")
    if "seed" in g and (isinstance(g["seed"], bool) or not isinstance(g["seed"], int) or not 0 <= g["seed"] < 2 ** 32):
        errs.append(f"{where}.seed: {g['seed']!r} must be an integer 0-4294967295")
    for layer, blocks in (("scene", SCENE_BLOCKS), ("subject", SUBJECT_BLOCKS)):
        if layer not in g or g[layer] is None:
            continue
        L = g[layer]
        if not isinstance(L, dict):
            errs.append(f"{where}.{layer}: must be a mapping")
            continue
        for name, block in L.items():
            if name not in blocks:
                hint = " (paper and vignette are applied once over both layers: set them under scene)" \
                    if layer == "subject" and name in ("paper", "vignette") else ""
                errs.append(f"{where}.{layer}: unknown key '{name}' (known: {', '.join(blocks)}){hint}")
            else:
                _check_block(f"{where}.{layer}.{name}", block, name, errs, partial)
    return errs


def defaults(blocks):
    out = {b: {k: spec[3] for k, spec in SCHEMA[b].items()} for b in blocks if b != "hue_pull"}
    out["hue_pull"] = {}
    return out


def resolve(g):
    """grade block -> (scene params, subject params or None, seed), every key filled."""
    scene = merge(defaults(SCENE_BLOCKS), g.get("scene") or {})
    subject = None
    if g.get("subject"):
        base = {k: v for k, v in scene.items() if k in SUBJECT_BLOCKS}
        subject = merge(merge(base, {"layer": defaults(("layer",))["layer"]}), g["subject"])
        for pull in subject["hue_pull"].values():
            pull.setdefault("width", 25.0)
            pull.setdefault("amount", 0.0)
    for pull in scene["hue_pull"].values():
        pull.setdefault("width", 25.0)
        pull.setdefault("amount", 0.0)
    return scene, subject, int(g.get("seed", 7))


def load_style_grade(style):
    """The grade: block of styles/<id>/style.yaml (style = folder or the style.yaml itself)."""
    path = Path(style)
    if path.is_dir():
        path = path / "style.yaml"
    if not path.is_file():
        raise Refused(f"--style {style}: no style.yaml there")
    try:
        import yaml
    except ImportError:
        raise Refused("--style needs PyYAML (pip install PyYAML, requirements.txt); or pass --params <file>.json")
    try:
        y = yaml.safe_load(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        raise Refused(f"{path}: not valid UTF-8")
    except yaml.YAMLError as e:
        raise Refused(f"{path}: not valid YAML: {' '.join(str(e).split())}")
    if not isinstance(y, dict):
        raise Refused(f"{path}: must be a mapping")
    if "grade" not in y:
        raise Refused(f"{path}: no 'grade:' block (add one: docs/CONVENTIONS.md §3, see styles/chan-thuc-blender)")
    return y["grade"], str(path)


def load_params(style=None, params=None):
    """Grade block from --style and/or --params (JSON deep-merged over the style). Refused on any error."""
    if not style and not params:
        raise Refused("pass --style styles/<id> (style.yaml grade:) and/or --params <file>.json")
    g, srcs = {}, []
    if style:
        sg, src = load_style_grade(style)
        errs = validate(sg)
        if errs:
            raise Refused(f"{src}:\n  " + "\n  ".join(errs))
        g, srcs = sg or {}, [src]
    if params:
        try:
            pj = json.loads(Path(params).read_text(encoding="utf-8"))
        except OSError as e:
            raise Refused(f"--params {params}: cannot be read ({e.strerror or e})")
        except ValueError as e:
            raise Refused(f"--params {params}: not valid JSON: {e}")
        if isinstance(pj, dict) and "grade" in pj and set(pj) <= {"grade"}:
            pj = pj["grade"]
        errs = validate(pj, partial=bool(style))
        if errs:
            raise Refused(f"{params}:\n  " + "\n  ".join(errs))
        g = merge(g, pj)
        errs = validate(g)
        if errs:
            raise Refused(f"{params} over {srcs[0]}:\n  " + "\n  ".join(errs))
        srcs.append(str(params))
    return g, srcs


# ============================================================================ colour (per pixel, LUT)
def hexrgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)], dtype=np.float32)


def rgb_to_hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    m = d > 1e-6
    rm = m & (mx == r)
    gm = m & (mx == g) & ~rm
    bm = m & ~rm & ~gm
    h[rm] = ((g - b)[rm] / d[rm]) % 6
    h[gm] = (b - r)[gm] / d[gm] + 2
    h[bm] = (r - g)[bm] / d[bm] + 4
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0)
    return h * 60.0, s, mx


def hsv_to_rgb(h, s, v):
    h = (h % 360) / 60.0
    i = np.floor(h).astype(int) % 6
    f = h - np.floor(h)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    out = np.empty(h.shape + (3,), dtype=np.float32)
    for k, (a, b, c) in enumerate(((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))):
        sel = i == k
        out[..., 0][sel], out[..., 1][sel], out[..., 2][sel] = a[sel], b[sel], c[sel]
    return out


def hue_of(hexcol):
    return float(rgb_to_hsv(hexrgb(hexcol)[None])[0][0])


def bump(h, centre, width):
    d = np.abs(((h - centre + 180) % 360) - 180)
    return np.exp(-0.5 * (d / width) ** 2)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / max(e1 - e0, 1e-6), 0, 1)
    return t * t * (3 - 2 * t)


def colour(rgb, p):
    """Steps 1-4 on an (..., 3) float array in 0..1 (display-referred sRGB)."""
    rgb = np.clip(rgb, 0, 1).astype(np.float32)
    h, s, v = rgb_to_hsv(rgb)
    S = p["saturation"]
    w = {k: bump(h, c, wd) for k, (c, wd) in BANDS.items()}
    mult = np.ones_like(h)
    for k, wk in w.items():
        mult = mult + wk * (S[k] - 1.0)
    mult = mult * S["global"]
    K = p["keep_red"]
    if K["amount"] > 0:          # cinnabar: a saturated red keeps its own gain instead of the band/global multipliers
        red = K["amount"] * w["red"] * smoothstep(K["min_sat"], K["min_sat"] + 0.2, s) * smoothstep(0.08, 0.25, v)
        mult = mult * (1 - red) + red * K["gain"]
    s2 = np.clip(s * mult, 0, 1)
    h2 = h.copy()
    for pull in p["hue_pull"].values():
        if pull["amount"] <= 0:
            continue
        tgt = hue_of(pull["to"])
        wk = bump(h, pull.get("centre", tgt), pull["width"])
        h2 = h2 + pull["amount"] * wk * (((tgt - h + 180) % 360) - 180)
    x = np.clip(hsv_to_rgb(h2, s2, v), 0, 1)
    T = p["tone"]
    piv, c = T["pivot"], T["contrast"]
    lo = piv * np.power(np.clip(x / piv, 0, None), c)
    hi = 1 - (1 - piv) * np.power(np.clip((1 - x) / (1 - piv), 0, None), c)
    y = np.power(np.where(x < piv, lo, hi), T["gamma"])
    y = T["black"] + (T["white"] - T["black"]) * y
    Sp = p["split"]
    if Sp["shadow_amount"] > 0 or Sp["highlight_amount"] > 0:
        lum = (0.2126 * y[..., 0] + 0.7152 * y[..., 1] + 0.0722 * y[..., 2])[..., None]
        ws = np.clip(1 - lum / 0.5, 0, 1) ** 2 * Sp["shadow_amount"]
        wh = np.clip((lum - 0.5) / 0.5, 0, 1) ** 2 * Sp["highlight_amount"]
        sh, hl = hexrgb(Sp["shadow"]), hexrgb(Sp["highlight"])
        y = y * (1 - ws) + np.clip(sh / max(float(sh.mean()), 1e-3) * lum, 0, 1) * ws
        y = y * (1 - wh) + np.clip(hl / max(float(hl.mean()), 1e-3) * lum, 0, 1) * wh
    return np.clip(y, 0, 1).astype(np.float32)


def lut_table(p, size):
    """(size**3, 3) float32, red index fastest (the .cube and Pillow Color3DLUT order)."""
    g = np.linspace(0, 1, size, dtype=np.float32)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")
    return colour(np.stack([r, gg, b], -1).reshape(-1, 3), p)


def write_cube(path, p, size, title):
    table = lut_table(p, size)
    lines = [f'TITLE "{title}"',
             "# tools/compose/grade.py: colour steps only (hue-band saturation, hue pulls, tone curve, split tone).",
             "# Mist (depth pass), the subject layer (mask pass), paper grain and vignette are spatial and are NOT in",
             "# this LUT: grade with tools/compose/grade.py to get them.",
             "# Input: display-referred sRGB (after the view transform, e.g. Blender AgX), 0..1.",
             f"LUT_3D_SIZE {size}", "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
    lines += [f"{c[0]:.6f} {c[1]:.6f} {c[2]:.6f}" for c in table]
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


# ============================================================================ spatial helpers
def _box(a, k, axis):
    pad = [(0, 0)] * a.ndim
    pad[axis] = (k + 1, k)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float64)
    n = a.shape[axis]
    hi, lo = [slice(None)] * a.ndim, [slice(None)] * a.ndim
    hi[axis], lo[axis] = slice(2 * k + 1, 2 * k + 1 + n), slice(0, n)
    return ((c[tuple(hi)] - c[tuple(lo)]) / (2 * k + 1)).astype(np.float32)


def blur(a, sigma):
    """Gaussian-like blur (three box passes) of a 2D float array; sigma in px. numpy (+ Pillow resize for wide
    blurs, done at a lower resolution), deterministic."""
    if sigma <= 0.3:
        return a.astype(np.float32)
    f = int(sigma // 3)
    if f >= 2 and min(a.shape) >= 8 * f:          # wide and smooth: blur a 1/f copy, scale back up
        H, W = a.shape
        small = Image.fromarray(a.astype(np.float32), "F").resize((max(1, W // f), max(1, H // f)), Image.BOX)
        sb = blur(np.asarray(small, np.float32), sigma / f)
        return np.asarray(Image.fromarray(sb, "F").resize((W, H), Image.BILINEAR), np.float32)
    k = max(1, int(round((math.sqrt(4 * sigma * sigma + 1) - 1) / 2)))
    out = a.astype(np.float32)
    for _ in range(3):
        out = _box(_box(out, k, 0), k, 1)
    return out


def value_noise(shape, cell, rng):
    H, W = shape
    gh, gw = max(2, int(H / cell) + 2), max(2, int(W / cell) + 2)
    g = (rng.random((gh, gw)) * 255).astype(np.uint8)
    im = Image.fromarray(g, "L").resize((max(W, int(gw * cell)), max(H, int(gh * cell))), Image.BICUBIC)
    return np.asarray(im, dtype=np.float32)[:H, :W] / 255.0 - 0.5


def paper_texture(shape, P, seed):
    """Procedural paper, about -1..1: value noise at several scales + thin fibres (mostly horizontal)."""
    rng = np.random.default_rng(seed)
    H, W = shape
    s = H / REF_H
    t = np.zeros(shape, np.float32)
    for cell, amp in ((180, 0.55), (60, 0.5), (18, 0.4), (5, 0.35), (2, 0.3)):
        t += amp * value_noise(shape, max(1.0, cell * s), rng)
    fib = Image.new("L", (W, H), 0)
    dr = ImageDraw.Draw(fib)
    for _ in range(int(P["fibres"] * W * H / (1920 * 1080))):
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        ang = rng.normal(0, 0.5) + (math.pi / 2 if rng.random() < 0.25 else 0)
        L = rng.uniform(15, 90) * s
        pts = [(x + math.cos(ang) * L * k / 5 + rng.normal(0, 1.2), y + math.sin(ang) * L * k / 5 + rng.normal(0, 1.2))
               for k in range(6)]
        dr.line(pts, fill=int(rng.uniform(40, 120)), width=1)
    fib = np.asarray(fib.filter(ImageFilter.GaussianBlur(0.6)), np.float32) / 255.0
    return t / (np.abs(t).max() + 1e-6) + P["fibre_amount"] * fib


LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


MIST_FIELD_KEYS = ("amount", "start", "falloff", "sky", "max", "low", "low_from")


def mist_field(F, depth, H):
    """Mist amount 0..max (H, W) from the depth pass. depth = (metres, sky bool)."""
    metres, sky = depth
    s = H / REF_H
    d = np.expm1(blur(np.log1p(metres), 1.5 * s))
    f = F["amount"] * (1 - np.exp(-np.clip(d - F["start"], 0, None) / F["falloff"]))
    if F["low"] > 0:
        ys = np.linspace(0, 1, H, dtype=np.float32)[:, None]
        f = f * (1 + F["low"] * smoothstep(F["low_from"], 1.0, ys))
    f = np.where(sky, F["sky"], f)
    return np.clip(blur(f, 2.0 * s), 0, F["max"])


def mist(out, p, depth, scale=1.0, field=None):
    """Blend toward the mist colour by distance. depth = (metres, sky bool) or None; field: a ready mist_field."""
    F = p["mist"]
    if depth is None or F["amount"] <= 0 or scale <= 0:
        return out
    if field is None:
        field = mist_field(F, depth, out.shape[0])
    f = (field * scale)[..., None]
    fc = hexrgb(F["color"])
    lum = (out @ LUMA)[..., None]
    fcol = np.clip(fc * (0.85 + 0.15 * lum / max(float(fc.mean()), 1e-3)), 0, 1)   # mist glows where the scene is bright
    return out * (1 - f) + fcol * f


class Grader:
    """Grades frames of one size with one parameter set. LUTs and the paper texture are built once."""

    def __init__(self, g):
        self.scene, self.subject, self.seed = resolve(g)
        self.luts = {"scene": self._lut(self.scene)}
        if self.subject:
            self.luts["subject"] = self._lut(self.subject)
        self._static = {}

    @staticmethod
    def _lut(p):
        return ImageFilter.Color3DLUT(LUT_INTERNAL, lut_table(p, LUT_INTERNAL).reshape(-1))

    def static(self, H, W):
        """(paper texture or None, vignette weight or None) for this frame size."""
        if (H, W) not in self._static:
            Pp, V = self.scene["paper"], self.scene["vignette"]
            paper = paper_texture((H, W), Pp, self.seed) if Pp["amount"] > 0 else None
            vig = None
            if V["amount"] > 0:
                yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
                r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / math.sqrt(2)
                vig = (V["amount"] * smoothstep(V["radius"], 1.05, r))[..., None].astype(np.float32)
            self._static[(H, W)] = (paper, vig)
        return self._static[(H, W)]

    def weight(self, mask):
        """Feathered subject weight 0..1 (H, W) from a raw mask 0..1."""
        L = self.subject["layer"]
        return np.clip(blur(mask, L["edge"] * mask.shape[0] / REF_H), 0, 1)

    def frame(self, img, depth=None, mask=None):
        """img: PIL RGB or uint8 (H, W, 3). depth: (metres, sky) or None. mask: float (H, W) 0..1 or None. -> uint8."""
        im = img if isinstance(img, Image.Image) else Image.fromarray(np.ascontiguousarray(img), "RGB")
        im = im.convert("RGB")
        W, H = im.size
        f = np.float32(1 / 255.0)
        field = None
        if depth is not None and self.scene["mist"]["amount"] > 0:
            field = mist_field(self.scene["mist"], depth, H)
        out = mist(np.asarray(im.filter(self.luts["scene"]), np.float32) * f, self.scene, depth, field=field)
        if mask is not None and self.subject:
            L = self.subject["layer"]
            same = all(self.subject["mist"][k] == self.scene["mist"][k] for k in MIST_FIELD_KEYS)
            subj = mist(np.asarray(im.filter(self.luts["subject"]), np.float32) * f, self.subject, depth,
                        scale=L["mist_keep"], field=field if same else None)
            m = self.weight(mask)
            out = out * (1 - (m * L["opacity"])[..., None]) + subj * (m * L["opacity"])[..., None]
            hw = L["rim_width"] * H / REF_H
            if L["rim"] > 0 and hw > 0:
                rim = (np.clip((blur(m, hw) - m) * 2.0, 0, 1) * L["rim"])[..., None]
                out = out * (1 - rim) + hexrgb(self.subject["mist"]["color"]) * rim
        paper, vig = self.static(H, W)
        if paper is not None:
            Pp = self.scene["paper"]
            k = Pp["amount"] * (Pp["dark"] + (1 - Pp["dark"]) * (out @ LUMA))
            out = out * (1 + (k * paper)[..., None])
            if Pp["tint"] > 0:
                out = out * (1 - Pp["tint"]) + hexrgb(Pp["color"]) * out.mean(-1, keepdims=True) * Pp["tint"]
        if vig is not None:
            warm = hexrgb(self.scene["vignette"]["color"])
            out = out * (1 - vig) + out * (warm / max(float(warm.max()), 1e-3)) * vig * 0.6
        return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)


# ============================================================================ passes
def read_depth(path, size, depth_range):
    """Blender depth pass -> (metres float32, sky bool). size = (W, H) of the frame."""
    with Image.open(path) as im:
        if im.mode == "F":
            v = np.asarray(im, np.float32)
        elif im.mode.startswith("I"):
            v = np.asarray(im).astype(np.float32) / 65535.0
        else:
            v = np.asarray(im.convert("L")).astype(np.float32) / 255.0
    if (v.shape[1], v.shape[0]) != tuple(size):
        v = np.asarray(Image.fromarray(v.astype(np.float32), "F").resize(size, Image.BILINEAR), np.float32)
    return depth_metres(v, depth_range)


def depth_metres(v, depth_range):
    """Normalised depth pass (near = 1, far and sky = 0) -> (metres, sky). Beyond `far` counts as sky."""
    near, far = depth_range
    return (near + (1 - np.clip(v, 0, 1)) * (far - near)).astype(np.float32), v <= 1.5 / 65535.0


def read_depth_array(a, depth_range):
    """uint16 (or uint8) depth pass array -> (metres, sky)."""
    return depth_metres(np.asarray(a, np.float32) / (65535.0 if a.dtype == np.uint16 else 255.0), depth_range)


def read_mask(paths, size):
    """Union (max) of 8-bit mask passes -> float32 (H, W) 0..1."""
    m = None
    for p in paths:
        with Image.open(p) as im:
            if im.mode.startswith("I"):
                a = np.asarray(im).astype(np.float32) / 65535.0
            else:
                a = np.asarray(im.convert("L")).astype(np.float32) / 255.0
        if (a.shape[1], a.shape[0]) != tuple(size):
            a = np.asarray(Image.fromarray(a, "F").resize(size, Image.BILINEAR), np.float32)
        m = a if m is None else np.maximum(m, a)
    return np.clip(m, 0, 1)


def pngs(folder):
    return sorted(p for p in Path(folder).iterdir() if p.suffix.lower() == ".png" and p.is_file())


class PassSource:
    """A pass given as one file (every frame) or a folder. A folder is matched by frame file name when any name
    matches (then a missing name is an error, never the neighbour's pass), else by order (video frames)."""

    def __init__(self, path, label, names=None):
        self.path, self.label, self.by_order = Path(path), label, None
        if self.path.is_dir():
            self.files = pngs(self.path)
            if not self.files:
                raise Refused(f"{label} {path}: no PNG files")
            self.by_name = {p.name: p for p in self.files}
            if names is not None:
                self.by_order = not any(n in self.by_name for n in names)
        elif self.path.is_file():
            self.files = None
        else:
            raise Refused(f"{label} {path}: not found")

    def get(self, index, name):
        if self.files is None:
            return self.path
        if self.by_order is None:                  # frame names not known up front (a video): the first decides
            self.by_order = name not in self.by_name
        if not self.by_order:
            if name in self.by_name:
                return self.by_name[name]
            raise Failed(f"{self.label} {self.path}: no {name} for frame {index + 1} (the pass is matched by file "
                         f"name; re-render the missing frame)")
        if index < len(self.files):
            return self.files[index]
        raise Failed(f"{self.label} {self.path}: no file for frame {index + 1} ({name}): {len(self.files)} files")


# ============================================================================ frame sources / sinks
def ffmpeg_bin(name="ffmpeg"):
    env = (os.environ.get("FILM_FFMPEG") or "").strip()
    if env and os.path.isfile(env):
        if name == "ffmpeg":
            return env
        cand = os.path.join(os.path.dirname(env), name + (".exe" if env.lower().endswith(".exe") else ""))
        if os.path.isfile(cand):
            return cand
    return shutil.which(name)


def probe(video):
    """(W, H, fps, has_audio) of a video, with ffprobe."""
    fp = ffmpeg_bin("ffprobe")
    if not fp:
        raise Failed("ffprobe is not installed (comes with ffmpeg; or set FILM_FFMPEG)")
    r = subprocess.run([fp, "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate",
                        "-of", "json", str(video)], capture_output=True, text=True)
    if r.returncode:
        raise Failed(f"ffprobe cannot read {video}: {(r.stderr.strip().splitlines() or ['?'])[-1]}")
    streams = json.loads(r.stdout or "{}").get("streams", [])
    vs = [s for s in streams if s.get("codec_type") == "video"]
    if not vs:
        raise Failed(f"{video}: no video stream")
    num, _, den = str(vs[0].get("r_frame_rate", "24/1")).partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 24.0
    return int(vs[0]["width"]), int(vs[0]["height"]), fps, any(s.get("codec_type") == "audio" for s in streams)


def video_frames(video, size):
    ff = ffmpeg_bin()
    if not ff:
        raise Failed("ffmpeg is not installed (or set FILM_FFMPEG)")
    W, H = size
    errf = tempfile.TemporaryFile()                # stderr in a file: a full pipe would block ffmpeg
    proc = subprocess.Popen([ff, "-v", "error", "-i", str(video), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                            stdout=subprocess.PIPE, stderr=errf)
    n = W * H * 3
    i = 0
    done = False
    try:
        while True:
            buf = proc.stdout.read(n)
            if len(buf) < n:
                break
            yield i, f"{i + 1:06d}.png", np.frombuffer(buf, np.uint8).reshape(H, W, 3)
            i += 1
        done = True
    finally:
        proc.stdout.close()
        if not done and proc.poll() is None:    # the caller stopped early (preview, a failed frame)
            proc.kill()
        rc = proc.wait()
        errf.seek(0)
        err = errf.read().decode("utf-8", "replace")
        errf.close()
    if rc or i == 0:
        raise Failed(f"ffmpeg could not decode {video}: {(err.strip().splitlines() or ['no frames'])[-1]}")


class VideoSink:
    def __init__(self, path, size, fps, audio_from=None):
        ff = ffmpeg_bin()
        if not ff:
            raise Failed("ffmpeg is not installed (or set FILM_FFMPEG)")
        W, H = size
        cmd = [ff, "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", f"{fps:g}", "-i", "-"]
        if audio_from:
            cmd += ["-i", str(audio_from), "-map", "0:v", "-map", "1:a?", "-c:a", "copy"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-preset", "medium", "-movflags", "+faststart",
                str(path)]
        self.path = path
        self.errf = tempfile.TemporaryFile()       # stderr in a file: a full pipe would block ffmpeg
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=self.errf)

    def _err(self):
        self.errf.seek(0)
        err = self.errf.read().decode("utf-8", "replace")
        return (err.strip().splitlines() or ["?"])[-1]

    def write(self, name, arr):
        try:
            self.proc.stdin.write(np.ascontiguousarray(arr).tobytes())
        except (BrokenPipeError, OSError):
            self.proc.kill()
            self.proc.wait()
            raise Failed(f"ffmpeg stopped while encoding {self.path}: {self._err()}") from None

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        rc = self.proc.wait()
        err = self._err()
        self.errf.close()
        if rc:
            raise Failed(f"ffmpeg could not encode {self.path}: {err}")

    def abort(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.proc.kill()
        self.proc.wait()
        self.errf.close()


class DirSink:
    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    def write(self, name, arr):
        Image.fromarray(arr, "RGB").save(self.path / (Path(name).stem + ".png"), optimize=False)

    def close(self):
        pass

    def abort(self):
        pass


class ImageSink:
    def __init__(self, path):
        self.path = Path(path)

    def write(self, name, arr):
        Image.fromarray(arr, "RGB").save(self.path, optimize=False)

    def close(self):
        pass

    def abort(self):
        pass


def png_frames(files):
    for i, p in enumerate(files):
        try:
            with Image.open(p) as im:
                yield i, p.name, np.asarray(im.convert("RGB"))
        except OSError as e:
            raise Failed(f"cannot read {p} ({e})")


def read_render_json(folder):
    p = Path(folder) / "render.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise Refused(f"{p}: not valid JSON ({e})")


class Job:
    """What to grade: frames + passes + metadata, from IN and the pass flags."""

    def __init__(self, a):
        src = Path(a.input)
        self.audio = None
        info = {}
        depth, masks = a.depth, list(a.mask or [])
        if src.is_dir() and (src / "beauty").is_dir():                       # a Blender render folder
            info = read_render_json(src)
            self.kind, self.files = "seq", pngs(src / "beauty")
            if depth is None and (src / "depth").is_dir() and not a.no_depth:
                depth = str(src / "depth")
            for asset in a.subject or []:
                d = src / "mask" / asset
                if not d.is_dir():
                    have = sorted(p.name for p in (src / "mask").iterdir() if p.is_dir()) if (src / "mask").is_dir() else []
                    raise Refused(f"--subject {asset}: no mask pass {d} (masks here: {', '.join(have) or 'none'}; "
                                  f"render with --passes depth mask)")
                masks.append(str(d))
        elif a.subject:
            raise Refused("--subject needs IN = a Blender render folder (renders3d/s<NN>/); otherwise pass --mask")
        elif src.is_dir():
            self.kind, self.files = "seq", pngs(src)
        elif src.is_file() and src.suffix.lower() in VIDEO_EXT:
            self.kind, self.files = "video", None
        elif src.is_file() and src.suffix.lower() in IMAGE_EXT:
            self.kind, self.files = "image", [src]
        elif not src.exists():
            raise Refused(f"IN {src}: not found")
        else:
            raise Refused(f"IN {src}: not a .png/.jpg, a folder of PNG frames, a video or a render folder")
        if self.files is not None and not self.files:
            raise Refused(f"IN {src}: no PNG frames")
        self.src = src
        if self.kind == "video":
            W, H, self.fps, has_audio = probe(src)
            self.size, self.count = (W, H), None
            self.audio = src if has_audio else None
        else:
            with Image.open(self.files[0]) as im:
                self.size = im.size
            self.count = len(self.files)
            self.fps = float(info.get("fps") or 24)
        if a.fps:
            self.fps = a.fps
        self.depth_range = tuple(a.depth_range) if a.depth_range else tuple(info.get("depth_range") or ())
        if depth is not None and a.no_depth:
            raise Refused("--depth and --no-depth together")
        if depth is not None and not self.depth_range:
            rj = read_render_json(Path(depth).parent) if Path(depth).is_dir() else read_render_json(Path(depth).parent.parent)
            self.depth_range = tuple(rj.get("depth_range") or ())
            if not self.depth_range:
                raise Refused(f"--depth {depth}: depth_range unknown (no render.json next to it): pass --depth-range NEAR FAR")
        if self.depth_range and not (len(self.depth_range) == 2 and 0 <= self.depth_range[0] < self.depth_range[1]):
            raise Refused(f"depth_range {list(self.depth_range)} must be [near, far] with 0 <= near < far")
        names = [p.name for p in self.files] if self.files is not None else None
        self.depth = PassSource(depth, "--depth", names) if depth is not None else None
        self.masks = [PassSource(m, "--mask", names) for m in masks]

    def frames(self):
        if self.kind == "video":
            return video_frames(self.src, self.size)
        return png_frames(self.files)

    def passes(self, i, name, grader):
        depth = read_depth(self.depth.get(i, name), self.size, self.depth_range) if self.depth else None
        mask = read_mask([m.get(i, name) for m in self.masks], self.size) if self.masks and grader.subject else None
        return depth, mask


# ============================================================================ CLI
def side_by_side(before, after):
    H, W = before.shape[:2]
    gap = max(2, W // 240)
    sheet = np.full((H, W * 2 + gap, 3), 255, np.uint8)
    sheet[:, :W], sheet[:, W + gap:] = before, after
    return sheet


def refuse_existing(path):
    p = Path(path)
    if p.is_dir() and any(p.iterdir()):
        raise Refused(f"{p} already exists and is not empty: not overwriting (pick a new name, _v<NN>)")
    if p.exists() and not p.is_dir():
        raise Refused(f"{p} already exists: not overwriting (pick a new name, _v<NN>)")


def parse(argv):
    ap = argparse.ArgumentParser(prog="grade.py", description="Two-layer ink-wash grade + .cube export (free, local).",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n")[1])
    ap.add_argument("input", nargs="?", help="image, folder of PNG frames, video, or Blender render folder")
    ap.add_argument("output", nargs="?", help=".png, new folder, or .mp4")
    ap.add_argument("--style", help="styles/<id>: parameters from style.yaml grade:")
    ap.add_argument("--params", help="JSON with the same shape as grade: (deep-merged over --style)")
    ap.add_argument("--depth", help="depth pass: a PNG or a folder (default: depth/ of a render folder)")
    ap.add_argument("--no-depth", action="store_true", help="ignore the depth pass of a render folder (no mist)")
    ap.add_argument("--depth-range", nargs=2, type=float, metavar=("NEAR", "FAR"),
                    help="metres of the depth pass (default: render.json depth_range)")
    ap.add_argument("--mask", action="append", help="subject mask pass: a PNG or a folder (repeatable: union)")
    ap.add_argument("--subject", nargs="+", help="asset id(s) of a render folder: mask/<asset>/ is the subject")
    ap.add_argument("--fps", type=float, help="fps of an .mp4 written from frames (default: render.json fps or 24)")
    ap.add_argument("--preview", help="write one frame side by side (before | after) to this .png and stop")
    ap.add_argument("--frame", type=int, default=1, help="frame number for --preview (1 = first)")
    ap.add_argument("--export-lut", help="write the colour part as a .cube 3D LUT")
    ap.add_argument("--layer", choices=("scene", "subject"), default="scene", help="which layer --export-lut writes")
    ap.add_argument("--lut-size", type=int, default=33, help="LUT_3D_SIZE of --export-lut (2-129, default 33)")
    ap.add_argument("--check", action="store_true", help="only validate the parameters")
    return ap.parse_args(argv)


def part_path(out):
    """Where OUT is written until it is complete: <name>.part/ (folder) or <stem>.part<suffix> (file)."""
    return out.with_name(out.name + ".part") if not out.suffix else out.with_name(out.stem + ".part" + out.suffix)


def remove_path(p):
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
    elif p.exists():
        p.unlink()


def run(a):
    g, srcs = load_params(a.style, a.params)
    if a.check:
        scene, subject, seed = resolve(g)
        print(f"grade: ok ({' + '.join(srcs)}): layers scene{' + subject' if subject else ''}, seed {seed}")
        return 0
    if not (a.input or a.export_lut):
        raise Refused("nothing to do: pass IN OUT, IN --preview P.png, or --export-lut F.cube")
    if a.export_lut:                              # checked first, written only after IN/OUT are checked too
        if not 2 <= a.lut_size <= 129:
            raise Refused(f"--lut-size {a.lut_size}: must be 2-129")
        scene, subject, _ = resolve(g)
        if a.layer == "subject" and not subject:
            raise Refused("--layer subject: the grade has no subject: block")
        refuse_existing(a.export_lut)
    job = out = None
    single = False
    if a.input:
        if a.preview and a.output:
            raise Refused("--preview writes one frame: drop OUT")
        if not a.preview and not a.output:
            raise Refused("OUT is missing (or use --preview P.png)")
        job = Job(a)
        if a.preview:
            refuse_existing(a.preview)
            if a.frame < 1 or (job.count is not None and a.frame > job.count):
                raise Refused(f"--frame {a.frame}: IN has {job.count} frame(s)")
        else:
            out = Path(a.output)
            refuse_existing(out)
            single = job.kind == "image" or (job.count == 1 and out.suffix.lower() == ".png")
            if job.kind == "image" and out.suffix.lower() != ".png":
                raise Refused(f"OUT {out}: one image in -> a .png out")
            if not single and out.suffix and out.suffix.lower() not in VIDEO_OUT_EXT:
                raise Refused(f"OUT {out}: a folder (no suffix) or a {' / '.join(sorted(VIDEO_OUT_EXT))} "
                              "(H.264)")
    if a.export_lut:
        write_cube(a.export_lut, subject if a.layer == "subject" else scene, a.lut_size,
                   f"film-lab grade {a.layer}")
        print(f"lut {a.export_lut} ({a.layer}, {a.lut_size}^3; colour only: mist, subject layer, paper and vignette "
              f"need grade.py)")
        if not a.input:
            return 0
    grader = Grader(g)
    if job.masks and not grader.subject:
        print("grade: WARN mask given but the grade has no subject: block: one layer only", file=sys.stderr)
    if grader.subject and not job.masks:
        print("grade: note: no mask (--mask / --subject): scene layer only", file=sys.stderr)
    if job.depth is None and grader.scene["mist"]["amount"] > 0:
        print("grade: note: no depth pass: no mist", file=sys.stderr)

    if a.preview:
        frames = job.frames()
        try:
            for i, name, arr in frames:
                if i + 1 == a.frame:
                    res = grader.frame(arr, *job.passes(i, name, grader))
                    Image.fromarray(side_by_side(arr, res), "RGB").save(a.preview)
                    print(f"preview {a.preview} (frame {a.frame}: before | after)")
                    return 0
        finally:
            frames.close()
        raise Refused(f"--frame {a.frame}: IN has fewer frames")

    # written under a .part name, renamed when every frame is done: a failed run leaves nothing that looks finished
    part = part_path(out)
    if part.exists():
        print(f"grade: note: removing {part} left by an earlier run that stopped", file=sys.stderr)
        remove_path(part)
    out.parent.mkdir(parents=True, exist_ok=True)
    if single:                                     # one image, or a sequence / render folder of one frame
        sink = ImageSink(part)
    elif out.suffix:
        sink = VideoSink(part, job.size, job.fps, audio_from=job.audio)
    else:
        sink = DirSink(part)
    n = 0
    frames = job.frames()
    try:
        for i, name, arr in frames:
            if arr.shape[1::-1] != job.size:
                raise Failed(f"frame {i + 1} ({name}) is {arr.shape[1]}x{arr.shape[0]}, the first is "
                             f"{job.size[0]}x{job.size[1]}")
            sink.write(name, grader.frame(arr, *job.passes(i, name, grader)))
            n += 1
        sink.close()
    except BaseException:
        frames.close()
        sink.abort()
        remove_path(part)
        raise
    if out.is_dir():                               # an empty folder named OUT (refuse_existing let it through)
        out.rmdir()
    os.replace(part, out)
    layers = "scene + subject" if grader.subject and job.masks else "scene"
    print(f"graded {n} frame(s) -> {out} ({layers}; mist {'on' if job.depth else 'off'})")
    return 0


def main(argv=None):
    a = parse(sys.argv[1:] if argv is None else argv)
    try:
        return run(a)
    except Refused as e:
        print(f"grade: {e}", file=sys.stderr)
        return 2
    except Failed as e:
        print(f"grade: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
