"""shot3d.json version 1: validation, defaults, frame counts and camera path math.

Pure Python (stdlib only), imported by tools/blender/blender.py (Windows Python 3.12-3.14, Linux 3.12) and by
tools/blender/scene.py inside Blender (its bundled Python 3.13). Coordinates are Blender's: metres, Z up, the ground
is the XY plane, a camera at y < 0 looking toward +y sees the scene from the front. Angles in degrees.

    errors = validate(data, base_dir)         # ["camera.move: 'zoom' is not one of static, push-in, ..."]
    shot = normalize(data)                    # a copy with every default filled in
    n = frame_count(shot["seconds"], shot["fps"])
    cam = camera_at(shot, t)                  # {"pos", "target", "lens", "roll"} at t seconds
    p = asset_position(asset, t)              # [x, y, z] (at + anim.path offset)

Camera moves (shots.csv `camera`, same meanings as tools/toon/project.js):
  static     the camera does not move and keeps its first aim
  push-in    toward the target (camera.to, or `amount` of the way, default 0.3)
  pull-out   away from the target (camera.to, or `amount` of the distance back)
  pan        stays in place and turns left/right (`degrees`, + = to the left) or to `target_to`
  tilt       stays in place and turns up/down (`degrees`, + = up) or to `target_to`
  orbit      circles the target in the ground plane (`degrees`, + = counter-clockwise seen from above)
  dolly      camera and aim slide together from `from` to `to` (a truck/dolly move)
  crane      rises (`rise` metres, default 2, or to `to`) while aiming at the target
  track      follows a moving target (asset with anim.path), keeping the start offset; `to` adds a drift
"""
import json
import math
import os
import re

VERSION = 1
HERE = os.path.dirname(os.path.abspath(__file__))

MOVES = ("static", "push-in", "pull-out", "pan", "tilt", "orbit", "dolly", "crane", "track")
EASES = ("linear", "in", "out", "inout", "sine")
ENGINES = ("eevee", "cycles")
PASSES = ("depth", "normal", "line", "mask")
PRIMS = ("cube", "sphere", "ico", "cylinder", "cone", "plane", "torus")

# Procedural presets (tools/blender/presets.py): parameters (name -> (kind, min, max)), nominal height in metres at
# scale 1 (the default camera aim is half of it) and the actions their rigs play.
PRESETS = {
    "mountains": {"height": 18.0, "actions": (), "params": {
        "width": ("num", 4, 2000), "depth": ("num", 2, 1000), "height": ("num", 0.5, 1000), "peaks": ("int", 1, 40),
        "sharp": ("num", 0.2, 4), "detail": ("num", 0, 1), "res": ("int", 16, 600), "seed": ("int", 0, 2 ** 31 - 1)}},
    "rocks": {"height": 1.0, "actions": (), "params": {
        "count": ("int", 1, 200), "spread": ("num", 0, 500), "size": ("num", 0.05, 100), "seed": ("int", 0, 2 ** 31 - 1)}},
    "pines": {"height": 6.0, "actions": ("sway",), "params": {
        "count": ("int", 1, 100), "spread": ("num", 0, 500), "height": ("num", 0.5, 100), "seed": ("int", 0, 2 ** 31 - 1)}},
    "water": {"height": 0.0, "actions": (), "params": {
        "width": ("num", 1, 5000), "depth": ("num", 1, 5000)}},
    "ground": {"height": 0.0, "actions": (), "params": {
        "width": ("num", 1, 5000), "depth": ("num", 1, 5000), "relief": ("num", 0, 50), "seed": ("int", 0, 2 ** 31 - 1)}},
    "giot": {"height": 1.0, "actions": ("idle", "hop", "walk", "wave"), "params": {
        "body": ("color", None, None), "cheek": ("color", None, None)}},
}

PREVIEW_W, PREVIEW_FPS = 960, 12
DEFAULTS = {"size": [1920, 1080], "fps": 24, "seconds": 5, "seed": 0, "look": "grey-layout", "engine": "eevee",
            "passes": [], "depth_range": [0.5, 100.0]}
WORLD_DEFAULTS = {"mist": 0.35, "sun": [35.0, 120.0]}
CAMERA_DEFAULTS = {"lens": 35.0, "ease": "inout", "roll": 0.0, "amount": 0.3, "rise": 2.0}
MOVE_DEGREES = {"pan": 20.0, "tilt": 10.0, "orbit": 30.0}

TOP_KEYS = {"version", "title", "note", "size", "fps", "seconds", "seed", "look", "engine", "world", "assets",
            "camera", "passes", "depth_range", "samples", "asset_root", "materials"}
WORLD_KEYS = {"paper", "ink", "mist", "mist_range", "sun", "hdri", "hdri_strength", "hdri_rot", "sun_strength"}
# look `realistic`: preset roles that get a PBR texture set from `materials` (role -> texture id, folder or object)
MATERIAL_ROLES = ("mountain", "rock", "ground", "water", "trunk", "foliage", "prim")
MATERIAL_KEYS = {"tex", "scale", "displace"}
# file name parts of a texture set folder (Poly Haven <id>_<map>_<res>.<ext>, ambientCG <id>_<Map>.<ext>), first match
TEXTURE_MAPS = {"diff": ("_diff_", "_diffuse", "_albedo", "_basecolor", "_color"), "nor_gl": ("_nor_gl", "_normalgl"),
                "rough": ("_rough", "_roughness"), "ao": ("_ao_", "_ambientocclusion"), "disp": ("_disp", "_displacement")}
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".exr", ".tif", ".tiff")
HDRI_EXT = (".hdr", ".exr")
ASSET_KEYS = {"id", "src", "at", "rot", "scale", "fit", "color", "ink", "params", "anim", "mask", "lines", "note"}
ANIM_KEYS = {"action", "path", "ease", "face_path", "speed"}
CAMERA_KEYS = {"move", "from", "to", "target", "target_to", "aim", "lens", "lens_to", "roll", "ease", "t", "amount",
               "degrees", "rise"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def look_ids():
    """The look ids of tools/blender/looks.json (the registry; looks.py implements them)."""
    try:
        with open(os.path.join(HERE, "looks.json"), encoding="utf-8") as f:
            return tuple(json.load(f)["looks"])
    except (OSError, ValueError, KeyError):
        return ("grey-layout", "clay", "toon-ink", "ink-wash")


# ------------------------------------------------------------------ validation
def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _vec(v, n=3):
    return isinstance(v, list) and len(v) == n and all(_num(x) for x in v)


class _Errors(list):
    def add(self, path, reason):
        self.append(f"{path}: {reason}")


def _unknown(err, obj, allowed, path):
    for k in obj:
        if k not in allowed:
            err.add(f"{path}.{k}" if path else k, "unknown key")


def _range(err, path, v, lo, hi, kind="num"):
    if not (_int(v) if kind == "int" else _num(v)):
        err.add(path, "must be an integer" if kind == "int" else "must be a number")
    elif not lo <= v <= hi:
        err.add(path, f"must be between {lo} and {hi} (got {v})")


def _src_kind(src):
    """'preset' | 'prim' | 'file' | None."""
    if not isinstance(src, str) or not src:
        return None
    if src.startswith("preset:"):
        return "preset"
    if src.startswith("prim:"):
        return "prim"
    if src.lower().endswith((".glb", ".gltf")):
        return "file"
    if blend_src(src)[0].lower().endswith(".blend"):
        return "blend"
    return None


def blend_src(src):
    """(path, collection name or None) of a `<file>.blend` or `<file>.blend#<Collection>` asset src."""
    path, _, coll = str(src).partition("#")
    return path, (coll or None)


def _abs(base_dir, path):
    return path if os.path.isabs(path) else os.path.join(base_dir or ".", path)


def _is_path(ref):
    return "/" in str(ref) or "\\" in str(ref)


def resolve_hdri(ref, asset_root, base_dir):
    """Path of an HDRI: a .hdr/.exr path (relative to the spec) or an id looked up as <asset_root>/hdri/<id>*.hdr|exr.
    -> path or None."""
    if str(ref).lower().endswith(HDRI_EXT):
        path = _abs(base_dir, ref)
        return path if os.path.isfile(path) else None
    if not asset_root:
        return None
    folder = os.path.join(_abs(base_dir, asset_root), "hdri")
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return None
    for n in names:
        if n.startswith(str(ref)) and n.lower().endswith(HDRI_EXT):
            return os.path.join(folder, n)
    return None


def resolve_texture(ref, asset_root, base_dir):
    """{map: path} of a PBR texture set (keys of TEXTURE_MAPS): a folder path (relative to the spec) or a texture id
    under <asset_root>/textures/<id>/. -> dict, empty when the folder is missing or has no colour map."""
    if _is_path(ref):
        folder = _abs(base_dir, ref)
    elif asset_root:
        folder = os.path.join(_abs(base_dir, asset_root), "textures", str(ref))
    else:
        return {}
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return {}
    found = {}
    for key, parts in TEXTURE_MAPS.items():
        for n in names:
            low = n.lower()
            if any(pt in low for pt in parts) and low.endswith(IMAGE_EXT):
                found[key] = os.path.join(folder, n)
                break
    return found if "diff" in found else {}


def validate(data, base_dir=None):
    """Errors of a shot3d.json document as 'path: reason' strings (empty list = valid). base_dir (the spec's folder)
    turns on the check that .glb/.gltf files exist."""
    err = _Errors()
    if not isinstance(data, dict):
        err.add("(root)", "must be a JSON object")
        return list(err)
    _unknown(err, data, TOP_KEYS, "")
    if "version" not in data:
        err.add("version", "missing (must be 1)")
    elif data["version"] != VERSION:
        err.add("version", f"must be {VERSION} (got {data['version']!r})")
    size = data.get("size", DEFAULTS["size"])
    if not (isinstance(size, list) and len(size) == 2 and all(_int(x) for x in size)):
        err.add("size", "must be [width, height] in pixels")
    else:
        for i, x in enumerate(size):
            if not 16 <= x <= 8192:
                err.add(f"size[{i}]", f"must be between 16 and 8192 (got {x})")
            elif x % 2:
                err.add(f"size[{i}]", f"must be even for H.264 (got {x})")
    if "fps" in data:
        _range(err, "fps", data["fps"], 1, 120, "int")
    if "seconds" in data:
        _range(err, "seconds", data["seconds"], 0.04, 600)
    if "seed" in data:
        _range(err, "seed", data["seed"], 0, 2 ** 31 - 1, "int")
    if "samples" in data:
        _range(err, "samples", data["samples"], 1, 4096, "int")
    looks = look_ids()
    if "look" in data and data["look"] not in looks:
        err.add("look", f"{data['look']!r} is not one of {', '.join(looks)}")
    if "engine" in data and data["engine"] not in ENGINES:
        err.add("engine", f"{data['engine']!r} is not one of {', '.join(ENGINES)}")
    for k in ("title", "note"):
        if k in data and not isinstance(data[k], str):
            err.add(k, "must be a string")

    world = data.get("world", {})
    if not isinstance(world, dict):
        err.add("world", "must be an object")
    else:
        _unknown(err, world, WORLD_KEYS, "world")
        for k in ("paper", "ink"):
            if k in world and not (isinstance(world[k], str) and HEX_RE.match(world[k])):
                err.add(f"world.{k}", "must be a colour '#rrggbb'")
        if "mist" in world:
            _range(err, "world.mist", world["mist"], 0, 1)
        if "mist_range" in world:
            mr = world["mist_range"]
            if not (_vec(mr, 2) and 0 <= mr[0] < mr[1]):
                err.add("world.mist_range", "must be [start, end] metres with 0 <= start < end")
        if "sun" in world:
            s = world["sun"]
            if not _vec(s, 2):
                err.add("world.sun", "must be [elevation, azimuth] in degrees")
            elif not 0 <= s[0] <= 90:
                err.add("world.sun", f"elevation must be between 0 and 90 (got {s[0]})")
        if "hdri" in world:
            h = world["hdri"]
            if not (isinstance(h, str) and h):
                err.add("world.hdri", "must be an HDRI id (with asset_root) or a .hdr/.exr path")
            elif not h.lower().endswith(HDRI_EXT) and not data.get("asset_root"):
                err.add("world.hdri", f"id {h!r} needs asset_root (or give a .hdr/.exr path)")
            elif base_dir is not None and resolve_hdri(h, data.get("asset_root"), base_dir) is None:
                err.add("world.hdri", f"not found: {h}")
        if "hdri_strength" in world:
            _range(err, "world.hdri_strength", world["hdri_strength"], 0, 20)
        if "hdri_rot" in world:
            _range(err, "world.hdri_rot", world["hdri_rot"], -360, 360)
        if "sun_strength" in world:
            _range(err, "world.sun_strength", world["sun_strength"], 0, 50)
    if "asset_root" in data:
        r = data["asset_root"]
        if not (isinstance(r, str) and r):
            err.add("asset_root", "must be a folder path (relative to the spec)")
        elif base_dir is not None and not os.path.isdir(_abs(base_dir, r)):
            err.add("asset_root", f"folder not found: {r}")
    if "materials" in data:
        _validate_materials(err, data["materials"], data.get("asset_root"), base_dir)

    seconds = data.get("seconds", DEFAULTS["seconds"]) if _num(data.get("seconds", 5)) else DEFAULTS["seconds"]
    ids = _validate_assets(err, data.get("assets"), base_dir, seconds)
    _validate_camera(err, data.get("camera"), ids, data.get("assets") if isinstance(data.get("assets"), list) else [])

    passes = data.get("passes", [])
    if not isinstance(passes, list):
        err.add("passes", f"must be a list of {', '.join(PASSES)}")
    else:
        for i, p in enumerate(passes):
            if p not in PASSES:
                err.add(f"passes[{i}]", f"{p!r} is not one of {', '.join(PASSES)}")
        if len(set(map(str, passes))) != len(passes):
            err.add("passes", "has duplicates")
    if "depth_range" in data:
        dr = data["depth_range"]
        if not (_vec(dr, 2) and 0 < dr[0] < dr[1]):
            err.add("depth_range", "must be [near, far] metres with 0 < near < far")
    return list(err)


def _validate_materials(err, mats, asset_root, base_dir):
    if not isinstance(mats, dict):
        err.add("materials", f"must be an object role -> texture ({', '.join(MATERIAL_ROLES)})")
        return
    for role, m in mats.items():
        p = f"materials.{role}"
        if role not in MATERIAL_ROLES:
            err.add(p, f"unknown role (one of {', '.join(MATERIAL_ROLES)})")
            continue
        if isinstance(m, str):
            m = {"tex": m}
        if not isinstance(m, dict):
            err.add(p, "must be a texture id or folder, or {tex, scale, displace}")
            continue
        _unknown(err, m, MATERIAL_KEYS, p)
        tex = m.get("tex")
        if not (isinstance(tex, str) and tex):
            err.add(f"{p}.tex", "missing (a texture id under asset_root/textures/ or a folder path)")
        elif not _is_path(tex) and not asset_root:
            err.add(f"{p}.tex", f"id {tex!r} needs asset_root (or give a folder path)")
        elif base_dir is not None and not resolve_texture(tex, asset_root, base_dir):
            err.add(f"{p}.tex", f"no texture set with a colour map found for {tex!r}")
        if "scale" in m:
            _range(err, f"{p}.scale", m["scale"], 0.01, 1000)
        if "displace" in m:
            _range(err, f"{p}.displace", m["displace"], 0, 50)


def _validate_assets(err, assets, base_dir, seconds):
    ids = {}
    if not isinstance(assets, list) or not assets:
        err.add("assets", "must be a non-empty list")
        return ids
    for i, a in enumerate(assets):
        p = f"assets[{i}]"
        if not isinstance(a, dict):
            err.add(p, "must be an object")
            continue
        _unknown(err, a, ASSET_KEYS, p)
        aid = a.get("id")
        if not isinstance(aid, str) or not ID_RE.match(aid):
            err.add(f"{p}.id", "must be 1-40 characters a-z 0-9 _ - (starting with a letter or digit)")
        elif aid in ids:
            err.add(f"{p}.id", f"{aid!r} is used twice")
        else:
            ids[aid] = a
        src = a.get("src")
        kind = _src_kind(src)
        if "src" not in a:
            err.add(f"{p}.src", "missing")
        elif kind is None:
            err.add(f"{p}.src", "must be preset:<id>, prim:<shape>, a .glb/.gltf path or <file>.blend[#Collection]")
        elif kind == "preset":
            name = src[7:]
            if name not in PRESETS:
                err.add(f"{p}.src", f"unknown preset {name!r} ({', '.join(PRESETS)})")
        elif kind == "prim":
            if src[5:] not in PRIMS:
                err.add(f"{p}.src", f"unknown primitive {src[5:]!r} ({', '.join(PRIMS)})")
        elif kind in ("file", "blend") and base_dir is not None:
            path = _abs(base_dir, blend_src(src)[0] if kind == "blend" else src)
            if not os.path.isfile(path):
                err.add(f"{p}.src", f"file not found: {src}")
        for k in ("at", "rot"):
            if k in a and not _vec(a[k]):
                err.add(f"{p}.{k}", "must be [x, y, z]")
        if "scale" in a:
            s = a["scale"]
            if not ((_num(s) and s > 0) or (_vec(s) and all(x > 0 for x in s))):
                err.add(f"{p}.scale", "must be a positive number or [x, y, z]")
        if "fit" in a and not (_num(a["fit"]) and a["fit"] > 0):
            err.add(f"{p}.fit", "must be a positive number (metres of the largest side)")
        if "color" in a and not (isinstance(a["color"], str) and HEX_RE.match(a["color"])):
            err.add(f"{p}.color", "must be a colour '#rrggbb'")
        if "ink" in a:
            _range(err, f"{p}.ink", a["ink"], 0, 1)
        for k in ("mask", "lines"):
            if k in a and not isinstance(a[k], bool):
                err.add(f"{p}.{k}", "must be true or false")
        if "params" in a:
            _validate_params(err, f"{p}.params", a["params"], src[7:] if kind == "preset" else None)
        if "anim" in a:
            _validate_anim(err, f"{p}.anim", a["anim"], kind, src, seconds)
    return ids


def _validate_params(err, p, params, preset):
    if not isinstance(params, dict):
        err.add(p, "must be an object")
        return
    if preset not in PRESETS:
        if params:
            err.add(p, "only preset assets take params")
        return
    spec = PRESETS[preset]["params"]
    for k, v in params.items():
        if k not in spec:
            err.add(f"{p}.{k}", f"unknown parameter of preset:{preset} ({', '.join(spec) or 'none'})")
            continue
        kind, lo, hi = spec[k]
        if kind == "color":
            if not (isinstance(v, str) and HEX_RE.match(v)):
                err.add(f"{p}.{k}", "must be a colour '#rrggbb'")
        else:
            _range(err, f"{p}.{k}", v, lo, hi, kind)


def _validate_anim(err, p, anim, kind, src, seconds):
    if not isinstance(anim, dict):
        err.add(p, "must be an object")
        return
    _unknown(err, anim, ANIM_KEYS, p)
    if "action" in anim:
        act = anim["action"]
        if not isinstance(act, str) or not act:
            err.add(f"{p}.action", "must be a name")
        elif kind == "preset":
            acts = PRESETS.get(src[7:], {}).get("actions", ())
            if act not in acts:
                err.add(f"{p}.action", f"{act!r} is not an action of {src} ({', '.join(acts) or 'none'})")
        elif kind == "prim":
            err.add(f"{p}.action", "primitives have no actions (use path)")
    if "ease" in anim and anim["ease"] not in EASES:
        err.add(f"{p}.ease", f"{anim['ease']!r} is not one of {', '.join(EASES)}")
    if "face_path" in anim and not isinstance(anim["face_path"], bool):
        err.add(f"{p}.face_path", "must be true or false")
    if "speed" in anim:
        _range(err, f"{p}.speed", anim["speed"], 0.05, 20)
    if "path" in anim:
        path = anim["path"]
        if not isinstance(path, list) or len(path) < 2:
            err.add(f"{p}.path", "must be a list of at least two [t, [dx, dy, dz]] keys")
            return
        last = -1.0
        for j, key in enumerate(path):
            if not (isinstance(key, list) and len(key) == 2 and _num(key[0]) and _vec(key[1])):
                err.add(f"{p}.path[{j}]", "must be [t, [dx, dy, dz]]")
                continue
            if key[0] <= last:
                err.add(f"{p}.path[{j}]", "times must increase")
            elif key[0] < 0 or key[0] > seconds + 1e-9:
                err.add(f"{p}.path[{j}]", f"time {key[0]} is outside the shot (0..{seconds} s)")
            last = key[0]


def _target_ok(err, path, t, ids):
    if isinstance(t, str):
        if t not in ids:
            err.add(path, f"unknown asset {t!r}")
    elif not _vec(t):
        err.add(path, "must be an asset id or [x, y, z]")


def _validate_camera(err, cam, ids, assets):
    if not isinstance(cam, dict):
        err.add("camera", "missing (an object with move, from, target)")
        return
    _unknown(err, cam, CAMERA_KEYS, "camera")
    move = cam.get("move")
    if move not in MOVES:
        err.add("camera.move", f"{move!r} is not one of {', '.join(MOVES)}" if "move" in cam else "missing")
    if not _vec(cam.get("from")):
        err.add("camera.from", "must be [x, y, z]" if "from" in cam else "missing")
    if "target" not in cam:
        err.add("camera.target", "missing (an asset id or [x, y, z])")
    else:
        _target_ok(err, "camera.target", cam["target"], ids)
    if "target_to" in cam:
        _target_ok(err, "camera.target_to", cam["target_to"], ids)
        if move not in ("pan", "tilt"):
            err.add("camera.target_to", "only pan and tilt use it")
    for k in ("to", "aim"):
        if k in cam and not _vec(cam[k]):
            err.add(f"camera.{k}", "must be [x, y, z]")
    for k in ("lens", "lens_to"):
        if k in cam:
            _range(err, f"camera.{k}", cam[k], 4, 600)
    if "roll" in cam:
        _range(err, "camera.roll", cam["roll"], -180, 180)
    if "ease" in cam and cam["ease"] not in EASES:
        err.add("camera.ease", f"{cam['ease']!r} is not one of {', '.join(EASES)}")
    if "amount" in cam:
        _range(err, "camera.amount", cam["amount"], 0, 0.95)
        if move not in ("push-in", "pull-out"):
            err.add("camera.amount", "only push-in and pull-out use it")
    if "degrees" in cam:
        _range(err, "camera.degrees", cam["degrees"], -720, 720)
        if move not in ("pan", "tilt", "orbit"):
            err.add("camera.degrees", "only pan, tilt and orbit use it")
    if "rise" in cam:
        _range(err, "camera.rise", cam["rise"], -500, 500)
        if move != "crane":
            err.add("camera.rise", "only crane uses it")
    if "t" in cam:
        t = cam["t"]
        if not (_vec(t, 2) and 0 <= t[0] < t[1]):
            err.add("camera.t", "must be [start, end] seconds with 0 <= start < end")
    if move == "dolly" and "to" not in cam:
        err.add("camera.to", "dolly needs `to`")
    if move == "track" and "to" not in cam:
        tgt = cam.get("target")
        a = ids.get(tgt) if isinstance(tgt, str) else None
        if not (isinstance(a, dict) and isinstance(a.get("anim"), dict) and "path" in a["anim"]):
            err.add("camera.target", "track follows a moving asset (one with anim.path) or needs `to`")
    if move in ("push-in", "pull-out", "orbit") and _vec(cam.get("from")) and _vec(cam.get("target")):
        if _dist(cam["from"], cam["target"]) < 1e-6:
            err.add("camera.target", "is where the camera stands")


# ------------------------------------------------------------------ defaults
def normalize(data):
    """A deep copy of a valid spec with every default filled in."""
    d = json.loads(json.dumps(data))
    for k, v in DEFAULTS.items():
        d.setdefault(k, json.loads(json.dumps(v)))
    w = d.setdefault("world", {})
    for k, v in WORLD_DEFAULTS.items():
        w.setdefault(k, list(v) if isinstance(v, list) else v)
    for a in d["assets"]:
        a.setdefault("at", [0.0, 0.0, 0.0])
        a.setdefault("rot", [0.0, 0.0, 0.0])
        a.setdefault("scale", 1.0)
        a.setdefault("params", {})
        a.setdefault("mask", True)
        if "anim" in a:
            a["anim"].setdefault("ease", "linear")
            a["anim"].setdefault("face_path", "path" in a["anim"])
            a["anim"].setdefault("speed", 1.0)
    c = d["camera"]
    for k, v in CAMERA_DEFAULTS.items():
        c.setdefault(k, v)
    if c["move"] in MOVE_DEGREES:
        c.setdefault("degrees", MOVE_DEGREES[c["move"]])
    if "aim" not in c:
        c["aim"] = default_aim(d, c["target"])
    return d


def scale3(scale):
    return [float(scale)] * 3 if _num(scale) else [float(x) for x in scale]


def default_aim(d, target):
    """Aim offset for a camera target: half the nominal height of a preset or a fitted asset, else 0."""
    if not isinstance(target, str):
        return [0.0, 0.0, 0.0]
    a = next((x for x in d["assets"] if x.get("id") == target), None)
    if not a:
        return [0.0, 0.0, 0.0]
    if "fit" in a:
        return [0.0, 0.0, a["fit"] * 0.5]
    src = a.get("src", "")
    if src.startswith("preset:"):
        h = PRESETS[src[7:]]["height"]
        params = a.get("params") or {}
        if "height" in params:
            h = params["height"]
        return [0.0, 0.0, h * 0.5 * scale3(a.get("scale", 1.0))[2]]
    return [0.0, 0.0, 0.0]


# ------------------------------------------------------------------ frames
def frame_count(seconds, fps):
    """Frames of a shot: seconds x fps rounded, at least 1. Frame numbers run 1..N."""
    return max(1, int(round(seconds * fps)))


def frame_time(frame, fps):
    """Seconds at frame `frame` (1-based): frame 1 is t = 0."""
    return (frame - 1) / float(fps)


def preview_size(size):
    """--preview frame size: 960 wide, the spec's aspect, even height."""
    w, h = size
    ph = int(round(PREVIEW_W * h / float(w) / 2.0)) * 2
    return [PREVIEW_W, max(2, ph)]


def timeline(shot, preview=False):
    """(width, height, fps, frames) the renderer uses."""
    size = preview_size(shot["size"]) if preview else list(shot["size"])
    fps = PREVIEW_FPS if preview else shot["fps"]
    return size[0], size[1], fps, frame_count(shot["seconds"], fps)


def parse_frames(text, n):
    """'A:B' (inclusive, 1-based), 'A' or 'A,B,C' -> sorted frame list within 1..n. Raises ValueError."""
    text = str(text).strip()
    if ":" in text:
        a, b = text.split(":", 1)
        a = int(a) if a.strip() else 1
        b = int(b) if b.strip() else n
        frames = list(range(a, b + 1))
        if a > b:
            raise ValueError(f"--frames {text}: start is after end")
    else:
        frames = sorted({int(x) for x in text.split(",") if x.strip()})
    if not frames:
        raise ValueError(f"--frames {text}: no frames")
    bad = [f for f in frames if not 1 <= f <= n]
    if bad:
        raise ValueError(f"--frames {text}: frame {bad[0]} is outside 1..{n}")
    return frames


# ------------------------------------------------------------------ math
def ease(name, k):
    k = min(1.0, max(0.0, k))
    if name == "linear":
        return k
    if name == "in":
        return k * k * k
    if name == "out":
        return 1 - (1 - k) ** 3
    if name == "sine":
        return 0.5 - 0.5 * math.cos(math.pi * k)
    return 4 * k * k * k if k < 0.5 else 1 - (-2 * k + 2) ** 3 / 2      # inout


def _lerp(a, b, k):
    return [x + (y - x) * k for x, y in zip(a, b)]


def _add(a, b):
    return [x + y for x, y in zip(a, b)]


def _sub(a, b):
    return [x - y for x, y in zip(a, b)]


def _mul(a, s):
    return [x * s for x in a]


def _dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _rot_z(v, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [v[0] * c - v[1] * s, v[0] * s + v[1] * c, v[2]]


def _tilt(v, deg):
    """Rotate a view vector up (deg > 0) about the horizontal axis at right angles to it."""
    h = math.hypot(v[0], v[1])
    if h < 1e-9:
        return list(v)
    pitch = math.atan2(v[2], h) + math.radians(deg)
    pitch = max(-math.pi / 2 + 1e-4, min(math.pi / 2 - 1e-4, pitch))
    r = math.sqrt(h * h + v[2] * v[2])
    return [v[0] / h * r * math.cos(pitch), v[1] / h * r * math.cos(pitch), r * math.sin(pitch)]


def path_offset(anim, t):
    """anim.path offset [dx, dy, dz] at t seconds: piecewise between keys (eased per key span), held at the ends."""
    path = (anim or {}).get("path")
    if not path:
        return [0.0, 0.0, 0.0]
    if t <= path[0][0]:
        return [float(x) for x in path[0][1]]
    if t >= path[-1][0]:
        return [float(x) for x in path[-1][1]]
    for (t0, p0), (t1, p1) in zip(path, path[1:]):
        if t0 <= t <= t1:
            return _lerp(p0, p1, ease(anim.get("ease", "linear"), (t - t0) / (t1 - t0)))
    return [float(x) for x in path[-1][1]]


def asset_position(asset, t):
    """World position of an asset's origin at t seconds: `at` + its anim.path offset."""
    return _add([float(x) for x in asset.get("at", [0, 0, 0])], path_offset(asset.get("anim"), t))


def path_heading(asset, t, dt=1.0 / 24):
    """Yaw in degrees that turns the asset's front (-Y) along its path at t (None without a path or face_path false).
    While it stands still it keeps the heading of the last span it walked (or of the first one, before it starts)."""
    anim = asset.get("anim") or {}
    path = anim.get("path")
    if not path or not anim.get("face_path", True):
        return None
    a, b = path_offset(anim, max(0.0, t - dt)), path_offset(anim, t + dt)
    dx, dy = b[0] - a[0], b[1] - a[1]
    if math.hypot(dx, dy) < 1e-6:
        spans = list(zip(path, path[1:]))
        before = [sp for sp in spans if sp[0][0] <= t]
        for (t0, p0), (t1, p1) in list(reversed(before)) + spans:
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
            if math.hypot(dx, dy) > 1e-6:
                break
        else:
            return None
    return math.degrees(math.atan2(dx, -dy))


def _point(shot, target, t):
    if isinstance(target, str):
        a = next(x for x in shot["assets"] if x["id"] == target)
        return asset_position(a, t)
    return [float(x) for x in target]


def move_window(shot, fps=None):
    """[start, end] seconds of the camera move: camera.t or from 0 to the last frame's time."""
    cam = shot["camera"]
    if "t" in cam:
        return [float(cam["t"][0]), float(cam["t"][1])]
    fps = fps or shot["fps"]
    last = frame_time(frame_count(shot["seconds"], fps), fps)
    return [0.0, max(last, 1e-6)]


def camera_at(shot, t, fps=None):
    """Camera of a normalized shot at t seconds -> {"pos", "target", "lens", "roll"} (Blender coordinates).
    fps (the render's, e.g. 12 for --preview) only sets the default move window so the last frame ends the move."""
    cam = shot["camera"]
    t0, t1 = move_window(shot, fps)
    k = ease(cam.get("ease", "inout"), (t - t0) / (t1 - t0))
    aim = cam.get("aim") or [0.0, 0.0, 0.0]
    start = [float(x) for x in cam["from"]]
    tgt0 = _add(_point(shot, cam["target"], t0), aim)
    tgt_t = _add(_point(shot, cam["target"], t), aim)
    move = cam["move"]
    pos, target = start, tgt_t
    if move == "static":
        target = tgt0
    elif move in ("push-in", "pull-out"):
        if "to" in cam:
            end = cam["to"]
        else:
            toward = _sub(tgt0, start)
            amt = cam.get("amount", 0.3)
            end = _add(start, _mul(toward, amt if move == "push-in" else -amt))
        pos = _lerp(start, end, k)
    elif move in ("pan", "tilt"):
        if "target_to" in cam:
            target = _lerp(tgt0, _add(_point(shot, cam["target_to"], t1), aim), k)
        else:
            view = _sub(tgt0, start)
            deg = cam.get("degrees", MOVE_DEGREES[move]) * k
            view = _rot_z(view, deg) if move == "pan" else _tilt(view, deg)
            target = _add(start, view)
    elif move == "orbit":
        centre = tgt_t
        off = _sub(start, tgt0)
        pos = _add(centre, _rot_z(off, cam.get("degrees", MOVE_DEGREES["orbit"]) * k))
    elif move == "dolly":
        delta = _mul(_sub(cam["to"], start), k)
        pos, target = _add(start, delta), _add(tgt0, delta)
    elif move == "crane":
        end = cam["to"] if "to" in cam else _add(start, [0.0, 0.0, cam.get("rise", 2.0)])
        pos = _lerp(start, end, k)
    elif move == "track":
        follow = _sub(tgt_t, tgt0)
        drift = _mul(_sub(cam["to"], start), k) if "to" in cam else [0.0, 0.0, 0.0]
        pos = _add(_add(start, follow), drift)
    lens = cam.get("lens", 35.0)
    if "lens_to" in cam:
        lens = lens + (cam["lens_to"] - lens) * k
    return {"pos": pos, "target": target, "lens": float(lens), "roll": float(cam.get("roll", 0.0))}


# ------------------------------------------------------------------ files
def load(path):
    """(data, errors) of a shot3d.json file; errors already as 'path: reason'."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        return None, [f"(file): cannot read {path}: {e.strerror or e}"]
    except ValueError as e:
        return None, [f"(file): not valid JSON: {e}"]
    return data, validate(data, os.path.dirname(os.path.abspath(path)))


def summary(shot, preview=False):
    """One line describing a normalized shot."""
    w, h, fps, n = timeline(shot, preview)
    assets = ", ".join(f"{a['id']}={a['src']}" for a in shot["assets"])
    return (f"{w}x{h} {fps} fps {n} frames ({shot['seconds']} s) · look {shot['look']} · engine {shot['engine']} · "
            f"camera {shot['camera']['move']} · assets {assets} · passes {','.join(shot['passes']) or 'none'}")
