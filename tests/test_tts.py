"""tools/tts/vieneu_tts.py without the model: script parsing, Vietnamese normalisation, pronunciation map, log format.
The VieNeu engine is replaced by a fake that returns a sine tone, so nothing is downloaded or synthesised."""
import json, os, shutil, sys, unittest
from unittest import mock

import numpy as np

import re

from helpers import EPISODE_FIX, REPO, TmpDirCase, load, run_main

tts = load("tts/vieneu_tts.py", "film_vieneu_tts")
SCRIPT = EPISODE_FIX / "script.md"


class FakeEngine:
    """Stands in for VieneuEngine: 0.2 s + 0.1 s of tone per word (or `seconds` per line when set). The floor keeps
    one-word lines ("Hết.") above the 0.2 s EMPTY threshold."""
    mode, precision, version, repo, revision, rate, watermark = "v3turbo", "int8", "9.9.9", "fake/repo", "abc123", 24000, True

    def __init__(self, seconds=None):
        self.seconds, self.calls = seconds, []

    def voices(self):
        return [{"name": "Bắc Một", "gender": "male", "region": "bac", "style": "kể chuyện", "description": ""},
                {"name": "Nam Một", "gender": "male", "region": "nam", "style": "đọc truyện", "description": ""},
                {"name": "Nữ Nam", "gender": "female", "region": "nam", "style": "tin tức", "description": ""}]

    def default_voice(self):
        return "Bắc Một"

    def resolve(self, name):
        return name if name in {v["name"] for v in self.voices()} else None

    def native_speed(self):
        return False

    def synth(self, text, voice, seed=None, speed=1.0):
        self.calls.append((text, voice, seed))
        dur = self.seconds if self.seconds is not None else 0.2 + 0.1 * len(text.split())
        t = np.arange(int(dur * self.rate)) / self.rate
        return (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), self.rate


class TestParse(unittest.TestCase):
    def test_script_fixture(self):
        lines = tts.parse_script(SCRIPT.read_text(encoding="utf-8"))
        self.assertEqual([l["id"] for l in lines], ["VO1", "VO2", "VO3", "VO4", "VO5"])
        self.assertEqual([l["start_s"] for l in lines], [0, 5, 12, 20, 26])
        self.assertEqual(lines[2]["text"], "Nó có đuôi dài, tiếng kêu như tên gọi.")    # "- " bullet dropped
        self.assertFalse(any("Ghi chú" in l["text"] or "đọc chậm" in l["text"] for l in lines))

    def test_ignores_non_narration(self):
        text = ("---\ntitle: x\n---\n# Tiêu đề\n> [00:01] trích dẫn\n<!-- [00:02] chú thích\nnhiều dòng -->\n"
                "```\n[00:03] mã\n```\n---\n[00:04] Câu thật.\n[00:09]\n")
        lines = tts.parse_script(text)
        self.assertEqual([(l["start_s"], l["text"]) for l in lines], [(4, "Câu thật.")])

    def test_slots_from_episode_length(self):
        self.assertEqual(tts.episode_length(str(SCRIPT)), 30.0)
        lines = tts.add_slots(tts.parse_script(SCRIPT.read_text(encoding="utf-8")), 30.0)
        self.assertEqual([l["slot_s"] for l in lines], [5, 7, 8, 6, 4])

    def test_last_slot_unknown_without_length(self):
        lines = tts.add_slots([{"id": "A", "text": "x", "start_s": 0}, {"id": "B", "text": "y", "start_s": 4}])
        self.assertEqual(lines[0]["slot_s"], 4)
        self.assertNotIn("slot_s", lines[1])


class TestNumbers(unittest.TestCase):
    def test_cardinals(self):
        cases = {0: "không", 5: "năm", 10: "mười", 11: "mười một", 15: "mười lăm", 21: "hai mươi mốt",
                 24: "hai mươi bốn", 25: "hai mươi lăm", 100: "một trăm", 105: "một trăm lẻ năm",
                 110: "một trăm mười", 1000: "một ngàn", 1005: "một ngàn không trăm lẻ năm",
                 1998: "một ngàn chín trăm chín mươi tám", 2024: "hai ngàn không trăm hai mươi bốn",
                 1000000: "một triệu", 2500000: "hai triệu năm trăm ngàn", 3000000000: "ba tỷ"}
        for n, want in cases.items():
            self.assertEqual(tts.num_words(n), want, n)

    def test_northern_reading(self):
        self.assertEqual(tts.num_words(1005, "bac"), "một nghìn không trăm linh năm")

    def test_roman(self):
        self.assertEqual([tts.roman_to_int(s) for s in ["I", "IV", "IX", "XIV", "MCMXC"]], [1, 4, 9, 14, 1990])
        self.assertIsNone(tts.roman_to_int("IIII"))


class TestNormalize(unittest.TestCase):
    def n(self, s, **kw):
        return tts.normalize_vi(s, **kw)

    def test_years_and_thousands(self):
        self.assertEqual(self.n("Năm 1998, có 3.000 người."),
                         "Năm một ngàn chín trăm chín mươi tám, có ba ngàn người.")

    def test_units_percent_decimal(self):
        self.assertEqual(self.n("Cao 3 m, cách 25 km, nặng 10 kg, 12,5% dân số, 36°C."),
                         "Cao ba mét, cách hai mươi lăm ki lô mét, nặng mười ki lô gam, "
                         "mười hai phẩy năm phần trăm dân số, ba mươi sáu độ xê.")

    def test_unit_only_after_number(self):
        self.assertEqual(self.n("3 mẫu ruộng, m nào"), "ba mẫu ruộng, m nào")

    def test_ordinals_and_era(self):
        self.assertEqual(self.n("Thế kỷ IV TCN, thế kỷ thứ 4, thứ 1, chương 21."),
                         "Thế kỷ thứ tư trước Công nguyên, thế kỷ thứ tư, thứ nhất, chương hai mươi mốt.")

    def test_lowercase_words_are_not_roman(self):
        self.assertEqual(self.n("phần mềm, thứ di"), "phần mềm, thứ di")

    def test_dates_times_ranges(self):
        self.assertEqual(self.n("Ngày 12/4/2024 lúc 7h30, đi 300-400 dặm."),
                         "Ngày mười hai tháng tư năm hai ngàn không trăm hai mươi bốn lúc bảy giờ ba mươi phút, "
                         "đi ba trăm đến bốn trăm dặm.")

    def test_keeps_diacritics_and_strips_emphasis(self):
        self.assertEqual(self.n("**Bắc Thị** là *thú* lạ."), "Bắc Thị là thú lạ.")


class TestPron(TmpDirCase, unittest.TestCase):
    def test_map_whole_words_longest_first(self):
        p = self.tmp / "pron.csv"
        p.write_text("term,doc\n# chú thích\nChiêu Diêu,Chiêu Dao\nDiêu,Dao\nSơn,Sơn\n", encoding="utf-8")
        pron = tts.read_pron(str(p))
        self.assertEqual(pron[0][0], "Chiêu Diêu")
        self.assertEqual(tts.normalize_vi("Núi Chiêu Diêu, Diêu Sơn, Diêuu.", pron),
                         "Núi Chiêu Dao, Dao Sơn, Diêuu.")

    def test_bad_header(self):
        p = self.tmp / "pron.csv"
        p.write_text("a,b\nx,y\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            tts.read_pron(str(p))


class TestCli(TmpDirCase, unittest.TestCase):
    LOG_KEYS = {"id", "text", "spoken", "file", "duration_s", "voice", "model", "version", "licence", "watermark",
                "sample_rate", "slot_s", "fit", "seed", "text_sha", "status", "rms_dbfs", "peak_dbfs", "clipped",
                "lead_silence_s", "tail_silence_s"}

    def run_tool(self, argv, engine=None):
        eng = engine or FakeEngine()
        made = []
        code, out, err = run_main(lambda a: tts.main(a, make_engine=lambda _: made.append(1) or eng), argv)
        return code, out, err, eng, made

    def test_script_render_and_log(self):
        out = self.tmp / "vo"
        code, so, _, eng, _ = self.run_tool(["--script", str(SCRIPT), "--out", str(out), "--voice", "Nam Một"])
        self.assertEqual(code, 0, so)
        log = json.loads((out / "tts-log.json").read_text(encoding="utf-8"))
        self.assertEqual([e["id"] for e in log], ["VO1", "VO2", "VO3", "VO4", "VO5"])
        for e in log:
            self.assertTrue(self.LOG_KEYS <= set(e), self.LOG_KEYS - set(e))
            self.assertTrue(os.path.isfile(e["file"]))
            wav, rate = tts.read_wav(e["file"])
            self.assertEqual(rate, 24000)
            self.assertAlmostEqual(len(wav) / rate, e["duration_s"], places=2)
            self.assertEqual((e["voice"], e["licence"], e["version"]), ("Nam Một", "Apache-2.0", "vieneu 9.9.9"))
        self.assertTrue(all(c[1] == "Nam Một" and c[2] == 1234 for c in eng.calls))
        self.assertIn("VO5", so)

    def test_over_slot_flagged(self):
        out = self.tmp / "vo"
        code, so, _, _, _ = self.run_tool(["--script", str(SCRIPT), "--out", str(out), "--strict"], FakeEngine(seconds=6.5))
        self.assertEqual(code, 1)
        log = {e["id"]: e for e in json.loads((out / "tts-log.json").read_text(encoding="utf-8"))}
        self.assertTrue(log["VO1"]["fit"].startswith("OVER"))         # 6.5 s in a 5 s slot
        self.assertTrue(log["VO3"]["fit"].startswith("ok"))           # 8 s slot
        self.assertEqual((log["VO1"]["status"], log["VO3"]["status"]), ("OVER", "ok"))
        self.assertIn("OVER slot: VO1, VO4, VO5", so)

    def test_only_rerenders_and_keeps_other_entries(self):
        out = self.tmp / "vo"
        self.run_tool(["--script", str(SCRIPT), "--out", str(out)])
        code, _, _, eng, _ = self.run_tool(["--script", str(SCRIPT), "--out", str(out), "--only", "VO2,VO4"])
        self.assertEqual(code, 0)
        self.assertEqual(len(eng.calls), 2)
        log = json.loads((out / "tts-log.json").read_text(encoding="utf-8"))
        self.assertEqual([e["id"] for e in log], ["VO1", "VO2", "VO3", "VO4", "VO5"])     # script order, not sorted

    def test_vo_lines_json(self):
        lines = self.tmp / "vo-lines.json"
        lines.write_text(json.dumps({"lines": [{"id": "VO1", "text": "Năm 1998."}, {"id": "VO2", "text": "Hết."}]},
                                    ensure_ascii=False), encoding="utf-8")
        out = self.tmp / "vo"
        code, _, _, eng, _ = self.run_tool(["--lines", str(lines), "--out", str(out)])
        self.assertEqual(code, 0)
        self.assertEqual(eng.calls[0][0], "Năm một ngàn chín trăm chín mươi tám.")
        log = json.loads((out / "tts-log.json").read_text(encoding="utf-8"))
        self.assertEqual(log[0]["text"], "Năm 1998.")
        self.assertIsNone(log[0]["slot_s"])

    def test_dry_run_loads_no_model(self):
        code, so, _, _, made = self.run_tool(["--script", str(SCRIPT), "--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(made, [])
        self.assertIn("VO4: Người xưa gọi nó là Bắc Thị.", so)

    def test_unknown_only_id(self):
        code, _, err, _, _ = self.run_tool(["--script", str(SCRIPT), "--dry-run", "--only", "VO9"])
        self.assertNotEqual(code, 0)
        self.assertIn("VO9", err)

    def test_audition_southern_first(self):
        out = self.tmp / "aud"
        code, so, _, eng, _ = self.run_tool(["--audition", "male", "--text", "Câu một.", "--text", "Câu hai.",
                                             "--out", str(out)])
        self.assertEqual(code, 0, so)
        log = json.loads((out / "audition-log.json").read_text(encoding="utf-8"))
        self.assertEqual([t["voice"] for t in log["takes"]], ["Nam Một", "Nam Một", "Bắc Một", "Bắc Một"])
        t = log["takes"][0]
        self.assertTrue({"duration_s", "rms_dbfs", "peak_dbfs", "clipped", "audio_per_compute_s"} <= set(t))
        self.assertTrue((out / "nam-mot_T1.wav").is_file())

    def test_missing_vieneu_prints_install_hint(self):
        with mock.patch.dict(sys.modules, {"vieneu": None}):
            code, _, err = run_main(tts.main, ["--text", "Xin chào.", "--out", str(self.tmp / "vo")])
        self.assertEqual(code, tts.EXIT_MISSING)
        self.assertIn("pip install vieneu==", err)


class TestAudio(TmpDirCase, unittest.TestCase):
    def test_wav24_roundtrip_and_stats(self):
        x = np.concatenate([np.zeros(2400), 0.5 * np.sin(np.arange(24000) / 10.0), np.ones(10)]).astype(np.float32)
        p = str(self.tmp / "a.wav")
        tts.write_wav24(p, x, 24000)
        y, rate = tts.read_wav(p)
        self.assertEqual(rate, 24000)
        self.assertLess(float(np.max(np.abs(y - x))), 1e-5)
        st = tts.audio_stats(y, rate)
        self.assertEqual(st["clipped"], 10)
        self.assertAlmostEqual(st["lead_silence_s"], 0.1, places=2)
        self.assertEqual(st["peak_dbfs"], 0.0)

    def test_voice_meta_and_slug(self):
        self.assertEqual(tts.voice_meta("Nam · Nam · Phong cách kể chuyện"), ("male", "nam", "Phong cách kể chuyện"))
        self.assertEqual(tts.voice_meta("Nữ · Bắc · Phong cách tin tức")[:2], ("female", "bac"))
        self.assertEqual(tts.slug("Đức Trí"), "duc-tri")


def write_script(folder, texts, step=5):
    """script.md with one mark every `step` seconds; returns its path."""
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / "script.md"
    marks = [f"[{i * step // 60:02d}:{i * step % 60:02d}] {t}\n" for i, t in enumerate(texts)]
    p.write_text("# Lời bình\n" + "".join(marks), encoding="utf-8")
    return p


class CliCase(TmpDirCase):
    def run_tool(self, argv, engine=None):
        eng = engine or FakeEngine()
        made = []
        code, out, err = run_main(lambda a: tts.main(a, make_engine=lambda _: made.append(1) or eng), argv)
        return code, out, err, eng, made

    def read_log(self, out):
        return json.loads((out / "tts-log.json").read_text(encoding="utf-8"))

    def write_log(self, out, log):
        (out / "tts-log.json").write_text(json.dumps(log, ensure_ascii=False), encoding="utf-8")

    def files(self):
        return sorted(str(p.relative_to(self.tmp)) for p in self.tmp.rglob("*") if p.is_file())


class TestScriptProblems(CliCase, unittest.TestCase):
    CASES = {  # name -> (script body, extra argv, line number of the problem)
        "no mark": ("[00:00] Câu một.\nCâu hai không mốc.\n[00:05] Câu ba.\n", [], 2),
        "malformed mark": ("[00:00] Câu một.\n[0:05] Câu hai.\n[00:09] Câu ba.\n", [], 2),
        "seconds over 59": ("[00:00] Câu một.\n\n[00:75] Câu hai.\n", [], 3),
        "empty text": ("[00:00] Câu một.\n[00:05]\n[00:09] Câu ba.\n", [], 2),
        "not after previous": ("[00:00] Câu một.\n[00:10] Câu hai.\n[00:05] Câu ba.\n", [], 3),
        "same as previous": ("[00:00] Câu một.\n[00:10] Câu hai.\n[00:10] Câu ba.\n", [], 3),
        "length before last mark": ("[00:00] Câu một.\n[00:10] Câu hai.\n", ["--length", "10"], 2),
    }

    def test_each_problem_exits_2_with_line_number(self):
        for name, (body, extra, n) in self.CASES.items():
            with self.subTest(name):
                p = self.tmp / "ep" / "script.md"
                p.parent.mkdir(exist_ok=True)
                p.write_text(body, encoding="utf-8")
                for mode in (["--dry-run"], ["--out", str(self.tmp / "vo")]):
                    code, _, err, _, made = self.run_tool(["--script", str(p), *extra, *mode])
                    self.assertEqual(code, tts.EXIT_INPUT, (mode, err))
                    self.assertIn(f"script.md:{n}: ", err)
                    self.assertEqual(len(err.strip().splitlines()), 1, err)
                    self.assertEqual(made, [])
                self.assertFalse((self.tmp / "vo").exists())

    def test_no_flag_bypasses(self):
        p = self.tmp / "script.md"
        p.write_text("[00:00] Câu một.\nCâu hai không mốc.\n[00:05] Câu ba.\n", encoding="utf-8")
        for extra in (["--only", "VO1"], ["--allow-stale"], ["--check"]):
            code, _, err, _, made = self.run_tool(["--script", str(p), "--out", str(self.tmp / "vo"), *extra])
            self.assertEqual((code, made), (tts.EXIT_INPUT, []), extra)

    def test_function_reports_every_problem(self):
        text = "[00:00] Một.\n[0:05] Hai.\nBa.\n[00:75] Bốn.\n[00:10] Năm.\n[00:08] Sáu.\n[00:20]\n"
        got = tts.script_problems(text, 9)
        self.assertEqual([n for n, _ in got], [2, 3, 4, 6, 7, 7])
        self.assertTrue(all(isinstance(r, str) and r for _, r in got))

    def test_fixture_has_no_problems(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertEqual(tts.script_problems(text, 30.0), [])
        self.assertEqual(tts.script_problems(text, None), [])
        self.assertEqual(len(tts.parse_script(text)), 5)

    def test_no_narration_is_an_input_error(self):
        p = self.tmp / "script.md"
        p.write_text("# Chỉ có tiêu đề\n> ghi chú\n", encoding="utf-8")
        code, _, err, _, _ = self.run_tool(["--script", str(p), "--dry-run"])
        self.assertEqual(code, tts.EXIT_INPUT, err)


class TestLinesInput(CliCase, unittest.TestCase):
    def lines_file(self, data):
        p = self.tmp / "vo-lines.json"
        p.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return p

    def refused(self, data, needle=None):
        p = self.lines_file(data)
        out = self.tmp / "d" / "x" / "vo"
        before = self.files()
        code, _, err, _, made = self.run_tool(["--lines", str(p), "--out", str(out)])
        self.assertEqual(code, tts.EXIT_INPUT, err)
        self.assertEqual(made, [])
        self.assertEqual(len(err.strip().splitlines()), 1, err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(self.files(), before)          # nothing written, inside or outside --out
        if needle:
            self.assertIn(needle, err)

    def test_duplicate_id(self):
        self.refused({"lines": [{"id": "VO1", "text": "Một."}, {"id": "VO1", "text": "Hai."}]}, "VO1")

    def test_path_escaping_id(self):
        self.refused({"lines": [{"id": "VO1", "text": "Một."}, {"id": "../../escape", "text": "Hai."}]}, "escape")
        for bad in ("a/b", ".hidden", "", "x" * 33, "VO 1", 7):
            self.refused({"lines": [{"id": bad, "text": "Một."}]})

    def test_wrong_shapes(self):
        for data in ({"vo": []}, {"lines": {"id": "VO1"}}, {"lines": ["Một."]}, [{"id": "VO1", "text": "Một."}],
                     "{broken", '"just a string"'):
            self.refused(data)

    def test_non_numeric_start_and_slot(self):
        self.refused({"lines": [{"id": "VO1", "text": "Một.", "start_s": "abc"}]}, "start_s")
        self.refused({"lines": [{"id": "VO1", "text": "Một.", "slot_s": [1]}]}, "slot_s")
        self.refused({"lines": [{"id": "VO1", "text": "Một.", "slot_s": True}]}, "slot_s")

    def test_empty_text_and_empty_list(self):
        self.refused({"lines": [{"id": "VO1", "text": "  "}]}, "text")
        self.refused({"lines": [{"id": "VO1"}]}, "text")
        self.refused({"lines": []})

    def test_missing_files(self):
        for flag in ("--lines", "--script"):
            code, _, err, _, made = self.run_tool([flag, str(self.tmp / "nope"), "--out", str(self.tmp / "vo")])
            self.assertEqual((code, made), (tts.EXIT_INPUT, []), err)
            self.assertEqual(len(err.strip().splitlines()), 1, err)
        self.assertEqual(self.files(), [])

    def test_valid_lines_keep_start_and_slot(self):
        p = self.lines_file({"lines": [{"id": "a_1", "text": "Một.", "start_s": 0, "slot_s": 2.5}, {"text": "Hai."}]})
        out = self.tmp / "vo"
        code, _, err, _, _ = self.run_tool(["--lines", str(p), "--out", str(out)])
        self.assertEqual(code, 0, err)
        self.assertEqual([(e["id"], e["slot_s"]) for e in self.read_log(out)], [("a_1", 2.5), ("VO2", None)])


class TestLogSafety(CliCase, unittest.TestCase):
    def test_corrupt_log_is_renamed_before_the_engine_is_created(self):
        for i, bad in enumerate(("{broken", '{"VO1": {}}', '["VO1"]')):
            with self.subTest(bad):
                out = self.tmp / f"vo{i}"
                out.mkdir()
                (out / "tts-log.json").write_text(bad, encoding="utf-8")
                seen = []

                def make(_):
                    seen.append(sorted(p.name for p in out.iterdir()))
                    return FakeEngine()
                code, so, err = run_main(lambda a: tts.main(a, make_engine=make),
                                         ["--script", str(SCRIPT), "--out", str(out)])
                self.assertEqual(code, 0, err)
                self.assertEqual(len(seen[0]), 1)
                self.assertTrue(seen[0][0].startswith("tts-log.json.bad-"), seen)
                kept = next(out.glob("tts-log.json.bad-*"))
                self.assertEqual(kept.read_text(encoding="utf-8"), bad)
                self.assertIn(kept.name, so + err)
                self.assertEqual([e["id"] for e in self.read_log(out)], ["VO1", "VO2", "VO3", "VO4", "VO5"])

    def test_log_is_written_after_every_line(self):
        class Dies(FakeEngine):
            def synth(self, text, voice, seed=None, speed=1.0):
                if len(self.calls) == 2:
                    raise RuntimeError("model crashed")
                return super().synth(text, voice, seed, speed)
        out = self.tmp / "vo"
        with self.assertRaises(RuntimeError):
            self.run_tool(["--script", str(SCRIPT), "--out", str(out)], Dies())
        self.assertEqual([e["id"] for e in self.read_log(out)], ["VO1", "VO2"])


class TestStale(CliCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.ep, self.out = self.tmp / "ep", self.tmp / "vo"
        self.base = ["--script", str(self.ep / "script.md"), "--length", "20", "--out", str(self.out)]
        write_script(self.ep, ["Một.", "Hai.", "Ba."])
        self.assertEqual(self.run_tool(self.base)[0], 0)

    def test_only_refused_when_another_line_is_stale(self):
        write_script(self.ep, ["Một.", "Chèn mới.", "Hai sửa."])
        code, so, err, _, made = self.run_tool(self.base + ["--only", "VO2"])
        self.assertEqual((code, made), (tts.EXIT_INPUT, []), err)
        self.assertIn("STALE VO3: text changed since render", so + err)
        self.assertIn("--allow-stale", err)
        self.assertEqual({e["id"]: e["text"] for e in self.read_log(self.out)}["VO2"], "Hai.")   # untouched

    def test_allow_stale_renders_and_still_reports(self):
        write_script(self.ep, ["Một.", "Chèn mới.", "Hai sửa."])
        code, so, err, eng, _ = self.run_tool(self.base + ["--only", "VO2", "--allow-stale"])
        self.assertEqual(code, 0, err)
        self.assertEqual(len(eng.calls), 1)
        self.assertIn("STALE VO3: text changed since render", so + err)
        self.assertEqual([(e["id"], e["text"]) for e in self.read_log(self.out)],
                         [("VO1", "Một."), ("VO2", "Chèn mới."), ("VO3", "Ba.")])

    def test_only_the_stale_line_itself_is_fine(self):
        write_script(self.ep, ["Một.", "Hai.", "Ba sửa."])
        code, so, err, _, _ = self.run_tool(self.base + ["--only", "VO3"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.read_log(self.out)[2]["text"], "Ba sửa.")

    def test_full_render_moves_orphans_and_keeps_script_order(self):
        write_script(self.ep, ["Một."])
        code, so, err, _, _ = self.run_tool(self.base)
        self.assertEqual(code, 0, err)
        self.assertIn("ORPHAN VO2: not in script", so + err)
        self.assertEqual([e["id"] for e in self.read_log(self.out)], ["VO1"])
        self.assertEqual(sorted(p.name for p in self.out.glob("*.wav")), ["VO1.wav"])
        self.assertEqual(sorted(p.name for p in (self.out / "_stale").iterdir()), ["VO2.wav", "VO3.wav"])

    def test_only_keeps_orphans_and_lists_them_last(self):
        write_script(self.ep, ["Một.", "Hai."])
        code, so, err, _, _ = self.run_tool(self.base + ["--only", "VO1"])
        self.assertEqual(code, 0, err)
        self.assertIn("ORPHAN VO3: not in script", so + err)
        self.assertEqual([e["id"] for e in self.read_log(self.out)], ["VO1", "VO2", "VO3"])
        self.assertTrue((self.out / "VO3.wav").is_file())

    def test_orphan_with_an_unsafe_id_is_dropped_and_no_file_is_touched(self):
        victim = self.tmp / "escape.wav"
        victim.write_bytes(b"keep")
        self.write_log(self.out, self.read_log(self.out) + [{"id": "../escape", "text": "x", "file": str(victim)}])
        self.assertEqual(self.run_tool(self.base)[0], 0)
        self.assertEqual(victim.read_bytes(), b"keep")
        self.assertEqual([e["id"] for e in self.read_log(self.out)], ["VO1", "VO2", "VO3"])

    def test_old_entry_without_text_sha_is_compared_by_text(self):
        log = self.read_log(self.out)
        self.assertTrue(all(len(e.pop("text_sha")) == 12 for e in log))
        self.write_log(self.out, log)
        code, so, err, _, _ = self.run_tool(self.base + ["--only", "VO1"])
        self.assertEqual(code, 0, err)
        self.assertNotIn("STALE", so + err)
        log = self.read_log(self.out)
        log[2]["text"] = "Ba cũ."
        self.assertNotIn("text_sha", log[2])
        self.write_log(self.out, log)
        code, so, err, _, _ = self.run_tool(self.base + ["--only", "VO1"])
        self.assertEqual(code, tts.EXIT_INPUT)
        self.assertIn("STALE VO3", so + err)

    def test_dry_run_reports_stale_without_changing_anything(self):
        write_script(self.ep, ["Một.", "Hai sửa."])
        before = {p.name: p.read_bytes() for p in self.out.iterdir()}
        code, so, err, _, made = self.run_tool(self.base + ["--dry-run"])
        self.assertEqual((code, made), (0, []), err)
        self.assertIn("STALE VO2", so + err)
        self.assertIn("ORPHAN VO3", so + err)
        self.assertEqual({p.name: p.read_bytes() for p in self.out.iterdir()}, before)


class TestCheck(CliCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.ep, self.out = self.tmp / "ep", self.tmp / "vo"
        self.src = ["--script", str(self.ep / "script.md"), "--length", "20", "--out", str(self.out)]
        self.base = self.src + ["--voice", "Nam Một"]
        write_script(self.ep, ["Một.", "Hai.", "Ba."])
        self.assertEqual(self.run_tool(self.base)[0], 0)

    def check(self, *extra, base=None):
        code, so, err, _, made = self.run_tool((base or self.base) + ["--check", *extra])
        self.assertEqual(made, [])                       # never loads a model
        return code, so + err

    def test_passes_after_a_render(self):
        code, text = self.check()
        self.assertEqual(code, 0, text)
        code, text = self.check(base=self.src)           # no --voice: one voice across the log is enough
        self.assertEqual(code, 0, text)

    def test_fails_after_a_text_edit(self):
        write_script(self.ep, ["Một.", "Hai sửa.", "Ba."])
        code, text = self.check()
        self.assertEqual(code, 1)
        self.assertIn("VO2", text)
        self.assertNotIn("VO1", text)

    def test_fails_on_missing_wav_and_unrendered_line(self):
        (self.out / "VO3.wav").unlink()
        code, text = self.check()
        self.assertEqual(code, 1)
        self.assertIn("VO3", text)
        write_script(self.ep, ["Một.", "Hai.", "Ba.", "Bốn."])
        code, text = self.check()
        self.assertEqual(code, 1)
        self.assertIn("VO4", text)

    def test_fails_on_other_voice_mode_or_seed(self):
        for base, extra in ((self.src, ["--voice", "Bắc Một"]), (self.base, ["--seed", "7"]),
                            (self.base, ["--mode", "v3nano"])):
            code, text = self.check(*extra, base=base)
            self.assertEqual(code, 1, extra)
            self.assertIn(extra[0].lstrip("-"), text)

    def test_fails_on_mixed_voices_when_no_voice_is_given(self):
        self.assertEqual(self.run_tool(self.src + ["--voice", "Bắc Một", "--only", "VO2"])[0], 0)
        code, text = self.check(base=self.src)
        self.assertEqual(code, 1)
        self.assertIn("voice", text)

    def test_fails_on_zero_duration(self):
        log = self.read_log(self.out)
        log[0]["duration_s"] = 0
        self.write_log(self.out, log)
        code, text = self.check()
        self.assertEqual(code, 1)
        self.assertIn("VO1", text)

    def test_orphan_fails_the_check(self):
        write_script(self.ep, ["Một.", "Hai."])
        code, text = self.check()
        self.assertEqual(code, 1)
        self.assertIn("ORPHAN VO3", text)

    def test_no_render_yet_and_bad_usage(self):
        code, text = self.check(base=["--script", str(self.ep / "script.md"), "--length", "20", "--out",
                                      str(self.tmp / "empty")])
        self.assertEqual(code, 1)
        self.assertFalse((self.tmp / "empty").exists())
        for argv in (["--check", "--script", str(self.ep / "script.md")],
                     ["--check", "--text", "Một.", "--out", str(self.out)],
                     self.base + ["--check", "--only", "VO1"], self.base + ["--check", "--dry-run"]):
            code, _, err, _, made = self.run_tool(argv)
            self.assertEqual((code, made), (tts.EXIT_INPUT, []), argv)

    def test_works_with_lines_json(self):
        lines = self.tmp / "vo-lines.json"
        lines.write_text(json.dumps({"lines": [{"id": "A", "text": "Một."}, {"id": "B", "text": "Hai."}]}), "utf-8")
        out = self.tmp / "vo2"
        self.assertEqual(self.run_tool(["--lines", str(lines), "--out", str(out)])[0], 0)
        self.assertEqual(self.run_tool(["--lines", str(lines), "--out", str(out), "--check"])[0], 0)


class TestStrict(CliCase, unittest.TestCase):
    def test_empty_take_fails_without_strict(self):
        out = self.tmp / "vo"
        code, so, err, _, _ = self.run_tool(["--text", "Xin chào.", "--out", str(out)], FakeEngine(seconds=0))
        self.assertEqual(code, 1)
        self.assertIn("EMPTY", so + err)
        self.assertEqual(self.read_log(out)[0]["status"], "EMPTY")

    def test_near_silent_take_is_empty(self):
        class Quiet(FakeEngine):
            def synth(self, text, voice, seed=None, speed=1.0):
                wav, rate = super().synth(text, voice, seed, speed)
                return wav * 0.001, rate
        out = self.tmp / "vo"
        code, _, _, _, _ = self.run_tool(["--text", "Xin chào các bạn.", "--out", str(out)], Quiet(seconds=1))
        self.assertEqual(code, 1)
        self.assertEqual(self.read_log(out)[0]["status"], "EMPTY")

    def test_noslot_only_fails_a_strict_script_render(self):
        script = write_script(self.tmp / "ep", ["Một hai ba.", "Bốn năm sáu."])       # no EPISODE.md, no --length
        out = self.tmp / "vo"
        code, so, err, _, _ = self.run_tool(["--script", str(script), "--out", str(out)])
        self.assertEqual(code, 0, err)
        self.assertEqual([e["status"] for e in self.read_log(out)], ["ok", "NOSLOT"])
        code, so, err, _, _ = self.run_tool(["--script", str(script), "--out", str(out), "--strict"])
        self.assertEqual(code, 1)
        self.assertIn("NOSLOT", so + err)
        self.assertIn("--length", so + err)
        self.assertIn("length_s", so + err)
        code, _, _, _, _ = self.run_tool(["--script", str(script), "--out", str(out), "--strict", "--length", "10"])
        self.assertEqual(code, 0)
        code, _, _, _, _ = self.run_tool(["--text", "Một hai ba.", "--out", str(out), "--strict"])
        self.assertEqual(code, 0)                         # --text has no slots by design

    def test_clipped_fails_strict(self):
        class Loud(FakeEngine):
            def synth(self, text, voice, seed=None, speed=1.0):
                wav, rate = super().synth(text, voice, seed, speed)
                return np.where(wav >= 0, 1.0, -1.0).astype(np.float32), rate
        out = self.tmp / "vo"
        code, _, _, _, _ = self.run_tool(["--text", "Một hai ba.", "--out", str(out)], Loud(seconds=1))
        self.assertEqual(code, 0)
        e = self.read_log(out)[0]
        self.assertEqual(e["status"], "CLIPPED")
        self.assertGreater(e["clipped"], 0)
        code, so, err, _, _ = self.run_tool(["--text", "Một hai ba.", "--out", str(out), "--strict"], Loud(seconds=1))
        self.assertEqual(code, 1)
        self.assertIn("CLIPPED", so + err)

    def test_dry_run_estimate(self):
        script = write_script(self.tmp / "ep", ["một hai ba bốn năm sáu bảy tám chín mười mười một.",   # 12 syl
                                                "một hai ba bốn, năm sáu bảy tám – chín.",              # 9 syl
                                                "Hết."], step=2)
        argv = ["--script", str(script), "--length", "6", "--dry-run"]
        code, so, err, _, made = self.run_tool(argv)
        self.assertEqual((code, made), (0, []), err)
        rows = {ln.split()[0]: ln for ln in so.splitlines() if re.match(r"VO\d\s", ln)}
        self.assertIn("3.00", rows["VO1"])
        self.assertIn("OVER? (est.)", rows["VO1"])
        self.assertIn("2.25", rows["VO2"])                # the dash is not a syllable
        self.assertIn("OVER? (est.)", rows["VO2"])
        self.assertNotIn("OVER?", rows["VO3"])
        self.assertEqual(self.run_tool(argv + ["--strict"])[0], 1)
        self.assertEqual(self.run_tool(argv + ["--strict", "--rate", "8"])[0], 0)
        self.assertEqual(self.run_tool(argv + ["--strict", "--only", "VO2"])[0], 0)    # +12.5 %: flagged only
        self.assertEqual(self.run_tool(argv + ["--strict", "--only", "VO1"])[0], 1)    # +50 %
        self.assertEqual(self.run_tool(argv + ["--rate", "0"])[0], 2)

    def test_dry_run_strict_noslot(self):
        script = write_script(self.tmp / "ep", ["Một.", "Hai."])
        self.assertEqual(self.run_tool(["--script", str(script), "--dry-run"])[0], 0)
        code, so, err, _, _ = self.run_tool(["--script", str(script), "--dry-run", "--strict"])
        self.assertEqual(code, 1)
        self.assertIn("NOSLOT", so + err)

    def test_syllables(self):
        self.assertEqual(tts.syllables("Nó có đuôi dài, tiếng kêu – như tên gọi... 12 !"), 10)


class TestResidue(CliCase, unittest.TestCase):
    def test_half_converted_and_han_tokens(self):
        self.assertEqual(tts.residue(tts.normalize_vi("Cách 3.5 km.")), ["ba.5"])
        self.assertEqual(tts.residue(tts.normalize_vi("Khoảng 1e6 con.")), ["mộte6"])
        self.assertEqual(tts.residue(tts.normalize_vi("Sơn Hải Kinh (山海經), quyển 《南山經》.")), ["山海經", "《南山經》"])
        self.assertEqual(tts.residue("giá 5$ & a+b = c^2, 30° và và/hoặc"),
                         ["5$", "&", "a+b", "=", "c^2", "30°", "và/hoặc"])
        self.assertEqual(tts.residue("ba.5 rồi lại ba.5"), ["ba.5"])

    def test_clean_sentence_has_none(self):
        for s in ("Năm 1998, có 3.000 người: cao 3 m, 12,5% dân số, 36°C.", "Thế kỷ IV TCN – \"Bắc Thị\" (thú lạ)!",
                  *[ln["text"] for ln in tts.parse_script(SCRIPT.read_text(encoding="utf-8"))]):
            self.assertEqual(tts.residue(tts.normalize_vi(s)), [], s)

    def test_warn_and_strict(self):
        argv = ["--text", "Cách 3.5 km.", "--text", "Câu sạch."]
        code, so, err, _, made = self.run_tool(argv + ["--dry-run"])
        self.assertEqual((code, made), (0, []))
        self.assertIn("WARN T1: unread token 'ba.5': add it to pronunciation.csv or rewrite the line", so + err)
        self.assertNotIn("WARN T2", so + err)
        self.assertEqual(self.run_tool(argv + ["--dry-run", "--strict"])[0], 1)
        out = self.tmp / "vo"
        code, so, err, _, made = self.run_tool(argv + ["--out", str(out), "--strict"])
        self.assertEqual((code, made), (1, []))            # before the model loads
        self.assertFalse(out.exists())
        code, so, err, _, made = self.run_tool(argv + ["--out", str(out)])
        self.assertEqual((code, made), (0, [1]))
        self.assertIn("WARN T1", so + err)

    def test_pron_map_clears_the_warning(self):
        pron = self.tmp / "pron.csv"
        pron.write_text("term,doc\n山海經,Sơn Hải Kinh\n", encoding="utf-8")
        code, so, err, _, _ = self.run_tool(["--text", "Sách 山海經.", "--pron", str(pron), "--dry-run", "--strict"])
        self.assertEqual(code, 0, so + err)


class TestSpeed(CliCase, unittest.TestCase):
    def test_out_of_range_rejected_by_argparse(self):
        for bad in ("1.5", "0.3", "0", "-1", "abc", "nan"):
            code, _, err, _, made = self.run_tool(["--text", "Một hai.", "--out", str(self.tmp / "vo"), "--speed", bad])
            self.assertEqual((code, made), (2, []), bad)
            self.assertIn("0.9", err)
        self.assertFalse((self.tmp / "vo").exists())

    def test_ffmpeg_checked_before_the_engine(self):
        argv = ["--text", "Một hai.", "--out", str(self.tmp / "vo"), "--speed", "1.05"]
        with mock.patch.object(tts.shutil, "which", return_value=None):
            code, _, err, _, made = self.run_tool(argv)
            self.assertEqual((code, made), (tts.EXIT_INPUT, []))
            self.assertIn("ffmpeg", err)
            self.assertEqual(self.run_tool(argv + ["--mode", "v3nano"])[4], [1])     # native speed: no ffmpeg needed
            code, _, _, _, made = self.run_tool(["--text", "Một hai.", "--dry-run", "--speed", "1.05"])
            self.assertEqual((code, made), (0, []))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_speed_in_range_renders_through_ffmpeg(self):
        out = self.tmp / "vo"
        code, _, err, _, _ = self.run_tool(["--text", "Một hai.", "--out", str(out), "--speed", "1.1"],
                                           FakeEngine(seconds=1))
        self.assertEqual(code, 0, err)
        e = self.read_log(out)[0]
        self.assertAlmostEqual(e["duration_s"], 1 / 1.1, delta=0.03)
        self.assertEqual(e["speed"], 1.1)

    def test_help_and_readme_agree(self):
        helptext = tts.build_parser().format_help()
        self.assertIn("0.9-1.1", helptext)
        self.assertNotIn("0.8-1.2", helptext)
        self.assertIn("0,9–1,1", (REPO / "tools" / "tts" / "README.md").read_text(encoding="utf-8"))


class TestReviewHardening(CliCase, unittest.TestCase):
    """Hostile inputs found in review: each one is an input error (exit 2, one stderr line, no engine)."""

    def setUp(self):
        super().setUp()
        self.ep, self.out = self.tmp / "ep", self.tmp / "vo"
        self.script = write_script(self.ep, ["Một.", "Hai."])
        self.base = ["--script", str(self.script), "--out", str(self.out)]

    def assert_input_error(self, argv, needle):
        code, so, err, _, made = self.run_tool(argv)
        self.assertEqual((code, made), (tts.EXIT_INPUT, []), err)
        self.assertIn(needle, err)
        self.assertEqual(len(err.strip().splitlines()), 1, err)

    def test_length_must_be_a_positive_finite_number(self):
        for bad in ("nan", "inf", "-inf", "0", "-4", "abc"):
            for extra in (["--dry-run", "--strict"], ["--strict"]):
                with self.subTest(length=bad, extra=extra):
                    code, _, err, _, made = self.run_tool(self.base + ["--length", bad] + extra)
                    self.assertEqual((code, made), (tts.EXIT_INPUT, []), err)
                    self.assertIn("--length", err)
        self.assertFalse(self.out.exists())

    def test_unusable_length_s_in_episode_md_is_an_input_error(self):
        for raw in (b"---\nlength_s: 1.2.3\n---\n", b"\xff\xfe"):
            with self.subTest(raw=raw):
                (self.ep / "EPISODE.md").write_bytes(raw)
                self.assert_input_error(self.base + ["--dry-run"], "EPISODE.md")

    def test_lines_with_a_huge_number_or_deep_nesting(self):
        huge = self.tmp / "huge.json"
        huge.write_text('{"lines": [{"id": "A", "text": "x", "start_s": 1' + "0" * 400 + "}]}", encoding="utf-8")
        self.assert_input_error(["--lines", str(huge), "--dry-run"], "start_s")
        deep = self.tmp / "deep.json"
        deep.write_text("[" * 100000, encoding="utf-8")
        self.assert_input_error(["--lines", str(deep), "--dry-run"], "cannot read")

    def test_out_that_cannot_be_a_folder_is_refused_before_the_engine(self):
        blocker = self.tmp / "afile"
        blocker.write_text("x", encoding="utf-8")
        for out in (blocker, blocker / "vo"):
            with self.subTest(out=out):
                self.assert_input_error(["--script", str(self.script), "--length", "10", "--out", str(out)], "--out")
                self.assert_input_error(["--audition", "Nam Một", "--text", "Xin chào.", "--out", str(out)], "--out")
        self.assertEqual(blocker.read_text(encoding="utf-8"), "x")

    def test_only_without_an_id_is_refused(self):
        self.assert_input_error(self.base + ["--length", "10", "--only", ","], "--only")

    def test_log_is_in_script_order_whatever_the_render_order(self):
        base = self.base + ["--length", "10"]
        self.assertEqual(self.run_tool(base + ["--only", "VO2"])[0], 0)
        self.assertEqual(self.run_tool(base + ["--only", "VO1"])[0], 0)
        self.assertEqual([e["id"] for e in self.read_log(self.out)], ["VO1", "VO2"])

    def test_retiring_the_same_orphan_twice_keeps_both_wavs(self):
        full = self.base + ["--length", "10"]
        with mock.patch.object(tts.time, "strftime", return_value="20260101T000000Z"):
            for _ in range(3):                      # three takes of VO2 leave the script in the same second
                write_script(self.ep, ["Một.", "Hai."])
                self.assertEqual(self.run_tool(full)[0], 0)
                write_script(self.ep, ["Một."])
                self.assertEqual(self.run_tool(full + ["--length", "4"])[0], 0)
        self.assertEqual(len(list((self.out / "_stale").glob("VO2*.wav"))), 3)


class TestNarratorAgent(unittest.TestCase):
    AGENTS = REPO / ".claude" / "agents"

    def front(self, name):
        head = (self.AGENTS / f"{name}.md").read_text(encoding="utf-8").split("---\n")[1]
        return {ln.split(":")[0]: ln.split(":", 1)[1].strip() for ln in head.splitlines() if ln and ln[0] != " "}

    def test_front_matter_matches_animator(self):
        nar, ani = self.front("film-narrator"), self.front("film-animator")
        self.assertEqual(set(nar), set(ani))
        self.assertEqual((nar["name"], nar["tools"], nar["model"], nar["background"], nar["maxTurns"]),
                         ("film-narrator", "Bash, Read, Write, Glob, Grep", "sonnet", "true", "30"))

    def test_flags_named_in_the_agent_exist(self):
        text = (self.AGENTS / "film-narrator.md").read_text(encoding="utf-8")
        flags = set(re.findall(r"(?<![\w-])--[a-z][a-z-]+", text))
        known = {o for a in tts.build_parser()._actions for o in a.option_strings}
        self.assertIn("--check", flags)
        self.assertEqual(flags - known, set())


if __name__ == "__main__":
    unittest.main()
