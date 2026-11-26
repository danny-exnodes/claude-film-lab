"""tools/comfy/comfy.py run qwen-edit (issue #68): Qwen-Image-Edit 2511 image edit, local and free. The fake ComfyUI
server of test_comfy.py stands in for the real one; nothing reaches a real server, a GPU or the network."""
import json, os, unittest
from pathlib import Path
from unittest import mock

from PIL import Image

import test_comfy as tc
from helpers import REPO

comfy, ark = tc.comfy, tc.ark
EDIT = "qwen-edit"
LORA4 = "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"
LORA8 = "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors"


class EditCase(tc.ComfyCase):
    def setUp(self):
        super().setUp()
        self.src = self.image("render.png", (1920, 1080), (120, 80, 40))
        self.ref = self.image("concept.png", (800, 800), (10, 200, 10))
        self.edited = str(self.tmp / "edit" / "s21_last_edit_v01.png")

    def run_edit(self, *extra, image=True, out=None, ledger=True):
        args = ["run", EDIT, "--prompt", "repaint the feathers, keep everything else exactly", "--seed", "1717",
                "--out", out or self.edited]
        if image:
            args += ["--image", self.src]
        if ledger:
            args += ["--ledger", self.ledger]
        return self.run_comfy(*(args + list(extra)))

    def graph(self, **kw):
        template, meta, _ = comfy.load_workflow(EDIT)
        v = {"prompt": "p", "negative": "", "seed": 5, "steps": 40, "cfg": 4.0, "denoise": 1.0, "megapixels": 1.0,
             "out_width": 1920, "out_height": 1080, "crop": "disabled", "prefix": "film-lab/qwen-edit",
             "turbo": False, "image": "in.png", "refs": [], "drop": meta["ref_modes"]["full"]["drop"]}
        v.update(kw)
        return comfy.build_graph(template, meta, v), meta


class TestEditGraph(EditCase):
    def test_allow_list_core_nodes_only(self):
        graph, meta, _ = comfy.load_workflow(EDIT)
        classes = comfy.graph_classes(graph)
        self.assertEqual(classes, {"UNETLoader", "CLIPLoader", "VAELoader", "ModelSamplingAuraFlow", "CFGNorm",
                                   "LoraLoaderModelOnly", "LoadImage", "ImageScaleToTotalPixels",
                                   "TextEncodeQwenImageEditPlus", "ReferenceLatent",
                                   "FluxKontextMultiReferenceLatentMethod", "VAEEncode", "KSampler", "VAEDecode",
                                   "ImageScale", "SaveImage"})
        self.assertLessEqual(classes, comfy.ALLOWED_NODES)
        self.assertFalse([c for c in comfy.ALLOWED_NODES if "Minimax" in c or c.endswith("ApiNode")])
        for node, inp in (x for v in meta["params"].values() for x in v):
            self.assertIn(inp, graph[node]["inputs"], f"{node}.{inp}")
        self.assertEqual((meta["kind"], meta["ledger_model"], meta["model_set"]),
                         ("image", "comfy:qwen-edit", "qwen-image-edit-2511"))
        # a workflow JSON holds no comment: the meta names its source, THIRD_PARTY.md has the row
        self.assertIn("image_qwen_image_edit_2511.json", meta["source"])
        self.assertIn(f"| `tools/comfy/workflows/{EDIT}.json` |", (REPO / "THIRD_PARTY.md").read_text(encoding="utf-8"))

    def test_defaults_full_mode_no_lora(self):
        g, _ = self.graph()
        self.assertEqual((comfy.dangling(g), comfy.disallowed(g)), ([], []))
        self.assertNotIn("6", g)                                            # no Lightning LoRA
        self.assertEqual(g["41"]["inputs"]["model"], ["5", 0])               # CFGNorm -> KSampler
        self.assertEqual(g["5"]["inputs"]["model"], ["4", 0])
        self.assertEqual(g["4"]["inputs"]["shift"], 3.1)
        k = g["41"]["inputs"]
        self.assertEqual((k["steps"], k["cfg"], k["denoise"], k["sampler_name"], k["scheduler"], k["seed"]),
                         (40, 4.0, 1.0, "euler", "simple", 5))
        self.assertEqual(k["latent_image"], ["40", 0])                      # VAEEncode of image 1: denoise works
        self.assertEqual(g["40"]["inputs"]["pixels"], ["20", 0])
        self.assertEqual((g["20"]["inputs"]["megapixels"], g["20"]["inputs"]["resolution_steps"]), (1.0, 16))
        self.assertEqual(g["10"]["inputs"]["image"], "in.png")
        for enc in ("30", "31"):                                            # full: encoders see the VAE
            self.assertEqual(g[enc]["inputs"]["vae"], ["3", 0])
            self.assertEqual(g[enc]["inputs"]["image1"], ["20", 0])
        self.assertNotIn("34", g)
        self.assertEqual(g["32"]["inputs"]["conditioning"], ["30", 0])
        self.assertEqual(g["33"]["inputs"]["conditioning"], ["31", 0])
        self.assertEqual(g["32"]["inputs"]["reference_latents_method"], "index_timestep_zero")
        self.assertEqual((g["30"]["inputs"]["prompt"], g["31"]["inputs"]["prompt"]), ("p", ""))
        self.assertEqual(g["43"]["inputs"], {"image": ["42", 0], "upscale_method": "lanczos", "width": 1920,
                                             "height": 1080, "crop": "disabled"})
        self.assertEqual(g["44"]["inputs"]["images"], ["43", 0])

    def test_lightning_refs_vl_size_and_denoise_wiring(self):
        _, meta = self.graph()
        g, _ = self.graph(turbo=True, lora=LORA8, steps=8, cfg=1.0, denoise=0.75, refs=["r1.png", "r2.png"],
                          drop=meta["ref_modes"]["vl"]["drop"], out_width=1344, out_height=768, crop="center")
        self.assertEqual((comfy.dangling(g), comfy.disallowed(g)), ([], []))
        self.assertEqual(g["6"]["inputs"]["lora_name"], LORA8)
        self.assertEqual(g["6"]["inputs"]["model"], ["5", 0])
        self.assertEqual(g["41"]["inputs"]["model"], ["6", 0])
        self.assertEqual((g["41"]["inputs"]["steps"], g["41"]["inputs"]["cfg"], g["41"]["inputs"]["denoise"]),
                         (8, 1.0, 0.75))
        for enc in ("30", "31"):                                            # refs wired to both encoders
            self.assertEqual(g[enc]["inputs"]["image2"], ["11", 0])
            self.assertEqual(g[enc]["inputs"]["image3"], ["12", 0])
            self.assertNotIn("vae", g[enc]["inputs"])                       # vl: refs only seen by the VL encoder
        self.assertEqual((g["11"]["inputs"]["image"], g["12"]["inputs"]["image"]), ("r1.png", "r2.png"))
        self.assertEqual(g["34"]["inputs"], {"conditioning": ["30", 0], "latent": ["40", 0]})
        self.assertEqual(g["32"]["inputs"]["conditioning"], ["34", 0])
        self.assertEqual(g["33"]["inputs"]["conditioning"], ["35", 0])
        self.assertEqual((g["43"]["inputs"]["width"], g["43"]["inputs"]["height"], g["43"]["inputs"]["crop"]),
                         (1344, 768, "center"))
        g4, _ = self.graph(turbo=True, lora=LORA4, refs=["r1.png"])
        self.assertEqual(g4["6"]["inputs"]["lora_name"], LORA4)
        self.assertNotIn("image3", g4["30"]["inputs"])
        self.assertNotIn("12", g4)

    def test_lock_has_the_edit_models(self):
        lock = comfy.load_lock()
        graph, meta, _ = comfy.load_workflow(EDIT)
        files = {f: e for *_, e, f in comfy.model_entries(graph, lock)}
        self.assertTrue(all(files.values()), files)
        self.assertEqual(files["qwen_image_edit_2511_fp8mixed.safetensors"]["set"], "qwen-image-edit-2511")
        self.assertEqual(files["qwen_2.5_vl_7b_fp8_scaled.safetensors"]["set"], "qwen-image")   # shared with t2i
        by_file = {m["file"]: m for m in lock["models"]}
        for n in ("4", "8"):
            self.assertIn(meta["lightning"][n]["lora"], by_file)
            self.assertIn(EDIT, by_file[meta["lightning"][n]["lora"]]["workflows"])
        self.assertEqual(lock["sets"]["qwen-image-edit-2511"]["requires"], ["qwen-image"])


class TestEditRun(EditCase):
    def test_dry_run_sends_nothing(self):
        f = self.server()
        code, out, err = self.run_edit("--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual(f.calls, [])
        self.assertFalse(os.path.exists(self.ledger))
        self.assertIn("workflow qwen-edit (comfy:qwen-edit) · 16 nodes · 1920x1080 · steps 40 · cfg 4 · "
                      "denoise 1 · seed 1717", out)
        self.assertIn("1920x1080 -> ~1360x768 working (1 MP, multiple of 16) -> 1920x1080 output lanczos", out)
        self.assertIn("estimate ~248 s of GPU", out)                       # 8 + 40 x 3 x 2 (cfg > 1)
        self.assertIn("dry-run: nothing uploaded or queued, no ledger row", out)
        code, out, err = self.run_edit("--dry-run", "--lightning", "4", "--ref", self.ref, "--ref", self.ref,
                                       "--denoise", "0.8", "--size", "1344x768", "--ref-mode", "vl")
        self.assertEqual(code, 0, err)
        self.assertIn("· 1344x768 · steps 4 · cfg 1 (lightning 4 LoRA) · denoise 0.8 · seed 1717", out)
        self.assertIn(f"Picture 2: {self.ref} (ref-mode vl)", out)
        self.assertIn("Picture 3:", out)
        self.assertIn(LORA4, out)
        self.assertIn("estimate ~36 s of GPU", out)                        # 8 + 4 x 3 + 2 refs x 8
        self.assertEqual(f.calls, [])
        code, out, err = self.run_edit("--dry-run", "--size", "1000x1000")
        self.assertEqual(code, 0, err)
        self.assertIn("another aspect than the input", err)
        self.assertIn("(center crop)", out)

    def test_local_refusals(self):
        f = self.server()
        (self.tmp / "edit").mkdir()
        old = self.tmp / "edit" / "old_v01.png"
        old.write_bytes(tc.PNG)
        for extra, kw, want in (
                (["--lightning", "4", "--negative", "blurry"], {}, "--negative is refused at cfg 1 (--lightning 4)"),
                (["--cfg", "1", "--negative", "blurry"], {}, "--negative is refused at cfg 1"),
                (["--ref", self.ref, "--ref", self.ref, "--ref", self.ref], {}, "takes 0..2 --ref images"),
                ([], {"image": False}, "needs --image IN.png"),
                (["--denoise", "0"], {}, "--denoise must be > 0 and <= 1"),
                (["--denoise", "1.5"], {}, "--denoise must be > 0 and <= 1"),
                (["--turbo"], {}, "--turbo do not apply (speed LoRA: --lightning 4|8"),
                (["--seconds", "5"], {}, "--seconds do not apply"),
                (["--last", self.src], {}, "--last do not apply"),
                (["--ref", str(self.tmp / "nope.png")], {}, "no such file"),
                (["--size", "10x10"], {}, "each side must be 64..4096"),
                ([], {"out": str(old)}, "next free: "),
                ([], {"out": str(self.tmp / "edit" / "x_v01.jpg")}, "saves PNG"),
                ([], {"ledger": False}, "run needs --ledger")):
            with self.subTest(extra=extra, kw=kw):
                code, out, err = self.run_edit(*extra, **kw)
                self.assertEqual(code, 2, out + err)
                self.assertIn(want, err)
        self.assertIn("with cfg 1 the sampler never uses the negative prompt", self.run_edit(
            "--lightning", "8", "--negative", "x")[2])
        self.assertFalse(os.path.exists(self.ledger), "a refusal writes no ledger row")
        self.assertEqual(f.calls, [], "a refusal contacts nothing")
        # the edit flags belong to qwen-edit only
        code, _, err = self.run_still("--lightning", "4")
        self.assertEqual(code, 2)
        self.assertIn("--lightning belong to qwen-edit", err)
        code, _, err = self.run_clip(tc.I2V, "--denoise", "0.5")
        self.assertEqual(code, 2)
        self.assertIn("--denoise belong to qwen-edit", err)
        code, _, err = self.run_still("--image", self.src)
        self.assertIn("to edit an image: qwen-edit --image", err)

    def test_negative_allowed_when_cfg_above_1(self):
        self.server()
        code, out, err = self.run_edit("--dry-run", "--negative", "blurry, extra legs")
        self.assertEqual(code, 0, err)
        self.assertIn("negative:\n  blurry, extra legs", out)
        code, out, err = self.run_edit("--dry-run", "--lightning", "4", "--cfg", "2", "--negative", "x")
        self.assertEqual(code, 0, err)
        self.assertIn("distilled for cfg 1", err)

    def test_happy_path_uploads_ledger_sidecar(self):
        f = self.server()
        code, out, err = self.run_edit("--lightning", "4", "--ref", self.ref, "--denoise", "0.85")
        self.assertEqual(code, 0, err)
        self.assertEqual(Path(self.edited).read_bytes(), tc.PNG)
        (prompt,) = f.prompts
        g = prompt["prompt"]
        self.assertEqual(comfy.disallowed(g), [])
        self.assertEqual(sorted(f.uploads), sorted([g["10"]["inputs"]["image"], g["11"]["inputs"]["image"]]))
        self.assertRegex(g["10"]["inputs"]["image"], r"^film-lab_[0-9a-f]{12}_image1\.png$")
        self.assertEqual(f.uploads[g["10"]["inputs"]["image"]], Path(self.src).read_bytes())   # uploaded as is
        self.assertEqual(f.uploads[g["11"]["inputs"]["image"]], Path(self.ref).read_bytes())
        self.assertEqual((g["41"]["inputs"]["steps"], g["41"]["inputs"]["cfg"], g["41"]["inputs"]["denoise"]),
                         (4, 1.0, 0.85))
        self.assertEqual(g["6"]["inputs"]["lora_name"], LORA4)
        self.assertEqual((g["43"]["inputs"]["width"], g["43"]["inputs"]["height"]), (1920, 1080))
        for v in range(1, 5):
            self.assertIn(f"step {v}/4 elapsed", out)                      # websocket progress of node 41
        rows = self.rows()
        self.assertEqual([r["status"] for r in rows], ["pending", "ok"])
        last = rows[-1]
        self.assertEqual((last["kind"], last["model"], last["size"], last["count"], last["task_id"]),
                         ("image", "comfy:qwen-edit", "1920x1080", "1", prompt["prompt_id"]))
        self.assertEqual(ark.cost_units(last), 0.0)
        self.assertIn("seed=1717", last["note"])
        side = json.loads(Path(self.edited + ".json").read_text(encoding="utf-8"))
        self.assertEqual((side["workflow"], side["model"], side["lightning"], side["denoise"], side["ref_mode"],
                          side["input_size"], side["working_size"], side["crop"]),
                         (EDIT, "comfy:qwen-edit", "4", 0.85, "full", [1920, 1080], [1360, 768], "disabled"))
        self.assertEqual(side["inputs"]["image1"]["path"], self.src)
        self.assertEqual(side["inputs"]["image2"]["size"], [800, 800])
        self.assertEqual(f.frees, [{"unload_models": True, "free_memory": True}])   # VRAM back before the lock goes
        self.assertFalse((self.tmp / "gpu" / "gpu.owner").exists())

    def test_never_overwrites_and_rechecks_after_the_gpu_wait(self):
        f = self.server()
        Path(self.edited).parent.mkdir(parents=True)
        Path(self.edited).write_bytes(b"keep me")
        code, _, err = self.run_edit()
        self.assertEqual(code, 2, err)
        self.assertEqual(Path(self.edited).read_bytes(), b"keep me")
        self.assertEqual(f.prompts, [])
        out2 = str(self.tmp / "edit" / "s21_last_edit_v02.png")
        orig = comfy.hold_gpu

        def appear(wid):                    # another run with the same --out finished while this one waited
            orig(wid)
            Path(out2).write_bytes(b"other run")
        with mock.patch.object(comfy, "hold_gpu", appear):
            code, _, err = self.run_edit(out=out2)
        self.assertEqual(code, 2, err)
        self.assertIn("appeared while this run waited for the GPU", err)
        self.assertEqual(Path(out2).read_bytes(), b"other run")
        self.assertEqual((f.prompts, f.uploads), ([], {}))
        self.assertFalse(os.path.exists(self.ledger))

    def test_review_hook_gets_the_image(self):
        self.server()
        hook = mock.MagicMock()
        with mock.patch.object(comfy, "review_hook", return_value=hook) as rh:
            code, out, err = self.run_edit("--lightning", "8", "--review", "edit-a", "--keep-models")
        self.assertEqual(code, 0, err)
        self.assertEqual(rh.call_args.args[1], "image")
        (im,) = hook.image.call_args_list
        self.assertEqual(im.args, (self.edited, "s21_last_edit_v01"))
        self.assertEqual((im.kwargs["model"], im.kwargs["sampler_steps"], im.kwargs["width"]),
                         ("comfy:qwen-edit lightning8", 8, 1920))
        hook.finish.assert_called_once()

    def test_keep_models_skips_free(self):
        f = self.server()
        code, _, err = self.run_edit("--lightning", "4", "--keep-models")
        self.assertEqual(code, 0, err)
        self.assertEqual(f.frees, [])

    def test_paid_or_custom_node_module_is_refused_on_the_server(self):
        f = self.server()
        f.modules = {"TextEncodeQwenImageEditPlus": "comfy_api_nodes.nodes_qwen"}
        code, _, err = self.run_edit("--lightning", "4")
        self.assertEqual(code, 2, err)
        self.assertIn("comes from comfy_api_nodes.nodes_qwen", err)
        self.assertEqual((f.prompts, f.uploads), ([], {}))
        self.assertFalse(os.path.exists(self.ledger))
        f.modules = {"KSampler": "custom_nodes.evil_pack.nodes"}
        code, _, err = self.run_edit("--lightning", "4")
        self.assertEqual(code, 2, err)
        self.assertIn("custom nodes never run from here", err)
        f.modules = {"KSampler": "nodes", "TextEncodeQwenImageEditPlus": "comfy_extras.nodes_qwen",
                     "ImageScale": "comfy_extras.v3.odd"}
        code, _, err = self.run_edit("--lightning", "4")
        self.assertEqual(code, 0, err)
        f.modules = {"ImageScale": "somewhere_else"}
        code, _, err = self.run_edit("--lightning", "4", out=str(self.tmp / "edit" / "b_v01.png"))
        self.assertEqual(code, 0, err)                                       # unknown module: a warning only
        self.assertIn("check that it is a core node", err)

    def test_workflows_lists_qwen_edit(self):
        code, out, _ = self.run_comfy("workflows")
        self.assertEqual(code, 0)
        self.assertIn("qwen-edit  Qwen-Image-Edit 2511", out)
        self.assertIn("model comfy:qwen-edit · set qwen-image-edit-2511", out)
        self.assertIn("--lightning 4: 4 steps, cfg 1 · --lightning 8: 8 steps, cfg 1", out)
        self.assertIn("--size WxH (default: the input's)", out)


if __name__ == "__main__":
    unittest.main()
