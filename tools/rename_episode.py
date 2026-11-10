#!/usr/bin/env python3
"""Rename an episode id in the working copy, e.g. migrate ep01 to q01t01 (docs/CONVENTIONS.md §2). Free, local.

  python3 tools/rename_episode.py ep01 q01t01 --project-dir projects/<p>/ep01-<slug> --media out/<p>/ep01          # dry run
  python3 tools/rename_episode.py ep01 q01t01 --project-dir projects/<p>/ep01-<slug> --media out/<p>/ep01 --apply

Dry run (default) prints every step and changes nothing. --apply does, in this order:
  1. rewrites references in the text files (.md .csv .json .txt .yaml .yml .html .js) of the episode folder, the media
     folder (ledger.csv, film/ sources...) and projects/<p>/PROJECT.md (drive.folders keys):
       <OLD>_...                    -> <NEW>_...                  (file names in prompts.csv, shots.csv, anchors.json keys...)
       <old folder> (ep01-<slug>)   -> <new folder> (q01-t01-<slug>) (EPISODE.md drive:, Drive logical paths)
       .../<OLD> (media path)       -> .../<NEW>                  (EPISODE.md media:, ledger.csv out column)
     and sets EPISODE.md `episode:` / `book:` from NEW (book removed when NEW is ep<NN>);
  2. renames every file and folder whose name starts with `<OLD>_` (plates, clips, frame folders, renders, bundles,
     prompts/*.txt), deepest first;
  3. renames the episode folder (slug kept) and the media folder.
Refuses (exit 2, nothing changed) when an id is invalid, the folders do not carry OLD, or a target already exists.
Then on Drive (by hand, connector): rename 03_KichBan/, 04_SanXuat/, 05_ThanhPham/<old folder> with update_file
(title; IDs stay, PROJECT.md keys already rewritten), push the renamed text files (drive_sync.py plan), and fix the
episode row of TienDo_SanXuat. Run tools/check_episode.py on the new folder afterwards.
"""
import argparse, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import episode_id  # noqa: E402

TEXT_EXT = {".md", ".csv", ".json", ".txt", ".yaml", ".yml", ".html", ".js", ".mjs"}
SKIP_DIRS = {"node_modules", ".git", "__pycache__"}


class RenameError(Exception):
    pass


def text_files(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in SKIP_DIRS)
        for fn in sorted(fns):
            if os.path.splitext(fn)[1].lower() in TEXT_EXT:
                yield os.path.join(dp, fn)


def make_rewriter(old, new, old_dir, new_dir):
    """One regex pass (so a replacement is never replaced again)."""
    rx = re.compile(
        rf"(?P<dir>(?<![A-Za-z0-9-]){re.escape(old_dir)}(?![A-Za-z0-9-]))"
        rf"|(?P<pre>(?<![A-Za-z0-9]){re.escape(old)}_)"
        rf"|(?P<path>(?<=/){re.escape(old)}(?![A-Za-z0-9_-]))")
    repl = {"dir": new_dir, "pre": new + "_", "path": new}

    def rewrite(text):
        return rx.subn(lambda m: repl[m.lastgroup], text)
    return rewrite


def set_front_matter_ids(text, new):
    """Set episode:/book: in the EPISODE.md front matter for id `new`. Returns (text, changed)."""
    m = re.match(r"^(---[ \t]*\n)(.*?)(\n---[ \t]*(?:\n|$))", text, re.S)
    if not m:
        return text, False
    book, ep = episode_id.parse_id(new)
    lines = [l for l in m.group(2).split("\n") if not re.match(r"^book\s*:", l)]
    out, done = [], False
    for l in lines:
        if re.match(r"^episode\s*:", l):
            if book is not None:
                out.append(f"book: {book}")
            out.append(re.sub(r"^episode\s*:\s*[^#]*?(\s*#.*)?$", lambda x: f"episode: {ep}" + (x.group(1) or ""), l))
            done = True
        else:
            out.append(l)
    if not done:
        if book is not None:
            out.append(f"book: {book}")
        out.append(f"episode: {ep}")
    body = "\n".join(out)
    return m.group(1) + body + m.group(3) + text[m.end():], body != m.group(2)


def plan(old, new, project_dir, media):
    """List of steps: ('edit', path, count) / ('rename', src, dst)."""
    for x in (old, new):
        if episode_id.parse_id(x) is None:
            raise RenameError(f"'{x}' is not an episode id (ep<NN> or q<NN>t<NN>)")
    if old == new:
        raise RenameError("OLD_ID and NEW_ID are the same")
    project_dir = os.path.abspath(project_dir)
    if not os.path.isdir(project_dir):
        raise RenameError(f"{project_dir}: episode folder not found")
    parsed = episode_id.parse_dir(os.path.basename(project_dir))
    if not parsed or parsed[0] != old:
        raise RenameError(f"episode folder '{os.path.basename(project_dir)}' is not for {old} "
                          f"(expected {episode_id.dir_prefix(old)}-<slug>)")
    old_dir = os.path.basename(project_dir)
    new_dir = episode_id.dir_name(new, parsed[1])
    roots = [project_dir]
    if media:
        media = os.path.abspath(media)
        if not os.path.isdir(media):
            raise RenameError(f"{media}: media folder not found")
        if os.path.basename(media) != old:
            raise RenameError(f"media folder '{os.path.basename(media)}' is not {old}")
        roots.append(media)
    renames_top = [(project_dir, os.path.join(os.path.dirname(project_dir), new_dir))]
    if media:
        renames_top.append((media, os.path.join(os.path.dirname(media), new)))
    for _, dst in renames_top:
        if os.path.exists(dst):
            raise RenameError(f"{dst} already exists")

    rewrite = make_rewriter(old, new, old_dir, new_dir)
    steps = []
    edit_files = [f for r in roots for f in text_files(r)]
    manifest = os.path.join(os.path.dirname(project_dir), "PROJECT.md")
    if os.path.isfile(manifest):
        edit_files.append(manifest)
    for f in edit_files:
        with open(f, encoding="utf-8") as fh:
            try:
                text = fh.read()
            except UnicodeDecodeError:
                continue
        new_text, n = rewrite(text)
        if f == os.path.join(project_dir, "EPISODE.md"):
            new_text, changed = set_front_matter_ids(new_text, new)
            n += int(changed)
        if n:
            steps.append(("edit", f, n, new_text))

    prefix = old + "_"
    for r in roots:
        for dp, dns, fns in os.walk(r, topdown=False):
            for name in sorted(fns) + sorted(dns):
                if name.startswith(prefix):
                    src = os.path.join(dp, name)
                    dst = os.path.join(dp, new + "_" + name[len(prefix):])
                    if os.path.exists(dst):
                        raise RenameError(f"{dst} already exists")
                    steps.append(("rename", src, dst))
    steps += [("rename", s, d) for s, d in renames_top]
    return steps, old_dir, new_dir


def apply(steps):
    for st in steps:
        if st[0] == "edit":
            tmp = st[1] + ".renaming"
            with open(tmp, "w", encoding="utf-8", newline="") as fh:
                fh.write(st[3])
            os.replace(tmp, st[1])
    for st in steps:
        if st[0] == "rename":
            os.rename(st[1], st[2])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("old_id", help="current id, e.g. ep01")
    p.add_argument("new_id", help="new id, e.g. q01t01")
    p.add_argument("--project-dir", required=True, help="projects/<p>/<old episode folder>")
    p.add_argument("--media", default=None, help="out/<p>/<old id> (optional: text folder only without it)")
    p.add_argument("--apply", action="store_true", help="do it (default: dry run)")
    a = p.parse_args(argv)
    try:
        steps, old_dir, new_dir = plan(a.old_id, a.new_id, a.project_dir, a.media)
    except (RenameError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    cwd = os.getcwd()
    rel = lambda x: os.path.relpath(x, cwd)
    for st in steps:
        if st[0] == "edit":
            print(f"edit    {rel(st[1])} ({st[2]} change(s))")
        else:
            print(f"rename  {rel(st[1])} -> {os.path.basename(st[2])}")
    edits = sum(1 for s in steps if s[0] == "edit")
    print(f"{a.old_id} -> {a.new_id}: {edits} file(s) to edit, {len(steps) - edits} rename(s); folder {old_dir} -> {new_dir}")
    if not a.apply:
        print("dry run: nothing changed (add --apply)")
        return 0
    apply(steps)
    print(f"done. Drive: rename 03_KichBan|04_SanXuat|05_ThanhPham/{old_dir} to {new_dir} (update_file title), "
          f"push with tools/drive_sync.py plan, update TienDo_SanXuat; then tools/check_episode.py episode "
          f"{rel(os.path.join(os.path.dirname(os.path.abspath(a.project_dir)), new_dir))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
