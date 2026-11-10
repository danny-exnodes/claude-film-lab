#!/usr/bin/env python3
"""Draw 4 placeholder plates + anchors.json for a free test of the compose kit (no image generation, no API).

  python3 tools/compose/demo_plates.py out/demo        # -> out/demo/plates/ep00_s01_L{1..4}_*.png, out/demo/anchors.json

L1 opaque landscape 2400x1350 (sky, far ridges, a pale sun) · L2 RGBA mid ridge fading into mist · L3 RGBA foreground
rocks and a pine · L4 RGBA 2048x2048 creature silhouette with a long tail (anchors: subject, feet, tail_root,
tail_tip, boxes tail and eye). Ink-wash-like on purpose, but they are only test shapes: never shown as a film.
Needs Pillow and numpy (installed with rembg by the session hook).
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

RNG = np.random.default_rng(20261110)
PAPER = np.array([239, 231, 214], np.float32)
INK = np.array([26, 23, 20], np.float32)


def noise(w, h, cells, octaves=4):
    """Smooth value noise 0..1 (upscaled random grids), shape (h, w)."""
    out = np.zeros((h, w), np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        cw, ch = max(2, int(cells * 2 ** o)), max(2, int(cells * 2 ** o * h / w))
        grid = Image.fromarray((RNG.random((ch, cw)) * 255).astype(np.uint8))
        out += amp * np.asarray(grid.resize((w, h), Image.BICUBIC), np.float32) / 255
        total += amp
        amp *= 0.5
    return out / total


def ridge(w, base, amp, cells, phase):
    x = np.arange(w, dtype=np.float32) / w
    n = noise(w, 8, cells, 3)[4]
    return base + amp * (0.55 * np.sin((x * 2.1 + phase) * np.pi) + 0.9 * (n - 0.5))


def ink_mix(tone, shade):
    """Ink tone 0 (paper) .. 1 (burnt ink) -> RGB, shade adds texture."""
    t = np.clip(tone + shade, 0, 1)[..., None]
    return PAPER * (1 - t) + INK * t


def rgba(rgb, alpha):
    return Image.fromarray(np.dstack([np.clip(rgb, 0, 255), np.clip(alpha * 255, 0, 255)]).astype(np.uint8), "RGBA")


def plate_l1(w=2400, h=1350):
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    tex = noise(w, h, 5) - 0.5
    tone = 0.05 + 0.06 * y + 0.05 * tex
    rgb = ink_mix(np.broadcast_to(tone, (h, w)), 0)
    rgb += np.array([10, 4, -8], np.float32) * (1 - y)[..., None]  # warm low sun light on the upper sky
    yy = np.arange(h, dtype=np.float32)[:, None]
    for base, amp, cells, ph, tone in ((610, 120, 3, 0.2, 0.22), (700, 90, 5, 1.1, 0.34)):
        top = ridge(w, base, amp, cells, ph)[None, :]
        depth = np.clip((yy - top) / 260, 0, 1)
        body = (yy > top) * (1 - depth) ** 1.4                              # dissolves downward into mist
        shade = 0.08 * (noise(w, h, 9) - 0.5)
        mix = np.clip(body * tone + shade * body, 0, 1)[..., None]
        rgb = rgb * (1 - mix) + INK * mix
    sx, sy = 1935, 381                                                      # the sun the template's glow sits on
    d = np.sqrt((np.arange(w)[None, :] - sx) ** 2 + (yy - sy) ** 2)
    rgb += (np.clip(1 - d / 150, 0, 1) ** 0.6 * 22)[..., None] * np.array([1, 0.9, 0.7], np.float32)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")


def plate_l2(w=2400, h=1350):
    yy = np.arange(h, dtype=np.float32)[:, None]
    top = ridge(w, 760, 150, 4, 0.7)[None, :]
    depth = np.clip((yy - top) / 330, 0, 1)
    alpha = (yy > top - 2) * (1 - depth) ** 1.6
    alpha = np.asarray(Image.fromarray((alpha * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3)), np.float32) / 255
    streaks = noise(w, h, 40, 2)                                            # dry-brush texture along the slopes
    rgb = ink_mix(np.full((h, w), 0.5, np.float32) + 0.25 * (1 - depth), 0.2 * (streaks - 0.5))
    return rgba(rgb, alpha)


def plate_l3(w=2400, h=1350):
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    d.polygon([(0, 1350), (0, 1010), (160, 960), (330, 1040), (520, 1120), (700, 1230), (760, 1350)], fill=255)
    d.polygon([(1720, 1350), (1830, 1180), (2010, 1080), (2200, 1040), (2400, 1000), (2400, 1350)], fill=255)
    d.polygon([(0, 1350), (0, 1290), (900, 1310), (1500, 1300), (2400, 1280), (2400, 1350)], fill=255)
    d.line([(150, 1000), (190, 700), (250, 430), (300, 260)], fill=255, width=30)          # a leaning pine
    for y, span in ((330, 260), (450, 330), (580, 380), (700, 300)):
        d.ellipse([250 - span // 3, y - 40, 250 + span, y + 40], fill=255)
    mask = np.asarray(m.filter(ImageFilter.GaussianBlur(2.5)), np.float32) / 255
    soft = np.asarray(m.filter(ImageFilter.GaussianBlur(18)), np.float32) / 255
    edge = np.clip(mask - soft, 0, 1)                                       # loaded stroke: darker at its edge
    rgb = ink_mix(0.72 + 0.6 * edge, 0.18 * (noise(w, h, 30, 2) - 0.5))
    return rgba(rgb, mask)


def tail_poly(root, ctrl, tip, w0, w1, n=48):
    pts_l, pts_r = [], []
    for i in range(n + 1):
        u = i / n
        p = [(1 - u) ** 2 * root[k] + 2 * (1 - u) * u * ctrl[k] + u ** 2 * tip[k] for k in (0, 1)]
        dp = [2 * (1 - u) * (ctrl[k] - root[k]) + 2 * u * (tip[k] - ctrl[k]) for k in (0, 1)]
        ln = (dp[0] ** 2 + dp[1] ** 2) ** 0.5 or 1
        nx, ny = -dp[1] / ln, dp[0] / ln
        wd = (w0 + (w1 - w0) * u) / 2
        pts_l.append((p[0] + nx * wd, p[1] + ny * wd))
        pts_r.append((p[0] - nx * wd, p[1] - ny * wd))
    return pts_l + pts_r[::-1]


def plate_l4(n=2048):
    m = Image.new("L", (n, n), 0)
    d = ImageDraw.Draw(m)
    d.ellipse([470, 1020, 1330, 1480], fill=255)                            # body
    d.polygon([(560, 1130), (440, 980), (620, 900), (760, 1080)], fill=255)  # neck
    d.ellipse([330, 810, 710, 1190], fill=255)                              # head
    d.polygon([(380, 860), (330, 640), (470, 820)], fill=255)               # horns
    d.polygon([(560, 830), (620, 610), (650, 840)], fill=255)
    for x0 in (560, 720, 1080, 1220):                                       # legs, feet on y = 1720
        d.polygon([(x0, 1360), (x0 + 80, 1360), (x0 + 70, 1720), (x0 + 5, 1720)], fill=255)
    d.polygon(tail_poly((1300, 1200), (1660, 1260), (1985, 885), 84, 16), fill=255)
    d.ellipse([1930, 820, 2030, 930], fill=255)                             # tail tuft
    mask = np.asarray(m.filter(ImageFilter.GaussianBlur(2)), np.float32) / 255
    soft = np.asarray(m.filter(ImageFilter.GaussianBlur(26)), np.float32) / 255
    edge = np.clip(mask - soft, 0, 1)
    rgb = ink_mix(0.5 + 0.7 * edge, 0.2 * (noise(n, n, 24, 3) - 0.5))
    img = rgba(rgb, mask)
    e = ImageDraw.Draw(img)
    e.ellipse([472, 952, 608, 1038], fill=(236, 226, 200, 255))             # the eye (anchors box "eye")
    e.ellipse([515, 965, 575, 1028], fill=(150, 40, 30, 255))
    e.ellipse([532, 978, 558, 1014], fill=(18, 14, 12, 255))
    e.ellipse([472, 952, 608, 1038], outline=(20, 16, 12, 255), width=6)
    return img


# The shape tools/layers/anchors.py writes: points per layer file; a box is the point pair <box>_tl / <box>_br.
ANCHORS = {
    "ep00_s01_L4_demo-thu_v01.png": {
        "subject": [540, 995], "feet": [900, 1720], "tail_root": [1310, 1195], "tail_tip": [1985, 880],
        "tail_tl": [1290, 760], "tail_br": [2044, 1330], "eye_tl": [466, 946], "eye_br": [614, 1044],
    }
}


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "out/demo")
    (root / "plates").mkdir(parents=True, exist_ok=True)
    for name, make in (("ep00_s01_L1_demo-nui_v01.png", plate_l1), ("ep00_s01_L2_demo-day_v01.png", plate_l2),
                       ("ep00_s01_L3_demo-da_v01.png", plate_l3), ("ep00_s01_L4_demo-thu_v01.png", plate_l4)):
        img = make()
        img.save(root / "plates" / name)
        print(f"{root / 'plates' / name}: {img.size[0]}x{img.size[1]} {img.mode}")
    (root / "anchors.json").write_text(json.dumps(ANCHORS, indent=1) + "\n", encoding="utf-8")
    print(f"{root / 'anchors.json'}")


if __name__ == "__main__":
    main()
