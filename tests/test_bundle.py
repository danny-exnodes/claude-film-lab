"""tools/bundle.py: the zip is reproducible (same inputs -> same sha256), so an unchanged re-run is not re-uploaded."""
import datetime, hashlib, os, stat, time, unittest, zipfile

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
