"""Real Blender renders of tools/blender (method: blender): a 64x36, 3-frame shot with every pass, a still twice (same
bytes), keyframes at another size, a Cycles still, a turntable and the lookbook. Free and local; skipped when no Blender
is found ($FILM_BLENDER, PATH, the usual install folders), so it skips in WSL and in cloud sessions.
Run on the Windows PC:  cd tests && python -m unittest test_blender_render -v"""
import json, os, struct, subprocess, sys, textwrap, unittest, zlib
from pathlib import Path

import helpers

bl = helpers.load("blender/blender.py", "film_blender_cli_r")
BLENDER, _WHY = bl.find()
CLI = str(helpers.TOOLS / "blender" / "blender.py")

SHOT = {
    "version": 1, "size": [64, 36], "fps": 12, "seconds": 0.25, "seed": 5, "look": "ink-wash",
    "world": {"mist": 0.6, "mist_range": [4, 60], "sun": [35, 280]},
    "assets": [
        {"id": "ground", "src": "preset:ground", "params": {"width": 60, "depth": 60, "relief": 0.2}, "mask": False},
        {"id": "hills", "src": "preset:mountains", "at": [0, 30, -1], "params": {"width": 40, "depth": 12, "height": 10,
                                                                                  "peaks": 3, "res": 60}},
        {"id": "giot", "src": "preset:giot", "at": [0, 0, 0], "anim": {"action": "walk",
                                                                      "path": [[0, [0, 0, 0]], [0.25, [0.3, 0, 0]]]}}],
    "camera": {"move": "push-in", "from": [0, -4, 1.2], "to": [0, -3, 1.1], "target": "giot"},
    "passes": ["depth", "normal", "line", "mask"], "depth_range": [0.5, 60]}


def png_info(path):
    """(width, height, bit depth, colour type) from the IHDR chunk."""
    with open(path, "rb") as f:
        head = f.read(33)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", path
    w, h, depth, ctype = struct.unpack(">IIBB", head[16:26])
    return w, h, depth, ctype


def gray(path, x, y):
    from PIL import Image
    im = Image.open(path)
    v = im.getpixel((x, y))
    return v if isinstance(v, (int, float)) else v[0]


@unittest.skipUnless(BLENDER, f"Blender not found ({_WHY})")
class TestBlenderRender(helpers.TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.spec = self.tmp / "shot.json"
        self.spec.write_text(json.dumps(SHOT), encoding="utf-8")

    def cli(self, *args, timeout=1800):
        r = subprocess.run([sys.executable, CLI, *map(str, args)], capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return r

    def test_render_every_pass(self):
        out = self.tmp / "r"
        r = self.cli("render", self.spec, "--out", out)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        for f in ("0001", "0002", "0003"):
            self.assertEqual(png_info(out / "beauty" / f"{f}.png")[:3], (64, 36, 8))
            self.assertEqual(png_info(out / "depth" / f"{f}.png"), (64, 36, 16, 0))
            self.assertEqual(png_info(out / "normal" / f"{f}.png"), (64, 36, 16, 2))
            self.assertEqual(png_info(out / "line" / f"{f}.png")[:2], (64, 36))
            self.assertTrue((out / "mask" / "giot" / f"{f}.png").is_file())
            self.assertTrue((out / "mask" / "hills" / f"{f}.png").is_file())
        self.assertFalse((out / "mask" / "ground").exists(), "mask: false")
        self.assertTrue((out / "beauty.mp4").is_file() and (out / "beauty.mp4").stat().st_size > 0)
        info = json.loads((out / "render.json").read_text(encoding="utf-8"))
        self.assertTrue(info["blender"].startswith("5."), info["blender"])
        self.assertIn(info["engine"], ("BLENDER_EEVEE", "CYCLES"))
        self.assertEqual(len(info["seconds_per_frame"]), 3)
        self.assertEqual(info["size"], [64, 36])
        self.assertEqual(info["depth_range"], [0.5, 60])
        print(f"\n  real render: {info['engine']} on {info['device']}, {info['mean_seconds_per_frame']} s/frame")
        try:
            import PIL  # noqa: F401
        except ImportError:
            return
        d = out / "depth" / "0002.png"
        from PIL import Image
        self.assertEqual(Image.open(d).getextrema()[0], 0, "the sky is black (far)")
        self.assertGreater(gray(d, 32, 30), 40000, "giot / the ground near the camera is near white")
        m = out / "mask" / "giot" / "0002.png"
        self.assertEqual(gray(m, 1, 1), 0)
        self.assertGreater(gray(m, 32, 22), 200, "giot is in the middle of the frame")

    def test_still_twice_same_bytes_and_cycles(self):
        a, b = self.tmp / "a.png", self.tmp / "b.png"
        for p in (a, b):
            r = self.cli("still", self.spec, "--frame", "2", "--out", p)
            self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        self.assertEqual(a.read_bytes(), b.read_bytes(), "same frame, same bytes")
        c = self.tmp / "c.png"
        r = self.cli("still", self.spec, "--frame", "2", "--out", c, "--engine", "cycles", "--look", "clay")
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        info = json.loads((self.tmp / "c.render.json").read_text(encoding="utf-8"))
        self.assertEqual(info["engine"], "CYCLES")
        self.assertTrue(info["device"])

    def test_keyframes_other_size(self):
        out = self.tmp / "kf"
        r = self.cli("keyframes", self.spec, "--out", out, "--size", "96x54")
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        self.assertEqual(png_info(out / "first.png")[:2], (96, 54))
        self.assertEqual(png_info(out / "last.png")[:2], (96, 54))
        kf = json.loads((out / "keyframes.json").read_text(encoding="utf-8"))
        self.assertEqual(kf["frames"], [1, 3])
        self.assertNotEqual((out / "first.png").read_bytes(), (out / "last.png").read_bytes(), "the camera moved")

    def make_blend(self, path):
        """A .blend (scene 24 fps) with a cube that slides x -3 -> 3 m over frames 1..25 (action 'slide', linear)."""
        script = textwrap.dedent(f"""
            import bpy
            sc = bpy.context.scene
            sc.render.fps, sc.render.fps_base = 24, 1.0
            for o in list(bpy.data.objects):
                bpy.data.objects.remove(o, do_unlink=True)
            bpy.context.preferences.edit.keyframe_new_interpolation_type = 'LINEAR'
            me = bpy.data.meshes.new('slider')
            s = 0.4
            me.from_pydata([(x, y, z) for x in (-s, s) for y in (-s, s) for z in (0, 2 * s)], [],
                           [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)])
            ob = bpy.data.objects.new('slider', me)
            sc.collection.objects.link(ob)
            ob.location = (-3, 0, 0)
            ob.keyframe_insert('location', frame=1)
            ob.location = (3, 0, 0)
            ob.keyframe_insert('location', frame=25)
            ob.animation_data.action.name = 'slide'
            bpy.ops.wm.save_as_mainfile(filepath={str(path)!r})
            """)
        r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python-exit-code", "1", "--python-expr", script],
                           capture_output=True, text=True, timeout=600, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])

    def test_blend_action_keeps_its_timing_in_preview(self):
        """Issue #55: a 24 fps .blend action rendered with --preview (12 fps) is where the final render has it."""
        blend = self.tmp / "slide.blend"
        self.make_blend(blend)
        shot = {"version": 1, "size": [64, 36], "fps": 24, "seconds": 1, "seed": 1, "look": "clay",
                "assets": [{"id": "slider", "src": "slide.blend", "anim": {"action": "slide"}, "color": "#C03020"}],
                "camera": {"move": "static", "from": [0, -9, 0.4], "target": [0, 0, 0.4], "lens": 35},
                "passes": ["mask"], "depth_range": [0.5, 60]}
        sp = self.tmp / "slide.json"
        sp.write_text(json.dumps(shot), encoding="utf-8")
        final, prev = self.tmp / "final", self.tmp / "prev"
        for out, extra in ((final, ["--frames", "7"]), (prev, ["--preview", "--frames", "4"])):   # both t = 0.25 s
            r = self.cli("render", sp, "--out", out, "--no-mp4", *extra)
            self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        fi = json.loads((final / "render.json").read_text(encoding="utf-8"))["actions"]["slider"]
        pi = json.loads((prev / "render.json").read_text(encoding="utf-8"))["actions"]["slider"]
        self.assertEqual((fi["fps"], fi["fps_from"], fi["start"]), (24.0, "blend scene", 1.0))
        self.assertEqual((fi["scale"], pi["scale"]), (1.0, 0.5))
        try:
            from PIL import Image
        except ImportError:
            return

        def centre_x(png):
            im = Image.open(png).convert("L")
            w, h = im.size
            xs = [x for y in range(h) for x in range(w) if im.getpixel((x, y)) > 127]
            self.assertTrue(xs, f"{png}: the cube is not in the mask")
            return sum(xs) / len(xs) / w
        a = centre_x(final / "mask" / "slider" / "0007.png")
        b = centre_x(prev / "mask" / "slider" / "0004.png")
        print(f"\n  action timing: final x {a:.3f}, preview x {b:.3f} (of the frame width)")
        self.assertAlmostEqual(a, b, delta=0.025)      # the old frame mapping is ~0.09 apart (0.75 m)

    def test_turntable_realistic_blend_collection_with_head_bone(self):
        """Issue #56: the G2 turntable of a .blend#Collection (armature with a head bone), look realistic, tiny."""
        blend = self.tmp / "creature.blend"
        script = textwrap.dedent(f"""
            import bpy
            sc = bpy.context.scene
            for o in list(bpy.data.objects):
                bpy.data.objects.remove(o, do_unlink=True)
            coll = bpy.data.collections.new('Creature')
            sc.collection.children.link(coll)
            me = bpy.data.meshes.new('body')
            me.from_pydata([(x, y, z) for x in (-0.3, 0.3) for y in (-0.2, 0.2) for z in (0, 1.2)], [],
                           [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)])
            body = bpy.data.objects.new('body', me)
            coll.objects.link(body)
            arm = bpy.data.armatures.new('rig')
            rig = bpy.data.objects.new('rig', arm)
            coll.objects.link(rig)
            bpy.context.view_layer.objects.active = rig
            bpy.ops.object.mode_set(mode='EDIT')
            b = arm.edit_bones.new('spine')
            b.head, b.tail = (0, 0, 0.2), (0, 0, 1.0)
            h = arm.edit_bones.new('head')
            h.head, h.tail, h.parent = (0, -0.1, 1.0), (0, -0.1, 1.25), b
            bpy.ops.object.mode_set(mode='OBJECT')
            other = bpy.data.objects.new('stray', None)
            sc.collection.objects.link(other)
            bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})
            """)
        r = subprocess.run([BLENDER, "-b", "--factory-startup", "--python-exit-code", "1", "--python-expr", script],
                           capture_output=True, text=True, timeout=600, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])
        out = self.tmp / "g2"
        r = self.cli("turntable", f"{blend}#Creature", "--out", out, "--look", "realistic", "--frames", "4",
                     "--samples", "4", "--size", "64x36", "--front", "180")
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        info = json.loads((out / "render.json").read_text(encoding="utf-8"))
        self.assertEqual((info["engine"], info["frame_count"], info["samples"]), ("CYCLES", 4, 4))
        tt = info["turntable"]
        self.assertEqual(tt["stills"]["head"]["head"], "bone head")
        self.assertTrue(tt["studio"])
        self.assertAlmostEqual(tt["height_m"], 1.2, places=2)                   # own size (no --fit)
        self.assertTrue((out / "beauty.mp4").is_file())
        for v in ("front", "34", "side", "head"):
            self.assertEqual(png_info(out / f"still_{v}.png")[:2], (64, 36), v)

    def test_turntable_and_lookbook(self):
        out = self.tmp / "tt"
        r = self.cli("turntable", "preset:rocks", "--out", out, "--seconds", "0.25", "--size", "64x36", "--preview")
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        self.assertEqual(len(list((out / "beauty").glob("*.png"))), 3)
        for v in ("front", "34", "side", "head"):                        # issue #56: the review stills
            self.assertEqual(png_info(out / f"still_{v}.png")[:2], (64, 36), v)
        tt = json.loads((out / "render.json").read_text(encoding="utf-8"))["turntable"]
        self.assertEqual((tt["backdrop"], tt["fill"]), ("cyc", 0.7))
        self.assertEqual(tt["stills"]["head"]["head"], "top of the bounding box")   # rocks have no head bone
        self.assertGreater(tt["camera_distance_m"], tt["turn_radius_m"])
        self.assertNotEqual((out / "still_front.png").read_bytes(), (out / "still_side.png").read_bytes())
        lb = self.tmp / "lb"
        r = self.cli("lookbook", "--out", lb, "--spec", self.spec, "--size", "64x36")
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        book = json.loads((lb / "lookbook.json").read_text(encoding="utf-8"))
        for look in ("grey-layout", "clay", "toon-ink", "ink-wash"):
            self.assertEqual(png_info(lb / f"{look}.png")[:2], (64, 36))
            self.assertIn(look, book["looks"])


if __name__ == "__main__":
    unittest.main()
