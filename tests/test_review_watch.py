"""tools/review/watch.py (issue #59): a fake out/<project>/ folder, a fake review client and a fake Blender. Which
files become steps/renders, frame sequences and passes skipped, the .blend -> GLB export (decimated when too big),
state across restarts, the first-run cutoff, retries, the real client (tags, server-numbered steps), review.py watch."""
import json, os, struct, subprocess, sys, time, unittest
from pathlib import Path
from unittest import mock

import helpers
from helpers import REPO, TmpDirCase, load, run_main
from test_review import FakeIngest, client, review

sys.path.insert(0, str(REPO / "tools" / "review"))
watch = load("review/watch.py", "film_review_watch")


def glb_bytes(verts=30, pad=0):
    gltf = {"accessors": [{"count": verts}], "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}]}
    js = json.dumps(gltf).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<I4s", len(js), b"JSON") + js + b"\0" * pad
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


class FakeReview:
    def __init__(self, log, bid, title, kind, tags, media, ok=True):
        self.log, self.bid, self.title, self.kind, self.tags, self.media, self.ok = log, bid, title, kind, tags, media, ok
        log.append(("build", bid, title, kind, tags))

    def step(self, label, glb=None, image=None, stats=None, **kw):
        self.log.append(("step", self.bid, label, glb or image, stats))
        return self.ok

    def render(self, label, video=None, **kw):
        self.log.append(("render", self.bid, label, video))
        return self.ok

    def done(self, message=None):
        self.log.append(("done", self.bid, message))
        return True

    def job(self, tool, status, *a, **kw):
        self.log.append(("job", self.bid, tool, status, kw.get("message")))
        return True

    def media_dir(self):
        d = os.path.join(self.media, self.bid)
        os.makedirs(d, exist_ok=True)
        return d


class WatchCase(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.out = self.tmp / "out" / "shk"
        self.now = time.time()
        self.log = []
        self.ok = True
        self.blender_calls = []
        self.glb_sizes = []
        self.blender = self.tmp / "fake-blender"           # find_blender() takes an existing file as given
        self.blender.write_text("", encoding="utf-8")

    def touch(self, rel, data=b"x", age=100.0):
        p = self.out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        os.utime(p, (self.now - age, self.now - age))
        return p

    def fake_blender(self, cmd, **kw):
        """Writes the GLB named after '--' (big on the first call when self.glb_sizes says so)."""
        self.blender_calls.append(cmd)
        out = cmd[cmd.index("--") + 1]
        pad = self.glb_sizes.pop(0) if self.glb_sizes else 0
        Path(out).write_bytes(glb_bytes(pad=pad))
        Path(out + ".json").write_text(json.dumps({"verts": 30, "faces": 10, "decimate": 1.0}), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    def watcher(self, **kw):
        kw.setdefault("episode", "q01t03")
        kw.setdefault("blender", str(self.blender))
        return watch.Watcher("shk", out_root=str(self.out), state_file=str(self.tmp / "state.json"),
                             make_review=lambda bid, title, kind, tags: FakeReview(
                                 self.log, bid, title, kind, tags, str(self.tmp / "media"), self.ok),
                             clock=lambda: self.now, runner=self.fake_blender,
                             registry={"subject": {"values": {"phuong-hoang": "Phượng hoàng"}}}, **kw)

    def of(self, kind):
        return [e for e in self.log if e[0] == kind]

    def layout(self):
        self.touch("characters/phuong-hoang/wip/ld01_front34.png")
        self.touch("characters/phuong-hoang/wip/sheet.jpg")
        self.touch("characters/phuong-hoang/NOTES.md")
        for i in range(1, 11):
            self.touch(f"characters/phuong-hoang/wip/beauty/{i:04d}.png")          # a pass folder
            self.touch(f"characters/phuong-hoang/wip/r1/{i:04d}.png")              # a frame sequence
        self.touch("characters/phuong-hoang/turntable.mp4")
        self.touch("characters/phuong-hoang/phuong-hoang.blend", age=60)
        self.touch("characters/phuong-hoang/phuong-hoang.blend1", age=60)
        self.touch("characters/phuong-hoang/wip/ph2_r8.blend", age=60)              # not <slug>.blend
        self.touch("locations/dan-huyet/cave.webp")
        self.touch("q01t03/renders3d/s21_keys/first.png")
        self.touch("q01t03/renders3d/s21_keys_v02/last.png")
        self.touch("q01t03/renders3d/s21_preview/beauty.mp4")
        for i in range(1, 11):
            self.touch(f"q01t03/renders3d/s21_preview/beauty/{i:04d}.png")
        self.touch("q01t03/renders3d/s21_preview/depth/0001.png")
        self.touch("q01t03/concepts/c.png")                                          # not watched


class TestWatcher(WatchCase):
    def test_a_scan_publishes_wip_skips_sequences_and_exports_the_blend(self):
        self.layout()
        r = self.watcher(since=1).scan()
        builds = {e[1]: e for e in self.of("build")}
        self.assertEqual(set(builds), {"shk-phuong-hoang", "shk-dan-huyet", "shk-q01t03-s21"})
        ph = builds["shk-phuong-hoang"]
        self.assertEqual((ph[2], ph[3]), ("Phượng hoàng", "model"))
        self.assertEqual(ph[4], {"kind": "model", "engine": "blender", "project": "shk", "subject": "phuong-hoang",
                                 "stage": "lookdev", "episode": "q01t03"})
        self.assertEqual(builds["shk-q01t03-s21"][4], {"kind": "render", "engine": "blender", "project": "shk",
                                                       "episode": "q01t03", "shot": "s21"})
        steps = {(e[1], e[2]) for e in self.of("step") if not str(e[3]).endswith(".glb")}
        self.assertEqual(steps, {("shk-phuong-hoang", "wip/ld01_front34"), ("shk-phuong-hoang", "wip/sheet"),
                                 ("shk-dan-huyet", "cave"), ("shk-q01t03-s21", "s21_keys/first"),
                                 ("shk-q01t03-s21", "s21_keys_v02/last")})
        renders = {(e[1], e[2]) for e in self.of("render")}
        self.assertEqual(renders, {("shk-phuong-hoang", "turntable"), ("shk-q01t03-s21", "s21_preview/beauty")})
        glb = [e for e in self.of("step") if str(e[3]).endswith(".glb")]
        self.assertEqual(len(glb), 1)
        self.assertEqual(glb[0][2], "phuong-hoang.blend · GLB")
        self.assertTrue(Path(glb[0][3]).is_file())
        self.assertEqual(Path(glb[0][3]).parent, self.tmp / "media" / "shk-phuong-hoang", "written in place")
        self.assertEqual((glb[0][4]["verts"], glb[0][4]["faces"]), (30, 10))
        cmd = self.blender_calls[0]
        self.assertEqual(cmd[:4], [str(self.blender), "-b", "--factory-startup",
                                   str(self.out / "characters" / "phuong-hoang" / "phuong-hoang.blend")])
        self.assertIn("bpy_export_glb.py", cmd[cmd.index("-P") + 1])
        self.assertNotIn("--decimate", cmd)
        self.assertEqual([e[3] for e in self.of("job")], ["running", "done"])
        self.assertEqual(r["exported"], 1)
        self.assertEqual({e[1] for e in self.of("done")}, set(builds))
        # nothing new: nothing published; a changed file goes again; a restart remembers
        self.log.clear()
        self.assertEqual(self.watcher().scan()["published"], 0)
        self.assertEqual(self.log, [])
        self.touch("characters/phuong-hoang/wip/sheet.jpg", b"new bytes", age=10)
        w = self.watcher()
        w.scan()
        self.assertEqual([e[2] for e in self.of("step")], ["wip/sheet"])
        self.assertEqual(len(self.blender_calls), 1, "the unchanged .blend is not exported again")

    def test_settle_first_run_cutoff_and_retries(self):
        self.touch("characters/huy/old.png", age=48 * 3600)
        self.touch("characters/huy/new.png", age=60)
        self.touch("characters/huy/writing.png", age=0.5)
        self.touch("characters/huy/huy.blend", age=5)                    # saved 5 s ago: not stable yet
        self.ok = False                                                  # the server is down
        r = self.watcher(since=12).scan()
        self.assertEqual([e[2] for e in self.of("step")], ["new"])
        self.assertEqual(r["pending"], 2, "writing.png waits; new.png was not taken")
        self.assertEqual(self.blender_calls, [])
        self.ok = True
        self.now += 30
        self.log.clear()
        self.watcher(since=12).scan()
        labels = [e[2] for e in self.of("step")]
        self.assertEqual(sorted(labels), ["huy.blend · GLB", "new", "writing"], "old.png stays seen-only")

    def test_a_huge_glb_is_exported_again_decimated(self):
        self.touch("characters/dan-huyet/dan-huyet_v2.blend", age=60)
        self.touch("characters/dan-huyet/dan-huyet.blend", age=600)      # older: the _v2 one is exported
        self.glb_sizes = [3 * 2 ** 20, 0]
        self.watcher(max_glb_mb=1.0).scan()
        self.assertEqual(len(self.blender_calls), 2)
        self.assertIn("dan-huyet_v2.blend", self.blender_calls[0][3])
        ratio = float(self.blender_calls[1][self.blender_calls[1].index("--decimate") + 1])
        self.assertTrue(0.05 <= ratio <= 0.35, ratio)
        glb = [e for e in self.of("step") if str(e[3]).endswith(".glb")]
        self.assertTrue(glb[0][3].endswith("-lite.glb"))
        media = list((self.tmp / "media" / "shk-dan-huyet").glob("*.glb"))
        self.assertEqual(len(media), 1, "the big export is removed")
        self.log.clear()
        self.blender_calls.clear()
        self.watcher(decimate=0.5).scan()
        self.assertEqual(self.blender_calls, [], "already exported")

    def test_export_failure_and_no_blender(self):
        self.touch("characters/te/te.blend", age=60)
        w = self.watcher()
        w.runner = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, b"", b"Error: boom D:\\x\\y.blend")
        with mock.patch("sys.stdout"):
            w.scan()
        self.assertEqual([e[3] for e in self.of("job")], ["running", "failed"])
        self.assertEqual(self.of("job")[-1][4], "xuất GLB lỗi", "a fixed category on the public page")
        self.assertEqual([e for e in self.of("step") if str(e[3]).endswith(".glb")], [])
        self.touch("characters/te/te.blend", age=40)
        w2 = self.watcher(blender=None)
        with mock.patch.object(watch, "find_blender", lambda x=None: None), mock.patch("sys.stdout"):
            w2.scan()
        self.assertEqual(len(self.of("job")), 2, "no Blender: no job, nothing exported")

    def test_build_ids_and_sequences(self):
        self.assertEqual(watch.build_id("son-hai-kinh", "q01t03", "s21"), "son-hai-kinh-q01t03-s21")
        self.assertEqual(watch.build_id("a" * 40, "b" * 40), ("a" * 40 + "-" + "b" * 40)[:64])
        self.assertIsNone(watch.build_id("..", "!!"))
        for name, frame in (("0001.png", True), ("beauty_0012.exr", True), ("feather_test_01.png", False),
                            ("ld01_front34.png", False)):
            self.assertEqual(bool(watch.FRAME.search(name)), frame, name)


class TestWatcherWithTheRealClient(WatchCase):
    def test_events_carry_tags_and_no_step_number(self):
        fake = FakeIngest()
        self.addCleanup(fake.stop)
        self.touch("characters/phuong-hoang/wip/a.png")
        env = {"FILM_REVIEW_URL": fake.url, "FILM_REVIEW_MEDIA": str(self.tmp / "media")}
        with mock.patch.dict(os.environ, env):
            w = watch.Watcher("shk", out_root=str(self.out), state_file=str(self.tmp / "s.json"), glb=False,
                              registry={})
            w.scan()
        self.assertEqual(fake.types(), ["build", "step", "done"])
        b = fake.of("build")[0]
        self.assertEqual((b["build"], b["kind"], b["project"]), ("shk-phuong-hoang", "model", "shk"))
        self.assertEqual(b["tags"]["subject"], ["phuong-hoang"])
        step = fake.of("step")[0]
        self.assertNotIn("n", step)
        self.assertEqual(step["image"], "shk-phuong-hoang/a.png")

    @unittest.skipIf(os.name == "nt", "the fake Blender is a POSIX script")
    def test_a_fake_blender_executable(self):
        script = self.tmp / "blender"
        script.write_text("#!" + sys.executable + "\n"
                          "import sys, struct, json\n"
                          "out = sys.argv[sys.argv.index('--') + 1]\n"
                          f"open(out, 'wb').write({glb_bytes()!r})\n", encoding="utf-8")
        script.chmod(0o755)
        self.touch("characters/huy/huy.blend", age=60)
        w = self.watcher(blender=str(script))
        w.runner = subprocess.run
        w.scan()
        glb = [e for e in self.of("step") if str(e[3]).endswith(".glb")]
        self.assertEqual(len(glb), 1)
        self.assertEqual(glb[0][4]["verts"], 30)


class TestWatchCli(TmpDirCase, unittest.TestCase):
    def test_dry_run_refusals_and_pid_check(self):
        code, out, _ = run_main(review.main, ["watch", "son-hai-kinh", "--episode", "q01t03", "--max-glb-mb", "80",
                                              "--dir", "characters", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("watch.py son-hai-kinh --episode q01t03 --max-glb-mb 80 --dir characters", out.replace("\\", "/"))
        self.assertIn("watch-son-hai-kinh.pid", out)
        self.assertEqual(run_main(review.main, ["watch", "../x", "--dry-run"])[0], 2)
        self.assertEqual(run_main(review.main, ["watch", "p", "--episode", "a/b", "--dry-run"])[0], 2)
        self.assertTrue(review.is_watch({"name": "python3", "cmdline": "python3 /lab/tools/review/watch.py shk"}))
        self.assertFalse(review.is_watch({"name": "python3", "cmdline": "python3 tools/review/monitor.py"}))
        self.assertFalse(review.is_watch({"name": "blender", "cmdline": "tools/review/watch.py"}))
        self.assertEqual(watch.main(["../x"]), 2)
        self.assertEqual(watch.main(["p", "--decimate", "2"]), 2)
        with mock.patch.object(watch.client, "lab_out", lambda *p: str(self.tmp / "nope" / "/".join(p))):
            self.assertEqual(watch.main(["p", "--once"]), 2, "no out/<project> folder")


if __name__ == "__main__":
    unittest.main()
