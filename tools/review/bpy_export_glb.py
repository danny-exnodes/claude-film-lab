"""Export an open .blend as GLB for the review dashboard (runs inside Blender 5.x, CPU only: no render).

    blender -b --factory-startup <file.blend> --python-exit-code 1 -P tools/review/bpy_export_glb.py -- <out.glb>
            [--decimate R]

tools/review/watch.py runs this when a <slug>.blend has been saved and left alone for 20 s. Every object of the scene
is exported (bpy_snapshot.export_glb: modifiers applied, posed armatures baked, no cameras/lights). --decimate R (0..1)
adds a Decimate modifier (collapse, ratio R) to every mesh before the export, for a model too heavy for a phone; the
.blend is never saved. Writes <out.glb> and <out.glb>.json ({"objects", "verts", "faces", "tris", "decimate"}).
"""
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bpy_snapshot import export_glb, mesh_stats  # noqa: E402


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        print("usage: ... -P bpy_export_glb.py -- <out.glb> [--decimate R]", file=sys.stderr)
        return 2
    out = os.path.abspath(argv[0])
    ratio = 1.0
    if "--decimate" in argv:
        ratio = max(0.01, min(1.0, float(argv[argv.index("--decimate") + 1])))
    scene = bpy.context.scene
    if ratio < 1.0:
        for ob in scene.objects:
            if ob.type == "MESH":
                mod = ob.modifiers.new("review_decimate", "DECIMATE")
                mod.decimate_type = "COLLAPSE"
                mod.ratio = ratio
    os.makedirs(os.path.dirname(out), exist_ok=True)
    export_glb(out)
    stats = mesh_stats(list(scene.objects))
    stats["decimate"] = ratio
    with open(out + ".json", "w", encoding="utf-8") as f:
        json.dump(stats, f)
    print(f"review: exported {os.path.basename(out)} ({stats['verts']} verts, decimate {ratio:g})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
