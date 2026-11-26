"""Issue #69: `comfy.py run hunyuan3d` (Hunyuan3D 2.1 image-to-3D, tools/comfy/mesh3d.py) against the fake ComfyUI of
test_comfy.py: graph, dry-run, input background check, refusals, the GLB download (never replaced), sidecar, ledger,
GPU lock and /free. Nothing reaches a real server, a GPU or the network."""
import csv, io, json, os, struct, unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

import test_comfy
from test_comfy import ComfyCase, FakeComfy

comfy = test_comfy.comfy
H3D = "hunyuan3d"
CKPT = "hunyuan_3d_v2.1.safetensors"


def tiny_glb():
    """One triangle as a binary glTF (what SaveGLB writes: POSITION float32 + uint32 indices)."""
    pos = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    idx = struct.pack("<3I", 0, 1, 2)
    gltf = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
            "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
                          {"bufferView": 1, "componentType": 5125, "count": 3, "type": "SCALAR"}],
            "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36}, {"buffer": 0, "byteOffset": 36,
                                                                                 "byteLength": 12}],
            "buffers": [{"byteLength": 48}]}
    js = json.dumps(gltf).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", 48, 0x004E4942) + pos + idx
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


GLB = tiny_glb()


class FakeMeshComfy(FakeComfy):
    """The fake ComfyUI, plus the checkpoint of Hunyuan3D and a SaveGLB result in /history."""

    def __init__(self):
        super().__init__()
        self.models.add(CKPT)
        self.ws = False                 # the fake's websocket follows qwen-t2i's node ids; progress falls back to time

    def history(self, pid):
        prompt = next((p["prompt"] for p in self.prompts if p.get("prompt_id") == pid), {})
        if self.mode == "success" and any(n.get("class_type") == "SaveGLB" for n in prompt.values()):
            start = ["execution_start", {"prompt_id": pid, "timestamp": 1000}]
            return {"outputs": {"10": {"3d": [{"filename": "hunyuan3d_00001_.glb", "subfolder": "film-lab",
                                               "type": "output"}]}},
                    "status": {"status_str": "success", "completed": True,
                               "messages": [start, ["execution_success", {"prompt_id": pid, "timestamp": 41500}]]}}
        return super().history(pid)


class MeshCase(ComfyCase):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(test_comfy, "MP4", GLB)        # the fake's /view serves this for a non-png file
        p.start()
        self.addCleanup(p.stop)
        self.concept = self.subject("concept.png")
        self.glb = str(self.tmp / "characters" / "ho-giao" / "ho-giao_raw_v01.glb")

    def subject(self, name, size=(1200, 800), box=(300, 200, 900, 600), bg=(255, 255, 255)):
        im = Image.new("RGB", size, bg)
        ImageDraw.Draw(im).rectangle(box, fill=(120, 60, 30))
        path = self.tmp / name
        im.save(path)
        return str(path)

    def server(self):
        f = FakeMeshComfy()
        self.addCleanup(f.stop)
        os.environ["FILM_COMFY_URL"] = f.url
        f.owner = str(self.tmp / "gpu" / "gpu.owner")
        return f

    def run_mesh(self, *extra, image=None, out=None, ledger=True):
        args = ["run", H3D, "--image", image or self.concept, "--seed", "7", "--out", out or self.glb]
        if ledger:
            args += ["--ledger", self.ledger]
        return self.run_comfy(*args, *extra)


class TestGraph(MeshCase):
    def test_graph_values_and_allow_list(self):
        graph, meta, _ = comfy.load_workflow(H3D)
        self.assertEqual((meta["kind"], meta["ledger_model"], meta["model_set"], meta["output"]["ext"]),
                         ("mesh", "comfy:hunyuan3d", "hunyuan3d-2.1", ".glb"))
        for node, inp in (x for v in meta["params"].values() for x in v):
            self.assertIn(inp, graph[node]["inputs"], f"{node}.{inp}")
        self.assertEqual(comfy.graph_classes(graph),
                         {"LoadImage", "ImageOnlyCheckpointLoader", "ModelSamplingAuraFlow", "CLIPVisionEncode",
                          "Hunyuan3Dv2Conditioning", "EmptyLatentHunyuan3Dv2", "KSampler", "VAEDecodeHunyuan3D",
                          "VoxelToMesh", "SaveGLB"})
        self.assertEqual(comfy.disallowed(graph), [])
        m3d = comfy.mesh3d()
        p = {"seed": 5, "steps": 50, "cfg": 5.0, "octree": 512, "num_chunks": 32000}
        g = m3d.fill_graph(comfy._Helpers(), graph, meta, H3D, p, "film-lab_x_concept.png")
        self.assertEqual(comfy.dangling(g), [])
        k = g["7"]["inputs"]
        self.assertEqual((k["seed"], k["steps"], k["cfg"], k["sampler_name"], k["scheduler"], k["denoise"]),
                         (5, 50, 5.0, "euler", "normal", 1.0))
        self.assertEqual((g["8"]["inputs"]["octree_resolution"], g["8"]["inputs"]["num_chunks"]), (512, 32000))
        self.assertEqual(g["1"]["inputs"]["image"], "film-lab_x_concept.png")
        self.assertEqual(g["2"]["inputs"]["ckpt_name"], CKPT)
        self.assertEqual(g["3"]["inputs"], {"model": ["2", 0], "shift": 1.0})
        self.assertEqual(g["4"]["inputs"]["crop"], "center")
        self.assertEqual(g["6"]["inputs"]["resolution"], 4096)
        self.assertEqual((g["9"]["inputs"]["algorithm"], g["9"]["inputs"]["threshold"]), ("surface net", 0.6))
        self.assertEqual(g["10"]["inputs"]["filename_prefix"], "film-lab/hunyuan3d")
        self.assertEqual(graph["8"]["inputs"]["octree_resolution"], 256, "the template is not changed")
        self.assertEqual(comfy.MODEL_INPUTS["ImageOnlyCheckpointLoader"], "ckpt_name")

    def test_source_and_licence_are_named(self):
        meta = comfy.load_workflow(H3D)[1]
        self.assertIn("https://github.com/Comfy-Org/workflow_templates", meta["source"])
        self.assertIn("3d_hunyuan3d-v2.1.json", meta["source"])
        self.assertIn("EU", meta["licence"])
        third = (test_comfy.REPO / "THIRD_PARTY.md").read_text(encoding="utf-8")
        self.assertIn("| `tools/comfy/workflows/hunyuan3d.json` |", third)
        self.assertIn("Tencent Hunyuan", third)

    def test_lock_entry_when_present(self):
        # the hunyuan3d-2.1 lock set is added on another branch; once it is there it must name this checkpoint
        lock = comfy.load_lock()
        entries = [m for m in lock["models"] if m["set"] == "hunyuan3d-2.1"]
        for m in entries:
            self.assertEqual((m["folder"], m["file"]), ("checkpoints", CKPT))

    def test_workflows_lists_it(self):
        code, out, _ = self.run_comfy("workflows")
        self.assertEqual(code, 0)
        self.assertIn("hunyuan3d  Hunyuan3D 2.1 image-to-3D", out)
        self.assertIn("model comfy:hunyuan3d · set hunyuan3d-2.1", out)
        self.assertIn("--octree 256|512 (default 256)", out)
        self.assertIn("Tencent Hunyuan 3D 2.1 Community License", out)


class TestInput(MeshCase):
    def test_bg_check(self):
        m3d = comfy.mesh3d()
        ok = m3d.bg_check(self.concept)
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["white_share"], 1.0)
        grey = m3d.bg_check(self.subject("grey.png", bg=(128, 128, 128)))
        self.assertFalse(grey["ok"])
        self.assertLess(grey["white_share"], 0.01)
        cut = m3d.bg_check(self.subject("cut.png", box=(-200, 100, 700, 700)))    # the body runs off the left edge
        self.assertFalse(cut["ok"])
        self.assertTrue(m3d.bg_check(self.subject("blank.png", box=(-5, -5, -1, -1)))["empty"])
        rgba = Image.new("RGBA", (400, 400), (0, 0, 0, 0))                          # a cut-out counts as white
        ImageDraw.Draw(rgba).ellipse((100, 100, 300, 300), fill=(10, 10, 10, 255))
        rgba.save(self.tmp / "cutout.png")
        self.assertTrue(m3d.bg_check(str(self.tmp / "cutout.png"))["ok"])

    def test_square_input_pads_and_centres(self):
        m3d = comfy.mesh3d()
        dst = str(self.tmp / "sq.png")
        info = m3d.square_input(self.concept, dst)
        self.assertEqual(info["bbox"], [300, 200, 901, 601])
        self.assertFalse(info["touches_edge"])
        with Image.open(dst) as im:
            self.assertEqual(im.size, (1024, 1024))
            px = im.load()
            self.assertEqual(px[5, 5], (255, 255, 255))
            self.assertLess(sum(px[512, 512]), 400)
            row = [x for x in range(1024) if sum(px[x, 512]) < 600]
        width = (row[-1] - row[0] + 1) / 1024
        self.assertAlmostEqual(width, 0.85, delta=0.01, msg="the subject fills 85 % of the side")
        self.assertAlmostEqual((row[0] + row[-1]) / 2, 511.5, delta=2)


class TestRefusals(MeshCase):
    def test_dry_run_sends_nothing(self):
        f = self.server()
        code, out, err = self.run_mesh("--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual(f.calls, [])
        self.assertFalse(os.path.exists(self.ledger))
        self.assertIn("workflow hunyuan3d (comfy:hunyuan3d) · 10 nodes · octree 256 (num_chunks 8000) · steps 30 · "
                      "cfg 5 · seed 7", out)
        self.assertIn("border 100.0% white -> subject cropped, padded to a white 1024x1024 square (85% of the side)", out)
        self.assertIn("models: " + CKPT, out)
        self.assertIn("estimate ~40 s of GPU", out)
        self.assertIn("licence: Tencent Hunyuan 3D 2.1 Community License", out)
        self.assertIn("dry-run: nothing uploaded or queued, no ledger row", out)
        code, out, err = self.run_mesh("--dry-run", "--octree", "512", "--steps", "50")
        self.assertEqual(code, 0, err)
        self.assertIn("octree 512 (num_chunks 32000) · steps 50", out)
        self.assertIn("estimate ~181 s of GPU", out)

    def test_local_refusals(self):
        grey = self.subject("grey.png", bg=(128, 128, 128))
        exists = self.tmp / "characters" / "ho-giao" / "old_raw_v01.glb"
        exists.parent.mkdir(parents=True)
        exists.write_bytes(GLB)
        for extra, kw, want in (
                ((), {"image": grey}, "the background is not plain white"),
                ((), {"image": str(self.tmp / "nope.png")}, "no such file"),
                ((), {"image": self.subject("blank.png", box=(-5, -5, -1, -1))}, "no subject found"),
                ((), {"out": str(self.tmp / "x_v01.png")}, "saves GLB"),
                ((), {"out": str(exists)}, "next free: "),
                (("--octree", "300"), {}, "--octree 300: hunyuan3d knows 256 | 512"),
                (("--steps", "0"), {}, "--steps must be 1..200"),
                (("--cfg", "0"), {}, "--cfg must be > 0"),
                (("--prompt", "a dragon"), {}, "--prompt belong to the other workflows"),
                (("--res", "480p", "--turbo"), {}, "--res, --turbo belong to the other workflows"),
                ((), {"ledger": False}, "run needs --ledger")):
            with self.subTest(want=want):
                code, _, err = self.run_mesh(*extra, **kw)
                self.assertEqual(code, 2, err)
                self.assertIn(want, err)
        code, _, err = self.run_comfy("run", H3D, "--seed", "1", "--out", self.glb, "--ledger", self.ledger)
        self.assertEqual(code, 2)
        self.assertIn("hunyuan3d needs --image", err)
        code, _, err = self.run_still("--octree", "512")
        self.assertEqual(code, 2)
        self.assertIn("--octree/--allow-bg are for the image-to-3D workflow", err)
        code, _, err = self.run_clip(test_comfy.I2V, "--allow-bg")
        self.assertEqual(code, 2)
        self.assertIn("--octree/--allow-bg are for the image-to-3D workflow", err)
        self.assertFalse(os.path.exists(self.ledger))

    def test_allow_bg_sends_a_bad_background_with_a_warning(self):
        grey = self.subject("grey.png", bg=(128, 128, 128))
        code, out, err = self.run_mesh("--dry-run", "--allow-bg", image=grey)
        self.assertEqual(code, 0, err)
        self.assertIn("(--allow-bg)", out)
        self.assertIn("non-white border", err)

    def test_server_without_the_checkpoint_or_nodes(self):
        f = self.server()
        f.models.discard(CKPT)
        code, _, err = self.run_mesh()
        self.assertEqual(code, 2)
        self.assertIn(f"model {CKPT} (ImageOnlyCheckpointLoader.ckpt_name) is not in ComfyUI's", err)
        f.models.add(CKPT)
        f.missing_classes.add("VAEDecodeHunyuan3D")
        code, _, err = self.run_mesh()
        self.assertEqual(code, 2)
        self.assertIn("node VAEDecodeHunyuan3D is not installed", err)
        self.assertEqual([c for c in f.calls if c[0] == "POST"], [])
        self.assertFalse(os.path.exists(self.ledger))


class TestRun(MeshCase):
    def test_happy_path_glb_sidecar_ledger_gpu(self):
        f = self.server()
        code, out, err = self.run_mesh("--octree", "512", "--steps", "50")
        self.assertEqual(code, 0, err)
        self.assertEqual(Path(self.glb).read_bytes(), GLB)
        (prompt,) = f.prompts
        g = prompt["prompt"]
        self.assertEqual(comfy.disallowed(g), [])
        self.assertEqual((g["7"]["inputs"]["seed"], g["7"]["inputs"]["steps"]), (7, 50))
        self.assertEqual((g["8"]["inputs"]["octree_resolution"], g["8"]["inputs"]["num_chunks"]), (512, 32000))
        (name, data), = f.uploads.items()
        self.assertEqual(g["1"]["inputs"]["image"], name)
        self.assertRegex(name, r"^film-lab_[0-9a-f]{12}_concept\.png$")
        with Image.open(io.BytesIO(data)) as im:
            self.assertEqual(im.size, (1024, 1024))
        self.assertIn(("POST", "/prompt", True), [x for x in f.held if x[1] == "/prompt"], "queued under the GPU lock")
        self.assertEqual(len(f.frees), 1, "POST /free before the GPU lock is released")
        self.assertEqual(f.view["filename"], ["hunyuan3d_00001_.glb"])
        side = json.loads(Path(self.glb + ".json").read_text(encoding="utf-8"))
        self.assertEqual((side["workflow"], side["model"], side["seed"], side["steps"], side["octree"]),
                         (H3D, "comfy:hunyuan3d", 7, 50, 512))
        self.assertEqual(side["mesh"], {"verts": 3, "tris": 1})
        self.assertEqual(side["gpu_seconds"], 40.5)
        self.assertEqual(side["input"]["path"], self.concept)
        self.assertEqual(side["input"]["bbox"], [300, 200, 901, 601])
        self.assertTrue(side["input"]["background"]["ok"])
        self.assertIn("EU", side["licence"])
        self.assertIn("blender.py mesh-prep", side["next"])
        self.assertEqual(side["models"][0]["file"], CKPT)
        with open(self.ledger, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual([r["status"] for r in rows], ["pending", "ok"])
        last = rows[-1]
        self.assertEqual((last["kind"], last["model"], last["size"], last["count"], last["out"], last["agent"]),
                         ("image", "comfy:hunyuan3d", "1024x1024", "1", self.glb, "film-animator"))
        self.assertRegex(last["note"], r"^req=[0-9a-f]{32}; seed=7; steps=50; octree=512$")
        self.assertEqual(last["usage"], "gpu_s=40.5")
        self.assertEqual(last["task_id"], prompt["prompt_id"])
        self.assertEqual(comfy.ark.cost_units(last), 0.0)
        self.assertIn("saved " + self.glb + " (3 verts, 1 tris, 40.5 GPU s)", out)
        self.assertIn("next: python tools/blender/blender.py mesh-prep", out)
        code, _, err = self.run_mesh()
        self.assertEqual(code, 2, "versions only go up")
        self.assertIn("next free: ", err)

    def test_execution_error_and_glb_appearing_meanwhile(self):
        f = self.server()
        f.mode = "error"
        code, _, err = self.run_mesh()
        self.assertEqual(code, 1)
        self.assertIn("CUDA out of memory", err)
        self.assertFalse(os.path.exists(self.glb))
        f.mode = "success"
        out2 = str(self.tmp / "characters" / "ho-giao" / "ho-giao_raw_v02.glb")
        f.on_view = lambda: Path(out2).write_bytes(b"someone else's mesh")
        code, _, err = self.run_mesh(out=out2)
        self.assertEqual(code, 1)
        self.assertIn("appeared while this job ran", err)
        self.assertEqual(Path(out2).read_bytes(), b"someone else's mesh")
        with open(self.ledger, newline="", encoding="utf-8") as fh:
            st = [(r["out"][-6:], r["status"]) for r in csv.DictReader(fh)]
        self.assertEqual(st, [("01.glb", "pending"), ("01.glb", "failed"), ("02.glb", "pending"), ("02.glb", "failed")])

    def test_review_publishes_a_model_build(self):
        self.server()
        events = self.tmp / "events.jsonl"
        client = self.tmp / "client.py"
        client.write_text("import json\n"
                          f"LOG = {str(events)!r}\n"
                          "def path_tags(*a):\n    return {'project': 'lab'}\n"
                          "class RV:\n"
                          "    def step(self, label, glb=None, stats=None, **k):\n"
                          "        open(LOG, 'a').write(json.dumps(['step', label, glb, stats]) + '\\n')\n"
                          "class Hook:\n"
                          "    def __init__(self):\n        self.rv, self.key = RV(), None\n"
                          "    def start(self, m, **k):\n        open(LOG, 'a').write(json.dumps(['start', m]) + '\\n')\n"
                          "    def update(self, *a, **k):\n        pass\n"
                          "    def failed(self, m):\n        open(LOG, 'a').write(json.dumps(['failed', m]) + '\\n')\n"
                          "    def finish(self, r, gpu_s=None, message=None):\n"
                          "        open(LOG, 'a').write(json.dumps(['finish', gpu_s]) + '\\n')\n"
                          "def job_hook(build, tool, kind='render', tags=None, label=None, **kw):\n"
                          "    open(LOG, 'a').write(json.dumps(['hook', build, tool, kind, tags, label]) + '\\n')\n"
                          "    return Hook()\n", encoding="utf-8")
        with mock.patch.object(comfy, "REVIEW_CLIENT", str(client)):
            code, _, err = self.run_mesh("--review", "ho-giao-blank")
        self.assertEqual(code, 0, err)
        ev = [json.loads(l) for l in events.read_text().splitlines()]
        self.assertEqual(ev[0], ["hook", "ho-giao-blank", "comfy", "model", {"project": "lab", "engine": "comfy-hunyuan3d"},
                                 "hunyuan3d"])
        self.assertEqual(ev[1][0], "start")
        self.assertEqual(ev[2], ["step", "ho-giao_raw_v01", self.glb, {"verts": 3, "tris": 1}])
        self.assertEqual(ev[3], ["finish", 40.5])


if __name__ == "__main__":
    unittest.main()
