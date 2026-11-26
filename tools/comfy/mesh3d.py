"""`comfy.py run` for the image-to-3D workflows (meta kind "mesh": hunyuan3d), loaded by tools/comfy/comfy.py on use.

  python tools/comfy/comfy.py run hunyuan3d --image <concept, white background>.png --out <asset>_raw_v<NN>.glb
                     [--steps 30] [--octree 256|512] [--cfg 5] [--seed N] [--allow-bg]
                     (--ledger L.csv | --no-ledger) [--dry-run] [--review BUILD] [--keep-models] [--timeout S]

Hunyuan3D 2.1 (ComfyUI core nodes, checkpoint hunyuan_3d_v2.1.safetensors) turns ONE concept image into an untextured
mesh: a sculpt blank ("phoi") to remesh, retopologise and detail in Blender (tools/blender/blender.py mesh-prep).
The input must be the whole creature on a plain white background (make it with Qwen-Image-Edit): the border of the
image must be white (--allow-bg skips that check, e.g. for a deliberately cropped test). Before upload the subject is
cropped to its bounding box and padded to a white 1024x1024 square in which it fills 85 % of the side (CLIPVisionEncode
centre-crops: a wide image would lose head and tail), in a temp file (the source is never touched).
--octree 256 (default: 30 steps ~40 s on the owner's RTX 5070 Ti) or 512 (more detail: use --steps 50, ~3 min).
Output: <out>.glb (written atomically, never replaced) + <out>.glb.json sidecar (seed, steps, octree, input and its
background check, mesh vertex/triangle counts, graph, GPU seconds, model licence). Ledger: kind image, model
comfy:hunyuan3d, size 1024x1024, count 1, note req=..; seed=..; steps=..; octree=.. (cost 0 like every comfy row).
GPU lock, POST /free before the lock is released, exit codes, refusals: as every `comfy.py run` (comfy.py's help).
Weights licence: Tencent Hunyuan 3D 2.1 Community License (not valid in the EU, the UK, South Korea).

The square-input step is adapted from the owner's trial script (projects/.../film3d-blender/hunyuan3d/run_h3d.py,
the lab's own code); this module takes comfy.py's helpers as `c` (comfy.py passes itself), so the GPU lock, the
ledger writer and the fakes of the tests are the same objects.
"""
import json, os, secrets, shutil, struct, sys, tempfile, time, uuid

# --- input image ------------------------------------------------------------------------------------------------------
def _rgb(path):
    """The image as RGB with any transparency flattened onto white (a cut-out PNG counts as a white background)."""
    from PIL import Image, ImageOps
    with Image.open(path) as im0:
        im = ImageOps.exif_transpose(im0)
        if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
            im = im.convert("RGBA")
            flat = Image.new("RGB", im.size, (255, 255, 255))
            flat.paste(im, mask=im.getchannel("A"))
            return flat
        return im.convert("RGB")


def foreground(im, white):
    """Boolean mask (numpy) of the pixels that are not near-white (any channel below `white`)."""
    import numpy as np
    return (np.asarray(im, dtype=np.uint8) < white).any(axis=2)


def bg_check(path, white=235, border=0.02, need=0.98):
    """Is the background plain white and the subject whole? Looks only at a frame `border` (share of the short side,
    at least 2 px) around the edge: `need` of those pixels must be near-white. -> dict (ok, white_share, ...)."""
    import numpy as np
    im = _rgb(path)
    fg = foreground(im, white)
    h, w = fg.shape
    b = max(2, int(round(min(w, h) * border)))
    frame = np.concatenate([fg[:b].ravel(), fg[-b:].ravel(), fg[b:-b, :b].ravel(), fg[b:-b, -b:].ravel()])
    share = 1.0 - float(frame.mean()) if frame.size else 0.0
    return {"ok": bool(share >= need and fg.any()), "white_share": round(share, 4), "border_px": b,
            "foreground": round(float(fg.mean()), 4), "size": [w, h], "empty": not bool(fg.any())}


def square_input(src, dst, size=1024, fill=0.85, white=235, min_px=8):
    """Crop to the non-white subject and pad it to a white square in which it fills `fill` of the side; save PNG.
    Rows/columns with fewer than `min_px` foreground pixels are ignored for the box (specks at the borders).
    -> dict (bbox in source pixels, touches_edge)."""
    import numpy as np
    from PIL import Image
    im = _rgb(src)
    a = np.asarray(im)
    fg = foreground(im, white)
    xs = np.nonzero(fg.sum(0) >= min_px)[0]
    ys = np.nonzero(fg.sum(1) >= min_px)[0]
    if not len(xs) or not len(ys):
        xs, ys = np.nonzero(fg.any(0))[0], np.nonzero(fg.any(1))[0]
    if not len(xs) or not len(ys):
        raise ValueError("no subject found (the whole image is white)")
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    clean = a.copy()
    clean[(a > 240).all(axis=2)] = 255                      # the off-white background becomes pure white
    crop = Image.fromarray(clean).crop((x0, y0, x1, y1))
    side = max(1, int(max(crop.size) / fill))
    sq = Image.new("RGB", (side, side), (255, 255, 255))
    sq.paste(crop, ((side - crop.size[0]) // 2, (side - crop.size[1]) // 2))
    sq.resize((size, size), Image.LANCZOS).save(dst, "PNG")
    return {"bbox": [x0, y0, x1, y1], "touches_edge": x0 == 0 or y0 == 0 or x1 == fg.shape[1] or y1 == fg.shape[0]}


def glb_counts(path):
    """{'verts', 'tris'} of a .glb from its JSON chunk (accessor counts), or None when unreadable."""
    try:
        with open(path, "rb") as f:
            magic, _, _, clen, ctype = struct.unpack("<4sIII4s", f.read(20))
            if magic != b"glTF" or ctype != b"JSON":
                return None
            gltf = json.loads(f.read(clen).decode("utf-8"))
    except (OSError, ValueError, struct.error):
        return None
    acc, verts, tris = gltf.get("accessors") or [], 0, 0
    for mesh in gltf.get("meshes") or []:
        for prim in mesh.get("primitives") or []:
            pos, idx = (prim.get("attributes") or {}).get("POSITION"), prim.get("indices")
            n = acc[pos].get("count", 0) if isinstance(pos, int) and pos < len(acc) else 0
            verts += n
            if prim.get("mode", 4) == 4:
                tris += (acc[idx].get("count", 0) if isinstance(idx, int) and idx < len(acc) else n) // 3
    return {"verts": verts, "tris": tris}


# --- plan -------------------------------------------------------------------------------------------------------------
def plan(c, a, meta, wid):
    """Every local refusal of `run` for a mesh workflow; returns the plan dict (nothing is sent)."""
    other = [flag for flag, v in (("--last", a.last), ("--ref", a.ref), ("--guide", a.guide), ("--ref-size", a.ref_size),
                                  ("--seconds", a.seconds), ("--res", a.res), ("--keep-frames", a.keep_frames),
                                  ("--prompt", a.prompt), ("--prompt-file", a.prompt_file),
                                  ("--negative", a.negative), ("--size", a.size), ("--turbo", a.turbo),
                                  ("--lightning", getattr(a, "lightning", None)),
                                  ("--denoise", getattr(a, "denoise", None)),
                                  ("--ref-mode", getattr(a, "ref_mode", None))) if v is not None and v is not False]
    if other:
        c.refuse(f"{wid} makes a mesh from one image: {', '.join(other)} belong to the other workflows "
                 "(its inputs: --image, --steps, --octree, --cfg, --seed, --allow-bg)")
    if not a.image:
        c.refuse(f"{wid} needs --image: the approved concept, whole subject on a plain white background "
                 "(make it with Qwen-Image-Edit)")
    if not (os.path.isfile(a.image) and os.access(a.image, os.R_OK)):
        c.refuse(f"no such file: {a.image}")
    if c.image_size(a.image) is None:
        c.refuse(f"not a PNG/JPEG/WEBP image (or unreadable): {a.image}")
    ext = meta["output"].get("ext", ".glb")
    if not a.out.lower().endswith(ext):
        c.refuse(f"--out {a.out}: {wid} saves {ext[1:].upper()}: name it <asset>_raw_v<NN>{ext}")
    c.ark.guard_output(a.out)
    if os.path.exists(a.out + ".json"):
        c.refuse(f"sidecar exists: {a.out}.json (versions only go up)")
    d = meta["defaults"]
    octree = int(a.octree) if a.octree is not None else int(d["octree"])
    if str(octree) not in meta["octree"]:
        c.refuse(f"--octree {octree}: {wid} knows {' | '.join(meta['octree'])}")
    steps = a.steps if a.steps is not None else d["steps"]
    if not 1 <= steps <= 200:
        c.refuse("--steps must be 1..200")
    cfg = a.cfg if a.cfg is not None else d["cfg"]
    if not 0 < cfg <= 30:
        c.refuse("--cfg must be > 0 and <= 30")
    seed = a.seed if a.seed is not None else secrets.randbelow(2**32)
    if not 0 <= seed <= 0xFFFFFFFFFFFFFFFF:
        c.refuse("--seed must be 0..2^64-1")
    inp = meta["input"]
    try:
        bg = bg_check(a.image, inp["white"], inp["border"], inp["border_white"])
    except ImportError:
        c.refuse("Pillow and numpy are needed to check and square the input image (pip install Pillow numpy)")
    except Exception as e:          # an image Pillow cannot read
        c.refuse(f"cannot read {a.image} ({type(e).__name__}: {e})")
    if bg["empty"]:
        c.refuse(f"{a.image}: no subject found (the whole image is near-white)")
    if not bg["ok"] and not a.allow_bg:
        c.refuse(f"{a.image}: the background is not plain white or the subject touches the edge "
                 f"({bg['white_share']:.1%} of a {bg['border_px']} px border is white, {inp['border_white']:.0%} "
                 "needed): Hunyuan3D wants the whole subject on white (make it with Qwen-Image-Edit); "
                 "--allow-bg to send it anyway")
    if not bg["ok"]:
        c.warn(f"--allow-bg: {a.image} has a non-white border ({bg['white_share']:.1%} white): expect a worse mesh")
    e = meta.get("estimate") or {}
    est = steps * e.get("seconds_per_step", 0.62) + (e.get("decode_seconds") or {}).get(str(octree), 30)
    return {"steps": steps, "cfg": float(cfg), "seed": seed, "octree": octree,
            "num_chunks": meta["octree"][str(octree)]["num_chunks"], "bg": bg, "estimate": est}


def fill_graph(c, template, meta, wid, p, image):
    g = c.build_graph(template, meta, {"seed": p["seed"], "steps": p["steps"], "cfg": p["cfg"],
                                        "prefix": f"film-lab/{wid}"})
    for name, value in (("image", image), ("octree", p["octree"]), ("num_chunks", p["num_chunks"])):
        c.set_param(g, meta, name, value)
    bad = c.disallowed(g) or c.dangling(g)
    if bad:
        c.refuse(f"{wid}: filled graph is not runnable: {', '.join(bad)}")
    return g


def describe(c, graph, meta, lock):
    """The `comfy.py workflows` lines of a mesh workflow."""
    d, e = meta["defaults"], meta.get("estimate") or {}
    print(f"  inputs: --image (concept, whole subject on white; --allow-bg skips the check) · --octree "
          f"{'|'.join(meta['octree'])} (default {d['octree']}) · --steps (default {d['steps']}) · --cfg (default "
          f"{d['cfg']:g}) · --seed")
    print(f"  constraints: one {meta['output'].get('ext', '.glb')} (untextured, not watertight: "
          f"tools/blender/blender.py mesh-prep) · input squared to {meta['input']['size']}px, subject "
          f"{meta['input']['fill']:.0%} of the side" + (f" · {e['note']}" if e.get("note") else ""))
    print(f"  licence: {meta.get('licence', '?')}")
    print(f"  graph: {len(graph)} nodes · verified against a live /object_info: "
          f"{'yes' if meta.get('verified') else 'no (unverified)'}")


def review_hook(c, a, wid):
    """A tools/review JobHook (build kind model, engine comfy-hunyuan3d) for --review BUILD / $FILM_REVIEW_BUILD, else
    None. Never raises."""
    bid = (getattr(a, "review", None) or os.environ.get("FILM_REVIEW_BUILD") or "").strip()
    if not bid or a.dry_run:
        return None
    try:
        import importlib.util
        sp = importlib.util.spec_from_file_location("film_review_client", c.REVIEW_CLIENT)
        mod = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(mod)
        tags = dict(getattr(mod, "path_tags", lambda *_: {})(a.out, a.ledger), engine="comfy-hunyuan3d")
        return mod.job_hook(bid, "comfy", "model", tags=tags, label=wid)
    except Exception as e:
        c.warn(f"review publishing off ({type(e).__name__}: {e})")
        return None


# --- run --------------------------------------------------------------------------------------------------------------
def run(c, a, wid, template, meta, wf_sha):
    """`comfy.py run <mesh workflow>`: one GLB, a ledger row kind image (cost 0), progress per sampler step."""
    p = plan(c, a, meta, wid)
    c.ledger_args(a)
    lock = c.load_lock()
    graph = fill_graph(c, template, meta, wid, p, "<concept>")
    models = c.model_entries(graph, lock)
    model = meta.get("ledger_model") or c.MODEL_PREFIX + wid
    size = meta["input"]["size"]
    est = p["estimate"]
    print(f"workflow {wid} ({model}) · {len(graph)} nodes · octree {p['octree']} (num_chunks {p['num_chunks']}) · "
          f"steps {p['steps']} · cfg {p['cfg']:g} · seed {p['seed']}")
    bg = p["bg"]
    sw, sh = bg["size"]
    print(f"input {a.image}: {sw}x{sh}, border {bg['white_share']:.1%} white"
          f"{'' if bg['ok'] else ' (--allow-bg)'} -> subject cropped, padded to a white {size}x{size} square "
          f"({meta['input']['fill']:.0%} of the side)")
    print("models: " + ", ".join(f for *_, f in models))
    print(f"estimate ~{est:.0f} s of GPU (estimate; a session's first run also loads the 7.4 GB checkpoint)")
    print(f"licence: {meta.get('licence', '?')}")
    if a.dry_run:
        mdir = c.models_dir(c.layout(c.comfy_home()))
        if mdir and os.path.isdir(mdir):
            for _, _, _, entry, f in models:
                if not c.find_model(mdir, entry["folder"] if entry else "checkpoints", f):
                    c.warn(f"model file not found under {mdir}: {f}")
        print("dry-run: nothing uploaded or queued, no ledger row")
        return 0
    stats = c.system_stats()
    if stats is None:
        c.refuse(f"ComfyUI is not reachable at {c.base_url()}: start it with `python tools/comfy/comfy.py start` "
                 "(nothing sent)")
    if not c.offline_flag(stats):
        c.warn("this ComfyUI was not started with --offline: paid partner nodes are loaded (run never queues them: "
               "allow list)")
    try:
        problems = c.server_problems(graph, models)
    except c.ComfyError as e:
        c.refuse(f"/object_info failed ({e}); nothing sent")
    if problems:
        c.refuse("the server cannot run this graph, nothing sent:\n  " + "\n  ".join(problems))
    c.hold_gpu(wid)
    c.recheck_outputs(a)
    rid = c.ark.new_req()
    tmpdir = tempfile.mkdtemp(prefix="film-comfy-")
    try:
        sq = os.path.join(tmpdir, "concept.png")
        try:
            box = square_input(a.image, sq, size, meta["input"]["fill"], meta["input"]["white"])
        except Exception as e:
            c.refuse(f"cannot square {a.image} ({type(e).__name__}: {e}); nothing sent")
        try:
            uploaded = c.upload(sq, f"film-lab_{rid[:12]}_concept.png")
        except c.ComfyError as e:
            c.refuse(f"upload failed ({e}); nothing queued, no ledger row")
        inp = {"path": a.image, "sha256": c.sha256_file(a.image), "size": [sw, sh], "background": bg,
               "bbox": box["bbox"], "touches_edge": box["touches_edge"], "uploaded": uploaded,
               "uploaded_sha256": c.sha256_file(sq), "uploaded_size": [size, size]}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    graph = fill_graph(c, template, meta, wid, p, uploaded)
    gsha = c.graph_sha(graph)
    pid = str(uuid.uuid4())
    client_id = "film-lab-" + rid[:12]
    req = {"kind": "image", "model": model, "size": f"{size}x{size}", "count": 1, "out": a.out, "task_id": pid}
    tag = f"seed={p['seed']}; steps={p['steps']}; octree={p['octree']}"
    c.ark.make_out_dir(a.out)
    hook = None
    steps = c.StepListener(client_id, meta.get("progress_node"))
    steps.prompt_id = pid
    c.ark.reserve(a, req, rid, tag=tag)
    t0 = time.monotonic()
    state = {"logged": False}
    if not a.keep_models:
        c.GPU_HOLD.callback(c.free_models)      # before the lock is released (ExitStack: last in, first out)

    def final(status, note="", usage="", cat=None):
        """The ledger row in full; the public review page gets a fixed category only."""
        if not state["logged"]:
            c.ark.log_row(a, req, rid, status, "; ".join(x for x in (tag, note) if x), usage=usage)
            state["logged"] = True
            if hook and status != "ok":
                hook.failed(f"{status}: {cat}" if cat else status)

    def publish_steps(el):
        for v, m in steps.drain():
            print(f"step {v}/{m} elapsed {int(el)}s", flush=True)
            if hook and m:
                hook.update(min(0.9, 0.9 * v / m), f"step {v}/{m} · {int(el)} s", force=True, step=v, steps=m)

    try:                                    # everything after the pending row: an interrupt writes the final row
        hook = review_hook(c, a, wid)
        if hook:
            hook.key = f"comfy-{pid}"
            hook.start(f"{wid} · octree {p['octree']} · {p['steps']} steps · ~{est:.0f} s GPU (estimate)")
        if steps.connect():
            steps.start()
        try:
            c.call("POST", "/prompt", {"prompt": graph, "client_id": client_id, "prompt_id": pid})
        except c.ComfyError as e:
            detail = " ".join((e.body or str(e)).split())[:300]
            final("failed", "prompt refused by ComfyUI: " + detail, cat="prompt refused")
            print(f"ComfyUI refused the prompt: {detail}", file=sys.stderr)
            return c.FAILED
        print(f"queued prompt {pid} (req {rid[:12]})" + ("" if steps.ok else " · no websocket: progress by time"),
              flush=True)
        entry, last_state, last_print, errors = None, None, 0.0, 0
        while True:
            el = time.monotonic() - t0
            try:
                hist = c.call("GET", f"/history/{pid}")
                errors = 0
            except c.ComfyError as e:
                errors += 1
                if errors > c.POLL_ERRORS:
                    gone = c.wait_gone(pid)
                    final("failed", f"polling stopped: {e}; {gone}", f"gpu_s={round(el, 1)}", cat="server lost")
                    print(f"lost the server while polling ({e}); {gone}", file=sys.stderr)
                    return c.FAILED
                hist = {}
            entry = hist.get(pid)
            st = (entry or {}).get("status") or {}
            if entry and (st.get("completed") or st.get("status_str") in ("success", "error")):
                break
            if el > a.timeout:
                note = c.stop_prompt(pid)
                final("interrupted", f"timeout after {a.timeout:g}s ({note})", f"gpu_s={round(el, 1)}", cat="timeout")
                print(f"timeout after {a.timeout:g}s: prompt {pid} stopped ({note})", file=sys.stderr)
                return c.FAILED
            publish_steps(el)
            if not steps.ok or steps.last is None:
                s = c.queue_state(pid)
                if hook and not steps.last:
                    hook.update(min(0.9, el / est) if est else 0.0, f"{s} · {int(el)} s / ~{int(est)} s")
                if s != last_state or el - last_print >= c.PROGRESS_SECONDS:
                    print(f"step {s} elapsed {int(el)}s", flush=True)
                    last_state, last_print = s, el
            time.sleep(c.POLL_SECONDS)
        wall = time.monotonic() - t0
        steps.wait_last()
        publish_steps(wall)
        gpu = c.gpu_seconds(entry, wall)
        usage = f"gpu_s={gpu:g}"
        msgs = c.exec_messages(entry)
        if st.get("status_str") != "success" or "execution_error" in msgs or "execution_interrupted" in msgs:
            if "execution_interrupted" in msgs:
                final("interrupted", "interrupted on the server", usage, cat="interrupted on the server")
                print(f"prompt {pid} was interrupted", file=sys.stderr)
                return c.FAILED
            err = msgs.get("execution_error") or {}
            why = f"{err.get('node_type', '?')} (node {err.get('node_id', '?')}): {err.get('exception_message', st)}"
            final("failed", "execution error: " + " ".join(str(why).split())[:300], usage, cat="execution error")
            print(f"ComfyUI execution error: {why}", file=sys.stderr)
            return c.FAILED
        ext = meta["output"].get("ext", ".glb")
        item = c.find_output(entry, meta["output"]["node"], ext)
        if not item:
            final("failed", f"no {ext} in the prompt's history outputs", usage, cat="no output")
            print(f"the prompt finished but its history lists no {ext} output", file=sys.stderr)
            return c.FAILED
        try:
            c.download_view(item, a.out)
        except (c.ComfyError, OSError) as e:
            final("failed", f"download failed: {e}; the mesh is in ComfyUI's output folder: "
                            f"{item.get('subfolder', '')}/{item['filename']}", usage, cat="download failed")
            print(f"DOWNLOAD FAILED ({e}); the mesh is in ComfyUI's output folder as "
                  f"{item.get('subfolder', '')}/{item['filename']}", file=sys.stderr)
            return c.FAILED
        counts = glb_counts(a.out)
        if counts is None:
            c.warn(f"{a.out} is not a readable GLB (kept as downloaded)")
        sys_ = stats.get("system", {})
        sidecar = {
            "tool": "tools/comfy/comfy.py", "workflow": wid, "model": model, "workflow_file_sha256": wf_sha,
            "graph_sha256": gsha, "prompt_id": pid, "req": rid, "seed": p["seed"], "steps": p["steps"], "cfg": p["cfg"],
            "octree": p["octree"], "num_chunks": p["num_chunks"], "input": inp, "mesh": counts,
            "bytes": os.path.getsize(a.out), "licence": meta.get("licence"),
            "models": [{"file": f, "folder": e["folder"] if e else None, "size": e.get("size") if e else None,
                        "sha256": e.get("sha256") if e else None} for _, _, _, e, f in models],
            "comfyui": {"version": sys_.get("comfyui_version"), "pytorch": sys_.get("pytorch_version"),
                        "python": (sys_.get("python_version") or "").split(" ")[0],
                        "device": ((stats.get("devices") or [{}])[0]).get("name"), "offline": c.offline_flag(stats),
                        "url": c.base_url()},
            "gpu_seconds": gpu, "wall_seconds": round(wall, 1), "output": item, "created": c.ark.utc_now(),
            "next": f"python tools/blender/blender.py mesh-prep {a.out} --out <dir> --concept {a.image}",
            "graph": graph,
        }
        c.write_json_atomic(a.out + ".json", sidecar)
        final("ok", "", usage)
        if hook:
            hook.rv.step(os.path.splitext(os.path.basename(a.out))[0], glb=a.out, stats=counts or {})
            hook.finish([], gpu_s=gpu, message=f"{gpu:g} GPU s")
        n = f"{counts['verts']} verts, {counts['tris']} tris, " if counts else ""
        print(f"saved {a.out} ({n}{gpu:g} GPU s) + {os.path.basename(a.out)}.json")
        print(f"next: python tools/blender/blender.py mesh-prep {a.out} --out <dir> --concept {a.image}")
        return 0
    except BaseException as e:
        if not state["logged"]:
            if isinstance(e, c.ark.Interrupted):
                final("interrupted", f"{e} ({c.stop_prompt(pid)})", f"gpu_s={round(time.monotonic() - t0, 1)}",
                      cat="stopped")
            else:
                final("failed", c.ark.err_note(e), cat=f"error ({type(e).__name__})")
        raise
    finally:
        steps.close()
