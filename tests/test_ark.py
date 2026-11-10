"""tools/ark.py: ledger, budget, 502 handling, new image flags, --ref re-encoding. Network is always mocked."""
import base64, csv, hashlib, io, json, os, subprocess, sys, unittest
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


class TestLedger(ArkCase):
    def test_image_ok_row(self):
        f = self.fake()
        out = str(self.tmp / "a.png")
        code, so, _ = self.run_ark("image", "a mountain", out, "--ledger", self.ledger)
        self.assertEqual(code, 0)
        self.assertEqual(len(f.generation_calls()), 1)
        self.assertIn("model seedream-5-0-lite-260128", so)
        self.assertIn("saved " + out, so)
        self.assertIn('usage {"generated_images": 1}', so)
        with open(self.ledger) as fh:
            self.assertEqual(fh.readline().strip(), ",".join(ark.LEDGER_FIELDS))
        (r,) = self.rows()
        self.assertEqual((r["kind"], r["model"], r["size"], r["count"], r["status"], r["out"], r["agent"]),
                         ("image", "seedream-5-0-lite-260128", "2K", "1", "ok", out, "film-test-agent"))
        self.assertEqual(json.loads(r["usage"]), {"generated_images": 1})
        self.assertRegex(r["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        with Image.open(out) as im:
            self.assertEqual(im.format, "PNG")

    def test_env_fallback(self):
        self.fake()
        os.environ["FILM_LEDGER"] = self.ledger
        code, _, _ = self.run_ark("image", "x", str(self.tmp / "b.png"))
        self.assertEqual(code, 0)
        self.assertEqual(len(self.rows()), 1)

    def test_no_ledger_no_file(self):
        self.fake()
        code, _, _ = self.run_ark("image", "x", str(self.tmp / "c.png"))
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(self.ledger))

    def test_http_error_failed_row(self):
        f = self.fake(image=SystemExit('HTTP 400: {"error": "InvalidParameter"}'))
        code, _, err = self.run_ark("image", "x", str(self.tmp / "d.png"), "--ledger", self.ledger)
        self.assertEqual(code, 1)
        self.assertIn("HTTP 400", err)
        (r,) = self.rows()
        self.assertEqual(r["status"], "failed")
        self.assertIn("HTTP 400", r["note"])
        self.assertEqual(len(f.generation_calls()), 1)

    def test_cut_502_row_no_retry(self):
        f = self.fake(image=SystemExit("HTTP 502: upstream request failed"))
        with mock.patch.object(ark, "PROXY_CUTOFF", 5):   # any duration counts as "cut"
            code, _, err = self.run_ark("image", "x", str(self.tmp / "e.png"), "--ledger", self.ledger)
        self.assertEqual(code, 1)
        self.assertIn("NOT retried", err)
        self.assertEqual(len(f.generation_calls()), 1)
        (r,) = self.rows()
        self.assertEqual(r["status"], "cut-502")

    def test_fast_502_is_failed_not_cut(self):
        self.fake(image=SystemExit("HTTP 502: bad gateway"))
        code, _, _ = self.run_ark("image", "x", str(self.tmp / "f.png"), "--ledger", self.ledger)
        self.assertEqual(code, 1)
        self.assertEqual(self.rows()[0]["status"], "failed")

    def test_guard_exits_are_not_api_calls(self):
        f = self.fake()
        code, _, _ = self.run_ark("image", "x", str(self.tmp / "g.png"), "--size", "4K", "--ledger", self.ledger)
        self.assertEqual(code, 1)
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


class TestBudget(ArkCase):
    def test_refused_budget_exit_3(self):
        self.write_budget("images: 2\nvideo_seconds: 60\n")
        self.seed_ledger({"kind": "image", "model": "m1", "count": 1, "status": "ok"},
                         {"kind": "image", "model": "m1", "count": 1, "status": "failed"})
        f = self.fake()
        code, _, err = self.run_ark("image", "x", str(self.tmp / "a.png"), "--ledger", self.ledger, "--budget", self.budget)
        self.assertEqual(code, 3)
        self.assertEqual(f.calls, [])
        self.assertIn("REFUSED", err)
        self.assertIn("images: 2 used + 1 requested > cap 2", err)
        last = self.rows()[-1]
        self.assertEqual((last["status"], last["kind"], last["agent"]), ("refused-budget", "image", "film-test-agent"))

    def test_refused_and_unknown_rows_do_not_count(self):
        self.write_budget("images: 2\n")
        self.seed_ledger({"kind": "image", "model": "m1", "count": 1, "status": "ok"},
                         {"kind": "image", "model": "m1", "count": 1, "status": "refused-budget"},
                         {"kind": "image", "model": "m1", "count": 1, "status": "refused-budget"})
        f = self.fake()
        code, _, _ = self.run_ark("image", "x", str(self.tmp / "a.png"), "--ledger", self.ledger, "--budget", self.budget)
        self.assertEqual(code, 0)
        self.assertEqual(len(f.generation_calls()), 1)

    def test_cut_502_counts(self):
        self.write_budget("images: 1\n")
        self.seed_ledger({"kind": "image", "model": "m1", "count": 1, "status": "cut-502"})
        self.fake()
        code, _, _ = self.run_ark("image", "x", str(self.tmp / "a.png"), "--ledger", self.ledger, "--budget", self.budget)
        self.assertEqual(code, 3)

    def test_model_cap(self):
        pro = "dola-seedream-5-0-pro-260628"
        self.write_budget(f"images: 40\nmodels:\n  {pro}: 1\n")
        self.seed_ledger({"kind": "image", "model": pro, "count": 1, "status": "ok"})
        f = self.fake()
        code, _, err = self.run_ark("image", "x", str(self.tmp / "a.png"), "--model", pro, "--force",
                                    "--ledger", self.ledger, "--budget", self.budget)
        self.assertEqual(code, 3)
        self.assertIn(f"models.{pro}", err)
        code, _, _ = self.run_ark("image", "x", str(self.tmp / "b.png"), "--ledger", self.ledger, "--budget", self.budget)
        self.assertEqual(code, 0)
        self.assertEqual(len(f.generation_calls()), 1)
        self.assertEqual([r["status"] for r in self.rows()], ["ok", "refused-budget", "ok"])

    def test_env_budget(self):
        self.write_budget("images: 0\n")
        os.environ["FILM_BUDGET"] = self.budget
        os.environ["FILM_LEDGER"] = self.ledger
        f = self.fake()
        code, _, _ = self.run_ark("image", "x", str(self.tmp / "a.png"))
        self.assertEqual(code, 3)
        self.assertEqual(f.calls, [])
        self.assertEqual(self.rows()[0]["status"], "refused-budget")

    def test_video_seconds(self):
        self.write_budget("images: 40\nvideo_seconds: 10\n")
        self.seed_ledger({"kind": "video", "model": ark.VIDEO_DEFAULT, "seconds": 5, "count": 1, "status": "ok"},
                         {"kind": "image", "model": "m1", "count": 30, "status": "ok"})
        f = self.fake(polls=[{"status": "running"},
                             {"status": "succeeded", "content": {"video_url": "https://host.example/v.mp4"},
                              "usage": {"completion_tokens": 7}}])
        out = str(self.tmp / "v.mp4")
        code, _, err = self.run_ark("video", "x", out, "--duration", "6", "--ledger", self.ledger, "--budget", self.budget)
        self.assertEqual(code, 3)
        self.assertIn("video_seconds: 5 used + 6 requested > cap 10", err)
        self.assertEqual(f.calls, [])
        code, so, _ = self.run_ark("video", "x", out, "--duration", "5", "--ledger", self.ledger, "--budget", self.budget)
        self.assertEqual(code, 0)
        self.assertIn("task cgt-test-1", so)
        self.assertIn("video host: host.example", so)
        self.assertEqual(self.downloads, [("https://host.example/v.mp4", out)])
        r = self.rows()[-1]
        self.assertEqual((r["kind"], r["status"], r["seconds"], r["task_id"], r["size"]),
                         ("video", "ok", "5", "cgt-test-1", "1080p"))
        self.assertEqual(json.loads(r["usage"]), {"completion_tokens": 7})


class TestVideoRows(ArkCase):
    def test_task_failed_one_row(self):
        self.fake(polls=[{"status": "failed", "error": {"code": "OutputVideoSensitive"}}])
        code, _, err = self.run_ark("video", "x", str(self.tmp / "v.mp4"), "--ledger", self.ledger)
        self.assertEqual(code, 1)
        self.assertIn("OutputVideoSensitive", err)
        (r,) = self.rows()
        self.assertEqual((r["status"], r["task_id"]), ("failed", "cgt-test-1"))

    def test_task_creation_failed(self):
        self.fake(create=SystemExit("HTTP 400: InvalidParameter"))
        code, _, _ = self.run_ark("video", "x", str(self.tmp / "v.mp4"), "--ledger", self.ledger)
        self.assertEqual(code, 1)
        (r,) = self.rows()
        self.assertEqual((r["status"], r["task_id"], r["seconds"]), ("failed", "", "5"))
        self.assertIn("task creation", r["note"])

    def test_polling_error_logged(self):
        self.fake(polls=[{"status": "running"}, SystemExit("HTTP 500: poll broke")])
        code, _, err = self.run_ark("video", "x", str(self.tmp / "v.mp4"), "--ledger", self.ledger)
        self.assertEqual(code, 1)
        self.assertIn("poll broke", err)
        (r,) = self.rows()
        self.assertEqual((r["status"], r["task_id"]), ("failed", "cgt-test-1"))
        self.assertIn("polling stopped", r["note"])


class TestImageFlags(ArkCase):
    def body(self, f):
        (call,) = f.generation_calls()
        return call[2]

    def test_only_given_keys(self):
        f = self.fake()
        self.run_ark("image", "x", str(self.tmp / "a.png"))
        b = self.body(f)
        for k in ("seed", "negative_prompt", "guidance_scale", "image"):
            self.assertNotIn(k, b)
        self.assertEqual(b["response_format"], "b64_json")

    def test_seed_negative_guidance(self):
        f = self.fake()
        self.run_ark("image", "x", str(self.tmp / "a.png"), "--seed", "42", "--negative", "text",
                     "--negative", "signature, watermark", "--guidance", "5.5")
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
        code, so, _ = self.run_ark("image", "x", str(self.tmp / "o.png"), "--ref", str(a), str(b))
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
        self.run_ark("image", "x", str(self.tmp / "o.png"), "--ref", str(b))
        self.assertIsInstance(f.generation_calls()[0][2]["image"], str)


if __name__ == "__main__":
    unittest.main()
