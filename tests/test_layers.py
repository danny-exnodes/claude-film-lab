"""tools/layers/{matte,anchors,upscale}.py and tools/bundle.py on small synthetic images."""
import contextlib, datetime, hashlib, io, json, multiprocessing, os, re, shutil, sys, types, unittest, zipfile
from pathlib import Path
from unittest import mock

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
        self.assertIn("method luminance paper #FFFFFF, low 8, high 245", so)
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


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ink_square(path, size=20):
    """White paper with a black square in the middle, saved as RGB."""
    a = np.full((size, size, 3), 255, np.uint8)
    a[size // 4:size * 3 // 4, size // 4:size * 3 // 4] = 0
    rgb_image(a).save(path)
    return path


class FakeRembg:
    """Stands in for the rembg package: records calls, never loads or downloads a model."""

    def __init__(self):
        self.sessions, self.removes = [], []
        self.module = types.ModuleType("rembg")
        self.module.new_session = self.new_session
        self.module.remove = self.remove

    def new_session(self, name="bria-rmbg", *args, **kwargs):
        self.sessions.append(name)
        return ("session", name, len(self.sessions))

    def remove(self, img, session=None, **kwargs):
        self.removes.append(session)
        out = img.convert("RGBA")
        al = np.zeros((out.height, out.width), np.uint8)
        al[out.height // 4:out.height * 3 // 4, out.width // 4:out.width * 3 // 4] = 255
        out.putalpha(Image.fromarray(al, "L"))
        return out


class RembgCase(TmpDirCase):
    """Fake rembg in sys.modules, model folders pointed at a temp dir, session cache emptied."""
    ENV = ("U2NET_HOME", "REMBG_HOME", "XDG_DATA_HOME", "FILM_REMBG_MODEL")

    def setUp(self):
        super().setUp()
        self.fake = FakeRembg()
        self.home = self.tmp / "rembg-home"
        self.home.mkdir()
        env = {k: v for k, v in os.environ.items() if k not in self.ENV}
        env["U2NET_HOME"] = str(self.home)
        env["HOME"] = str(self.tmp / "nohome")
        for p in (mock.patch.dict(sys.modules, {"rembg": self.fake.module}),
                  mock.patch.dict(os.environ, env, clear=True)):
            p.start()
            self.addCleanup(p.stop)
        matte._REMBG_SESSIONS.clear()
        self.addCleanup(matte._REMBG_SESSIONS.clear)

    def cache(self, model, legacy=False):
        f = self.home / f"{model}.onnx" if legacy else self.home / "models" / model / f"{model}.onnx"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"not a model")


class TestMatteRembgModel(RembgCase, unittest.TestCase):
    def test_default_model_is_u2net_and_session_is_reused(self):
        self.assertEqual(matte.REMBG_MODEL, "u2net")
        im = Image.new("RGB", (16, 16), "white")
        for _ in range(2):
            out = np.asarray(matte.run(im, "rembg", low=60, high=200))
        self.assertEqual(self.fake.sessions, ["u2net"])                      # one session for two calls
        self.assertEqual(self.fake.removes, [("session", "u2net", 1)] * 2)   # ... and remove() gets it
        self.assertEqual(out[0, 0, 3], 0)
        self.assertEqual(out[8, 8, 3], 255)

    def test_run_keyword_and_one_session_per_model(self):
        im = Image.new("RGB", (8, 8), "white")
        matte.run(im, "rembg", rembg_model="isnet-general-use")
        matte.run(im, "rembg")
        matte.run(im, "rembg", rembg_model="isnet-general-use")
        self.assertEqual(self.fake.sessions, ["isnet-general-use", "u2net"])
        self.assertEqual([s[1] for s in self.fake.removes], ["isnet-general-use", "u2net", "isnet-general-use"])
        _, a = matte.matte_rembg(im)                                         # positional use keeps working
        self.assertEqual(self.fake.removes[-1][1], "u2net")

    def test_cli_default_flag_and_env(self):
        src = ink_square(self.tmp / "x.png")
        for m in ("u2net", "isnet-general-use", "silueta"):
            self.cache(m)
        code, so, err = run_main(matte.main, [str(src), str(self.tmp / "a.png"), "--method", "rembg"])
        self.assertEqual(code, 0, err)
        self.assertIn("method rembg(u2net)", so)
        with mock.patch.dict(os.environ, {"FILM_REMBG_MODEL": "silueta"}):
            code, so, err = run_main(matte.main, [str(src), str(self.tmp / "b.png"), "--method", "rembg"])
            self.assertEqual(code, 0, err)
            self.assertIn("method rembg(silueta)", so)
            code, so, err = run_main(matte.main, [str(src), str(self.tmp / "c.png"), "--method", "rembg",
                                                  "--rembg-model", "isnet-general-use"])   # flag beats env
            self.assertEqual(code, 0, err)
            self.assertIn("method rembg(isnet-general-use)", so)
        self.assertEqual(self.fake.sessions, ["u2net", "silueta", "isnet-general-use"])
        with Image.open(self.tmp / "c.png") as im:
            self.assertEqual(im.getpixel((0, 0))[3], 0)
            self.assertEqual(im.getpixel((10, 10))[3], 255)

    def test_not_cached_is_refused_before_rembg_is_touched(self):
        src = ink_square(self.tmp / "x.png")
        out = self.tmp / "o.png"
        code, _, err = run_main(matte.main, [str(src), str(out), "--method", "rembg"])
        self.assertEqual(code, 2)
        self.assertIn("matte: rembg model u2net is not cached", err)
        self.assertIn("--allow-download", err)
        self.assertEqual((self.fake.sessions, self.fake.removes), ([], []))
        self.assertFalse(out.exists())
        self.cache("u2net")                                   # another model being cached does not help
        code, _, err = run_main(matte.main, [str(src), str(out), "--method", "rembg", "--rembg-model", "bria-rmbg"])
        self.assertEqual(code, 2)
        self.assertIn("rembg model bria-rmbg is not cached", err)
        self.assertEqual(self.fake.sessions, [])

    def test_allow_download_skips_the_check(self):
        src = ink_square(self.tmp / "x.png")
        code, so, err = run_main(matte.main, [str(src), str(self.tmp / "o.png"), "--method", "rembg", "--allow-download"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.fake.sessions, ["u2net"])

    def test_other_methods_do_not_need_the_model(self):
        src = ink_square(self.tmp / "x.png")
        code, _, err = run_main(matte.main, [str(src), str(self.tmp / "o.png"), "--method", "luminance"])
        self.assertEqual(code, 0, err)

    def test_style_rembg_layer_checks_the_cache_too(self):
        src = ink_square(self.tmp / "ep01_s01_L4_thu_v01.png")
        code, _, err = run_main(matte.main, [str(src), str(self.tmp / "o.png"), "--style", str(STYLE_FIX)])
        self.assertEqual(code, 2)
        self.assertIn("is not cached", err)

    def test_cache_locations(self):
        self.assertFalse(matte.rembg_model_cached("u2net"))
        self.cache("u2net", legacy=True)                      # $U2NET_HOME/u2net.onnx (old layout)
        self.assertTrue(matte.rembg_model_cached("u2net"))
        self.assertFalse(matte.rembg_model_cached("silueta"))
        self.cache("silueta")                                 # $U2NET_HOME/models/silueta/silueta.onnx
        self.assertTrue(matte.rembg_model_cached("silueta"))
        rh, xdg, home = self.tmp / "rh", self.tmp / "xdg", self.tmp / "nohome"
        cases = [({"REMBG_HOME": str(rh)}, rh / "models/m1/m1.onnx", "m1"),
                 ({"XDG_DATA_HOME": str(xdg)}, xdg / "rembg/models/m2/m2.onnx", "m2"),
                 ({"XDG_DATA_HOME": str(xdg)}, xdg / ".u2net/m3.onnx", "m3"),
                 ({}, home / ".rembg/models/m4/m4.onnx", "m4"),
                 ({}, home / ".u2net/m5.onnx", "m5")]
        for extra, f, model in cases:
            env = {k: v for k, v in os.environ.items() if k not in self.ENV}
            env.update(extra)
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertFalse(matte.rembg_model_cached(model), model)
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(b"x")
                self.assertTrue(matte.rembg_model_cached(model), model)

    def test_model_name_cannot_be_a_path(self):
        src = ink_square(self.tmp / "x.png")
        code, _, err = run_main(matte.main, [str(src), str(self.tmp / "o.png"), "--method", "rembg",
                                             "--rembg-model", "../u2net"])
        self.assertEqual(code, 2)
        self.assertEqual(self.fake.sessions, [])


class TestMatteOverwrite(TmpDirCase, unittest.TestCase):
    def test_in_equals_out_is_refused(self):
        src = ink_square(self.tmp / "ep01_s01_L2_nui_v01.png")
        before = sha(src)
        link = self.tmp / "link.png"
        os.symlink(src, link)
        (self.tmp / "sub").mkdir()
        spellings = [str(src), str(self.tmp / "." / "sub" / ".." / src.name), str(link)]
        for out in spellings:
            for extra in ([], ["--overwrite"]):
                code, so, err = run_main(matte.main, [str(src), out, "--style", str(STYLE_FIX)] + extra)
                self.assertEqual(code, 2, (out, extra, so))
                self.assertIn("OUT is the same file as IN: the source image is never overwritten", err)
                self.assertEqual(sha(src), before)
        with Image.open(src) as im:
            self.assertEqual(im.mode, "RGB")

    def test_in_equals_out_when_in_is_missing(self):
        code, _, err = run_main(matte.main, [str(self.tmp / "nope.png"), str(self.tmp / "x" / ".." / "nope.png"),
                                             "--method", "none"])
        self.assertEqual(code, 2)
        self.assertIn("same file as IN", err)

    def test_existing_out_is_refused_without_overwrite(self):
        src = ink_square(self.tmp / "x.png")
        out = self.tmp / "o.png"
        out.write_bytes(b"an approved matte")
        code, _, err = run_main(matte.main, [str(src), str(out), "--method", "luminance"])
        self.assertEqual(code, 2)
        self.assertIn("OUT exists (versions only go up; --overwrite replaces a matte)", err)
        self.assertEqual(out.read_bytes(), b"an approved matte")
        code, so, err = run_main(matte.main, [str(src), str(out), "--method", "luminance", "--overwrite"])
        self.assertEqual(code, 0, err)
        with Image.open(out) as im:
            self.assertEqual(im.mode, "RGBA")

    def test_default_out_is_matte_subfolder(self):
        plates = self.tmp / "plates"
        plates.mkdir()
        src = ink_square(plates / "ep01_s01_L2_nui_v01.png")
        before = sha(src)
        code, so, err = run_main(matte.main, [str(src), "--style", str(STYLE_FIX)])
        self.assertEqual(code, 0, err)
        out = plates / "matte" / "ep01_s01_L2_nui_v01.png"
        self.assertIn(f"saved {out} ", so)
        with Image.open(out) as im:
            self.assertEqual(im.mode, "RGBA")
        self.assertEqual(sha(src), before)
        code, _, err = run_main(matte.main, [str(src), "--style", str(STYLE_FIX)])     # second run: OUT exists
        self.assertEqual(code, 2)
        self.assertIn("OUT exists", err)

    def test_default_out_for_a_jpeg_is_png(self):
        src = self.tmp / "ep01_s01_L2_nui_v01.jpg"
        Image.new("RGB", (8, 8), "white").save(src)
        code, so, err = run_main(matte.main, [str(src), "--method", "luminance"])
        self.assertEqual(code, 0, err)
        self.assertTrue((self.tmp / "matte" / "ep01_s01_L2_nui_v01.png").is_file())

    def test_preview_equal_to_in_or_out_is_refused(self):
        src = ink_square(self.tmp / "x.png")
        before = sha(src)
        out = self.tmp / "o.png"
        for prev in (out, src, self.tmp / "sub" / ".." / "o.png"):
            code, _, err = run_main(matte.main, [str(src), str(out), "--method", "luminance", "--preview", str(prev)])
            self.assertEqual(code, 2, prev)
            self.assertIn("--preview", err)
            self.assertFalse(out.exists())
            self.assertEqual(sha(src), before)
        code, _, err = run_main(matte.main, [str(src), "--method", "luminance",
                                             "--preview", str(self.tmp / "matte" / "x.png")])   # the default OUT
        self.assertEqual(code, 2)
        self.assertFalse((self.tmp / "matte").exists())

    def test_help_explains_default_out_and_model_flags(self):
        code, so, _ = run_main(matte.main, ["--help"])
        self.assertEqual(code, 0)
        for text in ("matte/<IN stem>.png", "--rembg-model", "--allow-download", "--overwrite", "FILM_REMBG_MODEL"):
            self.assertIn(text, so)


class TestMatteStyleBackground(TmpDirCase, unittest.TestCase):
    def style(self, per_layer, key_bg="#FF00FF", paper_bg="#FFFFFF"):
        d = self.tmp / "style"
        d.mkdir(exist_ok=True)
        (d / "style.yaml").write_text(
            f'id: t\nmatte:\n  key_bg: "{key_bg}"\n  paper_bg: "{paper_bg}"\n  per_layer:\n{per_layer}', encoding="utf-8")
        return str(d)

    def block(self, name, bg, fg):
        a = np.empty((40, 40, 3), np.uint8); a[:] = bg; a[10:30, 10:30] = fg
        p = self.tmp / name
        rgb_image(a).save(p)
        return str(p)

    def alpha(self, path):
        with Image.open(path) as im:
            return im.getpixel((0, 0))[3], im.getpixel((20, 20))[3]

    def test_chroma_uses_layer_bg(self):
        style = self.style('    L3: {method: chroma, low: 30, high: 220, bg: "#00FF00"}\n')
        src = self.block("ep01_s01_L3_da_v01.png", (0, 255, 0), (120, 120, 120))
        out = self.tmp / "o.png"
        code, so, err = run_main(matte.main, [src, str(out), "--style", style])
        self.assertEqual(code, 0, err)
        self.assertIn("method chroma key #00FF00, low 30, high 220", so)
        self.assertEqual(self.alpha(out), (0, 255))

    def test_luminance_uses_layer_bg(self):
        style = self.style('    L2: {method: luminance, low: 8, high: 245, bg: "#f4efe4"}\n')
        src = self.block("ep01_s01_L2_nui_v01.png", (244, 239, 228), (0, 0, 0))
        out = self.tmp / "o.png"
        code, so, err = run_main(matte.main, [src, str(out), "--style", style])
        self.assertEqual(code, 0, err)
        self.assertIn("method luminance paper #F4EFE4", so)
        self.assertEqual(self.alpha(out), (0, 255))

    def test_without_bg_the_top_level_colours_apply(self):
        style = self.style("    L3: {method: chroma}\n    L2: {method: luminance}\n", key_bg="#0000FF", paper_bg="#F4EFE4")
        out = self.tmp / "o3.png"
        code, so, err = run_main(matte.main, [self.block("ep01_s01_L3_da_v01.png", (0, 0, 255), (200, 200, 0)),
                                              str(out), "--style", style])
        self.assertEqual(code, 0, err)
        self.assertIn("method chroma key #0000FF", so)
        self.assertEqual(self.alpha(out), (0, 255))
        out = self.tmp / "o2.png"
        code, so, err = run_main(matte.main, [self.block("ep01_s01_L2_nui_v01.png", (244, 239, 228), (0, 0, 0)),
                                              str(out), "--style", style])
        self.assertIn("method luminance paper #F4EFE4", so)
        self.assertEqual(self.alpha(out), (0, 255))

    def test_flag_wins_over_bg(self):
        style = self.style('    L3: {method: chroma, bg: "#00FF00"}\n    L2: {method: luminance, bg: "#F4EFE4"}\n')
        out = self.tmp / "o3.png"
        code, so, err = run_main(matte.main, [self.block("ep01_s01_L3_da_v01.png", (0, 0, 255), (200, 200, 0)),
                                              str(out), "--style", style, "--key", "#0000FF"])
        self.assertEqual(code, 0, err)
        self.assertIn("method chroma key #0000FF", so)
        self.assertEqual(self.alpha(out), (0, 255))
        out = self.tmp / "o2.png"
        code, so, err = run_main(matte.main, [self.block("ep01_s01_L2_nui_v01.png", (255, 255, 255), (0, 0, 0)),
                                              str(out), "--style", style, "--paper", "#FFFFFF"])
        self.assertEqual(code, 0, err)
        self.assertIn("method luminance paper #FFFFFF", so)
        self.assertEqual(self.alpha(out), (0, 255))

    def test_bg_follows_the_method_actually_used(self):
        # bg is the flat background the layer was generated on, whatever method the style names:
        # L4 is rembg on white, and --method chroma / luminance then key on that white, not on key_bg / paper_bg
        style = self.style('    L4: {method: rembg, bg: "#FFFFFF"}\n', paper_bg="#F4EFE4")
        self.assertEqual(matte.style_settings(style, "L4")["bg"], "#FFFFFF")
        src = self.block("ep01_s01_L4_thu_v01.png", (255, 255, 255), (20, 20, 20))
        for method, how in (("chroma", "chroma key #FFFFFF"), ("luminance", "luminance paper #FFFFFF")):
            out = self.tmp / f"{method}.png"
            code, so, err = run_main(matte.main, [src, str(out), "--style", style, "--method", method])
            self.assertEqual(code, 0, err)
            self.assertIn("method " + how, so)
            self.assertEqual(self.alpha(out)[0], 0)
            self.assertGreater(self.alpha(out)[1], 230)

    def test_bad_bg_colour(self):
        style = self.style('    L3: {method: chroma, bg: "green"}\n')
        code, _, err = run_main(matte.main, [self.block("ep01_s01_L3_da_v01.png", (0, 255, 0), (9, 9, 9)),
                                             str(self.tmp / "o.png"), "--style", style])
        self.assertEqual(code, 1)
        self.assertIn("matte: ", err)

    def test_non_mapping_layer_spec(self):
        style = self.style("    L4: rembg\n")
        code, _, err = run_main(matte.main, [self.block("ep01_s01_L4_thu_v01.png", (255, 255, 255), (0, 0, 0)),
                                             str(self.tmp / "o.png"), "--style", style])
        self.assertEqual(code, 1)
        self.assertRegex(err, r"^matte: .*per_layer\.L4 must be a mapping")
        self.assertNotIn("Traceback", err)

    def test_missing_style_yaml(self):
        src = self.block("ep01_s01_L2_nui_v01.png", (255, 255, 255), (0, 0, 0))
        code, _, err = run_main(matte.main, [src, str(self.tmp / "o.png"), "--style", str(self.tmp / "no-such-style")])
        self.assertEqual(code, 1)
        self.assertRegex(err, r"^matte: .*no-such-style.*style\.yaml")

    def test_missing_or_unreadable_in(self):
        out = self.tmp / "o.png"
        code, _, err = run_main(matte.main, [str(self.tmp / "nope.png"), str(out), "--method", "luminance"])
        self.assertEqual(code, 1)
        self.assertRegex(err, r"^matte: cannot read .*nope\.png")
        bad = self.tmp / "bad.png"
        bad.write_text("this is not an image")
        code, _, err = run_main(matte.main, [str(bad), str(out), "--method", "luminance"])
        self.assertEqual(code, 1)
        self.assertRegex(err, r"^matte: cannot read .*bad\.png")
        self.assertFalse(out.exists())
        self.assertFalse((self.tmp / "matte").exists())


# sha256[:12] of matte.run() output on the opaque image of test_opaque_input_is_unchanged, keyed by
# (method, with low/high); recorded from the code before source alpha was combined into the matte
OPAQUE_BASELINE = {("luminance", False): "81217ed54747", ("luminance", True): "10d1f815f4a4",
                   ("chroma", False): "1c8b17dc9f25", ("chroma", True): "1c8b17dc9f25", ("none", False): "552bae27c97b"}


class TestMatteSourceAlpha(TmpDirCase, unittest.TestCase):
    def rgba(self):
        a = np.zeros((40, 40, 4), np.uint8)              # transparent black ...
        a[10:30, 10:30] = (255, 0, 0, 255)               # ... around an opaque red square
        return Image.fromarray(a, "RGBA")

    def test_rgba_keeps_transparent_pixels(self):
        for method in ("luminance", "chroma"):
            with contextlib.redirect_stderr(io.StringIO()):
                out = np.asarray(matte.run(self.rgba(), method))
            self.assertEqual(out[0, 0, 3], 0, method)
            self.assertEqual(out[20, 20, 3], 255, method)
            self.assertEqual(tuple(out[20, 20, :3]), (255, 0, 0), method)

    def test_partial_source_alpha_scales_the_matte(self):
        a = np.asarray(self.rgba()).copy(); a[10:30, 10:20, 3] = 128
        with contextlib.redirect_stderr(io.StringIO()):
            out = np.asarray(matte.run(Image.fromarray(a, "RGBA"), "chroma", low=20, high=230))
        self.assertEqual(out[20, 15, 3], 128)
        self.assertEqual(out[20, 25, 3], 255)

    def test_la_keeps_transparent_pixels(self):
        a = np.zeros((20, 20, 2), np.uint8)
        a[5:15, 5:15] = (0, 255)
        with contextlib.redirect_stderr(io.StringIO()):
            out = np.asarray(matte.run(Image.fromarray(a, "LA"), "luminance"))
        self.assertEqual(out[0, 0, 3], 0)
        self.assertEqual(out[10, 10, 3], 255)

    def test_palette_transparency_and_note(self):
        im = Image.new("P", (20, 20), 0)
        im.putpalette([90, 90, 90, 0, 0, 0] + [0] * 756)
        im.paste(1, (5, 5, 15, 15))
        src = self.tmp / "pal.png"
        im.save(src, transparency=0)
        for method in ("luminance", "chroma"):
            out = self.tmp / f"{method}.png"
            code, so, err = run_main(matte.main, [str(src), str(out), "--method", method])
            self.assertEqual(code, 0, err)
            self.assertEqual(err.count("already has alpha"), 1)
            with Image.open(out) as o:
                self.assertEqual(o.getpixel((0, 0))[3], 0)
                self.assertEqual(o.getpixel((10, 10))[3], 255)
            self.assertIn("transparent 75.0%", so)

    def test_none_keeps_source_alpha_without_note(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            out = np.asarray(matte.run(self.rgba(), "none"))
        self.assertEqual((out[0, 0, 3], out[20, 20, 3]), (0, 255))
        self.assertEqual(err.getvalue(), "")

    def test_opaque_input_is_unchanged(self):
        a = np.full((40, 40, 3), 255, np.uint8)
        a[5:20, 5:20] = (30, 60, 90); a[20:35, 5:35] = 128; a[0:5] = (255, 0, 255)
        rgb = rgb_image(a)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            for method, kw in (("luminance", {}), ("luminance", {"low": 8, "high": 245}), ("chroma", {}),
                               ("chroma", {"low": 20, "high": 230}), ("none", {})):
                plain = np.asarray(matte.run(rgb, method, **kw))
                self.assertTrue((plain == np.asarray(matte.run(rgb.convert("RGBA"), method, **kw))).all(), method)
                self.assertEqual(hashlib.sha256(plain.tobytes()).hexdigest()[:12], OPAQUE_BASELINE[method, bool(kw)])
        self.assertEqual(err.getvalue(), "")                 # no note for an opaque source

    def test_exif_orientation_is_applied(self):
        src = self.tmp / "rot.jpg"
        exif = Image.Exif()
        exif[0x0112] = 6                                     # displayed rotated: 80x60 stored, 60x80 shown
        Image.new("RGB", (80, 60), "white").save(src, exif=exif)
        out = self.tmp / "o.png"
        code, so, err = run_main(matte.main, [str(src), str(out), "--method", "none"])
        self.assertEqual(code, 0, err)
        with Image.open(out) as im:
            self.assertEqual(im.size, (60, 80))


def _set_many(path, name, worker, n):
    """Child process for TestAnchors.test_parallel_set_loses_no_points."""
    with contextlib.redirect_stdout(io.StringIO()):
        for k in range(n):
            anchors.set_point(path, name, f"w{worker}_{k}", worker, k)


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

    def test_parallel_set_loses_no_points(self):
        # up to 3 plate-makers write anchors.json at once (CONVENTIONS §10): flock on .anchors.json.lock
        j = str(self.tmp / "ep" / "anchors.json")
        ctx = multiprocessing.get_context("fork")
        procs = [ctx.Process(target=_set_many, args=(j, self.NAME, w, 20)) for w in range(3)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(60)
            self.assertEqual(p.exitcode, 0)
        pts = json.loads(Path(j).read_text())[self.NAME]
        self.assertEqual(len(pts), 60)
        self.assertEqual(pts["w2_19"], [2, 19])
        self.assertTrue((Path(j).parent / ".anchors.json.lock").exists())
        self.assertFalse(Path(j + ".lock").exists())

    def test_set_rejects_non_numbers(self):
        code, _, _ = run_main(anchors.main, ["set", str(self.tmp / "a.json"), self.NAME, "neck", "x", "1"])
        self.assertEqual(code, 2)

    def test_nan_and_inf_are_rejected(self):
        j = self.tmp / "a.json"
        run_main(anchors.main, ["set", str(j), self.NAME, "neck", "1", "2"])
        before = j.read_bytes()
        for x, y in (("nan", "5"), ("5", "NaN"), ("inf", "1"), ("1", "+inf"), ("1e999", "1"), ("Infinity", "1")):
            code, _, err = run_main(anchors.main, ["set", str(j), self.NAME, "neck", x, y])
            self.assertEqual(code, 2, (x, y))
            self.assertIn("X and Y must be", err)
            self.assertEqual(j.read_bytes(), before)
        for bad in (float("nan"), float("inf"), "nan", "-inf"):
            with self.assertRaises(ValueError):
                anchors.set_point(str(j), self.NAME, "neck", bad, 1)
        self.assertEqual(j.read_bytes(), before)
        json.loads(before, parse_constant=self.fail)             # strict JSON: no NaN / Infinity token

    def test_corrupt_file_is_named(self):
        j = self.tmp / "g.json"
        j.write_text('{"x": ')
        code, _, err = run_main(anchors.main, ["set", str(j), self.NAME, "feet", "50", "60"])
        self.assertEqual(code, 1)
        self.assertIn(f"{j}: not valid JSON (", err)
        self.assertNotIn("must be numbers", err)
        self.assertEqual(j.read_text(), '{"x": ')
        img = self.tmp / self.NAME
        Image.new("RGB", (10, 10)).save(img)
        code, _, err = run_main(anchors.main, ["mark", str(img), str(j), str(self.tmp / "m.png")])
        self.assertEqual(code, 1)
        self.assertIn("not valid JSON", err)

    def test_bad_and_reserved_point_names(self):
        j = self.tmp / "a.json"
        with self.assertRaises(ValueError):
            anchors.set_point(str(j), self.NAME, "-x", 1, 2)     # (argparse itself refuses "-x" on the CLI)
        for name in ("", "tail tl", "_x", "a.b", "đuôi", "a/b", "size", "_size", "points", "boxes", "version"):
            code, _, err = run_main(anchors.main, ["set", str(j), self.NAME, name, "1", "2"])
            self.assertEqual(code, 2, name)
            self.assertIn("point name", err)
            with self.assertRaises(ValueError):
                anchors.set_point(str(j), self.NAME, name, 1, 2)
        self.assertFalse(j.exists())
        for name in ("neck", "tail_root", "P1-duoi", "9"):
            code, _, err = run_main(anchors.main, ["set", str(j), self.NAME, name, "1", "2"])
            self.assertEqual(code, 0, name)

    def test_lock_is_a_dotfile(self):
        ep = self.tmp / "ep"
        j = ep / "anchors.json"
        code, _, _ = run_main(anchors.main, ["set", str(j), self.NAME, "neck", "1", "2"])
        self.assertEqual(code, 0)
        self.assertTrue((ep / ".anchors.json.lock").exists())
        self.assertEqual([n for n in os.listdir(ep) if not n.startswith(".")], ["anchors.json"])

    def test_failed_dump_leaves_no_temp_file(self):
        ep = self.tmp / "ep"
        j = ep / "anchors.json"
        run_main(anchors.main, ["set", str(j), self.NAME, "neck", "1", "2"])
        before = j.read_bytes()
        with self.assertRaises(ValueError):
            anchors.save(str(j), {self.NAME: {"neck": [float("nan"), 1]}})
        with self.assertRaises(TypeError):
            anchors.save(str(j), {self.NAME: {"neck": {1, 2}}})
        self.assertEqual(j.read_bytes(), before)
        self.assertEqual(sorted(os.listdir(ep)), [".anchors.json.lock", "anchors.json"])

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

    def test_in_equals_out_is_refused(self):
        src = self.tmp / "same.png"
        Image.new("RGBA", (20, 16), (9, 9, 9, 255)).save(src)
        before = sha(src)
        (self.tmp / "d").mkdir()
        for extra in ([], ["--overwrite"]):
            for out in (src, self.tmp / "d" / ".." / "same.png"):
                code, _, err = run_main(upscale.main, [str(src), str(out), "--factor", "2"] + extra)
                self.assertEqual(code, 2)
                self.assertIn("OUT is the same file as IN: the source image is never overwritten", err)
                self.assertEqual(sha(src), before)

    def test_existing_out_needs_overwrite(self):
        src, out = self.tmp / "i.png", self.tmp / "o.png"
        Image.new("RGB", (20, 16), "white").save(src)
        out.write_bytes(b"earlier upscale")
        code, _, err = run_main(upscale.main, [str(src), str(out), "--factor", "2"])
        self.assertEqual(code, 2)
        self.assertIn("OUT exists", err)
        self.assertEqual(out.read_bytes(), b"earlier upscale")
        code, so, err = run_main(upscale.main, [str(src), str(out), "--factor", "2", "--overwrite"])
        self.assertEqual(code, 0, err)
        with Image.open(out) as im:
            self.assertEqual(im.size, (40, 32))

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

    def test_bundle_with_film(self):
        film = self.media / "film" / "demo"
        for rel, data in (("film.html", b"<html>"), ("STATE.md", b"# s"), ("review/qc-1.md", b"ok"),
                          ("renders/draft-v1.mp4", b"x"), ("plates/a.png", b"x"), ("node_modules/x/index.js", b"x")):
            p = film / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        code, so, err = run_main(bundle.main, [str(self.media), "--shot", "s02", "--with-film"])
        self.assertEqual(code, 0, err)
        day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        with zipfile.ZipFile(self.media / "bundles" / f"ep01_s02_{day}.zip") as z:
            film_names = sorted(n for n in z.namelist() if n.startswith("film/"))
        self.assertEqual(film_names, ["film/demo/STATE.md", "film/demo/film.html", "film/demo/review/qc-1.md"])

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

    def test_finds_episode_dir_in_projects(self):
        lab = self.tmp / "lab"
        ep_dir = lab / "projects" / "test-series" / "ep01-test-ep"
        shutil.copytree(EPISODE_FIX, ep_dir)
        (lab / "series" / "test-series" / "ep01-old").mkdir(parents=True)   # legacy layout loses to projects/
        old_lab, bundle.LAB = bundle.LAB, str(lab)
        try:
            self.assertEqual(bundle.find_series_dir(str(self.media)), str(ep_dir))
            shutil.rmtree(lab / "projects")
            self.assertEqual(bundle.find_series_dir(str(self.media)), str(lab / "series" / "test-series" / "ep01-old"))
        finally:
            bundle.LAB = old_lab

    def test_without_series_dir(self):
        code, so, err = run_main(bundle.main, [str(self.media), "--shot", "s01"])
        self.assertEqual(code, 0, err)
        self.assertIn("no episode dir found", so)


if __name__ == "__main__":
    unittest.main()
