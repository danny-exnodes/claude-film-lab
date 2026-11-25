"""tools/compose/inline.py write path (atomic, line endings, aspect label, size warning, anchors path from any working
directory) and demo_plates.py --help. Free: no browser, no API."""
import json, os, re, shutil, subprocess, sys, unittest
from pathlib import Path

from helpers import FIX, REPO, TmpDirCase, load

INLINE = REPO / "tools" / "compose" / "inline.py"
DEMO = REPO / "tools" / "compose" / "demo_plates.py"
CINECODE_FIX = FIX / "cinecode"


def run(script, *args, cwd=None):
    return subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True, cwd=cwd)


class FilmCase(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.dir = self.tmp / "out" / "p" / "ep01" / "film" / "demo"
        self.dir.mkdir(parents=True)
        self.film = self.dir / "film.html"
        shutil.copy(CINECODE_FIX / "film.html", self.film)
        shutil.copy(CINECODE_FIX / "quick-STATE.md", self.dir / "STATE.md")

    def html(self):
        return self.film.read_text(encoding="utf-8")


class TestLineEndingsAndAtomicWrite(FilmCase):
    def test_a_crlf_film_and_state_stay_crlf(self):
        for f in (self.film, self.dir / "STATE.md"):
            f.write_bytes(f.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        r = run(INLINE, self.film, "--init")
        self.assertEqual(r.returncode, 0, r.stderr)
        for f in (self.film, self.dir / "STATE.md"):
            raw = f.read_bytes()
            self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), f"{f.name}: every line ends in CRLF")
            self.assertNotIn(b"\r\r", raw)
        self.assertIn(b"<!-- compose-kit begin", self.film.read_bytes())
        once = self.film.read_bytes()
        self.assertEqual(run(INLINE, self.film).returncode, 0)
        self.assertEqual(self.film.read_bytes(), once, "a refresh of a CRLF film changes nothing")

    def test_an_lf_film_stays_lf_and_no_temporary_file_is_left(self):
        r = run(INLINE, self.film, "--init")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(b"\r\n", self.film.read_bytes())
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["STATE.md", "film.html"])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores folder permissions")
    def test_a_folder_that_cannot_be_written_leaves_both_files_whole(self):
        before = self.film.read_bytes(), (self.dir / "STATE.md").read_bytes()
        os.chmod(self.dir, 0o555)
        try:
            r = run(INLINE, self.film, "--init")
        finally:
            os.chmod(self.dir, 0o755)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertRegex(r.stderr, r"^FAILED: cannot write")
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual((self.film.read_bytes(), (self.dir / "STATE.md").read_bytes()), before)


class TestAspectAndSize(FilmCase):
    def test_aspect_label(self):
        mod = load("compose/inline.py", "film_inline_aspect")
        for (w, h), want in {(1920, 1080): "16:9", (960, 540): "16:9", (1080, 1920): "9:16", (1080, 1080): "1:1",
                             (1440, 1080): "4:3", (2048, 858): "2.39:1", (858, 2048): "1:2.39"}.items():
            self.assertEqual(mod.aspect(w, h), want, f"{w}x{h}")

    def test_state_format_line_follows_the_size(self):
        r = run(INLINE, self.film, "--init", "--size", "1080x1920")
        self.assertEqual(r.returncode, 0, r.stderr)
        state = (self.dir / "STATE.md").read_text(encoding="utf-8")
        self.assertRegex(state, r"\*\*Format:\*\* [\d.?]+ s, 9:16, 1080x1920, 24 fps")
        self.assertIn("STATE.md Format: 9:16, 1080x1920", r.stdout)

    def test_a_film_without_the_size_line_is_a_warning(self):
        html = self.html()
        line = re.search(r"const W = \+q\.get\('w'\) \|\| \d+, H = \+q\.get\('h'\) \|\| \d+", html)[0]
        self.film.write_text(html.replace(line, "const W = 1280, H = 720"), encoding="utf-8")
        r = run(INLINE, self.film, "--init")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"(?m)^WARNING: the default size line .* was not found")
        self.assertIn("const W = 1280, H = 720", self.html())
        r = run(INLINE, self.film)
        self.assertRegex(r.stdout, r"(?m)^WARNING: the default size line")


class TestAnchorsFromAnyDirectory(FilmCase):
    def setUp(self):
        super().setUp()
        self.ep = self.tmp / "projects" / "p" / "ep01-demo"
        self.ep.mkdir(parents=True)
        self.anchors = self.ep / "anchors.json"
        self.anchors.write_text(json.dumps({"a.png": {"eye": [10, 20]}}), encoding="utf-8")

    def test_a_relative_anchors_path_is_found_again_from_another_directory(self):
        r = run(INLINE, self.film.relative_to(self.tmp), "--init", "--anchors", "projects/p/ep01-demo/anchors.json", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        rel = "../../../../../projects/p/ep01-demo/anchors.json"
        self.assertRegex(self.html(), r"<!-- compose-kit begin v\S+ anchors=%s sha=[0-9a-f]{8}: " % re.escape(rel))
        self.anchors.write_text(json.dumps({"a.png": {"eye": [99, 99]}}), encoding="utf-8")
        for cwd in (self.dir, self.tmp / "projects", REPO):
            with self.subTest(cwd=str(cwd)):
                r = run(INLINE, self.film, cwd=cwd)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("anchors: refreshed from", r.stdout)
                self.assertNotIn("kept from the earlier embed", r.stdout)
                self.assertIn('{"a.png":{"eye":[99,99]}}', self.html())

    def test_a_path_recorded_relative_to_the_old_working_directory_is_found_and_recorded_anew(self):
        r = run(INLINE, self.film, "--init", "--anchors", self.anchors)
        self.assertEqual(r.returncode, 0, r.stderr)
        old, n = re.subn(r"anchors=\S+ sha=", "anchors=projects/p/ep01-demo/anchors.json sha=", self.html())
        self.assertEqual(n, 1)
        self.film.write_text(old, encoding="utf-8")
        r = run(INLINE, self.film, cwd=self.tmp)                 # the directory the older inline.py ran in
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("anchors path recorded relative to film.html: ../../../../../projects/p/ep01-demo/anchors.json", r.stdout)
        r = run(INLINE, self.film, cwd=self.ep)                  # from now on, any directory
        self.assertIn("anchors: refreshed from", r.stdout)
        self.assertNotIn("anchors path recorded", r.stdout)


class TestDemoPlatesHelp(TmpDirCase, unittest.TestCase):
    def test_help_creates_nothing(self):
        r = run(DEMO, "--help", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("placeholder plates", r.stdout)
        self.assertEqual(list(self.tmp.iterdir()), [], "no out/demo, no --help folder")
        r = run(DEMO, "--bogus", cwd=self.tmp)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(list(self.tmp.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
