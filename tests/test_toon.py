"""The TOON kit (method: code): node suite (tests/js/toon.test.cjs) and real renders in headless Chromium through
tools/toon/toon.py (every one of the ten style packs once, small; the same frame twice must be the same bytes).
Free: no API. Skipped when node, Playwright or the pinned three.js are missing (tools/doctor.sh reports why)."""
import hashlib, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
THREE = Path(os.environ.get("FILM_THREE", "/opt/film-lab/vendor/three/build/three.module.js"))


def playwright_ok():
    if not NODE:
        return False
    r = subprocess.run([NODE, "-e", "require('playwright')"], capture_output=True)
    return r.returncode == 0


@unittest.skipUnless(NODE, "node is not installed")
class TestToonNode(unittest.TestCase):
    def test_node_suite(self):
        r = subprocess.run([NODE, "--test", str(REPO / "tests" / "js" / "toon.test.cjs")], capture_output=True, text=True,
                           timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout[-6000:] + r.stderr[-2000:])


@unittest.skipUnless(playwright_ok(), "node + Playwright are needed for the browser renders")
class TestToonRender(unittest.TestCase):
    STYLES = ["hoat-hinh-phang", "bong-muc", "ong-cao-su", "ban-ve-ky-thuat", "in-riso", "pixel-16bit", "chu-ascii",
              "dat-nan-3d", "low-poly-90", "bia-cat-dan", "sach-pop-up"]

    def still(self, style, out, t="2.6"):
        r = subprocess.run([sys.executable, str(REPO / "tools" / "toon" / "toon.py"), "still", style, "--t", t,
                            "--size", "480x270", "--out", str(out)], capture_output=True, text=True, timeout=600)
        return r

    def test_every_style_renders(self):
        with tempfile.TemporaryDirectory() as d:
            for s in self.STYLES:
                if s in ("dat-nan-3d", "low-poly-90", "bia-cat-dan", "sach-pop-up") and not THREE.is_file():
                    continue
                with self.subTest(style=s):
                    out = Path(d) / f"{s}.png"
                    r = self.still(s, out)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                    self.assertNotIn("WARN", r.stdout)
                    from PIL import Image
                    im = Image.open(out).convert("RGB")
                    self.assertEqual(im.size, (480, 270))
                    colours = len(im.resize((96, 54)).getcolors(maxcolors=100000) or [])
                    self.assertGreater(colours, 8, f"{s}: frame looks blank ({colours} colours)")

    def test_same_frame_same_bytes(self):
        styles = ["ong-cao-su"] + (["low-poly-90", "sach-pop-up"] if THREE.is_file() else [])
        with tempfile.TemporaryDirectory() as d:
            for s in styles:
                with self.subTest(style=s):
                    a, b = Path(d) / f"{s}-a.png", Path(d) / f"{s}-b.png"
                    for p in (a, b):
                        r = self.still(s, p, "1.3")
                        self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertEqual(hashlib.sha256(a.read_bytes()).hexdigest(), hashlib.sha256(b.read_bytes()).hexdigest())

    def test_refuses_existing_output_and_unknown_style(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "x.png"
            out.write_bytes(b"keep")
            r = self.still("hoat-hinh-phang", out)
            self.assertEqual(r.returncode, 2)
            self.assertEqual(out.read_bytes(), b"keep")
            r = self.still("no-such-style", Path(d) / "y.png")
            self.assertEqual(r.returncode, 2)
            r = self.still("thuy-mac", Path(d) / "z.png")          # an image style is not drawn by TOON
            self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
