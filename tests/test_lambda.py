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


class TestLedgerWithoutTrailingNewline(LambdaCase):
    """A hand-edited ledger often ends without a newline: the next row must not be glued onto the last line."""

    def setUp(self):
        super().setUp()
        self.seed_ledger({"ts": "2026-11-10T01:00:00Z", "kind": "image", "model": PRO, "count": 1, "status": "ok",
                          "note": "req=aa"})
        text = Path(self.ledger).read_text()
        Path(self.ledger).write_text(text.rstrip("\n"))        # as Write/Edit/printf leave it

    def test_image_rows_stay_separate_and_count(self):
        self.write_budget("images: 2\n")
        f = self.fake()
        self.assertEqual(self.run_ark("image", "x", str(self.tmp / "a.png"), *self.cost)[0], 0)
        rows = self.rows()
        self.assertEqual([r["status"] for r in rows], ["ok", "pending", "ok"])
        self.assertEqual(ark.req_id(rows[0]), "aa")            # not 'aa2026...' from a glued line
        self.assertEqual(self.run_ark("image", "x", str(self.tmp / "b.png"), *self.cost)[0], 3)   # cap 2 is full

    def test_lambda_prepare_counts_against_the_model_cap_and_finish_finds_it(self):
        self.write_budget(f"images: 10\nmodels:\n  {PRO}: 2\n")
        code, out, _ = self.prepare()
        self.assertEqual(code, 0)
        job = json.loads(out)["job_id"]
        self.assertEqual(self.prepare()[0], 3)                 # 1 seeded + 1 pending = cap 2
        st = self.status_file(job, status="succeeded", keys=[f"images/{job}.jpg"], seconds=40)
        self.assertEqual(self.run_ark("lambda-job", "finish", "--status-json", st, "--ledger", self.ledger)[0], 0)


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

    def test_rows_only_in_out_are_kept_when_out_is_not_an_input(self):
        """The documented pull command: ledger-merge ledger.drive-*.csv -o ledger.csv, with local-only rows in -o."""
        self.seed_ledger(self.row("aa", "pending", "2026-11-10T01:00:00Z"), self.row("aa", "ok", "2026-11-10T01:00:30Z"),
                         self.row("10ca1", "pending", "2026-11-10T03:00:00Z"),
                         self.row("10ca1", "ok", "2026-11-10T03:00:20Z"))
        drive = self.ledger_file("ledger.drive-1.csv", self.row("aa", "pending", "2026-11-10T01:00:00Z"),
                                 self.row("aa", "ok", "2026-11-10T01:00:30Z"),
                                 self.row("d21fe", "pending", "2026-11-10T02:00:00Z"))
        code, out, _ = self.run_ark("ledger-merge", drive, "-o", self.ledger)
        self.assertEqual(code, 0)
        rows = self.rows()
        self.assertEqual(sorted({ark.req_id(r) for r in rows}), ["10ca1", "aa", "d21fe"])
        self.assertEqual(len(ark.billed_requests(rows)), 3)
        self.assertIn("4 row(s) already in ledger.csv", out)

    def test_bom_ledger_is_read_and_survives_a_merge(self):
        self.seed_ledger(self.row("aa", "pending", "2026-11-10T01:00:00Z"), self.row("aa", "ok", "2026-11-10T01:00:30Z"))
        raw = Path(self.ledger).read_bytes()
        Path(self.ledger).write_bytes(b"\xef\xbb\xbf" + raw)
        self.assertEqual(len(ark.billed_requests(ark.ledger_rows(self.ledger))), 1)
        self.write_budget("images: 1\n")
        f = self.fake()
        code, _, _ = self.run_ark("image", "x", str(self.tmp / "a.png"), *self.cost)
        self.assertEqual((code, f.calls), (3, []))             # the BOM ledger still fills the cap
        self.assertEqual(self.run_ark("ledger-merge", self.ledger, "-o", self.ledger)[0], 0)
        self.assertEqual(len(ark.billed_requests(self.rows())), 1)

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


class FakeAwsError(Exception):
    """Shaped like botocore's ClientError (the tests run without boto3/botocore)."""

    def __init__(self, code):
        super().__init__(f"An error occurred ({code}) when calling the operation")
        self.response = {"Error": {"Code": code}}


class ParamValidationError(Exception):
    """Stands in for botocore.exceptions.ParamValidationError: the worker matches it by class name."""


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.puts = []                 # every key written, in order
        self.conditional = True        # False: this "botocore" does not know IfNoneMatch
        self.get_error = None          # error code raised by every get_object

    def put_object(self, Bucket, Key, Body, ContentType=None, IfNoneMatch=None):
        if IfNoneMatch is not None:
            if not self.conditional:
                raise ParamValidationError('Unknown parameter in input: "IfNoneMatch"')
            if Key in self.objects:
                raise FakeAwsError("PreconditionFailed")
        self.puts.append(Key)
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        if self.get_error:
            raise FakeAwsError(self.get_error)
        if Key not in self.objects:
            raise FakeAwsError("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[Key])}


FAKE_KEY = "FAKEKEY-0123456789-abcdefghij"            # obviously fake; shaped like a usable key
JOB = "0123456789abcdef0123456789abcdef"              # the format of ark.py new_req()
WORKER = REPO / "lambda" / "ark_image_worker.py"
BAD_SECRET = "secret s is empty, a placeholder or malformed: enter it again in the console"


class TestWorker(unittest.TestCase):
    """lambda/ark_image_worker.py with boto3 stubbed: no key in any output, a fresh key per job, the same job_id
    never generates twice, and every status says whether anything was sent."""

    def setUp(self):
        self.s3 = FakeS3()
        self.secret = FAKE_KEY + "\n"
        self.secret_reads = 0

        def get_secret_value(SecretId):
            self.secret_reads += 1
            return {"SecretString": self.secret}
        sm = types.SimpleNamespace(get_secret_value=get_secret_value)
        boto3 = types.ModuleType("boto3")
        boto3.client = lambda name: self.s3 if name == "s3" else sm
        env = mock.patch.dict(os.environ, {"BUCKET": "b", "SECRET_ID": "s", "ARK_BASE": "http://127.0.0.1:9/x"})
        mods = mock.patch.dict(sys.modules, {"boto3": boto3})
        env.start(); mods.start()
        self.addCleanup(env.stop); self.addCleanup(mods.stop)
        spec = importlib.util.spec_from_file_location("film_worker", WORKER)
        self.w = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.w)
        self.posts, self.auth, self.timeouts, self.seen_running = [], [], [], []
        self.fail = None                                     # exception raised by urlopen instead of answering
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
            self.auth.append(req.get_header("Authorization"))
            self.timeouts.append(timeout)
            self.seen_running.append(json.loads(self.s3.objects[f"jobs/{JOB}.json"]))
            if self.fail is not None:
                raise self.fail
            return Resp(body)
        p = mock.patch.object(self.w.urllib.request, "urlopen", urlopen)
        p.start(); self.addCleanup(p.stop)
        self.remaining_ms = 300000
        self.ctx = types.SimpleNamespace(aws_request_id="rid",
                                         get_remaining_time_in_millis=lambda: self.remaining_ms)
        self.ev = {"job_id": JOB, "prompt": "p", "size": "2K"}
        import hashlib
        self.sha = hashlib.sha256(WORKER.read_bytes()).hexdigest()

    def status(self):
        return json.loads(self.s3.objects[f"jobs/{JOB}.json"])

    def assert_no_secret(self, *needles, exc=None):
        for needle in needles:
            for key, body in self.s3.objects.items():
                self.assertNotIn(needle.encode(), body, key)
            if exc is not None:
                self.assertNotIn(needle, str(exc))
                self.assertNotIn(needle, repr(exc))
        if exc is not None:                                  # nothing chained for CloudWatch to print
            self.assertIsNone(exc.__cause__)
            self.assertTrue(exc.__suppress_context__ or exc.__context__ is None)

    # --- the two scenarios that already held -------------------------------------------------------------
    def test_run_then_duplicate_is_skipped(self):
        r = self.w.handler(self.ev, self.ctx)
        self.assertEqual(r["keys"], [f"images/{JOB}.jpg"])
        st = self.status()
        self.assertEqual((st["status"], st["usage"]), ("succeeded", {"generated_images": 1}))
        self.assertIs(st["sent"], True)
        again = self.w.handler(self.ev, self.ctx)
        self.assertEqual((again["skipped"], again["status"]), ("duplicate", "succeeded"))
        self.assertEqual(len(self.posts), 1)                 # one generation, one bill

    def test_running_job_is_not_restarted(self):
        self.s3.objects[f"jobs/{JOB}.json"] = json.dumps({"job_id": JOB, "status": "running"}).encode()
        self.assertEqual(self.w.handler(self.ev, self.ctx)["status"], "running")
        self.assertEqual(self.posts, [])
        self.assertEqual(self.s3.puts, [])

    # --- key hygiene ---------------------------------------------------------------------------------------
    def test_multiline_secret_fails_before_sending_and_is_nowhere(self):
        self.secret = "FAKEKEY-first-half-0123\nFAKEKEY-second-half-4567\n"
        with self.assertRaises(RuntimeError) as cm:
            self.w.handler(self.ev, self.ctx)
        self.assertEqual(self.posts, [])
        st = self.status()
        self.assertEqual((st["status"], st["sent"], st["error"]), ("failed", False, BAD_SECRET))
        self.assertEqual(str(cm.exception), BAD_SECRET)
        self.assert_no_secret("FAKEKEY", exc=cm.exception)

    def test_placeholder_short_and_spaced_secrets_are_refused(self):
        for bad in ("REPLACE_WITH_ARK_API_KEY", "", "short", "FAKEKEY with spaces 0123456789",
                    "FAKEKEY-khóa-0123456789abc"):
            self.s3.objects.clear()
            self.secret = bad
            with self.assertRaises(RuntimeError):
                self.w.handler(self.ev, self.ctx)
            st = self.status()
            self.assertEqual((st["status"], st["sent"], st["error"]), ("failed", False, BAD_SECRET), bad)
        self.assertEqual(self.posts, [])

    def test_key_echoed_in_http_error_body_is_redacted(self):
        body = ('{"error": {"message": "invalid key %s"}}' % FAKE_KEY).encode() + b"\xff"
        self.fail = self.w.urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, io.BytesIO(body))
        with self.assertRaises(RuntimeError) as cm:
            self.w.handler(self.ev, self.ctx)
        self.assertEqual(len(self.posts), 1)
        st = self.status()
        self.assertEqual((st["status"], st["sent"]), ("failed", True))
        self.assertTrue(st["error"].startswith('HTTP 401: {"error": {"message": "invalid key <redacted>"}}'),
                        st["error"])
        self.assertEqual(str(cm.exception), st["error"])
        self.assert_no_secret(FAKE_KEY, exc=cm.exception)

    def test_bearer_text_is_cut_even_when_it_is_not_the_exact_key(self):
        self.fail = ValueError("Invalid header value b'Bearer FAKEKEY-other-half\\nFAKEKEY-rest'")
        with self.assertRaises(RuntimeError) as cm:
            self.w.handler(self.ev, self.ctx)
        self.assertEqual(self.status()["error"], "Invalid header value b'Bearer <redacted>")
        self.assert_no_secret("FAKEKEY", exc=cm.exception)

    def test_secret_is_read_again_for_every_job(self):
        self.secret = "REPLACE_WITH_ARK_API_KEY"
        with self.assertRaises(RuntimeError):
            self.w.handler(self.ev, self.ctx)
        self.assertEqual(self.posts, [])
        self.s3.objects.clear()
        self.secret = FAKE_KEY                               # the user enters the key; same warm instance
        self.w.handler(self.ev, self.ctx)
        self.assertEqual(self.auth, ["Bearer " + FAKE_KEY])
        self.assertEqual(self.secret_reads, 2)

    # --- sent flag, references, prompt ---------------------------------------------------------------------
    def test_missing_reference_is_unsent_with_a_clear_message(self):
        for code in ("NoSuchKey", "AccessDenied"):
            self.s3.objects.clear()
            self.s3.get_error = code
            with self.assertRaises(RuntimeError):
                self.w.handler({**self.ev, "ref_keys": [f"refs/{JOB}-1.jpg"]}, self.ctx)
            st = self.status()
            self.assertEqual((st["status"], st["sent"]), ("failed", False))
            self.assertEqual(st["error"], f"ref not in bucket: refs/{JOB}-1.jpg: upload it, then prepare a new job")
        self.assertEqual(self.posts, [])

    def test_reference_is_sent_as_a_data_uri(self):
        self.s3.objects[f"refs/{JOB}-1.jpg"] = b"\xff\xd8\xff" + b"0" * 8
        self.w.handler({**self.ev, "ref_keys": [f"refs/{JOB}-1.jpg"]}, self.ctx)
        self.assertTrue(self.posts[0]["image"].startswith("data:image/jpeg;base64,"))

    def test_missing_prompt_is_unsent(self):
        with self.assertRaises(RuntimeError):
            self.w.handler({"job_id": JOB}, self.ctx)
        st = self.status()
        self.assertEqual((st["status"], st["sent"]), ("failed", False))
        self.assertIn("prompt", st["error"])
        self.assertEqual((self.posts, self.secret_reads), ([], 0))

    # --- deadline --------------------------------------------------------------------------------------------
    def test_running_status_has_deadline_and_timeout_fits_the_time_left(self):
        self.remaining_ms = 25000
        self.w.handler(self.ev, self.ctx)
        running = self.seen_running[0]
        self.assertEqual((running["status"], running["sent"]), ("running", True))
        self.assertAlmostEqual(running["deadline"], running["started"] + 25, delta=1)
        self.assertEqual(self.timeouts, [5])
        self.assertLessEqual(self.timeouts[0], 25)

    def test_timeout_never_drops_below_one_second(self):
        self.remaining_ms = 8000
        self.w.handler(self.ev, self.ctx)
        self.assertEqual(self.timeouts, [1])

    def test_long_limit_leaves_twenty_seconds(self):
        self.remaining_ms = 900000
        self.w.handler(self.ev, self.ctx)
        self.assertEqual(self.timeouts, [880])

    # --- duplicate guard -------------------------------------------------------------------------------------
    def test_event_without_a_prepared_job_id_is_refused(self):
        for ev in ({"prompt": "p"}, {"job_id": "abc", "prompt": "p"}, {"job_id": JOB.upper(), "prompt": "p"},
                   {"job_id": JOB + "\n", "prompt": "p"}, {"job_id": 5, "prompt": "p"}, None):
            r = self.w.handler(ev, self.ctx)
            self.assertEqual(r, {"error": "no job_id: use ark.py lambda-job prepare"})
        self.assertEqual((self.s3.puts, self.posts, self.secret_reads), ([], [], 0))

    def test_second_delivery_never_posts_again(self):
        self.w.handler(self.ev, self.ctx)
        self.s3.get_error = "SlowDown"                       # the read of the old status fails: still a duplicate
        again = self.w.handler(self.ev, self.ctx)
        self.assertEqual((again["job_id"], again["skipped"]), (JOB, "duplicate"))
        self.assertEqual(len(self.posts), 1)

    def test_existing_status_only_treats_missing_as_missing(self):
        self.assertIsNone(self.w.existing_status(JOB))
        self.s3.get_error = "AccessDenied"
        self.assertIsNone(self.w.existing_status(JOB))
        self.s3.get_error = "SlowDown"
        with self.assertRaises(FakeAwsError):
            self.w.existing_status(JOB)

    def test_read_error_in_the_fallback_raises_and_posts_nothing(self):
        self.s3.conditional = False
        self.s3.get_error = "InternalError"
        with self.assertRaises(FakeAwsError):
            self.w.handler(self.ev, self.ctx)
        self.assertEqual((self.posts, self.s3.puts), ([], []))

    def test_fallback_without_conditional_writes_runs_the_job_once(self):
        self.s3.conditional = False
        self.assertEqual(self.w.handler(self.ev, self.ctx)["keys"], [f"images/{JOB}.jpg"])
        self.assertEqual(self.w.handler(self.ev, self.ctx)["skipped"], "duplicate")
        self.assertEqual(len(self.posts), 1)

    def test_other_claim_errors_are_not_swallowed(self):
        real_put = self.s3.put_object

        def put(**kw):
            if kw.get("IfNoneMatch"):
                raise FakeAwsError("ServiceUnavailable")
            return real_put(**kw)
        self.s3.put_object = put
        with self.assertRaises(FakeAwsError):
            self.w.handler(self.ev, self.ctx)
        self.assertEqual(self.posts, [])

    # --- worker identity -------------------------------------------------------------------------------------
    def test_every_status_carries_the_worker_hash(self):
        self.w.handler(self.ev, self.ctx)
        self.assertEqual(self.seen_running[0]["worker_sha256"], self.sha)
        self.assertEqual(self.status()["worker_sha256"], self.sha)
        self.s3.objects.clear()
        self.secret = "REPLACE_WITH_ARK_API_KEY"
        with self.assertRaises(RuntimeError):
            self.w.handler(self.ev, self.ctx)
        self.assertEqual(self.status()["worker_sha256"], self.sha)

    def test_worker_does_not_import_botocore(self):
        src = WORKER.read_text()
        self.assertNotIn("import botocore", src)
        self.assertNotIn("from botocore", src)


if __name__ == "__main__":
    unittest.main()
