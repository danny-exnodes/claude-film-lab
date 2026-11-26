#!/usr/bin/env python3
"""One read-only screen for an episode: stage, method, gates, budget, open paid requests, layers, forecast, gate.

  python3 tools/status.py <episode dir> [--media DIR] [--gate G1|G2|G3|G4] [--json]
  python3 tools/status.py --ledger L.csv [--budget budget.yaml] [--json]      # BUDGET section only

Run it at session start and before a gate instead of reading EPISODE.md, budget.yaml, ledger.csv, prompts.csv
and the media tree by hand. It writes nothing and makes no network call.

Sections: STAGE (stage, gates, BLOCKED lines), METHOD (`method:` of EPISODE.md: layers | seedance | code | blender,
missing = seedance; code = characters drawn in code, nothing to pay for; blender = Blender 3D renders on the owner's PC,
free; plus `video_engine:` seedance | comfy for stage 6), NEXT (the `## Việc tiếp theo` lines of EPISODE.md), BUDGET (used against each cap, counted exactly like
tools/ark.py does, then ATTENTION: OPEN / CUT-502 / FAILED / MISSING requests), SHOTS (state of every layer of
every shot, clips, orphan plates), FORECAST (what the episode will still cost, from shots.csv and prompts.csv
alone: images to make, Seedance seconds planned, each against what is left under budget.yaml: `fits` or
`OVER by N`; CONFLICT lines for ai_motion shots in a `method: layers` episode), MEDIA (files in no bundle,
renders, and `UNSAVED media`: renders, vo/ takes and audio/ stems with no line of their current hash in the project's
.pulled.sha256, i.e. not pushed to Drive 04_SanXuat/<episode>/_ChuaDuyet/ yet – tools/drive_sync.py), CREATURES (the
`## Sinh vật của tập` table of EPISODE.md: main creature, owner's book photo, concept; an `OWNER_REFS` line when
SERIES.md has owner_refs.required: true; shown when the table exists, owner_refs is required or the method is blender
or code), GATE (checklist for the first undated gate, or the one named by --gate). LOCAL (inside BUDGET): ledger rows
of the local engines (model comfy:* or blender:*), free: they count against no cap and are never OPEN/MISSING paid
requests (tools/ark.py skips them the same way); FORECAST adds the local GPU minutes still to run (estimates).

Exit codes: 0 nothing blocks; 1 something needs action (a BLOCKED line, an OPEN request, a MISSING paid file, or
--gate given and that gate is not ready); 2 usage (no EPISODE.md, unreadable front matter).
The media folder comes from `media:` in EPISODE.md (relative to the repo root) or --media; the episode folder name
is never parsed.
"""
import argparse, csv, datetime, io, json, math, os, re, shlex, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import ark            # noqa: E402  (tools/ark.py: the one ledger/budget implementation; no import side effects)
import check_episode  # noqa: E402  (tools/check_episode.py: front matter and text reading)
import drive_sync     # noqa: E402  (tools/drive_sync.py: which media are on Drive, from .pulled.sha256)

STAGES = {0: "Mở tập", 1: "Nghiên cứu nguồn", 2: "Kịch bản, shot list", 3: "Thiết kế nhân vật, bối cảnh",
          4: "Ảnh khóa", 5: "Lớp tranh", 6: "Clip AI", 7: "Dựng shot, âm thanh", 8: "Dựng cả tập",
          9: "Kiểm tra độc lập", 10: "Bản cuối", 11: "Xuất bản"}        # docs/WORKFLOW.md §2
BLENDER_STAGES = {3: "Model 3D, shot3d.json", 4: "Turntable + shot mẫu", 5: "Render Blender", 6: "Clip AI (tuỳ chọn)"}
GATE_STAGE = {"G1": 2, "G2": 4, "G3": 8, "G4": 10}                      # the stage each gate closes
GATES = list(GATE_STAGE)
NEXT_HEADING = "## Việc tiếp theo"
RE_SHOT = re.compile(r"_(s\d{2,3})_")            # s<NN> or s<NNN> (tools/episode_id.py)
RE_VERSION = re.compile(r"_v(\d{2})\.")
RE_RENDER = re.compile(r"_(draft|final)_v(\d{2})\.mp4$")
RE_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
STATUSES = ["ok", "cut-502", "failed", "abandoned", "pending"]
LIST_MAX = 10          # MISSING lines shown in the text form (the JSON form has them all)
USAGE_EXIT = 2
METHODS = ("layers", "seedance", "code", "blender")   # EPISODE.md `method:`; missing = seedance (episodes older than the key)
DEFAULT_METHOD = "seedance"
VIDEO_ENGINES = ("seedance", "comfy")      # EPISODE.md `video_engine:` (method seedance and blender); missing = seedance
LOCAL_PREFIXES = ("comfy:", "blender:")   # ledger models of the local engines: free, counted against no cap
# Local GPU time, for FORECAST only. ESTIMATES, not a promise: measure on the owner's PC and fix these numbers.
#   MiniMax H3 (tools/comfy/, workflow h3-i2v / h3-r2v), measured on the owner's PC 2026-11-25: a 5.17 s clip at
#   1344x768, 20 steps = 713 GPU s (~34 s per step) = 2.3 min per clip second; the 864x480 draft (~10 s per step, from
#   the owner's Desktop logs) is ~0.8 min per clip second.
H3_MIN_PER_S = {"final": 2.3, "draft": 0.8}
#   Blender (tools/blender/blender.py render), per shot: --preview 960x540 12 fps, final 1920x1080 24 fps EEVEE (estimate)
BLENDER_MIN_PER_SHOT = {"preview": 1.0, "final": 5.0}
MIN_CLIP_S = 4                     # shortest clip Seedance accepts (docs/MODELS.md): a shorter shot still bills 4 s
TO_MAKE = ("no-prompt", "todo", "rejected")   # layer states that still need a paid image


class Usage(Exception):
    pass


def show(path):
    """A path as the user would type it from the current directory."""
    rel = os.path.relpath(path)
    return path if rel.startswith("..") else rel


# ------------------------------------------------------------------ episode ---
def load_episode(ep_dir):
    path = os.path.join(ep_dir, "EPISODE.md")
    if not os.path.isfile(path):
        raise Usage(f"{path}: not found (give the episode folder, the one that holds EPISODE.md)")
    import yaml
    try:
        fm, body = check_episode.split_front_matter(check_episode.read_text(path))
        meta = yaml.safe_load(fm) if fm is not None else None
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise Usage(f"{path}: unreadable front matter: {str(e).splitlines()[0]}")
    if not isinstance(meta, dict):
        raise Usage(f"{path}: unreadable front matter (no '---' block holding a mapping)")
    stage = meta.get("stage")
    if not isinstance(stage, int) or isinstance(stage, bool):
        raise Usage(f"{path}: unreadable front matter: stage must be a number 0-11 (got {stage!r})")
    return meta, body


def read_method(meta, notes):
    """The production method of the episode: {name: the method the forecast uses, source: episode | default |
    invalid, raw: the value as written}. Only the exact words layers / seedance / code are a method."""
    raw = meta.get("method")
    if "method" not in meta:
        return {"name": DEFAULT_METHOD, "source": "default", "raw": None}
    if isinstance(raw, str) and raw.strip() in METHODS:
        return {"name": raw.strip(), "source": "episode", "raw": raw}
    notes.append(f"EPISODE.md: method = {raw!r} is not layers | seedance | code | blender: the forecast counts the "
                 f"episode as {DEFAULT_METHOD}")
    return {"name": DEFAULT_METHOD, "source": "invalid", "raw": raw}


def read_video_engine(meta, method, notes):
    """The clip engine of stage 6: {name: seedance | comfy | None (method layers/code: no clip), explicit: bool}."""
    raw = meta.get("video_engine")
    if method in ("layers", "code"):
        if "video_engine" in meta:
            notes.append(f"EPISODE.md: video_engine = {raw!r} in a method {method} episode (makes no clip): ignored")
        return {"name": None, "explicit": False}
    if "video_engine" not in meta:
        return {"name": "seedance", "explicit": False}
    if isinstance(raw, str) and raw.strip().lower() in VIDEO_ENGINES:
        return {"name": raw.strip().lower(), "explicit": True}
    notes.append(f"EPISODE.md: video_engine = {raw!r} is not seedance | comfy: counted as seedance")
    return {"name": "seedance", "explicit": False}


def method_text(m, engine=None):
    if m["source"] == "default":
        out = f"{m['name']} (default, no method: in EPISODE.md)"
    elif m["source"] == "invalid":
        out = f"invalid ({m['raw']!r}; counted as {m['name']})"
    else:
        out = m["name"]
    if engine and engine.get("explicit"):
        out += f" · video_engine {engine['name']}" + (" (local ComfyUI clips, free)" if engine["name"] == "comfy" else "")
    return out


def stage_name(stage, method):
    """The stage's name (docs/WORKFLOW.md §2); method blender names stages 3-6 after its own work."""
    if method == "blender" and stage in BLENDER_STAGES:
        return BLENDER_STAGES[stage]
    return STAGES.get(stage, "?")


def is_local(row):
    """A ledger row of a local engine (tools/comfy/comfy.py, tools/blender/blender.py): free."""
    return str(row.get("model") or "").startswith(LOCAL_PREFIXES)


def gate_dates(meta, notes):
    """Gate -> its date as text, or None. Only a date passes a gate: `G2: false`, `no`, 0 or 'null' do not."""
    g = meta.get("gates") if isinstance(meta.get("gates"), dict) else {}
    out = {}
    for k in GATES:
        v = g.get(k)
        dated = isinstance(v, datetime.date) or (isinstance(v, str) and RE_DATE.match(v.strip()))
        out[k] = str(v).strip() if dated else None
        if not dated and v not in (None, ""):
            notes.append(f"EPISODE.md: gates.{k} = {v!r} is not a date YYYY-MM-DD: counts as not passed")
    return out


def blocked_gates(stage, gates):
    return [{"gate": g, "stage": stage, "text": f"stage {stage} needs {g} (not passed)"}
            for g in GATES if GATE_STAGE[g] < stage and not gates[g]]


def next_lines(body):
    out, on = [], False
    for line in body.splitlines():
        if line.startswith("## "):
            if on:
                break
            on = line.strip() == NEXT_HEADING
        elif on:
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    while out and not out[0].strip():
        out.pop(0)
    return out


def media_dir(meta, override):
    if override:
        return override
    m = meta.get("media")
    if not isinstance(m, str) or not m.strip():
        return None
    return m if os.path.isabs(m) else os.path.join(LAB, m)


# ------------------------------------------------------------------- budget ---
def read_budget(path, notes):
    """(budget dict or None, state) where state is ok | missing | invalid. Never raises."""
    name = os.path.basename(path)
    if not os.path.isfile(path):
        notes.append(f"{name} not found at {show(path)}: no caps to compare with")
        return None, "missing"
    try:
        b = ark.load_budget(path)
    except SystemExit as e:
        why = e.code if isinstance(e.code, str) else f"tools/ark.py refused it (exit {e.code})"
        notes.append(f"{name} is not usable: {why}")
        return None, "invalid"
    except Exception as e:
        notes.append(f"{name} is not usable: {str(e).splitlines()[0] if str(e) else type(e).__name__}")
        return None, "invalid"
    if not isinstance(b, dict):
        notes.append(f"{name} is not usable: not a mapping")
        return None, "invalid"
    return b, "ok"


def cap_value(budget, key, notes, where=None):
    v = (where if where is not None else budget or {}).get(key)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        notes.append(f"budget.yaml: cap {key} is not a number ({v!r}): ignored")
        return None
    return v


def read_ledger(path, notes):
    if not path or not os.path.isfile(path):
        notes.append(f"{os.path.basename(path) if path else 'ledger.csv'} not found"
                     f"{' at ' + show(path) if path else ''}: nothing counted as spent")
        return []
    try:
        return ark.ledger_rows(path)
    except Exception as e:
        notes.append(f"{show(path)} could not be read: {e}")
        return []


def budget_section(budget, billed, notes):
    """One entry per cap; `used` is the sum of ark.units over ark.billed_requests, as in ark.budget_check."""
    def entry(name, rows, cap):
        by = {s: sum(ark.units(r) for r in rows if r.get("status") == s) for s in STATUSES}
        used = sum(ark.units(r) for r in rows)
        return {"name": name, "used": used, "cap": cap, "left": None if cap is None else cap - used, "by_status": by}

    caps = [entry("images", [r for r in billed if r.get("kind") == "image"], cap_value(budget, "images", notes)),
            entry("video_seconds", [r for r in billed if r.get("kind") == "video"],
                  cap_value(budget, "video_seconds", notes))]
    models = (budget or {}).get("models")
    for model in (models if isinstance(models, dict) else {}):
        cap = cap_value(budget, model, notes, models)
        if cap is not None:
            caps.append(entry(f"models.{model}", [r for r in billed if r.get("model") == model], cap))
    return {"caps": caps}


RE_GPU_S = re.compile(r"(?:^|[;\s])gpu_s=([0-9.]+)")


def local_section(rows):
    """Ledger rows of the local engines (model comfy:* / blender:*), one per request: the last final row of its req=
    (any status but pending), else its pending row (a run that died or still runs). Free: no cap counts them."""
    groups, single = {}, []
    for r in rows:
        if not is_local(r):
            continue
        rid = ark.req_id(r) or (("task:" + r["task_id"]) if r.get("task_id") else None)
        (groups.setdefault(rid, []) if rid else single).append(r)
    decided = list(single) + [([x for x in g if x.get("status") != "pending"] or g)[-1] for g in groups.values()]
    models = {}
    for r in decided:
        m = models.setdefault(r.get("model") or "?", {"model": r.get("model") or "?", "requests": 0, "by_status": {},
                                                       "video_s": 0.0, "gpu_s": 0.0})
        m["requests"] += 1
        st_ = r.get("status") or "?"
        m["by_status"][st_] = m["by_status"].get(st_, 0) + 1
        if r.get("kind") == "video" and st_ == "ok":
            m["video_s"] += ark.units(r)
        g = RE_GPU_S.search(r.get("usage") or "")
        if g:
            try:
                m["gpu_s"] += float(g.group(1))
            except ValueError:
                pass
    open_ = [{"req": ark.req_id(r) or "-", "model": r.get("model") or "", "out": r.get("out") or "",
              "age": age_text(r.get("ts"))} for r in decided if r.get("status") == "pending"]
    return {"models": sorted(models.values(), key=lambda m: m["model"]), "open": open_}


def age_text(ts, now=None):
    try:
        t = datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return "?"
    s = max(0, int(((now or datetime.datetime.now(datetime.timezone.utc)) - t).total_seconds()))
    return f"{s // 86400}d" if s >= 86400 else f"{s // 3600}h" if s >= 3600 else f"{s // 60}m"


def media_index(media):
    """basename -> path for every file under <media>/plates and <media>/clips (subfolders included)."""
    found = {}
    for sub in ("plates", "clips"):
        for root, dirs, names in os.walk(os.path.join(media, sub)) if media else ():
            dirs.sort()
            for n in sorted(names):
                found.setdefault(n, os.path.join(root, n))
    return found


def attention_section(rows, billed, ledger, media, bundled):
    """OPEN (pending, no final row), CUT/FAILED (final row not ok) and MISSING (ok, file gone) requests."""
    led = shlex.quote(show(ledger)) if ledger else "L.csv"
    tasks = {}
    for r in rows:                                   # a request's task id may sit on any of its rows
        if r.get("task_id") and ark.req_id(r):
            tasks[ark.req_id(r)] = r["task_id"]
    index = None
    att = {"open": [], "cut_failed": [], "missing": []}
    for r in billed:
        rid = ark.req_id(r)
        task = r.get("task_id") or tasks.get(rid) or ""
        out = r.get("out") or ""
        item = {"req": rid or (f"task:{task}" if task else "-"), "kind": r.get("kind") or "", "out": out,
                "status": r.get("status"), "ts": r.get("ts") or "", "model": r.get("model") or "",
                "size": r.get("size") or "", "agent": r.get("agent") or "", "task_id": task, "commands": []}
        resume = " ".join(["python3 tools/ark.py video --resume-task", shlex.quote(task)]
                          + ([shlex.quote(out)] if out else [])
                          + ["--ledger", led])
        if r.get("status") == "pending":
            item["age"] = age_text(r.get("ts"))
            if r.get("kind") == "video" and task:
                item["commands"].append(resume)
            if "lambda" in (r.get("note") or "").lower():
                item["commands"].append(f"read jobs/{rid or '<req>'}.json from the bucket, then python3 tools/ark.py "
                                        f"lambda-job finish --status-json <file> --image <image> --ledger {led}")
            if rid:      # an orphan that will never get a final row: close it (it stays counted)
                item["close"] = f"python3 tools/ark.py ledger-close --req {rid} --ledger {led} --status abandoned"
            att["open"].append(item)
        elif r.get("status") == "abandoned":
            continue                                 # closed by ledger-close: counted, no file expected
        elif r.get("status") in ("cut-502", "failed"):
            if r.get("status") == "failed" and r.get("kind") == "video" and task:
                item["commands"].append(resume)
            att["cut_failed"].append(item)
        elif out:
            if os.path.exists(out) or (not os.path.isabs(out) and os.path.exists(os.path.join(LAB, out))):
                continue
            if index is None:
                index = media_index(media)
            base = os.path.basename(out)
            if base in index:
                continue
            item["bundle"] = next((z for z, names in bundled.items() if any(os.path.basename(n) == base
                                                                           for n in names)), None)
            att["missing"].append(item)
    return att


# -------------------------------------------------------------------- shots ---
def read_table(path, notes, what):
    """Rows of a CSV as dicts (empty list with a note when the file is missing or unreadable)."""
    name = os.path.basename(path)
    if not os.path.isfile(path):
        notes.append(f"{name} not found: {what}")
        return None
    try:
        rows = list(csv.DictReader(io.StringIO(check_episode.read_text(path), newline="")))
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        notes.append(f"{name} could not be read ({e}): {what}")
        return None
    return [{k: (v or "").strip() for k, v in r.items() if isinstance(k, str)} for r in rows]


def version_of(name):
    m = RE_VERSION.search(name or "")
    return int(m.group(1)) if m else 0


def listdir_files(path):
    try:
        return sorted(n for n in os.listdir(path) if not n.startswith(".") and os.path.isfile(os.path.join(path, n)))
    except OSError:
        return []


def layer_state(rows, plates, on_disk):
    """State of one (shot, layer) from its prompts.csv rows; the highest version decides."""
    if not rows:
        return {"state": "no-prompt"}
    row = max(rows, key=lambda r: version_of(r.get("file")))
    name = row.get("file", "")
    here = name in on_disk
    approved = row.get("approved", "").lower()
    out = {"file": name}
    if approved == "no":
        m = RE_VERSION.search(name)
        stem = name[:m.start()] if m else None
        taken = [version_of(r.get("file")) for r in rows]
        taken += [version_of(n) for n in plates if stem and n.startswith(stem + "_v")]
        out.update(state="rejected", next_version=max(taken) + 1)
    elif approved == "yes":
        out["state"] = "approved" if here else "lost"
    elif here:
        out["state"] = "made"
    else:
        out["state"] = "lost" if row.get("usage") else "todo"
    return out


def shots_section(ep_dir, media, notes, method=None):
    shots = read_table(os.path.join(ep_dir, "shots.csv"), notes, "no shot table")
    code = method in ("code", "blender")            # layers drawn in code / rendered by Blender: no prompts.csv
    prompts = None if code else read_table(os.path.join(ep_dir, "prompts.csv"), notes, "every layer shows as no-prompt")
    blender = method == "blender"
    renders3d, turntables = check_episode.renders3d_index(media) if blender else ({}, [])
    shots3d = {m.group(1) for m in (check_episode.RE_SHOT3D_FILE.match(n) for n in
                                    listdir_files(os.path.join(ep_dir, "shots3d"))) if m} if blender else set()
    plates = listdir_files(os.path.join(media, "plates")) if media else []
    on_disk = set(plates)
    clip_shots = set()
    for root, _dirs, names in os.walk(os.path.join(media, "clips")) if media else ():
        for n in names:
            m = RE_SHOT.search(n)
            if m and n.lower().endswith(".mp4"):
                clip_shots.add(m.group(1))
    out = []
    for s in shots or []:
        shot = s.get("shot", "")
        if not shot:
            continue
        layers = []
        for code in [c.strip() for c in s.get("layers", "").split(";") if c.strip()]:
            if method == "code":
                layers.append({"layer": code, "state": "drawn"})
                continue
            if blender:
                layers.append({"layer": code, "state": "3d"})
                continue
            rows = [r for r in prompts or [] if r.get("shot") == shot and r.get("layer") == code]
            layers.append(dict({"layer": code}, **layer_state(rows, plates, on_disk)))
        item = {"shot": shot, "reuse_of": s.get("reuse_of") or None, "layers": layers,
                "clip": (shot in clip_shots) if s.get("ai_motion") else None,
                "from_s": s.get("from_s", ""), "to_s": s.get("to_s", "")}
        if blender:          # shot3d.json written? Blender render: final | preview | none
            r3 = renders3d.get(shot, {})
            item.update(shot3d=shot in shots3d,
                        render="final" if r3.get("final") else "preview" if r3.get("preview") else "none")
        out.append(item)
    listed = {r.get("file") for r in prompts or []}
    return {"present": {"shots.csv": shots is not None, "prompts.csv": prompts is not None},
            "shots": out, "orphans": [n for n in plates if n not in listed], "turntables": turntables}


# ----------------------------------------------------------------- forecast ---
def clip_seconds(shot):
    """(whole seconds one Seedance clip for this shot would bill, None), or (None, why) when from_s/to_s are
    unusable."""
    try:
        a, b = float(shot["from_s"]), float(shot["to_s"])
    except (TypeError, ValueError):
        return None, f"from_s={shot['from_s']!r} to_s={shot['to_s']!r} are not numbers"
    if not (math.isfinite(a) and math.isfinite(b)) or b <= a:
        return None, f"from_s={shot['from_s']} to_s={shot['to_s']} is not a positive duration"
    return max(MIN_CLIP_S, math.ceil(round(b - a, 6))), None


def shot_length(shot):
    """Seconds of a shot (from_s/to_s), or None when they are unusable."""
    try:
        a, b = float(shot["from_s"]), float(shot["to_s"])
    except (TypeError, ValueError):
        return None
    return b - a if math.isfinite(a) and math.isfinite(b) and b > a else None


def local_forecast(shots, method, engine):
    """Local GPU minutes still to run (ESTIMATES: BLENDER_MIN_PER_SHOT, H3_MIN_PER_S): Blender renders of the non-reuse
    shots of a method blender episode (preview + final, or only the final once a preview exists) and one local H3
    clip per ai_motion shot without a clip when video_engine is comfy. Free; only time."""
    out = {"estimate": True, "blender_shots": [], "blender_min": 0.0, "h3_clips": [], "h3_min": 0.0,
           "h3_draft_min": 0.0}
    if method == "blender":
        for s in shots["shots"]:
            if s["reuse_of"] or s.get("render") == "final":
                continue
            m = BLENDER_MIN_PER_SHOT["final"] + (0 if s.get("render") == "preview" else BLENDER_MIN_PER_SHOT["preview"])
            out["blender_shots"].append(s["shot"])
            out["blender_min"] += m
    if engine and engine.get("name") == "comfy":
        for s in shots["shots"]:
            if s["clip"] is False and not s["reuse_of"]:
                sec = shot_length(s)
                if sec is None:
                    continue
                out["h3_clips"].append({"shot": s["shot"], "seconds": round(sec, 3)})
                out["h3_min"] += sec * H3_MIN_PER_S["final"]
                out["h3_draft_min"] += sec * H3_MIN_PER_S["draft"]
    return out


def forecast_section(shots, method, caps, notes, engine=None):
    """What is still to pay for, from the SHOTS data alone (no network), against what is left under each cap.
    Images: one per layer code of a non-reuse shot that is neither approved, made nor lost (a lost file was paid
    for: it is pulled back from Drive, see MISSING). Video: one clip per ai_motion shot without a clip, the shot
    length rounded up to whole seconds and never under MIN_CLIP_S; a `layers` episode plans none and lists every
    ai_motion shot as a conflict. video_engine comfy plans no paid second: its clips go to `local` (GPU minutes, an
    estimate), like the Blender renders of a method blender episode. Returns None when there is no shots.csv."""
    if not shots["present"]["shots.csv"]:
        return None
    engine = engine or {"name": None if method in ("layers", "code") else "seedance", "explicit": False}
    states = [l["state"] for s in shots["shots"] if not s["reuse_of"] for l in s["layers"]]
    clips, conflicts, skipped = [], [], []
    for s in shots["shots"]:
        if s["clip"] is None:                       # no ai_motion: code motion only
            continue
        if method in ("layers", "code"):
            conflicts.append(f"method {method} but {s['shot']} has ai_motion")
        elif method == "blender" and not engine.get("explicit"):
            conflicts.append(f"method blender but {s['shot']} has ai_motion and EPISODE.md has no video_engine "
                             f"(comfy = local clip, seedance = paid clip)")
        elif s["clip"] is False and engine.get("name") == "seedance":
            seconds, why = clip_seconds(s)
            if seconds is None:
                skipped.append(s["shot"])
                notes.append(f"shots.csv: {s['shot']} {why}: its clip is not counted in the forecast")
            else:
                clips.append({"shot": s["shot"], "seconds": seconds})
    left = {c["name"]: c["left"] for c in caps}

    def against(need, cap):
        rest = left.get(cap)
        over = 0 if rest is None or need <= max(rest, 0) else need - rest
        return {"left": rest, "over": over,
                "verdict": "no cap" if rest is None else f"OVER by {over:g}" if over else "fits"}

    images = {"layers": len(states), "approved": states.count("approved"), "made": states.count("made"),
              "lost": states.count("lost"), "to_make": sum(1 for x in states if x in TO_MAKE)}
    images.update(against(images["to_make"], "images"))
    video = {"planned": sum(c["seconds"] for c in clips), "clips": clips}
    video.update(against(video["planned"], "video_seconds"))
    return {"method": method, "images": images, "video_seconds": video, "conflicts": conflicts, "skipped": skipped,
            "fits": not images["over"] and not video["over"], "local": local_forecast(shots, method, engine)}


def forecast_text(f, notes):
    def tail(x):
        return "no cap" if x["left"] is None else f"{x['left']:g} left · {x['verdict']}"

    i, v = f["images"], f["video_seconds"]
    had = [f"{i[k]} {k}" for k in ("approved", "made", "lost") if i[k]]
    each = ", ".join(f"{c['shot']} {c['seconds']}" for c in v["clips"])
    out = [f"FORECAST (method {f['method']})",
           f"  images: {i['to_make']} to make of {i['layers']} layers" + (f" ({', '.join(had)})" if had else "")
           + f" · {tail(i)}",
           f"  video_seconds: {v['planned']} planned" + (f" in {len(v['clips'])} clip(s) ({each})" if each else "")
           + f" · {tail(v)}"]
    loc = f.get("local") or {}
    parts = []
    if loc.get("blender_shots"):
        parts.append(f"Blender {len(loc['blender_shots'])} shot(s) ≈ {loc['blender_min']:.0f} min")
    if loc.get("h3_clips"):
        parts.append(f"H3 {len(loc['h3_clips'])} clip(s) ≈ {loc['h3_min']:.0f} min at 1344x768 "
                     f"(draft 864x480 ≈ {loc['h3_draft_min']:.0f} min)")
    if parts:
        out.append("  local GPU (free; estimate, measure): " + " · ".join(parts))
    out += [f"  CONFLICT: {c}" for c in f["conflicts"]]
    return out + notes_text(notes)


def forecast_brief(f):
    """The forecast on one line, for the gate checklist."""
    if f is None:
        return "no shots.csv"

    def one(name, need, word, x):
        return (f"{name} {need} {word}" + ("" if x["left"] is None else f", {x['left']:g} left")
                + (f": {x['verdict']}" if x["over"] else ""))

    return "; ".join([one("images", f["images"]["to_make"], "to make", f["images"]),
                      one("video_seconds", f["video_seconds"]["planned"], "planned", f["video_seconds"])]
                     + ([f"clip of {', '.join(f['skipped'])} not counted: fix from_s/to_s in shots.csv"]
                        if f["skipped"] else []))


# -------------------------------------------------------------------- media ---
def bundle_names(media, notes):
    """zip name -> set of member names for every <media>/bundles/*.zip."""
    out = {}
    d = os.path.join(media, "bundles") if media else ""
    for n in listdir_files(d):
        if not n.lower().endswith(".zip"):
            continue
        try:
            with zipfile.ZipFile(os.path.join(d, n)) as z:
                out[n] = {m.replace("\\", "/") for m in z.namelist()}
        except (zipfile.BadZipFile, OSError) as e:
            notes.append(f"bundles/{n} could not be read ({e}): its files count as not bundled")
    return out


def media_section(media, bundled, notes):
    sec = {"dir": media, "exists": bool(media and os.path.isdir(media)), "unbundled": {}, "draft": None,
           "final": None}
    if not sec["exists"]:
        notes.append(f"media folder {show(media) if media else '(none: no media: in EPISODE.md, no --media)'} "
                     "not found: plates, clips and renders show as absent (container reclaimed? pull the bundles "
                     "from Drive)")
        return sec
    packed = set().union(*bundled.values()) if bundled else set()
    for sub in ("plates", "clips"):
        for root, dirs, names in os.walk(os.path.join(media, sub)):
            dirs.sort()
            for n in names:
                m = RE_SHOT.search(n)
                rel = os.path.relpath(os.path.join(root, n), media).replace(os.sep, "/")
                if m and rel not in packed:
                    sec["unbundled"][m.group(1)] = sec["unbundled"].get(m.group(1), 0) + 1
    sec["unbundled"] = dict(sorted(sec["unbundled"].items()))
    best = {}
    for n in listdir_files(os.path.join(media, "renders")):
        m = RE_RENDER.search(n)
        if m and int(m.group(2)) >= best.get(m.group(1), (-1, ""))[0]:
            best[m.group(1)] = (int(m.group(2)), n)
    for kind in ("draft", "final"):
        sec[kind] = best[kind][1] if kind in best else None
    return sec


def unsaved_section(ep_dir, media, notes):
    """Renders, narration takes and sound stems of this episode not on Drive yet (tools/drive_sync.py unsaved_in):
    {files, by_kind, snapshot}. The project working copy is the episode folder's parent (projects/<project>/)."""
    pd = os.path.dirname(os.path.abspath(ep_dir))
    try:
        snap = drive_sync.read_snapshot(pd)
    except drive_sync.SyncError as e:
        notes.append(f"{e}: every render, take and stem counts as not on Drive")
        snap = None
    found = drive_sync.unsaved_in(pd, media, snap) if media and os.path.isdir(media) else []
    by = {}
    for _, kind in found:
        by[kind] = by.get(kind, 0) + 1
    return {"files": [k for k, _ in found], "by_kind": {k: by[k] for k in drive_sync.SAVE_NOW if k in by},
            "snapshot": snap is not None, "project": pd}


def unsaved_text(m):
    u = m.get("unsaved") or {"files": []}
    loose = sum(m["unbundled"].values())
    if not u["files"]:
        return ["  UNSAVED media: none" + (f" (plates/clips in no bundle: {loose}, see above)" if loose else "")]
    kinds = ", ".join(f"{k} {n}" for k, n in u["by_kind"].items())
    project = show(u["project"])
    out = [f"  UNSAVED media: {len(u['files'])} file(s) not on Drive ({kinds}) – lost when a cloud container is "
           f"reclaimed: push them now to 04_SanXuat/<episode>/_ChuaDuyet/ "
           f"(python3 tools/drive_sync.py plan {project} --include-out out/{os.path.basename(u['project'])})"]
    out += [f"    {k}" for k in u["files"][:LIST_MAX]]
    if len(u["files"]) > LIST_MAX:
        out.append(f"    ... and {len(u['files']) - LIST_MAX} more (see --json)")
    if not u["snapshot"]:
        out.append(f"    (no {drive_sync.SNAPSHOT} in {project}: nothing counts as on Drive)")
    return out


# ---------------------------------------------------------------- creatures ---
def creatures_section(ep_dir, body, method, media, notes):
    """The `## Sinh vật của tập` table (check_episode.read_creatures), SERIES.md owner_refs, the main creatures
    without an approved concept and the creatures still waiting for the owner's book photo."""
    tab = check_episode.read_creatures(body)
    refs, problem = check_episode.owner_refs(ep_dir)
    if problem:
        notes.append(f"SERIES.md: {problem}")
    rows = tab["rows"] if tab else []
    notes += [p for p in (tab or {}).get("problems", [])]
    for r in rows:
        r["concept_file"] = check_episode.concept_record(ep_dir, r["slug"]) if r["concept"] == "approved" else None
    refs_dir = os.path.join(os.path.dirname(os.path.abspath(media)), "assets", "refs") if media else None
    here = [r["slug"] for r in rows if r["book"] == "yes" and refs_dir
            and not listdir_files(os.path.join(refs_dir, r["slug"], "book"))]
    if here:
        notes.append(f"book photo of {', '.join(here)} not on this machine ({show(refs_dir)}/<slug>/book/; never on "
                     "Drive or git): fine in a cloud session, needed on the lab host before modelling")
    return {"present": tab is not None, "rows": rows, "owner_refs": refs,
            "required": bool(refs and refs["required"]),
            "missing_book": [r["slug"] for r in rows if r["book"] == "pending"],
            "concept_gaps": [{"slug": s_, "why": w} for s_, w in check_episode.concept_gaps(ep_dir, rows)],
            "gated": method in check_episode.CREATURE_METHODS}


def owner_refs_text(c):
    """The OWNER_REFS line (only when SERIES.md owner_refs.required)."""
    src = c["owner_refs"]["source"] or "the owner's material (SERIES.md owner_refs.source)"
    if not c["present"]:
        return (f"OWNER_REFS: no '{check_episode.CREATURE_HEADING}' table in EPISODE.md: list every creature/deity of "
                f"the episode and ask the owner for the pages of {src} before the research round")
    if c["missing_book"]:
        return (f"OWNER_REFS: book photo missing for {', '.join(c['missing_book'])}: ask the owner for the pages of "
                f"{src} (or 'không' when the book has none) before the research round")
    have = sum(1 for r in c["rows"] if r["book"] == "yes")
    return (f"OWNER_REFS: ok ({len(c['rows'])} creature(s): {have} with a book photo, "
            f"{len(c['rows']) - have} not in the book)")


def creatures_text(c, notes):
    if not (c["present"] or c["required"] or c["gated"]):
        return notes_text(notes)
    out = [f"CREATURES ({check_episode.CREATURE_HEADING})" if c["present"]
           else f"CREATURES  no '{check_episode.CREATURE_HEADING}' table in EPISODE.md"]
    book = {"yes": "book photo yes", "none": "not in the book", "pending": "book photo PENDING"}
    for r in c["rows"]:
        concept = ("concept approved" + (f" ({r['concept_file']})" if r["concept_file"] else
                                         " (not recorded in CHARACTER.md)")
                   if r["concept"] == "approved" else "concept pending")
        out.append(f"  {r['slug']}  {r['name'] or '-'} · {'main' if r['main'] else 'secondary'} · {book[r['book']]} · "
                   f"{concept}")
    if c["present"] and not c["rows"]:
        out.append("  (no creature listed)")
    if c["required"]:
        out.append("  " + owner_refs_text(c))
    if c["gated"] and c["concept_gaps"]:
        out.append("  concept gate (before any 3D/code model): "
                   + "; ".join(f"{g['slug']} {g['why']}" for g in c["concept_gaps"]))
    return out + notes_text(notes)


# --------------------------------------------------------------------- gate ---
def run_check(ep_dir, media):
    """Run tools/check_episode.py on the episode in a subprocess: (exit code, its Summary line)."""
    cmd = [sys.executable, os.path.join(HERE, "check_episode.py"), "episode", ep_dir]
    if media:
        cmd += ["--media", media]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, f"could not run ({e})"
    lines = [l for l in p.stdout.splitlines() if l.startswith("Summary:")]
    return p.returncode, lines[-1] if lines else f"no Summary line (exit {p.returncode})"


def script_vo_ids(ep_dir):
    """Ids VO1..VOn of the narration lines of script.md, numbered as tools/tts/vieneu_tts.py parse_script does
    (None when script.md is missing or unreadable)."""
    try:
        text = check_episode.read_text(os.path.join(ep_dir, "script.md"))
    except (OSError, check_episode.CheckError):
        return None
    n = 0
    for _, line in check_episode.narration_lines(text):
        m = check_episode.RE_MARK.match(line)
        if m and m.group(3).strip():
            n += 1
    return {f"VO{i}" for i in range(1, n + 1)}


def narration_watermark(media, ids=None):
    """G4: (ok, text) for <media>/vo/tts-log.json of tools/tts/vieneu_tts.py: every take rendered with the audio
    watermark on. No log = no narration rendered by the lab's TTS = n/a. With `ids` (the current script's VO ids),
    takes VO<n> of lines cut from the script are ignored, as `vieneu_tts.py --check` does (the log keeps them);
    takes with other ids (rendered from vo-lines.json with --lines) are always checked."""
    path = os.path.join(media, "vo", "tts-log.json") if media else None
    if not path or not os.path.isfile(path):
        return True, "narration watermark: n/a (no vo/tts-log.json)"
    try:
        with open(path, encoding="utf-8") as f:
            log = json.load(f)
    except (OSError, ValueError) as e:
        return False, f"narration watermark: vo/tts-log.json unreadable ({e})"
    if not isinstance(log, list) or not log or not all(isinstance(e, dict) for e in log):
        return False, "narration watermark: vo/tts-log.json is not a non-empty list of takes"
    if ids is not None:      # VO<n> takes come from --script; other ids (vo-lines.json, --lines) are always checked
        log = [e for e in log if str(e.get("id")) in ids or not re.fullmatch(r"VO\d+", str(e.get("id")))]
        if not log:
            return False, "narration watermark: vo/tts-log.json has no take of the current script.md"
    off = [str(e.get("id", "?")) for e in log if e.get("watermark") is not True]
    if off:
        return False, (f"narration watermark on for every take (off: {', '.join(off[:6])}"
                       f"{f', +{len(off) - 6} more' if len(off) > 6 else ''}; render again with --require-watermark)")
    return True, f"narration watermark on for every take ({len(log)})"


def gate_section(gate, ep_dir, media, d, budget_state, ledger):
    req = []

    def need(ok, text):
        req.append({"ok": bool(ok), "text": text})

    def exists(name, non_empty=False):
        p = os.path.join(ep_dir, name)
        if not os.path.isfile(p):
            return False
        try:
            return not non_empty or bool(check_episode.read_text(p).strip())
        except (OSError, UnicodeDecodeError):
            return False

    for g in GATES[:GATES.index(gate)]:
        need(d["gates"][g], f"{g} dated" + (f" ({d['gates'][g]})" if d["gates"][g] else ""))
    need(not d["blocked"], "stage is not ahead of a gate" +
         (f" ({'; '.join(b['text'] for b in d['blocked'])})" if d["blocked"] else ""))
    rc, summary = run_check(ep_dir, media)
    need(rc == 0, f"check_episode: {summary}")
    c = d.get("creatures")
    if c and c["required"] and gate in ("G1", "G2"):
        # SERIES.md owner_refs.required: the owner's book pages come before the research round (stage 1)
        need(c["present"] and not c["missing_book"],
             "OWNER_REFS: a book photo (or the owner's 'không') for every creature of "
             f"{check_episode.CREATURE_HEADING}" + (f" (missing: {', '.join(c['missing_book'])})" if c["missing_book"]
                                                    else "" if c["present"] else " (no table)"))
    if c and c["gated"] and gate == "G2":
        # method blender/code: no creature model is built before the owner picked its concept (stage 3a)
        if not c["present"]:
            need(False, f"creature table {check_episode.CREATURE_HEADING} in EPISODE.md (empty table when the "
                        "episode has none)")
        else:
            gaps = c["concept_gaps"]
            need(not gaps, "approved concept for every main creature (A-<slug>/C-<slug>: Concept 'duyệt' + "
                           f"{check_episode.CONCEPT_HEADING} in characters/<slug>/CHARACTER.md)"
                 + (f" (not yet: {'; '.join(g['slug'] + ' ' + g['why'] for g in gaps)})" if gaps else ""))
    shots = [s for s in d["shots"]["shots"] if not s["reuse_of"]]
    n_open = len(d["attention"]["open"])
    if gate == "G1":
        need(exists("research.md", non_empty=True), "research.md non-empty")
        need(exists("script.md"), "script.md present")
        need(exists("shots.csv"), "shots.csv present")
        need(budget_state == "ok", f"budget.yaml present and loadable ({budget_state})")
    elif gate == "G2" and d["method"]["name"] == "code":
        # method code: the locked characters (character.json) and a sample shot seen as a turntable + still
        chars = []
        cdir = os.path.join(ep_dir, "characters")
        for root_, _d, names in os.walk(cdir) if os.path.isdir(cdir) else ():
            chars += [os.path.relpath(os.path.join(root_, n), ep_dir) for n in names if n == "character.json"]
        series_chars = os.path.join(os.path.dirname(os.path.abspath(ep_dir)), "characters")
        for root_, _d, names in os.walk(series_chars) if os.path.isdir(series_chars) else ():
            chars += [os.path.relpath(os.path.join(root_, n), os.path.dirname(os.path.abspath(ep_dir)))
                      for n in names if n == "character.json"]
        need(chars, "a character.json (characters/<slug>/)" + (f" ({', '.join(sorted(chars)[:4])})" if chars else " (none)"))
        rv = os.path.join(ep_dir, "review")
        turn = [n for n in listdir_files(rv) if n.startswith("turntable")] if os.path.isdir(rv) else []
        need(turn, "turntable of the characters in review/ (tools/toon/toon.py turntable)" +
             (f" ({', '.join(turn[:3])})" if turn else " (none)"))
        fc = d["forecast"]
        need(fc and fc["fits"] and not fc["conflicts"], f"nothing to pay for ({forecast_brief(fc)})")
    elif gate == "G2" and d["method"]["name"] == "blender":
        # method blender: the 3D models seen as a turntable and one sample shot rendered (blender-method.md)
        turn = d["shots"].get("turntables") or []
        need(turn, "turntable of the 3D models in renders3d/ (tools/blender/blender.py turntable)" +
             (f" ({', '.join(turn[:3])})" if turn else " (none)"))
        sample = [s["shot"] for s in d["shots"]["shots"] if s.get("render") in ("final", "preview")]
        need(sample, "one sample shot rendered in renders3d/ (blender.py render, --preview is enough)" +
             (f" ({', '.join(sample[:4])})" if sample else " (none)"))
        fc = d["forecast"]
        need(fc and fc["fits"] and not fc["conflicts"] and not fc["skipped"],
             f"nothing over the budget ({forecast_brief(fc)})")
    elif gate == "G2":
        need(exists("prompts.csv"), "prompts.csv present")
        done = [s["shot"] for s in shots
                if s["layers"] and all(l["state"] in ("made", "approved") for l in s["layers"])]
        need(done, "one shot with every layer made or approved" + (f" ({', '.join(done)})" if done else " (none)"))
        need(ledger and os.path.isfile(ledger), "ledger.csv present")
        fc = d["forecast"]                 # a clip left out of the sum (unreadable from_s/to_s) proves nothing
        need(fc and fc["fits"] and not fc["skipped"], f"forecast fits the budget ({forecast_brief(fc)})")
    elif gate == "G3":
        bad = [f"{s['shot']} {l['layer']}:{l['state']}" for s in shots for l in s["layers"]
               if l["state"] not in ("approved", "drawn", "3d")]
        need(shots and not bad, "every layer of every non-reuse shot approved" +
             (f" (not yet: {', '.join(bad[:6])}{f', +{len(bad) - 6} more' if len(bad) > 6 else ''})" if bad
              else "" if shots else " (no shots)"))
        if d["method"]["name"] == "blender":
            todo = [s["shot"] for s in shots if s.get("render") != "final"]
            need(shots and not todo, "every non-reuse shot rendered by Blender (final)" +
                 (f" (not yet: {', '.join(todo[:6])}{f', +{len(todo) - 6} more' if len(todo) > 6 else ''})"
                  if todo else ""))
        no_clip = [s["shot"] for s in d["shots"]["shots"] if s["clip"] is False]
        need(not no_clip, "every ai_motion shot has a clip" + (f" (none for {', '.join(no_clip)})" if no_clip else ""))
        need(d["media"]["draft"], f"draft render ({d['media']['draft'] or 'none'})")
        need(not n_open, f"no open paid request ({n_open} open)")
    else:
        need(d["media"]["final"], f"final render ({d['media']['final'] or 'none'})")
        need(not n_open, f"no open paid request ({n_open} open)")
        need(*narration_watermark(media, script_vo_ids(ep_dir)))
    missing = sum(1 for r in req if not r["ok"])
    return {"gate": gate, "ready": missing == 0, "missing": missing, "requirements": req}


# ------------------------------------------------------------------- output ---
def short_id(req):
    """The 8-character prefix of a request id; a request known only by its task id keeps the whole id."""
    return req if req.startswith("task:") else req[:8]


def notes_text(notes):
    return [f"  note: {n}" for n in notes]


def budget_text(d, notes):
    out = ["BUDGET"]
    for c in d["budget"]["caps"]:
        head = (f"{c['name']} {c['used']:g}/{c['cap']:g} ({c['left']:g} left)" if c["cap"] is not None
                else f"{c['name']} {c['used']:g} (no cap)")
        if c["name"].startswith("models."):
            out.append("  " + head)
            continue
        by = c["by_status"]
        parts = [f"ok {by['ok']:g}", f"cut-502 {by['cut-502']:g}"] + \
                [f"{s} {by[s]:g}" for s in ("failed", "abandoned") if by[s]] + [f"pending {by['pending']:g}"]
        out.append("  " + " · ".join([head] + parts))
    loc = d.get("local") or {"models": [], "open": []}
    if loc["models"]:
        out.append("  LOCAL (local engines, free: no cap counts them)")
    for m in loc["models"]:
        parts = [f"{n} {k}" for k, n in sorted(m["by_status"].items())]
        extra = (f" · {m['video_s']:g} s video" if m["video_s"] else "") +                 (f" · GPU {m['gpu_s'] / 60:.1f} min" if m["gpu_s"] else "")
        out.append(f"    {m['model']} {m['requests']} run(s) · {' · '.join(parts)}{extra}")
    for o in loc["open"]:
        out.append(f"    open     {o['req'][:8]} {o['model']} {os.path.basename(o['out']) or '-'} · age {o['age']} "
                   f"(no final row: the run died or still runs; free, nothing to resume)")
    out += notes_text(notes)
    att = d["attention"]
    if any(att.values()):
        out.append("  ATTENTION")
    for o in att["open"]:
        out.append(f"    OPEN     {short_id(o['req'])} {o['kind']} {os.path.basename(o['out']) or '-'} · "
                   f"agent {o['agent'] or '-'} · age {o['age']}" + ("" if o["commands"] else " (counted as spent)"))
        out += [f"             {c}" for c in o["commands"]]
        if o.get("close"):
            out.append(f"             never finishing: {o['close']}")
    for o in att["cut_failed"]:
        out.append(f"    {o['status'].upper():<8} {o['ts']} {o['model']} {o['size']} "
                   f"{os.path.basename(o['out']) or '-'} (billed or may be; do not retry unchanged)")
        out += [f"             {c}" for c in o["commands"]]
    for o in att["missing"][:LIST_MAX]:
        out.append(f"    MISSING  {short_id(o['req'])} {o['kind']} {o['out']} (paid, not on disk"
                   + (f"; inside bundles/{o['bundle']}" if o.get("bundle") else "") + ")")
    if len(att["missing"]) > LIST_MAX:
        out.append(f"             ... and {len(att['missing']) - LIST_MAX} more MISSING (see --json)")
    return out


def episode_text(d, notes):
    st = d["stage"]
    out = [f"STAGE  {st['n']} {st['name']} · " + " · ".join(f"{g} {d['gates'][g] or '-'}" for g in GATES)]
    out += [f"  BLOCKED: {b['text']}" for b in d["blocked"]]
    out += notes_text(notes["stage"])
    out.append(f"METHOD {method_text(d['method'], d.get('video_engine'))}")
    out += notes_text(notes["method"])
    if d.get("creatures"):
        out += creatures_text(d["creatures"], notes["creatures"])
    out.append("NEXT")
    out += d["next"] or ["  (nothing under '## Việc tiếp theo')"]
    out += budget_text(d, notes["budget"])
    out.append("SHOTS")
    for s in d["shots"]["shots"]:
        cells = [f"reuse of {s['reuse_of']}"] if s["reuse_of"] else \
            [f"{l['layer']}:{l['state']}" + (f"(next v{l['next_version']:02d})" if l["state"] == "rejected" else "")
             for l in s["layers"]]
        clip = "" if s["clip"] is None else f" · clip {'yes' if s['clip'] else 'no'}"
        if "render" in s and not s["reuse_of"]:
            clip = f" · shot3d {'yes' if s['shot3d'] else 'no'} · render {s['render']}" + clip
        out.append(f"  {s['shot']}  {' '.join(cells) or '(no layers)'}{clip}")
    if d["shots"].get("turntables"):
        out.append(f"  turntables (renders3d/): {', '.join(d['shots']['turntables'])}")
    if d["shots"]["orphans"]:
        out.append(f"  orphans (in plates/, no prompts.csv row): {', '.join(d['shots']['orphans'])}")
    out += notes_text(notes["shots"])
    if d["forecast"]:
        out += forecast_text(d["forecast"], notes["forecast"])
    m = d["media"]
    out.append(f"MEDIA  {show(m['dir']) if m['dir'] else '-'}")
    out += [f"  {shot}: {n} file(s) only in this container" for shot, n in m["unbundled"].items()]
    out.append(f"  draft: {m['draft'] or 'none'} · final: {m['final'] or 'none'}")
    if m["exists"]:
        out += unsaved_text(m)
    out += notes_text(notes["media"])
    g = d["gate"]
    if g is None:
        out.append("GATE   all four gates are dated")
    else:
        out.append(f"GATE   {g['gate']} (closes stage {GATE_STAGE[g['gate']]})")
        out += [f"  [{'ok' if r['ok'] else 'MISSING'}] {r['text']}" for r in g["requirements"]]
        out.append(f"  Gate {g['gate']}: " + ("READY" if g["ready"] else f"NOT READY ({g['missing']} missing)"))
    return out


def flat(notes):
    return [n for group in notes.values() for n in group]


# --------------------------------------------------------------------- main ---
def collect_ledger(ledger, budget_path, media, bundled, notes):
    budget, state = (None, "missing") if budget_path is None else read_budget(budget_path, notes)
    rows = read_ledger(ledger, notes)
    # Local engines (comfy:*, blender:*) cost nothing: they are left out of every cap and of ATTENTION here, whatever
    # tools/ark.py counts, and listed apart under LOCAL.
    billed = [r for r in ark.billed_requests(rows) if not is_local(r)]
    paid_rows = [r for r in rows if not is_local(r)]
    return ({"budget": budget_section(budget, billed, notes),
             "attention": attention_section(paid_rows, billed, ledger, media, bundled),
             "local": local_section(rows)}, state)


def needs_action(d):
    return bool(d.get("blocked") or d["attention"]["open"] or d["attention"]["missing"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 epilog="exit 0 nothing blocks · 1 needs action · 2 usage")
    ap.add_argument("episode", nargs="?", help="episode folder (holds EPISODE.md)")
    ap.add_argument("--media", help="media folder (default: media: in EPISODE.md, relative to the repo root)")
    ap.add_argument("--gate", choices=GATES, help="check this gate (default: the first undated one); "
                                                   "exit 1 when it is not ready")
    ap.add_argument("--ledger", help="ledger.csv (default <media>/ledger.csv); alone: print BUDGET only")
    ap.add_argument("--budget", help="budget.yaml (default <episode dir>/budget.yaml)")
    ap.add_argument("--json", action="store_true", help="print the same data as one JSON object")
    a = ap.parse_args(argv)

    if a.episode is None:
        if not a.ledger:
            ap.error("give an episode folder, or --ledger L.csv for the budget section alone")
        notes = {"budget": []}
        media = os.path.dirname(os.path.abspath(a.ledger))
        d, _ = collect_ledger(a.ledger, a.budget, media, bundle_names(media, notes["budget"]), notes["budget"])
        d["notes"] = flat(notes)
        print(json.dumps(d, ensure_ascii=False, indent=1) if a.json else "\n".join(budget_text(d, notes["budget"])))
        return 1 if needs_action(d) else 0

    try:
        meta, body = load_episode(a.episode)
    except Usage as e:
        print(f"error: {e}", file=sys.stderr)
        return USAGE_EXIT
    notes = {"stage": [], "method": [], "creatures": [], "budget": [], "shots": [], "forecast": [], "media": []}
    if not isinstance(meta.get("gates"), dict):
        notes["stage"].append("EPISODE.md: gates is not a mapping {G1: ..., G4: ...}: every gate counts as not passed")
    media = media_dir(meta, a.media)
    ledger = a.ledger or (os.path.join(media, "ledger.csv") if media else None)
    stage = meta["stage"]
    bundled = bundle_names(media, notes["media"])
    d = {"stage": {"n": stage, "name": STAGES.get(stage, "?"), "length_s": meta.get("length_s")},
         "gates": gate_dates(meta, notes["stage"])}
    d["blocked"] = blocked_gates(stage, d["gates"])
    d["method"] = read_method(meta, notes["method"])
    d["video_engine"] = read_video_engine(meta, d["method"]["name"], notes["method"])
    d["stage"]["name"] = stage_name(stage, d["method"]["name"])
    d["next"] = next_lines(body)
    led, budget_state = collect_ledger(ledger, a.budget or os.path.join(a.episode, "budget.yaml"), media, bundled,
                                       notes["budget"])
    d.update(led)
    d["shots"] = shots_section(a.episode, media, notes["shots"], d["method"]["name"])
    d["forecast"] = forecast_section(d["shots"], d["method"]["name"], d["budget"]["caps"], notes["forecast"],
                                     d["video_engine"])
    d["creatures"] = creatures_section(a.episode, body, d["method"]["name"], media, notes["creatures"])
    d["media"] = media_section(media, bundled, notes["media"])
    if d["media"]["exists"]:
        d["media"]["unsaved"] = unsaved_section(a.episode, media, notes["media"])
    gate = a.gate or next((g for g in GATES if not d["gates"][g]), None)
    d["gate"] = gate_section(gate, a.episode, media, d, budget_state, ledger) if gate else None
    d["notes"] = flat(notes)
    print(json.dumps(d, ensure_ascii=False, indent=1, default=str) if a.json else "\n".join(episode_text(d, notes)))
    return 1 if needs_action(d) or (a.gate and not d["gate"]["ready"]) else 0


if __name__ == "__main__":
    sys.exit(main())
