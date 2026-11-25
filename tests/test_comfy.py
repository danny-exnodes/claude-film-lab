"""tools/comfy/comfy.py: the local ComfyUI video engine (MiniMax H3). A fake ComfyUI HTTP server runs in a thread;
nothing reaches a real server, a GPU or the network."""
import csv, hashlib, io, json, os, re, socket, subprocess, sys, threading, time, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from PIL import Image

from helpers import REPO, TmpDirCase, load, run_main

comfy = load("comfy/comfy.py", "film_comfy")
ark = comfy.ark
I2V, R2V = "h3-i2v", "h3-r2v"
MP4 = b"\x00\x00\x00\x18ftypmp42fake-clip-with-audio"
LOCK = json.loads((REPO / "tools" / "comfy" / "comfy.lock.json").read_text(encoding="utf-8"))
PAID = ("MinimaxTextToVideoNode", "MinimaxImageToVideoNode", "MinimaxSubjectToVideoNode", "MinimaxHailuoVideoNode",
        "MinimaxHailuo03TextToVideoNode", "MinimaxHailuo03FirstLastFrameNode", "MinimaxHailuo03ReferenceNode")


class FakeComfy:
    """Stands in for ComfyUI: /system_stats, /object_info/<class>, /upload/image, /prompt, /history/<id>, /view,
    /queue, /interrupt. `mode` decides the job's fate: success | error | interrupted | never."""

    def __init__(self):
        self.mode, self.polls_until_done, self.offline = "success", 2, True
        self.missing_classes, self.models = set(), {m["file"] for m in LOCK["models"]}
        self.prompt_status, self.prompt_error = 200, None
        self.calls, self.uploads, self.prompts, self.interrupts, self.deletes = [], {}, [], [], []
        self.polls = {}
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send_json(self, obj, code=200):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n) if n else b""

            def do_GET(self):
                fake.calls.append(("GET", self.path))
                u = urlparse(self.path)
                if u.path == "/system_stats":
                    argv = ["main.py", "--listen", "127.0.0.1"] + (["--offline"] if fake.offline else [])
                    return self.send_json({"system": {"comfyui_version": "0.43.1", "python_version": "3.13.12 (x)",
                                                      "pytorch_version": "2.12.1+cu130", "argv": argv,
                                                      "ram_total": 2**37, "ram_free": 2**36},
                                           "devices": [{"name": "cuda:0 NVIDIA GeForce RTX 5070 Ti",
                                                        "vram_total": 16 * 2**30, "vram_free": 15 * 2**30}]})
                if u.path.startswith("/object_info/"):
                    cls = u.path.rsplit("/", 1)[1]
                    if cls in fake.missing_classes:
                        return self.send_json({})
                    spec = {}
                    if cls in comfy.MODEL_INPUTS:
                        spec[comfy.MODEL_INPUTS[cls]] = [sorted(fake.models), {}]
                    if cls == "VAELoader":        # V3-style combo on one loader, to cover both shapes
                        spec["vae_name"] = ["COMBO", {"options": sorted(fake.models)}]
                    return self.send_json({cls: {"input": {"required": spec}}})
                if u.path.startswith("/history/"):
                    pid = u.path.rsplit("/", 1)[1]
                    fake.polls[pid] = fake.polls.get(pid, 0) + 1
                    if fake.mode == "never" or fake.polls[pid] < fake.polls_until_done:
                        return self.send_json({})
                    return self.send_json({pid: fake.history(pid)})
                if u.path == "/queue":
                    running = [[1, p["prompt_id"], {}, {}, []] for p in fake.prompts]
                    return self.send_json({"queue_running": running, "queue_pending": []})
                if u.path == "/view":
                    q = parse_qs(u.query)
                    fake.view = q
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(MP4)))
                    self.end_headers()
                    return self.wfile.write(MP4)
                self.send_json({"error": "not found"}, 404)

            def do_POST(self):
                fake.calls.append(("POST", self.path))
                raw = self.body()
                if self.path == "/upload/image":
                    m = re.search(rb'name="image"; filename="([^"]+)"\r\nContent-Type: [^\r]+\r\n\r\n', raw)
                    name = m.group(1).decode()
                    end = raw.rfind(b"\r\n--")
                    fake.uploads[name] = raw[m.end():end]
                    return self.send_json({"name": name, "subfolder": "", "type": "input"})
                data = json.loads(raw or b"{}")
                if self.path == "/prompt":
                    fake.prompts.append(data)
                    if fake.prompt_status != 200:
                        return self.send_json(fake.prompt_error, fake.prompt_status)
                    return self.send_json({"prompt_id": data["prompt_id"], "number": 1, "node_errors": {}})
                if self.path == "/interrupt":
                    fake.interrupts.append(data)
                    return self.send_json({})
                if self.path == "/queue":
                    fake.deletes.append(data)
                    return self.send_json({})
                self.send_json({"error": "not found"}, 404)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def history(self, pid):
        start = ["execution_start", {"prompt_id": pid, "timestamp": 1000}]
        if self.mode == "success":
            return {"outputs": {"17": {"images": [{"filename": "h3_00001_.mp4", "subfolder": "film-lab",
                                                   "type": "output"}], "animated": [True]}},
                    "status": {"status_str": "success", "completed": True,
                               "messages": [start, ["execution_success", {"prompt_id": pid, "timestamp": 13500}]]}}
        if self.mode == "error":
            return {"outputs": {}, "status": {"status_str": "error", "completed": False, "messages": [
                start, ["execution_error", {"prompt_id": pid, "node_id": "13", "node_type": "SamplerCustomAdvanced",
                                            "exception_message": "CUDA out of memory", "timestamp": 2000}]]}}
        return {"outputs": {}, "status": {"status_str": "error", "completed": False, "messages": [
            start, ["execution_interrupted", {"prompt_id": pid, "timestamp": 3000}]]}}

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class ComfyCase(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("FILM_", "LOCALAPPDATA", "APPDATA"))}
        env["FILM_AGENT"] = "film-animator"
        env["FILM_COMFY_URL"] = "http://127.0.0.1:9"          # closed port unless a test starts the fake server
        env["FILM_COMFY_MODELS"] = str(self.tmp / "models")
        env["FILM_COMFY_WORK"] = str(self.tmp / "comfy-work")   # `start` never writes into the lab's out/
        self._env = mock.patch.dict(os.environ, env, clear=True)
        self._env.start()
        for name, val in (("POLL_SECONDS", 0.01), ("PROGRESS_SECONDS", 0), ("START_POLL", 0.1)):
            p = mock.patch.object(comfy, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.ledger = str(self.tmp / "ledger.csv")
        self.start = self.image("start.png", (1920, 1080), (200, 30, 30))
        self.end = self.image("end.jpg", (1600, 1200), (30, 30, 200))
        self.out = str(self.tmp / "clips" / "ep01_s03_clip_v01.mp4")

    def tearDown(self):
        mock.patch.stopall()
        self._env.stop()
        super().tearDown()

    def image(self, name, size, color, fmt=None):
        path = self.tmp / name
        Image.new("RGB", size, color).save(path, fmt)
        return str(path)

    def server(self):
        f = FakeComfy()
        self.addCleanup(f.stop)
        os.environ["FILM_COMFY_URL"] = f.url
        return f

    def run_comfy(self, *argv):
        return run_main(comfy.main, list(argv))

    def run_clip(self, wid=I2V, *extra, ledger=True):
        args = ["run", wid, "--prompt", "a dragon flies over ink mountains", "--seed", "7", "--out", self.out]
        if wid == I2V and "--no-image" not in extra:
            args += ["--image", self.start]
        args += [x for x in extra if x != "--no-image"]
        if ledger:
            args += ["--ledger", self.ledger]
        return self.run_comfy(*args)

    def rows(self):
        if not os.path.exists(self.ledger):
            return []
        with open(self.ledger, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))


class TestPure(ComfyCase):
    def test_frames_snap_up_to_17k_plus_5(self):
        meta = comfy.load_workflow(I2V)[1]
        for sec, frames in ((5, 124), (10, 243), (2, 56), (0.1, 5), (15, 362), (5.2, 141)):
            self.assertEqual(comfy.snap_frames(sec, meta), frames, sec)
            self.assertEqual(comfy.snap_frames(sec, meta) % 17, 5)
        # the template's ComfyMathExpression: max(5, round(a*24)) + (5 - (max(5, round(a*24)) % 17)) % 17
        for sec in (1, 3.3, 7.5, 12):
            n = max(5, round(sec * 24))
            self.assertEqual(comfy.snap_frames(sec, meta), n + (5 - n % 17) % 17)

    def test_crop_box_center(self):
        self.assertEqual(comfy.crop_box(1920, 1080, 1344, 768), (15, 0, 1905, 1080))
        self.assertEqual(comfy.crop_box(1344, 768, 1344, 768), (0, 0, 1344, 768))
        l, t, r, b = comfy.crop_box(1000, 1000, 1344, 768)
        self.assertEqual((l, r, b - t), (0, 1000, 571))

    def test_image_size_stdlib(self):
        for name, fmt in (("a.png", None), ("a.jpg", None), ("a.webp", None), ("b.webp", "WEBP")):
            p = self.image(name, (321, 123), (1, 2, 3), fmt)
            self.assertEqual(comfy.image_size(p), (321, 123), name)
        Image.new("RGBA", (77, 55)).save(self.tmp / "l.webp", lossless=True)
        self.assertEqual(comfy.image_size(str(self.tmp / "l.webp")), (77, 55))
        (self.tmp / "x.txt").write_text("no image")
        self.assertIsNone(comfy.image_size(str(self.tmp / "x.txt")))

    def test_prepare_frame_crops_and_resizes_exactly(self):
        src = self.image("wide.png", (2000, 1000), (0, 0, 0))
        im = Image.open(src)
        im.paste((255, 255, 255), (0, 0, 100, 1000))      # a white band that the 7:4 crop removes
        im.save(src)
        before = hashlib.sha256(Path(src).read_bytes()).hexdigest()
        dst = str(self.tmp / "prep.png")
        comfy.prepare_frame(src, 864, 480, dst)
        with Image.open(dst) as out:
            self.assertEqual(out.size, (864, 480))
            self.assertLess(out.getpixel((0, 240))[0], 10)
        self.assertEqual(hashlib.sha256(Path(src).read_bytes()).hexdigest(), before)

    def test_allow_list_is_exactly_the_graph_classes(self):
        classes = set()
        for wid in comfy.workflow_ids():
            classes |= comfy.graph_classes(comfy.load_workflow(wid)[0])
        self.assertEqual(sorted(comfy.workflow_ids()), [I2V, R2V])
        self.assertEqual(comfy.ALLOWED_NODES, classes | {"LoadImage", "MiniMaxH3AddGuide"})
        for cls in PAID:
            self.assertNotIn(cls, comfy.ALLOWED_NODES)
        self.assertFalse([c for c in comfy.ALLOWED_NODES if c.startswith("Minimax")])

    def test_every_variant_is_a_closed_graph(self):
        for wid in comfy.workflow_ids():
            graph, meta, _ = comfy.load_workflow(wid)
            for node, inp in (x for v in meta["params"].values() for x in v):
                self.assertIn(inp, graph[node]["inputs"], f"{wid} {node}.{inp}")
            self.assertEqual(meta["output"]["node"] in graph, True)
            for turbo in (False, True):
                for img in ([None, None], ["s.png", None], ["s.png", "e.png"]) if wid == I2V else ([None, None],):
                    v = {"turbo": turbo, "image": img[0], "last": img[1], "refs": ["r.png"] if wid == R2V else [],
                         "guides": [(12, "g.png"), (60, "h.png")] if wid == R2V else []}
                    g = comfy.build_graph(graph, meta, v)
                    self.assertEqual(comfy.dangling(g), [], (wid, v))
                    self.assertEqual(comfy.disallowed(g), [], (wid, v))
                    model_src = g["11"]["inputs"]["model"]
                    self.assertEqual(model_src, ["2", 0] if turbo else ["1", 0])
                    self.assertEqual(g["12"]["inputs"]["model"], model_src)
                    self.assertNotIn("negative", json.dumps(g))
                    if wid == I2V:
                        self.assertEqual("first_frame" in g["8"]["inputs"], bool(img[0]))
                        self.assertEqual("last_frame" in g["8"]["inputs"], bool(img[1]))

    def test_r2v_refs_and_guide_chain(self):
        graph, meta, _ = comfy.load_workflow(R2V)
        g = comfy.build_graph(graph, meta, {"refs": ["a.png", "b.png"], "guides": [(36, "g1.png"), (100, "g2.png")]})
        self.assertEqual(g["8"]["inputs"]["ref_images.ref_image_0"], ["100", 0])
        self.assertEqual(g["8"]["inputs"]["ref_images.ref_image_1"], ["101", 0])
        self.assertEqual(g["101"]["inputs"]["image"], "b.png")
        self.assertEqual(g["201"]["inputs"]["positive"], ["8", 0])
        self.assertEqual(g["201"]["inputs"]["frame_idx"], 36)
        self.assertEqual(g["203"]["inputs"]["positive"], ["201", 0])
        self.assertEqual(g["203"]["inputs"]["latent"], ["8", 1])
        self.assertEqual(g["12"]["inputs"]["conditioning"], ["203", 0])
        g0 = comfy.build_graph(graph, meta, {"refs": ["a.png"]})
        self.assertEqual(g0["12"]["inputs"]["conditioning"], ["8", 0])

    def test_lock_and_graph_models(self):
        lock = comfy.load_lock()
        self.assertEqual(lock["custom_nodes"], [])
        self.assertEqual({m["set"] for m in lock["models"]}, {"minimax-h3"})
        self.assertFalse(any("wan" in m["file"].lower() for m in lock["models"]))
        for wid in comfy.workflow_ids():
            graph = comfy.load_workflow(wid)[0]
            for _, cls, inp, entry, f in comfy.model_entries(graph, lock):
                self.assertIsNotNone(entry, f)
                self.assertIn(wid, entry["workflows"])
        unet = {w: comfy.load_workflow(w)[0]["1"]["inputs"]["unet_name"] for w in (I2V, R2V)}
        self.assertEqual(unet, {I2V: "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                                R2V: "minimax_h3_ref2va_pruned_int8_convrot.safetensors"})
        self.assertEqual(comfy.load_workflow(I2V)[0]["3"]["inputs"]["type"], "minimax")

    def test_canvas_sizes_fit_the_nodes(self):
        for wid in comfy.workflow_ids():
            meta = comfy.load_workflow(wid)[1]
            self.assertEqual(meta["res"], {"480p": [864, 480], "768p": [1344, 768]})
            for w, h in meta["res"].values():
                self.assertEqual((w % meta["size_multiple"], h % meta["size_multiple"]), (0, 0))
            self.assertEqual((meta["fps"], meta["defaults"]["steps"], meta["negative"]), (24, 20, False))

    def test_lock_parsing_refusals(self):
        for bad, msg in (({"models": "x"}, "'models' list"),
                         ({"models": [{"set": "s", "folder": "vae"}]}, r"models\[0\]\.file"),
                         ({"models": [{"set": "s", "folder": "vae", "file": "f", "sha256": "ABC"}]}, "64 lowercase"),
                         ({"models": [{"set": "s", "folder": "vae", "file": "f", "size": -1}]}, "size must be")):
            path = self.tmp / "bad.json"
            path.write_text(json.dumps(bad))
            code, _, err = self.run_comfy("models", "--lock", str(path))
            self.assertEqual(code, 2, bad)
            self.assertRegex(err, msg)
        (self.tmp / "bad.json").write_text("{not json")
        self.assertEqual(self.run_comfy("models", "--lock", str(self.tmp / "bad.json"))[0], 2)

    def test_prompt_file_assembly(self):
        pf = self.tmp / "p.json"
        pf.write_text(json.dumps({"integrated_multimodal_description": "Rồng bay.", "overall_soundscape": "gió",
                                  "non_diegetic_music": "đàn tranh"}), encoding="utf-8")
        text = comfy.read_prompt_file(str(pf), "i2v")
        self.assertEqual(text, "integrated_multimodal_description:\nRồng bay.\n\noverall_soundscape:\ngió\n\n"
                               "non_diegetic_music:\nđàn tranh")
        a = mock.Mock(prompt_file=str(pf), prompt=None)
        full = comfy.assemble_prompt(a, {"prompt_format": "i2v"}, True)
        self.assertTrue(full.startswith(comfy.I2V_HEADER + "\n\nintegrated_multimodal_description:\n"))
        self.assertEqual(comfy.assemble_prompt(a, {"prompt_format": "i2v"}, False), text)    # text-to-video
        a = mock.Mock(prompt_file=None, prompt=comfy.I2V_HEADER + "\n\nalready there")
        self.assertEqual(comfy.assemble_prompt(a, {"prompt_format": "i2v"}, True).count("For the target video"), 1)


class TestRefusals(ComfyCase):
    def assert_refused(self, *argv, msg, server=None, out_exists=False):
        code, out, err = self.run_comfy(*argv)
        self.assertEqual(code, 2, out + err)
        self.assertRegex(err, msg)
        self.assertFalse(os.path.exists(self.ledger), "a refusal writes no ledger row")
        self.assertEqual(os.path.exists(self.out), out_exists)
        if server:
            self.assertFalse([c for c in server.calls if c[0] == "POST"], "a refusal uploads/queues nothing")
        return err

    def base(self, wid=I2V, image=True):
        return ["run", wid, "--prompt", "x", "--out", self.out, "--ledger", self.ledger] + (
            ["--image", self.start] if image and wid == I2V else [])

    def test_local_refusals(self):
        f = self.server()
        r2v = ["run", R2V, "--prompt", "x", "--out", self.out, "--ledger", self.ledger, "--ref", self.start]
        cases = [
            (["run", "wan22-i2v", "--prompt", "x", "--out", self.out, "--ledger", self.ledger], "unknown workflow"),
            (self.base() + ["--negative", "blurry"], "CFG-distilled"),
            (["run", I2V, "--prompt", "x", "--out", self.out, "--ledger", self.ledger, "--last", self.end],
             "--last needs --image"),
            (r2v + ["--last", self.end], "no end-frame input"),
            (r2v + ["--image", self.start], "takes no --image"),
            (self.base() + ["--ref", self.start], "takes no --ref"),
            (self.base() + ["--guide", f"1={self.start}"], "takes no --guide"),
            (["run", R2V, "--prompt", "x", "--out", self.out, "--ledger", self.ledger], "needs 1..9 --ref"),
            (["run", R2V, "--prompt", "x", "--out", self.out, "--ledger", self.ledger]
             + [x for _ in range(10) for x in ("--ref", self.start)], "needs 1..9 --ref"),
            (r2v + ["--guide", f"6={self.start}"], "outside the clip"),
            (r2v + ["--guide", "1.5"], "SECONDS=IMAGE"),
            (self.base() + ["--seconds", "16"], "362"),
            (self.base() + ["--res", "1080p"], "--res 1080p"),
            (["run", I2V, "--prompt", "x", "--out", self.out, "--ledger", self.ledger, "--image", "nope.png"],
             "no such file"),
            (self.base()[:-2] + ["--image", str(self.tmp / "ledger-not-image.txt")], "no such file"),
            (self.base() + ["--prompt-file", "p.json"], "exactly one of --prompt"),
            (["run", I2V, "--out", self.out, "--ledger", self.ledger], "exactly one of --prompt"),
            (["run", I2V, "--prompt", "x", "--out", str(self.tmp / "a.mov"), "--ledger", self.ledger], "mp4"),
            (["run", I2V, "--prompt", "x", "--out", self.out], "needs --ledger"),
            (["run", I2V, "--prompt", "x", "--out", self.out, "--no-ledger"], "FILM_AGENT"),
        ]
        for argv, msg in cases:
            with self.subTest(msg=msg):
                self.assert_refused(*argv, msg=msg, server=f)
        notimg = self.tmp / "text.png"
        notimg.write_text("not an image")
        self.assert_refused(*self.base()[:-2], "--image", str(notimg), msg="not a PNG/JPEG/WEBP", server=f)

    def test_output_exists_suggests_next_version(self):
        os.makedirs(os.path.dirname(self.out))
        Path(self.out).write_bytes(b"old")
        self.assert_refused(*self.base(), msg=r"next free: .*_v02\.mp4", out_exists=True)
        self.assertEqual(Path(self.out).read_bytes(), b"old")
        os.remove(self.out)
        Path(self.out + ".json").write_text("{}")
        self.assert_refused(*self.base(), msg="sidecar exists")

    def test_prompt_file_problems(self):
        pf = self.tmp / "p.json"
        pf.write_text(json.dumps({"summary": "x", "overall_soundscape": "y"}))
        err = self.assert_refused("run", I2V, "--prompt-file", str(pf), "--image", self.start, "--out", self.out,
                                  "--ledger", self.ledger, msg="unknown field")
        self.assertIn("missing or empty field(s) integrated_multimodal_description", err)

    def test_bad_ledger_header(self):
        Path(self.ledger).write_text("a,b,c\n1,2,3\n")
        code, _, err = self.run_comfy(*self.base())
        self.assertEqual(code, 2)
        self.assertIn("ledger header mismatch", err)

    def test_disallowed_node_class(self):
        wf = self.tmp / "wf"
        wf.mkdir()
        g = json.loads((REPO / "tools/comfy/workflows/h3-i2v.json").read_text())
        g["99"] = {"class_type": "MinimaxHailuo03FirstLastFrameNode", "inputs": {}}
        (wf / "evil.json").write_text(json.dumps(g))
        (wf / "evil.meta.json").write_text((REPO / "tools/comfy/workflows/h3-i2v.meta.json").read_text())
        (wf / "ui.json").write_text(json.dumps({"nodes": [], "links": []}))
        (wf / "ui.meta.json").write_text("{}")
        with mock.patch.object(comfy, "WORKFLOWS", str(wf)):
            self.assert_refused("run", "evil", "--prompt", "x", "--out", self.out, "--ledger", self.ledger,
                                msg="outside the allow list: MinimaxHailuo03FirstLastFrameNode")
            self.assert_refused("run", "ui", "--prompt", "x", "--out", self.out, "--ledger", self.ledger,
                                msg="not a ComfyUI API-format graph")

    def test_server_down_is_a_refusal(self):
        self.assert_refused(*self.base(), msg="not reachable")

    def test_server_without_model_or_node(self):
        f = self.server()
        f.models.discard("minimax_h3_fl2va_pruned_int8_convrot.safetensors")
        err = self.assert_refused(*self.base(), msg="cannot run this graph", server=f)
        self.assertIn("minimax_h3_fl2va_pruned_int8_convrot.safetensors", err)
        f.models.add("minimax_h3_fl2va_pruned_int8_convrot.safetensors")
        f.models.discard("minimax_h3_video_vae_int8_convrot.safetensors")     # the V3 COMBO shape
        self.assert_refused(*self.base(), msg="minimax_h3_video_vae_int8_convrot", server=f)
        f.models.add("minimax_h3_video_vae_int8_convrot.safetensors")
        f.missing_classes.add("MiniMaxH3ImageToVideo")
        self.assert_refused(*self.base(), msg="node MiniMaxH3ImageToVideo is not installed", server=f)
        self.assertEqual(f.uploads, {})

    def test_turbo_lora_missing_only_matters_with_turbo(self):
        f = self.server()
        f.models.discard("minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors")
        self.assert_refused(*self.base(), "--turbo", msg="turbo_8step", server=f)
        self.assertEqual(self.run_clip()[0], 0)


class TestDryRun(ComfyCase):
    def test_dry_run_prints_plan_and_sends_nothing(self):
        f = self.server()
        code, out, err = self.run_clip(I2V, "--last", self.end, "--seconds", "10", "--res", "480p", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual(f.calls, [])
        self.assertFalse(os.path.exists(self.ledger))
        self.assertIn("864x480 (480p) · 243 frames = 10.125 s at 24 fps · steps 20 · seed 7", out)
        self.assertIn("1920x1080 -> center crop 1920x1067 -> 864x480 lanczos", out)
        self.assertIn("1600x1200 -> center crop 1600x889 -> 864x480 lanczos", out)
        self.assertIn(comfy.I2V_HEADER, out)
        self.assertIn("dry-run: nothing uploaded or queued", out)

    def test_dry_run_r2v_turbo(self):
        code, out, err = self.run_comfy("run", R2V, "--ref", self.start, "--ref", self.end, "--guide",
                                        f"2.5={self.end}", "--turbo", "--prompt", "x", "--out", self.out,
                                        "--ledger", self.ledger, "--dry-run", "--seed", "1")
        self.assertEqual(code, 0, err)
        self.assertIn("steps 4 (turbo LoRA)", out)
        self.assertIn("<Picture 2>", out)
        self.assertIn("guide frame 60 (2.50 s)", out)
        self.assertIn("minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors", out)
        self.assertIn("Drafts only", err)

    def test_dry_run_warns_about_models_missing_on_disk(self):
        code, _, err = self.run_clip(I2V, "--dry-run")
        self.assertEqual(code, 0)
        os.makedirs(self.tmp / "models")
        code, _, err = self.run_clip(I2V, "--dry-run")
        self.assertIn("model file not found", err)


class TestRun(ComfyCase):
    def test_happy_path_i2v_first_last(self):
        f = self.server()
        before = hashlib.sha256(Path(self.start).read_bytes()).hexdigest()
        code, out, err = self.run_clip(I2V, "--last", self.end)
        self.assertEqual(code, 0, err)
        self.assertEqual(Path(self.out).read_bytes(), MP4)
        self.assertEqual(f.view["filename"], ["h3_00001_.mp4"])
        self.assertEqual(f.view["subfolder"], ["film-lab"])
        # uploads: exact canvas, PNG, source untouched
        self.assertEqual(len(f.uploads), 2)
        for name, data in f.uploads.items():
            self.assertRegex(name, r"^film-lab_[0-9a-f]{12}_(image|last)\.png$")
            with Image.open(io.BytesIO(data)) as im:
                self.assertEqual((im.format, im.size), ("PNG", (1344, 768)))
        self.assertEqual(hashlib.sha256(Path(self.start).read_bytes()).hexdigest(), before)
        # the graph sent
        sent = f.prompts[0]
        g = sent["prompt"]
        self.assertRegex(sent["prompt_id"], r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
        self.assertEqual((g["8"]["inputs"]["width"], g["8"]["inputs"]["height"], g["8"]["inputs"]["length"]),
                         (1344, 768, 124))
        self.assertEqual(g["9"]["inputs"]["noise_seed"], 7)
        self.assertEqual(g["11"]["inputs"]["steps"], 20)
        self.assertEqual(g["16"]["inputs"]["fps"], 24.0)
        self.assertNotIn("2", g)
        self.assertTrue(g["8"]["inputs"]["prompt"].startswith(comfy.I2V_HEADER + "\n\n"))
        self.assertEqual(g["6"]["inputs"]["image"], [n for n in f.uploads if n.endswith("_image.png")][0])
        self.assertEqual(comfy.disallowed(g), [])
        # ledger: pending + ok, same req, prompt id known before the POST
        rows = self.rows()
        self.assertEqual([r["status"] for r in rows], ["pending", "ok"])
        for r in rows:
            self.assertEqual((r["kind"], r["model"], r["size"], r["seconds"], r["out"], r["agent"]),
                             ("video", "comfy:h3-i2v", "1344x768", "5.167", self.out, "film-animator"))
            self.assertEqual(r["task_id"], sent["prompt_id"])
            self.assertRegex(r["note"], r"^req=[0-9a-f]{32}; seed=7")
        self.assertEqual(ark.req_id(rows[0]), ark.req_id(rows[1]))
        self.assertEqual(rows[1]["usage"], "gpu_s=12.5")
        # sidecar
        side = json.loads(Path(self.out + ".json").read_text(encoding="utf-8"))
        self.assertEqual((side["workflow"], side["seed"], side["frames"], side["fps"], side["gpu_seconds"]),
                         (I2V, 7, 124, 24, 12.5))
        self.assertEqual(side["graph_sha256"], comfy.graph_sha(g))
        self.assertEqual(side["comfyui"]["version"], "0.43.1")
        self.assertTrue(side["comfyui"]["offline"])
        self.assertEqual({m["file"] for m in side["models"]},
                         {"minimax_h3_fl2va_pruned_int8_convrot.safetensors",
                          "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                          "minimax_h3_video_vae_int8_convrot.safetensors", "minimax_h3_audio_vae_fp32.safetensors"})
        self.assertEqual(side["inputs"]["image"]["sha256"], before)
        self.assertIn("saved " + self.out, out)
        self.assertRegex(out, r"step running elapsed \d+s")
        # free: the rows never consume a cap
        budget = {"images": 0, "video_seconds": 0, "models": {"comfy:h3-i2v": 0}, "ledger_required": True}
        req = {"kind": "video", "model": "dreamina-seedance-2-5-260628", "seconds": 0}
        self.assertEqual(ark.budget_check(budget, rows, req), [])

    def test_r2v_with_guides_and_prompt_file(self):
        f = self.server()
        pf = self.tmp / "p.yaml"
        pf.write_text("".join(f"{k}: text for {k}\n" for k in comfy.PROMPT_FIELDS["r2v"]), encoding="utf-8")
        code, out, err = self.run_comfy("run", R2V, "--ref", self.start, "--ref", self.end, "--guide",
                                        f"0={self.start}", "--guide", f"3:{self.end}", "--prompt-file", str(pf),
                                        "--res", "480p", "--seconds", "4", "--ref-size", "max", "--seed", "3",
                                        "--out", self.out, "--ledger", self.ledger)
        self.assertEqual(code, 0, err)
        g = f.prompts[0]["prompt"]
        self.assertEqual(g["8"]["inputs"]["ref_image_size"], "max")
        self.assertEqual(g["8"]["inputs"]["length"], 107)
        self.assertEqual([g["201"]["inputs"]["frame_idx"], g["203"]["inputs"]["frame_idx"]], [0, 72])
        self.assertTrue(g["8"]["inputs"]["prompt"].startswith("subject_definitions:\ntext for subject_definitions"))
        refs = sorted(n for n in f.uploads if "_ref" in n)
        self.assertEqual(len(refs), 2)
        with Image.open(io.BytesIO(f.uploads[refs[1]])) as im:
            self.assertEqual(im.size, (1600, 1200))        # references are uploaded as they are
        guides = sorted(n for n in f.uploads if "_guide" in n)
        with Image.open(io.BytesIO(f.uploads[guides[0]])) as im:
            self.assertEqual(im.size, (864, 480))
        self.assertEqual(self.rows()[-1]["model"], "comfy:h3-r2v")

    def test_text_to_video_and_no_ledger_in_main_session(self):
        del os.environ["FILM_AGENT"]
        f = self.server()
        code, _, err = self.run_clip(I2V, "--no-image", "--no-ledger", ledger=False)
        self.assertEqual(code, 0, err)
        g = f.prompts[0]["prompt"]
        self.assertNotIn("6", g)
        self.assertNotIn("first_frame", g["8"]["inputs"])
        self.assertFalse(g["8"]["inputs"]["prompt"].startswith("For the target"))
        self.assertFalse(os.path.exists(self.ledger))

    def test_execution_error_is_a_failed_row(self):
        f = self.server()
        f.mode = "error"
        code, _, err = self.run_clip()
        self.assertEqual(code, 1)
        self.assertIn("CUDA out of memory", err)
        self.assertFalse(os.path.exists(self.out))
        self.assertFalse(os.path.exists(self.out + ".json"))
        rows = self.rows()
        self.assertEqual([r["status"] for r in rows], ["pending", "failed"])
        self.assertIn("SamplerCustomAdvanced", rows[-1]["note"])
        self.assertEqual(rows[-1]["usage"], "gpu_s=1")

    def test_prompt_rejected_by_server(self):
        f = self.server()
        f.prompt_status = 400
        f.prompt_error = {"error": {"message": "Prompt outputs failed validation"},
                          "node_errors": {"8": {"errors": [{"message": "Value not in list", "details": "length"}]}}}
        code, _, err = self.run_clip()
        self.assertEqual(code, 1)
        rows = self.rows()
        self.assertEqual([r["status"] for r in rows], ["pending", "failed"])
        self.assertIn("Value not in list", rows[-1]["note"])

    def test_timeout_interrupts_our_prompt(self):
        f = self.server()
        f.mode = "never"
        code, _, err = self.run_clip(I2V, "--timeout", "0.3")
        self.assertEqual(code, 1)
        pid = f.prompts[0]["prompt_id"]
        self.assertEqual(f.interrupts, [{"prompt_id": pid}])
        self.assertEqual(f.deletes, [{"delete": [pid]}])
        rows = self.rows()
        self.assertEqual([r["status"] for r in rows], ["pending", "interrupted"])
        self.assertIn("timeout", rows[-1]["note"])
        self.assertFalse(os.path.exists(self.out))
        # interrupted closes the request: nothing open for status.py / ledger-close
        self.assertEqual([r["status"] for _, r in ark.request_rows(rows)], ["interrupted"])

    def test_interrupted_on_server(self):
        f = self.server()
        f.mode = "interrupted"
        code, _, _ = self.run_clip()
        self.assertEqual(code, 1)
        self.assertEqual(self.rows()[-1]["status"], "interrupted")

    def test_signal_writes_interrupted_row(self):
        f = self.server()
        f.mode = "never"
        real_sleep = time.sleep
        calls = {"n": 0}

        def boom(s):
            calls["n"] += 1
            if calls["n"] == 3:
                raise ark.Interrupted(2)
            real_sleep(0.01)
        with mock.patch.object(comfy.time, "sleep", boom):
            code, _, err = self.run_clip()
        self.assertEqual(code, 130)
        self.assertEqual(self.rows()[-1]["status"], "interrupted")
        self.assertEqual(len(f.interrupts), 1)

    def test_offline_warning(self):
        f = self.server()
        f.offline = False
        code, _, err = self.run_clip()
        self.assertEqual(code, 0)
        self.assertIn("not started with --offline", err)


class TestOtherCommands(ComfyCase):
    def desktop(self, models=True):
        home = self.tmp / "ComfyUI-Installs" / "ComfyUI"
        (home / "ComfyUI" / "comfy").mkdir(parents=True)
        (home / "ComfyUI" / "main.py").write_text("")
        (home / "ComfyUI" / "comfyui_version.py").write_text('__version__ = "0.43.1"\n')
        (home / "ComfyUI" / "comfy" / "cli_args.py").write_text('parser.add_argument("--offline")\n')
        (home / "standalone-env").mkdir()
        (home / "standalone-env" / "python.exe").write_text("")      # base interpreter, no torch: not chosen
        (home / "ComfyUI" / ".venv" / "Scripts").mkdir(parents=True)
        (home / "ComfyUI" / ".venv" / "Scripts" / "python.exe").write_text("")
        os.environ["FILM_COMFY_HOME"] = str(home)
        if models:
            for m in LOCK["models"]:
                d = self.tmp / "models" / m["folder"]
                d.mkdir(parents=True, exist_ok=True)
                with open(d / m["file"], "wb") as fh:
                    fh.truncate(m["size"])                 # sparse: the size check passes, no disk used
        return home

    def tiny_lock(self, files):
        lock = {"comfyui": LOCK["comfyui"], "custom_nodes": [], "models": []}
        for name, folder, data, pin, opt in files:
            d = self.tmp / "models" / folder
            d.mkdir(parents=True, exist_ok=True)
            if data is not None:
                (d / name).write_bytes(data)
            m = {"set": "t", "folder": folder, "file": name, "size": len(data or b"xyz"),
                 "sha256": (hashlib.sha256(data).hexdigest() if pin == "good" else "0" * 64) if pin else None}
            if opt:
                m["optional"] = "--turbo"
            lock["models"].append(m)
        path = self.tmp / "lock.json"
        path.write_text(json.dumps(lock))
        return str(path)

    def test_models_verify(self):
        lock = self.tiny_lock([("a.safetensors", "vae", b"aaa", "good", False),
                               ("b.safetensors", "unet", b"bbb", None, False),
                               ("c.safetensors", "loras", None, None, True)])
        code, out, _ = self.run_comfy("models", "--verify", "--lock", lock)
        self.assertEqual(code, 0, out)
        self.assertIn("sha256 ok", out)
        self.assertIn("present, not pinned", out)
        self.assertIn("missing (optional: --turbo)", out)
        bad = self.tiny_lock([("a.safetensors", "vae", b"aaa", "bad", False)])
        code, out, _ = self.run_comfy("models", "--verify", "--lock", bad)
        self.assertEqual(code, 1)
        self.assertIn("sha256 MISMATCH", out)
        code, out, _ = self.run_comfy("models", "--lock", bad)          # no --verify: size only
        self.assertEqual(code, 0)
        (self.tmp / "models" / "vae" / "a.safetensors").write_bytes(b"aaaa")
        code, out, _ = self.run_comfy("models", "--lock", bad)
        self.assertEqual(code, 1)
        self.assertIn("size 4 != 3", out)
        self.assertEqual(self.run_comfy("models", "--set", "nope", "--lock", bad)[0], 2)

    @unittest.skipIf(os.name == "nt", "the real lock sizes need sparse files (POSIX)")
    def test_models_diffusion_alias_and_real_lock(self):
        self.desktop()
        code, out, _ = self.run_comfy("models")
        self.assertEqual(code, 0, out)
        self.assertIn("7/7 ok", out)
        os.remove(self.tmp / "models" / "diffusion_models" / "minimax_h3_ref2va_pruned_int8_convrot.safetensors")
        code, out, _ = self.run_comfy("models", "--set", "minimax-h3")
        self.assertEqual(code, 1)

    def test_install_dry_run_never_downloads_models(self):
        self.desktop(models=False)
        code, out, _ = self.run_comfy("install", "--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("ComfyUI: present at", out)
        self.assertIn("desktop layout, v0.43.1", out)
        self.assertIn("install never downloads models", out)
        self.assertIn("dry-run: nothing downloaded or changed", out)
        self.assertNotIn("huggingface", out)

    @unittest.skipIf(os.name == "nt", "the real lock sizes need sparse files (POSIX)")
    def test_install_dry_run_ok_and_portable_plan(self):
        self.desktop()
        code, out, _ = self.run_comfy("install", "--dry-run")
        self.assertEqual(code, 0, out)
        os.environ["FILM_COMFY_HOME"] = str(self.tmp / "nothing-here" / "ComfyUI_windows_portable")
        code, out, _ = self.run_comfy("install", "--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("NOT FOUND", out)
        code, out, _ = self.run_comfy("install", "--dry-run", "--portable")
        self.assertEqual(code, 0, out)
        self.assertIn("ComfyUI_windows_portable_nvidia.7z", out)
        self.assertIn("sha256 pinned", out)

    def test_workflows(self):
        code, out, _ = self.run_comfy("workflows")
        self.assertEqual(code, 0)
        self.assertIn("h3-i2v", out)
        self.assertIn("h3-r2v", out)
        self.assertIn("17k+5", out)
        self.assertIn("unverified", out)

    def test_ping(self):
        self.assertEqual(self.run_comfy("ping")[0], 1)
        f = self.server()
        code, out, _ = self.run_comfy("ping")
        self.assertEqual(code, 0)
        self.assertIn("ComfyUI 0.43.1", out)
        self.assertIn("RTX 5070 Ti", out)
        self.assertIn("offline: yes", out)
        f.offline = False
        self.assertIn("offline: NO", self.run_comfy("ping")[1])

    def test_interrupt_only_our_jobs(self):
        f = self.server()
        self.assertEqual(self.run_comfy("interrupt")[0], 2)
        rows = [{"kind": "video", "model": "comfy:h3-i2v", "status": "pending", "task_id": "p-open",
                 "note": "req=aa; seed=1"},
                {"kind": "video", "model": "comfy:h3-i2v", "status": "pending", "task_id": "p-done", "note": "req=bb"},
                {"kind": "video", "model": "comfy:h3-i2v", "status": "ok", "task_id": "p-done", "note": "req=bb"},
                {"kind": "video", "model": "dreamina-seedance-2-5-260628", "status": "pending", "task_id": "cgt-1",
                 "note": "req=cc"}]
        for r in rows:
            ark.ledger_append(self.ledger, r)
        f.prompts.append({"prompt_id": "p-open"})            # /queue lists it as running
        code, out, _ = self.run_comfy("interrupt", "--ledger", self.ledger)
        self.assertEqual(code, 0)
        self.assertEqual(f.interrupts, [{"prompt_id": "p-open"}])
        code, out, _ = self.run_comfy("interrupt", "--prompt-id", "p-other")
        self.assertIn("not queued or running", out)
        self.assertEqual(len(f.interrupts), 1)

    def test_start_when_running_and_without_install(self):
        self.server()
        code, out, _ = self.run_comfy("start")
        self.assertEqual(code, 0)
        self.assertIn("already answers", out)
        os.environ["FILM_COMFY_URL"] = "http://127.0.0.1:9"
        os.environ["FILM_COMFY_HOME"] = str(self.tmp / "none")
        self.assertEqual(self.run_comfy("start")[0], 2)
        os.environ["FILM_COMFY_URL"] = "http://192.0.2.1:8188"
        with mock.patch.object(comfy, "system_stats", lambda: None):
            self.assertIn("not this machine", self.run_comfy("start")[2])

    def test_start_dry_run_command(self):
        home = self.desktop(models=False)
        (self.tmp / "input").mkdir()            # the Desktop's shared input/output (owner's files, on C:): never used
        (self.tmp / "output").mkdir()
        work = self.tmp / "work"
        os.environ["FILM_COMFY_WORK"] = str(work)
        yml = self.tmp / "inst.yaml"
        yml.write_text("x: 1\n")
        os.environ["FILM_COMFY_MODEL_PATHS"] = str(yml)
        code, out, _ = self.run_comfy("start", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn(str(home / "ComfyUI" / ".venv" / "Scripts" / "python.exe"), out)
        for part in ("--listen 127.0.0.1 --port 9", "--disable-auto-launch", "--offline",
                     f"--extra-model-paths-config {yml}", f"--input-directory {work / 'input'}",
                     f"--output-directory {work / 'output'}", f"--temp-directory {work / 'temp'}",
                     f"--user-directory {work / 'user'}", f"log: {work / 'server.log'}"):
            self.assertIn(part, out)
        self.assertNotIn(f"--input-directory {self.tmp / 'input'}", out)
        self.assertFalse(work.exists(), "a dry run creates nothing")
        (home / "ComfyUI" / "comfy" / "cli_args.py").write_text("# old ComfyUI\n")
        self.assertIn("no flag that blocks the paid API nodes", self.run_comfy("start", "--dry-run")[2])

    def test_start_spawns_and_waits(self):
        home = self.desktop(models=False)
        (home / "ComfyUI" / "main.py").write_text(
            "import sys, json\nfrom http.server import BaseHTTPRequestHandler, HTTPServer\n"
            "port = int(sys.argv[sys.argv.index('--port') + 1])\n"
            "class H(BaseHTTPRequestHandler):\n"
            "    def log_message(self, *a): pass\n"
            "    def do_GET(self):\n"
            "        b = json.dumps({'system': {'comfyui_version': 'fake', 'argv': sys.argv}, 'devices': []}).encode()\n"
            "        self.send_response(200); self.end_headers(); self.wfile.write(b)\n"
            "HTTPServer(('127.0.0.1', port), H).serve_forever()\n")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        os.environ["FILM_COMFY_URL"] = f"http://127.0.0.1:{port}"
        os.environ["FILM_COMFY_PYTHON"] = sys.executable
        code, out, err = self.run_comfy("start", "--wait", "30")
        pid = int(re.search(r"started pid (\d+)", out).group(1))
        try:
            self.assertEqual(code, 0, out + err)
            self.assertIn("ComfyUI fake", out)
        finally:
            os.kill(pid, 15)
        work = self.tmp / "comfy-work"
        self.assertTrue((work / "server.log").exists())
        self.assertTrue(all((work / k).is_dir() for k in ("input", "output", "temp", "user")))


if __name__ == "__main__":
    unittest.main()
