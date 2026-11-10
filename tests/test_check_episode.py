"""tools/check_episode.py: a valid episode/style fixture passes; broken variants (made in tmp dirs) fail."""
import re, shutil, unittest
from pathlib import Path

from helpers import EPISODE_FIX, STYLE_FIX, TmpDirCase, load, run_main

ce = load("check_episode.py", "film_check_episode")

PLATES = ["ep01_s01_L1_nui-co_v01.png", "ep01_s02_L4_bac-thi_v02.png", "ep01_s02_P1-duoi_bac-thi_v01.png"]


class EpisodeCase(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.ep = self.tmp / "series" / "test-series" / "ep01-test-ep"
        shutil.copytree(EPISODE_FIX, self.ep)
        self.media = self.tmp / "out" / "test-series" / "ep01"
        for sub, names in (("plates", PLATES), ("clips", ["ep01_s02_seedance25_v01.mp4"]),
                           ("renders", ["ep01_draft_v01.mp4"])):
            (self.media / sub).mkdir(parents=True)
            for n in names:
                (self.media / sub / n).write_bytes(b"x")
        (self.media / "ledger.csv").write_text(",".join(ce.LEDGER_HEADER) + "\n")

    def check(self, *extra, media=True):
        argv = ["episode", str(self.ep)] + (["--media", str(self.media)] if media else []) + list(extra)
        return run_main(ce.main, argv)

    def edit(self, name, old, new, count=1):
        p = self.ep / name
        s = p.read_text(encoding="utf-8")
        self.assertIn(old, s, f"fixture text not found in {name}")
        p.write_text(s.replace(old, new, count), encoding="utf-8")

    def assert_error(self, pattern):
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        self.assertTrue(any(l.startswith("ERROR") and re.search(pattern, l) for l in out.splitlines()),
                        f"no ERROR matching {pattern!r} in:\n{out}")
        return out


class TestEpisodeGood(EpisodeCase):
    def test_fixture_passes(self):
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("Summary: 0 error(s)", out)
        self.assertIn("4 shot(s), 30 s", out)
        self.assertRegex(out, r"WARN  script.md:\d+: en dash outside narration")   # blockquote note: WARN only

    def test_unknown_code_motion_is_warn(self):
        self.edit("shots.csv", "L1;L2;L3,mist-bands,", "L1;L2;L3,mist-bands;fog-wobble,")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("code_motion 'fog-wobble' is not in tools/compose/motions.json", out)

    def test_report_file(self):
        code, out, _ = self.check("--out", "review/check-v1.txt")
        self.assertEqual(code, 0)
        rep = (self.ep / "review" / "check-v1.txt").read_text()
        self.assertIn("Summary: 0 error(s)", rep)

    def test_missing_media_is_warn(self):
        shutil.rmtree(self.media)
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"WARN  media: media folder .* not found")

    def test_prompts_missing_before_stage_5_warn(self):
        (self.ep / "prompts.csv").unlink()
        self.edit("EPISODE.md", "stage: 5", "stage: 4")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("WARN  prompts.csv: missing", out)

    def test_prompts_missing_at_stage_5_error(self):
        (self.ep / "prompts.csv").unlink()
        self.assert_error(r"prompts.csv: missing \(required from stage 5")


class TestEpisodeFrontMatter(EpisodeCase):
    def test_missing_key(self):
        self.edit("EPISODE.md", 'drive: "AI Film Lab/test-series/ep01"\n', "")
        self.assert_error(r"front matter key 'drive' missing")

    def test_missing_section(self):
        self.edit("EPISODE.md", "## Việc tiếp theo", "## Viec tiep theo")
        self.assert_error(r"required section '## Việc tiếp theo' missing")

    def test_episode_number_mismatch(self):
        self.edit("EPISODE.md", "episode: 1", "episode: 2")
        self.assert_error(r"episode 2 != folder number ep01")

    def test_bad_gate_date(self):
        self.edit("EPISODE.md", "G1: 2026-11-01", "G1: yesterday")
        self.assert_error(r"gates.G1 = 'yesterday'")

    def test_stage_range(self):
        self.edit("EPISODE.md", "stage: 5", "stage: 12")
        self.assert_error(r"stage 12 must be an integer 0..11")

    def test_state_md_forbidden(self):
        (self.ep / "STATE.md").write_text("x")
        self.assert_error(r"STATE.md belongs to cinecode")


class TestEpisodeShots(EpisodeCase):
    def test_bad_header(self):
        self.edit("shots.csv", "reuse_of", "reuse")
        self.assert_error(r"shots.csv: header is")

    def test_not_continuous(self):
        self.edit("shots.csv", "s02,8,15", "s02,9,15")
        self.assert_error(r"not continuous: from_s=9 but previous to_s=8")

    def test_first_not_zero(self):
        self.edit("shots.csv", "s01,0,8", "s01,1,8")
        self.assert_error(r"first shot must start at 0")

    def test_too_short_and_too_long(self):
        self.edit("shots.csv", "s02,8,15", "s02,8,10")
        self.edit("shots.csv", "s03,15,24.5", "s03,10,24.5")
        out = self.assert_error(r"s02 lasts 2 s")
        self.assertRegex(out, r"s03 lasts 14.5 s")

    def test_wrong_end(self):
        self.edit("EPISODE.md", "length_s: 30", "length_s: 31")
        self.assert_error(r"last shot ends at 30 s, length_s is 31 s")

    def test_bad_values(self):
        self.edit("shots.csv", "s02,8,15,medium,push-in", "s02,8,15,mid,zoom")
        out = self.assert_error(r"shot_size 'mid'")
        self.assertIn("camera 'zoom'", out)

    def test_adjacent_identical(self):
        self.edit("shots.csv", "s02,8,15,medium,push-in", "s02,8,15,wide,static")
        self.assert_error(r"s02 repeats both shot_size 'wide' and camera 'static' of s01")

    def test_ids_increasing(self):
        self.edit("shots.csv", "s03,", "s02,")
        self.assert_error(r"shot ids must increase")

    def test_bad_layer_code(self):
        self.edit("shots.csv", "L1;L4,", "L1;L5;P-x,")
        out = self.assert_error(r"layer code 'L5' invalid")
        self.assertIn("layer code 'P-x' invalid", out)

    def test_reuse_unknown(self):
        self.edit("shots.csv", "wind,s01", "wind,s09")
        self.assert_error(r"reuse_of 's09' is not a shot id")


class TestEpisodeScript(EpisodeCase):
    def test_line_without_mark(self):
        self.edit("script.md", "[00:20] Người xưa", "Người xưa")
        self.assert_error(r"script.md:\d+: narration line without \[mm:ss\] mark")

    def test_marks_not_increasing(self):
        self.edit("script.md", "[00:20]", "[00:10]")
        self.assert_error(r"mark \[00:10\] not after previous \[00:12\]")

    def test_gap_under_3s(self):
        self.edit("script.md", "[00:05]", "[00:02]")
        self.assert_error(r"only 2 s after the previous line")

    def test_em_dash_in_narration(self):
        self.edit("script.md", "loài thú lạ.", "loài thú — lạ.")
        self.assert_error(r"em dash in narration")

    def test_beyond_length(self):
        self.edit("script.md", "[00:26] Hết.", "[00:26] Gần hết.\n[00:31] Hết.")
        self.assert_error(r"\[00:31\] = 31 s is not within length_s 30 s")


class TestEpisodePrompts(EpisodeCase):
    def test_bad_header(self):
        self.edit("prompts.csv", "drive_link", "link")
        self.assert_error(r"prompts.csv: header is")

    def test_bad_name(self):
        self.edit("prompts.csv", "ep01_s01_L1_nui-co_v01.png,s01", "ep01_s01_L1_Nui_Co_v1.png,s01")
        self.assert_error(r"file 'ep01_s01_L1_Nui_Co_v1.png' does not match")

    def test_shot_column_mismatch(self):
        self.edit("prompts.csv", "ep01_s01_L1_nui-co_v01.png,s01", "ep01_s01_L1_nui-co_v01.png,s02")
        self.assert_error(r"is for s01 but shot column is 's02'")

    def test_approved_value(self):
        self.edit("prompts.csv", ",yes,", ",maybe,")
        self.assert_error(r"approved 'maybe'")

    def test_listed_file_missing_in_media(self):
        (self.media / "plates" / PLATES[1]).unlink()
        self.assert_error(r"ep01_s02_L4_bac-thi_v02.png listed but not found")


class TestEpisodeMedia(EpisodeCase):
    def test_bad_media_names(self):
        (self.media / "plates" / "ep01_s03_L4_bac thi_v1.png").write_bytes(b"x")
        (self.media / "clips" / "s03.mp4").write_bytes(b"x")
        (self.media / "renders" / "ep01_final.mp4").write_bytes(b"x")
        out = self.assert_error(r"media/plates/ep01_s03_L4_bac thi_v1.png: name does not match")
        self.assertIn("media/clips/s03.mp4", out)
        self.assertIn("media/renders/ep01_final.mp4", out)

    def test_other_episode_file(self):
        (self.media / "clips" / "ep02_s01_seedance25_v01.mp4").write_bytes(b"x")
        self.assert_error(r"not for episode ep01")


class TestStyle(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.st = self.tmp / "styles" / "test-style"
        shutil.copytree(STYLE_FIX, self.st)

    def check(self):
        return run_main(ce.main, ["style", str(self.st)])

    def edit(self, old, new, name="style.yaml"):
        p = self.st / name
        s = p.read_text(encoding="utf-8")
        self.assertIn(old, s)
        p.write_text(s.replace(old, new, 1), encoding="utf-8")

    def assert_error(self, pattern):
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        self.assertTrue(any(l.startswith("ERROR") and re.search(pattern, l) for l in out.splitlines()),
                        f"no ERROR matching {pattern!r} in:\n{out}")

    def test_fixture_passes(self):
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("Summary: 0 error(s), 0 warning(s)", out)

    def test_id_mismatch(self):
        moved = self.tmp / "styles" / "other-style"
        self.st.rename(moved)
        self.st = moved
        self.assert_error(r"id 'test-style' != folder name 'other-style'")

    def test_missing_required(self):
        self.edit("light: \"upper-left, soft\"\n", "")
        self.assert_error(r"required key 'light' missing")

    def test_status(self):
        self.edit("status: draft", "status: beta")
        self.assert_error(r"status 'beta'")

    def test_method(self):
        self.edit("L3: {method: chroma", "L3: {method: grabcut")
        self.assert_error(r"matte.per_layer.L3.method 'grabcut'")

    def test_threshold_range(self):
        self.edit("low: 8, high: 245", "low: 8, high: 300")
        self.assert_error(r"matte.per_layer.L2.high = 300")

    def test_layer_bg(self):
        self.edit("low: 8, high: 245", "low: 8, high: 245, bg: white")
        self.assert_error(r"matte.per_layer.L2.bg = 'white' must be a #RRGGBB colour")

    def test_layer_bg_ok(self):
        self.edit("low: 8, high: 245", 'low: 8, high: 245, bg: "#FFFFFF"')
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("unknown key 'bg'", out)

    def test_low_ge_high(self):
        self.edit("low: 8, high: 245", "low: 245, high: 8")
        self.assert_error(r"low 245 must be < high 8")

    def test_hex(self):
        self.edit('seal: "#B0302A"', 'seal: "red"')
        self.assert_error(r"palette.seal = 'red'")
        self.edit('key_bg: "#FF00FF"', 'key_bg: "#FF00F"')
        self.assert_error(r"matte.key_bg")

    def test_placeholder(self):
        self.edit("{subject}", "{subject} {camera}", name="prompts/plate.txt")
        self.assert_error(r"placeholder \{camera\} not allowed")

    def test_no_prompts(self):
        shutil.rmtree(self.st / "prompts")
        self.assert_error(r"no prompt templates")


if __name__ == "__main__":
    unittest.main()
