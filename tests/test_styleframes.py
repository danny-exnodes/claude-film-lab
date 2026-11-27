"""tools/styleframes.py: contact sheet, palette and comparison of the style frames (stage 3b, #71). Pillow only."""
import json, unittest

from helpers import TmpDirCase, load, run_main

sf = load("styleframes.py", "film_styleframes")
try:
    from PIL import Image
except ImportError:            # tools/ci.sh --install brings Pillow (requirements-ci.txt)
    Image = None


@unittest.skipIf(Image is None, "Pillow is not installed")
class StyleFramesTool(TmpDirCase, unittest.TestCase):
    def frame(self, name, color, size=(320, 180), stripe=None):
        im = Image.new("RGB", size, color)
        if stripe:
            for x in range(size[0] // 4):
                for y in range(size[1]):
                    im.putpixel((x, y), stripe)
        p = self.tmp / "frames" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        im.save(p)
        return p

    def run_tool(self, *argv):
        return run_main(sf.main, [str(a) for a in argv])

    def test_sheet_and_palette(self):
        self.frame("ep01_sf01_nui_v01.png", (200, 200, 190), stripe=(20, 20, 30))
        self.frame("ep01_sf02_song_v01.png", (180, 190, 200))
        self.frame("ep01_sf03_huy_v01.png", (60, 40, 30), size=(180, 320))      # portrait: letterboxed in its tile
        out, pal = self.tmp / "review" / "styleframes" / "ep01_contact_v01.png", self.tmp / "review" / "pal.png"
        code, text, err = self.run_tool("sheet", self.tmp / "frames", "--out", out, "--palette-out", pal,
                                        "--colors", "4", "--cols", "2", "--tile", "200")
        self.assertEqual(code, 0, err)
        with Image.open(out) as im:            # 2 columns, 2 rows of 200x112 tiles + labels + gaps
            self.assertEqual(im.size, (8 + 2 * 208, 8 + 2 * (112 + 28 + 8)))
        with Image.open(pal) as im:
            self.assertEqual(im.height, 128)
        self.assertIn("sheet: ", text)
        self.assertRegex(text, r"palette: (#[0-9A-F]{6} \d+% ?){1,4}")
        self.assertIn("ep01_sf03_huy_v01.png: luma ", text)
        code, text, err = self.run_tool("sheet", self.tmp / "frames", "--out", out)
        self.assertEqual(code, 2)
        self.assertIn("exists: never overwritten", err)

    def test_sheet_json_numbers(self):
        self.frame("a.png", (255, 255, 255))
        self.frame("b.png", (0, 0, 0))
        code, text, err = self.run_tool("sheet", self.tmp / "frames" / "a.png", self.tmp / "frames" / "b.png",
                                        "--out", self.tmp / "s.png", "--json", "--colors", "2")
        self.assertEqual(code, 0, err)
        d = json.loads(text)
        self.assertEqual([(f["frame"], f["luma"], f["contrast"], f["saturation"]) for f in d["frames"]],
                         [("a.png", 100.0, 0.0, 0.0), ("b.png", 0.0, 0.0, 0.0)])
        self.assertEqual(sorted(p["hex"] for p in d["palette"]), ["#000000", "#FFFFFF"])
        self.assertAlmostEqual(sum(p["share"] for p in d["palette"]), 1.0, places=2)

    def test_compare(self):
        ref = self.frame("ref.png", (200, 200, 190), stripe=(30, 30, 40))
        same = self.frame("shot-ok.png", (198, 202, 188), stripe=(32, 30, 40))
        dark = self.frame("shot-dark.png", (90, 90, 85), stripe=(10, 10, 12))
        code, text, err = self.run_tool("compare", ref, same)
        self.assertEqual(code, 0, text + err)
        self.assertIn("ok    shot-ok.png", text)
        code, text, err = self.run_tool("compare", ref, same, dark)
        self.assertEqual(code, 1, text)
        self.assertRegex(text, r"DRIFT shot-dark.png: luma -\d")
        self.assertIn("(luma", text)
        code, text, err = self.run_tool("compare", ref, dark, "--tol", "100", "--json")
        self.assertEqual(code, 0, text)
        d = json.loads(text)
        self.assertEqual(d["frames"][0]["drift"], [])
        self.assertLess(d["frames"][0]["diff"]["luma"], -30)
        self.assertGreater(d["frames"][0]["numbers"]["palette"], 10)

    def test_palette_distance(self):
        white = [("#FFFFFF", 1.0, (255, 255, 255))]
        self.assertEqual(sf.palette_distance(white, white), 0.0)
        self.assertEqual(sf.palette_distance(white, [("#000000", 1.0, (0, 0, 0))]), 100.0)

    def test_usage_errors(self):
        code, _, err = self.run_tool("sheet", self.tmp / "nope", "--out", self.tmp / "s.png")
        self.assertEqual(code, 2)
        self.assertIn("no such file or folder", err)
        (self.tmp / "empty").mkdir()
        code, _, err = self.run_tool("sheet", self.tmp / "empty", "--out", self.tmp / "s.png")
        self.assertEqual(code, 2)
        self.assertIn("no frame", err)
        (self.tmp / "bad.png").write_bytes(b"not a png")
        code, _, err = self.run_tool("compare", self.tmp / "bad.png", self.tmp / "bad.png")
        self.assertEqual(code, 2)
        self.assertIn("not an image", err)
        self.frame("x.png", (1, 2, 3))
        code, _, err = self.run_tool("compare", self.tmp / "frames" / "x.png", self.tmp / "frames", "--tol", "0")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
