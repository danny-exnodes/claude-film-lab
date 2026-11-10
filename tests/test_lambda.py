"""Lambda path: ark.py lambda-job prepare/finish, ledger-merge, ledger_required, and the worker's duplicate guard.
No network, no AWS: boto3 is a stub and ark.call is never reached."""
import csv, importlib.util, io, json, os, sys, types, unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from helpers import REPO
from test_ark import ArkCase, ark

PRO = "dola-seedream-5-0-pro-260628"


class LambdaCase(ArkCase):
    def prepare(self, *extra, out=None):
        out = out or str(self.tmp / "plates" / "a.png")
        code, stdout, err = self.run_ark("lambda-job", "prepare", "a prompt", out, *extra, *self.cost)
        return code, stdout, err

    def status_file(self, job, **fields):
        path = str(self.tmp / f"{job}.json")
        with open(path, "w") as f:
            json.dump({"job_id": job, **fields}, f)
        return path

    def downloaded(self):
        path = str(self.tmp / "dl.jpg")
        Image.new("RGB", (8, 8), (200, 10, 10)).save(path, "JPEG")
        return path


class TestPrepare(LambdaCase):
    def test_payload_and_pending_row(self):
        f = self.fake()
        code, out, _ = self.prepare("--size", "4K")
        self.assertEqual(code, 0)
        self.assertEqual(f.calls, [])                       # prepare never calls the API
        payload = json.loads(out)
        self.assertEqual((payload["model"], payload["size"], payload["prompt"]), (PRO, "4K", "a prompt"))
        row, = self.rows()
        self.assertEqual((row["status"], row["kind"], row["model"], row["size"]), ("pending", "image", PRO, "4K"))
        self.assertEqual(ark.req_id(row), payload["job_id"])
        self.assertIn("lambda", row["note"])
        self.assertNotIn("ref_keys", payload)

    def test_needs_ledger(self):
        code, out, err = self.run_ark("lambda-job", "prepare", "x", str(self.tmp / "a.png"), "--no-budget")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("no ledger, no Lambda call", err)

    def test_needs_budget_or_no_budget(self):
        code, out, _ = self.run_ark("lambda-job", "prepare", "x", str(self.tmp / "a.png"), "--ledger", self.ledger)
        self.assertEqual((code, out), (2, ""))
        self.assertFalse(os.path.exists(self.ledger))

    def test_model_cap_refuses_and_prints_no_payload(self):
        self.write_budget(f"images: 10\nmodels:\n  {PRO}: 1\n")
        self.assertEqual(self.prepare()[0], 0)
        code, out, err = self.prepare()
        self.assertEqual((code, out), (3, ""))               # no payload -> nothing to invoke
        self.assertIn(f"models.{PRO}: 1 used + 1 requested > cap 1", err)
        self.assertEqual([r["status"] for r in self.rows()], ["pending", "refused-budget"])

    def test_pending_lambda_job_counts_against_plain_image(self):
        self.write_budget("images: 1\n")
        self.assertEqual(self.prepare()[0], 0)
        f = self.fake()
        code, _, _ = self.run_ark("image", "x", str(self.tmp / "b.png"), *self.cost)
        self.assertEqual((code, f.calls), (3, []))

    def test_refs_reencoded_for_upload(self):
        src = str(self.tmp / "ref.png")
        Image.new("RGBA", (3000, 1000), (0, 0, 0, 0)).save(src)
        code, out, err = self.prepare("--ref", src)
        self.assertEqual(code, 0)
        payload = json.loads(out)
        job = payload["job_id"]
        self.assertEqual(payload["ref_keys"], [f"refs/{job}-1.jpg"])
        local = self.tmp / "plates" / "lambda-refs" / f"{job}-1.jpg"
        with Image.open(local) as im:
            self.assertEqual((im.format, max(im.size)), ("JPEG", ark.REF_LONG_EDGE))
        self.assertIn(f"refs/{job}-1.jpg", err)

    def test_payload_file(self):
        pf = str(self.tmp / "p" / "payload.json")
        code, out, _ = self.prepare("--payload", pf)
        self.assertEqual(json.loads(Path(pf).read_text()), json.loads(out))


class TestFinish(LambdaCase):
    def job(self):
        out = str(self.tmp / "plates" / "a.png")
        code, stdout, _ = self.prepare(out=out)
        self.assertEqual(code, 0)
        return json.loads(stdout)["job_id"], out

    def test_succeeded_saves_image_and_writes_ok(self):
        job, out = self.job()
        st = self.status_file(job, status="succeeded", model=PRO, keys=[f"images/{job}.jpg"],
                              usage={"generated_images": 1}, seconds=47.2)
        code, _, _ = self.run_ark("lambda-job", "finish", "--status-json", st, "--image", self.downloaded(),
                                  "--ledger", self.ledger)
        self.assertEqual(code, 0)
        with Image.open(out) as im:
            self.assertEqual(im.format, "PNG")               # converted to the extension, like `image`
        rows = self.rows()
        self.assert_one_request(rows, "ok")
        self.assertEqual(json.loads(rows[-1]["usage"]), {"generated_images": 1})
        self.assertIn("seconds=47.2", rows[-1]["note"])
        self.assertEqual(len(ark.billed_requests(rows)), 1)

    def test_finish_twice_adds_no_row(self):
        job, _ = self.job()
        st = self.status_file(job, status="succeeded", keys=[f"images/{job}.jpg"], seconds=40)
        args = ("lambda-job", "finish", "--status-json", st, "--ledger", self.ledger)
        self.assertEqual(self.run_ark(*args)[0], 0)
        code, out, _ = self.run_ark(*args)
        self.assertEqual(code, 0)
        self.assertIn("already has a final row", out)
        self.assertEqual([r["status"] for r in self.rows()], ["pending", "ok"])

    def test_failed_job_is_failed_row_and_still_counts(self):
        job, _ = self.job()
        st = self.status_file(job, status="failed", error="HTTP 400: bad size", seconds=1.2)
        code, _, err = self.run_ark("lambda-job", "finish", "--status-json", st, "--ledger", self.ledger)
        self.assertEqual(code, 1)
        rows = self.rows()
        self.assert_one_request(rows, "failed")
        self.assertIn("HTTP 400", rows[-1]["note"])
        self.assertEqual(len(ark.billed_requests(rows)), 1)

    def test_running_writes_nothing(self):
        job, _ = self.job()
        st = self.status_file(job, status="running")
        code, _, err = self.run_ark("lambda-job", "finish", "--status-json", st, "--ledger", self.ledger)
        self.assertEqual(code, 1)
        self.assertEqual([r["status"] for r in self.rows()], ["pending"])

    def test_unprepared_job_refused(self):
        self.seed_ledger({"kind": "image", "model": "m", "status": "ok"})
        st = self.status_file("deadbeef", status="succeeded", keys=["images/deadbeef.jpg"])
        code, _, err = self.run_ark("lambda-job", "finish", "--status-json", st, "--ledger", self.ledger)
        self.assertEqual(code, 2)
        self.assertIn("lambda-job prepare", err)
        self.assertEqual(len(self.rows()), 1)

    def test_job_id_mismatch(self):
        job, _ = self.job()
        st = self.status_file("other", status="succeeded")
        code, _, _ = self.run_ark("lambda-job", "finish", "--job", job, "--status-json", st, "--ledger", self.ledger)
        self.assertEqual(code, 2)


class TestLedgerRequired(ArkCase):
    def test_missing_ledger_refused_before_any_call(self):
        self.write_budget("images: 5\nledger_required: true\n")
        f = self.fake()
        code, _, err = self.run_ark("image", "x", str(self.tmp / "a.png"), *self.cost)
        self.assertEqual((code, f.calls), (2, []))
        self.assertIn("ledger_required", err)
        self.assertFalse(os.path.exists(self.ledger))

    def test_empty_ledger_from_merge_then_allowed(self):
        self.write_budget("images: 5\nledger_required: true\n")
        self.assertEqual(self.run_ark("ledger-merge", "-o", self.ledger)[0], 0)
        self.assertEqual(Path(self.ledger).read_text(), ",".join(ark.LEDGER_FIELDS) + "\n")
        f = self.fake()
        code, _, _ = self.run_ark("image", "x", str(self.tmp / "a.png"), *self.cost)
        self.assertEqual((code, len(f.calls)), (0, 1))

    def test_default_is_off(self):
        f = self.fake()
        self.assertEqual(self.run_ark("image", "x", str(self.tmp / "a.png"), *self.cost)[0], 0)


class TestLedgerMerge(ArkCase):
    def ledger_file(self, name, *rows):
        path = str(self.tmp / name)
        for r in rows:
            ark.ledger_append(path, r)
        return path

    @staticmethod
    def row(req, status, ts, **kw):
        return dict({"ts": ts, "kind": "image", "model": "m", "count": 1, "status": status,
                     "note": f"req={req}"}, **kw)

    def test_union_keeps_rows_of_both_sessions(self):
        shared = [self.row("aa", "pending", "2026-11-10T01:00:00Z"), self.row("aa", "ok", "2026-11-10T01:00:30Z")]
        a = self.ledger_file("a.csv", *shared, self.row("bb", "pending", "2026-11-10T02:00:00Z"),
                             self.row("bb", "ok", "2026-11-10T02:00:20Z"))
        b = self.ledger_file("b.csv", *shared, self.row("cc", "pending", "2026-11-10T01:30:00Z"),
                             self.row("cc", "cut-502", "2026-11-10T01:30:31Z"))
        code, out, _ = self.run_ark("ledger-merge", a, b, "-o", self.ledger)
        self.assertEqual(code, 0)
        rows = self.rows()
        self.assertEqual([ark.req_id(r) for r in rows], ["aa", "aa", "cc", "cc", "bb", "bb"])   # by time
        self.assertEqual(len(ark.billed_requests(rows)), 3)   # "newest file wins" would have counted 2
        self.assertIn("3 image(s)", out)

    def test_pending_in_one_final_in_other_counts_once(self):
        a = self.ledger_file("a.csv", self.row("aa", "pending", "2026-11-10T01:00:00Z"))
        b = self.ledger_file("b.csv", self.row("aa", "pending", "2026-11-10T01:00:00Z"),
                             self.row("aa", "failed", "2026-11-10T01:00:09Z"))
        self.run_ark("ledger-merge", a, b, "-o", self.ledger)
        rows = self.rows()
        self.assertEqual([r["status"] for r in rows], ["pending", "failed"])
        self.assertEqual(len(ark.billed_requests(rows)), 1)

    def test_video_pending_rows_with_and_without_task_id_kept(self):
        v = dict(kind="video", seconds=5)
        a = self.ledger_file("a.csv", self.row("vv", "pending", "2026-11-10T01:00:00Z", **v),
                             self.row("vv", "pending", "2026-11-10T01:00:01Z", task_id="cgt-1", **v))
        self.run_ark("ledger-merge", a, a, "-o", self.ledger)
        self.assertEqual([r["task_id"] for r in self.rows()], ["", "cgt-1"])

    def test_old_rows_without_req_dedupe_only_when_identical(self):
        old = {"ts": "2026-11-09T00:00:00Z", "kind": "image", "model": "m", "count": 1, "status": "ok", "out": "x.png"}
        a = self.ledger_file("a.csv", old, dict(old, out="y.png"))
        b = self.ledger_file("b.csv", old)
        self.run_ark("ledger-merge", a, b, "-o", self.ledger)
        self.assertEqual(sorted(r["out"] for r in self.rows()), ["x.png", "y.png"])

    def test_out_may_be_an_input_and_merge_is_idempotent(self):
        a = self.ledger_file("ledger.csv", self.row("aa", "pending", "2026-11-10T01:00:00Z"))
        b = self.ledger_file("b.csv", self.row("bb", "pending", "2026-11-10T02:00:00Z"))
        self.assertEqual(a, self.ledger)
        self.run_ark("ledger-merge", a, b, "-o", self.ledger)
        first = Path(self.ledger).read_text()
        self.run_ark("ledger-merge", a, b, "-o", self.ledger)
        self.assertEqual(Path(self.ledger).read_text(), first)
        self.assertEqual(len(self.rows()), 2)

    def test_refused_rows_survive_but_do_not_count(self):
        a = self.ledger_file("a.csv", {"ts": "2026-11-10T01:00:00Z", "kind": "image", "model": "m",
                                       "status": "refused-budget", "note": "images: 1 used"})
        self.run_ark("ledger-merge", a, "-o", self.ledger)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(ark.billed_requests(self.rows()), [])

    def test_no_input_does_not_wipe_existing_rows(self):
        self.seed_ledger(self.row("aa", "ok", "2026-11-10T01:00:00Z"))
        code, _, err = self.run_ark("ledger-merge", "-o", self.ledger)
        self.assertEqual(code, 2)
        self.assertEqual(len(self.rows()), 1)

    def test_missing_input(self):
        self.assertEqual(self.run_ark("ledger-merge", str(self.tmp / "nope.csv"), "-o", self.ledger)[0], 2)


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)                              # stands in for NoSuchKey / AccessDenied
        return {"Body": io.BytesIO(self.objects[Key])}


class TestWorker(unittest.TestCase):
    """lambda/ark_image_worker.py with boto3 stubbed: the same job_id never generates twice."""

    def setUp(self):
        self.s3 = FakeS3()
        sm = types.SimpleNamespace(get_secret_value=lambda SecretId: {"SecretString": "not-a-real-key\n"})
        boto3 = types.ModuleType("boto3")
        boto3.client = lambda name: self.s3 if name == "s3" else sm
        env = mock.patch.dict(os.environ, {"BUCKET": "b", "SECRET_ID": "s", "ARK_BASE": "http://127.0.0.1:9/x"})
        mods = mock.patch.dict(sys.modules, {"boto3": boto3})
        env.start(); mods.start()
        self.addCleanup(env.stop); self.addCleanup(mods.stop)
        spec = importlib.util.spec_from_file_location("film_worker", REPO / "lambda" / "ark_image_worker.py")
        self.w = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.w)
        self.posts = []
        buf = io.BytesIO()
        Image.new("RGB", (4, 4)).save(buf, "JPEG")
        import base64
        body = json.dumps({"data": [{"b64_json": base64.b64encode(buf.getvalue()).decode()}],
                           "usage": {"generated_images": 1}}).encode()

        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def urlopen(req, timeout=None):
            self.posts.append(json.loads(req.data))
            return Resp(body)
        p = mock.patch.object(self.w.urllib.request, "urlopen", urlopen)
        p.start(); self.addCleanup(p.stop)
        self.ctx = types.SimpleNamespace(aws_request_id="rid", get_remaining_time_in_millis=lambda: 300000)

    def test_run_then_duplicate_is_skipped(self):
        ev = {"job_id": "abc", "prompt": "p", "size": "2K"}
        r = self.w.handler(ev, self.ctx)
        self.assertEqual(r["keys"], ["images/abc.jpg"])
        st = json.loads(self.s3.objects["jobs/abc.json"])
        self.assertEqual((st["status"], st["usage"]), ("succeeded", {"generated_images": 1}))
        again = self.w.handler(ev, self.ctx)
        self.assertEqual(again["skipped"], "duplicate")
        self.assertEqual(len(self.posts), 1)                 # one generation, one bill

    def test_running_job_is_not_restarted(self):
        self.s3.objects["jobs/abc.json"] = json.dumps({"job_id": "abc", "status": "running"}).encode()
        self.assertEqual(self.w.handler({"job_id": "abc", "prompt": "p"}, self.ctx)["status"], "running")
        self.assertEqual(self.posts, [])


if __name__ == "__main__":
    unittest.main()
