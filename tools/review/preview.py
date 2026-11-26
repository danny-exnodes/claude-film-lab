"""JPEG previews of large images for the review dashboard (tools/review/README.md, "Băng thông").

    jpeg_preview(src, dest, max_px=1280, quality=82) -> dest, or None when Pillow is not importable or the image
                                                          cannot be read

A 1664x928 PNG of 2-3 MB becomes a ~150-300 KB JPEG: the public tunnel (ngrok free) runs out of bandwidth on PNGs.
Pillow is optional (requirements-ci.txt has it; Blender's Python has not): client.py publishes the original when this
returns None. Never raises. Alpha is flattened on the dashboard's dark background.
"""
import importlib
import os

MAX_PX = 1280
QUALITY = 82
BACKGROUND = (10, 14, 22)          # --bg of web/app.css


def _pil():
    try:
        return importlib.import_module("PIL.Image")
    except Exception:
        return None


def available():
    return _pil() is not None


def jpeg_preview(src, dest, max_px=MAX_PX, quality=QUALITY):
    Image = _pil()
    if Image is None:
        return None
    try:
        with Image.open(src) as im:
            im.load()
            if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, BACKGROUND)
                bg.paste(im, mask=im.getchannel("A"))
                im = bg
            elif im.mode != "RGB":
                im = im.convert("RGB")
            if max(im.size) > max_px:
                im.thumbnail((max_px, max_px), Image.LANCZOS)
            os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
            tmp = dest + ".part"
            im.save(tmp, "JPEG", quality=int(quality), optimize=True, progressive=True)
        os.replace(tmp, dest)
        return dest
    except Exception:
        try:
            os.remove(dest + ".part")
        except OSError:
            pass
        return None
