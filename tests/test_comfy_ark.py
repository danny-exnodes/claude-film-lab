"""tools/ark.py changes for the local engines (package P1): rows of comfy:/blender: models cost 0 against every cap,
`interrupted` is a final status, and the ledger lock works where fcntl does not exist (Windows: msvcrt)."""
import csv, importlib.util, os, sys, types, unittest
from unittest import mock

from helpers import TOOLS, TmpDirCase
from test_ark import ArkCase, ark

SEEDANCE = "dreamina-seedance-2-5-260628"


def row(req, status, model, seconds=5, kind="video", **kw):
    return dict({"ts": "2026-11-25T01:00:00Z", "kind": kind, "model": model, "seconds": seconds, "count": 1,
                 "status": status, "note": f"req={req}"}, **kw)


class TestLocalRowsAreFree(ArkCase):
    BUDGET = {"images": 1, "video_seconds": 10, "models": {"comfy:h3-i2v": 0, SEEDANCE: 10}, "ledger_required": False}

    def test_is_local_and_cost_units(self):
        self.assertTrue(ark.is_local({"model": "comfy:h3-i2v"}))
        self.assertTrue(ark.is_local({"model": "blender:render"}))
        self.assertFalse(ark.is_local({"model": SEEDANCE}))
        self.assertFalse(ark.is_local({"model": "xcomfy:a"}))
        self.assertFalse(ark.is_local({}))
        r = row("aa", "ok", "comfy:h3-i2v", seconds=10)
        self.assertEqual(ark.units(r), 10)            # the row keeps its real length
        self.assertEqual(ark.cost_units(r), 0)
        self.assertEqual(ark.cost_units(row("bb", "ok", SEEDANCE, seconds=5)), 5)

    def test_local_rows_consume_no_cap(self):
        rows = [row("a1", "ok", "comfy:h3-i2v", seconds=30), row("a2", "pending", "comfy:h3-r2v", seconds=15),
                row("a3", "ok", "blender:shot", kind="image", seconds="", count=50)]
        self.assertEqual(ark.budget_check(self.BUDGET, rows, {"kind": "video", "model": SEEDANCE, "seconds": 10}), [])
        self.assertEqual(ark.budget_check(self.BUDGET, rows, {"kind": "image", "model": "m", "count": 1}), [])
        # a local request itself never trips a cap, not even models.<comfy id>: 0
        self.assertEqual(ark.budget_check(self.BUDGET, rows, {"kind": "video", "model": "comfy:h3-i2v",
                                                               "seconds": 60}), [])
        paid = rows + [row("b1", "ok", SEEDANCE, seconds=8)]
        over = ark.budget_check(self.BUDGET, paid, {"kind": "video", "model": SEEDANCE, "seconds": 5})
        self.assertEqual(len(over), 2)
        self.assertIn("video_seconds: 8 used + 5 requested > cap 10", over[0])

    def test_seedance_after_comfy_rows_through_the_cli(self):
        self.write_budget("video_seconds: 5\n")
        self.seed_ledger(row("c1", "ok", "comfy:h3-i2v", seconds=60, task_id="p1"))
        self.fake(polls=[{"status": "succeeded", "content": {"video_url": "https://h.example/v.mp4"}, "usage": {}}])
        code, _, err = self.run_ark("video", "x", str(self.tmp / "v.mp4"), "--duration", "5", *self.cost)
        self.assertEqual(code, 0, err)

    def test_batch_image_units_skip_local(self):
        rows = [row("i1", "ok", "blender:still", kind="image", seconds="", count=9)]
        self.assertEqual(ark._image_units(rows), 0)

    def test_interrupted_is_final_and_mergeable(self):
        rows = [row("aa", "pending", "comfy:h3-i2v", task_id="p"), row("aa", "interrupted", "comfy:h3-i2v")]
        self.assertEqual([r["status"] for _, r in ark.request_rows(rows)], ["interrupted"])
        self.assertIn("interrupted", ark.FINAL)
        self.assertEqual(ark.row_problems(rows[1]), [])
        a = self.ledger_path("a.csv", rows)
        b = self.ledger_path("b.csv", [row("bb", "ok", SEEDANCE, seconds=5)])
        code, out, err = self.run_ark("ledger-merge", a, b, "-o", self.ledger)
        self.assertEqual(code, 0, err)
        self.assertIn("5 video second(s) · 1 local request(s)", out)

    def test_close_refuses_an_interrupted_request(self):
        for r in (row("abcd", "pending", "comfy:h3-i2v"), row("abcd", "interrupted", "comfy:h3-i2v")):
            ark.ledger_append(self.ledger, r)
        code, _, err = self.run_ark("ledger-close", "--req", "abcd", "--status", "abandoned", "--ledger", self.ledger)
        self.assertEqual(code, 2)
        self.assertIn("already has a final row (interrupted)", err)

    def ledger_path(self, name, rows):
        path = str(self.tmp / name)
        for r in rows:
            ark.ledger_append(path, r)
        return path


class FakeMsvcrt(types.ModuleType):
    """msvcrt.locking stand-in: records (fd, mode, nbytes, position); fails the first `busy` LK_NBLCK calls."""
    LK_UNLCK, LK_LOCK, LK_NBLCK = 0, 1, 2

    def __init__(self, busy=0):
        super().__init__("msvcrt")
        self.calls, self.busy = [], busy

    def locking(self, fd, mode, n):
        self.calls.append((mode, n, os.lseek(fd, 0, os.SEEK_CUR)))
        if mode == self.LK_NBLCK and self.busy:
            self.busy -= 1
            raise OSError(36, "Resource deadlock avoided")


def load_ark_without_fcntl(msvcrt):
    """Import tools/ark.py as on Windows: `import fcntl` fails, msvcrt is the fake."""
    with mock.patch.dict(sys.modules, {"fcntl": None, "msvcrt": msvcrt}):
        spec = importlib.util.spec_from_file_location("film_ark_win", TOOLS / "ark.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


class TestWindowsLock(TmpDirCase, unittest.TestCase):
    def test_imports_and_locks_without_fcntl(self):
        fake = FakeMsvcrt()
        win = load_ark_without_fcntl(fake)
        self.assertIsNone(win.fcntl)
        win._pread = None                       # no os.pread on Windows either
        led = str(self.tmp / "ledger.csv")
        win.ledger_append(led, {"kind": "video", "model": "comfy:h3-i2v", "status": "ok", "note": "req=aa"})
        with open(led, "a", encoding="utf-8") as f:
            f.write("2026-11-25T01:00:00Z,video,m,,5,1,ok,,,,,req=bb")      # torn last line, no newline
        win.ledger_append(led, {"kind": "video", "model": "m", "status": "ok", "note": "req=cc"})
        rows = win.ledger_rows(led)
        self.assertEqual([r["note"] for r in rows], ["req=aa", "req=bb", "req=cc"])
        # every lock is one byte at WIN_LOCK_OFFSET, every lock is released
        modes = [c[0] for c in fake.calls]
        self.assertEqual(modes, [2, 0] * 3)
        self.assertTrue(all(c[1:] == (1, win.WIN_LOCK_OFFSET) for c in fake.calls))

    def test_waits_while_another_process_holds_the_lock(self):
        fake = FakeMsvcrt(busy=3)
        win = load_ark_without_fcntl(fake)
        led = str(self.tmp / "l.csv")
        with mock.patch.object(win, "WIN_LOCK_POLL", 0):
            a = types.SimpleNamespace(ledger=led, budget=None)
            win.reserve(a, {"kind": "video", "model": "comfy:h3-i2v", "seconds": 5, "count": 1}, "ab12")
        self.assertEqual([c[0] for c in fake.calls], [2, 2, 2, 2, 0])
        with open(led, newline="", encoding="utf-8") as f:
            self.assertEqual([r["status"] for r in csv.DictReader(f)], ["pending"])

    def test_file_position_is_kept(self):
        fake = FakeMsvcrt()
        win = load_ark_without_fcntl(fake)
        path = self.tmp / "x.txt"
        path.write_text("hello\n")
        with open(path, "a+", newline="", encoding="utf-8") as f:
            f.seek(0)
            win.lock_file(f)
            self.assertEqual(f.read(), "hello\n")
            win.unlock_file(f)
            self.assertEqual(win._last_byte(f, 6), b"\n")

    @unittest.skipIf(os.name == "nt", "POSIX only")
    def test_linux_still_uses_flock(self):
        self.assertIsNotNone(ark.fcntl)
        with mock.patch.object(ark.fcntl, "flock") as fl, open(self.tmp / "y", "a+") as f:
            ark.lock_file(f, shared=True)
            ark.unlock_file(f)
        self.assertEqual([c.args[1] for c in fl.call_args_list], [ark.fcntl.LOCK_SH, ark.fcntl.LOCK_UN])


if __name__ == "__main__":
    unittest.main()
