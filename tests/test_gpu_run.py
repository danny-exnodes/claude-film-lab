"""tools/gpu_run.py: the lab-wide GPU lock (one GPU job at a time). Real processes on a temporary lock file
(FILM_GPU_LOCK); no GPU needed."""
import json, os, re, subprocess, sys, time, unittest
from pathlib import Path
from unittest import mock

import helpers

gr = helpers.load("gpu_run.py", "film_gpu_run")
CLI = str(helpers.TOOLS / "gpu_run.py")


class GpuCase(helpers.TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.lock = str(self.tmp / "gpu" / "gpu.lock")
        env = {k: v for k, v in os.environ.items() if not k.startswith("FILM_GPU")}
        env["FILM_GPU_LOCK"] = self.lock
        self._env = mock.patch.dict(os.environ, env, clear=True)
        self._env.start()
        self.addCleanup(self._env.stop)

    def child_env(self, **over):
        env = {k: v for k, v in os.environ.items() if k != "FILM_GPU_HELD"}   # a separate job, not our child
        env.update(over)
        return env

    def cli(self, *args, env=None, timeout=60):
        return subprocess.run([sys.executable, CLI, *args], capture_output=True, text=True, timeout=timeout,
                              env=env or self.child_env())

    def py(self, code):
        return [sys.executable, "-c", code]


class TestPlaces(GpuCase):
    def test_lock_and_owner_paths(self):
        self.assertEqual(gr.lock_path(), os.path.abspath(self.lock))
        self.assertEqual(gr.owner_path(), str(self.tmp / "gpu" / "gpu.owner"))
        with mock.patch.dict(os.environ, {"FILM_GPU_LOCK": ""}):
            default = gr.lock_path()
        self.assertTrue(default.replace("\\", "/").endswith("out/_gpu/gpu.lock"), default)
        main = gr.main_checkout()
        self.assertTrue(default.startswith(main))
        # every worktree resolves to the main checkout: it holds the .git folder (or, outside git, this repo)
        self.assertTrue(os.path.isdir(os.path.join(main, ".git")) or main == gr.REPO, main)

    def test_label_is_safe_for_a_public_page(self):
        for raw in ("C:\\Users\\me\\scene.blend; rm -rf /", "blender render s21 --spec D:/x/y.json", "x" * 200,
                    "phượng hoàng <b>", "", None):
            s = gr.clean_label(raw)
            self.assertRegex(s, r"^[A-Za-z0-9 _.:/-]{1,60}$")
            self.assertNotIn("\\", s)
        self.assertEqual(gr.clean_label("blender render s21"), "blender render s21")
        self.assertEqual(gr.clean_label(None), "gpu-job")


class TestLock(GpuCase):
    def test_owner_file_while_held_and_gone_after(self):
        with gr.gpu_lock("blender turntable phoenix") as owner:
            data = json.loads(Path(gr.owner_path()).read_text(encoding="utf-8"))
            self.assertEqual(set(data), {"label", "pid", "since"})
            self.assertEqual(data["label"], "blender turntable phoenix")
            self.assertEqual(data["pid"], os.getpid())
            self.assertRegex(data["since"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
            self.assertEqual(owner, data)
            self.assertEqual(os.environ["FILM_GPU_HELD"], str(os.getpid()))
            with gr.gpu_lock("nested") as inner:          # same process: no deadlock, no second owner
                self.assertIsNone(inner)
            self.assertEqual(json.loads(Path(gr.owner_path()).read_text())["label"], "blender turntable phoenix")
        self.assertFalse(os.path.exists(gr.owner_path()))
        self.assertNotIn("FILM_GPU_HELD", os.environ)

    def test_two_jobs_run_one_after_the_other(self):
        log = self.tmp / "times.log"
        job = ("import sys, time; f = open(sys.argv[1], 'a'); f.write(f'start {sys.argv[2]} {time.time()}\\n'); "
               "f.flush(); time.sleep(0.8); f.write(f'end {sys.argv[2]} {time.time()}\\n'); f.close()")
        procs = [subprocess.Popen([sys.executable, CLI, "--label", f"job {n}", "--", sys.executable, "-c", job,
                                   str(log), str(n)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                  env=self.child_env()) for n in (1, 2)]
        outs = [p.communicate(timeout=60) for p in procs]
        self.assertEqual([p.returncode for p in procs], [0, 0], outs)
        ev = [l.split() for l in log.read_text().splitlines()]
        self.assertEqual(len(ev), 4)
        spans = {}
        for kind, n, t in ev:
            spans.setdefault(n, {})[kind] = float(t)
        a, b = sorted(spans.values(), key=lambda s: s["start"])
        self.assertLessEqual(a["end"], b["start"], f"the jobs overlapped: {ev}")
        waited = "".join(err for _, err in outs)
        self.assertRegex(waited, r"waiting for the GPU \(held by: job [12] · pid \d+ · since ")
        self.assertFalse(os.path.exists(gr.owner_path()))

    def test_exit_code_is_the_commands(self):
        r = self.cli("--label", "x", "--", *self.py("import sys; sys.exit(7)"))
        self.assertEqual(r.returncode, 7, r.stderr)
        r = self.cli("--", *self.py("print('ran')"))
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "ran"))

    def test_wait_timeout_runs_nothing(self):
        marker = self.tmp / "ran"
        with gr.gpu_lock("comfy run qwen-t2i"):
            t0 = time.monotonic()
            r = self.cli("--label", "late", "--wait", "0.5", "--", *self.py(f"open({str(marker)!r}, 'w')"))
            self.assertLess(time.monotonic() - t0, 20)
        self.assertEqual(r.returncode, gr.BUSY_EXIT, r.stderr)
        self.assertFalse(marker.exists())
        self.assertIn("held by: comfy run qwen-t2i", r.stderr)
        self.assertIn("was not run", r.stderr)
        with gr.gpu_lock("holder"):            # in-process: GpuBusy carries the holder
            env = self.child_env()
            code = ("import sys; sys.path.insert(0, sys.argv[1]); import gpu_run\n"
                    "try:\n  with gpu_run.gpu_lock('b', wait=0.2): print('got it')\n"
                    "except gpu_run.GpuBusy as e: print('busy', e.holder['label'])")
            r = subprocess.run([sys.executable, "-c", code, str(helpers.TOOLS)], capture_output=True, text=True,
                               env=env, timeout=60)
        self.assertEqual(r.stdout.strip(), "busy holder", r.stderr)

    def test_status(self):
        self.assertEqual(self.cli("status").stdout.strip(), "free")
        with gr.gpu_lock("blender render s21"):
            out = self.cli("status").stdout.strip()
        self.assertRegex(out, rf"^blender render s21 · pid {os.getpid()} · since \S+Z$")
        self.assertEqual(self.cli("status").stdout.strip(), "free")
        # a job killed hard leaves its owner file behind: the lock is free, status says so and cleans it
        os.makedirs(os.path.dirname(gr.owner_path()), exist_ok=True)
        Path(gr.owner_path()).write_text(json.dumps({"label": "dead", "pid": 1, "since": "x"}), encoding="utf-8")
        self.assertEqual(self.cli("status").stdout.strip(), "free")
        self.assertFalse(os.path.exists(gr.owner_path()))

    def test_queue_off(self):
        marker = self.tmp / "ran"
        with gr.gpu_lock("holder"):
            r = self.cli("--wait", "0.2", "--", *self.py(f"open({str(marker)!r}, 'w')"),
                         env=self.child_env(FILM_GPU_QUEUE="0"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(marker.exists())
            self.assertIn("without the GPU lock", r.stderr)
            self.assertIn("off", self.cli("status", env=self.child_env(FILM_GPU_QUEUE="0")).stdout)
        with mock.patch.dict(os.environ, {"FILM_GPU_QUEUE": "0"}):
            with gr.gpu_lock("x") as owner:
                self.assertIsNone(owner)
                self.assertFalse(os.path.exists(gr.owner_path()))

    def test_child_of_the_holder_does_not_deadlock(self):
        inner = [sys.executable, CLI, "--label", "inner", "--wait", "3", "--", *self.py("print('inner ran')")]
        r = self.cli("--label", "outer", "--", *inner)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "inner ran")
        self.assertNotIn("waiting", r.stderr)
        # a FILM_GPU_HELD that is not the holder's pid (left over, copied) does not skip the lock
        with gr.gpu_lock("real holder"):
            r = self.cli("--wait", "0.3", "--", *self.py("print('ran')"), env=self.child_env(FILM_GPU_HELD="1"))
        self.assertEqual(r.returncode, gr.BUSY_EXIT, r.stdout + r.stderr)

    def test_bad_arguments(self):
        self.assertEqual(self.cli().returncode, 2)
        self.assertEqual(self.cli("--wait", "soon", "--", "x").returncode, 2)
        self.assertEqual(self.cli("--bogus", "--", "x").returncode, 2)
        r = self.cli("--wait", "0", "--", sys.executable, "-c", "print(1)")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "1"))

    def test_default_wait_from_env(self):
        self.assertIsNone(gr.default_wait())
        with mock.patch.dict(os.environ, {"FILM_GPU_WAIT": "90"}):
            self.assertEqual(gr.default_wait(), 90.0)
        with mock.patch.dict(os.environ, {"FILM_GPU_WAIT": "soon"}):
            self.assertIsNone(gr.default_wait())


if __name__ == "__main__":
    unittest.main()
