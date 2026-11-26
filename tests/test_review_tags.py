"""tools/review/ (issues #57, #60, #64, #65): tag chips (registry, client normalisation, server storage, migration of an
old database, inference for old builds), image builds (kind image, step metadata, job detail, the ComfyUI link), JPEG
previews, the main-checkout media folder (worktrees), review.py mount/status/tunnels, the GPU owner on the monitor, the
ComfyUI log lookup from a worktree, and the pure parts of the web app (tags.js, route.js) under node.
No Docker, no network, no tunnel binary is ever run."""
import io, json, os, re, shutil, sqlite3, subprocess, sys, time, unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

import helpers
from helpers import REPO, TmpDirCase, load, run_main
from test_review import ServerCase, FakeIngest, free_port, server, client, review, vendor

monitor = load("review/monitor.py", "film_review_monitor_tags")
preview = load("review/preview.py", "film_review_preview")
try:
    import PIL.Image as PILImage
except ImportError:            # tools/ci.sh --install brings Pillow
    PILImage = None
NODE = shutil.which("node")
WEB = REPO / "tools" / "review" / "web"


# ------------------------------------------------------------------ #65 tags on the server
class TestTagsApi(ServerCase):
    def build(self, bid):
        return self.get_json(f"/api/builds/{bid}")["build"]

    def test_tags_round_trip_merge_and_name(self):
        self.ok({"type": "build", "build": "t1", "title": "Phượng hoàng 鳳皇", "kind": "model",
                 "tags": {"engine": "blender", "look": ["realistic"], "episode": "q01t03", "subject": "phuong-hoang"}})
        b = self.build("t1")
        self.assertEqual(b["tags"], {"kind": ["model"], "engine": ["blender"], "look": ["realistic"],
                                     "episode": ["q01t03"], "subject": ["phuong-hoang"]})
        self.assertEqual(b["name"], "Phượng hoàng 鳳皇")
        # a given group replaces the stored one, [] removes it, other groups stay
        self.ok({"type": "build", "build": "t1", "tags": {"look": ["clay", "clay"], "subject": []}})
        b = self.build("t1")
        self.assertEqual(b["tags"]["look"], ["clay"])
        self.assertNotIn("subject", b["tags"])
        self.assertEqual(b["tags"]["engine"], ["blender"])
        listed = {x["id"]: x for x in self.get_json("/api/builds")["builds"]}
        self.assertEqual(listed["t1"]["tags"], b["tags"])

    def test_old_callers_get_inferred_tags_and_a_clean_name(self):
        self.ok({"type": "build", "build": "shk-phoenix", "title": "Phượng hoàng 鳳皇 · Q1·T3 (Blender, realistic)",
                 "kind": "model", "project": "Sơn Hải Kinh"})
        b = self.build("shk-phoenix")
        self.assertEqual(b["name"], "Phượng hoàng 鳳皇")
        self.assertEqual(b["title"], "Phượng hoàng 鳳皇 · Q1·T3 (Blender, realistic)", "the stored title is kept")
        for g, v in (("kind", ["model"]), ("engine", ["blender"]), ("look", ["realistic"]), ("episode", ["q01t03"]),
                     ("project", ["son-hai-kinh"])):
            self.assertEqual(b["tags"].get(g), v, g)
        self.ok({"type": "progress", "build": "ep01-s03-h3", "progress": 0.1})       # created by a non-build event
        self.assertEqual(self.build("ep01-s03-h3")["tags"],
                         {"kind": ["model"], "engine": ["comfy-h3"], "episode": ["ep01"], "shot": ["s03"]})
        self.assertEqual(server.display_name("Concept chim (Qwen-Image)"), "Concept chim")
        self.assertEqual(server.display_name("Thuyền (v2)"), "Thuyền (v2)", "an unknown annotation stays")
        self.assertEqual(server.display_name("(Blender)"), "(Blender)", "never empty")

    def test_bad_tags_are_refused(self):
        bad = [{"Kind": "model"}, {"kind": "Model"}, {"kind": "a/b"}, {"kind": ["x"] * 9}, {"kind": 5},
               {f"g{i}": "x" for i in range(17)}, ["kind"], {"kind": "C:\\Users\\x"}]
        for tags in bad:
            code, body = self.post({"type": "build", "build": "bad", "tags": tags})
            self.assertEqual(code, 400, (tags, body))

    def test_registry_endpoint_and_media_overlay(self):
        reg = self.get_json("/api/tags")
        for g in ("kind", "engine", "look", "project", "episode", "subject", "shot", "stage"):
            self.assertIn(g, reg["groups"])
            self.assertRegex(reg["groups"][g]["color"], r"^#[0-9a-fA-F]{6}$")
        self.assertEqual(reg["groups"]["kind"]["values"]["image"], "Ảnh")
        (self.media / "_tags.json").write_text(json.dumps({"groups": {"subject": {"values": {
            "phuong-hoang": "Phượng hoàng"}}}}), encoding="utf-8")
        reg = self.get_json("/api/tags")
        self.assertEqual(reg["groups"]["subject"]["values"], {"phuong-hoang": "Phượng hoàng"})
        self.assertEqual(reg["groups"]["subject"]["color"], "#ff9f6b", "the overlay keeps the shipped colour")
        self.ok({"type": "build", "build": "ph2", "title": "Phượng hoàng lookdev", "kind": "model"})
        self.assertEqual(self.build("ph2")["tags"].get("subject"), ["phuong-hoang"])
        self.assertEqual(self.build("ph2")["tags"].get("stage"), ["lookdev"])

    def test_shipped_registry_is_valid(self):
        doc = json.loads((REPO / "tools" / "review" / "tags.json").read_text(encoding="utf-8"))
        for name, g in doc["groups"].items():
            self.assertRegex(name, server.TAG_GROUP.pattern)
            self.assertRegex(g["color"], r"^#[0-9a-fA-F]{6}$")
            self.assertTrue(g["label"])
            for v in g["values"]:
                self.assertRegex(v, server.TAG_VALUE.pattern, f"{name}.{v}")
            if "pattern" in g:
                re.compile(g["pattern"])
        self.assertEqual(set(doc["groups"]["kind"]["values"]) >= set(server.KINDS), True,
                         "every build kind has a chip label")


# ------------------------------------------------------------------ #64 image builds
class TestImageBuilds(ServerCase):
    def test_image_kind_step_meta_and_job_detail(self):
        (self.media / "img").mkdir()
        self.ok({"type": "build", "build": "img", "title": "Concept chim", "kind": "image",
                 "tags": {"engine": "comfy-qwen"}})
        self.ok({"type": "job", "build": "img", "tool": "comfy", "status": "running", "job": "comfy-p1",
                 "label": "qwen-t2i", "progress": 0.3, "step": 12, "steps": 30, "item": 2, "items": 4, "eta": 81.5})
        self.ok({"type": "step", "build": "img", "label": "concept 1/4", "image": "img/c1.jpg",
                 "prompt": "a phoenix over D:\\Projects\\secret\\ref.png", "seed": 2 ** 63 + 5, "model": "qwen_image.safetensors",
                 "sampler_steps": 30, "seconds": 134.8, "width": 1664, "height": 928, "workflow": "qwen-t2i",
                 "item": 1, "items": 4, "chosen": True})
        d = self.get_json("/api/builds/img")
        self.assertEqual(d["build"]["kind"], "image")
        self.assertEqual((d["build"]["images"], d["build"]["thumb"]), (1, "img/c1.jpg"))
        meta = d["steps"][0]["meta"]
        self.assertEqual(meta["seed"], 2 ** 63 + 5)
        self.assertEqual(meta["prompt"], "a phoenix over ref.png", "paths in a prompt are cut to the base name")
        self.assertEqual((meta["sampler_steps"], meta["width"], meta["items"], meta["chosen"]), (30, 1664, 4, True))
        job = d["build"]["job"]
        self.assertEqual((job["label"], job["step"], job["steps"], job["item"], job["items"], job["eta"]),
                         ("qwen-t2i", 12, 30, 2, 4, 81.5))
        # a later job event without the detail keeps it (COALESCE), with new values replaces it
        self.ok({"type": "job", "build": "img", "tool": "comfy", "status": "running", "job": "comfy-p1", "item": 3})
        job = self.get_json("/api/builds/img")["build"]["job"]
        self.assertEqual((job["item"], job["steps"], job["label"]), (3, 30, "qwen-t2i"))
        # the ComfyUI card links the running prompt with its workflow and image k/N
        self.assertEqual(self.app.store.comfy_build("p1"), {"id": "img", "title": "Concept chim", "kind": "image",
                                                            "workflow": "qwen-t2i", "item": 3, "items": 4,
                                                            "step": 12, "steps": 30})
        self.ok({"type": "build", "build": "cc", "kind": "concept"})

    def test_bad_meta_and_detail_are_refused(self):
        base = {"type": "step", "build": "b1", "label": "x"}
        for extra in ({"seed": -1}, {"seed": 2 ** 64}, {"sampler_steps": 0}, {"width": 70000}, {"seconds": -1},
                      {"item": 5, "items": 4}, {"chosen": "yes"}, {"prompt": 5}, {"seed": 1.5}):
            self.assertEqual(self.post(dict(base, **extra))[0], 400, extra)
        job = {"type": "job", "build": "b1", "tool": "comfy", "status": "running"}
        for extra in ({"step": 31, "steps": 30}, {"steps": 0}, {"eta": -2}, {"label": 3}):
            self.assertEqual(self.post(dict(job, **extra))[0], 400, extra)
        self.assertEqual(self.post({"type": "build", "build": "b1", "kind": "picture"})[0], 400)


# ------------------------------------------------------------------ #65 migration of an old database
OLD_SCHEMA = """
CREATE TABLE builds (id TEXT PRIMARY KEY, title TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('model','render','clip','demo')), project TEXT,
  status TEXT NOT NULL CHECK (status IN ('queued','building','rendering','done','failed')),
  progress REAL NOT NULL DEFAULT 0 CHECK (progress >= 0 AND progress <= 1), expected_steps INTEGER, current TEXT,
  message TEXT, thumb TEXT, started REAL NOT NULL, updated REAL NOT NULL, finished REAL);
CREATE TABLE steps (id INTEGER PRIMARY KEY, build TEXT NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
  n INTEGER NOT NULL, label TEXT NOT NULL, stats TEXT, glb TEXT, image TEXT, t REAL NOT NULL, UNIQUE (build, n));
CREATE TABLE renders (id INTEGER PRIMARY KEY, build TEXT NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
  label TEXT NOT NULL, video TEXT, image TEXT, frames INTEGER, fps REAL, duration REAL, engine TEXT,
  seconds_per_frame REAL, t REAL NOT NULL);
CREATE TABLE jobs (id INTEGER PRIMARY KEY, build TEXT NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
  job TEXT NOT NULL, tool TEXT NOT NULL CHECK (tool IN ('blender','comfy')),
  status TEXT NOT NULL CHECK (status IN ('queued','running','done','failed')), progress REAL, gpu_s REAL,
  message TEXT, started REAL NOT NULL, t REAL NOT NULL, UNIQUE (build, job));
CREATE TABLE metrics_min (t INTEGER PRIMARY KEY, data TEXT NOT NULL);
"""


class TestMigration(TmpDirCase, unittest.TestCase):
    def test_v1_database_is_migrated_in_place(self):
        path = str(self.tmp / "review.db")
        db = sqlite3.connect(path)
        db.executescript(OLD_SCHEMA)
        db.execute("INSERT INTO builds VALUES ('ph', 'Phượng hoàng · Q1·T3 (Blender, realistic)', 'model', NULL, "
                   "'done', 1, 3, NULL, NULL, 'ph/s.png', 1, 2, 3)")
        db.execute("INSERT INTO steps (build, n, label, stats, glb, image, t) VALUES ('ph', 1, 'body', '{}', "
                   "'ph/a.glb', NULL, 1)")
        db.execute("INSERT INTO renders (build, label, video, t) VALUES ('ph', 'tt', 'ph/tt.mp4', 1)")
        db.execute("INSERT INTO jobs (build, job, tool, status, started, t) VALUES ('ph', 'blender-1', 'blender', "
                   "'done', 1, 2)")
        db.commit()
        db.close()
        for _ in range(2):                                    # idempotent: the second open changes nothing
            store = server.Store(path, server.Registry(str(REPO / "tools" / "review" / "tags.json")))
            b = store.build("ph")
            self.assertEqual((b["steps"], b["renders"], b["job"]["job"]), (1, 1, "blender-1"))
            self.assertEqual(b["tags"]["engine"], ["blender"])
            self.assertEqual(b["tags"]["episode"], ["q01t03"])
            self.assertEqual(b["name"], "Phượng hoàng")
            self.assertEqual(store.db.execute("PRAGMA user_version").fetchone()[0], server.SCHEMA_VERSION)
            self.assertEqual(store.db.execute("PRAGMA foreign_key_check").fetchall(), [])
            store.close()
        store = server.Store(path)
        store.apply("build", "img1", {"kind": "image", "title": "x"})            # the kind CHECK is gone
        store.apply("job", "ph", {"tool": "comfy", "status": "running", "job": "c", "label": "qwen-t2i", "items": 4})
        store.apply("step", "ph", {"label": "s", "image": "ph/s.jpg", "seed": 7})
        self.assertEqual(store.rows("steps", "ph")[-1]["meta"], {"seed": 7})
        store.db.execute("DELETE FROM builds WHERE id='ph'")                      # cascades still work
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM steps").fetchone()[0], 0)
        store.close()


# ------------------------------------------------------------------ client: tags, meta, job detail, previews
class TestClientTags(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeIngest()
        self.addCleanup(self.fake.stop)
        self.media = self.tmp / "media"
        client._TAG_WARNED.clear()

    def test_tags_are_normalised_and_unknown_ones_only_warn(self):
        err = io.StringIO()
        with redirect_stderr(err):
            rv = client.Review("c1", "Phượng hoàng", "model", url=self.fake.url, media=str(self.media),
                               tags={"Kind": "Model", "engine": ["Blender", "maya-x"], "episode": "Q01T03",
                                     "subject": "Phượng hoàng", "mood": "dark", "look": "", "bad group!": None,
                                     "stage": "!!!"})
        ev = self.fake.events[0]
        self.assertEqual(ev["tags"], {"kind": ["model"], "engine": ["blender", "maya-x"], "episode": ["q01t03"],
                                      "subject": ["phuong-hoang"], "mood": ["dark"], "bad_group": []})
        text = err.getvalue()
        self.assertIn("unknown value engine='maya-x'", text)
        self.assertIn("unknown group 'mood'", text)
        self.assertIn("not a valid slug", text)
        self.assertTrue(rv.enabled)
        self.assertEqual(client.normalize_tags("nope"), {})                         # never raises
        self.assertEqual(client.normalize_tags({"episode": "ep99"}, client.load_registry(str(self.media))),
                         {"episode": ["ep99"]})

    def test_meta_detail_append_and_hooks(self):
        img = self.tmp / "c.png"
        img.write_bytes(b"\x89PNG small")
        with redirect_stderr(io.StringIO()):
            rv = client.Review("c2", "T", "image", url=self.fake.url, media=str(self.media), append=True)
            self.assertTrue(rv.step("c 1/2", image=str(img), meta={"seed": 42, "sampler_steps": "30", "width": 0,
                                                                   "prompt": "p", "bogus": 1, "item": 3, "items": 2}))
            self.assertTrue(rv.job("comfy", "running", 0.5, job="comfy-x", label="qwen-t2i", step=5, steps=30,
                                   eta=10, nope=1))
        step = self.fake.of("step")[0]
        self.assertNotIn("n", step, "append: the server numbers the step")
        self.assertEqual({k: step[k] for k in ("seed", "sampler_steps", "prompt", "items")},
                         {"seed": 42, "sampler_steps": 30, "prompt": "p", "items": 2})
        self.assertNotIn("width", step)
        self.assertNotIn("item", step, "item > items is dropped")
        job = self.fake.of("job")[0]
        self.assertEqual((job["label"], job["step"], job["steps"], job["eta"]), ("qwen-t2i", 5, 30, 10.0))
        self.assertNotIn("nope", job)
        with mock.patch.dict(os.environ, {"FILM_REVIEW_BUILD": "", "FILM_REVIEW_URL": self.fake.url}):
            hook = client.job_hook("img-b", "comfy", "image", title="Concept chim", tags={"engine": "comfy-qwen"},
                                   label="qwen-t2i", media=str(self.media))
        build = self.fake.of("build")[-1]
        self.assertEqual((build["title"], build["kind"], build["tags"]), ("Concept chim", "image",
                                                                          {"engine": ["comfy-qwen"]}))
        hook.start("queued", items=4)
        hook.update(0.1, "step 3/30", force=True, step=3, steps=30, item=1, items=4)
        self.assertTrue(hook.image(str(img), seed=1, seconds=12.5, item=1, items=4))
        hook.finish()
        jobs = [e for e in self.fake.of("job") if e.get("job") == hook.key]
        self.assertTrue(all(j["label"] == "qwen-t2i" for j in jobs))
        self.assertEqual(jobs[1]["item"], 1)
        img_step = self.fake.of("step")[-1]
        self.assertEqual((img_step["label"], img_step["workflow"], img_step["seed"]), ("c", "qwen-t2i", 1))

    def test_client_and_server_share_the_contract(self):
        self.assertEqual(client.TAG_GROUP.pattern, server.TAG_GROUP.pattern)
        self.assertEqual(client.TAG_VALUE.pattern, server.TAG_VALUE.pattern)
        self.assertEqual((client.MAX_TAG_GROUPS, client.MAX_TAG_VALUES), (server.MAX_TAG_GROUPS, server.MAX_TAG_VALUES))
        self.assertEqual(set(client.STEP_META), set(server.STEP_META))
        self.assertEqual(set(client.JOB_DETAIL), set(server.JOB_DETAIL))
        self.assertEqual(client.RANGES, server.RANGES)
        for k, v in client.TEXT_FIELDS.items():
            self.assertEqual(v, server.MAX_STR[k], k)

    @unittest.skipIf(PILImage is None, "Pillow is missing")
    def test_large_images_go_as_jpeg_previews(self):
        import random
        rnd = random.Random(1)
        big = self.tmp / "concept 01.png"
        PILImage.frombytes("RGBA", (1664, 928), rnd.randbytes(1664 * 928 * 4)).save(big)
        self.assertGreater(big.stat().st_size, client.PREVIEW_MIN)
        rv = client.Review("p1", url=self.fake.url, media=str(self.media))
        self.assertTrue(rv.step("c1", image=str(big)))
        rel = self.fake.of("step")[0]["image"]
        self.assertEqual(rel, "p1/concept_01.jpg")
        with PILImage.open(self.media / rel) as im:
            self.assertEqual((im.format, max(im.size)), ("JPEG", 1280))
        self.assertLess((self.media / rel).stat().st_size, big.stat().st_size)
        with mock.patch.dict(os.environ, {"FILM_REVIEW_PREVIEW": "off"}):
            rv2 = client.Review("p2", url=self.fake.url, media=str(self.media))
        self.assertTrue(rv2.step("c1", image=str(big)))
        self.assertEqual(self.fake.of("step")[-1]["image"], "p2/concept_01.png")

    def test_without_pillow_the_original_goes(self):
        big = self.tmp / "b.png"
        big.write_bytes(b"\x89PNG" + b"\0" * client.PREVIEW_MIN)
        rv = client.Review("p3", url=self.fake.url, media=str(self.media))
        with mock.patch.object(preview, "_pil", return_value=None), \
                mock.patch.object(client, "_load_preview", return_value=preview), redirect_stderr(io.StringIO()) as e:
            self.assertTrue(rv.step("b", image=str(big)))
        self.assertEqual(self.fake.of("step")[0]["image"], "p3/b.png")
        self.assertIn("Pillow not importable", e.getvalue())


# ------------------------------------------------------------------ #60 media folder from a worktree
def fake_repo(root):
    """main/ with .git/ and a linked worktree wt/ (as `git worktree add` lays them out)."""
    main, wt = root / "main", root / "wt"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    (main / ".git" / "worktrees" / "wt" / "commondir").write_text("../..\n", encoding="utf-8")
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'wt'}\n", encoding="utf-8")
    return main, wt


class TestMainCheckout(TmpDirCase, unittest.TestCase):
    def test_worktree_resolves_to_the_main_checkout(self):
        main, wt = fake_repo(self.tmp)
        self.assertEqual(Path(client.main_checkout(str(wt))), main)
        self.assertEqual(Path(client.main_checkout(str(main))), main)
        plain = self.tmp / "plain"
        plain.mkdir()
        self.assertEqual(Path(client.main_checkout(str(plain))), plain)
        rel = self.tmp / "wt2"
        rel.mkdir()
        (rel / ".git").write_text("gitdir: ../main/.git/worktrees/wt\n", encoding="utf-8")    # relative gitdir
        self.assertEqual(Path(client.main_checkout(str(rel))), main)

    def test_client_and_up_use_the_same_folder(self):
        main, wt = fake_repo(self.tmp)
        with mock.patch.object(client, "main_checkout", lambda path=None: str(main)), \
                mock.patch.object(review.client, "main_checkout", lambda path=None: str(main)), \
                mock.patch.dict(os.environ, {"FILM_REVIEW_MEDIA": ""}):
            self.assertEqual(Path(client.media_root()), main / "out" / "_review" / "media")
            self.assertEqual(Path(review.media_dir()), main / "out" / "_review" / "media")
        with mock.patch.dict(os.environ, {"FILM_REVIEW_MEDIA": str(self.tmp / "m")}):
            self.assertEqual(Path(client.media_root()), self.tmp / "m")
            code, out, _ = run_main(review.main, ["up", "--no-ngrok", "--dry-run"])
        self.assertIn(f"mount {self.tmp / 'm'} -> /media", out)

    def test_up_passes_the_mount_to_compose(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append((cmd, kw.get("env") or {}))
            return subprocess.CompletedProcess(cmd, 0)
        media = self.tmp / "media"
        with mock.patch.dict(os.environ, {"FILM_REVIEW_MEDIA": str(media)}), \
                mock.patch.object(review.vendor_three, "verify", lambda *a, **k: []), \
                mock.patch.object(review.shutil, "which", lambda x: "/usr/bin/" + x), \
                mock.patch.object(review.subprocess, "run", fake_run), \
                mock.patch.object(review, "wait_health", lambda *a: True), \
                mock.patch.object(review, "start_monitor", lambda a: 0):
            code, out, err = run_main(review.main, ["up", "--no-ngrok"])
        self.assertEqual(code, 0, err)
        self.assertEqual(calls[0][0][-3:], ["up", "-d", "--build"])
        self.assertEqual(calls[0][1][review.MOUNT_ENV], str(media))
        self.assertTrue(media.is_dir())

    def test_status_warns_when_the_container_mounts_another_folder(self):
        with mock.patch.dict(os.environ, {"FILM_REVIEW_MEDIA": str(self.tmp / "main" / "media")}), \
                mock.patch.object(review, "get_json", side_effect=OSError("down")), \
                mock.patch.object(review, "monitor_pid", lambda: None), mock.patch.object(review, "watchers", list), \
                mock.patch.object(review, "current_url", lambda: (None, None)):
            with mock.patch.object(review, "container_media_mount", lambda: str(self.tmp / "wt" / "media")):
                _, out, _ = run_main(review.main, ["status"])
            self.assertIn("WARNING media: the container mounts", out)
            with mock.patch.object(review, "container_media_mount", lambda: str(self.tmp / "main" / "media") + "/"):
                _, out, _ = run_main(review.main, ["status"])
            self.assertIn("the container mounts the same folder", out)
            self.assertNotIn("WARNING", out)

    def test_docker_inspect_paths(self):
        self.assertTrue(review.host_path("/run/desktop/mnt/host/d/Projects/x").startswith("D:"))
        self.assertTrue(review.same_path("D:\\Projects\\Lab\\out", "d:/projects/lab/out/"))
        self.assertTrue(review.same_path(review.host_path("/host_mnt/d/Lab/out"), "D:/Lab/out"))
        self.assertFalse(review.same_path("D:/Lab/out", "D:/Lab-wt/out"))
        mounts = json.dumps([{"Type": "volume", "Destination": "/data", "Source": "/var/lib/x"},
                             {"Type": "bind", "Destination": "/media", "Source": "/run/desktop/mnt/host/d/Lab/out"}])
        with mock.patch.object(review.shutil, "which", lambda x: "/usr/bin/docker"), \
                mock.patch.object(review.subprocess, "run",
                                  lambda *a, **k: subprocess.CompletedProcess(a[0], 0, mounts, "")):
            self.assertTrue(review.same_path(review.container_media_mount(), "D:/Lab/out"))

    def test_compose_and_dockerfile(self):
        text = (REPO / "tools" / "review" / "Dockerfile").read_text(encoding="utf-8")
        run = re.search(r"RUN for f in (.*?); do", text, re.S).group(1)
        self.assertEqual(sorted(run.replace("\\", " ").split()), sorted(vendor.FILES),
                         "the image build checks every vendored three.js file")
        self.assertIn("exit 1", text)
        self.assertIn("tags.json", text)


# ------------------------------------------------------------------ #60 tunnels
class TestTunnels(TmpDirCase, unittest.TestCase):
    def up(self, *args, which=None, ts=("Running", "lab.tail1234.ts.net")):
        with mock.patch.object(review.vendor_three, "verify", lambda *a, **k: []), \
                mock.patch.object(review.shutil, "which", which or (lambda x: None)), \
                mock.patch.object(review, "ngrok_url", lambda: None), \
                mock.patch.object(review, "tailscale_status", lambda exe: ts), \
                mock.patch.object(review.subprocess, "run", side_effect=AssertionError("docker must not run")):
            return run_main(review.main, ["up"] + list(args))

    def test_missing_binary_or_login_refuses_before_docker(self):
        for kind in ("ngrok", "tailscale", "cloudflared"):
            code, _, err = self.up("--tunnel", kind)
            self.assertEqual(code, 2, kind)
            self.assertIn(f"{kind} not found on PATH", err)
        code, _, err = self.up("--tunnel", "tailscale", which=lambda x: "/usr/bin/" + x, ts=("NeedsLogin", None))
        self.assertEqual(code, 2)
        self.assertIn("not logged in", err)

    def test_dry_run_prints_each_tunnel(self):
        out = {k: run_main(review.main, ["up", "--dry-run", "--tunnel", k])[1] for k in review.TUNNELS}
        self.assertIn("ngrok http 127.0.0.1:8790", out["ngrok"])
        self.assertIn("tailscale funnel --bg 8790", out["tailscale"])
        self.assertIn("cloudflared tunnel --no-autoupdate --metrics 127.0.0.1:20241 --url http://127.0.0.1:8790",
                      out["cloudflared"])
        src = (REPO / "tools" / "review" / "review.py").read_text(encoding="utf-8").split('"""', 2)[2]
        for never in ("ngrok.yml", "config.yml", "authtoken", ".cloudflared", "tailscale up", "tailscale login"):
            self.assertNotIn(never, src, never)

    def test_cloudflared_url_from_its_log(self):
        log = self.tmp / "cf.log"
        log.write_text("INF |  https://bright-owl-1234.trycloudflare.com  |\n", encoding="utf-8")
        with mock.patch.object(review, "CLOUDFLARED_LOG", str(log)), \
                mock.patch.object(review, "get_json", side_effect=OSError("no metrics")):
            self.assertEqual(review.cloudflared_url(), "https://bright-owl-1234.trycloudflare.com")
        with mock.patch.object(review, "get_json", lambda *a, **k: {"hostname": "x-y.trycloudflare.com"}):
            self.assertEqual(review.cloudflared_url(), "https://x-y.trycloudflare.com")


# ------------------------------------------------------------------ #57 who holds the GPU
class TestGpuOwner(TmpDirCase, unittest.TestCase):
    def owner(self, d):
        p = self.tmp / "gpu.owner"
        p.write_text(json.dumps(d), encoding="utf-8")
        return str(p)

    def test_owner_file_alive_dead_and_sanitised(self):
        p = self.owner({"label": "film-3d-artist s21 · Phượng D:\\Projects\\Danny\\x\\ph.blend <b>", "pid": 4242,
                        "since": "2026-11-26T08:15:00Z"})
        got = monitor.read_gpu_owner(p, alive=lambda pid: pid == 4242)
        self.assertEqual(got["label"], "film-3d-artist s21 Phuong ph.blend b")
        self.assertEqual(got["since"], 1795680900.0)
        self.assertRegex(got["label"], server.GPU_OWNER.pattern)
        self.assertIsNone(monitor.read_gpu_owner(p, alive=lambda pid: False), "a dead pid = free")
        self.assertIsNone(monitor.read_gpu_owner(str(self.tmp / "none"), alive=lambda pid: True))
        self.assertEqual(monitor.read_gpu_owner(self.owner({"pid": 1}), alive=lambda pid: True)["label"], "GPU job")
        self.assertEqual(len(monitor.gpu_owner_label("x" * 200)), 60)
        self.assertTrue(monitor.pid_alive(os.getpid()))
        self.assertFalse(monitor.pid_alive(0))
        with mock.patch.dict(os.environ, {"FILM_GPU_LOCK": str(self.tmp / "locks" / "gpu.lock")}):
            self.assertEqual(Path(monitor.gpu_owner_path()), self.tmp / "locks" / "gpu.owner")

    def test_server_takes_the_owner_and_refuses_bad_labels(self):
        ev = monitor.clamp_event({"type": "metrics", "t": 1, "cpu": 5, "gpu_owner": {"label": "blender s21", "since": 5}})
        _, clean = server.validate_sys(ev)
        self.assertEqual(clean["gpu_owner"], {"label": "blender s21", "since": 5})
        for bad in ({"label": "<script>"}, {"label": ""}, {"label": "x" * 61}, {"label": "ok", "pid": 3}):
            with self.assertRaises(server.BadEvent):
                server.validate_sys({"type": "metrics", "gpu_owner": bad})
        self.assertNotIn("gpu_owner", monitor.clamp_event({"type": "metrics", "gpu_owner": None}))
        mon = monitor.Monitor("off", f"http://127.0.0.1:{free_port()}", None)
        with mock.patch.object(monitor, "read_gpu_owner", lambda: {"label": "comfy qwen-t2i", "since": None}):
            self.assertEqual(mon.metrics()["gpu_owner"]["label"], "comfy qwen-t2i")


# ------------------------------------------------------------------ #64 point 1: the ComfyUI log from a worktree
class TestComfyLogFromWorktree(TmpDirCase, unittest.TestCase):
    def test_the_main_checkouts_log_is_found(self):
        main, wt = fake_repo(self.tmp)
        log = main / "out" / "_comfy" / "server.log"
        env = {"FILM_COMFY_LOG": "", "FILM_COMFY_WORK": ""}
        with mock.patch.object(monitor.client, "main_checkout", lambda path=None: str(main)), \
                mock.patch.object(monitor, "LAB", str(wt)), mock.patch.dict(os.environ, env):
            cands = monitor.comfy_log_candidates()
            self.assertEqual([Path(c) for c in cands], [log, wt / "out" / "_comfy" / "server.log"])
            self.assertEqual(Path(monitor.default_comfy_log()), log, "nothing exists yet: the main checkout's path")
            mine = wt / "out" / "_comfy" / "server.log"
            mine.parent.mkdir(parents=True)
            mine.write_text("x", encoding="utf-8")
            self.assertEqual(Path(monitor.default_comfy_log()), mine)
            log.parent.mkdir(parents=True)
            log.write_text("y", encoding="utf-8")
            os.utime(log, (time.time() + 60, time.time() + 60))
            self.assertEqual(Path(monitor.default_comfy_log()), log, "both exist: the newer one")
        with mock.patch.dict(os.environ, {"FILM_COMFY_WORK": str(self.tmp / "w"), "FILM_COMFY_LOG": ""}):
            self.assertEqual(Path(monitor.default_comfy_log()), self.tmp / "w" / "server.log")


# ------------------------------------------------------------------ web: tags.js and route.js under node
TAGS_TEST = r"""
import { parseRoute } from '%s';
import { setRegistry, tagLabel, matches, facets, groupBuilds, parseState, stateQuery, orderGroups } from '%s';
setRegistry({ groups: {
  kind: { label: 'Loại', color: '#5ef2ff', values: { model: 'Model' } },
  episode: { label: 'Tập', color: '#3ddc97', values: {}, labels_re: [['^q0*([0-9]+)t0*([0-9]+)$', 'Q$1·T$2']] },
  engine: { label: 'Engine', color: '#b69cff', values: { blender: 'Blender' } } } });
const b = [
  { id: 'a', tags: { kind: ['model'], engine: ['blender'], episode: ['q01t03'] } },
  { id: 'b', tags: { kind: ['image'], engine: ['comfy-qwen'], episode: ['q01t04'] } },
  { id: 'c', tags: { kind: ['model'], engine: ['blender'], episode: ['q01t04'] } },
  { id: 'd', tags: { kind: ['clip'] } },
];
const pick = (sel) => b.filter((x) => matches(x, sel)).map((x) => x.id);
const st = parseState('st=active&t=kind:model,episode:q01t03,episode:q01t04,bad:X,%%3Cs%%3E:x&g=episode');
console.log(JSON.stringify({
  labels: [tagLabel('episode', 'q01t03'), tagLabel('kind', 'model'), tagLabel('subject', 'phuong-hoang')],
  and: pick({ kind: new Set(['model']), episode: new Set(['q01t04']) }),
  or: pick({ episode: new Set(['q01t03', 'q01t04']) }),
  none: pick({}),
  facets: facets(b).map(([g, vals]) => [g, vals]),
  groups: groupBuilds(b, 'episode').map(([v, xs]) => [v, xs.map((x) => x.id)]),
  state: { status: st.status, group: st.group, sel: Object.fromEntries(Object.entries(st.sel).map(([g, s]) => [g, [...s]])) },
  query: stateQuery(st),
  order: orderGroups(['zeta', 'engine', 'kind', 'alpha']),
  route: parseRoute('#/?t=kind:model&g=episode', ['', 'build', 'images']),
  img: parseRoute('#/images/concept%%20a', ['', 'build', 'images']),
}));
"""


@unittest.skipIf(NODE is None, "node is missing")
class TestTagsJs(unittest.TestCase):
    def test_filter_group_and_hash_state(self):
        src = TAGS_TEST % ((WEB / "route.js").resolve().as_uri(), (WEB / "tags.js").resolve().as_uri())
        r = subprocess.run([NODE, "--input-type=module", "-e", src], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["labels"], ["Q1·T3", "Model", "Phuong hoang"])
        self.assertEqual(out["and"], ["c"], "AND across groups")
        self.assertEqual(out["or"], ["a", "b", "c"], "OR within a group")
        self.assertEqual(out["none"], ["a", "b", "c", "d"])
        self.assertEqual(out["facets"][0], ["kind", [["clip", 1], ["image", 1], ["model", 2]]])
        self.assertEqual([g for g, _ in out["facets"]], ["kind", "episode", "engine"], "registry order")
        self.assertEqual(out["groups"], [["q01t03", ["a"]], ["q01t04", ["b", "c"]], [None, ["d"]]])
        self.assertEqual(out["state"], {"status": "active", "group": "episode",
                                        "sel": {"kind": ["model"], "episode": ["q01t03", "q01t04"]}})
        self.assertEqual(out["query"], "st=active&t=episode:q01t03,episode:q01t04,kind:model&g=episode")
        self.assertEqual(out["order"], ["kind", "engine", "alpha", "zeta"])
        self.assertEqual((out["route"]["key"], out["route"]["query"]), ("", "t=kind:model&g=episode"))
        self.assertEqual((out["img"]["key"], out["img"]["args"]), ("images", ["concept a"]))


class TestWebFiles(unittest.TestCase):
    def test_gallery_and_dashboard_wiring(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("images: () => import('./gallery.js')", app)
        self.assertIn("history.replaceState", app, "filters go into the hash without a re-render")
        gal = (WEB / "gallery.js").read_text(encoding="utf-8")
        self.assertIn("if (!alive()) return {};", gal)
        self.assertNotRegex(gal, r"three-util|from 'three", "the gallery needs no three.js")
        self.assertIn("MAX_COMPARE = 4", gal)
        sysjs = (WEB / "sys.js").read_text(encoding="utf-8")
        self.assertIn("gpu_owner", sysjs)
        self.assertIn("'images'", sysjs)
        for js in ("app.js", "gallery.js", "tags.js", "sys.js", "blueprint.js"):
            text = (WEB / js).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"https?://", f"{js}: no CDN, no external URL")
            self.assertNotIn("innerHTML", text, f"{js}: text only (tags and prompts are untrusted)")


if __name__ == "__main__":
    unittest.main()
