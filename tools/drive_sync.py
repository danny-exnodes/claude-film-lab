#!/usr/bin/env python3
"""Plan Google Drive pushes for a project working copy (docs/CONVENTIONS.md §11). No network, no Drive calls.

The Drive connector has no CLI: Claude pulls and pushes one file at a time with MCP tools
(download_file_content, create_file, update_file). This helper remembers what was pulled, maps every local
path to its Drive folder ID from PROJECT.md and prints the exact connector calls for what changed.

  python3 tools/drive_sync.py snapshot projects/<project> [--include-out out/<project>]
  python3 tools/drive_sync.py plan     projects/<project> [--include-out out/<project>] [--json] [--now YYYYMMDD-HHMM] [--date YYYY-MM-DD]
  python3 tools/drive_sync.py record   projects/<project> --uploaded <path> --id <newDriveFileId> [--uploaded ... --id ...]

snapshot  right after a pull: hash the working copy into projects/<project>/.pulled.sha256 and write the pull time
          to projects/<project>/.pulled.at (§11.6 pull step 4).
plan      list new/changed files: target folder (logical path + ID, or MISSING + which folder to create under which
          parent first), Drive title, mime type, the create_file file reference `sha256:<hex>:<absolute path>` and,
          for changed files, the search_files query that finds the old version(s) and their archive name in
          99_LuuTru/ (§11.6 push step 3). TienDo_SanXuat.csv is listed apart (§11.6 step 5). --json: same plan as JSON.
record    after each successful create_file: replace just that file's line in .pulled.sha256 and append
          `<UTC> <path> <new Drive ID>` to projects/<project>/.pushed.log (§11.6 push steps 2 and 6).

State files in projects/<project>/ (dotfiles: never pushed, never snapshotted):
  .pulled.sha256  `sha256sum` format `<hex>  <path>`; paths as `find projects/<project>` prints them from the repo
                  root (projects/<project>/..., media from --include-out as out/<project>/...), so the shell commands
                  of §11.6 and `sha256sum -c` (from the repo root) still work on it.
  .pulled.at      pull time, UTC ISO (2026-11-10T15:30:00Z).
  .pushed.log     one line per upload this session: `<UTC ISO> <path> <new Drive ID>`.

Ignored everywhere: dotfiles and dot-directories, __pycache__.
Exit: 0 ok, 1 plan has blockers (folders to create, unmapped files), 2 cannot plan (no PROJECT.md, bad manifest...).
"""
import argparse, datetime, hashlib, json, mimetypes, os, re, sys

import yaml

SNAPSHOT, PULLED_AT, PUSHED_LOG = ".pulled.sha256", ".pulled.at", ".pushed.log"
ARCHIVE = "99_LuuTru"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHEET_LOCAL = "TienDo_SanXuat.csv"            # Google Sheet 00_QuanLy/TienDo_SanXuat (§11.6 step 5)
SHEET_KEY = "00_QuanLy/TienDo_SanXuat"
CATALOG = "sources/DanhMuc.csv"               # the one editable file of 01_TaiLieuGoc (§11.3)
MIME = {
    ".md": "text/markdown", ".csv": "text/csv", ".json": "application/json", ".yaml": "text/plain",
    ".yml": "text/plain", ".txt": "text/plain", ".zip": "application/zip", ".mp4": "video/mp4",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".pdf": "application/pdf", ".wav": "audio/wav", ".mp3": "audio/mpeg", ".html": "text/html",
}
RE_EP_DIR = re.compile(r"^ep(\d{2})-[a-z0-9]+(?:-[a-z0-9]+)*$")
RE_MEDIA_EP = re.compile(r"^ep(\d{2})$")
RE_BUNDLE_DATE = re.compile(r"_(\d{4})(\d{2})(\d{2})\.zip$")
RE_NOW = re.compile(r"^\d{8}-\d{4}$")
RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class SyncError(Exception):
    """A problem that stops the command (exit 2)."""


# --- files and hashes -------------------------------------------------------------------------------------

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ignored(rel):
    return any((p.startswith(".") and p != "..") or p == "__pycache__" for p in rel.split("/"))


def walk(root):
    """Relative POSIX paths of the files under root, sorted, minus dotfiles and __pycache__."""
    found = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if not x.startswith(".") and x != "__pycache__"]
        for f in files:
            rel = os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/")
            if not ignored(rel):
                found.append(rel)
    return sorted(found)


def lab_root(project_dir):
    """The directory `find projects/<project>` runs from: two levels above the project working copy."""
    return os.path.dirname(os.path.dirname(project_dir))


def key_for(project_dir, path):
    """Snapshot key: path relative to the repo root (projects/<project>/..., out/<project>/...), POSIX."""
    return os.path.relpath(os.path.abspath(path), lab_root(project_dir)).replace(os.sep, "/")


def mime_for(name):
    ext = os.path.splitext(name)[1].lower()
    return MIME.get(ext) or mimetypes.guess_type(name)[0] or "application/octet-stream"


def utc_iso(now=None):
    return (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- state files --------------------------------------------------------------------------------------------

def read_snapshot(project_dir):
    """{key: sha256} from .pulled.sha256, or None when there is no snapshot."""
    path = os.path.join(project_dir, SNAPSHOT)
    if not os.path.isfile(path):
        return None
    snap = {}
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            m = re.match(r"^([0-9a-fA-F]{64}) [ *](.+)$", line)
            if not m:
                raise SyncError(f"{path}:{n}: not a sha256sum line: {line[:80]!r}")
            p = m.group(2)
            p = key_for(project_dir, p) if os.path.isabs(p) else os.path.normpath(p).replace(os.sep, "/")
            snap[p] = m.group(1).lower()
    return snap


def write_snapshot(project_dir, snap):
    path = os.path.join(project_dir, SNAPSHOT)
    with open(path, "w", encoding="utf-8") as f:
        for k in sorted(snap):
            f.write(f"{snap[k]}  {k}\n")
    return path


def read_text(path):
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def pushed_ids(project_dir):
    """New Drive IDs this session uploaded (third field of .pushed.log)."""
    text = read_text(os.path.join(project_dir, PUSHED_LOG)) or ""
    return [parts[-1] for parts in (l.split() for l in text.splitlines()) if len(parts) >= 3]


# --- manifest ----------------------------------------------------------------------------------------------

def known_id(v):
    return isinstance(v, str) and v.strip() != "" and not v.strip().startswith("<")


def load_manifest(project_dir):
    path = os.path.join(project_dir, "PROJECT.md")
    if not os.path.isfile(path):
        raise SyncError(f"{path} not found: pull 00_QuanLy/PROJECT.md from Drive first (CONVENTIONS §11.6), "
                        "or for a new project copy templates/project/PROJECT.md (§11.5)")
    text = read_text(path)
    m = re.match(r"^---\s*\n(.*?)\n---\s*(\n|$)", text, re.S)
    if not m:
        raise SyncError(f"{path}: no YAML front matter (--- ... ---), see templates/project/PROJECT.md")
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise SyncError(f"{path}: front matter is not valid YAML: {e}")
    drive = fm.get("drive") if isinstance(fm, dict) else None
    if not isinstance(drive, dict) or not isinstance(drive.get("folders"), dict):
        raise SyncError(f"{path}: front matter needs drive.folders (logical path -> folder ID), CONVENTIONS §11.2")
    folders = {str(k).strip("/"): (str(v).strip() if v is not None else None) for k, v in drive["folders"].items()}
    files = {str(k): (str(v).strip() if v is not None else None) for k, v in (drive.get("files") or {}).items()}
    return {"path": path, "project": fm.get("project") or os.path.basename(project_dir),
            "name": drive.get("name"), "root": drive.get("root"), "folders": folders, "files": files}


def folder_id(man, logical):
    v = man["folders"].get(logical)
    return v if known_id(v) else None


def missing_chain(man, logical):
    """Folders to create (parent first) before `logical` exists: [{path, name, parent_path, parent_id}]."""
    parts = logical.split("/")
    chain = []
    for i in range(1, len(parts) + 1):
        p = "/".join(parts[:i])
        if folder_id(man, p):
            continue
        parent = "/".join(parts[:i - 1])
        pid = folder_id(man, parent) if parent else (man["root"] if known_id(man["root"]) else None)
        chain.append({"path": p, "name": parts[i - 1], "parent_path": parent or "(project root)", "parent_id": pid})
    return chain


# --- §11.3 mapping -------------------------------------------------------------------------------------------

def map_project(rel):
    """Drive folder (logical path) for a file of projects/<project>/ (rel to it), or None when unmapped."""
    parts = rel.split("/")
    name, head = parts[-1], parts[0]
    if len(parts) == 1:
        return {"PROJECT.md": "00_QuanLy", SHEET_LOCAL: "00_QuanLy", "SERIES.md": "02_KinhThu"}.get(name)
    sub = "/".join(parts[1:-1])
    join = lambda base: base + ("/" + sub if sub else "")
    if head == "characters" and len(parts) >= 3:
        return join("02_KinhThu/NhanVat")
    if head == "locations" and len(parts) >= 3:
        return join("02_KinhThu/BoiCanh")
    if head == "style":
        return join("02_KinhThu/PhongCach")
    if head == "sources":
        return join("01_TaiLieuGoc")
    if RE_EP_DIR.match(head):
        return "03_KichBan/" + "/".join(parts[:-1])
    return None


def episode_dirs(project_dir, man, nn):
    """ep<NN>-<slug> names known for episode NN (working copy folders, then manifest keys)."""
    names = sorted(d for d in os.listdir(project_dir)
                   if os.path.isdir(os.path.join(project_dir, d)) and RE_EP_DIR.match(d) and d[2:4] == nn)
    if not names:
        names = sorted({k.split("/")[1] for k in man["folders"]
                        if k.count("/") >= 1 and k.split("/")[0] in ("03_KichBan", "04_SanXuat", "05_ThanhPham")
                        and RE_EP_DIR.match(k.split("/")[1]) and k.split("/")[1][2:4] == nn})
    return names


def map_out(rel, project_dir, man, day):
    """(folder, reason) for a file of out/<project>/ (rel to it); folder None when this tool does not push it."""
    parts = rel.split("/")
    name, head = parts[-1], parts[0]
    if head == "characters" and len(parts) >= 3:
        return "02_KinhThu/NhanVat/" + "/".join(parts[1:-1]), None
    if head == "locations" and len(parts) >= 3:
        return "02_KinhThu/BoiCanh/" + "/".join(parts[1:-1]), None
    if head == "sources" and len(parts) >= 2:
        return "/".join(["01_TaiLieuGoc"] + parts[1:-1]), None
    m = RE_MEDIA_EP.match(head)
    if not m:
        return None, "skip"
    kind = None
    if len(parts) == 2 and name == "ledger.csv":
        kind = "ledger"
    elif len(parts) == 3 and parts[1] == "bundles" and name.endswith(".zip"):
        kind = "bundle"
    elif len(parts) == 3 and parts[1] == "renders" and "_draft_" in name and name.endswith(".mp4"):
        kind = "draft"
    elif len(parts) == 3 and parts[1] == "renders" and "_final_" in name:
        kind = "final"
    if not kind:
        return None, "skip"      # plates/, clips/, frames...: they travel inside the shot bundles (§9)
    eps = episode_dirs(project_dir, man, m.group(1))
    if len(eps) != 1:
        why = "no" if not eps else "several"
        return None, (f"{why} episode folder ep{m.group(1)}-<slug> in the working copy or drive.folders: "
                      "cannot tell the Drive episode folder")
    ep = eps[0]
    if kind == "ledger":
        return f"04_SanXuat/{ep}", None
    if kind == "final":
        return f"05_ThanhPham/{ep}", None
    d = RE_BUNDLE_DATE.search(name) if kind == "bundle" else None
    return f"04_SanXuat/{ep}/" + (f"{d.group(1)}-{d.group(2)}-{d.group(3)}" if d else day), None


# --- archive naming (§11.6 step 3) ----------------------------------------------------------------------------

def archive_name(folder, title, stamp):
    """<folder path, '/' -> '__'>__<name without extension>_<YYYYMMDD-HHMM>.<ext>"""
    stem, ext = os.path.splitext(title)
    return f"{folder.replace('/', '__')}__{stem}_{stamp}{ext}"


def search_query(fid, folder, title):
    return f"parentId = '{fid or '<ID of ' + folder + '>'}' and title = '{title}' and trashed = false"


# --- commands ------------------------------------------------------------------------------------------------

def project_dir_of(arg):
    d = os.path.abspath(arg)
    if not os.path.isdir(d):
        raise SyncError(f"{arg}: project working copy not found (pull it from Drive first, CONVENTIONS §11.6)")
    return d


def out_files(out_arg):
    """[(rel to out dir, abs path)] of every file of out/<project>/ (mapping decides what is pushed)."""
    out_dir = os.path.abspath(out_arg)
    if not os.path.isdir(out_dir):
        return []          # nothing generated or pulled yet (new project, fresh container)
    return [(r, os.path.join(out_dir, r)) for r in walk(out_dir)]


def cmd_snapshot(a):
    pd = project_dir_of(a.project)
    snap = {key_for(pd, os.path.join(pd, r)): sha256(os.path.join(pd, r)) for r in walk(pd)}
    n_project = len(snap)
    if a.include_out:
        for _, full in out_files(a.include_out):
            snap[key_for(pd, full)] = sha256(full)
    path = write_snapshot(pd, snap)
    at = utc_iso()
    with open(os.path.join(pd, PULLED_AT), "w", encoding="utf-8") as f:
        f.write(at + "\n")
    print(f"snapshot  {os.path.relpath(path)}: {n_project} file(s)"
          + (f" + {len(snap) - n_project} media" if a.include_out else "") + f" · pulled at {at}")
    return 0


def parse_now(a):
    if a.now:
        if not RE_NOW.match(a.now):
            raise SyncError(f"--now {a.now!r}: expected YYYYMMDD-HHMM (UTC)")
        now = datetime.datetime.strptime(a.now, "%Y%m%d-%H%M")
    else:
        now = datetime.datetime.now(datetime.timezone.utc)
    day = a.date or now.strftime("%Y-%m-%d")
    if not RE_DATE.match(day):
        raise SyncError(f"--date {day!r}: expected YYYY-MM-DD")
    return now.strftime("%Y%m%d-%H%M"), day


def entry(man, key, full, folder, h, status, stamp, sheet=False):
    """One planned upload: folder, create_file arguments, archive step for changed files."""
    title = "TienDo_SanXuat" if sheet else os.path.basename(key)
    fid = folder_id(man, folder)
    archive = None
    if status == "changed" or sheet:
        archive = {"search_files": search_query(fid, folder, title),
                   "move": "every result except the new ID", "parentId": folder_id(man, ARCHIVE),
                   "title": archive_name(folder, title, stamp)}
        if sheet and known_id(man["files"].get(SHEET_KEY)):
            archive["drive_files_id"] = man["files"][SHEET_KEY]
    return {"status": status, "local": key, "path": os.path.abspath(full), "sha256": h,
            "folder": {"path": folder, "id": fid, "missing": [] if fid else missing_chain(man, folder)},
            "create_file": {"title": title, "parentId": fid, "contentMimeType": mime_for(os.path.basename(key)),
                            "base64Content": f"sha256:{h}:{os.path.abspath(full)}",
                            "disableConversionToGoogleType": not sheet},
            "archive": archive, "notes": []}


def build_plan(a):
    pd = project_dir_of(a.project)
    man = load_manifest(pd)
    stamp, day = parse_now(a)
    snap = read_snapshot(pd)
    has_snapshot = snap is not None
    pulled_at = (read_text(os.path.join(pd, PULLED_AT)) or "").strip() or None
    warnings = []
    if not has_snapshot:
        warnings.append(f"no {SNAPSHOT}: every file counts as new. Right after a pull run "
                        f"`python3 tools/drive_sync.py snapshot {a.project}` (brand-new project: ignore this)")
        snap = {}
    elif not pulled_at:
        warnings.append(f"no {PULLED_AT}: cannot tell user edits on Drive from the pull (re-run snapshot after pulling)")
    if not folder_id(man, ARCHIVE):
        warnings.append(f"drive.folders has no ID for {ARCHIVE}: changed files cannot be archived")

    candidates, unmapped, skipped = [], [], 0
    for rel in walk(pd):
        folder = map_project(rel)
        if folder is None:
            unmapped.append({"local": key_for(pd, os.path.join(pd, rel)),
                             "reason": "no CONVENTIONS §11.3 mapping (move it under a mapped folder)"})
        else:
            candidates.append((rel, os.path.join(pd, rel), folder, "project"))
    if a.include_out:
        for rel, full in out_files(a.include_out):
            folder, why = map_out(rel, pd, man, day)
            if folder:
                candidates.append((rel, full, folder, "media"))
            elif why == "skip":
                skipped += 1
            else:
                unmapped.append({"local": key_for(pd, full), "reason": why})

    actions, sheet, counts = [], None, {"new": 0, "changed": 0, "unchanged": 0}
    for rel, full, folder, origin in candidates:
        key, h = key_for(pd, full), sha256(full)
        old = snap.get(key)
        if old == h:
            counts["unchanged"] += 1
            continue
        status = "changed" if old is not None else "new"
        if origin == "project" and rel == SHEET_LOCAL:
            sheet = entry(man, key, full, folder, h, status, stamp, sheet=True)
            sheet["notes"].append("not a text push (§11.6 step 5): edit the episode row in the Sheet in place if a "
                                  "Sheets tool is available; otherwise upload WITH conversion (create_file and archive lines), "
                                  f"then set drive.files.{SHEET_KEY} to the new ID and push PROJECT.md")
            continue
        if origin == "project" and rel.startswith("sources/") and rel != CATALOG and status == "changed":
            warnings.append(f"{key}: files in 01_TaiLieuGoc are never edited (§11.4, only DanhMuc.csv is) – "
                            "not planned; restore it or add a new file")
            continue
        x = entry(man, key, full, folder, h, status, stamp)
        if origin == "media":
            x["notes"].append("media: push only after the user approved it (§9)")
        counts[status] += 1
        actions.append(x)
    # PROJECT.md last: folder IDs added while pushing go up with it.
    actions.sort(key=lambda x: (x["local"].endswith("/PROJECT.md") and x["local"].count("/") == 2, x["local"]))

    present = {key_for(pd, c[1]) for c in candidates}
    project_prefix = key_for(pd, pd) + "/"
    deleted = [k for k in sorted(snap) if k not in present and not ignored(k)
               and (a.include_out or k.startswith(project_prefix))
               and not os.path.exists(os.path.join(lab_root(pd), k))]

    to_create, seen = [], set()
    for x in actions + ([sheet] if sheet else []):
        for c in x["folder"]["missing"]:
            if c["path"] not in seen:
                seen.add(c["path"])
                to_create.append(c)
    to_create.sort(key=lambda c: (c["path"].count("/"), c["path"]))
    if any(c["parent_path"] == "(project root)" and not c["parent_id"] for c in to_create):
        warnings.append("drive.root has no ID in PROJECT.md: top-level folders cannot be created")
    return {
        "project": man["project"], "project_dir": pd, "drive_name": man["name"], "drive_root": man["root"],
        "archive_time_utc": stamp, "date_folder": day,
        "snapshot": {"path": os.path.join(pd, SNAPSHOT), "exists": has_snapshot, "entries": len(snap)},
        "pulled_at": pulled_at, "pushed_ids": pushed_ids(pd),
        "create_folders": to_create, "actions": actions, "sheet": sheet, "deleted": deleted,
        "unmapped": unmapped, "skipped_media": skipped, "warnings": warnings,
        "counts": dict(counts, unmapped=len(unmapped), deleted=len(deleted), folders_to_create=len(to_create)),
    }


def print_entry(x, label, project_arg, rel):
    f, c, ar = x["folder"], x["create_file"], x["archive"]
    print(f"\n{label} {x['status'].upper():<7} {x['local']}")
    if f["id"]:
        print(f"  folder       {f['path']} = {f['id']}")
    else:
        first = f["missing"][0]
        print(f"  folder       {f['path']} = MISSING – create folder {first['path']} under "
              f"{first['parent_id'] or first['parent_path'] + ' (also missing)'} first")
    print(f"  create_file  title={c['title']}  parentId={c['parentId'] or '<missing>'}  "
          f"contentMimeType={c['contentMimeType']}  "
          f"disableConversionToGoogleType={str(c['disableConversionToGoogleType']).lower()}")
    print(f"               base64Content={c['base64Content']}")
    print(f"  record       python3 tools/drive_sync.py record {project_arg} --uploaded {rel(x['path'])} --id <new ID>")
    if ar:
        print(f"  archive      search_files {ar['search_files']}")
        print(f"               update_file each result except the new ID: parentId={ar['parentId'] or '<99_LuuTru ID missing>'}"
              f"  title={ar['title']}")
        if ar.get("drive_files_id"):
            print(f"               (drive.files.{SHEET_KEY} = {ar['drive_files_id']})")
    for note in x["notes"]:
        print(f"  note         {note}")


def print_plan(plan, project_arg):
    rel = lambda p: os.path.relpath(p)
    print(f"Plan  {rel(plan['project_dir'])} -> ClaudeFilmLab/{plan['drive_name']} (root {plan['drive_root']})")
    print(f"      snapshot {plan['snapshot']['entries']} file(s) · pulled at {plan['pulled_at'] or '?'} · "
          f"{len(plan['pushed_ids'])} upload(s) in .pushed.log · archive time {plan['archive_time_utc']} UTC")
    for w in plan["warnings"]:
        print(f"WARN  {w}")
    if plan["create_folders"]:
        print(f"\nFolders to create first (create_file title=<name> mimeType={FOLDER_MIME} parentId=<parent>):")
        for c in plan["create_folders"]:
            parent = c["parent_id"] or f"<ID of {c['parent_path']} once created>"
            print(f"  {c['path']:<46} parentId={parent}")
        print("  then add each new ID to drive.folders in PROJECT.md and run plan again.")
    if plan["actions"] and plan["pulled_at"]:
        print(f"\nBefore uploading a CHANGED file: its archive search_files result with modifiedTime after "
              f"{plan['pulled_at']} and an ID not in .pushed.log = user edit on Drive → download, merge first (§11.6 step 4).")
    n = len(plan["actions"])
    for i, x in enumerate(plan["actions"], 1):
        print_entry(x, f"[{i}/{n}]", project_arg, rel)
    if plan["sheet"]:
        print_entry(plan["sheet"], "[sheet]", project_arg, rel)
    for d in plan["deleted"]:
        print(f"\nDELETED locally (still on Drive): {d} – to retire it, move it to 99_LuuTru (§11.7)")
    for u in plan["unmapped"]:
        print(f"UNMAPPED {u['local']}: {u['reason']}")
    k = plan["counts"]
    print(f"\nSummary: {k['new']} new, {k['changed']} changed, {k['unchanged']} unchanged, "
          f"{k['folders_to_create']} folder(s) to create, {k['unmapped']} unmapped, {k['deleted']} deleted locally"
          + (", TienDo_SanXuat changed" if plan["sheet"] else "")
          + (f", {plan['skipped_media']} media file(s) not pushed (plates/clips go in bundles)" if plan["skipped_media"] else ""))
    if not plan["actions"] and not plan["sheet"]:
        print("Nothing to push.")


def cmd_plan(a):
    plan = build_plan(a)
    if a.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print_plan(plan, a.project)
    return 1 if plan["create_folders"] or plan["unmapped"] else 0


def cmd_record(a):
    pd = project_dir_of(a.project)
    if len(a.id) != len(a.uploaded):
        raise SyncError("give one --id per --uploaded, in the same order")
    snap = read_snapshot(pd) or {}
    lines = []
    for p, fid in zip(a.uploaded, a.id):
        full = p if os.path.isabs(p) or os.path.exists(p) else os.path.join(pd, p)
        if not os.path.isfile(full):
            raise SyncError(f"{p}: file not found")
        key = key_for(pd, full)
        if ignored(key):
            raise SyncError(f"{p}: dotfiles and __pycache__ are never pushed")
        if not fid.strip() or fid.strip().startswith("<"):
            raise SyncError(f"--id {fid!r}: give the ID create_file returned")
        snap[key] = sha256(full)
        lines.append(f"{utc_iso()} {key} {fid.strip()}\n")
    write_snapshot(pd, snap)
    with open(os.path.join(pd, PUSHED_LOG), "a", encoding="utf-8") as f:
        f.writelines(lines)
    for l in lines:
        print(f"recorded  {l.rstrip()}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="drive_sync.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot", help="after a pull: hash the working copy, write .pulled.at")
    s.add_argument("project")
    s.add_argument("--include-out", metavar="out/<project>", help="also hash the media folder (e.g. pulled ledger.csv)")
    s = sub.add_parser("plan", help="list create_file / update_file calls for new and changed files")
    s.add_argument("project")
    s.add_argument("--include-out", metavar="out/<project>", help="also plan ledger, bundles, renders, key images")
    s.add_argument("--json", action="store_true", help="emit the plan as JSON")
    s.add_argument("--now", metavar="YYYYMMDD-HHMM", help="UTC time for archive names (default: now)")
    s.add_argument("--date", metavar="YYYY-MM-DD", help="04_SanXuat/<date>/ folder for drafts (default: today UTC)")
    s = sub.add_parser("record", help="after a successful create_file: update the snapshot line, log the new ID")
    s.add_argument("project")
    s.add_argument("--uploaded", action="append", required=True, metavar="PATH")
    s.add_argument("--id", action="append", required=True, metavar="NEW_DRIVE_FILE_ID")
    a = p.parse_args(argv)
    try:
        return {"snapshot": cmd_snapshot, "plan": cmd_plan, "record": cmd_record}[a.cmd](a)
    except SyncError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
