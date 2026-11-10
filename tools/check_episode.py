#!/usr/bin/env python3
"""Free schema/timing/naming checks for AI Film Lab episodes and style packs (docs/CONVENTIONS.md).

  python3 tools/check_episode.py episode projects/<project>/ep<NN>-<slug> [--media out/<project>/ep<NN>] [--probe] [--out review/check-v1.txt]
  python3 tools/check_episode.py style styles/<id>

Prints ERROR / WARN lines and a summary. Exit 1 when there is any ERROR, else 0.
Relative --out paths are taken relative to the episode directory (so `--out review/check-v1.txt`
lands in projects/<project>/ep<NN>-<slug>/review/). Without --media the `media:` path from EPISODE.md
front matter is used (relative to the repo root).

--probe measures every clip and render mp4 with ffprobe (size, fps, duration, audio) and, for
renders/ep<NN>_final_v<NN>.mp4, integrated loudness with ffmpeg ebur128 (target -14 +-1 LUFS); the
numbers go into the report, so `--probe --out review/check-<v>.txt` is what film-reviewer reads.

script.md rules: every narration line starts with a [mm:ss] mark (an optional "- " bullet before it is
allowed). Lines that are not narration: blank lines, headings (#), blockquotes (>), HTML comments,
fenced code blocks, a YAML front matter block and horizontal rules.
"""
import argparse, csv, io, json, os, re, shutil, subprocess, sys, unicodedata

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def known_motions():
    """Motion ids from tools/compose/motions.json (None if the registry is missing)."""
    try:
        with open(os.path.join(LAB, "tools", "compose", "motions.json"), encoding="utf-8") as f:
            return set(json.load(f)["motions"])
    except (OSError, ValueError, KeyError):
        return None

# --- §2 naming -----------------------------------------------------------------
RE_LAYER_FILE = re.compile(r"^ep\d{2}_s\d{2}_(L[1-4]|P\d+-[a-z0-9-]+|FX)_[a-z0-9-]+_v\d{2}\.(png|jpg)$")
RE_CLIP_FILE = re.compile(r"^ep\d{2}_s\d{2}_[a-z0-9]+_v\d{2}\.mp4$")
RE_RENDER_FILE = re.compile(r"^ep\d{2}_(draft|final)_v\d{2}\.mp4$")
# Other files under clips/ (film-compose-shot/references/seedance-layer.md):
#   clips/ep<NN>_s<NN>_start_v<NN>.png          start frame for Seedance (tools/compose/keyframe.py)
#   clips/<clip stem>/000001.png ...            keyed RGBA frames (matte.py chroma), read by a `seq` layer
#   clips/<clip stem>/raw/000001.png ...        raw frames extracted with ffmpeg before keying
RE_START_FRAME = re.compile(r"^ep\d{2}_s\d{2}_start_v\d{2}\.png$")
RE_CLIP_STEM = re.compile(r"^ep\d{2}_s\d{2}_[a-z0-9]+_v\d{2}$")
RE_FRAME = re.compile(r"^\d{6}\.png$")
RE_LAYER_CODE = re.compile(r"^(L[1-4]|P\d+-[a-z0-9-]+|FX)$")
RE_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RE_EP_DIR = re.compile(r"^ep(\d{2})-([a-z0-9]+(?:-[a-z0-9]+)*)$")
RE_SHOT = re.compile(r"^s(\d{2})$")
RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
MEDIA_RULES = {"plates": RE_LAYER_FILE, "clips": RE_CLIP_FILE, "renders": RE_RENDER_FILE}

# --- §5 / §6 schema --------------------------------------------------------------
EPISODE_KEYS = ["series", "episode", "slug", "style", "length_s", "stage", "gates", "media", "drive"]
EPISODE_SECTIONS = ["## Ghi chú người dùng (nguyên văn)", "## Đã khóa (không làm lại)", "## Việc tiếp theo", "## Nhật ký"]
GATES = ["G1", "G2", "G3", "G4"]
SHOTS_HEADER = ["shot", "from_s", "to_s", "shot_size", "camera", "action", "layers", "code_motion", "ai_motion", "sound", "reuse_of"]
PROMPTS_HEADER = ["file", "shot", "layer", "model", "size", "prompt_file", "refs", "seed", "usage", "approved", "drive_link"]
LEDGER_HEADER = ["ts", "kind", "model", "size", "seconds", "count", "status", "out", "task_id", "usage", "agent", "note"]
SHOT_SIZES = {"extreme-wide", "wide", "medium", "close", "extreme-close", "insert"}
CAMERAS = {"static", "push-in", "pull-out", "pan-left", "pan-right", "tilt-up", "tilt-down", "drift", "handheld"}
SHOT_MIN_S, SHOT_MAX_S = 3, 13
LINE_GAP_S = 3
# --probe (docs/WORKFLOW.md stages 8-10): 16:9 frames, final master at -14 LUFS integrated.
LUFS_TARGET, LUFS_TOL = -14.0, 1.0
LENGTH_TOL_S = 1.0
# A prompts.csv row is written at stage 3, before its image/clip exists. Its file must exist in media
# only once it was generated (non-empty usage), approved, or the episode is at/after this stage.
FILES_REQUIRED_FROM_STAGE = 7
APPROVED = {"yes", "no", ""}
STAGE_MAX = 11
# Stage (docs/WORKFLOW.md) from which a file must exist; before it, a missing file is only a WARN.
REQUIRED_FROM_STAGE = {"script.md": 3, "shots.csv": 3, "prompts.csv": 5}
DASHES = {"—": "em dash", "–": "en dash"}
EPS = 1e-6

# --- §3 style pack ---------------------------------------------------------------
STYLE_REQUIRED = ["id", "name", "status", "base", "style_block", "negative", "palette", "light", "matte", "layers", "models"]
STYLE_OPTIONAL = ["motion", "sound", "type"]   # may come from the cinecode recipe named in base:
STYLE_STATUS = {"stable", "draft"}
MATTE_METHODS = {"none", "luminance", "chroma", "rembg"}
STYLE_LAYER_KEY = re.compile(r"^(L[1-4]|P|P\d+-[a-z0-9-]+|FX)$")
PLACEHOLDERS = {"style_block", "subject", "constraints", "light"}


class Report:
    def __init__(self):
        self.lines, self.errors, self.warns = [], 0, 0

    def error(self, where, msg):
        self.errors += 1
        self.lines.append(f"ERROR {where}: {msg}")

    def warn(self, where, msg):
        self.warns += 1
        self.lines.append(f"WARN  {where}: {msg}")

    def info(self, msg):
        self.lines.append(f"INFO  {msg}")

    def text(self, title):
        return "\n".join([title] + self.lines + [f"Summary: {self.errors} error(s), {self.warns} warning(s)"]) + "\n"


def nfc(s):
    return unicodedata.normalize("NFC", s)


def read_text(path):
    with open(path, encoding="utf-8-sig") as f:
        return nfc(f.read())


def split_front_matter(text):
    """Return (yaml text or None, body)."""
    m = re.match(r"^---[ \t]*\n(.*?)\n---[ \t]*(?:\n|$)", text, re.S)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def read_csv(path, header, rep, name):
    """Read a CSV checking the header. Returns list of (line number, row dict) or None."""
    try:
        text = read_text(path)
        rd = csv.reader(io.StringIO(text, newline=""), strict=True)
        rows = list(rd)
    except (csv.Error, UnicodeDecodeError) as e:
        rep.error(name, f"not valid RFC 4180 UTF-8 CSV: {e}")
        return None
    if not rows:
        rep.error(name, "empty file (header required)")
        return None
    if [h.strip() for h in rows[0]] != header:
        rep.error(name, f"header is {','.join(rows[0])!r}, expected {','.join(header)!r}")
        return None
    out = []
    for n, r in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in r):
            continue
        if len(r) != len(header):
            rep.error(f"{name}:{n}", f"{len(r)} fields, expected {len(header)} (quote fields that contain commas)")
            continue
        out.append((n, {k: v.strip() for k, v in zip(header, r)}))
    return out


def to_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def fmt_s(x):
    return f"{x:g}"


# ================================================================== episode =====
def check_front_matter(ep_dir, rep):
    import yaml
    path = os.path.join(ep_dir, "EPISODE.md")
    if not os.path.isfile(path):
        rep.error("EPISODE.md", "missing (episode state file; never STATE.md)")
        return None
    if os.path.exists(os.path.join(ep_dir, "STATE.md")):
        rep.error("STATE.md", "episode state must be EPISODE.md; STATE.md belongs to cinecode")
    text = read_text(path)
    fm, body = split_front_matter(text)
    if fm is None:
        rep.error("EPISODE.md", "no YAML front matter (--- ... --- at the top)")
        return None
    try:
        meta = yaml.safe_load(fm) or {}
    except yaml.YAMLError as e:
        rep.error("EPISODE.md", f"front matter is not valid YAML: {str(e).splitlines()[0]}")
        return None
    if not isinstance(meta, dict):
        rep.error("EPISODE.md", "front matter must be a mapping")
        return None
    W = "EPISODE.md"
    for k in EPISODE_KEYS:
        if k not in meta:
            rep.error(W, f"front matter key '{k}' missing")
    for k in meta:
        if k not in EPISODE_KEYS:
            rep.warn(W, f"unknown front matter key '{k}'")

    ep_abs = os.path.abspath(ep_dir)   # abspath first: `episode .` must see the real folder name, not '.'
    folder = os.path.basename(ep_abs)
    series_folder = os.path.basename(os.path.dirname(ep_abs))
    m = RE_EP_DIR.match(folder)
    if not m:
        rep.error(W, f"episode folder '{folder}' does not match ep<NN>-<slug>")
    series = meta.get("series")
    if "series" in meta:
        if not isinstance(series, str) or not RE_SLUG.match(series):
            rep.error(W, f"series {series!r} is not an ASCII kebab-case slug")
        elif series != series_folder:
            rep.error(W, f"series '{series}' != parent folder '{series_folder}'")
    ep = meta.get("episode")
    if "episode" in meta:
        if not isinstance(ep, int) or isinstance(ep, bool) or ep < 0 or ep > 99:
            rep.error(W, f"episode {ep!r} must be an integer 0-99")
        elif m and int(m.group(1)) != ep:
            rep.error(W, f"episode {ep} != folder number ep{m.group(1)}")
    if "slug" in meta:
        slug = meta.get("slug")
        if not isinstance(slug, str) or not RE_SLUG.match(slug):
            rep.error(W, f"slug {slug!r} is not an ASCII kebab-case slug")
        elif m and slug != m.group(2):
            rep.error(W, f"slug '{slug}' != folder slug '{m.group(2)}'")
    if "style" in meta:
        st = meta.get("style")
        if not isinstance(st, str) or not RE_SLUG.match(st):
            rep.error(W, f"style {st!r} is not a style id")
        elif not os.path.isdir(os.path.join(LAB, "styles", st)):
            rep.warn(W, f"style '{st}' has no folder styles/{st}/")
    length = meta.get("length_s")
    if "length_s" in meta and (isinstance(length, bool) or not isinstance(length, (int, float)) or length <= 0):
        rep.error(W, f"length_s {length!r} must be a positive number of seconds")
        meta["length_s"] = None
    stage = meta.get("stage")
    if "stage" in meta and (isinstance(stage, bool) or not isinstance(stage, int) or not 0 <= stage <= STAGE_MAX):
        rep.error(W, f"stage {stage!r} must be an integer 0..{STAGE_MAX}")
        meta["stage"] = None
    if "gates" in meta:
        gates = meta.get("gates")
        if not isinstance(gates, dict):
            rep.error(W, "gates must be a mapping {G1: null|YYYY-MM-DD, ...}")
        else:
            for g in GATES:
                if g not in gates:
                    rep.error(W, f"gates.{g} missing")
            for g, val in gates.items():
                if g not in GATES:
                    rep.error(W, f"unknown gate '{g}' (allowed {', '.join(GATES)})")
                elif val is not None and not RE_DATE.match(str(val)):
                    rep.error(W, f"gates.{g} = {val!r}: expected null or YYYY-MM-DD")
    for k in ("media", "drive"):
        if k in meta and not isinstance(meta.get(k), str):
            rep.error(W, f"{k} must be a string path")
    if isinstance(series, str) and isinstance(ep, int) and not isinstance(ep, bool):
        exp_media = f"out/{series}/ep{ep:02d}"
        if isinstance(meta.get("media"), str) and meta["media"].rstrip("/") != exp_media:
            rep.warn(W, f"media '{meta['media']}' differs from the convention '{exp_media}'")
        slug = meta.get("slug") if isinstance(meta.get("slug"), str) else "<slug>"
        exp_drive = f"ClaudeFilmLab/<ProjectName>/03_KichBan/ep{ep:02d}-{slug}"
        drive = meta.get("drive")
        if isinstance(drive, str) and not re.fullmatch(
                rf"ClaudeFilmLab/[A-Za-z0-9]+/03_KichBan/ep{ep:02d}-{re.escape(slug)}", drive.rstrip("/")):
            rep.warn(W, f"drive '{drive}' differs from the convention '{exp_drive}' (docs/CONVENTIONS.md §11)")

    headings = {nfc(l.rstrip()) for l in body.splitlines() if l.startswith("## ")}
    for sec in EPISODE_SECTIONS:
        if sec not in headings:
            rep.error(W, f"required section '{sec}' missing")
    return meta


def missing_file(rep, meta, name):
    stage = meta.get("stage") if meta else None
    need = REQUIRED_FROM_STAGE.get(name, 0)
    if isinstance(stage, int) and stage >= need:
        rep.error(name, f"missing (required from stage {need}; episode is at stage {stage})")
    else:
        rep.warn(name, f"missing (required from stage {need})")


def check_shots(ep_dir, meta, rep):
    path = os.path.join(ep_dir, "shots.csv")
    if not os.path.isfile(path):
        missing_file(rep, meta, "shots.csv")
        return None
    rows = read_csv(path, SHOTS_HEADER, rep, "shots.csv")
    if rows is None:
        return None
    if not rows:
        rep.error("shots.csv", "no shots")
        return {}
    shots, prev, prev_num, prev_to = {}, None, None, None
    length = meta.get("length_s") if meta else None
    for n, r in rows:
        W = f"shots.csv:{n}"
        sid = r["shot"]
        m = RE_SHOT.match(sid)
        if not m:
            rep.error(W, f"shot id '{sid}' must be s<NN> (two digits)")
        else:
            num = int(m.group(1))
            if prev_num is None and num != 1:
                rep.warn(W, f"first shot is {sid}, expected s01")
            if prev_num is not None:
                if num <= prev_num:
                    rep.error(W, f"shot ids must increase: {sid} after s{prev_num:02d}")
                elif num != prev_num + 1:
                    rep.warn(W, f"gap in shot ids: {sid} after s{prev_num:02d}")
            prev_num = num if prev_num is None or num > prev_num else prev_num
        if sid in shots:
            rep.error(W, f"duplicate shot id {sid}")
        a, b = to_float(r["from_s"]), to_float(r["to_s"])
        if a is None or b is None:
            rep.error(W, f"from_s/to_s must be numbers (got {r['from_s']!r}, {r['to_s']!r})")
        else:
            if prev_to is None and abs(a) > EPS:
                rep.error(W, f"first shot must start at 0 (from_s={fmt_s(a)})")
            if prev_to is not None and abs(a - prev_to) > EPS:
                rep.error(W, f"not continuous: from_s={fmt_s(a)} but previous to_s={fmt_s(prev_to)}")
            d = b - a
            if d <= 0:
                rep.error(W, f"to_s {fmt_s(b)} must be after from_s {fmt_s(a)}")
            elif d < SHOT_MIN_S - EPS or d > SHOT_MAX_S + EPS:
                rep.error(W, f"{sid} lasts {fmt_s(d)} s (allowed {SHOT_MIN_S}-{SHOT_MAX_S} s)")
            prev_to = b
        if r["shot_size"] not in SHOT_SIZES:
            rep.error(W, f"shot_size '{r['shot_size']}' not in {', '.join(sorted(SHOT_SIZES))}")
        if r["camera"] not in CAMERAS:
            rep.error(W, f"camera '{r['camera']}' is not one move from {', '.join(sorted(CAMERAS))}")
        if prev and prev["shot_size"] == r["shot_size"] and prev["camera"] == r["camera"]:
            rep.error(W, f"{sid} repeats both shot_size '{r['shot_size']}' and camera '{r['camera']}' of {prev['shot']}")
        codes = [c.strip() for c in r["layers"].split(";") if c.strip()]
        if not codes and not r["reuse_of"]:
            rep.warn(W, f"{sid} has no layers")
        for c in codes:
            if not RE_LAYER_CODE.match(c):
                rep.error(W, f"layer code '{c}' invalid (L1-L4, P<n>-<part>, FX)")
        if len(codes) != len(set(codes)):
            rep.error(W, f"duplicate layer codes in '{r['layers']}'")
        motions = known_motions()
        if motions is not None:
            for m in (x.strip() for x in r["code_motion"].split(";")):
                if m and m not in motions:
                    rep.warn(W, f"{sid} code_motion '{m}' is not in tools/compose/motions.json")
        r["_codes"] = codes
        r["_line"] = n
        shots[sid] = r
        prev = r
    for sid, r in shots.items():
        ru = r["reuse_of"]
        if ru:
            if ru not in shots:
                rep.error(f"shots.csv:{r['_line']}", f"reuse_of '{ru}' is not a shot id in this file")
            elif ru == sid:
                rep.error(f"shots.csv:{r['_line']}", "reuse_of points to itself")
    if isinstance(length, (int, float)) and prev_to is not None and abs(prev_to - length) > EPS:
        rep.error("shots.csv", f"last shot ends at {fmt_s(prev_to)} s, length_s is {fmt_s(length)} s")
    return shots


def narration_lines(text):
    """Yield (line number, line) for narration lines of script.md."""
    lines = text.splitlines()
    i, n = 0, len(lines)
    if lines and lines[0].strip() == "---":   # optional front matter
        for j in range(1, n):
            if lines[j].strip() == "---":
                i = j + 1
                break
    fence = comment = False
    for k in range(i, n):
        raw = lines[k]
        s = raw.strip()
        if s.startswith("```") or s.startswith("~~~"):
            fence = not fence
            continue
        if fence:
            continue
        if comment:
            if "-->" in s:
                comment = False
            continue
        if s.startswith("<!--"):
            comment = "-->" not in s[4:]
            continue
        if not s or s.startswith("#") or s.startswith(">") or re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            continue
        yield k + 1, raw


RE_MARK = re.compile(r"^\s*(?:[-*]\s+)?\[(\d{2}):(\d{2})\]\s*(.*)$")


def check_script(ep_dir, meta, rep):
    path = os.path.join(ep_dir, "script.md")
    if not os.path.isfile(path):
        missing_file(rep, meta, "script.md")
        return
    text = read_text(path)
    narr = list(narration_lines(text))
    narr_nos = {n for n, _ in narr}
    for n, line in enumerate(text.splitlines(), start=1):
        for ch, name in DASHES.items():
            if ch in line and n not in narr_nos:
                rep.warn(f"script.md:{n}", f"{name} outside narration (use ',' '.' or ':')")
    if not narr:
        rep.error("script.md", "no narration lines")
        return
    prev_t, prev_n = None, None
    length = meta.get("length_s") if meta else None
    for n, line in narr:
        W = f"script.md:{n}"
        for ch, name in DASHES.items():
            if ch in line:
                rep.error(W, f"{name} in narration (TTS reads it badly; use ',' '.' or ':')")
        m = RE_MARK.match(line)
        if not m:
            rep.error(W, f"narration line without [mm:ss] mark: {line.strip()[:60]!r}")
            continue
        mm, ss, said = int(m.group(1)), int(m.group(2)), m.group(3).strip()
        if ss > 59:
            rep.error(W, f"[{m.group(1)}:{m.group(2)}] seconds must be 00-59")
        t = mm * 60 + ss
        if not said:
            rep.error(W, "mark without text")
        if prev_t is not None:
            if t <= prev_t:
                rep.error(W, f"mark [{mm:02d}:{ss:02d}] not after previous [{prev_t // 60:02d}:{prev_t % 60:02d}] (line {prev_n})")
            elif t - prev_t < LINE_GAP_S:
                rep.error(W, f"only {t - prev_t} s after the previous line (min {LINE_GAP_S} s)")
        if isinstance(length, (int, float)) and t >= length:
            rep.error(W, f"mark [{mm:02d}:{ss:02d}] = {t} s is not within length_s {fmt_s(length)} s")
        prev_t, prev_n = t, n
    if isinstance(length, (int, float)) and prev_t is not None and prev_t < length and length - prev_t < LINE_GAP_S:
        rep.warn("script.md", f"last line starts {fmt_s(length - prev_t)} s before the end (< {LINE_GAP_S} s to say it)")


def check_prompts(ep_dir, meta, shots, rep):
    path = os.path.join(ep_dir, "prompts.csv")
    if not os.path.isfile(path):
        missing_file(rep, meta, "prompts.csv")
        return None
    rows = read_csv(path, PROMPTS_HEADER, rep, "prompts.csv")
    if rows is None:
        return None
    ep = meta.get("episode") if meta else None
    files = []
    seen = set()
    for n, r in rows:
        W = f"prompts.csv:{n}"
        f = r["file"]
        files.append(r)
        if f in seen:
            rep.error(W, f"duplicate file {f}")
        seen.add(f)
        m = RE_LAYER_FILE.match(f)
        clip = RE_CLIP_FILE.match(f)
        if not m and not clip:
            rep.error(W, f"file '{f}' does not match ep<NN>_s<NN>_<layer>_<subject>_v<NN>.<png|jpg> "
                         f"(layer) or ep<NN>_s<NN>_<model>_v<NN>.mp4 (clip)")
        else:
            parts = f.split("_")
            if isinstance(ep, int) and parts[0] != f"ep{ep:02d}":
                rep.error(W, f"file '{f}' is not for episode ep{ep:02d}")
            if parts[1] != r["shot"]:
                rep.error(W, f"file '{f}' is for {parts[1]} but shot column is '{r['shot']}'")
            # A Seedance clip row names the layer it replaces/feeds (seedance-layer.md: layer = L4);
            # the clip name carries no layer code, so only the column itself is validated below.
            if m and m.group(1) != r["layer"]:
                rep.error(W, f"file '{f}' has layer {m.group(1)} but layer column is '{r['layer']}'")
        if not RE_SHOT.match(r["shot"]):
            rep.error(W, f"shot '{r['shot']}' must be s<NN>")
        elif shots is not None and r["shot"] not in shots:
            rep.error(W, f"shot '{r['shot']}' is not in shots.csv")
        elif shots and RE_LAYER_CODE.match(r["layer"]) and r["layer"] not in shots[r["shot"]]["_codes"]:
            rep.warn(W, f"layer {r['layer']} is not listed in shots.csv layers for {r['shot']}")
        if not RE_LAYER_CODE.match(r["layer"]):
            rep.error(W, f"layer '{r['layer']}' invalid")
        if r["approved"] not in APPROVED:
            rep.error(W, f"approved '{r['approved']}' must be yes, no or empty")
        if r["prompt_file"] and not os.path.isfile(os.path.join(ep_dir, r["prompt_file"])):
            rep.warn(W, f"prompt_file '{r['prompt_file']}' not found in the episode folder")
        if r["seed"] and not re.fullmatch(r"-?\d+", r["seed"]):
            rep.error(W, f"seed '{r['seed']}' must be an integer or empty")
        if r["usage"]:
            try:
                json.loads(r["usage"])
            except ValueError:
                rep.warn(W, "usage is not valid JSON (store the Ark usage object verbatim)")
    return files


def check_media_name(rel, name, sub, rx, ep, rep):
    """Name check for one file under plates/, clips/ or renders/ (rel: path inside the media folder)."""
    parts = rel.split(os.sep)[1:]            # path below plates/ | clips/ | renders/
    where = "media/" + rel.replace(os.sep, "/")
    check_ep = name
    if sub == "clips" and len(parts) > 1:
        # clips/<clip stem>/000001.png (keyed) or clips/<clip stem>/raw/000001.png (raw ffmpeg frames)
        stem, inner = parts[0], parts[1:]
        if not RE_CLIP_STEM.match(stem):
            rep.error(where, f"frame folder '{stem}' is not a clip name without .mp4 ({RE_CLIP_STEM.pattern})")
            return
        if not (len(inner) == 1 or (len(inner) == 2 and inner[0] == "raw")) or not RE_FRAME.match(name):
            rep.error(where, "frame folders hold only <6 digits>.png files and an optional raw/ subfolder "
                             f"(clips/{stem}/000001.png, clips/{stem}/raw/000001.png)")
            return
        check_ep = stem
    elif sub == "clips" and RE_START_FRAME.match(name):
        pass
    elif not rx.match(name):
        extra = f" or {RE_START_FRAME.pattern}" if sub == "clips" else ""
        rep.error(where, f"name does not match the {sub} convention ({rx.pattern}{extra})")
        return
    if isinstance(ep, int) and not check_ep.startswith(f"ep{ep:02d}_"):
        rep.error(where, f"file is not for episode ep{ep:02d}")


def check_media(media, meta, prompt_rows, rep):
    if not media or not os.path.isdir(media):
        rep.warn("media", f"media folder {media or '(none)'} not found: plates/clips/renders not checked")
        return False
    ep = meta.get("episode") if meta else None
    for sub, rx in MEDIA_RULES.items():
        d = os.path.join(media, sub)
        if not os.path.isdir(d):
            continue
        for root, dirs, names in os.walk(d):
            dirs.sort()
            for name in sorted(names):
                check_media_name(os.path.relpath(os.path.join(root, name), media), name, sub, rx, ep, rep)
    check_listed_files(media, meta, prompt_rows, rep)
    led = os.path.join(media, "ledger.csv")
    if os.path.isfile(led):
        with open(led, encoding="utf-8") as fh:
            head = fh.readline().strip()
        if head != ",".join(LEDGER_HEADER):
            rep.error("media/ledger.csv", f"header is {head!r}, expected {','.join(LEDGER_HEADER)!r}")
    return True


def check_listed_files(media, meta, prompt_rows, rep):
    """Every prompts.csv file should exist in plates/ (images) or clips/ (clips) once it was made.

    Rows are written at stage 3, before anything is generated, so a missing file is an ERROR only when
    the row says it was generated or accepted (non-empty `usage` or `approved=yes`) or the episode is at
    stage >= FILES_REQUIRED_FROM_STAGE (7, compositing: every listed file must exist by then). Otherwise
    it is a pending row: one INFO line lists them, so stage 3-6 checks (and gate G2) can pass.
    """
    stage = meta.get("stage") if meta else None
    late = isinstance(stage, int) and stage >= FILES_REQUIRED_FROM_STAGE
    pending = []
    for r in prompt_rows or []:
        f = r["file"]
        sub = "plates" if RE_LAYER_FILE.match(f) else "clips" if RE_CLIP_FILE.match(f) else None
        if sub is None or os.path.isfile(os.path.join(media, sub, f)):
            continue
        made = r["approved"] == "yes" or bool(r["usage"])
        if made or late:
            why = ("approved=yes" if r["approved"] == "yes" else "usage is filled") if made else f"episode is at stage {stage}"
            rep.error("prompts.csv", f"{f} listed but not found in {os.path.join(media, sub)} ({why})")
        else:
            pending.append(f)
    if pending:
        rep.info(f"prompts.csv: {len(pending)} file(s) not generated yet (no usage, not approved; required from "
                 f"stage {FILES_REQUIRED_FROM_STAGE}): {', '.join(pending)}")


# ==================================================================== probe =====
def ffprobe(path):
    """Return {width, height, fps, duration, audio} for a video file (raises RuntimeError)."""
    cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError((p.stderr.strip().splitlines() or ["ffprobe failed"])[-1])
    info = json.loads(p.stdout or "{}")
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if v is None:
        raise RuntimeError("no video stream")
    fps = None
    for key in ("avg_frame_rate", "r_frame_rate"):
        num, _, den = str(v.get(key, "0/0")).partition("/")
        try:
            if float(den or 1):
                fps = float(num) / float(den or 1)
                break
        except ValueError:
            pass
    dur = to_float(info.get("format", {}).get("duration")) or to_float(v.get("duration"))
    return {"width": int(v.get("width") or 0), "height": int(v.get("height") or 0), "fps": fps, "duration": dur,
            "audio": any(s.get("codec_type") == "audio" for s in streams)}


def loudness(path):
    """Integrated loudness (LUFS) and true peak (dBTP or None) with ffmpeg's ebur128 filter."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-map", "0:a:0",
           "-af", "ebur128=peak=true:framelog=quiet", "-f", "null", "-"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    summary = p.stderr[p.stderr.rfind("Summary:"):] if "Summary:" in p.stderr else ""
    m = re.search(r"\bI:\s+(-?[\d.]+|-inf)\s+LUFS", summary)
    if p.returncode != 0 or not m:
        raise RuntimeError((p.stderr.strip().splitlines() or ["ffmpeg ebur128 failed"])[-1])
    pk = re.search(r"Peak:\s+(-?[\d.]+|-inf)\s+dBFS", summary)
    return float(m.group(1)), (float(pk.group(1)) if pk else None)


def is_16_9(w, h):
    return w > 0 and h > 0 and abs(w / h - 16 / 9) <= 0.01


def probe_media(media, meta, rep):
    """--probe: ffprobe numbers for clips/*.mp4 and renders/*.mp4, loudness for final renders."""
    if not (shutil.which("ffprobe") and shutil.which("ffmpeg")):
        rep.error("probe", "ffprobe/ffmpeg not found on PATH: clips and renders not measured")
        return
    length = meta.get("length_s") if meta else None
    found = 0
    for sub in ("clips", "renders"):
        d = os.path.join(media, sub)
        names = sorted(n for n in os.listdir(d) if n.endswith(".mp4")) if os.path.isdir(d) else []
        for name in names:
            found += 1
            where = f"media/{sub}/{name}"
            final = sub == "renders" and "_final_" in name
            try:
                pr = ffprobe(os.path.join(d, name))
            except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as e:
                rep.error(where, f"ffprobe failed: {e}")
                continue
            w, h = pr["width"], pr["height"]
            ratio = "16:9" if is_16_9(w, h) else f"{w / h:.3f}:1" if h else "?"
            fps = f"{pr['fps']:.3g} fps" if pr["fps"] else "fps ?"
            dur = f"{pr['duration']:.2f} s" if pr["duration"] is not None else "duration ?"
            diff = None
            if sub == "renders" and isinstance(length, (int, float)) and pr["duration"] is not None:
                diff = pr["duration"] - length
                dur += f" (length_s {fmt_s(length)} s, {diff:+.2f} s)"
            msg = f"probe {where}: {w}x{h} ({ratio}), {fps}, {dur}, audio {'yes' if pr['audio'] else 'no'}"
            if final and pr["audio"]:
                try:
                    lufs, peak = loudness(os.path.join(d, name))
                    msg += f", integrated {lufs:.1f} LUFS" + (f", true peak {peak:.1f} dBTP" if peak is not None else "")
                except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as e:
                    lufs = None
                    rep.error(where, f"loudness not measured: {e}")
            rep.info(msg)
            if not is_16_9(w, h):
                (rep.error if final else rep.warn)(where, f"{w}x{h} is not 16:9")
            if final:
                if not pr["audio"]:
                    rep.error(where, f"final render has no audio stream (master must be {LUFS_TARGET:g} LUFS)")
                elif lufs is not None and abs(lufs - LUFS_TARGET) > LUFS_TOL:
                    rep.error(where, f"integrated loudness {lufs:.1f} LUFS outside {LUFS_TARGET:g} +-{LUFS_TOL:g} LUFS")
            if diff is not None and abs(diff) > LENGTH_TOL_S:
                rep.warn(where, f"duration {pr['duration']:.2f} s differs from length_s {fmt_s(length)} s "
                                f"by {diff:+.2f} s (> {LENGTH_TOL_S:g} s)")
    if not found:
        rep.info(f"probe: no mp4 in {os.path.join(media, 'clips')} or {os.path.join(media, 'renders')}")


def cmd_episode(a):
    rep = Report()
    ep_dir = a.episode
    if not os.path.isdir(ep_dir):
        print(f"ERROR {ep_dir}: not a directory")
        return 1
    meta = check_front_matter(ep_dir, rep) or {}
    shots = check_shots(ep_dir, meta, rep)
    check_script(ep_dir, meta, rep)
    files = check_prompts(ep_dir, meta, shots, rep)
    media = a.media
    if media is None and isinstance(meta.get("media"), str):
        media = meta["media"] if os.path.isabs(meta["media"]) else os.path.join(LAB, meta["media"])
    if check_media(media, meta, files, rep) and a.probe:
        probe_media(media, meta, rep)
    if shots:
        total = max(to_float(r["to_s"]) or 0 for r in shots.values())
        rep.info(f"{len(shots)} shot(s), {fmt_s(total)} s; media: {media or '-'}")
    out = rep.text(f"check_episode episode {os.path.normpath(ep_dir)}")
    sys.stdout.write(out)
    if a.out:
        dest = a.out if os.path.isabs(a.out) else os.path.join(ep_dir, a.out)
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"written {dest}")
    return 1 if rep.errors else 0


# ==================================================================== style =====
def check_style(style_dir, rep):
    import yaml
    sid = os.path.basename(os.path.normpath(style_dir))
    path = os.path.join(style_dir, "style.yaml")
    if not os.path.isfile(path):
        rep.error("style.yaml", "missing")
        return
    try:
        y = yaml.safe_load(read_text(path)) or {}
    except yaml.YAMLError as e:
        rep.error("style.yaml", f"not valid YAML: {str(e).splitlines()[0]}")
        return
    if not isinstance(y, dict):
        rep.error("style.yaml", "must be a mapping")
        return
    W = "style.yaml"
    for k in STYLE_REQUIRED:
        if k not in y:
            rep.error(W, f"required key '{k}' missing")
    for k in STYLE_OPTIONAL:
        if k not in y:
            rep.warn(W, f"optional key '{k}' missing (inherited from base recipe?)")
    for k in y:
        if k not in STYLE_REQUIRED and k not in STYLE_OPTIONAL:
            rep.warn(W, f"unknown key '{k}'")
    if "id" in y:
        if y["id"] != sid:
            rep.error(W, f"id '{y['id']}' != folder name '{sid}'")
        if not isinstance(y["id"], str) or not RE_SLUG.match(y["id"]):
            if sid.startswith("_") and y["id"] == sid:   # styles/_template: renamed when copied
                rep.warn(W, f"id '{sid}' is a template id; set id = new folder name after copying")
            else:
                rep.error(W, f"id {y['id']!r} must be kebab-case ASCII")
    if "status" in y and y["status"] not in STYLE_STATUS:
        rep.error(W, f"status {y['status']!r} must be stable or draft")
    if "base" in y and y["base"] is not None and not isinstance(y["base"], str):
        rep.error(W, "base must be a recipe name (e.g. cinecode:ink-wash) or null")
    for k in ("name", "style_block", "light"):
        if k in y and (not isinstance(y[k], str) or not y[k].strip()):
            rep.error(W, f"{k} must be a non-empty string")
    if "negative" in y and (not isinstance(y["negative"], list) or not all(isinstance(x, str) for x in y["negative"])):
        rep.error(W, "negative must be a list of strings")
    if "palette" in y:
        pal = y["palette"]
        if not isinstance(pal, dict) or not pal:
            rep.error(W, "palette must be a non-empty mapping name -> \"#RRGGBB\"")
        else:
            for name, hx in pal.items():
                if not isinstance(hx, str) or not RE_HEX.match(hx):
                    rep.error(W, f"palette.{name} = {hx!r} is not #RRGGBB")
    if "matte" in y:
        check_matte(y["matte"], rep)
    if "layers" in y:
        lay = y["layers"]
        if not isinstance(lay, dict) or not lay:
            rep.error(W, "layers must be a mapping layer -> {size, ...}")
        else:
            for code, spec in lay.items():
                if not STYLE_LAYER_KEY.match(str(code)):
                    rep.error(W, f"layers.{code}: invalid layer code (L1-L4, P, FX)")
                if not isinstance(spec, dict) or "size" not in spec:
                    rep.error(W, f"layers.{code}: needs at least size")
    if "models" in y:
        mo = y["models"]
        if not isinstance(mo, dict) or not all(isinstance(v, str) and v for v in mo.values()):
            rep.error(W, "models must map role -> model id string")
        elif "image" not in mo:
            rep.error(W, "models.image missing")
    if "motion" in y and not isinstance(y["motion"], list):
        rep.error(W, "motion must be a list of module ids")
    elif "motion" in y and known_motions() is not None:
        for m in y["motion"]:
            if m not in known_motions():
                rep.warn(W, f"motion id '{m}' is not in tools/compose/motions.json")
    check_style_prompts(style_dir, rep)
    if not os.path.isfile(os.path.join(style_dir, "STYLE.md")):
        rep.warn("STYLE.md", "missing")


def check_matte(matte, rep):
    W = "style.yaml"
    if not isinstance(matte, dict):
        rep.error(W, "matte must be a mapping {key_bg, paper_bg, per_layer}")
        return
    for k in ("key_bg", "paper_bg"):
        if k in matte and (not isinstance(matte[k], str) or not RE_HEX.match(matte[k])):
            rep.error(W, f"matte.{k} = {matte[k]!r} is not #RRGGBB")
    pl = matte.get("per_layer")
    if not isinstance(pl, dict) or not pl:
        rep.error(W, "matte.per_layer must be a mapping layer -> {method, low, high}")
        return
    methods = set()
    for code, spec in pl.items():
        where = f"matte.per_layer.{code}"
        if not STYLE_LAYER_KEY.match(str(code)):
            rep.error(W, f"{where}: invalid layer code (L1-L4, P, FX)")
        if not isinstance(spec, dict):
            rep.error(W, f"{where} must be a mapping")
            continue
        m = spec.get("method")
        if m not in MATTE_METHODS:
            rep.error(W, f"{where}.method {m!r} not in {'|'.join(sorted(MATTE_METHODS))}")
        methods.add(m)
        lo, hi = spec.get("low"), spec.get("high")
        for k, val in (("low", lo), ("high", hi)):
            if val is not None and (isinstance(val, bool) or not isinstance(val, int) or not 0 <= val <= 255):
                rep.error(W, f"{where}.{k} = {val!r} must be an integer 0-255")
        if isinstance(lo, int) and isinstance(hi, int) and not isinstance(lo, bool) and lo >= hi:
            rep.error(W, f"{where}: low {lo} must be < high {hi}")
        bg = spec.get("bg")
        if bg is not None and not (isinstance(bg, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", bg)):
            rep.error(W, f"{where}.bg = {bg!r} must be a #RRGGBB colour")
        for k in spec:
            if k not in ("method", "low", "high", "bg"):
                rep.warn(W, f"{where}: unknown key '{k}'")
    if "chroma" in methods and "key_bg" not in matte:
        rep.error(W, "matte.key_bg required when a layer uses method chroma")
    if "luminance" in methods and "paper_bg" not in matte:
        rep.error(W, "matte.paper_bg required when a layer uses method luminance")


def check_style_prompts(style_dir, rep):
    d = os.path.join(style_dir, "prompts")
    txt = sorted(f for f in os.listdir(d) if f.endswith(".txt")) if os.path.isdir(d) else []
    if not txt:
        rep.error("prompts/", "no prompt templates (prompts/*.txt)")
        return
    for f in txt:
        text = read_text(os.path.join(d, f))
        if not text.strip():
            rep.error(f"prompts/{f}", "empty")
        for ph in re.findall(r"\{([^{}\n]*)\}", text):
            if ph not in PLACEHOLDERS:
                rep.error(f"prompts/{f}", f"placeholder {{{ph}}} not allowed (only {', '.join('{%s}' % p for p in sorted(PLACEHOLDERS))})")
        if "{style_block}" not in text:
            rep.warn(f"prompts/{f}", "does not use {style_block} (it should open every image prompt)")


def cmd_style(a):
    rep = Report()
    if not os.path.isdir(a.style):
        print(f"ERROR {a.style}: not a directory")
        return 1
    check_style(a.style, rep)
    sys.stdout.write(rep.text(f"check_episode style {os.path.normpath(a.style)}"))
    return 1 if rep.errors else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    sp = p.add_subparsers(dest="cmd", required=True)
    e = sp.add_parser("episode", help="check an episode folder projects/<project>/ep<NN>-<slug>")
    e.add_argument("episode")
    e.add_argument("--media", default=None, help="media folder out/<project>/ep<NN> (default: EPISODE.md media:)")
    e.add_argument("--probe", action="store_true",
                   help="measure clips/renders with ffprobe and final renders' loudness with ffmpeg ebur128")
    e.add_argument("--out", default=None, help="also write the report here (relative = inside the episode folder)")
    s = sp.add_parser("style", help="check a style pack styles/<id>")
    s.add_argument("style")
    a = p.parse_args(argv)
    return cmd_episode(a) if a.cmd == "episode" else cmd_style(a)


if __name__ == "__main__":
    sys.exit(main())
