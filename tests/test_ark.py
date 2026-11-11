"""tools/ark.py: ledger, budget, 502 handling, new image flags, --ref re-encoding. Network is always mocked."""
import base64, csv, hashlib, io, json, os, signal, subprocess, sys, time, unittest
from unittest import mock

from PIL import Image

from helpers import REPO, TmpDirCase, load, run_main

ark = load("ark.py", "film_ark")


def tiny_jpeg_b64():
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


class FakeArk:
    """Stands in for ark.call(); records every request. Never touches the network."""

    def __init__(self, image=None, create=None, polls=None):
        self.calls = []
        self.image = image
        self.create = create
        self.polls = list(polls or [])

    def __call__(self, method, path, body=None, timeout=300):
        self.calls.append((method, path, body))
        if path == "/images/generations":
            if isinstance(self.image, BaseException):
                raise self.image
            return self.image or {"data": [{"b64_json": tiny_jpeg_b64()}], "usage": {"generated_images": 1}}
        if path == "/contents/generations/tasks":
            if isinstance(self.create, BaseException):
                raise self.create
            return self.create or {"id": "cgt-test-1"}
        if path.startswith("/contents/generations/tasks/"):
            nxt = self.polls.pop(0)
            if isinstance(nxt, BaseException):
                raise nxt
            return nxt
        raise AssertionError(f"unexpected call {method} {path}")

    def generation_calls(self):
        return [c for c in self.calls if c[0] == "POST"]


class ArkCase(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        env = {k: v for k, v in os.environ.items() if not k.startswith("FILM_")}
        env["FILM_AGENT"] = "film-test-agent"
        self._env = mock.patch.dict(os.environ, env, clear=True)
        self._env.start()
        self._poll = mock.patch.object(ark, "POLL_SECONDS", 0)
        self._poll.start()
        self.downloads = []
        self._dl = mock.patch.object(ark, "download", lambda url, out: self.downloads.append((url, out)))
        self._dl.start()
        self.ledger = str(self.tmp / "ledger.csv")
        self.budget = str(self.tmp / "budget.yaml")
        self.write_budget("images: 100\nvideo_seconds: 600\n")
        self.cost = ["--ledger", self.ledger, "--budget", self.budget]

    def tearDown(self):
        mock.patch.stopall()
        self._env.stop()
        super().tearDown()

    def fake(self, **kw):
        f = FakeArk(**kw)
        p = mock.patch.object(ark, "call", f)
        p.start()
        self.addCleanup(p.stop)
        return f

    def rows(self):
        with open(self.ledger, newline="") as f:
            return list(csv.DictReader(f))

    def write_budget(self, text):
        with open(self.budget, "w") as f:
            f.write(text)

    def seed_ledger(self, *rows):
        for r in rows:
            ark.ledger_append(self.ledger, r)

    def run_ark(self, *argv):
        return run_main(ark.main, list(argv))

    def assert_one_request(self, rows, final):
        """rows = pending (+ pending with task id) + one final row, all with the same req=<hex> id."""
        self.assertEqual([r["status"] for r in rows[:-1]], ["pending"] * (len(rows) - 1))
        self.assertEqual(rows[-1]["status"], final)
        ids = {ark.req_id(r) for r in rows}
        self.assertEqual(len(ids), 1)
        self.assertRegex(ids.pop(), r"^[0-9a-f]{32}$")


SUCCEEDED = {"status": "succeeded", "content": {"video_url": "https://host.example/v.mp4?sig=abc"},
             "usage": {"completion_tokens": 7}}


class TestLedger(ArkCase):
    def test_image_ok_row(self):
        f = self.fake()
        out = str(self.tmp / "a.png")
        code, so, _ = self.run_ark("image", "a mountain", out, *self.cost)
        self.assertEqual(code, 0)
        self.assertEqual(len(f.generation_calls()), 1)
        self.assertIn("model seedream-5-0-lite-260128", so)
        self.assertIn("saved " + out, so)
        self.assertIn('usage {"generated_images": 1}', so)
        with open(self.ledger) as fh:
            self.assertEqual(fh.readline().strip(), ",".join(ark.LEDGER_FIELDS))
        rows = self.rows()
        self.assert_one_request(rows, "ok")
        r = rows[-1]
        self.assertEqual((r["kind"], r["model"], r["size"], r["count"], r["status"], r["out"], r["agent"]),
                         ("image", "seedream-5-0-lite-260128", "2K", "1", "ok", out, "film-test-agent"))
        self.assertEqual(json.loads(r["usage"]), {"generated_images": 1})
        self.assertEqual(rows[0]["usage"], "")
        self.assertRegex(r["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        with Image.open(out) as im:
            self.assertEqual(im.format, "PNG")

    def test_env_fallback(self):
        self.fake()
        os.environ["FILM_LEDGER"] = self.ledger
        os.environ["FILM_BUDGET"] = self.budget
        code, _, _ = self.run_ark("image", "x", str(self.tmp / "b.png"))
        self.assertEqual(code, 0)
        self.assert_one_request(self.rows(), "ok")

    def test_makedirs_before_call(self):
        out = self.tmp / "new" / "deeper" / "a.png"
        seen = []
        f = FakeArk()

        def spy(*args, **kw):
            seen.append(out.parent.is_dir())
            return f(*args, **kw)
        with mock.patch.object(ark, "call", spy):
            code, so, _ = self.run_ark("image", "x", str(out), *self.cost)
        self.assertEqual(code, 0)
        self.assertEqual(seen, [True])
        self.assertTrue(out.is_file())
        self.assert_one_request(self.rows(), "ok")

    def test_save_failure_is_failed_row(self):
        self.fake()
        with mock.patch.object(ark, "save_image", side_effect=OSError("disk full")):
            code, _, err = self.run_ark("image", "x", str(self.tmp / "a.png"), *self.cost)
        self.assertEqual(code, 1)
        self.assertIn("SAVE FAILED", err)
        rows = self.rows()
        self.assert_one_request(rows, "failed")
        self.assertIn("save-failed: OSError: disk full", rows[-1]["note"])

    def test_http_error_failed_row(self):
        f = self.fake(image=SystemExit('HTTP 400: {"error": "InvalidParameter"}'))
        code, _, err = self.run_ark("image", "x", str(self.tmp / "d.png"), *self.cost)
        self.assertEqual(code, 1)
        self.assertIn("HTTP 400", err)
        rows = self.rows()
        self.assert_one_request(rows, "failed")
        self.assertIn("HTTP 400", rows[-1]["note"])
        self.assertEqual(len(f.generation_calls()), 1)

    def test_cut_502_row_no_retry(self):
        f = self.fake(image=SystemExit("HTTP 502: upstream request failed"))
        with mock.patch.object(ark, "PROXY_CUTOFF", 5):   # any duration counts as "cut"
            code, _, err = self.run_ark("image", "x", str(self.tmp / "e.png"), *self.cost)
        self.assertEqual(code, 1)
        self.assertIn("NOT retried", err)
        self.assertEqual(len(f.generation_calls()), 1)
        self.assert_one_request(self.rows(), "cut-502")

    def test_fast_502_is_failed_not_cut(self):
        self.fake(image=SystemExit("HTTP 502: bad gateway"))
        code, _, _ = self.run_ark("image", "x", str(self.tmp / "f.png"), *self.cost)
        self.assertEqual(code, 1)
        self.assertEqual(self.rows()[-1]["status"], "failed")

    def test_guard_exits_are_not_api_calls(self):
        f = self.fake()
        code, _, _ = self.run_ark("image", "x", str(self.tmp / "g.png"), "--size", "4K", *self.cost)
        self.assertEqual(code, 2)                 # a local refusal is a usage error: nothing was sent
        self.assertEqual(f.calls, [])
        self.assertFalse(os.path.exists(self.ledger))

    def test_concurrent_append(self):
        """4 processes x 40 rows each, appended under flock: no lost or torn rows."""
        code = ("import importlib.util, sys\n"
                "s = importlib.util.spec_from_file_location('a', sys.argv[1]); m = importlib.util.module_from_spec(s)\n"
                "s.loader.exec_module(m)\n"
                "for i in range(40):\n"
                "    m.ledger_append(sys.argv[2], {'kind': 'image', 'model': 'm', 'count': 1, 'status': 'ok',\n"
                "                    'note': 'note, with comma and \"quotes\" ' + sys.argv[3] + '-' + str(i)})\n")
        procs = [subprocess.Popen([sys.executable, "-c", code, str(REPO / "tools" / "ark.py"), self.ledger, f"p{k}"],
                                  env=dict(os.environ, FILM_AGENT=f"agent-{k}")) for k in range(4)]
        for pr in procs:
            self.assertEqual(pr.wait(timeout=60), 0)
        with open(self.ledger) as fh:
            text = fh.read()
        self.assertEqual(text.count("ts,kind,model"), 1)
        rows = self.rows()
        self.assertEqual(len(rows), 160)
        self.assertTrue(all(None not in r and len(r) == 12 for r in rows))
        notes = {r["note"] for r in rows}
        self.assertEqual(len(notes), 160)
        self.assertEqual({r["agent"] for r in rows}, {f"agent-{k}" for k in range(4)})


class TestAtomicReserve(ArkCase):
    """Budget check and pending row happen under one LOCK_EX: parallel agents cannot overrun a cap."""

    RACE_SCRIPT = (
        "import base64, importlib.util, io, sys, time\n"
        "from PIL import Image\n"
        "s = importlib.util.spec_from_file_location('a', sys.argv[1]); m = importlib.util.module_from_spec(s)\n"
        "s.loader.exec_module(m)\n"
        "buf = io.BytesIO(); Image.new('RGB', (4, 4)).save(buf, 'JPEG')\n"
        "b64 = base64.b64encode(buf.getvalue()).decode()\n"
        "def call(method, path, body=None, timeout=300):\n"
        "    assert path == '/images/generations', path\n"
        "    time.sleep(0.3)                     # the API call runs outside the lock\n"
        "    return {'data': [{'b64_json': b64}], 'usage': {'generated_images': 1}}\n"
        "def slow_ref(p):\n"
        "    time.sleep(0.3)                     # slow --ref re-encoding: the old race window\n"
        "    return 'data:image/jpeg;base64,' + b64\n"
        "m.call = call\n"
        "m.ref_data_uri = slow_ref\n"
        "start = float(sys.argv[2])\n"
        "while time.time() < start:              # all processes start together\n"
        "    time.sleep(0.005)\n"
        "m.main(sys.argv[3:])\n")

    def test_parallel_agents_cannot_overrun_cap(self):
        """8 processes race for a cap of 3 images: exactly 3 reservations, 5 refused-budget rows."""
        self.write_budget("images: 3\n")
        ref = self.tmp / "ref.png"
        Image.new("RGB", (8, 8), (1, 2, 3)).save(ref)
        start = time.time() + 1.5
        procs = [subprocess.Popen(
            [sys.executable, "-c", self.RACE_SCRIPT, str(REPO / "tools" / "ark.py"), str(start),
             "image", f"shot {k}", str(self.tmp / f"s{k}.png"), "--ref", str(ref), *self.cost],
            env=dict(os.environ, FILM_AGENT=f"agent-{k}"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True) for k in range(8)]
        codes = []
        for pr in procs:
            _, err = pr.communicate(timeout=60)
            codes.append(pr.returncode)
            if pr.returncode == ark.BUDGET_EXIT:
                self.assertIn("REFUSED (budget", err)
        self.assertEqual(sorted(codes), [0] * 3 + [ark.BUDGET_EXIT] * 5)
        rows = self.rows()
        by_status = {}
        for r in rows:
            by_status.setdefault(r["status"], []).append(r)
        self.assertEqual(len(by_status["pending"]), 3)
        self.assertEqual(len(by_status["ok"]), 3)
        self.assertEqual(len(by_status["refused-budget"]), 5)
        self.assertEqual(set(by_status), {"pending", "ok", "refused-budget"})
        # each winner: pending then ok with the same req id; the refused ones have no req id
        self.assertEqual({ark.req_id(r) for r in by_status["pending"]}, {ark.req_id(r) for r in by_status["ok"]})
        self.assertTrue(all(ark.req_id(r) is None for r in by_status["refused-budget"]))
        self.assertEqual(sum(ark.units(r) for r in ark.billed_requests(rows)), 3)
        # winners' out files exist, refused agents never reached the API
        self.assertEqual(sum(os.path.exists(self.tmp / f"s{k}.png") for k in range(8)), 3)

    def test_refused_row_written_under_same_lock(self):
        """In-process: a full ledger refuses with exit 3, one refused-budget row, no pending, no call."""
        self.write_budget("images: 1\n")
        self.seed_ledger({"kind": "image", "model": "m", "count": 1, "status": "ok"})
        f = self.fake()
        code, _, err = self.run_ark("image", "x", str(self.tmp / "r.png"), *self.cost)
        self.assertEqual(code, ark.BUDGET_EXIT)
        self.assertIn("REFUSED", err)
        self.assertEqual(f.calls, [])
        self.assertEqual([r["status"] for r in self.rows()], ["ok", "refused-budget"])


class TestCostFlags(ArkCase):
    """Budget is not opt-in: image/video need budget + ledger, or an explicit --no-budget."""

    def refused(self, *argv):
        f = self.fake()
        code, so, err = self.run_ark(*argv)
        self.assertEqual(code, 2, err)
        self.assertEqual(f.calls, [])
        self.assertFalse(os.path.exists(self.ledger))
        return err

    def test_refuses_without_budget_and_ledger(self):
        err = self.refused("image", "x", str(self.tmp / "sub" / "a.png"))
        self.assertIn("without a budget", err)
        self.assertIn("--no-budget", err)
        self.refused("video", "x", str(self.tmp / "sub" / "v.mp4"))
        self.assertFalse((self.tmp / "sub").exists())   # refused before anything is created

    def test_ledger_alone_refused(self):
        err = self.refused("image", "x", str(self.tmp / "a.png"), "--ledger", self.ledger)
        self.assertIn("without a budget", err)
        os.environ["FILM_LEDGER"] = self.ledger
        self.refused("video", "x", str(self.tmp / "v.mp4"))

    def test_budget_without_ledger_is_error(self):
        err = self.refused("image", "x", str(self.tmp / "a.png"), "--budget", self.budget)
        self.assertIn("--budget without --ledger", err)
        os.environ["FILM_BUDGET"] = self.budget
        err = self.refused("video", "x", str(self.tmp / "v.mp4"))
        self.assertIn("--budget without --ledger", err)

    def test_no_budget_runs_with_warning(self):
        f = self.fake()
        out = self.tmp / "adhoc" / "c.png"
        code, _, err = self.run_ark("image", "x", str(out), "--no-budget")
        self.assertEqual(code, 0)
        self.assertEqual(len(f.generation_calls()), 1)
        self.assertEqual(len([ln for ln in err.splitlines() if "--no-budget" in ln]), 1)
        self.assertTrue(out.is_file())
        self.assertFalse(os.path.exists(self.ledger))

    def test_no_budget_with_ledger_still_logs(self):
        self.write_budget("images: 0\n")   # would refuse; --no-budget skips the check
        self.fake()
        code, _, _ = self.run_ark("image", "x", str(self.tmp / "c.png"), "--no-budget", *self.cost)
        self.assertEqual(code, 0)
        self.assert_one_request(self.rows(), "ok")

    def test_video_needs_prompt_and_out(self):
        err = self.refused("video", str(self.tmp / "v.mp4"), *self.cost)
        self.assertIn("prompt and an output", err)

    def test_resume_needs_ledger(self):
        err = self.refused("video", "--resume-task", "cgt-1", str(self.tmp / "v.mp4"), "--budget", self.budget)
        self.assertIn("--resume-task needs --ledger", err)


class TestCounting(ArkCase):
    def used(self, rows, kind="image"):
        return sum(ark.units(r) for r in ark.billed_requests(rows) if r["kind"] == kind)

    def test_pending_alone_counts(self):
        self.assertEqual(self.used([{"kind": "image", "count": "1", "status": "pending", "note": "req=aa"}]), 1)

    def test_pending_plus_final_counts_once(self):
        rows = [{"kind": "image", "count": "1", "status": "pending", "note": "req=aa"},
                {"kind": "image", "count": "2", "status": "ok", "note": "req=aa"},
                {"kind": "image", "count": "1", "status": "pending", "note": "req=bb"},
                {"kind": "image", "count": "1", "status": "failed", "note": "req=bb; HTTP 400"}]
        self.assertEqual(self.used(rows), 3)

    def test_video_pending_with_task_then_resumed(self):
        v = {"kind": "video", "seconds": "5"}
        rows = [dict(v, status="pending", note="req=cc"),
                dict(v, status="pending", task_id="t1", note="req=cc; task created"),
                dict(v, status="failed", task_id="t1", note="req=cc; polling stopped"),
                dict(v, status="ok", task_id="t1", note="req=cc; resumed")]
        self.assertEqual(self.used(rows, "video"), 5)

    def test_rows_without_req_count_as_before(self):
        rows = [{"kind": "image", "count": "1", "status": "ok", "note": ""},
                {"kind": "image", "count": "1", "status": "failed", "note": "HTTP 400"},
                {"kind": "image", "count": "1", "status": "cut-502", "note": ""},
                {"kind": "image", "count": "1", "status": "refused-budget", "note": "images: ..."}]
        self.assertEqual(self.used(rows), 3)
        old = [{"kind": "video", "seconds": "5", "status": "failed", "task_id": "t9", "note": "polling stopped"},
               {"kind": "video", "seconds": "5", "status": "ok", "task_id": "t9", "note": "resumed"}]
        self.assertEqual(self.used(old, "video"), 5)   # an old task resumed counts once (same task_id)

    def test_pending_blocks_budget(self):
        self.write_budget("images: 2\n")
        self.seed_ledger({"kind": "image", "model": "m1", "count": 1, "status": "pending", "note": "req=aa"},
                         {"kind": "image", "model": "m1", "count": 1, "status": "pending", "note": "req=bb"},
                         {"kind": "image", "model": "m1", "count": 1, "status": "ok", "note": "req=bb"})
        f = self.fake()
        code, _, err = self.run_ark("image", "x", str(self.tmp / "a.png"), *self.cost)
        self.assertEqual(code, 3)
        self.assertIn("images: 2 used + 1 requested > cap 2", err)
        self.assertEqual(f.calls, [])


class TestBudget(ArkCase):
    def test_refused_budget_exit_3(self):
        self.write_budget("images: 2\nvideo_seconds: 60\n")
        self.seed_ledger({"kind": "image", "model": "m1", "count": 1, "status": "ok"},
                         {"kind": "image", "model": "m1", "count": 1, "status": "failed"})
        f = self.fake()
        code, _, err = self.run_ark("image", "x", str(self.tmp / "a.png"), *self.cost)
        self.assertEqual(code, 3)
        self.assertEqual(f.calls, [])
        self.assertIn("REFUSED", err)
        self.assertIn("images: 2 used + 1 requested > cap 2", err)
        last = self.rows()[-1]
        self.assertEqual((last["status"], last["kind"], last["agent"]), ("refused-budget", "image", "film-test-agent"))
        self.assertEqual(len(self.rows()), 3)   # no pending row for a refused request

    def test_refused_and_unknown_rows_do_not_count(self):
        self.write_budget("images: 2\n")
        self.seed_ledger({"kind": "image", "model": "m1", "count": 1, "status": "ok"},
                         {"kind": "image", "model": "m1", "count": 1, "status": "refused-budget"},
                         {"kind": "image", "model": "m1", "count": 1, "status": "refused-budget"})
        f = self.fake()
        code, _, _ = self.run_ark("image", "x", str(self.tmp / "a.png"), *self.cost)
        self.assertEqual(code, 0)
        self.assertEqual(len(f.generation_calls()), 1)

    def test_cut_502_counts(self):
        self.write_budget("images: 1\n")
        self.seed_ledger({"kind": "image", "model": "m1", "count": 1, "status": "cut-502"})
        self.fake()
        code, _, _ = self.run_ark("image", "x", str(self.tmp / "a.png"), *self.cost)
        self.assertEqual(code, 3)

    def test_model_cap(self):
        pro = "dola-seedream-5-0-pro-260628"
        self.write_budget(f"images: 40\nmodels:\n  {pro}: 1\n")
        self.seed_ledger({"kind": "image", "model": pro, "count": 1, "status": "ok"})
        f = self.fake()
        code, _, err = self.run_ark("image", "x", str(self.tmp / "a.png"), "--model", pro, "--force", *self.cost)
        self.assertEqual(code, 3)
        self.assertIn(f"models.{pro}", err)
        code, _, _ = self.run_ark("image", "x", str(self.tmp / "b.png"), *self.cost)
        self.assertEqual(code, 0)
        self.assertEqual(len(f.generation_calls()), 1)
        self.assertEqual([r["status"] for r in self.rows()], ["ok", "refused-budget", "pending", "ok"])

    def test_env_budget(self):
        self.write_budget("images: 0\n")
        os.environ["FILM_BUDGET"] = self.budget
        os.environ["FILM_LEDGER"] = self.ledger
        f = self.fake()
        code, _, _ = self.run_ark("image", "x", str(self.tmp / "a.png"))
        self.assertEqual(code, 3)
        self.assertEqual(f.calls, [])
        self.assertEqual(self.rows()[0]["status"], "refused-budget")

    def test_video_ratio(self):
        """Seedance 2.5 image-to-video rejects 'ratio' (HTTP 400): with --image it is not sent unless asked."""
        self.write_budget("images: 40\nvideo_seconds: 60\n")
        img = str(self.tmp / "start.png")
        Image.new("RGB", (16, 9), (1, 2, 3)).save(img)
        out = str(self.tmp / "v.mp4")
        f = self.fake(polls=[SUCCEEDED])
        code, so, err = self.run_ark("video", "x", out, "--image", img, *self.cost)
        self.assertEqual(code, 0, err)
        self.assertNotIn("ratio", f.generation_calls()[-1][2])
        self.assertIn("ratio not sent", so)
        self.assertNotIn("WARNING", err)
        f = self.fake(polls=[SUCCEEDED])
        code, so, err = self.run_ark("video", "x", out, "--image", img, "--ratio", "16:9", *self.cost)
        self.assertEqual(code, 0, err)
        self.assertEqual(f.generation_calls()[-1][2]["ratio"], "16:9")
        self.assertIn("WARNING: --ratio 16:9 with --image", err)
        f = self.fake(polls=[SUCCEEDED])
        code, so, err = self.run_ark("video", "x", out, *self.cost)
        self.assertEqual(code, 0, err)
        self.assertEqual(f.generation_calls()[-1][2]["ratio"], "16:9")

    def test_video_seconds(self):
        self.write_budget("images: 40\nvideo_seconds: 10\n")
        self.seed_ledger({"kind": "video", "model": ark.VIDEO_DEFAULT, "seconds": 5, "count": 1, "status": "ok"},
                         {"kind": "image", "model": "m1", "count": 30, "status": "ok"})
        f = self.fake(polls=[{"status": "running"}, SUCCEEDED])
        out = str(self.tmp / "clips" / "v.mp4")
        code, _, err = self.run_ark("video", "x", out, "--duration", "6", *self.cost)
        self.assertEqual(code, 3)
        self.assertIn("video_seconds: 5 used + 6 requested > cap 10", err)
        self.assertEqual(f.calls, [])
        code, so, _ = self.run_ark("video", "x", out, "--duration", "5", *self.cost)
        self.assertEqual(code, 0)
        self.assertIn("task cgt-test-1", so)
        self.assertIn("video host: host.example", so)
        self.assertNotIn("sig=abc", so)
        self.assertEqual(self.downloads, [(SUCCEEDED["content"]["video_url"], out)])
        self.assertTrue(os.path.isdir(os.path.dirname(out)))
        rows = self.rows()[3:]
        self.assert_one_request(rows, "ok")
        self.assertEqual([r["task_id"] for r in rows], ["", "cgt-test-1", "cgt-test-1"])
        r = rows[-1]
        self.assertEqual((r["kind"], r["status"], r["seconds"], r["task_id"], r["size"]),
                         ("video", "ok", "5", "cgt-test-1", "720p"))      # the CLI default
        self.assertEqual(json.loads(r["usage"]), {"completion_tokens": 7})


class TestVideoRows(ArkCase):
    def test_task_failed_one_final_row(self):
        self.fake(polls=[{"status": "failed", "error": {"code": "OutputVideoSensitive"}}])
        code, _, err = self.run_ark("video", "x", str(self.tmp / "v.mp4"), *self.cost)
        self.assertEqual(code, 1)
        self.assertIn("OutputVideoSensitive", err)
        rows = self.rows()
        self.assert_one_request(rows, "failed")
        self.assertEqual((len(rows), rows[-1]["task_id"]), (3, "cgt-test-1"))

    def test_task_creation_failed(self):
        self.fake(create=SystemExit("HTTP 400: InvalidParameter"))
        code, _, _ = self.run_ark("video", "x", str(self.tmp / "v.mp4"), *self.cost)
        self.assertEqual(code, 1)
        rows = self.rows()
        self.assert_one_request(rows, "failed")
        r = rows[-1]
        self.assertEqual((len(rows), r["task_id"], r["seconds"]), (2, "", "5"))
        self.assertIn("task creation", r["note"])

    def test_polling_error_logged(self):
        # a 4xx on a status GET is not retried (transient 5xx / network errors are: test_ark_guards.TestPolling)
        self.fake(polls=[{"status": "running"}, SystemExit("HTTP 404: poll broke")])
        code, _, err = self.run_ark("video", "x", str(self.tmp / "v.mp4"), *self.cost)
        self.assertEqual(code, 1)
        self.assertIn("poll broke", err)
        self.assertIn("--resume-task cgt-test-1", err)
        rows = self.rows()
        self.assert_one_request(rows, "failed")
        self.assertEqual(rows[-1]["task_id"], "cgt-test-1")
        self.assertIn("polling stopped", rows[-1]["note"])

    def test_download_failed(self):
        self.fake(polls=[SUCCEEDED])
        out = str(self.tmp / "v.mp4")
        with mock.patch.object(ark, "download", side_effect=OSError("connection reset")):
            code, so, err = self.run_ark("video", "x", out, *self.cost)
        self.assertEqual(code, 1)
        self.assertIn("task_id cgt-test-1", err)
        self.assertIn("url " + SUCCEEDED["content"]["video_url"], err)
        rows = self.rows()
        self.assert_one_request(rows, "failed")
        self.assertIn("download-failed", rows[-1]["note"])
        self.assertEqual(json.loads(rows[-1]["usage"]), {"completion_tokens": 7})
        self.assertEqual(len(ark.billed_requests(rows)), 1)

    def test_interrupt_after_creation_keeps_task_id(self):
        """KeyboardInterrupt right after the task is created: the task id is already in a pending row."""
        self.fake(polls=[KeyboardInterrupt()])
        code, _, _ = self.run_ark_raising("video", "x", str(self.tmp / "v.mp4"), *self.cost)
        rows = self.rows()
        self.assert_one_request(rows, "failed")
        self.assertEqual([r["task_id"] for r in rows], ["", "cgt-test-1", "cgt-test-1"])

    def run_ark_raising(self, *argv):
        try:
            return self.run_ark(*argv)
        except KeyboardInterrupt:
            return None, "", ""


class TestSignals(ArkCase):
    def test_sigterm_during_image_call_writes_failed_row(self):
        f = FakeArk()

        def killed(*args, **kw):
            f.calls.append(args)
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(5)   # the handler raises before this returns
            raise AssertionError("SIGTERM handler did not raise")
        with mock.patch.object(ark, "call", killed):
            code, _, err = self.run_ark("image", "x", str(self.tmp / "a.png"), *self.cost)
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertIn("interrupted by SIGTERM", err)
        rows = self.rows()
        self.assert_one_request(rows, "failed")
        self.assertIn("interrupted by SIGTERM", rows[-1]["note"])
        self.assertEqual(signal.getsignal(signal.SIGTERM), signal.SIG_DFL)   # handler restored

    def test_sigterm_during_video_polling(self):
        base = FakeArk()

        def call(method, path, body=None, timeout=300):
            if path.startswith("/contents/generations/tasks/"):
                os.kill(os.getpid(), signal.SIGTERM)
                time.sleep(5)
            return base(method, path, body, timeout)
        with mock.patch.object(ark, "call", call):
            code, _, err = self.run_ark("video", "x", str(self.tmp / "v.mp4"), *self.cost)
        self.assertEqual(code, 128 + signal.SIGTERM)
        rows = self.rows()
        self.assert_one_request(rows, "failed")
        self.assertEqual(rows[-1]["task_id"], "cgt-test-1")
        self.assertIn("interrupted by SIGTERM", rows[-1]["note"])

    KILL_SCRIPT = (
        "import importlib.util, os, signal, sys\n"
        "s = importlib.util.spec_from_file_location('a', sys.argv[1]); m = importlib.util.module_from_spec(s)\n"
        "s.loader.exec_module(m)\n"
        "m.POLL_SECONDS = 0\n"
        "def call(method, path, body=None, timeout=300):\n"
        "    if path == '/contents/generations/tasks':\n"
        "        return {'id': 'cgt-killed-1'}\n"
        "    os.kill(os.getpid(), signal.SIGKILL)   # image call or first poll\n"
        "m.call = call\n"
        "m.main(sys.argv[2:])\n")

    def sigkill_run(self, *argv):
        pr = subprocess.run([sys.executable, "-c", self.KILL_SCRIPT, str(REPO / "tools" / "ark.py"), *argv],
                            capture_output=True, text=True, timeout=60)
        self.assertEqual(pr.returncode, -signal.SIGKILL, pr.stderr)
        return pr

    def test_sigkill_during_image_call_leaves_pending(self):
        self.sigkill_run("image", "x", str(self.tmp / "a.png"), *self.cost)
        rows = self.rows()
        self.assertEqual([r["status"] for r in rows], ["pending"])
        self.assertEqual(len(ark.billed_requests(rows)), 1)

    def test_sigkill_during_video_polling_keeps_task_id_then_resume(self):
        out = str(self.tmp / "v.mp4")
        pr = self.sigkill_run("video", "x", out, *self.cost)
        self.assertIn("task cgt-killed-1", pr.stdout)
        rows = self.rows()
        self.assertEqual([(r["status"], r["task_id"]) for r in rows], [("pending", ""), ("pending", "cgt-killed-1")])
        rid = ark.req_id(rows[0])
        self.assertEqual(ark.req_id(rows[1]), rid)
        self.assertEqual(sum(ark.units(r) for r in ark.billed_requests(rows)), 5)
        # resume: no creation, no budget check (cap already used up), final row with the same req id
        self.write_budget("video_seconds: 5\n")
        f = self.fake(polls=[{"status": "running"}, SUCCEEDED])
        code, so, _ = self.run_ark("video", "--resume-task", "cgt-killed-1", "--ledger", self.ledger)
        self.assertEqual(code, 0, so)
        self.assertEqual(f.generation_calls(), [])
        self.assertEqual(self.downloads, [(SUCCEEDED["content"]["video_url"], out)])   # out taken from the ledger
        rows = self.rows()
        self.assertEqual(len(rows), 3)
        r = rows[-1]
        self.assertEqual((r["status"], r["task_id"], ark.req_id(r), r["seconds"], r["out"]),
                         ("ok", "cgt-killed-1", rid, "5", out))
        self.assertIn("resumed", r["note"])
        self.assertEqual(sum(ark.units(r) for r in ark.billed_requests(rows)), 5)


class TestResume(ArkCase):
    def test_resume_unknown_task_uses_flags(self):
        f = self.fake(polls=[SUCCEEDED])
        out = str(self.tmp / "r" / "v.mp4")
        code, _, err = self.run_ark("video", "--resume-task", "cgt-other", out, "--duration", "8",
                                    "--ledger", self.ledger)
        self.assertEqual(code, 0)
        self.assertIn("not in", err)
        self.assertEqual(f.generation_calls(), [])
        (r,) = self.rows()
        self.assertEqual((r["status"], r["task_id"], r["seconds"], r["out"], ark.req_id(r)),
                         ("ok", "cgt-other", "8", out, None))
        self.assertEqual(self.downloads, [(SUCCEEDED["content"]["video_url"], out)])

    def test_resume_task_failed(self):
        self.seed_ledger({"kind": "video", "model": "m", "seconds": 5, "status": "pending", "task_id": "t1",
                          "out": str(self.tmp / "v.mp4"), "note": "req=abc123; task created"})
        self.fake(polls=[{"status": "expired"}])
        code, _, _ = self.run_ark("video", "--resume-task", "t1", "--ledger", self.ledger)
        self.assertEqual(code, 1)
        r = self.rows()[-1]
        self.assertEqual((r["status"], ark.req_id(r)), ("failed", "abc123"))
        self.assertIn("resumed; task expired", r["note"])


class TestImageFlags(ArkCase):
    def body(self, f):
        (call,) = f.generation_calls()
        return call[2]

    def test_only_given_keys(self):
        f = self.fake()
        self.run_ark("image", "x", str(self.tmp / "a.png"), "--no-budget")
        b = self.body(f)
        for k in ("seed", "negative_prompt", "guidance_scale", "image"):
            self.assertNotIn(k, b)
        self.assertEqual(b["response_format"], "b64_json")

    def test_seed_negative_guidance(self):
        f = self.fake()
        self.run_ark("image", "x", str(self.tmp / "a.png"), "--seed", "42", "--negative", "text",
                     "--negative", "signature, watermark", "--guidance", "5.5", "--no-budget")
        b = self.body(f)
        self.assertEqual(b["seed"], 42)
        self.assertEqual(b["negative_prompt"], "text, signature, watermark")
        self.assertEqual(b["guidance_scale"], 5.5)

    def test_help_mentions_unverified(self):
        self.assertIn("unverified", ark.i.format_help())


class TestRefReencode(ArkCase):
    def make(self, name, size, mode="RGBA"):
        path = self.tmp / name
        im = Image.new(mode, size, (200, 30, 30, 0) if mode == "RGBA" else (200, 30, 30))
        if mode == "RGBA":   # right half opaque red, left half transparent
            im.paste((200, 30, 30, 255), (size[0] // 2, 0, size[0], size[1]))
        im.save(path)
        return path

    def test_large_rgba_png(self):
        src = self.make("big.png", (3000, 1500))
        before = hashlib.sha256(src.read_bytes()).hexdigest()
        raw, desc = ark.ref_jpeg(str(src))
        self.assertEqual(raw[:3], b"\xff\xd8\xff")
        with Image.open(io.BytesIO(raw)) as im:
            self.assertEqual((im.format, im.mode, im.size), ("JPEG", "RGB", (2048, 1024)))
            left = im.getpixel((10, 500))
            right = im.getpixel((2000, 500))
        self.assertTrue(all(c >= 250 for c in left), left)     # alpha flattened onto white
        self.assertGreater(right[0], 180)
        self.assertLess(right[1], 60)
        self.assertIn("-> 2048x1024 JPEG", desc)
        self.assertEqual(hashlib.sha256(src.read_bytes()).hexdigest(), before)   # disk untouched

    def test_small_kept_size(self):
        src = self.tmp / "small.png"
        Image.new("P", (120, 60)).save(src)
        raw, _ = ark.ref_jpeg(str(src))
        with Image.open(io.BytesIO(raw)) as im:
            self.assertEqual((im.mode, im.size), ("RGB", (120, 60)))

    def test_image_sends_jpeg_refs(self):
        a = self.make("a.png", (2500, 2500))
        b = self.tmp / "b.jpg"
        Image.new("RGB", (64, 64), (1, 2, 3)).save(b)
        f = self.fake()
        code, so, _ = self.run_ark("image", "x", str(self.tmp / "o.png"), "--ref", str(a), str(b), "--no-budget")
        self.assertEqual(code, 0)
        self.assertIn("ref a.png: 2500x2500 PNG", so)
        imgs = f.generation_calls()[0][2]["image"]
        self.assertEqual(len(imgs), 2)
        for u in imgs:
            self.assertTrue(u.startswith("data:image/jpeg;base64,"))
        with Image.open(io.BytesIO(base64.b64decode(imgs[0].split(",", 1)[1]))) as im:
            self.assertEqual(im.size, (2048, 2048))

    def test_single_ref_is_string(self):
        b = self.tmp / "b.jpg"
        Image.new("RGB", (64, 64)).save(b)
        f = self.fake()
        self.run_ark("image", "x", str(self.tmp / "o.png"), "--ref", str(b), "--no-budget")
        self.assertIsInstance(f.generation_calls()[0][2]["image"], str)


if __name__ == "__main__":
    unittest.main()
