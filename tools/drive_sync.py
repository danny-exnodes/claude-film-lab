#!/usr/bin/env python3
"""Plan Google Drive pushes for a project working copy (docs/CONVENTIONS.md §11). No network, no Drive calls.

The Drive connector has no CLI: Claude pulls and pushes one file at a time with MCP tools
(download_file_content, create_file, update_file). This helper remembers what was pulled, maps every local
path to its Drive folder ID from PROJECT.md and prints the exact connector calls for what changed.

  python3 tools/drive_sync.py save     projects/<project> --id <fileId> --to <path> [--size <fileSize>] [--from-file <blob>] [--id ...] [--transcript GLOB] [--force]
  python3 tools/drive_sync.py snapshot projects/<project> [--include-out out/<project>] [--only <path>...] [--force]
  python3 tools/drive_sync.py pulled   projects/<project> <path>...
  python3 tools/drive_sync.py plan     projects/<project> [--include-out out/<project>] [--json] [--now YYYYMMDD-HHMM] [--date YYYY-MM-DD]
  python3 tools/drive_sync.py record   projects/<project> --uploaded <path> --id <newDriveFileId> [--sha256 <hex>] [--uploaded ... --id ...]

save      right after each download_file_content: write the file the connector returned (base64, into the
          conversation) to disk without retyping it. The newest result for that file ID is read from the session
          transcripts (JSONL under ~/.claude/projects/ or $CLAUDE_CONFIG_DIR/projects/: this repo's folder first, with
          its subagents/, then every project; --transcript GLOB to name them), decoded (standard or url-safe base64),
          checked against --size (Drive fileSize), written atomically, then marked pulled like `pulled` does.
          Local sessions: the connector may instead save the file itself and answer `Binary content (<mime>, <n>KB)
          saved to <file>` (tool-results/mcp-...-blob-*.<ext>, raw bytes); that line is found the same way and the
          saved file is copied (it must lie in the Claude transcript store). --from-file <blob> after an --id copies
          that file directly, without searching transcripts; it needs --size (nothing ties the file to the ID).
          Several --id/--to[/--size] groups per call; all are checked before anything is written. Refused (exit 1,
          nothing written): overwriting a file with local changes not pushed yet, unless --force. Paths must stay in
          projects/<project>/ or out/<project>/ (symlinks resolved). The file content is never printed.
snapshot  right after the first pull of a container: hash the working copy into projects/<project>/.pulled.sha256
          and write the pull time to projects/<project>/.pulled.at (§11.6 pull step 4). When a snapshot already
          exists and files differ from it (local edits not pushed yet), nothing is written and the exit code is 1:
          push them, or use `pulled` for the files just pulled; --force rewrites everything anyway. Without
          --include-out the out/<project>/ lines of the old snapshot are kept. --only <path>...: the first snapshot
          lists just these files (files made locally before the first snapshot stay NEW); refused when a snapshot
          exists (use `pulled`), --force rewrites it with only these files.
pulled    after pulling more files into a working copy that already has a snapshot: set only those files' lines
          to their current hashes. No .pushed.log line, .pulled.at untouched.
plan      list new/changed files: target folder (logical path + ID, or MISSING + which folder to create under which
          parent first), Drive title, mime type, the create_file file reference `sha256:<hex>:<absolute path>` and,
          the search_files query that finds the old version(s) and their archive name in 99_LuuTru/ (§11.6 push
          step 3): for changed files always; for new files too, because Drive may already hold a file with that
          title in the folder (first push after a manual upload, lost snapshot) – archive it if the search finds one. TienDo_SanXuat.csv is listed apart (§11.6 step 5). --json: same plan as JSON.
          A ledger.csv gets a `pre` block before its create_file line: download every Drive copy, ledger-merge,
          plan again, then upload (§11.6 push step 3); it has no approval gate. When ledger.drive-<n>.csv copies are
          on disk and every row of them is already in the ledger, the block says `pre done` (delete the copies).
record    after each successful create_file: replace just that file's line in .pulled.sha256 and append
          `<UTC> <path> <new Drive ID>` to projects/<project>/.pushed.log (§11.6 push steps 2 and 6).
          --sha256 (as the plan prints it) is the hash that was uploaded: when the file was edited after the
          upload, that hash is stored, so the file stays CHANGED.

State files in projects/<project>/ (dotfiles: never pushed, never snapshotted), changed only under an exclusive
lock on projects/<project>/.drive_sync.lock and replaced atomically, so parallel `record` calls are safe:
  .pulled.sha256  `sha256sum` format `<hex>  <path>`; paths as `find projects/<project>` prints them from the repo
                  root (projects/<project>/..., media from --include-out as out/<project>/...), so the shell commands
                  of §11.6 and `sha256sum -c` (from the repo root) still work on it.
  .pulled.at      pull time, UTC ISO (2026-11-10T15:30:00Z).
  .pushed.log     one line per upload this session: `<UTC ISO> <path> <new Drive ID>`.

Ignored everywhere: dotfiles and dot-directories, __pycache__. Never planned or snapshotted: temp files
(*.b64, *.orig, *.bak, *.tmp, *.part, *~, *.lock, *.swp; the plan lists them once) and ledger.drive-*.csv (Drive copies to merge).
Ignored everywhere too: files whose real path (symlinks resolved) leaves projects/<project>/ and out/<project>/;
plan lists them as UNMAPPED, pulled/record/save refuse them.
Exit: 0 ok, 1 plan has blockers (folders to create, unmapped files), snapshot or save refused, 2 cannot plan,
record or save (no PROJECT.md, bad manifest, a path outside the project, no download in the transcripts...).
"""
import argparse, base64, binascii, contextlib, csv, datetime, fnmatch, glob, hashlib, io, json, mimetypes, os, re
import sys, zipfile

try:
    import fcntl
except ImportError:          # no flock on this platform: state files are still replaced atomically
    fcntl = None

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import episode_id  # noqa: E402  ep<NN> | q<NN>t<NN> (docs/CONVENTIONS.md §2)

SNAPSHOT, PULLED_AT, PUSHED_LOG = ".pulled.sha256", ".pulled.at", ".pushed.log"
LOCK = ".drive_sync.lock"
TEMP_PATTERNS = ("*.b64", "*.orig", "*.bak", "*.tmp", "*.part", "*~", "*.lock", "*.swp")     # pull / editor / bundle leftovers
LEDGER, LEDGER_COPIES = "ledger.csv", "ledger.drive-*.csv"                # copies: downloaded for ledger-merge
RE_SHOT_TAG = re.compile(r"_s\d{2,3}_")                                     # as tools/bundle.py picks shot media
SNIPPETS_OFF = "  excludeContentSnippets=true"       # search_files returns long content snippets by default
NOTE_MEDIA = "media: push only after the user approved it (§9)"
NOTE_LEDGER = "ledger: push after every stage that generated; no approval gate"
ARCHIVE = "99_LuuTru"
IF_EXISTS = "if a file with this title already exists in the folder (first push), archive it"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHEET_LOCAL = "TienDo_SanXuat.csv"            # Google Sheet 00_QuanLy/TienDo_SanXuat (§11.6 step 5)
SHEET_KEY = "00_QuanLy/TienDo_SanXuat"
PRON_LOCAL = "pronunciation.csv"              # Hán Việt map for tools/tts/vieneu_tts.py --pron, next to SERIES.md
CATALOG = "sources/DanhMuc.csv"               # the one editable file of 01_TaiLieuGoc (§11.3)
MIME = {
    ".md": "text/markdown", ".csv": "text/csv", ".json": "application/json", ".yaml": "text/plain",
    ".yml": "text/plain", ".txt": "text/plain", ".zip": "application/zip", ".mp4": "video/mp4",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".pdf": "application/pdf", ".wav": "audio/wav", ".mp3": "audio/mpeg", ".html": "text/html",
}
RE_EP_DIR = episode_id.RE_DIR          # ep<NN>-<slug> | q<NN>-t<NN>-<slug>
RE_MEDIA_EP = episode_id.RE_ID         # ep<NN> | q<NN>t<NN>
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


def is_temp(path):
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatchcase(name, pat) for pat in TEMP_PATTERNS)


def is_ledger_copy(path):
    return fnmatch.fnmatchcase(path.rsplit("/", 1)[-1], LEDGER_COPIES)


def lab_root(project_dir):
    """The directory `find projects/<project>` runs from: two levels above the project working copy."""
    return os.path.dirname(os.path.dirname(project_dir))


def key_for(project_dir, path):
    """Snapshot key: path relative to the repo root (projects/<project>/..., out/<project>/...), POSIX."""
    return os.path.relpath(os.path.abspath(path), lab_root(project_dir)).replace(os.sep, "/")


def out_prefix(project_dir):
    """Snapshot key prefix of the media folder out/<project>/."""
    return f"out/{os.path.basename(project_dir)}/"


def real_roots(project_dir, out_arg=None):
    """Real paths (symlinks resolved) a file of this project may live in: projects/<p>/ and out/<p>/."""
    roots = {os.path.realpath(project_dir),
             os.path.realpath(os.path.join(lab_root(project_dir), "out", os.path.basename(project_dir)))}
    if out_arg:
        roots.add(os.path.realpath(out_arg))
    return roots


def escapes(path, roots):
    """True when path, symlinks resolved, is outside every root (a link to /etc/..., another project...)."""
    rp = os.path.realpath(path)
    return not any(rp == r or rp.startswith(r.rstrip(os.sep) + os.sep) for r in roots)


ESCAPE_REASON = "symlink to a file outside the project (never pushed): replace it with a real file or remove it"


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
            p = m.group(2).replace("\\", "/")
            p = key_for(project_dir, p) if os.path.isabs(p) else os.path.normpath(p).replace(os.sep, "/")
            snap[p] = m.group(1).lower()
    return snap


def write_atomic(path, text):
    """Replace path with text: temp dotfile in the same folder, fsync, os.replace (never a truncated file)."""
    tmp = os.path.join(os.path.dirname(path), f"{os.path.basename(path)}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return path


def write_snapshot(project_dir, snap):
    return write_atomic(os.path.join(project_dir, SNAPSHOT), "".join(f"{snap[k]}  {k}\n" for k in sorted(snap)))


class State:
    """What locked_state yields: the snapshot as it is on disk now, plus what to write when the block ends."""

    def __init__(self, snap):
        self.existed = snap is not None
        self.snap = snap or {}       # edit in place; written back when the block ends
        self.save = True             # set False to leave .pulled.sha256 untouched
        self.pulled_at = None        # set to a UTC ISO string to rewrite .pulled.at
        self.log = []                # lines to append to .pushed.log


@contextlib.contextmanager
def locked_state(project_dir, fresh=False):
    """Exclusive lock on <project dir>/.drive_sync.lock around a read-modify-write of the state files.

    The snapshot is re-read inside the lock, so parallel `record` calls each see the lines the others wrote.
    fresh=True starts from an empty snapshot without reading the old one (snapshot --force, also over a damaged
    file). Nothing is written when the block raises."""
    with open(os.path.join(project_dir, LOCK), "a") as lock:
        if fcntl:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            st = State(None if fresh else read_snapshot(project_dir))
            yield st
            if st.save:
                write_snapshot(project_dir, st.snap)
            if st.pulled_at:
                write_atomic(os.path.join(project_dir, PULLED_AT), st.pulled_at + "\n")
            if st.log:
                with open(os.path.join(project_dir, PUSHED_LOG), "a", encoding="utf-8") as f:
                    f.writelines(st.log)
                    f.flush()
                    os.fsync(f.fileno())
        finally:
            if fcntl:
                fcntl.flock(lock, fcntl.LOCK_UN)


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
        return {"PROJECT.md": "00_QuanLy", SHEET_LOCAL: "00_QuanLy", "SERIES.md": "02_KinhThu",
                PRON_LOCAL: "02_KinhThu"}.get(name)
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


def episode_dirs(project_dir, man, eid):
    """Episode folder names (ep<NN>-<slug> or q<NN>-t<NN>-<slug>) known for episode id `eid` (ep01, q01t01):
    working copy folders first, then manifest keys."""
    same = lambda d: (episode_id.parse_dir(d) or ("",))[0] == eid
    names = sorted(d for d in os.listdir(project_dir)
                   if os.path.isdir(os.path.join(project_dir, d)) and same(d))
    if not names:
        names = sorted({k.split("/")[1] for k in man["folders"]
                        if k.count("/") >= 1 and k.split("/")[0] in ("03_KichBan", "04_SanXuat", "05_ThanhPham")
                        and same(k.split("/")[1])})
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
    eps = episode_dirs(project_dir, man, head)
    if len(eps) != 1:
        why = "no" if not eps else "several"
        return None, (f"{why} episode folder {episode_id.dir_prefix(head)}-<slug> in the working copy or drive.folders: "
                      "cannot tell the Drive episode folder")
    ep = eps[0]
    if kind == "ledger":
        return f"04_SanXuat/{ep}", None
    if kind == "final":
        return f"05_ThanhPham/{ep}", None
    d = RE_BUNDLE_DATE.search(name) if kind == "bundle" else None
    return f"04_SanXuat/{ep}/" + (f"{d.group(1)}-{d.group(2)}-{d.group(3)}" if d else day), None


# --- ledger copies (§11.6 push step 3) --------------------------------------------------------------------------

def ledger_adds_nothing(mine_path, copy_path):
    """True when ark.py ledger-merge of the local ledger with a downloaded copy would give back the local ledger:
    every billed row of the copy is already counted. Uses ark's own merge (multiset rows without req=, the row with
    more billing units per request), so `plan` never calls a copy merged that ledger-merge would still add to.
    False when either file cannot be read or fails ark's row checks (counted as not merged)."""
    import ark                                   # tools/ark.py; imported here, only plans with ledger copies need it
    rows = []
    for path in (mine_path, copy_path):
        try:
            with open(path, newline="", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            return False
        got, problems = ark.read_ledger_strict(path, text)
        if problems:
            return False
        rows.append(got)
    return ark.merge_rows([rows[0], rows[1]]) == ark.merge_rows([rows[0]])


# --- archive naming (§11.6 step 3) ----------------------------------------------------------------------------

def archive_name(folder, title, stamp):
    """<folder path, '/' -> '__'>__<name without extension>_<YYYYMMDD-HHMM>.<ext>"""
    stem, ext = os.path.splitext(title)
    return f"{folder.replace('/', '__')}__{stem}_{stamp}{ext}"


def search_query(fid, folder, title):
    title = title.replace("\\", "\\\\").replace("'", "\\'")      # Drive query syntax: escape \ and ' in values
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


def state_key(pd, arg):
    """(snapshot key, absolute path) for a file argument of `pulled` / `record`; SyncError when it is not a
    pushable file of this project (projects/<project>/... or out/<project>/...)."""
    p = arg.replace("\\", "/")
    full = p if os.path.isabs(p) or os.path.exists(p) else os.path.join(pd, p)
    if not os.path.isfile(full):
        raise SyncError(f"{arg}: file not found")
    key = key_for(pd, full)
    own = (key_for(pd, pd) + "/", f"out/{os.path.basename(pd)}/")
    if not key.startswith(own):
        raise SyncError(f"{arg}: not a file of this project (expected a path under {own[0]} or {own[1]})")
    if ignored(key):
        raise SyncError(f"{arg}: dotfiles and __pycache__ are never pushed")
    if escapes(full, real_roots(pd)):
        raise SyncError(f"{arg}: resolves to {os.path.realpath(full)}, outside {own[0]} and {own[1]} (symlink?)")
    return key, os.path.abspath(full)


def only_files(pd, args):
    """(key, abs path) of the files named by `snapshot --only`: files, or folders (every file under them)."""
    found = []
    for arg in args:
        p = arg.replace("\\", "/")
        full = p if os.path.isabs(p) or os.path.exists(p) else os.path.join(pd, p)
        if os.path.isdir(full):
            found += [state_key(pd, os.path.join(full, r)) for r in walk(full)]
        else:
            found.append(state_key(pd, arg))
    return found


def cmd_snapshot_only(a, pd):
    if a.include_out:
        raise SyncError("--only names the files itself: drop --include-out (paths under out/<project>/ are accepted)")
    files = [(k, full) for k, full in only_files(pd, a.only) if not (is_temp(k) or is_ledger_copy(k))]
    snap = {k: sha256(full) for k, full in files}
    at = utc_iso()
    with locked_state(pd, fresh=a.force) as st:
        refused = st.existed          # never with --force: fresh starts from an empty snapshot
        if refused:
            st.save = False
        else:
            st.snap.update(snap)
            st.pulled_at = at
    if refused:
        print(f"a snapshot exists already: add the files just pulled with `drive_sync.py pulled {a.project} <path>...` "
              "(nothing was written; snapshot --only --force rewrites it with only these files)", file=sys.stderr)
        return 1
    for k in sorted(snap):
        print(f"only      {k}")
    print(f"snapshot  {os.path.relpath(os.path.join(pd, SNAPSHOT))}: {len(snap)} file(s) (--only; every other file "
          f"stays NEW) · pulled at {at}")
    return 0


def cmd_snapshot(a):
    pd = project_dir_of(a.project)
    if a.only:
        return cmd_snapshot_only(a, pd)
    roots = real_roots(pd, a.include_out)
    files = [os.path.join(pd, r) for r in walk(pd)]
    n_project = len(files)
    if a.include_out:
        files += [full for _, full in out_files(a.include_out)]
    snap, n_kept, escaped = {}, 0, []
    for i, full in enumerate(files):
        key = key_for(pd, full)
        if is_temp(key) or is_ledger_copy(key):
            continue                 # never pushed: not part of what was pulled
        if escapes(full, roots):
            escaped.append(key)      # a symlink out of the project: not ours to hash or push
            continue
        snap[key] = sha256(full)
        n_kept += i < n_project
    at = utc_iso()
    kept_out = 0
    with locked_state(pd, fresh=a.force) as st:
        # An existing snapshot is the record of what is on Drive: a file that differs from its line (or has none)
        # is work not pushed yet, and rewriting the snapshot would make `plan` report it as already pushed.
        pending = sorted(k for k, h in snap.items() if st.snap.get(k) != h) if st.existed else []
        if pending:
            st.save = False
        else:
            old = st.snap
            if a.force and not a.include_out:
                try:                 # --force starts empty (the file may be damaged): out/ lines only if readable
                    old = read_snapshot(pd) or {}
                except SyncError:
                    old = {}
            # out/ was not hashed this time: keep its lines, so the ledger stays unchanged/CHANGED (not NEW) and
            # the next `snapshot --include-out` does not list every media file as a local change.
            keep = {} if a.include_out else {k: h for k, h in old.items() if k.startswith(out_prefix(pd))}
            kept_out = len(keep)
            st.snap.clear()
            st.snap.update(keep)
            st.snap.update(snap)
            st.pulled_at = at
    for k in escaped:
        print(f"WARN {k}: {ESCAPE_REASON}", file=sys.stderr)
    if pending:
        for k in pending[:20]:
            print(f"  {k}", file=sys.stderr)
        if len(pending) > 20:
            print(f"  ... and {len(pending) - 20} more", file=sys.stderr)
        print(f"{len(pending)} local change(s) not yet pushed would be marked as pulled: push them, or record just "
              f"the pulled files with: drive_sync.py pulled {a.project} <path>...\n"
              f"(a file pulled after the snapshot is listed too until `pulled` is run for it; nothing was written; "
              f"snapshot --force rewrites every line)", file=sys.stderr)
        return 1
    print(f"snapshot  {os.path.relpath(os.path.join(pd, SNAPSHOT))}: {n_kept} file(s)"
          + (f" + {len(snap) - n_kept} media" if a.include_out else "")
          + (f" + {kept_out} out/ line(s) kept (no --include-out)" if kept_out else "") + f" · pulled at {at}")
    return 0


def cmd_pulled(a):
    pd = project_dir_of(a.project)
    files = [state_key(pd, p) for p in a.paths]
    hashes = [(key, sha256(full)) for key, full in files]
    with locked_state(pd) as st:
        if not st.existed:
            raise SyncError(f"no {SNAPSHOT} yet: after the first pull of a container run "
                            f"`python3 tools/drive_sync.py snapshot {a.project} --include-out out/<project>`")
        st.snap.update(hashes)
    for key, h in hashes:
        print(f"pulled    {key} {h[:12]}")
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
    """One planned upload: folder, create_file arguments, archive step (after the upload).

    Changed files always have an old version on Drive. New files may too (first push after a manual upload, or a
    lost snapshot), so they get the same search, labelled conditional: archive only what the search finds."""
    title = "TienDo_SanXuat" if sheet else os.path.basename(key)
    fid = folder_id(man, folder)
    archive = {"search_files": search_query(fid, folder, title), "excludeContentSnippets": True,
               "move": "every result except the new ID", "parentId": folder_id(man, ARCHIVE),
               "title": archive_name(folder, title, stamp),
               "when": "always" if status == "changed" else "if_exists"}
    if archive["when"] == "if_exists":
        archive["condition"] = IF_EXISTS
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
        warnings.append(f"drive.folders has no ID for {ARCHIVE}: old versions cannot be archived")

    candidates, unmapped, skipped = [], [], 0
    ignored_temp = []                    # pull/editor leftovers: listed once, never planned, never UNMAPPED
    shot_media, bundled = [], {}         # (media folder, path inside it) of plates/clips; bundle members per folder
    roots = real_roots(pd, a.include_out)
    for rel in walk(pd):
        if is_ledger_copy(rel):
            continue
        if is_temp(rel):
            ignored_temp.append(key_for(pd, os.path.join(pd, rel)))
            continue
        if escapes(os.path.join(pd, rel), roots):
            unmapped.append({"local": key_for(pd, os.path.join(pd, rel)), "reason": ESCAPE_REASON})
            continue
        folder = map_project(rel)
        if folder is None:
            unmapped.append({"local": key_for(pd, os.path.join(pd, rel)),
                             "reason": "no CONVENTIONS §11.3 mapping (move it under a mapped folder)"})
        else:
            candidates.append((rel, os.path.join(pd, rel), folder, "project"))
    if a.include_out:
        for rel, full in out_files(a.include_out):
            if is_ledger_copy(rel):
                continue
            if is_temp(rel):
                ignored_temp.append(key_for(pd, full))
                continue
            if escapes(full, roots):
                unmapped.append({"local": key_for(pd, full), "reason": ESCAPE_REASON})
                continue
            media, _, inside = rel.partition("/")        # out/<project>/<media folder>/<inside>
            if inside.startswith(("plates/", "clips/")) and RE_SHOT_TAG.search(os.path.basename(inside)):
                shot_media.append((media, inside))
            elif inside.startswith("bundles/") and inside.endswith(".zip"):
                try:
                    with zipfile.ZipFile(full) as z:
                        bundled.setdefault(media, set()).update(z.namelist())
                except (zipfile.BadZipFile, OSError):
                    pass                                 # unreadable bundle: its media count as not bundled
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
        if origin == "media" and rel.count("/") == 1 and os.path.basename(rel) == LEDGER:
            # The ledger of a media folder: other sessions may have pushed rows this copy lacks (§11.6 step 3).
            x["notes"].append(NOTE_LEDGER)
            x["pre"] = {"ledger_merge": {"into": key,        # paths from the repo root, like "local"
                                         "copies_glob": f"{os.path.dirname(key)}/{LEDGER_COPIES}",
                                         "search_files": x["archive"]["search_files"],
                                         "excludeContentSnippets": True}}
            copies = sorted(glob.glob(os.path.join(glob.escape(os.path.dirname(full)), LEDGER_COPIES)))
            if copies:               # downloaded already: done once every copy's rows are in the ledger
                unmerged = [key_for(pd, c) for c in copies if not ledger_adds_nothing(full, c)]
                x["pre"]["ledger_merge"].update(copies=[key_for(pd, c) for c in copies], unmerged=unmerged,
                                                done=not unmerged)
        elif origin == "media":
            x["notes"].append(NOTE_MEDIA)
        counts[status] += 1
        actions.append(x)
    # PROJECT.md last: folder IDs added while pushing go up with it.
    actions.sort(key=lambda x: (x["local"].endswith("/PROJECT.md") and x["local"].count("/") == 2, x["local"]))

    present = {key_for(pd, c[1]) for c in candidates}
    project_prefix = key_for(pd, pd) + "/"
    deleted = [k for k in sorted(snap) if k not in present and not ignored(k)
               and not is_temp(k) and not is_ledger_copy(k)
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
        "ignored_temp": sorted(ignored_temp),
        "unbundled_media": sum(1 for media, inside in shot_media if inside not in bundled.get(media, ())),
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
    merge = (x.get("pre") or {}).get("ledger_merge")
    if merge and merge.get("done"):
        names = ", ".join(os.path.basename(c) for c in merge["copies"])
        print(f"  pre          done: every Drive copy ({names}) is merged into this ledger; delete the copies, then upload")
    elif merge:
        local, copies = rel(x["path"]), os.path.join(os.path.dirname(rel(x["path"])), LEDGER_COPIES)
        print("  pre          merge the Drive copies into this ledger BEFORE uploading (§11.6 push step 3):")
        print(f"               1) search_files {merge['search_files']}{SNIPPETS_OFF}")
        print(f"               2) download EVERY result to {copies.replace('*', '<n>')} (no result: skip to the upload)")
        print(f"               3) python3 tools/ark.py ledger-merge {local} {copies} -o {local}")
        print("               4) run plan again (the hash changes): this block says `pre done` once every copy is "
              "merged; then upload")
        if merge.get("unmerged"):
            print(f"               not merged yet: {', '.join(merge['unmerged'])}")
    print(f"  create_file  title={c['title']}  parentId={c['parentId'] or '<missing>'}  "
          f"contentMimeType={c['contentMimeType']}  "
          f"disableConversionToGoogleType={str(c['disableConversionToGoogleType']).lower()}")
    print(f"               base64Content={c['base64Content']}")
    print(f"  record       python3 tools/drive_sync.py record {project_arg} --uploaded {rel(x['path'])} --id <new ID> "
          f"--sha256 {x['sha256']}")
    if ar:
        if ar.get("condition"):
            print(f"  archive      {ar['condition']}:")
            print(f"               search_files {ar['search_files']}{SNIPPETS_OFF}")
        else:
            print(f"  archive      search_files {ar['search_files']}{SNIPPETS_OFF}")
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
    if plan["ignored_temp"]:
        print(f"\nignored temp files ({len(plan['ignored_temp'])}, never pushed; delete them when done): "
              + ", ".join(plan["ignored_temp"]))
    planned = plan["actions"] + ([plan["sheet"]] if plan["sheet"] else [])
    if any(x["status"] == "changed" for x in planned) and plan["pulled_at"]:
        print(f"\nBefore uploading a CHANGED file: its archive search_files result with modifiedTime after "
              f"{plan['pulled_at']} and an ID not in .pushed.log = user edit on Drive → download, merge first (§11.6 step 4).")
    if any(x["status"] == "new" for x in planned):
        print("Before uploading a NEW file: run its archive search_files too; a result whose ID is not in .pushed.log "
              "is a copy never pulled (manual upload, lost snapshot) → download, compare, merge first (§11.6 step 4).")
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
        if plan["unbundled_media"]:
            print(f"Nothing to push (text). {plan['unbundled_media']} plate/clip file(s) are in no bundle: they exist "
                  "only in this container (lost when it is reclaimed; bundle approved shots with tools/bundle.py)")
        else:
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
    shas = a.sha256 or []
    if shas and len(shas) != len(a.uploaded):
        raise SyncError("give one --sha256 per --uploaded, in the same order (or none at all)")
    for h in shas:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", h):
            raise SyncError(f"--sha256 {h!r}: expected the 64 hex digits the plan printed")
    updates, lines, warns = {}, [], []
    for i, (p, fid) in enumerate(zip(a.uploaded, a.id)):
        key, full = state_key(pd, p)
        if not fid.strip() or fid.strip().startswith("<"):
            raise SyncError(f"--id {fid!r}: give the ID create_file returned")
        updates[key] = sha256(full)
        if shas and shas[i].lower() != updates[key]:
            # Edited after create_file read it: Drive holds the planned bytes, so the file must stay CHANGED.
            updates[key] = shas[i].lower()
            warns.append(f"WARN {key} changed after the upload: still to push")
        lines.append(f"{utc_iso()} {key} {fid.strip()}\n")
    with locked_state(pd) as st:
        st.snap.update(updates)
        st.log = lines
    for l in lines:
        print(f"recorded  {l.rstrip()}")
    for w in warns:
        print(w)
    if not shas:
        print("note      recorded the file's hash as it is now; pass --sha256 <hex> as the plan prints it, so that "
              "an edit made after the upload stays to push")
    return 0


# --- save: a download_file_content result from the session transcript to disk (pull side) -----------------------

DOWNLOAD_TOOL = "download_file_content"
RE_PERSISTED = re.compile(r"Full output saved to: (\S+)")          # Claude Code keeps a large tool result in a file
RE_B64 = re.compile(r"^[A-Za-z0-9+/_-]*={0,2}$")
RE_CONTENT = re.compile(r'"content"\s*:\s*"([A-Za-z0-9+/=_\-\s]*)"')
SIZE_KEYS = ("fileSize", "size")
RE_SIZE = re.compile(r'"(fileSize|size)"\s*:\s*"?(\d+)')
# Local sessions: the connector writes the file itself (raw bytes) and the result only names it, e.g.
# "[Resource from claude.ai Google Drive at googledrive://file/<id>] Binary content (text/markdown, 8.9KB) saved to
# C:\\Users\\...\\tool-results\\mcp-claude_ai_Google_Drive-blob-<n>.md" (+ a JSON part, "content": "(file sent separately)").
RE_SAVED = re.compile(r"Binary content \(([^,()]*)(?:,\s*([^()]*))?\) saved to (.+?)\s*$", re.M)
RE_RESOURCE = re.compile(r"googledrive://file/([^\]\s]+)")


class Hit:
    """One download result found in a transcript (b64 = the base64 text; never printed)."""

    def __init__(self, source, line, ts, mtime, b64=None, error=None, meta=None, fallback=False, blob=None):
        self.source, self.line, self.ts, self.mtime = source, line, ts, mtime
        self.b64, self.error, self.meta, self.fallback = b64, error, meta or {}, fallback
        self.blob = blob             # file the connector saved the content to (raw bytes), instead of b64

    def order(self):
        return (self.ts if self.ts is not None else self.mtime, self.mtime, self.line)

    def where(self):
        if self.line is None:
            return f"--from-file {os.path.basename(self.source)}"
        return f"{os.path.basename(self.source)}:{self.line}" + (", saved file" if self.blob else "")


def claude_projects_dir():
    """Where Claude Code keeps session transcripts: $CLAUDE_CONFIG_DIR/projects or ~/.claude/projects."""
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(base, "projects")


def transcript_slug(path):
    """Claude Code's transcript folder name for a working directory: every non-alphanumeric character -> '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(path))


def transcripts_in(folder):
    """Session transcripts of one project folder: <folder>/*.jsonl and <folder>/<session>/subagents/*.jsonl."""
    g = glob.escape(folder)
    return glob.glob(os.path.join(g, "*.jsonl")) + glob.glob(os.path.join(g, "*", "subagents", "*.jsonl"))


def newest_first(paths):
    uniq = {os.path.abspath(p) for p in paths if os.path.isfile(p)}
    return sorted(uniq, key=lambda p: (-os.path.getmtime(p), p))


def transcript_tiers(pd, patterns):
    """[(label, [transcript, ...] newest first)] in search order: the --transcript globs only; else the transcript
    folder of this repo (cwd or the repo root of the project), then every other project folder."""
    if patterns:
        found = []
        for pat in patterns:
            hits = [h for h in glob.glob(os.path.expanduser(pat), recursive=True) if os.path.isfile(h)]
            if not hits:
                raise SyncError(f"--transcript {pat}: no file matches")
            found += hits
        return [("--transcript", newest_first(found))]
    root = claude_projects_dir()
    slugs = sorted({transcript_slug(os.getcwd()), transcript_slug(lab_root(pd))})
    own = newest_first(f for s in slugs for f in transcripts_in(os.path.join(root, s)))
    seen = set(own)
    rest = newest_first(f for d in glob.glob(os.path.join(glob.escape(root), "*")) for f in transcripts_in(d)
                        if os.path.abspath(f) not in seen)
    return [(f"{root}/{'|'.join(slugs)}", own), (f"{root}/*", rest)]


def iso_epoch(ts):
    if not isinstance(ts, str):
        return None
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def blocks_of(rec):
    """Content blocks (dicts with a type) of one transcript record: message.content, or content."""
    if not isinstance(rec, dict):
        return []
    msg = rec.get("message")
    content = msg.get("content") if isinstance(msg, dict) else rec.get("content")
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def strings_in(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from strings_in(x)
    elif isinstance(v, list):
        for x in v:
            yield from strings_in(x)


def content_dict(obj, fid):
    """The {"content": <base64>, ...} dict of a parsed download result: the one whose id is fid, else the only one."""
    found = []

    def walk_obj(v):
        if isinstance(v, dict):
            if isinstance(v.get("content"), str):
                found.append(v)
            for x in v.values():
                walk_obj(x)
        elif isinstance(v, list):
            for x in v:
                walk_obj(x)
    walk_obj(obj)
    mine = [d for d in found if d.get("id") == fid or d.get("fileId") == fid]
    return mine[0] if mine else (found[0] if len(found) == 1 else None)


def meta_of(d):
    return {k: d[k] for k in ("title", "mimeType", *SIZE_KEYS) if k in d and not isinstance(d[k], (dict, list))}


def store_roots(transcript):
    """Folders a file named by a tool result may be read from: the Claude transcript store, and the folder two
    levels above the transcript (the store of a --transcript file kept elsewhere)."""
    return {os.path.realpath(claude_projects_dir()), os.path.realpath(os.path.dirname(os.path.dirname(transcript)))}


def native_path(p):
    """A path as the connector printed it, openable by this Python: C:\\x\\y -> /mnt/c/x/y under WSL/Linux."""
    p = p.strip().strip('"')
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", p)
    if m and os.sep == "/":
        return f"/mnt/{m.group(1).lower()}/" + m.group(2).replace("\\", "/")
    return p


def persisted_text(path, transcript):
    """Text of a tool result Claude Code saved to a file (`Full output saved to: <path>`), when that file is in the
    transcript store (beside the transcript); None otherwise."""
    path = native_path(path)
    if escapes(path, store_roots(transcript)) or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def payload_of_text(text, fid, transcript, depth=0):
    """(base64, meta) from the text of a download_file_content result, or None."""
    s = text.strip()
    try:
        d = content_dict(json.loads(s), fid)
        if d is not None:
            return d["content"], meta_of(d)
    except ValueError:
        pass
    m = RE_PERSISTED.search(s)
    if m and depth == 0:
        inner = persisted_text(m.group(1), transcript)
        if inner is not None:
            return payload_of_text(inner, fid, transcript, depth + 1)
    m = RE_CONTENT.search(s)                         # text around the JSON, or JSON cut short
    if not m:
        return None
    size = RE_SIZE.search(s)
    return m.group(1), ({size.group(1): size.group(2)} if size else {})


def saved_hit(text, fid, transcript, n, ts, mtime, fallback=False):
    """Hit for a `Binary content (...) saved to <file>` result naming this file id (or no id), else None."""
    m = RE_SAVED.search(text)
    if not m:
        return None
    rid = RE_RESOURCE.search(text)
    if rid and rid.group(1) != fid:
        return None
    path = native_path(m.group(3))
    meta = {"mimeType": m.group(1).strip()}
    if escapes(path, store_roots(transcript)):
        return Hit(transcript, n, ts, mtime, meta=meta, fallback=fallback,
                   error=f"the connector saved it to {path}, outside the Claude transcript store "
                         "(copy it with --from-file <that file> --size <Drive fileSize> if you trust it)")
    if not os.path.isfile(path):
        return Hit(transcript, n, ts, mtime, meta=meta, fallback=fallback,
                   error=f"the file the connector saved ({path}) is gone")
    return Hit(transcript, n, ts, mtime, meta=meta, fallback=fallback, blob=path)


def result_hit(block, fid, transcript, n, ts, mtime):
    if block.get("is_error"):
        return Hit(transcript, n, ts, mtime, error="the download failed (is_error in the transcript)")
    content = block.get("content")
    texts = [content] if isinstance(content, str) else \
        [b.get("text") for b in content or [] if isinstance(b, dict) and isinstance(b.get("text"), str)]
    for text in texts:                               # local session: the connector saved the file itself
        got = saved_hit(text, fid, transcript, n, ts, mtime)
        if got:
            return got
    for text in texts + (["".join(texts)] if len(texts) > 1 else []):
        got = payload_of_text(text, fid, transcript)
        if got:
            return Hit(transcript, n, ts, mtime, b64=got[0], meta=got[1])
    return Hit(transcript, n, ts, mtime, error="the result has no base64 \"content\"")


def fallback_hit(rec, fid, transcript, n, ts, mtime):
    """No download_file_content call to pair with: a JSON object with this id and a content field anywhere."""
    pats = (re.compile(r'\{[^{}]*?"content"\s*:\s*"([A-Za-z0-9+/=_\-\s]*)"[^{}]*?"id"\s*:\s*"' + re.escape(fid) + '"'),
            re.compile(r'\{[^{}]*?"id"\s*:\s*"' + re.escape(fid) + r'"[^{}]*?"content"\s*:\s*"([A-Za-z0-9+/=_\-\s]*)"'))
    for s in strings_in(rec):
        if fid not in s:
            continue
        if RE_RESOURCE.search(s) and RE_SAVED.search(s):
            h = saved_hit(s, fid, transcript, n, ts, mtime, fallback=True)
            if h and not h.error:
                return h
            continue
        try:
            d = content_dict(json.loads(s), fid)
            if d is not None and (d.get("id") == fid or d.get("fileId") == fid):
                return Hit(transcript, n, ts, mtime, b64=d["content"], meta=meta_of(d), fallback=True)
        except ValueError:
            pass
        for pat in pats:
            m = pat.search(s)
            if m:
                return Hit(transcript, n, ts, mtime, b64=m.group(1), fallback=True)
    return None


RE_TOOL_USE = re.compile(r'"id"\s*:\s*"([^"]+)"\s*,\s*"name"\s*:\s*"([^"]+)"')


def scan_transcript(path, ids):
    """{file id: ([paired hits], [fallback hits])} found in one transcript (JSONL, one record per line)."""
    found = {i: ([], []) for i in ids}
    calls = {}                                       # tool_use id -> file id
    other = set()                                    # tool_use ids of other tools (search_files snippets...)
    mtime = os.path.getmtime(path)
    with open(path, encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, 1):
            if '"tool_use"' in line:
                other.update(u for u, name in RE_TOOL_USE.findall(line) if not name.endswith(DOWNLOAD_TOOL))
            named = [i for i in ids if i in line]
            answers = bool(calls) and "tool_result" in line and any(c in line for c in calls)
            if not named and not answers:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            ts = iso_epoch(rec.get("timestamp")) if isinstance(rec, dict) else None
            paired = set()
            for b in blocks_of(rec):
                if b.get("type") == "tool_use" and str(b.get("name", "")).endswith(DOWNLOAD_TOOL):
                    fid = next((v for v in strings_in(b.get("input")) if v in found), None)
                    if fid and isinstance(b.get("id"), str):
                        calls[b["id"]] = fid
                elif b.get("type") == "tool_result" and b.get("tool_use_id") in calls:
                    fid = calls[b["tool_use_id"]]
                    paired.add(fid)
                    found[fid][0].append(result_hit(b, fid, path, n, ts, mtime))
            if any(b.get("type") == "tool_use" or b.get("tool_use_id") in other for b in blocks_of(rec)):
                continue                             # a call, or the result of another tool: never a download
            for fid in named:
                if fid not in paired:
                    h = fallback_hit(rec, fid, path, n, ts, mtime)
                    if h:
                        found[fid][1].append(h)
    return found


def find_downloads(pd, ids, patterns):
    """{file id: newest Hit} for every id; SyncError naming the ids not found."""
    best, searched = {}, []
    todo = list(dict.fromkeys(ids))
    for label, files in transcript_tiers(pd, patterns):
        searched.append(f"{label} ({len(files)} transcript(s))")
        paired, loose = {i: [] for i in todo}, {i: [] for i in todo}
        open_ids = list(todo)
        for k, path in enumerate(files):
            for fid, (p, fb) in scan_transcript(path, open_ids).items():
                paired[fid] += p
                loose[fid] += fb
            nxt = os.path.getmtime(files[k + 1]) if k + 1 < len(files) else None
            # files are newest first: once a result is newer than the next file was last written, it is the newest
            open_ids = [i for i in open_ids if not (paired[i] and nxt is not None
                                                    and max(h.order() for h in paired[i])[0] >= nxt)]
            if not open_ids:
                break
        for fid in todo:
            hits = paired[fid] or loose[fid]
            if hits:
                best[fid] = max(hits, key=Hit.order)
        todo = [i for i in todo if i not in best]
        if not todo:
            break
    if todo:
        raise SyncError(f"no {DOWNLOAD_TOOL} result for file id(s) {', '.join(todo)} in "
                        + "; ".join(searched) + f": call {DOWNLOAD_TOOL} first (this session), or name the transcript "
                        "that holds it with --transcript GLOB (a subagent or another session)")
    return best


def decode_b64(text):
    """Bytes of standard or url-safe base64 (whitespace and missing padding tolerated); ValueError otherwise."""
    s = re.sub(r"\s+", "", text)
    if not RE_B64.match(s):
        raise ValueError("not base64 (unexpected characters)")
    if re.search(r"[-_]", s) and re.search(r"[+/]", s):
        raise ValueError("mixes standard and url-safe base64")
    s = s.rstrip("=")
    if len(s) % 4 == 1:
        raise ValueError("base64 cut short")
    s += "=" * (-len(s) % 4)
    try:
        return base64.b64decode(s.translate(str.maketrans("-_", "+/")), validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"not base64 ({e})")


def save_target(pd, arg):
    """(snapshot key, absolute path) for --to: relative to the project folder, or projects/<p>/... | out/<p>/...
    from the repo root, or absolute; SyncError when it leaves the project (symlinks resolved)."""
    p = arg.replace("\\", "/")
    if os.path.isabs(p):
        full = p
    elif p.startswith(("projects/", "out/")):
        full = os.path.join(lab_root(pd), p)
    else:
        full = os.path.join(pd, p)
    full = os.path.normpath(full)
    key = key_for(pd, full)
    own = (key_for(pd, pd) + "/", out_prefix(pd))
    if not key.startswith(own):
        raise SyncError(f"--to {arg}: not a path of this project (expected a path under {own[0]} or {own[1]})")
    if ignored(key):
        raise SyncError(f"--to {arg}: dotfiles and __pycache__ are never pulled")
    if escapes(full, real_roots(pd)):
        raise SyncError(f"--to {arg}: resolves to {os.path.realpath(full)}, outside {own[0]} and {own[1]} (symlink?)")
    if os.path.isdir(full):
        raise SyncError(f"--to {arg}: is a folder; give the file path")
    return key, full


def write_bytes_atomic(path, data):
    """Replace path with data: hidden temp file in the same folder (never planned), fsync, os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.{os.getpid()}.part")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


class SaveGroup(argparse.Action):
    """--id starts a file; the --to and --size after it belong to that file."""

    def __call__(self, parser, ns, value, opt):
        jobs = list(getattr(ns, "jobs", None) or [])
        if self.dest == "id":
            jobs.append({"id": value})
        elif not jobs:
            parser.error(f"{opt} must follow an --id")
        elif self.dest in jobs[-1]:
            parser.error(f"{opt} given twice for --id {jobs[-1]['id']}")
        else:
            jobs[-1][self.dest] = value
        ns.jobs = jobs


def cmd_save(a):
    jobs = a.jobs or []
    if not jobs:
        raise SyncError("give at least one --id <fileId> --to <path>")
    pd = os.path.abspath(a.project)
    if not os.path.isdir(pd) and os.path.basename(os.path.dirname(pd)) != "projects":
        raise SyncError(f"{a.project}: project working copy not found (expected projects/<project>)")
    targets = set()
    for j in jobs:
        if not str(j["id"]).strip() or str(j["id"]).startswith("<"):
            raise SyncError(f"--id {j['id']!r}: give the Drive file ID passed to {DOWNLOAD_TOOL}")
        if "to" not in j:
            raise SyncError(f"--id {j['id']}: give --to <path> after it")
        if j.get("from_file") is not None:
            if j.get("size") is None:
                raise SyncError(f"--id {j['id']}: --from-file needs --size <Drive fileSize> (nothing else ties the "
                                "file to this ID)")
            src = native_path(j["from_file"])
            if not os.path.isfile(src):
                raise SyncError(f"--from-file {j['from_file']}: file not found")
            j["from_file"] = src
        if j.get("size") is not None and j["size"] < 0:
            raise SyncError(f"--size {j['size']}: expected Drive's fileSize in bytes")
        j["key"], j["full"] = save_target(pd, j["to"])
        if j["key"] in targets:
            raise SyncError(f"--to {j['to']}: given twice")
        targets.add(j["key"])
    hits = {}
    wanted = [j["id"] for j in jobs if j.get("from_file") is None]
    if wanted:
        hits = find_downloads(pd, wanted, a.transcript)
    for j in jobs:
        if j.get("from_file") is not None:
            h = Hit(j["from_file"], None, None, os.path.getmtime(j["from_file"]), blob=j["from_file"])
        else:
            h = hits[j["id"]]
        if h.error:
            raise SyncError(f"--id {j['id']}: newest result ({h.where()}): {h.error}; download it again")
        if h.fallback and j.get("size") is None:
            raise SyncError(f"--id {j['id']}: found only by text search ({h.where()}, no {DOWNLOAD_TOOL} call to pair "
                            "it with): pass --size <Drive fileSize> to accept it")
        try:
            if h.blob:
                with open(h.blob, "rb") as f:
                    j["data"] = f.read()
            else:
                j["data"] = decode_b64(h.b64)
        except OSError as e:
            raise SyncError(f"--id {j['id']}: cannot read {h.blob}: {e.strerror}; download it again")
        except ValueError as e:
            hint = (" (the connector saved the file separately: pass the file it named with --from-file <file> "
                    "--size <Drive fileSize>)" if "sent separately" in (h.b64 or "") else "")
            raise SyncError(f"--id {j['id']}: result at {h.where()}: {e}{hint}; download it again")
        if j.get("size") is not None and len(j["data"]) != j["size"]:
            raise SyncError(f"--id {j['id']}: decoded {len(j['data'])} bytes, --size says {j['size']} "
                            f"({h.where()}): the result is cut short or another version; download it again")
        j["hit"], j["sha"] = h, hashlib.sha256(j["data"]).hexdigest()
    if not os.path.isdir(pd):
        os.makedirs(pd)                              # the very first pull of a container (PROJECT.md)
        print(f"created   {os.path.relpath(pd)}/")
    refused, notes = [], []
    with locked_state(pd) as st:
        st.save = st.existed                         # no snapshot yet: `snapshot` runs after the first pull
        for j in jobs:
            j["track"] = not (is_temp(j["key"]) or is_ledger_copy(j["key"]))
            if not (j["track"] and os.path.isfile(j["full"])) or a.force:
                continue
            cur = sha256(j["full"])
            if cur == j["sha"] or (st.existed and st.snap.get(j["key"]) == cur):
                continue                             # same bytes, or untouched since the last pull/push
            why = ("no snapshot yet: cannot tell a pulled file from local work" if not st.existed else
                   "not in the snapshot: made locally" if j["key"] not in st.snap else "local changes not pushed yet")
            refused.append(f"{j['key']}: {why}")
        if refused:
            st.save = False
        else:
            for j in jobs:
                write_bytes_atomic(j["full"], j["data"])
                if j["track"] and st.existed:
                    st.snap[j["key"]] = j["sha"]
    if refused:
        for r in refused:
            print(f"  {r}", file=sys.stderr)
        print(f"{len(refused)} file(s) would be overwritten: push them first (plan), or save the Drive copy beside "
              "them to compare (--to <path>.orig, never pushed); --force overwrites. Nothing was written.",
              file=sys.stderr)
        return 1
    for j in jobs:
        h = j["hit"]
        print(f"saved     {j['key']}  {len(j['data'])} bytes  sha256 {j['sha'][:12]}  <- {j['id']} ({h.where()}"
              + (", text search" if h.fallback else "") + ")")
        size_meta = next((h.meta[k] for k in SIZE_KEYS if k in h.meta), None)
        if j.get("size") is None and size_meta is not None and str(size_meta) != str(len(j["data"])):
            print(f"WARN      {j['key']}: the result says size {size_meta}, decoded {len(j['data'])} bytes: "
                  "compare with Drive's fileSize")
        if not j["track"]:
            notes.append(f"{j['key']}: temp file or Drive ledger copy, not marked pulled (never pushed)")
        elif st.existed:
            print(f"pulled    {j['key']} {j['sha'][:12]}")
    if not st.existed and any(j["track"] for j in jobs):
        notes.append(f"no {SNAPSHOT} yet: after the first pull run `python3 tools/drive_sync.py snapshot {a.project} "
                     "--include-out out/<project>` (files made locally before it: snapshot --only <pulled files>)")
    if any(j.get("size") is None for j in jobs):
        notes.append("no --size for some file(s): pass Drive's fileSize to catch a result cut short")
    for n in notes:
        print(f"note      {n}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="drive_sync.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("save", help="after download_file_content: write the file from the session transcript, mark it pulled")
    s.add_argument("project")
    s.add_argument("--id", action=SaveGroup, metavar="FILE_ID", help="Drive file ID given to download_file_content")
    s.add_argument("--to", action=SaveGroup, metavar="PATH",
                   help="where to write it: relative to the project folder, or projects/<p>/... | out/<p>/...")
    s.add_argument("--size", action=SaveGroup, type=int, metavar="BYTES", help="Drive fileSize: the decoded size must match")
    s.add_argument("--from-file", action=SaveGroup, metavar="BLOB",
                   help="the file the connector saved (`Binary content ... saved to <file>`): copy it, no transcript "
                        "search; needs --size")
    s.add_argument("--transcript", action="append", metavar="GLOB",
                   help="search only these session transcripts (*.jsonl; a subagent's or another session's)")
    s.add_argument("--force", action="store_true", help="overwrite files with local changes not pushed yet")
    s.set_defaults(jobs=None)
    s = sub.add_parser("snapshot", help="after a pull: hash the working copy, write .pulled.at")
    s.add_argument("project")
    s.add_argument("--include-out", metavar="out/<project>", help="also hash the media folder (e.g. pulled ledger.csv)")
    s.add_argument("--only", nargs="+", metavar="PATH",
                   help="first snapshot of just these files/folders (files made locally before it stay NEW)")
    s.add_argument("--force", action="store_true",
                   help="rewrite an existing snapshot even when local changes are not pushed yet (marks them as pulled)")
    s = sub.add_parser("pulled", help="after pulling more files: set just their snapshot lines (snapshot exists)")
    s.add_argument("project")
    s.add_argument("paths", nargs="+", metavar="path", help="file(s) just pulled, under projects/<project>/ or out/<project>/")
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
    s.add_argument("--sha256", action="append", metavar="HEX",
                   help="hash that was uploaded (the plan prints it), one per --uploaded: a later edit stays CHANGED")
    a = p.parse_args(argv)
    try:
        return {"save": cmd_save, "snapshot": cmd_snapshot, "pulled": cmd_pulled, "plan": cmd_plan,
                "record": cmd_record}[a.cmd](a)
    except SyncError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
