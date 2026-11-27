#!/usr/bin/env python3
"""Concept chain for a creature (stage 3a, film-pipeline §2.2): text-to-image -> edit -> contact sheet -> approve.

  python tools/concept.py gen <DESIGN-OPTIONS.md | jobs.json> --slug S --out-dir DIR --ledger L
                         [--n 2] [--seed-start 1001] [--only a,b] [--size 1664x928] [--turbo] [--version 1]
                         [--review BUILD] [--dry-run]
  python tools/concept.py edit <image.png ...> --ledger L (--instruction TEXT | --options DESIGN-OPTIONS.md)
                         [--ref R.png ...] [--lightning 0|4|8] [--denoise 1.0] [--steps N] [--cfg C] [--seed N ...]
                         [--size WxH] [--redo] [--review BUILD] [--dry-run]
  python tools/concept.py sheet <dir | image.png ...> [--out SHEET.png] [--cell 480] [--cols 3]
  python3 tools/concept.py approve <slug> <image.png> --episode projects/<project>/<episode dir>
                         [--date YYYY-MM-DD] [--quote "lời người dùng"] [--name "Tên"] [--dry-run]

An orchestrator: every image comes from `python tools/comfy/comfy.py run qwen-t2i` (gen) or `run qwen-edit` (edit), one
subprocess per image (each takes the lab's GPU lock, writes its own ledger row, cost 0, and its <out>.json sidecar).
All but the last call of a batch get --keep-models; the last frees the VRAM. A call that exits non-zero stops the
batch (never retried: exit 1 = the job was queued and failed, see its ledger row) and `comfy.py free` unloads what the
earlier calls kept. gen --turbo (cfg 1) sends no negative prompt. edit --lightning 0 = no LoRA (40 steps, cfg 4). --dry-run prints the plan and calls
nothing. Only the main session or an agent in a local session on the owner's PC runs gen/edit (ComfyUI, GPU).

Names (docs/CONVENTIONS.md §2, film-pipeline §2.2; default folder out/<project>/characters/<slug>/concept/):
  <slug>_<dir>_s<seed>_v<NN>.png          gen: direction <dir>, seed, round --version NN
  <slug>_<dir>_s<seed>_v<NN>_e<NN>.png    edit of that image (next free e<NN>; an edit of an edit gets the next one too)
  <slug>_sheet_v<NN>.png                  sheet (next free version)
gen skips an image whose file exists (resume); a new round of prompts = --version 2. edit records each edit in
concept_edits.json beside the images: the same source, instruction, seed and settings again = skipped (--redo makes
another version).

Accepted options files (gen; edit --options reads the `Edit EN` of the image's direction):
  Markdown: one `### <dir>` heading per direction (`### a`, `### a – Phượng thời Lý`, `### Hướng b: ...`); <dir> is the
    first word after an optional Hướng/Direction/Option/Phương án, lower case, [a-z0-9-]. In the section (up to the next
    heading of level 1-3): a line `Prompt EN: <text>` (also `- **Prompt EN:** <text>`, `Prompt:`), or the label alone
    (also the template's `**Prompt (EN)** (qwen-t2i):`) followed by a fenced block; optional `Negative EN:` and
    `Edit EN:` the same way. An unlabelled fenced block is the prompt when there is no Prompt line. HTML comments are ignored; a direction without a prompt is skipped (WARN).
    Also read: a Markdown table whose header has a `Hướng` (or `Direction`, `id`) column and a `Prompt` column,
    optional `Negative` and `Edit` columns. Template: templates/research/DESIGN-OPTIONS.md.
  JSON: {"slug": "...", "size": "1664x928", "negative": "...", "seeds": [7, 9],
         "directions": [{"id": "a", "prompt": "...", "negative": "...", "edit": "...", "seeds": [...]}]}
    or just the list of directions. Command line flags win over the file.

approve writes `## Concept đã duyệt` into characters/<slug>/CHARACTER.md (the episode folder's when it has one, else the
project's; created when missing) and the Concept cell `duyệt <date> <file>` of the slug's row in the `## Sinh vật của
tập` table of EPISODE.md (a missing row is added: Chính có, Ảnh sách chờ). Other rows and sections are never touched;
the same file twice changes nothing. The result is read back with tools/check_episode.py (what status.py --gate G2 uses).

Exit codes: 0 ok · 2 refused here, nothing called · otherwise the exit code of the comfy.py call that failed.
Lesson (SHK Q1·T3): text-only Qwen-Image drops unusual details (a human face on a beast, three legs, one horn) and
trigger phrases pull their own anatomy ("water buffalo" -> two horns): leave such words out of the prompt and fix
with an edit; counts (horns, legs, eyes) are fixed in the 3D model, not by editing concepts.
Generic code adapted from the owner's SHK Q1·T3 qwen-edit test scripts (make_jobs.py, sheet.py; no project content).
"""
import argparse, datetime, hashlib, json, os, re, subprocess, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
COMFY = os.path.join(HERE, "comfy", "comfy.py")
REFUSED = 2
SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
RE_SLUG = re.compile(rf"^{SLUG}$")
RE_NAME = re.compile(rf"^(?P<slug>{SLUG})_(?P<dir>{SLUG})_s(?P<seed>\d+)_v(?P<v>\d{{2,}})(?P<edits>(?:_e\d{{2,}})*)\.png$")
RE_EDIT_TAIL = re.compile(r"_e(\d{2,})$")
EDITS_FILE = "concept_edits.json"
DEFAULT_SIZE = "1664x928"
LABELS = {"prompt": "prompt", "negative": "negative", "edit": "edit"}
# `Prompt EN: x`, `- **Prompt EN:** x`, `Prompt:`, and the template's `**Prompt (EN)** (qwen-t2i):` /
# `**Edit (EN)** (qwen-edit) – nền `x.png`:` (a parenthetical and a dash note before the colon are ignored).
RE_LABEL = re.compile(r"^\s*(?:[-*+]\s+)?(?:\*\*|__)?\s*(prompt|negative|edit)(?:\s+en|\s*\(en\))?"
                      r"(?:\s*(?:\*\*|__))?(?:\s*\([^)]*\))*(?:\s*(?:\*\*|__))?(?:\s+[–—-][^:]*)?"
                      r"\s*:\s*(?:\*\*|__)?\s*(.*)$", re.I)
RE_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
RE_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*([\w-]*)")
DIR_PREFIX = re.compile(r"^(?:hướng|huong|direction|option|phương án|phuong an)\s+", re.I)
CONTROL = re.compile(r"[\x00-\x1f\x7f\u2028\u2029]")       # line breaks and other control characters
CONCEPT_HEADING = "## Concept đã duyệt"
CREATURE_HEADING = "## Sinh vật của tập"


class Refused(Exception):
    """Exit 2: nothing was called or written."""


def nfc(s):
    return unicodedata.normalize("NFC", s)


def say(msg):
    print(msg, flush=True)


def warn(msg):
    print(f"concept: WARN {msg}", file=sys.stderr, flush=True)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_cmd(argv):
    """Run one tool (its output goes straight to the terminal); -> exit code. Tests replace this function."""
    return subprocess.run(argv).returncode


def comfy_argv(workflow, args):
    return [sys.executable, COMFY, "run", workflow] + args


def show(argv):
    """The command as one line (for --dry-run and the log), long prompts shortened."""
    out = []
    for a in argv[1:] if argv and argv[0] == sys.executable else argv:
        if out and out[-1] in ("--prompt", "--negative"):      # long text: shortened; paths stay whole
            a = " ".join(a.split())
            a = a if len(a) <= 90 else a[:87] + "..."
        out.append(a if re.fullmatch(r"[\w./\\:=,+-]+", a) else '"' + a.replace('"', '\\"') + '"')
    return "python " + " ".join(out)


def free_vram():
    """After a batch stopped at a failure: `comfy.py free` (POST /free only), since the calls before it (and the
    failed one, when it had --keep-models) left their models in VRAM. Best effort: its exit code is only reported."""
    code = run_cmd([sys.executable, COMFY, "free"])
    if code:
        print(f"concept: comfy.py free exited {code}: ComfyUI may still hold the models in VRAM "
              "(python tools/comfy/comfy.py free)", file=sys.stderr)


def run_batch(jobs, dry_run, on_ok=None):
    """jobs: [(label, argv)] of comfy.py calls; --keep-models on all but the last. -> exit code (stops at the first
    failure, never retries; then frees the VRAM the --keep-models calls kept). on_ok(i) after each call that worked."""
    for i, (label, argv) in enumerate(jobs):
        keep = i < len(jobs) - 1
        argv = argv + (["--keep-models"] if keep else [])
        say(f"[{i + 1}/{len(jobs)}] {label}\n  {show(argv)}")
        if dry_run:
            continue
        code = run_cmd(argv)
        if code:
            print(f"concept: stopped: comfy.py exited {code} on {label} (not retried; exit 1 = see its ledger row)",
                  file=sys.stderr)
            if keep or i:
                free_vram()
            return code
        if on_ok:
            on_ok(i)
    if dry_run:
        say("dry-run: nothing called, no ledger row")
    return 0


# ------------------------------------------------------------------------------------------------ options files
def strip_comments(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def dir_id(title):
    t = DIR_PREFIX.sub("", nfc(title).strip().strip("*_`").strip())
    word = re.split(r"[\s:.)–—,]+", t, maxsplit=1)[0] if t else ""
    word = word.strip("*_`(").lower()
    return word if RE_SLUG.match(word) else None


def parse_sections(lines):
    """Markdown `### <dir>` sections -> [{"id", "prompt", "negative", "edit"}] (raw, unchecked)."""
    out, cur, fence, pending, block, para = [], None, None, None, [], None
    for line in lines:
        m = RE_FENCE.match(line)
        if fence is None and m:
            para = None
            fence = m.group(1)
            info = m.group(2).lower()
            block = []
            if cur is not None and pending is None:
                for key in LABELS:
                    if info.startswith(key):
                        pending = key
            continue
        if fence is not None:
            if line.strip().startswith(fence[0] * len(fence)) and not line.strip().strip(fence[0]):
                fence = None
                if cur is not None:
                    key = pending or ("prompt" if "prompt" not in cur and "_fenced" not in cur else None)
                    if key and key not in cur:
                        cur[key] = "\n".join(block).strip()
                    cur["_fenced"] = True
                pending = None
            else:
                block.append(line)
            continue
        h = RE_HEADING.match(line)
        if h:
            para = None
        if h and len(h.group(1)) <= 3:
            cur = None
            pending = None
            if len(h.group(1)) == 3:
                did = dir_id(h.group(2))
                if did:
                    cur = {"id": did}
                    out.append(cur)
                else:
                    warn(f"heading '{line.strip()}': no direction id ([a-z0-9-]) after ###; skipped")
            continue
        if cur is None:
            continue
        lm = RE_LABEL.match(line)
        if lm:
            key = LABELS[lm.group(1).lower()]
            val = lm.group(2).strip().strip("*_").strip()
            para = None
            if val:
                if key not in cur:
                    cur[key] = val.strip("`").strip()
                    para = key                      # following lines up to a blank line continue it
                pending = None
            else:
                pending = key
            continue
        if not line.strip():
            para = None
            continue
        if pending and pending not in cur:          # `Prompt EN:` alone, then a plain paragraph
            cur[pending] = line.strip()
            para, pending = pending, None
        elif para:
            cur[para] += " " + line.strip()
    for d in out:
        d.pop("_fenced", None)
    return out


def table_rows(lines):
    """Directions from Markdown tables with a direction column and a Prompt column."""
    out, head = [], None
    cells = lambda l: [c.strip() for c in l.strip().strip("|").split("|")]
    for line in lines + [""]:
        if not line.strip().startswith("|"):
            head = None
            continue
        row = cells(line)
        if head is None:
            names = [nfc(c).strip("*` ").lower() for c in row]
            col = {}
            for i, n in enumerate(names):
                if n in ("hướng", "huong", "direction", "id") and "id" not in col:
                    col["id"] = i
                elif n.startswith("prompt") and "prompt" not in col:
                    col["prompt"] = i
                elif n.startswith("negative") and "negative" not in col:
                    col["negative"] = i
                elif n.startswith("edit") and "edit" not in col:
                    col["edit"] = i
            head = col if "id" in col and "prompt" in col else {}
            continue
        if not head or all(re.fullmatch(r":?-+:?", c) for c in row if c):
            continue
        rec = {k: (row[i].strip("`").strip() if i < len(row) else "") for k, i in head.items()}
        did = dir_id(rec.pop("id"))
        if did:
            out.append(dict({k: v for k, v in rec.items() if v}, id=did))
    return out


def parse_markdown(text):
    lines = strip_comments(nfc(text)).splitlines()
    dirs = parse_sections(lines)
    if not dirs:                                    # an older DESIGN-OPTIONS.md: `## A. "<tên>"` directions
        for line in lines:
            h = RE_HEADING.match(line)
            if h and len(h.group(1)) == 2 and re.match(r"(?:hướng\s+)?[a-z]\b\s*[.:)–—-]", nfc(h.group(2)), re.I):
                warn(f"heading '{line.strip()}': a direction needs a level-3 heading (### a – <tên hướng>)")
    seen = {d["id"] for d in dirs}
    dirs += [d for d in table_rows(lines) if d["id"] not in seen]
    return {"directions": dirs}


def load_options(path):
    """{"slug"?, "size"?, "negative"?, "seeds"?, "directions": [{"id", "prompt", "negative"?, "edit"?, "seeds"?}]}"""
    try:
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise Refused(f"{path}: cannot read it ({type(e).__name__})")
    if path.lower().endswith(".json"):
        try:
            data = json.loads(text)
        except ValueError as e:
            raise Refused(f"{path}: not valid JSON ({e})")
        if isinstance(data, list):
            data = {"directions": data}
        if not isinstance(data, dict) or not isinstance(data.get("directions"), list):
            raise Refused(f"{path}: a jobs JSON is a list of directions or {{\"directions\": [...]}}")
    else:
        data = parse_markdown(text)
    dirs, ids = [], set()
    for i, d in enumerate(data["directions"]):
        if not isinstance(d, dict):
            raise Refused(f"{path}: direction {i + 1} is not an object")
        did = str(d.get("id", "")).strip().lower()
        if not RE_SLUG.match(did):
            raise Refused(f"{path}: direction id {d.get('id')!r} is not [a-z0-9-] (it goes into the file name)")
        if did in ids:
            raise Refused(f"{path}: direction '{did}' is given twice")
        ids.add(did)
        if not str(d.get("prompt") or "").strip():
            warn(f"{path}: direction '{did}' has no prompt: skipped")
            continue
        dirs.append(dict(d, id=did, prompt=str(d["prompt"]).strip()))
    data["directions"] = dirs
    return data


# ------------------------------------------------------------------------------------------------ gen
def seeds_arg(text):
    return [int(x) for x in str(text).split(",") if x.strip()]


def cmd_gen(a):
    opts = load_options(a.options)
    slug = a.slug or opts.get("slug")
    if not slug or not RE_SLUG.match(str(slug)):
        raise Refused(f"--slug {slug!r}: give the creature's slug (characters/<slug>/, lower case [a-z0-9-])")
    dirs = opts["directions"]
    if a.only:
        want = [x.strip().lower() for x in a.only.split(",") if x.strip()]
        unknown = [x for x in want if x not in {d["id"] for d in dirs}]
        if unknown:
            raise Refused(f"--only {','.join(unknown)}: not a direction of {a.options} "
                          f"({', '.join(d['id'] for d in dirs) or 'none'})")
        dirs = [d for d in dirs if d["id"] in want]
    if not dirs:
        raise Refused(f"{a.options}: no direction with a prompt (format: tools/concept.py --help)")
    if (a.n is not None and a.n < 1) or a.version < 1:
        raise Refused("--n and --version must be >= 1")
    ledger = a.ledger or os.environ.get("FILM_LEDGER")
    if not ledger:
        raise Refused("--ledger L.csv (the episode's ledger; comfy.py writes one row per image, cost 0)")
    size = a.size or opts.get("size")
    jobs, skipped, dropped = [], 0, set()
    for d in dirs:
        listed = d.get("seeds") or opts.get("seeds")
        if listed and a.seed_start is None:
            seeds = [int(s) for s in listed][:a.n] if a.n else [int(s) for s in listed]
        else:
            seeds = [(1001 if a.seed_start is None else a.seed_start) + k for k in range(a.n or 2)]
        negative = d.get("negative") or opts.get("negative")
        if negative and a.turbo:            # cfg 1: comfy.py refuses a negative it could not use
            dropped.add(d["id"])
            negative = None
        for seed in seeds:
            out = os.path.join(a.out_dir, f"{slug}_{d['id']}_s{seed}_v{a.version:02d}.png")
            if os.path.exists(out) and os.path.getsize(out) > 0:
                say(f"skip (exists): {out}")
                skipped += 1
                continue
            if os.path.exists(out + ".json"):
                raise Refused(f"{out}.json exists without its image (a failed run?): use --version {a.version + 1}")
            args = ["--prompt", d["prompt"], "--seed", str(seed), "--out", out, "--ledger", ledger]
            if size:
                args += ["--size", str(size)]
            if negative:
                args += ["--negative", str(negative)]
            if a.turbo:
                args.append("--turbo")
            if a.review:
                args += ["--review", a.review]
            jobs.append((f"{d['id']} seed {seed}", comfy_argv("qwen-t2i", args)))
    say(f"concept gen: {slug} · {len(dirs)} direction(s) · {len(jobs)} image(s) to make, {skipped} done"
        + (" · --turbo: drafts only" if a.turbo else ""))
    if dropped:
        say(f"  --turbo (cfg 1) has no negative prompt: `Negative EN` of {', '.join(sorted(dropped))} not sent")
    if not jobs:
        return 0
    if not a.dry_run:
        os.makedirs(a.out_dir, exist_ok=True)
    return run_batch(jobs, a.dry_run)


# ------------------------------------------------------------------------------------------------ edit
def base_stem(name):
    """x_s7_v01_e02.png -> x_s7_v01 (the generated image an edit chain starts from)."""
    stem = os.path.splitext(os.path.basename(name))[0]
    while RE_EDIT_TAIL.search(stem):
        stem = RE_EDIT_TAIL.sub("", stem)
    return stem


def next_edit(folder, base):
    taken = [int(m.group(1)) for n in os.listdir(folder) if n.startswith(base + "_e")
             for m in [re.fullmatch(re.escape(base) + r"_e(\d{2,})(?:\.png|\.png\.json)", n)] if m]
    return os.path.join(folder, f"{base}_e{(max(taken) + 1 if taken else 1):02d}.png")


def read_edits(folder):
    path = os.path.join(folder, EDITS_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        raise Refused(f"{path}: unreadable ({type(e).__name__}); fix or move it")


def write_json_atomic(path, obj):
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def edit_settings(a):
    s = {"lightning": a.lightning, "denoise": a.denoise}
    if a.steps is not None:
        s["steps"] = a.steps
    if a.cfg is not None:
        s["cfg"] = a.cfg
    if a.size:
        s["size"] = a.size
    return s


def qwen_edit_args(image, refs, prompt, settings, seed, out, ledger, review):
    args = ["--image", image]
    for r in refs:
        args += ["--ref", r]
    args += ["--prompt", prompt]
    if settings.get("lightning"):
        args += ["--lightning", str(settings["lightning"])]
    for k in ("steps", "cfg", "denoise"):
        if settings.get(k) is not None:
            args += [f"--{k}", f"{settings[k]:g}" if isinstance(settings[k], float) else str(settings[k])]
    args += ["--seed", str(seed)]
    if settings.get("size"):
        args += ["--size", settings["size"]]
    args += ["--out", out, "--ledger", ledger]
    if review:
        args += ["--review", review]
    return args


def cmd_edit(a):
    ledger = a.ledger or os.environ.get("FILM_LEDGER")
    if not ledger:
        raise Refused("--ledger L.csv (the episode's ledger; comfy.py writes one row per image, cost 0)")
    if (a.instruction is None) == (a.options is None):
        raise Refused("give exactly one of --instruction TEXT or --options DESIGN-OPTIONS.md (its `Edit EN` lines)")
    if a.denoise is not None and not 0 < a.denoise <= 1:
        raise Refused("--denoise must be > 0 and <= 1")
    opts = load_options(a.options) if a.options else None
    for r in a.ref or []:
        if not os.path.isfile(r):
            raise Refused(f"--ref {r}: no such file")
    settings = edit_settings(a)
    jobs, records, planned = [], {}, {}
    for img in a.images:
        if not os.path.isfile(img):
            raise Refused(f"{img}: no such file")
        name = os.path.basename(img)
        m = RE_NAME.match(name)
        if not m:
            raise Refused(f"{name}: not a concept name <slug>_<dir>_s<seed>_v<NN>[_e<NN>].png (concept.py gen)")
        if a.instruction is not None:
            instr = a.instruction.strip()
        else:
            d = next((d for d in opts["directions"] if d["id"] == m.group("dir")), None)
            instr = str((d or {}).get("edit") or "").strip()
            if not instr:
                raise Refused(f"{name}: direction '{m.group('dir')}' has no `Edit EN` in {a.options}")
        if not instr:
            raise Refused("the edit instruction is empty")
        folder = os.path.dirname(os.path.abspath(img))
        if folder not in records:
            records[folder] = read_edits(folder)
        src_sha = sha256_file(img)
        for seed in a.seed or [int(m.group("seed"))]:
            key = {"src_sha256": src_sha, "instruction": instr, "seed": seed, "settings": settings,
                   "refs": [sha256_file(r) for r in a.ref or []]}
            done = [r for r in records[folder] if all(r.get(k) == v for k, v in key.items())
                    and os.path.isfile(os.path.join(folder, r.get("out", "")))]
            if done and not a.redo:
                say(f"skip (done): {name} seed {seed} -> {done[-1]['out']}")
                continue
            base = base_stem(name)
            out = next_edit(folder, base)
            while out in planned:                          # several edits of one base in this batch
                n = int(RE_EDIT_TAIL.search(os.path.splitext(out)[0]).group(1)) + 1
                out = os.path.join(folder, f"{base}_e{n:02d}.png")
            planned[out] = True
            rec = dict(key, src=name, out=os.path.basename(out),
                       date=datetime.date.today().isoformat())
            args = qwen_edit_args(img, a.ref or [], instr, settings, seed, out, ledger, a.review)
            jobs.append((f"{name} seed {seed} -> {os.path.basename(out)}", comfy_argv("qwen-edit", args), folder, rec))
    say(f"concept edit: {len(jobs)} edit(s) · " + (f"Lightning {a.lightning}" if a.lightning else
                                                   "no Lightning (40 steps, cfg 4)") + f" · denoise {a.denoise:g}")
    if not jobs:
        return 0

    def done(i):                        # each finished edit is recorded even when a later one fails
        _, _, folder, rec = jobs[i]
        records[folder].append(rec)
        write_json_atomic(os.path.join(folder, EDITS_FILE), records[folder])

    return run_batch([(label, argv) for label, argv, _, _ in jobs], a.dry_run, done)


# ------------------------------------------------------------------------------------------------ sheet
def font(size):
    from PIL import ImageFont
    for name in ("DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "arial.ttf",
                 "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(name, size), True
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size), True       # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default(), False


def fit(text, width, fnt, draw):
    """Shorten text with '...' until it fits width pixels."""
    if draw.textlength(text, font=fnt) <= width:
        return text
    while text and draw.textlength(text + "...", font=fnt) > width:
        text = text[:-1]
    return text + "..."


def label_of(name, edit=None):
    m = RE_NAME.match(name)
    if not m:
        return os.path.splitext(name)[0]
    tail = m.group("edits").replace("_", " ").strip()
    lab = f"{m.group('dir')} · s{m.group('seed')} · v{m.group('v')}" + (f" · {tail}" if tail else "")
    return lab


def make_sheet(rows, out, cell=480, title=None):
    """rows: [[(path, label, sublabel), ...], ...] -> a labelled contact sheet PNG at out (never overwritten).
    Each cell keeps its image's aspect inside a cell x cell*9/16 box."""
    from PIL import Image, ImageDraw
    if os.path.exists(out):
        raise Refused(f"{out} exists (nothing is overwritten; pick a new name)")
    ch = round(cell * 9 / 16)
    band = max(18, cell // 18)
    fnt, unicode_ok = font(max(11, band - 6))
    top = band + 8 if title else 0
    cols = max(len(r) for r in rows)
    sheet = Image.new("RGB", (cols * cell, top + len(rows) * (ch + 2 * band)), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    clean = (lambda s: s) if unicode_ok else (lambda s: s.encode("latin-1", "replace").decode("latin-1"))
    if title:
        d.text((8, 4), clean(fit(title, cols * cell - 16, fnt, d)), fill=(235, 235, 235), font=fnt)
    for r, row in enumerate(rows):
        y0 = top + r * (ch + 2 * band)
        for c, (path, lab, sub) in enumerate(row):
            x0 = c * cell
            with Image.open(path) as im:
                im = im.convert("RGB")
                im.thumbnail((cell - 4, ch - 4), Image.LANCZOS)
                sheet.paste(im, (x0 + (cell - im.width) // 2, y0 + band + (ch - im.height) // 2))
            d.text((x0 + 6, y0 + 3), clean(fit(lab, cell - 12, fnt, d)), fill=(255, 220, 120), font=fnt)
            if sub:
                d.text((x0 + 6, y0 + band + ch + 3), clean(fit(sub, cell - 12, fnt, d)), fill=(200, 200, 200),
                       font=fnt)
    tmp = out + f".tmp{os.getpid()}.png"
    try:
        sheet.save(tmp)
        try:
            os.link(tmp, out)
        except FileExistsError:
            raise Refused(f"{out} appeared meanwhile: not replaced") from None
        except OSError:
            if os.path.exists(out):
                raise Refused(f"{out} appeared meanwhile: not replaced") from None
            os.rename(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return out


def next_free(folder, stem, ext=".png"):
    n = 1
    while os.path.exists(os.path.join(folder, f"{stem}_v{n:02d}{ext}")):
        n += 1
    return os.path.join(folder, f"{stem}_v{n:02d}{ext}")


def cmd_sheet(a):
    files = []
    for p in a.inputs:
        if os.path.isdir(p):
            files += [os.path.join(p, n) for n in sorted(os.listdir(p)) if RE_NAME.match(n)]
        elif os.path.isfile(p):
            files.append(p)
        else:
            raise Refused(f"{p}: no such file or folder")
    if not files:
        raise Refused("no concept image (<slug>_<dir>_s<seed>_v<NN>[_e<NN>].png) to put on a sheet")
    if a.cols < 1 or a.cell < 64:
        raise Refused("--cols >= 1 and --cell >= 64")
    by_base, order = {}, []
    for f in files:
        b = base_stem(f)
        if b not in by_base:
            by_base[b] = []
            order.append(b)
        by_base[b].append(f)
    notes = {}
    for folder in {os.path.dirname(os.path.abspath(f)) for f in files}:
        for r in read_edits(folder):
            notes[os.path.join(folder, r.get("out", ""))] = r
    rows, plain = [], []
    for b in order:
        group = by_base[b]
        base = [f for f in group if base_stem(f) == os.path.splitext(os.path.basename(f))[0]]
        edits = [f for f in group if f not in base]
        if edits:                       # before/after: the source, then its edits (instruction underneath)
            src = base[0] if base else None
            if src is None:
                cand = os.path.join(os.path.dirname(edits[0]), b + ".png")
                src = cand if os.path.isfile(cand) else None
            row = [(src, label_of(os.path.basename(src)), "before")] if src else []
            for e in sorted(edits):
                rec = notes.get(os.path.abspath(e), {})
                sub = (f"seed {rec['seed']}: " if "seed" in rec else "") + str(rec.get("instruction", ""))
                row.append((e, label_of(os.path.basename(e)), sub or "edit"))
            rows.append(row)
        else:
            plain += [(f, label_of(os.path.basename(f)), "") for f in base]
    for i in range(0, len(plain), a.cols):
        rows.append(plain[i:i + a.cols])
    first = os.path.basename(files[0])
    m = RE_NAME.match(first)
    folder = os.path.dirname(os.path.abspath(files[0]))
    out = a.out or next_free(folder, f"{m.group('slug') if m else 'concepts'}_sheet")
    make_sheet(rows, out, a.cell, title=a.title or (m.group("slug") if m else None))
    say(f"sheet: {len(files)} image(s), {len(rows)} row(s) -> {out}")
    return 0


# ------------------------------------------------------------------------------------------------ approve
def load_check_episode():
    import importlib.util
    sp = importlib.util.spec_from_file_location("film_check_episode", os.path.join(HERE, "check_episode.py"))
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    return mod


def comment_lines(lines):
    """Set of line indexes that lie inside an HTML comment (whole line)."""
    inside, out = False, set()
    for i, line in enumerate(lines):
        s = line
        if inside:
            out.add(i)
            if "-->" in s:
                inside = False
                s = s.split("-->", 1)[1]
            else:
                continue
        while "<!--" in s:
            head, s = s.split("<!--", 1)
            if not head.strip() and "-->" not in s:
                out.add(i)
            if "-->" in s:
                s = s.split("-->", 1)[1]
            else:
                inside = True
                break
    return out


def section_span(lines, heading):
    """(start, end) line indexes of a `## ` section (heading line, first line of the next `## ` or len), or None.
    Headings inside fences or HTML comments do not count."""
    skip, fence, start = comment_lines(lines), None, None
    for i, line in enumerate(lines):
        m = RE_FENCE.match(line)
        if m:
            fence = None if fence and line.strip().startswith(fence) else (fence or m.group(1))
            continue
        if fence or i in skip or not line.startswith("## "):
            continue
        if start is not None:
            return start, i
        if nfc(line.rstrip()) == heading:
            start = i
    return (start, len(lines)) if start is not None else None


def split_row(line):
    """'| a | b |' -> (lead, [' a ', ' b '], tail)."""
    s = line.rstrip("\n")
    first, last = s.index("|"), s.rindex("|")
    return s[:first], s[first + 1:last].split("|"), s[last + 1:]


def rel_display(path):
    p = os.path.abspath(path)
    try:
        r = os.path.relpath(p)
    except ValueError:                   # another drive (Windows)
        r = p
    if r.startswith(".."):
        r = p
    return r.replace(os.sep, "/")


def update_episode(text, slug, cell, name, ce):
    """-> (new text, what changed: 'unchanged' | 'updated' | 'added'). Only the slug's row is touched."""
    lines = text.split("\n")
    span = section_span(lines, CREATURE_HEADING)
    if span is None:
        raise Refused(f"EPISODE.md has no '{CREATURE_HEADING}' section: copy it from templates/episode/EPISODE.md")
    skip = comment_lines(lines)
    rows = [i for i in range(span[0] + 1, span[1]) if i not in skip and lines[i].strip().startswith("|")]
    if not rows:
        raise Refused(f"'{CREATURE_HEADING}' has no table header (| slug | Tên | Chính | Ảnh sách | Concept |)")
    _, head_cells, _ = split_row(lines[rows[0]])
    head = [ce.CREATURE_COLS.get(" ".join(nfc(c).lower().split()).strip("`*")) for c in head_cells]
    if "slug" not in head or "concept" not in head:
        raise Refused(f"'{CREATURE_HEADING}': the header needs the slug and Concept columns")
    body = rows[1:]
    if body and all(re.fullmatch(r":?-+:?", c.strip()) for c in split_row(lines[body[0]])[1] if c.strip()):
        body = body[1:]
    ci, si = head.index("concept"), head.index("slug")
    for i in body:
        lead, cells, tail = split_row(lines[i])
        if si >= len(cells):
            continue
        s = nfc(cells[si]).strip().strip("`")
        s = s[2:] if s.startswith(("A-", "C-")) else s
        if s != slug:
            continue
        cells += [" "] * (len(head) - len(cells))
        old = cells[ci].strip()
        if ce.cell_word(old) in ("duyệt", "approved") and cell.split(" ", 2)[-1] in old:
            return text, "unchanged"
        cells[ci] = f" {cell} "
        lines[i] = lead + "|" + "|".join(cells) + "|" + tail
        return "\n".join(lines), "updated"
    vals = {"slug": slug, "name": name or "", "main": "có", "book": "chờ", "concept": cell}
    new = "| " + " | ".join(vals.get(k or "", "") for k in head) + " |"
    at = (body or rows)[-1] + 1
    lines.insert(at, new)
    return "\n".join(lines), "added"


def concept_block(file_disp, date, quote, name_info, prev):
    out = [f"- File: `{file_disp}`", f"- Ngày duyệt: {date}"]
    if name_info:
        out.append(f"- Hướng: {name_info['dir']} · seed {name_info['seed']} · v{name_info['v']}"
                   + (f" · sửa {name_info['edits'].replace('_', ' ').strip()}" if name_info["edits"] else ""))
    if quote:
        out.append(f"- Lời người dùng (nguyên văn): \"{quote}\"")
    out.append("- Ghi bởi: `tools/concept.py approve` (chi tiết đếm được – sừng, chân, mắt – dựng thẳng trong 3D)")
    if prev:
        out.append(f"- Thay cho: {prev}")
    return out


def update_character(text, block, file_disp):
    """-> (new text, 'unchanged' | 'updated' | 'added'). Only the `## Concept đã duyệt` section is written."""
    lines = text.split("\n")
    span = section_span(lines, CONCEPT_HEADING)
    if span is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", CONCEPT_HEADING, ""] + block + [""]
        return "\n".join(lines), "added"
    old = lines[span[0] + 1:span[1]]
    if any(f"`{file_disp}`" in l for l in old if l.lstrip().startswith("- File:")):
        return text, "unchanged"
    lines[span[0] + 1:span[1]] = [""] + block + [""]
    return "\n".join(lines), "updated"


def previous_file(text):
    lines = text.split("\n")
    span = section_span(lines, CONCEPT_HEADING)
    if not span:
        return None
    f = next((l for l in lines[span[0] + 1:span[1]] if l.lstrip().startswith("- File:")), None)
    d = next((l for l in lines[span[0] + 1:span[1]] if l.lstrip().startswith("- Ngày duyệt:")), None)
    if not f:
        return None
    return f.split(":", 1)[1].strip() + (f" ({d.split(':', 1)[1].strip()})" if d else "")


def write_text_atomic(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(nfc(text))
    os.replace(tmp, path)


def cmd_approve(a):
    ce = load_check_episode()
    slug = a.slug.strip()
    if not RE_SLUG.match(slug):
        raise Refused(f"slug {slug!r} is not lower-case [a-z0-9-] (characters/<slug>/)")
    if not os.path.isfile(a.file):
        raise Refused(f"{a.file}: no such file")
    ep = os.path.abspath(a.episode)
    ep_md = os.path.join(ep, "EPISODE.md")
    if not os.path.isfile(ep_md):
        raise Refused(f"{ep_md}: no such file (--episode is the episode folder projects/<project>/<episode>)")
    date = a.date or datetime.date.today().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise Refused(f"--date {date}: YYYY-MM-DD")
    file_disp = rel_display(a.file)
    if "|" in file_disp or "`" in file_disp or CONTROL.search(file_disp):
        raise Refused(f"{file_disp}: a file name with |, ` or a control character cannot go into the table")
    if a.name is not None and (not a.name.strip() or "|" in a.name or "`" in a.name or CONTROL.search(a.name)):
        raise Refused(f"--name {a.name!r}: one line without | or ` (it goes into the EPISODE.md table and the "
                      "CHARACTER.md title)")
    if a.quote is not None and CONTROL.search(a.quote):
        raise Refused("--quote: one line (no line break or control character): it is one list item of CHARACTER.md")
    m = RE_NAME.match(os.path.basename(a.file))
    if not m:
        warn(f"{os.path.basename(a.file)} is not a concept.py name (<slug>_<dir>_s<seed>_v<NN>.png)")
    elif m.group("slug") != slug:
        warn(f"{os.path.basename(a.file)} is named for '{m.group('slug')}', not '{slug}'")
    char_md = os.path.join(ep, "characters", slug, "CHARACTER.md")
    if not os.path.isfile(char_md):
        char_md = os.path.join(os.path.dirname(ep), "characters", slug, "CHARACTER.md")
    char_text = ce.read_text(char_md) if os.path.isfile(char_md) else f"# {a.name or slug}\n"
    ep_text = ce.read_text(ep_md)
    prev = previous_file(char_text)
    if prev and f"`{file_disp}`" in prev:
        prev = None
    block = concept_block(file_disp, date, a.quote, m.groupdict() if m else None, prev)
    new_char, what_c = update_character(char_text, block, file_disp)
    new_ep, what_e = update_episode(ep_text, slug, f"duyệt {date} {file_disp}", a.name, ce)
    say(f"{os.path.relpath(char_md, os.path.dirname(ep))}: {CONCEPT_HEADING} {what_c}")
    say(f"EPISODE.md: {CREATURE_HEADING} row '{slug}' {what_e}" + (" (Chính: có, Ảnh sách: chờ)" if what_e == "added"
                                                                    else ""))
    if a.dry_run:
        say("dry-run: nothing written")
        return 0
    if what_c != "unchanged":
        write_text_atomic(char_md, new_char)
    if what_e != "unchanged":
        write_text_atomic(ep_md, new_ep)
    # read back exactly as check_episode.py / status.py --gate G2 do
    _, body = ce.split_front_matter(ce.read_text(ep_md))
    tab = ce.read_creatures(body) or {"rows": []}
    row = next((r for r in tab["rows"] if r["slug"] == slug), None)
    if not row or row.get("concept") != "approved" or not ce.concept_record(ep, slug):
        print(f"concept: written, but check_episode.py does not read '{slug}' as approved: look at EPISODE.md and "
              f"{char_md}", file=sys.stderr)
        return 1
    say(f"approved: {slug} -> {file_disp} (check_episode: concept approved, {ce.concept_record(ep, slug)})")
    return 0


# ------------------------------------------------------------------------------------------------ CLI
def parser():
    p = argparse.ArgumentParser(prog="concept.py", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sp = p.add_subparsers(dest="cmd", required=True)
    g = sp.add_parser("gen", help="text-to-image concepts (comfy.py run qwen-t2i), N seeds per direction")
    g.add_argument("options", help="DESIGN-OPTIONS.md (### <dir> + Prompt EN) or a jobs JSON")
    g.add_argument("--slug", default=None, help="the creature's slug (characters/<slug>/; or \"slug\" in the JSON)")
    g.add_argument("--out-dir", required=True, help="e.g. out/<project>/characters/<slug>/concept")
    g.add_argument("--ledger", default=None, help="the episode's ledger.csv (env FILM_LEDGER)")
    g.add_argument("--n", type=int, default=None, help="seeds per direction (default 2, or all the file's seeds)")
    g.add_argument("--seed-start", type=int, default=None, help="seeds S, S+1, ... (default 1001; wins over the "
                                                                "file's seeds)")
    g.add_argument("--only", default=None, help="only these directions: a,b")
    g.add_argument("--size", default=None, help=f"WxH (comfy.py default {DEFAULT_SIZE})")
    g.add_argument("--turbo", action="store_true", help="Turbo LoRA, 2 steps: drafts only, never the approved image")
    g.add_argument("--version", type=int, default=1, help="round: _v<NN> of the names (default 1)")
    g.add_argument("--review", default=None, metavar="BUILD", help="pass-through to comfy.py (a concept build)")
    g.add_argument("--dry-run", action="store_true", help="print the plan, call nothing")
    e = sp.add_parser("edit", help="Qwen-Image-Edit on chosen concepts (comfy.py run qwen-edit) -> _e<NN>.png")
    e.add_argument("images", nargs="+")
    e.add_argument("--instruction", default=None, help="English edit instruction (\"remove ..., keep everything "
                                                       "else exactly\")")
    e.add_argument("--options", default=None, help="DESIGN-OPTIONS.md: the `Edit EN` of each image's direction")
    e.add_argument("--ref", action="append", default=None, metavar="IMG", help="reference image (Picture 2..)")
    e.add_argument("--lightning", type=int, choices=(0, 4, 8), default=4,
                   help="Lightning LoRA steps (default 4; 0 = no LoRA: 40 steps, cfg 4, slower, full quality)")
    e.add_argument("--denoise", type=float, default=1.0, help="default 1.0 (repaints; lower keeps more)")
    e.add_argument("--steps", type=int, default=None)
    e.add_argument("--cfg", type=float, default=None)
    e.add_argument("--seed", type=int, action="append", default=None, help="repeat for several (default: the "
                                                                           "image's own seed)")
    e.add_argument("--size", default=None, metavar="WxH")
    e.add_argument("--redo", action="store_true", help="edit again even when the same edit exists")
    e.add_argument("--ledger", default=None, help="the episode's ledger.csv (env FILM_LEDGER)")
    e.add_argument("--review", default=None, metavar="BUILD")
    e.add_argument("--dry-run", action="store_true")
    s = sp.add_parser("sheet", help="labelled contact sheet; before/after rows for edits")
    s.add_argument("inputs", nargs="+", help="a concept folder or images")
    s.add_argument("--out", default=None, help="default <folder>/<slug>_sheet_v<NN>.png (next free)")
    s.add_argument("--cell", type=int, default=480, help="cell width in pixels (default 480)")
    s.add_argument("--cols", type=int, default=3, help="columns of the plain grid (default 3)")
    s.add_argument("--title", default=None)
    r = sp.add_parser("approve", help="record the owner's pick: CHARACTER.md + the EPISODE.md creature row")
    r.add_argument("slug")
    r.add_argument("file")
    r.add_argument("--episode", required=True, help="projects/<project>/<episode dir>")
    r.add_argument("--date", default=None, help="YYYY-MM-DD (default today)")
    r.add_argument("--quote", default=None, help="the owner's words, verbatim")
    r.add_argument("--name", default=None, help="display name for a new row / a new CHARACTER.md")
    r.add_argument("--dry-run", action="store_true")
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    a = parser().parse_args(argv)
    try:
        return {"gen": cmd_gen, "edit": cmd_edit, "sheet": cmd_sheet, "approve": cmd_approve}[a.cmd](a)
    except Refused as e:
        print(f"concept: refused: {e}", file=sys.stderr)
        return REFUSED


if __name__ == "__main__":
    sys.exit(main())
