#!/usr/bin/env python3
"""BytePlus ModelArk from a Claude Code cloud session (AI Film Lab).

  python3 ark.py ping [--all]
  python3 ark.py image "prompt" out.png [--model seedream-5-0-lite-260128 | --fast] [--size 2K|2560x1440] [--ref a.png ...]
                       [--seed N] [--negative TEXT ...] [--guidance F] [--force] [--ledger L.csv] [--budget B.yaml]
  python3 ark.py video "prompt" out.mp4 [--image first.png] [--model dreamina-seedance-2-5-260628]
                       [--ratio adaptive|16:9] [--duration 5] [--resolution 1080p] [--no-audio]
                       [--ledger L.csv] [--budget B.yaml]

Budget and ledger (docs/CONVENTIONS.md §7): --ledger/--budget (or env FILM_LEDGER/FILM_BUDGET).
Every generation API call appends one row to the ledger (file-locked); the budget is checked
BEFORE the call and a request over any cap is refused with exit code 3.

Credentials: in a Claude cloud session the agent proxy injects the real Ark key
for ark.ap-southeast.bytepluses.com, so this script sends a placeholder. Outside
that proxy, set ARK_API_KEY. Never print, log or search for the key.
"""
import argparse, base64, csv, datetime, fcntl, io, json, mimetypes, os, sys, time, urllib.request, urllib.error

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
BILLED = {"ok", "failed", "cut-502"}   # every status that may have been billed
BUDGET_EXIT = 3


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


def budget_check(budget, rows, req):
    """Return a list of human-readable cap violations for request `req` (a ledger-shaped dict)."""
    if not budget:
        return []
    used = [r for r in rows if r.get("status") in BILLED]
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
    """Budget check before any generation call. Exits 3 (and logs refused-budget) when over a cap."""
    budget = load_budget(a.budget)
    if budget is None:
        return
    if not a.ledger:
        print("warning: --budget without --ledger: only the current request is counted", file=sys.stderr)
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
    try:
        r = api("POST", "/images/generations", body)
    except BaseException as e:
        ledger_append(a.ledger, dict(req, status=fail_status(e), note=err_note(e)))
        raise
    data = r.get("data", [])
    ledger_append(a.ledger, dict(req, status="ok", count=max(1, len(data)),
                                 usage=json.dumps(r.get("usage", {}), separators=(",", ":"))))
    stem, ext = os.path.splitext(a.out)
    for i, d in enumerate(data):
        out = a.out if i == 0 else f"{stem}-{i}{ext}"
        save_image(base64.b64decode(d["b64_json"]), out)
        print("saved", out)
    print("usage", json.dumps(r.get("usage", {})))


def video(a):
    content = [{"type": "text", "text": a.prompt}]
    if a.image:
        content.append({"type": "image_url", "image_url": {"url": data_uri(a.image)}, "role": "first_frame"})
    ratio = a.ratio or ("adaptive" if a.image else "16:9")
    req = {"kind": "video", "model": a.model, "size": a.resolution, "seconds": a.duration, "count": 1, "out": a.out}
    guard_budget(a, req)
    body = {"model": a.model, "content": content, "duration": a.duration, "resolution": a.resolution,
            "ratio": ratio, "watermark": False}
    if a.no_audio:
        body["generate_audio"] = False
    print("model", a.model, "| ratio", ratio, "| audio", "off" if a.no_audio else "model default")
    try:
        task = api("POST", "/contents/generations/tasks", body)["id"]
    except BaseException as e:
        ledger_append(a.ledger, dict(req, status=fail_status(e), note="task creation: " + err_note(e)))
        raise
    print("task", task)
    req["task_id"] = task
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
                ledger_append(a.ledger, dict(req, status="failed", note=f"task {t['status']}: {msg[:300]}",
                                             usage=json.dumps(t.get("usage", {}), separators=(",", ":"))))
                logged = True
                sys.exit(msg)
    except BaseException as e:
        if not logged:  # polling broke off: the task may still run and be billed
            ledger_append(a.ledger, dict(req, status="failed", note="polling stopped (task may still run): " + err_note(e)))
        raise
    ledger_append(a.ledger, dict(req, status="ok", usage=json.dumps(t.get("usage", {}), separators=(",", ":"))))
    url = t["content"]["video_url"]
    print("video host:", url.split("/")[2])
    download(url, a.out)
    print("saved", a.out)


def add_cost_args(sp):
    sp.add_argument("--ledger", default=None,
                    help="ledger.csv to append one row per API call (env FILM_LEDGER); see docs/CONVENTIONS.md §7")
    sp.add_argument("--budget", default=None,
                    help="budget.yaml checked before the call; over a cap -> refused-budget row, exit 3 (env FILM_BUDGET)")


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
v = sp.add_parser("video"); v.add_argument("prompt"); v.add_argument("out"); v.add_argument("--image")
v.add_argument("--model", default=VIDEO_DEFAULT)
v.add_argument("--ratio", default=None, help="default: adaptive with --image, else 16:9")
v.add_argument("--duration", type=int, default=5); v.add_argument("--resolution", default="1080p")
v.add_argument("--no-audio", action="store_true", help="send generate_audio=false")
add_cost_args(v)


def main(argv=None):
    a = p.parse_args(argv)
    if a.cmd in ("image", "video"):
        a.ledger = a.ledger or os.environ.get("FILM_LEDGER") or None
        a.budget = a.budget or os.environ.get("FILM_BUDGET") or None
    return {"ping": ping, "image": image, "video": video}[a.cmd](a)


if __name__ == "__main__":
    main()
