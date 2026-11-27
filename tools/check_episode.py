#!/usr/bin/env python3
"""Free schema/timing/naming checks for AI Film Lab episodes and style packs (docs/CONVENTIONS.md).

  python3 tools/check_episode.py episode projects/<project>/<episode folder> [--media out/<project>/<id>] [--probe] [--out review/check-v1.txt]
  python3 tools/check_episode.py style styles/<id>

Episode ids (§2, tools/episode_id.py): `ep<NN>` (folder ep<NN>-<slug>, media out/<project>/ep<NN>/, files ep<NN>_...)
or, for a project split into books, `q<NN>t<NN>` (folder q<NN>-t<NN>-<slug>, media out/<project>/q<NN>t<NN>/,
files q<NN>t<NN>_..., EPISODE.md `book:`). The folder, `book`/`episode`, media folder and every file prefix must agree.

Prints ERROR / WARN lines and a summary. Exit 1 when there is any ERROR, else 0.
Relative --out paths are taken relative to the episode directory (so `--out review/check-v1.txt`
lands in projects/<project>/<episode folder>/review/). Without --media the `media:` path from EPISODE.md
front matter is used (relative to the repo root).

--probe measures every clip and render mp4 with ffprobe (size, fps, duration, audio) and, for
renders/<id>_final_v<NN>.mp4, integrated loudness with ffmpeg ebur128 (target -14 +-1 LUFS); the
numbers go into the report, so `--probe --out review/check-v<N>.txt` is what film-reviewer reads.

script.md rules: every narration line starts with a [mm:ss] mark (an optional "- " bullet before it is
allowed). Lines that are not narration: blank lines, headings (#), blockquotes (>), HTML comments,
fenced code blocks, a YAML front matter block and horizontal rules.

Also checked: budget.yaml (the four keys of docs/CONVENTIONS.md §7, both totals required), `stage` against
the gate dates, and with --probe only the newest draft and the newest final render (older versions get one
INFO line). A file that cannot be read gives an ERROR line; the report is written even then.

Shot ids are s<NN> or s<NNN> (one width per episode); layer codes include pose plates L4b..L4z; method code
layers are C-/M-<slug>, E-<slug>, FX[-<name>], T; method blender layers are A-<asset>, E-<slug>, FX[-<name>], T, its
cameras the shot3d moves (static, push-in, pull-out, pan, tilt, orbit, dolly, crane, track), and <episode>/shots3d/s<NN>.json
is validated with tools/blender/spec.py when that module exists (a WARN when it does not). code_motion ids come from tools/compose/motions.json (entries
with engine: toon are method code actions; their project.js moves are camera values there too). Coverage:
two approved images (or clips) of one shot layer = ERROR; files in plates/ without a prompts.csv row = WARN;
from stage 8 (G3) a seedance shot with ai_motion and no clip in clips/ = ERROR. A key given twice in the
EPISODE.md front matter or in budget.yaml = ERROR.

method blender/code (WARN only): a main creature of `## Sinh vật của tập` without a close-up or an extreme-wide shot
in shots.csv (its model A-<slug> / C-<slug> / M-<slug> in the layers); STYLE-FRAMES.md (stage 3b) with 5-8 frames and
its `## Khung chuẩn đã duyệt` table (one atmosphere frame, one per main creature) from stage 3.
"""
import argparse, csv, datetime, io, json, math, os, re, shutil, subprocess, sys, unicodedata

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(LAB, "tools"))
import episode_id as eid_mod  # noqa: E402


def motion_registry():
    """{motion id: entry} from tools/compose/motions.json, the one source of truth for code_motion ids (compose kit
    calls and, with `engine: toon`, method: code actions and camera moves); None if the registry is missing."""
    try:
        with open(os.path.join(LAB, "tools", "compose", "motions.json"), encoding="utf-8") as f:
            reg = json.load(f)["motions"]
        return {k: (v if isinstance(v, dict) else {}) for k, v in reg.items()}
    except (OSError, ValueError, KeyError, AttributeError):
        return None


def known_motions():
    """Motion ids from tools/compose/motions.json (None if the registry is missing)."""
    reg = motion_registry()
    return None if reg is None else set(reg)


def is_toon_motion(entry):
    return entry.get("engine") == "toon"


def is_toon_camera(entry):
    """A toon camera move (tools/toon/project.js): also a valid `camera` value in a method: code episode."""
    return is_toon_motion(entry) and str(entry.get("module", "")).endswith("project.js")


def needs_plate(entry):
    """A compose motion that rigs a painted plate (PLATES.<id>.rig...): nothing to rig in a method: code episode."""
    return str(entry.get("call", "")).startswith("PLATES.")

# --- §2 naming -----------------------------------------------------------------
# <id> = ep<NN> or q<NN>t<NN>, <shot> = s<NN> or s<NNN>, layer codes incl. pose plates L4b.. (tools/episode_id.py)
ID = eid_mod.ID
SHOT = eid_mod.SHOT
RE_LAYER_FILE = re.compile(rf"^{ID}_{SHOT}_({eid_mod.LAYER})_[a-z0-9-]+_v\d{{2}}\.(png|jpg)$")   # group 1 = layer
RE_CLIP_FILE = re.compile(rf"^{ID}_{SHOT}_[a-z0-9]+_v\d{{2}}\.mp4$")
RE_RENDER_FILE = re.compile(rf"^{ID}_(draft|final)_v\d{{2}}\.mp4$")
# Other files under clips/ (film-compose-shot/references/seedance-layer.md):
#   clips/<id>_s<NN>_start_v<NN>.png            start frame for Seedance (tools/compose/keyframe.py)
#   clips/<clip stem>/000001.png ...            keyed RGBA frames (tools/layers/matte_seq.py), read by a `seq` layer
#   clips/<clip stem>/raw/000001.png ...        raw frames extracted with ffmpeg before keying
RE_START_FRAME = re.compile(rf"^{ID}_{SHOT}_start_v\d{{2}}\.png$")
RE_CLIP_STEM = re.compile(rf"^{ID}_{SHOT}_[a-z0-9]+_v\d{{2}}$")
#   clips/<clip>.mp4.json or clips/<clip stem>.json  sidecar of a local clip (tools/comfy/comfy.py run: seed, workflow, models)
RE_CLIP_SIDECAR = re.compile(rf"^{ID}_{SHOT}_[a-z0-9]+_v\d{{2}}(?:\.mp4)?\.json$")
RE_FRAME = re.compile(r"^\d{6}\.png$")
RE_LAYER_CODE = eid_mod.RE_LAYER
# method: code (drawn in code, tools/toon/, code-method.md §4): C-<character> or M-<model>, E-<setting>,
# FX or FX-<effect>, T (on-screen text)
RE_CODE_LAYER = re.compile(r"^([CM]-[a-z0-9-]+|E-[a-z0-9-]+|FX(-[a-z0-9-]+)?|T)$")
# method: blender (3D renders, blender-method.md): A-<asset> (3D model: GLB or preset), E-<setting>, FX[-<effect>], T
RE_BLENDER_LAYER = re.compile(rf"^(A-{eid_mod.ASSET}|E-[a-z0-9-]+|FX(-[a-z0-9-]+)?|T)$")   # asset id: spec.py ID_RE
# <episode>/shots3d/s<NN>.json: one shot3d.json per shot (tools/blender/README.md)
RE_SHOT3D_FILE = re.compile(r"^(s(?:\d{2}|\d{3}))\.json$")
# out/<project>/<id>/renders3d/<folder>/ (one definition in tools/episode_id.py, shared with tools/bundle.py)
RE_RENDER3D_DIR = eid_mod.RE_RENDER3D_DIR
RE_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RE_EP_DIR = eid_mod.RE_DIR
RE_SHOT = eid_mod.RE_SHOT
RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
MEDIA_RULES = {"plates": RE_LAYER_FILE, "clips": RE_CLIP_FILE, "renders": RE_RENDER_FILE}

# --- §5 / §6 schema --------------------------------------------------------------
EPISODE_KEYS = ["series", "episode", "slug", "style", "length_s", "stage", "gates", "media", "drive"]
EPISODE_OPTIONAL = ["book", "method", "video_engine"]   # book set = project split into books: id q<book>t<episode>
# layers: image models + code motion; seedance: clips; code: no AI, all drawn in code; blender: 3D renders (local, free)
METHODS = ("layers", "seedance", "code", "blender")
# video_engine (stage 6, docs/WORKFLOW.md): seedance = paid Ark clips (tools/ark.py video, the default); comfy = local
# MiniMax H3 clips (tools/comfy/comfy.py run, free, owner's PC only). Allowed with method seedance and blender only.
VIDEO_ENGINES = ("seedance", "comfy")
VIDEO_ENGINE_METHODS = ("seedance", "blender")
EPISODE_SECTIONS = ["## Ghi chú người dùng (nguyên văn)", "## Đã khóa (không làm lại)", "## Việc tiếp theo", "## Nhật ký"]
GATES = ["G1", "G2", "G3", "G4"]
SHOTS_HEADER = ["shot", "from_s", "to_s", "shot_size", "camera", "action", "layers", "code_motion", "ai_motion", "sound", "reuse_of"]
PROMPTS_HEADER = ["file", "shot", "layer", "model", "size", "prompt_file", "refs", "seed", "usage", "approved", "drive_link"]
LEDGER_HEADER = ["ts", "kind", "model", "size", "seconds", "count", "status", "out", "task_id", "usage", "agent", "note"]
SHOT_SIZES = {"extreme-wide", "wide", "medium", "close", "extreme-close", "insert"}
CAMERAS = {"static", "push-in", "pull-out", "pan-left", "pan-right", "tilt-up", "tilt-down", "drift", "handheld"}
CAMERAS_CODE = CAMERAS | {"orbit", "dolly", "crane", "track"}   # a 3D camera moves in method: code (tools/toon/project.js)
# method: blender: exactly the camera.move names of shot3d.json (tools/blender/spec.py, same meanings as tools/toon/project.js)
CAMERAS_BLENDER = {"static", "push-in", "pull-out", "pan", "tilt", "orbit", "dolly", "crane", "track"}
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
# engine: code (a style drawn by tools/toon/, no image model): no prompt, matte, layers or models keys
STYLE_REQUIRED_CODE = ["id", "name", "status", "base", "engine", "render", "palette"]
STYLE_OPTIONAL_CODE = STYLE_OPTIONAL + ["name_en"]
# engine: blender (a style rendered by Blender, tools/blender/; method: blender): render = {look, palette, line, mist, engine}
STYLE_REQUIRED_BLENDER = STYLE_REQUIRED_CODE
STYLE_EXTRA = ["grade"]   # any engine, never required: two-layer grade of tools/compose/grade.py
STYLE_ENGINES = {"image", "code", "blender"}
BLENDER_RENDER_KEYS = {"look", "palette", "line", "mist", "engine"}
BLENDER_RENDER_ENGINES = {"eevee", "cycles"}
BLENDER_LOOKS = ("grey-layout", "clay", "toon-ink", "ink-wash", "realistic")   # spec §4.3; tools/blender/looks.json wins when present
RENDER_ENGINES = {"canvas2d", "three"}
RENDER_KEYS = {"engine", "look", "post", "hold", "palette", "opts", "camera", "env", "seed"}
STYLE_STATUS = {"stable", "draft"}
MATTE_METHODS = {"none", "luminance", "chroma", "rembg"}
STYLE_LAYER_KEY = re.compile(rf"^(P|{eid_mod.LAYER})$")
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


class CheckError(Exception):
    """A file that cannot be read as text. `msg` is the text for the report, str() also names the file."""

    def __init__(self, path, msg):
        super().__init__(f"{path}: {msg}")
        self.path, self.msg = path, msg


def read_text(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return nfc(f.read())
    except UnicodeDecodeError as e:
        raise CheckError(path, f"not valid UTF-8 (byte {e.start}); save the file as UTF-8") from None


def yaml_load_dups(text):
    """yaml.safe_load(text) plus the keys given twice in one mapping: (data, [(key, line), ...]).

    PyYAML keeps the last value of a repeated key without a word, so `method: layers` followed later by
    `method: seedance` would silently change the episode's method. Merge keys (<<) are not counted."""
    import yaml
    dups = []

    class Loader(yaml.SafeLoader):
        pass

    def mapping(loader, node):
        seen = set()
        for kn, _vn in node.value:
            if kn.tag == "tag:yaml.org,2002:merge":
                continue
            k = loader.construct_object(kn, deep=True)
            try:
                if k in seen:
                    dups.append((k, kn.start_mark.line + 1))
                seen.add(k)
            except TypeError:                    # an unhashable key: construct_mapping reports it
                pass
        return yaml.SafeLoader.construct_mapping(loader, node, deep=True)

    Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    return yaml.load(text, Loader=Loader), dups


def report_dups(rep, where, dups, line_offset=0, what="key"):
    for k, line in dups:
        rep.error(where, f"{what} '{k}' given twice (line {line + line_offset}): YAML silently keeps the last value; "
                         f"keep one")


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
    except (csv.Error, CheckError) as e:
        rep.error(name, f"not valid RFC 4180 UTF-8 CSV: {getattr(e, 'msg', e)}")
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
    """A finite number or None ('nan' and 'inf' are not timings: every comparison with them is false)."""
    try:
        x = float(s)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def fmt_s(x):
    return f"{x:g}"


# ================================================================== episode =====
def episode_method(front_matter):
    """(method, explicit) from the EPISODE.md front matter: a missing key means ('seedance', False), so episodes
    written before the key keep their meaning; a value that is neither layers nor seedance gives (None, True)."""
    if not isinstance(front_matter, dict) or "method" not in front_matter:
        return "seedance", False
    v = front_matter["method"]
    v = v.strip().lower() if isinstance(v, str) else None
    return (v if v in METHODS else None), True


def video_engine(front_matter):
    """(engine, explicit) from the EPISODE.md front matter: a missing key means ('seedance', False); a value that is
    neither seedance nor comfy gives (None, True). Only meaningful for method seedance and blender."""
    if not isinstance(front_matter, dict) or "video_engine" not in front_matter:
        return "seedance", False
    v = front_matter["video_engine"]
    v = v.strip().lower() if isinstance(v, str) else None
    return (v if v in VIDEO_ENGINES else None), True


def remote_session():
    """True in a Claude Code cloud session (the session hook's CLAUDE_CODE_REMOTE): no GPU, no Blender, no ComfyUI."""
    return os.environ.get("CLAUDE_CODE_REMOTE", "").strip().lower() == "true"


def check_front_matter(ep_dir, rep):
    import yaml
    path = os.path.join(ep_dir, "EPISODE.md")
    if not os.path.isfile(path):
        rep.error("EPISODE.md", "missing (episode state file; never STATE.md)")
        return None
    if os.path.exists(os.path.join(ep_dir, "STATE.md")):
        rep.error("STATE.md", "episode state must be EPISODE.md; STATE.md belongs to cinecode")
    try:
        text = read_text(path)
    except CheckError as e:
        rep.error("EPISODE.md", e.msg)
        return None
    fm, body = split_front_matter(text)
    if fm is None:
        rep.error("EPISODE.md", "no YAML front matter (--- ... --- at the top)")
        return None
    try:
        meta, dups = yaml_load_dups(fm)
        meta = meta or {}
    except (yaml.YAMLError, ValueError) as e:   # ValueError: an impossible date such as 2026-11-31
        rep.error("EPISODE.md", f"front matter is not valid YAML: {str(e).splitlines()[0]}")
        return None
    if not isinstance(meta, dict):
        rep.error("EPISODE.md", "front matter must be a mapping")
        return None
    W = "EPISODE.md"
    report_dups(rep, W, dups, line_offset=1, what="front matter key")   # +1: the opening '---' line
    for k in EPISODE_KEYS:
        if k not in meta:
            rep.error(W, f"front matter key '{k}' missing")
    for k in meta:
        if k not in EPISODE_KEYS and k not in EPISODE_OPTIONAL:
            rep.warn(W, f"unknown front matter key '{k}'")
    method, explicit = episode_method(meta)
    if method is None:
        rep.error(W, f"method must be layers, seedance, code or blender (got {meta['method']!r})")
    elif not explicit:
        rep.warn(W, "EPISODE.md has no method: (treated as seedance); add method: layers, seedance, code or blender")
    engine, engine_set = video_engine(meta)
    if engine is None:
        rep.error(W, f"video_engine must be seedance or comfy (got {meta['video_engine']!r})")
    elif engine_set and method in ("layers", "code"):
        rep.error(W, f"video_engine is for method seedance or blender; a method {method} episode makes no clip "
                     f"(remove video_engine: {meta['video_engine']})")
    if remote_session() and method is not None:
        if method == "blender":
            rep.warn(W, "method blender renders with Blender on the owner's PC: this cloud session cannot run stages "
                        "4-6 (tools/blender/blender.py), only text work and checks")
        if engine == "comfy" and method in VIDEO_ENGINE_METHODS:
            rep.warn(W, "video_engine comfy makes clips with ComfyUI on the owner's PC: this cloud session cannot run "
                        "stage 6 (tools/comfy/comfy.py)")

    ep_abs = os.path.abspath(ep_dir)   # abspath first: `episode .` must see the real folder name, not '.'
    folder = os.path.basename(ep_abs)
    series_folder = os.path.basename(os.path.dirname(ep_abs))
    parsed = eid_mod.parse_dir(folder)
    if not parsed:
        rep.error(W, f"episode folder '{folder}' does not match ep<NN>-<slug> or q<NN>-t<NN>-<slug>")
    dir_id, dir_slug = parsed or (None, None)
    dir_book, dir_ep = eid_mod.parse_id(dir_id) if dir_id else (None, None)
    series = meta.get("series")
    if "series" in meta:
        if not isinstance(series, str) or not RE_SLUG.match(series):
            rep.error(W, f"series {series!r} is not an ASCII kebab-case slug")
        elif series != series_folder:
            rep.error(W, f"series '{series}' != parent folder '{series_folder}'")
    ep = meta.get("episode")
    ep_ok = isinstance(ep, int) and not isinstance(ep, bool) and 0 <= ep <= 99
    if "episode" in meta and not ep_ok:
        rep.error(W, f"episode {ep!r} must be an integer 0-99")
    book = meta.get("book")
    book_ok = "book" in meta and isinstance(book, int) and not isinstance(book, bool) and 0 <= book <= 99
    book_bad = book is not None and not book_ok
    if book_bad:
        rep.error(W, f"book {book!r} must be an integer 0-99 (or absent for ep<NN> numbering)")
    book = book if book_ok else None
    meta["_id"] = None
    if ep_ok and not book_bad:
        meta["_id"] = eid_mod.make_id(ep, book)
        if dir_id and meta["_id"] != dir_id:
            want = f"book {book}, episode {ep}" if book is not None else f"episode {ep}"
            got = f"q{dir_book:02d}-t{dir_ep:02d}" if dir_book is not None else f"ep{dir_ep:02d}"
            hint = (" (folder uses books: set 'book:')" if dir_book is not None and book is None else
                    " (folder has no book: rename it q<NN>-t<NN>-<slug> or drop 'book:')"
                    if dir_book is None and book is not None else "")
            rep.error(W, f"{want} != folder number {got}{hint}")
    if "slug" in meta:
        slug = meta.get("slug")
        if not isinstance(slug, str) or not RE_SLUG.match(slug):
            rep.error(W, f"slug {slug!r} is not an ASCII kebab-case slug")
        elif dir_slug and slug != dir_slug:
            rep.error(W, f"slug '{slug}' != folder slug '{dir_slug}'")
    if "style" in meta:
        st = meta.get("style")
        if not isinstance(st, str) or not RE_SLUG.match(st):
            rep.error(W, f"style {st!r} is not a style id")
        elif not os.path.isdir(os.path.join(LAB, "styles", st)):
            rep.warn(W, f"style '{st}' has no folder styles/{st}/")
        elif method is not None:                 # the style's engine must suit the method
            eng = style_engine(os.path.join(LAB, "styles", st))
            if method == "code" and eng not in (None, "code"):
                rep.error(W, f"method code needs an engine: code style pack; styles/{st} is engine: {eng}")
            elif method == "blender" and eng not in (None, "blender"):
                rep.error(W, f"method blender needs an engine: blender style pack; styles/{st} is engine: {eng}")
            elif method != "code" and eng == "code":
                rep.error(W, f"styles/{st} is engine: code (drawn by tools/toon/); set method: code or pick an image style")
            elif method != "blender" and eng == "blender":
                rep.error(W, f"styles/{st} is engine: blender (rendered by tools/blender/); set method: blender or pick "
                             f"an image style")
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
    if isinstance(series, str) and meta["_id"]:
        eid = meta["_id"]
        exp_media = f"out/{series}/{eid}"
        if isinstance(meta.get("media"), str) and meta["media"].rstrip("/") != exp_media:
            rep.warn(W, f"media '{meta['media']}' differs from the convention '{exp_media}'")
        slug = meta.get("slug") if isinstance(meta.get("slug"), str) else "<slug>"
        exp_drive = f"ClaudeFilmLab/<ProjectName>/03_KichBan/{eid_mod.dir_name(eid, slug)}"
        drive = meta.get("drive")
        if isinstance(drive, str) and not re.fullmatch(
                rf"ClaudeFilmLab/[A-Za-z0-9]+/03_KichBan/{re.escape(eid_mod.dir_name(eid, slug))}", drive.rstrip("/")):
            rep.warn(W, f"drive '{drive}' differs from the convention '{exp_drive}' (docs/CONVENTIONS.md §11)")

    headings = {nfc(l.rstrip()) for l in body.splitlines() if l.startswith("## ")}
    for sec in EPISODE_SECTIONS:
        if sec not in headings:
            rep.error(W, f"required section '{sec}' missing")
    return meta


# Stage at which each gate is presented (docs/WORKFLOW.md §2); past it the gate must carry a date.
GATE_STAGE = {"G1": 2, "G2": 4, "G3": 8, "G4": 10}


def check_stage_gates(meta, rep):
    """`stage` must not be ahead of an unpassed gate; gate dates are filled in order and do not decrease."""
    W = "EPISODE.md"
    stage, gates = meta.get("stage"), meta.get("gates")
    if isinstance(stage, bool) or not isinstance(stage, int) or not isinstance(gates, dict):
        return                                   # check_front_matter already reported it
    dates = {}
    for g in GATES:
        val = gates.get(g, "")
        if val is None:
            dates[g] = None
        elif not RE_DATE.match(str(val)):
            return                               # missing or malformed: reported by check_front_matter
        else:
            try:
                dates[g] = datetime.date.fromisoformat(str(val))
            except ValueError:
                rep.error(W, f"gates.{g} = {val!r} is not a calendar date")
                return
    behind = set()
    for g in GATES:
        if dates[g] is None and stage > GATE_STAGE[g]:
            behind.add(g)
            rep.error(W, f"stage {stage} is past gate {g} (stage {GATE_STAGE[g]}) but gates.{g} is null: "
                         f"only the user passes a gate; set stage back or record the approval date")
    for i, g in enumerate(GATES):
        later = [x for x in GATES[i + 1:] if dates[x] is not None]
        if dates[g] is None and later and g not in behind:
            rep.error(W, f"gates.{later[0]} is dated but the earlier gate {g} is null")
    prev = None
    soon = datetime.date.today() + datetime.timedelta(days=1)   # one day of slack for time zones
    for g in GATES:
        d = dates[g]
        if d is None:
            continue
        if prev and d < dates[prev]:
            rep.error(W, f"gates.{g} {d} is before gates.{prev} {dates[prev]}")
        if d > soon:
            rep.warn(W, f"gates.{g} {d} is in the future")
        prev = g


BUDGET_KEYS = ("images", "video_seconds", "models", "ledger_required")
BUDGET_REQUIRED = ("images", "video_seconds")
LEDGER_REQUIRED_FROM_STAGE = 4


def is_cap(v):
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) and v >= 0


def check_budget(ep_dir, meta, rep):
    """budget.yaml (docs/CONVENTIONS.md §7): a stage-0 output; a misspelled or missing cap is no cap."""
    import yaml
    W = "budget.yaml"
    path = os.path.join(ep_dir, W)
    if not os.path.isfile(path):
        rep.error(W, "missing (written at stage 0: no paid call without a budget; copy templates/episode/budget.yaml)")
        return
    try:
        b, dups = yaml_load_dups(read_text(path))
        report_dups(rep, W, dups)
    except CheckError as e:
        rep.error(W, e.msg)
        return
    except (yaml.YAMLError, ValueError) as e:
        rep.error(W, f"not valid YAML: {str(e).splitlines()[0]}")
        return
    if b is None:
        b = {}                                   # an empty file is an empty mapping: both totals are missing
    if not isinstance(b, dict):
        rep.error(W, f"must be a mapping with {', '.join(BUDGET_KEYS)}")
        return
    for k in b:
        if k not in BUDGET_KEYS:
            rep.error(W, f"unknown key {k} (a misspelled cap is no cap)")
    for k in BUDGET_REQUIRED:
        if k not in b:
            rep.error(W, f"required key '{k}' missing")
        elif not is_cap(b[k]):
            rep.error(W, f"{k} = {b[k]!r} must be a number >= 0")
    models = b.get("models")
    if models is not None:
        if not isinstance(models, dict):
            rep.error(W, "models must be a mapping model id -> number >= 0")
        else:
            for mid, cap in models.items():
                if not is_cap(cap):
                    rep.error(W, f"models.{mid} = {cap!r} must be a number >= 0")
    method = episode_method(meta)[0]
    if method == "layers":      # layers never calls Seedance: no video cap may be open
        caps = [("video_seconds", b.get("video_seconds"))]
        if isinstance(models, dict):
            caps += [(f"models.{mid}", cap) for mid, cap in models.items() if "seedance" in str(mid).lower()]
        for name, cap in caps:
            if is_cap(cap) and cap > 0:
                rep.error(W, f"method layers: {name} = {cap!r} must be 0 (no Seedance), or set method: seedance")
    elif method == "code":      # code calls no model at all: every cap is 0
        caps = [("images", b.get("images")), ("video_seconds", b.get("video_seconds"))]
        if isinstance(models, dict):
            caps += [(f"models.{mid}", cap) for mid, cap in models.items()]
        for name, cap in caps:
            if is_cap(cap) and cap > 0:
                rep.error(W, f"method code: {name} = {cap!r} must be 0 (no image or video model is called)")
    elif method == "blender":   # Blender renders are free; only paid Seedance clips (video_engine seedance) need a cap
        engine, engine_set = video_engine(meta)
        paid_clips = engine == "seedance" and engine_set and bool(shots_with_ai_motion(ep_dir))
        caps = [("images", b.get("images"))]
        if isinstance(models, dict):
            caps += [(f"models.{mid}", cap) for mid, cap in models.items() if "seedance" not in str(mid).lower()]
        for name, cap in caps:
            if is_cap(cap) and cap > 0:
                rep.error(W, f"method blender: {name} = {cap!r} must be 0 (no image model: Blender renders the frames)")
        if not paid_clips:
            caps = [("video_seconds", b.get("video_seconds"))]
            if isinstance(models, dict):
                caps += [(f"models.{mid}", cap) for mid, cap in models.items() if "seedance" in str(mid).lower()]
            why = ("video_engine comfy makes free local clips" if engine == "comfy" else
                   "no shot has ai_motion" if engine_set else "no video_engine: seedance with ai_motion shots")
            for name, cap in caps:
                if is_cap(cap) and cap > 0:
                    rep.error(W, f"method blender: {name} = {cap!r} must be 0 ({why})")
    if method == "seedance" and video_engine(meta)[0] == "comfy":
        vs = b.get("video_seconds")
        if is_cap(vs) and vs > 0:
            rep.warn(W, f"video_engine comfy: clips are local and free, Seedance is not called; video_seconds = {vs!r} "
                        f"is not used (set 0)")
    required = b.get("ledger_required")
    if "ledger_required" in b and not isinstance(required, bool):
        rep.error(W, f"ledger_required = {required!r} must be true or false")
    elif required is not True:
        stage = meta.get("stage") if meta else None
        if isinstance(stage, int) and stage >= LEDGER_REQUIRED_FROM_STAGE:
            rep.warn(W, f"ledger_required is not true at stage {stage} (set it from stage {LEDGER_REQUIRED_FROM_STAGE}: "
                        f"ark.py then refuses to generate before the ledger was pulled from Drive)")


def shots_with_ai_motion(ep_dir):
    """Shot ids with a non-empty ai_motion in shots.csv, read leniently (check_shots reports what is wrong)."""
    try:
        with open(os.path.join(ep_dir, "shots.csv"), encoding="utf-8-sig", newline="") as f:
            return [r.get("shot") for r in csv.DictReader(f) if (r.get("ai_motion") or "").strip()]
    except (OSError, UnicodeDecodeError, csv.Error):
        return []


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
        stage = meta.get("stage") if meta else None
        early = isinstance(stage, int) and stage < REQUIRED_FROM_STAGE["shots.csv"]
        (rep.warn if early else rep.error)("shots.csv", "no shots")
        return {}
    shots, prev, prev_num, prev_to = {}, None, None, None
    length = meta.get("length_s") if meta else None
    method = episode_method(meta)[0]
    layers_only = method == "layers"
    code = method == "code"
    blender = method == "blender"
    engine_set = video_engine(meta)[1]
    registry = motion_registry()
    cameras = CAMERAS_CODE if code else CAMERAS_BLENDER if blender else CAMERAS
    if code and registry:                        # toon camera moves of motions.json are camera values too
        cameras = cameras | {k for k, v in registry.items() if is_toon_camera(v)}
    width = None                                 # digits of the first valid shot id: 2 (s01) or 3 (s001)
    for n, r in rows:
        W = f"shots.csv:{n}"
        sid = r["shot"]
        sn = eid_mod.shot_number(sid)
        if not sn:
            rep.error(W, f"shot id '{sid}' must be s<NN> (s01-s99) or s<NNN> (s001-s999)")
        else:
            num, w = sn
            if width is None:
                width = w
            elif w != width:
                rep.error(W, f"shot id '{sid}' has {w} digits but the first shot has {width}: one episode uses one "
                             f"width (all s<NN> or all s<NNN>; more than 99 shots need s001...)")
            if prev_num is None and num != 1:
                rep.warn(W, f"first shot is {sid}, expected {eid_mod.make_shot(1, w)}")
            if prev_num is not None:
                if num <= prev_num:
                    rep.error(W, f"shot ids must increase: {sid} after {eid_mod.make_shot(prev_num, width)}")
                elif num != prev_num + 1:
                    rep.warn(W, f"gap in shot ids: {sid} after {eid_mod.make_shot(prev_num, width)}")
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
        if r["camera"] not in cameras:
            rep.error(W, f"camera '{r['camera']}' is not one move from {', '.join(sorted(cameras))}")
        if prev and prev["shot_size"] == r["shot_size"] and prev["camera"] == r["camera"]:
            rep.error(W, f"{sid} repeats both shot_size '{r['shot_size']}' and camera '{r['camera']}' of {prev['shot']}")
        codes = [c.strip() for c in r["layers"].split(";") if c.strip()]
        if not codes and not r["reuse_of"]:
            rep.warn(W, f"{sid} has no layers")
        for c in codes:
            if code:
                if not RE_CODE_LAYER.match(c):
                    rep.error(W, f"method code: layer code '{c}' invalid "
                                 f"(C-<character> or M-<model>, E-<setting>, FX[-<effect>], T)")
            elif blender:
                if not RE_BLENDER_LAYER.match(c):
                    rep.error(W, f"method blender: layer code '{c}' invalid "
                                 f"(A-<asset>, E-<setting>, FX[-<effect>], T)")
            elif not RE_LAYER_CODE.match(c):
                rep.error(W, f"layer code '{c}' invalid (L1-L4, pose plates L4b-L4z, P<n>-<part>, FX)")
            elif eid_mod.RE_POSE.match(c) and method == "seedance":
                rep.warn(W, f"{sid}: pose plate {c} belongs to method layers (pose-cycle); a seedance episode moves "
                            f"the character with a clip")
        if len(codes) != len(set(codes)):
            rep.error(W, f"duplicate layer codes in '{r['layers']}'")
        if registry is not None:
            for m in (x.strip() for x in r["code_motion"].split(";")):
                if not m:
                    continue
                if m not in registry:
                    rep.warn(W, f"{sid} code_motion '{m}' is not in tools/compose/motions.json")
                elif is_toon_motion(registry[m]) and not code:
                    rep.warn(W, f"{sid} code_motion '{m}' is a method code (TOON) action; a {method or 'seedance'} "
                                f"episode has no TOON character")
                elif method in ("code", "blender") and not is_toon_motion(registry[m]) and needs_plate(registry[m]):
                    rep.warn(W, f"{sid} code_motion '{m}' rigs a painted plate ({registry[m].get('call')}); "
                                f"a method {method} episode has none")
        if layers_only and r["ai_motion"].strip():
            rep.error(W, f"method layers: shot {sid} has ai_motion; use code_motion or pose-cycle, or set method: seedance")
        if code and r["ai_motion"].strip():
            rep.error(W, f"method code: shot {sid} has ai_motion; every motion is a TOON action (code_motion)")
        if blender and r["ai_motion"].strip() and not engine_set:
            rep.error(W, f"method blender: shot {sid} has ai_motion but EPISODE.md has no video_engine: set comfy "
                         f"(local MiniMax H3 clip (tools/comfy/comfy.py) from Blender keyframes, free) or seedance (paid clip), "
                         f"or empty ai_motion")
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


RE_INLINE_COMMENT = re.compile(r"<!--.*?-->")


def narration_lines(text):
    """Yield (line number, line) for narration lines of script.md.

    HTML comments are removed from a line before it is classified, so narration before or after a comment
    on the same line is kept (without the comment); the line is yielded unchanged when it has none."""
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
        if comment:                              # inside a multi-line comment: keep what follows its end
            if "-->" not in raw:                 # (a ``` line in a comment is part of the comment, not a fence)
                continue
            comment = False
            raw = raw.split("-->", 1)[1].strip()
        s = raw.strip()
        if s.startswith("```") or s.startswith("~~~"):
            fence = not fence
            continue
        if fence:
            continue
        if "<!--" in raw:
            raw = RE_INLINE_COMMENT.sub("", raw)
            if "<!--" in raw:                    # a comment that continues on the next lines
                comment = True
                raw = raw.split("<!--", 1)[0]
            raw = raw.strip()
        s = raw.strip()
        if not s or s.startswith("#") or s.startswith(">") or re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            continue
        yield k + 1, raw


RE_MARK = re.compile(r"^\s*(?:[-*]\s+)?\[(\d{2}):(\d{2})\]\s*(.*)$")
RE_CJK = re.compile("[\u3400-\u9fff\uf900-\ufaff]+")
UNSPEAKABLE = ("|", "`", "](", "<", ">")


def unspeakable(said):
    """What a TTS engine would read as noise in the spoken text of a narration line."""
    found = [f"CJK ideograph(s) {''.join(RE_CJK.findall(said))}"] if RE_CJK.search(said) else []
    return found + [repr(x) for x in UNSPEAKABLE if x in said]


def check_script(ep_dir, meta, rep):
    path = os.path.join(ep_dir, "script.md")
    if not os.path.isfile(path):
        missing_file(rep, meta, "script.md")
        return
    try:
        text = read_text(path)
    except CheckError as e:
        rep.error("script.md", e.msg)
        return
    narr = list(narration_lines(text))
    narr_nos = {n for n, _ in narr}
    for n, line in enumerate(text.splitlines(), start=1):
        for ch, name in DASHES.items():
            if ch in line and n not in narr_nos:
                rep.warn(f"script.md:{n}", f"{name} outside narration (use ',' '.' or ':')")
        if "--" in line and n not in narr_nos and line.lstrip().startswith(">"):
            rep.warn(f"script.md:{n}", "double hyphen '--' outside narration (use ',' '.' or ':')")
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
        if "--" in line:
            rep.error(W, "double hyphen '--' in narration (TTS reads it badly; use ',' '.' or ':')")
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
        if unspeakable(said):
            rep.warn(W, f"not speakable: {', '.join(unspeakable(said))} in the spoken text (TTS reads it as noise)")
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
    method = episode_method(meta)[0]
    if method in ("code", "blender"):           # no image model: no prompts.csv needed
        if os.path.isfile(path):
            rep.warn("prompts.csv", "method code generates no image or clip; prompts.csv is not used" if method == "code"
                     else "method blender generates no image (clips are recorded in the ledger and the clip's "
                          "prompts/<clip>.txt or .json sidecar); prompts.csv is not used")
        return None
    if not os.path.isfile(path):
        missing_file(rep, meta, "prompts.csv")
        return None
    rows = read_csv(path, PROMPTS_HEADER, rep, "prompts.csv")
    if rows is None:
        return None
    eid = meta.get("_id") if meta else None
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
            rep.error(W, f"file '{f}' does not match <id>_s<NN>_<layer>_<subject>_v<NN>.<png|jpg> "
                         f"(layer) or <id>_s<NN>_<model>_v<NN>.mp4 (clip); <id> = ep<NN> or q<NN>t<NN>")
        else:
            parts = f.split("_")
            if eid and parts[0] != eid:
                rep.error(W, f"file '{f}' is not for episode {eid}")
            if parts[1] != r["shot"]:
                rep.error(W, f"file '{f}' is for {parts[1]} but shot column is '{r['shot']}'")
            # A Seedance clip row names the layer it replaces/feeds (seedance-layer.md: layer = L4);
            # the clip name carries no layer code, so only the column itself is validated below.
            if m and m.group(1) != r["layer"]:
                rep.error(W, f"file '{f}' has layer {m.group(1)} but layer column is '{r['layer']}'")
        if not RE_SHOT.match(r["shot"]):
            rep.error(W, f"shot '{r['shot']}' must be s<NN> or s<NNN>")
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
    check_approved_once(files, rep)
    return files


def check_approved_once(rows, rep):
    """One approved image per (shot, layer) and one approved clip per (shot, layer): with two, nobody knows which
    one the film uses (a clip row names the layer it replaces, so an approved L4 plate plus its clip is fine)."""
    approved = {}
    for r in rows:
        if r["approved"] == "yes":
            kind = "clip" if RE_CLIP_FILE.match(r["file"]) else "image"
            approved.setdefault((r["shot"], r["layer"], kind), []).append(r["file"])
    for (shot, layer, kind), names in approved.items():
        if len(names) > 1:
            rep.error("prompts.csv", f"{shot} {layer}: {len(names)} approved {kind}s ({', '.join(names)}); "
                                     f"keep approved=yes on the one the film uses, set the others to no")


def check_media_name(rel, name, sub, rx, eid, rep):
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
    elif sub == "clips" and (RE_START_FRAME.match(name) or RE_CLIP_SIDECAR.match(name)):
        pass
    elif not rx.match(name):
        extra = f" or {RE_START_FRAME.pattern} or {RE_CLIP_SIDECAR.pattern}" if sub == "clips" else ""
        rep.error(where, f"name does not match the {sub} convention ({rx.pattern}{extra})")
        return
    if eid and not check_ep.startswith(f"{eid}_"):
        rep.error(where, f"file is not for episode {eid}")


def check_media(media, meta, prompt_rows, rep, shots=None):
    if not media or not os.path.isdir(media):
        rep.warn("media", f"media folder {media or '(none)'} not found: plates/clips/renders not checked")
        return False
    eid = meta.get("_id") if meta else None
    base = os.path.basename(os.path.normpath(os.path.abspath(media)))
    if eid and base != eid:
        rep.error("media", f"media folder '{base}' does not match episode id '{eid}' (out/<project>/{eid})")
    for sub, rx in MEDIA_RULES.items():
        d = os.path.join(media, sub)
        if not os.path.isdir(d):
            continue
        for root, dirs, names in os.walk(d):
            dirs.sort()
            for name in sorted(names):
                check_media_name(os.path.relpath(os.path.join(root, name), media), name, sub, rx, eid, rep)
    check_listed_files(media, meta, prompt_rows, rep)
    check_orphan_plates(media, prompt_rows, rep)
    check_clips(media, meta, shots, prompt_rows, rep)
    check_renders3d(media, meta, shots, rep)
    led = os.path.join(media, "ledger.csv")
    if os.path.isfile(led):
        head = ledger_head(led, rep)
        if head is not None and head != ",".join(LEDGER_HEADER):
            rep.error("media/ledger.csv", f"header is {head!r}, expected {','.join(LEDGER_HEADER)!r}")
    return True


def check_orphan_plates(media, prompt_rows, rep):
    """Images in plates/ (not plates/matte/) with no prompts.csv row: a paid image nobody recorded (no prompt,
    no approval), or a test file. One WARN line lists them. Skipped when prompts.csv could not be read."""
    if prompt_rows is None:
        return
    d = os.path.join(media, "plates")
    try:
        names = sorted(n for n in os.listdir(d) if not n.startswith(".") and os.path.isfile(os.path.join(d, n)))
    except OSError:
        return
    listed = {r["file"] for r in prompt_rows}
    orphans = [n for n in names if n not in listed]
    if orphans:
        rep.warn("media/plates", f"{len(orphans)} file(s) with no prompts.csv row (record the prompt, or move test "
                                 f"files out of plates/): {', '.join(orphans)}")


def check_clips(media, meta, shots, prompt_rows, rep):
    """From G3 (stage 8, the whole-episode draft) every seedance or blender shot with ai_motion has its clip in clips/
    (the shot named in reuse_of for a reused shot; a Seedance or a local ComfyUI clip). A clip rejected in prompts.csv
    (approved=no) does not count."""
    stage = meta.get("stage") if meta else None
    if not shots or episode_method(meta)[0] not in VIDEO_ENGINE_METHODS or not isinstance(stage, int)             or stage < GATE_STAGE["G3"]:
        return
    rejected = {r["file"] for r in prompt_rows or [] if r["approved"] == "no"}
    d = os.path.join(media, "clips")
    try:
        names = os.listdir(d)
    except OSError:
        names = []
    have = {eid_mod.RE_SHOT_TAG.search(n).group(1) for n in names
            if RE_CLIP_FILE.match(n) and n not in rejected and os.path.isfile(os.path.join(d, n))}
    for sid, r in shots.items():
        if not r["ai_motion"].strip():
            continue
        owner = r["reuse_of"] or sid
        if owner not in have:
            rep.error(f"shots.csv:{r['_line']}", f"{sid} has ai_motion '{r['ai_motion']}' but no clip "
                      f"<id>_{owner}_<model>_v<NN>.mp4 in {d} at stage {stage} (G3 needs every clip; "
                      f"pull the shot bundle from Drive, or empty ai_motion and move it with code_motion)")


def render3d_done(path):
    """True when a renders3d/<name>/ folder holds a render: render.json, beauty.mp4 or a frame in beauty/."""
    if os.path.isfile(os.path.join(path, "render.json")) or os.path.isfile(os.path.join(path, "beauty.mp4")):
        return True
    try:
        return any(n.lower().endswith(".png") for n in os.listdir(os.path.join(path, "beauty")))
    except OSError:
        return False


def renders3d_index(media):
    """{shot id: {"final": bool, "preview": bool}} and the turntable folder names under <media>/renders3d/ (only
    folders that hold a render count; tools/blender/blender.py writes them, docs/CONVENTIONS.md §2)."""
    shots, turn = {}, []
    d = os.path.join(media, "renders3d") if media else ""
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return shots, turn
    for n in names:
        m = RE_RENDER3D_DIR.match(n)
        p = os.path.join(d, n)
        if not m or not os.path.isdir(p) or not render3d_done(p):
            continue
        if m.group(1) is None:
            turn.append(n)
        elif m.group(2) != "keys":
            st = shots.setdefault(m.group(1), {"final": False, "preview": False})
            st["preview" if m.group(2) == "preview" else "final"] = True
    return shots, turn


def check_renders3d(media, meta, shots, rep):
    """Names under <media>/renders3d/ and, for method blender from stage 7 (compositing), a final render of every
    non-reuse shot (renders3d/s<NN>/ or s<NN>_v<NN>/)."""
    d = os.path.join(media, "renders3d")
    blender = episode_method(meta)[0] == "blender"
    if os.path.isdir(d):
        for n in sorted(os.listdir(d)):
            where = f"media/renders3d/{n}"
            m = RE_RENDER3D_DIR.match(n)
            if not os.path.isdir(os.path.join(d, n)):
                rep.warn(where, "renders3d/ holds one folder per render (blender.py --out), not files")
            elif not m:
                rep.warn(where, "folder name is not s<NN>[_preview|_keys][_v<NN>] or turntable-<asset>[_v<NN>]")
            elif m.group(1) and shots and m.group(1) not in shots:
                rep.warn(where, f"{m.group(1)} is not a shot of shots.csv")
        if not blender:
            rep.warn("media/renders3d", "Blender renders in a method "
                     f"{episode_method(meta)[0] or 'seedance'} episode: renders3d/ is used by method blender")
    if not blender or not shots:
        return
    stage = meta.get("stage") if meta else None
    done, _ = renders3d_index(media)
    todo = [sid for sid, r in shots.items() if not r["reuse_of"] and not done.get(sid, {}).get("final")]
    if not todo:
        return
    if isinstance(stage, int) and stage >= FILES_REQUIRED_FROM_STAGE:
        rep.error("media/renders3d", f"no final Blender render for {', '.join(todo)} at stage {stage} (compositing "
                                     f"needs renders3d/<shot>/: tools/blender/blender.py render, or pull the shot "
                                     f"bundles from Drive and unzip them in the media folder: tools/bundle.py packs "
                                     f"renders3d/<shot>/beauty.mp4 + render.json)")
    else:
        rep.info(f"renders3d: {len(todo)} shot(s) not rendered yet (required from stage {FILES_REQUIRED_FROM_STAGE}): "
                 f"{', '.join(todo)}")


SHOT3D_STAGE = 5          # method blender: every non-reuse shot has shots3d/s<NN>.json from stage 5 (renders)
ASSETS_STAGE = 4          # method blender: ASSETS.md (licence and source of every 3D model) from stage 4 (G2)


def blender_spec_module():
    """tools/blender/spec.py (package P2) imported by path, or None when it is not in this checkout."""
    import importlib.util
    path = os.path.join(LAB, "tools", "blender", "spec.py")
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("film_blender_spec", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def shot3d_errors(mod, path, data):
    """Problems of one shot3d.json as 'path: reason' strings, through tools/blender/spec.py: the first of
    validate_file / check_file / load_file (given the path) or validate / check / errors (given the parsed JSON)
    that the module has. It may return a list of problems, a (value, problems) pair, or raise. None = no such
    function in the module."""
    import inspect
    for name, arg in (("validate_file", path), ("check_file", path), ("load_file", path),
                      ("validate", data), ("check", data), ("errors", data)):
        fn = getattr(mod, name, None)
        if not callable(fn):
            continue
        kw = {}
        try:
            sig = inspect.signature(fn).parameters
            params = [p for p in sig.values()
                      if p.default is p.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
            if "base_dir" in sig and len(params) < 2:   # spec.validate(data, base_dir=None): also checks .glb files
                kw["base_dir"] = os.path.dirname(path)
        except (TypeError, ValueError):
            params = [None]
        args = [arg, os.path.dirname(path)][:max(1, len(params))]
        try:
            out = fn(*args, **kw)
        except Exception as e:                   # spec.py raises its own error type with 'path: reason' lines
            return [l for l in str(e).splitlines() if l.strip()] or [type(e).__name__]
        if isinstance(out, tuple) and len(out) == 2 and isinstance(out[1], (list, tuple)):
            out = out[1]
        if isinstance(out, (list, tuple)):
            return [str(x) for x in out]
        return []
    return None


def check_shots3d(ep_dir, meta, shots, rep):
    """<episode>/shots3d/s<NN>.json (method blender): names, one per non-reuse shot from stage 5, camera.move and
    seconds against shots.csv, and the schema through tools/blender/spec.py when that module exists."""
    method = episode_method(meta)[0]
    d = os.path.join(ep_dir, "shots3d")
    names = sorted(n for n in os.listdir(d) if not n.startswith(".")) if os.path.isdir(d) else []
    if names and method != "blender":
        rep.warn("shots3d", f"shot3d.json files in a method {method or 'seedance'} episode: only method blender "
                            f"renders them")
    have = set()
    mod, mod_err, warned = None, None, False
    for n in names:
        where = f"shots3d/{n}"
        m = RE_SHOT3D_FILE.match(n)
        if not m:
            rep.error(where, "name must be s<NN>.json (one shot3d.json per shot of shots.csv)")
            continue
        sid = m.group(1)
        have.add(sid)
        if shots is not None and sid not in shots:
            rep.error(where, f"{sid} is not a shot of shots.csv")
        path = os.path.join(d, n)
        try:
            data = json.loads(read_text(path))
        except CheckError as e:
            rep.error(where, e.msg)
            continue
        except ValueError as e:
            rep.error(where, f"not valid JSON: {e}")
            continue
        if not isinstance(data, dict):
            rep.error(where, "must be a JSON object (shot3d.json, tools/blender/README.md)")
            continue
        row = (shots or {}).get(sid)
        cam = data.get("camera") if isinstance(data.get("camera"), dict) else {}
        if row and cam.get("move") and cam.get("move") != row["camera"]:
            rep.warn(where, f"camera.move '{cam.get('move')}' differs from shots.csv camera '{row['camera']}' of {sid}")
        a, b = (to_float(row["from_s"]), to_float(row["to_s"])) if row else (None, None)
        sec = data.get("seconds")
        if a is not None and b is not None and is_cap(sec) and abs(sec - (b - a)) > 0.05:
            rep.warn(where, f"seconds {fmt_s(sec)} differs from the shot length {fmt_s(b - a)} s in shots.csv")
        if mod is None and mod_err is None:
            try:
                mod = blender_spec_module()
                mod_err = "missing" if mod is None else None
            except Exception as e:
                mod_err = f"cannot be imported ({type(e).__name__}: {e})"
        if mod is None:
            if not warned:
                rep.warn("shots3d", ("tools/blender/spec.py not in this checkout" if mod_err == "missing" else
                                     f"tools/blender/spec.py {mod_err}") + ": shot3d.json schema not checked")
                warned = True
            continue
        errs = shot3d_errors(mod, path, data)
        if errs is None:
            if not warned:
                rep.warn("shots3d", "tools/blender/spec.py has no validate/check function this checker knows: "
                                    "shot3d.json schema not checked")
                warned = True
            continue
        for e in errs:
            rep.error(where, e)
    if method != "blender" or not shots:
        return
    stage = meta.get("stage") if meta else None
    todo = [sid for sid, r in shots.items() if not r["reuse_of"] and sid not in have]
    if todo and isinstance(stage, int) and stage >= SHOT3D_STAGE:
        rep.error("shots3d", f"no shot3d.json for {', '.join(todo)} (required from stage {SHOT3D_STAGE}; "
                             f"episode is at stage {stage})")
    elif todo and isinstance(stage, int) and stage >= 3:
        rep.info(f"shots3d: {len(todo)} shot(s) without shots3d/<shot>.json yet (required from stage {SHOT3D_STAGE}): "
                 f"{', '.join(todo)}")


def check_assets(ep_dir, meta, rep):
    """method blender: ASSETS.md (source and licence of every 3D model) in the episode or the project folder."""
    if episode_method(meta)[0] != "blender":
        return
    stage = meta.get("stage") if meta else None
    here = [p for p in (os.path.join(ep_dir, "ASSETS.md"),
                        os.path.join(os.path.dirname(os.path.abspath(ep_dir)), "ASSETS.md")) if os.path.isfile(p)]
    if here or not isinstance(stage, int) or stage < 3:
        return
    msg = ("missing: source and licence of every 3D model (GLB or preset), written at stage 3 "
           "(.claude/skills/film-compose-shot/references/blender-method.md)")
    (rep.error if stage >= ASSETS_STAGE else rep.warn)("ASSETS.md", msg)


# --- creature table (EPISODE.md `## Sinh vật của tập`, docs/CONVENTIONS.md §5; issues #52, #53) ------------------
# One row per creature/deity of the episode: the owner's book photo (SERIES.md owner_refs) and the approved concept
# (creature design gate, stage 3a) live here. slug = characters/<slug>/ = the model id A-<slug> (blender) / C-<slug>.
CREATURE_HEADING = "## Sinh vật của tập"
CREATURE_COLS = {"slug": "slug", "tên": "name", "chính": "main", "ảnh sách": "book", "concept": "concept"}
CREATURE_NEED = ("slug", "main", "book", "concept")
CREATURE_VALUES = {   # first word of the cell, lower case -> value; "" = an empty cell (main: none, see read_creatures)
    "main": {"có": True, "yes": True, "x": True, "không": False, "no": False},
    "book": {"có": "yes", "yes": "yes", "không": "none", "no": "none", "chờ": "pending", "pending": "pending",
             "": "pending"},
    "concept": {"duyệt": "approved", "approved": "approved", "chờ": "pending", "pending": "pending", "": "pending"},
}
CREATURE_HELP = {"main": "có | không", "book": "có | không | chờ", "concept": "chờ | duyệt"}
CONCEPT_HEADING = "## Concept đã duyệt"      # characters/<slug>/CHARACTER.md: which concept the owner picked, when
CREATURE_METHODS = ("blender", "code")       # methods that build creature models: concept approved before G2
CONCEPT_STAGE = 5                            # past G2 (closes stage 4): an unapproved main creature is an ERROR
RE_TABLE_SEP = re.compile(r"^:?-+:?$")        # GFM delimiter cells: ---, :--, --:, :-:, --
RE_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
RE_COMMENT = re.compile(r"<!--.*?-->", re.S)


def cell_word(v):
    """First word of a table cell, lower case, without trailing punctuation ('Duyệt 2026-11-26' -> 'duyệt')."""
    w = nfc(v).strip().split()
    return w[0].lower().strip(".,;:()") if w else ""


def section_lines(body, heading):
    """Lines of the `## ` section named heading (HTML comments removed), or None when the section is missing.
    A `## ` line inside a fenced code block (``` or ~~~) is text, not a heading."""
    lines, on, found, fence = [], False, False, None
    for line in RE_COMMENT.sub("", nfc(body)).splitlines():
        m = RE_FENCE.match(line)
        if m:
            mark = m.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence) and not line.strip()[len(mark):].strip():
                fence = None
        elif fence is None and line.startswith("## "):
            if on:
                break
            on = line.rstrip() == heading
            found = found or on
            continue
        if on:
            lines.append(line)
    return lines if found else None


def read_creatures(body):
    """The creature table of an EPISODE.md body: None when the section is missing, else {"rows": [...],
    "problems": [...]}; each row {"slug", "name", "main": bool, "book": yes|none|pending,
    "concept": approved|pending, "concept_text": the cell as written}. Rows with a bad value keep the default."""
    lines = section_lines(body, CREATURE_HEADING)
    if lines is None:
        return None
    out = {"rows": [], "problems": []}
    table = [l.strip() for l in lines if l.strip().startswith("|")]
    if not table:
        return out
    cells = lambda l: [c.strip() for c in l.strip().strip("|").split("|")]
    head = [CREATURE_COLS.get(" ".join(nfc(c).lower().split()).strip("`*")) for c in cells(table[0])]
    missing = [CREATURE_COLS_INV[k] for k in CREATURE_NEED if k not in head]
    if missing:
        out["problems"].append(f"{CREATURE_HEADING}: column(s) {', '.join(missing)} missing (header: "
                               f"| slug | Tên | Chính | Ảnh sách | Concept |)")
        return out
    body_rows = table[1:]
    if body_rows and all(RE_TABLE_SEP.match(c) for c in cells(body_rows[0]) if c):
        body_rows = body_rows[1:]
    for n, line in enumerate(body_rows, 1):
        vals = dict(zip(head, cells(line)))
        if not any(v.strip() for v in vals.values()):
            continue
        slug = nfc(vals.get("slug", "")).strip().strip("`")
        if slug.startswith(("A-", "C-")):
            slug = slug[2:]
        row = {"slug": slug, "name": vals.get("name", "").strip(), "concept_text": vals.get("concept", "").strip()}
        if not RE_SLUG.match(slug):
            out["problems"].append(f"{CREATURE_HEADING} row {n}: slug '{slug}' is not a lower-case slug "
                                   "(characters/<slug>/, model A-<slug>)")
        for key, table_ in CREATURE_VALUES.items():
            word = cell_word(vals.get(key, ""))
            if word in table_:
                row[key] = table_[word]
            elif key == "main" and not word:     # empty or missing "Chính": counted as main (the gate still applies)
                row[key] = True
                out["problems"].append(f"{CREATURE_HEADING} row {n} ({slug}): {CREATURE_COLS_INV[key]} is empty: "
                                       f"counted as main (write {CREATURE_HELP[key]})")
            else:
                row[key] = True if key == "main" else table_[""]     # unreadable "main": the gate still applies
                out["problems"].append(f"{CREATURE_HEADING} row {n} ({slug}): {CREATURE_COLS_INV[key]} "
                                       f"'{vals.get(key, '').strip()}' is not {CREATURE_HELP[key]}")
        out["rows"].append(row)
    return out


CREATURE_COLS_INV = {v: k for k, v in CREATURE_COLS.items()}


def concept_record(ep_dir, slug):
    """Path (relative to the project folder) of the characters/<slug>/CHARACTER.md that records the approved concept
    in a non-empty `## Concept đã duyệt` section (episode folder first, then the project), or None."""
    ep = os.path.abspath(ep_dir)
    project = os.path.dirname(ep)
    for base in (ep, project):
        path = os.path.join(base, "characters", slug, "CHARACTER.md")
        try:
            text = read_text(path)
        except (OSError, CheckError):
            continue
        lines = section_lines(text, CONCEPT_HEADING)
        if lines and any(l.strip() for l in lines):
            return os.path.relpath(path, project).replace(os.sep, "/")
    return None


def concept_gaps(ep_dir, rows):
    """[(slug, why)] for every main creature whose concept is not approved, or approved in the table but not recorded
    in its CHARACTER.md."""
    gaps = []
    for r in rows:
        if not r.get("main"):
            continue
        if r.get("concept") != "approved":
            gaps.append((r["slug"], "concept not 'duyệt' in the table"))
        elif not concept_record(ep_dir, r["slug"]):
            gaps.append((r["slug"], f"no '{CONCEPT_HEADING}' in characters/{r['slug']}/CHARACTER.md"))
    return gaps


def owner_refs(ep_dir):
    """(config, problem) from `owner_refs:` in the front matter of SERIES.md beside the episode folder: config is
    {"source": str, "required": bool} or None (no SERIES.md, no key); problem is a message or None."""
    path = os.path.join(os.path.dirname(os.path.abspath(ep_dir)), "SERIES.md")
    if not os.path.isfile(path):
        return None, None
    try:
        import yaml
        fm, _ = split_front_matter(read_text(path))
        meta = yaml.safe_load(fm) if fm else None
    except Exception as e:                       # unreadable file, bad YAML
        return None, f"front matter unreadable ({str(e).splitlines()[0] if str(e) else type(e).__name__})"
    if not isinstance(meta, dict) or meta.get("owner_refs") is None:
        return None, None
    v = meta["owner_refs"]
    if not isinstance(v, dict) or not isinstance(v.get("required", False), bool):
        return None, ("owner_refs must be {source: \"<the owner's material>\", required: true|false}"
                      f" (got {v!r})")
    return {"source": str(v.get("source") or "").strip(), "required": v.get("required", False)}, None


def check_creatures(ep_dir, meta, rep):
    """The creature table: well-formed; book photos when SERIES.md owner_refs.required; an approved concept for every
    main creature of a method blender/code episode (WARN at stages 3-4, ERROR from stage 5, after G2)."""
    W = "EPISODE.md"
    try:
        _, body = split_front_matter(read_text(os.path.join(ep_dir, "EPISODE.md")))
    except (OSError, CheckError):
        return
    stage = meta.get("stage") if isinstance(meta.get("stage"), int) else -1
    method = episode_method(meta)[0]
    refs, problem = owner_refs(ep_dir)
    if problem:
        rep.warn("SERIES.md", problem)
    required = bool(refs and refs["required"])
    tab = read_creatures(body)
    if tab is None:
        if (method in CREATURE_METHODS and stage >= 3) or (required and stage >= 1):
            rep.info(f"{W}: no '{CREATURE_HEADING}' table (creatures, book photos, approved concepts: "
                     "templates/episode/EPISODE.md); status.py --gate asks for it")
        return
    for msg in tab["problems"]:
        rep.warn(W, msg)
    if required and stage >= 2:
        pend = [r["slug"] for r in tab["rows"] if r["book"] == "pending"]
        if pend:
            rep.warn(W, f"owner_refs.required (SERIES.md): no book photo yet for {', '.join(pend)}: ask the owner for "
                        "the page, or write 'không' when the owner says the book has none")
    if method in CREATURE_METHODS and stage >= 3:
        gaps = concept_gaps(ep_dir, tab["rows"])
        if gaps:
            (rep.error if stage >= CONCEPT_STAGE else rep.warn)(
                W, f"main creature(s) without an approved concept: "
                   + "; ".join(f"{s} ({why})" for s, why in gaps)
                   + f" – creature design gate before any {method} model (film-pipeline stage 3a)")


# --- creature coverage in shots.csv (film-script §2, docs/CONVENTIONS.md §6; issue #72) ------------------------------
# Every main creature of a blender/code episode gets at least one detail close-up and one shot small in a vast
# landscape. A creature is in a shot when its model is in the shot's layers: A-<slug> (blender), C-<slug> / M-<slug>
# (code), or a variant <prefix>-<slug>-<suffix> when <slug>-<suffix> is not another creature of the table.
CLOSE_SIZES = ("close", "extreme-close", "insert")
VAST_SIZES = ("extreme-wide",)
CREATURE_PREFIXES = {"blender": ("A-",), "code": ("C-", "M-")}


def creature_in_codes(slug, codes, prefixes, others):
    """A-giao-long-head is giao-long's when giao-long is a creature too, never giao's: a variant belongs to the
    longest creature slug it starts with."""
    longer = [o for o in others if len(o) > len(slug) and o.startswith(slug + "-")]
    for c in codes:
        for p in prefixes:
            if not c.startswith(p):
                continue
            name = c[len(p):]
            if name == slug or (name.startswith(slug + "-") and name not in others
                                and not any(name == o or name.startswith(o + "-") for o in longer)):
                return True
    return False


def creature_coverage(rows, shots, method):
    """[(slug, [what is missing])] for the main creatures of a blender/code episode: 'in no shot', or no close-up
    (close, extreme-close, insert) and/or no vast shot (extreme-wide). A reuse_of shot without layers uses the layers
    of the shot it reuses."""
    prefixes = CREATURE_PREFIXES.get(method)
    if not prefixes or not shots:
        return []
    slugs = {r["slug"] for r in rows}
    out = []
    for r in rows:
        if not r.get("main") or not RE_SLUG.match(r["slug"]):
            continue
        sizes = set()
        for s in shots.values():
            codes = s.get("_codes") or (shots.get(s.get("reuse_of"), {}).get("_codes") or [])
            if creature_in_codes(r["slug"], codes, prefixes, slugs - {r["slug"]}):
                sizes.add(s.get("shot_size"))
        if not sizes:
            out.append((r["slug"], [f"in no shot (layers {' or '.join(p + r['slug'] for p in prefixes)})"]))
            continue
        miss = []
        if not sizes & set(CLOSE_SIZES):
            miss.append(f"no detail close-up ({', '.join(CLOSE_SIZES)})")
        if not sizes & set(VAST_SIZES):
            miss.append(f"no shot small in a vast landscape ({', '.join(VAST_SIZES)})")
        if miss:
            out.append((r["slug"], miss))
    return out


def check_creature_shots(ep_dir, meta, shots, rep):
    """WARN for every main creature (EPISODE.md `## Sinh vật của tập`) of a blender/code episode that lacks a close-up
    or a vast shot in shots.csv (rhythm rule of film-script, the DoP pass of stage 2b). Never an ERROR."""
    method = episode_method(meta)[0]
    if method not in CREATURE_PREFIXES or not shots:
        return
    try:
        _, body = split_front_matter(read_text(os.path.join(ep_dir, "EPISODE.md")))
    except (OSError, CheckError):
        return
    tab = read_creatures(body)
    if not tab:
        return
    for slug, miss in creature_coverage(tab["rows"], shots, method):
        rep.warn("shots.csv", f"main creature {slug}: {'; '.join(miss)} – each main creature needs one detail "
                              f"close-up and one shot small in a vast landscape (film-dop, CAMERA-BIBLE.md)")


# --- style frames (STYLE-FRAMES.md, docs/CONVENTIONS.md §5; issue #71) ----------------------------------------------
# Stage 3b of a blender/code episode: 5-8 style frames (one per chapter) made before mass production; the owner picks
# the reference frames ("khung chuẩn": one for the atmosphere, one per main creature) and the director records them in
# the `## Khung chuẩn đã duyệt` table of STYLE-FRAMES.md. status.py --gate G2 asks for it; check_episode only WARNs
# (episodes that passed G2 before this step existed keep validating).
STYLEFRAMES_FILE = "STYLE-FRAMES.md"
SF_FRAMES_HEADING = "## Khung"
SF_REF_HEADING = "## Khung chuẩn đã duyệt"
SF_REF_COLS = {"vai": "role", "khung": "frame", "ngày": "date"}
SF_ATMOSPHERE = {"không khí", "khong khi", "không-khí", "khong-khi", "atmosphere"}
SF_COUNT = (5, 8)
SF_WARN_STAGE = 4            # stage: 3 = 3a + 3b + 3 (film-pipeline §2); from the sample shot on, they are due
STYLEFRAME_METHODS = CREATURE_METHODS
RE_SF_DATE = re.compile(r"^(?:duyệt\s+|approved\s+)?(\d{4}-\d{2}-\d{2})(?![\d-])", re.I)
RE_SF_PLACEHOLDER = re.compile(r"^(?:[-–—?.…x]*|<.*>|(?:chờ|cho|tbd|todo|n/?a|none|chưa)\b.*)$", re.I)


def md_table(lines):
    """(header cells lower case, [row cells]) of the Markdown table in lines; the GFM delimiter row and empty rows
    are skipped. ([], []) when there is no table."""
    table = [l.strip() for l in lines if l.strip().startswith("|")]
    if not table:
        return [], []
    cells = lambda l: [c.strip() for c in l.strip().strip("|").split("|")]
    head = [" ".join(nfc(c).lower().split()).strip("`*") for c in cells(table[0])]
    rows = table[1:]
    if rows and all(RE_TABLE_SEP.match(c) for c in cells(rows[0]) if c):
        rows = rows[1:]
    return head, [r for r in (cells(l) for l in rows) if any(r)]


def read_style_frames(ep_dir):
    """STYLE-FRAMES.md of the episode folder: None when the file is missing, else {"frames": rows of the `## Khung`
    table, "refs": [{"role": "atmosphere" | <creature slug>, "frame", "date"}], "problems": [...]}.
    A reference row counts only with a role, a frame and a YYYY-MM-DD date that starts the Ngày cell (`duyệt
    2026-11-26` too; `chờ duyệt (dự kiến 2026-12-01)` is not approved). The frame must be an id or a file of the
    `## Khung` table (when it has rows) or a file in review/styleframes/; never a placeholder (chờ, -, ?, <…>)."""
    path = os.path.join(ep_dir, STYLEFRAMES_FILE)
    if not os.path.isfile(path):
        return None
    out = {"frames": 0, "refs": [], "problems": []}
    try:
        text = read_text(path)
    except (OSError, CheckError) as e:
        out["problems"].append(f"unreadable ({getattr(e, 'msg', e)})")
        return out
    fhead, frows = md_table(section_lines(text, SF_FRAMES_HEADING) or [])
    out["frames"] = len(frows)
    known = set()
    for col in ("id", "file"):
        if col in fhead:
            i = fhead.index(col)
            for r in frows:
                v = r[i].strip("` ") if i < len(r) else ""
                if v:
                    known |= {v, os.path.basename(v.replace("\\", "/"))}
    head, rows = md_table(section_lines(text, SF_REF_HEADING) or [])
    if not head:
        return out
    idx = {SF_REF_COLS[h]: i for i, h in enumerate(head) if h in SF_REF_COLS}
    missing = [k for k, v in SF_REF_COLS.items() if v not in idx]
    if missing:
        out["problems"].append(f"{SF_REF_HEADING}: column(s) {', '.join(missing)} missing "
                               "(header: | Vai | Khung | Ngày | Lời chủ dự án |)")
        return out
    for n, cells in enumerate(rows, 1):
        get = lambda k: cells[idx[k]].strip() if idx[k] < len(cells) else ""
        role = " ".join(nfc(get("role")).lower().strip("`* ").split())
        frame, date = get("frame").strip("` "), RE_SF_DATE.match(nfc(get("date")))
        if date:
            try:
                datetime.date.fromisoformat(date.group(1))
            except ValueError:
                date = None
        if role in SF_ATMOSPHERE:
            role = "atmosphere"
        else:
            role = role[2:] if role[:2] in ("a-", "c-", "m-") else role
            if not RE_SLUG.match(role):
                out["problems"].append(f"{SF_REF_HEADING} row {n}: Vai '{get('role')}' is neither 'không khí' nor a "
                                       "creature slug of ## Sinh vật của tập")
                continue
        if not frame or RE_SF_PLACEHOLDER.match(nfc(frame)):
            why = "no frame" if not frame else f"Khung '{frame}' is a placeholder"
        elif not date:
            why = f"Ngày '{get('date')}' does not start with a YYYY-MM-DD date"
        elif frows and frame not in known and not any(
                os.path.isfile(os.path.join(ep_dir, d, frame)) for d in ("review/styleframes", ".")):
            why = f"Khung '{frame}' is not an id or file of {SF_FRAMES_HEADING} nor a file in review/styleframes/"
        else:
            out["refs"].append({"role": role, "frame": frame, "date": date.group(1)})
            continue
        out["problems"].append(f"{SF_REF_HEADING} row {n} ({role}): {why}: not counted as approved")
    return out


def style_frame_gaps(sf, creature_rows):
    """What the style-frame approval still lacks: [] when STYLE-FRAMES.md records an atmosphere reference frame and
    one for every main creature of the creature table."""
    if sf is None:
        return [f"no {STYLEFRAMES_FILE}"]
    if not sf["refs"]:
        return [f"no approved reference frame in {SF_REF_HEADING}"]
    roles = {r["role"] for r in sf["refs"]}
    gaps = [] if "atmosphere" in roles else ["no atmosphere frame ('không khí')"]
    need = [r["slug"] for r in creature_rows or [] if r.get("main") and r["slug"] not in roles]
    if need:
        gaps.append(f"no reference frame for {', '.join(need)}")
    return gaps


def check_style_frames(ep_dir, meta, rep):
    """method blender/code: STYLE-FRAMES.md well-formed, 5-8 frames, the reference frames approved before G2
    (WARN from stage 4, the sample shot for G2: stage 3 holds 3a, 3b and 3 and the frames are made there; INFO once
    G2 is dated without them: the step did not exist then). Never an ERROR."""
    method = episode_method(meta)[0]
    sf = read_style_frames(ep_dir)
    if method not in STYLEFRAME_METHODS and sf is None:
        return
    stage = meta.get("stage") if isinstance(meta.get("stage"), int) else -1
    for msg in (sf or {}).get("problems", []):
        rep.warn(STYLEFRAMES_FILE, msg)
    if sf is not None and stage >= SF_WARN_STAGE and not SF_COUNT[0] <= sf["frames"] <= SF_COUNT[1]:
        rep.warn(STYLEFRAMES_FILE, f"{sf['frames']} frame(s) in the {SF_FRAMES_HEADING} table: "
                                   f"{SF_COUNT[0]}-{SF_COUNT[1]} expected (one per chapter)")
    if method not in STYLEFRAME_METHODS or stage < SF_WARN_STAGE:
        return
    try:
        _, body = split_front_matter(read_text(os.path.join(ep_dir, "EPISODE.md")))
        tab = read_creatures(body)
    except (OSError, CheckError):
        tab = None
    gaps = style_frame_gaps(sf, (tab or {}).get("rows"))
    if not gaps:
        return
    gates = meta.get("gates") if isinstance(meta.get("gates"), dict) else {}
    msg = (f"style frames not approved: {'; '.join(gaps)} – stage 3b before G2 "
           f"(templates/episode/{STYLEFRAMES_FILE}, film-pipeline §2.3)")
    if stage >= 5 and gates.get("G2"):
        rep.info(f"{STYLEFRAMES_FILE}: {msg} (G2 already dated)")
    else:
        rep.warn(STYLEFRAMES_FILE, msg)


def ledger_head(path, rep):
    """First line of ledger.csv (a BOM is not part of it), or None after reporting an unreadable file."""
    try:
        return read_text(path).split("\n", 1)[0].strip()
    except CheckError as e:
        rep.error("media/ledger.csv", e.msg)
        return None


def required_rows(prompt_rows, stage):
    """prompts.csv rows whose file must be on disk.

    Rows are written at stage 3, before anything is generated. A row is required once it was accepted
    (approved=yes) or generated and not judged yet (non-empty `usage`, `approved` empty); every other row
    from stage FILES_REQUIRED_FROM_STAGE (7, compositing). A rejected row (approved=no) is never required:
    it is the record of a paid image, not an input of the film."""
    late = isinstance(stage, int) and stage >= FILES_REQUIRED_FROM_STAGE
    return [r for r in prompt_rows or []
            if r["approved"] != "no" and (r["approved"] == "yes" or r["usage"] or late)]


def check_listed_files(media, meta, prompt_rows, rep):
    """Every required prompts.csv file (required_rows) must exist in plates/ (images) or clips/ (clips).

    A missing file that is not required yet is a pending row: one INFO line lists them, so stage 3-6
    checks (and gate G2) can pass. Missing rejected files get one INFO line as well.
    """
    stage = meta.get("stage") if meta else None
    required = {id(r) for r in required_rows(prompt_rows, stage)}
    pending, rejected = [], []
    for r in prompt_rows or []:
        f = r["file"]
        sub = "plates" if RE_LAYER_FILE.match(f) else "clips" if RE_CLIP_FILE.match(f) else None
        if sub is None or os.path.isfile(os.path.join(media, sub, f)):
            continue
        if r["approved"] == "no":
            rejected.append(f)
        elif id(r) in required:
            why = ("approved=yes" if r["approved"] == "yes" else "usage is filled" if r["usage"]
                   else f"episode is at stage {stage}")
            rep.error("prompts.csv", f"{f} listed but not found in {os.path.join(media, sub)} ({why})")
        else:
            pending.append(f)
    if pending:
        rep.info(f"prompts.csv: {len(pending)} file(s) not generated yet (no usage, not approved; required from "
                 f"stage {FILES_REQUIRED_FROM_STAGE}): {', '.join(pending)}")
    if rejected:
        rep.info(f"prompts.csv: {len(rejected)} rejected file(s) not on disk (approved=no): {', '.join(rejected)}")


def check_media_missing(media, meta, prompt_rows, rep):
    """The media folder is absent (check_media said so): from compositing on that is not a detail."""
    stage = meta.get("stage") if meta else None
    n = len(required_rows(prompt_rows, stage))
    if episode_method(meta)[0] == "blender" and isinstance(stage, int) and stage >= FILES_REQUIRED_FROM_STAGE:
        rep.error("media", f"media folder missing at stage {stage}: the Blender renders (renders3d/) are needed for "
                           f"compositing; pull the shot bundles from Drive and unzip them in "
                           f"out/<project>/<id>/ (they restore renders3d/<shot>/)")
        return
    if n and isinstance(stage, int) and stage >= FILES_REQUIRED_FROM_STAGE:
        rep.error("media", f"media folder missing but {n} approved/generated file(s) are required: "
                           f"pull the shot bundles from Drive (drive_link)")
    else:
        rep.info(f"media: {n} approved/generated file(s) of prompts.csv not checked (media folder missing)")


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


RE_RENDER_VERSION = re.compile(r"_(draft|final)_v(\d{2})\.mp4$")
DEFAULT_FORMAT = (1920, 1080, 24.0)
FPS_TOL = 0.01


def series_format(ep_dir, rep=None):
    """(width, height, fps) from `format:` in the front matter of SERIES.md in the episode's parent folder
    (docs/CONVENTIONS.md §4), else 1920x1080 at 24 fps. With rep, one INFO line says which format the renders
    are judged against and where it came from (a damaged SERIES.md of a vertical series must not stay silent)."""
    import yaml
    path = os.path.join(os.path.dirname(os.path.abspath(ep_dir)), "SERIES.md")
    why = "format: missing or not {width, height, fps} with positive numbers"
    try:
        fm, _ = split_front_matter(read_text(path))
        f = yaml.safe_load(fm or "")["format"]
        w, h, fps = f["width"], f["height"], f["fps"]
        if all(isinstance(x, int) and not isinstance(x, bool) and x > 0 for x in (w, h)) and is_cap(fps) and fps > 0:
            if rep:
                rep.info(f"probe: series format {w}x{h} at {float(fps):g} fps (SERIES.md)")
            return w, h, float(fps)
    except FileNotFoundError:
        why = "no SERIES.md in the project folder"
    except (KeyError, TypeError):
        pass                                     # readable, but no usable format: block
    except (OSError, CheckError, yaml.YAMLError, ValueError) as e:
        why = f"SERIES.md unreadable: {getattr(e, 'msg', None) or (str(e).splitlines() or [type(e).__name__])[0]}"
    if rep:
        w, h, fps = DEFAULT_FORMAT
        rep.info(f"probe: series format {w}x{h} at {fps:g} fps (default: {why})")
    return DEFAULT_FORMAT


def probe_media(media, meta, rep, fmt=None):
    """--probe: ffprobe numbers for clips/*.mp4 and the newest draft and final in renders/, loudness for the final.

    Versions are never deleted (docs/CONVENTIONS.md §2), so only the highest version of each kind is judged;
    an older one gets one INFO line and is not measured."""
    if not (shutil.which("ffprobe") and shutil.which("ffmpeg")):
        rep.error("probe", "ffprobe/ffmpeg not found on PATH: clips and renders not measured")
        return
    length = meta.get("length_s") if meta else None
    fw, fh, ffps = fmt or DEFAULT_FORMAT
    found = 0
    for sub in ("clips", "renders"):
        d = os.path.join(media, sub)
        names = sorted(n for n in os.listdir(d) if n.endswith(".mp4")) if os.path.isdir(d) else []
        versions = {n: RE_RENDER_VERSION.search(n) for n in names} if sub == "renders" else {}
        newest = {}
        for m in filter(None, versions.values()):
            newest[m.group(1)] = max(newest.get(m.group(1), 0), int(m.group(2)))
        for name in names:
            found += 1
            where = f"media/{sub}/{name}"
            m = versions.get(name)
            kind = m.group(1) if m else None
            if m and int(m.group(2)) < newest[kind]:
                rep.info(f"probe {where}: superseded by v{newest[kind]:02d}, not measured")
                continue
            final, draft = kind == "final", kind == "draft"
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
            if final:
                if (w, h) != (fw, fh) or not pr["fps"] or abs(pr["fps"] - ffps) > FPS_TOL:
                    if pr["fps"] and abs(pr["fps"] - ffps) > FPS_TOL and fps == f"{ffps:.3g} fps":
                        # 23.976 must not print as '24 fps is not ... 24 fps'
                        fps = f"{pr['fps']:.3f} fps"
                    rep.error(where, f"{w}x{h} at {fps} is not the series format {fw}x{fh} at {ffps:g} fps")
                if not pr["audio"]:
                    rep.error(where, f"final render has no audio stream (master must be {LUFS_TARGET:g} LUFS)")
                elif lufs is not None and abs(lufs - LUFS_TARGET) > LUFS_TOL:
                    rep.error(where, f"integrated loudness {lufs:.1f} LUFS outside {LUFS_TARGET:g} +-{LUFS_TOL:g} LUFS")
            elif draft:
                if (w, h) != (fw // 2, fh // 2):
                    rep.warn(where, f"{w}x{h} is not the draft size {fw // 2}x{fh // 2} (half the series format)")
                if not pr["audio"]:
                    rep.warn(where, "draft render has no audio stream")
            elif not is_16_9(w, h):
                rep.warn(where, f"{w}x{h} is not 16:9")
            if final and diff is None:           # the length rule would pass in silence
                rep.warn(where, "duration not checked: " + ("ffprobe reports no duration" if pr["duration"] is None
                                                            else "EPISODE.md has no numeric length_s"))
            if diff is not None and abs(diff) > LENGTH_TOL_S:
                (rep.error if final else rep.warn)(
                    where, f"duration {pr['duration']:.2f} s differs from length_s {fmt_s(length)} s "
                           f"by {diff:+.2f} s (> {LENGTH_TOL_S:g} s)")
    if not found:
        rep.info(f"probe: no mp4 in {os.path.join(media, 'clips')} or {os.path.join(media, 'renders')}")


def cmd_episode(a, rep=None):
    rep = rep or Report()
    ep_dir = a.episode
    if not os.path.isdir(ep_dir):
        print(f"ERROR {ep_dir}: not a directory")
        return 1
    meta = check_front_matter(ep_dir, rep) or {}
    check_stage_gates(meta, rep)
    check_budget(ep_dir, meta, rep)
    shots = check_shots(ep_dir, meta, rep)
    check_shots3d(ep_dir, meta, shots, rep)
    check_assets(ep_dir, meta, rep)
    check_creatures(ep_dir, meta, rep)
    check_creature_shots(ep_dir, meta, shots, rep)
    check_style_frames(ep_dir, meta, rep)
    check_script(ep_dir, meta, rep)
    files = check_prompts(ep_dir, meta, shots, rep)
    media = a.media
    if media is None and isinstance(meta.get("media"), str):
        media = meta["media"] if os.path.isabs(meta["media"]) else os.path.join(LAB, meta["media"])
    if check_media(media, meta, files, rep, shots) and a.probe:
        probe_media(media, meta, rep, series_format(ep_dir, rep))
    if not (media and os.path.isdir(media)):
        check_media_missing(media, meta, files, rep)
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
    except CheckError as e:
        rep.error("style.yaml", e.msg)
        return
    except (yaml.YAMLError, ValueError) as e:
        rep.error("style.yaml", f"not valid YAML: {str(e).splitlines()[0]}")
        return
    if not isinstance(y, dict):
        rep.error("style.yaml", "must be a mapping")
        return
    W = "style.yaml"
    engine = y.get("engine", "image")
    if engine not in STYLE_ENGINES:
        rep.error(W, f"engine {engine!r} must be image, code or blender")
        engine = "image"
    no_model = engine in ("code", "blender")     # no image model: no prompt, matte, layers or models keys
    required = STYLE_REQUIRED_BLENDER if engine == "blender" else STYLE_REQUIRED_CODE if no_model else STYLE_REQUIRED
    optional = STYLE_OPTIONAL_CODE if no_model else STYLE_OPTIONAL + ["engine"]
    for k in required:
        if k not in y:
            rep.error(W, f"required key '{k}' missing")
    for k in optional:
        if k not in y and k not in ("engine", "name_en"):
            rep.warn(W, f"optional key '{k}' missing (inherited from base recipe?)")
    for k in y:
        if k not in required and k not in optional and k not in STYLE_EXTRA:
            rep.warn(W, f"unknown key '{k}'" + (f" (not used by an engine: {engine} style)" if no_model else ""))
    if "grade" in y:
        check_grade(y["grade"], rep)
    if "id" in y:
        if y["id"] != sid:
            rep.error(W, f"id '{y['id']}' != folder name '{sid}'")
        if not isinstance(y["id"], str) or not RE_SLUG.match(y["id"]):
            if sid.startswith("_") and y["id"] == sid:   # styles/_template: renamed when copied
                rep.warn(W, f"id '{sid}' is a template id; set id = new folder name after copying")
            else:
                rep.error(W, f"id {y['id']!r} must be kebab-case ASCII")
    if "status" in y and (not isinstance(y["status"], str) or y["status"] not in STYLE_STATUS):
        rep.error(W, f"status {y['status']!r} must be stable or draft")
    if "base" in y and y["base"] is not None and not isinstance(y["base"], str):
        rep.error(W, "base must be a recipe name (e.g. cinecode:ink-wash) or null")
    for k in ("name", "style_block", "light"):
        if k in y and (not isinstance(y[k], str) or not y[k].strip()):
            rep.error(W, f"{k} must be a non-empty string")
    if "negative" in y and (not isinstance(y["negative"], list) or not all(isinstance(x, str) for x in y["negative"])):
        rep.error(W, "negative must be a list of strings")
    if engine == "code" and "render" in y:
        check_render(y["render"], rep)
    elif engine == "blender" and "render" in y:
        check_render_blender(y["render"], rep)
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
                    rep.error(W, f"layers.{code}: invalid layer code (L1-L4, L4b-L4z, P, FX)")
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
            if not isinstance(m, str):
                rep.error(W, f"motion entry {m!r} must be a module id string")
            elif m not in known_motions():
                rep.warn(W, f"motion id '{m}' is not in tools/compose/motions.json")
    if not no_model:
        check_style_prompts(style_dir, rep)
    if not os.path.isfile(os.path.join(style_dir, "STYLE.md")):
        rep.warn("STYLE.md", "missing")


def check_grade(g, rep):
    """The grade: block of a style pack, with the schema of tools/compose/grade.py (ERROR per problem)."""
    import importlib.util
    path = os.path.join(LAB, "tools", "compose", "grade.py")
    try:
        spec = importlib.util.spec_from_file_location("film_grade", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except (OSError, ImportError) as e:
        rep.warn("style.yaml", f"grade: not checked (tools/compose/grade.py cannot be loaded: {e})")
        return
    for e in mod.validate(g):
        rep.error("style.yaml", e)


def style_engine(style_dir):
    """engine of a style pack ('image' when the key is missing), or None when style.yaml cannot be read."""
    import yaml
    try:
        y = yaml.safe_load(read_text(os.path.join(style_dir, "style.yaml"))) or {}
    except Exception:
        return None
    return y.get("engine", "image") if isinstance(y, dict) else None


def known_looks():
    """(geometry looks {id: engine}, post ids) from tools/toon/looks.json, or None when it is missing."""
    try:
        with open(os.path.join(LAB, "tools", "toon", "looks.json"), encoding="utf-8") as f:
            d = json.load(f)
        return {k: v.get("engine") for k, v in d["looks"].items()}, set(d["posts"])
    except (OSError, ValueError, KeyError, AttributeError):
        return None


RE_COLOR = re.compile(r"^(#[0-9A-Fa-f]{6}|rgba?\([\d.,\s]+\))$")


def check_render(r, rep):
    """The render block of an engine: code style pack (docs/CONVENTIONS.md §3)."""
    W = "style.yaml"
    if not isinstance(r, dict):
        rep.error(W, "render must be a mapping {engine, look, post, hold, ...}")
        return
    for k in r:
        if k not in RENDER_KEYS:
            rep.warn(W, f"render: unknown key '{k}'")
    eng, look = r.get("engine"), r.get("look")
    if eng not in RENDER_ENGINES:
        rep.error(W, f"render.engine {eng!r} must be canvas2d or three")
    known = known_looks()
    if known:
        looks, posts = known
        if look not in looks:
            rep.error(W, f"render.look {look!r} is not a geometry look of tools/toon/looks.json ({', '.join(sorted(looks))})")
        elif eng in RENDER_ENGINES and looks[look] != eng:
            rep.error(W, f"render.engine {eng} does not match look {look} (engine {looks[look]})")
        post = r.get("post", [])
        if not isinstance(post, list):
            rep.error(W, "render.post must be a list of post ids or {id: ..., options}")
        else:
            for q in post:
                pid = q.get("id") if isinstance(q, dict) else q
                if pid not in posts:
                    rep.error(W, f"render.post {pid!r} is not a post of tools/toon/looks.json ({', '.join(sorted(posts))})")
    hold = r.get("hold")
    if hold is not None and (isinstance(hold, bool) or not isinstance(hold, int) or not 1 <= hold <= 4):
        rep.error(W, f"render.hold {hold!r} must be 1 (24 drawings/s), 2 (on twos), 3 or 4")
    pal = r.get("palette")
    if pal is not None:
        if not isinstance(pal, dict):
            rep.error(W, "render.palette must be a mapping name -> colour")
        else:
            for name, c in pal.items():
                if not isinstance(c, str) or not RE_COLOR.match(c):
                    rep.error(W, f"render.palette.{name} = {c!r} is not #RRGGBB or rgba(...)")
    for k in ("opts", "camera", "env"):
        if k in r and not isinstance(r[k], dict):
            rep.error(W, f"render.{k} must be a mapping")


def blender_looks():
    """Look ids of tools/blender/looks.json (package P2) when it is readable, else the four looks of the design
    (BLENDER_LOOKS). The registry may map id -> spec, hold a "looks" mapping or list, or be a list of ids/objects."""
    try:
        with open(os.path.join(LAB, "tools", "blender", "looks.json"), encoding="utf-8") as f:
            reg = json.load(f)
    except (OSError, ValueError):
        return set(BLENDER_LOOKS)
    if isinstance(reg, dict) and "looks" in reg:
        reg = reg["looks"]
    if isinstance(reg, dict):
        return set(reg)
    if isinstance(reg, list):
        return {x.get("id") if isinstance(x, dict) else x for x in reg} - {None}
    return set(BLENDER_LOOKS)


def check_render_blender(r, rep):
    """The render block of an engine: blender style pack (docs/CONVENTIONS.md §3): look, palette, line, mist, engine."""
    W = "style.yaml"
    if not isinstance(r, dict):
        rep.error(W, "render must be a mapping {look, palette, line, mist, engine}")
        return
    for k in r:
        if k not in BLENDER_RENDER_KEYS:
            rep.warn(W, f"render: unknown key '{k}' (engine: blender takes {', '.join(sorted(BLENDER_RENDER_KEYS))})")
    looks = blender_looks()
    if r.get("look") not in looks:
        rep.error(W, f"render.look {r.get('look')!r} is not a Blender look ({', '.join(sorted(looks))})")
    eng = r.get("engine", "eevee")
    if eng not in BLENDER_RENDER_ENGINES:
        rep.error(W, f"render.engine {eng!r} must be eevee or cycles")
    line = r.get("line")
    if line is not None and (isinstance(line, bool) or not is_cap(line)):
        rep.error(W, f"render.line {line!r} must be a line width >= 0 (0 = no line art)")
    mist = r.get("mist")
    if mist is not None and (isinstance(mist, bool) or not is_cap(mist) or mist > 1):
        rep.error(W, f"render.mist {mist!r} must be a number 0-1")
    pal = r.get("palette")
    if pal is not None:
        if not isinstance(pal, dict):
            rep.error(W, "render.palette must be a mapping name -> \"#RRGGBB\"")
        else:
            for name, c in pal.items():
                if not isinstance(c, str) or not RE_HEX.match(c):
                    rep.error(W, f"render.palette.{name} = {c!r} is not #RRGGBB")


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
            rep.error(W, f"{where}: invalid layer code (L1-L4, L4b-L4z, P, FX)")
        if not isinstance(spec, dict):
            rep.error(W, f"{where} must be a mapping")
            continue
        m = spec.get("method")
        if not isinstance(m, str) or m not in MATTE_METHODS:
            rep.error(W, f"{where}.method {m!r} not in {'|'.join(sorted(MATTE_METHODS))}")
        else:
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
        try:
            text = read_text(os.path.join(d, f))
        except CheckError as e:
            rep.error(f"prompts/{f}", e.msg)
            continue
        if not text.strip():
            rep.error(f"prompts/{f}", "empty")
        for ph in re.findall(r"\{([^{}\n]*)\}", text):
            if ph not in PLACEHOLDERS:
                rep.error(f"prompts/{f}", f"placeholder {{{ph}}} not allowed (only {', '.join('{%s}' % p for p in sorted(PLACEHOLDERS))})")
        if "{style_block}" not in text:
            rep.warn(f"prompts/{f}", "does not use {style_block} (it should open every image prompt)")


def cmd_style(a, rep=None):
    rep = rep or Report()
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
    e = sp.add_parser("episode", help="check an episode folder projects/<project>/<ep<NN>|q<NN>-t<NN>>-<slug>")
    e.add_argument("episode")
    e.add_argument("--media", default=None, help="media folder out/<project>/<id> (default: EPISODE.md media:)")
    e.add_argument("--probe", action="store_true",
                   help="measure clips/renders with ffprobe and final renders' loudness with ffmpeg ebur128")
    e.add_argument("--out", default=None, help="also write the report here (relative = inside the episode folder)")
    s = sp.add_parser("style", help="check a style pack styles/<id>")
    s.add_argument("style")
    a = p.parse_args(argv)
    rep = Report()
    try:
        return cmd_episode(a, rep) if a.cmd == "episode" else cmd_style(a, rep)
    except Exception as e:   # a bug or an input nobody foresaw: still a report with what was found, not a traceback
        rep.error("internal", f"{type(e).__name__}: {e}")
        target = a.episode if a.cmd == "episode" else a.style
        out = rep.text(f"check_episode {a.cmd} {os.path.normpath(target)}")
        sys.stdout.write(out)
        if getattr(a, "out", None):
            dest = a.out if os.path.isabs(a.out) else os.path.join(target, a.out)
            try:
                os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
                with open(dest, "w", encoding="utf-8") as f:
                    f.write(out)
                print(f"written {dest}")
            except OSError as oe:
                print(f"ERROR {dest}: report not written: {oe}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
