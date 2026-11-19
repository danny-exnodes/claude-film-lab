"""tools/check_episode.py: a valid episode/style fixture passes; broken variants (made in tmp dirs) fail."""
import os, re, shutil, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock

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
        self.assertIn("INFO  prompts.csv: 1 file(s) not generated yet", out)
        self.assertIn(PLATES[2], out)
        self.assertIn(f"INFO  prompts.csv: 1 rejected file(s) not on disk (approved=no): {PLATES[1]}", out)

    def test_pending_row_missing_is_error_from_stage_7(self):
        (self.media / "plates" / PLATES[2]).unlink()            # approved empty, no usage
        self.edit("EPISODE.md", "stage: 5", "stage: 7")
        self.assert_error(r"ep01_s02_P1-duoi_bac-thi_v01.png listed but not found .*episode is at stage 7")

    def test_rejected_row_missing_is_info_at_stage_7(self):
        # a rejected plate that is gone must not block the later gates (its row is the only record of it)
        (self.media / "plates" / PLATES[1]).unlink()            # approved=no
        self.edit("EPISODE.md", "stage: 5", "stage: 7")
        self.edit("prompts.csv", "ep01_s01_L1_nui-co_v01.png,,,no,", 'ep01_s01_L1_nui-co_v01.png,,"{""generated_images"":1}",no,')
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("INFO  prompts.csv: 1 rejected file(s) not on disk", out)
        self.assertNotIn("listed but not found", out)

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


def ffmpeg(out, size="160x90", seconds=1, audio_db=None, src="testsrc"):
    """Tiny test video (lavfi testsrc, or a flat colour for big frames; optional 1 kHz sine: mono, 0 dB gain = -21 LUFS)."""
    video = f"color=c=gray:size={size}:rate=24:duration={seconds}" if src == "color" else \
        f"testsrc=size={size}:rate=24:duration={seconds}"
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", video]
    if audio_db is not None:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=1000:duration={seconds}", "-af", f"volume={audio_db}dB",
                "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out)]
    subprocess.run(cmd, check=True, timeout=120)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe not installed")
class TestEpisodeProbe(EpisodeCase):
    @classmethod
    def setUpClass(cls):
        cls._vids = tempfile.mkdtemp(prefix="film-probe-")
        v = Path(cls._vids)
        ffmpeg(v / "clip.mp4", "160x90", 1)
        ffmpeg(v / "square.mp4", "96x96", 1)
        ffmpeg(v / "draft.mp4", "160x90", 2, audio_db=0)
        ffmpeg(v / "draft_ok.mp4", "960x540", 30, audio_db=0, src="color")
        ffmpeg(v / "draft_silent.mp4", "960x540", 30, src="color")
        ffmpeg(v / "final_ok.mp4", "1920x1080", 30, audio_db=7.07, src="color")      # -14.0 LUFS, the fixture's length_s
        ffmpeg(v / "final_quiet.mp4", "1920x1080", 30, audio_db=0, src="color")      # -21 LUFS
        ffmpeg(v / "final_silent.mp4", "1920x1080", 30, src="color")
        ffmpeg(v / "final_12s.mp4", "1920x1080", 12, audio_db=7.07, src="color")
        ffmpeg(v / "final_small.mp4", "320x180", 30, audio_db=7.07, src="color")
        ffmpeg(v / "final_43.mp4", "160x120", 30, audio_db=7.07, src="color")
        ffmpeg(v / "final_vertical.mp4", "1080x1920", 30, audio_db=7.07, src="color")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._vids, ignore_errors=True)

    def setUp(self):
        super().setUp()                                   # the placeholder mp4 files are not videos:
        self.put("clip.mp4", "clips/ep01_s02_seedance25_v01.mp4")
        self.put("draft_ok.mp4", "renders/ep01_draft_v01.mp4")

    def put(self, src, rel):
        shutil.copy(Path(self._vids) / src, self.media / rel)

    def test_probe_numbers_in_report(self):
        self.put("clip.mp4", "clips/ep01_s02_seedance25_v01.mp4")
        self.put("draft.mp4", "renders/ep01_draft_v01.mp4")
        self.put("final_ok.mp4", "renders/ep01_final_v01.mp4")
        code, out, _ = self.check("--probe", "--out", "review/check-v1.txt")
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"INFO  probe media/clips/ep01_s02_seedance25_v01.mp4: 160x90 \(16:9\), 24 fps, 1.0\d s, audio no")
        self.assertRegex(out, r"INFO  probe media/renders/ep01_final_v01.mp4: 1920x1080 \(16:9\), 24 fps, "
                              r"30.0\d s \(length_s 30 s, [+-]0.0\d s\), audio yes, "
                              r"integrated -1[34].\d LUFS, true peak -?\d+.\d dBTP")
        self.assertRegex(out, r"WARN  media/renders/ep01_draft_v01.mp4: duration .* differs from length_s 30 s")
        self.assertRegex(out, r"WARN  media/renders/ep01_draft_v01.mp4: 160x90 is not the draft size 960x540")
        rep = (self.ep / "review" / "check-v1.txt").read_text()
        self.assertIn("integrated", rep)
        self.assertIn("160x90 (16:9)", rep)

    def test_good_draft_and_final_have_no_findings(self):
        self.put("draft_ok.mp4", "renders/ep01_draft_v01.mp4")
        self.put("final_ok.mp4", "renders/ep01_final_v01.mp4")
        code, out, _ = self.check("--probe")
        self.assertEqual(code, 0, out)
        self.assertNotRegex(out, r"(WARN|ERROR)\s+media/renders")

    def test_probe_errors(self):
        # the newest final (v03) is judged; a broken draft and an odd clip are still reported
        self.put("square.mp4", "clips/ep01_s02_seedance25_v01.mp4")
        self.put("final_quiet.mp4", "renders/ep01_final_v01.mp4")
        self.put("final_43.mp4", "renders/ep01_final_v02.mp4")
        self.put("final_silent.mp4", "renders/ep01_final_v03.mp4")
        (self.media / "renders" / "ep01_draft_v01.mp4").write_bytes(b"not a video")
        code, out, _ = self.check("--probe")
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"WARN  media/clips/ep01_s02_seedance25_v01.mp4: 96x96 is not 16:9")
        self.assertRegex(out, r"ERROR media/renders/ep01_final_v03.mp4: final render has no audio")
        self.assertRegex(out, r"ERROR media/renders/ep01_draft_v01.mp4: ffprobe failed")
        for old in ("v01", "v02"):
            self.assertRegex(out, rf"INFO  probe media/renders/ep01_final_{old}.mp4: superseded by v03, not measured")
            self.assertNotRegex(out, rf"(ERROR|WARN)\s+media/renders/ep01_final_{old}.mp4")

    def test_newest_final_loudness(self):
        self.put("final_ok.mp4", "renders/ep01_final_v01.mp4")
        self.put("final_quiet.mp4", "renders/ep01_final_v02.mp4")
        code, out, _ = self.check("--probe")
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"ERROR media/renders/ep01_final_v02.mp4: integrated loudness -2[01].\d LUFS outside -14 \+-1")

    def test_superseded_bad_final_does_not_block(self):
        self.put("draft_ok.mp4", "renders/ep01_draft_v01.mp4")
        self.put("final_quiet.mp4", "renders/ep01_final_v01.mp4")      # -21 LUFS, kept on disk by convention
        self.put("final_ok.mp4", "renders/ep01_final_v02.mp4")
        code, out, _ = self.check("--probe")
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"INFO  probe media/renders/ep01_final_v01.mp4: superseded by v02")
        self.assertNotIn("-21", out)

    def test_superseded_draft_is_not_measured(self):
        (self.media / "renders" / "ep01_draft_v01.mp4").write_bytes(b"not a video")
        self.put("draft_ok.mp4", "renders/ep01_draft_v02.mp4")
        code, out, _ = self.check("--probe")
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"INFO  probe media/renders/ep01_draft_v01.mp4: superseded by v02")

    def test_newest_final_wrong_size(self):
        self.put("final_small.mp4", "renders/ep01_final_v01.mp4")
        code, out, _ = self.check("--probe")
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"ERROR media/renders/ep01_final_v01.mp4: 320x180 at 24 fps is not the series format 1920x1080 at 24 fps")

    def test_newest_final_not_16_9(self):
        self.put("final_43.mp4", "renders/ep01_final_v01.mp4")
        code, out, _ = self.check("--probe")
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"ERROR media/renders/ep01_final_v01.mp4: 160x120 at 24 fps is not the series format")

    def test_final_fps_just_off_shows_the_difference(self):
        self.put("final_ok.mp4", "renders/ep01_final_v01.mp4")
        real = ce.ffprobe
        with mock.patch.object(ce, "ffprobe", lambda path: dict(real(path), fps=24000 / 1001)):
            code, out, _ = self.check("--probe")
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"ERROR media/renders/ep01_final_v01.mp4: 1920x1080 at 23.976 fps is not the series "
                              r"format 1920x1080 at 24 fps")

    def test_final_duration_is_error(self):
        self.put("final_12s.mp4", "renders/ep01_final_v01.mp4")
        code, out, _ = self.check("--probe")
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"ERROR media/renders/ep01_final_v01.mp4: duration 12.0\d s differs from length_s 30 s by -1[78].\d\d s")

    def test_silent_draft_is_warn(self):
        self.put("draft_silent.mp4", "renders/ep01_draft_v01.mp4")
        code, out, _ = self.check("--probe")
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"WARN  media/renders/ep01_draft_v01.mp4: draft render has no audio")

    def test_series_format_vertical(self):
        (self.ep.parent / "SERIES.md").write_text(
            "---\nseries: test-series\nformat: {width: 1080, height: 1920, fps: 24}\n---\n# Test\n", encoding="utf-8")
        self.put("final_vertical.mp4", "renders/ep01_final_v01.mp4")
        code, out, _ = self.check("--probe")
        self.assertEqual(code, 0, out)
        self.assertNotRegex(out, r"(WARN|ERROR)\s+media/renders/ep01_final_v01.mp4")
        self.put("final_ok.mp4", "renders/ep01_final_v02.mp4")       # 1920x1080 is now the wrong size
        code, out, _ = self.check("--probe")
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"ERROR media/renders/ep01_final_v02.mp4: 1920x1080 at 24 fps is not the series format 1080x1920")

    def test_unreadable_series_md_falls_back_to_default_format(self):
        (self.ep.parent / "SERIES.md").write_text("---\nformat: [1, 2\n---\n", encoding="utf-8")
        self.put("final_ok.mp4", "renders/ep01_final_v01.mp4")
        code, out, _ = self.check("--probe")
        self.assertEqual(code, 0, out)

    def test_without_probe_measures_nothing(self):
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("probe", out)


class TestEpisodeBudget(EpisodeCase):
    def budget(self, text):
        (self.ep / "budget.yaml").write_text(text, encoding="utf-8")

    def test_fixture_budget_is_valid(self):
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("budget.yaml", out)

    def test_template_budget_is_valid(self):
        shutil.copy(ce.LAB + "/templates/episode/budget.yaml", self.ep / "budget.yaml")
        self.edit("EPISODE.md", "stage: 5", "stage: 3")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("budget.yaml", out)

    def test_typo_key(self):
        self.budget("imagez: 40\nvideo_seconds: 30\n")
        out = self.assert_error(r"budget.yaml: unknown key imagez \(a misspelled cap is no cap\)")
        self.assertRegex(out, r"ERROR budget.yaml: required key 'images' missing")

    def test_string_cap(self):
        self.budget('images: "40"\nvideo_seconds: lots\n')
        out = self.assert_error(r"budget.yaml: images = '40' must be a number >= 0")
        self.assertRegex(out, r"ERROR budget.yaml: video_seconds = 'lots' must be a number >= 0")

    def test_negative_bool_and_nan_caps(self):
        self.budget("images: -4\nvideo_seconds: true\n")
        out = self.assert_error(r"budget.yaml: images = -4 must be a number >= 0")
        self.assertRegex(out, r"ERROR budget.yaml: video_seconds = True must be a number >= 0")
        self.budget("images: .nan\nvideo_seconds: .inf\n")
        out = self.assert_error(r"budget.yaml: images = nan must be a number >= 0")
        self.assertRegex(out, r"ERROR budget.yaml: video_seconds = inf must be a number >= 0")

    def test_empty_file(self):
        self.budget("")
        out = self.assert_error(r"budget.yaml: required key 'images' missing")
        self.assertRegex(out, r"ERROR budget.yaml: required key 'video_seconds' missing")

    def test_missing_file_is_error_even_at_stage_0(self):
        (self.ep / "budget.yaml").unlink()
        self.assert_error(r"budget.yaml: missing")
        self.edit("EPISODE.md", "stage: 5", "stage: 0")
        self.assert_error(r"budget.yaml: missing")

    def test_not_a_mapping_and_invalid_yaml(self):
        self.budget("- images\n- 40\n")
        self.assert_error(r"budget.yaml: must be a mapping")
        self.budget("images: [40\n")
        self.assert_error(r"budget.yaml: not valid YAML")
        (self.ep / "budget.yaml").write_bytes(b"images: 40\nvideo_seconds: 30 # tr\xe2n\n")
        self.assert_error(r"budget.yaml: not valid UTF-8")

    def test_models(self):
        self.budget("images: 40\nvideo_seconds: 30\nmodels: [a, b]\n")
        self.assert_error(r"budget.yaml: models must be a mapping model id -> number >= 0")
        self.budget("images: 40\nvideo_seconds: 30\nmodels: {pro: six, lite: -1, ok: 3}\n")
        out = self.assert_error(r"budget.yaml: models.pro = 'six' must be a number >= 0")
        self.assertRegex(out, r"ERROR budget.yaml: models.lite = -1 must be a number >= 0")
        self.assertNotIn("models.ok", out)
        self.budget("images: 40\nvideo_seconds: 30\nmodels:\n")          # key with nothing under it: same as absent
        code, out, _ = self.check()
        self.assertNotIn("ERROR budget.yaml", out)

    def test_ledger_required(self):
        self.budget("images: 40\nvideo_seconds: 30\nledger_required: yes please\n")
        self.assert_error(r"budget.yaml: ledger_required = 'yes please' must be true or false")
        self.budget("images: 40\nvideo_seconds: 30\nledger_required: false\n")
        self.edit("EPISODE.md", "stage: 5", "stage: 4")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"WARN  budget.yaml: ledger_required is not true at stage 4")
        self.budget("images: 40\nvideo_seconds: 30\n")                    # absent = not true
        code, out, _ = self.check()
        self.assertRegex(out, r"WARN  budget.yaml: ledger_required is not true at stage 4")
        self.edit("EPISODE.md", "stage: 4", "stage: 3")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("ledger_required", out)


class TestEpisodeMethod(EpisodeCase):
    """EPISODE.md `method: layers | seedance` (docs/CONVENTIONS.md §5): layers never uses Seedance."""
    WARN = "WARN  EPISODE.md: EPISODE.md has no method: (treated as seedance); add method: layers, seedance or code"

    def method(self, value):
        s = (self.ep / "EPISODE.md").read_text(encoding="utf-8")
        s = re.sub(r"(?m)^method:.*\n", "", s)
        if value is not None:
            s = s.replace("stage: 5\n", f"method: {value}\nstage: 5\n", 1)
        (self.ep / "EPISODE.md").write_text(s, encoding="utf-8")

    def layers_clean(self, value="layers"):
        self.method(value)
        self.edit("shots.csv", ",,slow blink,,", ",breathe-test-id,,,")
        (self.ep / "budget.yaml").write_text("images: 40\nvideo_seconds: 0\nledger_required: true\n", encoding="utf-8")

    def test_helper(self):
        self.assertEqual(ce.episode_method({}), ("seedance", False))
        self.assertEqual(ce.episode_method({"method": "seedance"}), ("seedance", True))
        self.assertEqual(ce.episode_method({"method": "  LAYERS "}), ("layers", True))
        for bad in ("layer", "", None, 3, ["layers"], True):
            self.assertEqual(ce.episode_method({"method": bad}), (None, True), bad)

    def test_missing_key_is_one_warn_and_no_error(self):
        self.method(None)
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count(self.WARN), 1, out)
        self.assertEqual(out.count("method"), 2, out)      # that one line only: s03 keeps its ai_motion

    def test_fixture_states_its_method(self):
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("method", out)

    def test_seedance_explicit_with_ai_motion_passes(self):
        self.method("seedance")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("method", out)

    def test_layers_with_ai_motion_is_error(self):
        self.layers_clean()
        self.edit("shots.csv", ",breathe-test-id,,,", ",,slow blink,,")
        self.edit("shots.csv", "strip-warp,,drum", "strip-warp,  ,drum")       # blank ai_motion is empty
        out = self.assert_error(r"shots\.csv:4: method layers: shot s03 has ai_motion; use code_motion or pose-cycle, "
                                r"or set method: seedance$")
        self.assertEqual(out.count("has ai_motion"), 1, out)

    def test_layers_with_video_seconds_is_error(self):
        self.layers_clean()
        (self.ep / "budget.yaml").write_text("images: 40\nvideo_seconds: 30\nledger_required: true\n", encoding="utf-8")
        out = self.assert_error(r"budget\.yaml: method layers: video_seconds = 30 must be 0")
        self.assertEqual(out.count("ERROR"), 1, out)

    def test_layers_with_seedance_model_cap_is_error(self):
        self.layers_clean()
        (self.ep / "budget.yaml").write_text(
            "images: 40\nvideo_seconds: 0\nledger_required: true\n"
            "models: {dola-SeeDance-2-0: 10, seedance-zero: 0, dola-seedream-5-0-pro: 6}\n", encoding="utf-8")
        out = self.assert_error(r"budget\.yaml: method layers: models\.dola-SeeDance-2-0 = 10 must be 0")
        self.assertEqual(out.count("ERROR"), 1, out)       # a 0 cap and an image model are fine

    def test_layers_clean_passes(self):
        self.layers_clean()
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("method", out)

    def test_layers_budget_without_video_seconds_adds_no_method_error(self):
        self.layers_clean()
        (self.ep / "budget.yaml").write_text("images: 40\nledger_required: true\n", encoding="utf-8")
        code, out, _ = self.check()
        self.assertNotIn("method layers", out)

    def test_invalid_value_is_error(self):
        for bad in ("layer", "both", "", "[layers]"):
            with self.subTest(value=bad):
                self.method(bad)
                out = self.assert_error(r"EPISODE\.md: method must be layers, seedance or code")
                self.assertNotIn("method layers", out)      # no layers rule is applied on an invalid value
                self.assertNotIn("has no method", out)

    def test_case_and_whitespace_tolerant(self):
        self.layers_clean('"  Layers "')
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.method("LAYERS   # comment")
        self.edit("shots.csv", ",breathe-test-id,,,", ",,slow blink,,")
        self.assert_error(r"method layers: shot s03 has ai_motion")
        self.method(" SeeDance")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("method", out)

    def test_broken_front_matter_does_not_add_the_warn(self):
        self.edit("EPISODE.md", "series: test-series", "series: [test-series")
        code, out, _ = self.check()
        self.assertNotIn("has no method", out)

    def test_episode_template_says_layers(self):
        fm, _ = ce.split_front_matter(Path(ce.LAB, "templates/episode/EPISODE.md").read_text(encoding="utf-8"))
        import yaml
        self.assertEqual(ce.episode_method(yaml.safe_load(fm)), ("layers", True))

    def test_templates_pass_together(self):
        """EPISODE.md + budget.yaml copied from templates/episode must not contradict each other."""
        shutil.copy(ce.LAB + "/templates/episode/budget.yaml", self.ep / "budget.yaml")
        self.method("layers")
        self.edit("shots.csv", ",,slow blink,,", ",,,,")
        self.edit("EPISODE.md", "stage: 5", "stage: 3")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("budget.yaml", out)


class TestEpisodeStageGates(EpisodeCase):
    def gates(self, stage, g1="null", g2="null", g3="null", g4="null"):
        self.edit("EPISODE.md", "stage: 5", f"stage: {stage}")
        self.edit("EPISODE.md", "gates: {G1: 2026-11-01, G2: 2026-11-05, G3: null, G4: null}",
                  f"gates: {{G1: {g1}, G2: {g2}, G3: {g3}, G4: {g4}}}")

    def test_fixture_has_no_gate_finding(self):
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("gate", out.lower())

    def test_stage_10_with_g1_null(self):
        self.gates(10, "null", "2026-11-05", "2026-11-08")
        out = self.assert_error(r"EPISODE.md: stage 10 is past gate G1 \(stage 2\) but gates.G1 is null")
        self.assertEqual(len([l for l in out.splitlines() if "G1" in l and l.startswith("ERROR")]), 1, out)

    def test_stage_5_with_g2_null(self):
        self.gates(5, "2026-11-01")
        self.assert_error(r"EPISODE.md: stage 5 is past gate G2 \(stage 4\) but gates.G2 is null")

    def test_stage_at_the_gate_is_fine(self):
        self.gates(4, "2026-11-01")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("ERROR", out)

    def test_later_gate_dated_while_earlier_null(self):
        self.gates(2, "null", "2026-11-05")
        self.assert_error(r"EPISODE.md: gates.G2 is dated but the earlier gate G1 is null")

    def test_decreasing_dates(self):
        self.gates(5, "2026-11-05", "2026-11-01")
        self.assert_error(r"EPISODE.md: gates.G2 2026-11-01 is before gates.G1 2026-11-05")

    def test_future_date_is_warn(self):
        self.gates(5, "2026-11-01", "2099-01-01")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"WARN  EPISODE.md: gates.G2 2099-01-01 is in the future")

    def test_quoted_impossible_date(self):
        self.gates(5, "2026-11-01", '"2026-11-31"')
        self.assert_error(r"EPISODE.md: gates.G2 = '2026-11-31' is not a calendar date")

    def test_unusable_stage_or_gates_is_skipped(self):
        self.edit("EPISODE.md", "gates: {G1: 2026-11-01, G2: 2026-11-05, G3: null, G4: null}", "gates: [G1]")
        out = self.assert_error(r"gates must be a mapping")
        self.assertEqual(out.count("ERROR"), 1, out)

    def test_no_shots_below_stage_3_is_warn(self):
        # a freshly filled template: header-only shots.csv, no prompts.csv yet
        self.gates(0)
        (self.ep / "shots.csv").write_text(",".join(ce.SHOTS_HEADER) + "\n", encoding="utf-8")
        (self.ep / "prompts.csv").unlink()
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("WARN  shots.csv: no shots", out)

    def test_no_shots_from_stage_3_is_error(self):
        self.gates(3, "2026-11-01")
        (self.ep / "shots.csv").write_text(",".join(ce.SHOTS_HEADER) + "\n", encoding="utf-8")
        (self.ep / "prompts.csv").unlink()
        self.assert_error(r"shots.csv: no shots")


class TestEpisodeMediaMissing(EpisodeCase):
    def test_folder_missing_at_stage_8_is_error(self):
        shutil.rmtree(self.media)
        self.edit("EPISODE.md", "stage: 5", "stage: 8")
        out = self.assert_error(r"media: media folder missing but 2 approved/generated file\(s\) are required: "
                                r"pull the shot bundles from Drive \(drive_link\)")
        self.assertRegex(out, r"WARN  media: media folder .* not found")

    def test_folder_missing_at_stage_5_is_info_with_count(self):
        shutil.rmtree(self.media)
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"INFO  media: 1 approved/generated file\(s\) of prompts.csv not checked")

    def test_folder_missing_with_only_rejected_rows_at_stage_8(self):
        shutil.rmtree(self.media)
        self.edit("EPISODE.md", "stage: 5", "stage: 8")
        rows = (self.ep / "prompts.csv").read_text(encoding="utf-8").splitlines()
        (self.ep / "prompts.csv").write_text("\n".join([rows[0], rows[2]]) + "\n", encoding="utf-8")   # approved=no only
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)

    def test_required_rows(self):
        rows = [{"file": "a", "approved": "yes", "usage": ""}, {"file": "b", "approved": "", "usage": "{}"},
                {"file": "c", "approved": "no", "usage": "{}"}, {"file": "d", "approved": "", "usage": ""}]
        self.assertEqual([r["file"] for r in ce.required_rows(rows, 5)], ["a", "b"])
        self.assertEqual([r["file"] for r in ce.required_rows(rows, 7)], ["a", "b", "d"])
        self.assertEqual([r["file"] for r in ce.required_rows(rows, None)], ["a", "b"])
        self.assertEqual(ce.required_rows(None, 9), [])


class TestNarrationLines(EpisodeCase):
    def lines(self, text):
        return list(ce.narration_lines(text))

    def test_comment_then_mark_on_one_line(self):
        got = self.lines("# T\n<!-- sửa 11/10 --> [00:05] Trên núi có loài thú lạ.\n")
        self.assertEqual([n for n, _ in got], [2])
        m = ce.RE_MARK.match(got[0][1])
        self.assertEqual(m.group(3).strip(), "Trên núi có loài thú lạ.")

    def test_trailing_comment_removed(self):
        got = self.lines("[00:26] Hết. <!-- đọc chậm -->\n")
        self.assertEqual(ce.RE_MARK.match(got[0][1]).group(3).strip(), "Hết.")

    def test_comment_only_line_and_multi_line_comment(self):
        got = self.lines("<!-- a --> <!-- b -->\n[00:00] Một.\n<!-- mở\n[00:03] trong chú thích\nđóng --> [00:06] Hai.\n"
                         "[00:09] Ba. <!-- mở tiếp\nvẫn chú thích -->\n[00:12] Bốn.\n")
        self.assertEqual([(n, ce.RE_MARK.match(l).group(3).strip()) for n, l in got],
                         [(2, "Một."), (5, "Hai."), (6, "Ba."), (8, "Bốn.")])

    def test_untouched_lines_keep_their_text(self):
        text = (self.ep / "script.md").read_text(encoding="utf-8")
        for n, line in self.lines(text):
            self.assertEqual(line, text.splitlines()[n - 1])

    def test_checker_sees_the_line_after_a_comment(self):
        self.edit("script.md", "[00:05] Trên núi", "<!-- sửa --> [00:02] Trên núi")
        self.assert_error(r"script.md:5: only 2 s after the previous line")

    def test_tts_gets_the_same_lines(self):
        import sys
        sys.path.insert(0, ce.LAB + "/tools")
        tts = load("tts/vieneu_tts.py", "film_vieneu_tts_narr")
        self.edit("script.md", "[00:05] Trên núi", "<!-- sửa 11/10 --> [00:05] Trên núi")
        self.edit("script.md", "[00:26] Hết.", "[00:26] Hết. <!-- đọc chậm -->")
        got = tts.parse_script((self.ep / "script.md").read_text(encoding="utf-8"))
        self.assertEqual(len(got), 5)
        self.assertEqual(got[1]["text"], "Trên núi có loài thú lạ.")
        self.assertEqual(got[4]["text"], "Hết.")

    def test_double_hyphen_in_narration_is_error(self):
        self.edit("script.md", "loài thú lạ.", "loài thú -- lạ.")
        self.assert_error(r"script.md:5: double hyphen '--' in narration")

    def test_double_hyphen_in_blockquote_is_warn(self):
        self.edit("script.md", "nhịp chậm – không", "nhịp chậm -- không")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"WARN  script.md:9: double hyphen '--' outside narration")

    def test_rules_comments_and_front_matter_are_not_double_hyphens(self):
        self.edit("script.md", "# Lời bình tập 1\n", "---\ntitle: x -- y\n---\n# Lời bình tập 1\n\n-----\n")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("double hyphen", out)

    def test_cjk_in_narration_is_warn(self):
        self.edit("script.md", "Người xưa gọi nó là Bắc Thị.", "Người xưa gọi nó là 猼訑.")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"WARN  script.md:11: not speakable: .*CJK")

    def test_markup_in_narration_is_warn(self):
        for bad, what in (("a | b", r"\|"), ("`code`", "`"), ("[link](http://x.y)", r"\]\("), ("<b>đậm</b>", "<")):
            with self.subTest(bad=bad):
                p = self.ep / "script.md"
                keep = p.read_text(encoding="utf-8")
                self.edit("script.md", "Người xưa gọi nó là Bắc Thị.", f"Người xưa gọi {bad}.")
                code, out, _ = self.check()
                self.assertEqual(code, 0, out)
                self.assertRegex(out, rf"WARN  script.md:11: not speakable: .*{what}")
                p.write_text(keep, encoding="utf-8")


class TestEpisodeNoCrash(EpisodeCase):
    """Malformed input gives an ERROR line and a written report, never a traceback."""
    OUT = "review/check-v9.txt"

    def assert_reported(self, pattern, *extra):
        code, out, err = self.check("--out", self.OUT, *extra)
        self.assertEqual(code, 1, out)
        self.assertNotIn("Traceback", err + out)
        self.assertTrue(any(l.startswith("ERROR") and re.search(pattern, l) for l in out.splitlines()),
                        f"no ERROR matching {pattern!r} in:\n{out}")
        rep = self.ep / self.OUT
        self.assertTrue(rep.is_file(), "report file not written")
        self.assertRegex(rep.read_text(encoding="utf-8"), pattern)
        self.assertIn("Summary:", rep.read_text(encoding="utf-8"))
        return out

    def corrupt(self, path):
        path.write_bytes(path.read_bytes().replace(b"\n", b" \xff\xfe\n", 1))

    def test_non_utf8_episode_md(self):
        self.corrupt(self.ep / "EPISODE.md")
        self.assert_reported(r"EPISODE.md: not valid UTF-8")

    def test_non_utf8_script_md(self):
        self.corrupt(self.ep / "script.md")
        out = self.assert_reported(r"script.md: not valid UTF-8")
        self.assertIn("4 shot(s), 30 s", out)            # the other checks still ran

    def test_non_utf8_csv(self):
        self.corrupt(self.ep / "shots.csv")
        self.assert_reported(r"shots.csv: not valid RFC 4180 UTF-8 CSV")

    def test_utf16_ledger(self):
        (self.media / "ledger.csv").write_text(",".join(ce.LEDGER_HEADER) + "\n", encoding="utf-16")
        self.assert_reported(r"media/ledger.csv: not valid UTF-8")

    def test_ledger_with_bom_is_fine(self):
        (self.media / "ledger.csv").write_text(",".join(ce.LEDGER_HEADER) + "\n", encoding="utf-8-sig")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("ledger.csv", out)

    def test_bad_ledger_header_still_reported(self):
        (self.media / "ledger.csv").write_text("ts,kind\n", encoding="utf-8")
        self.assert_reported(r"media/ledger.csv: header is 'ts,kind'")

    def test_impossible_gate_date(self):
        self.edit("EPISODE.md", "G1: 2026-11-01", "G1: 2026-11-31")
        self.assert_reported(r"EPISODE.md: front matter is not valid YAML: day is out of range for month")

    def test_nan_and_inf_timings_rejected(self):
        self.edit("shots.csv", "s02,8,15", "s02,8,nan")
        self.assert_reported(r"shots.csv:3: from_s/to_s must be numbers \(got '8', 'nan'\)")
        self.edit("shots.csv", "s02,8,nan", "s02,8,inf")
        self.assert_reported(r"shots.csv:3: from_s/to_s must be numbers \(got '8', 'inf'\)")

    def test_nan_end_does_not_hide_the_length(self):
        self.edit("shots.csv", "s04,24.5,30", "s04,24.5,nan")
        self.assert_reported(r"shots.csv:5: from_s/to_s must be numbers")

    def test_unexpected_exception_still_writes_the_report(self):
        from unittest import mock
        with mock.patch.object(ce, "check_script", side_effect=RuntimeError("boom")):
            out = self.assert_reported(r"internal: RuntimeError: boom")
        self.assertRegex(out, r"Summary: 1 error\(s\)")

    def test_unexpected_exception_in_style_check(self):
        from unittest import mock
        with mock.patch.object(ce, "check_style", side_effect=KeyError("k")):
            code, out, err = run_main(ce.main, ["style", str(STYLE_FIX)])
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"ERROR internal: KeyError: ")
        self.assertIn("Summary: 1 error(s)", out)
        self.assertNotIn("Traceback", err + out)


class TestRenamedEpisodeCopy(TmpDirCase, unittest.TestCase):
    """The new rules read no episode prefix: a copy with another folder name and file prefix still passes."""

    def test_renamed_copy_passes(self):
        ep = self.tmp / "projects" / "other-series" / "ep07-doi-ten"
        shutil.copytree(EPISODE_FIX, ep)
        for name in ("EPISODE.md", "prompts.csv", "anchors.json"):
            p = ep / name
            s = p.read_text(encoding="utf-8")
            s = s.replace("ep01-test-ep", "ep07-doi-ten").replace("ep01", "ep07").replace("test-series", "other-series")
            s = s.replace("TestSeries", "OtherSeries").replace("episode: 1", "episode: 7").replace("slug: test-ep", "slug: doi-ten")
            p.write_text(s, encoding="utf-8")
        media = self.tmp / "out" / "other-series" / "ep07"
        (media / "plates").mkdir(parents=True)
        (media / "renders").mkdir()
        for n in PLATES:
            (media / "plates" / n.replace("ep01", "ep07")).write_bytes(b"x")
        (media / "renders" / "ep07_final_v01.mp4").write_bytes(b"x")
        code, out, _ = run_main(ce.main, ["episode", str(ep), "--media", str(media)])
        self.assertEqual(code, 0, out)
        self.assertIn("Summary: 0 error(s)", out)

    def test_plain_fixture_copy_passes_without_media(self):
        ep = self.tmp / "projects" / "test-series" / "ep01-test-ep"
        shutil.copytree(EPISODE_FIX, ep)
        code, out, _ = run_main(ce.main, ["episode", str(ep), "--media", str(self.tmp / "nowhere")])
        self.assertEqual(code, 0, out)


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

    def test_non_scalar_values_do_not_crash(self):
        for old, new, pattern in (("status: draft", "status: [draft]", r"status \['draft'\] must be stable or draft"),
                                  ("motion: [mist-bands]", "motion: [{a: 1}]", r"motion entry \{'a': 1\} must be a module id"),
                                  ("L3: {method: chroma", "L3: {method: [chroma]", r"matte.per_layer.L3.method \['chroma'\] not in")):
            with self.subTest(new=new):
                keep = (self.st / "style.yaml").read_text(encoding="utf-8")
                self.edit(old, new)
                self.assert_error(pattern)
                (self.st / "style.yaml").write_text(keep, encoding="utf-8")

    def test_non_utf8_style_yaml(self):
        p = self.st / "style.yaml"
        p.write_bytes(p.read_bytes() + b"# \xff\xfe\n")
        self.assert_error(r"style.yaml: not valid UTF-8")

    def test_non_utf8_prompt_template(self):
        p = self.st / "prompts" / "plate.txt"
        p.write_bytes(p.read_bytes() + b"\xff\xfe\n")
        self.assert_error(r"prompts/plate.txt: not valid UTF-8")

    def test_impossible_date_in_style_yaml(self):
        self.edit("status: draft", "status: draft\nsince: 2026-11-31")
        self.assert_error(r"style.yaml: not valid YAML: day is out of range")


if __name__ == "__main__":
    unittest.main()
