"""tools/blender (method: blender): shot3d.json validation and camera math (spec.py), the CLI (blender.py) with a fake
Blender executable that records its argv and writes what scene.py would write, and the Blender lookup order.
No Blender, no GPU, no network: the real renders are tests/test_blender_render.py (skipped where Blender is missing)."""
import json, math, os, re, shutil, struct, sys, unittest, zlib
from pathlib import Path
from unittest import mock

import helpers

BL = helpers.TOOLS / "blender"
spec = helpers.load("blender/spec.py", "film_blender_spec_t")
bl = helpers.load("blender/blender.py", "film_blender_cli_t")
DEMOS = sorted((BL / "demo").glob("*.json"))


def shot(**over):
    """A small valid spec (3 frames at 12 fps), with top-level overrides."""
    d = {"version": 1, "size": [64, 36], "fps": 12, "seconds": 0.25, "seed": 1, "look": "grey-layout",
         "assets": [{"id": "hero", "src": "preset:giot", "at": [0, 0, 0]},
                    {"id": "box", "src": "prim:cube", "at": [2, 3, 0.5]}],
         "camera": {"move": "static", "from": [0, -6, 1.5], "target": "hero"},
         "passes": ["depth", "mask"], "depth_range": [0.5, 50]}
    d.update(over)
    return d


def errs(d, base=None):
    return spec.validate(d, base)


class TestValidation(unittest.TestCase):
    def test_demos_are_valid(self):
        self.assertGreaterEqual(len(DEMOS), 3)
        for p in DEMOS:
            with self.subTest(demo=p.name):
                data, e = spec.load(str(p))
                self.assertEqual(e, [])

    def test_small_shot_is_valid(self):
        self.assertEqual(errs(shot()), [])

    def test_error_format_is_path_reason(self):
        d = shot(version=2, fps=0, look="watercolour", passes=["depth", "zdepth"], depth_range=[5, 1], extra=1)
        d["assets"][0]["src"] = "preset:mountain"
        d["assets"][1]["id"] = "hero"
        d["camera"]["move"] = "zoom"
        e = errs(d)
        for line in e:
            self.assertRegex(line, r"^[\w\[\]().-]+: .+")
        joined = "\n".join(e)
        for want in ("version: must be 1", "fps: must be between", "look: 'watercolour' is not one of",
                     "passes[1]: 'zdepth' is not one of", "depth_range: must be", "extra: unknown key",
                     "assets[0].src: unknown preset 'mountain'", "assets[1].id: 'hero' is used twice",
                     "camera.move: 'zoom' is not one of static, push-in, pull-out, pan, tilt, orbit, dolly, crane, track"):
            self.assertIn(want, joined)

    def test_missing_parts(self):
        e = "\n".join(errs({"version": 1}))
        self.assertIn("assets: must be a non-empty list", e)
        self.assertIn("camera: missing", e)
        self.assertIn("(root): must be a JSON object", errs([1])[0])

    def test_size_must_be_even(self):
        self.assertIn("size[1]: must be even for H.264 (got 35)", errs(shot(size=[64, 35])))
        self.assertIn("size: must be [width, height] in pixels", errs(shot(size=[64])))

    def test_world(self):
        e = errs(shot(world={"paper": "white", "mist": 2, "sun": [100, 0], "mist_range": [5, 1], "fog": 1}))
        joined = "\n".join(e)
        for want in ("world.paper: must be a colour", "world.mist: must be between 0 and 1",
                     "world.sun: elevation must be between 0 and 90", "world.mist_range: must be", "world.fog: unknown key"):
            self.assertIn(want, joined)

    def test_asset_fields(self):
        d = shot()
        d["assets"][0].update({"scale": -1, "color": "#12345", "ink": 3, "mask": "yes", "fit": 0, "rot": [0, 0]})
        d["assets"][1]["src"] = "prim:blob"
        joined = "\n".join(errs(d))
        for want in ("assets[0].scale: must be a positive number", "assets[0].color: must be a colour",
                     "assets[0].ink: must be between 0 and 1", "assets[0].mask: must be true or false",
                     "assets[0].fit: must be a positive number", "assets[0].rot: must be [x, y, z]",
                     "assets[1].src: unknown primitive 'blob'"):
            self.assertIn(want, joined)
        d = shot()
        d["assets"][0]["src"] = "hero.fbx"
        self.assertIn("assets[0].src: must be preset:<id>, prim:<shape> or a .glb/.gltf path", errs(d))

    def test_preset_params(self):
        d = shot()
        d["assets"][0] = {"id": "m", "src": "preset:mountains", "params": {"peaks": 0, "heigth": 3, "width": 30}}
        d["camera"]["target"] = [0, 0, 0]
        joined = "\n".join(errs(d))
        self.assertIn("assets[0].params.peaks: must be between 1 and 40 (got 0)", joined)
        self.assertIn("assets[0].params.heigth: unknown parameter of preset:mountains", joined)
        d["assets"][0]["params"] = {"peaks": 2.5}
        self.assertIn("assets[0].params.peaks: must be an integer", errs(d))
        d["assets"][1]["params"] = {"a": 1}
        self.assertIn("assets[1].params: only preset assets take params", errs(d))

    def test_anim(self):
        d = shot()
        d["assets"][0]["anim"] = {"action": "fly", "path": [[0, [0, 0, 0]], [0, [1, 0, 0]], [9, [2, 0, 0]]], "ease": "bounce"}
        d["assets"][1]["anim"] = {"action": "spin"}
        joined = "\n".join(errs(d))
        self.assertIn("assets[0].anim.action: 'fly' is not an action of preset:giot (idle, hop, walk, wave)", joined)
        self.assertIn("assets[0].anim.path[1]: times must increase", joined)
        self.assertIn("assets[0].anim.path[2]: time 9 is outside the shot (0..0.25 s)", joined)
        self.assertIn("assets[0].anim.ease: 'bounce' is not one of", joined)
        self.assertIn("assets[1].anim.action: primitives have no actions (use path)", joined)
        d["assets"][0]["anim"] = {"path": [[0, [0, 0, 0]]]}
        self.assertIn("assets[0].anim.path: must be a list of at least two [t, [dx, dy, dz]] keys", errs(d))

    def test_glb_paths(self):
        with helpers_tmp() as tmp:
            d = shot()
            d["assets"][1]["src"] = "models/hero.glb"
            self.assertIn("assets[1].src: file not found: models/hero.glb", errs(d, str(tmp)))
            (tmp / "models").mkdir()
            (tmp / "models" / "hero.glb").write_bytes(b"glTF")
            self.assertEqual(errs(d, str(tmp)), [])
            self.assertEqual(errs(d), [], "without base_dir the file is not looked up")

    def test_camera_rules(self):
        cases = [
            ({"move": "dolly", "from": [0, 0, 1], "target": [0, 5, 1]}, "camera.to: dolly needs `to`"),
            ({"move": "track", "from": [0, 0, 1], "target": "box"},
             "camera.target: track follows a moving asset (one with anim.path) or needs `to`"),
            ({"move": "pan", "from": [0, 0, 1], "target": "ghost"}, "camera.target: unknown asset 'ghost'"),
            ({"move": "orbit", "from": [0, 0, 1], "target": [0, 0, 1]}, "camera.target: is where the camera stands"),
            ({"move": "static", "from": [0, 0, 1], "target": [0, 5, 1], "amount": 0.2},
             "camera.amount: only push-in and pull-out use it"),
            ({"move": "push-in", "from": [0, 0, 1], "target": [0, 5, 1], "degrees": 20},
             "camera.degrees: only pan, tilt and orbit use it"),
            ({"move": "push-in", "from": [0, 0, 1], "target": [0, 5, 1], "lens": 2}, "camera.lens: must be between 4 and 600"),
            ({"move": "push-in", "from": [0, 0, 1], "target": [0, 5, 1], "t": [2, 1]}, "camera.t: must be [start, end]"),
            ({"move": "crane", "from": [0, 0], "target": [0, 5, 1]}, "camera.from: must be [x, y, z]"),
            ({"move": "orbit", "from": [0, 0, 1], "target": [0, 5, 1], "target_to": [1, 5, 1]},
             "camera.target_to: only pan and tilt use it"),
        ]
        for cam, want in cases:
            with self.subTest(want=want):
                self.assertIn(want, "\n".join(errs(shot(camera=cam))))

    def test_look_ids_match_looks_json(self):
        looks = json.loads((BL / "looks.json").read_text(encoding="utf-8"))["looks"]
        self.assertEqual(set(spec.look_ids()), {"grey-layout", "clay", "toon-ink", "ink-wash"})
        self.assertEqual(tuple(looks), spec.look_ids())
        for lid, cfg in looks.items():
            with self.subTest(look=lid):
                for k in ("name", "name_vi", "paper", "ink", "lines", "view", "samples"):
                    self.assertIn(k, cfg)
                for eng in spec.ENGINES:
                    self.assertEqual(len(cfg["samples"][eng]), 2)

    def test_presets_have_builders(self):
        src = (BL / "presets.py").read_text(encoding="utf-8")
        for name in spec.PRESETS:
            self.assertRegex(src, rf"\ndef {name}\(", name)
        self.assertEqual(set(spec.PRESETS), {"mountains", "rocks", "pines", "water", "ground", "giot"})

    def test_blender_side_files_compile(self):
        for name in ("scene.py", "looks.py", "presets.py", "spec.py", "blender.py"):
            compile((BL / name).read_text(encoding="utf-8"), name, "exec")

    def test_spec_py_is_stdlib_only(self):
        src = (BL / "spec.py").read_text(encoding="utf-8")
        mods = set(re.findall(r"^(?:import|from) (\w+)", src, re.M))
        self.assertLessEqual(mods, {"json", "math", "os", "re"})


class helpers_tmp:
    def __enter__(self):
        import tempfile
        self.d = tempfile.mkdtemp(prefix="film-test-")
        return Path(self.d)

    def __exit__(self, *a):
        shutil.rmtree(self.d, ignore_errors=True)


class TestCameraMath(unittest.TestCase):
    def at(self, cam, t, assets=None, seconds=5, fps=24):
        d = shot(seconds=seconds, fps=fps, camera=cam, assets=assets or shot()["assets"])
        self.assertEqual(errs(d), [])
        s = spec.normalize(d)
        return spec.camera_at(s, t)

    def close(self, a, b, places=6):
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y, places=places)

    def test_frames(self):
        self.assertEqual(spec.frame_count(5, 24), 120)
        self.assertEqual(spec.frame_count(0.01, 24), 1)
        self.assertEqual(spec.frame_time(1, 24), 0)
        self.assertAlmostEqual(spec.frame_time(120, 24), 119 / 24)
        s = spec.normalize(shot(size=[1920, 1080], fps=24, seconds=5))
        self.assertEqual(spec.timeline(s), (1920, 1080, 24, 120))
        self.assertEqual(spec.timeline(s, preview=True), (960, 540, 12, 60))
        self.assertEqual(spec.preview_size([1344, 768]), [960, 548])

    def test_parse_frames(self):
        self.assertEqual(spec.parse_frames("2:4", 10), [2, 3, 4])
        self.assertEqual(spec.parse_frames(":3", 10), [1, 2, 3])
        self.assertEqual(spec.parse_frames("8:", 10), [8, 9, 10])
        self.assertEqual(spec.parse_frames("10,1", 10), [1, 10])
        for bad in ("0:3", "5:2", "11", "x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                spec.parse_frames(bad, 10)

    def test_ease(self):
        for name in spec.EASES:
            self.assertAlmostEqual(spec.ease(name, 0), 0)
            self.assertAlmostEqual(spec.ease(name, 1), 1)
        self.assertAlmostEqual(spec.ease("inout", 0.5), 0.5)
        self.assertAlmostEqual(spec.ease("in", 0.5), 0.125)
        self.assertAlmostEqual(spec.ease("out", 0.5), 0.875)
        self.assertEqual(spec.ease("linear", 2), 1)

    def test_static_keeps_its_first_aim(self):
        assets = [{"id": "hero", "src": "preset:giot", "anim": {"path": [[0, [0, 0, 0]], [5, [4, 0, 0]]]}}]
        cam = {"move": "static", "from": [0, -6, 1], "target": "hero", "aim": [0, 0, 0.5]}
        for t in (0, 2.5, 4.9):
            c = self.at(cam, t, assets)
            self.close(c["pos"], [0, -6, 1])
            self.close(c["target"], [0, 0, 0.5])

    def test_push_in_ends_on_the_last_frame(self):
        cam = {"move": "push-in", "from": [0, -10, 1], "to": [0, -4, 1], "target": [0, 0, 1]}
        self.close(self.at(cam, 0)["pos"], [0, -10, 1])
        self.close(self.at(cam, 119 / 24)["pos"], [0, -4, 1])
        self.close(self.at(cam, 119 / 24 / 2)["pos"], [0, -7, 1])           # inout is symmetric
        # preview: 12 fps, the last frame is t = 59/12 and still ends the move
        s = spec.normalize(shot(seconds=5, fps=24, camera=cam))
        self.close(spec.camera_at(s, 59 / 12, fps=12)["pos"], [0, -4, 1])

    def test_push_in_and_pull_out_by_amount(self):
        cam = {"move": "push-in", "from": [0, -10, 0], "target": [0, 0, 0], "amount": 0.5, "ease": "linear"}
        self.close(self.at(cam, 119 / 24)["pos"], [0, -5, 0])
        cam = dict(cam, move="pull-out")
        self.close(self.at(cam, 119 / 24)["pos"], [0, -15, 0])
        cam = {"move": "push-in", "from": [0, -10, 0], "target": [0, 0, 0], "ease": "linear"}
        self.close(self.at(cam, 119 / 24)["pos"], [0, -7, 0])               # default amount 0.3

    def test_pan_and_tilt_turn_in_place(self):
        cam = {"move": "pan", "from": [0, 0, 1], "target": [0, 10, 1], "degrees": 90, "ease": "linear"}
        end = self.at(cam, 119 / 24)
        self.close(end["pos"], [0, 0, 1])
        self.close(end["target"], [-10, 0, 1])                               # + = to the left
        cam = {"move": "tilt", "from": [0, 0, 1], "target": [0, 10, 1], "degrees": 30, "ease": "linear"}
        end = self.at(cam, 119 / 24)
        self.close(end["target"], [0, 10 * math.cos(math.radians(30)), 1 + 10 * math.sin(math.radians(30))])
        cam = {"move": "pan", "from": [0, 0, 1], "target": [0, 10, 1], "target_to": [5, 10, 1], "ease": "linear"}
        self.close(self.at(cam, 119 / 24 / 2)["target"], [2.5, 10, 1])

    def test_orbit_keeps_distance_and_height(self):
        cam = {"move": "orbit", "from": [0, -8, 2], "target": [0, 0, 1], "degrees": 90, "ease": "linear"}
        for t in (0, 1.3, 119 / 24):
            c = self.at(cam, t)
            self.assertAlmostEqual(math.hypot(c["pos"][0], c["pos"][1]), 8)
            self.assertAlmostEqual(c["pos"][2], 2)
        self.close(self.at(cam, 119 / 24)["pos"], [8, 0, 2])                 # counter-clockwise from above

    def test_dolly_crane_track(self):
        cam = {"move": "dolly", "from": [0, -8, 1], "to": [4, -8, 1], "target": [0, 0, 1], "ease": "linear"}
        end = self.at(cam, 119 / 24)
        self.close(end["pos"], [4, -8, 1])
        self.close(end["target"], [4, 0, 1])
        cam = {"move": "crane", "from": [0, -8, 1], "target": [0, 0, 1], "rise": 3, "ease": "linear"}
        end = self.at(cam, 119 / 24)
        self.close(end["pos"], [0, -8, 4])
        self.close(end["target"], [0, 0, 1])
        assets = [{"id": "hero", "src": "preset:giot", "anim": {"path": [[0, [0, 0, 0]], [4, [4, 0, 0]]]}}]
        cam = {"move": "track", "from": [0, -6, 1], "target": "hero"}
        c = self.at(cam, 2, assets)
        self.close(c["pos"], [2, -6, 1])
        self.close(c["target"], [2, 0, 0.5])                                  # giot: aim half its 1 m height

    def test_lens_and_roll(self):
        cam = {"move": "push-in", "from": [0, -10, 0], "target": [0, 0, 0], "lens": 30, "lens_to": 60,
               "roll": 5, "ease": "linear"}
        self.assertAlmostEqual(self.at(cam, 0)["lens"], 30)
        self.assertAlmostEqual(self.at(cam, 119 / 24)["lens"], 60)
        self.assertEqual(self.at(cam, 1)["roll"], 5)

    def test_move_window(self):
        cam = {"move": "push-in", "from": [0, -10, 0], "to": [0, -4, 0], "target": [0, 0, 0], "t": [1, 2], "ease": "linear"}
        self.close(self.at(cam, 0.5)["pos"], [0, -10, 0])
        self.close(self.at(cam, 1.5)["pos"], [0, -7, 0])
        self.close(self.at(cam, 3)["pos"], [0, -4, 0])

    def test_paths_and_heading(self):
        a = {"id": "g", "at": [1, 1, 0], "anim": {"path": [[0, [0, 0, 0]], [2, [2, 0, 0]], [4, [2, 2, 0]]], "ease": "linear"}}
        self.close(spec.asset_position(a, 1), [2, 1, 0])
        self.close(spec.asset_position(a, 3), [3, 2, 0])
        self.close(spec.asset_position(a, 9), [3, 3, 0])
        self.assertAlmostEqual(spec.path_heading(a, 1), 90)                  # walking +x: front (-Y) turned to +x
        self.assertAlmostEqual(spec.path_heading(a, 3), 180)                 # walking +y
        self.assertAlmostEqual(spec.path_heading(a, 9), 180)                 # stopped: keeps the last heading
        self.assertIsNone(spec.path_heading({"id": "x"}, 1))
        a["anim"]["face_path"] = False
        self.assertIsNone(spec.path_heading(a, 1))

    def test_default_aim(self):
        d = spec.normalize(shot(camera={"move": "static", "from": [0, -6, 1], "target": "hero"}))
        self.assertEqual(d["camera"]["aim"], [0, 0, 0.5])
        d = shot(camera={"move": "static", "from": [0, -6, 1], "target": "hero"})
        d["assets"][0]["scale"] = 2
        self.assertEqual(spec.normalize(d)["camera"]["aim"], [0, 0, 1.0])
        d["assets"][0]["fit"] = 3
        self.assertEqual(spec.normalize(d)["camera"]["aim"], [0, 0, 1.5])
        d = spec.normalize(shot(camera={"move": "static", "from": [0, -6, 1], "target": "box"}))
        self.assertEqual(d["camera"]["aim"], [0, 0, 0])

    def test_normalize_fills_defaults(self):
        d = spec.normalize({"version": 1, "assets": [{"id": "a", "src": "prim:cube"}],
                            "camera": {"move": "orbit", "from": [0, -5, 1], "target": [0, 0, 0]}})
        self.assertEqual(d["size"], [1920, 1080])
        self.assertEqual(d["fps"], 24)
        self.assertEqual(d["engine"], "eevee")
        self.assertEqual(d["camera"]["degrees"], 30)
        self.assertEqual(d["camera"]["lens"], 35)
        self.assertEqual(d["assets"][0]["at"], [0.0, 0.0, 0.0])


# ------------------------------------------------------------------ the CLI with a fake Blender
FAKE = r'''
import json, os, sys, zlib, struct
argv = sys.argv[1:]
with open(os.environ["FAKE_BLENDER_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps(argv) + "\n")
if argv == ["--version"]:
    print("Blender 5.3.0 (fake)")
    sys.exit(0)
if os.environ.get("FAKE_BLENDER_FAIL") == "early":
    print("Error: Python: Traceback ... spec problem", flush=True)
    sys.exit(1)
rest = argv[argv.index("--") + 1:]
opt = {}
i = 0
while i < len(rest):
    k = rest[i][2:]
    if k == "preview":
        opt[k] = True; i += 1
    else:
        opt[k] = rest[i + 1]; i += 2
import importlib.util
sp = importlib.util.spec_from_file_location("fake_spec", os.environ["FAKE_BLENDER_SPEC_PY"])
spec = importlib.util.module_from_spec(sp); sp.loader.exec_module(spec)
data, errors = spec.load(opt["spec"])
assert not errors, errors
shot = spec.normalize(data)
W, H, fps, n = spec.timeline(shot, opt.get("preview", False))
if "size" in opt:
    W, H = map(int, opt["size"].split("x"))
frames = spec.parse_frames(opt["frames"], n) if "frames" in opt else list(range(1, n + 1))
passes = shot["passes"] if "passes" not in opt else ([] if opt["passes"] == "none" else opt["passes"].split(","))
engine = opt.get("engine", shot["engine"])
print(f"film-blender: scene built: {W}x{H} {fps} fps, {len(frames)} of {n} frames, engine {engine}", flush=True)
if engine == "eevee" and os.environ.get("FAKE_BLENDER_FAIL") == "eevee":
    print("GPU: failed to create a context", flush=True)
    sys.exit(1)
def png(path, w, h):
    raw = b"".join(b"\x00" + b"\x80" * (w * 3) for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
out = opt["out"]
masks = [a["id"] for a in shot["assets"] if a.get("mask", True)]
for f in frames:
    png(os.path.join(out, "beauty", f"{f:04d}.png"), W, H)
    for p in passes:
        for sub in ([os.path.join("mask", m) for m in masks] if p == "mask" else [p]):
            png(os.path.join(out, sub, f"{f:04d}.png"), W, H)
    print(f"film-blender: frame {f}", flush=True)
mp4 = None
if "mp4" in opt:
    open(opt["mp4"], "wb").write(b"fake mp4")
    mp4 = {"file": "beauty.mp4", "encoder": "blender"}
info = {"engine": "CYCLES" if engine == "cycles" else "BLENDER_EEVEE", "device": "fake", "look": opt.get("look", shot["look"]),
        "size": [W, H], "fps": fps, "frame_count": n, "frames": frames, "seconds_per_frame": [0.01] * len(frames),
        "mean_seconds_per_frame": 0.01, "blender": "5.3.0", "passes": passes, "mp4": mp4}
json.dump(info, open(os.path.join(out, "render.json"), "w"))
print("film-blender: done", flush=True)
'''

FAKE_FFMPEG = r'''
import json, os, sys
with open(os.environ["FAKE_FFMPEG_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
open(sys.argv[-1], "wb").write(b"mp4")
'''


def make_exe(folder, name, source):
    """An executable running `source` with this Python (a .cmd wrapper on Windows)."""
    py = folder / f"{name}.py"
    py.write_text(source, encoding="utf-8")
    if os.name == "nt":
        exe = folder / f"{name}.cmd"
        exe.write_text(f'@"{sys.executable}" "{py}" %*\r\n', encoding="utf-8")
    else:
        exe = folder / name
        exe.write_text(f"#!{sys.executable}\nexec(open({str(py)!r}, encoding='utf-8').read())\n", encoding="utf-8")
        exe.chmod(0o755)
    return exe


class FakeBlenderCase(helpers.TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.log = self.tmp / "argv.log"
        self.exe = make_exe(self.bin, "blender", FAKE)
        self.env = mock.patch.dict(os.environ, {"FILM_BLENDER": str(self.exe), "FAKE_BLENDER_LOG": str(self.log),
                                                "FAKE_BLENDER_SPEC_PY": str(BL / "spec.py")})
        self.env.start()
        os.environ.pop("FAKE_BLENDER_FAIL", None)
        self.noff = mock.patch.object(bl, "ffmpeg_path", lambda: None)
        self.noff.start()
        self.spec_path = self.tmp / "shot.json"
        self.spec_path.write_text(json.dumps(shot()), encoding="utf-8")

    def tearDown(self):
        self.noff.stop()
        self.env.stop()
        super().tearDown()

    def run_cli(self, *argv):
        return helpers.run_main(bl.main, [str(a) for a in argv])

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(l) for l in self.log.read_text(encoding="utf-8").splitlines() if l.strip()]

    def opt(self, call, name):
        rest = call[call.index("--") + 1:]
        return rest[rest.index(name) + 1] if name in rest else None


class TestCli(FakeBlenderCase):
    def test_check(self):
        code, out, err = self.run_cli("check", self.spec_path)
        self.assertEqual(code, 0, err)
        self.assertIn("64x36 12 fps 3 frames", out)
        bad = self.tmp / "bad.json"
        bad.write_text(json.dumps(shot(look="nope")), encoding="utf-8")
        code, out, err = self.run_cli("check", bad)
        self.assertEqual(code, 2)
        self.assertIn("look: 'nope' is not one of", err)
        bad.write_text("{not json", encoding="utf-8")
        code, out, err = self.run_cli("check", bad)
        self.assertEqual(code, 2)
        self.assertIn("(file): not valid JSON", err)
        self.assertEqual(self.calls(), [], "check never starts Blender")

    def test_render_command_and_outputs(self):
        out = self.tmp / "r1"
        code, so, err = self.run_cli("render", self.spec_path, "--out", out)
        self.assertEqual(code, 0, err + so)
        (call,) = self.calls()
        self.assertEqual(call[0:5], ["-b", "--factory-startup", "--python-exit-code", "1", "-P"])
        self.assertEqual(Path(call[5]), BL / "scene.py")
        self.assertEqual(call[6], "--")
        self.assertEqual(Path(self.opt(call, "--spec")), self.spec_path.resolve())
        self.assertEqual(Path(self.opt(call, "--out")), out.resolve())
        self.assertEqual(self.opt(call, "--engine"), "eevee")
        self.assertEqual(Path(self.opt(call, "--mp4")), (out / "beauty.mp4").resolve(), "no ffmpeg: Blender encodes")
        self.assertEqual(sorted(p.name for p in (out / "beauty").iterdir()), ["0001.png", "0002.png", "0003.png"])
        self.assertTrue((out / "depth" / "0003.png").is_file())
        self.assertTrue((out / "mask" / "hero" / "0001.png").is_file())
        self.assertTrue((out / "mask" / "box" / "0001.png").is_file())
        self.assertTrue((out / "beauty.mp4").is_file())
        self.assertIn("rendered 3 frames 64x36", so)
        self.assertIn("blender: scene built", so)

    def test_render_options_are_passed(self):
        out = self.tmp / "r2"
        code, so, err = self.run_cli("render", self.spec_path, "--out", out, "--frames", "2:3", "--engine", "cycles",
                                     "--passes", "depth", "normal", "--look", "ink-wash", "--samples", "8", "--no-mp4")
        self.assertEqual(code, 0, err)
        (call,) = self.calls()
        self.assertEqual(self.opt(call, "--frames"), "2:3")
        self.assertEqual(self.opt(call, "--engine"), "cycles")
        self.assertEqual(self.opt(call, "--passes"), "depth,normal")
        self.assertEqual(self.opt(call, "--look"), "ink-wash")
        self.assertEqual(self.opt(call, "--samples"), "8")
        self.assertNotIn("--mp4", call)
        self.assertEqual(sorted(p.name for p in (out / "beauty").iterdir()), ["0002.png", "0003.png"])
        self.assertIn("no beauty.mp4 (--no-mp4)", so)

    def test_preview(self):
        self.spec_path.write_text(json.dumps(shot(size=[1920, 1080], fps=24, seconds=0.5)), encoding="utf-8")
        out = self.tmp / "pv"
        code, so, err = self.run_cli("render", self.spec_path, "--out", out, "--preview", "--passes", "none")
        self.assertEqual(code, 0, err)
        self.assertIn("--preview", self.calls()[0])
        self.assertEqual(len(list((out / "beauty").iterdir())), 6)          # 0.5 s at 12 fps
        info = json.loads((out / "render.json").read_text())
        self.assertEqual(info["size"], [960, 540])

    def test_ffmpeg_when_found(self):
        fflog = self.tmp / "ff.log"
        ff = make_exe(self.bin, "ffmpeg", FAKE_FFMPEG)
        out = self.tmp / "r3"
        with mock.patch.dict(os.environ, {"FAKE_FFMPEG_LOG": str(fflog)}), mock.patch.object(bl, "ffmpeg_path", lambda: str(ff)):
            code, so, err = self.run_cli("render", self.spec_path, "--out", out, "--frames", "2:3")
        self.assertEqual(code, 0, err)
        self.assertNotIn("--mp4", self.calls()[0])
        args = json.loads(fflog.read_text().splitlines()[0])
        self.assertEqual(args[args.index("-start_number") + 1], "2")
        self.assertEqual(args[args.index("-framerate") + 1], "12")
        self.assertEqual(Path(args[-1]), (out / "beauty.mp4").resolve())
        self.assertEqual(json.loads((out / "render.json").read_text())["mp4"], {"file": "beauty.mp4", "encoder": "ffmpeg"})

    def test_out_must_be_absent_or_empty(self):
        out = self.tmp / "full"
        out.mkdir()
        (out / "x.png").write_bytes(b"x")
        code, so, err = self.run_cli("render", self.spec_path, "--out", out)
        self.assertEqual(code, 2)
        self.assertIn("is not empty", err)
        code, so, err = self.run_cli("render", self.spec_path, "--out", out / "x.png")
        self.assertEqual(code, 2)
        self.assertIn("is a file", err)
        empty = self.tmp / "empty"
        empty.mkdir()
        code, so, err = self.run_cli("render", self.spec_path, "--out", empty, "--no-mp4")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.calls()), 1, "the refusals never started Blender")

    def test_refusals_before_blender(self):
        out = self.tmp / "o"
        for argv, want in (
            (["render", self.spec_path, "--out", out, "--frames", "1:9"], "outside 1..3"),
            (["render", self.spec_path, "--out", out, "--passes", "zdepth"], "--passes: 'zdepth'"),
            (["render", self.spec_path, "--out", out, "--look", "oil"], "--look 'oil'"),
            (["still", self.spec_path, "--frame", "4", "--out", self.tmp / "s.png"], "--frame 4 is outside 1..3"),
            (["still", self.spec_path, "--frame", "1", "--out", self.tmp / "s.png", "--size", "100x51"], "even"),
            (["keyframes", self.spec_path, "--out", out, "--size", "big"], "--size must be WxH"),
            (["turntable", "preset:castle", "--out", out], "unknown preset 'castle'"),
        ):
            with self.subTest(argv=argv[0:2]):
                code, so, err = self.run_cli(*argv)
                self.assertEqual(code, 2, so + err)
                self.assertIn(want, err)
        self.assertEqual(self.calls(), [])
        self.assertFalse(out.exists())

    def test_dry_run(self):
        out = self.tmp / "dry"
        code, so, err = self.run_cli("render", self.spec_path, "--out", out, "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("--factory-startup --python-exit-code 1 -P", so)
        self.assertEqual(self.calls(), [])
        self.assertFalse(out.exists())

    def test_eevee_failure_falls_back_to_cycles(self):
        out = self.tmp / "fb"
        with mock.patch.dict(os.environ, {"FAKE_BLENDER_FAIL": "eevee"}):
            code, so, err = self.run_cli("render", self.spec_path, "--out", out, "--no-mp4")
        self.assertEqual(code, 0, err)
        first, second = self.calls()
        self.assertEqual(self.opt(first, "--engine"), "eevee")
        self.assertEqual(self.opt(second, "--engine"), "cycles")
        info = json.loads((out / "render.json").read_text())
        self.assertIn("EEVEE failed", info["fallback"])
        self.assertEqual(info["engine"], "CYCLES")
        self.assertIn("rendered with Cycles", so)

    def test_failure_before_the_scene_is_not_retried(self):
        out = self.tmp / "bad"
        with mock.patch.dict(os.environ, {"FAKE_BLENDER_FAIL": "early"}):
            code, so, err = self.run_cli("render", self.spec_path, "--out", out)
        self.assertEqual(code, 1)
        self.assertEqual(len(self.calls()), 1)
        self.assertIn("Blender exited with 1", err)
        self.assertIn("spec problem", err)

    def test_blender_missing(self):
        with mock.patch.dict(os.environ, {"FILM_BLENDER": str(self.tmp / "nope.exe")}):
            code, so, err = self.run_cli("render", self.spec_path, "--out", self.tmp / "o")
            self.assertEqual(code, 1)
            self.assertIn("FILM_BLENDER=", err)
            code, so, err = self.run_cli("find")
            self.assertEqual(code, 1)

    def test_find(self):
        code, so, err = self.run_cli("find")
        self.assertEqual(code, 0, err)
        self.assertIn("(5.3.0) via FILM_BLENDER", so)

    def test_find_broken_blender_is_exit_3_not_1(self):
        broken = make_exe(self.bin, "blender-broken", "import sys\nprint('Segmentation fault')\nsys.exit(139)\n")
        with mock.patch.dict(os.environ, {"FILM_BLENDER": str(broken)}):
            code, so, err = self.run_cli("find")
        self.assertEqual(code, bl.BROKEN)
        self.assertEqual(code, 3)
        self.assertIn("but `--version` failed", err)
        self.assertEqual(so, "")

    def test_still(self):
        png = self.tmp / "stills" / "s01_v01.png"
        code, so, err = self.run_cli("still", self.spec_path, "--frame", "2", "--out", png, "--size", "128x72")
        self.assertEqual(code, 0, err)
        (call,) = self.calls()
        self.assertEqual(self.opt(call, "--frames"), "2")
        self.assertEqual(self.opt(call, "--passes"), "none")
        self.assertEqual(self.opt(call, "--size"), "128x72")
        self.assertTrue(png.is_file())
        self.assertTrue((self.tmp / "stills" / "s01_v01.render.json").is_file())
        self.assertEqual(sorted(p.name for p in png.parent.iterdir()), ["s01_v01.png", "s01_v01.render.json"],
                         "the work folder is removed")
        code, so, err = self.run_cli("still", self.spec_path, "--frame", "2", "--out", png)
        self.assertEqual(code, 2)
        self.assertIn("exists", err)

    def test_keyframes(self):
        out = self.tmp / "kf"
        code, so, err = self.run_cli("keyframes", self.spec_path, "--out", out)
        self.assertEqual(code, 0, err)
        (call,) = self.calls()
        self.assertEqual(self.opt(call, "--frames"), "1,3")
        self.assertEqual(self.opt(call, "--size"), "1344x768")
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["first.png", "keyframes.json", "last.png"])
        kf = json.loads((out / "keyframes.json").read_text())
        self.assertEqual(kf["size"], [1344, 768])
        self.assertEqual(kf["frames"], [1, 3])
        self.assertEqual(kf["seconds"], 0.25)
        self.assertEqual(kf["times"], [0.0, round(2 / 12, 4)])
        import hashlib
        self.assertEqual(kf["spec_sha256"], hashlib.sha256(self.spec_path.read_bytes()).hexdigest())
        out2 = self.tmp / "kf2"
        code, so, err = self.run_cli("keyframes", self.spec_path, "--out", out2, "--size", "864x480")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.opt(self.calls()[-1], "--size"), "864x480")

    def test_turntable(self):
        out = self.tmp / "tt"
        code, so, err = self.run_cli("turntable", "preset:giot", "--out", out, "--preview", "--look", "toon-ink")
        self.assertEqual(code, 0, err)
        (call,) = self.calls()
        self.assertEqual(Path(self.opt(call, "--spec")), (out / "turntable.json").resolve())
        t = json.loads((out / "turntable.json").read_text())
        self.assertEqual(spec.validate(t), [])
        self.assertEqual(t["camera"]["move"], "orbit")
        self.assertEqual(t["camera"]["degrees"], 360)
        self.assertEqual(t["look"], "toon-ink")
        self.assertEqual(len(list((out / "beauty").iterdir())), 48)          # 4 s at 12 fps
        glb = self.tmp / "hero.glb"
        glb.write_bytes(b"glTF")
        out2 = self.tmp / "tt2"
        code, so, err = self.run_cli("turntable", glb, "--out", out2, "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertFalse(out2.exists())

    def test_lookbook(self):
        out = self.tmp / "lb"
        lb = self.tmp / "lb.json"
        lb.write_text(json.dumps(shot(passes=[])), encoding="utf-8")
        code, so, err = self.run_cli("lookbook", "--out", out, "--spec", lb, "--size", "96x54")
        self.assertEqual(code, 0, err)
        looks = spec.look_ids()
        calls = self.calls()
        self.assertEqual([self.opt(c, "--look") for c in calls], list(looks))
        self.assertTrue(all(self.opt(c, "--frames") == "2" for c in calls))
        self.assertEqual(sorted(p.name for p in out.iterdir()), sorted([f"{l}.png" for l in looks] + ["lookbook.json"]))
        book = json.loads((out / "lookbook.json").read_text())
        self.assertEqual(list(book["looks"]), list(looks))

    def test_lookbook_default_spec_exists(self):
        self.assertTrue(Path(bl.LOOKBOOK_SPEC).is_file())


class TestFind(helpers.TmpDirCase, unittest.TestCase):
    def touch(self, *parts):
        p = self.tmp.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
        return str(p)

    def test_film_blender_first(self):
        p = self.touch("custom", "blender")
        on_path = self.touch("path", "blender")
        self.assertEqual(bl.find({"FILM_BLENDER": p}, "Linux", lambda n: on_path), (p, "FILM_BLENDER"))

    def test_film_blender_missing_is_an_error(self):
        on_path = self.touch("path", "blender")
        path, why = bl.find({"FILM_BLENDER": str(self.tmp / "gone")}, "Linux", lambda n: on_path)
        self.assertIsNone(path)
        self.assertIn("does not exist", why)

    def test_path_then_program_files(self):
        on_path = self.touch("path", "blender.exe")
        pf = self.tmp / "pf"
        self.touch("pf", "Blender Foundation", "Blender 4.5", "blender.exe")
        newest = self.touch("pf", "Blender Foundation", "Blender 5.10", "blender.exe")
        self.touch("pf", "Blender Foundation", "Blender 5.3", "blender.exe")
        env = {"ProgramFiles": str(pf)}
        self.assertEqual(bl.find(env, "Windows", lambda n: on_path), (on_path, "PATH"))
        self.assertEqual(bl.find(env, "Windows", lambda n: None), (newest, "Program Files"))
        order = [p for p, _ in bl.candidates(env, "Windows", lambda n: None)]
        self.assertEqual([Path(p).parent.name for p in order[:3]], ["Blender 5.10", "Blender 5.3", "Blender 4.5"])

    def test_other_systems(self):
        mac = [p for p, _ in bl.candidates({}, "Darwin", lambda n: None)]
        self.assertEqual(mac[0], "/Applications/Blender.app/Contents/MacOS/Blender")
        lin = [p for p, _ in bl.candidates({}, "Linux", lambda n: None)]
        self.assertEqual(lin, ["/usr/bin/blender"])
        self.assertNotIn("Program Files", " ".join(lin))

    def test_nothing_found(self):
        with mock.patch.object(os.path, "isfile", lambda p: False):
            path, why = bl.find({}, "Linux", lambda n: None)
        self.assertIsNone(path)
        self.assertIn("FILM_BLENDER", why)

    def test_version_parse(self):
        exe = make_exe(self.tmp, "blender", 'print("Blender 5.3.0\\n\\tbuild date: x")')
        self.assertEqual(bl.version(str(exe)), "5.3.0")
        self.assertIsNone(bl.version(str(self.tmp / "missing")))


class TestDemos(unittest.TestCase):
    def test_ink_wash_demo_is_the_mountain_push_in_with_giot(self):
        d = json.loads((BL / "demo" / "ink-wash-mountains.json").read_text(encoding="utf-8"))
        self.assertEqual(d["look"], "ink-wash")
        self.assertEqual(d["camera"]["move"], "push-in")
        self.assertGreater(d["world"]["mist"], 0)
        srcs = {a["src"] for a in d["assets"]}
        self.assertLessEqual({"preset:mountains", "preset:giot"}, srcs)
        self.assertEqual(set(d["passes"]), set(spec.PASSES))

    def test_demos_are_tiny(self):
        for p in DEMOS:
            self.assertLess(p.stat().st_size, 4000, p.name)


if __name__ == "__main__":
    unittest.main()
