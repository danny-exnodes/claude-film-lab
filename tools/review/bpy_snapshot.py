"""Snapshot the model being built in Blender to the review server (runs inside Blender 5.x; tools/review/README.md).

    import importlib.util, sys
    sys.path.insert(0, "<lab>/tools/review")
    from client import Review
    from bpy_snapshot import snapshot
    rv = Review("my-build", "Thuyền", "model", expected_steps=12)
    ...build some geometry...
    snapshot(rv, "hull")                 # -> <media>/my-build/step_01.glb + a step event with vertex/face counts

snapshot() exports the scene (or only `objects`, plus their parents) as GLB with bpy.ops.export_scene.gltf straight
into the build's media folder (no copy), counts vertices/faces of the evaluated meshes, optionally renders a small
Workbench thumbnail (JPEG q82: light on the public tunnel's bandwidth), and posts the step. It never raises: an export or post that fails is reported and returns None.
"""
import os
import sys
import time

import bpy


def mesh_stats(objects):
    """{'objects', 'verts', 'faces', 'tris'} of the evaluated mesh objects."""
    dg = bpy.context.evaluated_depsgraph_get()
    n = v = f = t = 0
    for ob in objects:
        if ob.type != "MESH":
            continue
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        try:
            n += 1
            v += len(me.vertices)
            f += len(me.polygons)
            t += sum(len(p.vertices) - 2 for p in me.polygons)
        finally:
            ev.to_mesh_clear()
    return {"objects": n, "verts": v, "faces": f, "tris": t}


def _with_parents(objects):
    out = []
    for ob in objects:
        while ob is not None and ob not in out:
            out.append(ob)
            ob = ob.parent
    return out


def export_glb(path, objects=None, animations=False):
    """Export to path (.glb). objects=None: every object of the scene (cameras and lights are left out).

    Without animations the skeleton is NOT exported (export_skins=False): the armature deformation is then baked into
    the mesh by export_apply, so a posed model looks posed. With a skin and no animation, viewers show the unbent rest
    pose, and parts baked in the posed shape (hair proxies, children of bones) float away from it."""
    kw = dict(filepath=path, export_format="GLB", export_apply=True, export_yup=True, export_materials="EXPORT",
              export_animations=bool(animations), export_skins=bool(animations), export_cameras=False,
              export_lights=False, export_extras=False, use_selection=False)
    if objects is not None:
        keep = set(_with_parents(objects))
        for ob in bpy.context.scene.objects:
            ob.select_set(ob in keep)
        kw["use_selection"] = True
    bpy.ops.export_scene.gltf(**kw)
    return path


def thumbnail(path, size=320, quality=82):
    """A small Workbench render of the scene camera's view to path (a JPEG, quality 82). -> path or None."""
    scene = bpy.context.scene
    if scene.camera is None:
        return None
    r = scene.render
    saved = (r.engine, r.resolution_x, r.resolution_y, r.resolution_percentage, r.filepath,
             r.image_settings.file_format, r.film_transparent, r.image_settings.quality)
    try:
        r.engine = "BLENDER_WORKBENCH"
        sh = scene.display.shading
        sh.light = "STUDIO"
        sh.color_type = "MATERIAL"
        sh.show_cavity = True
        r.resolution_x = r.resolution_y = size
        r.resolution_percentage = 100
        r.image_settings.file_format = "JPEG"
        r.image_settings.quality = quality
        r.film_transparent = False                   # JPEG has no alpha: the world colour behind the model
        r.filepath = path
        bpy.ops.render.render(write_still=True)
        return path if os.path.isfile(path) else None
    finally:
        (r.engine, r.resolution_x, r.resolution_y, r.resolution_percentage, r.filepath,
         r.image_settings.file_format, r.film_transparent, r.image_settings.quality) = saved


def snapshot(review, label, objects=None, *, thumb=False, extra_stats=None, animations=False):
    """Export step_<NN>.glb (+ step_<NN>.jpg when thumb) into the build's media folder and post a step.
    -> the step number, or None when nothing could be exported."""
    t0 = time.monotonic()
    n = review.n + 1
    try:
        folder = review.media_dir()
        glb = os.path.join(folder, f"step_{n:02d}.glb")
        if os.path.exists(glb):                      # never overwrite: a re-run of the same build gets new names
            k = 2
            while os.path.exists(os.path.join(folder, f"step_{n:02d}-{k}.glb")):
                k += 1
            glb = os.path.join(folder, f"step_{n:02d}-{k}.glb")
        objs = list(objects) if objects is not None else [o for o in bpy.context.scene.objects]
        export_glb(glb, objects, animations)
        stats = mesh_stats(objs)
        prev = getattr(review, "_bpy_prev", None) or {"verts": 0, "faces": 0}
        stats["new_verts"] = stats["verts"] - prev["verts"]
        stats["new_faces"] = stats["faces"] - prev["faces"]
        stats["export_s"] = round(time.monotonic() - t0, 2)
        stats["glb_bytes"] = os.path.getsize(glb)
        review._bpy_prev = stats
        if extra_stats:
            stats.update(extra_stats)
        image = None
        if thumb:
            try:
                image = thumbnail(os.path.splitext(glb)[0] + ".jpg")
            except Exception as e:                  # no GPU context in this session: the step goes without one
                print(f"review: thumbnail skipped ({type(e).__name__}: {e})", file=sys.stderr)
        review.step(label, glb=glb, image=image, stats=stats, n=n)
        return n
    except Exception as e:
        print(f"review: snapshot {label!r} failed ({type(e).__name__}: {e})", file=sys.stderr)
        return None
