#!/usr/bin/env python3
"""ComfyUI as a free local video engine for AI Film Lab (owner's Windows PC, NVIDIA GPU; tools/comfy/README.md).

  python tools/comfy/comfy.py ping                         GET /system_stats: ComfyUI, python, torch, GPU, VRAM, offline
  python tools/comfy/comfy.py start [--wait 120] [--dry-run]
                     run the installed ComfyUI headless on FILM_COMFY_URL (127.0.0.1:8188), paid API nodes blocked
                     (--offline); does nothing when a server already answers there (e.g. the Desktop app is open)
  python tools/comfy/comfy.py install [--dry-run] [--portable] [--lock L]
                     check the install against comfy.lock.json; never downloads a model (only lists what is missing);
                     --portable downloads + extracts the pinned portable ComfyUI when none is installed
  python tools/comfy/comfy.py models [--set S] [--verify] [--lock L]
                     each model file of the lock: present / size ok / (--verify) sha256 ok when the lock pins one
  python tools/comfy/comfy.py workflows                    id, title, model files, inputs, constraints
  python tools/comfy/comfy.py run <workflow> (--prompt TEXT | --prompt-file F.json|.yaml) --out <clips>/<name>_v<NN>.mp4
                     [--image START.png [--last END.png]] [--ref IMG ...] [--guide SECONDS=IMG ...] [--ref-size match|max]
                     [--seconds 5] [--res 480p|768p] [--seed N] [--steps N] [--turbo] [--timeout 2400] [--keep-frames]
                     (--ledger L.csv | --no-ledger) [--dry-run]
  python tools/comfy/comfy.py interrupt (--prompt-id ID | --ledger L.csv)     stop our own job(s), never a global stop

Workflows (tools/comfy/workflows/<id>.json in ComfyUI API format + <id>.meta.json):
  h3-i2v   MiniMax H3 image-to-video with audio: --image START (first frame), optional --last END (first-last frame);
           no --image = text-to-video. 24 fps, canvas 768p 1344x768 (7:4, the training canvas) or 480p 864x480.
  h3-r2v   MiniMax H3 reference-to-video with audio: --ref IMG (1-9, <Picture 1..n> in the prompt) and optional
           --guide SECONDS=IMG time anchors (MiniMaxH3AddGuide).
H3 rules: length = 17k+5 frames at 24 fps (`--seconds` is snapped up); the start frame is center-cropped to the canvas
aspect and resized with Lanczos to exactly the canvas in a temp file before upload (the node would stretch it; the source file is
never touched); CFG-distilled: no negative prompt (--negative is refused); 20 steps; --turbo (Lightning LoRA, few
steps) is for drafts only, never for faces or quality runs.

Exit codes (as tools/ark.py): 0 ok · 2 refused locally, nothing uploaded or queued (no ledger row) · 1 the job was
queued and failed, was interrupted or timed out (see its ledger row), or the server is unreachable (ping/interrupt).
`run` refuses (exit 2): an unknown workflow, a node class outside the allow list (ComfyUI's paid API/partner nodes can
never run from here), a missing input file, an output (or its sidecar) that exists (versions only go up: _v<NN>),
--negative, --last without --image or on a workflow without an end frame, --ref/--guide on the wrong workflow, more
than 9 refs, a guide outside the clip, a clip longer than the model's 362 frames, model files or node classes the
server does not have (/object_info), no --ledger (--no-ledger is for ad-hoc tests in the main session; never with
FILM_AGENT set).
Ledger (tools/ark.py's writer and lock): a `pending` row before POST /prompt and a final row after it, kind video,
model comfy:<workflow>, size WxH, seconds, task_id = the prompt id, usage gpu_s=<n>, note req=<hex>; seed=<n>, status
ok | failed | interrupted. Local rows cost 0 against every cap of budget.yaml (ark.cost_units), so no --budget here.
Output: <out> (mp4 with audio, written atomically) + <out>.json sidecar (workflow, sha256 of the filled graph, seed,
prompt, sizes, frames, model files, ComfyUI/torch versions, GPU seconds).

Env: FILM_COMFY_URL (default http://127.0.0.1:8188), FILM_COMFY_HOME (Windows default
%LOCALAPPDATA%\\Comfy-Desktop\\ComfyUI-Installs\\ComfyUI: Desktop layout ComfyUI\\.venv\\Scripts\\python.exe + ComfyUI\\main.py;
the portable layout python_embeded\\python.exe + ComfyUI\\main.py works too), FILM_COMFY_MODELS (Windows default
%LOCALAPPDATA%\\Comfy-Desktop\\ComfyUI-Shared\\models, else <ComfyUI>/models), FILM_COMFY_PYTHON (python for `start`), FILM_COMFY_WORK (start: input/output/temp/user + log, default <lab>/out/_comfy),
FILM_COMFY_MODEL_PATHS (extra_model_paths yaml for `start`; default: the Desktop's instance yaml), FILM_LEDGER,
FILM_AGENT. No key is needed or read; nothing but FILM_COMFY_URL is contacted (except `install --portable`).
"""
import argparse, glob, hashlib, http.client, io, json, os, re, secrets, shutil, signal, struct, subprocess, sys
import tempfile, time, urllib.error, urllib.parse, urllib.request, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import ark  # noqa: E402  (tools/ark.py: the one ledger writer, lock and request ids)

LOCK_FILE = os.path.join(HERE, "comfy.lock.json")
WORKFLOWS = os.path.join(HERE, "workflows")
DEFAULT_URL = "http://127.0.0.1:8188"
MODEL_PREFIX = "comfy:"
REFUSED, FAILED = 2, 1
POLL_SECONDS = 2          # /history polling interval (no websocket dependency)
PROGRESS_SECONDS = 30     # a progress line at least this often
POLL_ERRORS = 5           # consecutive failed polls before the job is given up (the server died)
HTTP_TIMEOUT = 30
UPLOAD_TIMEOUT = 120
START_POLL = 2
# GPU seconds per sampling step for a 124-frame (5.2 s) clip on the owner's RTX 5070 Ti, plus a fixed setup/decode
# overhead. 768p measured 2026-11-25: 20 steps x ~34 s + ~33 s = 713 s (the 20 GB model streams from RAM: 16 GB VRAM).
# 480p (~10 s/step) comes from the owner's own Desktop logs. Step time is scaled linearly by the frame count.
SECONDS_PER_STEP = {"768p": 34.0, "480p": 10.0}
SETUP_SECONDS = 35.0
# Every node class a graph sent by `run` may contain: exactly the classes of workflows/h3-*.json plus the nodes `run`
# adds itself (LoadImage per reference, MiniMaxH3AddGuide per --guide). ComfyUI's paid API/partner nodes (e.g. the
# Minimax*Node classes of comfy_api_nodes) are not in it, so they can never be queued from here.
ALLOWED_NODES = frozenset({
    "UNETLoader", "LoraLoaderModelOnly", "CLIPLoader", "VAELoader", "LoadImage",
    "MiniMaxH3ImageToVideo", "MiniMaxH3ReferenceToVideo", "MiniMaxH3AddGuide",
    "RandomNoise", "KSamplerSelect", "BasicScheduler", "BasicGuider", "SamplerCustomAdvanced",
    "VAEDecode", "VAEDecodeAudio", "CreateVideo", "SaveVideo",
})
MODEL_INPUTS = {"UNETLoader": "unet_name", "LoraLoaderModelOnly": "lora_name", "CLIPLoader": "clip_name",
                "VAELoader": "vae_name"}
MODEL_FOLDER_ALIASES = {"diffusion_models": ("diffusion_models", "unet"), "text_encoders": ("text_encoders", "clip")}
I2V_HEADER = "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
PROMPT_FIELDS = {
    "i2v": ("integrated_multimodal_description", "overall_soundscape", "non_diegetic_music"),
    "r2v": ("subject_definitions", "summary", "retention_analysis", "detailed_description", "overall_soundscape",
            "non_diegetic_music"),
}
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # localhost: never through a proxy


class ComfyError(Exception):
    def __init__(self, msg, status=None, body=None):
        super().__init__(msg)
        self.status, self.body = status, body


def refuse(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(REFUSED)


def warn(msg):
    print(f"WARNING: {msg}", file=sys.stderr)


# --- places ------------------------------------------------------------------------------------------------------
def base_url():
    return (os.environ.get("FILM_COMFY_URL") or DEFAULT_URL).rstrip("/")


def _localappdata():
    return os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")


def comfy_home():
    """FILM_COMFY_HOME, else the Comfy Desktop install on Windows, else None."""
    home = os.environ.get("FILM_COMFY_HOME")
    if home:
        return home
    if os.name == "nt":
        return os.path.join(_localappdata(), "Comfy-Desktop", "ComfyUI-Installs", "ComfyUI")
    return None


def layout(home):
    """{'root': ComfyUI source dir (main.py), 'python': interpreter or None, 'kind'} of an install, or None."""
    if not home or not os.path.isdir(home):
        return None
    if os.path.isfile(os.path.join(home, "ComfyUI", "main.py")):
        root = os.path.join(home, "ComfyUI")
    elif os.path.isfile(os.path.join(home, "main.py")):
        root = home
    else:
        return None
    # Comfy Desktop keeps its packages (torch...) in ComfyUI/.venv; standalone-env is only the base interpreter
    kinds = (("desktop", ("ComfyUI", ".venv", "Scripts", "python.exe")), ("desktop", ("ComfyUI", ".venv", "bin", "python3")),
             ("desktop", ("standalone-env", "python.exe")), ("desktop", ("standalone-env", "bin", "python3")),
             ("portable", ("python_embeded", "python.exe")), ("source", (".venv", "Scripts", "python.exe")),
             ("source", (".venv", "bin", "python3")))
    py, kind = None, "source"
    for k, parts in kinds:
        cand = os.path.join(home, *parts)
        if os.path.isfile(cand):
            py, kind = cand, k
            break
    py = os.environ.get("FILM_COMFY_PYTHON") or py
    return {"home": home, "root": root, "python": py, "kind": kind}


def comfy_work():
    """FILM_COMFY_WORK, else <lab>/out/_comfy: where `start` puts ComfyUI's input/output/temp/user folders and its log."""
    env = os.environ.get("FILM_COMFY_WORK")
    if env:
        return os.path.abspath(env)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "out", "_comfy")


def models_dir(lay=None):
    env = os.environ.get("FILM_COMFY_MODELS")
    if env:
        return env
    if os.name == "nt":
        shared = os.path.join(_localappdata(), "Comfy-Desktop", "ComfyUI-Shared", "models")
        if os.path.isdir(shared):
            return shared
    return os.path.join(lay["root"], "models") if lay else None


def model_paths_yaml():
    """FILM_COMFY_MODEL_PATHS, else the Comfy Desktop instance yaml (the newest when several exist), else None."""
    env = os.environ.get("FILM_COMFY_MODEL_PATHS")
    if env:
        return env
    appdata = os.environ.get("APPDATA")
    if os.name != "nt" or not appdata:
        return None
    found = sorted(glob.glob(os.path.join(appdata, "Comfy Desktop", "instance-model-paths", "*.yaml")),
                   key=os.path.getmtime)
    return found[-1] if found else None


def comfy_version(root):
    try:
        with open(os.path.join(root, "comfyui_version.py"), encoding="utf-8") as f:
            m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", f.read())
        return m.group(1) if m else "?"
    except OSError:
        return "?"


# --- HTTP ----------------------------------------------------------------------------------------------------------
def call(method, path, body=None, *, raw=None, ctype=None, timeout=HTTP_TIMEOUT, want="json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base_url() + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", ctype or "application/json")
    try:
        with OPENER.open(req, timeout=timeout) as r:
            payload = r.read()
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        raise ComfyError(f"HTTP {e.code}: {text[:600]}", status=e.code, body=text) from None
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        raise ComfyError(f"network error: {type(e).__name__}: {getattr(e, 'reason', None) or e}") from None
    if want == "bytes":
        return payload
    try:
        return json.loads(payload) if payload.strip() else {}
    except ValueError:
        raise ComfyError(f"not JSON from {path}: {payload[:120]!r}") from None


def system_stats():
    """/system_stats, or None when nothing answers on FILM_COMFY_URL."""
    try:
        return call("GET", "/system_stats", timeout=5)
    except ComfyError:
        return None


def stats_summary(st):
    s = st.get("system", {})
    dev = (st.get("devices") or [{}])[0]
    gb = lambda n: f"{(n or 0) / 2**30:.1f}"
    py = (s.get("python_version") or "?").split()[0]
    lines = [f"ComfyUI {s.get('comfyui_version', '?')} at {base_url()} · python {py} · torch {s.get('pytorch_version', '?')}",
             f"device {dev.get('name', '?')} · VRAM free {gb(dev.get('vram_free'))} / {gb(dev.get('vram_total'))} GB"
             f" · RAM free {gb(s.get('ram_free'))} / {gb(s.get('ram_total'))} GB"]
    return lines


def offline_flag(st):
    """True when the server runs with a flag that blocks the paid partner/API nodes."""
    argv = (st.get("system") or {}).get("argv") or []
    return any(a in ("--offline", "--disable-api-nodes", "--disable-partner-nodes") for a in argv)


# --- lock and workflows ----------------------------------------------------------------------------------------------
def load_lock(path=None):
    path = path or LOCK_FILE
    try:
        with open(path, encoding="utf-8") as f:
            lock = json.load(f)
    except (OSError, ValueError) as e:
        refuse(f"lock {path}: cannot read it ({type(e).__name__}: {e})")
    if not isinstance(lock, dict) or not isinstance(lock.get("models"), list):
        refuse(f"lock {path}: expected an object with a 'models' list")
    for n, m in enumerate(lock["models"]):
        for k in ("set", "folder", "file"):
            if not isinstance(m.get(k), str) or not m[k]:
                refuse(f"lock {path}: models[{n}].{k} must be a non-empty string")
        if m.get("size") is not None and (not isinstance(m["size"], int) or m["size"] < 0):
            refuse(f"lock {path}: models[{n}].size must be bytes (int) or null")
        if m.get("sha256") is not None and not re.fullmatch(r"[0-9a-f]{64}", str(m["sha256"])):
            refuse(f"lock {path}: models[{n}].sha256 must be 64 lowercase hex digits or null")
    for n, c in enumerate(lock.get("custom_nodes") or []):
        for k in ("name", "repo", "commit"):
            if not isinstance(c.get(k), str) or not c[k]:
                refuse(f"lock {path}: custom_nodes[{n}].{k} must be a non-empty string")
    return lock


def workflow_ids():
    try:
        names = sorted(os.listdir(WORKFLOWS))
    except OSError:
        return []
    return [n[:-len(".meta.json")] for n in names
            if n.endswith(".meta.json") and os.path.isfile(os.path.join(WORKFLOWS, n[:-len(".meta.json")] + ".json"))]


def graph_classes(graph):
    return {n.get("class_type") for n in graph.values() if isinstance(n, dict)}


def disallowed(graph):
    return sorted(str(c) for c in graph_classes(graph) - ALLOWED_NODES)


def load_workflow(wid):
    """(graph, meta, sha256 of the template file) of a shipped workflow; refusal for anything unknown or unsafe."""
    ids = workflow_ids()
    if wid not in ids:
        refuse(f"unknown workflow {wid!r} (known: {', '.join(ids) or 'none'})")
    gpath = os.path.join(WORKFLOWS, wid + ".json")
    try:
        with open(gpath, "rb") as f:
            raw = f.read()
        graph = json.loads(raw)
        with open(os.path.join(WORKFLOWS, wid + ".meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError) as e:
        refuse(f"workflow {wid}: cannot read it ({type(e).__name__}: {e})")
    if not isinstance(graph, dict) or "nodes" in graph or not all(
            isinstance(n, dict) and "class_type" in n and isinstance(n.get("inputs"), dict) for n in graph.values()):
        refuse(f"workflow {wid}: not a ComfyUI API-format graph ({{id: {{class_type, inputs}}}}; export it with "
               "'Export (API)', the UI format with nodes/links is rejected)")
    bad = disallowed(graph)
    if bad:
        refuse(f"workflow {wid}: node class(es) outside the allow list: {', '.join(bad)} (paid API nodes and "
               "unpinned custom nodes never run from here)")
    return graph, meta, hashlib.sha256(raw).hexdigest()


# --- graph filling ----------------------------------------------------------------------------------------------------
def set_param(graph, meta, name, value):
    for node, inp in meta["params"].get(name, []):
        graph[node]["inputs"][inp] = value


def drop_optional(graph, meta, feature):
    """Remove an optional feature from the graph (its nodes, the inputs that pointed at them, rewired links)."""
    opt = meta.get("optional", {}).get(feature)
    if not opt:
        return
    for node in opt.get("remove", []):
        graph.pop(node, None)
    for node, inp in opt.get("drop", []):
        graph[node]["inputs"].pop(inp, None)
    for node, inp, src, slot in opt.get("rewire", []):
        graph[node]["inputs"][inp] = [src, slot]


def dangling(graph):
    """['node.input -> missing'] for every link to a node that is not in the graph."""
    out = []
    for nid, n in graph.items():
        for k, v in n["inputs"].items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] not in graph:
                out.append(f"{nid}.{k} -> {v[0]}")
    return out


def build_graph(template, meta, v):
    """The API graph for one request: template + values `v` (dict), optional parts removed, refs and guides added."""
    g = json.loads(json.dumps(template))
    for name in ("prompt", "width", "height", "frames", "seed", "steps", "fps", "prefix", "ref_size"):
        if name in v and name in meta["params"]:
            set_param(g, meta, name, v[name])
    for name in meta.get("images", {}):
        if v.get(name):
            set_param(g, meta, name, v[name])
        else:
            drop_optional(g, meta, name)
    if not v.get("turbo"):
        drop_optional(g, meta, "turbo")
    refs = meta.get("refs")
    if refs:
        nid = refs["ids_from"]
        for i, name in enumerate(v.get("refs") or []):
            g[str(nid + i)] = {"class_type": "LoadImage", "inputs": {"image": name}}
            g[refs["node"]]["inputs"][f"{refs['prefix']}{refs['first'] + i}"] = [str(nid + i), 0]
    gd = meta.get("guides")
    if gd and v.get("guides"):
        prev, nid = list(gd["positive"]), gd["ids_from"]
        for i, (frame, name) in enumerate(v["guides"]):
            load_id, guide_id = str(nid + 2 * i), str(nid + 2 * i + 1)
            g[load_id] = {"class_type": "LoadImage", "inputs": {"image": name}}
            g[guide_id] = {"class_type": "MiniMaxH3AddGuide", "inputs": {
                "positive": prev, "latent": list(gd["latent"]), "vae": list(gd["vae"]),
                "audio_vae": list(gd["audio_vae"]), "image": [load_id, 0], "frame_idx": frame}}
            prev = [guide_id, 0]
        g[gd["consumer"][0]]["inputs"][gd["consumer"][1]] = prev
    return g


def graph_sha(graph):
    return hashlib.sha256(json.dumps(graph, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def snap_frames(seconds, meta):
    """Frame count for `seconds`: round(seconds*fps) snapped UP to the model's grid (H3: 17k+5, at least 5)."""
    step, rem = meta["frames"]["grid"]
    n = max(meta["frames"]["min"], round(seconds * meta["fps"]))
    return n + (rem - n % step) % step


def canvas(meta, res):
    w, h = meta["res"][res]
    return w, h


def crop_box(sw, sh, w, h):
    """(left, top, right, bottom) of the largest centered box of the source with the aspect w:h."""
    if sw * h > sh * w:          # source wider: crop the sides
        cw = round(sh * w / h)
        left = (sw - cw) // 2
        return left, 0, left + cw, sh
    ch = round(sw * h / w)
    top = (sh - ch) // 2
    return 0, top, sw, top + ch


def image_size(path):
    """(width, height) of a PNG, JPEG or WEBP file, with the stdlib (dry-run needs no Pillow); None if unknown."""
    try:
        with open(path, "rb") as f:
            head = f.read(64)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", head[16:24])
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                kind = head[12:16]
                if kind == b"VP8 ":
                    w, h = struct.unpack("<HH", head[26:30])
                    return w & 0x3FFF, h & 0x3FFF
                if kind == b"VP8L":
                    b = head[21:25]
                    return 1 + (((b[1] & 0x3F) << 8) | b[0]), 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
                if kind == b"VP8X":
                    return 1 + int.from_bytes(head[24:27], "little"), 1 + int.from_bytes(head[27:30], "little")
                return None
            if head[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    m = f.read(2)
                    if len(m) < 2 or m[0] != 0xFF:
                        return None
                    if m[1] in (0xD8, 0x01) or 0xD0 <= m[1] <= 0xD7:
                        continue
                    seg = f.read(2)
                    if len(seg) < 2:
                        return None
                    n = struct.unpack(">H", seg)[0]
                    if 0xC0 <= m[1] <= 0xCF and m[1] not in (0xC4, 0xC8, 0xCC):
                        d = f.read(5)
                        h, w = struct.unpack(">HH", d[1:5])
                        return w, h
                    f.seek(n - 2, 1)
    except (OSError, struct.error, IndexError):
        return None
    return None


def prepare_frame(src, w, h, dst):
    """Center-crop src to w:h, resize with Lanczos to exactly w x h, save PNG to dst (src is never touched)."""
    from PIL import Image, ImageOps
    with Image.open(src) as im0:
        im = ImageOps.exif_transpose(im0)
        if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
            im = im.convert("RGBA")
            flat = Image.new("RGB", im.size, (255, 255, 255))
            flat.paste(im, mask=im.getchannel("A"))
            im = flat
        elif im.mode != "RGB":
            im = im.convert("RGB")
        im = im.crop(crop_box(im.width, im.height, w, h)).resize((w, h), Image.LANCZOS)
        im.save(dst, "PNG")


def sha256_file(path, chunk=1 << 22):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


# --- prompt -------------------------------------------------------------------------------------------------------
def read_prompt_file(path, fmt):
    """Assemble the prompt from a JSON/YAML file with the workflow's fields (README: prompt format)."""
    fields = PROMPT_FIELDS[fmt]
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        refuse(f"--prompt-file {path}: cannot read it ({type(e).__name__})")
    if path.lower().endswith((".yaml", ".yml")):
        try:
            import yaml
        except ImportError:
            refuse("--prompt-file .yaml needs PyYAML (pip install pyyaml) or use a .json file")
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            refuse(f"--prompt-file {path}: invalid YAML ({' '.join(str(e).split())[:160]})")
    else:
        try:
            data = json.loads(text)
        except ValueError as e:
            refuse(f"--prompt-file {path}: invalid JSON ({e})")
    if not isinstance(data, dict):
        refuse(f"--prompt-file {path}: expected a mapping with {', '.join(fields)}")
    unknown = [k for k in data if k not in fields]
    missing = [k for k in fields if not (isinstance(data.get(k), str) and data[k].strip())]
    if unknown or missing:
        refuse(f"--prompt-file {path}: " + "; ".join(
            x for x in (f"unknown field(s) {', '.join(map(str, unknown))}" if unknown else "",
                        f"missing or empty field(s) {', '.join(missing)}" if missing else "") if x)
               + f" (fields of {fmt}: {', '.join(fields)})")
    return "\n\n".join(f"{k}:\n{data[k].strip()}" for k in fields)


def assemble_prompt(a, meta, has_image):
    fmt = meta["prompt_format"]
    if a.prompt_file:
        body = read_prompt_file(a.prompt_file, fmt)
    else:
        body = a.prompt.strip()
        if not body:
            refuse("--prompt is empty")
    if fmt == "i2v" and has_image and not body.startswith("For the target video,"):
        body = I2V_HEADER + "\n\n" + body
    return body


# --- ledger -------------------------------------------------------------------------------------------------------
def ledger_args(a):
    a.ledger = a.ledger or os.environ.get("FILM_LEDGER") or None
    a.budget = None
    agent = os.environ.get("FILM_AGENT")
    if a.no_ledger and agent:
        refuse(f"--no-ledger is for ad-hoc tests in the main session; FILM_AGENT={agent} is set, so it is refused "
               "(nothing sent). Pass --ledger out/<project>/ep<NN>/ledger.csv")
    if a.no_ledger and a.ledger:
        refuse("--no-ledger and --ledger together: pick one")
    if not a.ledger and not a.no_ledger:
        refuse("run needs --ledger (or FILM_LEDGER): every local clip is logged like a paid one (cost 0); "
               "--no-ledger only for ad-hoc tests in the main session")
    if a.ledger:
        ark.check_ledger_header(a.ledger)


# --- run ----------------------------------------------------------------------------------------------------------
def parse_guide(text):
    m = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*[=:@](.+)", text)
    if not m:
        refuse(f"--guide {text!r}: use SECONDS=IMAGE, e.g. --guide 2.5=key2.png")
    return float(m.group(1)), m.group(2)


def check_inputs(a, meta, wid):
    """Every local refusal of `run` that needs no server; returns the plan dict."""
    if a.negative is not None and meta.get("negative") is False:
        refuse(f"{wid}: --negative is refused: the model is CFG-distilled (BasicGuider, cfg 1) and ignores a "
               "negative prompt; describe what you want in the prompt instead")
    if (a.prompt is None) == (a.prompt_file is None):
        refuse("give exactly one of --prompt TEXT or --prompt-file F.json|.yaml")
    images = meta.get("images", {})
    if a.image and "image" not in images:
        refuse(f"{wid} takes no --image (references: --ref IMG; a frame anchor: --guide 0=IMG)")
    if a.last and "last" not in images:
        refuse(f"{wid} has no end-frame input: --last is refused (use h3-i2v --image START --last END)")
    if a.last and not a.image:
        refuse("--last needs --image (first-last-frame); for one end frame alone use h3-r2v --guide")
    if (a.ref or a.ref_size) and not meta.get("refs"):
        refuse(f"{wid} takes no --ref/--ref-size (use h3-r2v)")
    if a.guide and not meta.get("guides"):
        refuse(f"{wid} takes no --guide (use h3-r2v)")
    if a.turbo and not meta.get("turbo"):
        refuse(f"{wid} has no turbo LoRA")
    refs = a.ref or []
    if meta.get("refs"):
        r = meta["refs"]
        if not r["min"] <= len(refs) <= r["max"]:
            refuse(f"{wid} needs {r['min']}..{r['max']} --ref images (<Picture 1..n> in the prompt), got {len(refs)}")
    guides = [parse_guide(t) for t in (a.guide or [])]
    if meta.get("guides") and len(guides) > meta["guides"]["max"]:
        refuse(f"at most {meta['guides']['max']} --guide anchors")
    files = [p for p in [a.image, a.last] + refs + [g[1] for g in guides] if p]
    for p in files:
        if not (os.path.isfile(p) and os.access(p, os.R_OK)):
            refuse(f"no such file: {p}")
        if image_size(p) is None:
            refuse(f"not a PNG/JPEG/WEBP image (or unreadable): {p}")
    if not a.out.lower().endswith(".mp4"):
        refuse(f"--out {a.out}: the workflows save mp4 (H.264 + audio): name it <clips>/<name>_v<NN>.mp4")
    ark.guard_output(a.out)
    if os.path.exists(a.out + ".json"):
        refuse(f"sidecar exists: {a.out}.json (versions only go up)")
    frames_dir = os.path.splitext(a.out)[0] + "_frames"
    if a.keep_frames:
        if not shutil.which("ffmpeg"):
            refuse("--keep-frames needs ffmpeg on PATH")
        if os.path.isdir(frames_dir) and os.listdir(frames_dir):
            refuse(f"{frames_dir} exists and is not empty (versions only go up)")
    res = a.res or meta["defaults"]["res"]
    if res not in meta["res"]:
        refuse(f"--res {res}: {wid} knows {', '.join(meta['res'])}")
    w, h = canvas(meta, res)
    seconds = meta["defaults"]["seconds"] if a.seconds is None else a.seconds
    if not seconds > 0:
        refuse("--seconds must be > 0")
    frames = snap_frames(seconds, meta)
    if frames > meta["frames"]["max"]:
        refuse(f"--seconds {seconds:g}: {frames} frames > the model's {meta['frames']['max']} "
               f"({(meta['frames']['max']) / meta['fps']:.2f} s); make several clips (continue from the last frame)")
    lo = meta["frames"].get("trained", [0])[0]
    if frames < lo:
        warn(f"{frames} frames ({frames / meta['fps']:.2f} s) is below the model's trained range "
             f"({lo}..{meta['frames']['max']} frames)")
    guide_frames = []
    for sec, path in guides:
        idx = round(sec * meta["fps"])
        if not 0 <= idx <= frames - 1:
            refuse(f"--guide {sec:g}={path}: frame {idx} is outside the clip's {frames} frames "
                   f"(0..{(frames - 1) / meta['fps']:.2f} s)")
        guide_frames.append((idx, path))
    steps = a.steps or (meta["turbo"]["steps"] if a.turbo else meta["defaults"]["steps"])
    if steps < 1:
        refuse("--steps must be >= 1")
    if a.turbo:
        warn(f"--turbo: Lightning LoRA at {steps} steps. Drafts only, never for faces or quality runs"
             + (" (and this is the 768p quality canvas)" if res == "768p" else ""))
    seed = a.seed if a.seed is not None else secrets.randbelow(2**32)
    if not 0 <= seed <= 0xFFFFFFFFFFFFFFFF:
        refuse("--seed must be 0..2^64-1")
    return {"res": res, "width": w, "height": h, "seconds": seconds, "frames": frames, "fps": meta["fps"],
            "steps": steps, "seed": seed, "refs": refs, "guides": guide_frames, "frames_dir": frames_dir,
            "clip_seconds": round(frames / meta["fps"], 3), "turbo": bool(a.turbo),
            "ref_size": a.ref_size or "match"}


def model_entries(graph, lock):
    """[(node id, class, input, lock entry or None, file)] of every model file the graph loads."""
    by_file = {m["file"]: m for m in lock["models"]}
    out = []
    for nid in sorted(graph, key=lambda x: (len(x), x)):
        n = graph[nid]
        inp = MODEL_INPUTS.get(n["class_type"])
        if inp and isinstance(n["inputs"].get(inp), str):
            f = n["inputs"][inp]
            out.append((nid, n["class_type"], inp, by_file.get(f), f))
    return out


def find_model(mdir, folder, file):
    for sub in MODEL_FOLDER_ALIASES.get(folder, (folder,)):
        p = os.path.join(mdir, sub, file)
        if os.path.isfile(p):
            return p
    return None


def combo_choices(spec):
    """The options of an /object_info input spec ([list, {...}] or ['COMBO', {'options': [...]}])."""
    if isinstance(spec, list) and spec:
        if isinstance(spec[0], list):
            return spec[0]
        if spec[0] == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
            return spec[1].get("options") or []
    return None


def server_problems(graph, models):
    """Node classes and model files the running server does not have (from /object_info/<class>)."""
    problems, info = [], {}
    for cls in sorted(graph_classes(graph)):
        got = call("GET", "/object_info/" + urllib.parse.quote(cls))
        if cls not in got:
            problems.append(f"node {cls} is not installed in this ComfyUI (update ComfyUI: H3 nodes are core "
                            "from v0.43)")
        else:
            info[cls] = got[cls]
    for nid, cls, inp, entry, f in models:
        if cls not in info:
            continue
        ins = info[cls].get("input", {})
        spec = (ins.get("required") or {}).get(inp) or (ins.get("optional") or {}).get(inp)
        choices = combo_choices(spec)
        if choices is not None and f not in choices:
            where = entry["folder"] if entry else "models"
            problems.append(f"model {f} ({cls}.{inp}) is not in ComfyUI's {where}/ list")
    return problems


def multipart(fields, file_field, filename, data, mime):
    b = "----filmlab" + uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    out.write(f'--{b}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
              f"Content-Type: {mime}\r\n\r\n".encode())
    out.write(data)
    out.write(f"\r\n--{b}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={b}"


def upload(path, name):
    with open(path, "rb") as f:
        data = f.read()
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(
        os.path.splitext(name)[1].lower(), "application/octet-stream")
    body, ctype = multipart({"type": "input", "overwrite": "false"}, "image", name, data, mime)
    r = call("POST", "/upload/image", raw=body, ctype=ctype, timeout=UPLOAD_TIMEOUT)
    got = r.get("name") or name
    return f"{r['subfolder']}/{got}" if r.get("subfolder") else got


def queue_state(pid):
    try:
        q = call("GET", "/queue")
    except ComfyError:
        return "?"
    if any(len(x) > 1 and x[1] == pid for x in q.get("queue_running") or []):
        return "running"
    pend = [x for x in q.get("queue_pending") or [] if len(x) > 1]
    for n, x in enumerate(sorted(pend, key=lambda x: x[0])):
        if x[1] == pid:
            return f"queued ({n} ahead)"
    return "waiting"


def stop_prompt(pid):
    """Interrupt our prompt if it runs, drop it from the queue if it waits. Never a global interrupt."""
    msgs = []
    try:
        call("POST", "/interrupt", {"prompt_id": pid}, timeout=10)
        msgs.append("interrupt sent")
    except ComfyError as e:
        msgs.append(f"interrupt failed ({e})")
    try:
        call("POST", "/queue", {"delete": [pid]}, timeout=10)
    except ComfyError:
        pass
    return "; ".join(msgs)


def exec_messages(entry):
    return {ev: data for ev, data in ((m[0], m[1]) for m in (entry.get("status") or {}).get("messages") or []
                                      if isinstance(m, (list, tuple)) and len(m) == 2)}


def gpu_seconds(entry, wall):
    msgs = exec_messages(entry)
    try:
        t0 = msgs["execution_start"]["timestamp"]
        t1 = (msgs.get("execution_success") or msgs.get("execution_error") or msgs.get("execution_interrupted"))["timestamp"]
        return round((t1 - t0) / 1000.0, 1)
    except (KeyError, TypeError):
        return round(wall, 1)


def find_output(entry, node):
    outs = entry.get("outputs") or {}
    order = [node] + [k for k in outs if k != node]
    for nid in order:
        for v in (outs.get(nid) or {}).values():
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, dict) and str(item.get("filename", "")).lower().endswith(".mp4"):
                        return item
    return None


def download_view(item, out):
    q = urllib.parse.urlencode({"filename": item["filename"], "subfolder": item.get("subfolder") or "",
                                "type": item.get("type") or "output"})
    data = call("GET", "/view?" + q, want="bytes", timeout=300)
    if not data:
        raise ComfyError("empty file from /view")
    part = out + ".part"
    with open(part, "wb") as f:
        f.write(data)
    os.replace(part, out)


def write_json_atomic(path, obj):
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def run(a):
    wid = a.workflow
    template, meta, wf_sha = load_workflow(wid)
    plan = check_inputs(a, meta, wid)
    ledger_args(a)
    has_image = bool(a.image)
    prompt = assemble_prompt(a, meta, has_image)
    lock = load_lock()
    w, h = plan["width"], plan["height"]
    values = {"prompt": prompt, "width": w, "height": h, "frames": plan["frames"], "seed": plan["seed"],
              "steps": plan["steps"], "fps": float(plan["fps"]), "prefix": f"film-lab/{wid}",
              "ref_size": plan["ref_size"], "turbo": plan["turbo"],
              "image": "<start>" if a.image else None, "last": "<end>" if a.last else None,
              "refs": [f"<ref{i + 1}>" for i in range(len(plan["refs"]))],
              "guides": [(idx, f"<guide{i + 1}>") for i, (idx, _) in enumerate(plan["guides"])]}
    graph = build_graph(template, meta, values)
    bad = disallowed(graph) or dangling(graph)
    if bad:
        refuse(f"{wid}: filled graph is not runnable: {', '.join(bad)}")
    models = model_entries(graph, lock)
    model = MODEL_PREFIX + wid
    print(f"workflow {wid} ({model}) · {len(graph)} nodes · {w}x{h} ({plan['res']}) · {plan['frames']} frames "
          f"= {plan['clip_seconds']:g} s at {plan['fps']} fps · steps {plan['steps']}"
          f"{' (turbo LoRA)' if plan['turbo'] else ''} · seed {plan['seed']}")
    for label, path in (("start", a.image), ("end", a.last)):
        if path:
            sw, sh = image_size(path)
            box = crop_box(sw, sh, w, h)
            print(f"{label} frame {path}: {sw}x{sh} -> center crop {box[2] - box[0]}x{box[3] - box[1]} -> {w}x{h} lanczos")
    for i, p in enumerate(plan["refs"], 1):
        print(f"<Picture {i}> {p} (ref_image_size {plan['ref_size']})")
    for idx, p in plan["guides"]:
        print(f"guide frame {idx} ({idx / plan['fps']:.2f} s): {p} -> {w}x{h} lanczos")
    print("models: " + ", ".join(f for *_, f in models))
    est = plan["steps"] * SECONDS_PER_STEP.get(plan["res"], 34.0) * plan["frames"] / 124 + SETUP_SECONDS
    print(f"estimate ~{est / 60:.1f} min of GPU (estimate; measure)")
    mdir = models_dir(layout(comfy_home()))
    if a.dry_run:
        if mdir and os.path.isdir(mdir):
            for _, _, _, entry, f in models:
                if not find_model(mdir, entry["folder"] if entry else "", f):
                    warn(f"model file not found under {mdir}: {f}")
        print("prompt:\n  " + prompt.replace("\n", "\n  "))
        print("dry-run: nothing uploaded or queued, no ledger row")
        return 0
    stats = system_stats()
    if stats is None:
        refuse(f"ComfyUI is not reachable at {base_url()}: start it with `python tools/comfy/comfy.py start` "
               "(nothing sent)")
    if not offline_flag(stats):
        warn("this ComfyUI was not started with --offline: paid partner nodes are loaded (run never queues them: "
             "allow list)")
    try:
        problems = server_problems(graph, models)
    except ComfyError as e:
        refuse(f"/object_info failed ({e}); nothing sent")
    if problems:
        refuse("the server cannot run this graph, nothing sent:\n  " + "\n  ".join(problems))
    rid = ark.new_req()
    tmpdir = tempfile.mkdtemp(prefix="film-comfy-")
    try:
        uploads, inputs, todo = {}, {}, []
        for key, path, prep in ([("image", a.image, True), ("last", a.last, True)]
                                + [(f"ref{i + 1}", p, False) for i, p in enumerate(plan["refs"])]
                                + [(f"guide{i + 1}", p, True) for i, (_, p) in enumerate(plan["guides"])]):
            if not path:
                continue
            if prep:            # every frame is prepared before the first upload: a refusal here sends nothing
                src = os.path.join(tmpdir, f"{key}.png")
                try:
                    prepare_frame(path, w, h, src)
                except ImportError:
                    refuse("Pillow is needed to crop/resize frames: pip install Pillow (nothing sent)")
                except Exception as e:      # an image Pillow cannot read
                    refuse(f"cannot prepare {path} ({type(e).__name__}: {e}); nothing sent")
                name = f"film-lab_{rid[:12]}_{key}.png"
            else:
                src, name = path, f"film-lab_{rid[:12]}_{key}{os.path.splitext(path)[1].lower()}"
            todo.append((key, path, src, name))
        try:
            for key, path, src, name in todo:
                uploads[key] = upload(src, name)
                inputs[key] = {"path": path, "sha256": sha256_file(path), "size": list(image_size(path)),
                               "uploaded": uploads[key], "uploaded_sha256": sha256_file(src)}
        except ComfyError as e:
            refuse(f"upload failed ({e}); nothing queued, no ledger row")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    values.update(image=uploads.get("image"), last=uploads.get("last"),
                  refs=[uploads[f"ref{i + 1}"] for i in range(len(plan["refs"]))],
                  guides=[(idx, uploads[f"guide{i + 1}"]) for i, (idx, _) in enumerate(plan["guides"])])
    graph = build_graph(template, meta, values)
    gsha = graph_sha(graph)
    pid = str(uuid.uuid4())
    req = {"kind": "video", "model": model, "size": f"{w}x{h}", "seconds": f"{plan['clip_seconds']:g}", "count": 1,
           "out": a.out, "task_id": pid}
    seed_note = f"seed={plan['seed']}"
    ark.make_out_dir(a.out)
    ark.reserve(a, req, rid, tag=seed_note)
    t0 = time.monotonic()
    state = {"logged": False}

    def final(status, note="", usage=""):
        if not state["logged"]:
            ark.log_row(a, req, rid, status, "; ".join(x for x in (seed_note, note) if x), usage=usage)
            state["logged"] = True

    try:
        try:
            r = call("POST", "/prompt", {"prompt": graph, "client_id": "film-lab-" + rid[:12], "prompt_id": pid})
        except ComfyError as e:
            detail = e.body or str(e)
            try:
                j = json.loads(e.body or "")
                errs = [f"{n}: " + "; ".join(x.get("message", "") + " " + str(x.get("details", ""))
                                             for x in v.get("errors", [])) for n, v in (j.get("node_errors") or {}).items()]
                detail = (j.get("error") or {}).get("message", "") + (" | " + " | ".join(errs) if errs else "")
            except ValueError:
                pass
            final("failed", "prompt refused by ComfyUI: " + " ".join(detail.split())[:300])
            print(f"ComfyUI refused the prompt: {detail}", file=sys.stderr)
            return FAILED
        print(f"queued prompt {r.get('prompt_id', pid)} (req {rid[:12]})", flush=True)
        entry, last_state, last_print, errors = None, None, 0.0, 0
        while True:
            el = time.monotonic() - t0
            try:
                hist = call("GET", f"/history/{pid}")
                errors = 0
            except ComfyError as e:
                errors += 1
                if errors > POLL_ERRORS:
                    final("failed", f"polling stopped: {e}", f"gpu_s={round(el, 1)}")
                    print(f"lost the server while polling ({e}); prompt {pid} may still run: "
                          f"python tools/comfy/comfy.py interrupt --prompt-id {pid}", file=sys.stderr)
                    return FAILED
                hist = {}
            entry = hist.get(pid)
            st = (entry or {}).get("status") or {}
            if entry and (st.get("completed") or st.get("status_str") in ("success", "error")):
                break
            if el > a.timeout:
                note = stop_prompt(pid)
                final("interrupted", f"timeout after {a.timeout:g}s ({note})", f"gpu_s={round(el, 1)}")
                print(f"timeout after {a.timeout:g}s: prompt {pid} stopped ({note})", file=sys.stderr)
                return FAILED
            s = queue_state(pid)
            if s != last_state or el - last_print >= PROGRESS_SECONDS:
                print(f"step {s} elapsed {int(el)}s", flush=True)
                last_state, last_print = s, el
            time.sleep(POLL_SECONDS)
        wall = time.monotonic() - t0
        gpu = gpu_seconds(entry, wall)
        usage = f"gpu_s={gpu:g}"
        msgs = exec_messages(entry)
        if st.get("status_str") != "success" or "execution_error" in msgs or "execution_interrupted" in msgs:
            if "execution_interrupted" in msgs:
                final("interrupted", "interrupted on the server", usage)
                print(f"prompt {pid} was interrupted", file=sys.stderr)
                return FAILED
            err = msgs.get("execution_error") or {}
            why = f"{err.get('node_type', '?')} (node {err.get('node_id', '?')}): {err.get('exception_message', st)}"
            final("failed", "execution error: " + " ".join(str(why).split())[:300], usage)
            print(f"ComfyUI execution error: {why}", file=sys.stderr)
            return FAILED
        item = find_output(entry, meta["output"]["node"])
        if not item:
            final("failed", "no mp4 in the prompt's history outputs", usage)
            print("the prompt finished but its history lists no mp4 output", file=sys.stderr)
            return FAILED
        try:
            download_view(item, a.out)
        except (ComfyError, OSError) as e:
            final("failed", f"download failed: {e}; the clip is in ComfyUI's output folder: "
                            f"{item.get('subfolder', '')}/{item['filename']}", usage)
            print(f"DOWNLOAD FAILED ({e}); the clip is in ComfyUI's output folder as "
                  f"{item.get('subfolder', '')}/{item['filename']}", file=sys.stderr)
            return FAILED
        sidecar = {
            "tool": "tools/comfy/comfy.py", "workflow": wid, "model": model, "workflow_file_sha256": wf_sha,
            "graph_sha256": gsha, "prompt_id": pid, "req": rid, "seed": plan["seed"], "prompt": prompt,
            "width": w, "height": h, "res": plan["res"], "frames": plan["frames"], "fps": plan["fps"],
            "seconds_asked": plan["seconds"], "seconds": plan["clip_seconds"], "steps": plan["steps"],
            "turbo": plan["turbo"], "ref_image_size": plan["ref_size"] if meta.get("refs") else None,
            "guides": [{"frame": idx, "seconds": round(idx / plan["fps"], 3), "image": p}
                       for idx, p in plan["guides"]],
            "inputs": inputs,
            "models": [{"file": f, "folder": e["folder"] if e else None, "size": e.get("size") if e else None,
                        "sha256": e.get("sha256") if e else None} for _, _, _, e, f in models],
            "comfyui": {"version": stats.get("system", {}).get("comfyui_version"),
                        "pytorch": stats.get("system", {}).get("pytorch_version"),
                        "python": (stats.get("system", {}).get("python_version") or "").split(" ")[0],
                        "device": ((stats.get("devices") or [{}])[0]).get("name"), "offline": offline_flag(stats),
                        "url": base_url()},
            "gpu_seconds": gpu, "wall_seconds": round(wall, 1), "output": item, "created": ark.utc_now(),
            "graph": graph,
        }
        write_json_atomic(a.out + ".json", sidecar)
        final("ok", "", usage)
        print(f"saved {a.out} ({plan['clip_seconds']:g} s, {gpu:g} GPU s) + {os.path.basename(a.out)}.json")
        if a.keep_frames:
            os.makedirs(plan["frames_dir"], exist_ok=True)
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", a.out,
                   os.path.join(plan["frames_dir"], "%04d.png")]
            if subprocess.run(cmd).returncode != 0:
                warn(f"ffmpeg could not write the frames to {plan['frames_dir']} (the clip is saved)")
            else:
                print(f"frames in {plan['frames_dir']}")
        return 0
    except BaseException as e:
        if not state["logged"]:
            if isinstance(e, ark.Interrupted):
                final("interrupted", f"{e} ({stop_prompt(pid)})", f"gpu_s={round(time.monotonic() - t0, 1)}")
            else:
                final("failed", ark.err_note(e))
        raise


# --- other commands ---------------------------------------------------------------------------------------------------
def ping(a):
    st = system_stats()
    if st is None:
        print(f"ComfyUI is not reachable at {base_url()} (start it: python tools/comfy/comfy.py start)",
              file=sys.stderr)
        return FAILED
    for line in stats_summary(st):
        print(line)
    print("offline: " + ("yes (paid partner/API nodes blocked)" if offline_flag(st) else
                         "NO: started without --offline, paid partner/API nodes are loaded (run never queues them)"))
    return 0


def start(a):
    url = urllib.parse.urlparse(base_url())
    host, port = url.hostname or "127.0.0.1", url.port or 8188
    st = system_stats()
    if st is not None:
        print(f"a ComfyUI already answers at {base_url()}: nothing started")
        for line in stats_summary(st):
            print(line)
        return 0
    if host not in ("127.0.0.1", "localhost", "::1"):
        refuse(f"FILM_COMFY_URL {base_url()} is not this machine: start only launches a local server")
    home = comfy_home()
    lay = layout(home)
    if not lay:
        refuse(f"no ComfyUI install at {home or '(FILM_COMFY_HOME unset)'}: set FILM_COMFY_HOME to the folder "
               "with ComfyUI/main.py (Comfy Desktop: %LOCALAPPDATA%\\Comfy-Desktop\\ComfyUI-Installs\\ComfyUI)")
    if not lay["python"]:
        refuse(f"no python found for {home}: set FILM_COMFY_PYTHON")
    try:
        with open(os.path.join(lay["root"], "comfy", "cli_args.py"), encoding="utf-8") as f:
            cli = f.read()
    except OSError:
        cli = ""
    flag = next((f for f in ("--offline", "--disable-partner-nodes", "--disable-api-nodes") if f'"{f}"' in cli), None)
    if not flag:
        refuse(f"{lay['root']}/comfy/cli_args.py has no flag that blocks the paid API nodes (--offline); "
               "update ComfyUI")
    cmd = [lay["python"], "-s", os.path.join(lay["root"], "main.py"), "--listen", host, "--port", str(port),
           "--disable-auto-launch", flag]
    yaml_paths = model_paths_yaml()
    if yaml_paths and os.path.isfile(yaml_paths):
        cmd += ["--extra-model-paths-config", yaml_paths]
    # The lab's uploads, outputs, temp files and UI state go to its own work folder (default out/_comfy in the lab,
    # git-ignored), never into Comfy Desktop's shared input/output folders: those sit on the owner's small C: drive
    # and hold the owner's own files. Models still come from the Desktop's shared models folder.
    work = comfy_work()
    for kind in ("input", "output", "temp", "user"):
        cmd += [f"--{kind}-directory", os.path.join(work, kind)]
    log = os.path.join(work, "server.log")
    print("command: " + subprocess.list2cmdline(cmd))
    print(f"log: {log}")
    if a.dry_run:
        print("dry-run: not started")
        return 0
    for kind in ("input", "output", "temp", "user"):
        os.makedirs(os.path.join(work, kind), exist_ok=True)
    kw = {"stdin": subprocess.DEVNULL, "cwd": lay["root"]}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    with open(log, "ab") as lf:
        proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, env=env, **kw)
    print(f"started pid {proc.pid}; waiting up to {a.wait}s for {base_url()}", flush=True)
    t0 = time.monotonic()
    while time.monotonic() - t0 < a.wait:
        st = system_stats()
        if st is not None:
            for line in stats_summary(st):
                print(line)
            return 0
        if proc.poll() is not None:
            print(f"ComfyUI exited with code {proc.returncode}; last lines of {log}:", file=sys.stderr)
            print(_tail(log), file=sys.stderr)
            return FAILED
        time.sleep(START_POLL)
    print(f"ComfyUI (pid {proc.pid}) is not answering after {a.wait}s; it may still be loading. Check {log} "
          "and run `comfy.py ping`", file=sys.stderr)
    return FAILED


def _tail(path, n=20):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-n:])
    except OSError:
        return "(no log)"


def model_rows(lock, mdir, set_name=None, verify=False):
    """[(entry, path or None, state, ok)] for every model of the lock (of one set)."""
    rows = []
    for m in lock["models"]:
        if set_name and m["set"] != set_name:
            continue
        p = find_model(mdir, m["folder"], m["file"]) if mdir else None
        if not p:
            opt = m.get("optional")
            rows.append((m, None, "missing" + (f" (optional: {opt})" if opt else ""), bool(opt)))
            continue
        size = os.path.getsize(p)
        if m.get("size") is not None and size != m["size"]:
            rows.append((m, p, f"size {size} != {m['size']} (incomplete or another file)", False))
            continue
        if verify and m.get("sha256"):
            got = sha256_file(p)
            ok = got == m["sha256"]
            rows.append((m, p, "sha256 ok" if ok else f"sha256 MISMATCH ({got[:12]}...)", ok))
        elif verify:
            rows.append((m, p, "present, not pinned (no sha256 in the lock)", True))
        else:
            rows.append((m, p, "ok" if m.get("size") is not None else "present (size not pinned)", True))
    return rows


def models_cmd(a):
    lock = load_lock(a.lock)
    lay = layout(comfy_home())
    mdir = models_dir(lay)
    if not mdir:
        refuse("no models folder: set FILM_COMFY_MODELS (or FILM_COMFY_HOME)")
    sets = sorted({m["set"] for m in lock["models"]})
    if a.set and a.set not in sets:
        refuse(f"--set {a.set}: the lock has {', '.join(sets) or 'no set'}")
    print(f"models folder: {mdir}")
    rows = model_rows(lock, mdir, a.set, a.verify)
    for m, p, state, ok in rows:
        size = f"{m['size'] / 1e9:.2f} GB" if m.get("size") else "-"
        print(f"{'ok ' if ok else 'BAD'} {m['set']:12} {m['folder'] + '/' + m['file']:70} {size:>9}  {state}")
    bad = sum(1 for *_, ok in rows if not ok)
    print(f"{len(rows) - bad}/{len(rows)} ok")
    return FAILED if bad else 0


def fetch(url, dest, size, sha):
    """Download url to dest via dest.part (resumed with Range), check size and sha256, then rename."""
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    if size and have > size:
        os.remove(part)
        have = 0
    if not size or have < size:
        req = urllib.request.Request(url, headers={"User-Agent": "film-lab-comfy/1"})
        if have:
            req.add_header("Range", f"bytes={have}-")
        with urllib.request.urlopen(req, timeout=60) as r:
            if have and r.status != 206:
                have = 0
            with open(part, "ab" if have else "wb") as f:
                got, last = have, 0.0
                while True:
                    chunk = r.read(1 << 22)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if size and time.monotonic() - last > 10:
                        print(f"  {got / 1e9:.2f} / {size / 1e9:.2f} GB", flush=True)
                        last = time.monotonic()
    if size and os.path.getsize(part) != size:
        raise OSError(f"size {os.path.getsize(part)} != {size}")
    if sha and sha256_file(part) != sha:
        os.replace(part, dest + ".bad")
        raise OSError(f"sha256 mismatch (kept as {dest}.bad)")
    os.replace(part, dest)


def install(a):
    lock = load_lock(a.lock)
    home = comfy_home()
    lay = layout(home)
    bad, plan = 0, []
    if lay:
        plan.append(f"ComfyUI: present at {lay['root']} ({lay['kind']} layout, v{comfy_version(lay['root'])}, "
                    f"python {lay['python'] or 'not found: set FILM_COMFY_PYTHON'})")
    elif a.portable:
        c = lock.get("comfyui") or {}
        if not home:
            refuse("--portable needs FILM_COMFY_HOME (the folder to create)")
        if os.name != "nt" and not a.dry_run:
            refuse("the portable ComfyUI is a Windows build; on this system install ComfyUI yourself")
        parent = os.path.dirname(os.path.abspath(home))
        need = (c.get("size") or 0) * 3
        free = shutil.disk_usage(parent if os.path.isdir(parent) else os.path.dirname(parent) or ".").free
        plan.append(f"ComfyUI: download {c.get('url')} ({(c.get('size') or 0) / 1e9:.2f} GB, sha256 pinned) "
                    f"-> {parent}, extract with tar, rename to {home} (needs ~{need / 1e9:.1f} GB, free "
                    f"{free / 1e9:.1f} GB)")
        if free < need and not a.dry_run:
            refuse(f"not enough disk space on {parent}: {free / 1e9:.1f} GB free, ~{need / 1e9:.1f} GB needed")
    else:
        plan.append(f"ComfyUI: NOT FOUND at {home or '(FILM_COMFY_HOME unset)'}: point FILM_COMFY_HOME at your "
                    "install (Comfy Desktop or portable), or pass --portable to download the pinned portable build")
        bad += 1
    root = lay["root"] if lay else os.path.join(home or "", "ComfyUI")
    for c in lock.get("custom_nodes") or []:
        d = os.path.join(root, "custom_nodes", c["name"])
        head = None
        if os.path.isdir(os.path.join(d, ".git")):
            r = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True)
            head = r.stdout.strip() if r.returncode == 0 else None
        if head == c["commit"]:
            plan.append(f"custom node {c['name']}: present at {c['commit'][:12]}")
        elif os.path.isdir(d):
            plan.append(f"custom node {c['name']}: present at {str(head)[:12]}, lock pins {c['commit'][:12]}: "
                        f"git -C \"{d}\" checkout {c['commit']} (not done automatically)")
            bad += 1
        else:
            plan.append(f"custom node {c['name']}: git clone {c['repo']} + checkout {c['commit'][:12]}; "
                        f"pip install --no-deps {' '.join(c.get('pip') or [])}".rstrip())
    mdir = models_dir(lay)
    for m, p, state, ok in model_rows(lock, mdir, None, False):
        tail = "" if ok or p else f": install never downloads models, put it in {mdir}/{m['folder']}/"
        plan.append(f"model {m['folder']}/{m['file']}: {state}{tail}")
        bad += 0 if ok else 1
    for line in plan:
        print(line)
    if a.dry_run:
        print("dry-run: nothing downloaded or changed")
        return FAILED if bad else 0
    if not lay and a.portable:
        c = lock["comfyui"]
        parent = os.path.dirname(os.path.abspath(home))
        os.makedirs(parent, exist_ok=True)
        arc = os.path.join(parent, c["asset"])
        try:
            if not os.path.exists(arc):
                fetch(c["url"], arc, c["size"], c["sha256"])
            if subprocess.run(["tar", "-xf", arc, "-C", parent]).returncode != 0:
                raise OSError("tar could not extract " + arc)
            top = os.path.join(parent, "ComfyUI_windows_portable")
            if not os.path.exists(home) and os.path.isdir(top):
                os.replace(top, home)
        except (OSError, urllib.error.URLError) as e:
            print(f"ComfyUI download/extract failed: {e}", file=sys.stderr)
            return FAILED
        lay = layout(home)
    for c in lock.get("custom_nodes") or []:
        d = os.path.join(lay["root"] if lay else root, "custom_nodes", c["name"])
        if not os.path.isdir(d):
            ok = (subprocess.run(["git", "clone", c["repo"], d]).returncode == 0
                  and subprocess.run(["git", "-C", d, "checkout", "--detach", c["commit"]]).returncode == 0)
            if ok and c.get("pip") and lay and lay["python"]:
                ok = subprocess.run([lay["python"], "-s", "-m", "pip", "install", "--no-deps", *c["pip"]]).returncode == 0
            if not ok:
                print(f"custom node {c['name']}: install failed", file=sys.stderr)
                bad += 1
    if lay and lay["python"]:
        r = subprocess.run([lay["python"], "-c", "import torch;print(torch.__version__, torch.version.cuda, "
                            "torch.cuda.is_available(), torch.cuda.get_arch_list())"], capture_output=True, text=True)
        print("torch: " + (r.stdout.strip() or r.stderr.strip()[-300:]))
        if "sm_120" not in r.stdout:
            warn("torch does not list sm_120 (RTX 50 / Blackwell): a custom node may have replaced torch")
    return FAILED if bad else 0


def workflows_cmd(a):
    lock = load_lock()
    by_file = {m["file"]: m for m in lock["models"]}
    for wid in workflow_ids():
        graph, meta, _ = load_workflow(wid)
        print(f"{wid}  {meta.get('title', '')}")
        files = [f for *_, f in model_entries(graph, lock)]
        gb = sum((by_file.get(f) or {}).get("size") or 0 for f in files) / 1e9
        print(f"  model {MODEL_PREFIX}{wid} · set {meta.get('model_set')} · files: {', '.join(files)} ({gb:.1f} GB)")
        flags = [f"{v['flag']}" + (" (needs --image)" if v.get("needs") else "") for v in meta.get("images", {}).values()]
        if meta.get("refs"):
            flags.append(f"--ref IMG x{meta['refs']['min']}..{meta['refs']['max']} (<Picture n>) · --ref-size match|max")
        if meta.get("guides"):
            flags.append(f"--guide SECONDS=IMG (up to {meta['guides']['max']})")
        flags += ["--prompt | --prompt-file (" + ", ".join(PROMPT_FIELDS[meta['prompt_format']]) + ")",
                  f"--seconds (default {meta['defaults']['seconds']})",
                  f"--res {'|'.join(meta['res'])} (default {meta['defaults']['res']})",
                  f"--steps (default {meta['defaults']['steps']}; --turbo {meta['turbo']['steps']})", "--seed"]
        print("  inputs: " + " · ".join(flags))
        fr = meta["frames"]
        print(f"  constraints: {meta['fps']} fps · frames {fr['grid'][0]}k+{fr['grid'][1]} (snapped up), "
              f"{fr['min']}..{fr['max']} (trained {fr['trained'][0]}..{fr['trained'][1]}) · "
              + ", ".join(f"{k} {v[0]}x{v[1]}" for k, v in meta["res"].items())
              + " · frames center-cropped to the canvas aspect + Lanczos to its exact size"
              + (" · no negative prompt" if meta.get("negative") is False else ""))
        print(f"  graph: {len(graph)} nodes · verified against a live /object_info: "
              f"{'yes' if meta.get('verified') else 'no (unverified)'}")
    return 0


def interrupt(a):
    ids = []
    if a.prompt_id:
        ids = [a.prompt_id]
    else:
        a.ledger = a.ledger or os.environ.get("FILM_LEDGER")
        if not a.ledger:
            refuse("interrupt needs --prompt-id ID or --ledger L.csv (it never interrupts other people's jobs)")
        if not os.path.isfile(a.ledger):
            refuse(f"no such ledger: {a.ledger}")
        for _, r in ark.request_rows(ark.ledger_rows(a.ledger)):
            if r.get("status") == "pending" and str(r.get("model", "")).startswith(MODEL_PREFIX) and r.get("task_id"):
                ids.append(r["task_id"])
        if not ids:
            print(f"no open comfy job in {a.ledger}")
            return 0
    try:
        q = call("GET", "/queue")
    except ComfyError as e:
        print(f"ComfyUI is not reachable at {base_url()} ({e})", file=sys.stderr)
        return FAILED
    running = {x[1] for x in q.get("queue_running") or [] if len(x) > 1}
    pending = {x[1] for x in q.get("queue_pending") or [] if len(x) > 1}
    for pid in ids:
        if pid in running:
            call("POST", "/interrupt", {"prompt_id": pid})
            print(f"{pid}: running -> interrupted (the `run` process writes the ledger row)")
        elif pid in pending:
            call("POST", "/queue", {"delete": [pid]})
            print(f"{pid}: queued -> removed from the queue")
        else:
            print(f"{pid}: not queued or running (if its `run` process died, close the row with "
                  f"python3 tools/ark.py ledger-close --req <id> --status abandoned --ledger L)")
    return 0


# --- CLI ----------------------------------------------------------------------------------------------------------
def positive_float(text):
    x = float(text)
    if not x > 0:
        raise argparse.ArgumentTypeError(f"must be > 0, not {text}")
    return x


p = argparse.ArgumentParser(description="ComfyUI local video engine (AI Film Lab)",
                            epilog="tools/comfy/README.md has the details.")
sp = p.add_subparsers(dest="cmd", required=True)
sp.add_parser("ping", help="ComfyUI version, python, torch, GPU, VRAM, offline flag")
s = sp.add_parser("start", help="run the installed ComfyUI headless on FILM_COMFY_URL (paid API nodes blocked)")
s.add_argument("--wait", type=int, default=120, help="seconds to wait for /system_stats (default 120)")
s.add_argument("--dry-run", action="store_true", help="print the command, start nothing")
i = sp.add_parser("install", help="check the install against comfy.lock.json; never downloads models")
i.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
i.add_argument("--portable", action="store_true", help="download + extract the pinned portable ComfyUI if none")
i.add_argument("--lock", default=None, help=argparse.SUPPRESS)
m = sp.add_parser("models", help="model files of the lock: present / size / (--verify) sha256")
m.add_argument("--set", default=None, help="only this model set (e.g. minimax-h3)")
m.add_argument("--verify", action="store_true", help="hash the files whose sha256 the lock pins (slow)")
m.add_argument("--lock", default=None, help=argparse.SUPPRESS)
sp.add_parser("workflows", help="the shipped workflows: inputs, constraints, model files")
r = sp.add_parser("run", help="one clip from a workflow (see the module help)")
r.add_argument("workflow")
r.add_argument("--image", default=None, help="h3-i2v: start frame (center-cropped to the canvas aspect, Lanczos to its size)")
r.add_argument("--last", default=None, help="h3-i2v: end frame (first-last-frame; needs --image)")
r.add_argument("--ref", action="append", default=None, metavar="IMG", help="h3-r2v: reference image (repeat, 1-9)")
r.add_argument("--ref-size", choices=["match", "max"], default=None, help="h3-r2v: ref image sizing (default match)")
r.add_argument("--guide", action="append", default=None, metavar="SECONDS=IMG",
               help="h3-r2v: anchor IMG at that time of the clip (repeat)")
r.add_argument("--prompt", default=None)
r.add_argument("--prompt-file", default=None, help="JSON/YAML with the workflow's prompt fields")
r.add_argument("--negative", default=None, help="refused for H3 (CFG-distilled)")
r.add_argument("--seconds", type=positive_float, default=None, help="clip length, snapped up to 17k+5 frames (default 5)")
r.add_argument("--res", default=None, help="480p (864x480 draft) | 768p (1344x768, default)")
r.add_argument("--seed", type=int, default=None, help="default: random (printed and logged)")
r.add_argument("--steps", type=int, default=None, help="default 20 (--turbo: the LoRA's steps)")
r.add_argument("--turbo", action="store_true", help="Lightning LoRA, few steps: drafts only")
r.add_argument("--out", required=True, help="<clips>/<name>_v<NN>.mp4 (must not exist)")
r.add_argument("--ledger", default=None, help="the episode's ledger.csv (env FILM_LEDGER)")
r.add_argument("--no-ledger", action="store_true", help="ad-hoc test without a ledger (main session only)")
r.add_argument("--dry-run", action="store_true", help="validate and print the filled graph summary; send nothing")
r.add_argument("--timeout", type=positive_float, default=2400, help="seconds before the job is interrupted (2400)")
r.add_argument("--keep-frames", action="store_true", help="also extract PNG frames next to the clip (ffmpeg)")
t = sp.add_parser("interrupt", help="stop our own job: --prompt-id, or every open comfy job of --ledger")
t.add_argument("--prompt-id", default=None)
t.add_argument("--ledger", default=None)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):        # a Windows pipe (cp1252) must not crash on a Vietnamese prompt
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    a = p.parse_args(argv)
    if a.cmd == "run":
        prev = {}
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                prev[sig] = signal.signal(sig, ark._on_signal)
            except ValueError:          # not the main thread (tests)
                pass
        try:
            code = run(a)
        except ark.Interrupted as e:
            print(f"{e}: stopped (see the ledger for the request's final row)", file=sys.stderr)
            raise
        finally:
            for sig, h in prev.items():
                signal.signal(sig, h)
    else:
        code = {"ping": ping, "start": start, "install": install, "models": models_cmd, "workflows": workflows_cmd,
                "interrupt": interrupt}[a.cmd](a)
    if code:
        sys.exit(code)
    return 0


if __name__ == "__main__":
    main()
