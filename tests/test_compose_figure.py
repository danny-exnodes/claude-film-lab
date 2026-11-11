"""The code-drawn ink figure of method `layers` (tools/compose/ink.js, figure.js): tests/js/figure.test.cjs under
`node --test`, the kit lint and registration, inline.py on the cinecode fixture, and one check on real pixels in
headless Chrome. Free: no API.

Skipped when node (or Chrome) is not installed, so `python3 -m unittest discover -s tests` stays the one test command.
"""
import json, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
JS = REPO / "tests" / "js"
KIT = REPO / "tools" / "compose"
INLINE = KIT / "inline.py"
FIXTURE = REPO / "tests" / "fixtures" / "cinecode"
NODE = shutil.which("node")
CHROME = next((c for c in ("/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium") if Path(c).exists()), None)
FILES = ("ink.js", "figure.js")

# A paper-coloured 1920x1080 stage; one figure from behind at (960, 800), 240 px tall, in a strong wind from the left.
# Measured: where the ink is (its bounding box and how dark it gets), a second frame 1/24 s later, the same frame twice.
PAGE = """<!doctype html><meta charset=utf-8><body><pre id=o>running</pre><script>__KIT__</script><script>
try { (() => {
  const C = COMPOSE, W = 1920, H = 1080, PAPER = [239, 230, 211];
  C.seed = 7;
  const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
  const g = cv.getContext('2d', { willReadFrequently: true });
  const shot = (t, o) => {
    g.fillStyle = 'rgb(' + PAPER.join(',') + ')'; g.fillRect(0, 0, W, H);
    C.stage(g, { W, H }, C.camera(t), (st) => { st.wind = { dir: 0, strength: 0.9, gust: 0.5 }; C.figure.draw(st, o); });
    return g.getImageData(0, 0, W, H).data;
  };
  const measure = (d) => {
    let x0 = W, y0 = H, x1 = -1, y1 = -1, ink = 0, dark = 0, lighter = 0;
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const i = (y * W + x) * 4, lum = (d[i] + d[i + 1] + d[i + 2]) / 3, paper = (PAPER[0] + PAPER[1] + PAPER[2]) / 3;
      if (lum > paper + 1) lighter++;
      if (lum < paper - 12) { ink++; if (lum < 90) dark++; x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
    }
    return { box: [x0, y0, x1, y1], ink, dark, lighter };
  };
  const diff = (a, b) => { let n = 0; for (let i = 0; i < a.length; i += 4) if (Math.abs(a[i] - b[i]) > 1) n++; return n; };
  const o = { x: 960, y: 800, height: 240, salt: 1 };
  const a = shot(2, o), res = { a: measure(a), again: diff(a, shot(2, o)), next: diff(a, shot(2 + 1 / 24, o)) };
  res.tiny = measure(shot(2, { x: 960, y: 800, height: 60, salt: 1 }));
  res.walk = [3, 3.5].map((t) => measure(shot(t, { height: 200, salt: 2, path: [{ at: 0, x: 500, y: 800 }, { at: 8, x: 1300, y: 800 }] })));
  res.warnings = C.report();
  document.getElementById('o').textContent = 'RESULT ' + JSON.stringify(res);
})(); } catch (e) { document.getElementById('o').textContent = 'ERROR ' + e.stack; }
</script>"""


def inline():
    sys.path.insert(0, str(KIT))
    try:
        import inline as module
    finally:
        sys.path.remove(str(KIT))
    return module


@unittest.skipUnless(NODE, "node is not installed (the kit's JavaScript tests need it)")
class TestFigureJs(unittest.TestCase):
    def test_node_suite(self):
        r = subprocess.run([NODE, "--test", str(JS / "figure.test.cjs")], capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, "node --test failed:\n" + r.stdout[-6000:] + r.stderr[-2000:])


class TestFigureRegistration(unittest.TestCase):
    def test_files_are_pure(self):
        module = inline()
        for f in FILES:
            self.assertEqual(module.lint(f, (KIT / f).read_text(encoding="utf-8")), [])

    def test_order_and_lint_count(self):
        module = inline()
        order = module.ORDER
        self.assertLess(order.index("pose.js"), order.index("ink.js"))
        self.assertLess(order.index("cloth.js"), order.index("figure.js"))
        self.assertEqual(order.index("ink.js") + 1, order.index("figure.js"))
        self.assertFalse(set(FILES) & module.OPTIONAL, "the figure files are part of the kit, not optional")
        self.assertEqual(len(order), 16)
        r = subprocess.run([sys.executable, str(INLINE), "--lint"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"^compose kit v1\.[2-9]\d*\.\d+: 16 files, lint ok$")

    def test_motion_id_and_style(self):
        motions = json.loads((KIT / "motions.json").read_text(encoding="utf-8"))["motions"]
        self.assertEqual(motions["figure"]["module"], "figure.js")
        self.assertIn("COMPOSE.figure.draw", motions["figure"]["call"])
        style = (REPO / "styles" / "thuy-mac" / "style.yaml").read_text(encoding="utf-8")
        self.assertRegex(re.search(r"(?ms)^motion: \[(.*?)\]", style)[1], r"\bfigure\b")
        r = subprocess.run([sys.executable, str(REPO / "tools" / "check_episode.py"), "style", str(REPO / "styles" / "thuy-mac")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("is not in tools/compose/motions.json", r.stdout)

    def test_adapted_files_name_their_source(self):
        third = (REPO / "THIRD_PARTY.md").read_text(encoding="utf-8")
        for f, source in (("ink.js", "styles/ink-wash/demo/ink.js"), ("figure.js", "styles/ink-wash/demo/hero.js")):
            head = (KIT / f).read_text(encoding="utf-8").split("(function (root)")[0]
            self.assertIn("lemomo-ai/lemo-opuscar, " + source, head)
            self.assertIn("Copyright (c) 2026 LemoLab, MIT License", head)
            self.assertIn("Changed:", head)
            self.assertRegex(third, rf"\| `tools/compose/{re.escape(f)}` \| .*{re.escape(source)}.* \| MIT \|")
        self.assertIn("Copyright (c) 2026 LemoLab", third)
        self.assertIn('THE SOFTWARE IS PROVIDED "AS IS"', third)


class TestFigureInFilm(unittest.TestCase):
    def test_init_on_the_cinecode_fixture_inlines_both_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            film = Path(tmp) / "film.html"
            shutil.copy(FIXTURE / "film.html", film)
            shutil.copy(FIXTURE / "quick-STATE.md", Path(tmp) / "STATE.md")
            r = subprocess.run([sys.executable, str(INLINE), str(film), "--init"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("inlined (16 files, ", r.stdout)
            self.assertNotIn("WARNING", r.stdout)
            html = film.read_text(encoding="utf-8")
            marks = [html.find(f"// ---- tools/compose/{f}\n") for f in ("cloth.js", "pose.js", "ink.js", "figure.js", "mist.js")]
            self.assertTrue(all(m > 0 for m in marks))
            self.assertEqual(marks, sorted(marks))
            for f in FILES:
                self.assertEqual(html.count(f"// ---- tools/compose/{f}\n"), 1)
            once = html
            self.assertEqual(subprocess.run([sys.executable, str(INLINE), str(film)], capture_output=True, text=True).returncode, 0)
            self.assertEqual(film.read_text(encoding="utf-8"), once)


@unittest.skipUnless(CHROME, "Chrome is not installed (the pixel check needs a real canvas)")
class TestFigurePixels(unittest.TestCase):
    def test_the_figure_is_ink_on_paper_where_it_stands(self):
        kit = "\n".join((KIT / f).read_text(encoding="utf-8") for f in ["core.js", "plates.js", "stage.js", "cloth.js", *FILES])
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "figure.html"
            page.write_text(PAGE.replace("__KIT__", kit), encoding="utf-8")
            try:
                r = subprocess.run([CHROME, "--no-sandbox", "--headless=new", "--disable-gpu", "--virtual-time-budget=8000",
                                    "--dump-dom", page.as_uri()], capture_output=True, text=True, timeout=90)
            except (OSError, subprocess.TimeoutExpired) as e:
                self.skipTest(f"Chrome did not run: {e}")
        m = re.search(r'<pre id="o">(RESULT|ERROR) (.*?)</pre>', r.stdout, re.S)
        if not m:
            self.skipTest("Chrome gave no result (headless not available here, or the kit did not load)")
        self.assertEqual(m.group(1), "RESULT", m.group(2))
        res = json.loads(m.group(2).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))
        self.assertEqual(res["warnings"], [])
        self.assertEqual(res["again"], 0, "the same frame drawn twice differs")
        self.assertGreater(res["next"], 50, "the cloth does not move from one frame to the next")
        a = res["a"]
        x0, y0, x1, y1 = a["box"]
        self.assertEqual(a["lighter"], 0, "ink only darkens the paper")
        # it stands on (960, 800) and is about 240 px tall: head to feet, not a dot and not a smear across the frame
        self.assertTrue(795 <= y1 <= 812, a)
        self.assertTrue(200 <= y1 - y0 <= 262, a)
        self.assertTrue(x0 < 960 < x1 and 70 <= x1 - x0 <= 220, a)
        # neither a stick (a body has width and a pale mass) nor a blob (most of it is wash, the dark ink is the smaller part)
        self.assertGreater(a["ink"], 6000, a)
        self.assertGreater(a["dark"], 400, a)
        self.assertLess(a["dark"], a["ink"] * 0.6, a)
        tiny = res["tiny"]
        self.assertTrue(45 <= tiny["box"][3] - tiny["box"][1] <= 70, tiny)
        self.assertGreater(tiny["ink"], 300, tiny)
        # walking right: the ink moves with the path, the feet stay on the ground line
        w0, w1 = res["walk"]
        self.assertGreater(w1["box"][0], w0["box"][0] + 25)
        for w in (w0, w1):
            self.assertTrue(795 <= w["box"][3] <= 812, w)


if __name__ == "__main__":
    unittest.main()
