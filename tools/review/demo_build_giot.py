"""Rebuild the lab mascot Giọt step by step in Blender and publish every step to the review server (live demo).

  blender -b --factory-startup --python-exit-code 1 -P tools/review/demo_build_giot.py -- --build giot-demo [--step-delay 2]
          [--title T] [--project P] [--no-thumbs] [--url http://127.0.0.1:8791] [--media <folder>]

Same geometry and palette as tools/blender/presets.py `giot` (tools/toon/demo/giot.json), split into 10 steps:
body -> tip -> eyes -> cheeks -> mouth -> arms -> hands -> legs -> feet -> materials. After each step the scene is
exported as step_<NN>.glb (tools/review/bpy_snapshot.py) with a small Workbench thumbnail (--no-thumbs skips it) and
posted; --step-delay S waits S seconds after each step so the live build view is watchable. The build is restarted
(old steps of the same build id are replaced). Offline-safe: with no review server the model is still built.
"""
import argparse
import importlib.util
import math
import os
import sys
import time

import bpy
import mathutils

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from client import Review  # noqa: E402
from bpy_snapshot import snapshot  # noqa: E402


def _load_presets():
    sp = importlib.util.spec_from_file_location("film_blender_presets", os.path.join(LAB, "tools", "blender", "presets.py"))
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    return mod


P = _load_presets()
STEPS = ("body", "tip", "eyes", "cheeks", "mouth", "arms", "hands", "legs", "feet", "materials")


def parse(argv):
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser(prog="demo_build_giot.py")
    p.add_argument("--build", default="giot-demo")
    p.add_argument("--title", default="Giọt · dựng từng bước")
    p.add_argument("--project", default="lab")
    p.add_argument("--step-delay", type=float, default=0.0, help="seconds to wait after each step")
    p.add_argument("--no-thumbs", action="store_true", help="no Workbench thumbnail per step")
    p.add_argument("--url", default=None, help="ingest URL (default FILM_REVIEW_URL or http://127.0.0.1:8791)")
    p.add_argument("--media", default=None, help="media folder (default <lab>/out/_review/media)")
    return p.parse_args(argv)


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_rgba(h, linear=True):
    h = h.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    if linear:
        rgb = [srgb_to_linear(c) for c in rgb]
    return (*rgb, 1.0)


class Giot:
    """The giot preset's geometry, one part at a time (tools/blender/presets.py giot())."""

    def __init__(self, coll):
        g = P.GIOT
        self.g, self.pal, self.coll = g, dict(g["palette"]), coll
        self.leg, self.lr = g["leg"], g["limb_r"]
        self.z0 = self.leg - 0.02
        self.bh = g["height"] - self.leg + 0.02 - 0.04
        self.prof = P._drop_profile(self.bh, g["body_w"] / 2, g["body_d"] / 2, 0.0)
        self.root = P._empty("giot", coll)
        self.body_pivot = P._empty("giot.bodypivot", coll, parent=self.root, loc=(0, 0, self.z0))
        self.shoulders, self.hips, self.arm_end = {}, {}, {}

    def mesh(self, name, vf, role, color, parent, loc=None, rot=None):
        ob = P._mesh(f"giot.{name}", *vf, self.coll, role, color)
        ob.parent = parent
        if loc is not None:
            ob.location = loc
        if rot is not None:
            ob.rotation_euler = rot
        return ob

    def body(self):
        return [self.mesh("body", P._revolve(self.prof, 32), "body", self.pal["body"], self.body_pivot)]

    def tip(self):
        tip = self.prof[-1][2]
        ks = [i / 8 for i in range(9)]
        pts = [(0, 0.09 * (k ** 2) * 0.7, tip - 0.08 + 0.15 * math.sin(k * math.pi * 0.55)) for k in ks]
        rad = [0.035 * (1 - k) + 0.004 for k in ks]
        return [self.mesh("tuft", P._tube(pts, rad, 10), "tuft", self.pal["body"], self.body_pivot)]

    def _eye_pos(self, side):
        g = self.g
        ez = g["eye_y"] * self.bh
        rx, ry = P._drop_radius(self.prof, ez)
        ex = side * g["eye_gap"] / 2
        ey = -ry * math.sqrt(max(0.0, 1 - (ex / rx) ** 2)) + 0.012
        return ex, ey, ez

    def eyes(self):
        out, r = [], self.g["eye_r"]
        for side in (-1, 1):
            ex, ey, ez = self._eye_pos(side)
            s = "LR"[side > 0]
            out.append(self.mesh(f"eye{s}", P._ellipsoid(r * 0.9, r * 0.55, r * 1.1, 10, 18), "eye", self.pal["eye"],
                                 self.body_pivot, (ex, ey, ez)))
            out.append(self.mesh(f"pupil{s}", P._ellipsoid(r * 0.48, r * 0.3, r * 0.6, 8, 14), "pupil",
                                 self.pal["pupil"], self.body_pivot, (ex + side * 0.004, ey - r * 0.36, ez - 0.004)))
        return out

    def cheeks(self):
        out, g = [], self.g
        for side in (-1, 1):
            _, _, ez = self._eye_pos(side)
            cz = ez - g["eye_r"] * 1.55
            crx, cry = P._drop_radius(self.prof, cz)
            cx = side * g["eye_gap"] * 0.85
            cy = -cry * math.sqrt(max(0.0, 1 - (cx / crx) ** 2)) + 0.012
            out.append(self.mesh(f"cheek{'LR'[side > 0]}", P._ellipsoid(0.04, 0.012, 0.024, 6, 14), "cheek",
                                 self.pal["cheek"], self.body_pivot, (cx, cy, cz), (0, 0, side * 0.45)))
        return out

    def mouth(self):
        g = self.g
        mz = g["eye_y"] * self.bh - g["eye_r"] * 1.9
        mrx, mry = P._drop_radius(self.prof, mz)
        pts = []
        for i in range(9):
            k = -1 + i / 4
            x = 0.045 * k
            pts.append((x, -mry * math.sqrt(max(0.0, 1 - (x / mrx) ** 2)) - 0.004, mz + 0.018 * k * k))
        return [self.mesh("mouth", P._tube(pts, [0.007] * 9, 8), "mouth", self.pal["mouth"], self.body_pivot)]

    def arms(self):
        out, g = [], self.g
        sz = g["shoulder_y"] * self.bh
        srx, _ = P._drop_radius(self.prof, sz)
        for i, side in enumerate((-1, 1)):
            s = "LR"[i]
            sho = P._empty(f"giot.shoulder{s}", self.coll, loc=(side * (srx - 0.02), 0, sz), parent=self.body_pivot)
            self.shoulders[s] = sho
            A = g["arm"]
            pts = [(0, 0, 0), (side * A * 0.35, 0, -A * 0.45), (side * A * 0.5, 0, -A * 0.85)]
            self.arm_end[s] = pts[-1]
            out.append(self.mesh(f"arm{s}", P._tube(pts, [self.lr * 0.9] * 3, 10), "limb", self.pal["limb"], sho))
        return out

    def hands(self):
        return [self.mesh(f"hand{s}", P._ellipsoid(0.05, 0.05, 0.05, 8, 14), "hand", self.pal["glove"],
                          self.shoulders[s], self.arm_end[s]) for s in "LR"]

    def legs(self):
        out, g = [], self.g
        for i, side in enumerate((-1, 1)):
            s = "LR"[i]
            hip = P._empty(f"giot.hip{s}", self.coll, loc=(side * g["hip_w"] / 2, 0, self.leg), parent=self.root)
            self.hips[s] = hip
            pts = [(0, 0, 0.02), (0, 0, -self.leg * 0.5), (0, 0, -self.leg + 0.04)]
            out.append(self.mesh(f"leg{s}", P._tube(pts, [self.lr] * 3, 10), "limb", self.pal["limb"], hip))
        return out

    def feet(self):
        return [self.mesh(f"shoe{s}", P._ellipsoid(0.055, 0.085, 0.04, 8, 16), "shoe", self.pal["shoe"],
                          self.hips[s], (0, -0.025, -self.leg + 0.035)) for s in "LR"]

    def materials(self):
        mats, out = {}, []
        for ob in self.coll.objects:
            if ob.type != "MESH":
                continue
            role, color = ob.get("film_role", "body"), ob.get("film_color", "#888888")
            key = (role, color)
            if key not in mats:
                m = bpy.data.materials.new(f"giot.{role}")
                m.use_nodes = True
                bsdf = m.node_tree.nodes.get("Principled BSDF")
                if bsdf:
                    bsdf.inputs["Base Color"].default_value = hex_rgba(color)
                    bsdf.inputs["Roughness"].default_value = 0.25 if role in ("eye", "pupil") else 0.55
                m.diffuse_color = hex_rgba(color)
                mats[key] = m
            ob.data.materials.clear()
            ob.data.materials.append(mats[key])
            out.append(ob)
        return out


def setup_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    coll = bpy.data.collections.new("giot")
    scene.collection.children.link(coll)
    cam_data = bpy.data.cameras.new("thumb")
    cam_data.lens = 50
    cam = bpy.data.objects.new("thumb.camera", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (1.05, -1.95, 0.95)
    target = mathutils.Vector((0, 0, 0.48))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    return scene, coll


def main():
    a = parse(sys.argv)
    scene, coll = setup_scene()
    rv = Review(a.build, a.title, "demo", project=a.project, expected_steps=len(STEPS), url=a.url, media=a.media,
                status="building", restart=True)
    giot = Giot(coll)
    t_start = time.monotonic()
    try:
        for i, name in enumerate(STEPS, 1):
            t0 = time.monotonic()
            made = getattr(giot, name)()
            bpy.context.view_layer.update()
            n = snapshot(rv, name, objects=None, thumb=not a.no_thumbs,
                         extra_stats={"parts": len(made), "build_s": round(time.monotonic() - t0, 2)})
            print(f"film-review: step {i}/{len(STEPS)} {name} ({len(made)} parts)"
                  + ("" if n else " - snapshot failed"), flush=True)
            if a.step_delay > 0 and i < len(STEPS):
                time.sleep(a.step_delay)
    except Exception as e:
        rv.fail(f"{type(e).__name__}: {e}")
        raise
    rv.done(f"{len(STEPS)} steps in {time.monotonic() - t_start:.1f} s")
    state = "publishing off" if not rv.enabled else (f"not all published: {rv.last_error}" if rv.last_error else "published")
    print(f"film-review: done {a.build} ({state})", flush=True)


if __name__ == "__main__":
    main()
