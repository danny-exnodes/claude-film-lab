"""tools/ark.py local guards: every refusal here exits 2 before anything is written or sent.
Budget validation, output guard, proxy-cut guards, video arguments, polling/download robustness,
ledger header, redaction in lambda-job finish. Network is always mocked (only FAKEKEY literals)."""
import contextlib, http.server, io, json, os, threading, unittest, urllib.error
from pathlib import Path
from unittest import mock

from PIL import Image

from test_ark import ArkCase, SUCCEEDED, ark

REAL_DOWNLOAD = ark.download      # ArkCase replaces ark.download with a recorder
PRO = "dola-seedream-5-0-pro-260628"


class GuardCase(ArkCase):
    def setUp(self):
        super().setUp()
        self.outdir = self.tmp / "new"            # must never be created by a refused request
        self.png = str(self.outdir / "a_v01.png")
        self.mp4 = str(self.outdir / "c_v01.mp4")

    def ledger_bytes(self):
        return Path(self.ledger).read_bytes() if os.path.exists(self.ledger) else None

    def refused(self, *argv, code=2):
        """Run; assert the exit code, no API call at all, ledger untouched, no output folder. Returns stderr."""
        f = self.fake()
        before = self.ledger_bytes()
        got, _, err = self.run_ark(*argv)
        self.assertEqual(got, code, err)
        self.assertEqual(f.calls, [])
        self.assertEqual(self.ledger_bytes(), before)
        self.assertFalse(self.outdir.exists())
        self.assertNotIn("Traceback", err)
        return err

    def sent(self, *argv):
        f = self.fake(polls=[SUCCEEDED])
        code, _, err = self.run_ark(*argv)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(f.generation_calls()), 1)
        return f, err

    def image_args(self, *extra):
        return ("image", "x", self.png, *extra, *self.cost)

    def video_args(self, *extra):
        return ("video", "x", self.mp4, *extra, *self.cost)


class TestBudgetValidation(GuardCase):
    def test_typo_key_names_the_closest_key(self):
        self.write_budget("image: 2\n")
        err = self.refused(*self.image_args())
        self.assertIn(f"budget {self.budget}", err)
        self.assertIn("'image'", err)
        self.assertIn("did you mean 'images'", err)
        for k in ("images", "video_seconds", "models", "ledger_required"):
            self.assertIn(k, err)

    def test_typo_key_is_refused_every_time(self):
        """The reproduction: 4 requests under a 2-image typo budget used to be sent."""
        self.write_budget("image: 2\n")
        f = self.fake()
        for k in range(4):
            self.assertEqual(self.run_ark("image", "x", str(self.tmp / f"p{k}.png"), *self.cost)[0], 2)
        self.assertEqual(f.calls, [])

    def test_empty_file(self):
        self.write_budget("")
        self.assertIn("has no cap for image", self.refused(*self.image_args()))

    def test_comment_only_file(self):
        self.write_budget("# caps go here\n")
        err = self.refused(*self.video_args())
        self.assertIn(f"budget {self.budget} has no cap for video ({ark.VIDEO_DEFAULT})", err)

    def test_top_level_must_be_a_mapping(self):
        self.write_budget("- images\n- 2\n")
        self.assertIn("mapping", self.refused(*self.image_args()))

    def test_string_cap(self):
        self.write_budget("images: '40'\n")
        self.assertIn("'images' must be a number >= 0", self.refused(*self.image_args()))

    def test_negative_cap(self):
        self.write_budget("images: 10\nvideo_seconds: -5\n")
        self.assertIn("'video_seconds' must be a number >= 0", self.refused(*self.image_args()))

    def test_bool_cap(self):
        self.write_budget("images: true\n")
        self.assertIn("'images' must be a number >= 0", self.refused(*self.image_args()))

    def test_key_without_value(self):
        self.write_budget("images:\nvideo_seconds: 10\n")
        self.assertIn("'images' must be a number >= 0", self.refused(*self.image_args()))

    def test_missing_file(self):
        os.remove(self.budget)
        err = self.refused(*self.image_args())
        self.assertIn(f"budget {self.budget}:", err)
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_invalid_yaml(self):
        self.write_budget("images: [1, 2\n")
        err = self.refused(*self.image_args())
        self.assertIn(f"budget {self.budget}:", err)
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_ledger_required_as_string(self):
        self.write_budget("images: 5\nledger_required: 'false'\n")
        self.assertIn("'ledger_required' must be true or false", self.refused(*self.image_args()))

    def test_models_must_map_to_numbers(self):
        self.write_budget("images: 5\nmodels: 3\n")
        self.assertIn("'models'", self.refused(*self.image_args()))
        self.write_budget(f"images: 5\nmodels:\n  {PRO}: many\n")
        self.assertIn(f"models.{PRO}", self.refused(*self.image_args()))
        self.write_budget(f"images: 5\nmodels:\n  {PRO}: -1\n")
        self.assertIn(f"models.{PRO}", self.refused(*self.image_args()))

    def test_null_models_is_allowed(self):
        self.write_budget("images: 5\nmodels:\n")
        self.sent(*self.image_args())

    def test_video_under_images_only_budget(self):
        self.write_budget("images: 40\n")
        err = self.refused(*self.video_args())
        self.assertIn(f"budget {self.budget} has no cap for video ({ark.VIDEO_DEFAULT})", err)

    def test_image_covered_only_by_model_cap_is_sent(self):
        self.write_budget(f"video_seconds: 10\nmodels:\n  {ark.IMAGE_DEFAULT}: 2\n")
        self.sent(*self.image_args())
        self.assertEqual([r["status"] for r in self.rows()], ["pending", "ok"])
        # the same budget does not cover another image model
        self.outdir = self.tmp / "other"
        err = self.refused("image", "x", str(self.outdir / "b.png"), "--fast", *self.cost)
        self.assertIn(f"has no cap for image ({ark.IMAGE_FAST})", err)

    def test_lambda_prepare_validates_too(self):
        self.write_budget("image: 2\n")
        self.refused("lambda-job", "prepare", "x", self.png, *self.cost)

    def test_no_budget_skips_validation(self):
        self.write_budget("image: 2\n")
        self.sent("image", "x", self.png, "--no-budget", *self.cost)

    def test_return_shape(self):
        self.write_budget(f"images: 3\nvideo_seconds: 2.5\nmodels:\n  {PRO}: 1\nledger_required: true\n")
        self.assertEqual(ark.load_budget(self.budget),
                         {"images": 3, "video_seconds": 2.5, "models": {PRO: 1}, "ledger_required": True})
        self.write_budget("images: 3\n")
        self.assertEqual(ark.load_budget(self.budget),
                         {"images": 3, "video_seconds": None, "models": {}, "ledger_required": False})


class TestOutputGuard(GuardCase):
    def setUp(self):
        super().setUp()
        self.outdir = self.tmp / "never"          # these tests write into self.tmp / "plates"
        self.plates = self.tmp / "plates"
        self.plates.mkdir()

    def existing(self, name, data=b"paid"):
        path = self.plates / name
        path.write_bytes(data)
        return str(path)

    def test_existing_file_refused_with_next_free_version(self):
        out = self.existing("s01_L1_v01.png")
        self.existing("s01_L1_v02.png")
        err = self.refused("image", "x", out, *self.cost)
        self.assertIn(f"output exists: {out}", err)
        self.assertIn(f"next free: {self.plates / 's01_L1_v03.png'}", err)
        self.assertEqual(Path(out).read_bytes(), b"paid")

    def test_suggestion_keeps_zero_padding_and_counts_past_9(self):
        out = self.existing("clip_v009.mp4")
        err = self.refused("video", "x", out, *self.cost)
        self.assertIn(f"next free: {self.plates / 'clip_v010.mp4'}", err)

    def test_name_without_version_has_no_suggestion(self):
        out = self.existing("plain.png")
        err = self.refused("image", "x", out, *self.cost)
        self.assertIn(f"output exists: {out}", err)
        self.assertNotIn("next free", err)

    def test_second_image_to_the_same_plate_is_not_billed_twice(self):
        out = str(self.plates / "s02_L1_v01.png")
        f = self.fake()
        self.assertEqual(self.run_ark("image", "x", out, *self.cost)[0], 0)
        self.assertEqual(self.run_ark("image", "x", out, *self.cost)[0], 2)
        self.assertEqual(len(f.generation_calls()), 1)
        self.assertEqual([r["status"] for r in self.rows()], ["pending", "ok"])

    def test_overwrite_sends(self):
        out = self.existing("s01_L1_v01.png")
        self.sent("image", "x", out, "--overwrite", *self.cost)
        with Image.open(out) as im:
            self.assertEqual(im.format, "PNG")
        clip = self.existing("c_v01.mp4")
        self.sent("video", "x", clip, "--overwrite", *self.cost)

    def test_zero_byte_file_does_not_block(self):
        out = self.existing("s01_L1_v01.png", b"")
        self.sent("image", "x", out, *self.cost)

    def test_resume_task_is_not_blocked(self):
        out = self.existing("c_v01.mp4")
        f = self.fake(polls=[SUCCEEDED])
        code, _, err = self.run_ark("video", "--resume-task", "cgt-9", out, "--ledger", self.ledger)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.downloads, [(SUCCEEDED["content"]["video_url"], out)])

    def test_lambda_prepare_refuses_existing_output(self):
        out = self.existing("s01_L1_v01.png")
        f = self.fake()
        code, so, err = self.run_ark("lambda-job", "prepare", "x", out, *self.cost)
        self.assertEqual((code, so), (2, ""))                # no payload -> nothing to invoke
        self.assertIn("output exists", err)
        self.assertFalse(os.path.exists(self.ledger))
        code, so, _ = self.run_ark("lambda-job", "prepare", "x", out, "--overwrite", *self.cost)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(so)["prompt"], "x")

    def test_help_shows_overwrite(self):
        for parser in (ark.i, ark.v, ark.lp):
            self.assertIn("--overwrite", parser.format_help())


class TestProxyCutGuards(GuardCase):
    def test_large_sizes_refused(self):
        for size in ("3840x2160", "4096x2304", "8K", "4k", "4K", "3840X2160"):
            with self.subTest(size=size):
                err = self.refused(*self.image_args("--size", size))
                self.assertIn("larger than 2K", err)
                self.assertIn("lambda-job prepare", err)

    def test_sizes_up_to_2k_sent(self):
        for n, size in enumerate(("2560x1440", "2K", "1k", "1024x1024", "2048x2048")):
            with self.subTest(size=size):
                f, _ = self.sent("image", "x", str(self.tmp / f"ok{n}.png"), "--size", size, *self.cost)
                self.assertEqual(f.generation_calls()[0][2]["size"], size)

    def test_unknown_size(self):
        err = self.refused(*self.image_args("--size", "banana"))
        self.assertIn("unknown --size banana", err)

    def test_force_sends(self):
        self.sent("image", "x", str(self.tmp / "f1.png"), "--size", "4K", "--force", *self.cost)
        self.sent("image", "x", str(self.tmp / "f2.png"), "--model", PRO, "--force", *self.cost)

    def test_pro_model_variants_refused(self):
        for model in (PRO, "Dola-Seedream-5-0-pro-260628", "dola-seedream-5-0-pro-261101"):
            with self.subTest(model=model):
                err = self.refused(*self.image_args("--model", model))
                self.assertIn("lambda-job prepare", err)

    def test_refusal_text_hides_force_from_agents(self):
        err = self.refused(*self.image_args("--size", "4K")) + self.refused(*self.image_args("--model", PRO))
        self.assertNotIn("--force", err)
        del os.environ["FILM_AGENT"]
        err = self.refused(*self.image_args("--size", "4K"))
        self.assertIn("--force", err)
        self.assertIn("--force", self.refused(*self.image_args("--model", PRO)))

    def test_missing_ref(self):
        missing = str(self.tmp / "nope.png")
        err = self.refused(*self.image_args("--ref", missing))
        self.assertIn(f"no such file: {missing}", err)
        err = self.refused("lambda-job", "prepare", "x", self.png, "--ref", missing, *self.cost)
        self.assertIn(f"no such file: {missing}", err)

    def test_missing_first_frame(self):
        missing = str(self.tmp / "nope.png")
        err = self.refused(*self.video_args("--image", missing))
        self.assertIn(f"no such file: {missing}", err)

    def test_lambda_prepare_notes_named_sizes_only(self):
        f = self.fake()
        for n, size in enumerate(("1K", "2K", "4K")):
            code, _, err = self.run_ark("lambda-job", "prepare", "x", str(self.tmp / f"n{n}.png"),
                                        "--size", size, *self.cost)
            self.assertEqual(code, 0)
            self.assertEqual(len([ln for ln in err.splitlines() if "aspect ratio" in ln]), 1)
        code, _, err = self.run_ark("lambda-job", "prepare", "x", str(self.tmp / "wh.png"),
                                    "--size", "2560x1440", *self.cost)
        self.assertEqual(code, 0)
        self.assertNotIn("aspect ratio", err)
        self.assertEqual(f.calls, [])


class TestVideoArguments(GuardCase):
    def test_duration_must_be_positive(self):
        for d in ("0", "-1", "-20", "five"):
            with self.subTest(duration=d):
                self.refused(*self.video_args("--duration", d))

    def test_unknown_resolution(self):
        self.refused(*self.video_args("--resolution", "9999p"))

    def test_default_resolution_is_720p(self):
        f, _ = self.sent(*self.video_args())
        self.assertEqual(f.generation_calls()[0][2]["resolution"], "720p")
        self.assertEqual(self.rows()[-1]["size"], "720p")
        self.assertIn("720p", ark.v.format_help())

    def test_units_is_never_negative(self):
        self.assertEqual(ark.units({"kind": "video", "seconds": "-20"}), 0)
        self.assertEqual(ark.units({"kind": "image", "count": "-3"}), 0)
        self.assertEqual(ark.units({"kind": "video", "seconds": "5"}), 5)
        self.assertEqual(ark.units({"kind": "image", "count": ""}), 1)


class TestPolling(ArkCase):
    def setUp(self):
        super().setUp()
        self.out = str(self.tmp / "v.mp4")
        self.sleeps = []
        p = mock.patch.object(ark.time, "sleep", self.sleeps.append)
        p.start()
        self.addCleanup(p.stop)

    def video(self, **kw):
        f = self.fake(**kw)
        code, so, err = self.run_ark("video", "x", self.out, *self.cost)
        return f, code, err

    def test_one_503_does_not_end_a_paid_task(self):
        f, code, err = self.video(polls=[{"status": "running"}, SystemExit("HTTP 503: x"), {"status": "running"},
                                         SUCCEEDED])
        self.assertEqual(code, 0, err)
        self.assertIn("poll error (1/5): HTTP 503: x", err)
        rows = self.rows()
        self.assert_one_request(rows, "ok")
        self.assertEqual([r["status"] for r in rows].count("ok"), 1)
        self.assertEqual(len(f.generation_calls()), 1)          # the POST is never repeated
        self.assertEqual(self.downloads, [(SUCCEEDED["content"]["video_url"], self.out)])

    def test_retryable_kinds(self):
        polls = [SystemExit("network error: URLError: timed out"), SystemExit("HTTP 429: slow down"),
                 SystemExit("HTTP 502: bad gateway"), SUCCEEDED]
        f, code, err = self.video(polls=polls)
        self.assertEqual(code, 0, err)
        self.assertIn("poll error (3/5)", err)
        self.assert_one_request(self.rows(), "ok")

    def test_success_resets_the_count(self):
        polls = []
        for _ in range(3):
            polls += [SystemExit("HTTP 503: x")] * 4 + [{"status": "running"}]
        f, code, err = self.video(polls=polls + [SUCCEEDED])
        self.assertEqual(code, 0, err)
        self.assertNotIn("(5/5)", err)

    def test_backoff_is_capped(self):
        with mock.patch.object(ark, "POLL_SECONDS", 10):
            f, code, err = self.video(polls=[SystemExit("HTTP 503: x")] * 5 + [SUCCEEDED])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sleeps, [10, 20, 40, 60, 60, 60])

    def test_six_consecutive_errors_end_polling(self):
        f, code, err = self.video(polls=[SystemExit("HTTP 503: x")] * 6 + [SUCCEEDED])
        self.assertEqual(code, 1)
        self.assertIn("poll error (5/5)", err)
        self.assertIn(f"--resume-task cgt-test-1 {self.out}", err)
        rows = self.rows()
        self.assert_one_request(rows, "failed")
        self.assertEqual([r["status"] for r in rows].count("failed"), 1)
        self.assertIn("polling stopped (task may still run): HTTP 503", rows[-1]["note"])
        self.assertEqual(len(f.calls), 1 + 6)
        self.assertEqual(self.downloads, [])

    def test_http_400_is_fatal_at_once(self):
        f, code, err = self.video(polls=[SystemExit("HTTP 400: x"), SUCCEEDED])
        self.assertEqual(code, 1)
        self.assertNotIn("poll error", err)
        self.assertIn("--resume-task cgt-test-1", err)
        self.assert_one_request(self.rows(), "failed")
        self.assertEqual(len(f.calls), 2)

    def test_task_creation_is_never_retried(self):
        f, code, err = self.video(create=SystemExit("HTTP 503: x"))
        self.assertEqual(code, 1)
        self.assertEqual(len(f.calls), 1)
        self.assert_one_request(self.rows(), "failed")

    def test_succeeded_without_video_url(self):
        f, code, err = self.video(polls=[{"status": "succeeded", "content": {}, "usage": {"completion_tokens": 7}}])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)
        self.assertIn(f"--resume-task cgt-test-1 {self.out}", err)
        rows = self.rows()
        self.assert_one_request(rows, "failed")
        self.assertEqual([r["status"] for r in rows].count("failed"), 1)
        self.assertIn('no video_url in task: {"status": "succeeded"', rows[-1]["note"])
        self.assertEqual(self.downloads, [])


class TestNetworkErrors(ArkCase):
    def test_urlerror_is_a_clean_exit(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")) as uo:
            code, _, err = self.run_ark("image", "x", str(self.tmp / "a.png"), *self.cost)
        self.assertEqual(code, 1)
        self.assertEqual(uo.call_count, 1)
        self.assertIn("network error: URLError", err)
        self.assertNotIn("Traceback", err)
        rows = self.rows()
        self.assert_one_request(rows, "failed")
        self.assertIn("network error", rows[-1]["note"])

    def test_timeout_and_reset(self):
        for exc in (TimeoutError("timed out"), ConnectionResetError("reset by peer")):
            with self.subTest(exc=type(exc).__name__):
                with mock.patch("urllib.request.urlopen", side_effect=exc):
                    with self.assertRaises(SystemExit) as cm:
                        ark.call("GET", "/models")
                self.assertIn(f"network error: {type(exc).__name__}", str(cm.exception))

    def test_no_authorization_value_in_the_message(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("x")):
            with self.assertRaises(SystemExit) as cm:
                ark.call("GET", "/models")
        self.assertNotIn("Bearer", str(cm.exception))


class _Clip(http.server.BaseHTTPRequestHandler):
    BODY = b"\x00\x00\x00\x18ftypmp42" + b"v" * 5000
    plan = []           # per request: "short" or "ok"
    seen = 0

    def do_GET(self):
        cls = type(self)
        step = cls.plan[min(cls.seen, len(cls.plan) - 1)]
        cls.seen += 1
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.BODY)))
        self.end_headers()
        self.wfile.write(self.BODY if step == "ok" else self.BODY[:200])

    def log_message(self, *args):
        pass


class TestDownload(ArkCase):
    """The real download() against a local server (no proxy, nothing leaves the machine)."""

    def setUp(self):
        super().setUp()
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "*"
        _Clip.seen = 0
        self.srv = http.server.HTTPServer(("127.0.0.1", 0), _Clip)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/v.mp4"
        self.out = self.tmp / "clips_v01.mp4"
        p = mock.patch.object(ark, "DOWNLOAD_RETRY_SECONDS", 0)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def leftovers(self):
        return sorted(p.name for p in self.tmp.iterdir() if p.name.startswith("clips_v01"))

    def fetch(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            REAL_DOWNLOAD(self.url, str(self.out))
        return err.getvalue()

    def test_short_body_leaves_nothing(self):
        _Clip.plan = ["short"]
        with self.assertRaises(OSError):
            self.fetch()
        self.assertEqual(_Clip.seen, 3)
        self.assertEqual(self.leftovers(), [])

    def test_third_attempt_succeeds(self):
        _Clip.plan = ["short", "short", "ok"]
        self.assertIn("download error (2/3)", self.fetch())
        self.assertEqual(_Clip.seen, 3)
        self.assertEqual(self.out.read_bytes(), _Clip.BODY)
        self.assertEqual(self.leftovers(), ["clips_v01.mp4"])

    def test_failed_download_keeps_an_older_file(self):
        self.out.write_bytes(b"approved clip")
        _Clip.plan = ["short"]
        with self.assertRaises(OSError):
            self.fetch()
        self.assertEqual(self.out.read_bytes(), b"approved clip")
        self.assertEqual(self.leftovers(), ["clips_v01.mp4"])

    def test_video_run_with_a_broken_download_leaves_no_stub(self):
        _Clip.plan = ["short"]
        self.fake(polls=[{"status": "succeeded", "content": {"video_url": self.url}}])
        with mock.patch.object(ark, "download", REAL_DOWNLOAD):
            code, _, err = self.run_ark("video", "x", str(self.out), *self.cost)
        self.assertEqual(code, 1)
        self.assertIn("DOWNLOAD FAILED", err)
        self.assertEqual(self.leftovers(), [])
        rows = self.rows()
        self.assert_one_request(rows, "failed")
        self.assertIn("download-failed", rows[-1]["note"])


class TestLedgerHeader(GuardCase):
    GOOD = ",".join(ark.LEDGER_FIELDS)
    ROW = "2026-11-10T01:00:00Z,image,m,2K,,1,ok,a.png,,,film-art,req=a{}\n"

    def write_ledger(self, header, n=5, sep=",", eol="\n", bom=b""):
        text = header + "\n" + "".join(self.ROW.format(k) for k in range(n))
        text = text.replace(",", sep).replace("\n", eol)
        Path(self.ledger).write_bytes(bom + text.encode())

    def test_renamed_column_refused(self):
        self.write_budget("images: 2\n")
        self.write_ledger(self.GOOD.replace("status", "state"))
        err = self.refused(*self.image_args())
        self.assertIn(f"ledger header mismatch in {self.ledger}", err)
        self.assertIn("nothing sent", err)

    def test_semicolon_file_refused(self):
        self.write_budget("images: 2\n")
        self.write_ledger(self.GOOD, sep=";")
        self.assertIn("ledger header mismatch", self.refused(*self.image_args()))
        self.assertIn("ledger header mismatch", self.refused(*self.video_args()))
        self.assertIn("ledger header mismatch", self.refused("lambda-job", "prepare", "x", self.png, *self.cost))

    def test_header_only_wrong_header_refused(self):
        self.write_ledger("when,what,how", n=0)
        self.assertIn("ledger header mismatch", self.refused(*self.image_args()))

    def test_refused_with_no_budget_too(self):
        self.write_ledger(self.GOOD.replace("status", "state"))
        self.assertIn("ledger header mismatch", self.refused("image", "x", self.png, "--no-budget", *self.cost))

    def test_checked_inside_the_lock_as_well(self):
        """reserve() itself refuses: a header that goes bad after the early check still sends nothing."""
        self.write_ledger(self.GOOD.replace("status", "state"))
        with mock.patch.object(ark, "check_ledger_header", lambda path: None):
            self.assertIn("ledger header mismatch", self.refused("image", "x", str(self.tmp / "a.png"), *self.cost))

    def test_crlf_ledger_accepted_and_counted(self):
        self.write_budget("images: 5\n")
        self.write_ledger(self.GOOD, eol="\r\n")
        f = self.fake()
        code, _, err = self.run_ark(*self.image_args())
        self.assertEqual((code, f.calls), (3, []), err)         # 5 ok rows fill the cap of 5
        self.write_budget("images: 6\n")
        self.sent(*self.image_args())

    def test_bom_ledger_accepted_and_counted(self):
        self.write_budget("images: 5\n")
        self.write_ledger(self.GOOD, bom=b"\xef\xbb\xbf")
        f = self.fake()
        code, _, err = self.run_ark(*self.image_args())
        self.assertEqual((code, f.calls), (3, []), err)
        self.write_budget("images: 6\n")
        self.sent(*self.image_args())

    def test_merge_and_reader_stay_tolerant(self):
        self.write_ledger(self.GOOD.replace("note", "remark"))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(len(ark.ledger_rows(self.ledger)), 5)


class TestFinishRedaction(ArkCase):
    def test_bearer_value_never_reaches_stderr_or_the_ledger(self):
        out = str(self.tmp / "plates" / "a.png")
        code, so, _ = self.run_ark("lambda-job", "prepare", "x", out, *self.cost)
        self.assertEqual(code, 0)
        job = json.loads(so)["job_id"]
        st = str(self.tmp / "status.json")
        with open(st, "w") as f:
            json.dump({"job_id": job, "status": "failed", "seconds": 0.4,
                       "error": "Invalid header value b'Bearer FAKEKEY-abc\nFAKEKEY-def'"}, f)
        code, so, err = self.run_ark("lambda-job", "finish", "--status-json", st, "--ledger", self.ledger)
        self.assertEqual(code, 1)
        self.assertNotIn("FAKEKEY", err + so)
        self.assertIn("Invalid header value b'Bearer <redacted>", err)
        rows = self.rows()
        self.assert_one_request(rows, "failed")
        self.assertNotIn("FAKEKEY", Path(self.ledger).read_text())
        self.assertIn("Bearer <redacted>", rows[-1]["note"])

    def test_plain_error_is_unchanged(self):
        self.assertEqual(ark.redact("HTTP 400: bad size"), "HTTP 400: bad size")
        self.assertEqual(ark.redact(None), "")


if __name__ == "__main__":
    unittest.main()
