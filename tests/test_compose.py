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
        """The lint line counts the files really inlined: ORDER minus the OPTIONAL ones that are not there yet."""
        order = re.search(r"(?m)^ORDER = \[([^\]]+)\]", INLINE.read_text(encoding="utf-8"))
        names = re.findall(r'"([^"]+\.js)"', order[1])
        for f in ("smoke.js", "fire.js", "foliage.js", "cloth.js", "pose.js"):
            self.assertIn(f, names)
        self.assertLess(names.index("strip-warp.js"), names.index("cloth.js"))
        self.assertLess(names.index("strip-warp.js"), names.index("pose.js"))
        there = [f for f in names if (INLINE.parent / f).is_file()]
        missing = [f for f in names if f not in there]
        self.assertLessEqual(set(missing), {"cloth.js", "pose.js"})
        self.assertGreaterEqual(len(there), 12)
        r = run(INLINE, "--lint")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, rf"compose kit v\S+: {len(there)} files, lint ok")
        if missing:
            self.assertIn(f"(optional, not there yet: {', '.join(missing)})", r.stdout)


class TestInlineKitFiles(FilmCase):
    """ORDER lists cloth.js and pose.js before they exist: only those two may be missing."""
    def setUp(self):
        super().setUp()
        self.kit = self.tmp / "lab" / "tools" / "compose"            # a copy of the kit: the repo is never edited
        self.kit.mkdir(parents=True)
        for f in INLINE.parent.iterdir():
            if f.suffix in (".js", ".py", ".json"):
                shutil.copy(f, self.kit / f.name)
        tpl = Path(".claude") / "skills" / "film-compose-shot" / "templates" / "plates-film-section.js"
        (self.tmp / "lab" / tpl).parent.mkdir(parents=True)
        shutil.copy(REPO / tpl, self.tmp / "lab" / tpl)
        for f in ("cloth.js", "pose.js"):
            (self.kit / f).unlink(missing_ok=True)

    def count(self):
        r = run(self.kit / "inline.py", "--lint")
        self.assertEqual(r.returncode, 0, r.stderr)
        return int(re.search(r": (\d+) files, lint ok", r.stdout)[1]), r.stdout

    def test_optional_files_are_skipped_until_they_exist(self):
        n, out = self.count()
        self.assertIn("(optional, not there yet: cloth.js, pose.js)", out)
        r = run(self.kit / "inline.py", self.film, "--init")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"inlined ({n} files, ", r.stdout)
        html = self.html()
        for f in ("smoke.js", "fire.js", "foliage.js"):
            self.assertEqual(html.count(f"// ---- tools/compose/{f}\n"), 1, f)
        self.assertNotIn("// ---- tools/compose/cloth.js", html)
        self.assertNotIn("// ---- tools/compose/pose.js", html)
        self.assertLess(html.find("// ---- tools/compose/strip-warp.js"), html.find("// ---- tools/compose/foliage.js"))
        self.assertLess(html.find("// ---- tools/compose/mist.js"), html.find("// ---- tools/compose/smoke.js"))

        (self.kit / "cloth.js").write_text("// COMPOSE cloth (stub)\n", encoding="utf-8")
        n2, out = self.count()
        self.assertEqual(n2, n + 1)
        self.assertIn("(optional, not there yet: pose.js)", out)
        self.assertEqual(run(self.kit / "inline.py", self.film).returncode, 0)
        html = self.html()
        self.assertLess(html.find("// ---- tools/compose/strip-warp.js"), html.find("// ---- tools/compose/cloth.js"))
        # cloth cuts its region out of the plate at load: it must come after the rigs that sample the whole plate
        self.assertLess(html.find("// ---- tools/compose/eyelid.js"), html.find("// ---- tools/compose/cloth.js"))
        (self.kit / "pose.js").write_text("// COMPOSE pose (stub)\n", encoding="utf-8")
        n3, out = self.count()
        self.assertEqual(n3, n + 2)
        self.assertNotIn("not there yet", out)

    def test_an_optional_file_is_linted_like_the_rest(self):
        (self.kit / "pose.js").write_text("const x = Math.random();\n", encoding="utf-8")
        r = run(self.kit / "inline.py", "--lint")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("pose.js:1", r.stderr)

    def test_a_missing_required_file_fails_and_leaves_the_film_alone(self):
        (self.kit / "smoke.js").unlink()
        before = self.html()
        for args in (("--lint",), (self.film, "--init")):
            r = run(self.kit / "inline.py", *args)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("FAILED: kit file tools/compose/smoke.js: cannot be read", r.stderr)
            self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(self.html(), before)


class TestInlineQc(FilmCase):
    """READY's qc list carries the kit's warnings: a headless capture never shows console.warn."""
    PATCHED = "qc: COMPOSE.report().concat(qc.warnings),"

    def test_ready_qc_patched_on_pinned_template_and_idempotent(self):
        self.assertEqual(self.html().count("qc: qc.warnings"), 1)            # what the pin looks like
        r = run(INLINE, self.film, "--init")
        self.assertEqual(r.returncode, 0, r.stderr)
        html = self.html()
        self.assertEqual(html.count(self.PATCHED), 1)
        self.assertNotIn("qc: qc.warnings", html)
        self.assertGreater(html.find(self.PATCHED), html.find("\nwindow.READY = "))
        self.assertIn("C.report = ", html)                                   # the kit in the film has it
        self.assertIn("READY qc", r.stdout)
        self.assertNotIn("WARNING", r.stdout)
        r = run(INLINE, self.film)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.html(), html)
        self.assertNotIn("READY qc", r.stdout)
        self.assertNotIn("WARNING", r.stdout)

    def test_film_inlined_before_the_patch_gets_it_on_refresh(self):
        self.assertEqual(run(INLINE, self.film, "--init").returncode, 0)
        self.film.write_text(self.html().replace(self.PATCHED, "qc: qc.warnings,"), encoding="utf-8")
        r = run(INLINE, self.film)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.html().count(self.PATCHED), 1)

    def test_missing_qc_text_is_a_warning(self):
        """A cinecode template whose READY no longer returns `qc: qc.warnings`: doctor's compose-kit check must fail."""
        self.film.write_text(self.html().replace("qc: qc.warnings", "checks: qc.warnings"), encoding="utf-8")
        r = run(INLINE, self.film, "--init")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"(?m)^WARNING")
        self.assertNotIn("COMPOSE.report()", self.html().split("<!-- compose-kit end -->")[1])


class TestInlineAnchors(FilmCase):
    def setUp(self):
        super().setUp()
        self.anchors = self.tmp / "anchors.json"
        self.write({"a.png": {"eye": [10, 20]}})

    def write(self, data):
        self.anchors.write_text(json.dumps(data), encoding="utf-8")

    def test_refresh_rereads_the_recorded_anchors_file(self):
        r = run(INLINE, self.film, "--init", "--anchors", self.anchors)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('COMPOSE.ANCHORS = {"a.png":{"eye":[10,20]}};', self.html())
        self.assertRegex(self.html(), r"<!-- compose-kit begin v\S+ anchors=%s sha=[0-9a-f]{8}: " % re.escape(str(self.anchors)))
        self.write({"a.png": {"eye": [99, 99]}})
        r = run(INLINE, self.film)                               # the refresh form of the docstring, no --anchors
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"anchors: refreshed from {self.anchors}", r.stdout)
        self.assertIn('COMPOSE.ANCHORS = {"a.png":{"eye":[99,99]}};', self.html())
        self.assertNotIn("[10,20]", self.html())
        once = self.html()
        self.assertEqual(run(INLINE, self.film).returncode, 0)
        self.assertEqual(self.html(), once)

    def test_removed_anchors_file_keeps_the_embed_and_says_so(self):
        self.assertEqual(run(INLINE, self.film, "--init", "--anchors", self.anchors).returncode, 0)
        once = self.html()
        self.anchors.unlink()
        r = run(INLINE, self.film)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("anchors: kept from the earlier embed", r.stdout)
        self.assertEqual(self.html(), once)                      # the source stays recorded for when it is back
        self.write({"a.png": {"eye": [5, 6]}})
        r = run(INLINE, self.film)
        self.assertIn("anchors: refreshed from", r.stdout)
        self.assertIn('{"a.png":{"eye":[5,6]}}', self.html())

    def test_film_inlined_before_the_source_was_recorded_keeps_its_embed(self):
        self.assertEqual(run(INLINE, self.film, "--init", "--anchors", self.anchors).returncode, 0)
        old, n = re.subn(r"(<!-- compose-kit begin v\S+) anchors=.*? sha=[0-9a-f]{8}:", r"\1:", self.html())
        self.assertEqual(n, 1)
        self.film.write_text(old, encoding="utf-8")
        self.write({"a.png": {"eye": [99, 99]}})
        r = run(INLINE, self.film)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("anchors: kept from the earlier embed", r.stdout)
        self.assertIn('COMPOSE.ANCHORS = {"a.png":{"eye":[10,20]}};', self.html())

    def test_refresh_fails_on_a_recorded_file_that_is_no_longer_json(self):
        self.assertEqual(run(INLINE, self.film, "--init", "--anchors", self.anchors).returncode, 0)
        once = self.html()
        self.anchors.write_text("{ not json", encoding="utf-8")
        r = run(INLINE, self.film)
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stderr, r"^FAILED: ")
        self.assertEqual(self.html(), once)

    def test_closing_script_tag_in_an_anchor_key_stays_inside_the_block(self):
        self.assertEqual(run(INLINE, self.film, "--init").returncode, 0)
        closing = self.html().count("</script>")
        data = {"a</script><!--b.png": {"eye": [1, 2]}}
        self.write(data)
        r = run(INLINE, self.film, "--anchors", self.anchors)
        self.assertEqual(r.returncode, 0, r.stderr)
        html = self.html()
        self.assertEqual(html.count("</script>"), closing)
        m = re.search(r"COMPOSE\.ANCHORS = (.*);\n", html)
        self.assertNotIn("<!--", m[1])
        # what JavaScript reads back is the original key: "\/" is "/" and "\!" is "!" in a string literal
        self.assertEqual(json.loads(m[1].replace("<\\!--", "<!--")), data)
        self.assertEqual(run(INLINE, self.film).returncode, 0)
        self.assertEqual(self.html(), html)


class TestInlineNoHalfWrites(FilmCase):
    def both(self):
        return self.film.read_bytes(), (self.tmp / "STATE.md").read_bytes()

    def assert_fails_untouched(self, *args):
        before = self.both()
        r = run(INLINE, self.film, *args)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertRegex(r.stderr, r"^FAILED: ")
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(self.both(), before)
        return r

    def test_bad_anchors_argument(self):
        self.assert_fails_untouched("--init", "--anchors", self.tmp / "nope.json")
        bad = self.tmp / "bad.json"
        bad.write_text("{ not json", encoding="utf-8")
        self.assert_fails_untouched("--init", "--anchors", bad)
        bad.write_text("[1, 2]", encoding="utf-8")
        r = self.assert_fails_untouched("--init", "--anchors", bad)
        self.assertIn("object", r.stderr)

    def test_text_that_cannot_be_written_as_utf8_does_not_empty_the_film(self):
        """write_text opens (truncates) the file before it encodes: a lone surrogate used to leave film.html empty."""
        bad = self.tmp / "sur.json"
        bad.write_text('{"a\\ud800.png": {"eye": [1, 2]}}', encoding="utf-8")
        r = self.assert_fails_untouched("--init", "--anchors", bad)
        self.assertIn("UTF-8", r.stderr)
        self.assertEqual(run(INLINE, self.film, "--init").returncode, 0)
        before = self.both()
        self.assertGreater(len(before[0]), 1000)
        r = run(INLINE, self.film, "--anchors", bad)             # the refresh form: a film with scenes in it
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertRegex(r.stderr, r"^FAILED: ")
        self.assertEqual(self.both(), before)

    def test_unreadable_state_md(self):
        (self.tmp / "STATE.md").write_bytes(b"**Format:** <length, aspect, size, fps> \xff\n")
        self.assert_fails_untouched("--init")

    def test_anchors_path_that_would_close_the_marker_comment(self):
        for name in ("a --!> b.json", "a --> b.json", "a sha=b.json"):
            with self.subTest(name=name):
                odd = self.tmp / name
                odd.write_text('{"a.png": {"eye": [1, 2]}}', encoding="utf-8")
                r = self.assert_fails_untouched("--init", "--anchors", odd)
                self.assertIn("--anchors", r.stderr)

    def test_bad_size_argument(self):
        for size in ("1920", "1920x", "x1080", "0x1080", "1920x1080x2", "wide"):
            with self.subTest(size=size):
                r = self.assert_fails_untouched("--init", "--size", size)
                self.assertIn("--size", r.stderr)

    def test_late_failure_leaves_state_md_alone(self):
        html = self.html().replace("window.READY = loadType(TYPE)", "window.READY = loadKinds(TYPE)")
        self.film.write_text(html, encoding="utf-8")
        r = self.assert_fails_untouched("--init")
        self.assertIn("READY line not found", r.stderr)

    def test_missing_film(self):
        r = run(INLINE, self.tmp / "nope" / "film.html")
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stderr, r"^FAILED: ")

    def test_refresh_keeps_what_follows_the_end_marker(self):
        self.assertEqual(run(INLINE, self.film, "--init").returncode, 0)
        once = self.html()
        self.assertIn("<!-- compose-kit end -->\n<script>", once)
        glued = once.replace("<!-- compose-kit end -->\n<script>", "<!-- compose-kit end --><script>")
        self.film.write_text(glued, encoding="utf-8")
        r = run(INLINE, self.film)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.html(), once)                      # `<script>` whole, the newline back


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
