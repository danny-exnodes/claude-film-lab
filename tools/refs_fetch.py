#!/usr/bin/env python3
"""Licensed reference images from Wikimedia Commons, with their credits (film-iconographer, khâu 3a).

  python3 tools/refs_fetch.py search "<query>" [--limit 20] [--free-only]
  python3 tools/refs_fetch.py fetch <File:… | Commons URL> [...] --out <dir> [--name N] [--note T] [--kind K] [--page N]
  python3 tools/refs_fetch.py fetch --list refs.txt --out <dir>

- Metadata comes from the Commons API (imageinfo + extmetadata of the File page): licence, author, credit/source,
  date, description, page URL. The image itself is the Commons thumbnail (not the original), at most --max-px
  (default 1600) on its long side, resized again with Pillow if needed.
- Non-free or unknown licences are refused unless --allow-nonfree (then the credits line says "free": false).
- Never overwrites: an existing file, or a File page already in the folder's _credits.jsonl, is skipped.
- Every saved image gets one JSON line in <dir>/_credits.jsonl (title, page, file, licence, licence_url, free, author,
  credit, date, description, size, note, kind, fetched).
- Polite: one request at a time, --interval seconds apart (default 1), backoff on 429 honouring Retry-After
  (tools/netfetch.py), generic User-Agent without personal data.

--list file: one reference per line, `<File:… | URL> [| <name> [| <note>]]`; blank lines and lines starting with #
are skipped.
Exit codes: 0 done (skips included), 2 refused before any download (bad reference, non-free licence, usage),
1 a request failed (network, HTTP, missing page).
"""
import argparse, datetime, hashlib, html, io, json, os, re, sys, unicodedata, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netfetch  # noqa: E402

API = "https://commons.wikimedia.org/w/api.php"
PAGE = "https://commons.wikimedia.org/wiki/"
CREDITS = "_credits.jsonl"
META_KEYS = ("LicenseShortName", "License", "LicenseUrl", "UsageTerms", "NonFree", "Copyrighted", "Artist", "Credit",
             "DateTimeOriginal", "DateTime", "ImageDescription", "ObjectName", "Attribution", "AttributionRequired")

FREE_RE = re.compile(r"^\s*(public domain|pdm?\b|pd-|cc0|cc[- ]?zero|cc[- ]by(?:-sa)?\b|gfdl|fal\b|free art|"
                     r"no restrictions|attribution\b|copyrighted free use)", re.I)
NONFREE_RE = re.compile(r"(?<![a-z])(nc|nd|non-?commercial|no ?deriv\w*|fair use|non-?free|all rights reserved)"
                        r"(?![a-z])", re.I)


class Refused(Exception):
    """Refused before downloading (exit 2)."""


# --- pure helpers --------------------------------------------------------------------------------------------------

def plain(value, limit=300):
    """Text of an extmetadata value: HTML tags removed, entities decoded, whitespace collapsed."""
    if isinstance(value, dict):
        value = value.get("value", "")
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip() + ("…" if len(text) > limit else "")


def licence_of(meta):
    """(licence text, licence url, free?) from extmetadata."""
    lic = plain(meta.get("LicenseShortName")) or plain(meta.get("License")) or plain(meta.get("UsageTerms"))
    url = plain(meta.get("LicenseUrl"))
    if plain(meta.get("NonFree")).lower() == "true" or not lic:
        return lic or "unknown", url, False
    if NONFREE_RE.search(lic):
        return lic, url, False
    return lic, url, bool(FREE_RE.search(lic))


def parse_ref(ref):
    """(File: title, page number or None) of a reference: File:/Image: title, Commons File page URL (also
    index.php?title=…), or an upload.wikimedia.org URL (original or thumbnail). Raises Refused otherwise."""
    ref = ref.strip()
    if re.match(r"^(File|Image):", ref, re.I):
        return "File:" + ref.split(":", 1)[1].strip().replace("_", " "), None
    u = urllib.parse.urlparse(ref)
    if u.scheme not in ("http", "https"):
        raise Refused(f"not a Commons file: {ref}")
    query = urllib.parse.parse_qs(u.query)
    page = int(query["page"][0]) if query.get("page", [""])[0].isdigit() else None
    host = u.netloc.lower()
    path = urllib.parse.unquote(u.path)
    if host == "commons.wikimedia.org":
        if path.startswith("/wiki/"):
            title = path[len("/wiki/"):]
        else:
            title = urllib.parse.unquote(query.get("title", [""])[0])
        if re.match(r"^(File|Image):", title, re.I):
            return "File:" + title.split(":", 1)[1].replace("_", " "), page
    elif host == "upload.wikimedia.org":
        parts = [p for p in path.split("/") if p]
        if "thumb" in parts:                     # /wikipedia/commons/thumb/a/ab/Name.jpg/800px-Name.jpg
            i = parts.index("thumb")
            if len(parts) > i + 3:
                return "File:" + parts[i + 3].replace("_", " "), page
        elif parts:
            return "File:" + parts[-1].replace("_", " "), page
    raise Refused(f"not a Commons file: {ref}")


def slug_name(title):
    """Default file name (no extension) from a File: title: ASCII, lower case, '-' separated, ≤ 80 chars."""
    stem = os.path.splitext(title.split(":", 1)[-1])[0]
    ascii_ = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")[:80].strip("-")
    return s or "commons-" + hashlib.md5(title.encode("utf-8")).hexdigest()[:10]


def safe_name(name):
    name = os.path.basename(name.strip())
    if not re.match(r"^[\w.-]+$", name, re.A) or name.startswith("."):
        raise Refused(f"bad file name {name!r}: use letters, digits, '.', '_', '-'")
    return name


def read_list(path):
    """[(ref, name or None, note or None)] from a --list file."""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cells = [c.strip() for c in line.split(" | ")]
            out.append((cells[0], (cells[1] if len(cells) > 1 and cells[1] else None),
                        (" | ".join(cells[2:]) if len(cells) > 2 else None)))
    return out


def credited_pages(folder):
    """{page url: file} already in the folder's _credits.jsonl."""
    seen, path = {}, os.path.join(folder, CREDITS)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("page"):
                    seen[row["page"]] = row.get("file")
    return seen


def page_url(title):
    return PAGE + urllib.parse.quote(title.replace(" ", "_"), safe=":/(),'!*")


def fit(img, max_px):
    """Shrink a Pillow image so its long side is ≤ max_px (never enlarges). -> (image, resized?)"""
    if max(img.size) <= max_px:
        return img, False
    from PIL import Image
    img = img.copy()
    img.thumbnail((max_px, max_px), Image.LANCZOS)
    return img, True


# --- API -----------------------------------------------------------------------------------------------------------

def api_url(params):
    base = {"action": "query", "format": "json", "formatversion": "2", "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata", "iiextmetadatafilter": "|".join(META_KEYS)}
    base.update(params)
    return API + "?" + urllib.parse.urlencode(base)


def file_info(client, title, max_px, page=None):
    """imageinfo of one File page (thumbnail ≤ max_px wide). Raises FetchError when the page is missing."""
    params = {"titles": title}
    params["iiurlparam" if page else "iiurlwidth"] = f"page{page}-{max_px}px" if page else str(max_px)
    data = client.get_json(api_url(params))
    pages = (data.get("query") or {}).get("pages") or []
    if not pages or pages[0].get("missing") or not pages[0].get("imageinfo"):
        raise netfetch.FetchError(f"no such file on Commons: {title}")
    p = pages[0]
    return p.get("title", title), p["imageinfo"][0]


def search(client, query, limit):
    data = client.get_json(api_url({"generator": "search", "gsrsearch": query, "gsrnamespace": "6",
                                    "gsrlimit": str(limit), "iiurlwidth": "320"}))
    pages = (data.get("query") or {}).get("pages") or []
    return sorted(pages, key=lambda p: p.get("index", 0))


# --- fetch one -----------------------------------------------------------------------------------------------------

def fetch_one(client, ref, out, name=None, note=None, kind=None, page=None, max_px=1600, allow_nonfree=False,
              log=print):
    """Fetch one reference into out/. -> 'saved' | 'skipped'. Raises Refused / netfetch.FetchError."""
    title, ref_page = parse_ref(ref)
    page = page or ref_page
    purl = page_url(title) + (f"?page={page}" if page else "")
    seen = credited_pages(out)
    if purl in seen:
        log(f"skip  {title}: already in {CREDITS} as {seen[purl]}")
        return "skipped"
    if name:
        name = safe_name(name)
        if os.path.exists(os.path.join(out, name)):
            log(f"skip  {name}: exists")
            return "skipped"
    title, info = file_info(client, title, max_px, page)
    meta = info.get("extmetadata") or {}
    lic, lic_url, free = licence_of(meta)
    if not free and not allow_nonfree:
        raise Refused(f"{title}: licence {lic!r} is not free (add --allow-nonfree only for internal reference, "
                      "never for the film)")
    src = info.get("thumburl") or info.get("url")
    if not src:
        raise netfetch.FetchError(f"{title}: no image URL in the API answer")
    stem = os.path.splitext(name)[0] if name else slug_name(title) + (f"-p{page}" if page else "")
    data = client.get(src)
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    orig_fmt = (img.format or "").upper()
    fmt = orig_fmt if orig_fmt in ("JPEG", "PNG") else "PNG"     # GIF, WebP, TIFF… are saved as PNG
    img, resized = fit(img, max_px)
    ext = ".jpg" if fmt == "JPEG" else ".png"
    dest = os.path.join(out, safe_name(stem + ext))
    if os.path.exists(dest):
        log(f"skip  {os.path.basename(dest)}: exists")
        return "skipped"
    os.makedirs(out, exist_ok=True)
    part = dest + ".part"
    if resized or fmt != orig_fmt:
        if fmt == "JPEG" and img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(part, format=fmt, **({"quality": 90} if fmt == "JPEG" else {}))
    else:
        with open(part, "wb") as f:
            f.write(data)
    os.replace(part, dest)
    row = {"title": title, "page": purl, "file": os.path.basename(dest), "licence": lic, "licence_url": lic_url,
           "free": free, "author": plain(meta.get("Artist")), "credit": plain(meta.get("Credit")),
           "date": plain(meta.get("DateTimeOriginal")) or plain(meta.get("DateTime")),
           "description": plain(meta.get("ImageDescription"), 400), "orig_size": [info.get("width"), info.get("height")],
           "size": list(img.size), "url": src, "note": note or "", "kind": kind or "",
           "fetched": datetime.date.today().isoformat()}
    with open(os.path.join(out, CREDITS), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    log(f"saved {os.path.basename(dest)}  {img.size[0]}x{img.size[1]}  {lic}{'' if free else ' [NON-FREE]'}  "
        f"{row['author'][:60]}")
    return "saved"


# --- CLI -----------------------------------------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(prog="refs_fetch.py", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between requests (default 1)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="search File pages on Commons (no download)")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--free-only", action="store_true", help="hide non-free and unknown licences")
    f = sub.add_parser("fetch", help="download images with their credits")
    f.add_argument("refs", nargs="*", metavar="REF", help="File:<name> or a Commons / upload.wikimedia.org URL")
    f.add_argument("--list", help="file with one reference per line: REF [| name [| note]]")
    f.add_argument("--out", required=True, help="folder for the images and _credits.jsonl")
    f.add_argument("--name", help="file name for a single REF (extension follows the image format)")
    f.add_argument("--note", help="what the image is for (goes into _credits.jsonl)")
    f.add_argument("--kind", help="free label in _credits.jsonl, e.g. old | ico | real | vn")
    f.add_argument("--page", type=int, help="page of a PDF/DjVu file")
    f.add_argument("--max-px", type=int, default=1600, help="long side limit (default 1600)")
    f.add_argument("--allow-nonfree", action="store_true",
                   help="also fetch non-free/unknown licences (recorded with free: false; internal reference only)")
    return ap


def main(argv=None):
    netfetch.utf8_stdio()
    args = build_parser().parse_args(argv)
    client = netfetch.Client(min_interval=max(args.interval, 0.0), log=lambda m: print(m, file=sys.stderr))
    if args.cmd == "search":
        try:
            pages = search(client, args.query, max(1, min(args.limit, 500)))
        except netfetch.FetchError as e:
            print(f"refs_fetch: {e}", file=sys.stderr)
            return 1
        shown = 0
        for p in pages:
            info = (p.get("imageinfo") or [{}])[0]
            lic, _, free = licence_of(info.get("extmetadata") or {})
            if args.free_only and not free:
                continue
            shown += 1
            print(f"{p.get('title')} | {info.get('width')}x{info.get('height')} | {lic}"
                  f"{'' if free else ' [NON-FREE]'} | {plain((info.get('extmetadata') or {}).get('Artist'), 60)} | "
                  f"{page_url(p.get('title', ''))}")
        print(f"{shown} result(s)", file=sys.stderr)
        return 0
    jobs = [(r, args.name, args.note) for r in args.refs]
    if args.list:
        try:
            jobs += read_list(args.list)
        except OSError as e:
            print(f"refs_fetch: {e}", file=sys.stderr)
            return 2
    if not jobs:
        print("refs_fetch: nothing to fetch (give REF or --list)", file=sys.stderr)
        return 2
    if args.name and len(jobs) > 1:
        print("refs_fetch: --name needs exactly one REF", file=sys.stderr)
        return 2
    if args.max_px < 16:
        print("refs_fetch: --max-px too small", file=sys.stderr)
        return 2
    try:
        import PIL  # noqa: F401
    except ImportError:
        print("refs_fetch: Pillow is not installed (pip install pillow)", file=sys.stderr)
        return 2
    count = {"saved": 0, "skipped": 0, "refused": 0, "failed": 0}
    for ref, name, note in jobs:
        try:
            count[fetch_one(client, ref, args.out, name=name, note=note or args.note, kind=args.kind,
                            page=args.page, max_px=args.max_px, allow_nonfree=args.allow_nonfree)] += 1
        except Refused as e:
            count["refused"] += 1
            print(f"refused {e}", file=sys.stderr)
        except netfetch.FetchError as e:
            count["failed"] += 1
            print(f"failed {ref}: {e}", file=sys.stderr)
        except OSError as e:                       # unreadable image, disk full
            count["failed"] += 1
            print(f"failed {ref}: {e}", file=sys.stderr)
    print("refs_fetch: " + ", ".join(f"{v} {k}" for k, v in count.items()) + f"; {client.requests} request(s)")
    return 1 if count["failed"] else 2 if count["refused"] else 0


if __name__ == "__main__":
    sys.exit(main())
