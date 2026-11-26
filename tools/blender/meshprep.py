"""Inside Blender 5.x (headless): turn a raw image-to-3D GLB (Hunyuan3D: a triangle soup, not watertight, loose debris)
into a sculpt blank. Run by tools/blender/blender.py mesh-prep, never by hand:

  blender -b --factory-startup --python-exit-code 1 -P tools/blender/meshprep.py -- --glb RAW.glb --out DIR
          --name NAME [--voxel auto|SIZE|0] [--quad-faces N] [--decimate N] [--min-island F]

1. import the GLB, join its meshes, apply transforms (Blender axes: Z up; the concept view is seen from -Y);
2. voxel remesh (Remesh modifier, VOXEL; auto size = longest side / 300, ~1.3 cm on a 4 m creature): closes the holes
   and the surface-net seams, one manifold skin;
3. drop loose parts smaller than F (share of the vertices, default 0.002): debris of broken thin parts;
4. retopology: QuadriFlow to N quads (default 20000; edge flow, no rig loops yet), or --decimate N triangles, or
   neither (--quad-faces 0); QuadriFlow that fails falls back to decimate (prep.json says so);
5. write DIR/<NAME>_prep.glb (shape only), DIR/<NAME>_prep.blend (the prep mesh with a clay material + the raw mesh
   hidden in collection "source", the bake source) and DIR/prep.json (counts per stage, seconds, Blender version).
Existing files are never replaced (exit 1). Progress lines start with "film-blender: ".
Adapted from the owner's trial script blender_h3d.py (projects/.../film3d-blender/hunyuan3d/, the lab's own code):
import/join/transform handling; the remesh steps are new.
"""
import json
import os
import sys
import time

import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def opt(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def say(msg):
    print(f"film-blender: {msg}", flush=True)


GLB = os.path.abspath(opt("--glb"))
OUT = os.path.abspath(opt("--out"))
NAME = opt("--name") or os.path.splitext(os.path.basename(GLB))[0]
VOXEL = opt("--voxel", "auto")
QUAD = int(opt("--quad-faces", "20000"))
DEC = int(opt("--decimate", "0"))
MIN_ISLAND = float(opt("--min-island", "0.002"))
FILES = {"glb": f"{NAME}_prep.glb", "blend": f"{NAME}_prep.blend", "json": "prep.json"}


def counts(ob):
    import numpy as np
    me = ob.data
    lt = np.zeros(len(me.polygons), dtype=np.int32)
    me.polygons.foreach_get("loop_total", lt)
    return {"verts": len(me.vertices), "faces": len(me.polygons), "tris": int((lt - 2).sum()),
            "quads": int((lt == 4).sum()), "dims": [round(x, 4) for x in ob.dimensions]}


def activate(ob):
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob


def import_glb():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    bpy.ops.import_scene.gltf(filepath=GLB)
    obs = [o for o in sc.objects if o.type == "MESH"]
    if not obs:
        raise SystemExit(f"no mesh in {GLB}")
    bpy.ops.object.select_all(action="DESELECT")
    for o in obs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = obs[0]
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    if len(obs) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    for o in [o for o in sc.objects if o.type != "MESH"]:      # the glTF hierarchy's empties
        bpy.data.objects.remove(o, do_unlink=True)
    activate(ob)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    ob.rotation_mode = "XYZ"            # the importer leaves QUATERNION: a later rotation_euler would be ignored
    ob.data.materials.clear()
    attrs = ob.data.attributes          # projected colours of the raw mesh mean nothing after a remesh
    for name in [a.name for a in attrs if a.name.startswith(("Color", "Col")) and not a.is_internal]:
        attrs.remove(attrs[name])
    return ob


def apply_modifier(ob, kind, **props):
    m = ob.modifiers.new(kind.title(), kind)
    for k, v in props.items():
        setattr(m, k, v)
    activate(ob)
    bpy.ops.object.modifier_apply(modifier=m.name)


def drop_islands(ob, share):
    """Separate loose parts, delete those under `share` of the vertices, join the rest. -> (kept, removed, verts)."""
    total = len(ob.data.vertices)
    activate(ob)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.separate(type="LOOSE")
    bpy.ops.object.mode_set(mode="OBJECT")
    parts = [o for o in bpy.context.selected_objects if o.type == "MESH"]
    parts.sort(key=lambda o: len(o.data.vertices), reverse=True)
    keep = [o for i, o in enumerate(parts) if i == 0 or len(o.data.vertices) >= share * total]
    gone = [o for o in parts if o not in keep]
    removed_verts = sum(len(o.data.vertices) for o in gone)
    for o in gone:
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.object.select_all(action="DESELECT")
    for o in keep:
        o.select_set(True)
    bpy.context.view_layer.objects.active = keep[0]
    if len(keep) > 1:
        bpy.ops.object.join()
    return bpy.context.view_layer.objects.active, len(keep), len(gone), removed_verts


def clay(ob):
    m = bpy.data.materials.new("Clay")
    m.use_nodes = True
    p = m.node_tree.nodes.get("Principled BSDF")
    if p:
        p.inputs["Base Color"].default_value = (0.49, 0.45, 0.40, 1.0)
        p.inputs["Roughness"].default_value = 0.55
    ob.data.materials.clear()
    ob.data.materials.append(m)


def export_glb(ob, path):
    activate(ob)
    kw = dict(filepath=path, export_format="GLB", use_selection=True, export_apply=True, export_yup=True)
    try:
        bpy.ops.export_scene.gltf(export_materials="NONE", **kw)
    except TypeError:                   # an exporter without that option
        bpy.ops.export_scene.gltf(**kw)


def main():
    for f in FILES.values():
        if os.path.exists(os.path.join(OUT, f)):
            raise SystemExit(f"refusing: {os.path.join(OUT, f)} exists (nothing is overwritten)")
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    rep = {"tool": "tools/blender/meshprep.py", "blender": bpy.app.version_string, "glb": GLB, "name": NAME,
           "stages": {}, "seconds": {}, "notes": []}
    raw = import_glb()
    raw.name = f"{NAME}_raw"
    rep["stages"]["import"] = counts(raw)
    rep["seconds"]["import"] = round(time.time() - t0, 1)
    say(f"imported {rep['stages']['import']['tris']} tris, {rep['stages']['import']['verts']} verts")
    ob = raw.copy()
    ob.data = raw.data.copy()
    ob.name = f"{NAME}_prep"
    bpy.context.scene.collection.objects.link(ob)
    longest = max(ob.dimensions) or 1.0
    voxel = longest / 300.0 if VOXEL == "auto" else float(VOXEL)
    rep["voxel_size"] = round(voxel, 6)
    if voxel > 0:
        t = time.time()
        apply_modifier(ob, "REMESH", mode="VOXEL", voxel_size=voxel, adaptivity=0.0, use_smooth_shade=True)
        rep["stages"]["voxel"] = counts(ob)
        rep["seconds"]["voxel"] = round(time.time() - t, 1)
        say(f"voxel remesh {voxel:.5g}: {rep['stages']['voxel']['faces']} faces")
    if MIN_ISLAND > 0:
        t = time.time()
        ob, kept, removed, rv = drop_islands(ob, MIN_ISLAND)
        rep["stages"]["islands"] = {"kept": kept, "removed": removed, "removed_verts": rv, "min_share": MIN_ISLAND}
        rep["seconds"]["islands"] = round(time.time() - t, 1)
        say(f"loose parts: kept {kept}, removed {removed} ({rv} verts)")
    ob.name = f"{NAME}_prep"
    t = time.time()
    method, target = "none", None
    if DEC > 0:
        method, target = "decimate", DEC
    elif QUAD > 0:
        method, target = "quadriflow", QUAD
        before = len(ob.data.polygons)
        activate(ob)
        try:
            res = bpy.ops.object.quadriflow_remesh(mode="FACES", target_faces=QUAD, use_mesh_symmetry=False,
                                                   use_preserve_sharp=False, use_preserve_boundary=False,
                                                   smooth_normals=True, seed=0)
            ok = "FINISHED" in res and len(ob.data.polygons) != before
        except (RuntimeError, TypeError) as e:
            ok, res = False, str(e).strip().splitlines()[-1:]
        if not ok:
            rep["notes"].append(f"QuadriFlow failed ({res}): decimated to {QUAD * 2} triangles instead")
            say(rep["notes"][-1])
            method, target = "decimate (quadriflow failed)", QUAD * 2
    if method.startswith("decimate"):
        tris = counts(ob)["tris"]
        apply_modifier(ob, "DECIMATE", decimate_type="COLLAPSE", ratio=min(1.0, target / max(1, tris)))
    rep["retopo"] = {"method": method, "target": target}
    rep["seconds"]["retopo"] = round(time.time() - t, 1)
    for p in ob.data.polygons:
        p.use_smooth = True
    rep["stages"]["final"] = counts(ob)
    say(f"retopo {method}: {rep['stages']['final']['faces']} faces ({rep['stages']['final']['quads']} quads)")
    clay(ob)
    export_glb(ob, os.path.join(OUT, FILES["glb"]))
    src = bpy.data.collections.new("source")
    bpy.context.scene.collection.children.link(src)
    for c in list(raw.users_collection):
        c.objects.unlink(raw)
    src.objects.link(raw)
    raw.hide_render = raw.hide_viewport = True
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, FILES["blend"]), compress=True)
    rep["files"] = FILES
    rep["seconds"]["total"] = round(time.time() - t0, 1)
    with open(os.path.join(OUT, FILES["json"]), "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=1)
    say(f"done in {rep['seconds']['total']} s")


main()
