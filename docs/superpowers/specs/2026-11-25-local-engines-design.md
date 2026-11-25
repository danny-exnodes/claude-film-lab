# Local engines: Blender (3D) and ComfyUI (local video AI) — design

Date: 2026-11-25 · Branch: `claude/local-engines` · Research: `docs/superpowers/research/2026-11-25-blender-comfyui.md`

## 1. Intent

The owner wants the lab to "unlock the power of the local computer": build film shots from **3D models rendered in
Blender** and generate **video with a local AI model through ComfyUI workflows**, on the owner's PC instead of (or next
to) the paid cloud APIs. Today every moving picture is either drawn by code (`method: code`, three.js / canvas), painted
plates moved by code (`method: layers`) or a paid Seedance clip (`method: seedance`).

The owner's PC: Windows 11, RTX 5070 Ti 16 GB (Blackwell, sm_120), Core Ultra 9 285K, 127 GB RAM, Blender 5.3 at
`C:\Program Files\Blender Foundation\Blender 5.3\blender.exe` (bundled Python 3.13.13). ComfyUI v0.46.0 portable is being
installed at `D:\AI\ComfyUI_windows_portable` with the Wan 2.2 I2V-A14B set (lock: §4.4). Disk: D: ~34 GB free after it.

Owner's direction: "I believe in you, go ahead" — the how is ours; every call below is ours and stated as such.

## 2. Goals, non-goals, anti-goals

Goals
1. **ComfyUI as a local video engine**: start frame (+ optional end frame) + prompt → 5 s clip, free, recorded in the
   episode ledger, reproducible (seed, workflow hash, model hashes), same naming and exit-code contract as `ark.py`.
2. **Blender as a local 3D render engine**: a shot described in `shot3d.json` (assets, camera move, look, lights) →
   PNG sequence + mp4 + control passes (depth, normal, line, mask), headless, deterministic.
3. **A fourth method `method: blender`** wired through the pipeline (EPISODE.md, style `engine: blender`, checker,
   status, docs, agents), and an optional **`video_engine: comfy`** that swaps Seedance for local Wan clips.
4. **The bridge**: Blender renders consistent keyframes (start/end) → Wan first-last-frame animates between them.
5. Install/verify tooling: `comfy.py install|models|ping|start`, `blender.py find`, doctor lines.

Non-goals (this round)
- LTX-2.5 Layout-To-Render, Wan Fun Control / VACE depth-guided video (need 11–41 GB more disk and, for LTX, a gated
  licence on the owner's HF account). Workflow slots and docs mention them as "phase 2, not installed".
- Local image models (Flux, SDXL) — Seedream stays the paid image path; Blender is the free one.
- Running these engines in cloud sessions (no GPU there). Cloud sessions must keep working exactly as before.

Anti-goals (a failure even if it "works")
- **Any paid call.** ComfyUI ships paid "API nodes" (partner services). Our server is always started with `--offline`
  (blocks them), and `comfy.py run` refuses (exit 2) a workflow that contains a node whose class is not in an allow
  list of core/pinned nodes.
- Breaking cloud sessions or the WSL test suite (1064 tests must stay green; new tests must not need a GPU in WSL).
- Silent overwrites, unpinned downloads, models without hash checks, custom nodes that replace torch.
- Committing project data or media (CLAUDE.md rule) — workflows, presets and tiny test fixtures only.

## 3. Approaches considered

| | A. Thin wrappers (chosen) | B. comfy-cli + ComfyScript | C. Blender add-on + ComfyUI node pack |
|---|---|---|---|
| What | Our own stdlib CLIs `tools/comfy/comfy.py`, `tools/blender/blender.py` + in-Blender `scene.py`; API-format workflow templates with a meta file | Depend on comfy-cli / Python client libs | GUI-first tools for an artist |
| Fits repo | Same shape as `ark.py` (ledger, exit codes, refuse-before-send), testable with fakes in WSL | New deps, harder to pin, Python 3.12/3.13/3.14 spread | Not scriptable by Claude sessions |
| Chosen | ✔ — agents drive everything from the CLI, like the rest of the lab | comfy-cli only as an optional manual helper (docs) | ✘ |

## 4. Design

### 4.1 Where things run
- Both engines run on the **owner's Windows PC** in a **local** Claude Code session. Tools must run under **Windows
  Python ≥ 3.12** (stdlib only, plus PyYAML/Pillow where already used) **and** Linux Python 3.12 (WSL tests).
- `tools/ark.py` imports `fcntl` (Linux only). It gains a small portable lock helper (`fcntl.flock` on POSIX,
  `msvcrt.locking` on Windows) so `comfy.py` / `blender.py` can import ark's ledger code on Windows. Behaviour on Linux
  must not change (all ark tests unchanged).
- Env: `FILM_COMFY_URL` (default `http://127.0.0.1:8188`), `FILM_COMFY_HOME` (default `D:\AI\ComfyUI_windows_portable`
  on Windows, unset elsewhere), `FILM_BLENDER` (path to blender executable; else PATH; else newest
  `C:\Program Files\Blender Foundation\Blender */blender.exe`; else `/Applications/Blender.app/...`, `/usr/bin/blender`).

### 4.2 `tools/comfy/` (package P1)
Files: `comfy.py`, `comfy.lock.json` (pinned ComfyUI release + custom nodes + model files with url/size/sha256/licence;
content = the lock in §4.4), `workflows/<id>.json` (ComfyUI **API format**), `workflows/<id>.meta.json`,
`README.md`.

CLI (exit codes as ark: 0 ok · 2 refused locally, nothing sent · 1 sent and failed / see ledger · 3 not used):
```
python tools/comfy/comfy.py ping                      # GET /system_stats: ComfyUI version, python, torch, GPU, VRAM free
python tools/comfy/comfy.py start [--wait 120]         # launch the portable server: --listen 127.0.0.1 --port 8188 --offline --disable-auto-launch
                                                        #   --output/--input/--temp-directory under FILM_COMFY_HOME; detached; log to FILM_COMFY_HOME/film-lab-server.log
python tools/comfy/comfy.py install [--dry-run] [--set wan22-i2v]   # download+verify per comfy.lock.json (resume, sha256), extract portable (Windows tar.exe = bsdtar reads .7z), custom nodes at pinned commit, pip --no-deps; re-checks torch sees sm_120
python tools/comfy/comfy.py models [--set S] [--verify]             # present / size ok / (--verify) sha256 ok, per lock
python tools/comfy/comfy.py workflows                               # id, title, model set, inputs, constraints
python tools/comfy/comfy.py run <workflow> --image START.png [--last END.png] --prompt "..." [--negative "..."]
       [--seconds 5] [--res 480p|720p] [--seed N] [--steps 4] --out <clips>/<name>_v<NN>.mp4 --ledger L
       [--dry-run] [--timeout 2400] [--keep-frames]
python tools/comfy/comfy.py interrupt                               # POST /interrupt (own prompt only)
```
`run` contract:
- Local refusals (exit 2, nothing uploaded): missing image; `--out` exists (no overwrite; `_v<NN>` rule); workflow
  unknown; a node class outside the allow list (anti-goal: paid API nodes); model files of the workflow's set missing
  (checked via `/object_info` choices when the server is up, else on disk under FILM_COMFY_HOME); `--last` given to a
  workflow without an end-frame input; `--ledger` missing (unless `--no-ledger`, which `FILM_AGENT` may not use).
- Sizes/frames from the meta file: frames = `fps × seconds + 1` snapped to the model's rule (Wan: `4k+1`, max 81 at 16
  fps); width/height = the `--res` preset fitted to the start image's aspect, multiples of 16 (Wan).
- Flow: upload image(s) (`POST /upload/image`, unique names) → fill the template via the meta's input map → `POST /prompt`
  with a `client_id` → poll `/history/<prompt_id>` every 2 s (no websocket dependency), printing `step`/`elapsed` lines
  (progress from `/queue` + history status) → on success download the output via `/view` → write `--out` atomically
  (tmp + rename) → sidecar `<out>.json` (workflow id + sha256 of the filled graph, seed, prompt, size, frames, fps,
  model files + sha256 from the lock, ComfyUI version, elapsed GPU seconds).
- Ledger (ark's writer and lock): `pending` row before `POST /prompt`, final row after: kind `video`, model
  `comfy:<workflow>`, `seconds`, status `ok|failed|interrupted`, `task_id` = prompt_id, `usage` = `gpu_s=<n>`,
  note `req=<hex>;seed=<n>`. **Local rows cost 0**: ark's cap counting skips models starting with `comfy:` or
  `blender:` (P1 changes ark), so they never consume `images` / `video_seconds` caps; `status.py` shows them separately.
- `--dry-run`: print the filled graph summary (nodes, sizes, frames, seed) and exit 0 without contacting the server.

Workflows shipped (both built from ComfyUI's official Wan 2.2 14B I2V template, adapted to the GGUF loader):
- `wan22-i2v`: `UnetLoaderGGUF` ×2 (high/low noise Q5_K_M) → `LoraLoaderModelOnly` (lightx2v 4-step high/low) →
  `ModelSamplingSD3` (shift 5–8) → `CLIPLoader` (umt5, type `wan`) → `CLIPTextEncode` ×2 → `VAELoader` → `LoadImage` →
  `WanImageToVideo` → `KSamplerAdvanced` high (steps 0→2, cfg 1, `add_noise enable`, `return_with_leftover_noise
  enable`) → `KSamplerAdvanced` low (2→4) → `VAEDecode` → `CreateVideo` (fps 16) → `SaveVideo` (mp4/h264).
- `wan22-flf2v`: same, with `WanFirstLastFrameToVideo` and two `LoadImage` nodes (start, end).
Allow list = node classes used by these graphs. Exact node class names and inputs must be verified against
`/object_info` of the real server (the integrator runs this; agents without a server write the graph from the
template and the research notes and mark it "unverified").

Tests (`tests/test_comfy.py`, WSL): a fake ComfyUI HTTP server (stdlib `http.server` in a thread) implementing
`/system_stats`, `/object_info`, `/upload/image`, `/prompt`, `/history/<id>`, `/view`, `/queue`, `/interrupt`; cover
every refusal, frame/size snapping, dry-run, happy path (file + sidecar + ledger rows + no cap consumption), failure
path (execution_error → failed row, no file), timeout → `interrupted`, lock-file parsing, `models --verify` with tiny
fake files, `install --dry-run` plan. Plus ark tests stay green and a test that `comfy:` rows cost 0.

### 4.3 `tools/blender/` (package P2)
Files: `blender.py` (CLI, runs outside Blender), `spec.py` (pure Python, imported by both sides; no 3.13-only syntax),
`scene.py` (runs inside Blender: `blender -b --factory-startup --python-exit-code 1 -P scene.py -- --spec S --out D`),
`looks.py` (inside Blender: materials / line art / world per look), `presets.py` (procedural assets), `README.md`,
`demo/` (2–3 tiny demo `shot3d.json`).

`shot3d.json` (version 1; validated by `spec.py`, errors as `path: reason`):
```json
{ "version": 1, "size": [1920, 1080], "fps": 24, "seconds": 5, "seed": 7,
  "look": "toon-ink", "engine": "eevee",
  "world": { "paper": "#f2ead8", "mist": 0.35, "sun": [35, 120] },
  "assets": [
    { "id": "nui", "src": "preset:mountains", "at": [0, 40, 0], "scale": 30 },
    { "id": "hero", "src": "assets/hero.glb", "at": [0, 0, 0], "rot": [0, 0, 90],
      "anim": { "action": "walk", "path": [[0, [0,0,0]], [5, [0,6,0]]] } } ],
  "camera": { "move": "push-in", "from": [0, -12, 1.6], "to": [0, -7, 1.6], "target": "hero", "lens": 35, "ease": "inout" },
  "passes": ["depth", "normal", "line", "mask"], "depth_range": [1, 80] }
```
- Camera move names shared with the lab: `static, push-in, pull-out, pan, tilt, orbit, dolly, crane, track` (same
  meanings as `tools/toon/project.js`); camera path math lives in `spec.py` (testable without Blender).
- `src`: `preset:<id>` (procedural, in `presets.py`: at least `mountains`, `rocks`, `pines`, `water`, `ground`,
  `giot` — the lab mascot as simple 3D shapes), a `.glb/.gltf` path (relative to the spec), or `prim:<cube|sphere|...>`.
- Looks (in `looks.py`; registry `tools/blender/looks.json`): `grey-layout` (flat grey clay, for AI bridge input),
  `clay`, `toon-ink` (toon ramp shading + Line Art grease pencil), `ink-wash` (paper white, value ramps, line art,
  depth mist — the 3D counterpart of `thuy-mac`). EEVEE (`BLENDER_EEVEE` in 5.x) default, Cycles fallback
  (`--engine cycles`, OptiX/CUDA, fixed samples + seed). Blender 5.x API rules from research §B1 (no `action.fcurves`,
  `scene.compositing_node_group`, `Depth` pass name, `media_type` before `file_format`).
- Outputs in `--out`: `beauty/0001.png…`, `depth/` (16-bit, fixed `depth_range`, near = white, never per-frame
  normalized), `normal/`, `line/`, `mask/<asset>/`, `beauty.mp4` (ffmpeg if found, else skipped with a note),
  `render.json` (spec sha256, blender version, engine, device, seconds per frame).
- CLI:
```
python tools/blender/blender.py find                                 # path + version (exit 1 when not found)
python tools/blender/blender.py check <shot3d.json>                  # spec only, no Blender
python tools/blender/blender.py render <shot3d.json> --out <dir> [--frames A:B] [--preview] [--engine eevee|cycles] [--passes ...]
python tools/blender/blender.py still <shot3d.json> --frame N --out <png>
python tools/blender/blender.py turntable <asset.glb|preset:id> --out <dir> [--look L]
python tools/blender/blender.py keyframes <shot3d.json> --out <dir>  # first + last beauty frame → for comfy wan22-flf2v
python tools/blender/blender.py lookbook --out <dir>                 # one still per look
```
`--out` must not exist or be empty (no overwrite). `--preview` = 960×540, 12 fps, low samples.
- Tests: WSL — `spec.py` validation and camera math, CLI parsing, `find` order, a fake blender executable (script that
  records argv and writes the expected files) for `render/still/keyframes`. Windows — `tests/test_blender_render.py`
  renders a 64×36, 3-frame demo with the real Blender, `skipUnless(blender found)`; the integrator runs it on Windows.

### 4.4 Model lock (ComfyUI v0.46.0 portable + Wan 2.2 I2V A14B, set `wan22-i2v`, 31.03 GB)
Portable `ComfyUI_windows_portable_nvidia.7z` 2085169944 B sha256 `6a5255c7…5fac6`; custom node
`city96/ComfyUI-GGUF` @ `6ea2651e7df66d7585f6ffee804b20e92fb38b8a` (+ `pip install --no-deps gguf`); models:
`Wan2.2-I2V-A14B-{HighNoise,LowNoise}-Q5_K_M.gguf` (QuantStack, diffusion_models), `umt5_xxl_fp8_e4m3fn_scaled`
(text_encoders), `wan_2.1_vae` (vae), `wan2.2_i2v_lightx2v_4steps_lora_v1_{high,low}_noise` (loras). Full URLs,
sizes and sha256: the integrator copies `comfy.lock.json` into `tools/comfy/` (source of truth).

### 4.5 Pipeline integration (package P3)
- `EPISODE.md`: `method: layers | seedance | code | blender`; new optional key `video_engine: seedance | comfy`
  (default `seedance`; allowed with `seedance` and `blender`; with `layers`/`code` it is an ERROR).
- `method: blender`: style pack `engine: blender` (`render: { look, palette, line, mist, engine }`); `budget.yaml`
  `images: 0`; `video_seconds: 0` unless `video_engine: seedance` with `ai_motion`; shots.csv `layers` codes
  `A-<asset>` (3D asset), `E-<setting>`, `FX[-…]`, `T`; `camera` values = §4.3 move names; per shot a
  `shot3d.json` in `<episode>/shots3d/s<NN>.json` (project data, Drive); renders to `out/<project>/ep<NN>/renders3d/s<NN>/`.
  Stages: 3 = assets (GLB or presets) + `ASSETS.md` (licence/source per model) + shot3d drafts; 4 = turntable + one
  sample shot (G2); 5 = Blender renders (free); 6 = optional local clips (`video_engine: comfy`, bridge via
  `keyframes` + `wan22-flf2v`); 7–11 as today (the compositor uses the PNG sequence / mp4 like a clip).
- `video_engine: comfy` (with `seedance` or `blender`): stage 6 runs `comfy.py run` instead of `ark.py video`;
  `video_seconds` may be 0; checker WARNs when the session is not local (no `FILM_COMFY_URL` reachable is not an
  error for the checker — the checker never touches the network).
- `check_episode.py`: the rules above, style engine/method match, `shots3d/` files validated with `spec.py` when present.
- `status.py`: method blender; FORECAST shows local GPU minutes (estimates: Blender preview/final per shot, Wan
  480p ≈ 4 min / 720p ≈ 12 min per 5 s clip — constants marked "estimate, measure"), local ledger rows listed apart.
- `doctor.sh`: lines `blender` and `comfy` — `n/a` quietly when not found (cloud), WARN when configured but broken;
  never FAIL; never contacts anything but `FILM_COMFY_URL` (localhost).
- Docs (Vietnamese, as the repo): `docs/WORKFLOW.md` (four methods + local engines), `docs/CONVENTIONS.md`
  (EPISODE keys, shot3d schema reference, names `renders3d/`, `clips/` from comfy), `CLAUDE.md` (tool lines, local-only
  rule, no paid ComfyUI API nodes), `docs/MODELS.md` (local models + licences), `docs/RUNBOOK.md` (Blender/ComfyUI
  errors), new references `.claude/skills/film-compose-shot/references/blender-method.md` and `local-video.md`,
  `film-pipeline` skill (stage 0 choice, local-only), agents: `film-animator` (comfy path), new `film-3d-artist`
  (stages 3–5 for method blender: assets, shot3d.json, renders; Bash, Read, Write, Edit, Glob, Grep; no paid calls),
  `templates/` (shot3d example), style packs `styles/thuy-mac-blender/` and `styles/toon-3d-blender/` (status draft).
- `tests/test_docs.py` must stay green (every command/flag/path named in docs exists).

## 5. Packages, ownership, merge order
| Package | Owns | May touch lightly |
|---|---|---|
| P1 comfy | `tools/comfy/**`, `tests/test_comfy*.py`, ark portable lock + `comfy:`/`blender:` zero-cost rows (`tools/ark.py`, its tests) | `requirements-ci.txt` if needed |
| P2 blender | `tools/blender/**`, `tests/test_blender*.py` | – |
| P3 pipeline | `tools/check_episode.py`, `tools/status.py`, `tools/doctor.sh`, docs, skills, agents, templates, styles, their tests | – (codes against the interfaces in §4.2/§4.3; never edits P1/P2 files) |
Merge order P1 → P2 → P3 into `claude/local-engines`; the integrator then runs the WSL suite, the Windows Blender
test, and a real end-to-end clip (Blender keyframes → Wan FLF2V; and a Seedream-free i2v from a Blender still).
CHANGELOG/BACKLOG/RUNBOOK shared lines are written by the integrator (packages list theirs in their final report).

## 6. Left to the builders
Exact node graphs (verified later against `/object_info`), look shader details, preset geometry, progress-line format,
test fixture sizes — anything that does not change the contracts above.
