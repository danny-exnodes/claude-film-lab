"""tools/comfy/hybrid.py: Blender key frames -> Qwen-Edit -> eye check -> H3 -> assemble, with every subprocess faked
(no Blender, no ComfyUI, no GPU): argument lists, dry-run plan, the approval gate, resume / no overwrite, the ledger row
of the Blender step, and the ffmpeg concat on tiny generated clips when ffmpeg is installed."""
import csv, json, os, shutil, subprocess, sys, unittest
from pathlib import Path
from unittest import mock

import helpers

hybrid = helpers.load("comfy/hybrid.py", "film_hybrid_t")
try:
    from PIL import Image
except ImportError:
    Image = None
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def png(path, color=(80, 80, 80)):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if Image is not None:
        Image.new("RGB", (64, 36), color).save(path)
    else:
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(color) * 8)
    return path


def arg(argv, flag):
    return argv[argv.index(flag) + 1] if flag in argv else None


class Fake:
    """Stands in for blender.py / comfy.py / ffmpeg: records argv, writes the outputs they would write."""

    def __init__(self, fail=None, real_ffmpeg=False):
        self.calls, self.fail, self.real_ffmpeg, self.n = [], fail or {}, real_ffmpeg, 0

    def kind(self, argv):
        if argv[1:2] == [hybrid.BLENDER]:
            return "blender " + argv[2]
        if argv[1:2] == [hybrid.COMFY]:
            return argv[3] if len(argv) > 3 else argv[2]          # run <workflow> | free
        return "ffmpeg"

    def __call__(self, argv):
        self.calls.append(list(argv))
        k = self.kind(argv)
        self.n += 1
        if self.n in self.fail:
            return self.fail[self.n]
        if k == "blender keyframes":
            out = Path(arg(argv, "--out"))
            png(out / "first.png", (10, 10, 10))
            png(out / "last.png", (20, 20, 20))
            (out / "keyframes.json").write_text("{}")
        elif k == "blender still":
            png(arg(argv, "--out"), (30, 30, 30))
        elif k == "qwen-edit":
            out = arg(argv, "--out")
            png(out, (self.n, 100, 50))
            Path(out + ".json").write_text(json.dumps({"seed": arg(argv, "--seed")}))
        elif k == "h3-i2v":
            out = arg(argv, "--out")
            if self.real_ffmpeg:
                subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                                "testsrc=size=64x36:rate=24:duration=0.5", "-f", "lavfi", "-i",
                                "sine=frequency=440:duration=0.5", "-shortest", "-c:v", "libx264",
                                "-pix_fmt", "yuv420p", "-c:a", "aac", out], check=True)
            else:
                Path(out).write_bytes(b"fake mp4 " + str(self.n).encode())
            Path(out + ".json").write_text(json.dumps({"workflow": "h3-i2v", "seed": arg(argv, "--seed")}))
        elif k == "ffmpeg":
            if self.real_ffmpeg:
                return subprocess.run(argv).returncode
            Path(argv[-1]).write_bytes(b"concat")
        return 0

    def of(self, kind):
        return [c for c in self.calls if self.kind(c) == kind]


class Case(helpers.TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.spec = self.tmp / "ep01-test-ep" / "shots3d" / "s03.json"
        self.spec.parent.mkdir(parents=True)
        shutil.copy(helpers.REPO / "templates" / "episode" / "shot3d.json", self.spec)     # 5 s at 24 fps
        self.media = self.tmp / "out" / "test-series" / "ep01"
        self.root = self.media / "renders3d" / "s03_keys"
        self.ledger = self.media / "ledger.csv"
        self.motion = self.tmp / "s03.json"
        self.motion.write_text(json.dumps({"integrated_multimodal_description": "the bird turns its head"}))

    def cli(self, *argv, fake=None, ffmpeg="/usr/bin/ffmpeg"):
        fake = fake or Fake()
        with mock.patch.object(hybrid, "run_cmd", fake), mock.patch.object(hybrid, "ffmpeg_path", lambda: ffmpeg):
            code, out, err = helpers.run_main(hybrid.main, [str(x) for x in argv])
        return code, out, err, fake

    def base(self, cmd, *extra):
        return (cmd, self.spec, "--media", self.media, "--ledger", self.ledger, *extra)

    def edit_args(self):
        return ("--edit-prompt", "Repaint as a photorealistic mythic bird; keep the exact pose and framing",
                "--motion-prompt-file", self.motion)

    def state(self):
        return json.loads((self.root / hybrid.STATE).read_text(encoding="utf-8"))

    def rows(self):
        if not self.ledger.exists():
            return []
        with open(self.ledger, encoding="utf-8") as f:
            return list(csv.DictReader(f))


class TestPlan(Case):
    def test_dry_run_prints_every_call_and_runs_nothing(self):
        code, out, err, fake = self.cli(*self.base("run", *self.edit_args(), "--keys", "3", "--dry-run"))
        self.assertEqual(code, 0, err)
        self.assertEqual(fake.calls, [])
        self.assertIn("blender.py keyframes", out)
        self.assertIn("still", out)
        self.assertIn("--frame 60", out)
        self.assertEqual(out.count("run qwen-edit"), 3)
        self.assertIn("stop: eye check", out)
        self.assertIn("dry-run: nothing called", out)
        self.assertFalse(self.root.exists())

    def test_refusals(self):
        code, _, err, fake = self.cli("run", self.spec, "--media", self.tmp / "out" / "x", "--ledger", self.ledger)
        self.assertEqual((code, fake.calls), (2, []))
        self.assertIn("--media", err)
        code, _, err, _ = self.cli(*self.base("edit"))
        self.assertEqual(code, 2)                              # no edit prompt
        code, _, err, _ = self.cli(*self.base("animate", *self.edit_args()))
        self.assertEqual(code, 2)
        self.assertIn("approv", err)
        code, _, err, _ = self.cli(*self.base("keyframes", "--keys", "2", "--mid", "60"))
        self.assertEqual(code, 2)
        code, _, err, _ = self.cli(*self.base("keyframes", "--mid", "120"))
        self.assertEqual(code, 2)


class TestChain(Case):
    def test_run_stops_at_the_eye_check_then_finishes_after_approve(self):
        code, out, err, fake = self.cli(*self.base("run", *self.edit_args(), "--review", "q01t03-s03-hybrid",
                                                   "--expect", "5-6 tail ribbons"))
        self.assertEqual(code, 0, err)
        kf, = fake.of("blender keyframes")
        self.assertEqual(kf[:4], [sys.executable, hybrid.BLENDER, "keyframes", str(self.spec.resolve())])
        self.assertEqual(arg(kf, "--out"), str(self.root / "render"))
        self.assertEqual(arg(kf, "--size"), "1344x768")
        self.assertEqual(arg(kf, "--review"), "q01t03-s03-hybrid")
        edits = fake.of("qwen-edit")
        self.assertEqual(len(edits), 2)
        self.assertEqual([arg(c, "--image") for c in edits],
                         [str(self.root / "render" / "first.png"), str(self.root / "render" / "last.png")])
        for c in edits:
            self.assertEqual((arg(c, "--lightning"), arg(c, "--denoise"), arg(c, "--seed")), ("8", "1", "1717"))
            self.assertEqual(arg(c, "--ledger"), str(self.ledger))
            self.assertEqual(arg(c, "--review"), "q01t03-s03-hybrid")
        self.assertEqual([Path(arg(c, "--out")).name for c in edits], ["k1_e01.png", "k2_e01.png"])
        self.assertEqual([("--keep-models" in c) for c in edits], [True, False])
        self.assertEqual(fake.of("h3-i2v"), [])                    # stopped: nothing animated before the eye check
        self.assertIn("EYE CHECK", out)
        self.assertIn("peacock", out)
        self.assertIn("5-6 tail ribbons", out)
        self.assertIn("WAITING", out)
        self.assertIn(f"approve {self.spec} k1=k1_e01.png,k2=k2_e01.png --media", out)   # bound to these files
        if Image is not None:
            self.assertTrue((self.root / "check_v01.png").is_file())
        self.assertEqual([(r["model"], r["status"], r["count"]) for r in self.rows()], [("blender:keyframes", "ok", "2")])
        # resume: nothing is made again
        code, out, _, fake = self.cli(*self.base("run", *self.edit_args()))
        self.assertEqual((code, fake.calls), (0, []))
        # the owner approves exactly the files of the check sheet; run goes on with H3 and the concat
        code, out, err, _ = self.cli("approve", self.spec, "k1,k2", "--media", self.media)
        self.assertEqual(code, 2)                                   # a key without its file: refused
        self.assertIn("k1=k1_e01.png", err)
        code, out, err, _ = self.cli("approve", self.spec, "k1=k1_e01.png,k2=e01", "--media", self.media)
        self.assertEqual(code, 0, err)
        appr = json.loads((self.root / hybrid.APPROVED).read_text())
        self.assertEqual(sorted(appr["keys"]), ["k1", "k2"])
        code, out, err, fake = self.cli(*self.base("run", *self.edit_args(), "--res", "480p", "--motion-seed", "5"))
        self.assertEqual(code, 0, err)
        h3, = fake.of("h3-i2v")
        self.assertEqual(arg(h3, "--image"), str(self.root / "edit" / "k1_e01.png"))
        self.assertEqual(arg(h3, "--last"), str(self.root / "edit" / "k2_e01.png"))
        self.assertEqual(arg(h3, "--prompt-file"), str(self.motion))
        self.assertEqual(arg(h3, "--seconds"), "4.958")             # frames 1 -> 120 at 24 fps
        self.assertEqual((arg(h3, "--res"), arg(h3, "--seed")), ("480p", "5"))
        self.assertNotIn("--keep-models", h3)
        self.assertEqual(Path(arg(h3, "--out")).name, "k1-k2_v01.mp4")
        ff, = fake.of("ffmpeg")
        self.assertIn("concat", ff)
        self.assertEqual(ff[ff.index("-c") + 1], "copy")
        clip = self.media / "clips" / "ep01_s03_h3_v01.mp4"
        self.assertTrue(clip.is_file())
        side = json.loads(Path(str(clip) + ".json").read_text())
        self.assertEqual(side["workflow"], "h3-i2v")
        self.assertEqual([s["pair"] for s in side["segments"]], ["k1-k2"])
        self.assertEqual(side["segments"][0]["sidecar"]["seed"], "5")
        # everything done: a third run calls nothing
        code, out, _, fake = self.cli(*self.base("run", *self.edit_args(), "--res", "480p", "--motion-seed", "5"))
        self.assertEqual((code, fake.calls), (0, []))
        self.assertIn("assemble: done", out)

    def test_three_keys_rejected_middle_and_redo_invalidates_the_approval(self):
        code, _, err, fake = self.cli(*self.base("run", *self.edit_args(), "--keys", "3"))
        self.assertEqual(code, 0, err)
        st, = fake.of("blender still")
        self.assertEqual((arg(st, "--frame"), Path(arg(st, "--out")).name, arg(st, "--size")),
                         ("60", "f0060.png", "1344x768"))
        self.assertEqual(len(fake.of("qwen-edit")), 3)
        self.assertEqual([("--keep-models" in c) for c in fake.of("qwen-edit")], [True, True, False])
        # the owner rejects k2: H3 bridges k1 -> k3 in one segment
        code, out, err, fake = self.cli(*self.base("animate", *self.edit_args(), "--approved", "k1,k3"))
        self.assertEqual((code, fake.calls), (2, []))               # names without the files the owner saw
        code, out, err, fake = self.cli(*self.base("animate", *self.edit_args(), "--approved", "k1=e01,k3=e01"))
        self.assertEqual(code, 0, err)
        self.assertEqual([(r["model"], r["count"]) for r in self.rows() if r["model"].startswith("blender:")],
                         [("blender:keyframes", "2"), ("blender:still", "1")])     # one row per Blender call
        h3, = fake.of("h3-i2v")
        self.assertEqual(Path(arg(h3, "--last")).name, "k3_e01.png")
        self.assertEqual(arg(h3, "--seconds"), "4.958")
        appr = json.loads((self.root / hybrid.APPROVED).read_text())
        self.assertEqual(appr["rejected"], ["k2"])
        # a redo of an approved key: a new version (never an overwrite) and the approval no longer holds
        code, _, err, fake = self.cli(*self.base("edit", *self.edit_args(), "--redo", "k3", "--edit-seed", "9"))
        self.assertEqual(code, 0, err)
        redo, = fake.of("qwen-edit")
        self.assertEqual((Path(arg(redo, "--out")).name, arg(redo, "--seed")), ("k3_e02.png", "9"))
        self.assertTrue((self.root / "edit" / "k3_e01.png").is_file())
        code, out, _, fake = self.cli(*self.base("edit", *self.edit_args()))    # resume keeps k3_e02
        self.assertEqual((code, fake.calls), (0, []))
        code, _, err, fake = self.cli(*self.base("assemble"))
        self.assertEqual((code, fake.calls), (2, []))
        self.assertIn("changed since it was approved", err)

    def test_mid_frames_and_keys_are_fixed_per_root(self):
        code, _, err, _ = self.cli(*self.base("keyframes", "--mid", "40"))
        self.assertEqual(code, 0, err)
        self.assertEqual([k["frame"] for k in self.state()["keys"]], [1, 40, 120])
        code, _, err, fake = self.cli(*self.base("keyframes", "--keys", "2"))
        self.assertEqual((code, fake.calls), (2, []))
        self.assertIn("new --root", err)

    def test_existing_files_are_never_overwritten(self):
        png(self.root / "edit" / "k1_e01.png", (1, 2, 3))           # a file the state does not know
        before = (self.root / "edit" / "k1_e01.png").read_bytes()
        code, _, err, fake = self.cli(*self.base("run", *self.edit_args()))
        self.assertEqual(code, 0, err)
        self.assertEqual([Path(arg(c, "--out")).name for c in fake.of("qwen-edit")], ["k1_e02.png", "k2_e01.png"])
        self.assertEqual((self.root / "edit" / "k1_e01.png").read_bytes(), before)

    def test_a_failure_stops_the_chain(self):
        code, _, err, fake = self.cli(*self.base("run", *self.edit_args()), fake=Fake(fail={2: 1}))
        self.assertEqual(code, 1)
        # keyframes ok, first edit (--keep-models) failed, no more edits; the VRAM it kept is freed
        self.assertEqual([fake.kind(c) for c in fake.calls], ["blender keyframes", "qwen-edit", "free"])
        self.assertEqual(fake.calls[-1], [sys.executable, hybrid.COMFY, "free"])
        self.assertIn("not retried", err)
        self.assertNotIn("edits", self.state())
        code, _, err, fake = self.cli(*self.base("run", *self.edit_args()))   # resume: only the edits run
        self.assertEqual(code, 0, err)
        self.assertEqual([fake.kind(c) for c in fake.calls], ["qwen-edit", "qwen-edit"])

    def test_spec_change_needs_a_new_root(self):
        self.cli(*self.base("keyframes"))
        data = json.loads(self.spec.read_text())
        data["seed"] = 8
        self.spec.write_text(json.dumps(data))
        code, _, err, fake = self.cli(*self.base("edit", *self.edit_args()))
        self.assertEqual((code, fake.calls), (2, []))
        self.assertIn("changed", err)
        code, _, err, fake = self.cli(*self.base("keyframes", "--root", self.media / "renders3d" / "s03_keys_v02"))
        self.assertEqual(code, 0, err)
        self.assertEqual(len(fake.calls), 1)

    def test_status(self):
        self.cli(*self.base("run", *self.edit_args()))
        code, out, _, _ = self.cli("status", self.spec, "--media", self.media)
        self.assertEqual(code, 0)
        self.assertIn("k1 frame    1", out)
        self.assertIn("eye check pending", out)


class TestReviewFixes(Case):
    """Round-3 review: the eye check cannot be bypassed, assemble uses one animate's segments, run refuses before
    Blender, one ledger row per Blender call, --lightning 0, absolute prompt paths, asset files in the fingerprint."""

    def test_approval_is_bound_to_the_files_the_owner_saw(self):
        # a fresh root: nothing to have seen, refused before Blender renders anything
        code, _, err, fake = self.cli(*self.base("run", *self.edit_args(), "--approved", "k1=e01,k2=e01"))
        self.assertEqual((code, fake.calls), (2, []))
        self.assertIn("no edit yet", err)
        self.assertFalse((self.root / hybrid.APPROVED).exists())
        self.cli(*self.base("run", *self.edit_args()))                     # stops at the eye check (k1_e01, k2_e01)
        # a redo approved in the same call: refused before anything runs
        code, _, err, fake = self.cli(*self.base("run", *self.edit_args(), "--redo", "k2", "--edit-seed", "9",
                                                 "--approved", "k1=e01,k2=e01"))
        self.assertEqual((code, fake.calls), (2, []))
        self.assertIn("has not been checked yet", err)
        code, _, err, fake = self.cli(*self.base("run", *self.edit_args(), "--redo", "k2", "--edit-seed", "9",
                                                 "--approved", "k1=e01,k2=e02"))
        self.assertEqual((code, fake.calls), (2, []))
        # the redo alone: k2_e02 exists, the owner saw k2_e01 -> approving k2_e01 is refused, k2_e02 needs a check
        code, _, err, _ = self.cli(*self.base("edit", *self.edit_args(), "--redo", "k2", "--edit-seed", "9"))
        self.assertEqual(code, 0, err)
        code, _, err, _ = self.cli("approve", self.spec, "k1=e01,k2=e01", "--media", self.media)
        self.assertEqual(code, 2)
        self.assertIn("not the current edit of k2 (k2_e02.png)", err)
        self.assertFalse((self.root / hybrid.APPROVED).exists())
        code, _, err, fake = self.cli(*self.base("run", *self.edit_args(), "--approved", "k1=e01,k2=e02"))
        self.assertEqual(code, 0, err)                                   # the owner checked k2_e02: on to H3
        h3, = fake.of("h3-i2v")
        self.assertEqual(Path(arg(h3, "--last")).name, "k2_e02.png")
        self.assertEqual(fake.of("qwen-edit"), [])

    def test_an_edit_made_in_the_call_is_never_approved(self):
        self.cli(*self.base("run", *self.edit_args()))
        c = hybrid.Ctx(hybrid.parser().parse_args([str(x) for x in self.base("animate", *self.edit_args())]))
        c.fresh.add("k2")
        with self.assertRaises(hybrid.Refused) as e:
            hybrid.approve(c, "k1=e01,k2=e01")
        self.assertIn("made by this call", str(e.exception))

    def test_run_refuses_before_blender(self):
        code, _, err, fake = self.cli("run", self.spec, "--media", self.media, "--motion-prompt-file", self.motion)
        self.assertEqual((code, fake.calls), (2, []))                   # no ledger
        code, _, err, fake = self.cli(*self.base("run", "--motion-prompt-file", self.motion))
        self.assertEqual((code, fake.calls), (2, []))                   # no edit prompt
        self.assertIn("--edit-prompt", err)
        self.assertFalse(self.root.exists())
        self.cli(*self.base("run", *self.edit_args()))
        code, _, err, fake = self.cli(*self.base("run", "--approved", "k1=e01,k2=e01"))
        self.assertEqual((code, fake.calls), (2, []))                   # approved, but no motion prompt
        self.assertIn("--motion-prompt", err)

    def test_a_ledger_row_per_blender_call(self):
        code, _, _, fake = self.cli(*self.base("keyframes", "--keys", "3"), fake=Fake(fail={2: 1}))
        self.assertEqual(code, 1)
        self.assertEqual([(r["model"], r["status"], r["count"]) for r in self.rows()],
                         [("blender:keyframes", "ok", "2"), ("blender:still", "failed", "1")])
        code, _, _, _ = self.cli(*self.base("keyframes"), fake=Fake(fail={1: 2}))     # still refused: no row
        self.assertEqual(code, 2)
        self.assertEqual(len(self.rows()), 2)
        code, _, err, fake = self.cli(*self.base("keyframes"))                         # resume: only the still
        self.assertEqual(code, 0, err)
        self.assertEqual([fake.kind(c) for c in fake.calls], ["blender still"])
        self.assertEqual(self.rows()[-1]["model"], "blender:still")

    def test_lightning_off(self):
        self.cli(*self.base("keyframes"))
        code, out, err, fake = self.cli(*self.base("edit", *self.edit_args(), "--lightning", "0"))
        self.assertEqual(code, 0, err)
        self.assertTrue(fake.of("qwen-edit"))
        for c in fake.of("qwen-edit"):
            self.assertNotIn("--lightning", c)
        self.assertIn("no Lightning", out)
        self.assertEqual(self.state()["edit_params"]["lightning"], 0)

    def test_assemble_takes_the_segments_of_the_last_animate(self):
        self.cli(*self.base("run", *self.edit_args(), "--keys", "3"))
        ok = ("--approved", "k1=e01,k2=e01,k3=e01")
        code, _, err, _ = self.cli(*self.base("animate", *self.edit_args(), *ok, "--res", "480p"))
        self.assertEqual(code, 0, err)
        # 768p again: k1-k2 made, k2-k3 failed -> a 768p + 480p concat must not happen
        code, _, _, _ = self.cli(*self.base("animate", *self.edit_args(), "--res", "768p"), fake=Fake(fail={2: 1}))
        self.assertEqual(code, 1)
        code, _, err, fake = self.cli(*self.base("assemble"))
        self.assertEqual((code, fake.calls), (2, []))
        self.assertIn("no clip for k2-k3", err)
        code, _, err, fake = self.cli(*self.base("animate", *self.edit_args(), "--res", "768p"))
        self.assertEqual(len(fake.of("h3-i2v")), 1)                       # only the missing pair
        code, _, err, fake = self.cli(*self.base("assemble"))
        self.assertEqual(code, 0, err)
        side = json.loads((self.media / "clips" / "ep01_s03_h3_v01.mp4.json").read_text())
        self.assertEqual([Path(s["file"]).name for s in side["segments"]], ["k1-k2_v02.mp4", "k2-k3_v02.mp4"])

    def test_a_concat_of_the_wrong_length_is_not_a_clip(self):
        self.cli(*self.base("run", *self.edit_args()))
        self.cli(*self.base("animate", *self.edit_args(), "--approved", "k1=e01,k2=e01"))
        probe = lambda p: 5.0 if "segments" in str(p) else 2.0
        with mock.patch.object(hybrid, "probe_seconds", probe):
            code, _, err, fake = self.cli(*self.base("assemble"))
        self.assertEqual(code, 1)
        self.assertEqual(len(fake.of("ffmpeg")), 2)                       # copy, then the re-encode
        self.assertIn("2.00 s for 5.00 s of segments", err)
        self.assertFalse((self.media / "clips" / "ep01_s03_h3_v01.mp4").exists())
        self.assertEqual([p.name for p in (self.media / "clips").glob(".*")], [])

    def test_motion_prompt_path_is_stored_absolute(self):
        self.cli(*self.base("run", *self.edit_args()))
        old = Path.cwd()
        try:
            os.chdir(self.tmp)
            code, _, err, _ = self.cli(*self.base("animate", "--motion-prompt-file", "s03.json",
                                                  "--approved", "k1=e01,k2=e01"))
            self.assertEqual(code, 0, err)
            os.chdir(self.media)
            code, out, err, fake = self.cli(*self.base("animate"))           # resume from another folder
            self.assertEqual((code, fake.calls), (0, []), err)
        finally:
            os.chdir(old)
        self.assertEqual(self.state()["motion_prompts"], [["--prompt-file", str(self.motion)]])

    def test_a_changed_asset_file_needs_a_new_root(self):
        glb = self.spec.parent / "bird.glb"
        glb.write_bytes(b"glTF one")
        data = json.loads(self.spec.read_text())
        data["assets"].append({"id": "bird", "src": "bird.glb", "at": [0, 0, 0]})
        self.spec.write_text(json.dumps(data))
        code, _, err, _ = self.cli(*self.base("keyframes"))
        self.assertEqual(code, 0, err)
        self.assertEqual(list(self.state()["asset_files"]), ["bird.glb"])
        code, _, err, fake = self.cli(*self.base("keyframes"))
        self.assertEqual((code, fake.calls), (0, []))
        glb.write_bytes(b"glTF two")
        code, _, err, fake = self.cli(*self.base("edit", *self.edit_args()))
        self.assertEqual((code, fake.calls), (2, []))
        self.assertIn("changed since the key frames", err)
        self.assertIn(".glb", err)


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg/ffprobe not installed")
class TestAssembleWithFfmpeg(Case):
    def test_concat_without_reencode(self):
        code, out, err, _ = self.cli(*self.base("run", *self.edit_args(), "--keys", "3"), ffmpeg=FFMPEG)
        self.assertEqual(code, 0, err)
        self.assertIn("WAITING", out)                               # the owner looks at the check sheet first
        fake = Fake(real_ffmpeg=True)
        code, _, err, _ = self.cli(*self.base("run", *self.edit_args(), "--approved", "k1=e01,k2=e01,k3=e01"),
                                   fake=fake, ffmpeg=FFMPEG)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(fake.of("h3-i2v")), 2)
        clip = self.media / "clips" / "ep01_s03_h3_v01.mp4"
        self.assertTrue(clip.is_file())
        side = json.loads(Path(str(clip) + ".json").read_text())
        self.assertEqual(side["encoder"], "copy")
        dur = float(subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                    str(clip)], capture_output=True, text=True).stdout.strip())
        self.assertAlmostEqual(dur, 1.0, delta=0.15)
        streams = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                                  str(clip)], capture_output=True, text=True).stdout.split()
        self.assertEqual(sorted(streams), ["audio", "video"])
        self.assertEqual([p.name for p in self.root.glob(".concat-*")], [])
        self.assertEqual([p.name for p in (self.media / "clips").glob(".*")], [])


if __name__ == "__main__":
    unittest.main()
