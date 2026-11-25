"""Episode schema round (issues #28, #35): pose plates L4b.., shot ids s<NNN>, method code asset ids and the TOON
motion vocabulary, coverage rules (check-5) and the checker backlog items. Free: no API, no ffmpeg needed."""
import contextlib, io, re, shutil, unittest
from pathlib import Path
from unittest import mock

from helpers import EPISODE_FIX, STYLE_FIX, TmpDirCase, load, run_main

eid = load("episode_id.py", "film_episode_id_schema")
ce = load("check_episode.py", "film_check_episode_schema")
anchors = load("layers/anchors.py", "film_anchors_schema")
matte = load("layers/matte.py", "film_matte_schema")
bundle = load("bundle.py", "film_bundle_schema")
st = load("status.py", "film_status_schema")
ds = load("drive_sync.py", "film_drive_sync_schema")

PLATES = ["ep01_s01_L1_nui-co_v01.png", "ep01_s02_L4_bac-thi_v02.png", "ep01_s02_P1-duoi_bac-thi_v01.png"]


class TestSharedDefinitions(unittest.TestCase):
    def test_shot_ids(self):
        self.assertEqual(eid.shot_number("s03"), (3, 2))
        self.assertEqual(eid.shot_number("s103"), (103, 3))
        self.assertEqual(eid.shot_number("s007"), (7, 3))
        for bad in ("s1", "s1000", "S01", "s01 ", "03", "", None):
            self.assertIsNone(eid.shot_number(bad), bad)
        self.assertEqual(eid.make_shot(4), "s04")
        self.assertEqual(eid.make_shot(4, 3), "s004")

    def test_layer_codes(self):
        for good in ("L1", "L4", "L4b", "L4c", "L4z", "P1-duoi", "P12-canh-trai", "FX"):
            self.assertTrue(eid.RE_LAYER.match(good), good)
        for bad in ("L5", "L4a", "L1b", "L4B", "L4bb", "P", "P1", "FX-bui", "C-giot"):
            self.assertFalse(eid.RE_LAYER.match(bad), bad)
        self.assertEqual(eid.layer_family("L4b"), "L4")
        self.assertEqual(eid.layer_family("P3-duoi"), "P")
        self.assertEqual(eid.layer_family("L2"), "L2")

    def test_every_tool_accepts_pose_plates_and_three_digit_shots(self):
        for name in ("ep01_s03_L4b_bac-thi_v01.png", "q01t01_s103_L4c_bac-di_v02.png", "ep01_s103_L1_nui_v01.png"):
            with self.subTest(name=name):
                self.assertTrue(eid.RE_LAYER_FILE.match(name))
                self.assertTrue(ce.RE_LAYER_FILE.match(name))
                self.assertTrue(anchors.RE_LAYER_FILE.match(name))
                self.assertEqual(matte.RE_LAYER.match(name).group(1), ce.RE_LAYER_FILE.match(name).group(1))
        self.assertEqual(matte.RE_LAYER.match("ep01_s03_L4b_bac-thi_v01.png").group(1), "L4b")
        self.assertTrue(ce.RE_CLIP_FILE.match("ep01_s103_seedance25_v01.mp4"))
        self.assertTrue(ce.RE_START_FRAME.match("ep01_s103_start_v01.png"))
        self.assertTrue(ce.RE_CLIP_STEM.match("ep01_s103_seedance25_v01"))
        self.assertTrue(ce.STYLE_LAYER_KEY.match("L4b"))
        self.assertEqual(st.RE_SHOT.search("ep01_s103_L4_x_v01.png").group(1), "s103")
        self.assertTrue(ds.RE_SHOT_TAG.search("ep01_s103_L4_x_v01.png"))
        for bad in ("ep01_s1000_L4_x_v01.png", "ep01_s3_L4_x_v01.png", "ep01_s03_L4a_x_v01.png"):
            self.assertFalse(ce.RE_LAYER_FILE.match(bad), bad)
            self.assertFalse(anchors.RE_LAYER_FILE.match(bad), bad)


class TestToolsOnPosePlates(TmpDirCase, unittest.TestCase):
    def test_matte_pose_plate_uses_l4_settings(self):
        self.assertEqual(matte.style_key("L4b"), "L4")
        self.assertEqual(matte.style_settings(str(STYLE_FIX), "L4b"), matte.style_settings(str(STYLE_FIX), "L4"))

    def test_matte_own_pose_entry_wins(self):
        style = self.tmp / "styles" / "test-style"
        shutil.copytree(STYLE_FIX, style)
        y = style / "style.yaml"
        y.write_text(y.read_text(encoding="utf-8").replace(
            "    P:  {method: rembg, low: 60, high: 200}\n",
            "    P:  {method: rembg, low: 60, high: 200}\n    L4b: {method: chroma, low: 30, high: 220}\n", 1),
            encoding="utf-8")
        self.assertEqual(matte.style_settings(str(style), "L4b")["method"], "chroma")
        self.assertEqual(matte.style_settings(str(style), "L4c")["method"], "rembg")
        rep = ce.Report()
        ce.check_style(str(style), rep)
        self.assertEqual(rep.errors, 0, rep.lines)

    def test_anchors_takes_a_pose_plate_without_warning(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            anchors.set_point(str(self.tmp / "anchors.json"), "ep01_s103_L4b_bac-thi_v01.png", "feet", 10, 20)
        self.assertEqual(err.getvalue(), "")

    def test_bundle_shot_ids(self):
        with self.assertRaises(SystemExit) as cm:
            bundle.bundle(str(self.tmp / "nowhere"), "s1")
        self.assertIn("s<NN> or s<NNN>", str(cm.exception))
        with self.assertRaises(SystemExit) as cm:       # s103 passes the id check, then the folder is missing
            bundle.bundle(str(self.tmp / "nowhere"), "s103")
        self.assertIn("media folder not found", str(cm.exception))

    def test_bundle_three_digit_shot(self):
        media = self.tmp / "out" / "test-series" / "ep01"
        (media / "plates").mkdir(parents=True)
        for n in ("ep01_s103_L4b_bac-thi_v01.png", "ep01_s103_L1_nui_v01.png", "ep01_s010_L1_nui_v01.png"):
            (media / "plates" / n).write_bytes(b"x" * 10)
        code, out, err = run_main(bundle.main, [str(media), "--shot", "s103", "--series-dir", str(self.tmp)])
        self.assertEqual(code, 0, err)
        self.assertIn("files  2 media", out)


class EpisodeCase(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.ep = self.tmp / "projects" / "test-series" / "ep01-test-ep"
        shutil.copytree(EPISODE_FIX, self.ep)
        self.media = self.tmp / "out" / "test-series" / "ep01"
        for sub, names in (("plates", PLATES), ("clips", ["ep01_s02_seedance25_v01.mp4"]),
                           ("renders", ["ep01_draft_v01.mp4"])):
            (self.media / sub).mkdir(parents=True)
            for n in names:
                (self.media / sub / n).write_bytes(b"x")
        (self.media / "ledger.csv").write_text(",".join(ce.LEDGER_HEADER) + "\n")

    def check(self, *extra):
        return run_main(ce.main, ["episode", str(self.ep), "--media", str(self.media)] + list(extra))

    def edit(self, name, old, new, count=1):
        p = self.ep / name
        s = p.read_text(encoding="utf-8")
        self.assertIn(old, s, f"fixture text not found in {name}")
        p.write_text(s.replace(old, new, count), encoding="utf-8")

    def lines(self, out, kind):
        return [l for l in out.splitlines() if l.startswith(kind)]

    def assert_line(self, out, kind, pattern):
        self.assertTrue(any(re.search(pattern, l) for l in self.lines(out, kind)),
                        f"no {kind} matching {pattern!r} in:\n{out}")

    def set_method(self, value, style=None):
        s = (self.ep / "EPISODE.md").read_text(encoding="utf-8")
        s = re.sub(r"(?m)^method:.*$", f"method: {value}", s)
        if style:
            s = re.sub(r"(?m)^style: .*$", f"style: {style}", s)
        (self.ep / "EPISODE.md").write_text(s, encoding="utf-8")


class TestShotIds(EpisodeCase):
    def to_three_digits(self):
        for name in ("shots.csv", "prompts.csv"):
            p = self.ep / name
            p.write_text(re.sub(r"(?<![a-z0-9])s0(\d)(?![0-9])", r"s00\1", p.read_text(encoding="utf-8")),
                         encoding="utf-8")
        for sub in ("plates", "clips"):
            for f in (self.media / sub).iterdir():
                f.rename(f.with_name(f.name.replace("_s0", "_s00")))

    def test_three_digit_episode_passes(self):
        self.to_three_digits()
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("4 shot(s), 30 s", out)
        self.assertNotIn("orphan", out)
        self.assertEqual(self.lines(out, "WARN  media/plates"), [], out)

    def test_mixed_widths_are_an_error(self):
        self.edit("shots.csv", "s03,15", "s003,15")
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        self.assert_line(out, "ERROR", r"shots\.csv:4: shot id 's003' has 3 digits but the first shot has 2")

    def test_bad_ids(self):
        self.edit("shots.csv", "s03,15", "s3,15")
        code, out, _ = self.check()
        self.assert_line(out, "ERROR", r"shot id 's3' must be s<NN> \(s01-s99\) or s<NNN> \(s001-s999\)")

    def test_gap_and_order_messages_keep_the_width(self):
        self.to_three_digits()
        self.edit("shots.csv", "s004,24.5", "s006,24.5")
        code, out, _ = self.check()
        self.assert_line(out, "WARN", r"gap in shot ids: s006 after s003")
        self.edit("shots.csv", "s001,0", "s002,0")
        code, out, _ = self.check()
        self.assert_line(out, "WARN", r"first shot is s002, expected s001")


class TestPosePlates(EpisodeCase):
    def layers_episode(self):
        self.set_method("layers")
        self.edit("shots.csv", ",,slow blink,,", ",,,,")
        (self.ep / "budget.yaml").write_text("images: 40\nvideo_seconds: 0\nledger_required: true\n", encoding="utf-8")

    def add_pose(self):
        self.edit("shots.csv", "L1;L2;L4;P1-duoi,strip-warp", "L1;L2;L4;L4b;P1-duoi,strip-warp;pose-cycle")
        with open(self.ep / "prompts.csv", "a", encoding="utf-8") as f:
            f.write("ep01_s02_L4b_bac-thi_v01.png,s02,L4b,dola-seedream-5-0-flash-260915,2K,prompts/s02_L4.txt,,,"
                    "\"{\"\"generated_images\"\":1}\",,\n")
        (self.media / "plates" / "ep01_s02_L4b_bac-thi_v01.png").write_bytes(b"x")

    def test_layers_episode_with_pose_plate_passes(self):
        self.layers_episode()
        self.add_pose()
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("L4b", out)

    def test_pose_plate_in_seedance_episode_is_warn(self):
        self.add_pose()
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assert_line(out, "WARN", r"s02: pose plate L4b belongs to method layers")


class TestMethodCodeVocabulary(EpisodeCase):
    SHOTS = """shot,from_s,to_s,shot_size,camera,action,layers,code_motion,ai_motion,sound,reuse_of
s01,0,8,wide,track,Thú đi vào,M-ky-lan;E-doi-co,walk-cycle,,wind,
s02,8,15,medium,push-in,Thú vẫy đuôi,C-giot;E-doi-co;T,wave;mist-bands,,pop,
s03,15,24.5,close,orbit,Thú nhảy,M-ky-lan;E-doi-co;FX-bui,jump,,,
s04,24.5,30,wide,crane,Thú đi ra,M-ky-lan;E-doi-co,walk-cycle,,wind,
"""

    def setUp(self):
        super().setUp()
        (self.ep / "prompts.csv").unlink()
        shutil.rmtree(self.media / "plates")
        shutil.rmtree(self.media / "clips")
        (self.ep / "shots.csv").write_text(self.SHOTS, encoding="utf-8")
        (self.ep / "budget.yaml").write_text("images: 0\nvideo_seconds: 0\nledger_required: true\n", encoding="utf-8")
        self.set_method("code", style="hoat-hinh-phang")

    def test_model_ids_and_toon_motions_pass(self):
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.lines(out, "WARN  shots.csv"), [], out)

    def test_plate_rig_motion_warns_in_code(self):
        self.edit("shots.csv", "wave;mist-bands", "wave;cloth")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assert_line(out, "WARN", r"s02 code_motion 'cloth' rigs a painted plate")

    def test_toon_motion_warns_outside_code(self):
        self.set_method("layers", style="thuy-mac")
        code, out, _ = self.check()
        self.assert_line(out, "WARN", r"s01 code_motion 'walk-cycle' is a method code \(TOON\) action")

    def test_new_registry_ids_just_work(self):
        """A toon motion or camera move added to motions.json (toon-creatures) needs no checker change."""
        reg = dict(ce.motion_registry())
        reg["tail-fan"] = {"module": "toon/motion.js", "call": "TOON timeline clip", "engine": "toon"}
        reg["fly-through"] = {"module": "toon/project.js", "call": "TOON SHOT camera", "engine": "toon"}
        self.edit("shots.csv", "s03,15,24.5,close,orbit,Thú nhảy,M-ky-lan;E-doi-co;FX-bui,jump",
                  "s03,15,24.5,close,fly-through,Thú nhảy,M-ky-lan;E-doi-co;FX-bui,tail-fan")
        code, out, _ = self.check()
        self.assert_line(out, "ERROR", r"camera 'fly-through' is not one move")
        self.assert_line(out, "WARN", r"code_motion 'tail-fan' is not in tools/compose/motions.json")
        with mock.patch.object(ce, "motion_registry", lambda: reg):
            code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.lines(out, "WARN  shots.csv"), [], out)

    def test_bad_code_layer(self):
        self.edit("shots.csv", "M-ky-lan;E-doi-co,walk-cycle,,wind,\ns02", "X-ky-lan;E-doi-co,walk-cycle,,wind,\ns02")
        code, out, _ = self.check()
        self.assert_line(out, "ERROR", r"layer code 'X-ky-lan' invalid \(C-<character> or M-<model>")


class TestCoverage(EpisodeCase):
    """check-5: two approved versions, orphan plates, ai_motion without a clip from G3."""

    def test_two_approved_versions_is_error(self):
        with open(self.ep / "prompts.csv", "a", encoding="utf-8") as f:
            f.write("ep01_s01_L1_nui-co_v02.png,s01,L1,seedream-5-0-lite-260128,2K,prompts/s01_L1.txt,,,,yes,\n")
        (self.media / "plates" / "ep01_s01_L1_nui-co_v02.png").write_bytes(b"x")
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        self.assert_line(out, "ERROR", r"prompts\.csv: s01 L1: 2 approved images \(ep01_s01_L1_nui-co_v01\.png, "
                                       r"ep01_s01_L1_nui-co_v02\.png\)")

    def test_approved_plate_and_its_clip_are_fine(self):
        self.edit("prompts.csv", "prompts/s02_L4.txt,ep01_s01_L1_nui-co_v01.png,,,no,",
                  "prompts/s02_L4.txt,ep01_s01_L1_nui-co_v01.png,,,yes,")
        with open(self.ep / "prompts.csv", "a", encoding="utf-8") as f:
            f.write("ep01_s02_seedance25_v01.mp4,s02,L4,dreamina-seedance-2-5-260628,720p,prompts/s02_L4.txt,,,,yes,\n")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("approved", out)

    def test_orphan_plates_warn(self):
        (self.media / "plates" / "ep01_s01_L2_test_v01.png").write_bytes(b"x")
        (self.media / "plates" / "matte").mkdir()
        (self.media / "plates" / "matte" / "ep01_s01_L1_nui-co_v01.png").write_bytes(b"x")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        warns = self.lines(out, "WARN  media/plates")
        self.assertEqual(len(warns), 1, out)
        self.assertIn("1 file(s) with no prompts.csv row", warns[0])
        self.assertIn("ep01_s01_L2_test_v01.png", warns[0])

    def g3(self, stage=8):
        self.edit("EPISODE.md", "stage: 5", f"stage: {stage}")

    def test_ai_motion_without_clip_from_g3(self):
        code, out, _ = self.check()
        self.assertNotIn("no clip", out)               # stage 5: still to be made
        self.g3()
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        self.assert_line(out, "ERROR", r"shots\.csv:4: s03 has ai_motion 'slow blink' but no clip "
                                       r"<id>_s03_<model>_v<NN>\.mp4 .* at stage 8")

    def test_clip_present_passes_and_rejected_clip_does_not_count(self):
        self.g3()
        (self.media / "clips" / "ep01_s03_seedance25_v01.mp4").write_bytes(b"x")
        code, out, _ = self.check()
        self.assertNotIn("no clip", out)
        with open(self.ep / "prompts.csv", "a", encoding="utf-8") as f:
            f.write("ep01_s03_seedance25_v01.mp4,s03,L4,dreamina-seedance-2-5-260628,720p,prompts/s02_L4.txt,,,,no,\n")
        code, out, _ = self.check()
        self.assert_line(out, "ERROR", r"s03 has ai_motion 'slow blink' but no clip")

    def test_reused_shot_uses_the_clip_of_its_source(self):
        self.g3()
        self.edit("shots.csv", ",,slow blink,,", ",,slow blink,,s02")
        code, out, _ = self.check()
        self.assertNotIn("no clip", out)               # s02's clip is on disk

    def test_layers_episode_is_not_asked_for_clips(self):
        self.g3()
        self.set_method("layers")
        code, out, _ = self.check()
        self.assertNotIn("no clip", out)               # ai_motion is its own ERROR there


class TestBacklogItems(EpisodeCase):
    def test_duplicate_front_matter_key_is_error(self):
        self.edit("EPISODE.md", "stage: 5\n", "stage: 5\nmethod: layers\n")
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        self.assert_line(out, "ERROR", r"EPISODE\.md: front matter key 'method' given twice \(line 9\)")

    def test_duplicate_budget_key_is_error(self):
        (self.ep / "budget.yaml").write_text("images: 40\nvideo_seconds: 30\nimages: 400\nledger_required: true\n",
                                             encoding="utf-8")
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        self.assert_line(out, "ERROR", r"budget\.yaml: key 'images' given twice \(line 3\)")

    def test_yaml_merge_key_is_not_a_duplicate(self):
        data, dups = ce.yaml_load_dups("a: &x {k: 1}\nb:\n  <<: *x\n  k: 2\n")
        self.assertEqual(dups, [])
        self.assertEqual(data["b"], {"k": 2})

    def test_fence_inside_comment_does_not_hide_narration(self):
        lines = list(ce.narration_lines("<!--\n```\n-->\n[00:00] câu một\n"))
        self.assertEqual(lines, [(4, "[00:00] câu một")])
        lines = list(ce.narration_lines("```\n<!-- x\n```\n[00:03] câu hai\n"))
        self.assertEqual(lines, [(4, "[00:03] câu hai")])     # a comment start inside a fence is fence text

    def test_series_format_says_where_it_came_from(self):
        rep = ce.Report()
        self.assertEqual(ce.series_format(str(self.ep), rep), ce.DEFAULT_FORMAT)
        self.assertIn("INFO  probe: series format 1920x1080 at 24 fps (default: no SERIES.md", rep.lines[0])
        (self.ep.parent / "SERIES.md").write_text("---\nformat: [1, 2\n---\n", encoding="utf-8")
        rep = ce.Report()
        ce.series_format(str(self.ep), rep)
        self.assertRegex(rep.lines[0], r"default: SERIES\.md unreadable: ")
        (self.ep.parent / "SERIES.md").write_text("---\nseries: x\n---\n", encoding="utf-8")
        rep = ce.Report()
        ce.series_format(str(self.ep), rep)
        self.assertIn("default: format: missing", rep.lines[0])
        (self.ep.parent / "SERIES.md").write_text("---\nformat: {width: 1080, height: 1920, fps: 30}\n---\n",
                                                  encoding="utf-8")
        rep = ce.Report()
        self.assertEqual(ce.series_format(str(self.ep), rep), (1080, 1920, 30.0))
        self.assertEqual(rep.lines, ["INFO  probe: series format 1080x1920 at 30 fps (SERIES.md)"])

    def probe(self, duration):
        (self.media / "renders" / "ep01_final_v01.mp4").write_bytes(b"x")
        fake = {"width": 1920, "height": 1080, "fps": 24.0, "duration": duration, "audio": True}
        with mock.patch.object(ce.shutil, "which", lambda name: "/usr/bin/" + name), \
                mock.patch.object(ce, "ffprobe", lambda path: dict(fake)), \
                mock.patch.object(ce, "loudness", lambda path: (-14.0, -1.0)):
            return self.check("--probe")

    def test_final_without_duration_is_warn(self):
        code, out, _ = self.probe(None)
        self.assert_line(out, "WARN", r"media/renders/ep01_final_v01\.mp4: duration not checked: ffprobe reports "
                                      r"no duration")

    def test_final_without_length_s_is_warn(self):
        self.edit("EPISODE.md", "length_s: 30", "length_s: thirty")
        code, out, _ = self.probe(30.0)
        self.assert_line(out, "WARN", r"ep01_final_v01\.mp4: duration not checked: EPISODE\.md has no numeric length_s")

    def test_final_with_length_has_no_such_warn(self):
        code, out, _ = self.probe(30.0)
        self.assertNotIn("duration not checked", out)


class TestDocsAgree(unittest.TestCase):
    def test_report_name_is_check_v_n_everywhere(self):
        root = Path(ce.LAB)
        hits = []
        for p in list((root / ".claude").rglob("*.md")) + list((root / "docs").glob("*.md")) + [root / "tools" / "check_episode.py"]:
            if p.name in ("BACKLOG.md",) or "releases" in p.parts:
                continue
            if "check-<v>" in p.read_text(encoding="utf-8"):
                hits.append(str(p.relative_to(root)))
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
