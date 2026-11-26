#!/usr/bin/env python3
"""Style frames of an episode (stage 3b, blender/code; film-pipeline §2.3): contact sheet, palette, comparison.

  python3 tools/styleframes.py sheet <frame|dir>... --out <sheet>.png [--palette-out <palette>.png] [--colors 8]
                                     [--cols 4] [--tile 480] [--json]
  python3 tools/styleframes.py compare <reference>.png <frame|dir>... [--tol 1.0] [--json]

sheet    one contact sheet of the frames (file-name order, each tile labelled with its file name) and, with
         --palette-out, a palette strip: the --colors main colours of all frames together, with hex and share.
         Prints the palette and the numbers of every frame (luma, contrast, saturation; 0-100) for the
         `## Bảng màu` section of STYLE-FRAMES.md.
compare  the same numbers for a reference frame ("khung chuẩn") and for each later frame, with the difference and the
         palette distance (how far each main colour of the reference is from the nearest colour of the frame, 0-100).
         DRIFT when a number differs by more than its tolerance (LIMITS) times --tol. Exit 1 when a frame drifts.

The numbers measure, they do not judge: the director and the owner still look at the frames. Local, free, Pillow
only, no network. Never overwrites: an existing --out / --palette-out is refused (take the next _v<NN>).
Exit codes: 0 ok, 1 drift (compare), 2 usage, unreadable image or existing output.
"""
import argparse, json, os, sys

EXTS = (".png", ".jpg", ".jpeg", ".webp")
THUMB = 256                 # measuring size (long side): numbers do not depend on the render size
LIMITS = {"luma": 8.0, "contrast": 8.0, "saturation": 10.0, "palette": 12.0}   # compare: allowed difference, 0-100
SHEET_BG, LABEL_FG, LABEL_H, GAP = (24, 24, 24), (230, 230, 230), 28, 8


class Usage(Exception):
    pass


def pil():
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageStat
    except ImportError:
        raise Usage("Pillow is not installed (it comes with rembg; requirements-ci.txt pins it)")
    return Image, ImageDraw, ImageFont, ImageStat


def frames(paths):
    """Image files of the arguments: a file as is, a folder's images in name order."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            out += sorted(os.path.join(p, n) for n in os.listdir(p) if n.lower().endswith(EXTS))
        elif os.path.isfile(p):
            out.append(p)
        else:
            raise Usage(f"{p}: no such file or folder")
    if not out:
        raise Usage("no frame (png, jpg, webp) given")
    return out


def load(path):
    Image = pil()[0]
    try:
        with Image.open(path) as im:
            return im.convert("RGB")
    except (OSError, ValueError) as e:
        raise Usage(f"{path}: not an image ({e})")


def thumb(im):
    t = im.copy()
    t.thumbnail((THUMB, THUMB))
    return t


def palette(images, n):
    """[(hex, share 0-1, (r, g, b))] of the n main colours of the images together, most used first."""
    Image = pil()[0]
    h = THUMB // 2              # every frame at the same height side by side: one quantization, no empty band
    ts = [im.resize((max(1, round(im.width * h / im.height)), h)) for im in images]
    canvas = Image.new("RGB", (sum(t.width for t in ts), h))
    x = 0
    for t in ts:
        canvas.paste(t, (x, 0))
        x += t.width
    q = canvas.quantize(colors=max(1, n), method=Image.Quantize.MEDIANCUT if hasattr(Image, "Quantize") else 0)
    pal = q.getpalette()
    counts = {i: c for c, i in q.getcolors(maxcolors=256) or []}
    total = sum(counts.values()) or 1
    out = []
    for i, c in sorted(counts.items(), key=lambda kv: -kv[1]):
        rgb = tuple(pal[3 * i:3 * i + 3])
        out.append(("#%02X%02X%02X" % rgb, c / total, rgb))
    return out[:n]


def numbers(im):
    """{"luma", "contrast", "saturation"} of an image, 0-100: mean and spread of the brightness, mean saturation."""
    ImageStat = pil()[3]
    t = thumb(im)
    lum = ImageStat.Stat(t.convert("L"))
    sat = ImageStat.Stat(t.convert("HSV").split()[1])
    return {"luma": round(lum.mean[0] / 2.55, 1), "contrast": round(lum.stddev[0] / 2.55, 1),
            "saturation": round(sat.mean[0] / 2.55, 1)}


def palette_distance(ref_pal, pal):
    """Share-weighted distance from each reference colour to the nearest colour of pal, 0 (same) - 100 (white vs
    black)."""
    if not ref_pal or not pal:
        return 0.0
    d = 0.0
    for _, share, (r, g, b) in ref_pal:
        d += share * min(((r - x) ** 2 + (g - y) ** 2 + (b - z) ** 2) ** 0.5 for _, _, (x, y, z) in pal)
    return round(d / (3 * 255 ** 2) ** 0.5 * 100, 1)


def refuse_existing(*paths):
    for p in paths:
        if p and os.path.exists(p):
            raise Usage(f"{p} exists: never overwritten, take the next _v<NN>")


def save(im, path):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    im.save(path)


def contact_sheet(paths, images, cols, tile):
    Image, ImageDraw, ImageFont, _ = pil()
    ratio = images[0].height / images[0].width
    th = max(1, round(tile * ratio))
    cols = max(1, min(cols, len(images)))
    rows = -(-len(images) // cols)
    sheet = Image.new("RGB", (GAP + cols * (tile + GAP), GAP + rows * (th + LABEL_H + GAP)), SHEET_BG)
    draw, font = ImageDraw.Draw(sheet), ImageFont.load_default()
    for k, (p, im) in enumerate(zip(paths, images)):
        x, y = GAP + (k % cols) * (tile + GAP), GAP + (k // cols) * (th + LABEL_H + GAP)
        t = im.copy()
        t.thumbnail((tile, th))
        sheet.paste(t, (x + (tile - t.width) // 2, y + (th - t.height) // 2))
        draw.text((x + 4, y + th + 8), os.path.basename(p), fill=LABEL_FG, font=font)
    return sheet


def palette_strip(pal):
    Image, ImageDraw, ImageFont, _ = pil()
    w, h = 120, 100
    strip = Image.new("RGB", (max(1, len(pal)) * w, h + LABEL_H), (255, 255, 255))
    draw, font = ImageDraw.Draw(strip), ImageFont.load_default()
    for k, (hx, share, rgb) in enumerate(pal):
        draw.rectangle((k * w, 0, (k + 1) * w - 1, h - 1), fill=rgb)
        draw.text((k * w + 4, h + 8), f"{hx} {share * 100:.0f}%", fill=(20, 20, 20), font=font)
    return strip


def cmd_sheet(a):
    paths = frames(a.frames)
    refuse_existing(a.out, a.palette_out)
    images = [load(p) for p in paths]
    pal = palette(images, a.colors)
    save(contact_sheet(paths, images, a.cols, a.tile), a.out)
    if a.palette_out:
        save(palette_strip(pal), a.palette_out)
    per = [dict(frame=os.path.basename(p), **numbers(im)) for p, im in zip(paths, images)]
    if a.json:
        print(json.dumps({"sheet": a.out, "palette_png": a.palette_out, "frames": per,
                          "palette": [{"hex": h, "share": round(s, 3)} for h, s, _ in pal]}, ensure_ascii=False,
                         indent=1))
        return 0
    print(f"sheet: {a.out} ({len(paths)} frame(s))" + (f" · palette: {a.palette_out}" if a.palette_out else ""))
    print("palette: " + " ".join(f"{h} {s * 100:.0f}%" for h, s, _ in pal))
    for r in per:
        print(f"  {r['frame']}: luma {r['luma']:g} · contrast {r['contrast']:g} · saturation {r['saturation']:g}")
    return 0


def cmd_compare(a):
    ref_im = load(a.reference)
    paths = frames(a.frames)
    ref, ref_pal = numbers(ref_im), palette([ref_im], 6)
    rows, drift = [], False
    for p in paths:
        im = load(p)
        n = numbers(im)
        n["palette"] = palette_distance(ref_pal, palette([im], 6))
        diff = {k: round(n[k] - ref.get(k, 0.0), 1) for k in LIMITS}
        bad = [k for k in LIMITS if abs(diff[k]) > LIMITS[k] * a.tol]
        drift = drift or bool(bad)
        rows.append({"frame": p, "numbers": n, "diff": diff, "drift": bad})
    if a.json:
        print(json.dumps({"reference": a.reference, "numbers": ref, "limits": LIMITS, "tol": a.tol, "frames": rows},
                         ensure_ascii=False, indent=1))
        return 1 if drift else 0
    print(f"reference {os.path.basename(a.reference)}: luma {ref['luma']:g} · contrast {ref['contrast']:g} · "
          f"saturation {ref['saturation']:g}")
    for r in rows:
        d = r["diff"]
        print(f"  {'DRIFT' if r['drift'] else 'ok   '} {os.path.basename(r['frame'])}: "
              + " · ".join(f"{k} {d[k]:+g}" for k in LIMITS)
              + (f"  ({', '.join(r['drift'])} beyond {', '.join(f'{LIMITS[k] * a.tol:g}' for k in r['drift'])})"
                 if r["drift"] else ""))
    return 1 if drift else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 epilog="exit 0 ok · 1 drift (compare) · 2 usage")
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("sheet", help="contact sheet + palette of the style frames")
    s.add_argument("frames", nargs="+", help="frame files or folders")
    s.add_argument("--out", required=True, help="contact sheet png (must not exist)")
    s.add_argument("--palette-out", default=None, help="palette strip png (must not exist)")
    s.add_argument("--colors", type=int, default=8, help="main colours of the palette (default 8)")
    s.add_argument("--cols", type=int, default=4, help="tiles per row (default 4)")
    s.add_argument("--tile", type=int, default=480, help="tile width in pixels (default 480)")
    s.add_argument("--json", action="store_true")
    c = sp.add_parser("compare", help="numbers of later frames against a reference frame")
    c.add_argument("reference", help="the reference frame (khung chuẩn)")
    c.add_argument("frames", nargs="+", help="frame files or folders to compare")
    c.add_argument("--tol", type=float, default=1.0, help="multiply every tolerance of LIMITS (default 1.0)")
    c.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "sheet":
            if a.colors < 1 or a.colors > 64 or a.cols < 1 or a.tile < 32:
                raise Usage("--colors 1-64, --cols >= 1, --tile >= 32")
            return cmd_sheet(a)
        if a.tol <= 0:
            raise Usage("--tol must be > 0")
        return cmd_compare(a)
    except Usage as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
