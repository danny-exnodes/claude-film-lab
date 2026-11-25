"""Real Blender renders of tools/blender (method: blender): a 64x36, 3-frame shot with every pass, a still twice (same
bytes), keyframes at another size, a Cycles still, a turntable and the lookbook. Free and local; skipped when no Blender
is found ($FILM_BLENDER, PATH, the usual install folders), so it skips in WSL and in cloud sessions.
Run on the Windows PC:  cd tests && python -m unittest test_blender_render -v"""
import json, os, struct, subprocess, sys, unittest, zlib
from pathlib import Path

import helpers

bl = helpers.load("blender/blender.py", "film_blender_cli_r")
BLENDER, _WHY = bl.find()
CLI = str(helpers.TOOLS / "blender" / "blender.py")

SHOT = {
    "version": 1, "size": [64, 36], "fps": 12, "seconds": 0.25, "seed": 5, "look": "ink-wash",
    "world": {"mist": 0.6, "mist_range": [4, 60], "sun": [35, 280]},
    "assets": [
        {"id": "ground", "src": "preset:ground", "params": {"width": 60, "depth": 60, "relief": 0.2}, "mask": False},
        {"id": "hills", "src": "preset:mountains", "at": [0, 30, -1], "params": {"width": 40, "depth": 12, "height": 10,
                                                                                  "peaks": 3, "res": 60}},
        {"id": "giot", "src": "preset:giot", "at": [0, 0, 0], "anim": {"action": "walk",
                                                                      "path": [[0, [0, 0, 0]], [0.25, [0.3, 0, 0]]]}}],
    "camera": {"move": "push-in", "from": [0, -4, 1.2], "to": [0, -3, 1.1], "target": "giot"},
    "passes": ["depth", "normal", "line", "mask"], "depth_range": [0.5, 60]}


def png_info(path):
    """(width, height, bit depth, colour type) from the IHDR chunk."""
    with open(path, "rb") as f:
        head = f.read(33)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", path
    w, h, depth, ctype = struct.unpack(">IIBB", head[16:26])
    return w, h, depth, ctype


def gray(path, x, y):
    from PIL import Image
    im = Image.open(path)
    v = im.getpixel((x, y))
    return v if isinstance(v, (int, float)) else v[0]


@unittest.skipUnless(BLENDER, f"Blender not found ({_WHY})")
class TestBlenderRender(helpers.TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.spec = self.tmp / "shot.json"
        self.spec.write_text(json.dumps(SHOT), encoding="utf-8")

    def cli(self, *args, timeout=1800):
        r = subprocess.run([sys.executable, CLI, *map(str, args)], capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return r

    def test_render_every_pass(self):
        out = self.tmp / "r"
        r = self.cli("render", self.spec, "--out", out)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        for f in ("0001", "0002", "0003"):
            self.assertEqual(png_info(out / "beauty" / f"{f}.png")[:3], (64, 36, 8))
            self.assertEqual(png_info(out / "depth" / f"{f}.png"), (64, 36, 16, 0))
            self.assertEqual(png_info(out / "normal" / f"{f}.png"), (64, 36, 16, 2))
            self.assertEqual(png_info(out / "line" / f"{f}.png")[:2], (64, 36))
            self.assertTrue((out / "mask" / "giot" / f"{f}.png").is_file())
            self.assertTrue((out / "mask" / "hills" / f"{f}.png").is_file())
        self.assertFalse((out / "mask" / "ground").exists(), "mask: false")
        self.assertTrue((out / "beauty.mp4").is_file() and (out / "beauty.mp4").stat().st_size > 0)
        info = json.loads((out / "render.json").read_text(encoding="utf-8"))
        self.assertTrue(info["blender"].startswith("5."), info["blender"])
        self.assertIn(info["engine"], ("BLENDER_EEVEE", "CYCLES"))
        self.assertEqual(len(info["seconds_per_frame"]), 3)
        self.assertEqual(info["size"], [64, 36])
        self.assertEqual(info["depth_range"], [0.5, 60])
        print(f"\n  real render: {info['engine']} on {info['device']}, {info['mean_seconds_per_frame']} s/frame")
        try:
            import PIL  # noqa: F401
        except ImportError:
            return
        d = out / "depth" / "0002.png"
        from PIL import Image
        self.assertEqual(Image.open(d).getextrema()[0], 0, "the sky is black (far)")
        self.assertGreater(gray(d, 32, 30), 40000, "giot / the ground near the camera is near white")
        m = out / "mask" / "giot" / "0002.png"
        self.assertEqual(gray(m, 1, 1), 0)
        self.assertGreater(gray(m, 32, 22), 200, "giot is in the middle of the frame")

    def test_still_twice_same_bytes_and_cycles(self):
        a, b = self.tmp / "a.png", self.tmp / "b.png"
        for p in (a, b):
            r = self.cli("still", self.spec, "--frame", "2", "--out", p)
            self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        self.assertEqual(a.read_bytes(), b.read_bytes(), "same frame, same bytes")
        c = self.tmp / "c.png"
        r = self.cli("still", self.spec, "--frame", "2", "--out", c, "--engine", "cycles", "--look", "clay")
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        info = json.loads((self.tmp / "c.render.json").read_text(encoding="utf-8"))
        self.assertEqual(info["engine"], "CYCLES")
        self.assertTrue(info["device"])

    def test_keyframes_other_size(self):
        out = self.tmp / "kf"
        r = self.cli("keyframes", self.spec, "--out", out, "--size", "96x54")
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        self.assertEqual(png_info(out / "first.png")[:2], (96, 54))
        self.assertEqual(png_info(out / "last.png")[:2], (96, 54))
        kf = json.loads((out / "keyframes.json").read_text(encoding="utf-8"))
        self.assertEqual(kf["frames"], [1, 3])
        self.assertNotEqual((out / "first.png").read_bytes(), (out / "last.png").read_bytes(), "the camera moved")

    def test_turntable_and_lookbook(self):
        out = self.tmp / "tt"
        r = self.cli("turntable", "preset:rocks", "--out", out, "--seconds", "0.25", "--size", "64x36", "--preview")
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        self.assertEqual(len(list((out / "beauty").glob("*.png"))), 3)
        lb = self.tmp / "lb"
        r = self.cli("lookbook", "--out", lb, "--spec", self.spec, "--size", "64x36")
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        book = json.loads((lb / "lookbook.json").read_text(encoding="utf-8"))
        for look in ("grey-layout", "clay", "toon-ink", "ink-wash"):
            self.assertEqual(png_info(lb / f"{look}.png")[:2], (64, 36))
            self.assertIn(look, book["looks"])


if __name__ == "__main__":
    unittest.main()
