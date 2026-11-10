"""tools/tts/vieneu_tts.py without the model: script parsing, Vietnamese normalisation, pronunciation map, log format.
The VieNeu engine is replaced by a fake that returns a sine tone, so nothing is downloaded or synthesised."""
import json, os, sys, unittest
from unittest import mock

import numpy as np

from helpers import EPISODE_FIX, TmpDirCase, load, run_main

tts = load("tts/vieneu_tts.py", "film_vieneu_tts")
SCRIPT = EPISODE_FIX / "script.md"


class FakeEngine:
    """Stands in for VieneuEngine: 0.1 s of tone per word (or `seconds` per line when set)."""
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
        dur = self.seconds if self.seconds is not None else 0.1 * len(text.split())
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
                "sample_rate", "slot_s", "fit", "seed"}

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
        self.assertIn("OVER slot: VO1, VO4, VO5", so)

    def test_only_rerenders_and_keeps_other_entries(self):
        out = self.tmp / "vo"
        self.run_tool(["--script", str(SCRIPT), "--out", str(out)])
        code, _, _, eng, _ = self.run_tool(["--script", str(SCRIPT), "--out", str(out), "--only", "VO2,VO4"])
        self.assertEqual(code, 0)
        self.assertEqual(len(eng.calls), 2)
        log = json.loads((out / "tts-log.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(e["id"] for e in log), ["VO1", "VO2", "VO3", "VO4", "VO5"])

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


if __name__ == "__main__":
    unittest.main()
