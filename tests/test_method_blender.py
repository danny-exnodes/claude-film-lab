"""method: blender (3D renders on the owner's PC, tools/blender/) and video_engine: comfy (local MiniMax H3 clips,
tools/comfy/): check_episode, the engine: blender style packs, status.py. Free: no Blender, no ComfyUI, no network
(tools/blender/spec.py is replaced by stand-ins; the real one is used only when it is in the checkout)."""
import csv, io, json, os, re, shutil, types, unittest
from pathlib import Path
from unittest import mock

from helpers import EPISODE_FIX, REPO, TmpDirCase, load, run_main

ce = load("check_episode.py", "film_check_episode_blender")
st = load("status.py", "film_status_blender")
ark = st.ark

SHOTS = """shot,from_s,to_s,shot_size,camera,action,layers,code_motion,ai_motion,sound,reuse_of
s01,0,8,wide,crane,Núi hiện ra,E-nui;A-da,mist-bands,,wind,
s02,8,15,medium,push-in,Giọt đi tới,A-giot;E-nui,,,step,
s03,15,24.5,close,orbit,Giọt quay đầu,A-giot;FX-bui;T,,,,
s04,24.5,30,wide,static,Toàn cảnh,E-nui;A-da,mist-bands,,wind,s01
"""
CAMERAS = {"s01": "crane", "s02": "push-in", "s03": "orbit"}
LENGTHS = {"s01": 8, "s02": 7, "s03": 9.5}
NO_REMOTE = {"CLAUDE_CODE_REMOTE": ""}


def shot3d(sid, **over):
    d = {"version": 1, "size": [1920, 1080], "fps": 24, "seconds": LENGTHS[sid], "seed": 7, "look": "ink-wash",
         "engine": "eevee", "assets": [{"id": "giot", "src": "preset:giot", "at": [0, 0, 0]}],
         "camera": {"move": CAMERAS[sid], "from": [0, -12, 1.6], "to": [0, -7, 1.6], "target": "giot", "lens": 35}}
    d.update(over)
    return d


def fake_spec(**fns):
    return types.SimpleNamespace(**fns)


GOOD_SPEC = fake_spec(validate=lambda data: [])


class BlenderEpisode(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.ep = self.tmp / "projects" / "test-series" / "ep01-test-ep"
        shutil.copytree(EPISODE_FIX, self.ep)
        (self.ep / "prompts.csv").unlink()
        (self.ep / "shots.csv").write_text(SHOTS, encoding="utf-8")
        self.budget("images: 0\nvideo_seconds: 0\nledger_required: true\n")
        self.front(method="blender", style="thuy-mac-blender", stage=5)
        (self.ep / "ASSETS.md").write_text("# Model 3D\n| giot | preset:giot |\n", encoding="utf-8")
        (self.ep / "shots3d").mkdir()
        for sid in CAMERAS:
            self.put3d(sid, shot3d(sid))
        self.media = self.tmp / "out" / "test-series" / "ep01"
        (self.media / "renders").mkdir(parents=True)
        (self.media / "ledger.csv").write_text(",".join(ce.LEDGER_HEADER) + "\n")
        for p in (mock.patch.dict(os.environ, NO_REMOTE), mock.patch.object(ce, "blender_spec_module",
                                                                             return_value=GOOD_SPEC)):
            p.start()
            self.addCleanup(p.stop)

    # --- builders ---------------------------------------------------------------------------------------------
    def front(self, method="blender", style="thuy-mac-blender", stage=5, engine=None):
        s = (EPISODE_FIX / "EPISODE.md").read_text(encoding="utf-8")
        s = re.sub(r"(?m)^method:.*\n", "", s)
        extra = f"method: {method}\n" + (f"video_engine: {engine}\n" if engine else "")
        s = s.replace("stage: 5\n", f"{extra}stage: {stage}\n", 1)
        s = re.sub(r"(?m)^style: .*$", f"style: {style}", s)
        if stage >= 8:
            s = s.replace("G3: null", "G3: 2026-11-06")
        (self.ep / "EPISODE.md").write_text(s, encoding="utf-8")

    def budget(self, text):
        (self.ep / "budget.yaml").write_text(text, encoding="utf-8")

    def put3d(self, sid, data, name=None):
        (self.ep / "shots3d" / (name or f"{sid}.json")).write_text(
            json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")

    def render(self, name, kind="render.json"):
        d = self.media / "renders3d" / name
        (d / "beauty").mkdir(parents=True, exist_ok=True)
        if kind == "render.json":
            (d / "render.json").write_text("{}")
        else:
            (d / "beauty" / "0001.png").write_bytes(b"x")

    def shots(self, old, new):
        (self.ep / "shots.csv").write_text(SHOTS.replace(old, new), encoding="utf-8")

    def check(self):
        return run_main(ce.main, ["episode", str(self.ep), "--media", str(self.media)])

    def errors(self, out):
        return [l for l in out.splitlines() if l.startswith("ERROR")]

    def warns(self, out):
        return [l for l in out.splitlines() if l.startswith("WARN")]

    def assert_error(self, text):
        code, out, _ = self.check()
        self.assertEqual(code, 1, out)
        self.assertTrue(any(text in l for l in self.errors(out)), f"no ERROR with {text!r} in:\n{out}")
        return out

    def assert_clean(self):
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        return out


class CheckBlender(BlenderEpisode):
    def test_clean_blender_episode_passes(self):
        out = self.assert_clean()
        self.assertNotIn("prompts.csv", out)
        self.assertIn("INFO  renders3d: 3 shot(s) not rendered yet (required from stage 7): s01, s02, s03", out)
        self.assertEqual(self.warns(out), [l for l in self.warns(out) if "en dash" in l], out)

    def test_video_engine_key_is_known(self):
        self.front(engine="comfy")
        out = self.assert_clean()
        self.assertNotIn("unknown front matter key", out)

    def test_bad_video_engine_and_engine_with_layers_or_code(self):
        self.front(engine="wan")
        self.assert_error("video_engine must be seedance or comfy (got 'wan')")
        for method, style in (("layers", "thuy-mac"), ("code", "hoat-hinh-phang")):
            with self.subTest(method=method):
                self.front(method=method, style=style, engine="comfy")
                self.assert_error(f"video_engine is for method seedance or blender; a method {method} episode")

    def test_caps(self):
        self.budget("images: 4\nvideo_seconds: 0\n")
        self.assert_error("method blender: images = 4 must be 0")
        self.budget("images: 0\nvideo_seconds: 0\nmodels:\n  seedream-5-0-lite-260128: 2\n")
        self.assert_error("method blender: models.seedream-5-0-lite-260128 = 2 must be 0")
        self.budget("images: 0\nvideo_seconds: 10\n")
        self.assert_error("method blender: video_seconds = 10 must be 0 (no video_engine: seedance with ai_motion")

    def test_paid_clips_need_seedance_and_ai_motion(self):
        self.budget("images: 0\nvideo_seconds: 10\n")
        self.shots("A-giot;FX-bui;T,,,", "A-giot;FX-bui;T,,the creature turns its head,")
        self.front(engine="seedance")
        self.assert_clean()
        self.front(engine="comfy")
        self.assert_error("method blender: video_seconds = 10 must be 0 (video_engine comfy makes free local clips)")

    def test_ai_motion_needs_an_explicit_video_engine(self):
        self.shots("A-giot;FX-bui;T,,,", "A-giot;FX-bui;T,,the creature turns its head,")
        out = self.assert_error("method blender: shot s03 has ai_motion but EPISODE.md has no video_engine")
        self.assertIn("local MiniMax H3 clip (tools/comfy/comfy.py) from Blender keyframes", out)
        self.assertNotIn("Wan", out)
        self.front(engine="comfy")
        self.assert_clean()

    def test_layer_codes_and_cameras(self):
        self.shots("E-nui;A-da,mist-bands,,wind,\ns02", "L1;C-giot,mist-bands,,wind,\ns02")
        out = self.assert_error("method blender: layer code 'L1' invalid (A-<asset>, E-<setting>, FX[-<effect>], T)")
        self.assertIn("layer code 'C-giot' invalid", out)
        self.shots("s02,8,15,medium,push-in", "s02,8,15,medium,pan-left")
        self.assert_error("camera 'pan-left' is not one move from crane, dolly, orbit, pan, pull-out, push-in, static, "
                          "tilt, track")

    def test_asset_ids_may_hold_an_underscore_like_spec_py(self):
        self.shots("A-giot;FX-bui;T,,,", "A-old_giot;FX-bui;T,,,")
        self.assert_clean()
        self.render("turntable-old_giot")
        self.render("turntable-old_giot_v02")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertNotIn("turntable-old_giot", out)
        self.shots("A-giot;FX-bui;T,,,", "A-_giot;FX-bui;T,,,")      # spec.py: an id starts with [a-z0-9]
        self.assert_error("layer code 'A-_giot' invalid")
        spec = load("blender/spec.py", "film_blender_spec_ids")
        for aid in ("giot", "old_man", "tree-2", "a_b-c_9"):
            self.assertRegex(aid, spec.ID_RE)
            self.assertRegex("A-" + aid, ce.RE_BLENDER_LAYER)
            self.assertRegex("turntable-" + aid, ce.RE_RENDER3D_DIR)

    def test_style_engine_must_match_method(self):
        self.front(style="thuy-mac")
        self.assert_error("method blender needs an engine: blender style pack; styles/thuy-mac is engine: image")
        self.front(method="layers", style="thuy-mac-blender")
        self.assert_error("styles/thuy-mac-blender is engine: blender (rendered by tools/blender/)")

    def test_prompt_plate_rigs_warn(self):
        self.shots("A-giot;E-nui,,,step,", "A-giot;E-nui,cloth,,step,")
        code, out, _ = self.check()
        self.assertIn("code_motion 'cloth' rigs a painted plate", out)
        self.assertIn("a method blender episode has none", out)

    def test_prompts_csv_is_only_a_warning(self):
        shutil.copy(EPISODE_FIX / "prompts.csv", self.ep / "prompts.csv")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("WARN  prompts.csv: method blender generates no image", out)

    def test_remote_session_warns_but_passes(self):
        self.front(engine="comfy")
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_REMOTE": "true"}):
            out = self.assert_clean()
        self.assertIn("method blender renders with Blender on the owner's PC", out)
        self.assertIn("video_engine comfy makes clips with ComfyUI on the owner's PC", out)


class CheckShots3d(BlenderEpisode):
    def test_missing_shot3d_from_stage_5_is_error_before_is_info(self):
        (self.ep / "shots3d" / "s02.json").unlink()
        self.assert_error("shots3d: no shot3d.json for s02 (required from stage 5")
        self.front(stage=4)
        out = self.assert_clean()
        self.assertIn("INFO  shots3d: 1 shot(s) without shots3d/<shot>.json yet", out)

    def test_names_and_unknown_shots(self):
        self.put3d("s01", shot3d("s01"), name="shot1.json")
        self.put3d("s01", shot3d("s01"), name="s09.json")
        out = self.assert_error("shots3d/shot1.json: name must be s<NN>.json")
        self.assertIn("ERROR shots3d/s09.json: s09 is not a shot of shots.csv", out)

    def test_invalid_json(self):
        self.put3d("s01", "{not json")
        self.assert_error("shots3d/s01.json: not valid JSON")

    def test_camera_and_seconds_against_shots_csv(self):
        self.put3d("s02", shot3d("s02", seconds=5, camera={"move": "orbit"}))
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("WARN  shots3d/s02.json: camera.move 'orbit' differs from shots.csv camera 'push-in' of s02", out)
        self.assertIn("WARN  shots3d/s02.json: seconds 5 differs from the shot length 7 s in shots.csv", out)

    def test_spec_errors_are_reported_per_file(self):
        bad = fake_spec(validate=lambda data: ["camera.move: 'zoom' is not a move"] if data["seed"] == 1 else [])
        self.put3d("s03", shot3d("s03", seed=1))
        with mock.patch.object(ce, "blender_spec_module", return_value=bad):
            out = self.assert_error("shots3d/s03.json: camera.move: 'zoom' is not a move")
        self.assertEqual(len(self.errors(out)), 1, out)

    def test_spec_module_missing_is_one_warn(self):
        with mock.patch.object(ce, "blender_spec_module", return_value=None):
            out = self.assert_clean()
        self.assertEqual(out.count("tools/blender/spec.py not in this checkout: shot3d.json schema not checked"), 1, out)

    def test_spec_module_that_cannot_import_is_one_warn(self):
        with mock.patch.object(ce, "blender_spec_module", side_effect=SyntaxError("bad")):
            out = self.assert_clean()
        self.assertEqual(out.count("tools/blender/spec.py cannot be imported (SyntaxError: bad)"), 1, out)

    def test_shots3d_in_another_method_warns(self):
        self.front(method="seedance", style="test-style")
        self.budget("images: 40\nvideo_seconds: 30\n")
        shutil.copy(EPISODE_FIX / "shots.csv", self.ep / "shots.csv")
        shutil.copy(EPISODE_FIX / "prompts.csv", self.ep / "prompts.csv")
        code, out, _ = self.check()
        self.assertIn("WARN  shots3d: shot3d.json files in a method seedance episode", out)


class Shot3dAdapter(unittest.TestCase):
    """shot3d_errors() reads any of the shapes spec.py may answer with."""

    def test_shapes(self):
        p, data = "/x/shots3d/s01.json", {"version": 1}
        self.assertEqual(ce.shot3d_errors(fake_spec(validate=lambda d: []), p, data), [])
        self.assertEqual(ce.shot3d_errors(fake_spec(validate=lambda d: ("spec", ["a: b"])), p, data), ["a: b"])
        self.assertEqual(ce.shot3d_errors(fake_spec(check=lambda d: None), p, data), [])

        def boom(path):
            raise ValueError(f"{path}: size: must be [w, h]\n{path}: fps: must be > 0")
        self.assertEqual(ce.shot3d_errors(fake_spec(validate_file=boom), p, data),
                         [f"{p}: size: must be [w, h]", f"{p}: fps: must be > 0"])
        seen = []
        ce.shot3d_errors(fake_spec(validate=lambda d, base: seen.append(base) or []), p, data)
        self.assertEqual(seen, ["/x/shots3d"])
        ce.shot3d_errors(fake_spec(validate=lambda d, base_dir=None: seen.append(base_dir) or []), p, data)
        self.assertEqual(seen, ["/x/shots3d", "/x/shots3d"], "spec.validate(data, base_dir=None): the folder is passed")
        self.assertIsNone(ce.shot3d_errors(fake_spec(other=lambda d: []), p, data))

    @unittest.skipUnless((REPO / "tools" / "blender" / "spec.py").is_file(), "tools/blender/spec.py not merged yet")
    def test_template_and_real_spec_module_agree(self):
        mod = ce.blender_spec_module()
        path = str(REPO / "templates" / "episode" / "shot3d.json")
        errs = ce.shot3d_errors(mod, path, json.loads(Path(path).read_text(encoding="utf-8")))
        self.assertIsNotNone(errs, "check_episode knows none of spec.py's functions: update shot3d_errors()")
        self.assertEqual(errs, [])


class CheckAssetsAndMedia(BlenderEpisode):
    def test_assets_md(self):
        (self.ep / "ASSETS.md").unlink()
        self.assert_error("ASSETS.md: missing: source and licence of every 3D model")
        self.front(stage=3)
        code, out, _ = self.check()
        self.assertIn("WARN  ASSETS.md: missing", out)
        (self.ep.parent / "ASSETS.md").write_text("# project models\n", encoding="utf-8")
        self.front(stage=5)
        self.assert_clean()

    def test_renders_required_from_stage_7(self):
        self.front(stage=7)
        self.assert_error("media/renders3d: no final Blender render for s01, s02, s03 at stage 7")
        self.render("s01")
        self.render("s02_v02", kind="frames")
        self.render("s03_preview")
        out = self.assert_error("no final Blender render for s03 at stage 7")
        self.assertIn("pull the shot bundles from Drive and unzip them in the media folder", out)
        self.render("s03")
        self.assert_clean()

    def test_render_folder_names(self):
        self.render("turntable-giot")
        self.render("s02_keys")
        self.render("shot-2")
        (self.media / "renders3d" / "loose.png").write_bytes(b"x")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("WARN  media/renders3d/shot-2: folder name is not", out)
        self.assertIn("WARN  media/renders3d/loose.png: renders3d/ holds one folder per render", out)
        self.assertNotIn("turntable-giot:", out)

    def test_local_clip_and_sidecar_names(self):
        d = self.media / "clips"
        d.mkdir()
        for n in ("ep01_s03_h3_v01.mp4", "ep01_s03_h3_v01.mp4.json", "ep01_s03_h3_v02.json"):
            (d / n).write_bytes(b"x")
        self.assert_clean()
        (d / "ep01_s03_h3.json").write_bytes(b"x")
        self.assert_error("media/clips/ep01_s03_h3.json: name does not match the clips convention")

    def test_ai_motion_clip_required_at_g3(self):
        self.front(stage=8, engine="comfy")
        self.shots("A-giot;FX-bui;T,,,", "A-giot;FX-bui;T,,the creature turns its head,")
        for sid in ("s01", "s02", "s03"):
            self.render(sid)
        self.assert_error("s03 has ai_motion 'the creature turns its head' but no clip")
        (self.media / "clips").mkdir()
        (self.media / "clips" / "ep01_s03_h3_v01.mp4").write_bytes(b"x")
        self.assert_clean()

    def test_media_folder_missing_at_stage_7(self):
        self.front(stage=7)
        shutil.rmtree(self.media)
        self.assert_error("media folder missing at stage 7: the Blender renders (renders3d/) are needed")

    def test_renders3d_in_another_method_warns(self):
        self.front(method="seedance", style="test-style")
        self.budget("images: 40\nvideo_seconds: 30\n")
        shutil.copy(EPISODE_FIX / "shots.csv", self.ep / "shots.csv")
        shutil.copy(EPISODE_FIX / "prompts.csv", self.ep / "prompts.csv")
        shutil.rmtree(self.ep / "shots3d")
        self.render("s01")
        code, out, _ = self.check()
        self.assertIn("WARN  media/renders3d: Blender renders in a method seedance episode", out)


class SeedanceWithComfy(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.ep = self.tmp / "projects" / "test-series" / "ep01-test-ep"
        shutil.copytree(EPISODE_FIX, self.ep)
        s = (self.ep / "EPISODE.md").read_text(encoding="utf-8").replace("method: seedance\n",
                                                                          "method: seedance\nvideo_engine: comfy\n")
        (self.ep / "EPISODE.md").write_text(s, encoding="utf-8")
        p = mock.patch.dict(os.environ, NO_REMOTE)
        p.start()
        self.addCleanup(p.stop)

    def test_comfy_with_seedance_warns_about_unused_video_seconds(self):
        code, out, _ = run_main(ce.main, ["episode", str(self.ep), "--media", str(self.tmp / "none")])
        self.assertEqual(code, 0, out)
        self.assertIn("WARN  budget.yaml: video_engine comfy: clips are local and free, Seedance is not called; "
                      "video_seconds = 30 is not used (set 0)", out)
        (self.ep / "budget.yaml").write_text("images: 40\nvideo_seconds: 0\nledger_required: true\n", encoding="utf-8")
        code, out, _ = run_main(ce.main, ["episode", str(self.ep), "--media", str(self.tmp / "none")])
        self.assertEqual(code, 0, out)
        self.assertNotIn("budget.yaml", out)


class BlenderStyles(unittest.TestCase):
    IDS = ["thuy-mac-blender", "toon-3d-blender", "chan-thuc-blender"]

    def test_packs_pass_clean(self):
        for sid in self.IDS:
            with self.subTest(style=sid):
                code, out, _ = run_main(ce.main, ["style", str(REPO / "styles" / sid)])
                self.assertEqual(code, 0, out)
                self.assertIn("0 error(s), 0 warning(s)", out)

    def test_packs_are_draft_and_blender(self):
        import yaml
        for sid in self.IDS:
            y = yaml.safe_load((REPO / "styles" / sid / "style.yaml").read_text(encoding="utf-8"))
            self.assertEqual((y["status"], y["engine"]), ("draft", "blender"))
            self.assertLessEqual(set(y["render"]), ce.BLENDER_RENDER_KEYS)
            self.assertIn(y["render"]["look"], ce.blender_looks())

    def test_ink_pack_uses_the_thuy_mac_palette(self):
        import yaml
        ink = yaml.safe_load((REPO / "styles" / "thuy-mac-blender" / "style.yaml").read_text(encoding="utf-8"))
        img = yaml.safe_load((REPO / "styles" / "thuy-mac" / "style.yaml").read_text(encoding="utf-8"))
        for k in ("ink", "grey", "paper", "ochre", "accent"):
            self.assertEqual(ink["palette"][k].upper(), img["palette"][k].upper(), k)

    def test_render_errors(self):
        rep = ce.Report()
        ce.check_render_blender({"look": "watercolor", "engine": "octane", "line": -1, "mist": 2,
                                 "palette": {"sky": "blue"}, "hold": 2}, rep)
        text = rep.text("x")
        for want in ("render.look 'watercolor' is not a Blender look", "render.engine 'octane' must be eevee or cycles",
                     "render.line -1", "render.mist 2 must be a number 0-1", "render.palette.sky = 'blue'",
                     "WARN  style.yaml: render: unknown key 'hold'"):
            self.assertIn(want, text)

    def test_image_keys_in_a_blender_pack_warn(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "x-blender"
            shutil.copytree(REPO / "styles" / "toon-3d-blender", d)
            y = (d / "style.yaml").read_text(encoding="utf-8").replace("id: toon-3d-blender", "id: x-blender")
            (d / "style.yaml").write_text(y + "style_block: painted\n", encoding="utf-8")
            code, out, _ = run_main(ce.main, ["style", str(d)])
            self.assertEqual(code, 0, out)
            self.assertIn("unknown key 'style_block' (not used by an engine: blender style)", out)

    def test_looks_registry_shapes(self):
        for reg, want in (({"looks": {"a": {}, "b": {}}}, {"a", "b"}), ({"a": {}}, {"a"}),
                          ([{"id": "a"}, "b"], {"a", "b"}), ({"looks": ["c"]}, {"c"})):
            with mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(reg))):
                self.assertEqual(ce.blender_looks(), want)
        with mock.patch("builtins.open", side_effect=OSError):
            self.assertEqual(ce.blender_looks(), set(ce.BLENDER_LOOKS))


class TemplatesBlender(unittest.TestCase):
    def test_shot3d_template_follows_the_lab_conventions(self):
        d = json.loads((REPO / "templates" / "episode" / "shot3d.json").read_text(encoding="utf-8"))
        self.assertEqual(d["version"], 1)
        self.assertIn(d["camera"]["move"], ce.CAMERAS_BLENDER)
        self.assertIn(d["look"], ce.BLENDER_LOOKS)
        for a in d["assets"]:
            self.assertRegex("A-" + a["id"], ce.RE_BLENDER_LAYER)


# ===================================================================================================== status ====
LEDGER_FIELDS = ark.LEDGER_FIELDS


class StatusBlender(BlenderEpisode):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(st, "run_check", return_value=(0, "Summary: 0 error(s), 0 warning(s)"))
        p.start()
        self.addCleanup(p.stop)
        self.rows([])

    def rows(self, rows):
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=LEDGER_FIELDS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(dict({"ts": "2026-11-25T08:00:00Z", "count": 1}, **r))
        (self.media / "ledger.csv").write_text(buf.getvalue(), encoding="utf-8")

    def status(self, *args):
        return run_main(st.main, [str(self.ep), "--media", str(self.media), *args])

    def data(self, *args):
        code, out, _ = self.status("--json", *args)
        return code, json.loads(out)

    def test_method_stage_and_shots(self):
        self.front(engine="comfy")
        self.render("s01")
        self.render("s02_preview")
        code, out, _ = self.status()
        self.assertIn("STAGE  5 Render Blender", out)
        self.assertIn("METHOD blender · video_engine comfy (local ComfyUI clips, free)", out)
        self.assertIn("s01  E-nui:3d A-da:3d · shot3d yes · render final", out)
        self.assertIn("s02  A-giot:3d E-nui:3d · shot3d yes · render preview", out)
        self.assertIn("s03  A-giot:3d FX-bui:3d T:3d · shot3d yes · render none", out)
        self.assertIn("s04  reuse of s01", out)

    def test_forecast_local_gpu_minutes(self):
        self.front(engine="comfy")
        self.shots("A-giot;FX-bui;T,,,", "A-giot;FX-bui;T,,the creature turns its head,")
        self.render("s01")
        self.render("s02_preview")
        code, d = self.data()
        f = d["forecast"]
        self.assertEqual(f["images"]["to_make"], 0)
        self.assertEqual(f["video_seconds"]["planned"], 0)
        loc = f["local"]
        self.assertEqual(loc["blender_shots"], ["s02", "s03"])
        bl = st.BLENDER_MIN_PER_SHOT
        self.assertAlmostEqual(loc["blender_min"], bl["final"] + bl["final"] + bl["preview"])
        self.assertEqual(loc["h3_clips"], [{"shot": "s03", "seconds": 9.5}])
        self.assertAlmostEqual(loc["h3_min"], 9.5 * st.H3_MIN_PER_S["final"])
        code, out, _ = self.status()
        self.assertRegex(out, r"local GPU \(free; estimate, measure\): Blender 2 shot\(s\) ≈ 11 min · H3 1 clip\(s\) "
                              r"≈ 22 min at 1344x768 \(draft 864x480 ≈ 8 min\)")   # 9.5 s x 2.3 / 0.8 min per s

    def test_paid_seedance_clip_counts_against_video_seconds(self):
        self.front(engine="seedance")
        self.budget("images: 0\nvideo_seconds: 20\n")
        self.shots("A-giot;FX-bui;T,,,", "A-giot;FX-bui;T,,the creature turns its head,")
        code, d = self.data()
        self.assertEqual(d["forecast"]["video_seconds"]["planned"], 10)
        self.assertEqual(d["forecast"]["local"]["h3_clips"], [])

    def test_ai_motion_without_video_engine_is_a_conflict(self):
        self.shots("A-giot;FX-bui;T,,,", "A-giot;FX-bui;T,,the creature turns its head,")
        code, out, _ = self.status()
        self.assertIn("CONFLICT: method blender but s03 has ai_motion and EPISODE.md has no video_engine", out)

    def test_g2(self):
        code, out, _ = self.status("--gate", "G2")
        self.assertEqual(code, 1, out)
        self.assertIn("[MISSING] turntable of the 3D models in renders3d/ (tools/blender/blender.py turntable) (none)", out)
        self.assertIn("[MISSING] one sample shot rendered in renders3d/", out)
        self.render("turntable-giot", kind="frames")
        self.render("s02_preview")
        code, out, _ = self.status("--gate", "G2")
        self.assertIn("[ok] turntable of the 3D models in renders3d/ (tools/blender/blender.py turntable) "
                      "(turntable-giot)", out)
        self.assertIn("[ok] one sample shot rendered in renders3d/ (blender.py render, --preview is enough) (s02)", out)
        self.assertIn("[ok] nothing over the budget", out)
        self.assertIn("[MISSING] creature table ## Sinh vật của tập in EPISODE.md", out)
        md = self.ep / "EPISODE.md"            # creature design gate (#52): giot's concept approved by the owner
        md.write_text(md.read_text(encoding="utf-8") + "\n## Sinh vật của tập\n\n| slug | Tên | Chính | Ảnh sách | "
                      "Concept |\n|---|---|---|---|---|\n| giot | Giọt | có | không | duyệt 2026-11-26 |\n",
                      encoding="utf-8")
        code, out, _ = self.status("--gate", "G2")
        self.assertIn("[MISSING] approved concept for every main creature", out)
        self.assertIn("giot no '## Concept đã duyệt' in characters/giot/CHARACTER.md", out)
        (self.ep.parent / "characters" / "giot").mkdir(parents=True)
        (self.ep.parent / "characters" / "giot" / "CHARACTER.md").write_text(
            "# Giọt\n\n## Concept đã duyệt\n- concept-b.png, 2026-11-26, chủ dự án chọn\n", encoding="utf-8")
        code, out, _ = self.status("--gate", "G2")
        self.assertIn("[ok] approved concept for every main creature", out)
        self.assertIn("giot  Giọt · main · not in the book · concept approved (characters/giot/CHARACTER.md)", out)
        self.assertIn("Gate G2: READY", out)
        self.assertIn("turntables (renders3d/): turntable-giot", out)

    def test_g3_needs_every_final_render(self):
        self.front(stage=8)
        self.render("s01")
        self.render("s02_preview")
        (self.media / "renders" / "ep01_draft_v01.mp4").write_bytes(b"x")
        code, out, _ = self.status("--gate", "G3")
        self.assertIn("[MISSING] every non-reuse shot rendered by Blender (final) (not yet: s02, s03)", out)
        self.assertIn("[ok] every layer of every non-reuse shot approved", out)
        self.render("s02")
        self.render("s03")
        code, out, _ = self.status("--gate", "G3")
        self.assertIn("[ok] every non-reuse shot rendered by Blender (final)", out)
        self.assertIn("Gate G3: READY", out)

    def test_local_ledger_rows_cost_nothing_and_are_listed_apart(self):
        self.budget("images: 0\nvideo_seconds: 0\n")
        clip = str(self.media / "clips" / "ep01_s03_h3_v01.mp4")
        self.rows([
            {"kind": "video", "model": "comfy:h3-i2v", "seconds": 10, "status": "pending", "out": clip,
             "note": "req=aa11;seed=7"},
            {"kind": "video", "model": "comfy:h3-i2v", "seconds": 10, "status": "ok", "out": clip,
             "usage": "gpu_s=210", "note": "req=aa11;seed=7"},
            {"kind": "video", "model": "comfy:h3-r2v", "seconds": 5, "status": "pending",
             "out": str(self.media / "clips" / "ep01_s02_h3_v01.mp4"), "note": "req=bb22;seed=3"},
            {"kind": "image", "model": "blender:render", "status": "ok", "out": str(self.media / "gone.png"),
             "note": "req=cc33"},
        ])
        code, d = self.data()
        caps = {c["name"]: c for c in d["budget"]["caps"]}
        self.assertEqual((caps["images"]["used"], caps["video_seconds"]["used"]), (0, 0))
        self.assertEqual(d["attention"], {"open": [], "cut_failed": [], "missing": []})
        models = {m["model"]: m for m in d["local"]["models"]}
        self.assertEqual(models["comfy:h3-i2v"]["by_status"], {"ok": 1})
        self.assertEqual(models["comfy:h3-i2v"]["video_s"], 10)
        self.assertEqual(models["comfy:h3-i2v"]["gpu_s"], 210)
        self.assertEqual([o["model"] for o in d["local"]["open"]], ["comfy:h3-r2v"])
        self.assertEqual(code, 0, "a local run never blocks: nothing was paid")
        code, out, _ = self.status()
        self.assertIn("images 0/0 (0 left)", out)
        self.assertIn("LOCAL (local engines, free: no cap counts them)", out)
        self.assertIn("comfy:h3-i2v 1 run(s) · 1 ok · 10 s video · GPU 3.5 min", out)
        self.assertIn("open     bb22 comfy:h3-r2v ep01_s02_h3_v01.mp4", out)
        self.assertNotIn("OPEN ", out)
        self.assertNotIn("MISSING ", out)

    def test_paid_rows_still_count_next_to_local_ones(self):
        self.budget("images: 0\nvideo_seconds: 20\n")
        self.rows([
            {"kind": "video", "model": "dreamina-seedance-2-5-260628", "seconds": 5, "status": "ok",
             "out": str(self.media / "clips" / "ep01_s03_seedance25_v01.mp4"), "note": "req=dd44"},
            {"kind": "video", "model": "comfy:h3-i2v", "seconds": 10, "status": "ok", "note": "req=ee55"},
        ])
        (self.media / "clips").mkdir()
        (self.media / "clips" / "ep01_s03_seedance25_v01.mp4").write_bytes(b"x")
        code, d = self.data()
        caps = {c["name"]: c for c in d["budget"]["caps"]}
        self.assertEqual(caps["video_seconds"]["used"], 5)


class StatusSeedanceComfy(unittest.TestCase):
    """forecast_section alone: a seedance episode with video_engine comfy plans H3 clips, no paid second."""

    def test_comfy_plans_no_paid_seconds(self):
        shots = {"present": {"shots.csv": True}, "shots": [
            {"shot": "s01", "reuse_of": None, "layers": [], "clip": False, "from_s": "0", "to_s": "5"},
            {"shot": "s02", "reuse_of": None, "layers": [], "clip": True, "from_s": "5", "to_s": "10"}]}
        caps = [{"name": "images", "left": 10}, {"name": "video_seconds", "left": 0}]
        f = st.forecast_section(shots, "seedance", caps, [], {"name": "comfy", "explicit": True})
        self.assertEqual(f["video_seconds"]["planned"], 0)
        self.assertTrue(f["fits"])
        self.assertEqual(f["local"]["h3_clips"], [{"shot": "s01", "seconds": 5.0}])
        f = st.forecast_section(shots, "seedance", caps, [], {"name": "seedance", "explicit": False})
        self.assertEqual(f["video_seconds"]["planned"], 5)
        self.assertFalse(f["fits"])

    def test_constants_are_marked_estimates(self):
        src = (REPO / "tools" / "status.py").read_text(encoding="utf-8")
        self.assertIn("ESTIMATES", src)
        self.assertIn("measure on the owner's PC", src)


if __name__ == "__main__":
    unittest.main()
