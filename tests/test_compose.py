"""tools/compose: inline.py on the pinned cinecode Quick template, keyframe.py geometry. Free: no browser, no API."""
import json, re, shutil, subprocess, sys, unittest
from pathlib import Path

from PIL import Image

from helpers import FIX, REPO, TmpDirCase

INLINE = REPO / "tools" / "compose" / "inline.py"
KEYFRAME = REPO / "tools" / "compose" / "keyframe.py"
CINECODE_FIX = FIX / "cinecode"
PIN = (REPO / "tools" / "compose" / "cinecode.ref").read_text().strip()
INSTALLED = Path("/root/.claude/skills/cinecode")


def run(script, *args):
    return subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True)


class FilmCase(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.film = self.tmp / "film.html"
        shutil.copy(CINECODE_FIX / "film.html", self.film)
        shutil.copy(CINECODE_FIX / "quick-STATE.md", self.tmp / "STATE.md")

    def html(self):
        return self.film.read_text(encoding="utf-8")


class TestInlineInit(FilmCase):
    def test_init_on_pinned_template(self):
        r = run(INLINE, self.film, "--init")
        self.assertEqual(r.returncode, 0, r.stderr)
        html = self.html()
        self.assertEqual(html.count("<!-- compose-kit begin"), 1)
        self.assertEqual(html.count("<!-- compose-kit end -->"), 1)
        self.assertLess(html.find("<!-- compose-kit begin"), html.find("// ============================== FILM"))
        self.assertIn("const W = +q.get('w') || 1920, H = +q.get('h') || 1080", html)
        self.assertRegex(html, r"(?m)^window\.READY = loadType\(TYPE\)\.then\(loadFormulas\)\.then\(loadPlates\)")
        self.assertRegex(html, r"(?m)^async function loadPlates\b")
        self.assertIn("LOOKS.plates = {", html)
        self.assertIn("get('look') || 'plates';", html)
        self.assertNotIn("function fieldGathers", html)          # cinecode's example scenes are gone
        self.assertIn("// ============================== HELPERS (picture)", html)
        for note in ("FILM section", "look: 'plates'", "default size 1080x1920 -> 1920x1080", "loadPlates) chained"):
            self.assertIn(note, r.stdout)
        self.assertNotIn("WARNING", r.stdout)

    def test_init_fills_state_format_line(self):
        run(INLINE, self.film, "--init")
        state = (self.tmp / "STATE.md").read_text(encoding="utf-8")
        self.assertNotIn("<length, aspect, size, fps>", state)
        self.assertRegex(state, r"\*\*Format:\*\* [\d.?]+ s, 16:9, 1920x1080, 24 fps")

    def test_refresh_is_idempotent(self):
        self.assertEqual(run(INLINE, self.film, "--init").returncode, 0)
        once = self.html()
        r = run(INLINE, self.film)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.html(), once)
        self.assertEqual(run(INLINE, self.film).returncode, 0)
        self.assertEqual(self.html(), once)

    def test_second_init_refused_and_file_untouched(self):
        run(INLINE, self.film, "--init")
        once = self.html()
        r = run(INLINE, self.film, "--init")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("fresh film.html", r.stderr)
        self.assertEqual(self.html(), once)

    def test_anchors_embedded_and_kept_on_refresh(self):
        anchors = self.tmp / "anchors.json"
        anchors.write_text(json.dumps({"plates": {"a.png": {"eye": [10, 20]}}}), encoding="utf-8")
        self.assertEqual(run(INLINE, self.film, "--init", "--anchors", anchors).returncode, 0)
        self.assertIn('COMPOSE.ANCHORS = {"plates":{"a.png":{"eye":[10,20]}}};', self.html())
        self.assertEqual(run(INLINE, self.film).returncode, 0)   # no --anchors: the embedded ones stay
        self.assertEqual(self.html().count("COMPOSE.ANCHORS = {"), 1)

    def test_custom_size(self):
        self.assertEqual(run(INLINE, self.film, "--init", "--size", "960x540").returncode, 0)
        self.assertIn("|| 960, H = +q.get('h') || 540", self.html())

    def test_changed_template_fails_loudly(self):
        """What a cinecode template change looks like: the markers are gone -> FAILED, nothing written."""
        broken = self.html().replace("// Cues are shared by picture and sound", "// Cues, renamed upstream")
        self.film.write_text(broken, encoding="utf-8")
        r = run(INLINE, self.film, "--init")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("markers not found", r.stderr)
        self.assertEqual(self.html(), broken)


class TestInlineDeterminism(FilmCase):
    def setUp(self):
        super().setUp()
        self.assertEqual(run(INLINE, self.film, "--init").returncode, 0)
        self.good = self.html()

    def inject(self, line):
        marker = "// ============================== HELPERS (picture)"
        self.film.write_text(self.good.replace(marker, line + "\n" + marker), encoding="utf-8")
        return run(INLINE, self.film)

    def test_refuses_unseeded_time_and_randomness(self):
        for line in ("const jitter = Math.random() * 4;", "const now = new Date();", "const t0 = performance.now();"):
            with self.subTest(line=line):
                r = self.inject(line)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("unseeded time or randomness", r.stderr)
                self.assertIn(line, r.stderr)

    def test_comments_do_not_trip_the_lint(self):
        r = self.inject("// never use Math.random or Date here")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_kit_lint(self):
        r = run(INLINE, "--lint")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"compose kit v\S+: 9 files, lint ok")


class TestKeyframe(TmpDirCase, unittest.TestCase):
    KEY = (0, 255, 0)
    RED = (200, 30, 30)

    def setUp(self):
        super().setUp()
        self.plate = self.tmp / "ep01_s03_L4_thu_v01.png"
        Image.new("RGBA", (200, 400), self.RED + (255,)).save(self.plate)
        self.out = self.tmp / "clips" / "start.png"

    def frame(self, *args):
        r = run(KEYFRAME, self.plate, self.out, *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        im = Image.open(self.out)
        self.assertEqual((im.size, im.mode), ((1920, 1080), "RGB"))
        return im

    def box(self, im):
        """Bounding box of the non-key pixels (the plate is opaque, so its edges are exact)."""
        mask = Image.eval(im.getchannel("G"), lambda g: 255 if g < 128 else 0)
        return mask.getbbox()

    def test_center_pivot(self):
        im = self.frame("--x", 960, "--y", 540, "--h", 400)
        self.assertEqual(self.box(im), (860, 340, 1060, 740))
        self.assertEqual(im.getpixel((5, 5)), self.KEY)
        self.assertEqual(im.getpixel((960, 540)), self.RED)

    def test_bottom_pivot_scales_to_height(self):
        im = self.frame("--x", 500, "--y", 900, "--h", 600, "--pivot", "bottom")
        self.assertEqual(self.box(im), (350, 300, 650, 900))     # 200x400 at 1.5x, feet on y=900

    def test_top_pivot_and_default_height(self):
        im = self.frame("--x", 300, "--y", 100, "--pivot", "top")
        self.assertEqual(self.box(im), (200, 100, 400, 500))

    def test_anchor_pivot_in_plate_pixels(self):
        anchors = self.tmp / "anchors.json"
        anchors.write_text(json.dumps({"plates": {self.plate.name: {"feet": [50, 380]}}}), encoding="utf-8")
        im = self.frame("--x", 1000, "--y", 800, "--h", 200, "--pivot", "feet", "--anchors", anchors)
        # scale 0.5: the anchor (50,380) lands on (1000,800) -> left = 1000-25, top = 800-190
        self.assertEqual(self.box(im), (975, 610, 1075, 810))

    def test_anchor_pivot_scaled_from_recorded_size(self):
        anchors = self.tmp / "anchors.json"                   # points measured on a 2x larger original
        anchors.write_text(json.dumps({self.plate.name: {"points": {"feet": [100, 760]}, "size": [400, 800]}}),
                           encoding="utf-8")
        im = self.frame("--x", 1000, "--y", 800, "--h", 200, "--pivot", "feet", "--anchors", anchors)
        self.assertEqual(self.box(im), (975, 610, 1075, 810))

    def test_custom_key_and_plate_past_the_edge(self):
        im = self.frame("--x", 0, "--y", 540, "--h", 400, "--key", "#FF00FF")
        self.assertEqual(im.getpixel((1900, 10)), (255, 0, 255))
        self.assertEqual(im.getpixel((50, 540)), self.RED)       # right half of the plate is inside the frame

    def test_transparent_plate_pixels_show_the_key(self):
        plate = Image.new("RGBA", (200, 400), (0, 0, 0, 0))
        plate.paste(self.RED + (255,), (0, 200, 200, 400))
        plate.save(self.plate)
        im = self.frame("--x", 960, "--y", 540, "--h", 400)
        self.assertEqual(im.getpixel((960, 400)), self.KEY)
        self.assertEqual(im.getpixel((960, 700)), self.RED)

    def test_anchor_errors(self):
        r = run(KEYFRAME, self.plate, self.out, "--pivot", "feet")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("pass --anchors", r.stderr)
        anchors = self.tmp / "anchors.json"
        anchors.write_text("{}", encoding="utf-8")
        r = run(KEYFRAME, self.plate, self.out, "--pivot", "feet", "--anchors", anchors)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no point 'feet'", r.stderr)


class TestCinecodePin(unittest.TestCase):
    def test_pin_is_a_full_commit_id(self):
        self.assertRegex(PIN, r"^[0-9a-f]{40}$")

    def test_setup_script_pins_the_same_commit(self):
        sh = (REPO / "docs" / "setup-script.sh").read_text(encoding="utf-8")
        m = re.search(r'^CINECODE_REF="\$\{CINECODE_REF:-([0-9a-f]{40})\}"', sh, re.M)
        self.assertTrue(m, "docs/setup-script.sh must set CINECODE_REF")
        self.assertEqual(m[1], PIN)
        self.assertNotIn("pull -q --ff-only", sh)                # never follow upstream HEAD

    def test_fixture_readme_names_the_pin_file(self):
        self.assertIn("tools/compose/cinecode.ref", (CINECODE_FIX / "README.md").read_text(encoding="utf-8"))

    @unittest.skipUnless((INSTALLED / ".git").exists(), "cinecode is not installed here")
    def test_installed_template_matches_fixture_when_on_the_pin(self):
        head = subprocess.run(["git", "-C", str(INSTALLED), "rev-parse", "HEAD"], capture_output=True, text=True)
        if head.stdout.strip() != PIN:
            self.skipTest(f"installed cinecode is {head.stdout.strip()[:7]}, pin is {PIN[:7]} (doctor warns)")
        self.assertEqual((INSTALLED / "templates/quick/film.html").read_bytes(),
                         (CINECODE_FIX / "film.html").read_bytes())


if __name__ == "__main__":
    unittest.main()
