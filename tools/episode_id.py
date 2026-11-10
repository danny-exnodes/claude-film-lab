"""Episode ids (docs/CONVENTIONS.md §2): the two numbering schemes shared by every tool.

  scheme   id (media folder, file prefix)   episode folder (text)      EPISODE.md          display
  ep       ep01                             ep01-<slug>                episode: 1          Tập 1
  book     q01t01                           q01-t01-<slug>             book: 1, episode: 1 Quyển 1 · Tập 1

A project that is split into books (quyển) numbers its episodes (tập) per book; a project that is not keeps
ep<NN>. Both are valid everywhere. File names start with `<id>_` (ep01_s03_..., q01t01_s03_...).
"""
import re

SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
ID = r"(?:ep\d{2}|q\d{2}t\d{2})"                    # use inside larger regexes
RE_ID = re.compile(rf"^(?:ep(\d{{2}})|q(\d{{2}})t(\d{{2}}))$")
RE_DIR = re.compile(rf"^(?:ep(\d{{2}})|q(\d{{2}})-t(\d{{2}}))-({SLUG})$")
RE_PREFIX = re.compile(rf"^({ID})_")                # file name prefix


def make_id(episode, book=None):
    """ep01 (book None) or q01t01."""
    return f"ep{episode:02d}" if book is None else f"q{book:02d}t{episode:02d}"


def parse_id(eid):
    """(book or None, episode) for 'ep01' / 'q01t01'; None when not an episode id."""
    m = RE_ID.match(eid or "")
    if not m:
        return None
    return (None, int(m.group(1))) if m.group(1) else (int(m.group(2)), int(m.group(3)))


def dir_prefix(eid):
    """Episode folder prefix for an id: ep01 -> 'ep01', q01t01 -> 'q01-t01'."""
    p = parse_id(eid)
    if p is None:
        raise ValueError(f"not an episode id: {eid!r}")
    book, ep = p
    return f"ep{ep:02d}" if book is None else f"q{book:02d}-t{ep:02d}"


def dir_name(eid, slug):
    return f"{dir_prefix(eid)}-{slug}"


def parse_dir(name):
    """(id, slug) for an episode folder name ('q01-t01-nam-son-kinh' -> ('q01t01', 'nam-son-kinh')), else None."""
    m = RE_DIR.match(name or "")
    if not m:
        return None
    eid = f"ep{m.group(1)}" if m.group(1) else f"q{m.group(2)}t{m.group(3)}"
    return eid, m.group(4)


def file_id(name):
    """Episode id a media file name starts with ('q01t01_s03_...png' -> 'q01t01'), else None."""
    m = RE_PREFIX.match(name or "")
    return m.group(1) if m else None


def display(eid):
    """Human label: 'Tập 1' or 'Quyển 1 · Tập 1' (YouTube titles, TienDo_SanXuat)."""
    book, ep = parse_id(eid)
    return f"Tập {ep}" if book is None else f"Quyển {book} · Tập {ep}"
