"""tools/status.py: one read-only screen for an episode (stage, gates, budget, open paid requests, layers, gate)."""
import csv, io, json, os, re, shutil, unittest, zipfile
from unittest import mock

from helpers import EPISODE_FIX, TmpDirCase, load, run_main

st = load("status.py", "film_status")
ark = st.ark

EPISODE_MD = """---
series: test-series
episode: 1
slug: test-ep
style: test-style
length_s: 30
stage: {stage}
gates: {{G1: {G1}, G2: {G2}, G3: {G3}, G4: {G4}}}
media: {media}
drive: "ClaudeFilmLab/TestSeries/03_KichBan/ep01-test-ep"
---
# Tập 1: Tập thử

## Ghi chú người dùng (nguyên văn)
Fixture cho tests/test_status.py.

## Đã khóa (không làm lại)
- G1 kịch bản.

## Việc tiếp theo
- Tạo lớp tranh cho s02.
  Gọi film-plate-maker, trần 6 ảnh.

## Nhật ký
- 2026-11-01, khâu 2, kịch bản duyệt, abc1234
"""
DATES = {"G1": "2026-11-01", "G2": "2026-11-03", "G3": "2026-11-06", "G4": "2026-11-09"}
SHOTS = """shot,from_s,to_s,shot_size,camera,action,layers,code_motion,ai_motion,sound,reuse_of
s01,0,8,wide,static,"Núi, sương sớm",L1;L2,mist-bands,,wind,
s02,8,15,medium,push-in,Nhân vật xuất hiện,L1;L4;P1-duoi,strip-warp,,drum,
s03,15,24.5,close,drift,Cận mặt,L1;L4,,slow blink,,
s04,24.5,30,wide,pan-left,Toàn cảnh khép lại,L1;L2,mist-bands,,wind,s01
"""
PROMPTS_HEADER = ["file", "shot", "layer", "model", "size", "prompt_file", "refs", "seed", "usage", "approved",
                  "drive_link"]
LITE = "seedream-5-0-lite-260128"
PRO = "dola-seedream-5-0-pro-260628"
VIDEO = "dreamina-seedance-2-5-260628"
BUDGET = f"images: 40\nvideo_seconds: 30\nmodels:\n  {PRO}: 6\n"
USAGE = '{"generated_images":1}'
CHECK_OK = (0, "Summary: 0 error(s), 0 warning(s)")
# (file, shot, layer, usage, approved): every layer of every non-reuse shot approved
ALL_APPROVED = [("ep01_s01_L1_nui_v01.png", "s01", "L1", USAGE, "yes"),
                ("ep01_s01_L2_suong_v01.png", "s01", "L2", USAGE, "yes"),
                ("ep01_s02_L1_nui_v01.png", "s02", "L1", USAGE, "yes"),
                ("ep01_s02_L4_bac-thi_v01.png", "s02", "L4", USAGE, "yes"),
                ("ep01_s02_P1-duoi_bac-thi_v01.png", "s02", "P1-duoi", USAGE, "yes"),
                ("ep01_s03_L1_nui_v01.png", "s03", "L1", USAGE, "yes"),
                ("ep01_s03_L4_bac-thi_v01.png", "s03", "L4", USAGE, "yes")]


def tree(root):
    """Every path under root with its size and mtime (to prove the tool writes nothing)."""
    out = {}
    for dp, dns, fns in os.walk(root):
        for n in dns + fns:
            p = os.path.join(dp, n)
            s = os.stat(p)
            out[os.path.relpath(p, root)] = (s.st_size if os.path.isfile(p) else -1, s.st_mtime_ns)
    return out


class StatusCase(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.ep = self.tmp / "projects" / "test-series" / "ep01-test-ep"
        shutil.copytree(EPISODE_FIX, self.ep)
        self.media = self.tmp / "out" / "test-series" / "ep01"
        self.ledger = self.media / "ledger.csv"
        self.episode(stage=5, G1=True, G2=True)
        (self.ep / "shots.csv").write_text(SHOTS, encoding="utf-8")
        (self.ep / "budget.yaml").write_text(BUDGET, encoding="utf-8")
        (self.ep / "research.md").write_text("# Nguồn\nNguyên văn.\n", encoding="utf-8")
        self.prompts([])
        self.rows([])
        self._patch = mock.patch.object(st, "run_check", return_value=CHECK_OK)
        self.run_check = self._patch.start()
        self.addCleanup(self.real_check)

    # --- builders -----------------------------------------------------------
    def episode(self, stage, G1=False, G2=False, G3=False, G4=False, media=None):
        g = {k: (DATES[k] if v else "null") for k, v in (("G1", G1), ("G2", G2), ("G3", G3), ("G4", G4))}
        (self.ep / "EPISODE.md").write_text(
            EPISODE_MD.format(stage=stage, media=media or self.media, **g), encoding="utf-8")

    def prompts(self, rows):
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(PROMPTS_HEADER)
        for f, shot, layer, usage, approved in rows:
            w.writerow([f, shot, layer, LITE, "2K", "prompts/s01_L1.txt", "", "", usage, approved, ""])
        (self.ep / "prompts.csv").write_text(buf.getvalue(), encoding="utf-8")

    def rows(self, rows):
        self.media.mkdir(parents=True, exist_ok=True)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=ark.LEDGER_FIELDS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(dict({"ts": "2026-11-09T08:00:00Z", "count": 1, "agent": "film-plate-maker"}, **r))
        self.ledger.write_text(buf.getvalue(), encoding="utf-8")

    def put(self, sub, *names):
        d = self.media / sub
        d.mkdir(parents=True, exist_ok=True)
        for n in names:
            (d / n).write_bytes(b"x")

    def img(self, name, status="ok", req=None, model=LITE, note="", **kw):
        note = "; ".join(x for x in (f"req={req}" if req else "", note) if x)
        return dict({"kind": "image", "model": model, "size": "2K", "status": status,
                     "out": str(self.media / "plates" / name), "note": note}, **kw)

    def vid(self, name, status, req, task="", note="", seconds=5):
        return {"kind": "video", "model": VIDEO, "size": "720p", "seconds": seconds, "status": status,
                "out": str(self.media / "clips" / name), "task_id": task, "agent": "film-animator",
                "note": "; ".join(x for x in (f"req={req}", note) if x)}

    def mixed_ledger(self):
        """2 ok images, 1 cut-502, a video with two pending rows and a task id, a Lambda pending row."""
        self.put("plates", "ep01_s01_L1_nui_v01.png", "ep01_s01_L2_suong_v01.png")
        self.rows([
            self.img("ep01_s01_L1_nui_v01.png", "pending", "aa01"),
            self.img("ep01_s01_L1_nui_v01.png", "ok", "aa01"),
            self.img("ep01_s01_L2_suong_v01.png", "pending", "aa02"),
            self.img("ep01_s01_L2_suong_v01.png", "ok", "aa02"),
            self.img("ep01_s02_L4_bac-thi_v01.png", "pending", "aa03"),
            self.img("ep01_s02_L4_bac-thi_v01.png", "cut-502", "aa03", note="HTTP 502 after 30.1s"),
            self.vid("ep01_s03_seedance25_v01.mp4", "pending", "bb01"),
            self.vid("ep01_s03_seedance25_v01.mp4", "pending", "bb01", task="cgt-123", note="task created"),
            self.img("ep01_s02_L4_bac-thi_v02.png", "pending", "cc01", model=PRO, note="lambda job prepared"),
            {"kind": "image", "model": LITE, "size": "2K", "status": "refused-budget", "out": "x.png"},
        ])

    def approve_all(self):
        self.prompts(ALL_APPROVED)
        self.put("plates", *[r[0] for r in ALL_APPROVED])

    def real_check(self):
        """Stop patching run_check: the check_episode subprocess runs for real from here on."""
        if self._patch is not None:
            self._patch.stop()
            self._patch = None

    # --- runners ------------------------------------------------------------
    def run_status(self, *extra, ep=True):
        code, out, err = run_main(st.main, ([str(self.ep)] if ep else []) + list(extra))
        self.assertNotIn("Traceback", out + err)
        return code, out

    def data(self, *extra, ep=True):
        code, out = self.run_status(*extra, "--json", ep=ep)
        return code, json.loads(out)

    def gate(self, *extra):
        code, d = self.data(*extra)
        return code, d["gate"]

    def missing(self, g):
        return [r["text"] for r in g["requirements"] if not r["ok"]]


class StageTest(StatusCase):
    def test_stage_name_gates_and_next(self):
        code, out = self.run_status()
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"STAGE\s+5\b.*Lớp tranh")
        self.assertIn("G1 2026-11-01", out)
        self.assertIn("G2 2026-11-03", out)
        self.assertRegex(out, r"G3 (-|null)")
        self.assertNotIn("BLOCKED", out)
        self.assertIn("- Tạo lớp tranh cho s02.\n", out)
        self.assertIn("  Gọi film-plate-maker, trần 6 ảnh.\n", out)   # verbatim, indentation kept
        self.assertNotIn("kịch bản duyệt", out)                        # stops at the next '## ' heading

    def test_stage_5_without_g2_is_blocked(self):
        self.episode(stage=5, G1=True)
        code, out = self.run_status()
        self.assertEqual(code, 1, out)
        self.assertIn("BLOCKED: stage 5 needs G2 (not passed)", out)
        self.assertNotIn("needs G1", out)
        self.assertNotIn("needs G3", out)

    def test_only_a_date_passes_a_gate(self):
        # `G2: false` / `no` / 0 / 'null' / free text are not an approval: the stage stays BLOCKED
        md = (self.ep / "EPISODE.md").read_text(encoding="utf-8")
        for value in ("false", "no", "0", "'null'", "chưa duyệt"):
            (self.ep / "EPISODE.md").write_text(
                md.replace(f"G2: {DATES['G2']}", f"G2: {value}"), encoding="utf-8")
            code, out = self.run_status()
            self.assertEqual(code, 1, value)
            self.assertIn("BLOCKED: stage 5 needs G2 (not passed)", out, value)
            self.assertRegex(out, r"note: EPISODE\.md: gates\.G2 = .* is not a date", value)
            self.assertIn("· G2 - ·", out, value)
        (self.ep / "EPISODE.md").write_text(md.replace(f"G2: {DATES['G2']}", f"G2: '{DATES['G2']}'"),
                                            encoding="utf-8")          # a quoted date is a date
        code, out = self.run_status()
        self.assertEqual(code, 0, out)
        self.assertIn(f"G2 {DATES['G2']}", out)

    def test_every_gate_below_the_stage_is_listed(self):
        self.episode(stage=11, G2=True)
        code, d = self.data()
        self.assertEqual(code, 1)
        self.assertEqual([b["gate"] for b in d["blocked"]], ["G1", "G3", "G4"])

    def test_stage_at_the_gate_is_not_blocked(self):
        self.episode(stage=4, G1=True)
        code, out = self.run_status()
        self.assertEqual(code, 0, out)
        self.assertNotIn("BLOCKED", out)

    def test_usage_errors_exit_2(self):
        (self.ep / "EPISODE.md").unlink()
        self.assertEqual(self.run_status()[0], 2)
        (self.ep / "EPISODE.md").write_text("# no front matter\n", encoding="utf-8")
        self.assertEqual(self.run_status()[0], 2)
        (self.ep / "EPISODE.md").write_text("---\nstage: [1\n---\n", encoding="utf-8")
        self.assertEqual(self.run_status()[0], 2)
        (self.ep / "EPISODE.md").write_text("---\nstage: soon\n---\n", encoding="utf-8")
        self.assertEqual(self.run_status()[0], 2)
        self.assertEqual(self.run_status(ep=False)[0], 2)               # neither an episode nor --ledger
        self.assertEqual(run_main(st.main, [str(self.tmp / "nope")])[0], 2)

    def test_relative_media_is_relative_to_the_repo_root(self):
        self.episode(stage=5, G1=True, G2=True, media="out/no-such-series/ep01")
        code, d = self.data()
        self.assertEqual(code, 0)
        self.assertEqual(d["media"]["dir"], os.path.join(st.LAB, "out/no-such-series/ep01"))
        self.assertFalse(d["media"]["exists"])
        code, d = self.data("--media", str(self.media))                 # --media overrides
        self.assertEqual(d["media"]["dir"], str(self.media))
        self.assertTrue(d["media"]["exists"])


class BudgetTest(StatusCase):
    def test_numbers_equal_billed_requests(self):
        self.mixed_ledger()
        code, out = self.run_status()
        self.assertEqual(code, 1, out)                                   # open requests
        self.assertIn("images 4/40 (36 left) · ok 2 · cut-502 1 · pending 1\n", out)
        self.assertIn("video_seconds 5/30 (25 left) · ok 0 · cut-502 0 · pending 5\n", out)
        self.assertIn(f"models.{PRO} 1/6 (5 left)\n", out)
        billed = ark.billed_requests(ark.ledger_rows(str(self.ledger)))
        code, d = self.data()
        caps = {c["name"]: c for c in d["budget"]["caps"]}
        self.assertEqual(caps["images"]["used"], sum(ark.units(r) for r in billed if r["kind"] == "image"))
        self.assertEqual(caps["video_seconds"]["used"], sum(ark.units(r) for r in billed if r["kind"] == "video"))
        self.assertEqual(caps[f"models.{PRO}"]["used"], sum(ark.units(r) for r in billed if r["model"] == PRO))
        # the same numbers budget_check refuses on
        over = ark.budget_check(ark.load_budget(str(self.ep / "budget.yaml")), ark.ledger_rows(str(self.ledger)),
                                {"kind": "image", "model": LITE, "count": 37})
        self.assertEqual(over, ["images: 4 used + 37 requested > cap 40"])

    def test_open_video_prints_the_resume_command(self):
        self.mixed_ledger()
        code, out = self.run_status()
        clip = self.media / "clips" / "ep01_s03_seedance25_v01.mp4"
        self.assertIn(f"python3 tools/ark.py video --resume-task cgt-123 {clip} --ledger {self.ledger}", out)
        self.assertRegex(out, r"OPEN\s+bb01 video ep01_s03_seedance25_v01\.mp4 · agent film-animator · age \d+[mhd]")

    def test_printed_commands_quote_paths_with_spaces(self):
        clip = self.media / "clips" / "my clip_s03_v01.mp4"
        ledger = self.media / "my ledger.csv"
        self.ledger = ledger
        self.rows([dict(self.vid("x", "pending", "bb01", task="cgt-1"), out=str(clip)),
                   self.img("ep01_s02_L4_bac-thi_v02.png", "pending", "cc01", model=PRO, note="lambda")])
        code, out = self.run_status("--ledger", str(ledger))
        self.assertIn(f"python3 tools/ark.py video --resume-task cgt-1 '{clip}' --ledger '{ledger}'", out)
        self.assertIn(f"lambda-job finish --status-json <file> --image <image> --ledger '{ledger}'", out)

    def test_task_id_comes_from_any_row_of_the_request(self):
        # the final row lost the task id; the pending row of the same request still has it
        self.rows([self.vid("ep01_s03_seedance25_v01.mp4", "pending", "bb01", task="cgt-7"),
                   self.vid("ep01_s03_seedance25_v01.mp4", "failed", "bb01", note="polling stopped")])
        code, out = self.run_status()
        self.assertIn("video --resume-task cgt-7 ", out)

    def test_request_known_only_by_its_task_id_is_shown_in_full(self):
        self.rows([dict(self.vid("ep01_s03_seedance25_v01.mp4", "pending", "x", task="cgt-20261109-abc"), note="")])
        code, out = self.run_status()
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"OPEN\s+task:cgt-20261109-abc video")

    def test_open_lambda_prints_the_finish_hint(self):
        self.mixed_ledger()
        code, out = self.run_status()
        self.assertIn("read jobs/cc01.json from the bucket, then python3 tools/ark.py lambda-job finish "
                      f"--status-json <file> --image <image> --ledger {self.ledger}", out)
        code, d = self.data()
        self.assertEqual(sorted(o["req"] for o in d["attention"]["open"]), ["bb01", "cc01"])

    def test_cut_and_failed_rows_are_listed_but_do_not_block(self):
        self.put("plates", "ep01_s01_L1_nui_v01.png")
        self.rows([self.img("ep01_s01_L1_nui_v01.png", "ok", "aa01"),
                   self.img("ep01_s02_L4_bac-thi_v01.png", "cut-502", "aa03", ts="2026-11-08T10:00:00Z"),
                   self.vid("ep01_s03_seedance25_v01.mp4", "pending", "bb01", task="cgt-9"),
                   self.vid("ep01_s03_seedance25_v01.mp4", "failed", "bb01", task="cgt-9",
                            note="polling stopped (task may still run)")])
        code, out = self.run_status()
        self.assertEqual(code, 0, out)
        self.assertRegex(out, rf"CUT-502\s+2026-11-08T10:00:00Z {LITE} 2K ep01_s02_L4_bac-thi_v01\.png"
                              r".*do not retry unchanged")
        self.assertRegex(out, r"FAILED\s+.*ep01_s03_seedance25_v01\.mp4")
        self.assertIn("video --resume-task cgt-9 ", out)
        self.assertNotRegex(out, r"(?m)^\s+OPEN\s")
        self.assertIn("video_seconds 5/30 (25 left) · ok 0 · cut-502 0 · failed 5 · pending 0\n", out)

    def test_ok_row_without_file_is_missing(self):
        self.rows([self.img("ep01_s01_L1_nui_v01.png", "ok", "aa01"),
                   self.img("ep01_s01_L2_suong_v01.png", "ok", "aa02")])
        self.put("plates", "ep01_s01_L2_suong_v01.png")
        code, out = self.run_status()
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"MISSING\s+aa01 image .*ep01_s01_L1_nui_v01\.png")
        self.assertNotIn("ep01_s01_L2_suong_v01.png", out.split("ATTENTION")[1].split("SHOTS")[0])

    def test_recorded_path_relative_to_the_repo_root_is_found(self):
        # ledger rows written from the repo root, status run from another directory
        self.rows([dict(self.img("a", "ok", "aa01"), out="tests/helpers.py")])
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(self.tmp)
        code, d = self.data()
        self.assertEqual((code, d["attention"]["missing"]), (0, []))

    def test_missing_falls_back_to_the_basename_under_the_media_folder(self):
        # rows written from another working directory: the recorded path does not resolve here
        self.rows([dict(self.img("a", "ok", "aa01"), out="elsewhere/plates/ep01_s01_L1_nui_v01.png"),
                   dict(self.vid("b", "ok", "bb01", task="t1"), out="old/clips/ep01_s03_seedance25_v01.mp4"),
                   dict(self.img("c", "ok", "aa02"), out="elsewhere/plates/ep01_s09_L1_gone_v01.png")])
        self.put("plates/keys", "ep01_s01_L1_nui_v01.png")
        self.put("clips", "ep01_s03_seedance25_v01.mp4")
        code, d = self.data()
        self.assertEqual(code, 1)
        self.assertEqual([m["req"] for m in d["attention"]["missing"]], ["aa02"])

    def test_json_counts_equal_the_text(self):
        self.mixed_ledger()
        code, out = self.run_status()
        jcode, d = self.data()
        self.assertEqual(code, jcode)
        self.assertEqual(sorted(d), ["attention", "blocked", "budget", "forecast", "gate", "gates", "local", "media",
                                     "method", "next", "notes", "shots", "stage", "video_engine"])
        for c in d["budget"]["caps"]:
            self.assertIn(f"{c['name']} {c['used']:g}/{c['cap']:g} ({c['left']:g} left)", out)
        self.assertEqual(len(d["attention"]["open"]), len(re.findall(r"^\s*OPEN\b", out, re.M)))
        self.assertEqual(len(d["attention"]["cut_failed"]), len(re.findall(r"^\s*(CUT-502|FAILED)\b", out, re.M)))
        self.assertEqual(d["stage"]["n"], 5)
        self.assertEqual(d["gates"], {"G1": "2026-11-01", "G2": "2026-11-03", "G3": None, "G4": None})
        self.assertEqual(d["next"], ["- Tạo lớp tranh cho s02.", "  Gọi film-plate-maker, trần 6 ảnh."])
        self.assertEqual(len(d["shots"]["shots"]), 4)

    def test_ledger_only_form(self):
        self.mixed_ledger()
        code, out = self.run_status("--ledger", str(self.ledger), "--budget", str(self.ep / "budget.yaml"), ep=False)
        self.assertEqual(code, 1, out)
        self.assertIn("images 4/40 (36 left) · ok 2 · cut-502 1 · pending 1\n", out)
        self.assertIn("--resume-task cgt-123", out)
        for section in ("STAGE", "NEXT", "SHOTS", "MEDIA", "GATE"):
            self.assertNotIn(section, out)
        self.run_check.assert_not_called()
        code, out = self.run_status("--ledger", str(self.ledger), ep=False)       # no caps
        self.assertEqual(code, 1, out)
        self.assertIn("images 4 (no cap) · ok 2 · cut-502 1 · pending 1\n", out)
        self.assertNotIn("models.", out)
        code, d = self.data("--ledger", str(self.ledger), ep=False)
        self.assertEqual(sorted(d), ["attention", "budget", "local", "notes"])

    def test_ledger_only_clean_ledger_exits_0(self):
        self.put("plates", "ep01_s01_L1_nui_v01.png")
        self.rows([self.img("ep01_s01_L1_nui_v01.png", "ok", "aa01")])
        code, out = self.run_status("--ledger", str(self.ledger), ep=False)
        self.assertEqual(code, 0, out)
        self.assertIn("images 1 (no cap) · ok 1 · cut-502 0 · pending 0\n", out)
        code, out = self.run_status("--ledger", str(self.tmp / "none.csv"), ep=False)
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"note: .*none\.csv.*not found")


class ShotsTest(StatusCase):
    def matrix(self):
        self.prompts([
            ("ep01_s01_L1_nui_v01.png", "s01", "L1", USAGE, "yes"),            # approved
            ("ep01_s02_L1_nui_v01.png", "s02", "L1", "", ""),                  # todo
            ("ep01_s02_L4_bac-thi_v01.png", "s02", "L4", USAGE, "yes"),        # an older version...
            ("ep01_s02_L4_bac-thi_v02.png", "s02", "L4", USAGE, "no"),         # ...the highest decides: rejected
            ("ep01_s02_P1-duoi_bac-thi_v01.png", "s02", "P1-duoi", USAGE, ""),  # made
            ("ep01_s03_L1_nui_v01.png", "s03", "L1", USAGE, ""),               # lost: usage, no file
            ("ep01_s03_L4_bac-thi_v01.png", "s03", "L4", "", "yes"),           # lost: approved, no file
        ])
        self.put("plates", "ep01_s01_L1_nui_v01.png", "ep01_s02_L4_bac-thi_v01.png", "ep01_s02_L4_bac-thi_v02.png",
                 "ep01_s02_P1-duoi_bac-thi_v01.png", "ep01_s03_L4_bac-thi_v09.png")
        self.put("plates/matte", "ep01_s01_L1_nui_v01_alpha.png")

    def test_every_layer_state(self):
        self.matrix()
        code, out = self.run_status()
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"s01\s+L1:approved L2:no-prompt\n")
        self.assertRegex(out, r"s02\s+L1:todo L4:rejected\(next v03\) P1-duoi:made\n")
        self.assertRegex(out, r"s03\s+L1:lost L4:lost · clip no\n")
        self.assertRegex(out, r"s04\s+reuse of s01\n")

    def test_clip_yes_and_orphans(self):
        self.matrix()
        self.put("clips", "ep01_s03_seedance25_v01.mp4", "ep01_s02_notes_v01.txt")
        code, d = self.data()
        shots = {s["shot"]: s for s in d["shots"]["shots"]}
        self.assertIs(shots["s03"]["clip"], True)
        self.assertIsNone(shots["s02"]["clip"])                          # no ai_motion: no clip expected
        self.assertEqual(shots["s04"]["reuse_of"], "s01")
        self.assertEqual({l["layer"]: l["state"] for l in shots["s02"]["layers"]},
                         {"L1": "todo", "L4": "rejected", "P1-duoi": "made"})
        self.assertEqual(d["shots"]["orphans"], ["ep01_s03_L4_bac-thi_v09.png"])   # plates/matte/ is not listed
        code, out = self.run_status()
        self.assertRegex(out, r"s03\s+L1:lost L4:lost · clip yes\n")
        self.assertRegex(out, r"orphans.*ep01_s03_L4_bac-thi_v09\.png")

    def test_next_version_skips_versions_already_on_disk(self):
        self.matrix()
        self.put("plates", "ep01_s02_L4_bac-thi_v04.png")
        code, out = self.run_status()
        self.assertIn("L4:rejected(next v05)", out)


class MediaTest(StatusCase):
    def test_bundled_files_are_not_counted(self):
        self.put("plates", "ep01_s02_L4_bac-thi_v01.png", "ep01_s02_L1_nui_v01.png", "ep01_s01_L1_nui_v01.png",
                 "notes.txt")
        self.put("clips", "ep01_s03_seedance25_v01.mp4")
        (self.media / "bundles").mkdir()
        with zipfile.ZipFile(self.media / "bundles" / "x.zip", "w") as z:
            z.writestr("plates/ep01_s02_L4_bac-thi_v01.png", b"x")
            z.writestr("plates/ep01_s01_L1_nui_v01.png", b"x")
        (self.media / "bundles" / "broken.zip").write_bytes(b"not a zip")
        code, out = self.run_status()
        self.assertEqual(code, 0, out)                                   # unbundled media is reported, not blocking
        self.assertIn("s02: 1 file(s) only in this container", out)
        self.assertIn("s03: 1 file(s) only in this container", out)
        self.assertNotIn("s01: ", out.split("MEDIA")[1].split("GATE")[0])
        self.assertRegex(out, r"note: .*broken\.zip")
        code, d = self.data()
        self.assertEqual(d["media"]["unbundled"], {"s02": 1, "s03": 1})

    def test_renders_highest_version(self):
        self.put("renders", "ep01_draft_v01.mp4", "ep01_draft_v03.mp4", "ep01_draft_v02.mp4", "ep01_final_v01.txt")
        code, d = self.data()
        self.assertEqual(d["media"]["draft"], "ep01_draft_v03.mp4")
        self.assertIsNone(d["media"]["final"])
        code, out = self.run_status()
        self.assertRegex(out, r"draft:? ep01_draft_v03\.mp4")
        self.assertRegex(out, r"final:? (none|-)")

    def test_unsaved_media(self):
        """Renders, takes and stems with no .pulled.sha256 line of their hash are UNSAVED; never blocking."""
        code, out = self.run_status()
        self.assertIn("UNSAVED media: none", out)
        self.put("renders", "ep01_draft_v01.mp4")
        self.put("vo", "VO1.wav", "VO2.wav", "tts-log.json")
        self.put("vo/_stale", "VO3.wav")
        self.put("audio", "music.wav")
        code, out = self.run_status()
        self.assertEqual(code, 0, out)
        self.assertIn("UNSAVED media: 5 file(s) not on Drive (renders 1, vo 3, audio 1)", out)
        self.assertIn("_ChuaDuyet", out)
        self.assertIn("--include-out out/test-series", out)
        self.assertIn("out/test-series/ep01/vo/VO1.wav", out)
        self.assertNotIn("_stale", out)
        self.assertIn("no .pulled.sha256", out)
        pd = self.tmp / "projects" / "test-series"
        lines = [f"{st.drive_sync.sha256(self.media / rel)}  out/test-series/ep01/{rel}\n"
                 for rel in ("renders/ep01_draft_v01.mp4", "vo/VO1.wav", "vo/VO2.wav", "vo/tts-log.json")]
        (pd / ".pulled.sha256").write_text("".join(lines), encoding="utf-8")
        code, d = self.data()
        self.assertEqual(d["media"]["unsaved"]["files"], ["out/test-series/ep01/audio/music.wav"])
        self.assertEqual(d["media"]["unsaved"]["by_kind"], {"audio": 1})
        (self.media / "vo" / "VO1.wav").write_bytes(b"new take")
        code, out = self.run_status()
        self.assertIn("UNSAVED media: 2 file(s) not on Drive (vo 1, audio 1)", out)
        self.assertNotIn("no .pulled.sha256", out)


class GateTest(StatusCase):
    def test_default_gate_is_the_first_undated(self):
        for stage, dated, want in ((2, {}, "G1"), (4, {"G1": True}, "G2"),
                                   (8, {"G1": True, "G2": True}, "G3"),
                                   (10, {"G1": True, "G2": True, "G3": True}, "G4")):
            self.episode(stage=stage, **dated)
            self.assertEqual(self.gate()[1]["gate"], want)
        self.episode(stage=11, G1=True, G2=True, G3=True, G4=True)
        code, d = self.data()
        self.assertIsNone(d["gate"])
        self.assertEqual(code, 0)

    def test_g1_ready_and_not_ready(self):
        self.episode(stage=2)
        code, g = self.gate("--gate", "G1")
        self.assertEqual((code, g["ready"], self.missing(g)), (0, True, []))
        code, out = self.run_status("--gate", "G1")
        self.assertIn("Gate G1: READY", out)
        self.assertIn("[ok] check_episode: Summary: 0 error(s), 0 warning(s)", out)
        (self.ep / "research.md").write_text("  \n", encoding="utf-8")
        (self.ep / "script.md").unlink()
        (self.ep / "budget.yaml").unlink()
        code, g = self.gate("--gate", "G1")
        self.assertEqual((code, g["ready"], g["missing"]), (1, False, 3))
        self.assertEqual(len(self.missing(g)), 3)
        code, out = self.run_status("--gate", "G1")
        self.assertEqual(code, 1)
        self.assertIn("Gate G1: NOT READY (3 missing)", out)
        self.assertEqual(len(re.findall(r"^\s*\[MISSING\]", out, re.M)), 3)
        code, out = self.run_status()                                   # default gate: reported, exit stays 0
        self.assertEqual(code, 0, out)
        self.assertIn("Gate G1: NOT READY (3 missing)", out)

    def test_failing_check_episode_makes_a_gate_not_ready(self):
        self.episode(stage=2)
        self.run_check.return_value = (1, "Summary: 2 error(s), 0 warning(s)")
        code, out = self.run_status("--gate", "G1")
        self.assertEqual(code, 1)
        self.assertIn("[MISSING] check_episode: Summary: 2 error(s), 0 warning(s)", out)
        self.assertIn("Gate G1: NOT READY (1 missing)", out)
        self.run_check.assert_called_with(str(self.ep), str(self.media))

    def test_g2_ready_and_not_ready(self):
        self.episode(stage=4, G1=True)
        self.prompts(ALL_APPROVED[:1] + [("ep01_s01_L2_suong_v01.png", "s01", "L2", USAGE, "")])
        self.put("plates", "ep01_s01_L1_nui_v01.png", "ep01_s01_L2_suong_v01.png")   # s01: approved + made
        code, g = self.gate("--gate", "G2")
        self.assertEqual((code, g["ready"], self.missing(g)), (0, True, []))
        (self.media / "plates" / "ep01_s01_L2_suong_v01.png").unlink()                # no complete shot any more
        self.ledger.unlink()
        code, g = self.gate("--gate", "G2")
        self.assertEqual((code, g["missing"]), (1, 2))
        (self.ep / "prompts.csv").unlink()
        self.episode(stage=4)                                         # G1 not dated: also a BLOCKED line
        code, g = self.gate("--gate", "G2")
        self.assertEqual((code, g["missing"]), (1, 5))

    def test_g3_ready_and_not_ready(self):
        self.episode(stage=8, G1=True, G2=True)
        self.approve_all()
        self.put("clips", "ep01_s03_seedance25_v01.mp4")
        self.put("renders", "ep01_draft_v01.mp4")
        code, g = self.gate("--gate", "G3")
        self.assertEqual((code, g["ready"], self.missing(g)), (0, True, []))
        self.prompts(ALL_APPROVED[:-1] + [("ep01_s03_L4_bac-thi_v01.png", "s03", "L4", USAGE, "")])   # made only
        (self.media / "clips" / "ep01_s03_seedance25_v01.mp4").unlink()
        (self.media / "renders" / "ep01_draft_v01.mp4").unlink()
        self.rows([self.vid("ep01_s03_seedance25_v02.mp4", "pending", "bb01", task="cgt-1")])
        code, g = self.gate("--gate", "G3")
        self.assertEqual((code, g["ready"], g["missing"]), (1, False, 4))
        self.assertTrue(any("s03" in t and "L4" in t for t in self.missing(g)), self.missing(g))

    def test_g4_ready_and_not_ready(self):
        self.episode(stage=10, G1=True, G2=True, G3=True)
        self.approve_all()
        self.put("renders", "ep01_draft_v01.mp4", "ep01_final_v01.mp4")
        code, g = self.gate()
        self.assertEqual((code, g["gate"], g["ready"], self.missing(g)), (0, "G4", True, []))
        (self.media / "renders" / "ep01_final_v01.mp4").unlink()
        self.rows([self.vid("ep01_s03_seedance25_v02.mp4", "pending", "bb01", task="cgt-1")])
        code, g = self.gate("--gate", "G4")
        self.assertEqual((code, g["missing"]), (1, 2))

    def test_a_blocked_stage_makes_the_gate_not_ready(self):
        self.episode(stage=10, G1=True, G3=True)                        # G2 never passed
        self.approve_all()
        self.put("renders", "ep01_final_v01.mp4")
        code, g = self.gate("--gate", "G4")
        self.assertEqual(code, 1)
        self.assertEqual(g["missing"], 2, self.missing(g))               # G2 not dated + BLOCKED line

    def test_check_episode_runs_for_real(self):
        self.real_check()
        self.episode(stage=2)
        code, out = self.run_status("--gate", "G1")
        self.assertRegex(out, r"\[(ok|MISSING)\] check_episode: Summary: \d+ error\(s\), \d+ warning\(s\)")


class ForecastCase(StatusCase):
    HEADER = "shot,from_s,to_s,shot_size,camera,action,layers,code_motion,ai_motion,sound,reuse_of\n"

    def method(self, value):
        """Write `method: <value>` into the front matter (None removes the key)."""
        md = re.sub(r"(?m)^method:.*\n", "", (self.ep / "EPISODE.md").read_text(encoding="utf-8"))
        if value is not None:
            md = md.replace("\nstage:", f"\nmethod: {value}\nstage:", 1)
        (self.ep / "EPISODE.md").write_text(md, encoding="utf-8")

    def shots(self, *lines):
        (self.ep / "shots.csv").write_text(self.HEADER + "".join(l + "\n" for l in lines), encoding="utf-8")

    def budget(self, images=40, video_seconds=30):
        (self.ep / "budget.yaml").write_text(f"images: {images}\nvideo_seconds: {video_seconds}\n",
                                             encoding="utf-8")


class MethodTest(ForecastCase):
    def test_missing_method_is_seedance_by_default(self):
        code, out = self.run_status()
        self.assertEqual(code, 0, out)
        self.assertIn("METHOD seedance (default, no method: in EPISODE.md)\n", out)
        self.assertEqual(self.data()[1]["method"], {"name": "seedance", "source": "default", "raw": None})

    def test_method_from_the_front_matter(self):
        for value in ("layers", "seedance"):
            self.method(value)
            code, out = self.run_status()
            self.assertEqual(code, 0, out)
            self.assertIn(f"METHOD {value}\n", out)
            self.assertEqual(self.data()[1]["method"], {"name": value, "source": "episode", "raw": value})

    def test_invalid_method_is_shown_as_invalid_with_a_note(self):
        for value, raw in (("paper", "paper"), ("Layers", "Layers"), ("[layers, seedance]", ["layers", "seedance"]),
                           ("3", 3), ("", None)):
            self.method(value)
            code, out = self.run_status()
            self.assertEqual(code, 0, value)
            self.assertRegex(out, r"METHOD invalid \(.*\)", value)
            self.assertRegex(out, r"note: EPISODE\.md: method = .* is not layers \| seedance", value)
            m = self.data()[1]["method"]
            self.assertEqual((m["name"], m["source"], m["raw"]), ("seedance", "invalid", raw), value)

    def test_the_fixture_episode_prints_method_and_forecast(self):
        code, out, err = run_main(st.main, [str(EPISODE_FIX)])
        self.assertNotIn("Traceback", out + err)
        self.assertRegex(out, r"(?m)^METHOD seedance$")   # the fixture states its method explicitly
        self.assertRegex(out, r"(?m)^FORECAST")
        self.assertRegex(out, r"(?m)^  images: \d+ to make of 9 layers")
        self.assertRegex(out, r"(?m)^  video_seconds: 10 planned in 1 clip\(s\) \(s03 10\)")


class ForecastTest(ForecastCase):
    def test_layers_method_with_all_code_shots_plans_no_video(self):
        self.method("layers")
        self.shots("s01,0,8,wide,static,Núi,L1;L2,mist-bands,,wind,",
                   "s02,8,15,medium,push-in,Nhân vật,L1;L4;P1-duoi,cloth,,drum,",
                   "s03,15,30,wide,pan-left,Khép lại,L1;L2,mist-bands,,wind,s01")
        self.prompts([("ep01_s01_L1_nui_v01.png", "s01", "L1", USAGE, "yes"),      # approved
                      ("ep01_s01_L2_suong_v01.png", "s01", "L2", USAGE, ""),       # made, not reviewed yet
                      ("ep01_s02_L1_nui_v01.png", "s02", "L1", "", ""),            # todo
                      ("ep01_s02_L4_bac-thi_v01.png", "s02", "L4", USAGE, "no")])  # rejected -> one more image
        self.put("plates", "ep01_s01_L1_nui_v01.png", "ep01_s01_L2_suong_v01.png", "ep01_s02_L4_bac-thi_v01.png")
        code, d = self.data()
        self.assertEqual(code, 0)
        f = d["forecast"]
        self.assertEqual(f["method"], "layers")
        self.assertEqual({k: f["images"][k] for k in ("layers", "approved", "made", "lost", "to_make")},
                         {"layers": 5, "approved": 1, "made": 1, "lost": 0, "to_make": 3})   # reuse shot not counted
        self.assertEqual((f["images"]["left"], f["images"]["verdict"]), (40, "fits"))
        self.assertEqual((f["video_seconds"]["planned"], f["video_seconds"]["clips"]), (0, []))
        self.assertEqual(f["video_seconds"]["verdict"], "fits")
        self.assertEqual((f["conflicts"], f["fits"]), ([], True))
        code, out = self.run_status()
        self.assertIn("FORECAST (method layers)\n", out)
        self.assertIn("  images: 3 to make of 5 layers (1 approved, 1 made) · 40 left · fits\n", out)
        self.assertIn("  video_seconds: 0 planned · 30 left · fits\n", out)
        self.assertNotIn("CONFLICT", out)

    def test_seedance_seconds_round_up_and_clamp_to_the_minimum(self):
        self.shots("s01,0,3,wide,static,Núi,L1,,mist rolls,,",          # 3 s   -> 4 (Seedance minimum)
                   "s02,3,9.2,medium,push-in,Thú,L1;L4,,tail sways,,",  # 6.2 s -> 7
                   "s03,9.2,20,close,drift,Cận,L1;L4,,slow blink,,",    # has a clip already: not planned
                   "s04,20,30,wide,static,Khép,L1,mist-bands,,,")       # code motion only
        self.put("clips", "ep01_s03_seedance25_v01.mp4")
        code, d = self.data()
        v = d["forecast"]["video_seconds"]
        self.assertEqual(v["planned"], 11)
        self.assertEqual(v["clips"], [{"shot": "s01", "seconds": 4}, {"shot": "s02", "seconds": 7}])
        self.assertEqual((v["left"], v["verdict"], d["forecast"]["fits"]), (30, "fits", True))
        self.assertEqual(d["forecast"]["images"]["to_make"], 6)
        code, out = self.run_status()
        self.assertEqual(code, 0, out)                                   # a forecast never changes the exit code
        self.assertIn("  video_seconds: 11 planned in 2 clip(s) (s01 4, s02 7) · 30 left · fits\n", out)

    def test_whole_seconds_are_not_rounded_up_by_float_noise(self):
        self.shots("s01,0.1,5.1,wide,static,Núi,L1,,mist rolls,,",      # 5.1 - 0.1 is not exactly 5.0 in floats
                   "s02,5.1,10.2,wide,static,Núi,L1,,mist rolls,,")     # 5.1 s (give or take) -> 6
        code, d = self.data()
        self.assertEqual([c["seconds"] for c in d["forecast"]["video_seconds"]["clips"]], [5, 6])

    def test_what_is_already_spent_counts_against_the_budget(self):
        self.budget(images=8, video_seconds=12)
        self.put("plates", "ep01_s01_L1_nui_v01.png")
        self.rows([self.img("ep01_s01_L1_nui_v01.png", "ok", "aa01"),
                   self.img("ep01_s01_L1_nui_v02.png", "cut-502", "aa02"),
                   self.vid("ep01_s09_seedance25_v01.mp4", "failed", "bb01", seconds=5)])
        self.prompts([("ep01_s01_L1_nui_v01.png", "s01", "L1", USAGE, "yes")])
        code, d = self.data()
        f = d["forecast"]                                                # SHOTS: 7 layers, s03 9.5 s of ai_motion
        self.assertEqual((f["images"]["to_make"], f["images"]["left"], f["images"]["verdict"]), (6, 6, "fits"))
        self.assertEqual((f["video_seconds"]["planned"], f["video_seconds"]["left"]), (10, 7))
        self.assertEqual((f["video_seconds"]["verdict"], f["video_seconds"]["over"]), ("OVER by 3", 3))
        self.assertIs(f["fits"], False)

    def test_over_budget(self):
        self.budget(images=5, video_seconds=8)
        code, out = self.run_status()
        self.assertEqual(code, 0, out)
        self.assertIn("  images: 7 to make of 7 layers · 5 left · OVER by 2\n", out)
        self.assertIn("  video_seconds: 10 planned in 1 clip(s) (s03 10) · 8 left · OVER by 2\n", out)
        f = self.data()[1]["forecast"]
        self.assertEqual((f["images"]["over"], f["video_seconds"]["over"], f["fits"]), (2, 2, False))

    def test_no_cap_is_not_over(self):
        (self.ep / "budget.yaml").unlink()
        code, d = self.data()
        f = d["forecast"]
        self.assertEqual((f["images"]["left"], f["images"]["verdict"], f["fits"]), (None, "no cap", True))
        self.assertIn("  images: 7 to make of 7 layers · no cap\n", self.run_status()[1])

    def test_layers_method_lists_ai_motion_shots_as_conflicts(self):
        self.method("layers")
        self.budget(video_seconds=0)
        code, d = self.data()
        f = d["forecast"]
        self.assertEqual(f["conflicts"], ["method layers but s03 has ai_motion"])
        self.assertEqual((f["video_seconds"]["planned"], f["video_seconds"]["clips"]), (0, []))
        self.assertEqual(f["video_seconds"]["verdict"], "fits")
        code, out = self.run_status()
        self.assertIn("  CONFLICT: method layers but s03 has ai_motion\n", out)
        self.method("seedance")
        self.assertNotIn("CONFLICT", self.run_status()[1])

    def test_pose_plates_are_separate_layers(self):
        self.method("layers")
        self.shots("s01,0,8,medium,static,Thú vồ mồi,L1;L4;L4b;L4c,pose-cycle,,roar,")
        self.prompts([("ep01_s01_L4_bac-thi_v01.png", "s01", "L4", USAGE, "yes"),
                      ("ep01_s01_L4b_bac-thi_v01.png", "s01", "L4b", USAGE, "")])
        self.put("plates", "ep01_s01_L4_bac-thi_v01.png", "ep01_s01_L4b_bac-thi_v01.png")
        code, d = self.data()
        self.assertEqual({l["layer"]: l["state"] for l in d["shots"]["shots"][0]["layers"]},
                         {"L1": "no-prompt", "L4": "approved", "L4b": "made", "L4c": "no-prompt"})
        i = d["forecast"]["images"]
        self.assertEqual((i["layers"], i["approved"], i["made"], i["to_make"]), (4, 1, 1, 2))

    def test_malformed_numbers_are_noted_and_skipped(self):
        self.shots("s01,0,soon,wide,static,Núi,L1,,mist rolls,,",
                   "s02,,9,medium,push-in,Thú,L1,,tail sways,,",
                   "s03,9,9,close,drift,Cận,L1,,slow blink,,",
                   "s04,12,10,close,drift,Cận,L1,,slow blink,,",
                   "s05,nan,inf,close,drift,Cận,L1,,slow blink,,",
                   "s06,20,25,wide,static,Khép,L1,,mist rolls,,",
                   "s07,x,y,wide,static,Không cần clip,L1,mist-bands,,,")   # no ai_motion: numbers not read
        code, out = self.run_status()
        self.assertEqual(code, 0, out)
        for shot in ("s01", "s02", "s03", "s04", "s05"):
            self.assertRegex(out, rf"note: shots\.csv: {shot} .*not counted", shot)
        self.assertNotRegex(out, r"note: shots\.csv: s0[67]")
        self.assertIn("  video_seconds: 5 planned in 1 clip(s) (s06 5) · 30 left · fits\n", out)
        code, d = self.data()
        self.assertEqual(len(d["forecast"]["skipped"]), 5)
        self.assertEqual(d["forecast"]["images"]["to_make"], 7)

    def test_short_rows_and_a_missing_column_do_not_crash(self):
        (self.ep / "shots.csv").write_text("shot,layers,ai_motion\ns01,L1,blink\ns02\n", encoding="utf-8")
        code, out = self.run_status()
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"note: shots\.csv: s01 .*not counted")
        self.assertIn("  images: 1 to make of 1 layers", out)

    def test_no_shots_csv_no_forecast(self):
        (self.ep / "shots.csv").unlink()
        code, out = self.run_status()
        self.assertNotIn("FORECAST", out)
        self.assertIsNone(self.data()[1]["forecast"])

    def test_json_keys(self):
        code, d = self.data()
        self.assertEqual(set(d["method"]), {"name", "source", "raw"})
        f = d["forecast"]
        self.assertEqual(set(f), {"method", "images", "video_seconds", "conflicts", "skipped", "fits", "local"})
        self.assertEqual(set(f["images"]), {"layers", "approved", "made", "lost", "to_make", "left", "verdict",
                                            "over"})
        self.assertEqual(set(f["video_seconds"]), {"planned", "clips", "left", "verdict", "over"})

    def test_gate_g2_checks_the_forecast(self):
        self.episode(stage=4, G1=True)
        self.prompts(ALL_APPROVED[:2])
        self.put("plates", *[r[0] for r in ALL_APPROVED[:2]])
        self.rows([self.img(ALL_APPROVED[0][0], "ok", "aa01")])
        code, out = self.run_status("--gate", "G2")
        self.assertEqual(code, 0, out)
        self.assertIn("  [ok] forecast fits the budget (images 5 to make, 39 left; video_seconds 10 planned, "
                      "30 left)\n", out)
        self.budget(images=5, video_seconds=30)                          # 1 spent, 4 left, 5 to make
        code, out = self.run_status("--gate", "G2")
        self.assertEqual(code, 1, out)
        self.assertIn("  [MISSING] forecast fits the budget (images 5 to make, 4 left: OVER by 1; "
                      "video_seconds 10 planned, 30 left)\n", out)
        self.assertIn("Gate G2: NOT READY (1 missing)", out)
        code, g = self.gate("--gate", "G1")                              # only G2 asks for it
        self.assertFalse([r for r in g["requirements"] if "forecast" in r["text"]])
        (self.ep / "shots.csv").unlink()
        code, g = self.gate("--gate", "G2")
        self.assertIn("forecast fits the budget (no shots.csv)", self.missing(g))

    def test_gate_g2_is_not_ready_when_a_clip_could_not_be_counted(self):
        self.episode(stage=4, G1=True)
        self.prompts(ALL_APPROVED[:2])
        self.put("plates", *[r[0] for r in ALL_APPROVED[:2]])
        self.rows([self.img(ALL_APPROVED[0][0], "ok", "aa01")])
        self.shots("s01,0,8,wide,static,Núi,L1;L2,mist-bands,,,",
                   "s02,8,soon,close,drift,Cận,L1,,slow blink,,")       # the forecast cannot price this clip
        code, out = self.run_status("--gate", "G2")
        self.assertEqual(code, 1, out)
        self.assertIn("  [MISSING] forecast fits the budget (images 1 to make, 39 left; video_seconds 0 planned, "
                      "30 left; clip of s02 not counted: fix from_s/to_s in shots.csv)\n", out)
        self.shots("s01,0,8,wide,static,Núi,L1;L2,mist-bands,,,",
                   "s02,8,12,close,drift,Cận,L1,,slow blink,,")
        code, out = self.run_status("--gate", "G2")
        self.assertEqual(code, 0, out)
        self.assertIn("  [ok] forecast fits the budget (", out)


class DegradeTest(StatusCase):
    def test_missing_inputs_are_notes_not_errors(self):
        (self.ep / "budget.yaml").unlink()
        (self.ep / "prompts.csv").unlink()
        shutil.rmtree(self.media)
        code, out = self.run_status()
        self.assertEqual(code, 0, out)
        for name in ("budget.yaml", "ledger.csv", "media folder", "prompts.csv"):
            self.assertRegex(out, rf"note: .*{re.escape(name)}", name)
        self.assertIn("images 0 (no cap)", out)
        self.assertRegex(out, r"s01\s+L1:no-prompt L2:no-prompt\n")
        (self.ep / "shots.csv").unlink()
        code, out = self.run_status()
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"note: .*shots\.csv")

    def test_invalid_budget_is_a_note(self):
        self.mixed_ledger()
        for text in ("- 1\n- 2\n", "images: [40\n", "images: 40\nmodels: 3\n", "images: many\nvideo_seconds: 30\n"):
            (self.ep / "budget.yaml").write_text(text, encoding="utf-8")
            code, out = self.run_status()
            self.assertEqual(code, 1, out)                               # the open requests, not the budget
            self.assertRegex(out, r"note: .*budget\.yaml", text)
            self.assertRegex(out, r"images 4 \(no cap\)", text)

    def test_load_budget_that_exits_is_a_note(self):
        with mock.patch.object(ark, "load_budget", side_effect=SystemExit(2)):
            code, out = self.run_status()
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"note: .*budget\.yaml")
        with mock.patch.object(ark, "load_budget", side_effect=SystemExit("budget x: images must be a number")):
            code, out = self.run_status("--gate", "G3")
        self.assertIn("images must be a number", out)
        self.assertEqual(code, 1)

    def test_garbage_ledger_rows_do_not_crash(self):
        self.ledger.write_text(",".join(ark.LEDGER_FIELDS) + "\nyesterday,painting,??,,-3,x,done\ntoo,few\n"
                               "2026-11-09T08:00:00Z,image,m,2K,,abc,pending,,,,,\n", encoding="utf-8")
        code, out = self.run_status()
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"OPEN\s+")

    def test_the_tool_writes_nothing(self):
        self.mixed_ledger()
        self.approve_all()
        self.put("renders", "ep01_draft_v01.mp4")
        before = tree(self.tmp)
        self.real_check()                                                # the real check_episode subprocess too
        for extra in ((), ("--json",), ("--gate", "G3")):
            self.run_status(*extra)
        self.run_status("--ledger", str(self.ledger), "--budget", str(self.ep / "budget.yaml"), ep=False)
        self.assertEqual(tree(self.tmp), before)


class LedgerCloseTest(StatusCase):
    """ark.py ledger-close: an abandoned request is closed (no OPEN line, no MISSING file) but still counted."""

    def test_open_request_prints_the_close_command(self):
        self.mixed_ledger()
        code, out = self.run_status()
        self.assertIn(f"never finishing: python3 tools/ark.py ledger-close --req cc01 --ledger {self.ledger} "
                      "--status abandoned", out)
        code, d = self.data()
        self.assertTrue(all(o["close"].startswith("python3 tools/ark.py ledger-close --req ")
                            for o in d["attention"]["open"]))

    def test_abandoned_is_closed_and_billed(self):
        self.rows([self.img("ep01_s02_L4_bac-thi_v02.png", "pending", "cc01", model=PRO, note="lambda"),
                   self.img("ep01_s02_L4_bac-thi_v02.png", "abandoned", "cc01", model=PRO,
                            note="closed by ledger-close")])
        code, out = self.run_status()
        self.assertEqual(code, 0, out)
        self.assertNotRegex(out, r"(?m)^\s+(OPEN|MISSING)\s")
        self.assertIn("images 1/40 (39 left) · ok 0 · cut-502 0 · abandoned 1 · pending 0\n", out)
        self.assertIn(f"models.{PRO} 1/6 (5 left)\n", out)


class NarrationWatermarkTest(StatusCase):
    """G4 checks vo/tts-log.json of tools/tts/vieneu_tts.py: every take rendered with the watermark on (#37)."""

    def setUp(self):
        super().setUp()
        self.episode(stage=10, G1=True, G2=True, G3=True)
        self.approve_all()
        self.put("renders", "ep01_draft_v01.mp4", "ep01_final_v01.mp4")

    def vo_log(self, entries=None, raw=None):
        (self.media / "vo").mkdir(parents=True, exist_ok=True)
        (self.media / "vo" / "tts-log.json").write_text(raw if raw is not None else json.dumps(entries),
                                                       encoding="utf-8")

    def requirement(self, g):
        return [r for r in g["requirements"] if r["text"].startswith("narration watermark")]

    def test_no_narration_is_not_applicable(self):
        code, g = self.gate("--gate", "G4")
        self.assertEqual((code, g["ready"]), (0, True))
        self.assertEqual(self.requirement(g), [{"ok": True, "text": "narration watermark: n/a (no vo/tts-log.json)"}])

    def test_every_take_watermarked_is_ready(self):
        self.vo_log([{"id": "VO1", "watermark": True}, {"id": "VO2", "watermark": True}])
        code, g = self.gate("--gate", "G4")
        self.assertEqual((code, g["ready"]), (0, True), self.missing(g))
        self.assertIn("(2)", self.requirement(g)[0]["text"])

    def test_a_take_without_watermark_blocks_g4(self):
        self.vo_log([{"id": "VO1", "watermark": True}, {"id": "VO2", "watermark": False}, {"id": "VO3"}])
        code, g = self.gate("--gate", "G4")
        self.assertEqual((code, g["ready"], g["missing"]), (1, False, 1))
        self.assertIn("off: VO2, VO3", self.missing(g)[0])
        self.assertIn("--require-watermark", self.missing(g)[0])
        code, out = self.run_status("--gate", "G4")
        self.assertIn("narration watermark", out)

    def test_takes_cut_from_the_script_are_ignored(self):
        """vieneu_tts.py keeps log entries of lines the script no longer has; --check ignores them, so G4 does too."""
        self.vo_log([{"id": f"VO{i}", "watermark": True} for i in range(1, 6)]
                    + [{"id": "VO6", "watermark": False}, {"id": "VO7"}])
        code, g = self.gate("--gate", "G4")
        self.assertEqual((code, g["ready"]), (0, True), self.missing(g))
        self.assertIn("(5)", self.requirement(g)[0]["text"])

    def test_takes_from_vo_lines_json_are_checked(self):
        """--lines (vo-lines.json) takes have their own ids: G4 checks them instead of calling them missing."""
        self.vo_log([{"id": f"N{i:02d}", "watermark": True} for i in range(1, 4)])
        code, g = self.gate("--gate", "G4")
        self.assertEqual((code, g["ready"]), (0, True), self.missing(g))
        self.vo_log([{"id": "N01", "watermark": True}, {"id": "N02", "watermark": False}])
        code, g = self.gate("--gate", "G4")
        self.assertEqual((code, g["missing"]), (1, 1), self.missing(g))

    def test_unreadable_log_blocks_g4(self):
        for raw in ("{broken", "{}", "[]"):
            with self.subTest(raw=raw):
                self.vo_log(raw=raw)
                code, g = self.gate("--gate", "G4")
                self.assertEqual((code, g["missing"]), (1, 1), self.missing(g))

    def test_other_gates_do_not_look_at_it(self):
        self.vo_log([{"id": "VO1", "watermark": False}])
        self.episode(stage=8, G1=True, G2=True)
        self.put("clips", "ep01_s03_seedance25_v01.mp4")
        code, g = self.gate("--gate", "G3")
        self.assertEqual(self.requirement(g), [])


if __name__ == "__main__":
    unittest.main()
