#!/usr/bin/env python3
"""Hybrid shot (method blender, video_engine comfy): Blender key frames -> Qwen-Image-Edit beauty pass -> the owner's
eye check -> MiniMax H3 in-betweens -> one clip. An orchestrator: it only calls the lab's CLIs as subprocesses.

  python tools/comfy/hybrid.py run <shot3d.json> --media out/<project>/<id> --ledger L
                     (--edit-prompt TEXT | --edit-prompt-file F.txt) (--motion-prompt TEXT | --motion-prompt-file F.json)
                     [--keys 2|3] [--mid FRAME] [--size 1344x768] [--look L] [--lightning 4|8] [--denoise 1.0]
                     [--edit-seed N] [--ref IMG] [--res 480p|768p] [--motion-seed N] [--turbo] [--approved k1,k2]
                     [--expect TEXT] [--root DIR] [--review BUILD] [--dry-run]
  python tools/comfy/hybrid.py keyframes|edit|animate|assemble <shot3d.json> --media ... [the same options]
  python tools/comfy/hybrid.py approve <shot3d.json> k1,k2[,k3] --media out/<project>/<id>
  python tools/comfy/hybrid.py status <shot3d.json> --media out/<project>/<id>

Steps (`run` = all of them, stopping at the eye check until the key frames are approved):
  keyframes  tools/blender/blender.py keyframes (k1 = frame 1, k<N> = the last frame) + blender.py still for a middle
             key (--keys 3: the middle frame, or --mid FRAME) -> <root>/render/; one ledger row blender:keyframes
             (cost 0) when --ledger is given
  edit       tools/comfy/comfy.py run qwen-edit on every key frame (Lightning 8, denoise 1.0, one seed for all keys)
             -> <root>/edit/<key>_e<NN>.png, a contact sheet <root>/check_v<NN>.png (render | edit per key), then
             STOP: the checklist for the owner's eye check is printed
  approve    writes <root>/hybrid_approved.json (the approved keys and the sha256 of their edits); a key left out is
             skipped (H3 bridges the keys on both sides of it); an edit redone after approval needs approving again
  animate    comfy.py run h3-i2v --image <key a> --last <key b> between consecutive approved keys, length = the
             frames between them / fps (H3 snaps up to its 17k+5 grid) -> <root>/segments/<a>-<b>_v<NN>.mp4
  assemble   ffmpeg concat (stream copy; re-encoded only when copy fails) -> <media>/clips/<id>_<shot>_h3_v<NN>.mp4 +
             <clip>.mp4.json (keys, segments, their sidecars); consecutive segments share the key frame between them
             (one frame repeated: retime in compositing)
--approved k1,k3 on run/animate/assemble = approve first. <root> defaults to <media>/renders3d/<shot>_keys/
(a new round of key frames: --root .../<shot>_keys_v02). State: <root>/hybrid.json.

Every step is resumable: an output that exists is never made again or overwritten (versions go up: _e<NN>, _v<NN>);
a key that has an edit keeps it: `edit --redo k2` makes a new edit of k2 (with --edit-seed N for another result),
`--redo all` edits every key again (new prompt or settings). Every comfy.py call of a step but the
last gets --keep-models; the last frees the VRAM. --ledger and --review pass through to comfy.py (one ledger row per
image or clip, cost 0) and --review to blender.py keyframes. A called tool that exits non-zero stops the chain (never
retried); hybrid.py exits with its code. --dry-run prints the plan and calls nothing.

Limits: Qwen-Edit is not frame-consistent (edit 2-3 key frames per shot, never every frame); fix a wrong volume (beak,
eye, horn count) in Blender first, the edit only upgrades the surface; the edited keys must be checked by eye before
H3 (counted parts, no peacock eye-spots, framing not shifted). Local session on the owner's PC only (GPU).
Exit codes: 0 ok (also: stopped at the eye check) · 2 refused here, nothing called · else the failed tool's code.
"""
import argparse, datetime, hashlib, importlib.util, json, os, re, shutil, subprocess, sys, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
COMFY = os.path.join(HERE, "comfy.py")
BLENDER = os.path.join(TOOLS, "blender", "blender.py")
sys.path.insert(0, TOOLS)
import ark          # noqa: E402  (tools/ark.py: the ledger writer for the blender:keyframes row)
import episode_id   # noqa: E402  (tools/episode_id.py: episode and shot ids)

REFUSED = 2
STATE = "hybrid.json"
APPROVED = "hybrid_approved.json"
KEY_SIZE = "1344x768"           # MiniMax H3's training canvas (blender.py keyframes default)
DEFAULT_EDIT_SEED = 1717


def _load(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(sp)
    sys.modules.setdefault(name, mod)
    sp.loader.exec_module(mod)
    return mod


spec = _load("film_blender_spec", os.path.join(TOOLS, "blender", "spec.py"))


class Refused(Exception):
    """Exit 2: nothing was called."""


def say(msg=""):
    print(msg, flush=True)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_cmd(argv):
    """Run one tool (output straight to the terminal) -> exit code. Tests replace this function."""
    return subprocess.run(argv).returncode


def show(argv):
    out = []
    for a in argv[1:] if argv and argv[0] == sys.executable else argv:
        if out and out[-1] in ("--prompt", "--negative"):      # long text: shortened; paths stay whole
            a = " ".join(a.split())
            a = a if len(a) <= 90 else a[:87] + "..."
        out.append(a if re.fullmatch(r"[\w./\\:=,+-]+", a) else '"' + a.replace('"', '\\"') + '"')
    return "python " + " ".join(out) if argv and argv[0] == sys.executable else " ".join(out)


def write_json_atomic(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise Refused(f"{path}: unreadable {what} ({type(e).__name__}); fix or move it")


def next_version(folder, stem, exts):
    """First _v<NN> (or _e<NN>) whose files (all exts) are free."""
    n = 1
    while any(os.path.exists(os.path.join(folder, f"{stem}{n:02d}{e}")) for e in exts):
        n += 1
    return os.path.join(folder, f"{stem}{n:02d}{exts[0]}")


def place_new(src, dst):
    """Move src to dst, never replacing a file at dst (Refused)."""
    try:
        os.link(src, dst)
    except FileExistsError:
        raise Refused(f"{dst} appeared meanwhile: not replaced") from None
    except OSError:
        if os.path.exists(dst):
            raise Refused(f"{dst} appeared meanwhile: not replaced")
        os.rename(src, dst)
        return
    os.remove(src)


# ------------------------------------------------------------------------------------------------ context
class Ctx:
    def __init__(self, a):
        self.a = a
        self.dry = bool(getattr(a, "dry_run", False))
        if not os.path.isfile(a.spec):
            raise Refused(f"{a.spec}: no such file")
        data, errors = spec.load(a.spec)
        if errors:
            raise Refused(f"{a.spec}: {len(errors)} error(s) (tools/blender/blender.py check)\n  " + "\n  ".join(errors))
        self.shot_spec = spec.normalize(data)
        _, _, self.fps, self.frames = spec.timeline(self.shot_spec, False)
        self.spec_sha = sha256_file(a.spec)
        stem = os.path.splitext(os.path.basename(a.spec))[0]
        self.shot = a.shot or stem
        if not episode_id.RE_SHOT.match(self.shot):
            raise Refused(f"shot id {self.shot!r}: name the spec shots3d/s<NN>.json or give --shot s<NN>")
        self.media = os.path.abspath(a.media)
        self.eid = os.path.basename(os.path.normpath(self.media))
        if not episode_id.RE_ID.match(self.eid):
            raise Refused(f"--media {a.media}: the episode's media folder out/<project>/<id> (ep01, q01t03)")
        self.root = os.path.abspath(a.root or os.path.join(self.media, "renders3d", f"{self.shot}_keys"))
        self.ledger = getattr(a, "ledger", None) or os.environ.get("FILM_LEDGER")
        self.state_path = os.path.join(self.root, STATE)
        self.state = read_json(self.state_path, "state") or {}
        if self.state and self.state.get("spec_sha256") != self.spec_sha:
            raise Refused(f"{a.spec} changed since the key frames of {self.root} were made: render a new round "
                          f"with --root {self.root}_v02 (or the next free _v<NN>)")
        self.state.setdefault("version", 1)
        self.state.setdefault("tool", "tools/comfy/hybrid.py")
        self.state.update({"spec": os.path.abspath(a.spec), "spec_sha256": self.spec_sha, "shot": self.shot,
                           "id": self.eid, "fps": self.fps, "frames": self.frames})
        self.keys = self.choose_keys()

    def p(self, rel):
        return os.path.normpath(os.path.join(self.root, rel))

    def save(self):
        if not self.dry:
            write_json_atomic(self.state_path, self.state)

    def need_ledger(self):
        if not self.ledger:
            raise Refused("--ledger out/<project>/<id>/ledger.csv (env FILM_LEDGER): comfy.py writes one row per "
                          "image/clip, cost 0")

    def choose_keys(self):
        a, n = self.a, self.frames
        if self.state.get("keys"):
            keys = self.state["keys"]
            want = getattr(a, "keys", None)
            mids = getattr(a, "mid", None)
            if (want and want != len(keys)) or (mids and sorted(mids) != [k["frame"] for k in keys[1:-1]]):
                raise Refused(f"the key frames of {self.root} are " + ", ".join(f"{k['name']} f{k['frame']}"
                                                                                 for k in keys)
                              + f": another choice needs a new --root ({self.root}_v02)")
            return keys
        mids = sorted(set(getattr(a, "mid", None) or []))
        count = getattr(a, "keys", None) or (2 + len(mids) if mids else 2)
        if not 2 <= count <= 3:
            raise Refused("--keys 2 or 3 (first, [middle,] last): Qwen-Edit is not frame-consistent, edit few frames")
        if n < 2:
            raise Refused(f"{self.a.spec}: {n} frame(s): no in-between to make")
        if count == 3 and not mids:
            mids = [(1 + n) // 2]
        if len(mids) != count - 2:
            raise Refused(f"--keys {count} takes {count - 2} --mid frame(s), got {len(mids)}")
        for f in mids:
            if not 1 < f < n:
                raise Refused(f"--mid {f}: a middle key is a frame in 2..{n - 1}")
        frames = [1] + mids + [n]
        keys = []
        for i, f in enumerate(frames):
            render = "render/first.png" if i == 0 else "render/last.png" if i == len(frames) - 1 \
                else f"render/f{f:04d}.png"
            keys.append({"name": f"k{i + 1}", "frame": f, "render": render})
        self.state["keys"] = keys
        return keys

    def key(self, name):
        k = next((k for k in self.keys if k["name"] == name), None)
        if not k:
            raise Refused(f"no key {name!r} (keys: {', '.join(k['name'] for k in self.keys)})")
        return k

    def current_edit(self, name):
        """The latest edit record of a key whose file exists, or None."""
        recs = [r for r in self.state.get("edits", {}).get(name, []) if os.path.isfile(self.p(r["file"]))]
        return recs[-1] if recs else None


def run_jobs(jobs, dry):
    """[(label, argv, on_ok)] -> exit code; --keep-models on every comfy call but the last; stops at a failure."""
    comfy_idx = [i for i, (_, argv, _) in enumerate(jobs) if argv[1:2] == [COMFY]]
    for i, (label, argv, on_ok) in enumerate(jobs):
        if i in comfy_idx and i != comfy_idx[-1]:
            argv = argv + ["--keep-models"]
        say(f"  [{i + 1}/{len(jobs)}] {label}\n      {show(argv)}")
        if dry:
            continue
        code = run_cmd(argv)
        if code:
            print(f"hybrid: stopped: {label} exited {code} (not retried"
                  + ("; exit 1 = see its ledger row" if argv[1:2] == [COMFY] else "") + ")", file=sys.stderr)
            return code
        if on_ok:
            on_ok()
    return 0


# ------------------------------------------------------------------------------------------------ keyframes
def step_keyframes(c):
    a = c.a
    size = a.size or c.state.get("size") or KEY_SIZE
    if c.state.get("size") and size != c.state["size"]:
        raise Refused(f"the key frames of {c.root} are {c.state['size']}: another --size needs a new --root")
    c.state["size"] = size
    render_dir = c.p("render")
    jobs = []
    have = all(os.path.isfile(c.p(k["render"])) for k in (c.keys[0], c.keys[-1]))
    if not have:
        if os.path.isdir(render_dir) and os.listdir(render_dir):
            raise Refused(f"{render_dir} is not empty but has no first.png/last.png (a failed render?): move it "
                          f"away or use a new --root")
        argv = [sys.executable, BLENDER, "keyframes", os.path.abspath(a.spec), "--out", render_dir, "--size", size]
        if a.look:
            argv += ["--look", a.look]
        if a.review:
            argv += ["--review", a.review]
        jobs.append(("blender keyframes (k1, last)", argv, None))
    for k in c.keys[1:-1]:
        if not os.path.isfile(c.p(k["render"])):
            argv = [sys.executable, BLENDER, "still", os.path.abspath(a.spec), "--frame", str(k["frame"]),
                    "--out", c.p(k["render"]), "--size", size]
            if a.look:
                argv += ["--look", a.look]
            jobs.append((f"blender still {k['name']} frame {k['frame']}", argv, None))
    say(f"keyframes: {c.shot} {c.frames} frames at {c.fps} fps · keys "
        + ", ".join(f"{k['name']} f{k['frame']}" for k in c.keys) + f" · {size} -> {render_dir}")
    if not jobs:
        say("  done (renders exist)")
        for k in c.keys:
            k.setdefault("render_sha256", sha256_file(c.p(k["render"])))
        c.save()
        return 0
    rid = ark.new_req()
    code = run_jobs(jobs, c.dry)
    if c.dry:
        return 0
    if c.ledger and code in (0, 1):
        ark.ledger_append(c.ledger, {"kind": "image", "model": "blender:keyframes", "size": size,
                                     "count": len(c.keys), "status": "ok" if code == 0 else "failed",
                                     "out": render_dir, "usage": "",
                                     "note": f"req={rid}; hybrid {c.eid} {c.shot} keys "
                                             + ",".join(str(k["frame"]) for k in c.keys)})
    if code:
        return code
    missing = [k["render"] for k in c.keys if not os.path.isfile(c.p(k["render"]))]
    if missing:
        print(f"hybrid: blender.py exited 0 but {', '.join(missing)} is missing", file=sys.stderr)
        return 1
    for k in c.keys:
        k["render_sha256"] = sha256_file(c.p(k["render"]))
    c.save()
    return 0


# ------------------------------------------------------------------------------------------------ edit
def read_prompt(text, path, what):
    if text is not None and path is not None:
        raise Refused(f"give one of --{what} or --{what}-file")
    if path is not None:
        try:
            with open(path, encoding="utf-8-sig") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as e:
            raise Refused(f"--{what}-file {path}: cannot read it ({type(e).__name__})")
    return text.strip() if text is not None else None


def edit_params(c):
    a = c.a
    prompt = read_prompt(a.edit_prompt, a.edit_prompt_file, "edit-prompt")
    if prompt is None:
        prompt = c.state.get("edit_prompt")
    if not prompt:
        raise Refused("the edit step needs --edit-prompt TEXT or --edit-prompt-file F.txt (English: the design to "
                      "paint onto the render, \"keep the exact pose, framing and camera\")")
    if a.denoise is not None and not 0 < a.denoise <= 1:
        raise Refused("--denoise must be > 0 and <= 1")
    for r in a.ref or []:
        if not os.path.isfile(r):
            raise Refused(f"--ref {r}: no such file")
    prev = c.state.get("edit_params") or {}
    params = {"prompt_sha256": sha256_text(prompt),
              "lightning": a.lightning or prev.get("lightning") or 8,
              "denoise": a.denoise if a.denoise is not None else prev.get("denoise", 1.0),
              "seed": a.edit_seed if a.edit_seed is not None else prev.get("seed", DEFAULT_EDIT_SEED),
              "steps": a.edit_steps if a.edit_steps is not None else prev.get("steps"),
              "cfg": a.edit_cfg if a.edit_cfg is not None else prev.get("cfg"),
              "refs": [sha256_file(r) for r in a.ref or []]}
    return prompt, params


def edit_argv(c, image, prompt, params, out):
    args = [sys.executable, COMFY, "run", "qwen-edit", "--image", image]
    for r in c.a.ref or []:
        args += ["--ref", r]
    args += ["--prompt", prompt, "--lightning", str(params["lightning"]), "--denoise", f"{params['denoise']:g}"]
    if params.get("steps") is not None:
        args += ["--steps", str(params["steps"])]
    if params.get("cfg") is not None:
        args += ["--cfg", f"{params['cfg']:g}"]
    args += ["--seed", str(params["seed"]), "--out", out, "--ledger", c.ledger]
    if c.a.review:
        args += ["--review", c.a.review]
    return args


def step_edit(c):
    c.need_ledger()
    prompt, params = edit_params(c)
    redo = set(x.strip() for x in (c.a.redo or "").split(",") if x.strip())
    if "all" in redo:
        redo = {k["name"] for k in c.keys}
    for name in redo:
        c.key(name)
    jobs = []
    for k in c.keys:
        render = c.p(k["render"])
        if not os.path.isfile(render) and not c.dry:
            raise Refused(f"{render} is missing: run the keyframes step first")
        want = dict(params, render_sha256=sha256_file(render) if os.path.isfile(render) else None)
        cur = c.current_edit(k["name"])
        if cur and k["name"] not in redo:        # an existing edit is kept: only --redo makes another one
            say(f"  {k['name']}: done ({cur['file']})" + ("" if cur.get("params") == want else
                                                          f" · made with other settings: --redo {k['name']} "
                                                          "(or --redo all) to edit it again"))
            continue
        out = next_version(c.p("edit"), f"{k['name']}_e", (".png", ".png.json"))

        def done(k=k, out=out, want=want):
            rec = {"file": os.path.relpath(out, c.root).replace(os.sep, "/"), "sha256": sha256_file(out),
                   "params": want, "date": datetime.date.today().isoformat()}
            c.state.setdefault("edits", {}).setdefault(k["name"], []).append(rec)
            c.save()

        jobs.append((f"qwen-edit {k['name']} (frame {k['frame']}) -> edit/{os.path.basename(out)}",
                     edit_argv(c, render, prompt, params, out), done))
    say(f"edit: Qwen-Image-Edit · Lightning {params['lightning']} · denoise {params['denoise']:g} · seed "
        f"{params['seed']} · {len(jobs)} key frame(s) to edit")
    if jobs and not c.dry:
        os.makedirs(c.p("edit"), exist_ok=True)
        c.state["edit_prompt"] = prompt
        if not redo or redo == {k["name"] for k in c.keys}:     # a single redo (another seed) keeps the defaults
            c.state["edit_params"] = {k: v for k, v in params.items() if k not in ("prompt_sha256", "refs")}
        c.save()
    code = run_jobs(jobs, c.dry)
    if code or c.dry:
        return code
    check_sheet(c)
    return 0


def check_sheet(c):
    """<root>/check_v<NN>.png: render | edit per key (made again only when an edit changed)."""
    rows, shas = [], []
    for k in c.keys:
        cur = c.current_edit(k["name"])
        if not cur or not os.path.isfile(c.p(k["render"])):
            return None
        rows.append([(c.p(k["render"]), f"{k['name']} · frame {k['frame']} · Blender", ""),
                     (c.p(cur["file"]), f"{k['name']} · {os.path.basename(cur['file'])} · Qwen-Edit", "")])
        shas.append(cur["sha256"])
    old = c.state.get("check_sheet") or {}
    if old.get("edits") == shas and os.path.isfile(c.p(old.get("file", ""))):
        return c.p(old["file"])
    try:
        concept = _load("film_concept", os.path.join(TOOLS, "concept.py"))
        out = next_version(c.root, "check_v", (".png",))
        concept.make_sheet(rows, out, 640, title=f"{c.eid} {c.shot} · eye check · Blender | Qwen-Edit")
    except Exception as e:          # Pillow missing, unreadable image: the check still works from the files
        print(f"hybrid: no contact sheet ({type(e).__name__}: {e})", file=sys.stderr)
        return None
    c.state["check_sheet"] = {"file": os.path.basename(out), "edits": shas}
    c.save()
    return out


def checklist(c):
    sheet = (c.state.get("check_sheet") or {}).get("file")
    lines = ["", "EYE CHECK (the owner, before any H3 clip; nothing runs until the keys are approved):"]
    if sheet:
        lines.append(f"  sheet: {c.p(sheet)}  (Blender render | Qwen-Edit, one row per key)")
    for k in c.keys:
        cur = c.current_edit(k["name"])
        lines.append(f"  {k['name']}  frame {k['frame']:>4}  {c.p(cur['file']) if cur else '(no edit yet)'}")
    lines += ["  For every edited key frame:",
              "  [ ] count horns, legs, toes/claws, eyes, wings, tail ribbons: as the approved design (CHARACTER.md)",
              "  [ ] no peacock eye-spots, no extra head, face or limb, nothing the design forbids",
              "  [ ] the creature stays where the render has it (framing not shifted or rescaled)",
              "  [ ] every key shows the same creature (colours, markings, crest) and the same light",
              "  [ ] no text, watermark or border"]
    lines += [f"  [ ] {e}" for e in c.a.expect or []]
    lines += ["  A wrong volume (beak, eye, horn count)? Fix the model in Blender and render again; do not edit harder.",
              f"  Approve:  python tools/comfy/hybrid.py approve {c.a.spec} "
              + ",".join(k["name"] for k in c.keys) + f" --media {c.a.media}"
              + (f" --root {c.a.root}" if c.a.root else ""),
              "  (leave a rejected key out, or redo it: hybrid.py edit ... --redo k2 --edit-seed <another>)"]
    say("\n".join(lines))


# ------------------------------------------------------------------------------------------------ approve
def approve(c, names):
    names = [n.strip() for n in names.split(",") if n.strip()]
    if len(set(names)) != len(names):
        raise Refused("a key is named twice")
    if len(names) < 2:
        raise Refused("approve at least 2 keys (H3 needs a first and a last frame)")
    rec = {}
    for n in names:
        c.key(n)
        cur = c.current_edit(n)
        if not cur:
            raise Refused(f"{n} has no edit yet: run the edit step first")
        rec[n] = {"file": cur["file"], "sha256": sha256_file(c.p(cur["file"]))}
    data = {"date": datetime.date.today().isoformat(), "keys": rec,
            "rejected": [k["name"] for k in c.keys if k["name"] not in rec]}
    old = read_json(c.p(APPROVED), "approval")
    if old and old.get("keys") == rec:
        say(f"approve: unchanged ({', '.join(names)})")
        return old
    listed = ", ".join(f"{n} ({rec[n]['file']})" for n in names)
    say(f"approve: {listed}" + (f" · rejected {', '.join(data['rejected'])}" if data["rejected"] else "")
        + f" -> {c.p(APPROVED)}")
    if not c.dry:
        write_json_atomic(c.p(APPROVED), data)
    return data


def approved_keys(c, required=True):
    """The approved keys in frame order, each with its edit file -> [(key, edit path, sha256)], or None (no approval
    and not required)."""
    data = approve(c, c.a.approved) if getattr(c.a, "approved", None) else read_json(c.p(APPROVED), "approval")
    if not data or not data.get("keys"):
        if required:
            raise Refused(f"no approval in {c.p(APPROVED)}: the owner checks the edited keys first "
                          "(hybrid.py approve <spec> k1,k2 --media ..., or --approved k1,k2)")
        return None
    out = []
    for k in c.keys:
        r = data["keys"].get(k["name"])
        if not r:
            continue
        path = c.p(r["file"])
        cur = c.current_edit(k["name"])
        if not os.path.isfile(path) or sha256_file(path) != r["sha256"] or not cur or cur["file"] != r["file"]:
            raise Refused(f"{k['name']} changed since it was approved ({r['file']}): check it and approve again")
        out.append((k, path, r["sha256"]))
    if len(out) < 2:
        raise Refused("fewer than 2 approved keys")
    return out


# ------------------------------------------------------------------------------------------------ animate
def motion_prompts(c, pairs):
    a = c.a
    texts, files = a.motion_prompt or [], a.motion_prompt_file or []
    if texts and files:
        raise Refused("give --motion-prompt or --motion-prompt-file, not both")
    given = [("--prompt", t) for t in texts] + [("--prompt-file", f) for f in files]
    if not given:
        given = [tuple(x) for x in c.state.get("motion_prompts") or []]
    if not given:
        raise Refused("the animate step needs --motion-prompt TEXT or --motion-prompt-file F.json (h3-i2v fields; "
                      "one for every segment, or one per segment in order)")
    if len(given) not in (1, len(pairs)):
        raise Refused(f"{len(given)} motion prompts for {len(pairs)} segment(s): give 1 or {len(pairs)}")
    for flag, v in given:
        if flag == "--prompt-file" and not os.path.isfile(v):
            raise Refused(f"--motion-prompt-file {v}: no such file")
    c.state["motion_prompts"] = [list(g) for g in given]
    return [given[0]] * len(pairs) if len(given) == 1 else given


def prompt_sha(flag, value):
    return sha256_file(value) if flag == "--prompt-file" else sha256_text(value)


def step_animate(c):
    c.need_ledger()
    keys = approved_keys(c)
    pairs = list(zip(keys, keys[1:]))
    prompts = motion_prompts(c, pairs)
    a = c.a
    jobs = []
    for ((ka, pa, sa), (kb, pb, sb)), (flag, val) in zip(pairs, prompts):
        seconds = round((kb["frame"] - ka["frame"]) / c.fps, 3)
        params = {"a": sa, "b": sb, "prompt_sha256": prompt_sha(flag, val), "seconds": seconds, "res": a.res,
                  "seed": a.motion_seed, "turbo": bool(a.turbo)}
        pair = f"{ka['name']}-{kb['name']}"
        segs = [s for s in c.state.get("segments", []) if s["pair"] == pair and s["params"] == params
                and os.path.isfile(c.p(s["file"]))]
        if segs:
            say(f"  {pair}: done ({segs[-1]['file']})")
            continue
        out = next_version(c.p("segments"), f"{pair}_v", (".mp4", ".mp4.json"))
        argv = [sys.executable, COMFY, "run", "h3-i2v", "--image", pa, "--last", pb, flag, val,
                "--seconds", f"{seconds:g}"]
        if a.res:
            argv += ["--res", a.res]
        if a.motion_seed is not None:
            argv += ["--seed", str(a.motion_seed)]
        if a.turbo:
            argv.append("--turbo")
        argv += ["--out", out, "--ledger", c.ledger]
        if a.review:
            argv += ["--review", a.review]

        def done(pair=pair, out=out, params=params):
            c.state.setdefault("segments", []).append(
                {"pair": pair, "file": os.path.relpath(out, c.root).replace(os.sep, "/"), "sha256": sha256_file(out),
                 "params": params, "date": datetime.date.today().isoformat()})
            c.save()

        jobs.append((f"h3-i2v {pair} ({seconds:g} s of the shot) -> segments/{os.path.basename(out)}", argv, done))
    say(f"animate: MiniMax H3 first/last between {len(keys)} approved keys · {len(jobs)} segment(s) to make"
        + (" · --turbo: draft" if a.turbo else ""))
    if jobs and not c.dry:
        os.makedirs(c.p("segments"), exist_ok=True)
        c.save()
    return run_jobs(jobs, c.dry)


# ------------------------------------------------------------------------------------------------ assemble
def current_segments(c, keys):
    """The newest clip of every pair of consecutive approved keys; None in a dry-run when one is missing."""
    out = []
    for (ka, _, sa), (kb, _, sb) in zip(keys, keys[1:]):
        pair = f"{ka['name']}-{kb['name']}"
        segs = [s for s in c.state.get("segments", []) if s["pair"] == pair and s["params"]["a"] == sa
                and s["params"]["b"] == sb and os.path.isfile(c.p(s["file"]))]
        if not segs:
            if c.dry:
                return None
            raise Refused(f"no clip for {pair} yet: run the animate step first")
        out.append(segs[-1])
    return out


def ffmpeg_path():
    return shutil.which("ffmpeg")


def step_assemble(c):
    keys = approved_keys(c)
    segs = current_segments(c, keys)
    if segs is None:
        say(f"assemble: after the segments exist -> {c.media}/clips/{c.eid}_{c.shot}_h3_v<NN>.mp4 (ffmpeg concat)")
        return 0
    want = [s["sha256"] for s in segs]
    for clip in c.state.get("clips", []):
        if clip["segments"] == want and os.path.isfile(os.path.join(c.media, clip["file"])):
            say(f"assemble: done ({os.path.join(c.media, clip['file'])})")
            return 0
    clips = os.path.join(c.media, "clips")
    out = next_version(clips, f"{c.eid}_{c.shot}_h3_v", (".mp4", ".mp4.json"))
    say(f"assemble: {len(segs)} segment(s) -> {out}")
    for s in segs:
        say(f"  {s['pair']}: {c.p(s['file'])}")
    ff = ffmpeg_path()
    if c.dry:
        say("  ffmpeg -f concat -c copy (re-encode only when copy fails)" + ("" if ff else " · ffmpeg NOT on PATH"))
        return 0
    if not ff:
        raise Refused("ffmpeg is not on PATH (the assemble step concatenates the H3 segments with it)")
    os.makedirs(clips, exist_ok=True)
    tag = uuid.uuid4().hex[:8]
    lst = os.path.join(c.root, f".concat-{tag}.txt")
    tmp = os.path.join(clips, f".{os.path.basename(out)}.{tag}.mp4")
    with open(lst, "w", encoding="utf-8", newline="\n") as f:
        for s in segs:
            f.write("file '" + c.p(s["file"]).replace("\\", "/").replace("'", "'\\''") + "'\n")
    base = [ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst]
    encoder = "copy"
    try:
        code = run_cmd(base + ["-c", "copy", "-movflags", "+faststart", tmp])
        if code or not os.path.isfile(tmp) or not os.path.getsize(tmp):
            say("  stream copy failed: re-encoding (libx264 crf 16, aac)")
            encoder = "libx264"
            code = run_cmd(base + ["-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p",
                                   "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", tmp])
            if code or not os.path.isfile(tmp) or not os.path.getsize(tmp):
                print(f"hybrid: ffmpeg failed ({code})", file=sys.stderr)
                return code or 1
        place_new(tmp, out)
    finally:
        for p in (lst, tmp):
            if os.path.exists(p):
                os.remove(p)
    side = {"tool": "tools/comfy/hybrid.py", "workflow": "h3-i2v", "spec": os.path.abspath(c.a.spec),
            "spec_sha256": c.spec_sha, "shot": c.shot, "fps_shot": c.fps, "encoder": encoder,
            "sha256": sha256_file(out),
            "keys": [{"name": k["name"], "frame": k["frame"], "render": c.p(k["render"]), "edit": p, "sha256": sh}
                     for k, p, sh in keys],
            "segments": []}
    for s in segs:
        seg = c.p(s["file"])
        side["segments"].append({"pair": s["pair"], "file": seg, "sha256": s["sha256"],
                                 "sidecar": read_json(seg + ".json", "sidecar") if os.path.isfile(seg + ".json")
                                 else None})
    write_json_atomic(out + ".json", side)
    c.state.setdefault("clips", []).append({"file": os.path.relpath(out, c.media).replace(os.sep, "/"),
                                            "segments": want, "encoder": encoder,
                                            "date": datetime.date.today().isoformat()})
    c.save()
    say(f"clip: {out} ({encoder}) + {os.path.basename(out)}.json")
    return 0


# ------------------------------------------------------------------------------------------------ run / status
def approval_valid(c):
    try:
        return approved_keys(c, required=False) is not None
    except Refused as e:
        say(f"approval: {e}")
        return False


def step_run(c):
    for name, fn in (("keyframes", step_keyframes), ("edit", step_edit)):
        say(f"== {name}")
        code = fn(c)
        if code:
            return code
    if c.dry and not all(c.current_edit(k["name"]) for k in c.keys):
        say("== stop: eye check of the edited key frames (dry-run: they do not exist yet)")
        return 0
    if not approval_valid(c):
        checklist(c)
        say("\nWAITING for the eye check: nothing more runs until the keys are approved.")
        return 0
    for name, fn in (("animate", step_animate), ("assemble", step_assemble)):
        say(f"== {name}")
        code = fn(c)
        if code:
            return code
    return 0


def step_status(c):
    say(f"hybrid {c.eid} {c.shot}: {c.frames} frames at {c.fps} fps · root {c.root}")
    for k in c.keys:
        cur = c.current_edit(k["name"])
        say(f"  {k['name']} frame {k['frame']:>4}  render {'ok' if os.path.isfile(c.p(k['render'])) else '-'}"
            f"  edit {cur['file'] if cur else '-'}")
    data = read_json(c.p(APPROVED), "approval")
    say("  approved: " + (", ".join(data["keys"]) + f" ({data.get('date')})" if data and data.get("keys")
                          else "no (eye check pending)"))
    for s in c.state.get("segments", []):
        say(f"  segment {s['pair']}: {s['file']}")
    for cl in c.state.get("clips", []):
        say(f"  clip: {cl['file']} ({cl['encoder']})")
    return 0


# ------------------------------------------------------------------------------------------------ CLI
def parser():
    p = argparse.ArgumentParser(prog="hybrid.py", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sp = p.add_subparsers(dest="cmd", required=True)

    def common(q):
        q.add_argument("spec", help="<episode>/shots3d/s<NN>.json")
        q.add_argument("--media", required=True, help="the episode's media folder out/<project>/<id>")
        q.add_argument("--root", default=None, help="work folder (default <media>/renders3d/<shot>_keys)")
        q.add_argument("--shot", default=None, help="shot id when the spec is not named s<NN>.json")
        q.add_argument("--dry-run", action="store_true", help="print the plan, call nothing")

    def steps(q):
        q.add_argument("--ledger", default=None, help="the episode's ledger.csv (env FILM_LEDGER)")
        q.add_argument("--review", default=None, metavar="BUILD", help="pass-through to blender.py/comfy.py")
        q.add_argument("--keys", type=int, choices=(2, 3), default=None, help="key frames per shot (default 2)")
        q.add_argument("--mid", type=int, action="append", default=None, metavar="FRAME",
                       help="frame of the middle key (default: the middle frame with --keys 3)")
        q.add_argument("--size", default=None, help=f"key frame size (default {KEY_SIZE}, H3's canvas)")
        q.add_argument("--look", default=None, help="blender.py --look")
        q.add_argument("--edit-prompt", default=None)
        q.add_argument("--edit-prompt-file", default=None)
        q.add_argument("--lightning", type=int, choices=(4, 8), default=None, help="Lightning LoRA (default 8)")
        q.add_argument("--denoise", type=float, default=None, help="default 1.0")
        q.add_argument("--edit-seed", type=int, default=None, help=f"one seed for every key (default "
                                                                  f"{DEFAULT_EDIT_SEED})")
        q.add_argument("--edit-steps", type=int, default=None)
        q.add_argument("--edit-cfg", type=float, default=None)
        q.add_argument("--ref", action="append", default=None, metavar="IMG", help="qwen-edit reference image")
        q.add_argument("--redo", default=None, metavar="k2,...", help="edit these keys again (all = every key)")
        q.add_argument("--expect", action="append", default=None, metavar="TEXT",
                       help="an extra line of the eye checklist (e.g. \"5-6 tail ribbons\")")
        q.add_argument("--motion-prompt", action="append", default=None, metavar="TEXT")
        q.add_argument("--motion-prompt-file", action="append", default=None, metavar="F.json")
        q.add_argument("--res", choices=("480p", "768p"), default=None, help="h3-i2v canvas (default 768p)")
        q.add_argument("--motion-seed", type=int, default=None)
        q.add_argument("--turbo", action="store_true", help="h3-i2v Lightning LoRA: drafts only")
        q.add_argument("--approved", default=None, metavar="k1,k2", help="approve these keys first")

    for q in (sp.add_parser("run", help="every step, stopping at the eye check until approved"),
              sp.add_parser("keyframes", help="Blender key frames"),
              sp.add_parser("edit", help="Qwen-Edit the key frames + the eye checklist"),
              sp.add_parser("animate", help="H3 between consecutive approved keys"),
              sp.add_parser("assemble", help="concat the H3 segments into one clip")):
        common(q)
        steps(q)
    q = sp.add_parser("approve", help="record the owner's eye check: the approved keys")
    common(q)
    q.add_argument("keys_ok", metavar="k1,k2[,k3]")
    q = sp.add_parser("status", help="what is done")
    common(q)
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    a = parser().parse_args(argv)
    try:
        c = Ctx(a)
        if a.cmd == "approve":
            approve(c, a.keys_ok)
            return 0
        if a.cmd == "status":
            return step_status(c)
        fn = {"run": step_run, "keyframes": step_keyframes, "edit": step_edit, "animate": step_animate,
              "assemble": step_assemble}[a.cmd]
        code = fn(c)
        if a.cmd == "edit" and not code and not c.dry:
            checklist(c)
        if c.dry and not code:
            say("dry-run: nothing called, no ledger row")
        return code
    except Refused as e:
        print(f"hybrid: refused: {e}", file=sys.stderr)
        return REFUSED


if __name__ == "__main__":
    sys.exit(main())
