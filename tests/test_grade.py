"""tools/compose/grade.py: two-layer ink-wash grade + .cube export. Synthetic frames and passes only; free.
The mp4 tests need ffmpeg/ffprobe on PATH and skip without them."""
import json, re, shutil, unittest

import numpy as np
from PIL import Image

from helpers import REPO, TmpDirCase, load, run_main

grade = load("compose/grade.py")
ce = load("check_episode.py")
STYLE = REPO / "styles" / "chan-thuc-blender"
HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
W, H = 96, 54


def sat(rgb):
    rgb = np.asarray(rgb, np.float32) / 255.0
    mx, mn = rgb.max(-1), rgb.min(-1)
    return np.where(mx > 1e-3, (mx - mn) / np.maximum(mx, 1e-3), 0)


def frame(colour=(70, 150, 60)):
    img = np.zeros((H, W, 3), np.uint8)
    img[...] = colour
    img[:, :, 0] = np.linspace(40, 200, W).astype(np.uint8)[None, :]      # a little variety for the LUT
    return img


def depth_pass(near_top=True):
    """16-bit like Blender's: near = white. Top row near, bottom row far (or the reverse)."""
    v = np.linspace(65535, 0, H) if near_top else np.linspace(0, 65535, H)
    return np.tile(v[:, None], (1, W)).astype(np.uint16)


def mask_pass():
    m = np.zeros((H, W), np.uint8)
    m[:, W // 2:] = 255
    return m


def make_render(root, frames=3, asset="beast"):
    """A fake renders3d/s<NN>/ folder: beauty/, depth/, mask/<asset>/, render.json."""
    for d in ("beauty", "depth", f"mask/{asset}"):
        (root / d).mkdir(parents=True)
    for f in range(1, frames + 1):
        Image.fromarray(frame((60 + f * 10, 150, 60))).save(root / "beauty" / f"{f:04d}.png")
        Image.fromarray(depth_pass()).save(root / "depth" / f"{f:04d}.png")
        Image.fromarray(mask_pass()).save(root / "mask" / asset / f"{f:04d}.png")
    (root / "render.json").write_text(json.dumps({"fps": 24, "depth_range": [0.5, 100]}), encoding="utf-8")
    return root


def style_grade():
    g, _ = grade.load_params(style=str(STYLE))
    return g


class TestParameters(TmpDirCase, unittest.TestCase):
    def test_style_pack_grade_is_valid_and_has_two_layers(self):
        g = style_grade()
        self.assertEqual(grade.validate(g), [])
        scene, subject, seed = grade.resolve(g)
        self.assertIsNotNone(subject)
        self.assertEqual(seed, 7)
        # subject inherits what it does not set (hue pulls, mist colour) and overrides the rest
        self.assertEqual(subject["hue_pull"].keys(), scene["hue_pull"].keys())
        self.assertGreater(subject["saturation"]["green"], scene["saturation"]["green"])

    def test_errors_name_the_key_and_the_reason(self):
        errs = grade.validate({"scene": {"tone": {"black": 2, "contrst": 1}, "split": {"shadow": "red"},
                                         "hue_pull": {"blue": {"amount": 0.5}}},
                               "subject": {"paper": {"amount": 0.1}}, "sed": 1})
        text = "\n".join(errs)
        self.assertIn("grade.scene.tone.black: 2 is out of range 0-0.5", text)
        self.assertIn("grade.scene.tone: unknown key 'contrst'", text)
        self.assertIn("grade.scene.split.shadow: 'red' is not \"#RRGGBB\"", text)
        self.assertIn("grade.scene.hue_pull.blue: 'to'", text)
        self.assertIn("set them under scene", text)
        self.assertIn("grade: unknown key 'sed'", text)
        self.assertEqual(grade.validate([1]), ["grade: must be a mapping {seed, scene, subject}"])
        self.assertIn("must be a number", grade.validate({"scene": {"mist": {"amount": True}}})[0])

    def test_bad_style_yaml_is_refused_with_a_clear_message(self):
        st = self.tmp / "styles" / "x"
        st.mkdir(parents=True)
        (st / "style.yaml").write_text("id: x\ngrade: {scene: [\n", encoding="utf-8")
        code, out, err = run_main(grade.main, ["--check", "--style", str(st)])
        self.assertEqual(code, 2)
        self.assertRegex(err, r"style\.yaml: not valid YAML")
        (st / "style.yaml").write_text("id: x\n", encoding="utf-8")
        code, _, err = run_main(grade.main, ["--check", "--style", str(st)])
        self.assertEqual(code, 2)
        self.assertIn("no 'grade:' block", err)
        (st / "style.yaml").write_text("grade:\n  scene:\n    tone: {white: 0.2}\n", encoding="utf-8")
        code, _, err = run_main(grade.main, ["--check", "--style", str(st)])
        self.assertEqual(code, 2)
        self.assertIn("grade.scene.tone.white: 0.2 is out of range 0.5-1", err)

    def test_params_json_is_merged_over_the_style(self):
        p = self.tmp / "shot.json"
        p.write_text(json.dumps({"grade": {"scene": {"mist": {"amount": 0.1}}}}), encoding="utf-8")
        g, srcs = grade.load_params(str(STYLE), str(p))
        self.assertEqual(g["scene"]["mist"]["amount"], 0.1)
        self.assertEqual(g["scene"]["mist"]["color"], style_grade()["scene"]["mist"]["color"])
        self.assertEqual(len(srcs), 2)
        p.write_text("{oops", encoding="utf-8")
        code, _, err = run_main(grade.main, ["--check", "--params", str(p)])
        self.assertEqual((code, "not valid JSON" in err), (2, True))

    def test_check_episode_validates_the_grade_block(self):
        code, out, _ = run_main(ce.main, ["style", str(STYLE)])
        self.assertNotIn("unknown key 'grade'", out)
        self.assertNotRegex(out, r"(?m)^ERROR.*grade")
        st = self.tmp / "styles" / "chan-thuc-blender"
        shutil.copytree(STYLE, st)
        y = (st / "style.yaml").read_text(encoding="utf-8").replace("contrast: 0.8,", "contrast: 9,", 1)
        (st / "style.yaml").write_text(y, encoding="utf-8")
        code, out, _ = run_main(ce.main, ["style", str(st)])
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"ERROR.*grade\.scene\.tone\.contrast: 9 is out of range")


class TestGrade(unittest.TestCase):
    def test_empty_grade_returns_the_input(self):
        img = frame()
        out = grade.Grader({}).frame(img)
        self.assertLessEqual(int(np.abs(out.astype(int) - img.astype(int)).max()), 2)

    def test_subject_is_more_saturated_than_the_scene(self):
        g = style_grade()
        img = frame((60, 160, 70))
        mask = mask_pass().astype(np.float32) / 255.0
        out = grade.Grader(g).frame(img, mask=mask)
        s = sat(out)
        scene, subj = s[:, 4:W // 2 - 8].mean(), s[:, W // 2 + 8:-4].mean()
        self.assertGreater(subj, scene * 1.3, (scene, subj))
        self.assertLess(scene, sat(img)[:, 4:W // 2 - 8].mean(), "the scene is paler than the render")

    def test_mask_edge_is_soft(self):
        g = style_grade()
        g["subject"]["layer"]["rim"] = 0
        gr = grade.Grader(g)
        img = np.zeros((1080, 64, 3), np.uint8)
        img[...] = (60, 160, 70)
        mask = np.zeros((1080, 64), np.float32)
        mask[:, 32:] = 1
        wgt = gr.weight(mask)[500]
        soft = np.count_nonzero((wgt > 0.05) & (wgt < 0.95))
        self.assertGreaterEqual(soft, 4, wgt[24:40])
        self.assertTrue(np.all(np.diff(wgt) >= -1e-6), "weight rises monotonically across the edge")
        s = sat(gr.frame(img, mask=mask))[500]
        lo, hi = s[:20].mean(), s[44:].mean()
        between = np.count_nonzero((s > lo + 0.1 * (hi - lo)) & (s < hi - 0.1 * (hi - lo)))
        self.assertGreaterEqual(between, 3, s[24:40])

    def test_mist_follows_depth(self):
        g = {"scene": {"mist": {"color": "#E6DFD0", "amount": 0.8, "start": 2, "falloff": 20}}}
        img = np.zeros((H, W, 3), np.uint8)
        img[...] = (40, 60, 40)
        d = grade.read_depth_array(depth_pass(), (0.5, 100))
        out = grade.Grader(g).frame(img, depth=d).astype(int)
        near, far = out[2].mean(), out[-3].mean()
        self.assertGreater(far, near + 60, (near, far))

    def test_deterministic_same_bytes(self):
        g = style_grade()
        img = frame()
        a = grade.Grader(g).frame(img, mask=mask_pass() / 255.0)
        b = grade.Grader(g).frame(img, mask=mask_pass() / 255.0)
        self.assertEqual(a.tobytes(), b.tobytes())
        g["seed"] = 8
        c = grade.Grader(g).frame(img, mask=mask_pass() / 255.0)
        self.assertNotEqual(a.tobytes(), c.tobytes(), "the seed changes the paper grain")


class TestCli(TmpDirCase, unittest.TestCase):
    def grade_cli(self, *args):
        return run_main(grade.main, [*map(str, args)])

    def test_render_folder_to_png_sequence_is_byte_identical_twice(self):
        r = make_render(self.tmp / "s03")
        for out in ("a", "b"):
            code, so, err = self.grade_cli(r, self.tmp / out, "--style", STYLE, "--subject", "beast")
            self.assertEqual(code, 0, err)
            self.assertIn("scene + subject; mist on", so)
        names = sorted(p.name for p in (self.tmp / "a").iterdir())
        self.assertEqual(names, ["0001.png", "0002.png", "0003.png"])
        for n in names:
            self.assertEqual((self.tmp / "a" / n).read_bytes(), (self.tmp / "b" / n).read_bytes())

    def test_existing_output_and_unknown_subject_are_refused(self):
        r = make_render(self.tmp / "s03")
        (self.tmp / "out").mkdir()
        (self.tmp / "out" / "x.png").write_bytes(b"x")
        code, _, err = self.grade_cli(r, self.tmp / "out", "--style", STYLE)
        self.assertEqual(code, 2)
        self.assertIn("not overwriting", err)
        code, _, err = self.grade_cli(r, self.tmp / "o2", "--style", STYLE, "--subject", "dragon")
        self.assertEqual(code, 2)
        self.assertIn("masks here: beast", err)
        self.assertFalse((self.tmp / "o2").exists())

    def test_single_image_with_explicit_passes_and_preview(self):
        img, dep, msk = self.tmp / "f.png", self.tmp / "d.png", self.tmp / "m.png"
        Image.fromarray(frame()).save(img)
        Image.fromarray(depth_pass()).save(dep)
        Image.fromarray(mask_pass()).save(msk)
        code, _, err = self.grade_cli(img, self.tmp / "g.png", "--style", STYLE, "--depth", dep, "--mask", msk)
        self.assertEqual(code, 2)
        self.assertIn("--depth-range", err)                           # no render.json: metres unknown
        code, _, err = self.grade_cli(img, self.tmp / "g.png", "--style", STYLE, "--depth", dep,
                                      "--depth-range", 0.5, 100, "--mask", msk)
        self.assertEqual(code, 0, err)
        with Image.open(self.tmp / "g.png") as im:
            self.assertEqual(im.size, (W, H))
        code, so, err = self.grade_cli(img, "--preview", self.tmp / "p.png", "--style", STYLE)
        self.assertEqual(code, 0, err)
        with Image.open(self.tmp / "p.png") as im:
            pw, ph = im.size
        self.assertEqual(ph, H)
        self.assertGreater(pw, 2 * W)

    def test_cube_lut_format(self):
        code, so, err = self.grade_cli("--export-lut", self.tmp / "s.cube", "--style", STYLE, "--lut-size", 9)
        self.assertEqual(code, 0, err)
        lines = (self.tmp / "s.cube").read_text(encoding="ascii").splitlines()
        self.assertIn("LUT_3D_SIZE 9", lines)
        self.assertTrue(any("NOT in" in l for l in lines if l.startswith("#")), "says mist/paper need the script")
        rows = [l for l in lines if re.match(r"^[0-9.]+ [0-9.]+ [0-9.]+$", l)]
        self.assertEqual(len(rows), 9 ** 3)
        vals = np.array([[float(x) for x in r.split()] for r in rows])
        self.assertTrue(((vals >= 0) & (vals <= 1)).all())
        # identity parameters -> identity LUT, red changing fastest
        code, _, err = run_main(grade.main, ["--export-lut", str(self.tmp / "id.cube"), "--params",
                                             str(self._json({"scene": {}})), "--lut-size", "3"])
        self.assertEqual(code, 0, err)
        rows = [l for l in (self.tmp / "id.cube").read_text().splitlines() if re.match(r"^[0-9.]+ ", l)]
        self.assertEqual(rows[:2], ["0.000000 0.000000 0.000000", "0.500000 0.000000 0.000000"])
        self.assertEqual(rows[3], "0.000000 0.500000 0.000000")
        code, _, err = self.grade_cli("--export-lut", self.tmp / "x.cube", "--params", self._json({"scene": {}}),
                                      "--layer", "subject")
        self.assertEqual((code, "no subject" in err), (2, True))

    def _json(self, d):
        p = self.tmp / f"p{len(list(self.tmp.iterdir()))}.json"
        p.write_text(json.dumps(d), encoding="utf-8")
        return p

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg/ffprobe not installed")
    def test_mp4_in_and_out(self):
        r = make_render(self.tmp / "s03", frames=4)
        code, _, err = self.grade_cli(r, self.tmp / "g.mp4", "--style", STYLE, "--subject", "beast")
        self.assertEqual(code, 0, err)
        w, h, fps, audio = grade.probe(self.tmp / "g.mp4")
        self.assertEqual((w, h, round(fps), audio), (W, H, 24, False))
        # video in, PNG folder out, passes matched by order
        code, so, err = self.grade_cli(self.tmp / "g.mp4", self.tmp / "frames", "--style", STYLE,
                                       "--depth", r / "depth", "--mask", r / "mask" / "beast")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(list((self.tmp / "frames").glob("*.png"))), 4)
        self.assertIn("scene + subject; mist on", so)


if __name__ == "__main__":
    unittest.main()
