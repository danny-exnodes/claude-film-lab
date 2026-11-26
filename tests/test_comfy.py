"""tools/comfy/comfy.py: the local ComfyUI engine (MiniMax H3 video, Qwen-Image stills). A fake ComfyUI HTTP server
(with a websocket for the sampler progress) runs in a thread; nothing reaches a real server, a GPU or the network."""
import base64, csv, hashlib, io, json, os, re, socket, struct, subprocess, sys, threading, time, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from PIL import Image

from helpers import REPO, TmpDirCase, load, run_main

comfy = load("comfy/comfy.py", "film_comfy")
ark = comfy.ark
I2V, R2V, QWEN = "h3-i2v", "h3-r2v", "qwen-t2i"
MP4 = b"\x00\x00\x00\x18ftypmp42fake-clip-with-audio"
_png = io.BytesIO()
Image.new("RGB", (1664, 928), (90, 40, 20)).save(_png, "PNG")
PNG = _png.getvalue()


def ws_frame(data, op=1):
    """A server -> client websocket frame (unmasked)."""
    data = json.dumps(data).encode() if op == 1 else data
    n = len(data)
    head = bytes([0x80 | op]) + (bytes([n]) if n < 126 else bytes([126]) + struct.pack(">H", n))
    return head + data
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
        self.pending, self.drop_posts = [], set()      # /queue pending ids; POST paths answered by a dropped connection
        self.calls, self.uploads, self.prompts, self.interrupts, self.deletes = [], {}, [], [], []
        self.polls = {}
        self.ws, self.ws_clients, self.ws_done = True, [], threading.Event()   # /ws: sampler progress of image jobs
        self.frees, self.history_status, self.queue_gone_after, self.queue_calls = [], None, None, 0
        self.on_view, self.owner = None, None      # on_view(): runs before /view answers; owner: a gpu.owner path
        self.held = []                             # (method, path, the GPU lock's owner file existed?)
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

            def websocket(self, u):
                """ComfyUI's /ws: a status message, then for our prompt a binary preview, the KSampler's progress
                (value 1..steps), one progress of another node; stays open until the client goes."""
                key = self.headers.get("Sec-WebSocket-Key", "")
                accept = base64.b64encode(hashlib.sha1((key + comfy.WS_GUID).encode()).digest()).decode()
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", accept)
                self.end_headers()
                cid = parse_qs(u.query).get("clientId", [""])[0]
                fake.ws_clients.append(cid)
                self.wfile.write(ws_frame({"type": "status", "data": {"sid": cid}}))
                self.wfile.flush()
                t0, p = time.time(), None
                while time.time() - t0 < 10 and p is None:
                    p = next((x for x in fake.prompts if x.get("client_id") == cid), None)
                    time.sleep(0.005)
                if p is not None:
                    pid, steps = p["prompt_id"], p["prompt"]["9"]["inputs"]["steps"]
                    out = ws_frame(b"\x00\x00\x00\x01\x00\x00\x00\x02preview-jpeg", op=2)
                    out += ws_frame({"type": "progress", "data": {"value": 1, "max": 1, "prompt_id": "other",
                                                                  "node": "9"}})
                    for v in range(1, steps + 1):
                        out += ws_frame({"type": "progress", "data": {"value": v, "max": steps, "prompt_id": pid,
                                                                      "node": "9"}})
                    out += ws_frame({"type": "progress", "data": {"value": 1, "max": 1, "prompt_id": pid,
                                                                  "node": "10"}})
                    self.wfile.write(out)
                    self.wfile.flush()
                    fake.ws_done.set()
                try:
                    self.connection.settimeout(10)
                    self.rfile.read(1)
                except OSError:
                    pass
                self.close_connection = True

            def do_GET(self):
                fake.calls.append(("GET", self.path))
                fake.held.append(("GET", self.path, bool(fake.owner and os.path.exists(fake.owner))))
                u = urlparse(self.path)
                if u.path == "/ws" and fake.ws:
                    return self.websocket(u)
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
                if u.path.startswith("/history/") and fake.history_status:
                    return self.send_json({"error": "boom"}, fake.history_status)
                if u.path.startswith("/history/"):
                    pid = u.path.rsplit("/", 1)[1]
                    fake.polls[pid] = fake.polls.get(pid, 0) + 1
                    if fake.mode == "never" or fake.polls[pid] < fake.polls_until_done:
                        return self.send_json({})
                    return self.send_json({pid: fake.history(pid)})
                if u.path == "/queue":
                    fake.queue_calls += 1
                    if fake.queue_gone_after is not None and fake.queue_calls > fake.queue_gone_after:
                        return self.send_json({"queue_running": [], "queue_pending": []})
                    running = [[1, p["prompt_id"], {}, {}, []] for p in fake.prompts]
                    pending = [[2, pid, {}, {}, []] for pid in fake.pending]
                    return self.send_json({"queue_running": running, "queue_pending": pending})
                if u.path == "/view":
                    if fake.on_view:
                        fake.on_view()
                    q = parse_qs(u.query)
                    fake.view = q
                    data = PNG if q["filename"][0].endswith(".png") else MP4
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    return self.wfile.write(data)
                self.send_json({"error": "not found"}, 404)

            def do_POST(self):
                fake.calls.append(("POST", self.path))
                fake.held.append(("POST", self.path, bool(fake.owner and os.path.exists(fake.owner))))
                raw = self.body()
                if self.path in fake.drop_posts:     # the server goes away mid-request: no answer at all
                    self.close_connection = True
                    return
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
                if self.path == "/free":
                    fake.frees.append(data)
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
        prompt = next((p["prompt"] for p in self.prompts if p.get("prompt_id") == pid), {})
        if self.mode == "success" and any(n.get("class_type") == "SaveImage" for n in prompt.values()):
            if self.ws_clients:
                self.ws_done.wait(5)            # the sampler's progress went out before the job ends
            return {"outputs": {"11": {"images": [{"filename": "qwen-t2i_00001_.png", "subfolder": "film-lab",
                                                   "type": "output"}]}},
                    "status": {"status_str": "success", "completed": True,
                               "messages": [start, ["execution_success", {"prompt_id": pid, "timestamp": 136000}]]}}
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
        env["FILM_GPU_LOCK"] = str(self.tmp / "gpu" / "gpu.lock")   # never the lab's own GPU lock
        self._env = mock.patch.dict(os.environ, env, clear=True)
        self._env.start()
        for name, val in (("POLL_SECONDS", 0.01), ("PROGRESS_SECONDS", 0), ("START_POLL", 0.1), ("LOST_POLL", 0.01),
                          ("FREE_WAIT", 0)):
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
        f.owner = str(self.tmp / "gpu" / "gpu.owner")
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

    def run_still(self, *extra, out=None):
        self.png = out or str(self.tmp / "concepts" / "phuong-hoang_v01.png")
        return self.run_comfy("run", QWEN, "--prompt", "a mythic phoenix of ink and fire, concept sheet", "--seed",
                              "11", "--out", self.png, "--ledger", self.ledger, *extra)

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
        self.assertEqual(sorted(comfy.workflow_ids()), [I2V, R2V, QWEN])
        self.assertEqual(comfy.ALLOWED_NODES, classes | {"LoadImage", "MiniMaxH3AddGuide"})
        for cls in PAID:
            self.assertNotIn(cls, comfy.ALLOWED_NODES)
        self.assertFalse([c for c in comfy.ALLOWED_NODES if c.startswith("Minimax")])
        self.assertEqual(comfy.graph_classes(comfy.load_workflow(QWEN)[0]),
                         {"UNETLoader", "LoraLoaderModelOnly", "CLIPLoader", "VAELoader", "ModelSamplingAuraFlow",
                          "CLIPTextEncode", "EmptySD3LatentImage", "KSampler", "VAEDecode", "SaveImage"})

    def test_every_variant_is_a_closed_graph(self):
        for wid in (I2V, R2V):
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

    def test_every_workflow_names_its_source_and_licence(self):
        # A workflow JSON cannot hold a comment: its .meta.json names the template it was adapted from, and
        # THIRD_PARTY.md has a row for it (CLAUDE.md: adapted code names its source).
        third = (REPO / "THIRD_PARTY.md").read_text(encoding="utf-8")
        for wid in (I2V, R2V):
            meta = comfy.load_workflow(wid)[1]
            self.assertIn("https://github.com/Comfy-Org/workflow_templates", meta.get("source", ""), wid)
            self.assertRegex(meta["source"], r"video_minimax_h3_\w+\.json", wid)
            self.assertIn(f"| `tools/comfy/workflows/{wid}.json` |", third)
        self.assertIn("### MIT: Comfy-Org/workflow_templates", third)
        # qwen-t2i is the lab's own graph of core nodes (nothing copied): its meta says so
        self.assertIn("no template file copied", comfy.load_workflow(QWEN)[1]["source"])

    def test_budget_rule_states_the_local_engine_exception(self):
        # CLAUDE.md asks --budget + --ledger on every generation command; comfy.py run takes --ledger only (no
        # --budget flag exists), so the rule must say so, in CLAUDE.md, WORKFLOW §4 and the film-animator agent.
        self.assertNotIn("--budget", comfy.p.format_help() + " ".join(
            a for sp in comfy.p._subparsers._group_actions for c in sp.choices.values() for a in c._option_string_actions))
        for rel in ("CLAUDE.md", "docs/WORKFLOW.md", ".claude/agents/film-animator.md"):
            text = re.sub(r"\s+", " ", (REPO / rel).read_text(encoding="utf-8"))
            self.assertIn("không có cờ `--budget`", text, rel)
        for rel in ("CLAUDE.md", "docs/WORKFLOW.md"):
            text = re.sub(r"\s+", " ", (REPO / rel).read_text(encoding="utf-8"))
            self.assertIn("`comfy:*`/`blender:*` tính 0", text, rel)

    def test_lock_and_graph_models(self):
        lock = comfy.load_lock()
        self.assertEqual(lock["custom_nodes"], [])
        self.assertEqual({m["set"] for m in lock["models"]}, {"minimax-h3", "qwen-image"})
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
        q = comfy.load_workflow(QWEN)[0]
        self.assertEqual((q["1"]["inputs"]["unet_name"], q["3"]["inputs"]["type"]),
                         ("qwen_image_2512_fp8_e4m3fn.safetensors", "qwen_image"))
        sizes = {m["file"]: m["size"] for m in lock["models"] if m["set"] == "qwen-image"}
        self.assertEqual(sizes["qwen_image_vae.safetensors"], 253806246)       # as on the owner's disk
        self.assertEqual([m["optional"] for m in lock["models"] if m["set"] == "qwen-image" and m.get("optional")],
                         ["--turbo"])

    def test_canvas_sizes_fit_the_nodes(self):
        for wid in (I2V, R2V):
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
            (self.base() + ["--steps", "0"], r"--steps must be >= 1"),     # 0 is refused, not the default
            (self.base() + ["--steps", "0", "--turbo"], r"--steps must be >= 1"),
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

    def test_keep_frames_land_where_check_episode_and_matte_seq_expect_them(self):
        f = self.server()
        real_run = subprocess.run
        ffmpeg_calls = []

        def fake_run(cmd, *a, **kw):
            if cmd and cmd[0] == "ffmpeg":
                ffmpeg_calls.append(cmd)
                for n in (1, 2, 3):
                    Path(cmd[-1] % n).write_bytes(b"png")
                return subprocess.CompletedProcess(cmd, 0)
            return real_run(cmd, *a, **kw)
        with mock.patch.object(comfy.shutil, "which", lambda name, *a, **kw: "/usr/bin/" + name),                 mock.patch.object(comfy.subprocess, "run", fake_run):
            code, out, err = self.run_clip(I2V, "--keep-frames")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(ffmpeg_calls), 1)
        stem = os.path.splitext(os.path.basename(self.out))[0]
        raw = Path(self.out).parent / stem / "raw"
        self.assertEqual(sorted(p.name for p in raw.iterdir()), ["000001.png", "000002.png", "000003.png"])
        self.assertIn(f"frames in {raw}", out)
        ce = load("check_episode.py", "film_check_episode_comfy_frames")
        media = self.tmp
        rep = ce.Report()
        names = []
        for root, _dirs, files in os.walk(media / "clips"):
            for n in files:
                rel = os.path.relpath(os.path.join(root, n), media)
                names.append(rel)
                ce.check_media_name(rel, n, "clips", ce.MEDIA_RULES["clips"], "ep01", rep)
        self.assertEqual(len(names), 5, names)        # clip + sidecar + 3 frames
        self.assertEqual(rep.errors, 0, rep.lines)
        # a second run of the same clip name is refused before anything is sent (versions only go up)
        os.remove(self.out)
        os.remove(self.out + ".json")
        n_prompts = len(f.prompts)
        with mock.patch.object(comfy.shutil, "which", lambda name, *a, **kw: "/usr/bin/" + name):
            code, _, err = self.run_clip(I2V, "--keep-frames")
        self.assertEqual(code, 2, err)
        self.assertIn("raw exists and is not empty", err)
        self.assertEqual(len(f.prompts), n_prompts)

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
        self.assertIn("11/11 ok", out)                                  # minimax-h3 7 + qwen-image 4
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

    def test_interrupt_goes_on_when_the_server_drops(self):
        f = self.server()
        for pid in ("p-run", "p-wait", "p-run2"):
            ark.ledger_append(self.ledger, {"kind": "video", "model": "comfy:h3-i2v", "status": "pending",
                                            "task_id": pid, "note": f"req={pid}"})
        f.prompts += [{"prompt_id": "p-run"}, {"prompt_id": "p-run2"}]   # running
        f.pending = ["p-wait"]
        f.drop_posts = {"/interrupt"}
        code, out, err = self.run_comfy("interrupt", "--ledger", self.ledger)
        self.assertEqual(code, 1, out + err)
        self.assertIn("p-run: running, interrupt FAILED (network error", err)
        self.assertIn("p-run2: running, interrupt FAILED", err)
        self.assertIn("p-wait: queued -> removed from the queue", out)   # the ids after a failure are still handled
        self.assertEqual(f.deletes, [{"delete": ["p-wait"]}])
        f.drop_posts = {"/queue"}
        code, out, err = self.run_comfy("interrupt", "--ledger", self.ledger)
        self.assertEqual(code, 1, out + err)
        self.assertIn("p-wait: queued, removal FAILED", err)
        self.assertIn("p-run: running -> interrupted", out)
        self.assertIn("p-run2: running -> interrupted", out)
        f.drop_posts = set()
        code, out, err = self.run_comfy("interrupt", "--prompt-id", "p-run")
        self.assertEqual(code, 0, out + err)

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


class TestQwenImage(ComfyCase):
    """Issue #54: qwen-t2i (Qwen-Image 2512 text-to-image) for concept art, local and free."""

    def test_graph_variants(self):
        graph, meta, _ = comfy.load_workflow(QWEN)
        self.assertEqual((meta["kind"], meta["ledger_model"], meta["output"]["type"]), ("image", "comfy:qwen-image", "image"))
        for node, inp in (x for v in meta["params"].values() for x in v):
            self.assertIn(inp, graph[node]["inputs"], f"{node}.{inp}")
        v = {"prompt": "p", "negative": "n", "width": 1328, "height": 1328, "seed": 5, "steps": 30, "cfg": 2.5,
             "prefix": "film-lab/qwen-t2i", "turbo": False}
        g = comfy.build_graph(graph, meta, v)
        self.assertEqual((comfy.dangling(g), comfy.disallowed(g)), ([], []))
        self.assertNotIn("2", g)                                             # no LoRA without --turbo
        self.assertEqual(g["5"]["inputs"], {"model": ["1", 0], "shift": 3.1})   # ModelSamplingAuraFlow shift 3.1
        k = g["9"]["inputs"]
        self.assertEqual((k["seed"], k["steps"], k["cfg"], k["sampler_name"], k["scheduler"]), (5, 30, 2.5, "euler", "simple"))
        self.assertEqual((g["6"]["inputs"]["text"], g["7"]["inputs"]["text"]), ("p", "n"))
        self.assertEqual((g["8"]["class_type"], g["8"]["inputs"]["width"], g["8"]["inputs"]["height"]),
                         ("EmptySD3LatentImage", 1328, 1328))
        self.assertEqual(g["3"]["inputs"]["type"], "qwen_image")
        gt = comfy.build_graph(graph, meta, dict(v, turbo=True, steps=2, cfg=1.0))
        self.assertEqual(gt["5"]["inputs"]["model"], ["2", 0])
        self.assertEqual(gt["2"]["inputs"]["lora_name"], "Wuli-Qwen-Image-2512-Turbo-LoRA-2steps-V1.0-bf16.safetensors")
        self.assertEqual(comfy.dangling(gt), [])

    def test_dry_run_is_clean_and_sends_nothing(self):
        f = self.server()
        code, out, err = self.run_still("--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual(f.calls, [])
        self.assertFalse(os.path.exists(self.ledger))
        self.assertIn("workflow qwen-t2i (comfy:qwen-image) · 10 nodes · 1664x928 · steps 30 · cfg 2.5 · seed 11", out)
        self.assertIn("estimate ~135 s of GPU", out)                       # the owner's measure: 30 steps, 1664x928
        self.assertIn("dry-run: nothing uploaded or queued, no ledger row", out)
        self.assertEqual(err, "")
        code, out, err = self.run_still("--dry-run", "--turbo", "--size", "1328x1328", "--negative", "blurry")
        self.assertEqual(code, 0, err)
        self.assertIn("11 nodes · 1328x1328 · steps 2 · cfg 1 (turbo LoRA)", out)
        self.assertIn("Wuli-Qwen-Image-2512-Turbo-LoRA-2steps-V1.0-bf16.safetensors", out)
        self.assertIn("negative:\n  blurry", out)
        self.assertIn("drafts only", err)
        code, out, err = self.run_still("--dry-run", "--size", "1024x768")
        self.assertEqual(code, 0, err)
        self.assertIn("not one of qwen-t2i's trained sizes", err)

    def test_local_refusals(self):
        (self.tmp / "concepts").mkdir()
        (self.tmp / "concepts" / "old_v01.png").write_bytes(PNG)
        start = self.start
        for extra, want in ((["--size", "1000x1000"], "needs multiples of 16 (e.g. 992x992)"),
                            (["--size", "4096x2048"], "each side must be 256..2048"),
                            (["--size", "big"], "use WxH"),
                            (["--image", start], "--image belong to the video workflows"),
                            (["--seconds", "5", "--res", "480p"], "--seconds, --res belong to the video workflows"),
                            (["--cfg", "0"], "--cfg must be > 0"),
                            (["--steps", "0"], "--steps must be >= 1")):
            with self.subTest(extra=extra):
                code, _, err = self.run_still(*extra)
                self.assertEqual(code, 2, err)
                self.assertIn(want, err)
        code, _, err = self.run_still(out=str(self.tmp / "concepts" / "old_v01.png"))
        self.assertEqual(code, 2)
        self.assertIn("next free: ", err)
        code, _, err = self.run_still(out=str(self.tmp / "concepts" / "x_v01.jpg"))
        self.assertEqual(code, 2)
        self.assertIn("saves PNG", err)
        code, _, err = self.run_comfy("run", QWEN, "--prompt", "x", "--out", str(self.tmp / "a_v01.png"))
        self.assertEqual(code, 2)
        self.assertIn("run needs --ledger", err)
        code, _, err = self.run_clip(I2V, "--cfg", "3")
        self.assertEqual(code, 2)
        self.assertIn("--size/--cfg are for the image workflows", err)
        self.assertFalse(os.path.exists(self.ledger))

    def test_happy_path_png_sidecar_ledger_and_steps(self):
        f = self.server()
        pf = self.tmp / "prompt.txt"
        pf.write_text("  phượng hoàng mực tàu, khung concept\n", encoding="utf-8")
        code, out, err = self.run_comfy("run", QWEN, "--prompt-file", str(pf), "--seed", "11", "--steps", "6",
                                        "--out", str(self.tmp / "concepts" / "ph_v01.png"), "--ledger", self.ledger)
        self.assertEqual(code, 0, err)
        png = self.tmp / "concepts" / "ph_v01.png"
        self.assertEqual(png.read_bytes(), PNG)
        (prompt,) = f.prompts
        g = prompt["prompt"]
        self.assertEqual(g["6"]["inputs"]["text"], "phượng hoàng mực tàu, khung concept")
        self.assertEqual((g["9"]["inputs"]["steps"], g["9"]["inputs"]["seed"]), (6, 11))
        self.assertEqual(comfy.disallowed(g), [])
        self.assertEqual(f.uploads, {}, "text-to-image uploads nothing")
        self.assertEqual(f.ws_clients, [prompt["client_id"]], "progress came over the websocket of our client id")
        self.assertEqual(f.view["filename"], ["qwen-t2i_00001_.png"])
        for v in range(1, 7):
            self.assertIn(f"step {v}/6 elapsed", out)
        self.assertNotIn("step 1/1", out, "another node's or another prompt's progress is not a sampler step")
        side = json.loads((self.tmp / "concepts" / "ph_v01.png.json").read_text(encoding="utf-8"))
        self.assertEqual((side["workflow"], side["model"], side["width"], side["height"], side["steps"], side["cfg"]),
                         (QWEN, "comfy:qwen-image", 1664, 928, 6, 2.5))
        self.assertEqual((side["seed"], side["turbo"], side["size"], side["gpu_seconds"]), (11, False, [1664, 928], 135.0))
        rows = self.rows()
        self.assertEqual([r["status"] for r in rows], ["pending", "ok"])
        last = rows[-1]
        self.assertEqual((last["kind"], last["model"], last["size"], last["count"], last["seconds"]),
                         ("image", "comfy:qwen-image", "1664x928", "1", ""))
        self.assertEqual((last["task_id"], last["usage"], last["agent"]), (prompt["prompt_id"], "gpu_s=135", "film-animator"))
        self.assertIn("seed=11", last["note"])
        self.assertEqual(ark.cost_units(last), 0.0)                     # local: free against every cap
        self.assertFalse((self.tmp / "gpu" / "gpu.owner").exists(), "the GPU lock is given back")

    def test_without_websocket_progress_is_by_time(self):
        f = self.server()
        f.ws = False
        code, out, err = self.run_still()
        self.assertEqual(code, 0, err)
        self.assertIn("no websocket: progress by time", out)
        self.assertEqual(Path(self.png).read_bytes(), PNG)

    def test_errors_are_ledger_rows(self):
        f = self.server()
        f.mode = "error"
        code, _, err = self.run_still()
        self.assertEqual(code, 1)
        self.assertIn("CUDA out of memory", err)
        self.assertEqual([r["status"] for r in self.rows()], ["pending", "failed"])
        self.assertFalse(os.path.exists(self.png))
        f.mode = "never"
        code, _, err = self.run_still("--timeout", "0.2", out=str(self.tmp / "concepts" / "b_v01.png"))
        self.assertEqual(code, 1)
        self.assertEqual(self.rows()[-1]["status"], "interrupted")
        self.assertTrue(f.interrupts)

    def test_review_hook_kind_image_steps_and_the_png(self):
        self.server()
        hook = mock.MagicMock()
        with mock.patch.object(comfy, "review_hook", return_value=hook) as rh:
            code, out, err = self.run_still("--steps", "4", "--review", "concept-a")
        self.assertEqual(code, 0, err)
        self.assertEqual(rh.call_args.args[1], "image")
        hook.start.assert_called_once()
        steps = [c.args for c in hook.update.call_args_list if c.args[1].startswith("step ")]
        self.assertEqual([s[1].split(" · ")[0] for s in steps], ["step 1/4", "step 2/4", "step 3/4", "step 4/4"])
        self.assertEqual([round(s[0], 2) for s in steps], [0.25, 0.5, 0.75, 0.99])
        self.assertTrue(all(c.kwargs.get("force") for c in hook.update.call_args_list if c.args[1].startswith("step ")))
        last = [c for c in hook.update.call_args_list if c.args[1].startswith("step 4/4")][0]
        self.assertEqual((last.kwargs["step"], last.kwargs["steps"]), (4, 4))
        (im,) = hook.image.call_args_list
        self.assertEqual(im.args, (self.png, "phuong-hoang_v01"))
        self.assertEqual({k: im.kwargs[k] for k in ("seed", "model", "sampler_steps", "width", "height")},
                         {"seed": 11, "model": "comfy:qwen-image", "sampler_steps": 4, "width": 1664, "height": 928})
        self.assertEqual(im.kwargs["prompt"], "a mythic phoenix of ink and fire, concept sheet")
        hook.rv.step.assert_not_called()
        hook.finish.assert_called_once()
        self.assertEqual(hook.finish.call_args.args[0], [])

    def test_review_events_with_the_real_client(self):
        events = []

        class Ingest(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                events.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Ingest)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
        os.environ["FILM_REVIEW_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        os.environ["FILM_REVIEW_MEDIA"] = str(self.tmp / "media")
        self.server()
        code, out, err = self.run_still("--steps", "3", "--review", "concept-a")
        self.assertEqual(code, 0, err)
        self.assertEqual((events[0]["type"], events[0]["kind"], events[0]["build"]), ("build", "image", "concept-a"))
        types = [e["type"] for e in events]
        self.assertEqual(types[-3:], ["step", "job", "done"])
        step = events[-3]
        self.assertEqual((step["label"], step["image"]), ("phuong-hoang_v01", "concept-a/phuong-hoang_v01.png"))
        self.assertEqual((step["seed"], step["sampler_steps"], step["workflow"], step["prompt"]),
                         (11, 3, "qwen-t2i", "a mythic phoenix of ink and fire, concept sheet"))
        self.assertEqual(events[0]["tags"]["engine"], ["comfy-qwen"])
        self.assertEqual((self.tmp / "media" / "concept-a" / "phuong-hoang_v01.png").read_bytes(), PNG)
        msgs = [e.get("message", "") for e in events if e["type"] == "job"]
        self.assertTrue(any(m.startswith("step 3/3") for m in msgs), msgs)
        self.assertRegex(events[1]["job"], r"^comfy-[0-9a-f-]{36}$")
        self.assertNotIn("phượng", json.dumps(events, ensure_ascii=False))
        self.assertNotIn(str(self.tmp), json.dumps(events), "no local path reaches the public page")

    def test_review_client_gets_build_kind_image(self):
        calls = []
        client = self.tmp / "client.py"
        client.write_text("import json, os\n"
                          "def path_tags(*paths):\n"
                          "    return {'project': 'shk', 'episode': 'q01t03'}\n"
                          "def job_hook(build, tool, kind='render', tags=None, label=None, **kw):\n"
                          "    with open(os.environ['HOOK_LOG'], 'a') as f:\n"
                          "        f.write(json.dumps([build, tool, kind, tags, label]) + '\\n')\n"
                          "    return None\n", encoding="utf-8")
        log = self.tmp / "hook.log"
        import argparse
        with mock.patch.object(comfy, "REVIEW_CLIENT", str(client)), mock.patch.dict(os.environ, {"HOOK_LOG": str(log)}):
            comfy.review_hook(argparse.Namespace(review="concept-a", dry_run=False, workflow="qwen-t2i"), "image")
            comfy.review_hook(argparse.Namespace(review="clip-a", dry_run=False, workflow="h3-i2v"))
        calls = [json.loads(l) for l in log.read_text().splitlines()]
        tag = {"project": "shk", "episode": "q01t03"}
        self.assertEqual(calls, [["concept-a", "comfy", "image", dict(tag, engine="comfy-qwen"), "qwen-t2i"],
                                 ["clip-a", "comfy", "clip", dict(tag, engine="comfy-h3"), "h3-i2v"]])

    def test_gpu_lock_is_taken_and_a_busy_gpu_refuses(self):
        f = self.server()
        hold = ("import sys, time; sys.path.insert(0, sys.argv[1]); import gpu_run\n"
                "with gpu_run.gpu_lock('blender render s21'):\n"
                "    print('held', flush=True); time.sleep(20)\n")
        env = {k: v for k, v in os.environ.items() if k != "FILM_GPU_HELD"}
        p = subprocess.Popen([sys.executable, "-c", hold, str(REPO / "tools")], stdout=subprocess.PIPE, text=True,
                             env=env)
        self.addCleanup(lambda: (p.kill(), p.wait(), p.stdout.close()))
        self.assertEqual(p.stdout.readline().strip(), "held")
        os.environ["FILM_GPU_WAIT"] = "0.3"
        code, _, err = self.run_still()
        self.assertEqual(code, 2, err)
        self.assertIn("the GPU is still busy", err)
        self.assertIn("blender render s21", err)
        self.assertFalse(os.path.exists(self.ledger), "nothing sent, no ledger row")
        self.assertEqual(f.prompts, [])
        code, _, err = self.run_clip(I2V)
        self.assertEqual(code, 2, err)                                   # the video path waits for the GPU too
        self.assertEqual(f.prompts, [])
        code, out, err = self.run_still("--dry-run")
        self.assertEqual(code, 0, err)                                   # --dry-run never waits
        p.kill()
        p.wait()
        os.environ.pop("FILM_GPU_WAIT")
        code, _, err = self.run_still(out=str(self.tmp / "concepts" / "c_v01.png"))
        self.assertEqual(code, 0, err)

    def test_workflows_lists_the_image_workflow(self):
        code, out, _ = self.run_comfy("workflows")
        self.assertEqual(code, 0)
        self.assertIn("qwen-t2i  Qwen-Image 2512", out)
        self.assertIn("model comfy:qwen-image · set qwen-image", out)
        self.assertIn("--size WxH (default 1664x928)", out)
        self.assertIn("~135 s for 30 steps at 1664x928", out)


class TestGpuSafety(ComfyCase):
    """Review round 2: outputs checked again once the GPU lock is held and never replaced; VRAM freed before the
    lock goes; the lock kept while a lost prompt may still run; a pending row always gets its final row."""

    def appear_during_wait(self, *paths):
        """Another run with the same --out finishes while this one waits for the GPU lock."""
        real = comfy.hold_gpu

        def hold(wid):
            for p in paths:
                Path(p).parent.mkdir(parents=True, exist_ok=True)
                Path(p).write_bytes(b"another run")
            real(wid)
        return mock.patch.object(comfy, "hold_gpu", hold)

    def owner_gone(self):
        self.assertFalse((self.tmp / "gpu" / "gpu.owner").exists(), "the GPU lock is given back")

    def test_output_that_appeared_during_the_gpu_wait_is_refused(self):
        f = self.server()
        for appear in ([self.out], [self.out + ".json"]):
            with self.subTest(appear=appear), self.appear_during_wait(*appear):
                code, _, err = self.run_clip()
                self.assertEqual(code, 2, err)
                self.assertIn("appeared while this run waited for the GPU", err)
                self.assertIn("nothing sent, no ledger row", err)
            for p in appear:
                os.remove(p)
        png = str(self.tmp / "concepts" / "phuong-hoang_v01.png")
        with self.appear_during_wait(png):
            code, _, err = self.run_still()
        self.assertEqual(code, 2, err)
        self.assertEqual(Path(png).read_bytes(), b"another run")
        self.assertEqual((f.prompts, f.uploads, f.frees), ([], {}, []))
        self.assertFalse(os.path.exists(self.ledger), "no ledger row")
        self.owner_gone()

    def test_download_never_replaces_a_file_that_appeared(self):
        f = self.server()
        f.on_view = lambda: Path(self.out).write_bytes(b"another run")
        code, _, err = self.run_clip()
        self.assertEqual(code, 1, err)
        self.assertIn("not replaced", err)
        self.assertEqual(Path(self.out).read_bytes(), b"another run")
        rows = self.rows()
        self.assertEqual([r["status"] for r in rows], ["pending", "failed"])
        self.assertIn("not replaced", rows[-1]["note"])
        self.assertEqual(list(Path(self.out).parent.glob("*.part")), [])
        self.assertFalse(os.path.exists(self.out + ".json"))

    def test_place_new_never_replaces(self):
        src, dst = self.tmp / "a.part", self.tmp / "a.mp4"
        src.write_bytes(b"new")
        dst.write_bytes(b"old")
        with self.assertRaises(FileExistsError):
            comfy.place_new(str(src), str(dst))
        self.assertEqual((dst.read_bytes(), src.read_bytes()), (b"old", b"new"))
        dst.write_bytes(b"")                                   # an empty file counts as free (as ark.guard_output)
        comfy.place_new(str(src), str(dst))
        self.assertEqual(dst.read_bytes(), b"new")
        self.assertFalse(src.exists())
        src.write_bytes(b"newer")
        with mock.patch.object(comfy.os, "link", side_effect=PermissionError("no hard links here")):
            with self.assertRaises(FileExistsError):
                comfy.place_new(str(src), str(dst))
            dst.unlink()
            comfy.place_new(str(src), str(dst))
        self.assertEqual(dst.read_bytes(), b"newer")
        self.assertFalse(src.exists())

    def test_models_are_freed_before_the_gpu_lock_is_released(self):
        f = self.server()
        code, out, err = self.run_clip()
        self.assertEqual(code, 0, err)
        self.assertEqual(f.frees, [{"unload_models": True, "free_memory": True}])
        posts = [c for c in f.calls if c[0] == "POST" or c[1].startswith("/view")]
        self.assertEqual(posts[-1], ("POST", "/free"), "after the download")
        self.assertIn(("POST", "/free", True), f.held, "while the GPU lock is still held")
        self.assertIn("models unloaded", out)
        self.owner_gone()
        f.mode = "error"                                       # a failed job frees them too
        self.out = str(self.tmp / "clips" / "ep01_s03_clip_v02.mp4")
        self.assertEqual(self.run_clip()[0], 1)
        self.assertEqual(len(f.frees), 2)
        f.mode = "success"
        code, _, err = self.run_still("--keep-models")         # a batch of comfy runs keeps them
        self.assertEqual(code, 0, err)
        self.assertEqual(len(f.frees), 2)
        code, _, err = self.run_still(out=str(self.tmp / "concepts" / "b_v01.png"))
        self.assertEqual(code, 0, err)
        self.assertEqual(len(f.frees), 3)
        self.assertEqual(f.held[-1][:2], ("POST", "/free"))
        self.assertTrue(f.held[-1][2])
        code, _, err = self.run_still("--dry-run", out=str(self.tmp / "concepts" / "c_v01.png"))
        self.assertEqual((code, len(f.frees)), (0, 3), "a dry run sends nothing")

    def test_free_failure_is_only_a_warning(self):
        f = self.server()
        f.drop_posts.add("/free")
        code, _, err = self.run_still()
        self.assertEqual(code, 0, err)
        self.assertIn("could not ask ComfyUI to unload its models", err)
        self.owner_gone()

    def test_lost_server_keeps_the_lock_until_the_prompt_left_the_queue(self):
        f = self.server()
        f.history_status = 500
        f.queue_gone_after = comfy.POLL_ERRORS + 3            # the polling loop reads /queue once per try
        code, _, err = self.run_clip()
        self.assertEqual(code, 1, err)
        row = self.rows()[-1]
        self.assertEqual(row["status"], "failed")
        self.assertIn("polling stopped", row["note"])
        self.assertIn("no longer queued or running", row["note"])
        queue = [h for h in f.held if h[1] == "/queue"]
        self.assertGreater(len(queue), comfy.POLL_ERRORS + 3, "waited for the prompt to leave the queue")
        self.assertTrue(all(h[2] for h in queue), "with the GPU lock held")
        self.owner_gone()
        f.queue_gone_after = None                              # never leaves: a bounded wait, then a clear note
        self.out = str(self.tmp / "clips" / "ep01_s03_clip_v02.mp4")
        with mock.patch.object(comfy, "LOST_WAIT", 0.2):
            code, _, err = self.run_clip()
        self.assertEqual(code, 1)
        self.assertIn("MAY STILL RUN", self.rows()[-1]["note"])
        self.assertIn("comfy.py interrupt --prompt-id", err)
        with mock.patch.object(comfy, "LOST_WAIT", 0.2):    # the image workflow too
            code, _, err = self.run_still()
        self.assertEqual(code, 1)
        self.assertIn("MAY STILL RUN", self.rows()[-1]["note"])

    def test_wait_gone_when_the_server_is_down(self):
        with mock.patch.object(sys, "stderr", io.StringIO()):
            note = comfy.wait_gone("abc", limit=30)            # FILM_COMFY_URL: a closed port
        self.assertIn("the server is down", note)

    def test_interrupt_right_after_the_pending_row_writes_the_final_row(self):
        f = self.server()
        hook = mock.MagicMock()
        hook.start.side_effect = ark.Interrupted(15)
        with mock.patch.object(comfy, "review_hook", return_value=hook):
            code, _, err = self.run_clip()
        self.assertEqual(code, 143, err)
        self.assertEqual([r["status"] for r in self.rows()], ["pending", "interrupted"])
        self.assertEqual(f.prompts, [])
        with mock.patch.object(comfy.StepListener, "connect", side_effect=ark.Interrupted(2)):
            code, _, err = self.run_still()
        self.assertEqual(code, 130, err)
        self.assertEqual([r["status"] for r in self.rows()][-2:], ["pending", "interrupted"])
        self.owner_gone()

if __name__ == "__main__":
    unittest.main()
