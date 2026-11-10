#!/usr/bin/env python3
"""BytePlus ModelArk from a Claude Code cloud session (AI Film Lab).

  python3 ark.py ping [--all]
  python3 ark.py image "prompt" out.png [--model seedream-5-0-lite-260128 | --fast] [--size 2K|2560x1440] [--ref a.png ...] [--force]
  python3 ark.py video "prompt" out.mp4 [--image first.png] [--model dreamina-seedance-2-5-260628]
                       [--ratio adaptive|16:9] [--duration 5] [--resolution 1080p] [--no-audio]

Credentials: in a Claude cloud session the agent proxy injects the real Ark key
for ark.ap-southeast.bytepluses.com, so this script sends a placeholder. Outside
that proxy, set ARK_API_KEY. Never print, log or search for the key.
"""
import argparse, base64, json, mimetypes, os, sys, time, urllib.request, urllib.error

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


# --- models available on this account (see Ark Console) --------------------
IMAGE_DEFAULT = "seedream-5-0-lite-260128"        # Dola-Seedream-5.0-lite, 2K ~25s
IMAGE_FAST = "dola-seedream-5-0-flash-260915"     # Dola-Seedream-5.0-flash
IMAGE_SLOW = {"dola-seedream-5-0-pro-260628"}     # always > proxy cutoff
VIDEO_DEFAULT = "dreamina-seedance-2-5-260628"    # Dreamina-Seedance-2.5
PROXY_CUTOFF = 30  # seconds: the agent proxy cuts synchronous requests here


def api(method, path, body=None):
    """call() plus a clear message when the agent proxy cuts a long request."""
    t0 = time.time()
    try:
        return call(method, path, body)
    except SystemExit as e:
        took = time.time() - t0
        if str(e).startswith("HTTP 502") and took >= PROXY_CUTOFF - 5:
            sys.exit(f"HTTP 502 after {took:.0f}s: the agent proxy cuts synchronous requests at ~{PROXY_CUTOFF}s.\n"
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
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        if want[0] == "JPEG" and im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.save(out, want[0])
        print(f"converted {got} -> {want[1]}")
    else:
        open(out, "wb").write(raw)


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
    body = {"model": model, "prompt": a.prompt, "size": a.size, "response_format": "b64_json", "watermark": False}
    if a.ref:
        body["image"] = [data_uri(p) for p in a.ref] if len(a.ref) > 1 else data_uri(a.ref[0])
    print("model", model)
    r = api("POST", "/images/generations", body)
    stem, ext = os.path.splitext(a.out)
    for i, d in enumerate(r.get("data", [])):
        out = a.out if i == 0 else f"{stem}-{i}{ext}"
        save_image(base64.b64decode(d["b64_json"]), out)
        print("saved", out)
    print("usage", json.dumps(r.get("usage", {})))


def video(a):
    content = [{"type": "text", "text": a.prompt}]
    if a.image:
        content.append({"type": "image_url", "image_url": {"url": data_uri(a.image)}, "role": "first_frame"})
    ratio = a.ratio or ("adaptive" if a.image else "16:9")
    body = {"model": a.model, "content": content, "duration": a.duration, "resolution": a.resolution,
            "ratio": ratio, "watermark": False}
    if a.no_audio:
        body["generate_audio"] = False
    print("model", a.model, "| ratio", ratio, "| audio", "off" if a.no_audio else "model default")
    task = api("POST", "/contents/generations/tasks", body)["id"]
    print("task", task)
    while True:
        time.sleep(10)
        t = api("GET", f"/contents/generations/tasks/{task}")
        print("status", t["status"], flush=True)
        if t["status"] == "succeeded":
            url = t["content"]["video_url"]
            print("video host:", url.split("/")[2])
            urllib.request.urlretrieve(url, a.out)
            print("saved", a.out)
            return
        if t["status"] in ("failed", "cancelled", "expired"):
            sys.exit(json.dumps(t.get("error", t))[:600])


p = argparse.ArgumentParser(description="BytePlus ModelArk helper")
sp = p.add_subparsers(dest="cmd", required=True)
pg = sp.add_parser("ping", help="list models, one per line")
pg.add_argument("--all", action="store_true", help="also show Shutdown models")
i = sp.add_parser("image"); i.add_argument("prompt"); i.add_argument("out")
i.add_argument("--model", default=None, help=f"default {IMAGE_DEFAULT}")
i.add_argument("--fast", action="store_true", help=f"use {IMAGE_FAST}")
i.add_argument("--size", default="2K"); i.add_argument("--ref", nargs="*")
i.add_argument("--force", action="store_true", help="allow 4K / slow models despite the proxy cutoff")
v = sp.add_parser("video"); v.add_argument("prompt"); v.add_argument("out"); v.add_argument("--image")
v.add_argument("--model", default=VIDEO_DEFAULT)
v.add_argument("--ratio", default=None, help="default: adaptive with --image, else 16:9")
v.add_argument("--duration", type=int, default=5); v.add_argument("--resolution", default="1080p")
v.add_argument("--no-audio", action="store_true", help="send generate_audio=false")
a = p.parse_args()
{"ping": ping, "image": image, "video": video}[a.cmd](a)
