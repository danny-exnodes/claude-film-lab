"""tools/bundle.py: the zip is reproducible (same inputs -> same sha256), so an unchanged re-run is not re-uploaded."""
import datetime, hashlib, json, os, stat, time, unittest, zipfile

from helpers import EPISODE_FIX, TmpDirCase, load, run_main

bundle = load("bundle.py", "film_bundle_repro")

MEDIA = ("plates/ep01_s02_L4_bac-thi_v02.png", "plates/ep01_s02_P1-duoi_bac-thi_v01.png",
         "plates/ep01_s01_L1_nui-co_v01.png", "clips/ep01_s02_seedance25_v01.mp4", "renders/ep01_s02_draft_v01.mp4")


class TestReproducibleBundle(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.media = self.tmp / "out" / "test-series" / "ep01"
        for rel in MEDIA:
            p = self.media / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(rel.encode() * 50)
        film = self.media / "film" / "demo"
        for rel, data in (("film.html", b"<html>" * 100), ("STATE.md", b"# s"), ("review/qc-1.md", b"ok")):
            p = film / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        self.zip = self.media / "bundles" / f"ep01_s02_{day}.zip"

    def run_bundle(self, *extra):
        code, out, err = run_main(bundle.main, [str(self.media), "--shot", "s02", "--series-dir", str(EPISODE_FIX),
                                                *extra])
        self.assertEqual(code, 0, err)
        return hashlib.sha256(self.zip.read_bytes()).hexdigest(), out

    def touch_all(self, when):
        for root, _dirs, names in os.walk(self.media):
            for n in names:
                if not n.endswith(".zip"):
                    os.utime(os.path.join(root, n), (when, when))

    def test_same_inputs_same_sha256(self):
        self.touch_all(time.time() - 86400 * 400)
        first, _ = self.run_bundle("--with-film")
        self.touch_all(time.time() - 3600)
        os.chmod(self.media / MEDIA[0], 0o600)
        second, _ = self.run_bundle("--with-film")
        self.assertEqual(first, second)

    def test_content_change_changes_sha256(self):
        first, _ = self.run_bundle()
        p = self.media / MEDIA[0]
        data = bytearray(p.read_bytes())
        data[0] ^= 1
        p.write_bytes(bytes(data))
        second, _ = self.run_bundle()
        self.assertNotEqual(first, second)

    def test_layout_and_member_metadata(self):
        self.run_bundle("--with-film")
        with zipfile.ZipFile(self.zip) as z:
            self.assertIsNone(z.testzip())
            self.assertEqual(z.namelist(), [
                "clips/ep01_s02_seedance25_v01.mp4", "plates/ep01_s02_L4_bac-thi_v02.png",
                "plates/ep01_s02_P1-duoi_bac-thi_v01.png", "prompts.csv",
                "film/demo/STATE.md", "film/demo/film.html", "film/demo/review/qc-1.md", "anchors.json"])
            for info in z.infolist():
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0), info.filename)
                self.assertEqual(stat.S_IMODE(info.external_attr >> 16), 0o644, info.filename)
                stored = os.path.splitext(info.filename)[1] in (".png", ".mp4")
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED,
                                 info.filename)
            self.assertEqual(z.read(MEDIA[0]), (self.media / MEDIA[0]).read_bytes())
            self.assertEqual(z.read("film/demo/film.html"), b"<html>" * 100)
            self.assertTrue(z.read("prompts.csv").decode().startswith("file,shot,layer"))

    def test_drive_reference_is_the_file_hash(self):
        digest, out = self.run_bundle()
        self.assertIn(f"drive  sha256:{digest}:{self.zip}", out)
        self.assertFalse(os.path.exists(str(self.zip) + ".part"))


if __name__ == "__main__":
    unittest.main()


class TestBlenderRenders(TmpDirCase, unittest.TestCase):
    """method blender: the shot's renders3d/ folders travel in the bundle (beauty.mp4 + render.json + keys; the PNG
    frame folders only on request or when they are the only picture), and unzipping restores them in place."""

    def setUp(self):
        super().setUp()
        self.media = self.tmp / "out" / "test-series" / "ep01"
        self.r3 = self.media / "renders3d"
        for folder in ("s02", "s02_v02", "s02_preview", "s03", "turntable-giot", "turntable-old_man_v02"):
            self.render(folder)
        keys = self.r3 / "s02_keys"
        keys.mkdir(parents=True)
        for n in ("first.png", "last.png", "keyframes.json"):
            (keys / n).write_bytes(n.encode())
        (keys / ".work").mkdir()
        (keys / ".work" / "0001.png").write_bytes(b"left over")
        nomp4 = self.r3 / "s02_v03"                     # render --no-mp4: beauty/ is the only picture
        (nomp4 / "beauty").mkdir(parents=True)
        (nomp4 / "beauty" / "0001.png").write_bytes(b"f1")
        (nomp4 / "depth").mkdir()
        (nomp4 / "depth" / "0001.png").write_bytes(b"d1")
        (nomp4 / "render.json").write_text("{}")
        (self.r3 / "s20").mkdir()                       # another shot whose id starts like s02
        (self.r3 / "s20" / "beauty.mp4").write_bytes(b"s20")
        (self.r3 / "shot-2").mkdir()                    # not a renders3d name: never bundled
        (self.r3 / "shot-2" / "beauty.mp4").write_bytes(b"x")
        day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        self.zip = self.media / "bundles" / f"ep01_s02_{day}.zip"

    def render(self, folder):
        d = self.r3 / folder
        for sub in ("beauty", "depth", "normal", "line", "mask/giot"):
            (d / sub).mkdir(parents=True, exist_ok=True)
            (d / sub / "0001.png").write_bytes(f"{folder}/{sub}".encode() * 100)
        (d / "beauty.mp4").write_bytes(f"mp4 {folder}".encode())
        (d / "render.json").write_text(json.dumps({"folder": folder}))

    def run_bundle(self, *extra):
        code, out, err = run_main(bundle.main, [str(self.media), "--shot", "s02", "--series-dir", str(EPISODE_FIX),
                                                *extra])
        self.assertEqual(code, 0, err)
        with zipfile.ZipFile(self.zip) as z:
            return [n for n in z.namelist() if n.startswith("renders3d/")], out

    def test_a_blender_shot_without_plates_or_clips_bundles(self):
        names, out = self.run_bundle()
        self.assertEqual(names, [
            "renders3d/s02/beauty.mp4", "renders3d/s02/render.json",
            "renders3d/s02_keys/first.png", "renders3d/s02_keys/keyframes.json", "renders3d/s02_keys/last.png",
            "renders3d/s02_preview/beauty.mp4", "renders3d/s02_preview/render.json",
            "renders3d/s02_v02/beauty.mp4", "renders3d/s02_v02/render.json",
            "renders3d/s02_v03/beauty/0001.png", "renders3d/s02_v03/render.json"])
        self.assertIn("Blender renders s02, s02_keys, s02_preview, s02_v02, s02_v03", out)
        with zipfile.ZipFile(self.zip) as z:
            self.assertEqual(z.getinfo("renders3d/s02/beauty.mp4").compress_type, zipfile.ZIP_STORED)

    def test_turntables_and_frames_on_request(self):
        names, _ = self.run_bundle("--with-turntables")
        self.assertIn("renders3d/turntable-giot/beauty.mp4", names)
        self.assertIn("renders3d/turntable-old_man_v02/render.json", names)
        self.assertNotIn("renders3d/turntable-giot/beauty/0001.png", names)
        names, _ = self.run_bundle("--with-frames")
        self.assertFalse([n for n in names if "turntable" in n])
        for sub in ("beauty", "depth", "normal", "line", "mask/giot"):
            self.assertIn(f"renders3d/s02/{sub}/0001.png", names)
        self.assertIn("renders3d/s02_v03/depth/0001.png", names)
        self.assertFalse([n for n in names if "/.work/" in n])

    def test_unzip_in_the_media_folder_restores_the_renders(self):
        self.run_bundle()
        ce = load("check_episode.py", "film_check_episode_bundle")
        fresh = self.tmp / "restored" / "out" / "test-series" / "ep01"
        fresh.mkdir(parents=True)
        with zipfile.ZipFile(self.zip) as z:
            z.extractall(fresh)
        self.assertEqual((fresh / "renders3d" / "s02" / "beauty.mp4").read_bytes(),
                         (self.r3 / "s02" / "beauty.mp4").read_bytes())
        done, _ = ce.renders3d_index(str(fresh))
        self.assertEqual(done, {"s02": {"final": True, "preview": True}})

    def test_no_media_at_all_is_refused(self):
        code, _, err = run_main(bundle.main, [str(self.media), "--shot", "s09", "--series-dir", str(EPISODE_FIX)])
        self.assertNotEqual(code, 0)
        self.assertIn("no Blender render", err)
