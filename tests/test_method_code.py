"""method: code (characters drawn in code, tools/toon/; issue #38): check_episode, the engine: code style packs,
status.py and inline.py --toon. Free: no browser, no API (the browser renders are in test_toon.py)."""
import json, re, shutil, unittest
from pathlib import Path

from helpers import EPISODE_FIX, REPO, TmpDirCase, load, run_main

ce = load("check_episode.py")
st = load("status.py")
inline = load("compose/inline.py", "film_inline")

CODE_SHOTS = """shot,from_s,to_s,shot_size,camera,action,layers,code_motion,ai_motion,sound,reuse_of
s01,0,8,wide,track,Giọt đi vào khung,C-giot;E-doi-co,walk-cycle,,wind,
s02,8,15,medium,push-in,Giọt vẫy tay,C-giot;E-doi-co;T,wave,,pop,
s03,15,24.5,close,orbit,Giọt nhảy,C-giot;E-doi-co;FX-bui,jump,,,
s04,24.5,30,wide,crane,Giọt đi ra,C-giot;E-doi-co,walk-cycle,,wind,
"""


class CodeEpisode(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.ep = self.tmp / "projects" / "test-series" / "ep01-test-ep"
        shutil.copytree(EPISODE_FIX, self.ep)
        (self.ep / "prompts.csv").unlink()
        (self.ep / "shots.csv").write_text(CODE_SHOTS, encoding="utf-8")
        (self.ep / "budget.yaml").write_text("images: 0\nvideo_seconds: 0\nledger_required: true\n", encoding="utf-8")
        s = (self.ep / "EPISODE.md").read_text(encoding="utf-8")
        s = re.sub(r"(?m)^method:.*\n", "", s).replace("stage: 5\n", "method: code\nstage: 5\n", 1)
        s = re.sub(r"(?m)^style: .*$", "style: hoat-hinh-phang", s)
        (self.ep / "EPISODE.md").write_text(s, encoding="utf-8")
        self.media = self.tmp / "out" / "test-series" / "ep01"
        (self.media / "renders").mkdir(parents=True)
        (self.media / "ledger.csv").write_text(",".join(ce.LEDGER_HEADER) + "\n")

    def check(self):
        return run_main(ce.main, ["episode", str(self.ep), "--media", str(self.media)])

    def errors(self, out):
        return [l for l in out.splitlines() if l.startswith("ERROR")]

    def test_clean_code_episode_passes(self):
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("prompts.csv", out)              # not needed, not asked for

    def test_caps_must_be_zero(self):
        (self.ep / "budget.yaml").write_text("images: 4\nvideo_seconds: 0\nledger_required: true\n", encoding="utf-8")
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        self.assertTrue(any("method code: images = 4 must be 0" in l for l in self.errors(out)), out)

    def test_plate_layer_codes_are_errors(self):
        (self.ep / "shots.csv").write_text(CODE_SHOTS.replace("C-giot;E-doi-co,walk-cycle,,wind,\ns02", "L1;L4,walk-cycle,,wind,\ns02"),
                                           encoding="utf-8")
        code, out, _ = self.check()
        self.assertTrue(any("method code: layer code 'L1' invalid" in l for l in self.errors(out)), out)

    def test_ai_motion_is_error(self):
        (self.ep / "shots.csv").write_text(CODE_SHOTS.replace("jump,,,", "jump,the beast turns,,"), encoding="utf-8")
        code, out, _ = self.check()
        self.assertTrue(any("method code: shot s03 has ai_motion" in l for l in self.errors(out)), out)

    def test_code_cameras_only_in_code(self):
        s = (self.ep / "EPISODE.md").read_text(encoding="utf-8").replace("method: code", "method: layers")
        s = s.replace("style: hoat-hinh-phang", "style: thuy-mac")
        (self.ep / "EPISODE.md").write_text(s, encoding="utf-8")
        code, out, _ = self.check()
        self.assertTrue(any("camera 'orbit' is not one move" in l for l in self.errors(out)), out)

    def test_style_engine_must_match_method(self):
        s = (self.ep / "EPISODE.md").read_text(encoding="utf-8").replace("style: hoat-hinh-phang", "style: thuy-mac")
        (self.ep / "EPISODE.md").write_text(s, encoding="utf-8")
        code, out, _ = self.check()
        self.assertTrue(any("method code needs an engine: code style pack" in l for l in self.errors(out)), out)

    def test_prompts_csv_is_only_a_warning(self):
        shutil.copy(EPISODE_FIX / "prompts.csv", self.ep / "prompts.csv")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("WARN  prompts.csv: method code generates no image or clip", out)

    def test_status_forecast_and_g2(self):
        code, out, _ = run_main(st.main, [str(self.ep), "--media", str(self.media), "--gate", "G2"])
        self.assertIn("METHOD code", out)
        self.assertIn("images: 0 to make", out)
        self.assertIn("a character.json (characters/<slug>/) (none)", out)
        (self.ep / "characters" / "giot").mkdir(parents=True)
        (self.ep / "characters" / "giot" / "character.json").write_text("{}", encoding="utf-8")
        (self.ep / "review").mkdir(exist_ok=True)
        (self.ep / "review" / "turntable-giot.png").write_bytes(b"x")
        code, out, _ = run_main(st.main, [str(self.ep), "--media", str(self.media), "--gate", "G2"])
        self.assertIn("[ok] a character.json (characters/<slug>/) (characters/giot/character.json)", out)
        self.assertIn("[ok] turntable of the characters", out)
        self.assertIn("Gate G2: READY", out)


class CodeStyles(unittest.TestCase):
    """The eleven engine: code style packs pass the style check and agree with looks.json."""
    IDS = ["dat-nan-3d", "hoat-hinh-phang", "ban-ve-ky-thuat", "in-riso", "pixel-16bit",
           "bong-muc", "ong-cao-su", "chu-ascii", "bia-cat-dan", "low-poly-90", "sach-pop-up"]

    def test_all_eleven_pass(self):
        for sid in self.IDS + ["_template-code"]:
            with self.subTest(style=sid):
                code, out, _ = run_main(ce.main, ["style", str(REPO / "styles" / sid)])
                self.assertEqual(code, 0, out)
                if sid != "_template-code":
                    self.assertIn("0 error(s), 0 warning(s)", out)

    def test_lookbook_lists_them(self):
        toon = load("toon/toon.py", "film_toon_cli")
        self.assertEqual(toon.LOOKBOOK, self.IDS)

    def test_render_errors(self):
        rep = ce.Report()
        ce.check_render({"engine": "three", "look": "flat-toon", "post": ["sepia"], "hold": 9, "palette": {"sky": "blue"}}, rep)
        text = "\n".join(e for e in rep.text("x").splitlines() if e.startswith("ERROR"))
        self.assertIn("does not match look flat-toon", text)
        self.assertIn("render.post 'sepia'", text)
        self.assertIn("render.hold 9", text)
        self.assertIn("render.palette.sky", text)

    def test_looks_json_matches_kit(self):
        looks = json.loads((REPO / "tools" / "toon" / "looks.json").read_text(encoding="utf-8"))
        src = (REPO / "tools" / "toon" / "toon.js").read_text(encoding="utf-8")
        for lid, spec in looks["looks"].items():
            self.assertRegex(src, rf"'{lid}': \{{ engine: '{spec['engine']}'", lid)
        for pid in looks["posts"]:
            self.assertIn(f"'{pid}'", src.split("T.POSTS = ")[1].split("\n")[0])


class InlineToon(TmpDirCase, unittest.TestCase):
    """inline.py --toon on cinecode's Quick template (skipped when cinecode is not installed)."""

    def setUp(self):
        super().setUp()
        kit = Path.home() / ".claude" / "skills" / "cinecode" / "templates" / "quick" / "film.html"
        if not kit.is_file():
            self.skipTest("cinecode Quick template not installed")
        self.film = self.tmp / "film.html"
        shutil.copy(kit, self.film)

    def run_inline(self, *args):
        import sys
        old = sys.argv
        sys.argv = ["inline.py", str(self.film), *args]
        try:
            return run_main(lambda _a: inline.main(), [])
        finally:
            sys.argv = old

    def test_init_toon_then_refresh_keeps_toon(self):
        code, out, err = self.run_inline("--init", "--toon")
        self.assertEqual(code, 0, out + err)
        html = self.film.read_text(encoding="utf-8")
        self.assertIn("// ---- tools/toon/toon.js", html)
        self.assertIn(".then(loadToon)", html)
        self.assertIn("COMPOSE.report().concat(TOON.report(), qc.warnings)", html)
        self.assertIn("TOON.THREE_URL = \"file://", html)
        self.assertIn("LOOKS.toon = ", html)
        code, out, err = self.run_inline()                 # a refresh without --toon keeps the TOON kit
        self.assertEqual(code, 0, out + err)
        html2 = self.film.read_text(encoding="utf-8")
        self.assertIn("// ---- tools/toon/toon.js", html2)
        self.assertEqual(html2.count("// ---- tools/toon/rig.js"), 1)


if __name__ == "__main__":
    unittest.main()
