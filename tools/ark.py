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
  python3 ark.py lambda-job prepare "prompt" out.png [--model dola-seedream-5-0-pro-260628] [--size 2K|4K] [--ref a.png ...]
                       [--refs-dir DIR] [--payload FILE] --ledger L.csv (--budget B.yaml | --no-budget)
  python3 ark.py lambda-job finish --status-json jobs/<job_id>.json [--job ID] [--image downloaded.jpg] [--out out.png] --ledger L.csv
  python3 ark.py ledger-merge A.csv B.csv [...] -o OUT.csv

lambda-job (lambda/README.md): pro and 4K images run on the AWS Lambda worker, outside the proxy. `prepare` does the
same atomic budget check + 'pending' row as `image` and prints the Lambda payload (job_id = the request id);
`finish` turns the worker's jobs/<job_id>.json into the request's final row. No ledger, no Lambda call.
ledger-merge: union of ledgers pulled from Drive or written by two sessions (rows deduplicated by
(req, status, task_id)), so no billed row is lost when two copies exist (docs/CONVENTIONS.md §7, §11.6).

Budget and ledger (docs/CONVENTIONS.md §7): --ledger/--budget (or env FILM_LEDGER/FILM_BUDGET).
image/video refuse to run (exit 2) without BOTH a budget and a ledger, unless --no-budget is given
(ad-hoc tests in the main session only). budget.yaml `ledger_required: true` also refuses (exit 2) when the ledger
file does not exist yet: pull it from Drive first. The budget is checked BEFORE the call (over a cap: exit 3),
in the same exclusive ledger lock that appends the request's 'pending' row (note req=<id>), so parallel
agents cannot overrun a cap. Each request then gets a final row
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
LAMBDA_DEFAULT = "dola-seedream-5-0-pro-260628"   # lambda-job: the model the Lambda worker exists for
LAMBDA_NOTE = "lambda"                            # note tag of rows written by lambda-job
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


def _ledger_record(row):
    rec = {k: "" for k in LEDGER_FIELDS}
    rec.update({k: v for k, v in row.items() if k in rec and v is not None})
    rec["ts"] = rec["ts"] or utc_now()
    rec["agent"] = rec["agent"] or os.environ.get("FILM_AGENT", "")
    return rec


def _write_locked(f, row):
    """Append one row to an open ledger whose LOCK_EX the caller holds; header when the file is empty."""
    f.seek(0, os.SEEK_END)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=LEDGER_FIELDS, lineterminator="\n")
    if f.tell() == 0:
        w.writeheader()
    w.writerow(_ledger_record(row))
    f.write(buf.getvalue())
    f.flush()
    os.fsync(f.fileno())


def _parse_rows(path, text):
    rows = list(csv.DictReader(io.StringIO(text)))
    if rows and list(rows[0].keys()) != LEDGER_FIELDS:
        print(f"warning: {path} header differs from {','.join(LEDGER_FIELDS)}", file=sys.stderr)
    return rows


def ledger_append(path, row):
    """Append one row under an exclusive flock; writes the header when the file is new/empty."""
    if not path:
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a+", newline="", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            _write_locked(f, row)
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
    return _parse_rows(path, text)


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
    return {"images": b.get("images"), "video_seconds": b.get("video_seconds"), "models": models,
            "ledger_required": bool(b.get("ledger_required"))}


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


def reserve(a, req, rid, tag=""):
    """Atomic budget check + reservation (docs/CONVENTIONS.md §7), called just before the POST.
    One LOCK_EX on the ledger covers reading it, summing the billed requests and appending either the
    'pending' row (note req=<rid>) or, over a cap, the 'refused-budget' row (then exit 3). Parallel
    agents are serialised here, so they can no longer all pass the check before any pending row exists.
    Slow work (ref re-encoding, folders, loading budget.yaml) happens before the lock; the API call after it.
    --no-budget: no check, the pending row is still written when a ledger is given.
    budget.yaml `ledger_required: true`: the ledger file must already exist and be non-empty (pulled from Drive),
    else exit 2 before anything is written - an empty ledger would restart every cap from zero."""
    budget = None if a.no_budget else load_budget(a.budget)
    pending = dict(req, status="pending", note="; ".join(x for x in (f"req={rid}", tag) if x))
    if not a.ledger:          # only possible with --no-budget (main() guarantees budget+ledger otherwise)
        return
    if budget and budget.get("ledger_required") and not (os.path.exists(a.ledger) and os.path.getsize(a.ledger)):
        print(f"error: {a.budget} has ledger_required: true but {a.ledger} does not exist (or is empty).\n"
              "Pull the episode's ledger.csv from Drive first (04_SanXuat/ep<NN>-<slug>/ledger.csv, "
              "docs/CONVENTIONS.md §11.6). Only when Drive has none yet (no image/video made for this episode): "
              f"python3 tools/ark.py ledger-merge -o {a.ledger}", file=sys.stderr)
        sys.exit(USAGE_EXIT)
    os.makedirs(os.path.dirname(os.path.abspath(a.ledger)), exist_ok=True)
    with open(a.ledger, "a+", newline="", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            over = []
            if budget:
                f.seek(0)
                over = budget_check(budget, _parse_rows(a.ledger, f.read()), req)
            _write_locked(f, dict(req, status="refused-budget", note="; ".join(over)) if over else pending)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    if over:
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
                     "(possibly still billed). Run it on the Lambda worker: `ark.py lambda-job prepare` "
                     "(lambda/README.md).")
        if a.size.upper() == "4K":
            sys.exit(f"--size 4K takes longer than the proxy's ~{PROXY_CUTOFF}s cutoff and fails with 502 "
                     "(possibly still billed). Use 2K, or the Lambda worker: `ark.py lambda-job prepare` "
                     "(lambda/README.md).")
    req = {"kind": "image", "model": model, "size": a.size, "count": 1, "out": a.out}
    make_out_dir(a.out)
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
    rid = new_req()
    reserve(a, req, rid)      # slow ref re-encoding is done above, outside the ledger lock
    print("model", model)
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
    body = {"model": a.model, "content": content, "duration": a.duration, "resolution": a.resolution,
            "ratio": ratio, "watermark": False}
    if a.no_audio:
        body["generate_audio"] = False
    rid = new_req()
    reserve(a, req, rid)
    print("model", a.model, "| ratio", ratio, "| audio", "off" if a.no_audio else "model default")
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


# --- Lambda jobs: pro / 4K images outside the proxy (lambda/README.md) ---------
def lambda_prepare(a):
    """Budget check + pending row for an image the Lambda worker will make; prints the Invoke payload.
    Nothing is sent anywhere: the caller invokes the Lambda with the payload (AWS MCP run_script)."""
    model = a.model or LAMBDA_DEFAULT
    rid = new_req()
    req = {"kind": "image", "model": model, "size": a.size, "count": 1, "out": a.out}
    make_out_dir(a.out)
    payload = {"job_id": rid, "prompt": a.prompt, "model": model, "size": a.size}
    uploads = []
    if a.ref:
        refs_dir = a.refs_dir or os.path.join(os.path.dirname(os.path.abspath(a.out)), "lambda-refs")
        os.makedirs(refs_dir, exist_ok=True)
        for n, path in enumerate(a.ref, 1):
            raw, desc = ref_jpeg(path)
            local = os.path.join(refs_dir, f"{rid}-{n}.jpg")
            with open(local, "wb") as f:
                f.write(raw)
            print("ref", desc, file=sys.stderr)
            uploads.append((local, f"refs/{rid}-{n}.jpg"))
        payload["ref_keys"] = [key for _, key in uploads]
    reserve(a, req, rid, LAMBDA_NOTE)     # exit 3 over a cap: no payload is printed, so nothing can be invoked
    text = json.dumps(payload, ensure_ascii=False)
    if a.payload:
        os.makedirs(os.path.dirname(os.path.abspath(a.payload)), exist_ok=True)
        with open(a.payload, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)
    for local, key in uploads:
        print(f"upload {local} -> s3 key {key} before invoking", file=sys.stderr)
    print(f"reserved req={rid} in {a.ledger}. Invoke the Lambda once with this payload, then:\n"
          f"  python3 tools/ark.py lambda-job finish --status-json <jobs/{rid}.json> --image <downloaded image>"
          f" --ledger {a.ledger}", file=sys.stderr)


def lambda_finish(a):
    """Final ledger row for a Lambda job from the worker's jobs/<job_id>.json; saves the downloaded image."""
    with open(a.status_json, encoding="utf-8") as f:
        st = json.load(f)
    job = a.job or st.get("job_id")
    if not job or (st.get("job_id") and st["job_id"] != job):
        usage_error(f"job id mismatch: --job {a.job!r}, status file says {st.get('job_id')!r}")
    known = [r for r in ledger_rows(a.ledger) if req_id(r) == job]
    if not known:
        usage_error(f"job {job} has no row in {a.ledger}: every Lambda job starts with 'lambda-job prepare' "
                    "(budget check + pending row). Check that this is the episode's ledger")
    status = st.get("status")
    if status not in ("succeeded", "failed"):
        print(f"job {job} is {status or 'unknown'}: no final row written; read jobs/{job}.json again later",
              file=sys.stderr)
        sys.exit(1)
    last = known[-1]
    req = {k: last.get(k, "") for k in ("kind", "model", "size", "seconds", "count", "out")}
    out = a.out or req.get("out")
    req["out"] = out
    done = [r for r in known if r.get("status") in FINAL]
    secs = f"{LAMBDA_NOTE}; seconds={st.get('seconds', '?')}"
    usage = json.dumps(st.get("usage") or {}, separators=(",", ":"))
    if status == "failed":
        if not done:
            log_row(a, req, job, "failed", f"{secs}; {str(st.get('error', ''))[:240]}")
        print(f"job {job} FAILED: {st.get('error')}\nIt may still have been billed; it stays counted. Not retried.",
              file=sys.stderr)
        sys.exit(1)
    final = dict(count=max(1, len(st.get("keys") or [])), usage=usage)
    if a.image:
        try:
            make_out_dir(out)
            with open(a.image, "rb") as f:
                save_image(f.read(), out)
            print("saved", out)
        except Exception as e:
            if not done:
                log_row(a, req, job, "failed", f"{secs}; save-failed: " + err_note(e), **final)
            print(f"SAVE FAILED ({err_note(e)}): the image was generated and billed; it is still in S3 "
                  f"({', '.join(st.get('keys') or [])})", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"no --image given: the image is still in S3 ({', '.join(st.get('keys') or [])}), "
              f"download it to {out}", file=sys.stderr)
    if done:
        print(f"job {job} already has a final row ({done[-1].get('status')}); ledger unchanged")
        return
    log_row(a, req, job, "ok", secs, **final)
    print("usage", usage, "| seconds", st.get("seconds"))


def _merge_key(row):
    rid = req_id(row)
    if rid:
        return (rid, row.get("status") or "", row.get("task_id") or "")
    return tuple(row.get(k) or "" for k in LEDGER_FIELDS)     # old rows without req=: identical rows only


def merge_rows(row_lists):
    """Union of ledgers: first occurrence of each (req, status, task_id) wins; ordered by time, a request's
    pending rows before its final row. Rows that are not ledger-shaped (no ts/kind/status) are dropped."""
    seen, out = set(), []
    for rows in row_lists:
        for r in rows:
            if not (r.get("ts") and r.get("kind") and r.get("status")):
                continue
            k = _merge_key(r)
            if k not in seen:
                seen.add(k)
                out.append({f: r.get(f) or "" for f in LEDGER_FIELDS})
    out.sort(key=lambda r: (r["ts"], 0 if r["status"] == "pending" else 1))
    return out


def ledger_merge(a):
    """Write the union of the input ledgers to --out under its exclusive lock (it may be one of the inputs).
    With no input: an empty ledger with the header (first generation of an episode with ledger_required)."""
    missing = [p for p in a.ledgers if not os.path.exists(p)]
    if missing:
        usage_error("no such ledger: " + ", ".join(missing))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "a+", newline="", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            current = f.read()
            if not a.ledgers and _parse_rows(a.out, current):
                usage_error(f"{a.out} already has rows; pass the ledgers to merge (it was left untouched)")
            lists = []
            for path in a.ledgers:
                if os.path.exists(a.out) and os.path.samefile(path, a.out):
                    lists.append(_parse_rows(path, current))
                else:
                    lists.append(ledger_rows(path))
            rows = merge_rows(lists)
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=LEDGER_FIELDS, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
            f.seek(0)
            f.truncate()
            f.write(buf.getvalue())
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    counts = ", ".join(f"{os.path.basename(p)}: {len(l)}" for p, l in zip(a.ledgers, lists)) or "no input"
    billed = billed_requests(rows)
    print(f"{a.out}: {len(rows)} row(s) from {counts} · billed requests: "
          f"{sum(units(r) for r in billed if r.get('kind') == 'image'):g} image(s), "
          f"{sum(units(r) for r in billed if r.get('kind') == 'video'):g} video second(s)")


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
lj = sp.add_parser("lambda-job", help="budget + ledger rows for images made by the Lambda worker (pro, 4K)")
ljs = lj.add_subparsers(dest="lcmd", required=True)
lp = ljs.add_parser("prepare", help="budget check + pending row; prints the Lambda Invoke payload (no network)")
lp.add_argument("prompt"); lp.add_argument("out")
lp.add_argument("--model", default=None, help=f"default {LAMBDA_DEFAULT}")
lp.add_argument("--size", default="2K")
lp.add_argument("--ref", nargs="*", help="reference image(s): re-encoded like `image --ref` into --refs-dir as "
                "<job_id>-<n>.jpg, to upload to the bucket as refs/<job_id>-<n>.jpg")
lp.add_argument("--refs-dir", default=None, help="where the re-encoded refs go (default <out dir>/lambda-refs)")
lp.add_argument("--payload", default=None, metavar="FILE", help="also write the payload JSON to this file")
add_cost_args(lp)
lf = ljs.add_parser("finish", help="final ledger row from the worker's jobs/<job_id>.json (no network)")
lf.add_argument("--status-json", required=True, help="local copy of s3 jobs/<job_id>.json")
lf.add_argument("--job", default=None, help="job id (default: job_id in the status file)")
lf.add_argument("--image", default=None, help="the downloaded image; saved to --out (converted to its extension)")
lf.add_argument("--out", default=None, help="output path (default: the out recorded by prepare)")
lf.add_argument("--ledger", default=None, help="the episode's ledger.csv (env FILM_LEDGER)")
lm = sp.add_parser("ledger-merge", help="union of ledger copies (two sessions, two Drive files) into one")
lm.add_argument("ledgers", nargs="*", help="ledgers to merge (none: create an empty ledger with the header)")
lm.add_argument("-o", "--out", required=True, help="merged ledger; may be one of the inputs")


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
    if a.cmd == "ledger-merge":
        return ledger_merge(a)
    if a.cmd == "lambda-job":
        a.ledger = a.ledger or os.environ.get("FILM_LEDGER") or None
        if not a.ledger:      # a Lambda call bypasses the proxy AND every cap unless it is in the ledger
            usage_error("lambda-job needs --ledger (or FILM_LEDGER): no ledger, no Lambda call")
        if a.lcmd == "finish":
            return lambda_finish(a)
        check_cost_args(a)
        return lambda_prepare(a)
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
