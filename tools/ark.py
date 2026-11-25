#!/usr/bin/env python3
"""BytePlus ModelArk from a Claude Code cloud session (AI Film Lab).

  python3 ark.py ping [--all]
  python3 ark.py image "prompt" out.png [--model seedream-5-0-lite-260128 | --fast] [--size 2K|2560x1440] [--ref a.png ...]
                       [--seed N] [--negative TEXT ...] [--guidance F] [--force] [--overwrite]
                       (--ledger L.csv --budget B.yaml | --no-budget [--ledger L.csv])
  python3 ark.py image-batch JOBS.csv [--parallel N (default 3, max 4)] [--dry-run] [--only ID ...] [--fast]
                       (--ledger L.csv --budget B.yaml | --no-budget [--ledger L.csv])     (`image-batch --help`: the CSV)
  python3 ark.py video "prompt" out.mp4 [--image first.png] [--model dreamina-seedance-2-5-260628]
                       [--ratio 16:9 (text-only; with --image the image decides)] [--duration 5]
                       [--resolution 480p|720p|1080p (default 720p)] [--no-audio] [--overwrite]
                       (--ledger L.csv --budget B.yaml | --no-budget [--ledger L.csv])
  python3 ark.py video --resume-task TASK_ID [out.mp4] --ledger L.csv
  python3 ark.py video --resume-pending --ledger L.csv          (every open video task of the ledger, one by one)
  python3 ark.py lambda-job prepare "prompt" out.png [--model dola-seedream-5-0-pro-260628] [--size 2K|4K] [--ref a.png ...]
                       [--refs-dir DIR] [--payload FILE] [--overwrite] --ledger L.csv (--budget B.yaml | --no-budget)
  python3 ark.py lambda-job finish --status-json jobs/<job_id>.json [--job ID] [--image downloaded.jpg] [--out out.png]
                       [--give-up] --ledger L.csv
  python3 ark.py ledger-merge A.csv B.csv [...] -o OUT.csv
  python3 ark.py ledger-close --req ID --status abandoned [--note TEXT] --ledger L.csv

image-batch: every row of a CSV is one `image` request (same ledger rows, same guards, never retried). All rows are
validated before anything is sent (exit 2 lists every problem), rows whose output file exists are skipped, the batch
is checked against the caps as a whole before the first request (exit 3, one refused-budget row), then up to
--parallel requests run at a time; each one still passes the atomic check below.

lambda-job (lambda/README.md): pro and 4K images run on the AWS Lambda worker, outside the proxy. `prepare` does the
same atomic budget check + 'pending' row as `image` and prints the Lambda payload (job_id = the request id);
`finish` turns the worker's jobs/<job_id>.json into the request's final row (`failed-unsent`, not counted, when the
worker never sent it; a job still `running` past its deadline is dead: `--give-up` closes it as a counted `failed`).
No ledger, no Lambda call.
ledger-merge: union of ledgers pulled from Drive or written by two sessions (rows deduplicated by
(req, status, task_id); rows without req= as a multiset), so no billed row is lost when two copies exist
(docs/CONVENTIONS.md §7, §11.6). Every row is checked first (file:line, exit 2, nothing written), and the result
must count every request at least as much as each copy does.
ledger-close: a final `abandoned` row for an orphan pending request (killed agent, prepared but never invoked Lambda
job): it stays counted against the caps, it is only no longer open.

Budget and ledger (docs/CONVENTIONS.md §7): --ledger/--budget (or env FILM_LEDGER/FILM_BUDGET).
image/video refuse to run (exit 2) without BOTH a budget and a ledger, unless --no-budget is given
(ad-hoc tests in the main session only: with FILM_AGENT set, --no-budget and --force are refused). budget.yaml `ledger_required: true` also refuses (exit 2) when the ledger
file does not exist yet: pull it from Drive first. The budget is checked BEFORE the call (over a cap: exit 3),
in the same exclusive ledger lock that appends the request's 'pending' row (note req=<id>), so parallel
agents cannot overrun a cap. Each request then gets a final row
(ok/failed/cut-502, same req=<id>) after it, so a killed process still leaves a billed row. A response without
image data is a failed row; extra images of one response never replace an existing file.

Exit codes of image / video / lambda-job prepare: 2 = refused locally (nothing sent, no ledger row, no output folder:
fix the command), 3 = over a cap (refused-budget row), 1 = the request left this machine (see its ledger row).
Local refusals, checked before anything is written or sent: a --size larger than 2K or a pro model on `image`
(the proxy would cut it), a missing --ref / --image file or a --ref that is not an image, an output file that already exists (versions only go up;
--overwrite for ad-hoc use), a budget.yaml with an unknown key, a bad value or no cap for the request, and a ledger
whose header is not the ledger header.

Credentials: in a Claude cloud session the agent proxy injects the real Ark key
for ark.ap-southeast.bytepluses.com, so this script sends a placeholder. Outside
that proxy, set ARK_API_KEY. Never print, log or search for the key.
"""
import argparse, base64, contextlib, csv, datetime, difflib, fcntl, hashlib, http.client, io, json, mimetypes, os, re
import signal, sys, threading, time, uuid
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
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:
        # no traceback; the message never holds the request (its headers carry the key)
        sys.exit(f"network error: {type(e).__name__}: {getattr(e, 'reason', None) or e}")


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


def encode_ref(path):
    """ref_jpeg() for a request that has not been reserved yet: a file that is not a readable image is a local
    refusal (exit 2), not a traceback."""
    try:
        return ref_jpeg(path)
    except Exception as e:
        usage_error(f"cannot read image: {path} ({type(e).__name__})")


def ref_data_uri(path):
    raw, desc = encode_ref(path)
    print("ref", desc)
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode()


# --- models available on this account (see Ark Console) --------------------
IMAGE_DEFAULT = "seedream-5-0-lite-260128"        # Dola-Seedream-5.0-lite, 2K ~25s
IMAGE_FAST = "dola-seedream-5-0-flash-260915"     # Dola-Seedream-5.0-flash
IMAGE_SLOW = {"dola-seedream-5-0-pro-260628"}     # always > proxy cutoff (any '-pro-' id counts as slow)
LAMBDA_DEFAULT = "dola-seedream-5-0-pro-260628"   # lambda-job: the model the Lambda worker exists for
LAMBDA_NOTE = "lambda"                            # note tag of rows written by lambda-job
VIDEO_DEFAULT = "dreamina-seedance-2-5-260628"    # Dreamina-Seedance-2.5
PROXY_CUTOFF = 30  # seconds: the agent proxy cuts synchronous requests here
POLL_SECONDS = 10  # video task polling interval
POLL_RETRIES = 5   # consecutive failed status GETs tolerated before polling stops (the task keeps running)
POLL_RETRYABLE = ("network error", "HTTP 429", "HTTP 5")   # prefixes of call()'s messages worth another GET
DOWNLOAD_ATTEMPTS = 3
DOWNLOAD_RETRY_SECONDS = 2
MAX_PIXELS = 2048 * 2048 * 1.15   # `image --size WxH` above this is "larger than 2K" (2560x1440 fits)
VIDEO_RESOLUTIONS = ("480p", "720p", "1080p")
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


def save_image(raw, out, quiet=False):
    """Write raw bytes, converting so the content matches the file extension."""
    want = EXT_FORMAT.get(os.path.splitext(out)[1].lower())
    got = sniff_mime(raw)
    if want and got and got != want[1]:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        if want[0] == "JPEG" and im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.save(out, want[0])
        if not quiet:
            print(f"converted {got} -> {want[1]}")
    else:
        open(out, "wb").write(raw)


def download(url, out):
    """Fetch url into out via <out>.part: `out` only ever holds a complete file. Up to DOWNLOAD_ATTEMPTS tries;
    a failed download leaves neither a stub at `out` nor the .part (an older file at `out` is left as it was)."""
    part = out + ".part"
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(url, timeout=300) as r, open(part, "wb") as f:
                want, got = r.headers.get("Content-Length"), 0
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
            if got == 0 or (want is not None and got != int(want)):
                raise OSError(f"incomplete download: {got} of {want or '?'} bytes")
            os.replace(part, out)
            return
        except BaseException as e:
            if os.path.exists(part):
                os.remove(part)
            if not isinstance(e, Exception) or attempt == DOWNLOAD_ATTEMPTS:
                raise            # a signal (Interrupted) is never retried
            print(f"download error ({attempt}/{DOWNLOAD_ATTEMPTS}): {err_note(e)}", file=sys.stderr)
            time.sleep(DOWNLOAD_RETRY_SECONDS * attempt)


# --- ledger and budget (docs/CONVENTIONS.md §7) ------------------------------
LEDGER_FIELDS = ["ts", "kind", "model", "size", "seconds", "count", "status", "out", "task_id", "usage", "agent", "note"]
# final row of a request (closes it): ok/failed/cut-502 may have been billed; abandoned = an orphan pending row closed
# by `ledger-close` (still billed); failed-unsent = a Lambda job whose worker never sent the request (sent: false)
FINAL = {"ok", "failed", "cut-502", "abandoned", "failed-unsent"}
UNBILLED = {"failed-unsent"}           # final rows that close a request without counting it
BILLED = FINAL | {"pending"}           # pending: written before the call, counts until a final row exists
STATUSES = BILLED | {"refused-budget"}   # every status a ledger row may carry (ledger-merge refuses others)
BUDGET_EXIT = 3
USAGE_EXIT = 2
REQ_RE = re.compile(r"req=([0-9a-f]+)(?=;|\s|$)")   # the whole token: 'req=abcXYZ' is no request id


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ledger_record(row):
    rec = {k: "" for k in LEDGER_FIELDS}
    rec.update({k: v for k, v in row.items() if k in rec and v is not None})
    rec["ts"] = rec["ts"] or utc_now()
    rec["agent"] = rec["agent"] or os.environ.get("FILM_AGENT", "")
    return rec


def _write_locked(f, row):
    """Append one row to an open ledger whose LOCK_EX the caller holds; header when the file is empty.
    A ledger whose last line has no newline (hand edit, torn write) gets one first: otherwise the new row is glued
    onto that line, the new request vanishes from the count and the previous one gets a wrong req id."""
    f.seek(0, os.SEEK_END)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=LEDGER_FIELDS, lineterminator="\n")
    size = os.fstat(f.fileno()).st_size
    if size == 0:
        w.writeheader()
    elif os.pread(f.fileno(), 1, size - 1) not in (b"\n", b"\r"):
        buf.write("\n")
    w.writerow(_ledger_record(row))
    f.write(buf.getvalue())
    f.flush()
    os.fsync(f.fileno())


def _parse_rows(path, text):
    text = text.lstrip("\ufeff")     # a UTF-8 BOM (saved from a spreadsheet) would turn the 'ts' column into '\ufeffts'
    rows = list(csv.DictReader(io.StringIO(text)))
    if rows and list(rows[0].keys()) != LEDGER_FIELDS:
        print(f"warning: {path} header differs from {','.join(LEDGER_FIELDS)}", file=sys.stderr)
    return rows


def _header_ok(text):
    """True when the first CSV record of a ledger's text is exactly LEDGER_FIELDS (BOM and CRLF tolerated)."""
    return next(csv.reader(io.StringIO(text.lstrip("\ufeff"))), None) == LEDGER_FIELDS


def _header_refusal(path):
    usage_error(f"ledger header mismatch in {path}: repair it or pull it again; nothing sent")


def _unreadable_ledger(path, e):
    """A ledger that is not UTF-8 text (a UTF-16 export, a folder) cannot be counted: refuse, do not crash."""
    usage_error(f"ledger {path} cannot be read ({getattr(e, 'strerror', None) or type(e).__name__}): "
                "repair it or pull it again; nothing sent")


def check_ledger_header(path):
    """Early (unlocked) copy of the check reserve() repeats inside the ledger lock: a refusal here happens before
    the output folder exists. A ledger with a foreign header would be read as zero billed requests."""
    if path and os.path.exists(path) and os.path.getsize(path):
        try:
            with open(path, newline="", encoding="utf-8") as f:
                head = f.readline()
        except (OSError, UnicodeDecodeError) as e:
            _unreadable_ledger(path, e)
        if not _header_ok(head):
            _header_refusal(path)


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


BUDGET_KEYS = ("images", "video_seconds", "models", "ledger_required")


def _is_cap(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0     # NaN fails x >= 0


def load_budget(path):
    """Read and validate budget.yaml; any problem is exit 2 `budget <path>: <reason>` (docs/CONVENTIONS.md §7).
    A cap that is silently missing means "no cap", so nothing is guessed: only the four known keys, numbers >= 0."""
    if not path:
        return None
    import yaml

    def bad(reason):
        usage_error(f"budget {path}: {reason}")
    try:
        with open(path, encoding="utf-8") as f:
            b = yaml.safe_load(f)
    except (OSError, UnicodeDecodeError) as e:
        bad(f"cannot read it ({getattr(e, 'strerror', None) or type(e).__name__})")
    except yaml.YAMLError as e:
        bad("invalid YAML (" + " ".join(str(e).split())[:160] + ")")
    if b is None:              # an empty or comment-only file is an empty mapping: it has no cap at all
        b = {}
    if not isinstance(b, dict):
        bad("expected a mapping with " + " / ".join(BUDGET_KEYS))
    for key in b:
        if key not in BUDGET_KEYS:
            close = difflib.get_close_matches(str(key), BUDGET_KEYS, n=1, cutoff=0.4)
            bad(f"unknown key {str(key)!r}" + (f", did you mean {close[0]!r}?" if close else "")
                + " (allowed keys: " + ", ".join(BUDGET_KEYS) + ")")
    for key in ("images", "video_seconds"):
        if key in b and not _is_cap(b[key]):
            bad(f"{key!r} must be a number >= 0, not {b[key]!r}")
    models = b.get("models")
    if models is None:
        models = {}
    if not isinstance(models, dict):
        bad("'models' must be a mapping model-id -> cap")
    for model, cap in models.items():
        if not _is_cap(cap):
            bad(f"models.{model} must be a number >= 0, not {cap!r}")
    if "ledger_required" in b and not isinstance(b["ledger_required"], bool):
        bad(f"'ledger_required' must be true or false, not {b['ledger_required']!r}")
    return {"images": b.get("images"), "video_seconds": b.get("video_seconds"), "models": models,
            "ledger_required": bool(b.get("ledger_required"))}


def checked_budget(a, kind, model):
    """Everything about budget and ledger that can be refused (exit 2) before any work is done for a request:
    the ledger header, budget.yaml itself, a cap that covers this request, ledger_required. Returns the budget
    (None with --no-budget) for reserve()."""
    check_ledger_header(a.ledger)
    if a.no_budget:
        return None
    budget = load_budget(a.budget)
    need_cap(a, budget, kind, model)
    need_ledger(a, budget)
    return budget


def need_cap(a, budget, kind, model):
    """Exit 2 when no cap of the budget covers a request of this kind and model."""
    cap = "images" if kind == "image" else "video_seconds"
    if budget[cap] is None and budget["models"].get(model) is None:
        usage_error(f"budget {a.budget} has no cap for {kind} ({model}): add `{cap}:` or `models: {{{model}: N}}`")


def need_ledger(a, budget):
    """Exit 2 for `ledger_required: true` without a ledger file."""
    if budget["ledger_required"] and not (os.path.exists(a.ledger) and os.path.getsize(a.ledger)):
        print(f"error: {a.budget} has ledger_required: true but {a.ledger} does not exist (or is empty).\n"
              "Pull the episode's ledger.csv from Drive first (04_SanXuat/ep<NN>-<slug>/ledger.csv, "
              "docs/CONVENTIONS.md §11.6). Only when Drive has none yet (no image/video made for this episode): "
              f"python3 tools/ark.py ledger-merge -o {a.ledger}", file=sys.stderr)
        sys.exit(USAGE_EXIT)


def _num(x):
    try:
        return float(x or 0)
    except ValueError:
        return 0.0


def units(row):
    """Billing units of a ledger row: images for kind=image, seconds for kind=video."""
    n = _num(row.get("seconds")) if row.get("kind") == "video" else _num(row.get("count") or 1)
    return max(0.0, n)        # a negative row must never credit a cap


def req_id(row):
    """The request id of a ledger row (note starts with 'req=<hex>'), or None for old/refused rows."""
    m = REQ_RE.match(row.get("note") or "")
    return m.group(1) if m else None


def request_rows(rows):
    """[(key, row)]: the row that decides each request (docs/CONVENTIONS.md §7), unbilled ones included.
    Rows are grouped by req id (else by task_id); a group is decided by its last final row (FINAL) or, with none,
    by its last pending row. Rows with neither id are requests of their own, keyed ('row', fields, n-th copy)."""
    single, groups, seen = [], {}, {}
    for r in rows:
        if r.get("status") not in BILLED:
            continue
        key = req_id(r) or ("task:" + r["task_id"] if r.get("task_id") else None)
        if key is None:
            t = tuple(r.get(k) or "" for k in LEDGER_FIELDS)
            seen[t] = seen.get(t, 0) + 1
            single.append((("row", t, seen[t]), r))
        else:
            groups.setdefault(key, []).append(r)
    out = list(single)
    for key, g in groups.items():
        finals = [r for r in g if r.get("status") in FINAL]
        out.append((key, (finals or g)[-1]))
    return out


def billed_requests(rows):
    """One row per request that may have been billed (docs/CONVENTIONS.md §7): request_rows() without the
    requests closed as failed-unsent (never sent)."""
    return [r for _, r in request_rows(rows) if r.get("status") not in UNBILLED]


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


def reserve(a, req, rid, tag="", budget=None):
    """Atomic budget check + reservation (docs/CONVENTIONS.md §7), called just before the POST.
    One LOCK_EX on the ledger covers reading it, summing the billed requests and appending either the
    'pending' row (note req=<rid>) or, over a cap, the 'refused-budget' row (then exit 3). Parallel
    agents are serialised here, so they can no longer all pass the check before any pending row exists.
    Slow work (ref re-encoding, folders, loading budget.yaml) happens before the lock; the API call after it.
    `budget` is what checked_budget() returned (None with --no-budget: no check, the pending row is still written
    when a ledger is given). checked_budget() has already refused, with exit 2 and before anything was written,
    a bad budget.yaml, a request no cap covers and `ledger_required: true` without a ledger.
    A non-empty ledger whose header is not LEDGER_FIELDS is refused here again, inside the lock (exit 2, no row):
    it would be read as zero billed requests and restart every cap from zero."""
    pending = dict(req, status="pending", note="; ".join(x for x in (f"req={rid}", tag) if x))
    if not a.ledger:          # only possible with --no-budget (main() guarantees budget+ledger otherwise)
        return
    os.makedirs(os.path.dirname(os.path.abspath(a.ledger)), exist_ok=True)
    with open(a.ledger, "a+", newline="", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            try:
                text = f.read()
            except UnicodeDecodeError as e:       # e.g. one Latin-1 row under a good header
                _unreadable_ledger(a.ledger, e)
            if text and not _header_ok(text):     # also with --no-budget: no row is appended to a foreign file
                _header_refusal(a.ledger)
            over = budget_check(budget, _parse_rows(a.ledger, text), req) if budget else []
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


VERSION_RE = re.compile(r"_v(\d+)$")
NAMED_SIZE_RE = re.compile(r"(\d+)K", re.I | re.A)      # ASCII digits only: the value is sent as typed
WXH_RE = re.compile(r"(\d+)x(\d+)", re.I | re.A)


def need_files(paths):
    """Exit 2 for an input file (--ref, --image) that is missing or unreadable, before anything is re-encoded."""
    for path in paths or []:
        if not (os.path.isfile(path) and os.access(path, os.R_OK)):
            usage_error(f"no such file: {path}")


def guard_output(path, overwrite=False):
    """Exit 2 when the output file already exists (size > 0): a paid file is never replaced, versions only go up.
    The message suggests the first free `_v<NN>` (same zero padding) when the name ends in one."""
    if overwrite or not (os.path.exists(path) and os.path.getsize(path) > 0):
        return
    stem, ext = os.path.splitext(path)
    m = VERSION_RE.search(stem)
    if not m:
        usage_error(f"output exists: {path} (versions only go up)")
    n, width = int(m.group(1)), len(m.group(1))
    while True:
        n += 1
        free = f"{stem[:m.start()]}_v{n:0{width}d}{ext}"
        if not os.path.exists(free):
            break
    usage_error(f"output exists: {path} (versions only go up; next free: {free})")


def extra_out(out, n, rid, avoid=()):
    """File for image n >= 1 of a multi-image response: <stem>-<n><ext>, or <stem>-<n>-<req id[:8]><ext> when that
    file exists already or is another batch row's out (realpaths in `avoid`): a paid file is never replaced."""
    stem, ext = os.path.splitext(out)
    path = f"{stem}-{n}{ext}"
    if (os.path.exists(path) and os.path.getsize(path) > 0) or os.path.realpath(path) in avoid:
        path = f"{stem}-{n}-{rid[:8]}{ext}"
    return path


def guard_proxy_cut(model, size):
    """Exit 2 for an `image` request the proxy would cut at ~30 s (and that may still be billed)."""
    force = "" if os.environ.get("FILM_AGENT") else " (--force sends it anyway)"
    lam = "the Lambda worker: `ark.py lambda-job prepare` (lambda/README.md)"
    if model in IMAGE_SLOW or "-pro-" in model.lower():
        usage_error(f"{model} always takes longer than the proxy's ~{PROXY_CUTOFF}s cutoff and fails with 502 "
                    f"(possibly still billed). Run it on {lam}.{force}")
    named, wxh = NAMED_SIZE_RE.fullmatch(size), WXH_RE.fullmatch(size)
    if not (named or wxh) or 0 in [int(x) for x in (named or wxh).groups()]:
        usage_error(f"unknown --size {size}: use 1K, 2K or <W>x<H> (e.g. 2560x1440).{force}")
    if (int(named.group(1)) not in (1, 2)) if named else (int(wxh.group(1)) * int(wxh.group(2)) > MAX_PIXELS):
        usage_error(f"--size {size} is larger than 2K: it takes longer than the proxy's ~{PROXY_CUTOFF}s cutoff "
                    f"and fails with 502 (possibly still billed). Use 2K, or {lam}.{force}")


def image(a):
    model = a.model or (IMAGE_FAST if a.fast else IMAGE_DEFAULT)
    if not a.force:
        guard_proxy_cut(model, a.size)
    need_files(a.ref)
    guard_output(a.out, a.overwrite)
    budget = checked_budget(a, "image", model)
    req = {"kind": "image", "model": model, "size": a.size, "count": 1, "out": a.out}
    refs = [ref_data_uri(p) for p in a.ref or []]      # exit 2 for a file that is not an image: before any folder
    make_out_dir(a.out)
    body = {"model": model, "prompt": a.prompt, "size": a.size, "response_format": "b64_json", "watermark": False}
    if a.seed is not None:
        body["seed"] = a.seed
    if a.negative:
        body["negative_prompt"] = ", ".join(a.negative)
    if a.guidance is not None:
        body["guidance_scale"] = a.guidance
    if refs:
        body["image"] = refs if len(refs) > 1 else refs[0]
    rid = new_req()
    reserve(a, req, rid, budget=budget)      # slow ref re-encoding is done above, outside the ledger lock
    print("model", model)
    try:
        r = api("POST", "/images/generations", body)
    except BaseException as e:
        log_row(a, req, rid, fail_status(e), err_note(e))
        raise
    data = r.get("data") or []
    final = dict(count=max(1, len(data)), usage=json.dumps(r.get("usage", {}), separators=(",", ":")))
    if not data:
        log_row(a, req, rid, "failed", "no image in the response", **final)
        print(f"FAILED: the response has no image data (it may still have been billed; not retried): "
              f"{json.dumps(r)[:300]}", file=sys.stderr)
        sys.exit(1)
    try:
        for i, d in enumerate(data):
            out = a.out if i == 0 else extra_out(a.out, i, rid)
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


# --- image-batch: a CSV of plates, one `image` request per row -------------------
# Not implemented on purpose (GitHub issue #28): Ark's asynchronous Batch API (cheaper batch pricing) and Seedream's
# sequential / group image generation. Neither has been verified on this account and both need paid requests to
# test, so a batch here is N ordinary synchronous requests at the normal price (docs/MODELS.md).
BATCH_COLUMNS = ("id", "prompt", "out", "size", "model", "ref", "seed", "negative")
BATCH_REQUIRED = ("id", "prompt", "out")
BATCH_PARALLEL = 3
BATCH_MAX_PARALLEL = 4
FORCE_HINT = " (--force sends it anyway)"      # guard_proxy_cut's hint; a batch has no --force
# a failed request after which every further request would fail the same way: stop scheduling new rows
BATCH_STOP_RE = re.compile(r"^HTTP 40[13]\b|overdue|arrears|insufficient.{0,20}balance|"
                           r"balance.{0,20}(insufficient|not enough)", re.I)

BATCH_HELP = f"""\
Generate every row of JOBS.csv as one `ark.py image` request (same ledger rows, same guards, never retried).

JOBS.csv is UTF-8 with a header row. Columns (any other column is an error):
  id        required, unique; names the row in every message and in --only
  prompt    required; the prompt text, or @FILE to read it from a file (path relative to the CSV)
  out       required; output file, relative to the current directory like `image` (not to the CSV); unique
  size      1K, 2K or <W>x<H> up to about 2K (default 2K)
  model     model id; empty = {IMAGE_DEFAULT}, or {IMAGE_FAST} with --fast
  ref       reference image paths separated by ';' (relative to the current directory)
  seed      integer, sent as 'seed'
  negative  text, sent as 'negative_prompt'

1. Every row is validated before anything is sent or written; exit 2 lists every problem with its row id.
   A row whose output file already exists (size > 0) is not a problem: it is skipped (`skip <id>: output exists`),
   so a batch can be run again after an interruption without paying twice. There is no --overwrite: to redo a
   plate, give the row a new out (_v<NN> + 1).
2. The rows left are counted against every cap of the budget before the first request; over a cap: the numbers,
   one refused-budget ledger row for the batch, exit 3, nothing sent.
3. Up to --parallel requests run at a time. Each one is checked against the budget again when it starts (the same
   atomic check as `image`) and writes its pending and final ledger rows. A failed row does not stop the others;
   a budget refusal, HTTP 401/403 or an account-balance error stops new rows from starting (rows in flight finish),
   and so does SIGINT/SIGTERM (exit 130/143). One line per finished row:
     ok|failed|cut-502 <id> <out> <seconds>s
   then `batch: N ok, N failed, N cut-502, N skipped, N not started · images used U/CAP`.

Exit codes: 0 nothing failed · 1 at least one request left this machine and failed (see its ledger row; it may
have been billed, do not rerun blindly) · 2 validation, nothing sent · 3 budget.
--dry-run does steps 1 and 2 only: prints the plan and the budget after the batch, writes nothing.
"""


def _refusal(fn, *args):
    """Run a local guard that exits through usage_error(); return (its message or None, its return value)."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(buf):
            return None, fn(*args)
    except SystemExit:
        msg = buf.getvalue().strip()
        return (msg[7:] if msg.startswith("error: ") else msg).replace(FORCE_HINT, ""), None


def read_jobs(a):
    """Phase 1: parse and validate every row of the jobs CSV. Returns (to send, skipped), each a list of job dicts
    in CSV order; any problem in any row is exit 2 with all of them listed. Nothing is written or sent here."""
    try:
        with open(a.jobs, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            raw = []
            for r in reader:
                raw.append((reader.line_num, r))
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        usage_error(f"cannot read {a.jobs} ({getattr(e, 'strerror', None) or type(e).__name__}): "
                    "a UTF-8 CSV with a header row is expected")
    if not header:
        usage_error(f"{a.jobs}: no header row (columns: {','.join(BATCH_COLUMNS)})")
    header = [h.strip() for h in header]
    unknown = [h for h in header if h not in BATCH_COLUMNS]
    if unknown:
        usage_error(f"{a.jobs}: unknown column(s) {', '.join(repr(h) for h in unknown)} "
                    f"(allowed: {','.join(BATCH_COLUMNS)})")
    missing = [h for h in BATCH_REQUIRED if h not in header]
    if missing or len(set(header)) != len(header):
        usage_error(f"{a.jobs}: " + (f"missing column(s) {', '.join(missing)}" if missing else "a column is repeated")
                    + f" (required: {','.join(BATCH_REQUIRED)})")
    if not raw:
        usage_error(f"{a.jobs}: no rows")
    base = os.path.dirname(os.path.abspath(a.jobs))
    default_model = IMAGE_FAST if a.fast else IMAGE_DEFAULT
    problems, jobs, ids, outs = [], [], {}, {}
    for line, r in raw:
        v = {h.strip(): (x or "").strip() for h, x in r.items() if h is not None}
        v = {k: v.get(k, "") for k in BATCH_COLUMNS}
        label = v["id"] or f"line {line}"

        def bad(msg, label=label):
            problems.append(f"{label}: {msg}")
        if r.get(None):
            bad("more cells than the header has columns (quote a prompt that contains a comma)")
        if not v["id"]:
            bad("id is empty")
        elif v["id"] in ids:
            problems.append(f"line {line}: duplicate id {v['id']!r} (first on line {ids[v['id']]})")
        else:
            ids[v["id"]] = line
        prompt = v["prompt"]
        if prompt.startswith("@"):
            path = os.path.join(base, prompt[1:])
            try:
                with open(path, encoding="utf-8") as f:
                    prompt = f.read().strip()
            except (OSError, UnicodeDecodeError) as e:
                bad(f"prompt file {path}: cannot read it ({getattr(e, 'strerror', None) or type(e).__name__})")
                prompt = None
        if prompt == "":
            bad("prompt is empty")
        exists = False
        if not v["out"]:
            bad("out is empty")
        else:
            key = os.path.realpath(v["out"])        # one file through two paths (a symlinked folder) is one out
            if key in outs:
                bad(f"out {v['out']} is the same file as row {outs[key]}")
            elif os.path.isdir(key):
                bad(f"out {v['out']} is a directory")
            else:
                outs[key] = label
                exists = os.path.exists(key) and os.path.getsize(key) > 0
        size, model = v["size"] or "2K", v["model"] or default_model
        msg, _ = _refusal(guard_proxy_cut, model, size)
        if msg:
            bad(msg)
        refs = [x.strip() for x in v["ref"].split(";") if x.strip()]
        for path in refs:
            msg, _ = _refusal(need_files, [path])
            if msg:
                bad(msg)
        seed = None
        if v["seed"]:
            try:
                seed = int(v["seed"])
            except ValueError:
                bad(f"seed must be an integer, not {v['seed']!r}")
        jobs.append({"id": v["id"], "prompt": prompt, "out": v["out"], "size": size, "model": model, "refs": refs,
                     "seed": seed, "negative": v["negative"], "exists": exists})
    for wanted in a.only or []:
        if wanted not in ids:
            problems.append(f"--only: no row with id {wanted!r}")
    chosen = [j for j in jobs if not a.only or j["id"] in a.only]
    todo, skipped = [j for j in chosen if not j["exists"]], [j for j in chosen if j["exists"]]
    # refs of the rows that will be sent are re-encoded now, once per file: a file that is not an image is a
    # validation problem, not a request that fails after its neighbours were paid for
    uris, notes = {}, []
    for j in todo:
        for path in j["refs"]:
            if path in uris or not os.path.isfile(path):
                continue
            msg, got = _refusal(encode_ref, path)
            if msg:
                problems.append(f"{j['id'] or '?'}: {msg}")
                uris[path] = None
            else:
                uris[path] = "data:image/jpeg;base64," + base64.b64encode(got[0]).decode()
                notes.append(got[1])
        j["ref_uris"] = [uris.get(path) for path in j["refs"]]
    if problems:
        print(f"error: {a.jobs}: {len(problems)} problem(s), nothing sent, nothing written:\n  "
              + "\n  ".join(problems), file=sys.stderr)
        sys.exit(USAGE_EXIT)
    for note in notes:
        print("ref", note)
    return todo, skipped


def _image_units(rows, model=None):
    """Billed image units in ledger rows; with `model`, the units of that model (any kind, like budget_check)."""
    return sum(units(r) for r in billed_requests(rows)
               if (r.get("model") == model if model else r.get("kind") == "image"))


def batch_caps(budget, rows, todo):
    """Phase 2 numbers: [(cap name, used, needed, cap)] for every cap the batch touches."""
    caps = []
    if budget and todo:
        if budget["images"] is not None:
            caps.append(("images", _image_units(rows), len(todo), budget["images"]))
        for model in sorted({j["model"] for j in todo}):
            if budget["models"].get(model) is not None:
                caps.append((f"models.{model}", _image_units(rows, model),
                             sum(1 for j in todo if j["model"] == model), budget["models"][model]))
    return caps


def batch_ledger_rows(a):
    try:
        return ledger_rows(a.ledger)
    except (OSError, UnicodeDecodeError) as e:
        _unreadable_ledger(a.ledger, e)


def batch_row(a, job, budget, avoid=frozenset()):
    """One row = one `image` request: pending row (atomic budget check), POST, save, final row. Never retried.
    Returns (ok|failed|cut-502, detail). A SystemExit out of reserve() means nothing was sent."""
    req = {"kind": "image", "model": job["model"], "size": job["size"], "count": 1, "out": job["out"]}
    body = {"model": job["model"], "prompt": job["prompt"], "size": job["size"], "response_format": "b64_json",
            "watermark": False}
    if job["seed"] is not None:
        body["seed"] = job["seed"]
    if job["negative"]:
        body["negative_prompt"] = job["negative"]
    if job["ref_uris"]:
        body["image"] = job["ref_uris"] if len(job["ref_uris"]) > 1 else job["ref_uris"][0]
    make_out_dir(job["out"])
    rid = new_req()
    reserve(a, req, rid, budget=budget)
    job["reserved"] = True          # from here on the request counts as sent, whatever goes wrong
    try:
        r = api("POST", "/images/generations", body)
    except BaseException as e:
        log_row(a, req, rid, fail_status(e), err_note(e))
        return fail_status(e), err_note(e)
    final = {}
    try:
        data = r.get("data") or []
        final = dict(count=max(1, len(data)), usage=json.dumps(r.get("usage", {}), separators=(",", ":")))
        if not data:
            raise ValueError("no image in the response")
        for n, d in enumerate(data):
            out = job["out"] if n == 0 else extra_out(job["out"], n, rid, avoid)
            # `out` only ever holds a complete file: a rerun skips a row by its output file. The request id keeps
            # the temporary name clear of every other row's out and of files already in the folder
            stem, ext = os.path.splitext(out)
            part = f"{stem}.{rid}.part{ext}"
            try:
                save_image(base64.b64decode(d["b64_json"]), part, quiet=True)
                os.replace(part, out)
            finally:
                if os.path.exists(part):
                    os.remove(part)
    except BaseException as e:
        log_row(a, req, rid, "failed", "save-failed: " + err_note(e), **final)
        return "failed", f"save-failed: {err_note(e)} (generated and billed, not saved)"
    log_row(a, req, rid, "ok", **final)
    return "ok", ""


def image_batch(a):
    todo, skipped = read_jobs(a)                                    # phase 1: exit 2
    check_ledger_header(a.ledger)
    budget = None if a.no_budget else load_budget(a.budget)
    if budget and todo:
        for model in sorted({j["model"] for j in todo}):
            need_cap(a, budget, "image", model)
        need_ledger(a, budget)
    for j in skipped:
        print(f"skip {j['id']}: output exists ({j['out']})")
    if a.dry_run:
        for j in todo:
            print(f"send {j['id']} {j['model']} {j['size']} {j['out']}")
    caps = batch_caps(budget, batch_ledger_rows(a), todo)           # phase 2: exit 3
    over = [f"{name}: {used:g} used + {need:g} requested > cap {cap}" for name, used, need, cap in caps
            if used + need > cap]
    if over:
        note = f"batch of {len(todo)}: " + "; ".join(over)
        if not a.dry_run:
            models = {j["model"] for j in todo}
            ledger_append(a.ledger, {"kind": "image", "model": models.pop() if len(models) == 1 else "",
                                     "count": len(todo), "status": "refused-budget", "out": a.jobs, "note": note})
        print(f"REFUSED (budget {a.budget}): {note}\nNothing was sent to the API. Shrink the batch (--only) or ask "
              "the user (main session) to raise the cap in budget.yaml.", file=sys.stderr)
        sys.exit(BUDGET_EXIT)
    if a.dry_run:
        after = "; ".join(f"{name} {used:g} used + {need:g} = {used + need:g}/{cap}" for name, used, need, cap in caps)
        print(f"dry-run: {len(todo)} to send, {len(skipped)} skipped · budget after the batch: "
              + (after or ("no budget (--no-budget)" if not budget else "nothing to send")))
        return 0

    # phase 3: bounded parallelism; every request does its own atomic reserve()
    avoid = frozenset(os.path.realpath(j["out"]) for j in todo + skipped)   # extra images never take a row's out
    lock = threading.Lock()
    queue = list(todo)
    count = {"ok": 0, "failed": 0, "cut-502": 0}
    state = {"stop": None, "code": 0, "signal": None}

    def stop(reason, code=0, unsent=None):
        with lock:
            if unsent:
                queue.insert(0, unsent)
            state["stop"] = state["stop"] or reason
            state["code"] = state["code"] or code

    def worker():
        while True:
            with lock:
                if state["stop"] or not queue:
                    return
                job = queue.pop(0)
                # the output appeared since validation (a second run of the same CSV): never paid for twice
                if os.path.exists(job["out"]) and os.path.getsize(job["out"]) > 0:
                    skipped.append(job)
                    sys.stdout.write(f"skip {job['id']}: output exists ({job['out']})\n")
                    sys.stdout.flush()
                    continue
            t0 = time.time()
            try:
                status, detail = batch_row(a, job, budget, avoid)
            except SystemExit as e:             # reserve(): over a cap (3) or a ledger it cannot count (2); not sent
                code = e.code if isinstance(e.code, int) and e.code else USAGE_EXIT
                why = "refused by the budget" if code == BUDGET_EXIT else "refused locally"
                return stop(f"{job['id']}: {why}", code, job)
            except Exception as e:
                if not job.get("reserved"):     # before the request left (e.g. the output folder): not sent
                    return stop(f"{job['id']}: {err_note(e)}", USAGE_EXIT, job)
                # the request left and its final ledger row could not be written (disk full, ledger gone): it is a
                # failed request, never a row to run again, and no further request may start without a ledger
                status, detail = "failed", f"ledger row not written: {err_note(e)} (sent, may have been billed)"
                stop(f"{job['id']}: {detail}")
            line = f"{status} {job['id']} {job['out']} {time.time() - t0:.1f}s" + (f" · {detail}" if detail else "")
            with lock:
                count[status] += 1
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            if status != "ok" and BATCH_STOP_RE.search(detail):
                stop(f"{job['id']}: {detail}")

    def on_signal(signum, frame):       # no lock here: the handler may interrupt the main thread anywhere
        state["signal"] = state["signal"] or signum
        state["stop"] = state["stop"] or f"interrupted by {signal.Signals(signum).name}"

    sys.stdout.flush()
    try:
        prev = {s: signal.signal(s, on_signal) for s in (signal.SIGTERM, signal.SIGINT)}
    except ValueError:                  # not the main thread: no handler, the default behaviour stays
        prev = {}
    try:
        threads = [threading.Thread(target=worker, name=f"image-batch-{n}") for n in range(min(a.parallel, len(todo)))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()                    # in-flight rows always finish and write their final rows
    finally:
        for s, h in prev.items():
            signal.signal(s, h)
    if state["stop"]:
        print(f"stopped: {state['stop']}; {len(queue)} row(s) not started (run the same command again for them "
              "once the cause is fixed)", file=sys.stderr)
    used = f"{_image_units(batch_ledger_rows(a)):g}" if a.ledger else "-"
    cap = budget["images"] if budget and budget["images"] is not None else "-"
    print(f"batch: {count['ok']} ok, {count['failed']} failed, {count['cut-502']} cut-502, {len(skipped)} skipped, "
          f"{len(queue)} not started · images used {used}/{cap}")
    if state["signal"]:
        return 128 + state["signal"]
    if count["failed"] or count["cut-502"]:
        return 1
    return state["code"]


def video(a):
    if a.resume_pending:
        return resume_pending(a)
    if a.resume_task:
        return resume_video(a)
    need_files([a.image] if a.image else [])
    guard_output(a.out, a.overwrite)
    budget = checked_budget(a, "video", a.model)
    content = [{"type": "text", "text": a.prompt}]
    if a.image:
        content.append({"type": "image_url", "image_url": {"url": data_uri(a.image)}, "role": "first_frame"})
    # Seedance 2.5 image-to-video rejects 'ratio' (HTTP 400): the first frame decides the aspect.
    # So with --image no ratio is sent unless the user asks for one explicitly.
    ratio = a.ratio if a.image else (a.ratio or "16:9")
    if a.image and a.ratio:
        print(f"WARNING: --ratio {a.ratio} with --image: Seedance 2.5 image-to-video may reject 'ratio' (HTTP 400). "
              "Make the start frame 16:9 (e.g. 1280x720) yourself instead.", file=sys.stderr)
    req = {"kind": "video", "model": a.model, "size": a.resolution, "seconds": a.duration, "count": 1, "out": a.out}
    make_out_dir(a.out)
    body = {"model": a.model, "content": content, "duration": a.duration, "resolution": a.resolution,
            "watermark": False}
    if ratio:
        body["ratio"] = ratio
    if a.no_audio:
        body["generate_audio"] = False
    rid = new_req()
    reserve(a, req, rid, budget=budget)
    print("model", a.model, "| ratio", ratio or "not sent (start frame decides)", "| audio", "off" if a.no_audio else "model default")
    try:
        task = api("POST", "/contents/generations/tasks", body)["id"]
    except BaseException as e:
        log_row(a, req, rid, fail_status(e), "task creation: " + err_note(e))
        raise
    req["task_id"] = task
    log_row(a, req, rid, "pending", "task created")   # the task id survives even a SIGKILL
    print("task", task, flush=True)
    poll_and_save(a, req, rid)


def open_video_tasks(rows):
    """[(task id, out)] of every video request still open (decided by a pending row) whose task id is known on any
    of its rows, in ledger order: the tasks `video --resume-pending` polls again."""
    tasks = {}
    for r in rows:
        if r.get("task_id") and req_id(r):
            tasks[req_id(r)] = r["task_id"]
    found = []
    for key, r in request_rows(rows):
        task = r.get("task_id") or tasks.get(key)
        if r.get("kind") == "video" and r.get("status") == "pending" and task:
            found.append((task, r.get("out") or ""))
    return found


def resume_pending(a):
    """--resume-pending: --resume-task for every open video task of the ledger, one after the other. A task that
    fails (or has no out) does not stop the others; exit 1 when any did. Nothing new is created or reserved."""
    todo = open_video_tasks(ledger_rows(a.ledger))
    if not todo:
        print(f"no open video task in {a.ledger}")
        return
    done = {"ok": 0, "failed": 0}
    for n, (task, out) in enumerate(todo, 1):
        a.resume_task, a.out = task, out or None
        print(f"[{n}/{len(todo)}] task {task} -> {out or '?'}", flush=True)
        try:
            resume_video(a)
            done["ok"] += 1
        except Interrupted:
            raise
        except SystemExit as e:
            done["failed"] += 1
            if isinstance(e.code, str):
                print(e.code, file=sys.stderr)
            print(f"task {task}: not saved (see its ledger row)", file=sys.stderr, flush=True)
    print(f"resume-pending: {done['ok']} saved, {done['failed']} failed, of {len(todo)} open task(s)")
    if done["failed"]:
        sys.exit(1)


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
    resume_hint = (f"task {task} may still run; resume with: python3 tools/ark.py video --resume-task {task} "
                   f"{a.out} --ledger {a.ledger or 'L.csv'}")
    logged = False
    try:
        errors, wait = 0, POLL_SECONDS
        while True:
            time.sleep(wait)
            try:
                t = api("GET", f"/contents/generations/tasks/{task}")
            except SystemExit as e:
                # One bad status GET must not turn a healthy paid task into a 'failed' row. Only transient
                # failures are polled again; a signal (Interrupted, also a SystemExit) and a 4xx end it at once.
                errors += 1
                if isinstance(e, Interrupted) or errors > POLL_RETRIES or not str(e).startswith(POLL_RETRYABLE):
                    raise
                print(f"poll error ({errors}/{POLL_RETRIES}): {err_note(e)}", file=sys.stderr, flush=True)
                wait = min(60, POLL_SECONDS * 2 ** errors)
                continue
            errors, wait = 0, POLL_SECONDS
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
            print(resume_hint, file=sys.stderr)
        raise
    usage = json.dumps(t.get("usage", {}), separators=(",", ":"))
    url = (t.get("content") or {}).get("video_url")
    if not url:
        log_row(a, req, rid, "failed", f"{pre}no video_url in task: " + json.dumps(t)[:200], usage=usage)
        print(f"task {task} succeeded but its status has no video_url.\n{resume_hint}", file=sys.stderr)
        sys.exit(1)
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
    need_files(a.ref)
    guard_output(a.out, a.overwrite)
    budget = checked_budget(a, "image", model)
    rid = new_req()
    req = {"kind": "image", "model": model, "size": a.size, "count": 1, "out": a.out}
    encoded = [encode_ref(path) for path in a.ref or []]     # exit 2 for a file that is not an image: before any folder
    if a.size.upper() in ("1K", "2K", "4K"):                 # after every local refusal: one message per outcome
        print(f"note: --size {a.size} is a named size and does not fix the aspect ratio (Pro 2K returned 1664x2496 "
              "on 2026-11-10); pass <W>x<H> for a layer plate.", file=sys.stderr)
    make_out_dir(a.out)
    payload = {"job_id": rid, "prompt": a.prompt, "model": model, "size": a.size}
    uploads = []
    if encoded:
        refs_dir = a.refs_dir or os.path.join(os.path.dirname(os.path.abspath(a.out)), "lambda-refs")
        os.makedirs(refs_dir, exist_ok=True)
        for n, (raw, desc) in enumerate(encoded, 1):
            local = os.path.join(refs_dir, f"{rid}-{n}.jpg")
            with open(local, "wb") as f:
                f.write(raw)
            print("ref", desc, file=sys.stderr)
            uploads.append((local, f"refs/{rid}-{n}.jpg"))
        payload["ref_keys"] = [key for _, key in uploads]
    reserve(a, req, rid, LAMBDA_NOTE, budget=budget)     # exit 3 over a cap: no payload is printed, so nothing can be invoked
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


def redact(text):
    """Cut a worker error from its first 'Bearer ' on: a mis-pasted key echoed by the HTTP client must not
    reach stderr or the ledger."""
    text = "" if text is None else str(text)
    cut = text.find("Bearer ")
    return text if cut < 0 else text[:cut] + "Bearer <redacted>"


WORKER_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambda", "ark_image_worker.py")
LAMBDA_GRACE = 60      # seconds after a running job's `deadline` at which its worker is known to be dead


def read_status_json(path):
    """The worker's jobs/<job_id>.json as a dict; anything else is a local refusal (exit 2, nothing written)."""
    try:
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
    except OSError as e:
        usage_error(f"cannot read status file {path} ({e.strerror or type(e).__name__})")
    except ValueError:
        st = None
    if not isinstance(st, dict):
        usage_error(f"status file {path} is not a JSON object (an S3 error page? download it again with "
                    "`curl -fsS -o`); nothing written")
    return st


def check_worker_hash(st, job):
    """WARN when the worker that ran the job is not the repo's lambda/ark_image_worker.py (stale deployment)."""
    try:
        with open(WORKER_FILE, "rb") as f:
            want = hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return
    got = st.get("worker_sha256")
    if got != want:
        ran = f"worker {str(got)[:12]}" if got else "a worker without worker_sha256 (older than the repo)"
        print(f"WARN: job {job} ran {ran}; the repo's lambda/ark_image_worker.py is {want[:12]}. Redeploy before the "
              "next job (lambda/README.md, 'Triển khai lại')", file=sys.stderr)


def lambda_finish(a):
    """Final ledger row for a Lambda job from the worker's jobs/<job_id>.json; saves the downloaded image."""
    st = read_status_json(a.status_json)
    job = a.job or st.get("job_id")
    if not job or (st.get("job_id") and st["job_id"] != job):
        usage_error(f"job id mismatch: --job {a.job!r}, status file says {st.get('job_id')!r}")
    known = [r for r in ledger_rows(a.ledger) if req_id(r) == job]
    if not known:
        usage_error(f"job {job} has no row in {a.ledger}: every Lambda job starts with 'lambda-job prepare' "
                    "(budget check + pending row). Check that this is the episode's ledger")
    status = st.get("status")
    last = known[-1]
    req = {k: last.get(k, "") for k in ("kind", "model", "size", "seconds", "count", "out")}
    out = a.out or req.get("out")
    req["out"] = out
    done = [r for r in known if r.get("status") in FINAL]
    secs = f"{LAMBDA_NOTE}; seconds={st.get('seconds', '?')}"
    usage = json.dumps(st.get("usage") or {}, separators=(",", ":"))
    finish = (f"python3 tools/ark.py lambda-job finish --status-json {a.status_json} --give-up "
              f"--ledger {a.ledger}")
    if status == "running":
        deadline = st.get("deadline")
        if not isinstance(deadline, (int, float)) or isinstance(deadline, bool):
            if a.give_up:
                usage_error(f"job {job}: the status has no deadline, so ark.py cannot tell that the worker is dead. "
                            "Wait 16 minutes after the Invoke, then close it with: python3 tools/ark.py ledger-close "
                            f"--req {job} --ledger {a.ledger} --status abandoned")
        else:
            late = time.time() - deadline
            if late > LAMBDA_GRACE:
                if not a.give_up:
                    print(f"job {job} is still 'running' {late:.0f}s after its deadline: the worker died (time or "
                          "memory limit). Stop reading the status and do not invoke again. Close the request (it "
                          f"may have been billed, so it stays counted):\n  {finish}", file=sys.stderr)
                    sys.exit(1)
                if done:
                    print(f"job {job} already has a final row ({done[-1].get('status')}); ledger unchanged",
                          file=sys.stderr)
                    sys.exit(1)
                log_row(a, req, job, "failed", f"{LAMBDA_NOTE}; gave up: still running {late:.0f}s after the "
                                                "deadline (worker died; may have been billed)")
                print(f"job {job} closed as failed (worker died); it stays counted. Not retried.", file=sys.stderr)
                sys.exit(1)
            if a.give_up:
                usage_error(f"job {job} may still run for {max(0, -late):.0f}s (+{LAMBDA_GRACE}s): --give-up only "
                            "after its deadline; read the status again later")
    if status not in ("succeeded", "failed"):
        print(f"job {job} is {status or 'unknown'}: no final row written; read jobs/{job}.json again later",
              file=sys.stderr)
        sys.exit(1)
    check_worker_hash(st, job)            # on the final status only: one WARN per job, not one per poll
    if status == "failed":
        error = redact(st.get("error"))
        unsent = st.get("sent") is False
        if done:
            print(f"job {job} FAILED: {error}. It already has a final row ({done[-1].get('status')}); ledger "
                  "unchanged.", file=sys.stderr)
            sys.exit(1)
        log_row(a, req, job, "failed-unsent" if unsent else "failed", f"{secs}; {error[:240]}")
        if unsent:
            print(f"job {job} FAILED before anything was sent to Ark (sent: false): {error}\nNothing was generated; "
                  "the request is closed as failed-unsent and no longer counts. Fix the cause, then prepare a new "
                  "job.", file=sys.stderr)
        else:
            print(f"job {job} FAILED: {error}\nIt may still have been billed; it stays counted. Not retried.",
                  file=sys.stderr)
        sys.exit(1)
    final = dict(count=max(1, len(st.get("keys") or [])), usage=usage)
    if a.image:
        need_files([a.image])
        with open(a.image, "rb") as f:
            raw = f.read()
        if not sniff_mime(raw):     # e.g. S3's XML error page saved by curl without -f
            usage_error(f"--image {a.image} is not a PNG, JPEG, WebP or GIF image (an S3 error page? download it "
                        "again with `curl -fsS -o`); nothing written")
        try:
            make_out_dir(out)
            save_image(raw, out)
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


TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z")


def row_problems(r):
    """Why one ledger row cannot be merged (empty list: it can). Strict on purpose: a row ledger-merge cannot
    read would otherwise be dropped or counted as 0, i.e. billed requests would vanish from the count."""
    bad = []
    if not TS_RE.fullmatch(r.get("ts") or ""):
        bad.append(f"ts {r.get('ts')!r} is not an ISO 8601 UTC time (YYYY-MM-DDTHH:MM:SSZ)")
    if r.get("kind") not in ("image", "video"):
        bad.append(f"kind {r.get('kind')!r} is not image or video")
    if r.get("status") not in STATUSES:
        bad.append(f"status {r.get('status')!r} is not one of {', '.join(sorted(STATUSES))}")
    for k in ("count", "seconds"):
        v = r.get(k) or ""
        try:
            ok = v == "" or 0 <= float(v) < float("inf")
        except ValueError:
            ok = False
        if not ok:
            bad.append(f"{k} {v!r} is not a number >= 0")
    note = r.get("note") or ""
    if note.startswith("req=") and not REQ_RE.match(note):
        bad.append(f"note {note[:40]!r} starts with req= but has no valid request id (lowercase hex, then ';' or end)")
    return bad


def read_ledger_strict(path, text):
    """(rows, problems) of a ledger's text for ledger-merge; every problem is 'path:line: reason'."""
    rows, problems = [], []
    reader = csv.reader(io.StringIO(text.lstrip("\ufeff")), strict=True)
    try:
        header = next(reader, None)
    except csv.Error as e:
        return rows, [f"{path}:1: {e}"]
    if header is None:
        return rows, problems                     # empty file: no rows
    if header != LEDGER_FIELDS:
        return rows, [f"{path}:1: header is not {','.join(LEDGER_FIELDS)}"]
    while True:
        line = reader.line_num + 1
        try:
            rec = next(reader)
        except StopIteration:
            break
        except csv.Error as e:                    # e.g. a quote that is never closed: the rest cannot be read
            problems.append(f"{path}:{line}: {e}")
            break
        if not rec:
            continue                              # blank line
        if len(rec) != len(LEDGER_FIELDS):
            problems.append(f"{path}:{line}: {len(rec)} cells, the header has {len(LEDGER_FIELDS)} "
                            "(quote a note that contains a comma)")
            continue
        r = dict(zip(LEDGER_FIELDS, rec))
        problems += [f"{path}:{line}: {why}" for why in row_problems(r)]
        rows.append(r)
    return rows, problems


def _row_tuple(r):
    return tuple(r.get(k) or "" for k in LEDGER_FIELDS)


def _merge_rank(t):
    return units(dict(zip(LEDGER_FIELDS, t))), t


def merge_rows(row_lists):
    """Union of ledgers (lists of validated rows), independent of the order of the lists.
    Rows with a request id: one row per (req, status, task_id); when copies differ, the one with more billing units
    wins, then the greater field tuple. Rows without one (old ledgers): as a multiset, each distinct row as many
    times as the copy that has it most often (two identical rows in one copy are two requests).
    Sorted by (ts, pending before final, fields)."""
    keyed, counts = {}, {}
    for rows in row_lists:
        local = {}
        for r in rows:
            t, rid = _row_tuple(r), req_id(r)
            if rid:
                k = (rid, r.get("status") or "", r.get("task_id") or "")
                keyed[k] = t if k not in keyed else max(keyed[k], t, key=_merge_rank)
            else:
                local[t] = local.get(t, 0) + 1
        for t, n in local.items():
            counts[t] = max(counts.get(t, 0), n)
    out = list(keyed.values()) + [t for t, n in counts.items() for _ in range(n)]
    status = LEDGER_FIELDS.index("status")
    out.sort(key=lambda t: (t[0], 0 if t[status] == "pending" else 1, t))
    return [dict(zip(LEDGER_FIELDS, t)) for t in out]


def merge_shortfall(inputs, merged):
    """The 'never bill less' check: every request an input counts must count at least as much, with the same kind
    and model, in the merged ledger, unless the merged ledger closes it as failed-unsent (never sent).
    `inputs` is [(path, rows)]; returns problems as 'path: reason'."""
    got = dict(request_rows(merged))
    problems = []
    for path, rows in inputs:
        for key, r in request_rows(rows):
            m = got.get(key)
            if r.get("status") in UNBILLED or (m is not None and m.get("status") in UNBILLED):
                continue
            name = key if isinstance(key, str) else "row " + ",".join(key[1])[:80]
            if m is None:
                problems.append(f"{path}: request {name} is missing from the merged ledger")
            elif (m.get("kind"), m.get("model")) != (r.get("kind"), r.get("model")) or units(m) < units(r):
                problems.append(f"{path}: request {name} counts {units(r):g} {r.get('kind')} {r.get('model')} "
                                f"({r.get('status')}) there but {units(m):g} {m.get('kind')} {m.get('model')} "
                                f"({m.get('status')}) after the merge: the copies disagree, fix the rows by hand")
    return problems


def _read_text(path):
    with open(path, newline="", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            return f.read()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def ledger_merge(a):
    """Write the union of the input ledgers and of --out's own rows to --out, under its exclusive lock.
    --out's existing rows are always kept, listed as an input or not: a merge never drops a billed row.
    Every row of every input is checked first; any problem (file:line), or a merged ledger that would count a
    request less than one of the copies does, is exit 2 and --out is left untouched.
    With no input: an empty ledger with the header (first generation of an episode with ledger_required)."""
    missing = [p for p in a.ledgers if not os.path.isfile(p)]
    if missing:
        usage_error("no such ledger: " + ", ".join(missing))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    created = not os.path.exists(a.out)
    with open(a.out, "a+", newline="", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            try:
                current = f.read()
            except UnicodeDecodeError as e:
                _unreadable_ledger(a.out, e)
            own_rows, problems = read_ledger_strict(a.out, current)
            if not a.ledgers and (own_rows or problems):
                usage_error(f"{a.out} already has rows; pass the ledgers to merge (it was left untouched)")
            inputs, out_listed = [], False
            for path in a.ledgers:
                if os.path.samefile(path, a.out):
                    rows, bad = own_rows, []
                    out_listed = True
                else:
                    try:
                        rows, bad = read_ledger_strict(path, _read_text(path))
                    except (OSError, UnicodeDecodeError) as e:
                        rows, bad = [], [f"{path}: cannot be read "
                                         f"({getattr(e, 'strerror', None) or type(e).__name__})"]
                problems += bad
                inputs.append((path, rows))
            own = [] if out_listed else own_rows      # rows only this copy has must survive
            if not problems:
                rows = merge_rows([own] + [r for _, r in inputs])
                problems = merge_shortfall([(a.out, own_rows)] + inputs, rows)
            if problems:
                problems = list(dict.fromkeys(problems))
                if created and not current:
                    os.remove(a.out)                  # nothing written: not even an empty file
                print(f"error: ledger-merge: {len(problems)} problem(s), nothing written:\n  " + "\n  ".join(problems),
                      file=sys.stderr)
                sys.exit(USAGE_EXIT)
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
    counts = ", ".join(f"{os.path.basename(p)}: {len(r)}" for p, r in inputs) or "no input"
    if own:
        counts += f" + {len(own)} row(s) already in {os.path.basename(a.out)}"
    billed = billed_requests(rows)
    print(f"{a.out}: {len(rows)} row(s) from {counts} · billed requests: "
          f"{sum(units(r) for r in billed if r.get('kind') == 'image'):g} image(s), "
          f"{sum(units(r) for r in billed if r.get('kind') == 'video'):g} video second(s)")


def ledger_close(a):
    """Close an orphan request (a pending row that will never get a final row: the agent was killed, a Lambda job
    was prepared but never invoked) with a final `abandoned` row under the ledger's exclusive lock. The request
    still counts against the caps (it may have been billed); the row only ends it, so status.py stops listing it
    as OPEN. Refused (exit 2, nothing written) when the request has no pending row or already has a final row."""
    if not re.fullmatch(r"[0-9a-f]{4,}", a.req or ""):
        usage_error(f"--req {a.req!r}: give the request id (req=<hex> in the ledger note; 4+ leading hex digits)")
    if not os.path.isfile(a.ledger):
        usage_error(f"no such ledger: {a.ledger}")
    with open(a.ledger, "a+", newline="", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            try:
                text = f.read()
            except UnicodeDecodeError as e:
                _unreadable_ledger(a.ledger, e)
            if text and not _header_ok(text):
                _header_refusal(a.ledger)
            rows = _parse_rows(a.ledger, text)
            ids = sorted({req_id(r) for r in rows if req_id(r)})
            found = [i for i in ids if i == a.req] or [i for i in ids if i.startswith(a.req)]
            if not found:
                usage_error(f"no request {a.req} in {a.ledger}")
            if len(found) > 1:
                usage_error(f"--req {a.req} matches {len(found)} requests ({', '.join(found[:4])}): give more digits")
            rid = found[0]
            group = [r for r in rows if req_id(r) == rid]
            finals = [r for r in group if r.get("status") in FINAL]
            if finals:
                usage_error(f"request {rid} already has a final row ({finals[-1].get('status')}): nothing to close")
            pending = [r for r in group if r.get("status") == "pending"]
            if not pending:
                usage_error(f"request {rid} has no pending row: nothing to close")
            last = pending[-1]
            task = next((r["task_id"] for r in reversed(group) if r.get("task_id")), "")
            row = {k: last.get(k, "") for k in ("kind", "model", "size", "seconds", "count", "out")}
            note = "; ".join(x for x in (f"req={rid}", "closed by ledger-close", a.note) if x)
            _write_locked(f, dict(row, task_id=task, status=a.status, note=note))
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    print(f"req={rid} closed as {a.status} in {a.ledger}: it still counts against the caps "
          f"({units(last):g} {'second(s) of video' if last.get('kind') == 'video' else 'image(s)'}, {last.get('model')})")
    if task:
        print(f"note: task {task} may still finish upstream; the clip can still be saved later with "
              f"python3 tools/ark.py video --resume-task {task} --ledger {a.ledger}", file=sys.stderr)


def add_cost_args(sp, overwrite=True):
    sp.add_argument("--ledger", default=None,
                    help="ledger.csv: a pending row before the call and a final row after it (env FILM_LEDGER); "
                         "see docs/CONVENTIONS.md §7")
    sp.add_argument("--budget", default=None,
                    help="budget.yaml checked before the call; over a cap -> refused-budget row, exit 3 "
                         "(env FILM_BUDGET). Required together with --ledger unless --no-budget")
    sp.add_argument("--no-budget", action="store_true",
                    help="run without a budget (ad-hoc tests in the main session only; --ledger optional)")
    if overwrite:
        sp.add_argument("--overwrite", action="store_true",
                        help="replace an existing output file (ad-hoc use; a plate or clip gets a new _v<NN> instead)")


def batch_parallel(text):
    n = int(text)
    if not 1 <= n <= BATCH_MAX_PARALLEL:
        raise argparse.ArgumentTypeError(f"must be 1..{BATCH_MAX_PARALLEL}, not {n}")
    return n


def positive_int(text):
    n = int(text)
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, not {n}")
    return n


p = argparse.ArgumentParser(description="BytePlus ModelArk helper")
sp = p.add_subparsers(dest="cmd", required=True)
pg = sp.add_parser("ping", help="list models, one per line")
pg.add_argument("--all", action="store_true", help="also show Shutdown models")
i = sp.add_parser("image"); i.add_argument("prompt"); i.add_argument("out")
i.add_argument("--model", default=None, help=f"default {IMAGE_DEFAULT}")
i.add_argument("--fast", action="store_true", help=f"use {IMAGE_FAST}")
i.add_argument("--size", default="2K", help="1K, 2K or <W>x<H> up to about 2K (default 2K); larger: lambda-job")
i.add_argument("--ref", nargs="*", help=f"reference image(s); re-encoded in memory to JPEG q{REF_QUALITY}, "
               f"long edge <= {REF_LONG_EDGE}, alpha flattened onto white (files on disk untouched)")
i.add_argument("--seed", type=int, default=None, help="sent as 'seed' (model support unverified)")
i.add_argument("--negative", action="append", metavar="TEXT",
               help="repeatable; joined with ', ' into 'negative_prompt' (model support unverified)")
i.add_argument("--guidance", type=float, default=None, help="sent as 'guidance_scale' (model support unverified)")
i.add_argument("--force", action="store_true",
               help="send a size above 2K, an unknown size or a pro model despite the proxy cutoff")
add_cost_args(i)
ib = sp.add_parser("image-batch", help="one `image` request per row of a CSV: validated first, budget checked for "
                    "the whole batch, bounded parallelism, existing outputs skipped",
                    description=BATCH_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
ib.add_argument("jobs", metavar="JOBS.csv", help="the jobs CSV (columns above)")
ib.add_argument("--parallel", type=batch_parallel, default=BATCH_PARALLEL, metavar="N",
                help=f"requests in flight at a time, 1..{BATCH_MAX_PARALLEL} (default {BATCH_PARALLEL}; 1 = sequential)")
ib.add_argument("--dry-run", action="store_true",
                help="validate, print the plan and the budget after the batch; sends nothing, writes nothing")
ib.add_argument("--only", nargs="+", metavar="ID", default=None,
                help="only these row ids (put JOBS.csv before --only); the whole CSV is still validated")
ib.add_argument("--fast", action="store_true", help=f"rows with an empty model column use {IMAGE_FAST}")
add_cost_args(ib, overwrite=False)
v = sp.add_parser("video")
v.add_argument("prompt", nargs="?", help="text prompt (omit with --resume-task)")
v.add_argument("out", nargs="?", help="output .mp4 (with --resume-task: optional, default the out in the ledger)")
v.add_argument("--image")
v.add_argument("--model", default=VIDEO_DEFAULT)
v.add_argument("--ratio", default=None, help="default 16:9 without --image; with --image not sent (the start frame decides the "
                                                  "aspect; Seedance 2.5 rejects ratio there)")
v.add_argument("--duration", type=positive_int, default=5, help="seconds, >= 1 (default 5)")
v.add_argument("--resolution", default="720p", choices=VIDEO_RESOLUTIONS, help="default 720p")
v.add_argument("--no-audio", action="store_true", help="send generate_audio=false")
v.add_argument("--resume-task", metavar="TASK_ID", default=None,
               help="resume polling + download of an existing task (no new request, no budget check; needs --ledger)")
v.add_argument("--resume-pending", action="store_true",
               help="--resume-task for every open video task of --ledger (pending, task id known), one by one")
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
lf.add_argument("--give-up", action="store_true",
                help=f"a job still 'running' more than {LAMBDA_GRACE}s after its deadline (the worker died): write a "
                     "final 'failed' row (still counted)")
lm = sp.add_parser("ledger-merge", help="union of ledger copies (two sessions, two Drive files) into one")
lm.add_argument("ledgers", nargs="*", help="ledgers to merge (none: create an empty ledger with the header)")
lm.add_argument("-o", "--out", required=True, help="merged ledger; may be one of the inputs")
lc = sp.add_parser("ledger-close", help="close an orphan pending request with a final 'abandoned' row (still counted)")
lc.add_argument("--req", required=True, help="the request id (req=<hex> in the note; a unique prefix of 4+ digits)")
lc.add_argument("--ledger", default=None, help="the episode's ledger.csv (env FILM_LEDGER)")
lc.add_argument("--status", required=True, choices=["abandoned"],
                help="abandoned: the request will never get a final row; it stays counted against the caps")
lc.add_argument("--note", default="", help="why (appended to the row's note)")


def usage_error(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(USAGE_EXIT)


def check_cost_args(a):
    """image/video need budget + ledger, or --no-budget; --resume-task needs a ledger only (exit 2 otherwise)."""
    a.ledger = a.ledger or os.environ.get("FILM_LEDGER") or None
    a.budget = a.budget or os.environ.get("FILM_BUDGET") or None
    agent = os.environ.get("FILM_AGENT")
    for flag, on in (("--no-budget", a.no_budget), ("--force", getattr(a, "force", False))):
        if agent and on:        # agents always run under the episode's caps and the proxy guards (cost-7)
            usage_error(f"{flag} is for ad-hoc tests in the main session; FILM_AGENT={agent} is set, so it is "
                        "refused (nothing sent). Pass --budget and --ledger; ask the main session for anything else")
    resume = getattr(a, "resume_task", None) or getattr(a, "resume_pending", False)
    if a.cmd == "video":
        if getattr(a, "resume_pending", False):
            if a.resume_task or a.prompt is not None:
                usage_error("--resume-pending takes no task id, prompt or output (they come from the ledger)")
        elif resume:
            if a.out is None:   # 'video --resume-task T out.mp4': the single positional is the output
                a.prompt, a.out = None, a.prompt
        elif a.prompt is None or a.out is None:
            usage_error("video needs a prompt and an output path (or --resume-task TASK_ID)")
    if resume:
        if not a.ledger:
            flag = "--resume-pending" if getattr(a, "resume_pending", False) else "--resume-task"
            usage_error(f"{flag} needs --ledger (or FILM_LEDGER) to log the final row")
        a.no_budget = True   # nothing new is requested, so there is nothing to check
        return
    if a.no_budget:
        print(f"warning: --no-budget: no budget check{'' if a.ledger else ', no ledger'}"
              " (ad-hoc tests in the main session only)", file=sys.stderr)
        return
    if a.budget and not a.ledger:
        usage_error("--budget without --ledger: the budget cannot count earlier requests. "
                    "Pass --ledger out/<project>/<ep<NN>|q<NN>t<NN>>/ledger.csv (or FILM_LEDGER)")
    if not (a.budget and a.ledger):
        usage_error(f"refusing to call the paid API without a budget: pass --budget B.yaml --ledger L.csv "
                    f"(or FILM_BUDGET/FILM_LEDGER), or --no-budget for an ad-hoc test (docs/CONVENTIONS.md §7)")


def main(argv=None):
    a = p.parse_args(argv)
    if a.cmd == "ledger-merge":
        return ledger_merge(a)
    if a.cmd == "ledger-close":
        a.ledger = a.ledger or os.environ.get("FILM_LEDGER") or None
        if not a.ledger:
            usage_error("ledger-close needs --ledger (or FILM_LEDGER)")
        return ledger_close(a)
    if a.cmd == "lambda-job":
        a.ledger = a.ledger or os.environ.get("FILM_LEDGER") or None
        if not a.ledger:      # a Lambda call bypasses the proxy AND every cap unless it is in the ledger
            usage_error("lambda-job needs --ledger (or FILM_LEDGER): no ledger, no Lambda call")
        if a.lcmd == "finish":
            return lambda_finish(a)
        check_cost_args(a)
        return lambda_prepare(a)
    if a.cmd == "image-batch":
        check_cost_args(a)
        code = image_batch(a)
        if code:
            sys.exit(code)
        return
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
