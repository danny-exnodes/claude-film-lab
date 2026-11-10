"""tools/layers/{matte,anchors,upscale}.py and tools/bundle.py on small synthetic images."""
import datetime, hashlib, json, os, re, shutil, unittest, zipfile

import numpy as np
from PIL import Image

from helpers import EPISODE_FIX, STYLE_FIX, TmpDirCase, load, run_main

matte = load("layers/matte.py", "film_matte")
anchors = load("layers/anchors.py", "film_anchors")
upscale = load("layers/upscale.py", "film_upscale")
bundle = load("bundle.py", "film_bundle")


def rgb_image(arr):
    return Image.fromarray(np.asarray(arr, dtype=np.uint8), "RGB")


class TestMatteLuminance(unittest.TestCase):
    def setUp(self):
        a = np.full((40, 40, 3), 255, np.uint8)        # white paper
        a[0:10, 0:10] = 0                              # solid black ink
        a[10:20, 0:10] = 128                           # 50 % grey wash
        a[20:30, 0:10] = 250                           # paper texture / noise
        a[30:40, 0:10] = (200, 120, 120)               # light red wash
        self.src = rgb_image(a)

    def test_unmix_reproduces_original(self):
        out = np.asarray(matte.run(self.src, "luminance"), np.float32)
        al = out[..., 3:] / 255
        comp = out[..., :3] * al + 255 * (1 - al)      # over the paper colour
        self.assertLessEqual(np.abs(comp - np.asarray(self.src, np.float32)).max(), 2.0)
        self.assertEqual(out[0, 0, 3], 255)
        self.assertEqual(out[0, 39, 3], 0)                      # paper is transparent
        self.assertAlmostEqual(out[15, 5, 3], 127, delta=2)     # wash keeps half alpha
        self.assertLessEqual(out[15, 5, :3].max(), 2)           # ... with black ink colour (un-premultiplied)
        r, g, b, a = out[35, 5]
        self.assertGreater(r, g + 100)                          # red wash keeps its hue

    def test_cleanup_thresholds(self):
        out = np.asarray(matte.run(self.src, "luminance", low=8, high=245))
        self.assertEqual(out[25, 5, 3], 0)                      # 250 -> alpha 5 < low
        self.assertEqual(out[5, 5, 3], 255)
        self.assertTrue(100 < out[15, 5, 3] < 160)

    def test_cleanup_function(self):
        a = np.array([0, 8, 9, 126.5, 245, 246, 255], np.float32)
        c = matte.cleanup(a, 8, 245)
        self.assertEqual(c[0], 0); self.assertEqual(c[1], 0); self.assertEqual(c[-1], 255); self.assertEqual(c[-3], 255)
        self.assertAlmostEqual(c[3], 127.5, delta=0.6)
        with self.assertRaises(ValueError):
            matte.cleanup(a, 200, 100)

    def test_coloured_paper(self):
        paper = (244, 239, 228)
        a = np.empty((10, 10, 3), np.uint8); a[:] = paper; a[0, 0] = (26, 23, 20)
        out = np.asarray(matte.run(rgb_image(a), "luminance", paper="#F4EFE4"))
        self.assertEqual(out[5, 5, 3], 0)
        self.assertAlmostEqual(int(out[0, 0, 3]), round(255 * max((p - i) / p for p, i in zip(paper, (26, 23, 20)))), delta=1)
        al = out[0, 0, 3] / 255
        comp = out[0, 0, :3] * al + np.array(paper) * (1 - al)                               # over the same paper
        self.assertLessEqual(np.abs(comp - (26, 23, 20)).max(), 2.0)


class TestMatteChroma(unittest.TestCase):
    def setUp(self):
        a = np.zeros((40, 40, 3), np.uint8); a[:] = (255, 0, 255)   # magenta key
        a[10:30, 10:30] = (40, 160, 60)                             # green subject
        a[10:30, 10] = (255, 220, 255)                              # pink spill on the left edge
        a[18:22, 18:22] = (128, 0, 128)                             # purple detail deep inside
        self.src = rgb_image(a)

    def test_alpha_and_despill(self):
        out = np.asarray(matte.run(self.src, "chroma", key="#FF00FF"))
        self.assertEqual(out[0, 0, 3], 0)
        self.assertEqual(out[15, 15, 3], 255)
        self.assertEqual(tuple(out[15, 15, :3]), (40, 160, 60))     # interior untouched
        r, g, b = out[15, 10, :3]
        self.assertEqual(out[15, 10, 3], 255)
        self.assertLessEqual(max(r, b) - g, 1)                      # spill removed: neutral
        self.assertEqual(tuple(out[20, 20, :3]), (128, 0, 128))     # interior purple kept (not near an edge)

    def test_soft_edge(self):
        a = np.zeros((1, 3, 3), np.uint8); a[0] = [(255, 0, 255), (200, 40, 200), (40, 160, 60)]
        out = np.asarray(matte.run(rgb_image(a), "chroma"))
        self.assertEqual(out[0, 0, 3], 0)
        self.assertTrue(0 < out[0, 1, 3] < 255)
        self.assertEqual(out[0, 2, 3], 255)


class TestMatteCli(TmpDirCase, unittest.TestCase):
    def test_style_layer_from_name_and_preview(self):
        src = self.tmp / "ep01_s01_L2_nui_v01.png"
        a = np.full((20, 20, 3), 255, np.uint8); a[5:15, 5:15] = 0
        rgb_image(a).save(src)
        out, prev = self.tmp / "o.png", self.tmp / "p.png"
        code, so, err = run_main(matte.main, [str(src), str(out), "--style", str(STYLE_FIX), "--preview", str(prev)])
        self.assertEqual(code, 0, err)
        self.assertIn("method luminance, low 8, high 245", so)
        with Image.open(out) as im:
            self.assertEqual(im.mode, "RGBA")
            self.assertEqual(im.getpixel((0, 0))[3], 0)
        with Image.open(prev) as im:
            self.assertEqual(im.getpixel((0, 0)), (255, 0, 0))
            self.assertEqual(im.getpixel((10, 10)), (0, 0, 0))

    def test_part_layer_maps_to_p(self):
        self.assertEqual(matte.style_key("P1-duoi"), "P")
        self.assertEqual(matte.style_settings(str(STYLE_FIX), "P2-chan")["method"], "rembg")
        self.assertEqual(matte.style_settings(str(STYLE_FIX), "L3")["method"], "chroma")

    def test_flag_overrides_style_and_none(self):
        src = self.tmp / "x.png"
        rgb_image(np.zeros((4, 4, 3))).save(src)
        out = self.tmp / "o.png"
        code, so, _ = run_main(matte.main, [str(src), str(out), "--style", str(STYLE_FIX), "--layer", "L4", "--method", "none"])
        self.assertEqual(code, 0)
        self.assertIn("method none", so)
        with Image.open(out) as im:
            self.assertEqual(im.getpixel((1, 1)), (0, 0, 0, 255))

    def test_needs_method(self):
        src = self.tmp / "x.png"
        rgb_image(np.zeros((4, 4, 3))).save(src)
        code, _, err = run_main(matte.main, [str(src), str(self.tmp / "o.png")])
        self.assertEqual(code, 2)
        self.assertIn("--method is required", err)

    @unittest.skipUnless(os.environ.get("FILM_TEST_REMBG") == "1",
                         "rembg loads u2net (~50 s on this container); set FILM_TEST_REMBG=1 to run")
    def test_rembg(self):
        from PIL import ImageDraw
        im = Image.new("RGB", (128, 128), "white")
        ImageDraw.Draw(im).ellipse([30, 30, 98, 98], fill="black")
        out = np.asarray(matte.run(im, "rembg", low=60, high=200))
        self.assertEqual(out[2, 2, 3], 0)
        self.assertEqual(out[64, 64, 3], 255)


class TestAnchors(TmpDirCase, unittest.TestCase):
    NAME = "ep01_s02_L4_bac-thi_v02.png"

    def test_set_and_update(self):
        j = self.tmp / "ep" / "anchors.json"
        code, so, _ = run_main(anchors.main, ["set", str(j), "plates/" + self.NAME, "neck", "120", "80.5"])
        self.assertEqual(code, 0)
        self.assertIn("added", so)
        run_main(anchors.main, ["set", str(j), self.NAME, "tail", "300", "210"])
        code, so, _ = run_main(anchors.main, ["set", str(j), self.NAME, "neck", "121", "81"])
        self.assertIn("updated", so)
        self.assertIn("was [120, 80.5]", so)
        data = json.loads(j.read_text())
        self.assertEqual(data, {self.NAME: {"neck": [121, 81], "tail": [300, 210]}})

    def test_set_rejects_non_numbers(self):
        code, _, _ = run_main(anchors.main, ["set", str(self.tmp / "a.json"), self.NAME, "neck", "x", "1"])
        self.assertEqual(code, 2)

    def test_mark(self):
        img = self.tmp / self.NAME
        Image.new("RGBA", (400, 300), (0, 0, 0, 0)).save(img)
        out = self.tmp / "marked.png"
        code, so, err = run_main(anchors.main, ["mark", str(img), str(EPISODE_FIX / "anchors.json"), str(out)])
        self.assertEqual(code, 0, err)
        self.assertIn("2 point(s)", so)
        with Image.open(out) as im:
            self.assertEqual(im.size, (400, 300))
            px = np.asarray(im.convert("RGB"))
        yellow = (px[..., 0] > 240) & (px[..., 1] > 200) & (px[..., 2] < 40)
        self.assertTrue(yellow[80, 112:129].any())          # horizontal arm through (120, 80)
        self.assertTrue(yellow[195:226, 300].any())         # vertical arm through (300, 210)

    def test_mark_without_points(self):
        img = self.tmp / "ep01_s09_L1_x_v01.png"
        Image.new("RGB", (10, 10)).save(img)
        code, _, err = run_main(anchors.main, ["mark", str(img), str(EPISODE_FIX / "anchors.json"), str(self.tmp / "o.png")])
        self.assertEqual(code, 1)
        self.assertIn("no points stored", err)


class TestUpscale(TmpDirCase, unittest.TestCase):
    def test_factor_keeps_alpha(self):
        a = np.zeros((16, 20, 4), np.uint8)
        a[3:13, 4:16] = (255, 255, 255, 255)
        src, out = self.tmp / "i.png", self.tmp / "o.png"
        Image.fromarray(a, "RGBA").save(src)
        code, so, _ = run_main(upscale.main, [str(src), str(out), "--factor", "2"])
        self.assertEqual(code, 0)
        self.assertIn("20x16 -> 40x32 RGBA", so)
        with Image.open(out) as im:
            o = np.asarray(im)
        self.assertEqual(o.shape, (32, 40, 4))
        self.assertEqual(o[0, 0, 3], 0)
        self.assertEqual(o[16, 20, 3], 255)
        edge = o[(o[..., 3] > 0) & (o[..., 3] < 255)]
        self.assertTrue((edge[:, :3] >= 250).all())          # no dark fringe from transparent black

    def test_long_edge(self):
        self.assertEqual(upscale.target_size((1000, 500), long_edge=3000), (3000, 1500))
        self.assertEqual(upscale.target_size((500, 1000), factor=1.5), (750, 1500))
        with self.assertRaises(ValueError):
            upscale.target_size((5, 5), factor=0)


class TestBundle(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.media = self.tmp / "out" / "test-series" / "ep01"
        for rel in ("plates/ep01_s02_L4_bac-thi_v02.png", "plates/ep01_s02_P1-duoi_bac-thi_v01.png",
                    "plates/ep01_s01_L1_nui-co_v01.png", "clips/ep01_s02_seedance25_v01.mp4",
                    "renders/ep01_s02_draft_v01.mp4"):
            p = self.media / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(rel.encode())

    def test_bundle_shot(self):
        code, so, err = run_main(bundle.main, [str(self.media), "--shot", "s02", "--series-dir", str(EPISODE_FIX)])
        self.assertEqual(code, 0, err)
        day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        zp = self.media / "bundles" / f"ep01_s02_{day}.zip"
        self.assertTrue(zp.is_file())
        with zipfile.ZipFile(zp) as z:
            names = sorted(z.namelist())
            self.assertEqual(names, ["anchors.json", "clips/ep01_s02_seedance25_v01.mp4", "plates/ep01_s02_L4_bac-thi_v02.png",
                                     "plates/ep01_s02_P1-duoi_bac-thi_v01.png", "prompts.csv"])
            rows = z.read("prompts.csv").decode().splitlines()
            self.assertTrue(rows[0].startswith("file,shot,layer"))
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(",s02," in r for r in rows[1:]))
            self.assertEqual(list(json.loads(z.read("anchors.json"))), ["ep01_s02_L4_bac-thi_v02.png"])
        digest = hashlib.sha256(zp.read_bytes()).hexdigest()
        self.assertIn(f"drive  sha256:{digest}:{zp}", so)
        self.assertRegex(so, rf"size   {zp.stat().st_size} bytes")

    def test_no_files(self):
        code, _, err = run_main(bundle.main, [str(self.media), "--shot", "s07", "--series-dir", str(EPISODE_FIX)])
        self.assertEqual(code, 1)
        self.assertIn("no files containing _s07_", err)

    def test_without_series_dir(self):
        code, so, err = run_main(bundle.main, [str(self.media), "--shot", "s01"])
        self.assertEqual(code, 0, err)
        self.assertIn("no series dir found", so)


if __name__ == "__main__":
    unittest.main()
