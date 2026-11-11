"""tools/ark.py image-batch: a whole CSV of plates in one command. Validation of every row before anything is sent,
skip of existing outputs, one budget check for the batch, bounded parallelism, one pending + one final ledger row per
request, no retry. Network is always mocked."""
import csv, os, signal, threading, time
from pathlib import Path
from unittest import mock

from PIL import Image

from test_ark import ArkCase, ark, tiny_jpeg_b64

COLUMNS = ["id", "prompt", "out", "size", "model", "ref", "seed", "negative"]
OK = {"data": [{"b64_json": tiny_jpeg_b64()}], "usage": {"generated_images": 1}}
CUT = SystemExit(f"{ark.CUT_PREFIX} 31s: the agent proxy cuts synchronous requests at ~30s.")


class ScriptedArk:
    """ark.call() stand-in that answers by prompt: script[prompt] is a response dict, an exception to raise or a
    callable. Thread-safe; records every request and the largest number of requests in flight."""

    def __init__(self, script=None, delay=0.0):
        self.script, self.delay = script or {}, delay
        self.calls, self.lock = [], threading.Lock()
        self.active = self.peak = 0

    def __call__(self, method, path, body=None, timeout=300):
        assert (method, path) == ("POST", "/images/generations"), (method, path)
        with self.lock:
            self.calls.append(body)
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            what = self.script.get(body["prompt"], OK)
            if callable(what):
                return what(body)
            if isinstance(what, BaseException):      # errors come back at once, successes after `delay`
                raise what
            if self.delay:
                time.sleep(self.delay)
            return what
        finally:
            with self.lock:
                self.active -= 1

    def prompts(self):
        return sorted(b["prompt"] for b in self.calls)


class BatchCase(ArkCase):
    def setUp(self):
        super().setUp()
        self.outdir = self.tmp / "plates"
        self.csv = str(self.tmp / "jobs.csv")

    def out(self, name):
        return str(self.outdir / name)

    def write_jobs(self, rows, columns=COLUMNS, path=None):
        with open(path or self.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=columns)
            w.writeheader()
            w.writerows(rows)

    def simple(self, n, **extra):
        """n rows p1..pn with prompt 'prompt k' and out plates/pk_v01.png."""
        return [dict({"id": f"p{k}", "prompt": f"prompt {k}", "out": self.out(f"p{k}_v01.png")}, **extra)
                for k in range(1, n + 1)]

    def scripted(self, script=None, delay=0.0):
        f = ScriptedArk(script, delay)
        p = mock.patch.object(ark, "call", f)
        p.start()
        self.addCleanup(p.stop)
        return f

    def batch(self, *extra, cost=None):
        return self.run_ark("image-batch", self.csv, *extra, *(self.cost if cost is None else cost))

    def ledger_bytes(self):
        return Path(self.ledger).read_bytes() if os.path.exists(self.ledger) else None

    def requests(self):
        """ledger rows grouped by req id -> list of statuses."""
        groups = {}
        for r in self.rows():
            groups.setdefault(ark.req_id(r), []).append(r["status"])
        return groups

    def summary(self, so):
        return [line for line in so.splitlines() if line.startswith("batch:")][-1]


class TestValidation(BatchCase):
    def refused(self, *extra, code=2):
        f = self.scripted()
        before = self.ledger_bytes()
        got, so, err = self.batch(*extra)
        self.assertEqual(got, code, err)
        self.assertEqual(f.calls, [])
        self.assertEqual(self.ledger_bytes(), before)
        self.assertFalse(self.outdir.exists())
        self.assertNotIn("Traceback", err)
        return err

    def test_every_bad_row_is_listed_and_nothing_is_sent(self):
        rows = self.simple(6)
        rows[1]["size"] = "4K"                                  # p2: the proxy would cut it
        rows[2]["ref"] = str(self.tmp / "missing.png")          # p3: no such ref
        rows[3]["prompt"] = ""                                  # p4: no prompt
        rows[4]["model"] = "dola-seedream-5-0-pro-260628"       # p5: pro model
        rows[5]["seed"] = "abc"                                 # p6: bad seed
        self.write_jobs(rows)
        err = self.refused()
        self.assertIn("p2: ", err)
        self.assertIn("larger than 2K", err)
        self.assertIn("p3: no such file", err)
        self.assertIn("p4: prompt is empty", err)
        self.assertIn("p5: ", err)
        self.assertIn("p6: seed", err)
        self.assertNotIn("p1:", err)
        self.assertNotIn("--force", err)
        self.assertIn("5 problem(s)", err)

    def test_duplicate_ids_and_duplicate_outs(self):
        rows = self.simple(3)
        rows[1]["id"] = "p1"
        rows[2]["out"] = os.path.join(str(self.outdir), ".", "p1_v01.png")     # the same file, spelled differently
        self.write_jobs(rows)
        err = self.refused()
        self.assertIn("duplicate id 'p1'", err)
        self.assertIn("p3: out", err)
        self.assertIn("same file as row p1", err)

    def test_unknown_column_is_named(self):
        self.write_jobs([dict(r, sizes="2K") for r in self.simple(1)], columns=COLUMNS + ["sizes"])
        err = self.refused()
        self.assertIn("unknown column", err)
        self.assertIn("sizes", err)

    def test_missing_required_column(self):
        self.write_jobs([{"id": "a", "prompt": "x"}], columns=["id", "prompt"])
        self.assertIn("missing column", self.refused())

    def test_missing_id_out_and_empty_file(self):
        self.write_jobs([{"id": "", "prompt": "x", "out": self.out("a.png")}, {"id": "b", "prompt": "x", "out": ""}])
        err = self.refused()
        self.assertIn("line 2: id is empty", err)
        self.assertIn("b: out is empty", err)
        self.write_jobs([])
        self.assertIn("no rows", self.refused())

    def test_missing_csv_and_non_utf8_csv(self):
        self.assertIn("cannot read", self.refused())
        Path(self.csv).write_bytes("id,prompt,out\na,caf\xe9,o.png\n".encode("latin-1"))
        self.assertIn("cannot read", self.refused())

    def test_ref_that_is_not_an_image(self):
        bad = self.tmp / "notes.png"
        bad.write_text("not an image")
        rows = self.simple(2)
        rows[1]["ref"] = str(bad)
        self.write_jobs(rows)
        self.assertIn("p2: cannot read image", self.refused())

    def test_only_with_an_unknown_id(self):
        self.write_jobs(self.simple(2))
        self.assertIn("--only: no row with id 'zz'", self.refused("--only", "p1", "zz"))

    def test_budget_and_ledger_are_required(self):
        self.write_jobs(self.simple(1))
        f = self.scripted()
        code, _, err = self.batch(cost=[])
        self.assertEqual(code, 2)
        self.assertIn("without a budget", err)
        self.assertEqual(f.calls, [])

    def test_no_overwrite_flag_and_parallel_limit(self):
        self.write_jobs(self.simple(1))
        self.assertEqual(self.batch("--overwrite")[0], 2)
        self.assertEqual(self.batch("--parallel", "5")[0], 2)
        self.assertEqual(self.batch("--parallel", "0")[0], 2)

    def test_budget_yaml_problem_is_exit_2(self):
        self.write_jobs(self.simple(2))
        self.write_budget("image: 5\n")
        self.assertIn("did you mean 'images'", self.refused())
        self.write_budget("video_seconds: 5\n")
        self.assertIn("has no cap for image", self.refused())

    def test_ledger_required_and_foreign_ledger_header(self):
        self.write_jobs(self.simple(2))
        self.write_budget("images: 9\nledger_required: true\n")
        self.assertIn("ledger_required", self.refused())
        self.write_budget("images: 9\n")
        Path(self.ledger).write_text("a,b,c\n1,2,3\n")
        self.assertIn("ledger header mismatch", self.refused())

    def test_help_documents_the_csv(self):
        code, so, _ = self.run_ark("image-batch", "--help")
        self.assertEqual(code, 0)
        for word in COLUMNS + ["@", "--parallel", "--dry-run", "--only", "skip"]:
            self.assertIn(word, so)


class TestRun(BatchCase):
    def test_six_rows_parallel_three(self):
        self.write_jobs(self.simple(6))
        f = self.scripted(delay=0.05)
        code, so, err = self.batch("--parallel", "3")
        self.assertEqual(code, 0, err)
        self.assertEqual(f.prompts(), [f"prompt {k}" for k in range(1, 7)])
        self.assertLessEqual(f.peak, 3)
        self.assertGreater(f.peak, 1)
        groups = self.requests()
        self.assertEqual(len(groups), 6)
        self.assertNotIn(None, groups)
        for statuses in groups.values():
            self.assertEqual(statuses, ["pending", "ok"])
        rows = ark.ledger_rows(self.ledger)
        self.assertEqual(len(rows), 12)
        self.assertEqual({tuple(r.keys()) for r in rows}, {tuple(ark.LEDGER_FIELDS)})
        billed = ark.billed_requests(rows)
        self.assertEqual(sum(ark.units(r) for r in billed), 6)
        self.assertEqual({r["agent"] for r in rows}, {"film-test-agent"})
        for k in range(1, 7):
            with Image.open(self.out(f"p{k}_v01.png")) as im:
                self.assertEqual(im.format, "PNG")
            self.assertRegex(so, rf"(?m)^ok p{k} {self.out(f'p{k}_v01.png')} \d+\.\ds$")
        self.assertEqual(self.summary(so), "batch: 6 ok, 0 failed, 0 cut-502, 0 skipped, 0 not started · images used 6/100")
        self.assertEqual([p.name for p in self.outdir.iterdir() if ".part" in p.name], [])

    def test_default_parallel_is_three_and_one_is_sequential(self):
        self.write_jobs(self.simple(6))
        f = self.scripted(delay=0.05)
        self.assertEqual(self.batch()[0], 0)
        self.assertEqual(f.peak, 3)
        self.write_jobs(self.simple(3, size="1K"))
        for k in range(1, 4):
            os.remove(self.out(f"p{k}_v01.png"))
        g = self.scripted(delay=0.02)
        self.assertEqual(self.batch("--parallel", "1")[0], 0)
        self.assertEqual(g.peak, 1)
        self.assertEqual([b["prompt"] for b in g.calls], ["prompt 1", "prompt 2", "prompt 3"])     # CSV order

    def test_row_fields_reach_the_request_and_the_ledger(self):
        ref = self.tmp / "ref.png"
        Image.new("RGBA", (8, 8), (1, 2, 3, 128)).save(ref)
        self.write_jobs([
            {"id": "a", "prompt": "one", "out": self.out("a.png"), "size": "2560x1440", "model": ark.IMAGE_FAST,
             "ref": f"{ref}; {ref}", "seed": "7", "negative": "text, watermark"},
            {"id": "b", "prompt": "two", "out": self.out("b.jpg")}])
        f = self.scripted()
        code, _, err = self.batch("--parallel", "1")
        self.assertEqual(code, 0, err)
        a, b = f.calls
        self.assertEqual((a["model"], a["size"], a["seed"], a["negative_prompt"]),
                         (ark.IMAGE_FAST, "2560x1440", 7, "text, watermark"))
        self.assertEqual(len(a["image"]), 2)
        self.assertTrue(a["image"][0].startswith("data:image/jpeg;base64,"))
        self.assertEqual((a["response_format"], a["watermark"]), ("b64_json", False))
        self.assertEqual((b["model"], b["size"]), (ark.IMAGE_DEFAULT, "2K"))
        for key in ("seed", "negative_prompt", "image"):
            self.assertNotIn(key, b)
        final = [r for r in self.rows() if r["status"] == "ok"]
        self.assertEqual([(r["model"], r["size"], r["out"], r["count"]) for r in final],
                         [(ark.IMAGE_FAST, "2560x1440", self.out("a.png"), "1"),
                          (ark.IMAGE_DEFAULT, "2K", self.out("b.jpg"), "1")])
        with Image.open(self.out("b.jpg")) as im:
            self.assertEqual(im.format, "JPEG")

    def test_fast_flag_is_the_default_model_of_rows_without_one(self):
        rows = self.simple(2)
        rows[1]["model"] = ark.IMAGE_DEFAULT
        self.write_jobs(rows)
        f = self.scripted()
        self.assertEqual(self.batch("--fast", "--parallel", "1")[0], 0)
        self.assertEqual([b["model"] for b in f.calls], [ark.IMAGE_FAST, ark.IMAGE_DEFAULT])

    def test_prompt_from_a_file_next_to_the_csv(self):
        sub = self.tmp / "ep"
        (sub / "prompts").mkdir(parents=True)
        (sub / "prompts" / "a.txt").write_text("núi mờ sương\nmực loang\n", encoding="utf-8")
        self.csv = str(sub / "jobs.csv")
        self.write_jobs([{"id": "a", "prompt": "@prompts/a.txt", "out": self.out("a.png")}])
        f = self.scripted()
        code, _, err = self.batch()
        self.assertEqual(code, 0, err)
        self.assertEqual(f.calls[0]["prompt"], "núi mờ sương\nmực loang")

    def test_prompt_file_missing_or_empty(self):
        (self.tmp / "empty.txt").write_text("  \n")
        self.write_jobs([{"id": "a", "prompt": "@nope.txt", "out": self.out("a.png")},
                         {"id": "b", "prompt": "@empty.txt", "out": self.out("b.png")}])
        f = self.scripted()
        code, _, err = self.batch()
        self.assertEqual(code, 2)
        self.assertIn("a: prompt file", err)
        self.assertIn("b: prompt is empty", err)
        self.assertEqual(f.calls, [])

    def test_only_selects_rows(self):
        self.write_jobs(self.simple(4))
        f = self.scripted()
        code, so, err = self.batch("--only", "p2", "p4")
        self.assertEqual(code, 0, err)
        self.assertEqual(f.prompts(), ["prompt 2", "prompt 4"])
        self.assertEqual(len(self.requests()), 2)
        self.assertFalse(os.path.exists(self.out("p1_v01.png")))
        self.assertIn("2 ok", self.summary(so))

    def test_existing_outputs_are_skipped(self):
        self.write_jobs(self.simple(3))
        self.outdir.mkdir()
        Path(self.out("p2_v01.png")).write_bytes(b"paid for")
        Path(self.out("p3_v01.png")).write_bytes(b"")           # an empty stub is not an output
        f = self.scripted()
        code, so, err = self.batch()
        self.assertEqual(code, 0, err)
        self.assertEqual(f.prompts(), ["prompt 1", "prompt 3"])
        self.assertIn("skip p2: output exists", so)
        self.assertEqual(Path(self.out("p2_v01.png")).read_bytes(), b"paid for")
        self.assertEqual(self.summary(so), "batch: 2 ok, 0 failed, 0 cut-502, 1 skipped, 0 not started · images used 2/100")

    def test_everything_skipped_sends_nothing_and_writes_nothing(self):
        self.write_jobs(self.simple(2))
        self.outdir.mkdir()
        for k in (1, 2):
            Path(self.out(f"p{k}_v01.png")).write_bytes(b"x")
        f = self.scripted()
        code, so, _ = self.batch()
        self.assertEqual(code, 0)
        self.assertEqual(f.calls, [])
        self.assertIsNone(self.ledger_bytes())
        self.assertIn("0 ok, 0 failed, 0 cut-502, 2 skipped", self.summary(so))

    def test_one_failure_does_not_stop_the_others(self):
        self.write_jobs(self.simple(5))
        f = self.scripted({"prompt 2": SystemExit("HTTP 500: upstream exploded")})
        code, so, err = self.batch("--parallel", "2")
        self.assertEqual(code, 1, err)
        self.assertEqual(len(f.calls), 5)
        by = sorted(self.requests().values())
        self.assertEqual(by, [["pending", "failed"]] + [["pending", "ok"]] * 4)
        failed = [r for r in self.rows() if r["status"] == "failed"][0]
        self.assertIn("HTTP 500: upstream exploded", failed["note"])
        self.assertEqual(failed["out"], self.out("p2_v01.png"))
        self.assertFalse(os.path.exists(self.out("p2_v01.png")))
        self.assertRegex(so, r"(?m)^failed p2 \S+ \d+\.\ds")
        self.assertIn("HTTP 500", so + err)
        self.assertEqual(self.summary(so), "batch: 4 ok, 1 failed, 0 cut-502, 0 skipped, 0 not started · images used 5/100")

    def test_cut_502_is_not_retried_and_stays_counted(self):
        self.write_jobs(self.simple(3))
        f = self.scripted({"prompt 1": CUT})
        code, so, err = self.batch("--parallel", "1")
        self.assertEqual(code, 1, err)
        self.assertEqual([b["prompt"] for b in f.calls], ["prompt 1", "prompt 2", "prompt 3"])     # once each
        self.assertEqual(sorted(self.requests().values()), [["pending", "cut-502"]] + [["pending", "ok"]] * 2)
        self.assertRegex(so, r"(?m)^cut-502 p1 ")
        self.assertEqual(self.summary(so), "batch: 2 ok, 0 failed, 1 cut-502, 0 skipped, 0 not started · images used 3/100")

    def test_save_failure_is_a_failed_row_and_leaves_no_file(self):
        self.write_jobs(self.simple(2))
        self.scripted({"prompt 1": {"data": [{"b64_json": "!!not base64!!"}], "usage": {}}})
        code, so, err = self.batch("--parallel", "1")
        self.assertEqual(code, 1, err)
        failed = [r for r in self.rows() if r["status"] == "failed"][0]
        self.assertIn("save-failed", failed["note"])
        self.assertEqual(sorted(p.name for p in self.outdir.iterdir()), ["p2_v01.png"])

    def test_rerun_after_partial_success_sends_only_the_missing_rows(self):
        self.write_jobs(self.simple(4))
        self.scripted({"prompt 2": SystemExit("HTTP 500: x"), "prompt 4": SystemExit("HTTP 500: x")})
        self.assertEqual(self.batch()[0], 1)
        g = self.scripted()
        code, so, err = self.batch()
        self.assertEqual(code, 0, err)
        self.assertEqual(g.prompts(), ["prompt 2", "prompt 4"])
        self.assertEqual(self.summary(so), "batch: 2 ok, 0 failed, 0 cut-502, 2 skipped, 0 not started · images used 6/100")
        h = self.scripted()
        self.assertEqual(self.batch()[0], 0)
        self.assertEqual(h.calls, [])

    def test_no_budget_runs_without_a_ledger(self):
        self.write_jobs(self.simple(2))
        f = self.scripted()
        code, so, err = self.batch("--no-budget", cost=[])
        self.assertEqual(code, 0, err)
        self.assertEqual(len(f.calls), 2)
        self.assertIn("--no-budget", err)
        self.assertFalse(os.path.exists(self.ledger))
        self.assertIn("images used -/-", self.summary(so))


class TestBudget(BatchCase):
    def test_batch_over_the_images_cap_is_refused_once(self):
        self.write_budget("images: 5\n")
        self.seed_ledger({"kind": "image", "model": ark.IMAGE_DEFAULT, "count": 1, "status": "ok", "note": "req=aa"},
                         {"kind": "image", "model": ark.IMAGE_DEFAULT, "count": 1, "status": "pending", "note": "req=bb"})
        self.write_jobs(self.simple(4))
        f = self.scripted()
        code, so, err = self.batch()
        self.assertEqual(code, 3, err)
        self.assertEqual(f.calls, [])
        self.assertIn("images: 2 used + 4 requested > cap 5", err)
        rows = self.rows()
        self.assertEqual([r["status"] for r in rows], ["ok", "pending", "refused-budget"])
        self.assertEqual(rows[-1]["note"], "batch of 4: images: 2 used + 4 requested > cap 5")
        self.assertEqual((rows[-1]["kind"], rows[-1]["count"], rows[-1]["out"]), ("image", "4", self.csv))
        self.assertFalse(self.outdir.exists())

    def test_batch_over_a_model_cap(self):
        self.write_budget(f"images: 100\nmodels:\n  {ark.IMAGE_FAST}: 2\n")
        rows = self.simple(5)
        for r in rows[:3]:
            r["model"] = ark.IMAGE_FAST
        self.write_jobs(rows)
        f = self.scripted()
        code, _, err = self.batch()
        self.assertEqual(code, 3)
        self.assertEqual(f.calls, [])
        self.assertIn(f"models.{ark.IMAGE_FAST}: 0 used + 3 requested > cap 2", err)
        self.assertEqual([r["status"] for r in self.rows()], ["refused-budget"])

    def test_skipped_rows_do_not_count_against_the_cap(self):
        self.write_budget("images: 2\n")
        self.write_jobs(self.simple(3))
        self.outdir.mkdir()
        Path(self.out("p1_v01.png")).write_bytes(b"x")
        f = self.scripted()
        code, so, err = self.batch()
        self.assertEqual(code, 0, err)
        self.assertEqual(len(f.calls), 2)
        self.assertIn("images used 2/2", self.summary(so))

    def test_dry_run_prints_the_plan_and_writes_nothing(self):
        self.write_jobs(self.simple(3))
        self.outdir.mkdir()
        Path(self.out("p3_v01.png")).write_bytes(b"x")
        f = self.scripted()
        code, so, err = self.batch("--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual(f.calls, [])
        self.assertIsNone(self.ledger_bytes())
        self.assertEqual(sorted(p.name for p in self.outdir.iterdir()), ["p3_v01.png"])
        self.assertRegex(so, rf"(?m)^send p1 {ark.IMAGE_DEFAULT} 2K {self.out('p1_v01.png')}$")
        self.assertIn("skip p3: output exists", so)
        self.assertIn("dry-run: 2 to send, 1 skipped", so)
        self.assertIn("images 0 used + 2 = 2/100", so)

    def test_dry_run_over_the_cap_is_exit_3_without_a_row(self):
        self.write_budget("images: 1\n")
        self.write_jobs(self.simple(2))
        f = self.scripted()
        code, _, err = self.batch("--dry-run")
        self.assertEqual(code, 3)
        self.assertIn("images: 0 used + 2 requested > cap 1", err)
        self.assertEqual(f.calls, [])
        self.assertIsNone(self.ledger_bytes())

    def test_dry_run_validation_is_exit_2(self):
        self.write_jobs(self.simple(1, size="8K"))
        self.assertEqual(self.batch("--dry-run")[0], 2)

    def test_budget_refusal_mid_batch_stops_scheduling(self):
        """Another agent takes the last images while the batch runs: reserve() refuses, later rows never start."""
        self.write_budget("images: 4\n")
        self.write_jobs(self.simple(4))

        def rival(body):        # a parallel agent reserves two images during the first request
            for k in ("r1", "r2"):
                ark.ledger_append(self.ledger, {"kind": "image", "model": ark.IMAGE_DEFAULT, "count": 1,
                                                "status": "pending", "note": f"req={k}"})
            return OK
        f = self.scripted({"prompt 1": rival})
        code, so, err = self.batch("--parallel", "1")
        self.assertEqual(code, 3, err)
        self.assertEqual([b["prompt"] for b in f.calls], ["prompt 1", "prompt 2"])
        self.assertEqual([r["status"] for r in self.rows()],
                         ["pending", "pending", "pending", "ok", "pending", "ok", "refused-budget"])
        self.assertIn("REFUSED", err)
        self.assertEqual(self.summary(so), "batch: 2 ok, 0 failed, 0 cut-502, 0 skipped, 2 not started · images used 4/4")
        self.assertFalse(os.path.exists(self.out("p4_v01.png")))

    def test_auth_error_stops_scheduling(self):
        for message in ("HTTP 401: bad key", "HTTP 403: forbidden",
                        'HTTP 400: {"error":{"code":"AccountOverdueError","message":"account balance is overdue"}}'):
            with self.subTest(message=message):
                if os.path.exists(self.ledger):
                    os.remove(self.ledger)
                self.write_jobs(self.simple(4))
                f = self.scripted({"prompt 1": SystemExit(message)})
                code, so, err = self.batch("--parallel", "1")
                self.assertEqual(code, 1, err)
                self.assertEqual(len(f.calls), 1)
                self.assertEqual(self.requests().popitem()[1], ["pending", "failed"])
                self.assertIn("0 ok, 1 failed, 0 cut-502, 0 skipped, 3 not started", self.summary(so))
                self.assertIn("stopped", err)

    def test_in_flight_rows_finish_after_a_stop(self):
        self.write_jobs(self.simple(6))
        f = self.scripted({"prompt 1": SystemExit("HTTP 401: bad key")}, delay=0.1)
        code, so, _ = self.batch("--parallel", "3")
        self.assertEqual(code, 1)
        self.assertEqual(len(f.calls), 3)                    # the two started next to it finish, nothing new starts
        self.assertEqual(sorted(self.requests().values()), [["pending", "failed"], ["pending", "ok"], ["pending", "ok"]])
        self.assertIn("2 ok, 1 failed, 0 cut-502, 0 skipped, 3 not started", self.summary(so))


class TestSignals(BatchCase):
    def run_signalled(self, signum):
        self.write_jobs(self.simple(5))

        def kill(body):
            os.kill(os.getpid(), signum)
            time.sleep(0.3)         # the handler runs in the main thread meanwhile
            return OK
        f = self.scripted({"prompt 1": kill, "prompt 2": lambda body: (time.sleep(0.3), OK)[1]})
        before = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
        code, so, err = self.batch("--parallel", "2")
        self.assertEqual({s: signal.getsignal(s) for s in before}, before)
        return f, code, so, err

    def test_sigterm_lets_in_flight_rows_finish(self):
        f, code, so, err = self.run_signalled(signal.SIGTERM)
        self.assertEqual(code, 143, err)
        self.assertEqual(f.prompts(), ["prompt 1", "prompt 2"])
        self.assertEqual(sorted(self.requests().values()), [["pending", "ok"], ["pending", "ok"]])
        self.assertTrue(os.path.exists(self.out("p1_v01.png")))
        self.assertIn("SIGTERM", err)
        self.assertEqual(self.summary(so), "batch: 2 ok, 0 failed, 0 cut-502, 0 skipped, 3 not started · images used 2/100")

    def test_sigint_exits_130(self):
        f, code, so, err = self.run_signalled(signal.SIGINT)
        self.assertEqual(code, 130, err)
        self.assertEqual(len(f.calls), 2)
        self.assertIn("3 not started", self.summary(so))
