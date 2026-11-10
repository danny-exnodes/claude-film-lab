#!/usr/bin/env python3
"""BytePlus ModelArk from a Claude Code cloud session (AI Film Lab).

  python3 ark.py ping [--all]
  python3 ark.py image "prompt" out.png [--model seedream-5-0-lite-260128 | --fast] [--size 2K|2560x1440] [--ref a.png ...]
                       [--seed N] [--negative TEXT ...] [--guidance F] [--force]
                       (--ledger L.csv --budget B.yaml | --no-budget [--ledger L.csv])
  python3 ark.py video "prompt" out.mp4 [--image first.png] [--model dreamina-seedance-2-5-260628]
                       [--ratio adaptive|16:9] [--duration 5] [--resolution 1080p] [--no-audio]
                       (--ledger L.csv --budget B.yaml | --no-budget [--ledger L.csv])
  python3 ark.py video --resume-task TASK_ID [out.mp4] --ledger L.csv

Budget and ledger (docs/CONVENTIONS.md §7): --ledger/--budget (or env FILM_LEDGER/FILM_BUDGET).
image/video refuse to run (exit 2) without BOTH a budget and a ledger, unless --no-budget is given
(ad-hoc tests in the main session only). The budget is checked BEFORE the call (over a cap: exit 3).
Each request appends a 'pending' row (note req=<id>) before the API call and a final row
(ok/failed/cut-502, same req=<id>) after it, so a killed process still leaves a billed row.

Credentials: in a Claude cloud session the agent proxy injects the real Ark key
for ark.ap-southeast.bytepluses.com, so this script sends a placeholder. Outside
that proxy, set ARK_API_KEY. Never print, log or search for the key.
"""
import argparse, base64, csv, datetime, fcntl, io, json, mimetypes, os, re, signal, sys, time, uuid
import urllib.request, urllib.error

BASE = os.environ.get("ARK_BASE", "https://ark.ap-southeast.bytepluses.com/api/v3")


def call(method, path, body=None, timeout=300):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body else None)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + (os.environ.get("ARK_API_KEY") or "proxy-injected"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode()[:600]}")


def data_uri(path):
    raw = open(path, "rb").read()
    mime = sniff_mime(raw) or mimetypes.guess_type(path)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


REF_LONG_EDGE = 2048   # --ref images are re-encoded to JPEG q90 with the long edge <= this
REF_QUALITY = 90


def ref_jpeg(path):
    """Re-encode a --ref image in memory: RGB (alpha flattened onto white), long edge <= 2048, JPEG q90.
    The file on disk is not touched. Returns (jpeg bytes, description)."""
    from PIL import Image, ImageOps
    with Image.open(path) as src:
        fmt, size0 = src.format, src.size
        im = ImageOps.exif_transpose(src)
        if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
            im = im.convert("RGBA")
            flat = Image.new("RGB", im.size, (255, 255, 255))
            flat.paste(im, mask=im.getchannel("A"))
            im = flat
        elif im.mode != "RGB":
            im = im.convert("RGB")
        if max(im.size) > REF_LONG_EDGE:
            s = REF_LONG_EDGE / max(im.size)
            im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=REF_QUALITY)
    raw = buf.getvalue()
    desc = (f"{os.path.basename(path)}: {size0[0]}x{size0[1]} {fmt} {os.path.getsize(path) / 1e6:.2f} MB"
            f" -> {im.width}x{im.height} JPEG {len(raw) / 1e6:.2f} MB")
    return raw, desc


def ref_data_uri(path):
    raw, desc = ref_jpeg(path)
    print("ref", desc)
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode()


# --- models available on this account (see Ark Console) --------------------
IMAGE_DEFAULT = "seedream-5-0-lite-260128"        # Dola-Seedream-5.0-lite, 2K ~25s
IMAGE_FAST = "dola-seedream-5-0-flash-260915"     # Dola-Seedream-5.0-flash
IMAGE_SLOW = {"dola-seedream-5-0-pro-260628"}     # always > proxy cutoff
VIDEO_DEFAULT = "dreamina-seedance-2-5-260628"    # Dreamina-Seedance-2.5
PROXY_CUTOFF = 30  # seconds: the agent proxy cuts synchronous requests here
POLL_SECONDS = 10  # video task polling interval
CUT_PREFIX = "HTTP 502 after"  # api() message for a request cut by the proxy


def api(method, path, body=None):
    """call() plus a clear message when the agent proxy cuts a long request."""
    t0 = time.time()
    try:
        return call(method, path, body)
    except SystemExit as e:
        took = time.time() - t0
        if str(e).startswith("HTTP 502") and took >= PROXY_CUTOFF - 5:
            sys.exit(f"{CUT_PREFIX} {took:.0f}s: the agent proxy cuts synchronous requests at ~{PROXY_CUTOFF}s.\n"
                     "The request may still have been billed upstream, so it was NOT retried.\n"
                     f"Try a smaller --size (e.g. 2K or 1024x1024) or --fast ({IMAGE_FAST}).")
        raise


def sniff_mime(raw):
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


EXT_FORMAT = {".png": ("PNG", "image/png"), ".jpg": ("JPEG", "image/jpeg"),
              ".jpeg": ("JPEG", "image/jpeg"), ".webp": ("WEBP", "image/webp")}


def save_image(raw, out):
    """Write raw bytes, converting so the content matches the file extension."""
    want = EXT_FORMAT.get(os.path.splitext(out)[1].lower())
    got = sniff_mime(raw)
    if want and got and got != want[1]:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        if want[0] == "JPEG" and im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.save(out, want[0])
        print(f"converted {got} -> {want[1]}")
    else:
        open(out, "wb").write(raw)


def download(url, out):
    urllib.request.urlretrieve(url, out)


# --- ledger and budget (docs/CONVENTIONS.md §7) ------------------------------
LEDGER_FIELDS = ["ts", "kind", "model", "size", "seconds", "count", "status", "out", "task_id", "usage", "agent", "note"]
FINAL = {"ok", "failed", "cut-502"}    # final row of a request; every one may have been billed
BILLED = FINAL | {"pending"}           # pending: written before the call, counts until a final row exists
BUDGET_EXIT = 3
USAGE_EXIT = 2
REQ_RE = re.compile(r"req=([0-9a-f]+)")


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ledger_append(path, row):
    """Append one row under an exclusive flock; writes the header when the file is new/empty."""
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    rec = {k: "" for k in LEDGER_FIELDS}
    rec.update({k: v for k, v in row.items() if k in rec and v is not None})
    rec["ts"] = rec["ts"] or utc_now()
    rec["agent"] = rec["agent"] or os.environ.get("FILM_AGENT", "")
    with open(path, "a+", newline="", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0, os.SEEK_END)
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=LEDGER_FIELDS, lineterminator="\n")
            if f.tell() == 0:
                w.writeheader()
            w.writerow(rec)
            f.write(buf.getvalue())
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def ledger_rows(path):
    if not path or not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            text = f.read()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    rows = list(csv.DictReader(io.StringIO(text)))
    if rows and list(rows[0].keys()) != LEDGER_FIELDS:
        print(f"warning: {path} header differs from {','.join(LEDGER_FIELDS)}", file=sys.stderr)
    return rows


def load_budget(path):
    if not path:
        return None
    import yaml
    with open(path, encoding="utf-8") as f:
        b = yaml.safe_load(f) or {}
    if not isinstance(b, dict):
        sys.exit(f"budget {path}: expected a mapping with images / video_seconds / models")
    models = b.get("models") or {}
    if not isinstance(models, dict):
        sys.exit(f"budget {path}: 'models' must be a mapping model-id -> cap")
    return {"images": b.get("images"), "video_seconds": b.get("video_seconds"), "models": models}


def _num(x):
    try:
        return float(x or 0)
    except ValueError:
        return 0.0


def units(row):
    """Billing units of a ledger row: images for kind=image, seconds for kind=video."""
    return _num(row.get("seconds")) if row.get("kind") == "video" else _num(row.get("count") or 1)


def req_id(row):
    """The request id of a ledger row (note starts with 'req=<hex>'), or None for old/refused rows."""
    m = REQ_RE.match(row.get("note") or "")
    return m.group(1) if m else None


def billed_requests(rows):
    """One row per request that may have been billed (docs/CONVENTIONS.md §7).
    Rows are grouped by req id (else by task_id); a group counts once, using its last final row
    (ok/failed/cut-502) or, with none, its last pending row. Rows with neither id count one by one."""
    single, groups = [], {}
    for r in rows:
        if r.get("status") not in BILLED:
            continue
        key = req_id(r) or ("task:" + r["task_id"] if r.get("task_id") else None)
        if key is None:
            single.append(r)
        else:
            groups.setdefault(key, []).append(r)
    out = list(single)
    for g in groups.values():
        finals = [r for r in g if r.get("status") in FINAL]
        out.append((finals or g)[-1])
    return out


def budget_check(budget, rows, req):
    """Return a list of human-readable cap violations for request `req` (a ledger-shaped dict)."""
    if not budget:
        return []
    used = billed_requests(rows)
    need = units(req)
    over = []
    if req["kind"] == "image" and budget.get("images") is not None:
        have = sum(units(r) for r in used if r.get("kind") == "image")
        if have + need > budget["images"]:
            over.append(f"images: {have:g} used + {need:g} requested > cap {budget['images']}")
    if req["kind"] == "video" and budget.get("video_seconds") is not None:
        have = sum(units(r) for r in used if r.get("kind") == "video")
        if have + need > budget["video_seconds"]:
            over.append(f"video_seconds: {have:g} used + {need:g} requested > cap {budget['video_seconds']}")
    cap = budget["models"].get(req["model"])
    if cap is not None:
        have = sum(units(r) for r in used if r.get("model") == req["model"])
        if have + need > cap:
            over.append(f"models.{req['model']}: {have:g} used + {need:g} requested > cap {cap}")
    return over


def guard_budget(a, req):
    """Budget check before any generation call. Exits 3 (and logs refused-budget) when over a cap.
    main() already guaranteed budget+ledger, or --no-budget."""
    if a.no_budget:
        return
    budget = load_budget(a.budget)
    over = budget_check(budget, ledger_rows(a.ledger), req)
    if over:
        ledger_append(a.ledger, dict(req, status="refused-budget", note="; ".join(over)))
        print(f"REFUSED (budget {a.budget}): " + "; ".join(over) + "\n"
              "Nothing was sent to the API. Ask the user (main session) to raise the cap in budget.yaml.",
              file=sys.stderr)
        sys.exit(BUDGET_EXIT)


def fail_status(e):
    return "cut-502" if isinstance(e, SystemExit) and str(e).startswith(CUT_PREFIX) else "failed"


def err_note(e):
    s = str(e) if isinstance(e, SystemExit) else f"{type(e).__name__}: {e}"
    return s.splitlines()[0][:300] if s else type(e).__name__


def new_req():
    return uuid.uuid4().hex


def log_row(a, req, rid, status, note="", **extra):
    """Append a ledger row for request `req`; the note starts with req=<rid> when the request has one."""
    note = "; ".join(x for x in (f"req={rid}" if rid else "", note) if x)
    ledger_append(a.ledger, dict(req, status=status, note=note, **extra))


def make_out_dir(out):
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)


class Interrupted(SystemExit):
    """Raised by the SIGTERM/SIGINT handler so the normal exception path writes the final ledger row."""

    def __init__(self, signum):
        super().__init__(128 + signum)
        self.signame = signal.Signals(signum).name

    def __str__(self):
        return f"interrupted by {self.signame}"


def _on_signal(signum, frame):
    raise Interrupted(signum)


def ping(a):
    models = api("GET", "/models").get("data", [])
    for m in sorted(models, key=lambda m: (m.get("domain") or "", m["id"])):
        if m.get("status") == "Shutdown" and not a.all:
            continue
        print(f"{m['id']:44} {m.get('domain') or '-':16} {','.join(m.get('task_type') or []) or '-':40} {m.get('status') or 'Active'}")
    print(f"# {len(models)} models listed by the API ({'all' if a.all else 'Shutdown hidden; --all to show'}).")
    print(f"# Note: {IMAGE_DEFAULT} works but is not listed by /models.")


def image(a):
    model = a.model or (IMAGE_FAST if a.fast else IMAGE_DEFAULT)
    if not a.force:
        if model in IMAGE_SLOW:
            sys.exit(f"{model} always takes longer than the proxy's ~{PROXY_CUTOFF}s cutoff and fails with 502 "
                     "(possibly still billed). Use --force to try anyway.")
        if a.size.upper() == "4K":
            sys.exit(f"--size 4K takes longer than the proxy's ~{PROXY_CUTOFF}s cutoff and fails with 502 "
                     "(possibly still billed). Use 2K, or --force to try anyway.")
    req = {"kind": "image", "model": model, "size": a.size, "count": 1, "out": a.out}
    make_out_dir(a.out)
    guard_budget(a, req)
    body = {"model": model, "prompt": a.prompt, "size": a.size, "response_format": "b64_json", "watermark": False}
    if a.seed is not None:
        body["seed"] = a.seed
    if a.negative:
        body["negative_prompt"] = ", ".join(a.negative)
    if a.guidance is not None:
        body["guidance_scale"] = a.guidance
    if a.ref:
        refs = [ref_data_uri(p) for p in a.ref]
        body["image"] = refs if len(refs) > 1 else refs[0]
    print("model", model)
    rid = new_req()
    log_row(a, req, rid, "pending")
    try:
        r = api("POST", "/images/generations", body)
    except BaseException as e:
        log_row(a, req, rid, fail_status(e), err_note(e))
        raise
    data = r.get("data", [])
    final = dict(count=max(1, len(data)), usage=json.dumps(r.get("usage", {}), separators=(",", ":")))
    stem, ext = os.path.splitext(a.out)
    try:
        for i, d in enumerate(data):
            out = a.out if i == 0 else f"{stem}-{i}{ext}"
            save_image(base64.b64decode(d["b64_json"]), out)
            print("saved", out)
    except BaseException as e:
        log_row(a, req, rid, "failed", "save-failed: " + err_note(e), **final)
        print(f"SAVE FAILED ({err_note(e)}): the image was generated and billed but not saved to {a.out}",
              file=sys.stderr)
        if isinstance(e, Exception):
            sys.exit(1)
        raise
    log_row(a, req, rid, "ok", **final)
    print("usage", json.dumps(r.get("usage", {})))


def video(a):
    if a.resume_task:
        return resume_video(a)
    content = [{"type": "text", "text": a.prompt}]
    if a.image:
        content.append({"type": "image_url", "image_url": {"url": data_uri(a.image)}, "role": "first_frame"})
    ratio = a.ratio or ("adaptive" if a.image else "16:9")
    req = {"kind": "video", "model": a.model, "size": a.resolution, "seconds": a.duration, "count": 1, "out": a.out}
    make_out_dir(a.out)
    guard_budget(a, req)
    body = {"model": a.model, "content": content, "duration": a.duration, "resolution": a.resolution,
            "ratio": ratio, "watermark": False}
    if a.no_audio:
        body["generate_audio"] = False
    print("model", a.model, "| ratio", ratio, "| audio", "off" if a.no_audio else "model default")
    rid = new_req()
    log_row(a, req, rid, "pending")
    try:
        task = api("POST", "/contents/generations/tasks", body)["id"]
    except BaseException as e:
        log_row(a, req, rid, fail_status(e), "task creation: " + err_note(e))
        raise
    req["task_id"] = task
    log_row(a, req, rid, "pending", "task created")   # the task id survives even a SIGKILL
    print("task", task, flush=True)
    poll_and_save(a, req, rid)


def resume_video(a):
    """--resume-task: no creation, no budget check, no pending row; poll, download, append the final row."""
    task = a.resume_task
    known = [r for r in ledger_rows(a.ledger) if r.get("task_id") == task]
    if known:
        last = known[-1]
        req = {k: last.get(k, "") for k in ("kind", "model", "size", "seconds", "count", "out")}
        rid = next((req_id(r) for r in reversed(known) if req_id(r)), None)
    else:
        print(f"warning: task {task} is not in {a.ledger}; logging it from the command-line flags", file=sys.stderr)
        req = {"kind": "video", "model": a.model, "size": a.resolution, "seconds": a.duration, "count": 1}
        rid = None
    a.out = a.out or req.get("out")
    if not a.out:
        print("error: --resume-task needs an output path (none given and none in the ledger)", file=sys.stderr)
        sys.exit(USAGE_EXIT)
    req.update(out=a.out, task_id=task)
    make_out_dir(a.out)
    print("resume task", task, "| req", rid or "-", flush=True)
    poll_and_save(a, req, rid, "resumed")


def poll_and_save(a, req, rid, tag=""):
    """Poll task req['task_id'] until done, download the clip, append the final ledger row."""
    task = req["task_id"]
    pre = tag + "; " if tag else ""
    logged = False
    try:
        while True:
            time.sleep(POLL_SECONDS)
            t = api("GET", f"/contents/generations/tasks/{task}")
            print("status", t["status"], flush=True)
            if t["status"] == "succeeded":
                break
            if t["status"] in ("failed", "cancelled", "expired"):
                msg = json.dumps(t.get("error", t))[:600]
                log_row(a, req, rid, "failed", f"{pre}task {t['status']}: {msg[:300]}",
                        usage=json.dumps(t.get("usage", {}), separators=(",", ":")))
                logged = True
                sys.exit(msg)
    except BaseException as e:
        if not logged:  # polling broke off: the task may still run and be billed
            log_row(a, req, rid, "failed", f"{pre}polling stopped (task may still run): " + err_note(e))
            print(f"task {task} may still run; resume with: python3 tools/ark.py video --resume-task {task} "
                  f"{a.out} --ledger {a.ledger or 'L.csv'}", file=sys.stderr)
        raise
    usage = json.dumps(t.get("usage", {}), separators=(",", ":"))
    url = t["content"]["video_url"]
    print("video host:", url.split("/")[2])
    try:
        download(url, a.out)
    except BaseException as e:
        log_row(a, req, rid, "failed", f"{pre}download-failed: " + err_note(e), usage=usage)
        print(f"DOWNLOAD FAILED ({err_note(e)}); the clip was generated and billed. Fetch it manually"
              f" (the link expires):\n  task_id {task}\n  url {url}\n"
              f"  or: python3 tools/ark.py video --resume-task {task} {a.out} --ledger {a.ledger or 'L.csv'}",
              file=sys.stderr)
        if isinstance(e, Exception):
            sys.exit(1)
        raise
    log_row(a, req, rid, "ok", tag, usage=usage)
    print("saved", a.out)


def add_cost_args(sp):
    sp.add_argument("--ledger", default=None,
                    help="ledger.csv: a pending row before the call and a final row after it (env FILM_LEDGER); "
                         "see docs/CONVENTIONS.md §7")
    sp.add_argument("--budget", default=None,
                    help="budget.yaml checked before the call; over a cap -> refused-budget row, exit 3 "
                         "(env FILM_BUDGET). Required together with --ledger unless --no-budget")
    sp.add_argument("--no-budget", action="store_true",
                    help="run without a budget (ad-hoc tests in the main session only; --ledger optional)")


p = argparse.ArgumentParser(description="BytePlus ModelArk helper")
sp = p.add_subparsers(dest="cmd", required=True)
pg = sp.add_parser("ping", help="list models, one per line")
pg.add_argument("--all", action="store_true", help="also show Shutdown models")
i = sp.add_parser("image"); i.add_argument("prompt"); i.add_argument("out")
i.add_argument("--model", default=None, help=f"default {IMAGE_DEFAULT}")
i.add_argument("--fast", action="store_true", help=f"use {IMAGE_FAST}")
i.add_argument("--size", default="2K")
i.add_argument("--ref", nargs="*", help=f"reference image(s); re-encoded in memory to JPEG q{REF_QUALITY}, "
               f"long edge <= {REF_LONG_EDGE}, alpha flattened onto white (files on disk untouched)")
i.add_argument("--seed", type=int, default=None, help="sent as 'seed' (model support unverified)")
i.add_argument("--negative", action="append", metavar="TEXT",
               help="repeatable; joined with ', ' into 'negative_prompt' (model support unverified)")
i.add_argument("--guidance", type=float, default=None, help="sent as 'guidance_scale' (model support unverified)")
i.add_argument("--force", action="store_true", help="allow 4K / slow models despite the proxy cutoff")
add_cost_args(i)
v = sp.add_parser("video")
v.add_argument("prompt", nargs="?", help="text prompt (omit with --resume-task)")
v.add_argument("out", nargs="?", help="output .mp4 (with --resume-task: optional, default the out in the ledger)")
v.add_argument("--image")
v.add_argument("--model", default=VIDEO_DEFAULT)
v.add_argument("--ratio", default=None, help="default: adaptive with --image, else 16:9")
v.add_argument("--duration", type=int, default=5); v.add_argument("--resolution", default="1080p")
v.add_argument("--no-audio", action="store_true", help="send generate_audio=false")
v.add_argument("--resume-task", metavar="TASK_ID", default=None,
               help="resume polling + download of an existing task (no new request, no budget check; needs --ledger)")
add_cost_args(v)


def usage_error(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(USAGE_EXIT)


def check_cost_args(a):
    """image/video need budget + ledger, or --no-budget; --resume-task needs a ledger only (exit 2 otherwise)."""
    a.ledger = a.ledger or os.environ.get("FILM_LEDGER") or None
    a.budget = a.budget or os.environ.get("FILM_BUDGET") or None
    resume = getattr(a, "resume_task", None)
    if a.cmd == "video":
        if resume:
            if a.out is None:   # 'video --resume-task T out.mp4': the single positional is the output
                a.prompt, a.out = None, a.prompt
        elif a.prompt is None or a.out is None:
            usage_error("video needs a prompt and an output path (or --resume-task TASK_ID)")
    if resume:
        if not a.ledger:
            usage_error("--resume-task needs --ledger (or FILM_LEDGER) to log the final row")
        a.no_budget = True   # nothing new is requested, so there is nothing to check
        return
    if a.no_budget:
        print(f"warning: --no-budget: no budget check{'' if a.ledger else ', no ledger'}"
              " (ad-hoc tests in the main session only)", file=sys.stderr)
        return
    if a.budget and not a.ledger:
        usage_error("--budget without --ledger: the budget cannot count earlier requests. "
                    "Pass --ledger out/<project>/ep<NN>/ledger.csv (or FILM_LEDGER)")
    if not (a.budget and a.ledger):
        usage_error(f"refusing to call the paid API without a budget: pass --budget B.yaml --ledger L.csv "
                    f"(or FILM_BUDGET/FILM_LEDGER), or --no-budget for an ad-hoc test (docs/CONVENTIONS.md §7)")


def main(argv=None):
    a = p.parse_args(argv)
    if a.cmd not in ("image", "video"):
        return ping(a)
    check_cost_args(a)
    prev = {s: signal.signal(s, _on_signal) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        return {"image": image, "video": video}[a.cmd](a)
    except Interrupted as e:
        print(f"{e}: stopped (see the ledger for the request's final row)", file=sys.stderr)
        raise
    finally:
        for s, h in prev.items():
            signal.signal(s, h)


if __name__ == "__main__":
    main()
