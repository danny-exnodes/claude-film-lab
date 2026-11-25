"""The TOON kit (method: code): node suites (tests/js/toon.test.cjs, tests/js/creature.test.cjs), the three.js pin
(tools/toon/three.lock) and real renders in headless Chromium through tools/toon/toon.py (every code style pack once,
small; the creatures in the ink look; the same frame twice must be the same bytes).
Free: no API. Skipped when node, Playwright or the pinned three.js are missing (tools/doctor.sh reports why)."""
import hashlib, os, re, shutil, subprocess, sys, tempfile, unittest
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

    def test_creature_suite(self):
        r = subprocess.run([NODE, "--test", str(REPO / "tests" / "js" / "creature.test.cjs")], capture_output=True, text=True,
                           timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout[-6000:] + r.stderr[-2000:])


class TestThreeLock(unittest.TestCase):
    """tools/toon/three.lock pins the three.js files the TOON page loads; .gitignore's *.lock once hid it from git."""
    LOCK = REPO / "tools" / "toon" / "three.lock"

    def test_lock_parses_and_covers_the_loaded_files(self):
        lines = [l.split() for l in self.LOCK.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
        version = [l[1] for l in lines if l[0] == "version"]
        self.assertEqual(len(version), 1)
        self.assertRegex(version[0], r"^\d+\.\d+\.\d+$")
        sha = {l[1]: l[2] for l in lines if l[0] == "sha256"}
        for h in sha.values():
            self.assertRegex(h, r"^[0-9a-f]{64}$")
        # toon.js loads build/three.module.js, which imports build/three.core.js
        src = (REPO / "tools" / "toon" / "toon.js").read_text(encoding="utf-8")
        url = re.search(r"T\.THREE_URL = T\.THREE_URL \|\| '([^']+)'", src)
        self.assertTrue(url and url.group(1).endswith("/build/three.module.js"))
        self.assertEqual(set(sha), {"build/three.module.js", "build/three.core.js"})
        setup = (REPO / "docs" / "setup-script.sh").read_text(encoding="utf-8")
        self.assertIn(f'THREE_VER="${{THREE_VER:-{version[0]}}}"', setup)

    @unittest.skipUnless(shutil.which("git"), "git is not installed")
    def test_lock_is_not_ignored(self):
        r = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", str(self.LOCK)], capture_output=True)
        if r.returncode == 128:
            self.skipTest("not a git checkout")
        self.assertEqual(r.returncode, 1, "tools/toon/three.lock is ignored by .gitignore: it would never be committed")


@unittest.skipUnless(playwright_ok(), "node + Playwright are needed for the browser renders")
class TestToonRender(unittest.TestCase):
    STYLES = ["hoat-hinh-phang", "bong-muc", "ong-cao-su", "ban-ve-ky-thuat", "in-riso", "pixel-16bit", "chu-ascii",
              "dat-nan-3d", "low-poly-90", "bia-cat-dan", "sach-pop-up", "thuy-mac-3d"]

    def still(self, style, out, t="2.6"):
        r = subprocess.run([sys.executable, str(REPO / "tools" / "toon" / "toon.py"), "still", style, "--t", t,
                            "--size", "480x270", "--out", str(out)], capture_output=True, text=True, timeout=600)
        return r

    def test_every_style_renders(self):
        with tempfile.TemporaryDirectory() as d:
            for s in self.STYLES:
                if s in ("dat-nan-3d", "low-poly-90", "bia-cat-dan", "sach-pop-up", "thuy-mac-3d") and not THREE.is_file():
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

    def toon(self, *args):
        return subprocess.run([sys.executable, str(REPO / "tools" / "toon" / "toon.py"), *args], capture_output=True,
                              text=True, timeout=600)

    @unittest.skipUnless(THREE.is_file(), "the pinned three.js is not installed")
    def test_creatures_render_in_the_ink_look(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            for c in ("mac-loc", "van-dieu", "luc-tuc-ngu"):
                with self.subTest(creature=c):
                    a, b = Path(d) / f"{c}-a.png", Path(d) / f"{c}-b.png"
                    for p in (a, b):
                        r = self.toon("still", "thuy-mac-3d", "--creature", c, "--t", "2.2", "--size", "480x270", "--out", str(p))
                        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                        self.assertNotIn("WARN", r.stdout)
                    self.assertEqual(a.read_bytes(), b.read_bytes(), "same frame, same bytes")
                    self.assertLess(Image.open(a).convert("L").getextrema()[0], 90, f"{c}: no ink in the frame")
            out = Path(d) / "tt.png"
            r = self.toon("turntable", "--creature", "mac-loc", "--size", "320x240", "--out", str(out))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)



class TestToonCli(unittest.TestCase):
    """toon.py argument checks that refuse before any render (no browser needed)."""

    def toon(self, *args):
        return subprocess.run([sys.executable, str(REPO / "tools" / "toon" / "toon.py"), *args], capture_output=True,
                              text=True, timeout=120)

    def test_creature_needs_a_look_that_draws_it(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.toon("still", "hoat-hinh-phang", "--creature", "mac-loc", "--out", str(Path(d) / "x.png"))
            self.assertEqual(r.returncode, 2)
            self.assertIn("does not draw creatures", r.stderr)
            r = self.toon("still", "thuy-mac-3d", "--creature", "no-such-beast", "--out", str(Path(d) / "y.png"))
            self.assertEqual(r.returncode, 2)
            self.assertIn("mac-loc", r.stderr)

    def test_refuses_existing_output_and_unknown_style(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "x.png"
            out.write_bytes(b"keep")
            r = self.toon("still", "hoat-hinh-phang", "--out", str(out))
            self.assertEqual(r.returncode, 2)
            self.assertEqual(out.read_bytes(), b"keep")
            r = self.toon("still", "no-such-style", "--out", str(Path(d) / "y.png"))
            self.assertEqual(r.returncode, 2)
            r = self.toon("still", "thuy-mac", "--out", str(Path(d) / "z.png"))   # an image style is not drawn by TOON
            self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
