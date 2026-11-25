# Local backends for AI Film Lab: ComfyUI + Blender (research, 2026-11-25)

Target box: Windows 11, RTX 5070 Ti 16 GB (Blackwell, sm_120), Core Ultra 9 285K, 127 GB RAM, Blender 5.3 installed,
ComfyUI not installed, **C: 16 GB free, D: 67 GB free**. Repo tests run in WSL Ubuntu, Python 3.12, no GPU.

Sizes below are decimal GB (1e9 bytes) read from the Hugging Face API (`/api/models/<repo>/tree/main/<dir>`) on 2026-11-25,
which also returns each file's `lfs.oid` = SHA-256 (useful for hash pinning, see A5).
"**Unverified**" = I could not confirm it from a primary source; treat as an estimate or something to measure.

---

## TL;DR

* **ComfyUI install:** Windows **portable** build `ComfyUI_windows_portable_nvidia.7z` (1.94 GB, CUDA 13.0 / Python 3.13,
  current stable v0.46.0, 2026-11-18), extracted to **D:**. Not the Desktop app (auto-updates; defaults on C:).
* **Default image-to-video (~31 GB):** **Wan 2.2 I2V-A14B** (Apache-2.0), GGUF Q5_K_M high+low experts + umt5 fp8 text
  encoder + Wan 2.1 VAE + lightx2v 4-step LoRAs. Native-fp8 alternative is 35.6 GB without the LoRAs.
* **Fast draft:** the same Wan 14B files at 832×480, 4 steps (lightx2v), 49–81 frames, so nothing extra to download. If you want a
  separate small model, use **Wan 2.2 TI2V-5B**: +11.4 GB, 1280×704 at 24 fps, shares the text encoder.
* **Blender-driven path (phase 2):** **LTX-2.5 (22B) + `LTX-2.5-22b-IC-LoRA-Layout-To-Render`** is made for this job:
  it takes a grey-box Blender playblast plus a styled first frame and returns a finished shot. It needs about 33–41 GB more,
  is gated, and is under the LTX-2 Community License (free under $10M annual revenue). With D: at 67 GB, the Wan stack and the LTX
  stack together do **not** fit with ComfyUI and outputs. Run a bake-off and keep one, or add disk. The cheap Apache alternative for
  depth/pose-guided video is **Wan 2.2 Fun Control 5B** (+11.4 GB).
* **Blender:** `blender.exe -b --factory-startup -P scene.py -- --shot shot.json`. Cycles OptiX supports RTX 50 (since 4.4).
  EEVEE (`BLENDER_EEVEE` since 5.0) needs a GPU context. That works in a normal Windows desktop session, but treat it as unverified
  for service or SSH sessions and in WSL.
* **WSL tests:** the `bpy` wheel exists (`bpy==5.3.0`, Linux x86-64 wheel 428 MB), but **it requires Python 3.13 exactly**
  (since bpy 5.1). Python 3.12 in WSL cannot install it. Use a `uv`-managed 3.13 venv only for the Blender tests.

---

## A. ComfyUI

### A1. Install on Windows for RTX 50-series

Options ([README](https://github.com/comfyanonymous/ComfyUI), [portable docs](https://docs.comfy.org/installation/comfyui_portable_windows)):

| Option | What it is | Fit for us |
|---|---|---|
| **Comfy Desktop** | Installer app, "the easiest and best way to get started"; config in `%APPDATA%\ComfyUI\extra_models_config.yaml` | Auto-updates (bad for pinning); its user/config data sits on C:. Not recommended here. |
| **Windows portable** | 7z with `python_embeded\`, `ComfyUI\`, `update\`, `run_nvidia_gpu.bat`, `advanced\` | **Recommended.** Self-contained, put on D:, and updates happen only when you run them. |
| **git + venv / comfy-cli** | `pip install comfy-cli && comfy install` or manual clone | Fine for a dev, but you manage torch yourself. comfy-cli is still useful *on top of* portable (A2). |

Portable assets for **v0.46.0 (2026-11-18)** ([release assets](https://github.com/Comfy-Org/ComfyUI/releases/expanded_assets/v0.46.0)):
`ComfyUI_windows_portable_nvidia.7z` **1.94 GB** (CUDA 13.0, Python 3.13, "modern RTX"), `..._nvidia_cu126.7z` 1.84 GB
(Python 3.12, for 10-series and older). The release workflow builds the embedded Python 3.13.6
([stable-release.yml](https://github.com/Comfy-Org/ComfyUI/blob/master/.github/workflows/stable-release.yml)). The exact bundled
torch version is **unverified** because it comes from a cached dependency archive and is not printed. Check it after unpacking:

```bat
python_embeded\python.exe -c "import torch;print(torch.__version__, torch.version.cuda, torch.cuda.get_arch_list())"
:: expect +cu130 and 'sm_120' in the arch list
```

PyTorch context: since **2.11** the default PyPI wheels are CUDA 13.0 ([2.11 blog](https://pytorch.org/blog/pytorch-2-11-release/),
[dev-discuss](https://dev-discuss.pytorch.org/t/transitioning-pypi-cuda-wheels-to-cuda-13-0-as-the-stable-release-2-11/3325)).
The current PyPI torch is **2.15.0 (2026-10-28)**. The README says NVIDIA users should be on cu130 or newer, that torch older than about 6 months
should be updated, and that Python 3.13 is "very well supported" (3.14 works, but some custom nodes may have issues).

Blackwell caveats (from the [RTX 50 support thread](https://github.com/Comfy-Org/ComfyUI/discussions/6643) and others; most date
from 2025, before cu128/cu130 stable, so many no longer apply):
* **Custom nodes can silently replace torch** (with CPU or older CUDA wheels), and then sm_120 kernels are missing. After every node install,
  re-run the check above. Prefer `comfy node install ... --no-deps` or installing node requirements by hand.
* `xformers` installs could downgrade torch. Not needed: ComfyUI uses PyTorch SDPA by default.
* SageAttention / triton-windows can work, but the global `--use-sage-attention` flag was reported to give **black output with
  Wan/Qwen**. Leave it off at first.
* Driver: Blackwell needs R570+ (CUDA 12.8+), and cu130 wheels need a CUDA-13-capable driver (R580+, **unverified** exact minimum).
  Update the Studio driver first.
* **Disk:** C: has only 16 GB. Keep ComfyUI, models, the HF cache (`HF_HOME=D:\hf`), pip/uv caches and `--temp-directory` on D:.

Useful launch flags ([cli_args.py](https://raw.githubusercontent.com/Comfy-Org/ComfyUI/master/comfy/cli_args.py)):
`--listen 127.0.0.1 --port 8188 --disable-auto-launch --output-directory D:\... --input-directory D:\... --temp-directory D:\...
--extra-model-paths-config <yaml> --offline` (blocks partner/API nodes; replaces the deprecated `--disable-api-nodes`),
`--reserve-vram GB`, `--enable-dynamic-vram`/`--disable-dynamic-vram`, `--cache-none|--cache-lru N`, `--deterministic`,
`--disable-all-custom-nodes --whitelist-custom-nodes ...`, `--disable-metadata`, `--log-stdout`, `--verbose`.
Use `--lowvram`/`--novram` only if dynamic VRAM fails. With 127 GB RAM, offloading the 14–22B models is fine.

### A2. Headless/API use

**HTTP routes** (from [server.py](https://raw.githubusercontent.com/Comfy-Org/ComfyUI/master/server.py) and
[docs](https://docs.comfy.org/development/comfyui-server/comms_routes)). Every route is also mounted under `/api/...`.

| Route | Use |
|---|---|
| `POST /prompt` | Body `{"prompt": <API-format graph>, "client_id": "<uuid>", "prompt_id": "<optional uuid>", "extra_data": {...}, "front": bool}`. 200 → `{"prompt_id","number","node_errors"}`; 400 → `{"error","node_errors"}` (validation happens before queueing, so it is a free check). |
| `GET /history/{prompt_id}` | `outputs[node_id]` → lists of `{filename, subfolder, type}` (key `images`; video save nodes may use other keys, so read all keys: **unverified** per node) plus `status`. |
| `GET /view?filename=&subfolder=&type=output` | Download a file (`preview=webp;90`, `channel=rgb/a/rgba`). |
| `POST /upload/image` | multipart `image`, `type` (`input`), `subfolder`, `overwrite`. Identical content is de-duplicated; different content with the same name gets a `(n)` suffix, so use unique names or `overwrite=true`. Default max upload is 100 MB (`--max-upload-size`). On the same machine, writing into `input/` directly is simpler. |
| `GET /object_info[/{class}]` | Node schemas. Use them to validate that a workflow's node classes exist before submitting. |
| `GET/POST /queue`, `POST /interrupt`, `POST /free` | Queue status, clear, stop, unload models / free memory. |
| `GET /system_stats` | ComfyUI version, Python, torch, devices, VRAM. Log this with every job. |
| `GET /api/jobs`, `/api/jobs/{id}`, `POST /api/jobs/{id}/cancel` | Newer job API (local server exposes it under `/api` only). |

**WebSocket** `ws://127.0.0.1:8188/ws?clientId=<uuid>` ([execution.py](https://raw.githubusercontent.com/Comfy-Org/ComfyUI/master/execution.py)):
`status`, `execution_start`, `execution_cached {nodes}`, `executing {node, prompt_id}`, `progress {value,max,node}`,
`executed {node, output}`, `execution_success`, `execution_error {node_id, node_type, exception_message, traceback}`,
`execution_interrupted`. Binary frames are latent previews, so skip them. Per-node messages are only sent if you passed `client_id`.
Completion: `execution_success` (or the classic `executing` with `node == null` for your `prompt_id`, as in the official
[websockets_api_example.py](https://raw.githubusercontent.com/Comfy-Org/ComfyUI/master/script_examples/websockets_api_example.py)).
Then read `/history/{prompt_id}` and download each output with `/view`. A fully cached prompt finishes almost at once, but its outputs
are still listed in history.

**API-format export:** in the frontend, **File → Export Workflow (API)** ([docs](https://docs.comfy.org/development/api-development/workflow-api-format)).
Older UIs used "Save (API Format)" after enabling dev mode. API format is `{node_id: {class_type, inputs}}` with no layout data.
UI-format JSON (`nodes`/`links`) is rejected by the API (the Cloud API returns `workflow_format_ui`). In API JSON, seeds are literal values:
`control_after_generate` is UI-only.

**comfy-cli** ([repo](https://github.com/Comfy-Org/comfy-cli), PyPI `comfy-cli` **1.29.0**, 2026-11-24): `comfy launch --background`,
`comfy stop`, `comfy run --workflow f.json [--wait]` (auto-converts UI format), `comfy jobs wait|status|watch <id>`,
`comfy download <id>`, `comfy node install|registry-install --version`, `comfy node save-snapshot|restore-snapshot`,
`comfy node deps-in-workflow`, `comfy model download --url ... --relative-path ...` (reads HF token from `HF_API_TOKEN` env),
`comfy system-stats`, `comfy free`. Telemetry is opt-in; set `DO_NOT_TRACK=1`.
**Recommendation:** use comfy-cli for **ops** (node pinning, snapshots, model download). For the pipeline, write our own **~200-line
stdlib + `websocket-client` client** in `tools/` (same pattern as `ark.py`: dry-run, exit codes, ledger line, no retries
on ambiguous failures). Reasons: we need exact control over input patching, output naming per `docs/CONVENTIONS.md`, and logging.
The client can be unit-tested in WSL against a fake server. I found no official first-party Python SDK besides the example scripts.

### A3. Local video models that fit 16 GB VRAM (Nov 2026)

All of these run on 16 GB with ComfyUI's dynamic VRAM / weight offload to system RAM (127 GB is plenty). VRAM is not the
binding limit here; **time and disk are.** All timings are estimates (**unverified** on a 5070 Ti) unless a source is cited.

| Model (date) | License | ComfyUI | Native output | Notes |
|---|---|---|---|---|
| **Wan 2.2 I2V/T2V-A14B** (Jul 2025) | **Apache-2.0** | Native | 480p/720p, **16 fps, 81 frames (5 s)** default ([config](https://raw.githubusercontent.com/Wan-Video/Wan2.2/main/wan/configs/shared_config.py)); two experts (high-noise / low-noise) | Most mature ecosystem: FLF2V, Fun-Control/Inpaint/Camera, VACE, Animate, lightx2v 4-step LoRAs. Good with stylized looks (community consensus, **unverified** for ink-wash). Official doc: 4-step LoRA cut 640×640×81 from about 524 s to 138 s on an RTX 4090D ([doc](https://docs.comfy.org/tutorials/video/wan/wan2-2-fun-control)). **Estimate on 5070 Ti: 480p 3–5 min, 720p 10–15 min (4 steps).** |
| **Wan 2.2 TI2V-5B** (Jul 2025) | Apache-2.0 | Native | **1280×704, 24 fps, 121 frames** ([card](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B)) | "Fits 8 GB with native offloading"; official claim is under 9 min for 5 s at 720p on one consumer GPU. Lower quality than 14B. |
| **LTX-2.5 22B** (Jul 2026; ComfyUI day-0 2026-08-12) | LTX-2.x Community License: **free commercial use below $10M annual revenue** ([card](https://huggingface.co/Lightricks/LTX-2.5)) | Native templates (T2V, I2V, FLF2V, DFR); **gated repo** (accept the license, needs an HF token) | W/H divisible by 32 (64 for Layout LoRA), frames = 8k+1, 24/25/50 fps, two-stage 960×544 → 1920×1088 | Audio and video together, multishot, many IC-LoRAs (Layout-To-Render, Colorization, Restore, Pixel upscaler, Clean-Plate...). Distilled model: 8 + 3 steps. NVFP4 build is Blackwell-native. One user reported VAE decode freezing for 10 s clips on a 5090 ([discussion](https://huggingface.co/Lightricks/LTX-2.5/discussions)). Speed on 16 GB is **unverified**; NVIDIA lists the 5070 Ti as the recommended floor for LTX-2.3 720p ([NVIDIA guide](https://www.nvidia.com/en-gb/geforce/news/rtx-ai-video-generation-guide)). |
| LTX-2.3 22B (Mar 2026) | same | Native | same rules; FLF2V, IC-LoRA Union Control (depth/canny/pose) | Superseded by 2.5, but **Union-Control (depth/canny/pose) is documented for 2.3** ([doc](https://docs.comfy.org/tutorials/video/ltx/ltx-2-3)). Whether it carries over to 2.5 is **unverified** (the card says "most LoRAs" carry over). |
| **HunyuanVideo 1.5 8.3B** (Nov 2025) | Tencent Hunyuan Community: **not licensed in EU/UK/South Korea**, >100M MAU needs a license ([LICENSE](https://huggingface.co/tencent/HunyuanVideo-1.5)) | Native | 480p/720p, 121 frames (about 5 s at 24 fps), SR to 1080p | 14 GB minimum with offload. Step-distilled 480p I2V: "within 75 s on a 4090" (8–12 steps). Good faces/motion. A license risk if the channel monetizes in the EU. |
| Others seen in ComfyUI core in 2026 | | | | Kandinsky 5 Video, Cosmos Predict2, Mochi, CogVideoX (older or weaker). **Bernini-R** (ByteDance, Apache, Wan2.2-based **video editing**, [repo](https://huggingface.co/Comfy-Org/Bernini-R)) and **SCAIL-2** (zai-org, MIT, Wan2.1-14B character animation) are new. Wan 2.5/2.6/3.0 are **API-only**: the Wan-AI HF org has nothing newer than Wan2.2 (incl. Animate-2, 2026-07). |

**Exact files (Comfy layout, `ComfyUI/models/<folder>/`):**

*Wan 2.2 I2V-A14B, recommended default (GGUF, needs [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) custom node):*

| File | Folder | Source | GB |
|---|---|---|---|
| `Wan2.2-I2V-A14B-HighNoise-Q5_K_M.gguf` | `diffusion_models/` (or `unet/`) | [QuantStack/Wan2.2-I2V-A14B-GGUF](https://huggingface.co/QuantStack/Wan2.2-I2V-A14B-GGUF) `HighNoise/` | 10.79 |
| `Wan2.2-I2V-A14B-LowNoise-Q5_K_M.gguf` | same | same, `LowNoise/` | 10.79 |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `text_encoders/` | [Comfy-Org/Wan_2.1_ComfyUI_repackaged](https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged) `split_files/text_encoders/` | 6.74 |
| `wan_2.1_vae.safetensors` | `vae/` | [Comfy-Org/Wan_2.2_ComfyUI_Repackaged](https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged) `split_files/vae/` | 0.25 |
| `wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors` | `loras/` | same repo, `split_files/loras/` | 1.23 |
| `wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors` | `loras/` | same | 1.23 |
| **Total** | | | **31.03** |

Native alternative without a custom node: `wan2.2_i2v_{high,low}_noise_14B_fp8_scaled.safetensors` at 14.29 GB each, so
35.57 GB with the encoder and VAE, or 38.03 GB with the LoRAs. Q4_K_M experts are 9.65 GB each (total 28.75 GB). The same set gives **FLF2V** (`WanFirstLastFrameToVideo`, core).

*Wan 2.2 TI2V-5B (draft / small model):* `wan2.2_ti2v_5B_fp16.safetensors` 10.00 + `wan2.2_vae.safetensors` 1.41
(+ the same umt5 encoder). That is **+11.41 GB** on top of the Wan default (18.15 GB standalone).

*LTX-2.5 (all from [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5), gated; [ComfyUI doc](https://docs.comfy.org/tutorials/video/ltx/ltx-2-5)):*

| File | Folder | GB |
|---|---|---|
| `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` (official Comfy pick) **or** `...-distilled-transformer-nvfp4.safetensors` (Blackwell FP4) **or** `unsloth/LTX-2.5-GGUF` `distilled/ltx-2.5-22b-distilled-Q4_K_M.gguf` | `diffusion_models/` | 21.50 / 18.72 / 13.58 |
| `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` | `text_encoders/` | 15.37 |
| `ltx-2.5-video-vae-bf16.safetensors` | `vae/` | 1.47 |
| `ltx-2.5-audio-vae-bf16.safetensors` | `vae/` | 0.36 |
| `ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors` | `latent_upscale_models/` | 1.00 |
| `ltx-2.5-22b-ic-lora-layout-to-render-1.0.safetensors` ([repo](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render)) | `loras/` | 1.31 |
| **Total** int8 / nvfp4 / GGUF-Q4 | | **41.0 / 38.2 / 33.1** |

Whether IC-LoRAs apply cleanly to a GGUF-quantized base is **unverified**. The NVFP4 distilled checkpoint had a shape-mismatch bug in the
I2V template that a thread marks fixed (**unverified**). Optional prompt enhancer `gemma4_e2b_it_int8_convrot` is about 5 GB.

*HunyuanVideo 1.5 compact I2V ([Comfy-Org/HunyuanVideo_1.5_repackaged](https://huggingface.co/Comfy-Org/HunyuanVideo_1.5_repackaged)):*
`hunyuanvideo1.5_720p_i2v_cfg_distilled_fp8_scaled` 8.33, `qwen_2.5_vl_7b_fp8_scaled` 9.38, `byt5_small_glyphxl_fp16` 0.44,
`hunyuanvideo15_vae_fp16` 2.52, `sigclip_vision_patch14_384` (size not checked), optional `hunyuanvideo1.5_1080p_sr_distilled_fp8_scaled` 8.34.
That is about 21 GB, or about 29 GB with SR.

**Recommendation**
* **Default image-to-video: Wan 2.2 I2V-A14B (GGUF Q5_K_M + lightx2v 4-step), 31.0 GB.** It is Apache-2.0, ungated and mature, and it
  works the same way as the current Seedance step (start frame in, 5 s clip out). FLF2V is included. Run it at 1280×720 (W/H multiple of 16, frames 4k+1),
  16 fps, 81 frames. Bring it to 24 fps with RIFE and to 1080p with an upscaler (A4).
* **Fast draft: the same files at 832×480, 4 steps, 49–81 frames.** No extra download; the draft and the final come from the same model, so motion
  carries over (same seed, re-render at 720p, though the result is not identical across resolutions). Optional second model: TI2V-5B (+11.4 GB).
* **Phase 2, decided by a bake-off on 2–3 real shots: LTX-2.5 distilled + Layout-To-Render** (A4/C). Disk: the Wan default (31) + LTX (33–41) +
  ComfyUI (about 8, **unverified** unpacked size) + outputs is more than D:'s 67 GB, so keep one stack or add a drive.

### A4. Extras for our pipeline

| Need | Option | Core or custom |
|---|---|---|
| First-last-frame | Wan 2.2 `WanFirstLastFrameToVideo` (same I2V files); LTX-2.5 FLF2V template | **Core** |
| Depth/pose/canny-guided video from Blender passes | **Wan 2.2 Fun Control** (`Wan22FunControlToVideo`; Canny, Depth, OpenPose, MLSD, trajectory; takes a start image) ([doc](https://docs.comfy.org/tutorials/video/wan/wan2-2-fun-control)). 14B fp8 is 2×14.30 GB; **5B bf16 is 10.00 GB** (+`wan2.2_vae`). Wan 2.2 Fun VACE 14B fp8 is 2×17.35 GB. | Model and node **core**. Preprocessors beyond Canny need `comfyui_controlnet_aux`, which we **skip**: Blender gives clean depth/normal/lines directly. |
| | **LTX-2.5 IC-LoRA Layout-To-Render**: input is a grey-clay or blocky playblast (camera, motion, placement) plus a styled first frame (optionally mid/last keyframes). Two stages: 960×544 at 8 steps, then 2× to 1920×1088 at 3 steps; 24 fps; W/H divisible by 64; strength 1.0, CFG 1, `euler_ancestral`; avoid the words "clay/3D" in prompts ([card](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render)). | Core LTX nodes plus the workflow JSON shipped in the repo |
| | LTX-2.3 IC-LoRA Union Control (depth/canny/pose; uses MoGe geometry model) | Core |
| | Bernini-R (Wan2.2 video **editing**, Apache) as a video-to-video restyle candidate | Core template |
| Frame interpolation | **Core** `FrameInterpolationModelLoader` + `Frame Interpolate` (FILM or RIFE). Models from [Comfy-Org/frame_interpolation](https://huggingface.co/Comfy-Org/frame_interpolation): `film_net_fp16` 0.07 GB, `rife_v4.26` 0.02 GB, `rife_v4.25_heavy` 0.09 GB → `models/frame_interpolation/`. Legacy pack [Fannovel16/ComfyUI-Frame-Interpolation](https://github.com/Fannovel16/ComfyUI-Frame-Interpolation) (custom, 1.0.11). | Core (the docs' template page still mentions custom nodes; **unverified** which) |
| Video upscaling | LTX latent x2 upscaler (inside the LTX workflow); **SeedVR2** 3B/7B (Apache; fp8/int8/**nvfp4** builds in [Comfy-Org/SeedVR2](https://huggingface.co/Comfy-Org/SeedVR2)); **RelayVSR** x2/x4 ([Comfy-Org/RelayVSR](https://huggingface.co/Comfy-Org/RelayVSR)); NVIDIA RTX Video Super Resolution node (NVIDIA guide) | Core packaging (sizes not checked) |
| Depth from AI images (reverse direction) | Depth-Anything-3, MoGe-2 in core `geometry_estimation/` | Core |

### A5. Reproducibility

* **Seeds:** API JSON holds literal seed ints (`KSampler.seed`, `RandomNoise.noise_seed`, etc.). Always set them explicitly and
  log them. Same GPU + same versions + same inputs is normally repeatable. `--deterministic` "prefers deterministic algorithms; not
  guaranteed". Bit-exactness across GPUs, drivers, torch versions, `--fast` features, SageAttention or GGUF vs fp8 is **not** expected.
  Note: ComfyUI caches node outputs, so re-submitting an identical prompt returns cached results. That is fine, but use
  `--cache-none` for timing benchmarks.
* **Pin ComfyUI:** portable release tag (v0.46.0) or `comfy update comfy --version <tag>`; don't run `update_comfyui.bat`
  (it moves to the latest commit). Record `/system_stats` (version, torch, CUDA) with each job.
* **Pin custom nodes:** keep the list minimal (ComfyUI-GGUF only, for the default). Use `comfy node registry-install <id> --version <v>`
  or a git checkout at a commit. Save `comfy node save-snapshot` / ComfyUI-Manager snapshots (they record the ComfyUI commit, each node's
  commit hash and `pip freeze`; restore is "best effort" ([docs](https://docs.comfy.org/installation/desktop/usage/snapshots))).
  Keep a repo-side lock file (`tools/comfy/nodes.lock`) with name, URL and commit.
* **Model hashes:** the HF tree API returns `lfs.oid` (SHA-256) and `size` per file, plus a repo commit `sha` from
  `/api/models/<repo>/revision/main`. Store `models.lock` = {repo, revision commit, path, size, sha256, folder} and
  download with `.../resolve/<commit>/<path>`. Check size (cheap) on every start and SHA-256 (slow, about 1 min per 10 GB) on install.
  ComfyUI can also hash assets (`--enable-asset-hashing`, blake3) but that is opt-in.
* **Workflows:** commit the API-format JSON templates to the repo (they are core, not project data) with a sidecar mapping of
  patchable inputs (node id → field), and hash the final submitted prompt into the job log.

---

## B. Blender 5.x

### B1. Headless rendering

Arguments ([manual 5.3](https://docs.blender.org/manual/en/latest/advanced/command_line/arguments.html)) run **in order**:

```bat
"C:\Program Files\Blender Foundation\Blender 5.3\blender.exe" -b --factory-startup --offline-mode -noaudio ^
   --python-exit-code 1 -P tools\blender\render_shot.py -- --shot shot.json --out D:\...\renders ^
   --cycles-device OPTIX
```

* `-b` = no UI; `-P` script; `--python-exit-code 1` makes exceptions fail the process (essential for CI and the pipeline);
  `--factory-startup` ignores the user's startup.blend and prefs (reproducible, but **also disables GPU prefs**, so the script must enable
  Cycles devices itself). `--` passes the rest to `sys.argv`. `-E <engine>`, `-o` (output; `#` = frame padding), `-F PNG`,
  `-s/-e/-a/-f`, `-t` threads, `--gpu-backend vulkan|opengl`, `--log`, `--log-level`.
* **Cycles on RTX 50:** supported since 4.4 ([4.4 Cycles notes](https://developer.blender.org/docs/release_notes/4.4/cycles/)).
  In script:
  `p=bpy.context.preferences.addons['cycles'].preferences; p.compute_device_type='OPTIX'; p.get_devices(); [setattr(d,'use',d.type!='CPU') for d in p.devices]; scene.cycles.device='GPU'`
  (or `-- --cycles-device OPTIX` when rendering with `-f/-a`).
* **EEVEE:** engine id is **`BLENDER_EEVEE`** again in 5.0 (was `BLENDER_EEVEE_NEXT` in 4.2–4.5) ([5.0 API notes](https://developer.blender.org/docs/release_notes/5.0/python_api/)).
  EEVEE, Workbench and Grease Pencil rendering need a GPU (OpenGL/Vulkan) context even with `-b`. Historically headless Linux needed X/EGL
  ([discussion](https://devtalk.blender.org/t/blender-2-8-unable-to-open-a-display-by-the-rendering-on-the-background-eevee/1436)).
  On a normal logged-in Windows desktop with the RTX card, `-b` + EEVEE works in practice. In a Windows service, SSH (session 0) or
  **WSL without GPU** it is **unverified/likely to fail**, so use Cycles there.
* **Output:** `image_settings.media_type` must be set **before** `file_format` (5.0):
  `r.image_settings.media_type='IMAGE'; r.image_settings.file_format='PNG'; color_depth='16'` for sequences, or
  `media_type='VIDEO'; file_format='FFMPEG'; r.ffmpeg.format='MPEG4'; r.ffmpeg.codec='H264'; r.ffmpeg.constant_rate_factor='HIGH'`.
  Recommended: **always render PNG/EXR sequences** and encode with our own ffmpeg (restartable, and frames feed ComfyUI directly).
* **4.x → 5.x breakage that bites old scripts** (5.0 notes unless noted):
  * `BLENDER_EEVEE_NEXT` → `BLENDER_EEVEE`; `scene.eevee.gtao_*` / `use_gtao` removed.
  * **Legacy action API removed:** `action.fcurves`, `action.groups`, `action.id_root` are gone (slotted/layered actions since 4.4).
    Use `bpy_extras.anim_utils.action_ensure_channelbag_for_slot(action, slot).fcurves` or, simpler, `obj.keyframe_insert(data_path, frame=f)`
    (handles slots automatically).
  * **`bgl` removed**; `Image.bindcode` removed (use the `gpu` module).
  * **Compositor:** `scene.node_tree` removed → `scene.compositing_node_group = bpy.data.node_groups.new(name,'CompositorNodeTree')`, output via
    `NodeGroupOutput` with an interface socket. File Output node: `base_path/file_slots/layer_slots` → `directory`, `file_name`,
    `file_output_items`. `scene.use_nodes` is deprecated.
  * Render pass names: `Z` → **`Depth`**, `IndexMA` → `Material Index`, etc. (fix socket lookups by name).
  * `bpy.props`-defined properties are no longer reachable via dict access (`scene['cycles']` fails).
  * GP types renamed: `GreasePencilv3` → `GreasePencil`, `bpy.data.grease_pencils_v3` → `grease_pencils`; old annotation types → `Annotation*`.
  * `mathutils` buffer protocol is float32 now (NumPy conversions).
  * The log format changed (affects parsing of render progress).
  * **5.1:** Python **3.13**; VSE strip time props renamed (`frame_final_start` → `left_handle`, etc., removal in 6.0)
    ([5.1 notes](https://developer.blender.org/docs/release_notes/5.1/python_api/)). **5.2:** Geometry Nodes modifier inputs moved to
    `modifier.properties.inputs` ([5.2](https://developer.blender.org/docs/release_notes/5.2/python_api/)). **5.3:** `bpy.data.all_ids`
    order changed ([5.3](https://developer.blender.org/docs/release_notes/5.3/python_api/)).

### B2. Procedural non-photoreal looks

* **Grease Pencil v3** (4.3+, Python names cleaned up in 5.0): `gp=bpy.data.grease_pencils.new('ink'); layer=gp.layers.new('L');
  frame=layer.frames.new(1); d=frame.drawing; d.add_strokes([n,...]); d.strokes[i].points[j].position=(x,y,z)` (+ `radius`, `opacity`,
  `vertex_color`). For speed use `d.attributes` (`position`, `radius`) with `foreach_set` ([GreasePencilDrawing](https://docs.blender.org/api/current/bpy.types.GreasePencilDrawing.html)).
  5.2 added annotation stroke helpers. Good for brush-stroke ink lines, seals, calligraphy-like strokes we generate in code.
* **Line Art modifier** on a GP object: `obj.modifiers.new('lineart','LINEART')` → `GreasePencilLineartModifier` with `source_type`
  (`SCENE/COLLECTION/OBJECT`), `source_camera`, `target_layer`, `target_material`, `radius`, `crease_threshold`, `level_start/end`,
  `silhouette_filtering`, `shadow_region_filtering`, `smooth_tolerance`, `chaining_image_threshold`
  ([API](https://docs.blender.org/api/current/bpy.types.GreasePencilLineartModifier.html)). Line Art is computed on the CPU, so it works in `-b`;
  the GP strokes are then drawn by the GPU engine (needs the GPU context above). Bake it (`is_baked`) for stable re-renders.
* **Freestyle:** `r.use_freestyle=True`, line sets per view layer; CPU-based and works in background with Cycles or EEVEE. Slow on dense
  meshes, but good for clean contour passes for ControlNet ("lineart" control).
* **Toon shading:** `Shader to RGB` + `ColorRamp` is **EEVEE-only**. In Cycles, use light-path / normal-dot tricks or render flat
  `Emission` + separate passes and do the stylization in the compositor or in ComfyUI.
* Practical split for us: Blender does **layout, camera, motion, and control passes** (clay, depth, normal, lines, masks). The painterly
  ink look comes from the image/video model, with optional GP/Line Art ink lines composited on top.

### B3. Driving a shot from JSON

* Import: `bpy.ops.import_scene.gltf(filepath=...)` (bundled glTF add-on; works in `-b` with `--factory-startup`). Cameras:
  `bpy.data.cameras.new` + `lens`, `sensor_width`, `clip_start/end`, `dof`. Set `r.resolution_x/y`, `r.fps`, `frame_start/end`.
* Keyframes: `obj.location=...; obj.keyframe_insert('location', frame=f)`, then set interpolation through the channelbag F-curves
  (`kp.interpolation='BEZIER'|'LINEAR'`).
* **Control passes** (enable on `view_layer`: `use_pass_z`, `use_pass_normal`, `use_pass_mist`, `use_pass_object_index`,
  `use_pass_cryptomatte_object`; property names **unverified** for 5.3 beyond the `Z`→`Depth` socket rename), written via the 5.0 File Output node to
  16-bit PNG or EXR:
  * **Depth for ControlNet-style models:** use the **Mist pass** with fixed `world.mist_settings.start/depth` per shot (or the Depth pass with fixed
    near/far), then invert so near = white. **Don't normalize per frame**: it causes depth "breathing" and flicker in the generated video.
  * Normals in camera space; object-index masks for characters (also useful for matte instead of `rembg`).
  * Clay/playblast pass for Layout-To-Render: Workbench (GPU) or a flat-grey Cycles material at low samples.
  * Set the view transform to **Standard** (not AgX/Filmic, the default) for control passes; mark data as Non-Color.
* **Determinism:** Cycles `scene.cycles.seed` fixed, `use_animated_seed=False` (or True for temporally varying noise, still deterministic),
  fixed samples, `use_denoising` with OIDN (the CPU OIDN path is deterministic; GPU denoise **unverified**). EEVEE is effectively deterministic
  for a fixed scene and sample count. Avoid `time`-based drivers. Pin the Blender version in the job log (`bpy.app.version_string`).

### B4. `bpy` as a pip wheel for WSL tests

* PyPI `bpy` **5.3.0 (2026-11-10)**: `manylinux_2_28_x86_64` wheel **427.5 MB** (Windows 356 MB) ([PyPI](https://pypi.org/project/bpy/)).
  **`requires_python ==3.13.*`**. bpy 5.1+ is cp313 only; 5.0.x and 4.5 LTS are cp311 only. **Nothing supports 3.12**, so the WSL Python 3.12
  can't import it. Options: `uv python install 3.13 && uv venv -p 3.13 .venv-bpy && uv pip install bpy==5.3.0` for a separate test env
  (keep the main test suite on 3.12), or mark the Blender tests `skip` if `bpy` isn't importable.
* Match versions: `bpy==5.3.0` with the installed Blender 5.3 (5.2.x and 4.5.x LTS also exist).
* What works in WSL without a GPU: building scenes, JSON → scene assertions, keyframe checks, compositor graph construction, and **tiny Cycles CPU
  renders** (e.g. 64×36, 1 sample). EEVEE/Workbench/GP rendering need a GPU context, so expect failure (**unverified**). The Linux wheel may need
  X/GL runtime libs (`libxrender1 libxi6 libxkbcommon0 libsm6 libgl1`; **unverified** exact list).

---

## C. Recommended architecture: Blender layout → ComfyUI stylize/animate

```
shot.json (from shots.csv)            [repo: tools/blender/, tools/comfy/]
   │
   ▼  blender -b --factory-startup -P tools/blender/render_shot.py -- --shot shot.json
Blender 5.3 (Windows, GPU)
   ├─ layout/clay playblast   960×544 or 1920×1088, 24 fps, 8k+1 frames   (PNG seq)
   ├─ depth (mist, fixed range, inverted), normal, line art/freestyle, object-index masks
   ├─ keyframe still(s): clay frame 0 (+ mid/last)
   └─ manifest.json (camera, fps, frames, seeds, blender version, pass list)
   │
   ▼  stylize keyframe (image)  -- Seedream (cloud, existing ark.py + ledger) OR local image model with depth control
styled first frame (ink-wash look, matches clay composition)
   │
   ▼  tools/comfy/run.py  (API-format template + param map → POST /prompt → ws progress → /history → /view)
ComfyUI (Windows, 127.0.0.1:8188)
   ├─ A. plain I2V:       Wan 2.2 I2V 14B (styled frame → clip)          — simple motion, default
   ├─ B. layout-driven:   LTX-2.5 + Layout-To-Render IC-LoRA (clay clip + styled frame [+ last frame])
   ├─ C. depth-driven:    Wan 2.2 Fun Control (depth/canny video + styled start frame)
   └─ post: RIFE 16→24 fps (Wan), upscale (LTX x2 / SeedVR2), save PNG seq + mp4
   │
   ▼  existing cinecode compositor / matte_seq.py / audio / check_episode.py
```

Integration notes:
* Treat ComfyUI as a **local, free but slow** backend: the same CLI contract as `ark.py` (dry-run validates against `/object_info`, exit codes
  2/1, outputs refuse to overwrite and use `_v<NN>`, ledger line with `cost=0`, seconds, seed, workflow hash, model lock hash).
  Never auto-retry after the prompt was queued; check `/history` first.
* Keep the GPU single-tenant: don't run a Blender GPU render and a ComfyUI job at the same time on 16 GB. Have the runner call `POST /free` before
  Blender jobs, or serialize them in one queue.
* The repo's WSL tests: mock ComfyUI HTTP/WS (pure Python 3.12), JSON → Blender scene tests in a separate 3.13 `bpy` env, and lint that each
  committed workflow template only references core node classes plus the locked custom nodes.
* Workflow templates and lock files are core (commit them). Shot JSON, generated keyframes and clips are project data (Drive/`out/`, never committed).

**Pitfalls found**
1. **Disk is the real constraint.** C: 16 GB: never install Desktop, the HF cache or pip caches on C:. D: 67 GB holds ComfyUI plus **one** video stack (31–41 GB) plus working
   media; two stacks don't fit.
2. **Torch hijack by custom nodes** breaks sm_120/cu130. Minimal nodes, `--no-deps`, re-check `torch.cuda.get_arch_list()`.
3. **Frame/size rules differ:** Wan 14B 16 fps, frames 4k+1, W/H multiple of 16; Wan 5B 24 fps, 121 frames; LTX frames 8k+1, W/H /32 (/64
   for Layout LoRA). 1920×1080 is invalid for LTX (use 1920×1088, then crop). Blender must render exactly what the workflow expects, or the
   model snaps the length and the control video drifts out of sync.
4. **Control-pass conventions:** depth near = white, fixed normalization across the shot, Standard view transform, no motion blur/DOF in
   control passes, same camera and resolution for all passes.
5. **Layout-To-Render takes its look from the first frame**, not from the clay; a grey first frame gives grey output. Keep prompts free of
   "3D/clay/render".
6. **Licenses:** Wan = Apache-2.0 (clean). LTX-2.x = free under $10M revenue, gated download (needs an HF token that the *user* sets as an env
   var, never pasted into chat or logged). HunyuanVideo 1.5 = not licensed in EU/UK/South Korea (YouTube distribution reaches the EU: treat it as a risk).
7. **Long clips:** VAE decode of 10 s/1080p can stall (LTX report); use tiled decode or generate 5 s segments joined with FLF2V/last-frame chaining.
8. **SageAttention/`--fast`** may change outputs or produce black frames; benchmark before enabling, and record the flags in the job log.
9. **EEVEE/GP need a GPU session:** run Blender jobs from the logged-in user session (scheduled task "run only when user is logged on"),
   not as a service; WSL CI uses Cycles CPU or no render at all.
10. **bpy wheel = Python 3.13 only** since 5.1. The repo's WSL Python 3.12 can't import it.

Unverified items to measure on the actual PC (cost nothing but time):
torch build in the portable; s/clip for Wan 14B at 480p/720p and LTX-2.5 two-stage on the 5070 Ti; NVFP4 vs int8 vs GGUF speed/quality
for LTX-2.5; IC-LoRA + GGUF compatibility; EEVEE `-b` from a scheduled task; ink-wash fidelity of Wan vs LTX (bake-off).
