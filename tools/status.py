#!/usr/bin/env python3
"""One read-only screen for an episode: stage, method, gates, budget, open paid requests, layers, forecast, gate.

  python3 tools/status.py <episode dir> [--media DIR] [--gate G1|G2|G3|G4] [--json]
  python3 tools/status.py --ledger L.csv [--budget budget.yaml] [--json]      # BUDGET section only

Run it at session start and before a gate instead of reading EPISODE.md, budget.yaml, ledger.csv, prompts.csv
and the media tree by hand. It writes nothing and makes no network call.

Sections: STAGE (stage, gates, BLOCKED lines), METHOD (`method:` of EPISODE.md: layers | seedance, missing =
seedance), NEXT (the `## Việc tiếp theo` lines of EPISODE.md), BUDGET (used against each cap, counted exactly like
tools/ark.py does, then ATTENTION: OPEN / CUT-502 / FAILED / MISSING requests), SHOTS (state of every layer of
every shot, clips, orphan plates), FORECAST (what the episode will still cost, from shots.csv and prompts.csv
alone: images to make, Seedance seconds planned, each against what is left under budget.yaml: `fits` or
`OVER by N`; CONFLICT lines for ai_motion shots in a `method: layers` episode), MEDIA (files in no bundle,
renders), GATE (checklist for the first undated gate, or the one named by --gate).

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

STAGES = {0: "Mở tập", 1: "Nghiên cứu nguồn", 2: "Kịch bản, shot list", 3: "Thiết kế nhân vật, bối cảnh",
          4: "Ảnh khóa", 5: "Lớp tranh", 6: "Clip AI", 7: "Dựng shot, âm thanh", 8: "Dựng cả tập",
          9: "Kiểm tra độc lập", 10: "Bản cuối", 11: "Xuất bản"}        # docs/WORKFLOW.md §2
GATE_STAGE = {"G1": 2, "G2": 4, "G3": 8, "G4": 10}                      # the stage each gate closes
GATES = list(GATE_STAGE)
NEXT_HEADING = "## Việc tiếp theo"
RE_SHOT = re.compile(r"_(s\d{2})_")
RE_VERSION = re.compile(r"_v(\d{2})\.")
RE_RENDER = re.compile(r"_(draft|final)_v(\d{2})\.mp4$")
RE_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
STATUSES = ["ok", "cut-502", "failed", "pending"]
LIST_MAX = 10          # MISSING lines shown in the text form (the JSON form has them all)
USAGE_EXIT = 2
METHODS = ("layers", "seedance")   # EPISODE.md `method:`; a missing key means seedance (episodes older than the key)
DEFAULT_METHOD = "seedance"
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
    invalid, raw: the value as written}. Only the exact words layers / seedance are a method."""
    raw = meta.get("method")
    if "method" not in meta:
        return {"name": DEFAULT_METHOD, "source": "default", "raw": None}
    if isinstance(raw, str) and raw.strip() in METHODS:
        return {"name": raw.strip(), "source": "episode", "raw": raw}
    notes.append(f"EPISODE.md: method = {raw!r} is not layers | seedance: the forecast counts the episode as "
                 f"{DEFAULT_METHOD}")
    return {"name": DEFAULT_METHOD, "source": "invalid", "raw": raw}


def method_text(m):
    if m["source"] == "default":
        return f"{m['name']} (default, no method: in EPISODE.md)"
    if m["source"] == "invalid":
        return f"invalid ({m['raw']!r}; counted as {m['name']})"
    return m["name"]


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
            att["open"].append(item)
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


def shots_section(ep_dir, media, notes):
    shots = read_table(os.path.join(ep_dir, "shots.csv"), notes, "no shot table")
    prompts = read_table(os.path.join(ep_dir, "prompts.csv"), notes, "every layer shows as no-prompt")
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
            rows = [r for r in prompts or [] if r.get("shot") == shot and r.get("layer") == code]
            layers.append(dict({"layer": code}, **layer_state(rows, plates, on_disk)))
        out.append({"shot": shot, "reuse_of": s.get("reuse_of") or None, "layers": layers,
                    "clip": (shot in clip_shots) if s.get("ai_motion") else None,
                    "from_s": s.get("from_s", ""), "to_s": s.get("to_s", "")})
    listed = {r.get("file") for r in prompts or []}
    return {"present": {"shots.csv": shots is not None, "prompts.csv": prompts is not None},
            "shots": out, "orphans": [n for n in plates if n not in listed]}


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


def forecast_section(shots, method, caps, notes):
    """What is still to pay for, from the SHOTS data alone (no network), against what is left under each cap.
    Images: one per layer code of a non-reuse shot that is neither approved, made nor lost (a lost file was paid
    for: it is pulled back from Drive, see MISSING). Video: one clip per ai_motion shot without a clip, the shot
    length rounded up to whole seconds and never under MIN_CLIP_S; a `layers` episode plans none and lists every
    ai_motion shot as a conflict. Returns None when there is no shots.csv."""
    if not shots["present"]["shots.csv"]:
        return None
    states = [l["state"] for s in shots["shots"] if not s["reuse_of"] for l in s["layers"]]
    clips, conflicts, skipped = [], [], []
    for s in shots["shots"]:
        if s["clip"] is None:                       # no ai_motion: code motion only
            continue
        if method == "layers":
            conflicts.append(f"method layers but {s['shot']} has ai_motion")
        elif s["clip"] is False:
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
            "fits": not images["over"] and not video["over"]}


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
    shots = [s for s in d["shots"]["shots"] if not s["reuse_of"]]
    n_open = len(d["attention"]["open"])
    if gate == "G1":
        need(exists("research.md", non_empty=True), "research.md non-empty")
        need(exists("script.md"), "script.md present")
        need(exists("shots.csv"), "shots.csv present")
        need(budget_state == "ok", f"budget.yaml present and loadable ({budget_state})")
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
               if l["state"] != "approved"]
        need(shots and not bad, "every layer of every non-reuse shot approved" +
             (f" (not yet: {', '.join(bad[:6])}{f', +{len(bad) - 6} more' if len(bad) > 6 else ''})" if bad
              else "" if shots else " (no shots)"))
        no_clip = [s["shot"] for s in d["shots"]["shots"] if s["clip"] is False]
        need(not no_clip, "every ai_motion shot has a clip" + (f" (none for {', '.join(no_clip)})" if no_clip else ""))
        need(d["media"]["draft"], f"draft render ({d['media']['draft'] or 'none'})")
        need(not n_open, f"no open paid request ({n_open} open)")
    else:
        need(d["media"]["final"], f"final render ({d['media']['final'] or 'none'})")
        need(not n_open, f"no open paid request ({n_open} open)")
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
                ([f"failed {by['failed']:g}"] if by["failed"] else []) + [f"pending {by['pending']:g}"]
        out.append("  " + " · ".join([head] + parts))
    out += notes_text(notes)
    att = d["attention"]
    if any(att.values()):
        out.append("  ATTENTION")
    for o in att["open"]:
        out.append(f"    OPEN     {short_id(o['req'])} {o['kind']} {os.path.basename(o['out']) or '-'} · "
                   f"agent {o['agent'] or '-'} · age {o['age']}" + ("" if o["commands"] else " (counted as spent)"))
        out += [f"             {c}" for c in o["commands"]]
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
    out.append(f"METHOD {method_text(d['method'])}")
    out += notes_text(notes["method"])
    out.append("NEXT")
    out += d["next"] or ["  (nothing under '## Việc tiếp theo')"]
    out += budget_text(d, notes["budget"])
    out.append("SHOTS")
    for s in d["shots"]["shots"]:
        cells = [f"reuse of {s['reuse_of']}"] if s["reuse_of"] else \
            [f"{l['layer']}:{l['state']}" + (f"(next v{l['next_version']:02d})" if l["state"] == "rejected" else "")
             for l in s["layers"]]
        clip = "" if s["clip"] is None else f" · clip {'yes' if s['clip'] else 'no'}"
        out.append(f"  {s['shot']}  {' '.join(cells) or '(no layers)'}{clip}")
    if d["shots"]["orphans"]:
        out.append(f"  orphans (in plates/, no prompts.csv row): {', '.join(d['shots']['orphans'])}")
    out += notes_text(notes["shots"])
    if d["forecast"]:
        out += forecast_text(d["forecast"], notes["forecast"])
    m = d["media"]
    out.append(f"MEDIA  {show(m['dir']) if m['dir'] else '-'}")
    out += [f"  {shot}: {n} file(s) only in this container" for shot, n in m["unbundled"].items()]
    out.append(f"  draft: {m['draft'] or 'none'} · final: {m['final'] or 'none'}")
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
    billed = ark.billed_requests(rows)
    return ({"budget": budget_section(budget, billed, notes),
             "attention": attention_section(rows, billed, ledger, media, bundled)}, state)


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
    notes = {"stage": [], "method": [], "budget": [], "shots": [], "forecast": [], "media": []}
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
    d["next"] = next_lines(body)
    led, budget_state = collect_ledger(ledger, a.budget or os.path.join(a.episode, "budget.yaml"), media, bundled,
                                       notes["budget"])
    d.update(led)
    d["shots"] = shots_section(a.episode, media, notes["shots"])
    d["forecast"] = forecast_section(d["shots"], d["method"]["name"], d["budget"]["caps"], notes["forecast"])
    d["media"] = media_section(media, bundled, notes["media"])
    gate = a.gate or next((g for g in GATES if not d["gates"][g]), None)
    d["gate"] = gate_section(gate, a.episode, media, d, budget_state, ledger) if gate else None
    d["notes"] = flat(notes)
    print(json.dumps(d, ensure_ascii=False, indent=1, default=str) if a.json else "\n".join(episode_text(d, notes)))
    return 1 if needs_action(d) or (a.gate and not d["gate"]["ready"]) else 0


if __name__ == "__main__":
    sys.exit(main())
