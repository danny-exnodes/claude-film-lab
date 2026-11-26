"""Image-to-3D blanks on the Blender side (issue #69): tools/blender/meshcheck.py (GLB reader, mesh report, silhouettes,
IoU against the concept, sheet) and blender.py mesh-check / mesh-prep with a fake Blender. Tiny GLB files are written
by the test; no real Blender, GPU or network."""
import json, os, struct, sys, unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw

import helpers
from test_blender import FAKE, make_exe

bl = helpers.load("blender/blender.py", "film_blender_cli_mesh")
mc = helpers.load("blender/meshcheck.py", "film_meshcheck")


# ------------------------------------------------------------------ tiny GLB files
def write_glb(path, parts, nodes=None):
    """parts: [(V (n,3), F (m,3))], one mesh each; nodes: optional list of node dicts (default one node per mesh)."""
    binary, views, accs, meshes = b"", [], [], []
    for V, F in parts:
        for arr, ctype, typ, target in ((np.asarray(V, np.float32), 5126, "VEC3", 34962),
                                        (np.asarray(F, np.uint32).reshape(-1), 5125, "SCALAR", 34963)):
            data = arr.tobytes()
            views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(data), "target": target})
            acc = {"bufferView": len(views) - 1, "componentType": ctype, "count": len(arr), "type": typ}
            if typ == "VEC3":
                acc.update(min=arr.min(0).tolist(), max=arr.max(0).tolist())
            accs.append(acc)
            binary += data + b"\0" * (-len(data) % 4)
        meshes.append({"primitives": [{"attributes": {"POSITION": len(accs) - 2}, "indices": len(accs) - 1}]})
    nodes = nodes if nodes is not None else [{"mesh": i} for i in range(len(parts))]
    kids = {c for n in nodes for c in n.get("children") or []}
    gltf = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [i for i in range(len(nodes)) if i not in kids]}],
            "nodes": nodes, "meshes": meshes, "accessors": accs, "bufferViews": views,
            "buffers": [{"byteLength": len(binary)}]}
    js = json.dumps(gltf).encode()
    js += b" " * (-len(js) % 4)
    out = (struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(binary), 0x004E4942) + binary)
    Path(path).write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(out)) + out)
    return str(path)


def box(sx=2.0, sy=1.0, sz=0.5, at=(0, 0, 0)):
    """A closed box (8 verts, 12 tris, outward winding), x width, y height (glTF up), z depth."""
    x, y, z = sx / 2, sy / 2, sz / 2
    V = np.array([[-x, -y, -z], [x, -y, -z], [x, y, -z], [-x, y, -z],
                  [-x, -y, z], [x, -y, z], [x, y, z], [-x, y, z]]) + np.array(at)
    F = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                  [3, 7, 6], [3, 6, 2], [0, 4, 7], [0, 7, 3], [1, 2, 6], [1, 6, 5]])
    return V, F


def tetra(at=(0, 0, 0), s=0.1):
    V = np.array([[0, 0, 0], [s, 0, 0], [0, s, 0], [0, 0, s]], float) + np.array(at)
    return V, np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])


def split_box():
    """The box with its vertices split per face (as a glTF exporter writes flat-shaded meshes): 36 vertices."""
    V, F = box()
    return V[F.reshape(-1)], np.arange(36).reshape(-1, 3)


def concept_png(path, size=(400, 300), rect=(100, 100, 300, 200), bg=(255, 255, 255), rgba=False):
    im = Image.new("RGBA" if rgba else "RGB", size, (0, 0, 0, 0) if rgba else bg)
    ImageDraw.Draw(im).rectangle([rect[0], rect[1], rect[2] - 1, rect[3] - 1], fill=(60, 50, 40, 255) if rgba else (60, 50, 40))
    im.save(path)
    return str(path)


# ------------------------------------------------------------------ meshcheck.py
class TestReadGlb(helpers.TmpDirCase, unittest.TestCase):
    def test_round_trip_and_node_transforms(self):
        V, F = box()
        p = write_glb(self.tmp / "b.glb", [(V, F)])
        V2, F2, info = mc.read_glb(p)
        np.testing.assert_allclose(V2, V, atol=1e-6)
        self.assertEqual(F2.tolist(), F.tolist())
        self.assertEqual(info["primitives"], 1)
        nodes = [{"children": [1], "translation": [10, 0, 0], "scale": [2, 2, 2]}, {"mesh": 0, "translation": [0, 1, 0]}]
        p2 = write_glb(self.tmp / "t.glb", [(V, F)], nodes=nodes)
        V3, _, _ = mc.read_glb(p2)
        np.testing.assert_allclose(V3, (V + [0, 1, 0]) * 2 + [10, 0, 0], atol=1e-6)
        rot = [{"mesh": 0, "rotation": [0, 0.7071068, 0, 0.7071068]}]       # 90 degrees about +Y: x -> -z
        V4, _, _ = mc.read_glb(write_glb(self.tmp / "r.glb", [(V, F)], nodes=rot))
        np.testing.assert_allclose(V4[:, 2], -V[:, 0], atol=1e-5)
        mat = [{"mesh": 0, "matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 3, 4, 5, 1]}]   # column-major translation
        V5, _, _ = mc.read_glb(write_glb(self.tmp / "m.glb", [(V, F)], nodes=mat))
        np.testing.assert_allclose(V5, V + [3, 4, 5], atol=1e-6)

    def test_two_meshes_and_refusals(self):
        p = write_glb(self.tmp / "two.glb", [box(), tetra(at=(5, 0, 0))])
        V, F, info = mc.read_glb(p)
        self.assertEqual((len(V), len(F), info["primitives"]), (12, 16, 2))
        self.assertEqual(F.max(), 11)
        (self.tmp / "x.glb").write_bytes(b"PK\x03\x04 not a glb at all....")
        for path, want in ((self.tmp / "x.glb", "no glTF magic"), (self.tmp / "nope.glb", "cannot read")):
            with self.subTest(path=path), self.assertRaises(mc.GlbError) as cm:
                mc.read_glb(str(path))
            self.assertIn(want, str(cm.exception))
        raw = bytearray(Path(p).read_bytes())
        Path(self.tmp / "cut.glb").write_bytes(bytes(raw[:len(raw) - 40]))     # binary chunk cut short
        with self.assertRaises(mc.GlbError):
            mc.read_glb(str(self.tmp / "cut.glb"))


class TestMeshStats(unittest.TestCase):
    def test_closed_box(self):
        st = mc.mesh_stats(*box())
        self.assertEqual((st["verts"], st["tris"], st["edges"]), (8, 12, 18))
        self.assertEqual((st["boundary_edges"], st["overshared_edges"], st["islands"]), (0, 0, 1))
        self.assertTrue(st["watertight"])
        self.assertEqual(st["dims"], [2.0, 1.0, 0.5])

    def test_split_vertices_are_welded(self):
        st = mc.mesh_stats(*split_box())
        self.assertEqual((st["verts_in_file"], st["verts"], st["islands"]), (36, 8, 1))
        self.assertTrue(st["watertight"])

    def test_hole_debris_and_fin(self):
        V, F = box()
        st = mc.mesh_stats(V, F[1:])                                    # one triangle missing: a hole
        self.assertEqual((st["boundary_edges"], st["non_manifold_edges"], st["watertight"]), (3, 3, False))
        tV, tF = tetra(at=(5, 5, 5))
        st = mc.mesh_stats(np.concatenate([V, tV]), np.concatenate([F, tF + 8]))
        self.assertEqual((st["islands"], st["largest_islands"], st["small_islands"]), (2, [8, 4], 0))
        fin = np.concatenate([F, [[0, 1, 8]]])                          # a third face on edge 0-1: a thin fin
        st = mc.mesh_stats(np.concatenate([V, [[0, -2, 0]]]), fin)
        self.assertEqual((st["overshared_edges"], st["boundary_edges"]), (1, 2))
        st = mc.mesh_stats(V, np.concatenate([F, [[0, 0, 1]]]))        # a degenerate triangle is dropped
        self.assertEqual((st["degenerate_tris"], st["tris"]), (1, 12))

    def test_components_on_a_long_chain(self):
        n = 5000
        perm = np.random.default_rng(3).permutation(n)
        edges = np.stack([perm[:-1], perm[1:]], 1)                      # one path through every vertex
        lab = mc.components(n, edges)
        self.assertEqual(len(set(lab.tolist())), 1)
        lab = mc.components(n, edges[np.arange(len(edges)) != 2500])     # cut once: two parts
        self.assertEqual(len(set(lab.tolist())), 2)

    def test_warnings(self):
        V, F = box()
        st = mc.mesh_stats(V, F[1:])
        w = mc.warnings(st, {"iou": 0.7, "aspect_drift": -0.2})
        self.assertTrue(any("not watertight" in x for x in w))
        self.assertTrue(any("IoU 0.70 < 0.85" in x for x in w))
        self.assertTrue(any("proportions drift -20%" in x for x in w))
        self.assertEqual(mc.warnings(mc.mesh_stats(V, F), {"iou": 0.95, "aspect_drift": 0.02}), [])


class TestSilhouette(helpers.TmpDirCase, unittest.TestCase):
    def test_box_front_side_and_iou(self):
        V, F = box(2.0, 1.0, 0.5)
        front = mc.silhouette(V, F, "front", size=200)
        ys, xs = np.nonzero(front)
        self.assertAlmostEqual((xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1), 2.0, delta=0.05)
        self.assertGreater(front[ys.min():ys.max() + 1, xs.min():xs.max() + 1].mean(), 0.99)   # filled, no holes
        side = mc.silhouette(V, F, "side", size=200)
        ys, xs = np.nonzero(side)
        self.assertAlmostEqual((xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1), 0.5, delta=0.05)
        concept = mc.concept_mask(concept_png(self.tmp / "c.png"))       # a 2:1 rectangle on white
        cmp = mc.compare(concept, front)
        self.assertGreater(cmp["iou"], 0.97)
        self.assertLess(abs(cmp["aspect_drift"]), 0.03)
        cmp = mc.compare(concept, side)                                  # wrong view: 1:2 against 2:1
        self.assertLess(cmp["iou"], 0.35)
        self.assertAlmostEqual(cmp["aspect_drift"], -0.75, delta=0.03)

    def test_compare_finds_a_mirrored_mesh_and_ignores_specks(self):
        L = np.zeros((100, 100), bool)
        L[10:90, 10:30] = True
        L[70:90, 10:80] = True                                           # an L
        cmp = mc.compare(L, L[:, ::-1].copy())
        self.assertTrue(cmp["mirrored"])
        self.assertAlmostEqual(cmp["iou"], 1.0, places=3)
        self.assertLess(cmp["iou_direct"], 0.6)
        noisy = L.copy()
        noisy[0, 99] = noisy[99, 0] = True                              # Qwen's corner specks
        self.assertAlmostEqual(mc.compare(L, noisy)["iou"], 1.0, delta=0.02)
        shifted = np.zeros((300, 300), bool)
        shifted[100:260, 40:80] = True
        shifted[220:260, 40:180] = True                                  # the same L, twice the size, elsewhere
        self.assertGreater(mc.compare(L, shifted)["iou"], 0.95)
        self.assertEqual(mc.iou(np.zeros((4, 4), bool), np.zeros((4, 4), bool)), 0.0)
        self.assertEqual(mc.compare(L, np.zeros((50, 50), bool))["iou"], 0.0)

    def test_floating_debris_is_left_out_of_the_silhouette(self):
        V, F = box()
        tV, tF = tetra(at=(3, 0, 0), s=0.05)
        V2, F2 = np.concatenate([V, tV]), np.concatenate([F, tF + 8])
        mV, mF = mc.main_part(V2, F2)
        self.assertEqual(len(mF), 12)
        wide = mc.silhouette(V2, F2, min_part=0)
        ys, xs = np.nonzero(wide)
        self.assertGreater((xs.max() - xs.min()) / (ys.max() - ys.min()), 3.5)      # box + debris 2 m to the right
        clean = mc.silhouette(V2, F2)
        ys, xs = np.nonzero(clean)
        self.assertAlmostEqual((xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1), 2.0, delta=0.05)
        self.assertEqual(clean.shape[1], 512 + 1, "the box alone fills the canvas")

    def test_square_vs_rectangle_iou_is_one_half(self):
        sq = np.zeros((100, 100), bool)
        sq[20:80, 20:80] = True
        rect = np.zeros((100, 200), bool)
        rect[30:70, 20:100] = True                                       # 2:1
        cmp = mc.compare(sq, rect, size=200)
        self.assertAlmostEqual(cmp["iou"], 0.5, delta=0.02)
        self.assertAlmostEqual(cmp["aspect_drift"], 1.0, delta=0.02)

    def test_concept_mask_alpha_and_white(self):
        m = mc.concept_mask(concept_png(self.tmp / "a.png", rgba=True))
        self.assertEqual((int(m.sum()), m.shape), (200 * 100, (300, 400)))
        m = mc.concept_mask(concept_png(self.tmp / "w.png", bg=(245, 245, 245)))   # off-white is background
        self.assertEqual(int(m.sum()), 200 * 100)

    def test_sheet(self):
        V, F = box()
        sil = mc.silhouette(V, F)
        c = concept_png(self.tmp / "c.png")
        out = str(self.tmp / "sheet.png")
        size = mc.compare_sheet(out, [("concept", c), ("sil", sil), ("overlay", mc.overlay(mc.concept_mask(c), sil)),
                                      ("missing", str(self.tmp / "nope.png")), ("x", None)], title="t")
        with Image.open(out) as im:
            self.assertEqual(im.size, size)
            self.assertEqual(im.size[0], 4 * 328 + 8)
        ov = mc.overlay(mc.concept_mask(c), sil, size=64)
        self.assertEqual(ov.shape, (64, 64, 3))
        self.assertGreater((ov == (215, 215, 215)).all(axis=2).mean(), 0.3)   # mostly overlap (light grey)


# ------------------------------------------------------------------ blender.py mesh-check / mesh-prep
MESH_FAKE = r'''
import json, os, shutil, sys
_argv = sys.argv[1:]
if "-P" in _argv and _argv[_argv.index("-P") + 1].endswith("meshprep.py"):
    with open(os.environ["FAKE_BLENDER_LOG"], "a", encoding="utf-8") as f:
        f.write(json.dumps(_argv) + "\n")
    if os.environ.get("FAKE_BLENDER_FAIL") == "early":
        print("Error: Python: Traceback ... QuadriFlow exploded", flush=True)
        sys.exit(1)
    rest = _argv[_argv.index("--") + 1:]
    opt = dict(zip(rest[0::2], rest[1::2]))
    out, name = opt["--out"], opt["--name"]
    files = {"glb": name + "_prep.glb", "blend": name + "_prep.blend", "json": "prep.json"}
    shutil.copyfile(os.environ.get("FAKE_PREP_GLB") or opt["--glb"], os.path.join(out, files["glb"]))
    open(os.path.join(out, files["blend"]), "wb").write(b"BLENDER-fake")
    print("film-blender: voxel remesh 0.01: 900 faces", flush=True)
    rep = {"tool": "tools/blender/meshprep.py", "blender": "5.3.0", "name": name, "voxel_size": 0.0067,
           "stages": {"import": {"faces": 16}, "final": {"faces": 12, "quads": 6, "tris": 12}},
           "retopo": {"method": "quadriflow", "target": int(opt["--quad-faces"])}, "files": files,
           "notes": ["QuadriFlow failed: decimated"] if os.environ.get("FAKE_QUAD_FAIL") else [],
           "env_gpu_held": os.environ.get("FILM_GPU_HELD")}
    json.dump(rep, open(os.path.join(out, "prep.json"), "w"))
    sys.exit(0)
'''


class MeshCliCase(helpers.TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.log = self.tmp / "argv.log"
        self.exe = make_exe(self.bin, "blender", MESH_FAKE + FAKE)
        env = {"FILM_BLENDER": str(self.exe), "FAKE_BLENDER_LOG": str(self.log),
               "FAKE_BLENDER_SPEC_PY": str(helpers.TOOLS / "blender" / "spec.py"),
               "FILM_GPU_LOCK": str(self.tmp / "gpu" / "gpu.lock")}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        for k in ("FAKE_BLENDER_FAIL", "FILM_GPU_HELD", "FILM_GPU_QUEUE", "FILM_GPU_WAIT", "FILM_AGENT",
                  "FILM_REVIEW_BUILD", "FAKE_PREP_GLB", "FAKE_QUAD_FAIL"):
            os.environ.pop(k, None)
        self.noff = mock.patch.object(bl, "ffmpeg_path", lambda: None)
        self.noff.start()
        V, F = box()
        tV, tF = tetra(at=(3, 0, 0), s=0.05)                           # a loose fragment
        self.raw = write_glb(self.tmp / "ho-giao_raw_v01.glb", [(V, F[1:]), (tV, tF)])   # + a hole
        self.clean = write_glb(self.tmp / "clean.glb", [split_box()])
        self.concept = concept_png(self.tmp / "concept.png")
        self.out = self.tmp / "prep_v01"

    def tearDown(self):
        self.noff.stop()
        self.env.stop()
        super().tearDown()

    def cli(self, *argv):
        return helpers.run_main(bl.main, [str(a) for a in argv])

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(l) for l in self.log.read_text(encoding="utf-8").splitlines() if l.strip()]


class TestMeshCheckCli(MeshCliCase):
    def test_report_json_and_sheet(self):
        code, out, err = self.cli("mesh-check", self.raw, "--concept", self.concept, "--json", self.tmp / "r.json",
                                  "--sheet", self.tmp / "s" / "sheet.png")
        self.assertEqual(code, 0, err)
        self.assertIn("ho-giao_raw_v01.glb: 15 tris, 12 verts, 2 island(s), 3 boundary + 0 over-shared edges -> "
                      "NOT watertight", out)
        self.assertRegex(out, r"view front vs concept: silhouette IoU (0\.9\d\d|1\.000) · proportions")
        self.assertIn("WARNING: not watertight", out)
        self.assertIn("WARNING: 2 loose parts", out)
        rep = json.loads((self.tmp / "r.json").read_text(encoding="utf-8"))
        self.assertEqual((rep["stats"]["islands"], rep["view"]), (2, "front"))
        self.assertGreater(rep["silhouette"]["iou"], 0.9)
        self.assertTrue((self.tmp / "s" / "sheet.png").is_file())
        self.assertEqual(self.calls(), [], "mesh-check never starts Blender")
        code, out, err = self.cli("mesh-check", self.raw, "--json", self.tmp / "r.json")
        self.assertEqual(code, 2)
        self.assertIn("exists (nothing is overwritten", err)
        code, out, err = self.cli("mesh-check", self.clean, "--view", "side")
        self.assertEqual(code, 0, err)
        self.assertIn("-> watertight", out)
        self.assertNotIn("WARNING", out)

    def test_refusals(self):
        bad = self.tmp / "bad.glb"
        bad.write_bytes(b"not a glb, only text here.")
        for argv, want in (((bad,), "no glTF magic"), ((self.tmp / "none.glb",), "no such file"),
                           ((self.raw, "--concept", self.tmp / "nope.png"), "--concept"),
                           ((self.raw, "--concept", bad), "not an image")):
            with self.subTest(argv=argv):
                code, _, err = self.cli("mesh-check", *argv)
                self.assertEqual(code, 2, err)
                self.assertIn(want, err)
        white = Image.new("RGB", (50, 50), (255, 255, 255))
        white.save(self.tmp / "white.png")
        code, _, err = self.cli("mesh-check", self.raw, "--concept", self.tmp / "white.png")
        self.assertEqual(code, 2)
        self.assertIn("no subject found", err)


class TestMeshPrepCli(MeshCliCase):
    def test_dry_run_prints_both_steps_and_runs_nothing(self):
        code, out, err = self.cli("mesh-prep", self.raw, "--out", self.out, "--concept", self.concept, "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("meshprep.py -- --glb", out)
        self.assertIn("--name ho-giao_v01 --voxel auto --quad-faces 20000 --min-island 0.002", out)
        self.assertIn("then: turntable", out)
        self.assertIn("ho-giao_v01_prep.glb --look clay --stills front,34,side", out)
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.out.exists())
        code, out, _ = self.cli("mesh-prep", self.raw, "--out", self.out, "--dry-run", "--decimate", "5000",
                                "--voxel", "0.01", "--no-turntable", "--min-island", "0")
        self.assertEqual(code, 0)
        self.assertIn("--voxel 0.01 --quad-faces 20000 --min-island 0 --decimate 5000", out)
        self.assertNotIn("then: turntable", out)

    def test_refusals_before_blender(self):
        bad = self.tmp / "bad.glb"
        bad.write_bytes(b"glTF but not really")
        (self.tmp / "full").mkdir()
        (self.tmp / "full" / "x.txt").write_text("x")
        for extra, want in ((["--voxel", "big"], "--voxel 'big'"), (["--voxel", "-1"], "--voxel '-1'"),
                            (["--quad-faces", "50"], "--quad-faces must be"), (["--decimate", "10"], "--decimate must"),
                            (["--min-island", "0.6"], "--min-island must"), (["--frames", "1"], "--frames must"),
                            (["--stills", "top"], "--stills: 'top'"), (["--look", "nope"], "--look 'nope'"),
                            (["--concept", self.tmp / "nope.png"], "--concept")):
            with self.subTest(extra=extra):
                code, _, err = self.cli("mesh-prep", self.raw, "--out", self.out, *extra)
                self.assertEqual(code, 2, err)
                self.assertIn(want, err)
        code, _, err = self.cli("mesh-prep", bad, "--out", self.out)
        self.assertEqual(code, 2)
        self.assertIn("not a GLB", err)
        code, _, err = self.cli("mesh-prep", self.raw, "--out", self.tmp / "full")
        self.assertEqual(code, 2)
        self.assertIn("is not empty", err)
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.out.exists())

    def test_happy_path_report_turntable_sheet(self):
        os.environ["FAKE_PREP_GLB"] = self.clean
        code, out, err = self.cli("mesh-prep", self.raw, "--out", self.out, "--concept", self.concept, "--frames", "3")
        self.assertEqual(code, 0, err)
        calls = self.calls()
        self.assertEqual(len(calls), 2, "meshprep.py, then the turntable scene")
        self.assertTrue(calls[0][calls[0].index("-P") + 1].endswith("meshprep.py"))
        self.assertTrue(calls[1][calls[1].index("-P") + 1].endswith("scene.py"))
        for name in ("mesh_report.json", "prep.json", "ho-giao_v01_prep.glb", "ho-giao_v01_prep.blend",
                     "silhouette_raw.png", "silhouette_prep.png", "compare.png", "turntable/turntable.json",
                     "turntable/render.json", "turntable/beauty.mp4", "turntable/still_front.png",
                     "turntable/still_34.png", "turntable/still_side.png"):
            self.assertTrue((self.out / name).is_file(), name)
        self.assertFalse((self.out / bl.CLAIM).exists())
        tt = json.loads((self.out / "turntable" / "turntable.json").read_text(encoding="utf-8"))
        self.assertEqual((tt["look"], tt["assets"][0]["src"], tt["turntable"]["stills"]),
                         ("clay", str((self.out / "ho-giao_v01_prep.glb").resolve()), ["front", "34", "side"]))
        self.assertEqual(round(tt["seconds"] * 24), 3)
        rep = json.loads((self.out / "mesh_report.json").read_text(encoding="utf-8"))
        self.assertEqual(rep["raw"]["stats"]["islands"], 2)
        self.assertEqual(rep["raw"]["stats"]["boundary_edges"], 3)
        self.assertTrue(rep["prep"]["stats"]["watertight"])
        self.assertEqual(rep["prep"]["stats"]["verts"], 8)
        self.assertEqual(rep["prep"]["blender"]["retopo"]["method"], "quadriflow")
        self.assertEqual(rep["prep"]["blender"]["env_gpu_held"], str(os.getpid()), "meshprep.py ran under the GPU lock")
        self.assertGreater(rep["silhouette"]["raw"]["iou"], 0.9)
        self.assertGreater(rep["silhouette"]["prep"]["iou"], 0.95)
        self.assertEqual(rep["files"]["turntable"], "turntable/")
        self.assertEqual(rep["turntable"]["stills"], ["still_front.png", "still_34.png", "still_side.png"])
        self.assertTrue(any(w.startswith("raw: not watertight") for w in rep["warnings"]))
        self.assertFalse(any(w.startswith("prep:") for w in rep["warnings"]))
        self.assertIn("raw: 15 tris", out)
        self.assertIn("prep: 12 tris, 8 verts, 1 island(s), 0 boundary + 0 over-shared edges -> watertight · quadriflow",
                      out)
        self.assertIn("raw vs concept: silhouette IoU", out)
        self.assertIn("mesh-prep ho-giao_v01 ->", out)
        with Image.open(self.out / "silhouette_prep.png") as im:
            self.assertEqual(im.mode, "L")
        code, _, err = self.cli("mesh-prep", self.raw, "--out", self.out)
        self.assertEqual(code, 2, "never into a used folder")
        self.assertIn("is not empty", err)

    def test_no_turntable_decimate_and_blender_failure(self):
        os.environ["FAKE_QUAD_FAIL"] = "1"
        code, out, err = self.cli("mesh-prep", self.raw, "--out", self.out, "--no-turntable", "--decimate", "5000",
                                  "--voxel", "0")
        self.assertEqual(code, 0, err)
        (call,) = self.calls()
        rest = call[call.index("--") + 1:]
        self.assertEqual(rest[rest.index("--voxel") + 1], "0")
        self.assertEqual(rest[rest.index("--decimate") + 1], "5000")
        self.assertFalse((self.out / "turntable").exists())
        rep = json.loads((self.out / "mesh_report.json").read_text(encoding="utf-8"))
        self.assertIsNone(rep["turntable"])
        self.assertIsNone(rep["silhouette"]["raw"], "no --concept: no IoU")
        self.assertIn("blender: QuadriFlow failed: decimated", rep["warnings"])
        self.assertIn("WARNING: blender: QuadriFlow failed", out)
        os.environ["FAKE_BLENDER_FAIL"] = "early"
        out2 = self.tmp / "prep_v02"
        code, _, err = self.cli("mesh-prep", self.raw, "--out", out2)
        self.assertEqual(code, 1)
        self.assertIn("Blender exited with 1", err)
        self.assertIn("QuadriFlow exploded", err)
        self.assertFalse((out2 / bl.CLAIM).exists())
        self.assertFalse((out2 / "mesh_report.json").exists())

    def test_prep_name(self):
        self.assertEqual(bl.prep_name("a/ho-giao_raw_v01.glb"), "ho-giao_v01")
        self.assertEqual(bl.prep_name("ho-giao_raw.glb"), "ho-giao")
        self.assertEqual(bl.prep_name("than-long_hi_s7.glb"), "than-long_hi_s7")
        self.assertEqual(bl.prep_name("_raw.glb"), "_raw")


class TestMeshprepScript(unittest.TestCase):
    def test_script_is_valid_python_and_never_overwrites(self):
        src = (helpers.TOOLS / "blender" / "meshprep.py").read_text(encoding="utf-8")
        compile(src, "meshprep.py", "exec")
        self.assertIn("refusing:", src)
        self.assertIn("quadriflow_remesh", src)
        self.assertIn('"VOXEL"', src)


if __name__ == "__main__":
    unittest.main()
