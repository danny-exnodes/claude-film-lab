"""tools/ark.py ledger round 2: strict ledger-merge (multiset, order-independent, file:line errors, never bill less),
ledger-close, failed-unsent / abandoned counting, agents refused --no-budget/--force, multi-image and empty-response
guards, cap 1 under parallel processes. Network is always mocked."""
import os, subprocess, sys, time
from pathlib import Path
from unittest import mock


from helpers import REPO
from test_ark import ArkCase, ark, tiny_jpeg_b64

PRO = "dola-seedream-5-0-pro-260628"
REQ = "0123456789abcdef0123456789abcdef"


def row(req, status, ts, **kw):
    return dict({"ts": ts, "kind": "image", "model": "m", "count": 1, "status": status,
                 "note": f"req={req}" if req else ""}, **kw)


class LedgerCase(ArkCase):
    def ledger_file(self, name, *rows):
        path = str(self.tmp / name)
        for r in rows:
            ark.ledger_append(path, r)
        return path

    def text_file(self, name, text):
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def merge(self, *paths, out=None):
        return self.run_ark("ledger-merge", *paths, "-o", out or self.ledger)


class TestReqId(LedgerCase):
    def test_whole_token_only(self):
        self.assertEqual(ark.req_id({"note": "req=abc"}), "abc")
        self.assertEqual(ark.req_id({"note": "req=abc; lambda"}), "abc")
        self.assertEqual(ark.req_id({"note": "req=abc task created"}), "abc")
        self.assertIsNone(ark.req_id({"note": "req=abcXYZ"}))        # was 'abc' before: another request's id
        self.assertIsNone(ark.req_id({"note": "req=ABC"}))
        self.assertIsNone(ark.req_id({"note": "req="}))
        self.assertIsNone(ark.req_id({"note": "x req=abc"}))


class TestCounting(LedgerCase):
    def test_abandoned_counts_and_closes(self):
        rows = [row("aa", "pending", "2026-11-10T01:00:00Z"), row("aa", "abandoned", "2026-11-10T02:00:00Z")]
        billed = ark.billed_requests(rows)
        self.assertEqual([r["status"] for r in billed], ["abandoned"])
        self.assertEqual(sum(ark.units(r) for r in billed), 1)

    def test_failed_unsent_closes_without_counting(self):
        rows = [row("aa", "pending", "2026-11-10T01:00:00Z"), row("aa", "failed-unsent", "2026-11-10T01:00:05Z"),
                row("bb", "pending", "2026-11-10T01:00:00Z")]
        self.assertEqual([ark.req_id(r) for r in ark.billed_requests(rows)], ["bb"])

    def test_failed_unsent_frees_the_cap(self):
        self.write_budget("images: 1\n")
        self.seed_ledger(row("aa", "pending", "2026-11-10T01:00:00Z"))
        f = self.fake()
        self.assertEqual(self.run_ark("image", "x", str(self.tmp / "a.png"), *self.cost)[0], 3)
        self.seed_ledger(row("aa", "failed-unsent", "2026-11-10T01:00:05Z"))
        self.assertEqual(self.run_ark("image", "x", str(self.tmp / "b.png"), *self.cost)[0], 0)
        self.assertEqual(len(f.generation_calls()), 1)


class TestMergeMultiset(LedgerCase):
    OLD = {"ts": "2026-11-09T00:00:00Z", "kind": "image", "model": "m", "count": 1, "status": "ok", "out": "x.png"}

    def test_two_identical_rows_without_req_are_two_requests(self):
        a = self.ledger_file("a.csv", self.OLD, self.OLD)        # two requests, same second, same file name
        b = self.ledger_file("b.csv", self.OLD)
        self.assertEqual(self.merge(a, b)[0], 0)
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(len(ark.billed_requests(self.rows())), 2)
        self.assertEqual(self.merge(a, b)[0], 0)                  # idempotent: --out's own two rows stay two
        self.assertEqual(len(self.rows()), 2)

    def test_same_copy_twice_is_not_doubled(self):
        a = self.ledger_file("a.csv", self.OLD)
        self.assertEqual(self.merge(a, a)[0], 0)
        self.assertEqual(len(self.rows()), 1)


class TestMergeOrder(LedgerCase):
    def test_result_does_not_depend_on_the_input_order(self):
        a = self.ledger_file("a.csv", row("aa", "pending", "2026-11-10T01:00:00Z"),
                             row("aa", "ok", "2026-11-10T01:00:30Z", usage='{"generated_images":1}', agent="x"),
                             row("", "ok", "2026-11-09T00:00:00Z", out="o.png"))
        b = self.ledger_file("b.csv", row("aa", "pending", "2026-11-10T01:00:00Z"),
                             row("aa", "ok", "2026-11-10T01:00:31Z", count=2, agent="y"),
                             row("cc", "pending", "2026-11-10T01:00:00Z"))
        self.assertEqual(self.merge(a, b, out=str(self.tmp / "ab.csv"))[0], 0)
        self.assertEqual(self.merge(b, a, out=str(self.tmp / "ba.csv"))[0], 0)
        ab, ba = (self.tmp / "ab.csv").read_text(), (self.tmp / "ba.csv").read_text()
        self.assertEqual(ab, ba)
        rows = ark.ledger_rows(str(self.tmp / "ab.csv"))
        oks = [r for r in rows if ark.req_id(r) == "aa" and r["status"] == "ok"]
        self.assertEqual([r["count"] for r in oks], ["2"])        # of two copies of one final row, the larger bill
        self.assertEqual(sum(ark.units(r) for r in ark.billed_requests(rows)), 4)   # aa 2 + cc 1 + old 1


class TestMergeErrors(LedgerCase):
    HEAD = ",".join(ark.LEDGER_FIELDS) + "\n"

    def assert_refused(self, *paths, expect=()):
        before = Path(self.ledger).read_bytes() if os.path.exists(self.ledger) else None
        code, _, err = self.merge(*paths)
        self.assertEqual(code, 2, err)
        self.assertIn("nothing written", err)
        for e in expect:
            self.assertIn(e, err)
        after = Path(self.ledger).read_bytes() if os.path.exists(self.ledger) else None
        self.assertEqual(after, before)
        return err

    def test_every_bad_line_is_named(self):
        bad = self.text_file("bad.csv", self.HEAD
                             + f"2026-11-10T01:00:00Z,image,m,2K,,1,pending,a.png,,,,req={REQ}\n"
                             + "2026-11-10T01:00:01Z,image,m,2K,,1,OK,a.png,,,,\n"                      # line 3
                             + "2026-11-10T01:00:02Z,image,m,2K,,1,ok,a.png,,,\n"                       # line 4
                             + "10/11/2026,image,m,2K,,1,ok,a.png,,,,\n"                                # line 5
                             + "2026-11-10T01:00:03Z,img,m,2K,,two,ok,a.png,,,,\n"                      # line 6
                             + "2026-11-10T01:00:04Z,image,m,2K,,1,ok,a.png,,,,req=abcXYZ\n"            # line 7
                             + "\n"
                             + '2026-11-10T01:00:05Z,image,m,2K,,1,ok,a.png,,,,"multi\nline"\n'        # lines 9-10
                             + "2026-11-10T01:00:06Z,video,m,720p,-5,1,ok,c.mp4,,,,\n")                 # line 11
        err = self.assert_refused(bad, expect=(
            "bad.csv:3: status 'OK'", "bad.csv:4: 11 cells", "bad.csv:5: ts '10/11/2026'",
            "bad.csv:6: kind 'img'", "bad.csv:6: count 'two'", "bad.csv:7: note 'req=abcXYZ'",
            "bad.csv:11: seconds '-5'"))
        self.assertNotIn("bad.csv:2:", err)
        self.assertNotIn("bad.csv:9", err)
        self.assertFalse(os.path.exists(self.ledger))           # not even an empty --out is left behind

    def test_foreign_header_and_unclosed_quote(self):
        hdr = self.text_file("hdr.csv", "ts;kind;model\n")
        quote = self.text_file("quote.csv", self.HEAD + '2026-11-10T01:00:00Z,image,m,2K,,1,ok,a.png,,,,"open\n')
        self.assert_refused(hdr, quote, expect=("hdr.csv:1: header is not", "quote.csv:2:"))

    def test_existing_out_with_a_bad_row_is_left_untouched(self):
        self.seed_ledger(row("aa", "ok", "2026-11-10T01:00:00Z"))
        with open(self.ledger, "a") as f:
            f.write("2026-11-10T01:00:01Z,image,m,2K,,1,done,a.png,,,,\n")
        good = self.ledger_file("good.csv", row("bb", "ok", "2026-11-10T02:00:00Z"))
        self.assert_refused(good, expect=(f"{self.ledger}:3: status 'done'",))

    def test_crlf_and_bom_input_is_fine(self):
        text = "\ufeff" + (self.HEAD + f"2026-11-10T01:00:00Z,image,m,2K,,1,ok,a.png,,,,req={REQ}\n").replace("\n", "\r\n")
        self.assertEqual(self.merge(self.text_file("win.csv", text))[0], 0)
        self.assertEqual([ark.req_id(r) for r in self.rows()], [REQ])


class TestNeverBillLess(LedgerCase):
    def test_disagreeing_copies_are_refused(self):
        """One copy has a two-image ok, the other a later one-image failed row for the same request: the merged
        ledger would count the later row, 1 image instead of 2."""
        a = self.ledger_file("a.csv", row("aa", "pending", "2026-11-10T01:00:00Z"),
                             row("aa", "ok", "2026-11-10T01:00:20Z", count=2))
        b = self.ledger_file("b.csv", row("aa", "pending", "2026-11-10T01:00:00Z"),
                             row("aa", "failed", "2026-11-10T01:00:40Z"))
        code, _, err = self.merge(a, b)
        self.assertEqual(code, 2)
        self.assertIn("request aa counts 2 image m (ok) there but 1 image m (failed) after the merge", err)
        self.assertFalse(os.path.exists(self.ledger))

    def test_failed_unsent_may_close_a_pending_copy(self):
        a = self.ledger_file("a.csv", row("aa", "pending", "2026-11-10T01:00:00Z", note="req=aa; lambda"))
        b = self.ledger_file("b.csv", row("aa", "pending", "2026-11-10T01:00:00Z", note="req=aa; lambda"),
                             row("aa", "failed-unsent", "2026-11-10T01:05:00Z", note="req=aa; lambda; ref missing"))
        code, out, err = self.merge(a, b)
        self.assertEqual(code, 0, err)
        self.assertEqual([r["status"] for r in self.rows()], ["pending", "failed-unsent"])
        self.assertIn("0 image(s)", out)

    def test_abandoned_and_a_later_resumed_ok_both_survive(self):
        v = dict(kind="video", seconds=5, task_id="cgt-1")
        a = self.ledger_file("a.csv", row("aa", "pending", "2026-11-10T01:00:00Z", **v),
                             row("aa", "abandoned", "2026-11-10T03:00:00Z", **v))
        b = self.ledger_file("b.csv", row("aa", "pending", "2026-11-10T01:00:00Z", **v),
                             row("aa", "ok", "2026-11-10T04:00:00Z", **v))
        self.assertEqual(self.merge(a, b)[0], 0)
        self.assertEqual([r["status"] for r in self.rows()], ["pending", "abandoned", "ok"])
        self.assertEqual(sum(ark.units(r) for r in ark.billed_requests(self.rows())), 5)


class TestLedgerClose(LedgerCase):
    def close(self, req, *extra):
        return self.run_ark("ledger-close", "--req", req, "--ledger", self.ledger, "--status", "abandoned", *extra)

    def test_orphan_pending_is_closed_and_still_counts(self):
        self.write_budget("images: 2\n")
        self.seed_ledger(row(REQ, "pending", "2026-11-10T01:00:00Z", model=PRO, out="p.png", note=f"req={REQ}; lambda"))
        code, out, err = self.close(REQ[:8], "--note", "never invoked")
        self.assertEqual(code, 0, err)
        rows = self.rows()
        self.assertEqual([r["status"] for r in rows], ["pending", "abandoned"])
        last = rows[-1]
        self.assertEqual((ark.req_id(last), last["model"], last["out"], last["agent"]), (REQ, PRO, "p.png",
                                                                                         "film-test-agent"))
        self.assertIn("closed by ledger-close; never invoked", last["note"])
        self.assertIn("still counts against the caps", out)
        self.assertEqual(sum(ark.units(r) for r in ark.billed_requests(rows)), 1)
        f = self.fake()                                          # 1 used + 1 = cap 2: one more fits, then full
        self.assertEqual(self.run_ark("image", "x", str(self.tmp / "a.png"), *self.cost)[0], 0)
        self.assertEqual(self.run_ark("image", "x", str(self.tmp / "b.png"), *self.cost)[0], 3)

    def test_refused_with_a_final_row(self):
        self.seed_ledger(row(REQ, "pending", "2026-11-10T01:00:00Z"), row(REQ, "ok", "2026-11-10T01:00:20Z"))
        before = Path(self.ledger).read_bytes()
        code, _, err = self.close(REQ)
        self.assertEqual(code, 2)
        self.assertIn("already has a final row (ok)", err)
        self.assertEqual(Path(self.ledger).read_bytes(), before)
        self.assertEqual(self.close(REQ)[0], 2)

    def test_closing_twice_is_refused(self):
        self.seed_ledger(row(REQ, "pending", "2026-11-10T01:00:00Z"))
        self.assertEqual(self.close(REQ)[0], 0)
        code, _, err = self.close(REQ)
        self.assertEqual(code, 2)
        self.assertIn("already has a final row (abandoned)", err)
        self.assertEqual(len(self.rows()), 2)

    def test_unknown_ambiguous_and_malformed_ids(self):
        other = "0123456789abcdef" + "f" * 16
        self.seed_ledger(row(REQ, "pending", "2026-11-10T01:00:00Z"), row(other, "pending", "2026-11-10T01:00:00Z"))
        before = Path(self.ledger).read_bytes()
        for req, msg in (("feed", "no request feed"), ("0123", "matches 2 requests"), ("xyz!", "give the request id")):
            code, _, err = self.close(req)
            self.assertEqual(code, 2, req)
            self.assertIn(msg, err)
        self.assertEqual(Path(self.ledger).read_bytes(), before)

    def test_missing_ledger_is_not_created(self):
        code, _, err = self.close(REQ)
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(self.ledger))

    def test_video_task_keeps_its_task_id_and_hints_resume(self):
        v = dict(kind="video", seconds=5)
        self.seed_ledger(row(REQ, "pending", "2026-11-10T01:00:00Z", **v),
                         row(REQ, "pending", "2026-11-10T01:00:01Z", task_id="cgt-9", **v))
        code, _, err = self.close(REQ)
        self.assertEqual(code, 0)
        self.assertEqual(self.rows()[-1]["task_id"], "cgt-9")
        self.assertIn("--resume-task cgt-9", err)
        self.assertEqual(sum(ark.units(r) for r in ark.billed_requests(self.rows())), 5)

    def test_only_abandoned_is_accepted(self):
        self.seed_ledger(row(REQ, "pending", "2026-11-10T01:00:00Z"))
        code, _, _ = self.run_ark("ledger-close", "--req", REQ, "--ledger", self.ledger, "--status", "ok")
        self.assertEqual(code, 2)
        self.assertEqual(len(self.rows()), 1)


class TestAgentsRefuseBypasses(LedgerCase):
    """cost-7: with FILM_AGENT set, --no-budget and --force are refused before anything happens."""

    def test_no_budget_refused_for_every_paid_command(self):
        f = self.fake()
        jobs = self.text_file("jobs.csv", "id,prompt,out\na,x,a.png\n")
        for argv in (("image", "x", str(self.tmp / "a.png")), ("video", "x", str(self.tmp / "c.mp4")),
                     ("image-batch", jobs), ("lambda-job", "prepare", "x", str(self.tmp / "p.png"))):
            code, _, err = self.run_ark(*argv, "--no-budget", "--ledger", self.ledger)
            self.assertEqual(code, 2, argv)
            self.assertIn("--no-budget is for ad-hoc tests in the main session; FILM_AGENT=film-test-agent", err)
        self.assertEqual(f.calls, [])
        self.assertFalse(os.path.exists(self.ledger))

    def test_force_refused(self):
        f = self.fake()
        code, _, err = self.run_ark("image", "x", str(self.tmp / "a.png"), "--size", "4K", "--force", *self.cost)
        self.assertEqual(code, 2)
        self.assertIn("--force is for ad-hoc tests", err)
        self.assertEqual(f.calls, [])
        self.assertFalse(os.path.exists(self.ledger))

    def test_main_session_keeps_both(self):
        self.main_session()
        f = self.fake()
        self.assertEqual(self.run_ark("image", "x", str(self.tmp / "a.png"), "--no-budget")[0], 0)
        self.assertEqual(self.run_ark("image", "x", str(self.tmp / "b.png"), "--size", "4K", "--force",
                                      *self.cost)[0], 0)
        self.assertEqual(len(f.generation_calls()), 2)

    def test_resume_task_is_not_affected(self):
        self.seed_ledger(row(REQ, "pending", "2026-11-10T01:00:00Z", kind="video", seconds=5, task_id="cgt-1",
                             out=str(self.tmp / "c.mp4")))
        self.fake(polls=[{"status": "succeeded", "content": {"video_url": "https://h.example/v.mp4"}}])
        code, _, err = self.run_ark("video", "--resume-task", "cgt-1", "--ledger", self.ledger)
        self.assertEqual(code, 0, err)


class TestImageResponseGuards(LedgerCase):
    def two_images(self):
        b64 = tiny_jpeg_b64()
        return {"data": [{"b64_json": b64}, {"b64_json": b64}, {"b64_json": b64}], "usage": {"generated_images": 3}}

    def test_extra_images_never_replace_an_existing_file(self):
        keep = self.tmp / "a-1.png"
        keep.write_bytes(b"paid earlier")
        self.fake(image=self.two_images())
        code, so, err = self.run_ark("image", "x", str(self.tmp / "a.png"), *self.cost)
        self.assertEqual(code, 0, err)
        self.assertEqual(keep.read_bytes(), b"paid earlier")
        rid = ark.req_id(self.rows()[-1])
        self.assertTrue((self.tmp / f"a-1-{rid[:8]}.png").exists())
        self.assertTrue((self.tmp / "a-2.png").exists())          # a free name is used as before
        self.assertEqual(self.rows()[-1]["count"], "3")

    def test_batch_extra_image_never_takes_another_rows_out(self):
        jobs = self.text_file("jobs.csv", f"id,prompt,out\nA,x,{self.tmp / 'a.png'}\nB,y,{self.tmp / 'a-1.png'}\n")
        b64 = tiny_jpeg_b64()
        resp = iter([{"data": [{"b64_json": b64}, {"b64_json": b64}]}, {"data": [{"b64_json": b64}]}])
        self.fake()
        with mock.patch.object(ark, "call", lambda *a, **k: next(resp)):
            code, so, err = self.run_ark("image-batch", jobs, "--parallel", "1", *self.cost)
        self.assertEqual(code, 0, err)
        self.assertIn("ok B", so)                                  # B was generated, not skipped as 'output exists'
        self.assertEqual(len([p for p in os.listdir(self.tmp) if p.startswith("a-1-")]), 1)

    def test_response_without_image_data_is_failed(self):
        self.fake(image={"data": [], "usage": {"generated_images": 0}})
        code, _, err = self.run_ark("image", "x", str(self.tmp / "a.png"), *self.cost)
        self.assertEqual(code, 1)
        self.assertIn("no image data", err)
        rows = self.rows()
        self.assert_one_request(rows, "failed")
        self.assertIn("no image in the response", rows[-1]["note"])
        self.assertFalse(os.path.exists(self.tmp / "a.png"))

    def test_zero_sizes_are_unknown(self):
        self.fake()
        for size in ("0K", "0x0", "0x1024"):
            code, _, err = self.run_ark("image", "x", str(self.tmp / "z.png"), "--size", size, *self.cost)
            self.assertEqual(code, 2, size)
            self.assertIn(f"unknown --size {size}", err)

    def test_refused_prepare_prints_no_size_note(self):
        out = self.tmp / "p.png"
        out.write_bytes(b"x")
        code, _, err = self.run_ark("lambda-job", "prepare", "x", str(out), "--size", "4K", *self.cost)
        self.assertEqual(code, 2)
        self.assertNotIn("aspect ratio", err)
        self.assertEqual(len(err.strip().splitlines()), 1)


class TestParallelCapOne(LedgerCase):
    """Proof that reserve() closed the 'N parallel agents overrun by N-1' gap (CONVENTIONS §7): image and
    lambda-job prepare processes race for a cap of 1; exactly one request is reserved."""

    SCRIPT = (
        "import base64, importlib.util, io, sys, time\n"
        "from PIL import Image\n"
        "s = importlib.util.spec_from_file_location('a', sys.argv[1]); m = importlib.util.module_from_spec(s)\n"
        "s.loader.exec_module(m)\n"
        "buf = io.BytesIO(); Image.new('RGB', (4, 4)).save(buf, 'JPEG')\n"
        "b64 = base64.b64encode(buf.getvalue()).decode()\n"
        "def call(method, path, body=None, timeout=300):\n"
        "    time.sleep(0.2)\n"
        "    return {'data': [{'b64_json': b64}], 'usage': {'generated_images': 1}}\n"
        "m.call = call\n"
        "start = float(sys.argv[2])\n"
        "while time.time() < start:\n"
        "    time.sleep(0.005)\n"
        "m.main(sys.argv[3:])\n")

    def test_cap_one_gives_exactly_one_pending(self):
        self.write_budget(f"images: 1\nmodels:\n  {PRO}: 5\n")
        start = time.time() + 1.5
        argvs = ([["image", f"s{k}", str(self.tmp / f"i{k}.png")] for k in range(4)]
                 + [["lambda-job", "prepare", f"p{k}", str(self.tmp / f"l{k}.png"), "--size", "2048x2048"]
                    for k in range(4)])
        procs = [subprocess.Popen([sys.executable, "-c", self.SCRIPT, str(REPO / "tools" / "ark.py"), str(start),
                                   *argv, *self.cost],
                                  env=dict(os.environ, FILM_AGENT=f"agent-{k}"), stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) for k, argv in enumerate(argvs)]
        codes = sorted(pr.wait(timeout=60) for pr in procs)
        for pr in procs:
            pr.stdout.close()
            pr.stderr.close()
        self.assertEqual(codes, [0] + [ark.BUDGET_EXIT] * 7)
        rows = self.rows()
        self.assertEqual(len([r for r in rows if r["status"] == "pending"]), 1)
        self.assertEqual(len([r for r in rows if r["status"] == "refused-budget"]), 7)
        self.assertEqual(sum(ark.units(r) for r in ark.billed_requests(rows)), 1)


class TestResumePending(LedgerCase):
    def video_rows(self, req, task, out, final=None):
        v = dict(kind="video", seconds=5, out=str(self.tmp / out))
        rows = [row(req, "pending", "2026-11-10T01:00:00Z", **v)]
        if task:
            rows.append(row(req, "pending", "2026-11-10T01:00:01Z", task_id=task, note=f"req={req}; task created", **v))
        if final:
            rows.append(row(req, final, "2026-11-10T01:03:00Z", task_id=task, **v))
        return rows

    def seed(self):
        self.seed_ledger(*self.video_rows("aa", "cgt-1", "a.mp4"), *self.video_rows("bb", "cgt-2", "b.mp4", "ok"),
                         *self.video_rows("cc", "", "c.mp4"), *self.video_rows("dd", "cgt-4", "d.mp4"))

    def test_every_open_task_is_resumed_once(self):
        self.seed()
        self.assertEqual(ark.open_video_tasks(self.rows()), [("cgt-1", str(self.tmp / "a.mp4")),
                                                             ("cgt-4", str(self.tmp / "d.mp4"))])
        url = {"status": "succeeded", "content": {"video_url": "https://h.example/v.mp4"}}
        f = self.fake(polls=[url, url])
        code, so, err = self.run_ark("video", "--resume-pending", "--ledger", self.ledger)
        self.assertEqual(code, 0, err)
        self.assertEqual(f.generation_calls(), [])                  # nothing new is created
        self.assertEqual([p for p, _, _ in f.calls], ["GET", "GET"])
        self.assertEqual([out for _, out in self.downloads], [str(self.tmp / "a.mp4"), str(self.tmp / "d.mp4")])
        self.assertIn("resume-pending: 2 saved, 0 failed, of 2 open task(s)", so)
        finals = {ark.req_id(r): r["status"] for r in self.rows() if r["status"] != "pending"}
        self.assertEqual(finals, {"aa": "ok", "bb": "ok", "dd": "ok"})
        code, so, _ = self.run_ark("video", "--resume-pending", "--ledger", self.ledger)
        self.assertEqual(code, 0)
        self.assertIn("no open video task", so)

    def test_a_failed_task_does_not_stop_the_next(self):
        self.seed()
        url = {"status": "succeeded", "content": {"video_url": "https://h.example/v.mp4"}}
        self.fake(polls=[{"status": "failed", "error": {"code": "x"}}, url])
        code, so, err = self.run_ark("video", "--resume-pending", "--ledger", self.ledger)
        self.assertEqual(code, 1)
        self.assertIn("task cgt-1: not saved", err)
        self.assertIn("resume-pending: 1 saved, 1 failed", so)
        finals = {ark.req_id(r): r["status"] for r in self.rows() if r["status"] != "pending"}
        self.assertEqual(finals, {"aa": "failed", "bb": "ok", "dd": "ok"})

    def test_arguments(self):
        self.assertEqual(self.run_ark("video", "--resume-pending")[0], 2)                       # needs a ledger
        self.assertEqual(self.run_ark("video", "x", "--resume-pending", "--ledger", self.ledger)[0], 2)
        self.assertEqual(self.run_ark("video", "--resume-pending", "--resume-task", "t", "--ledger", self.ledger)[0], 2)
