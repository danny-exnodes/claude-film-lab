"""Build and render one shot3d.json inside Blender 5.x (headless). Run by tools/blender/blender.py:

  blender -b --factory-startup --python-exit-code 1 -P tools/blender/scene.py -- --spec S --out D
          [--frames A:B | --frames 1,120] [--preview] [--engine eevee|cycles] [--passes depth,normal,line,mask|none]
          [--look L] [--samples N] [--size WxH] [--mp4 PATH]

Writes into --out: beauty/0001.png ... (8-bit RGB), depth/ (16-bit grey, the fixed depth_range of the spec mapped
near = white, far and sky = black; never normalized per frame), normal/ (16-bit RGB, camera space, 0.5 = 0; the sky is
(0.5, 0.5, 1)), line/ (8-bit grey, black edges on white from the normal and depth discontinuities), mask/<asset>/
(8-bit grey, the asset's visible coverage), render.json. --mp4 encodes the beauty frames with Blender's own FFmpeg
(blender.py asks for it only when no ffmpeg is on PATH).
A spec with `turntable` (blender.py turntable) turns that asset in place in front of a fixed camera framed on its
bounding box, builds a preset:cyc backdrop around both, adds studio lamps (`studio`) and writes still_<view>.png
before the beauty frames; render.json gets a `turntable` entry. Imported actions (.blend/glTF anim.action) play as an
NLA strip scaled to the action's own fps (render.json `actions`), so --preview keeps their timing.
Progress lines on stdout start with "film-blender:". Exit code 1 (via --python-exit-code) on any error.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import time

import bpy
import mathutils

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    sp = importlib.util.spec_from_file_location(f"film_blender_{name}", os.path.join(HERE, f"{name}.py"))
    mod = importlib.util.module_from_spec(sp)
    sys.modules[sp.name] = mod
    sp.loader.exec_module(mod)
    return mod


spec = _load("spec")
looks = _load("looks")
presets = _load("presets")


def say(msg):
    print(f"film-blender: {msg}", flush=True)


def parse(argv):
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser(prog="scene.py")
    p.add_argument("--spec", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--frames", default=None)
    p.add_argument("--preview", action="store_true")
    p.add_argument("--engine", choices=spec.ENGINES, default=None)
    p.add_argument("--passes", default=None)
    p.add_argument("--look", default=None)
    p.add_argument("--samples", type=int, default=None)
    p.add_argument("--size", default=None)
    p.add_argument("--mp4", default=None)
    return p.parse_args(argv)


# ------------------------------------------------------------------ assets
def _prim(kind, aid, coll):
    import bmesh
    bm = bmesh.new()
    if kind == "cube":
        bmesh.ops.create_cube(bm, size=1.0)
    elif kind == "sphere":
        bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=0.5)
    elif kind == "ico":
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=0.5)
    elif kind in ("cylinder", "cone"):
        bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=0.5, radius2=0.5 if kind == "cylinder" else 0.0,
                              depth=1.0)
    elif kind == "plane":
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
    elif kind == "torus":
        bm.free()
        verts, faces = [], []
        R, r, n, m = 0.375, 0.125, 32, 12
        for i in range(n):
            a = 2 * math.pi * i / n
            for j in range(m):
                b = 2 * math.pi * j / m
                verts.append(((R + r * math.cos(b)) * math.cos(a), (R + r * math.cos(b)) * math.sin(a), r * math.sin(b)))
        for i in range(n):
            for j in range(m):
                faces.append((i * m + j, ((i + 1) % n) * m + j, ((i + 1) % n) * m + (j + 1) % m, i * m + (j + 1) % m))
        me = bpy.data.meshes.new(f"{aid}.{kind}")
        me.from_pydata(verts, [], faces)
        me.shade_smooth()
        ob = bpy.data.objects.new(me.name, me)
        coll.objects.link(ob)
        return ob
    me = bpy.data.meshes.new(f"{aid}.{kind}")
    bm.to_mesh(me)
    bm.free()
    if kind in ("sphere", "ico", "cylinder", "cone"):
        me.shade_smooth()
    ob = bpy.data.objects.new(me.name, me)
    coll.objects.link(ob)
    return ob


def _base_color(mat):
    """sRGB hex of a glTF material's base colour (mean of its texture when there is one)."""
    try:
        node = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        sock = node.inputs["Base Color"]
        if sock.is_linked and sock.links[0].from_node.type == "TEX_IMAGE" and sock.links[0].from_node.image:
            import numpy as np
            img = sock.links[0].from_node.image
            px = np.empty(len(img.pixels), dtype=np.float32)
            img.pixels.foreach_get(px)
            c = px.reshape(-1, 4)[:, :3].mean(axis=0)
            c = [looks.srgb_to_linear(x) for x in c]       # pixels are sRGB-encoded floats
        else:
            c = list(sock.default_value)[:3]
        enc = [(1.055 * x ** (1 / 2.4) - 0.055) if x > 0.0031308 else 12.92 * x for x in c]
        return "#" + "".join(f"{max(0, min(255, round(v * 255))):02x}" for v in enc)
    except (StopIteration, AttributeError, KeyError):
        return None


def _descendants(ob):
    out = []
    for c in ob.children:
        out.append(c)
        out += _descendants(c)
    return out


ACTIONS = {}            # asset id -> how its imported action is timed (render.json "actions")


def build_asset(a, k, base_dir, seed, coll, render_fps=24, shot_fps=24):
    """-> (root, rig, meshes). An imported action (.blend/glTF anim.action) plays in shot seconds at its own fps
    (render_fps only sets the NLA scale), so --preview (12 fps) has the same timing as the final render."""
    src = a["src"]
    rig = None
    if src.startswith("preset:"):
        root, rig = presets.build(src[7:], a["id"], a.get("params") or {}, seed + 97 * k, coll)
    elif src.startswith("prim:"):
        root = presets._empty(a["id"], coll)
        ob = _prim(src[5:], a["id"], coll)
        ob.parent = root
        ob["film_role"] = "prim"
    else:
        blend = spec.blend_src(src)
        is_blend = blend[0].lower().endswith(".blend")
        path = blend[0] if is_blend else src
        path = path if os.path.isabs(path) else os.path.join(base_dir, path)
        before = set(bpy.data.objects)
        anim = a.get("anim") or {}
        if is_blend:
            if anim.get("action"):
                act_fps, fps_from = (float(anim["fps"]), "anim.fps") if "fps" in anim else (_blend_fps(path), "blend scene")
                if act_fps is None:
                    act_fps, fps_from = float(shot_fps), "shot fps (the .blend scene fps was unreadable)"
            new = _append_blend(path, blend[1])
        else:
            # the glTF importer turns key times (seconds) into frames at the scene fps: import at the shot's fps
            sc = bpy.context.scene
            keep = sc.render.fps, sc.render.fps_base
            sc.render.fps, sc.render.fps_base = int(shot_fps), 1.0
            try:
                bpy.ops.import_scene.gltf(filepath=path)
            finally:
                sc.render.fps, sc.render.fps_base = keep
            new = [o for o in bpy.data.objects if o not in before]
            act_fps, fps_from = float(shot_fps), "glTF import"
        root = presets._empty(a["id"], coll)
        for o in new:
            for c in list(o.users_collection):
                c.objects.unlink(o)
            coll.objects.link(o)
        for o in new:
            if o.parent is None:
                o.parent = root
            if o.type == "MESH":
                o["film_role"] = "glb"
                col = next((_base_color(m) for m in o.data.materials if m), None)
                if col:
                    o["film_color"] = col
        if anim.get("action"):
            info = _assign_action(new, anim["action"], render_fps, act_fps, float(anim.get("speed", 1.0)))
            ACTIONS[a["id"]] = dict(info, fps_from=fps_from)
            say(f"action {anim['action']} of {a['id']}: {act_fps:g} fps ({fps_from}), NLA scale {info['scale']:.4g} "
                f"at {render_fps} fps")
        else:                                   # no action named: the asset stands still (the importer plays one)
            for o in new:
                if o.animation_data:
                    o.animation_data.action = None
    meshes = [o for o in _descendants(root) if o.type == "MESH"]
    if "fit" in a:
        _fit(root, meshes, a["fit"], coll)
    for o in _descendants(root):                # hair curves too: they belong to the asset's mask
        o.pass_index = k
    for o in meshes:
        if "color" in a and (not src.startswith("preset:") or o.get("film_role") in
                             ("mountain", "rock", "ground", "water", "foliage", "body", "tuft", "limb", "prim", "glb")):
            o["film_color"] = a["color"]
        if "ink" in a:
            o["film_ink"] = float(a["ink"])
        if a.get("lines") is False:
            o["film_lines"] = False
    return root, rig, meshes


def _append_blend(path, collection):
    """Append the objects of a .blend (all of them, or those of one collection, nested collections included) with
    their materials, modifiers, geometry nodes and hair curves. -> the new objects (not linked to a scene yet)."""
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        if collection:
            if collection not in src.collections:
                raise RuntimeError(f"collection {collection!r} is not in {os.path.basename(path)} "
                                   f"({', '.join(src.collections) or 'none'})")
            dst.collections = [collection]
        else:
            dst.objects = list(src.objects)
    if collection:
        return list(dst.collections[0].all_objects)
    return [o for o in dst.objects if o is not None]


def _blend_fps(path):
    """Frame rate (fps / fps_base) of the first scene of a .blend: the rate its actions were keyed at. None if unknown.
    The scene is linked only to read it, then its library is removed again."""
    try:
        with bpy.data.libraries.load(path, link=True) as (src, dst):
            if not src.scenes:
                return None
            dst.scenes = [src.scenes[0]]
        sc = dst.scenes[0]
        if sc is None:
            return None
        fps = sc.render.fps / (sc.render.fps_base or 1.0)
        lib = sc.library
        if lib is not None:
            bpy.data.libraries.remove(lib)
        return float(fps)
    except Exception as e:                                      # noqa: BLE001 - the caller falls back to the shot fps
        say(f"cannot read the scene fps of {os.path.basename(path)} ({type(e).__name__}: {e})")
        return None


def _assign_action(objects, name, render_fps, action_fps, speed=1.0):
    """Play `name` on the asset's animated objects (and armatures) as one NLA strip from scene frame 1 (t = 0),
    scaled so action frame = start + t * action_fps * speed at every render fps (spec.nla_scale). Tracks the asset
    brought are muted. -> {"action", "fps", "start", "end", "scale", "speed", "objects"}."""
    act = bpy.data.actions.get(name)
    if act is None:
        raise RuntimeError(f"action {name!r} is not in the asset file ({', '.join(a.name for a in bpy.data.actions) or 'none'})")
    start, end = (float(x) for x in act.frame_range)
    scale = spec.nla_scale(render_fps, action_fps, speed)
    n = 0
    for o in objects:
        if o.animation_data is None and o.type != "ARMATURE":
            continue
        ad = o.animation_data_create()
        ad.action = None
        for tr in ad.nla_tracks:
            tr.mute = True
        tr = ad.nla_tracks.new()
        tr.name = "film_action"
        st = tr.strips.new(act.name, 1, act)
        slots = getattr(st, "action_suitable_slots", None)
        if slots and getattr(st, "action_slot", None) is None:
            st.action_slot = slots[0]
        st.action_frame_start, st.action_frame_end = start, end
        st.scale = scale
        st.extrapolation = "HOLD"
        st.blend_type = "REPLACE"
        n += 1
    return {"action": name, "fps": float(action_fps), "start": start, "end": end, "scale": round(scale, 6),
            "speed": float(speed), "objects": n}


def _bbox(objects):
    """World (lo, hi) of the evaluated objects (meshes, hair curves; armature deformation included), or None."""
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    lo = mathutils.Vector((1e18,) * 3)
    hi = mathutils.Vector((-1e18,) * 3)
    for o in objects:
        ev = o.evaluated_get(dg)
        for c in ev.bound_box:
            w = ev.matrix_world @ mathutils.Vector(c)
            lo = mathutils.Vector(map(min, lo, w))
            hi = mathutils.Vector(map(max, hi, w))
    return (lo, hi) if hi.x >= lo.x else None


def _fit(root, meshes, size, coll):
    """Scale the asset's children so the largest side is `size` metres (None: keep the size), centred on x/y,
    standing on z = 0."""
    box = _bbox(meshes)
    if box is None:
        return
    lo, hi = box
    dim = max(hi - lo)
    if dim <= 0:
        return
    s = 1.0 if size is None else size / dim
    holder = presets._empty(f"{root.name}.fit", coll, parent=root)
    for c in list(root.children):
        if c is not holder:
            mw = c.matrix_world.copy()
            c.parent = holder
            c.matrix_world = mw
    holder.scale = (s, s, s)
    holder.location = (-(lo.x + hi.x) / 2 * s, -(lo.y + hi.y) / 2 * s, -lo.z * s)


# ------------------------------------------------------------------ turntable (blender.py turntable)
# Studio light of a realistic turntable (fixed to the camera, the asset turns): warm key from the front left, cool
# fill from the front right, cool rim from behind. Sun lamps: the same light at every asset size.
STUDIO_SUNS = (("film_key", 3.2, (50.0, 0.0, -35.0), (1.0, 0.93, 0.84)),
               ("film_fill", 0.8, (70.0, 0.0, 45.0), (0.85, 0.9, 1.0)),
               ("film_rim", 1.6, (60.0, 0.0, 160.0), (0.85, 0.9, 1.0)))


def turntable_setup(shot, built, coll, seed, render_size):
    """Stand the turntable asset centred on the turn axis (x = y = 0, on z = 0; `fit` scales it, else its own size),
    frame the fixed camera on its bounding box and build the cyc around both. -> state for pose() and the stills."""
    tt = shot["turntable"]
    asset, root = next((a, r) for a, r, _ in built if a["id"] == tt["asset"])
    root.scale = spec.scale3(asset["scale"])
    parts = [o for o in _descendants(root) if o.type in ("MESH", "CURVES")]
    meshes = [o for o in parts if o.type == "MESH"] or parts
    if not parts:
        raise RuntimeError(f"turntable asset {asset['id']!r} has no mesh")
    if "fit" not in asset:
        _fit(root, meshes, None, coll)
    lo, hi = _bbox(parts)
    lo, hi = list(lo), list(hi)
    cam = spec.turntable_camera(lo, hi, shot["size"], tt["lens"], tt["fill"], render_size)
    if tt["backdrop"] == "cyc":
        params = spec.cyc_params(cam, shot["size"], render_size)
        croot, _ = presets.build("cyc", "film_cyc", params, seed, coll)
        for o in _descendants(croot):
            o["film_lines"] = False
    say(f"turntable: {asset['id']} {cam['height']:.3g} m tall, turn radius {cam['radius']:.3g} m, camera "
        f"{cam['distance']:.3g} m away ({tt['lens']:g} mm, fill {tt['fill']:g}), backdrop {tt['backdrop']}")
    return {"tt": tt, "asset": asset, "root": root, "meshes": meshes, "lo": lo, "hi": hi, "camera": cam}


def _studio(sc, keep_world):
    """Three sun lamps (STUDIO_SUNS); without an HDRI the sky of the look becomes a flat mid grey (no horizon tint)."""
    if not keep_world and sc.world and sc.world.node_tree:
        nt = sc.world.node_tree
        bg = next((n for n in nt.nodes if n.type == "BACKGROUND"), None)
        if bg:
            for link in list(bg.inputs["Color"].links):
                nt.links.remove(link)
            bg.inputs["Color"].default_value = (0.5, 0.5, 0.5, 1.0)
            bg.inputs["Strength"].default_value = 0.35
    for name, energy, rot, col in STUDIO_SUNS:
        light = bpy.data.lights.new(name, "SUN")
        light.energy = energy
        light.angle = math.radians(8.0)
        light.color = col
        ob = bpy.data.objects.new(name, light)
        sc.collection.objects.link(ob)
        ob.rotation_euler = tuple(math.radians(x) for x in rot)


def _head_point(state, bone_name):
    """(point, region size m, how) of the head close-up: the `bone_name` bone of the asset's armature (exact name,
    else a bone whose name contains it), else the top 45 % of the asset (centred on its vertices above 60 % height)."""
    import numpy as np
    root, h = state["root"], state["camera"]["height"]
    want = bone_name.lower()
    bpy.context.view_layer.update()
    for arm in (o for o in _descendants(root) if o.type == "ARMATURE"):
        bones = list(arm.pose.bones)
        pb = next((b for b in bones if b.name.lower() == want), None) or \
            next((b for b in bones if want in b.name.lower()), None)
        if pb:
            head, tail = arm.matrix_world @ pb.head, arm.matrix_world @ pb.tail
            point = head + (tail - head) * 0.35
            return list(point), max(2.5 * (tail - head).length, 0.08 * h), f"bone {pb.name}"
    dg = bpy.context.evaluated_depsgraph_get()
    lo_z = min(state["lo"][2], state["hi"][2])
    cut = lo_z + 0.6 * h
    pts = []
    for o in state["meshes"]:
        if o.type != "MESH":
            continue
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        co = np.empty(len(me.vertices) * 3, dtype=np.float64)
        me.vertices.foreach_get("co", co)
        ev.to_mesh_clear()
        m = np.array(ev.matrix_world)
        w = co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
        pts.append(w[w[:, 2] >= cut])
    pts = np.concatenate(pts) if pts else np.zeros((0, 3))
    x, y = (float(v) for v in pts[:, :2].mean(axis=0)) if len(pts) else (0.0, 0.0)
    return [x, y, lo_z + 0.8 * h], 0.45 * h, "top of the bounding box"


# ------------------------------------------------------------------ engine, camera, compositor
def setup_engine(sc, engine, samples, seed):
    if engine == "eevee":
        sc.render.engine = "BLENDER_EEVEE"
        sc.eevee.taa_render_samples = samples
        return "GPU (EEVEE)"
    sc.render.engine = "CYCLES"
    sc.cycles.samples = samples
    sc.cycles.seed = seed
    sc.cycles.use_animated_seed = True
    sc.cycles.use_adaptive_sampling = False
    sc.cycles.use_denoising = True
    sc.cycles.denoiser = "OPENIMAGEDENOISE"
    if hasattr(sc.cycles, "denoising_use_gpu"):
        sc.cycles.denoising_use_gpu = False
    want = os.environ.get("FILM_BLENDER_DEVICE", "auto").upper()
    prefs = bpy.context.preferences.addons["cycles"].preferences
    if want in ("AUTO", "GPU", "OPTIX", "CUDA"):
        for kind in (("OPTIX", "CUDA") if want in ("AUTO", "GPU") else (want,)):
            try:
                prefs.compute_device_type = kind
            except TypeError:
                continue
            prefs.get_devices()
            gpus = [d for d in prefs.devices if d.type == kind]
            if gpus:
                for d in prefs.devices:
                    d.use = d.type == kind
                sc.cycles.device = "GPU"
                return f"{kind}: {gpus[0].name}"
    prefs.compute_device_type = "NONE"
    sc.cycles.device = "CPU"
    return "CPU"


def sensor_height(size):
    """Vertical sensor extent (mm) of the spec's own frame with a 36 mm sensor fitted to its longer side."""
    w, h = size
    return 36.0 * h / w if w >= h else 36.0


def place_camera(cam, c):
    pos = mathutils.Vector(c["pos"])
    d = mathutils.Vector(c["target"]) - pos
    if d.length < 1e-9:
        d = mathutils.Vector((0, 1, 0))
    q = d.to_track_quat("-Z", "Y")
    if c["roll"]:
        q = q @ mathutils.Quaternion((0, 0, 1), math.radians(c["roll"]))
    cam.location = pos
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = q
    cam.data.lens = c["lens"]


def _fo(ng, directory, depth, mode):
    fo = ng.nodes.new("CompositorNodeOutputFile")
    fo.directory = directory
    fo.file_name = "0001"
    fo.format.media_type = "IMAGE"
    fo.format.file_format = "PNG"
    fo.format.color_mode = mode
    fo.format.color_depth = depth
    # raw data values: no view transform, no sRGB curve (5.x: the node's save_as_render plus a Non-Color override)
    fo.save_as_render = False
    fo.format.color_management = "OVERRIDE"
    fo.format.linear_colorspace_settings.name = "Non-Color"
    item = fo.file_output_items.new("RGBA" if mode != "BW" else "FLOAT", "")
    item.save_as_render = False
    return fo


def _m(ng, op, a, b=0.0, c=0.0, clamp=False):
    node = ng.nodes.new("ShaderNodeMath")
    node.operation = op
    node.use_clamp = clamp
    for sock, v in ((node.inputs[0], a), (node.inputs[1], b), (node.inputs[2], c)):
        if isinstance(v, (int, float)):
            sock.default_value = v
        else:
            ng.links.new(v, sock)
    return node.outputs[0]


def _maprange(ng, v, a, b, c, d, interp="LINEAR"):
    node = ng.nodes.new("ShaderNodeMapRange")
    node.interpolation_type = interp
    node.clamp = True
    ng.links.new(v, node.inputs["Value"])
    for name, x in (("From Min", a), ("From Max", b), ("To Min", c), ("To Max", d)):
        node.inputs[name].default_value = x
    return node.outputs["Result"]


def _noise(ng, vec, scale, detail):
    node = ng.nodes.new("ShaderNodeTexNoise")
    node.noise_dimensions = "2D"
    node.inputs["Scale"].default_value = scale
    node.inputs["Detail"].default_value = detail
    node.inputs["Roughness"].default_value = 0.6
    ng.links.new(vec, node.inputs["Vector"])
    return node.outputs["Fac"]


def setup_compositor(sc, out, passes, masks, depth_range, grain, height):
    """Beauty (with paper grain when the look has it) to the render result; one File Output node per pass."""
    vl = sc.view_layers[0]
    vl.use_pass_z = True
    for name, kind in [("film_normal", "COLOR"), ("film_cover", "VALUE")] + [(f"film_m{k}", "VALUE") for k, _ in masks]:
        aov = vl.aovs.add()
        aov.name, aov.type = name, kind
    ng = bpy.data.node_groups.new("film_comp", "CompositorNodeTree")
    sc.compositing_node_group = ng
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    rl = ng.nodes.new("CompositorNodeRLayers")
    go = ng.nodes.new("NodeGroupOutput")
    beauty = rl.outputs["Image"]
    if grain > 0:
        ic = ng.nodes.new("CompositorNodeImageCoordinates")
        ng.links.new(beauty, ic.inputs["Image"])
        px = ng.nodes.new("ShaderNodeVectorMath")
        px.operation = "SCALE"
        ng.links.new(ic.outputs["Pixel"], px.inputs[0])
        px.inputs["Scale"].default_value = 1080.0 / height
        coarse = _noise(ng, px.outputs[0], 0.004, 3.0)
        fine = _noise(ng, px.outputs[0], 0.45, 1.0)
        fibre = ng.nodes.new("ShaderNodeVectorMath")
        fibre.operation = "MULTIPLY"
        ng.links.new(px.outputs[0], fibre.inputs[0])
        fibre.inputs[1].default_value = (0.04, 0.6, 1.0)
        fib = _noise(ng, fibre.outputs[0], 0.5, 2.0)
        g = _m(ng, "MULTIPLY_ADD", coarse, 0.5)
        g = _m(ng, "ADD", g, _m(ng, "MULTIPLY", fine, 0.3))
        g = _m(ng, "ADD", g, _m(ng, "MULTIPLY", fib, 0.2))       # ~0.5 mean
        # vignette: aged paper darkens toward the corners
        ln = ng.nodes.new("ShaderNodeVectorMath")
        ln.operation = "LENGTH"
        ng.links.new(ic.outputs["Normalized"], ln.inputs[0])
        vig = _maprange(ng, ln.outputs["Value"], 0.55, 1.35, 0.0, 1.0, "SMOOTHSTEP")
        val = _m(ng, "MULTIPLY_ADD", _m(ng, "SUBTRACT", g, 0.5), -2.0 * grain, 1.0)
        val = _m(ng, "SUBTRACT", val, _m(ng, "MULTIPLY", vig, grain * 1.4))
        mix = ng.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = 1.0
        ng.links.new(beauty, mix.inputs[6])
        ng.links.new(val, mix.inputs[7])
        beauty = mix.outputs[2]
    ng.links.new(beauty, go.inputs[0])
    outs = []
    near, far = depth_range
    depth = _maprange(ng, rl.outputs["Depth"], near, far, 1.0, 0.0)
    if "depth" in passes:
        fo = _fo(ng, os.path.join(out, "depth"), "16", "BW")
        ng.links.new(depth, fo.inputs[0])
        outs.append(fo)
    cover = rl.outputs["film_cover"]
    nmix = ng.nodes.new("ShaderNodeMix")
    nmix.data_type = "RGBA"
    nmix.clamp_factor = True
    ng.links.new(cover, nmix.inputs["Factor"])
    nmix.inputs[6].default_value = (0.5, 0.5, 1.0, 1.0)
    ng.links.new(rl.outputs["film_normal"], nmix.inputs[7])
    normal = nmix.outputs[2]
    if "normal" in passes:
        fo = _fo(ng, os.path.join(out, "normal"), "16", "RGB")
        ng.links.new(normal, fo.inputs[0])
        outs.append(fo)
    if "line" in passes:
        sob_n = ng.nodes.new("CompositorNodeFilter")
        sob_n.inputs["Type"].default_value = "Sobel"
        ng.links.new(normal, sob_n.inputs["Image"])
        bw = ng.nodes.new("CompositorNodeRGBToBW")
        ng.links.new(sob_n.outputs[0], bw.inputs[0])
        # depth edges on log depth: a jump in distance is an edge, a ground plane running to the horizon is not
        logd = _m(ng, "LOGARITHM", _m(ng, "MINIMUM", rl.outputs["Depth"], far * 50.0), 2.718281828)
        sob_d = ng.nodes.new("CompositorNodeFilter")
        sob_d.inputs["Type"].default_value = "Sobel"
        ng.links.new(logd, sob_d.inputs["Image"])
        bwd = ng.nodes.new("CompositorNodeRGBToBW")
        ng.links.new(sob_d.outputs[0], bwd.inputs[0])
        e = _m(ng, "MAXIMUM", bw.outputs[0], _m(ng, "MULTIPLY", bwd.outputs[0], 0.8))
        e = _maprange(ng, e, 0.18, 0.55, 1.0, 0.0, "SMOOTHSTEP")
        fo = _fo(ng, os.path.join(out, "line"), "8", "BW")
        ng.links.new(e, fo.inputs[0])
        outs.append(fo)
    if "mask" in passes:
        for k, aid in masks:
            fo = _fo(ng, os.path.join(out, "mask", aid), "8", "BW")
            ng.links.new(rl.outputs[f"film_m{k}"], fo.inputs[0])
            outs.append(fo)
    return outs


def encode_mp4(frames_dir, frames, fps, size, path):
    """H.264 mp4 of a PNG sequence with Blender's own FFmpeg (VSE)."""
    enc = bpy.data.scenes.new("film_mp4")
    enc.render.resolution_x, enc.render.resolution_y = size
    enc.render.resolution_percentage = 100
    enc.render.fps = fps
    enc.view_settings.view_transform = "Standard"
    se = enc.sequence_editor_create()
    names = [f"{f:04d}.png" for f in frames]
    strip = se.strips.new_image("frames", os.path.join(frames_dir, names[0]), 1, 1)
    for n in names[1:]:
        strip.elements.append(n)
    enc.frame_start, enc.frame_end = 1, len(names)
    im = enc.render.image_settings
    im.media_type = "VIDEO"
    im.file_format = "FFMPEG"
    ff = enc.render.ffmpeg
    ff.format = "MPEG4"
    ff.codec = "H264"
    ff.constant_rate_factor = "HIGH"
    ff.ffmpeg_preset = "GOOD"
    ff.audio_codec = "NONE"
    enc.render.use_sequencer = True
    enc.render.use_compositing = False
    enc.render.filepath = path
    bpy.ops.render.render(animation=True, scene=enc.name)
    # Blender may append the frame range to the name: move it to the asked path
    if not os.path.isfile(path):
        d = os.path.dirname(path)
        stem = os.path.splitext(os.path.basename(path))[0]
        cand = [f for f in os.listdir(d) if f.startswith(stem) and f.endswith(".mp4")]
        if cand:
            os.replace(os.path.join(d, cand[0]), path)


# ------------------------------------------------------------------ main
def main():
    a = parse(sys.argv)
    data, errors = spec.load(a.spec)
    if errors:
        for e in errors:
            print(f"film-blender: spec error {e}", file=sys.stderr)
        raise SystemExit(2)
    shot = spec.normalize(data)
    if a.look:
        if a.look not in spec.look_ids():
            raise SystemExit(f"unknown look {a.look}")
        shot["look"] = a.look
    if a.engine:
        shot["engine"] = a.engine
    if a.passes is not None:
        shot["passes"] = [] if a.passes in ("", "none") else [p for p in a.passes.split(",") if p]
    with open(os.path.join(HERE, "looks.json"), encoding="utf-8") as f:
        cfg = json.load(f)["looks"][shot["look"]]
    out = os.path.abspath(a.out)
    base_dir = os.path.dirname(os.path.abspath(a.spec))
    W, H, fps, n = spec.timeline(shot, a.preview)
    if a.size:
        W, H = (int(x) for x in a.size.lower().split("x"))
    frames = spec.parse_frames(a.frames, n) if a.frames else list(range(1, n + 1))
    engine = shot["engine"]
    samples = a.samples or shot.get("samples") or cfg["samples"][engine][1 if a.preview else 0]
    seed = int(shot["seed"])

    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
    sc.render.fps, sc.render.fps_base = fps, 1.0
    sc.frame_start, sc.frame_end = 1, n
    sc.render.use_motion_blur = False
    # no metadata stamps (date, render time...): the same frame must give the same bytes
    for name in dir(sc.render):
        if name.startswith("use_stamp"):
            try:
                setattr(sc.render, name, False)
            except (AttributeError, TypeError):
                pass
    sc.render.film_transparent = False
    sc.render.use_compositing = True
    sc.render.image_settings.media_type = "IMAGE"
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.image_settings.color_depth = "8"
    device = setup_engine(sc, engine, samples, seed)
    if engine == "cycles" and cfg.get("adaptive"):          # noise threshold: fewer samples where the frame is clean
        sc.cycles.use_adaptive_sampling = True
        sc.cycles.adaptive_threshold = float(cfg["adaptive"])
    if cfg.get("motion_blur"):
        sc.render.use_motion_blur = True
        sc.render.motion_blur_shutter = float(cfg["motion_blur"])

    coll = sc.collection
    built, masks = [], []
    for k, asset in enumerate(shot["assets"], 1):
        root, rig, meshes = build_asset(asset, k, base_dir, seed, coll, fps, shot["fps"])
        built.append((asset, root, rig))
        if asset.get("mask", True):
            masks.append((k, asset["id"]))
    cam = bpy.data.objects.new("film_camera", bpy.data.cameras.new("film_camera"))
    coll.objects.link(cam)
    sc.camera = cam
    cam.data.sensor_fit = "VERTICAL"
    cam.data.sensor_height = sensor_height(shot["size"])
    cam.data.sensor_width = 36.0
    cam.data.clip_start = min(0.05, shot["depth_range"][0] * 0.5)
    cam.data.clip_end = max(1000.0, shot["depth_range"][1] * 4)
    tstate = turntable_setup(shot, built, coll, seed, (W, H)) if shot.get("turntable") else None

    ctx = looks.Context(sc, cfg, shot, engine, masks, H / 1080.0)
    if "hdri" in shot["world"]:
        ctx.hdri_path = spec.resolve_hdri(shot["world"]["hdri"], shot.get("asset_root"), base_dir)
    for role, m in (shot.get("materials") or {}).items():
        m = {"tex": m} if isinstance(m, str) else m
        ctx.textures[role] = {"maps": spec.resolve_texture(m["tex"], shot.get("asset_root"), base_dir),
                              "scale": float(m.get("scale", 4.0)), "displace": float(m.get("displace", 0.0))}
    looks.apply(ctx, shot["look"], [o for o in bpy.data.objects if o.type == "MESH"])
    if tstate and tstate["tt"]["studio"]:
        _studio(sc, keep_world=bool(ctx.hdri_path))
    outs = setup_compositor(sc, out, shot["passes"], masks, shot["depth_range"], float(cfg.get("grain", 0)), H)

    def pose(f, turn=None):
        """turn: degrees of the turntable asset (default: its angle at frame f)."""
        t = spec.frame_time(f, fps)
        for asset, root, rig in built:
            root.location = spec.asset_position(asset, t)
            rot = [math.radians(x) for x in asset["rot"]]
            yaw = spec.path_heading(asset, t, 1.0 / fps)
            if yaw is not None:
                rot[2] += math.radians(yaw)
            if tstate and asset is tstate["asset"]:
                rot[2] += math.radians(spec.turntable_angle(tstate["tt"], f, n) if turn is None else turn)
            root.rotation_euler = rot
            root.scale = spec.scale3(asset["scale"])
            anim = asset.get("anim") or {}
            if rig and (anim.get("action") or rig["kind"] == "giot"):
                presets.animate(rig, anim.get("action", "idle"), t, anim.get("speed", 1.0))
        place_camera(cam, tstate["camera"] if tstate else spec.camera_at(shot, t, fps))

    os.makedirs(os.path.join(out, "beauty"), exist_ok=True)
    say(f"scene built: {W}x{H} {fps} fps, {len(frames)} of {n} frames, look {shot['look']}, engine {engine} "
        f"({device}), {samples} samples")
    stills = {}
    if tstate:
        tt = tstate["tt"]
        for view in tt["stills"]:
            sc.frame_set(1)
            pose(1, tt["front"] + spec.TURNTABLE_VIEWS[view])
            how = None
            if view == "head":
                point, size, how = _head_point(tstate, tt["head_bone"])
                place_camera(cam, spec.closeup_camera(point, size, shot["size"]))
            name = f"still_{view}.png"
            sc.render.filepath = os.path.join(out, name)
            t0 = time.perf_counter()
            bpy.ops.render.render(write_still=True)
            stills[view] = {"file": name, "degrees": round(tt["front"] + spec.TURNTABLE_VIEWS[view], 3),
                            "seconds": round(time.perf_counter() - t0, 3)}
            if how:
                stills[view]["head"] = how
            say(f"still {view} {stills[view]['seconds']:.2f} s" + (f" ({how})" if how else ""))
    times = []
    t_all = time.perf_counter()
    for i, f in enumerate(frames, 1):
        sc.frame_set(f)
        pose(f)
        for fo in outs:
            fo.file_name = f"{f:04d}"
        sc.render.filepath = os.path.join(out, "beauty", f"{f:04d}.png")
        t0 = time.perf_counter()
        bpy.ops.render.render(write_still=True)
        dt = time.perf_counter() - t0
        times.append(round(dt, 3))
        say(f"frame {f} ({i}/{len(frames)}) {dt:.2f} s")
    total = time.perf_counter() - t_all
    if engine == "eevee":
        try:
            import gpu
            device = f"GPU: {gpu.platform.renderer_get()} ({gpu.platform.backend_type_get()})"
        except Exception:                                     # noqa: BLE001 - the name is only informative
            pass
    mp4 = None
    if a.mp4:
        encode_mp4(os.path.join(out, "beauty"), frames, fps, (W, H), os.path.abspath(a.mp4))
        mp4 = {"file": os.path.relpath(os.path.abspath(a.mp4), out).replace(os.sep, "/"), "encoder": "blender"}
        say(f"mp4 {a.mp4}")
    with open(a.spec, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    info = {
        "tool": "tools/blender/scene.py", "spec": os.path.abspath(a.spec), "spec_sha256": sha,
        "blender": bpy.app.version_string, "engine": sc.render.engine, "device": device, "look": shot["look"],
        "size": [W, H], "fps": fps, "frame_count": n, "frames": [frames[0], frames[-1]] if frames == list(
            range(frames[0], frames[-1] + 1)) else frames, "preview": bool(a.preview), "samples": samples, "seed": seed,
        "passes": shot["passes"], "depth_range": shot["depth_range"], "masks": [aid for _, aid in masks],
        "camera": shot["camera"]["move"], "seconds_per_frame": times,
        "mean_seconds_per_frame": round(sum(times) / len(times), 3), "total_seconds": round(total, 2), "mp4": mp4,
    }
    if ACTIONS:
        info["actions"] = ACTIONS
    if tstate:
        c = tstate["camera"]
        info["turntable"] = {"asset": tstate["asset"]["id"], "fill": tstate["tt"]["fill"], "front": tstate["tt"]["front"],
                             "lens": c["lens"], "camera_distance_m": round(c["distance"], 3),
                             "height_m": round(c["height"], 3), "turn_radius_m": round(c["radius"], 3),
                             "backdrop": tstate["tt"]["backdrop"], "studio": tstate["tt"]["studio"], "stills": stills}
    with open(os.path.join(out, "render.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    say(f"done: {len(frames)} frames, {info['mean_seconds_per_frame']} s/frame -> {out}")


if __name__ == "__main__":
    main()
