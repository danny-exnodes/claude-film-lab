"""tools/review/monitor.py and the machine/ComfyUI side of tools/review/server.py: the tqdm log parser, the /proc
readers, the allow list of job names (nothing but labels may reach the public page), offline behaviour, metrics/comfy
validation, the 10 min ring + 24 h downsampled history, the SSE throttle, the API, and the web app's route guard.
Standard library only; servers on 127.0.0.1 port 0; no Docker, no GPU, no ComfyUI."""
import http.client, json, os, shutil, socket, subprocess, sys, threading, time, unittest
from pathlib import Path
from unittest import mock

import helpers
from helpers import REPO, TmpDirCase, load, run_main

sys.path.insert(0, str(REPO / "tools" / "review"))
monitor = load("review/monitor.py", "film_review_monitor")
server = load("review/server.py", "film_review_server_m")
review = load("review/review.py", "film_review_cli_m")

BAR = "\u2588" * 3 + "\u258c"
H3_LINES = [f"{round(100 * i / 20):3d}%|{BAR}      | {i}/20 [{i * 34 // 60:02d}:{i * 34 % 60:02d}<{(20 - i) * 34 // 60:02d}:"
            f"{(20 - i) * 34 % 60:02d}, 34.10s/it]" for i in range(1, 21)]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ------------------------------------------------------------------ tqdm parser
class TestTqdmParser(unittest.TestCase):
    def test_lines(self):
        p = monitor.parse_tqdm("  5%|\u258c         | 1/20 [00:37<11:48, 37.30s/it]")
        self.assertEqual((p["step"], p["total"], p["pct"], p["elapsed"], p["eta"], p["s_per_step"]),
                         (1, 20, 5.0, 37.0, 708.0, 37.3))
        p = monitor.parse_tqdm("100%|\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588| 20/20 [11:03<00:00, 33.20s/it]")
        self.assertEqual((p["step"], p["pct"], p["elapsed"], p["eta"]), (20, 100.0, 663.0, 0.0))
        p = monitor.parse_tqdm(" 50%|#####     | 4/8 [00:02<00:02,  2.00it/s]")          # it/s -> s/step
        self.assertEqual(p["s_per_step"], 0.5)
        p = monitor.parse_tqdm("  0%|          | 0/20 [00:00<?, ?it/s]")
        self.assertEqual((p["step"], p["eta"], p["s_per_step"]), (0, None, None))
        p = monitor.parse_tqdm(" 10%|#         | 2/20 [1:02:03<?, 5.00s/it]")
        self.assertEqual((p["elapsed"], p["eta"]), (3723.0, 90.0))                  # eta from the rate when '?'

    def test_malformed(self):
        for line in ("", "got prompt", "  5%|\u258c   | 1/20 [00:37<11:4", "| 3/2 [00:01<00:00, 1.0s/it]",
                     " 5%|x| 21/20 [00:01<00:00, 1.00s/it]", " 5%|x| 1/0 [00:01<00:00, 1.00s/it]",
                     "Loading 1/20 models", "  5%|x| a/20 [00:01<00:00, 1.00s/it]"):
            self.assertIsNone(monitor.parse_tqdm(line), line)
        self.assertIsNone(monitor.hms("?"))
        self.assertEqual(monitor.hms("00:11:52"), 712.0)


class TestComfyLog(unittest.TestCase):
    def test_carriage_returns_and_partial_lines(self):
        log = monitor.ComfyLog()
        text = "got prompt\n" + "".join("\r" + x for x in H3_LINES[:5])
        # split mid-line: the newest update arrives in pieces and has no line end yet (tqdm writes '\r' first)
        log.feed(text[:-9], 100.0)
        cur = log.current(100.0)
        self.assertEqual((cur["step"], cur["total"]), (4, 20))                    # the cut 5th line is not used yet
        log.feed(text[-9:], 102.0)
        cur = log.current(102.0)
        self.assertEqual((cur["step"], cur["pct"], cur["s_per_step"], cur["bar"]), (5, 25.0, 34.1, 1))
        self.assertAlmostEqual(cur["eta"], 15 * 34 // 60 * 60 + 15 * 34 % 60)
        self.assertGreaterEqual(cur["job_elapsed"], cur["elapsed"])             # started = first seen - tqdm elapsed
        self.assertEqual(list(log.history), [])

    def test_job_finishes_with_100_percent_and_both_executed_formats(self):
        log = monitor.ComfyLog()
        log.feed("".join("\r" + x for x in H3_LINES) + "\r" + H3_LINES[-1] + "\n", 10.0)   # tqdm repeats 100 %
        self.assertEqual(log.current(10.0)["step"], 20)
        self.assertEqual(len(log.job["bars"]), 1, "the repeated 100 % line is the same bar")
        log.feed("\x1b[32m[INFO]\x1b[0m \x1b[32mPrompt executed in 00:11:52\x1b[0m\n", 11.0)
        self.assertIsNone(log.current(11.0))
        h = log.history[-1]
        self.assertEqual((h["duration"], h["steps"], h["s_per_step"], h["bars"], h["status"], h["t"]),
                         (712.0, 20, 34.1, 1, "ok", 11.0))
        log.feed("[INFO] Prompt executed in 138.35 seconds\n", 12.0)            # no bars (all cached): still a job
        self.assertEqual((log.history[-1]["duration"], log.history[-1]["steps"]), (138.3, None))

    def test_several_bars_one_job_and_history_cap(self):
        log = monitor.ComfyLog()
        a = [f"{p}%|x| {i}/8 [00:{i * 7:02d}<00:{(8 - i) * 7:02d}, 6.90s/it]" for i, p in ((1, 12), (4, 50), (8, 100))]
        b = [f"{p}%|x| {i}/3 [00:{i * 30:02d}<00:00, 38.20s/it]" for i, p in ((1, 33), (3, 100))]
        log.feed("\r".join([""] + a + b) + "\r", 5.0)
        self.assertEqual(log.current(5.0)["bar"], 2)
        log.feed("\nPrompt executed in 325.20 seconds\n", 6.0)
        h = log.history[-1]
        self.assertEqual((h["bars"], h["steps"], h["s_per_step"]), (2, 3, 38.2))   # the longest bar is the main one
        for i in range(12):
            log.feed(f"Prompt executed in {i}.5 seconds\n", 7.0 + i)
        self.assertEqual(len(log.history), 10)
        self.assertEqual(log.history[-1]["duration"], 11.5)

    def test_failure_interrupt_backlog_and_expiry(self):
        log = monitor.ComfyLog()
        log.feed("\r" + H3_LINES[0] + "\n!!! Exception during processing !!! CUDA out of memory\n"
                 "Prompt executed in 40.00 seconds\n", 1.0, backlog=True)
        self.assertEqual((log.history[-1]["status"], log.history[-1]["t"]), ("failed", None))  # old log: no time
        log.feed("\r" + H3_LINES[0] + "\nProcessing interrupted\nPrompt executed in 3.00 seconds\n", 2.0)
        self.assertEqual(log.history[-1]["status"], "interrupted")
        log.feed("\r" + H3_LINES[2] + "\n", 100.0)
        log.expire(150.0, active=False)
        self.assertIsNotNone(log.job, "not stale yet")
        log.expire(150.0 + monitor.STALE_JOB, active=True)
        self.assertIsNotNone(log.job, "a running prompt keeps it")
        log.expire(161.0 + monitor.STALE_JOB, active=False)
        self.assertIsNone(log.job)


class TestLogTail(TmpDirCase, unittest.TestCase):
    def test_growth_truncation_missing_and_split_utf8(self):
        path = self.tmp / "server.log"
        tail = monitor.LogTail(str(path), backlog=8)
        self.assertIsNone(tail.read())
        path.write_bytes(b"0123456789abcdef")
        self.assertEqual(tail.read(), "89abcdef")                               # only the backlog of an old file
        self.assertEqual(tail.read(), "")
        bar = "\u2588".encode("utf-8")
        with open(path, "ab") as f:
            f.write(b"x" + bar[:2])
        self.assertEqual(tail.read(), "x")                                     # half a character waits
        with open(path, "ab") as f:
            f.write(bar[2:] + b"y")
        self.assertEqual(tail.read(), "\u2588y")
        path.write_bytes(b"new")                                                # rotated: read from the start
        self.assertEqual(tail.read(), "new")
        path.unlink()
        self.assertIsNone(tail.read())


# ------------------------------------------------------------------ readers
class TestReaders(TmpDirCase, unittest.TestCase):
    def fake_proc(self):
        proc = self.tmp / "proc"
        proc.mkdir()
        (proc / "stat").write_text("cpu  100 0 100 700 100 0 0 0 0 0\ncpu0 1 2 3 4\n", encoding="ascii")
        (proc / "meminfo").write_text("MemTotal:       16000000 kB\nMemFree:  1000000 kB\n"
                                      "MemAvailable:    4000000 kB\n", encoding="ascii")
        procs = {101: ("blender", b"/opt/blender/blender\0-b\0/home/alice/secret-film/shot.blend\0"),
                 102: ("python3", b"python3\0/home/alice/ComfyUI/main.py\0--listen\0"),
                 103: ("python3", b"python3\0/home/alice/private/train.py\0--token=abc\0"),
                 104: ("bash", b"bash\0")}
        for pid, (comm, cmd) in procs.items():
            (proc / str(pid)).mkdir()
            (proc / str(pid) / "comm").write_text(comm + "\n", encoding="utf-8")
            (proc / str(pid) / "cmdline").write_bytes(cmd)
        (proc / "self").mkdir()
        return proc

    def test_proc_readers(self):
        proc = self.fake_proc()
        self.assertEqual(monitor.proc_cpu_times(str(proc)), (800, 1000))
        self.assertEqual(monitor.proc_meminfo(str(proc)), (12000000 * 1024, 16000000 * 1024))
        (proc / "meminfo").write_text("MemTotal: 1000 kB\nMemFree: 100 kB\nBuffers: 50 kB\nCached: 50 kB\n")
        self.assertEqual(monitor.proc_meminfo(str(proc)), (800 * 1024, 1000 * 1024))   # no MemAvailable
        self.assertIsNone(monitor.proc_cpu_times(str(self.tmp / "none")))
        self.assertIsNone(monitor.proc_meminfo(str(self.tmp / "none")))
        self.assertEqual(monitor.cpu_percent((800, 1000), (850, 1100)), 50.0)
        self.assertIsNone(monitor.cpu_percent(None, (1, 2)))
        self.assertIsNone(monitor.cpu_percent((5, 10), (5, 10)))

    def test_proc_processes_only_labels_leave(self):
        plist, comfy = monitor.proc_processes(str(self.fake_proc()))
        self.assertEqual(comfy, {102})
        jobs = monitor.heavy_jobs(plist, comfy)
        self.assertEqual(jobs, [{"name": "ComfyUI (python)", "count": 1}, {"name": "blender", "count": 1}])
        blob = json.dumps(jobs)
        for secret in ("alice", "secret", "home", "main.py", "token", "train", "/", "bash"):
            self.assertNotIn(secret, blob)

    def test_allow_list_never_passes_paths_or_command_lines(self):
        procs = [(1, r"C:\Users\bob\Apps\Blender.EXE"), (2, "blender.exe"), (3, "chrome.exe"), (4, "python.exe"),
                 (5, "python.exe"), (6, "ffmpeg.exe -i C:\\Users\\bob\\x.mp4"), (7, "KeePass.exe"),
                 (8, "pythonw.exe"), (9, "ComfyUI.exe")]
        jobs = monitor.heavy_jobs(procs, comfy_pids={5, 8, 3})
        self.assertEqual(jobs, [{"name": "ComfyUI (python)", "count": 2}, {"name": "ComfyUI Desktop", "count": 1},
                                {"name": "blender", "count": 2}])
        self.assertEqual(set(monitor.HEAVY.values()) | {monitor.COMFY_PY}, set(server.PROC_LABELS),
                         "the server accepts exactly the monitor's labels")
        blob = " ".join(j["name"] for j in jobs)
        for bad in ("bob", "Users", "\\", ":", "chrome", "KeePass", "-i", ".exe"):
            self.assertNotIn(bad, blob)

    def test_whole_metrics_payload_has_no_private_text(self):
        mon = monitor.Monitor("off", "http://127.0.0.1:9", None)
        procs = [(10, r"C:\Users\bob\blender.exe"), (11, "python.exe")]
        with mock.patch.object(monitor, "IS_WIN", False), \
                mock.patch.object(monitor, "proc_processes", return_value=(procs, {11})), \
                mock.patch.object(monitor, "proc_cpu_times", return_value=(1, 2)), \
                mock.patch.object(monitor, "proc_meminfo", return_value=(1, 2)), \
                mock.patch.object(monitor, "find_nvidia_smi", return_value=None), \
                mock.patch.dict(os.environ, {"USERNAME": "bob", "USER": "bob"}):
            ev = mon.metrics()
        blob = json.dumps(ev)
        self.assertNotIn("bob", blob)
        self.assertNotIn("\\", blob)
        self.assertEqual(ev["procs"], [{"name": "ComfyUI (python)", "count": 1}, {"name": "blender", "count": 1}])
        self.assertEqual(ev["gpus"], [])                                         # no nvidia-smi: no GPU, no error
        server.validate_sys(ev)

    def test_nvidia_smi_tasklist_and_tcp_table(self):
        g = monitor.parse_nvidia_smi("98, 7306, 16303, 50, 111.19, NVIDIA GeForce RTX 5070 Ti\n"
                                     "[N/A], 10, 20, [Not Supported], [N/A], Tesla, T4\nbroken line\n")
        self.assertEqual(g[0], {"name": "NVIDIA GeForce RTX 5070 Ti", "util": 98.0, "mem_used": 7306 * 2 ** 20,
                                "mem_total": 16303 * 2 ** 20, "temp": 50.0, "power": 111.19})
        self.assertEqual((g[1]["util"], g[1]["temp"], g[1]["name"]), (None, None, "TeslaT4"))
        self.assertEqual(len(g), 2)
        self.assertEqual(monitor.parse_tasklist('"blender.exe","4242","Console","1","1,234 K"\r\nINFO: x\r\n'),
                         [(4242, "blender.exe")])
        import struct
        row = lambda port, pid: struct.pack("<6I", 2, 0x0100007F, ((port & 0xFF) << 8) | (port >> 8), 0, 0, pid)  # noqa
        raw = struct.pack("<I", 3) + row(8188, 77) + row(8790, 5) + row(8188, 78)
        self.assertEqual(monitor.listen_pids_from_table(raw, 8188), {77, 78})
        self.assertEqual(monitor.comfy_port("http://127.0.0.1:8000"), 8000)


# ------------------------------------------------------------------ offline behaviour
class TestCollectorOffline(TmpDirCase, unittest.TestCase):
    def test_no_server_backs_off_and_never_raises(self):
        mon = monitor.Monitor(f"http://127.0.0.1:{free_port()}", f"http://127.0.0.1:{free_port()}",
                              str(self.tmp / "missing.log"), interval=2)
        t0 = time.monotonic()
        with mock.patch("sys.stdout"):
            m, c, ok = mon.tick()
        self.assertFalse(ok)
        self.assertLess(time.monotonic() - t0, 6)
        self.assertEqual((c["up"], c["running"], c["log"], c["current"]), (False, None, False, None))
        self.assertEqual(mon.backoff, 2)
        with mock.patch.object(mon, "post", side_effect=AssertionError("backing off: must not post")):
            self.assertFalse(mon.tick()[2])
        mon.next_post = 0
        with mock.patch("sys.stdout"):
            mon.tick()
        self.assertEqual(mon.backoff, 4)
        mon.backoff = 50
        mon.next_post = 0
        with mock.patch("sys.stdout"):
            mon.tick()
        self.assertEqual(mon.backoff, monitor.MAX_BACKOFF)

    def test_a_broken_reader_gives_null_and_the_rest_still_runs(self):
        mon = monitor.Monitor("off", None, None)
        with mock.patch.object(mon, "cpu", side_effect=RuntimeError("boom")), \
                mock.patch.object(monitor, "disks", side_effect=OSError("gone")):
            ev = mon.metrics()
        self.assertIsNone(ev["cpu"])
        self.assertEqual(ev["disks"], [])
        server.validate_sys(ev)

    def test_once_print_sends_nothing(self):
        with mock.patch.object(monitor.Monitor, "post", side_effect=AssertionError("must not send")):
            code, out, err = run_main(monitor.main, ["--once", "--print", "--comfy-log", "off",
                                                     "--comfy-url", f"http://127.0.0.1:{free_port()}"])
        self.assertEqual(code, 0, err)
        self.assertIn('"type": "metrics"', out)
        self.assertIn('"type": "comfy"', out)

    def test_comfy_queue_and_log_against_fakes(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        pid = "1b4e28ba-2fa1-11d2-883f-0016d3cca427"

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps({"queue_running": [[3, pid, {}, {"client_id": "x"}, []]],
                                   "queue_pending": [[4, "p2", {}, {}, []], [5, "p3", {}, {}, []]]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        log = self.tmp / "server.log"
        log.write_text("got prompt\n" + "".join("\r" + x for x in H3_LINES[:3]), encoding="utf-8")
        mon = monitor.Monitor("off", f"http://127.0.0.1:{httpd.server_address[1]}", str(log))
        c = mon.comfy()
        self.assertEqual((c["up"], c["running"], c["pending"], c["prompt_id"], c["log"]), (True, 1, 2, pid, True))
        self.assertEqual((c["current"]["step"], c["current"]["total"]), (3, 20))
        with open(log, "a", encoding="utf-8") as f:
            f.write("".join("\r" + x for x in H3_LINES[3:]) + "\nPrompt executed in 00:11:22\n")
        c = mon.comfy()
        self.assertIsNone(c["current"])
        self.assertEqual((c["history"][-1]["prompt_id"], c["history"][-1]["steps"]), (pid, 20))
        server.validate_sys(c)
        os.utime(log, (time.time() - 600, time.time() - 600))          # an old log while ComfyUI runs: not current
        log.write_text(log.read_text(encoding="utf-8") + "\r" + H3_LINES[0], encoding="utf-8")
        os.utime(log, (time.time() - 600, time.time() - 600))
        self.assertIsNone(mon.comfy()["current"])


# ------------------------------------------------------------------ server: validation, history, throttle, API
GOOD = {"type": "metrics", "t": 1.0, "cpu": 12.5, "ram_used": 10 * 2 ** 30, "ram_total": 127 * 2 ** 30,
        "gpus": [{"name": "NVIDIA GeForce RTX 5070 Ti", "util": 98, "mem_used": 7 * 2 ** 30, "mem_total": 16 * 2 ** 30,
                  "temp": 50, "power": 111.2}],
        "disks": [{"name": "C:", "free": 16 * 2 ** 30, "total": 465 * 2 ** 30}],
        "procs": [{"name": "blender", "count": 2}, {"name": "ComfyUI (python)", "count": 1}]}


class TestValidation(unittest.TestCase):
    def bad(self, ev, word):
        with self.assertRaises(server.BadEvent) as cm:
            server.validate_sys(ev)
        self.assertIn(word, str(cm.exception))

    def test_metrics(self):
        kind, out = server.validate_sys(GOOD)
        self.assertEqual((kind, out["procs"][0], out["gpus"][0]["util"]), ("metrics", {"name": "blender", "count": 2}, 98))
        self.assertEqual(server.validate_sys({"type": "metrics"})[1]["gpus"], [])
        for name in (r"C:\Users\bob\blender.exe", "/usr/bin/blender", "python main.py --listen", "a=b", "bob@host",
                     "x" * 41, "", "blender\n", "Blender", "chrome", 7, None):
            self.bad(dict(GOOD, procs=[{"name": name, "count": 1}]), "procs[0].name")
        self.bad(dict(GOOD, procs=[{"name": "blender", "count": 1, "cmdline": "x"}]), "unknown field")
        self.bad(dict(GOOD, user="bob"), "unknown field")
        self.bad(dict(GOOD, cpu=101), "cpu")
        self.bad(dict(GOOD, cpu=True), "cpu")
        self.bad(dict(GOOD, cpu=float("nan")), "cpu")
        self.bad(dict(GOOD, disks=[{"name": "C:\\Users", "free": 1, "total": 2}]), "drive letter")
        self.bad(dict(GOOD, disks=[{"name": "/home/bob", "free": 1, "total": 2}]), "drive letter")
        self.bad(dict(GOOD, gpus=[{"name": "GPU; rm -rf /", "util": 1}]), "gpus[0].name")
        self.bad(dict(GOOD, gpus=[{"util": 1}] * 9), "at most 8")
        self.bad(dict(GOOD, procs=[{"name": "blender", "count": 0}]), "count")

    def test_comfy(self):
        ev = {"type": "comfy", "up": True, "running": 1, "pending": 0, "prompt_id": "ab-12", "log": True,
              "current": {"step": 5, "total": 20, "pct": 25, "s_per_step": 34.1, "elapsed": 170, "eta": 511,
                          "bar": 1, "job_elapsed": 200},
              "history": [{"t": None, "duration": 712, "steps": 20, "s_per_step": 34.1, "bars": 1, "status": "ok",
                           "prompt_id": None}]}
        kind, out = server.validate_sys(ev)
        self.assertEqual((kind, out["current"]["step"], out["history"][0]["duration"]), ("comfy", 5, 712))
        self.bad(dict(ev, up=None), "up")
        self.bad(dict(ev, prompt_id="../../etc"), "prompt_id")
        self.bad(dict(ev, current={"step": 1}), "step and total")
        self.bad(dict(ev, current=dict(ev["current"], line="C:\\x")), "unknown field")
        self.bad(dict(ev, history=[{"status": "weird"}]), "status")
        self.bad(dict(ev, history=[{}] * 11), "at most 10")
        self.bad(dict(ev, message="hello"), "unknown field")


class TestHistory(TmpDirCase, unittest.TestCase):
    def test_downsample(self):
        rows = [{"t": 60.0 + i * 2, "cpu": 10.0 + i, "gpu_temp": 50 + i, "vram_used": 100 * i, "disks": [{"n": i}]}
                for i in range(30)] + [{"t": 120.0, "cpu": None}]
        out = server.downsample(rows)
        self.assertEqual([(r["t"], r["n"]) for r in out], [(60, 30), (120, 1)])
        self.assertEqual((out[0]["cpu"], out[0]["gpu_temp_max"], out[0]["vram_max"], out[0]["disks"]),
                         (24.5, 79, 2900, [{"n": 29}]))
        self.assertIsNone(out[1]["cpu"])

    def test_ring_minutes_and_pruning(self):
        store = server.Store(str(self.tmp / "db" / "r.db"))
        self.addCleanup(store.close)
        clock = [1_000_000.0]
        mach = server.Machine(store, clock=lambda: clock[0])
        _, clean = server.validate_sys(GOOD)
        start = clock[0]
        for i in range(400):                         # 800 s of 2 s samples
            clock[0] = start + 2 * i
            mach.add_metrics(dict(clean, cpu=float(i % 100)))
        self.assertEqual(len(mach.ring), server.METRICS_RING)
        w10 = mach.window("10m")
        self.assertEqual(w10["interval"], 2)
        self.assertTrue(all(r["t"] >= clock[0] - 600 for r in w10["samples"]))
        self.assertIn("gpu_util", w10["samples"][-1])
        w24 = mach.window("24h")
        self.assertEqual(w24["interval"], 60)
        ts = [r["t"] for r in w24["samples"]]
        self.assertEqual(ts, sorted(ts))
        self.assertTrue(all(t % 60 == 0 for t in ts))
        self.assertEqual(ts[-1], int(clock[0] // 60 * 60), "the minute in progress is included")
        self.assertGreaterEqual(len(ts), 13)
        self.assertNotIn("disks", w24["samples"][0])
        # a day later: rows older than 24 h are pruned when the next minute is written
        old = len(store.minutes(0))
        self.assertGreater(old, 10)
        clock[0] += server.KEEP_HISTORY + 120
        mach.add_metrics(clean)
        clock[0] += 60
        mach.add_metrics(clean)
        self.assertEqual(len(store.minutes(0)), 1)
        self.assertEqual(len(mach.window("10m")["samples"]), 2)


class TestThrottle(unittest.TestCase):
    def test_at_most_one_per_interval_and_newest_wins(self):
        got = []
        th = server.Throttle(lambda p: got.append((time.monotonic(), p)), every=0.3)
        self.addCleanup(th.close)
        for i in range(10):
            th.offer(i)
            time.sleep(0.02)
        time.sleep(0.5)
        self.assertEqual([p for _, p in got], [0, 9])
        self.assertGreaterEqual(got[1][0] - got[0][0], 0.29)
        th.offer(10)                                   # quiet for a while: goes out at once
        self.assertEqual(got[-1][1], 10)
        th.close()
        self.assertFalse(th.offer(11))


class ApiCase(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.app = server.App(str(self.tmp / "db" / "review.db"), str(self.tmp), None, host="127.0.0.1",
                              public_port=0, ingest_port=0, quiet=True).start()
        self.addCleanup(self.app.stop)

    def request(self, method, path, body=None, port=None):
        c = http.client.HTTPConnection("127.0.0.1", port or self.app.public_port, timeout=5)
        try:
            data = json.dumps(body).encode() if body is not None else None
            c.request(method, path, body=data, headers={"Content-Type": "application/json"} if data else {})
            r = c.getresponse()
            return r.status, json.loads(r.read() or b"{}")
        finally:
            c.close()

    def post(self, ev):
        return self.request("POST", "/ingest/event", ev, port=self.app.ingest_port)


class TestApi(ApiCase):
    def test_metrics_and_comfy_endpoints(self):
        code, body = self.request("GET", "/api/metrics")
        self.assertEqual((code, body["samples"], body["latest"], body["online"]), (200, [], None, False))
        self.assertEqual(self.post(GOOD)[0], 200)
        code, body = self.request("GET", "/api/metrics?window=10m")
        self.assertEqual((code, len(body["samples"]), body["online"]), (200, 1, True))
        self.assertEqual(body["latest"]["procs"], GOOD["procs"])
        self.assertEqual(body["samples"][0]["gpu_util"], 98)
        code, body = self.request("GET", "/api/metrics?window=24h")
        self.assertEqual((code, body["interval"], len(body["samples"])), (200, 60, 1))
        self.assertEqual(self.request("GET", "/api/metrics?window=7d")[0], 400)
        code, body = self.post(dict(GOOD, procs=[{"name": "C:\\Users\\bob\\x.exe", "count": 1}]))
        self.assertEqual(code, 400)
        self.assertEqual(self.request("POST", "/api/metrics", {})[0], 405)       # the public port stays read-only
        self.assertTrue(self.request("GET", "/api/health")[1]["monitor"])

    def test_comfy_prompt_is_linked_to_its_build(self):
        pid = "0f8e7d6c-1111-2222-3333-444455556666"
        self.assertEqual(self.post({"type": "build", "build": "ep01-s03", "title": "H3 s03", "kind": "clip"})[0], 200)
        self.assertEqual(self.post({"type": "job", "build": "ep01-s03", "tool": "comfy", "status": "running",
                                    "job": "comfy-" + pid})[0], 200)
        ev = {"type": "comfy", "up": True, "running": 1, "pending": 0, "prompt_id": pid, "log": True,
              "current": {"step": 2, "total": 20, "pct": 10}, "history": [
                  {"duration": 700, "steps": 20, "status": "ok", "prompt_id": pid},
                  {"duration": 9, "status": "ok", "prompt_id": "abc"}]}
        self.assertEqual(self.post(ev)[0], 200)
        body = self.request("GET", "/api/comfy")[1]
        self.assertTrue(body["online"])
        self.assertEqual(body["comfy"]["build"], {"id": "ep01-s03", "title": "H3 s03"})
        self.assertEqual(body["comfy"]["history"][0]["build"]["id"], "ep01-s03")
        self.assertIsNone(body["comfy"]["history"][1]["build"])
        self.assertEqual(self.post({"type": "comfy", "up": "yes"})[0], 400)
        self.assertEqual(self.post({"type": "comfy", "up": True, "build": "x"})[0], 400)


class TestStreamThrottle(ApiCase):
    def test_sse_metrics_are_throttled_and_not_replayed(self):
        with mock.patch.object(server, "PUSH_EVERY", 0.6):
            app = server.App(":memory:", str(self.tmp), None, host="127.0.0.1", public_port=0, ingest_port=0,
                             quiet=True).start()
        self.addCleanup(app.stop)
        c = http.client.HTTPConnection("127.0.0.1", app.public_port, timeout=5)
        self.addCleanup(c.close)
        c.request("GET", "/api/stream")
        r = c.getresponse()
        events, lock = [], threading.Lock()

        def reader():
            name = None
            try:
                for raw in r.fp:
                    line = raw.decode("utf-8").rstrip("\n")
                    if line.startswith("event: "):
                        name = line[7:]
                    elif line.startswith("data: ") and name in ("metrics", "comfy"):
                        with lock:
                            events.append((time.monotonic(), name, json.loads(line[6:])))
            except Exception:
                pass

        threading.Thread(target=reader, daemon=True).start()
        time.sleep(0.2)
        port = app.ingest_port
        for i in range(8):                                  # a monitor gone wild: 8 samples in ~0.4 s
            code, _ = self.request("POST", "/ingest/event", dict(GOOD, cpu=float(i)), port=port)
            self.assertEqual(code, 200)
            time.sleep(0.05)
        time.sleep(1.0)
        with lock:
            got = [e for e in events if e[1] == "metrics"]
        self.assertEqual(len(got), 2, "the first at once, then the newest held one after the interval")
        self.assertEqual((got[0][2]["sample"]["cpu"], got[1][2]["sample"]["cpu"]), (0.0, 7.0))
        self.assertGreaterEqual(got[1][0] - got[0][0], 0.55)
        self.assertFalse([it for it in app.hub.recent if it[1] == "metrics"], "machine events are not replayed")


# ------------------------------------------------------------------ review.py and the web app's route guard
class TestReviewCliMonitor(TmpDirCase, unittest.TestCase):
    def test_dry_runs(self):
        code, out, err = run_main(review.main, ["up", "--no-ngrok", "--dry-run", "--comfy-log", "x.log"])
        self.assertEqual(code, 0, err)
        self.assertRegex(out.replace("\\", "/"), r"tools/review/monitor\.py --comfy-log x\.log")
        code, out, _ = run_main(review.main, ["up", "--no-ngrok", "--no-monitor", "--dry-run"])
        self.assertNotIn("monitor.py", out)
        code, out, _ = run_main(review.main, ["monitor", "--dry-run", "--interval", "5"])
        self.assertEqual(code, 0)
        self.assertIn("--interval 5", out)

    def test_monitor_pid_is_checked_before_use(self):
        pidfile = self.tmp / "monitor.pid"
        with mock.patch.object(review, "MONITOR_PID", str(pidfile)):
            self.assertIsNone(review.monitor_pid())
            pidfile.write_text("not a pid")
            self.assertIsNone(review.monitor_pid())
            pidfile.write_text(str(os.getpid()))
            with mock.patch.object(review, "process_name", return_value="python3"):
                self.assertEqual(review.monitor_pid(), os.getpid())
            with mock.patch.object(review, "process_name", return_value="explorer.exe"):
                self.assertIsNone(review.monitor_pid(), "a reused pid of another program is never killed")


NODE = shutil.which("node")
ROUTE_TEST = r"""
import { makeRouter } from '%s';
const log = [];
const view = { kids: [], replaceChildren(...k) { this.kids = k; } };
const box = () => ({ id: Math.random(), kids: [], append(x) { this.kids.push(x); }, replaceChildren(...k) { this.kids = k; } });
let release;
const slow = new Promise((r) => { release = r; });
const viewOf = (name, wait) => async () => ({ default: async (root, args, live, alive) => {
  if (wait) await wait;
  root.append(name);                                   // a late view writes into its own (now detached) box
  log.push(`${name} alive=${alive()}`);
  return { destroy() { log.push(`${name} destroyed`); } };
} });
const r = makeRouter(view, box, (e) => log.push('error ' + e.message));
const a = r.go(viewOf('dai-ngac', slow), ['dai-ngac'], null);   // still loading its 12 MB GLB ...
await new Promise((res) => setTimeout(res, 0));
const b = await r.go(viewOf('chuc-long'), ['chuc-long'], null);  // ... when the user opens another build
release();
await a;
const shown = view.kids.flatMap((k) => k.kids);
console.log(JSON.stringify({ log, shown, current: r.current === b }));
"""


@unittest.skipIf(NODE is None, "node is missing")
class TestRouteGuard(unittest.TestCase):
    def test_a_stale_view_is_destroyed_and_never_shown(self):
        route = (REPO / "tools" / "review" / "web" / "route.js").resolve().as_uri()
        r = subprocess.run([NODE, "--input-type=module", "-e", ROUTE_TEST % route], capture_output=True, text=True,
                           timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["shown"], ["chuc-long"])
        self.assertTrue(out["current"])
        self.assertIn("dai-ngac alive=false", out["log"])
        self.assertIn("dai-ngac destroyed", out["log"])
        self.assertNotIn("chuc-long destroyed", out["log"])


class TestWebFiles(unittest.TestCase):
    def test_views_check_alive_after_their_loads(self):
        web = REPO / "tools" / "review" / "web"
        app = (web / "app.js").read_text(encoding="utf-8")
        self.assertIn("makeRouter", app)
        self.assertNotIn("mod.default(view", app, "views never render straight into #view")
        for name in ("blueprint.js", "viewer.js"):
            src = (web / name).read_text(encoding="utf-8")
            self.assertIn("if (!alive()) return {};", src, name)
            self.assertRegex(src, r"if \(destroyed \|\| !alive\(\) \|\| my !== \w+Token\) return;", name)
        lib = (web / "lib.js").read_text(encoding="utf-8")
        self.assertIn("'metrics', 'comfy'", lib)
        sysjs = (web / "sys.js").read_text(encoding="utf-8")
        for needle in ("metrics?window=", "api('comfy')", "drawChart", "LOW_DISK", "limit: 90", "limit: 83"):
            self.assertIn(needle, sysjs)


if __name__ == "__main__":
    unittest.main()
