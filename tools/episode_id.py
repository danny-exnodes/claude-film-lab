"""Episode ids (docs/CONVENTIONS.md §2): the two numbering schemes shared by every tool.

  scheme   id (media folder, file prefix)   episode folder (text)      EPISODE.md          display
  ep       ep01                             ep01-<slug>                episode: 1          Tập 1
  book     q01t01                           q01-t01-<slug>             book: 1, episode: 1 Quyển 1 · Tập 1

A project that is split into books (quyển) numbers its episodes (tập) per book; a project that is not keeps
ep<NN>. Both are valid everywhere. File names start with `<id>_` (ep01_s03_..., q01t01_s03_...).

Shot ids and layer codes (one definition for every tool that reads a media file name):
  shot   s<NN> (s01..s99) or s<NNN> (s001..s999); one episode uses one width (check_episode: mixed widths = ERROR)
  layer  L1 L2 L3 L4, pose plates L4b..L4z (method: layers, pose-cycle; matted like L4), P<n>-<part>, FX
  file   <id>_<shot>_<layer>_<subject>_v<NN>.png|jpg
"""
import re

SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
ID = r"(?:ep\d{2}|q\d{2}t\d{2})"                    # use inside larger regexes
RE_ID = re.compile(rf"^(?:ep(\d{{2}})|q(\d{{2}})t(\d{{2}}))$")
RE_DIR = re.compile(rf"^(?:ep(\d{{2}})|q(\d{{2}})-t(\d{{2}}))-({SLUG})$")
RE_PREFIX = re.compile(rf"^({ID})_")                # file name prefix

SHOT = r"s(?:\d{2}|\d{3})"                          # use inside larger regexes (no group)
RE_SHOT = re.compile(r"^s(\d{2}|\d{3})$")           # group 1: the digits
LAYER = r"(?:L[1-4]|L4[b-z]|P\d+-[a-z0-9-]+|FX)"    # use inside larger regexes (no group)
RE_LAYER = re.compile(rf"^{LAYER}$")
RE_POSE = re.compile(r"^L4[b-z]$")                  # pose plate of a method: layers shot (L4 = the base pose)
# A layer image: group 1 = shot, group 2 = layer code.
RE_LAYER_FILE = re.compile(rf"^{ID}_({SHOT})_({LAYER})_[a-z0-9-]+_v\d{{2}}\.(?:png|jpg)$")
RE_LAYER_PREFIX = re.compile(rf"^{ID}_({SHOT})_({LAYER})_")   # same groups, any tail (matte.py reads the code)
RE_SHOT_TAG = re.compile(rf"_({SHOT})_")            # the shot of any media file name (first match)
# method blender (blender-method.md): a 3D asset id = tools/blender/spec.py ID_RE (`_` allowed); layer code A-<asset>
ASSET = r"[a-z0-9][a-z0-9_-]*"                      # use inside larger regexes (no group)
# out/<project>/<id>/renders3d/<folder>/: s<NN>/ (blender.py render), s<NN>_v<NN>/ (render again: --out never
# overwrites), s<NN>_preview[_v<NN>]/ (--preview), s<NN>_keys[_v<NN>]/ (keyframes: first/last frame of a local H3
# clip), turntable-<asset>[_v<NN>]/. Group 1 = shot (None for a turntable), group 2 = preview | keys | None.
RE_RENDER3D_DIR = re.compile(rf"^(?:({SHOT})(?:_(preview|keys))?|turntable-{ASSET})(?:_v\d{{2}})?$")


def shot_number(sid):
    """(number, width) of a shot id: 's03' -> (3, 2), 's103' -> (103, 3); None when not a shot id."""
    m = RE_SHOT.match(sid or "")
    return (int(m.group(1)), len(m.group(1))) if m else None


def make_shot(num, width=2):
    """'s03' (width 2) or 's003' (width 3)."""
    return f"s{num:0{width}d}"


def layer_family(code):
    """The layer a code is made and matted like: L4b -> L4 (pose plate), P1-duoi -> P, others unchanged."""
    if RE_POSE.match(code or ""):
        return "L4"
    return "P" if re.fullmatch(r"P\d+-[a-z0-9-]+", code or "") else code


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
