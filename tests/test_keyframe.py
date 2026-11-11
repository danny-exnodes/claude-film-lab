"""tools/compose/keyframe.py: the free --check guard run before a paid Seedance call, and the warnings printed when
a start frame is generated. The geometry tests live in tests/test_compose.py. Free: no API."""
import subprocess, sys, unittest

from PIL import Image

from helpers import REPO, TmpDirCase

KEYFRAME = REPO / "tools" / "compose" / "keyframe.py"
GREEN = (0, 255, 0)
RED = (200, 30, 30)


def run(*args):
    return subprocess.run([sys.executable, str(KEYFRAME), *map(str, args)], capture_output=True, text=True)


class KeyframeCase(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.plate = self.tmp / "plate.png"
        Image.new("RGBA", (200, 400), RED + (255,)).save(self.plate)
        self.start = self.tmp / "clips" / "start.png"

    def make(self, *args):
        r = run(self.plate, self.start, *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def files(self):
        return sorted(str(p.relative_to(self.tmp)) for p in self.tmp.rglob("*") if p.is_file())


class TestCheck(KeyframeCase):
    def test_passes_on_a_frame_keyframe_just_wrote(self):
        self.make("--x", 960, "--y", 540, "--h", 400)
        before, stamp = self.files(), self.start.stat().st_mtime_ns
        r = run("--check", self.start, "--key", "#00FF00")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("figure bbox 860,340-1060,740", r.stdout)
        self.assertNotIn("WARN", r.stdout + r.stderr)
        self.assertEqual((self.files(), self.start.stat().st_mtime_ns), (before, stamp))   # --check never writes

    def test_default_key_is_green_and_magenta_works(self):
        self.make("--x", 960, "--y", 540, "--h", 400)
        self.assertEqual(run("--check", self.start).returncode, 0)
        self.make("--x", 960, "--y", 540, "--h", 400, "--key", "#FF00FF")
        self.assertEqual(run("--check", self.start, "--key", "#FF00FF").returncode, 0)
        r = run("--check", self.start, "--key", "#00FF00")                 # the wrong key for this frame
        self.assertEqual(r.returncode, 1)
        self.assertIn("border is not the key colour", r.stderr)

    def test_fails_on_a_square_image(self):
        sq = self.tmp / "square.png"
        Image.new("RGB", (1024, 1024), GREEN).save(sq)
        before = self.files()
        r = run("--check", sq, "--key", "#00FF00")
        self.assertEqual(r.returncode, 1)
        self.assertIn("1024x1024", r.stderr)
        self.assertIn("1920x1080", r.stderr)
        self.assertEqual(self.files(), before)

    def test_fails_on_a_non_key_border(self):
        im = Image.new("RGB", (1920, 1080), (255, 255, 255))               # an L4 plate on white paper
        im.paste(RED, (860, 340, 1060, 740))
        p = self.tmp / "white.png"
        im.save(p)
        r = run("--check", p, "--key", "#00FF00")
        self.assertEqual(r.returncode, 1)
        self.assertIn("border is not the key colour", r.stderr)

    def test_fails_on_an_rgba_file(self):
        p = self.tmp / "rgba.png"
        Image.new("RGBA", (1920, 1080), GREEN + (255,)).save(p)
        r = run("--check", p, "--key", "#00FF00")
        self.assertEqual(r.returncode, 1)
        self.assertIn("alpha", r.stderr)

    def test_figure_cut_over_more_than_2_percent_of_the_ring_fails(self):
        self.make("--x", 0, "--y", 540, "--h", 400)                        # 400 px of the left edge are plate
        r = run("--check", self.start, "--key", "#00FF00")
        self.assertEqual(r.returncode, 1)
        self.assertIn("border is not the key colour", r.stderr)

    def test_figure_touching_the_edge_a_little_warns_and_passes(self):
        im = Image.new("RGB", (1920, 1080), GREEN)
        im.paste(RED, (900, 1000, 960, 1080))                              # 60 px of the bottom edge: 1 % of the ring
        p = self.tmp / "touch.png"
        im.save(p)
        r = run("--check", p, "--key", "#00FF00")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("figure bbox 900,1000-960,1080", r.stdout)
        self.assertIn("WARN", r.stdout)
        self.assertIn("edge", r.stdout)

    def test_fails_on_a_frame_with_no_figure(self):
        blank = self.tmp / "blank.png"
        Image.new("RGB", (1920, 1080), GREEN).save(blank)
        r = run("--check", blank)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no figure", r.stderr)

    def test_missing_file_and_usage(self):
        r = run("--check", self.tmp / "nope.png")
        self.assertEqual(r.returncode, 1)
        self.assertIn("nope.png", r.stderr)
        self.assertEqual(run().returncode, 2)                              # PLATE and OUT are required without --check
        self.assertEqual(run(self.plate).returncode, 2)
        self.assertEqual(run(self.plate, self.start, "--check", self.plate).returncode, 2)
        self.assertEqual(self.files(), ["plate.png"])


class TestGenerateWarnings(KeyframeCase):
    def test_out_must_not_be_the_plate(self):
        before = self.plate.read_bytes()
        r = run(self.plate, self.tmp / "sub" / ".." / "plate.png")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.plate.read_bytes(), before)

    def test_clean_frame_has_no_warning(self):
        r = self.make("--x", 960, "--y", 540, "--h", 400)
        self.assertEqual(r.stderr, "")
        self.assertRegex(r.stdout, r"start\.png: 1920x1080, plate at scale 1\.0000, key #00FF00")

    def test_figure_cut_by_the_frame_edge(self):
        r = self.make("--x", 0, "--y", 540, "--h", 400)
        self.assertIn("WARN", r.stderr)
        self.assertIn("cut by the frame edge", r.stderr)
        self.assertTrue(self.start.is_file())

    def test_transparent_margin_past_the_edge_is_not_a_cut(self):
        plate = Image.new("RGBA", (200, 400), (0, 0, 0, 0))
        plate.paste(RED + (255,), (100, 0, 200, 400))                      # the figure is the right half only
        plate.save(self.plate)
        r = self.make("--x", 50, "--y", 540, "--h", 400)                   # plate box starts at x=-50, figure at 50
        self.assertNotIn("cut by the frame edge", r.stderr)

    def test_key_near_subject(self):
        Image.new("RGBA", (200, 400), (20, 230, 30, 255)).save(self.plate)  # a green creature on a green key
        r = self.make("--x", 960, "--y", 540, "--h", 400)
        self.assertIn("WARN KEY NEAR SUBJECT: pick the other key colour", r.stderr)
        r = self.make("--x", 960, "--y", 540, "--h", 400, "--key", "#FF00FF")
        self.assertNotIn("KEY NEAR SUBJECT", r.stderr)

    def test_transparent_key_coloured_pixels_do_not_count(self):
        plate = Image.new("RGBA", (200, 400), GREEN + (0,))                # matte leftovers: key colour at alpha 0
        plate.paste(RED + (255,), (50, 50, 150, 350))
        plate.save(self.plate)
        r = self.make("--x", 960, "--y", 540, "--h", 400)
        self.assertNotIn("KEY NEAR SUBJECT", r.stderr)


if __name__ == "__main__":
    unittest.main()
