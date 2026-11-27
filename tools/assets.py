#!/usr/bin/env python3
"""CC0 assets for the Blender `realistic` look (HDRI, PBR texture sets, scanned models) from Poly Haven and ambientCG.

  python3 tools/assets.py search --type hdri|texture|model [--source polyhaven|ambientcg|all] [--category C]
                                 [--tag T ...] [--query Q] [--limit 20]
  python3 tools/assets.py plan  <id> [<id> ...] --asset-root out/<project>/assets [--source S] [--res 2k] [--format F]
  python3 tools/assets.py fetch <id> [<id> ...] --asset-root out/<project>/assets [--res 2k] [--use "<hint>"] --yes

- `plan` lists every file (path under the asset root, resolution, size, md5 known or not, new / exists / partial), the
  total to download and the free disk space, then stops. Nothing is downloaded.
- `fetch` prints the same plan and refuses without --yes (exit 2): the user agrees to the size first. With --yes it
  downloads through <file>.part (resumed with an HTTP Range request), checks size and md5 against the API (ambientCG
  gives no md5: size only), never overwrites a finished file, and adds or updates one row per asset in
  <asset root>/ASSETS_MANIFEST.csv.
- Layout = what tools/blender/spec.py reads through `asset_root` in shot3d.json: hdri/<file>.hdr|exr,
  textures/<id>/<maps>, models/<id>/<gltf + bin + textures/>.
- Licence: both sources publish CC0 only; the manifest says CC0.
- Polite: one request at a time, --interval seconds apart (default 0.5), backoff on 429 honouring Retry-After
  (tools/netfetch.py), generic User-Agent without personal data.

Exit codes: 0 done, 2 refused before downloading (usage, unknown id or resolution, no --yes, not enough disk),
1 a download failed (the .part file is kept; a md5 mismatch says which file to delete).
"""
import argparse, csv, os, re, shutil, sys, urllib.parse, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netfetch  # noqa: E402

PH_API = "https://api.polyhaven.com"
ACG_API = "https://ambientcg.com/api/v2/full_json"
MANIFEST = "ASSETS_MANIFEST.csv"
HEADER = ["asset_id", "kind", "source", "title", "url_page", "licence", "resolution", "files", "bytes", "suggested_use"]
KINDS = ("hdri", "texture", "model")
SOURCES = ("polyhaven", "ambientcg")
PH_TYPE = {"hdri": "hdris", "texture": "textures", "model": "models"}
PH_KIND = {0: "hdri", 1: "texture", 2: "model"}
ACG_TYPE = {"hdri": "HDRI", "texture": "Material", "model": "3DModel"}
ACG_KIND = {v: k for k, v in ACG_TYPE.items()}
# texture maps: our name -> Poly Haven keys of /files/<id>; default format preference per map
PH_MAPS = {"diff": ("Diffuse", "diff"), "nor_gl": ("nor_gl",), "rough": ("Rough", "rough"), "ao": ("AO", "ao"),
           "disp": ("Displacement", "disp"), "arm": ("arm",), "nor_dx": ("nor_dx",), "bump": ("Bump", "bump")}
MAP_FORMATS = {"nor_gl": ("png", "jpg", "exr"), "disp": ("png", "jpg", "exr"), "nor_dx": ("png", "jpg", "exr")}
DEFAULT_MAPS = "diff,nor_gl,rough,ao,disp"
KEEP_FROM_ZIP = (".jpg", ".jpeg", ".png", ".exr", ".hdr", ".tif", ".tiff", ".gltf", ".glb", ".bin", ".obj", ".mtl",
                 ".fbx", ".usda", ".usdc")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
NAME_RE = re.compile(r"^[\w.-]+$", re.A)


class Refused(Exception):
    """Refused before downloading (exit 2)."""


def human(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def safe_rel(rel):
    """A relative path from an API answer, checked part by part (no '..', no absolute path, plain names)."""
    parts = [p for p in str(rel).replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or any(p == ".." or not NAME_RE.match(p) for p in parts):
        raise Refused(f"unsafe file name from the API: {rel!r}")
    return "/".join(parts)


def url_name(url):
    """File name of a download URL (last path segment, or the ?file= of an ambientCG get link)."""
    u = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(u.query)
    return safe_rel(os.path.basename(q["file"][0] if q.get("file") else urllib.parse.unquote(u.path)))


def kind_dir(kind, asset_id):
    return "hdri" if kind == "hdri" else f"{'textures' if kind == 'texture' else 'models'}/{asset_id}"


def pick(options, prefs):
    """First key of options (a dict) in prefs order, else None."""
    for p in prefs:
        if p in options:
            return p
    return None


# --- Poly Haven ----------------------------------------------------------------------------------------------------

def ph_search(client, kind, category=None, tags=(), query=None, limit=20):
    params = {"type": PH_TYPE[kind]}
    if category:
        params["categories"] = category
    data = client.get_json(f"{PH_API}/assets?{urllib.parse.urlencode(params)}")
    rows = []
    for aid, a in (data or {}).items():
        words = {w.lower() for w in (a.get("tags") or []) + (a.get("categories") or [])}
        if any(t.lower() not in words for t in tags):
            continue
        if query and query.lower() not in " ".join([aid, a.get("name", "")] + sorted(words)).lower():
            continue
        mr = a.get("max_resolution") or []
        rows.append({"id": aid, "source": "polyhaven", "kind": PH_KIND.get(a.get("type"), kind),
                     "title": a.get("name", aid), "tags": ", ".join((a.get("categories") or [])[:4]),
                     "max": "x".join(str(x) for x in mr), "rank": a.get("download_count", 0),
                     "page": f"https://polyhaven.com/a/{aid}"})
    rows.sort(key=lambda r: -int(r["rank"] or 0))
    return rows[:limit]


def ph_plan(client, aid, kind, res, fmt, maps):
    info = client.get_json(f"{PH_API}/info/{aid}")
    if not isinstance(info, dict) or "type" not in info:
        raise Refused(f"polyhaven: no asset {aid!r}")
    real = PH_KIND.get(info.get("type"))
    if kind and real != kind:
        raise Refused(f"polyhaven: {aid} is a {real}, not a {kind}")
    kind = real
    files = client.get_json(f"{PH_API}/files/{aid}")
    out = []

    def entry(block, label, prefs):
        if not isinstance(block, dict) or res not in block:
            have = sorted(block) if isinstance(block, dict) else []
            raise Refused(f"polyhaven: {aid} {label} has no {res} (has: {', '.join(have) or 'none'})")
        byfmt = block[res]
        f = pick(byfmt, prefs)
        if not f:
            raise Refused(f"polyhaven: {aid} {label} {res} has no {'/'.join(prefs)} (has: {', '.join(sorted(byfmt))})")
        return byfmt[f]

    if kind == "hdri":
        e = entry(files.get("hdri"), "hdri", (fmt,) if fmt else ("hdr", "exr"))
        out.append({"url": e["url"], "rel": url_name(e["url"]), "size": e.get("size"), "md5": e.get("md5")})
    elif kind == "texture":
        for m in maps:
            key = next((k for k in PH_MAPS.get(m, (m,)) if k in files), None)
            if key is None:
                if m == "diff":
                    raise Refused(f"polyhaven: {aid} has no colour map")
                continue                                    # e.g. no AO map for this set: skipped
            e = entry(files[key], m, (fmt,) if fmt else MAP_FORMATS.get(m, ("jpg", "png")))
            out.append({"url": e["url"], "rel": url_name(e["url"]), "size": e.get("size"), "md5": e.get("md5")})
    else:
        f = fmt or "gltf"
        e = entry(files.get(f), f, (f,))
        out.append({"url": e["url"], "rel": url_name(e["url"]), "size": e.get("size"), "md5": e.get("md5")})
        for rel, inc in sorted((e.get("include") or {}).items()):
            out.append({"url": inc["url"], "rel": safe_rel(rel), "size": inc.get("size"), "md5": inc.get("md5")})
    return {"id": aid, "source": "polyhaven", "kind": kind, "title": info.get("name", aid),
            "page": f"https://polyhaven.com/a/{aid}", "licence": "CC0", "res": res, "files": out}


# --- ambientCG -----------------------------------------------------------------------------------------------------

def acg_downloads(asset):
    """Every download entry of a v2 full_json asset (downloadFolders -> downloadFiletypeCategories -> downloads)."""
    out = []
    for folder in (asset.get("downloadFolders") or {}).values():
        for cat in (folder.get("downloadFiletypeCategories") or {}).values():
            out += [d for d in (cat.get("downloads") or []) if isinstance(d, dict)]
    return out


def acg_search(client, kind, category=None, tags=(), query=None, limit=20):
    params = {"type": ACG_TYPE[kind], "limit": str(limit), "include": "tagData,displayData", "sort": "Popular"}
    if query:
        params["q"] = query
    if tags:
        params["tags"] = ",".join(tags)
    if category:
        params["category"] = category
    data = client.get_json(f"{ACG_API}?{urllib.parse.urlencode(params)}")
    rows = []
    for a in (data or {}).get("foundAssets") or []:
        aid = a.get("assetId", "")
        rows.append({"id": aid, "source": "ambientcg", "kind": ACG_KIND.get(a.get("dataType"), kind),
                     "title": a.get("displayName", aid), "tags": ", ".join((a.get("tags") or [])[:4]), "max": "",
                     "page": f"https://ambientcg.com/view?id={aid}"})
    return rows[:limit]


def acg_plan(client, aid, kind, res, fmt):
    params = {"id": aid, "include": "downloadData,displayData"}
    data = client.get_json(f"{ACG_API}?{urllib.parse.urlencode(params)}")
    found = [a for a in (data or {}).get("foundAssets") or [] if a.get("assetId") == aid]
    if not found:
        raise Refused(f"ambientcg: no asset {aid!r}")
    a = found[0]
    real = ACG_KIND.get(a.get("dataType"))
    if real is None:
        raise Refused(f"ambientcg: {aid} is a {a.get('dataType')}, not an HDRI, material or 3D model")
    if kind and real != kind:
        raise Refused(f"ambientcg: {aid} is a {real}, not a {kind}")
    kind = real
    prefs = [fmt.upper()] if fmt else (["HDR", "EXR"] if kind == "hdri" else ["JPG", "PNG"])
    by_attr = {str(d.get("attribute", "")).upper(): d for d in acg_downloads(a)}
    want = [f"{res.upper()}-{p}" for p in prefs]
    attr = pick(by_attr, want)
    if not attr:
        raise Refused(f"ambientcg: {aid} has no {' / '.join(want)} (has: {', '.join(sorted(by_attr)) or 'none'})")
    d = by_attr[attr]
    url = d.get("fullDownloadPath") or d.get("downloadLink")
    name = safe_rel(os.path.basename(d.get("fileName") or url_name(url)))
    zipped = str(d.get("filetype", "")).lower() == "zip" or name.lower().endswith(".zip")
    return {"id": aid, "source": "ambientcg", "kind": kind, "title": a.get("displayName", aid),
            "page": f"https://ambientcg.com/view?id={aid}", "licence": "CC0", "res": res,
            "files": [{"url": url, "rel": name, "size": d.get("size"), "md5": d.get("md5"), "zip": zipped}]}


# --- plan, fetch, manifest -----------------------------------------------------------------------------------------

def read_manifest(root):
    path = os.path.join(root, MANIFEST)
    if not os.path.isfile(path):
        return list(HEADER), []
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        header = list(r.fieldnames or HEADER)
        rows = list(r)
    return header + [h for h in HEADER if h not in header], rows


def write_manifest(root, header, rows):
    path = os.path.join(root, MANIFEST)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def manifest_row(rows, aid, source):
    return next((r for r in rows if r.get("asset_id") == aid and r.get("source") == source), None)


def file_status(root, item, f, rows):
    """'exists' | 'partial' | 'new' for one planned file (a zip counts as there when the manifest lists the asset at
    this resolution and its files are on disk)."""
    base = os.path.join(root, kind_dir(item["kind"], item["id"]))
    if f.get("zip"):
        row = manifest_row(rows, item["id"], item["source"])
        if row and row.get("resolution") == item["res"] and all(
                os.path.isfile(os.path.join(base, p)) for p in (row.get("files") or "").split(";") if p):
            return "exists"
    dest = os.path.join(base, f["rel"])
    if os.path.isfile(dest):
        return "exists"
    return "partial" if os.path.isfile(dest + ".part") else "new"


def make_plan(client, ids, args):
    maps = [m.strip() for m in args.maps.split(",") if m.strip()]
    items = []
    for aid in ids:
        if not ID_RE.match(aid):
            raise Refused(f"bad asset id {aid!r}")
        if args.source == "polyhaven":
            items.append(ph_plan(client, aid, args.type, args.res.lower(), args.format, maps))
        else:
            items.append(acg_plan(client, aid, args.type, args.res.lower(), args.format))
    return items


def print_plan(root, items, rows):
    """Print the plan; -> (bytes to download, file count to download, free disk bytes or None)."""
    todo = files_todo = have = 0
    print(f"plan: {len(items)} asset(s) under {root}")
    for it in items:
        print(f"  {it['id']}  {it['kind']}  {it['source']}  {it['licence']}  {it['res']}  {it['page']}")
        for f in it["files"]:
            st = file_status(root, it, f, rows)
            f["status"] = st
            size = f.get("size") or 0
            part = os.path.join(root, kind_dir(it["kind"], it["id"]), f["rel"]) + ".part"
            left = size - (os.path.getsize(part) if st == "partial" and os.path.isfile(part) else 0)
            if st == "exists":
                have += size
            else:
                todo += max(left, 0)
                files_todo += 1
            extra = (" md5" if f.get("md5") else " size only") + (" zip→extract" if f.get("zip") else "")
            print(f"    {st:8} {kind_dir(it['kind'], it['id'])}/{f['rel']}  {human(size) if size else '? B'}{extra}")
    free = free_space(root)
    print(f"total: {files_todo} file(s) to download, {human(todo)} ({human(have)} already on disk)"
          + (f"; free on disk: {human(free)}" if free is not None else ""))
    return todo, files_todo, free


def free_space(path):
    """Free bytes on the disk that holds path (its nearest existing parent); None when unknown."""
    p = os.path.abspath(path)
    while not os.path.isdir(p) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return None


def extract(zpath, folder, keep_dirs=False):
    """Extract the useful files of a downloaded zip into folder (names checked, nothing overwritten).
    Flat for textures and HDRIs (spec.py looks for the maps in one folder); a model keeps its subfolders so the
    relative URIs of a .gltf / .obj still resolve. -> relative paths extracted or already there.
    Refused (FetchError, zip kept): two members that would land on the same name, or more than the free disk space."""
    picked = {}
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            parts = [p for p in info.filename.replace("\\", "/").split("/") if p not in ("", ".")]
            if not parts or not parts[-1].lower().endswith(KEEP_FROM_ZIP):
                continue
            if keep_dirs and all(p != ".." and NAME_RE.match(p) for p in parts):
                rel = "/".join(parts)
            elif NAME_RE.match(parts[-1]):
                rel = parts[-1]
            else:
                continue
            if rel in picked:
                raise netfetch.FetchError(f"{os.path.basename(zpath)}: two members land on {rel} "
                                          f"({picked[rel].filename}, {info.filename}); zip kept")
            picked[rel] = info
        need = sum(i.file_size for r, i in picked.items() if not os.path.exists(os.path.join(folder, r)))
        free = free_space(folder)
        if free is not None and need > free:
            raise netfetch.FetchError(f"{os.path.basename(zpath)}: {human(need)} to extract, {human(free)} free; "
                                      "zip kept")
        for rel, info in picked.items():
            dest = os.path.join(folder, *rel.split("/"))
            if not os.path.exists(dest):
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(info) as src, open(dest + ".part", "wb") as out:
                    shutil.copyfileobj(src, out)
                os.replace(dest + ".part", dest)
    return sorted(picked)


def fetch_item(client, root, it, use, header, rows):
    base = os.path.join(root, kind_dir(it["kind"], it["id"]))
    names = []
    for f in it["files"]:
        if f.get("status") == "exists" and f.get("zip"):
            row = manifest_row(rows, it["id"], it["source"])
            listed = [p for p in ((row or {}).get("files") or "").split(";") if p]
            if row and row.get("resolution") == it["res"] and listed and all(
                    os.path.isfile(os.path.join(base, p)) for p in listed):
                names += listed
                continue
            # the zip is on disk but was never extracted (an earlier run stopped): download() says "exists",
            # then it is extracted below
        dest = os.path.join(base, f["rel"])
        r = client.download(f["url"], dest, size=f.get("size"), md5=f.get("md5"))
        print(f"    {r['status']:6} {kind_dir(it['kind'], it['id'])}/{f['rel']}"
              + (f" (resumed at {human(r['resumed'])})" if r.get("resumed") else ""))
        if f.get("zip"):
            got = extract(dest, base, keep_dirs=it["kind"] == "model")
            if not got:
                raise netfetch.FetchError(f"{f['rel']}: no usable file in the zip (kept)")
            os.remove(dest)
            names += got
        else:
            names.append(f["rel"])
    total = sum(os.path.getsize(os.path.join(base, n)) for n in names if os.path.isfile(os.path.join(base, n)))
    old = manifest_row(rows, it["id"], it["source"])
    new = {"asset_id": it["id"], "kind": it["kind"], "source": it["source"], "title": it["title"],
           "url_page": it["page"], "licence": it["licence"], "resolution": it["res"], "files": ";".join(names),
           "bytes": str(total), "suggested_use": use or (old or {}).get("suggested_use", "")}
    if old:
        old.update(new)
    else:
        rows.append(new)
    write_manifest(root, header, rows)


# --- CLI -----------------------------------------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(prog="assets.py", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interval", type=float, default=0.5, help="seconds between requests (default 0.5)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="list assets (no download)")
    s.add_argument("--type", choices=KINDS, required=True)
    s.add_argument("--source", choices=SOURCES + ("all",), default="all")
    s.add_argument("--category", help="Poly Haven category / ambientCG category")
    s.add_argument("--tag", action="append", default=[], help="tag the asset must have (repeat for several)")
    s.add_argument("--query", help="free text (ambientCG search; Poly Haven: in id, name, tags)")
    s.add_argument("--limit", type=int, default=20)
    pl = sub.add_parser("plan", help="print files, sizes and the total; download nothing")
    fe = sub.add_parser("fetch", help="download (only with --yes, after the user agreed to the plan)")
    fe.add_argument("--use", help="suggested_use column of the manifest (which shot, what for)")
    fe.add_argument("--yes", action="store_true", help="the user agreed to the plan: download")
    for p in (pl, fe):
        p.add_argument("ids", nargs="+", metavar="ID")
        p.add_argument("--asset-root", required=True, help="out/<project>/assets (= asset_root of shot3d.json)")
        p.add_argument("--source", choices=SOURCES, default="polyhaven")
        p.add_argument("--type", choices=KINDS, help="check the asset's type (default: taken from the API)")
        p.add_argument("--res", default="2k", help="1k | 2k | 4k | 8k (default 2k)")
        p.add_argument("--format", help="hdri: hdr|exr; model: gltf|blend|fbx; ambientCG: jpg|png|hdr|exr")
        p.add_argument("--maps", default=DEFAULT_MAPS, help=f"texture maps (default {DEFAULT_MAPS}; also arm, nor_dx)")
    return ap


def main(argv=None):
    netfetch.utf8_stdio()
    args = build_parser().parse_args(argv)
    client = netfetch.Client(min_interval=max(args.interval, 0.0), log=lambda m: print(m, file=sys.stderr))
    try:
        if args.cmd == "search":
            rows = []
            for src in (SOURCES if args.source == "all" else (args.source,)):
                fn = ph_search if src == "polyhaven" else acg_search
                rows += fn(client, args.type, args.category, args.tag, args.query, max(1, args.limit))
            for r in rows:
                print(f"{r['id']} | {r['kind']} | {r['source']} | {r['title']} | {r['tags']}"
                      f"{' | max ' + r['max'] if r['max'] else ''} | {r['page']}")
            print(f"{len(rows)} result(s)", file=sys.stderr)
            return 0
        root = args.asset_root
        items = make_plan(client, args.ids, args)
        header, rows = read_manifest(root)
        todo, nfiles, free = print_plan(root, items, rows)
        if args.cmd == "plan":
            return 0
        if not args.yes:
            print("fetch: nothing downloaded. Show this plan to the user; after they agree, run again with --yes.",
                  file=sys.stderr)
            return 2
        if free is not None and todo > free:
            print(f"fetch: not enough disk space ({human(todo)} needed, {human(free)} free)", file=sys.stderr)
            return 2
        os.makedirs(root, exist_ok=True)
        failed = 0
        for it in items:
            print(f"  {it['id']}")
            try:
                fetch_item(client, root, it, args.use, header, rows)
            except (netfetch.FetchError, OSError, zipfile.BadZipFile) as e:
                failed += 1
                print(f"failed {it['id']}: {e}", file=sys.stderr)
        print(f"fetch: {len(items) - failed} asset(s) ready, {failed} failed; manifest {os.path.join(root, MANIFEST)}")
        return 1 if failed else 0
    except Refused as e:
        print(f"assets: {e}", file=sys.stderr)
        return 2
    except netfetch.FetchError as e:
        print(f"assets: {e}", file=sys.stderr)
        return 2 if e.status == 404 else 1


if __name__ == "__main__":
    sys.exit(main())
