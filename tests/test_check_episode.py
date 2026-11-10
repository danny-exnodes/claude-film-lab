"""tools/check_episode.py: a valid episode/style fixture passes; broken variants (made in tmp dirs) fail."""
import os, re, shutil, subprocess, tempfile, unittest
from pathlib import Path

from helpers import EPISODE_FIX, STYLE_FIX, TmpDirCase, load, run_main

ce = load("check_episode.py", "film_check_episode")

PLATES = ["ep01_s01_L1_nui-co_v01.png", "ep01_s02_L4_bac-thi_v02.png", "ep01_s02_P1-duoi_bac-thi_v01.png"]


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
        self.edit("EPISODE.md", 'drive: "ClaudeFilmLab/TestSeries/03_KichBan/ep01-test-ep"\n', "")
        self.assert_error(r"front matter key 'drive' missing")

    def test_fixture_drive_follows_convention(self):
        code, out, _ = self.check()
        self.assertNotIn("WARN  EPISODE.md: drive", out)

    def test_legacy_drive_path_is_warn(self):
        self.edit("EPISODE.md", 'drive: "ClaudeFilmLab/TestSeries/03_KichBan/ep01-test-ep"', 'drive: "AI Film Lab/test-series/ep01"')
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("drive 'AI Film Lab/test-series/ep01' differs from the convention "
                      "'ClaudeFilmLab/<ProjectName>/03_KichBan/ep01-test-ep'", out)

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
        (self.media / "plates" / PLATES[0]).unlink()            # row has approved=yes and usage
        self.assert_error(r"ep01_s01_L1_nui-co_v01.png listed but not found .*approved=yes")

    def test_pending_row_missing_is_info_before_stage_7(self):
        # rows are written at stage 3 before images exist: G2 (stage 4-5) must still pass
        for n in PLATES[1:]:
            (self.media / "plates" / n).unlink()                # approved=no / empty, no usage
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("INFO  prompts.csv: 2 file(s) not generated yet", out)
        self.assertIn(PLATES[1], out)

    def test_pending_row_missing_is_error_from_stage_7(self):
        (self.media / "plates" / PLATES[1]).unlink()
        self.edit("EPISODE.md", "stage: 5", "stage: 7")
        self.assert_error(r"ep01_s02_L4_bac-thi_v02.png listed but not found .*episode is at stage 7")

    def test_generated_row_missing_is_error(self):
        (self.media / "plates" / PLATES[2]).unlink()
        self.edit("prompts.csv", "prompts/s02_L4.txt,,,,,", 'prompts/s02_L4.txt,,,"{""generated_images"":1}",,')
        self.assert_error(r"ep01_s02_P1-duoi_bac-thi_v01.png listed but not found .*usage is filled")

    def test_clip_row(self):
        # seedance-layer.md: the clip is logged in prompts.csv with layer = L4
        row = 'ep01_s02_seedance25_v01.mp4,s02,L4,dreamina-seedance-2-5-260628,720p,,ep01_s02_start_v01.png,,"{""completion_tokens"":1}",,\n'
        with open(self.ep / "prompts.csv", "a", encoding="utf-8") as f:
            f.write(row)
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        (self.media / "clips" / "ep01_s02_seedance25_v01.mp4").unlink()
        self.assert_error(r"ep01_s02_seedance25_v01.mp4 listed but not found in .*clips")

    def test_clip_row_shot_mismatch(self):
        with open(self.ep / "prompts.csv", "a", encoding="utf-8") as f:
            f.write("ep01_s02_seedance25_v01.mp4,s03,L4,m,720p,,,,,,\n")
        self.assert_error(r"is for s02 but shot column is 's03'")


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

    def test_documented_clip_artefacts_pass(self):
        # CONVENTIONS §2 + film-compose-shot/references/seedance-layer.md
        clips = self.media / "clips"
        (clips / "ep01_s02_start_v01.png").write_bytes(b"x")
        stem = clips / "ep01_s02_seedance25_v01"
        (stem / "raw").mkdir(parents=True)
        for i in (1, 2, 120):
            (stem / f"{i:06d}.png").write_bytes(b"x")
            (stem / "raw" / f"{i:06d}.png").write_bytes(b"x")
        (self.media / "plates" / "matte").mkdir()
        (self.media / "plates" / "matte" / PLATES[1]).write_bytes(b"x")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("media/clips", out)

    def test_bad_clip_artefacts(self):
        clips = self.media / "clips"
        (clips / "ep01_s02_start.png").write_bytes(b"x")                   # no version
        (clips / "ep02_s01_start_v01.png").write_bytes(b"x")               # other episode
        (clips / "s02_frames").mkdir()
        (clips / "s02_frames" / "000001.png").write_bytes(b"x")            # folder is not a clip stem
        stem = clips / "ep01_s02_seedance25_v01"
        (stem / "keyed").mkdir(parents=True)
        (stem / "frame1.png").write_bytes(b"x")                            # not 6 digits
        (stem / "keyed" / "000001.png").write_bytes(b"x")                  # only raw/ allowed
        (clips / "ep02_s01_seedance25_v01").mkdir()
        (clips / "ep02_s01_seedance25_v01" / "000001.png").write_bytes(b"x")
        out = self.assert_error(r"media/clips/ep01_s02_start.png: name does not match")
        self.assertRegex(out, r"ERROR media/clips/ep02_s01_start_v01.png: file is not for episode ep01")
        self.assertRegex(out, r"ERROR media/clips/s02_frames/000001.png: frame folder 's02_frames'")
        self.assertRegex(out, r"ERROR media/clips/ep01_s02_seedance25_v01/frame1.png: frame folders hold only")
        self.assertRegex(out, r"ERROR media/clips/ep01_s02_seedance25_v01/keyed/000001.png: frame folders hold only")
        self.assertRegex(out, r"ERROR media/clips/ep02_s01_seedance25_v01/000001.png: file is not for episode ep01")


class TestEpisodeDot(EpisodeCase):
    def test_episode_dot(self):
        cwd = os.getcwd()
        os.chdir(self.ep)
        try:
            code, out, _ = run_main(ce.main, ["episode", ".", "--media", str(self.media)])
        finally:
            os.chdir(cwd)
        self.assertEqual(code, 0, out)
        self.assertNotIn("folder '.'", out)


def ffmpeg(out, size="160x90", seconds=1, audio_db=None):
    """Tiny test video (lavfi testsrc; optional 1 kHz sine: mono, 0 dB gain = -21 LUFS)."""
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=24:duration={seconds}"]
    if audio_db is not None:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=1000:duration={seconds}", "-af", f"volume={audio_db}dB",
                "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out)]
    subprocess.run(cmd, check=True, timeout=60)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe not installed")
class TestEpisodeProbe(EpisodeCase):
    @classmethod
    def setUpClass(cls):
        cls._vids = tempfile.mkdtemp(prefix="film-probe-")
        v = Path(cls._vids)
        ffmpeg(v / "clip.mp4", "160x90", 1)
        ffmpeg(v / "square.mp4", "96x96", 1)
        ffmpeg(v / "draft.mp4", "160x90", 2, audio_db=0)
        ffmpeg(v / "final_ok.mp4", "320x180", 2, audio_db=7.07)     # -14.0 LUFS
        ffmpeg(v / "final_quiet.mp4", "320x180", 2, audio_db=0)     # -21 LUFS
        ffmpeg(v / "final_43.mp4", "160x120", 2, audio_db=7.07)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._vids, ignore_errors=True)

    def put(self, src, rel):
        shutil.copy(Path(self._vids) / src, self.media / rel)

    def test_probe_numbers_in_report(self):
        self.put("clip.mp4", "clips/ep01_s02_seedance25_v01.mp4")
        self.put("draft.mp4", "renders/ep01_draft_v01.mp4")
        self.put("final_ok.mp4", "renders/ep01_final_v01.mp4")
        code, out, _ = self.check("--probe", "--out", "review/check-v1.txt")
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"INFO  probe media/clips/ep01_s02_seedance25_v01.mp4: 160x90 \(16:9\), 24 fps, 1.0\d s, audio no")
        self.assertRegex(out, r"INFO  probe media/renders/ep01_final_v01.mp4: 320x180 \(16:9\), 24 fps, "
                              r"2.0\d s \(length_s 30 s, -2[78].\d\d s\), audio yes, "
                              r"integrated -1[34].\d LUFS, true peak -?\d+.\d dBTP")
        self.assertRegex(out, r"WARN  media/renders/ep01_draft_v01.mp4: duration .* differs from length_s 30 s")
        rep = (self.ep / "review" / "check-v1.txt").read_text()
        self.assertIn("integrated", rep)
        self.assertIn("160x90 (16:9)", rep)

    def test_probe_errors(self):
        self.put("square.mp4", "clips/ep01_s02_seedance25_v01.mp4")
        self.put("final_quiet.mp4", "renders/ep01_final_v01.mp4")
        self.put("final_43.mp4", "renders/ep01_final_v02.mp4")
        self.put("clip.mp4", "renders/ep01_final_v03.mp4")          # no audio
        (self.media / "renders" / "ep01_draft_v01.mp4").write_bytes(b"not a video")
        code, out, _ = self.check("--probe")
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"WARN  media/clips/ep01_s02_seedance25_v01.mp4: 96x96 is not 16:9")
        self.assertRegex(out, r"ERROR media/renders/ep01_final_v01.mp4: integrated loudness -2[01].\d LUFS outside -14 \+-1")
        self.assertRegex(out, r"ERROR media/renders/ep01_final_v02.mp4: 160x120 is not 16:9")
        self.assertRegex(out, r"ERROR media/renders/ep01_final_v03.mp4: final render has no audio")
        self.assertRegex(out, r"ERROR media/renders/ep01_draft_v01.mp4: ffprobe failed")

    def test_without_probe_measures_nothing(self):
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("probe", out)


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
