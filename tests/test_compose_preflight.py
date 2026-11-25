"""`inline.py <film.html> --preflight` (tools/compose/preflight.cjs + preflight.js): a dry run of a plates film under
node before any render. Free: no browser, no API. Skipped when node is not installed."""
import json, re, shutil, subprocess, sys, unittest
from pathlib import Path

from PIL import Image

from helpers import FIX, REPO, TmpDirCase, load

INLINE = REPO / "tools" / "compose" / "inline.py"
NODE = shutil.which("node")
DEMO = load("compose/demo_plates.py", "film_demo_plates_pf")
SIZES = {"ep00_s01_L1_demo-nui_v01.png": ((2400, 1350), "RGB"), "ep00_s01_L2_demo-day_v01.png": ((2400, 1350), "RGBA"),
         "ep00_s01_L3_demo-da_v01.png": ((2400, 1350), "RGBA"), "ep00_s01_L4_demo-thu_v01.png": ((2048, 2048), "RGBA")}


def run(*args):
    return subprocess.run([sys.executable, str(INLINE), *map(str, args)], capture_output=True, text=True)


@unittest.skipUnless(NODE, "node is not installed (the preflight runs the film's code under node)")
class TestPreflight(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.ep = self.tmp / "out" / "p" / "ep00"
        self.dir = self.ep / "film" / "demo"
        self.dir.mkdir(parents=True)
        (self.ep / "plates").mkdir()
        for name, (size, mode) in SIZES.items():          # the demo plates' sizes: only the PNG header is read
            Image.new(mode, size).save(self.ep / "plates" / name)
        self.anchors = self.tmp / "anchors.json"
        self.anchors.write_text(json.dumps(DEMO.ANCHORS), encoding="utf-8")
        self.film = self.dir / "film.html"
        shutil.copy(FIX / "cinecode" / "film.html", self.film)
        shutil.copy(FIX / "cinecode" / "quick-STATE.md", self.dir / "STATE.md")
        r = run(self.film, "--init", "--anchors", self.anchors)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.html = self.film.read_text(encoding="utf-8")

    def edit(self, *pairs):
        html = self.html
        for old, new in pairs:
            self.assertIn(old, html)
            html = html.replace(old, new, 1)
        self.film.write_text(html, encoding="utf-8")

    def preflight(self, code=None):
        before = self.film.read_bytes()
        r = run(self.film, "--preflight")
        self.assertEqual(self.film.read_bytes(), before, "the preflight writes nothing")
        self.assertNotIn("Traceback", r.stderr)
        self.assertRegex(r.stdout, r"(?m)^preflight: \d+ error\(s\), \d+ warning\(s\);")
        if code is not None:
            self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return r.stdout

    def test_the_template_shot_on_the_demo_plates_is_clean(self):
        out = self.preflight(0)
        self.assertIn("preflight: 0 error(s), 0 warning(s); 4 plate(s), 1 shot(s), 96 frame(s) drawn at 12 fps", out)

    def test_unknown_keys_in_plates_are_errors_and_in_call_options_warnings(self):
        self.edit(("depth: 0.12, overscan: 1.02 }", "depth: 0.12, overscan: 1.02, overscam: 1.1 }"),
                  ("rig: { warp: { tail: { amp: 34,", "rig: { warp: { tail: { amp: 34, wave: 2,"),
                  ("speed: -12, alpha: 0.55, variant: 0 }", "speed: -12, alpha: 0.55, variant: 0, spd: 3 }"),
                  ("st.plate('L4', { eyes: { eye: { blinks", "st.plate('L4', { eye: 1, eyes: { eye: { blinks"))
        out = self.preflight(1)
        self.assertRegex(out, r'(?m)^ERROR plate L1: unknown key "overscam"')
        self.assertRegex(out, r'(?m)^ERROR plate L4 rig\.warp\.tail: unknown key "wave"')
        self.assertRegex(out, r'(?m)^WARN COMPOSE\.mist\.band: unknown key "spd"')
        self.assertRegex(out, r"(?m)^WARN st\.plate\('L4'\): unknown key \"eye\"")

    def test_missing_anchors_are_listed_before_the_load_fails(self):
        self.edit(("rig: { warp: { tail: {", "rig: { warp: { tale: {"),
                  ("eyes: { eye: {", "eyes: { eye_back: {"))
        out = self.preflight(1)
        self.assertRegex(out, r'(?m)^ERROR plate L4: rig\.warp\.tale needs anchor box "tale"')
        self.assertRegex(out, r'(?m)^ERROR plate L4: rig\.eyes\.eye_back needs anchor box "eye_back"')
        self.assertRegex(out, r"(?m)^ERROR load: ")
        self.assertIn("0 frame(s) drawn", out)

    def test_a_jpeg_plate_with_a_large_icc_block_is_measured(self):
        """The start-of-frame of a JPEG may lie past 64 KB (EXIF / ICC): the size is still read, not assumed."""
        Image.new("RGB", (2400, 1350)).save(self.ep / "plates" / "ep00_s01_L1_demo-nui_v01.png", "JPEG",
                                            icc_profile=bytes(200_000))
        out = self.preflight(0)
        self.assertNotIn("assumed", out)
        self.assertIn("preflight: 0 error(s), 0 warning(s)", out)

    def test_fps_before_the_film_path(self):
        r = subprocess.run([NODE, str(REPO / "tools" / "compose" / "preflight.cjs"), "--fps", "6", str(self.film)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("frame(s) drawn at 6 fps", r.stdout)

    def test_an_l1_too_small_for_the_camera_travel_names_the_overscan_it_needs(self):
        self.edit(("depth: 0.12, overscan: 1.02 }", "depth: 0.12 }"),
                  ("zoom: [1.0, 1.1],", "zoom: [1.0, 1.0], pan: [[-400, 0], [400, 0]],"))
        out = self.preflight(1)
        m = re.search(r"(?m)^ERROR plate L1 shows its edge under the camera move \(up to \+([\d.]+) % extra zoom, first at [\d.]+ s\): overscan >= ([\d.]+)", out)
        self.assertTrue(m, out)
        self.assertGreater(float(m[1]), 1)
        self.assertGreaterEqual(float(m[2]), 1 + float(m[1]) / 100)

    def test_a_figure_over_a_quarter_of_the_frame(self):
        self.edit(("    st.plate('L3');\n", "    st.plate('L3');\n    COMPOSE.figure.draw(st, { x: 700, y: 950, height: 400, salt: 1 });\n"
                   "    COMPOSE.figure.draw(st, { x: 1200, y: 950, height: 260, salt: 2 });\n"))
        out = self.preflight(1)
        self.assertRegex(out, r"(?m)^ERROR kit: figure 1: height 400 px is over the cap of 270 px")
        self.assertRegex(out, r"(?m)^WARN figure 2 is \d+ % of the frame height on screen .*camera zoom 1\.\d+")
        self.assertRegex(out, r"(?m)^WARN COMPOSE\.figure\.draw: height 400 is outside the documented 40\.\.270")

    def test_seq_frames_and_plate_files_that_are_not_there(self):
        clips = self.ep / "clips" / "k"
        clips.mkdir(parents=True)
        for i in (1, 2, 4):
            Image.new("RGBA", (1280, 720)).save(clips / f"{i:06d}.png")
        self.edit(("  // L4b: { seq:", "  L4b: { seq: { pattern: '../../clips/k/{n}.png', count: 5, at: 1 }, depth: 1.0 },\n"
                   "  L5: { src: '../../plates/ep00_s01_L5_khong-co_v01.png', depth: 1.0, cover: false },\n  // L4b: { seq:"))
        out = self.preflight(1)
        self.assertRegex(out, r"(?m)^ERROR plate L4b seq: 2 of 5 frames missing \(first \.\./\.\./clips/k/000003\.png, last \.\./\.\./clips/k/000005\.png\)")
        self.assertRegex(out, r"(?m)^ERROR plate L5: file \.\./\.\./plates/ep00_s01_L5_khong-co_v01\.png not found")

    def test_out_of_range_numbers_warn_and_a_shot_that_throws_is_an_error(self):
        self.edit(("    st.plate('L3');\n", "    st.plate('L3');\n    COMPOSE.smoke.plume(st, { x: 900, y: 800, rate: 20 });\n"
                   "    if (t > 5) COMPOSE.anchor('L4', 'nose');\n"))
        out = self.preflight(1)
        self.assertRegex(out, r"(?m)^WARN COMPOSE\.smoke\.plume: rate 20 is outside the documented 2\.\.8")
        self.assertRegex(out, r'(?m)^ERROR shot s01 throws at 5\.08 s: plate L4: no anchor point "nose"')
        self.assertEqual(len(re.findall(r"(?m)^ERROR shot s01 throws", out)), 1, "one line per message, not per frame")

    def test_warnings_alone_exit_0(self):
        self.edit(("speed: -12, alpha: 0.55, variant: 0 }", "speed: -12, alpha: 0.55, variant: 0, spd: 3 }"))
        out = self.preflight(0)
        self.assertIn("0 error(s), 1 warning(s)", out)

    def test_an_old_kit_in_the_film_is_a_warning_and_a_film_without_the_kit_cannot_be_checked(self):
        self.edit(("<!-- compose-kit begin v", "<!-- compose-kit begin v0.9.0-old+"))
        self.assertRegex(self.preflight(0), r"(?m)^WARN film\.html carries kit v0\.9\.0-old\+\S*, the repo has v")
        self.film.write_text((FIX / "cinecode" / "film.html").read_text(encoding="utf-8"), encoding="utf-8")
        r = run(self.film, "--preflight")
        self.assertEqual(r.returncode, 2)
        self.assertIn("no compose-kit block", r.stdout)

    def test_preflight_runs_alone(self):
        r = run(self.film, "--preflight", "--init")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--preflight runs alone", r.stderr)


if __name__ == "__main__":
    unittest.main()
