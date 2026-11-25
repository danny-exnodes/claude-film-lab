"""tools/review/: the review server (ingest -> SQLite -> API/SSE, media with Range, read-only public port), the
offline-safe client, vendor_three.py, review.py and the --review hooks of blender.py and comfy.py.
Servers run in threads on 127.0.0.1 with port 0; no Docker, no network, no Blender, no ComfyUI."""
import base64, hashlib, http.client, json, os, re, socket, struct, sys, threading, time, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import helpers
from helpers import REPO, TmpDirCase, load, run_main

server = load("review/server.py", "film_review_server")
client = load("review/client.py", "film_review_client")
vendor = load("review/vendor_three.py", "film_review_vendor")
sys.path.insert(0, str(REPO / "tools" / "review"))
review = load("review/review.py", "film_review_cli")

IMPORTMAP = '{"imports":{"three":"./vendor/three/build/three.module.js"}}'
INDEX = ('<!doctype html><html><head><script type="importmap">%s</script>'
         '<script type="module" src="app.js"></script></head><body></body></html>' % IMPORTMAP)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class FakeIngest:
    """Collects the events POSTed to /ingest/event."""

    def __init__(self):
        self.events = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                fake.events.append(json.loads(self.rfile.read(n)))
                body = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def types(self):
        return [e["type"] for e in self.events]

    def of(self, kind):
        return [e for e in self.events if e["type"] == kind]

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class ServerCase(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.media = self.tmp / "media"
        self.web = self.tmp / "web"
        (self.media / "b1").mkdir(parents=True)
        self.web.mkdir()
        (self.web / "index.html").write_text(INDEX, encoding="utf-8")
        (self.web / "app.js").write_text("console.log('hi')\n", encoding="utf-8")
        (self.tmp / "secret.txt").write_text("secret", encoding="utf-8")
        self.app = server.App(str(self.tmp / "db" / "review.db"), str(self.media), str(self.web), host="127.0.0.1",
                              public_port=0, ingest_port=0, quiet=True).start()
        self.addCleanup(self.app.stop)
        self.ingest_url = f"http://127.0.0.1:{self.app.ingest_port}"

    def request(self, method, path, body=None, headers=None, port=None):
        c = http.client.HTTPConnection("127.0.0.1", port or self.app.public_port, timeout=5)
        try:
            c.putrequest(method, path, skip_accept_encoding=True)
            for k, v in (headers or {}).items():
                c.putheader(k, v)
            data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
            if data is not None:
                c.putheader("Content-Length", str(len(data)))
            c.endheaders(data)
            r = c.getresponse()
            return r.status, dict((k.lower(), v) for k, v in r.getheaders()), r.read()
        finally:
            c.close()

    def get(self, path, headers=None):
        return self.request("GET", path, headers=headers)

    def get_json(self, path):
        code, _, body = self.get(path)
        self.assertEqual(code, 200, body)
        return json.loads(body)

    def post(self, ev, ctype="application/json"):
        code, _, body = self.request("POST", "/ingest/event", ev, {"Content-Type": ctype}, port=self.app.ingest_port)
        return code, json.loads(body or b"{}")

    def ok(self, ev):
        code, body = self.post(ev)
        self.assertEqual(code, 200, body)
        return body


class TestIngestApi(ServerCase):
    def test_build_steps_renders_jobs_round_trip(self):
        self.ok({"type": "build", "build": "b1", "title": "Giọt", "kind": "demo", "project": "lab", "expected_steps": 4})
        (self.media / "b1" / "step_01.glb").write_bytes(b"glTF")
        self.ok({"type": "step", "build": "b1", "label": "body", "glb": "b1/step_01.glb", "stats": {"verts": 930}})
        self.ok({"type": "step", "build": "b1", "label": "tip", "image": "b1/step_02.png"})
        b = self.get_json("/api/builds")["builds"]
        self.assertEqual(len(b), 1)
        self.assertEqual((b[0]["id"], b[0]["title"], b[0]["kind"], b[0]["status"]), ("b1", "Giọt", "demo", "building"))
        self.assertEqual((b[0]["steps"], b[0]["progress"], b[0]["current"]), (2, 0.5, "tip"))
        self.assertEqual((b[0]["last_glb"], b[0]["thumb"]), ("b1/step_01.glb", "b1/step_02.png"))
        steps = self.get_json("/api/builds/b1/steps")["steps"]
        self.assertEqual([(s["n"], s["label"]) for s in steps], [(1, "body"), (2, "tip")])
        self.assertEqual(steps[0]["stats"], {"verts": 930})
        self.ok({"type": "job", "build": "b1", "tool": "blender", "status": "running", "progress": 0.25,
                 "message": "frame 3/12", "job": "j1"})
        self.ok({"type": "job", "build": "b1", "tool": "blender", "status": "done", "progress": 1, "gpu_s": 12.5,
                 "job": "j1"})
        self.ok({"type": "render", "build": "b1", "label": "beauty", "video": "b1/beauty.mp4", "frames": 12,
                 "fps": 24, "duration": 0.5, "engine": "blender BLENDER_EEVEE", "seconds_per_frame": 0.2})
        self.ok({"type": "render", "build": "b1", "label": "beauty v2", "video": "b1/beauty.mp4", "frames": 12})
        self.ok({"type": "done", "build": "b1", "message": "ok"})
        d = self.get_json("/api/builds/b1")
        self.assertEqual([r["label"] for r in d["renders"]], ["beauty v2"], "the same file published twice: one row")
        self.assertEqual(d["build"]["status"], "done")
        self.assertEqual(d["build"]["progress"], 1)
        self.assertIsNotNone(d["build"]["finished"])
        self.assertEqual(len(d["jobs"]), 1)
        self.assertEqual((d["jobs"][0]["status"], d["jobs"][0]["gpu_s"], d["jobs"][0]["message"]),
                         ("done", 12.5, "frame 3/12"))
        self.assertEqual(d["renders"][0]["video"], "b1/beauty.mp4")
        lib = self.get_json("/api/renders")["renders"]
        self.assertEqual((lib[0]["build_title"], lib[0]["project"]), ("Giọt", "lab"))

    def test_events_for_an_unknown_build_create_it(self):
        self.ok({"type": "progress", "build": "late", "progress": 0.3, "message": "frame 3"})
        b = self.get_json("/api/builds/late")["build"]
        self.assertEqual((b["title"], b["status"], b["progress"], b["current"]), ("late", "building", 0.3, "frame 3"))

    def test_job_running_marks_rendering_and_fail(self):
        self.ok({"type": "build", "build": "r1", "kind": "render", "status": "queued"})
        self.ok({"type": "job", "build": "r1", "tool": "comfy", "status": "running", "progress": 0.4})
        self.assertEqual(self.get_json("/api/builds/r1")["build"]["status"], "rendering")
        self.ok({"type": "fail", "build": "r1", "message": "CUDA out of memory"})
        b = self.get_json("/api/builds/r1")["build"]
        self.assertEqual((b["status"], b["message"]), ("failed", "CUDA out of memory"))

    def test_restart_replaces_old_steps(self):
        self.ok({"type": "build", "build": "b1", "title": "t", "expected_steps": 2})
        for label in ("a", "b"):
            self.ok({"type": "step", "build": "b1", "label": label})
        self.ok({"type": "done", "build": "b1"})
        self.ok({"type": "build", "build": "b1", "restart": True})
        b = self.get_json("/api/builds/b1")
        self.assertEqual((b["build"]["status"], b["build"]["progress"], b["steps"]), ("building", 0, []))

    def test_bad_events_are_refused(self):
        bad = [
            {"type": "explode", "build": "b1"},
            {"build": "b1"},
            {"type": "step", "build": "../x", "label": "a"},
            {"type": "step", "build": "b1"},
            {"type": "step", "build": "b1", "label": "a", "colour": "red"},
            {"type": "step", "build": "b1", "label": "a", "glb": "../secret.txt"},
            {"type": "step", "build": "b1", "label": "a", "glb": "/etc/passwd"},
            {"type": "step", "build": "b1", "label": "a", "glb": "other/step.glb"},
            {"type": "step", "build": "b1", "label": "a", "glb": "b1\\..\\x.glb"},
            {"type": "progress", "build": "b1", "progress": 1.5},
            {"type": "progress", "build": "b1", "progress": "half"},
            {"type": "build", "build": "b1", "kind": "movie"},
            {"type": "job", "build": "b1", "tool": "maya", "status": "running"},
            {"type": "render", "build": "b1", "label": "no file"},
            [1, 2],
        ]
        for ev in bad:
            code, body = self.post(ev)
            self.assertEqual(code, 400, (ev, body))
            self.assertIn("error", body)
        self.assertEqual(self.get_json("/api/builds")["builds"], [])

    def test_ingest_wants_json(self):
        code, _ = self.post({"type": "done", "build": "b1"}, ctype="text/plain")
        self.assertEqual(code, 415)
        code, _, _ = self.request("POST", "/ingest/event", b"{not json", {"Content-Type": "application/json"},
                                  port=self.app.ingest_port)
        self.assertEqual(code, 400)
        code, _, _ = self.request("GET", "/ingest/event", port=self.app.ingest_port)
        self.assertEqual(code, 404)
        code, _, _ = self.request("PUT", "/ingest/event", b"{}", port=self.app.ingest_port)
        self.assertEqual(code, 405)

    def test_public_port_is_read_only(self):
        for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
            for path in ("/ingest/event", "/api/builds", "/"):
                code, headers, _ = self.request(method, path, b'{"type":"done","build":"b1"}',
                                                {"Content-Type": "application/json"})
                self.assertEqual(code, 405, (method, path))
                self.assertEqual(headers.get("allow"), "GET, HEAD")
        self.assertEqual(self.get_json("/api/builds")["builds"], [])

    def test_unknown_api_and_build(self):
        self.assertEqual(self.get("/api/nope")[0], 404)
        self.assertEqual(self.get("/api/builds/nope")[0], 404)
        self.assertEqual(self.get_json("/api/health")["ok"], True)


class TestStream(ServerCase):
    def open_stream(self, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.app.public_port, timeout=5)
        c.request("GET", "/api/stream", headers=headers or {})
        r = c.getresponse()
        self.addCleanup(c.close)
        return r

    def read_event(self, r, want):
        """The data of the first SSE event named want."""
        name, data, deadline = None, [], time.monotonic() + 5
        while time.monotonic() < deadline:
            line = r.fp.readline().decode("utf-8").rstrip("\n")
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data.append(line[6:])
            elif line == "":
                if name == want:
                    return json.loads("\n".join(data))
                name, data = None, []
        self.fail(f"no {want} event")

    def test_sse_delivers_events(self):
        r = self.open_stream()
        self.assertEqual(r.status, 200)
        self.assertTrue(r.getheader("Content-Type").startswith("text/event-stream"))
        self.read_event(r, "hello")
        self.ok({"type": "build", "build": "b1", "title": "Live", "expected_steps": 2})
        self.ok({"type": "step", "build": "b1", "label": "body"})
        ev = self.read_event(r, "step")
        self.assertEqual((ev["type"], ev["data"]["label"], ev["data"]["n"]), ("step", "body", 1))
        self.assertEqual((ev["build"]["id"], ev["build"]["progress"]), ("b1", 0.5))

    def test_last_event_id_replays_missed_events(self):
        first = self.ok({"type": "build", "build": "b1", "title": "x"})["id"]
        self.ok({"type": "step", "build": "b1", "label": "missed"})
        r = self.open_stream({"Last-Event-ID": str(first)})
        ev = self.read_event(r, "step")
        self.assertEqual(ev["data"]["label"], "missed")

    def test_heartbeat(self):
        with mock.patch.object(server, "HEARTBEAT", 0.1):
            app = server.App(":memory:", str(self.media), None, host="127.0.0.1", public_port=0, ingest_port=0,
                             quiet=True).start()
            self.addCleanup(app.stop)
            c = http.client.HTTPConnection("127.0.0.1", app.public_port, timeout=5)
            self.addCleanup(c.close)
            c.request("GET", "/api/stream")
            ev = self.read_event(c.getresponse(), "heartbeat")
            self.assertIn("t", ev)


class TestFiles(ServerCase):
    def setUp(self):
        super().setUp()
        self.blob = bytes(range(256)) * 4                 # 1024 bytes
        (self.media / "b1" / "clip.mp4").write_bytes(self.blob)

    def test_range_requests(self):
        code, h, body = self.get("/media/b1/clip.mp4")
        self.assertEqual((code, body, h["accept-ranges"], h["content-type"]), (200, self.blob, "bytes", "video/mp4"))
        for rng, start, end in (("bytes=0-99", 0, 99), ("bytes=1000-", 1000, 1023), ("bytes=-24", 1000, 1023),
                                ("bytes=1000-5000", 1000, 1023), ("bytes=5-5", 5, 5)):
            code, h, body = self.get("/media/b1/clip.mp4", {"Range": rng})
            self.assertEqual(code, 206, rng)
            self.assertEqual(h["content-range"], f"bytes {start}-{end}/1024", rng)
            self.assertEqual(body, self.blob[start:end + 1], rng)
            self.assertEqual(int(h["content-length"]), end - start + 1)
        for rng in ("bytes=2000-", "bytes=10-5", "bytes=-0", "items=0-1", "bytes=-"):
            code, h, body = self.get("/media/b1/clip.mp4", {"Range": rng})
            self.assertEqual(code, 416, rng)
            self.assertEqual(h["content-range"], "bytes */1024", rng)
            self.assertEqual(body, b"")
        code, _, body = self.get("/media/b1/clip.mp4", {"Range": "bytes=0-1,5-6"})
        self.assertEqual((code, body), (200, self.blob))

    def test_head_and_etag(self):
        code, h, body = self.request("HEAD", "/media/b1/clip.mp4")
        self.assertEqual((code, body, h["content-length"]), (200, b"", "1024"))
        code, _, _ = self.get("/media/b1/clip.mp4", {"If-None-Match": h["etag"]})
        self.assertEqual(code, 304)

    def test_mime_types(self):
        for name, mime in (("m.glb", "model/gltf-binary"), ("a.png", "image/png"), ("v.webm", "video/webm"),
                           ("s.wav", "audio/wav"), ("s.mp3", "audio/mpeg"), ("x.json", "application/json")):
            (self.media / "b1" / name).write_bytes(b"x")
            code, h, _ = self.get(f"/media/b1/{name}")
            self.assertEqual((code, h["content-type"]), (200, mime), name)
            self.assertEqual(h["x-content-type-options"], "nosniff")
        (self.media / "b1" / "evil.html").write_text("<script>alert(1)</script>")
        (self.media / "b1" / "tool.py").write_text("x")
        self.assertEqual(self.get("/media/b1/evil.html")[0], 404)
        self.assertEqual(self.get("/media/b1/tool.py")[0], 404)

    def test_no_directory_listing(self):
        for path in ("/media/", "/media/b1", "/media/b1/", "/media/nope.mp4"):
            code, _, body = self.get(path)
            self.assertIn(code, (403, 404), path)
            self.assertNotIn(b"clip.mp4", body)

    def test_traversal_is_refused(self):
        for path in ("/media/../secret.txt", "/media/b1/../../secret.txt", "/media/%2e%2e/secret.txt",
                     "/media/..%2fsecret.txt", "/media/b1%2f..%2f..%2fsecret.txt", "/media/..%5csecret.txt",
                     "/media/%2fetc%2fpasswd", "/media/C:%5cWindows%5cwin.ini", "/media/b1/clip.mp4%00.png",
                     "/../secret.txt", "/%2e%2e/secret.txt", "/vendor/../../secret.txt"):
            code, _, body = self.get(path)
            self.assertIn(code, (400, 403, 404), path)
            self.assertNotIn(b"secret", body, path)

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_symlink_out_of_the_root_is_refused(self):
        os.symlink(self.tmp / "secret.txt", self.media / "b1" / "link.png")
        code, _, body = self.get("/media/b1/link.png")
        self.assertEqual(code, 403)
        self.assertNotIn(b"secret", body)

    def test_web_app_and_csp(self):
        code, h, body = self.get("/")
        self.assertEqual((code, h["content-type"]), (200, "text/html; charset=utf-8"))
        csp = h["content-security-policy"]
        script = re.search(r"script-src ([^;]+)", csp).group(1).split()
        digest = base64.b64encode(hashlib.sha256(IMPORTMAP.encode()).digest()).decode()
        self.assertEqual(script, ["'self'", f"'sha256-{digest}'"])
        self.assertIn("default-src 'none'", csp)
        self.assertIn("connect-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertNotIn("unsafe-eval", csp)
        code, h, _ = self.get("/app.js")
        self.assertEqual((code, h["content-type"]), (200, "text/javascript; charset=utf-8"))
        self.assertIn("content-security-policy", self.get("/api/builds")[1])
        self.assertEqual(self.get("/missing.js")[0], 404)

    def test_the_real_web_app_csp_covers_its_import_map(self):
        web = REPO / "tools" / "review" / "web"
        hashes = server.importmap_hashes(str(web))
        self.assertEqual(len(hashes), 1, "index.html has exactly one inline import map")
        html = (web / "index.html").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"<script(?![^>]*\bsrc=)(?![^>]*importmap)", html)), 0,
                         "no inline script other than the import map")


class TestClient(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeIngest()
        self.addCleanup(self.fake.stop)
        self.media = self.tmp / "media"

    def rv(self, build="c1", **kw):
        return client.Review(build, "T", "model", url=kw.pop("url", self.fake.url), media=str(self.media), **kw)

    def test_offline_is_fast_and_never_raises(self):
        port = free_port()
        glb = self.tmp / "m.glb"
        glb.write_bytes(b"glTF")
        t0 = time.monotonic()
        rv = client.Review("c1", "T", "model", url=f"http://127.0.0.1:{port}", media=str(self.media))
        results = [rv.step("a", glb=str(glb)), rv.progress(0.5, "half"), rv.job("blender", "running", 0.5),
                   rv.render("r", video=str(glb)), rv.done(), rv.fail("x")]
        self.assertEqual(results, [False] * 6)
        self.assertLess(time.monotonic() - t0, 30)          # Windows retries a refused SYN for ~2 s per call
        self.assertIsNotNone(rv.last_error)
        self.assertTrue((self.media / "c1" / "m.glb").is_file(), "files are still copied while offline")

    def test_a_hanging_server_only_costs_one_timeout(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(16)                                        # accepts the connection, never answers
        self.addCleanup(s.close)
        with mock.patch.object(client, "TIMEOUT", 0.3):
            rv = client.Review("c1", url=f"http://127.0.0.1:{s.getsockname()[1]}", media=str(self.media))
            t0 = time.monotonic()
            for i in range(20):
                self.assertFalse(rv.progress(i / 20))
                self.assertFalse(rv.job("comfy", "running", i / 20))
            self.assertLess(time.monotonic() - t0, 1.0, "quiet after a timeout: no 2 s wait per call")

    def test_events_and_files(self):
        rv = self.rv(project="p", expected_steps=3, restart=True)
        a = self.tmp / "out" / "step.glb"
        a.parent.mkdir()
        a.write_bytes(b"one")
        self.assertTrue(rv.step("body", glb=str(a), stats={"verts": 3}))
        self.assertTrue(rv.step("again", glb=str(a)))                   # same bytes: same media file
        b = self.tmp / "other" / "step.glb"
        b.parent.mkdir()
        b.write_bytes(b"two")
        self.assertTrue(rv.step("other", glb=str(b)))                   # same name, new bytes: never overwritten
        steps = self.fake.of("step")
        self.assertEqual([s["glb"] for s in steps], ["c1/step.glb", "c1/step.glb", "c1/step-2.glb"])
        self.assertEqual([s["n"] for s in steps], [1, 2, 3])
        self.assertEqual((self.media / "c1" / "step.glb").read_bytes(), b"one")
        self.assertEqual((self.media / "c1" / "step-2.glb").read_bytes(), b"two")
        first = self.fake.events[0]
        self.assertEqual(first, {"type": "build", "build": "c1", "title": "T", "kind": "model", "project": "p",
                                 "expected_steps": 3, "restart": True})
        in_place = Path(rv.media_dir()) / "step_09.glb"
        in_place.write_bytes(b"x")
        rv.step("direct", glb=str(in_place))
        self.assertEqual(self.fake.of("step")[-1]["glb"], "c1/step_09.glb")
        self.assertFalse(rv.render("missing", video=str(self.tmp / "nope.mp4")))

    def test_names_are_sanitised(self):
        rv = self.rv()
        f = self.tmp / "Giọt bản cuối (v2).MP4"
        f.write_bytes(b"x")
        rv.render("r", video=str(f))
        self.assertRegex(self.fake.of("render")[0]["video"], r"^c1/[A-Za-z0-9._-]+\.mp4$")

    def test_off_and_bad_ids_disable_publishing(self):
        self.assertFalse(self.rv(url="off").progress(0.1))
        bad = client.Review("../evil", url=self.fake.url, media=str(self.media))
        self.assertFalse(bad.enabled)
        self.assertFalse(bad.step("x"))
        self.assertEqual(self.fake.events, [])

    def test_announce_is_retried_after_an_outage(self):
        port = free_port()
        rv = client.Review("c1", "T", url=f"http://127.0.0.1:{port}", media=str(self.media))
        rv.url = client.ingest_url(self.fake.url)
        rv._quiet_until = 0.0                               # (Windows: the refused port timed out; 15 s later)
        self.assertTrue(rv.progress(0.2))
        self.assertEqual(self.fake.types(), ["build", "progress"])

    def test_job_hook_throttles(self):
        rv = self.rv()
        hook = client.JobHook(rv, "blender", every=60)
        hook.start("go")
        for i in range(50):
            hook.update(i / 50, f"frame {i}")
        hook.update(0.99, "forced", force=True)
        hook.finish([{"label": "beauty", "image": str(self._png())}])
        jobs = self.fake.of("job")
        self.assertEqual([j["status"] for j in jobs], ["running", "running", "done"])
        self.assertEqual(jobs[1]["message"], "forced")
        self.assertEqual(self.fake.types()[-2:], ["render", "done"])
        self.assertEqual(len({j["job"] for j in jobs}), 1)

    def _png(self):
        p = self.tmp / "f.png"
        p.write_bytes(b"\x89PNG")
        return p

    def test_job_hook_from_env(self):
        with mock.patch.dict(os.environ, {"FILM_REVIEW_BUILD": "", "FILM_REVIEW_URL": self.fake.url}):
            self.assertIsNone(client.job_hook(None, "comfy"))
            os.environ["FILM_REVIEW_BUILD"] = "envb"
            hook = client.job_hook(None, "comfy", "clip", media=str(self.media))
        self.assertIsNotNone(hook)
        self.assertEqual(self.fake.events[0], {"type": "build", "build": "envb", "kind": "clip", "status": "rendering"})


class TestClientAgainstServer(ServerCase):
    def test_client_to_real_server(self):
        rv = client.Review("live", "Live", "demo", expected_steps=2, url=self.ingest_url, media=str(self.media))
        glb = self.tmp / "s.glb"
        glb.write_bytes(b"glTF-bytes")
        self.assertTrue(rv.step("body", glb=str(glb), stats={"verts": 1}))
        self.assertTrue(rv.done())
        d = self.get_json("/api/builds/live")
        self.assertEqual((d["build"]["status"], d["steps"][0]["glb"]), ("done", "live/s.glb"))
        code, _, body = self.get("/media/live/s.glb")
        self.assertEqual((code, body), (200, b"glTF-bytes"))


class TestVendor(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.src = self.tmp / "three"
        for rel in vendor.FILES:
            p = self.src / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"// {rel}\n", encoding="utf-8")
        (self.src / "package.json").write_text('{"name": "three", "version": "0.186.1"}', encoding="utf-8")
        self.core = self.tmp / "three.lock"
        self.core.write_text("# c\nversion 0.186.1\n" + "".join(
            f"sha256 {r} {vendor.sha256(self.src / r)}\n" for r in vendor.CORE), encoding="utf-8")
        self.lock = self.tmp / "three-examples.lock"
        self.dest = self.tmp / "web" / "vendor" / "three"

    def run_vendor(self, *extra):
        return run_main(vendor.main, ["--dest", str(self.dest), "--core-lock", str(self.core), "--lock", str(self.lock),
                                      *extra])

    def test_copy_records_then_verifies(self):
        code, out, err = self.run_vendor("--from", str(self.src))
        self.assertEqual(code, 0, err)
        self.assertEqual(out.count("recorded"), 4)
        for rel in vendor.FILES:
            self.assertEqual((self.dest / rel).read_bytes(), (self.src / rel).read_bytes())
        ver, pins = vendor.read_lock(str(self.lock))
        self.assertEqual((ver, sorted(pins)), ("0.186.1", sorted(vendor.EXAMPLES)))
        self.assertEqual(self.run_vendor("--check")[0], 0)
        code, out, _ = self.run_vendor("--from", str(self.src))       # pinned now: verified, not re-recorded
        self.assertEqual((code, out.count("recorded")), (0, 0))

    def test_mismatches_are_refused_and_nothing_is_copied(self):
        self.assertEqual(self.run_vendor("--from", str(self.src))[0], 0)
        (self.src / vendor.EXAMPLES[0]).write_text("// changed\n", encoding="utf-8")
        before = (self.dest / vendor.EXAMPLES[0]).read_bytes()
        code, _, err = self.run_vendor("--from", str(self.src))
        self.assertEqual(code, 2)
        self.assertIn("differs from the lock", err)
        self.assertEqual((self.dest / vendor.EXAMPLES[0]).read_bytes(), before)
        (self.src / vendor.CORE[0]).write_text("// not three\n", encoding="utf-8")
        self.assertEqual(self.run_vendor("--from", str(self.src))[0], 2)

    def test_wrong_version_or_missing_file(self):
        (self.src / "package.json").write_text('{"version": "0.170.0"}', encoding="utf-8")
        code, _, err = self.run_vendor("--from", str(self.src))
        self.assertEqual(code, 2)
        self.assertIn("not the pinned 0.186.1", err)
        (self.src / "package.json").write_text('{"version": "0.186.1"}', encoding="utf-8")
        os.remove(self.src / vendor.EXAMPLES[-1])
        self.assertEqual(self.run_vendor("--from", str(self.src))[0], 2)
        self.assertFalse(self.dest.exists())

    def test_check_reports_missing_and_tampered_files(self):
        self.assertEqual(self.run_vendor("--check")[0], 2)
        self.run_vendor("--from", str(self.src))
        (self.dest / vendor.CORE[1]).write_text("tampered", encoding="utf-8")
        problems = vendor.verify(str(self.dest), str(self.core), str(self.lock))
        self.assertEqual(problems, [f"{vendor.CORE[1]} does not match its pinned sha256"])

    def test_committed_lock_pins_the_examples_of_the_lab_release(self):
        cver, _ = vendor.read_lock(vendor.CORE_LOCK)
        ever, pins = vendor.read_lock(vendor.EXAMPLES_LOCK)
        self.assertEqual(ever, cver)
        self.assertEqual(sorted(pins), sorted(vendor.EXAMPLES))
        for h in pins.values():
            self.assertRegex(h, r"^[0-9a-f]{64}$")


class TestReviewCli(TmpDirCase, unittest.TestCase):
    def test_up_dry_run_prints_the_compose_command(self):
        code, out, err = run_main(review.main, ["up", "--no-ngrok", "--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertIn("docker compose -f tools/review/docker-compose.yml up -d --build", out.replace("\\", "/"))
        self.assertNotIn("ngrok http", out)
        code, out, _ = run_main(review.main, ["up", "--dry-run"])
        self.assertIn("ngrok http 127.0.0.1:8790", out)
        code, out, _ = run_main(review.main, ["down", "--dry-run"])
        self.assertIn("docker compose -f tools/review/docker-compose.yml down", out.replace("\\", "/"))

    def test_up_refuses_without_vendor_files(self):
        with mock.patch.object(review.vendor_three, "verify", lambda *a, **k: ["missing build/three.module.js"]), \
                mock.patch.object(review.subprocess, "run", side_effect=AssertionError("docker must not run")):
            code, _, err = run_main(review.main, ["up", "--no-ngrok"])
        self.assertEqual(code, 2)
        self.assertIn("vendor_three.py --from", err)

    def test_public_url_from_the_ngrok_api(self):
        tunnels = {"tunnels": [
            {"public_url": "https://other.ngrok.app", "config": {"addr": "http://localhost:3000"}},
            {"public_url": "http://abc.ngrok.app", "config": {"addr": "http://127.0.0.1:8790"}},
            {"public_url": "https://abc.ngrok.app", "config": {"addr": "http://127.0.0.1:8790"}}]}
        self.assertEqual(review.public_url(tunnels), "https://abc.ngrok.app")
        self.assertIsNone(review.public_url({"tunnels": []}))
        self.assertNotIn("ngrok.yml", (REPO / "tools" / "review" / "review.py").read_text(encoding="utf-8")
                         .split('"""', 2)[2], "never reads ngrok's config")

    def test_mp4_duration_and_glb_stats(self):
        mvhd = struct.pack(">I4sB3sIIII", 108, b"mvhd", 0, b"\0\0\0", 0, 0, 1000, 5167) + b"\0" * 80
        moov = struct.pack(">I4s", 8 + len(mvhd), b"moov") + mvhd
        mp4 = self.tmp / "c.mp4"
        mp4.write_bytes(struct.pack(">I4s4sI", 16, b"ftyp", b"isom", 0) + moov)
        self.assertEqual(review.mp4_duration(str(mp4)), 5.167)
        gltf = {"accessors": [{"count": 30}, {"count": 90}], "meshes": [{"primitives": [
            {"attributes": {"POSITION": 0}, "indices": 1}]}], "materials": [{}], "animations": []}
        js = json.dumps(gltf).encode()
        js += b" " * (-len(js) % 4)
        glb = self.tmp / "m.glb"
        glb.write_bytes(struct.pack("<4sII", b"glTF", 2, 20 + len(js)) + struct.pack("<I4s", len(js), b"JSON") + js)
        self.assertEqual(review.glb_stats(str(glb)), {"verts": 30, "tris": 30, "meshes": 1, "materials": 1,
                                                      "animations": 0})

    def test_publish_commands(self):
        fake = FakeIngest()
        self.addCleanup(fake.stop)
        mp4 = self.tmp / "clip.mp4"
        mp4.write_bytes(b"x")
        env = {"FILM_REVIEW_URL": fake.url, "FILM_REVIEW_MEDIA": str(self.tmp / "media")}
        with mock.patch.dict(os.environ, env):
            code, out, err = run_main(review.main, ["publish-video", str(mp4), "--build", "clip1", "--label", "H3"])
            self.assertEqual(code, 0, err)
            self.assertEqual(fake.types(), ["build", "render", "done"])
            self.assertEqual(fake.events[1]["video"], "clip1/clip.mp4")
            self.assertEqual(run_main(review.main, ["publish-video", str(mp4), "--build", "../x", "--label", "y"])[0], 2)
            self.assertEqual(run_main(review.main, ["publish-model", str(self.tmp / "no.glb"), "--build", "m"])[0], 2)
        with mock.patch.dict(os.environ, dict(env, FILM_REVIEW_URL=f"http://127.0.0.1:{free_port()}")):
            code, _, err = run_main(review.main, ["publish-video", str(mp4), "--build", "clip1", "--label", "H3"])
        self.assertEqual(code, 1)
        self.assertIn("not delivered", err)


class TestContainerFiles(unittest.TestCase):
    def test_compose_publishes_on_localhost_only(self):
        text = (REPO / "tools" / "review" / "docker-compose.yml").read_text(encoding="utf-8")
        ports = re.findall(r'^\s*-\s*"([^"]+:\d+:\d+)"', text, re.M)
        self.assertEqual(sorted(ports), ["127.0.0.1:8790:8790", "127.0.0.1:8791:8791"])
        self.assertIn("film-lab-review:", text)
        self.assertIn("restart: unless-stopped", text)
        self.assertRegex(text, r"- review-db:/data\b")
        self.assertRegex(text, r"out/_review/media:/media:ro")
        self.assertRegex(text, r"(?m)^volumes:\n\s+review-db:")

    def test_dockerfile(self):
        text = (REPO / "tools" / "review" / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^FROM python:3\.13-alpine$")
        self.assertRegex(text, r"(?m)^USER review$")
        self.assertIn("HEALTHCHECK", text)
        self.assertNotRegex(text, r"pip |npm |apk add|curl |wget ")

    def test_server_and_client_are_stdlib_only(self):
        stdlib = set(sys.stdlib_module_names)
        for name in ("server.py", "client.py", "review.py", "vendor_three.py", "monitor.py"):
            src = (REPO / "tools" / "review" / name).read_text(encoding="utf-8")
            mods = {m.split(".")[0] for m in re.findall(r"^\s*(?:import|from) ([\w.]+)", src, re.M)}
            self.assertLessEqual(mods - stdlib - {"client", "vendor_three"}, set(), name)


# ------------------------------------------------------------------ hooks of blender.py and comfy.py
import test_blender as tb  # noqa: E402  (the fake Blender of the blender tests)


class TestBlenderHook(tb.FakeBlenderCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeIngest()
        self.addCleanup(self.fake.stop)
        self.renv = mock.patch.dict(os.environ, {"FILM_REVIEW_URL": self.fake.url,
                                                 "FILM_REVIEW_MEDIA": str(self.tmp / "media")})
        self.renv.start()
        self.addCleanup(self.renv.stop)
        os.environ.pop("FILM_REVIEW_BUILD", None)

    def test_render_publishes_job_and_render(self):
        out = self.tmp / "r1"
        code, so, se = self.run_cli("render", self.spec_path, "--out", out, "--review", "shot-a")
        self.assertEqual(code, 0, se)
        types = self.fake.types()
        self.assertEqual(types[0], "build")
        self.assertEqual(self.fake.events[0]["status"], "rendering")
        self.assertEqual(types[-3:], ["job", "render", "done"])
        jobs = self.fake.of("job")
        self.assertEqual((jobs[0]["status"], jobs[0]["tool"], jobs[-1]["status"]), ("running", "blender", "done"))
        r = self.fake.of("render")[0]
        self.assertEqual(r["video"], "shot-a/beauty.mp4")              # Blender's own encoder (no ffmpeg)
        self.assertEqual(r["image"], "shot-a/0001.png")
        self.assertTrue((self.tmp / "media" / "shot-a" / "beauty.mp4").is_file())

    def test_env_and_progress(self):
        with mock.patch.dict(os.environ, {"FILM_REVIEW_BUILD": "envb"}), mock.patch.object(tb.bl, "review_hook") as rh:
            hook = mock.MagicMock()
            rh.return_value = hook
            code, _, se = self.run_cli("render", self.spec_path, "--out", self.tmp / "r2")
        self.assertEqual(code, 0, se)
        msgs = [c.args for c in hook.update.call_args_list]
        self.assertTrue(msgs, "each frame line reaches the hook")
        self.assertEqual(msgs[-1][0], 1.0)
        self.assertRegex(msgs[0][1], r"^frame \d+ · 1/\d+$")
        hook.finish.assert_called_once()

    def test_review_from_env_without_flag(self):
        with mock.patch.dict(os.environ, {"FILM_REVIEW_BUILD": "envb"}):
            code, _, se = self.run_cli("turntable", "preset:giot", "--out", self.tmp / "tt")
        self.assertEqual(code, 0, se)
        self.assertEqual(self.fake.events[0]["build"], "envb")
        self.assertIn("render", self.fake.types())

    def test_keyframes_publish_first_and_last(self):
        code, _, se = self.run_cli("keyframes", self.spec_path, "--out", self.tmp / "kf", "--review", "kf")
        self.assertEqual(code, 0, se)
        self.assertEqual([r["image"] for r in self.fake.of("render")], ["kf/first.png", "kf/last.png"])

    def test_failure_is_published(self):
        os.environ["FAKE_BLENDER_FAIL"] = "early"
        code, _, _ = self.run_cli("render", self.spec_path, "--out", self.tmp / "bad", "--review", "shot-b")
        self.assertEqual(code, 1)
        self.assertEqual(self.fake.types()[-1], "fail")
        self.assertEqual(self.fake.of("job")[-1]["status"], "failed")

    def test_no_review_no_events_and_dry_run_is_silent(self):
        self.assertEqual(self.run_cli("render", self.spec_path, "--out", self.tmp / "r3")[0], 0)
        self.assertEqual(self.run_cli("render", self.spec_path, "--out", self.tmp / "r4", "--dry-run",
                                      "--review", "x")[0], 0)
        self.assertEqual(self.fake.events, [])

    def test_offline_review_does_not_change_the_render(self):
        os.environ["FILM_REVIEW_URL"] = f"http://127.0.0.1:{free_port()}"
        code, _, se = self.run_cli("render", self.spec_path, "--out", self.tmp / "r5", "--review", "off-b")
        self.assertEqual(code, 0, se)
        self.assertTrue((self.tmp / "r5" / "render.json").is_file())


try:
    import test_comfy as tc  # noqa: E402  (needs Pillow, like the comfy tests)
except ImportError:
    tc = None


@unittest.skipIf(tc is None, "Pillow is missing (tests/test_comfy.py)")
class TestComfyHook(tc.ComfyCase if tc else unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeIngest()
        self.addCleanup(self.fake.stop)
        os.environ["FILM_REVIEW_URL"] = self.fake.url
        os.environ["FILM_REVIEW_MEDIA"] = str(self.tmp / "media")

    def test_run_publishes_job_and_clip(self):
        self.server()
        code, so, se = self.run_clip(tc.I2V, "--review", "clip-a")
        self.assertEqual(code, 0, se)
        self.assertEqual(self.fake.types()[0], "build")
        self.assertEqual(self.fake.events[0]["kind"], "clip")
        self.assertEqual(self.fake.types()[-3:], ["job", "render", "done"])
        r = self.fake.of("render")[0]
        self.assertEqual((r["video"], r["engine"], r["frames"]), ("clip-a/ep01_s03_clip_v01.mp4", "comfy:h3-i2v", 124))
        self.assertEqual((self.tmp / "media" / "clip-a" / "ep01_s03_clip_v01.mp4").read_bytes(), tc.MP4)
        self.assertEqual(self.fake.of("job")[-1]["status"], "done")
        self.assertRegex(self.fake.of("job")[0]["job"], r"^comfy-[0-9a-f-]{36}$")   # monitor.py links prompt -> build

    def test_error_is_published_and_env_works(self):
        f = self.server()
        f.mode = "error"
        os.environ["FILM_REVIEW_BUILD"] = "clip-b"
        code, _, _ = self.run_clip(tc.I2V)
        self.assertEqual(code, 1)
        self.assertEqual(self.fake.types()[-1], "fail")
        self.assertIn("CUDA out of memory", self.fake.of("fail")[0]["message"])

    def test_dry_run_publishes_nothing(self):
        code, _, se = self.run_clip(tc.I2V, "--dry-run", "--review", "clip-c")
        self.assertEqual(code, 0, se)
        self.assertEqual(self.fake.events, [])


if __name__ == "__main__":
    unittest.main()
