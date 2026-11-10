"""tools/layers/matte_seq.py on synthetic frame folders and an ffmpeg lavfi clip. Free: no API, no real rembg model."""
import json, os, re, shutil, subprocess, sys, types, unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from helpers import TmpDirCase, load, run_main

seq = load("layers/matte_seq.py", "film_matte_seq")

W, H = 320, 180
GREEN = (0, 255, 0)
DARK = (30, 28, 34)


def ellipse(cx, cy, rx=30, ry=45, w=W, h=H):
    yy, xx = np.mgrid[0:h, 0:w]
    return ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0


def frame(cx, cy=90, bg=GREEN, sigma=6.0, rng=None, w=W, h=H):
    a = np.empty((h, w, 3), np.float32)
    a[:] = bg
    if sigma:
        a += rng.normal(0, sigma, a.shape)
    a[ellipse(cx, cy, w=w, h=h)] = DARK
    return np.clip(np.round(a), 0, 255).astype(np.uint8)


def write_frames(folder, frames):
    folder.mkdir(parents=True, exist_ok=True)
    for i, a in enumerate(frames, 1):
        Image.fromarray(a, "RGB").save(folder / f"{i:06d}.png")
    return folder


def moving(n=6, **kw):
    rng = np.random.default_rng(7)
    return [frame(100 + 12 * i, rng=rng, **kw) for i in range(n)]


def warns(out):
    return [l for l in out.splitlines() if l.startswith("WARN")]


def keyed(folder):
    return sorted(p.name for p in folder.iterdir() if re.fullmatch(r"\d{6}\.png", p.name))


class SeqCase(TmpDirCase, unittest.TestCase):
    def run_seq(self, *args):
        return run_main(seq.main, [str(a) for a in args])

    def report(self, raw, *args):
        """Key raw into a fresh folder; returns (code, stdout, parsed --json)."""
        self._n = getattr(self, "_n", 0) + 1
        out = self.tmp / f"keyed{self._n}"
        js = self.tmp / f"report{self._n}.json"
        code, text, err = self.run_seq(raw, out, "--json", js, *args)
        self.assertIn(code, (0, 4), err)
        return code, text, json.loads(js.read_text(encoding="utf-8")), out


class TestChromaFolder(SeqCase):
    def setUp(self):
        super().setUp()
        self.raw = write_frames(self.tmp / "raw", moving())
        self.out = self.tmp / "keyed"

    def test_clean_sequence(self):
        code, text, err = self.run_seq(self.raw, self.out)
        self.assertEqual(code, 0, err)
        self.assertEqual(keyed(self.out), [f"{i:06d}.png" for i in range(1, 7)])
        self.assertEqual(warns(text), [])
        for i in range(6):
            im = Image.open(self.out / f"{i + 1:06d}.png")
            self.assertEqual((im.mode, im.size), ("RGBA", (W, H)))
            al = np.asarray(im)[..., 3]
            for corner in (al[:8, :8], al[:8, -8:], al[-8:, :8], al[-8:, -8:]):
                self.assertEqual(int(corner.max()), 0)
            self.assertEqual(int(al[90, 100 + 12 * i]), 255)                 # subject centre is opaque
            self.assertGreater(al[ellipse(100 + 12 * i, 90, 26, 41)].mean(), 254)
        m = re.search(r"key (#[0-9A-F]{6}) \(auto, ([\d.]+) from (#[0-9A-F]{6})\)", text)
        self.assertTrue(m, text)
        got = [int(m[1][i:i + 2], 16) for i in (1, 3, 5)]
        for g, want in zip(got, GREEN):
            self.assertLessEqual(abs(g - want), 3)
        self.assertEqual(m[3], "#00FF00")
        self.assertLessEqual(len(text.strip().splitlines()), 12)

    def test_colour_under_alpha_zero_is_dropped(self):
        # the key's noise under fully transparent pixels is never drawn; keeping it makes the PNGs many times larger
        self.assertEqual(self.run_seq(self.raw, self.out)[0], 0)
        px = np.asarray(Image.open(self.out / "000001.png"))
        self.assertEqual(int(px[px[..., 3] == 0][:, :3].max()), 0)
        self.assertEqual(tuple(px[90, 100]), DARK + (255,))                  # the subject keeps its colour

    def test_plates_row_is_the_last_line(self):
        code, text, _ = self.run_seq(self.raw, self.out)
        self.assertEqual(text.strip().splitlines()[-1],
                         "L4b: { seq: { pattern: '../../clips/keyed/{n}.png', digits: 6, start: 1, count: 6, fps: 24, "
                         "at: <t>, end: 'hold' }, depth: 1.0, cover: false },")

    def test_no_thresholds_leave_a_haze(self):
        _, _, clean, _ = self.report(self.raw)
        code, text, hazy, out = self.report(self.raw, "--low", 0, "--high", 255)
        self.assertEqual(code, 0)
        self.assertGreater(hazy["bg_dirty"], clean["bg_dirty"] + 50)
        self.assertLess(clean["bg_dirty"], 1.0)
        self.assertTrue(any(l.startswith("WARN HAZE") for l in warns(text)), text)
        self.assertFalse(any("HAZE" in w for w in clean["warnings"]))

    def test_strict_exits_4_and_still_writes(self):
        code, text, err = self.run_seq(self.raw, self.out, "--low", 0, "--high", 255, "--strict")
        self.assertEqual(code, 4)
        self.assertEqual(len(keyed(self.out)), 6)
        code, _, _ = self.run_seq(self.raw, self.tmp / "ok", "--strict")
        self.assertEqual(code, 0)

    def test_every_halves_count_and_fps(self):
        code, text, err = self.run_seq(self.raw, self.out, "--every", 2)
        self.assertEqual(code, 0, err)
        self.assertEqual(keyed(self.out), ["000001.png", "000002.png", "000003.png"])
        self.assertIn("count: 3, fps: 12,", text.strip().splitlines()[-1])
        # frame 2 of the output is raw frame 3
        self.assertEqual(int(np.asarray(Image.open(self.out / "000002.png"))[90, 124, 3]), 255)

    def test_max_frames_and_fps(self):
        code, text, err = self.run_seq(self.raw, self.out, "--max-frames", 4, "--fps", 30)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(keyed(self.out)), 4)
        self.assertIn("count: 4, fps: 30,", text.strip().splitlines()[-1])

    def test_json_equals_text(self):
        js = self.tmp / "r.json"
        code, text, err = self.run_seq(self.raw, self.out, "--json", js)
        self.assertEqual(code, 0, err)
        d = json.loads(js.read_text(encoding="utf-8"))
        self.assertEqual((d["frames"], d["fps"], d["size"], d["is_16_9"]), (6, 24, [W, H], True))
        self.assertEqual(d["method"], "chroma")
        self.assertEqual(d["warnings"], [])
        self.assertEqual((d["edge_frames"], d["empty_frames"], d["start_iou"]), (0, 0, None))
        self.assertIn(f"key {d['key']} ", text)
        self.assertIn(f"bg_flat {d['bg_flat']} ", text)
        self.assertIn(f"bg_dirty {d['bg_dirty']} %", text)
        self.assertIn(f"flicker {d['flicker']} ", text)
        self.assertIn(f"area_jitter {d['area_jitter']}", text)
        c = d["coverage"]
        self.assertIn(f"coverage {c['min']}/{c['median']}/{c['max']} %", text)
        self.assertIn("edge frames 0", text)
        self.assertIn("empty frames 0", text)
        self.assertLess(c["min"], c["max"] + 1e-9)
        self.assertAlmostEqual(c["median"], 100.0 * ellipse(100, 90).sum() / (W * H), delta=0.3)
        self.assertEqual(d["plates_row"], text.strip().splitlines()[-1])

    def test_explicit_key(self):
        code, text, err = self.run_seq(self.raw, self.out, "--key", "#00FF00")
        self.assertEqual(code, 0, err)
        self.assertIn("key #00FF00 (given", text)
        self.assertEqual(warns(text), [])

    def test_strip(self):
        strip = self.tmp / "strip.png"
        code, text, err = self.run_seq(self.raw, self.out, "--strip", strip)
        self.assertEqual(code, 0, err)
        im = Image.open(strip).convert("RGB")
        self.assertEqual(im.size, (3 * W, 2 * H))
        self.assertEqual(im.getpixel((2, H + 2)), (0xEF, 0xE6, 0xD3))           # bottom row: paper colour
        self.assertNotEqual(im.getpixel((2, 2)), (0xEF, 0xE6, 0xD3))            # top row: checkerboard
        r, g, b = im.getpixel((100, H + 90))                                    # the subject, first frame
        self.assertLess(max(r, g, b), 60)

    def test_cropped_and_empty(self):
        rng = np.random.default_rng(3)
        frames = [frame(100, rng=rng), frame(20, rng=rng), frame(100, rng=rng)]   # frame 2 touches the left edge
        blank = np.empty((H, W, 3), np.uint8); blank[:] = GREEN
        frames.append(blank)
        raw = write_frames(self.tmp / "raw2", frames)
        code, text, d, _ = self.report(raw)
        self.assertEqual((d["edge_frames"], d["empty_frames"]), (1, 1))
        self.assertTrue(any(l.startswith("WARN CROPPED") for l in warns(text)))
        self.assertTrue(any(l.startswith("WARN EMPTY") for l in warns(text)))

    def test_not_16_9(self):
        rng = np.random.default_rng(3)
        raw = write_frames(self.tmp / "sq", [frame(100, rng=rng, w=200, h=200) for _ in range(3)])
        code, text, d, _ = self.report(raw)
        self.assertFalse(d["is_16_9"])
        self.assertTrue(any(l.startswith("WARN NOT 16:9") for l in warns(text)))


class TestMetrics(SeqCase):
    def soft(self, jitter):
        """A static subject with a soft band around it; with jitter the band's brightness wobbles per frame
        by less than the 'raw pixel is static' limit, which moves the alpha of the band."""
        band = ellipse(160, 90, 36, 51) & ~ellipse(160, 90)
        frames = []
        for i in range(6):
            a = frame(160, sigma=0)
            a[band] = (40, 200 + (jitter * (1 if i % 2 else -1)), 40)
            frames.append(a)
        return frames

    def test_edge_jitter_raises_flicker(self):
        _, _, clean, _ = self.report(write_frames(self.tmp / "a", self.soft(0)))
        _, text, jit, _ = self.report(write_frames(self.tmp / "b", self.soft(3)))
        self.assertEqual(clean["flicker"], 0)
        self.assertGreater(jit["flicker"], clean["flicker"])
        self.assertGreater(jit["flicker"], 0.05)

    def test_strong_flicker_warns(self):
        # every background pixel wobbles around the low threshold: alpha flips between 0 and a haze
        frames = []
        for i in range(6):
            a = frame(160, sigma=0, bg=(0, 255 - (34 if i % 2 else 28), 0))
            frames.append(a)
        _, text, d, _ = self.report(write_frames(self.tmp / "c", frames), "--key", "#00FF00", "--low", 46)
        self.assertGreater(d["flicker"], seq.FLICKER_MAX)
        self.assertTrue(any(l.startswith("WARN FLICKER") for l in warns(text)), text)

    def test_drifting_background_is_not_flat(self):
        rng = np.random.default_rng(5)
        frames = [frame(160, bg=(0 + 14 * i, 255 - 22 * i, 6 * i), rng=rng) for i in range(6)]
        _, text, d, _ = self.report(write_frames(self.tmp / "d", frames))
        self.assertGreater(d["bg_flat"], seq.BG_FLAT_MAX)
        line = [l for l in warns(text) if l.startswith("WARN BACKGROUND NOT FLAT")]
        self.assertTrue(line, text)
        self.assertIn("--method rembg", line[0])
        _, text, d, _ = self.report(write_frames(self.tmp / "e", moving()))
        self.assertLess(d["bg_flat"], seq.BG_FLAT_MAX)
        self.assertTrue(2.0 < d["bg_flat"] < 7.0, d["bg_flat"])                  # sigma 6, clipped at 0 and 255

    def test_start_frame_iou(self):
        raw = write_frames(self.tmp / "raw", moving())
        same = self.tmp / "start_same.png"
        Image.fromarray(frame_big(100), "RGB").save(same)
        moved = self.tmp / "start_moved.png"
        Image.fromarray(frame_big(230), "RGB").save(moved)
        _, text, d, _ = self.report(raw, "--start-frame", same)
        self.assertGreater(d["start_iou"], 0.9)
        self.assertIn(f"start IoU {d['start_iou']}", text)
        self.assertFalse(any("REFRAMED" in l for l in warns(text)))
        _, text, d, _ = self.report(raw, "--start-frame", moved)
        self.assertLess(d["start_iou"], seq.IOU_MIN)
        self.assertTrue(any(l.startswith("WARN REFRAMED") for l in warns(text)), text)


def frame_big(cx):
    """The 320x180 scene at 1920x1080 (what keyframe.py writes for a 720p/1080p clip)."""
    a = np.empty((1080, 1920, 3), np.uint8)
    a[:] = GREEN
    a[ellipse(cx * 6, 540, 180, 270, 1920, 1080)] = DARK
    return a


class TestRefusals(SeqCase):
    def setUp(self):
        super().setUp()
        self.raw = write_frames(self.tmp / "raw", moving(3))

    def test_out_dir_is_the_raw_folder(self):
        code, _, err = self.run_seq(self.raw, self.raw)
        self.assertEqual(code, 2)
        self.assertIn("raw", err)
        code, _, err = self.run_seq(self.raw, self.tmp / "x" / ".." / "raw", "--overwrite")
        self.assertEqual(code, 2)
        self.assertEqual(np.asarray(Image.open(self.raw / "000001.png")).shape, (H, W, 3))   # raw frames untouched

    def test_out_dir_with_frames_needs_overwrite(self):
        out = self.tmp / "keyed"
        self.assertEqual(self.run_seq(self.raw, out)[0], 0)
        before = (out / "000001.png").read_bytes()
        code, _, err = self.run_seq(self.raw, out, "--low", 0, "--high", 255)
        self.assertEqual(code, 2)
        self.assertIn("--overwrite", err)
        self.assertEqual((out / "000001.png").read_bytes(), before)
        code, _, err = self.run_seq(self.raw, out, "--low", 0, "--high", 255, "--overwrite", "--max-frames", 2)
        self.assertEqual(code, 0, err)
        self.assertEqual(keyed(out), ["000001.png", "000002.png"])                # the stale third frame is gone
        self.assertNotEqual((out / "000001.png").read_bytes(), before)

    def test_folder_needs_out_dir(self):
        code, _, err = self.run_seq(self.raw)
        self.assertEqual(code, 2)
        self.assertIn("OUT_DIR", err)

    def test_missing_input_and_bad_values(self):
        self.assertEqual(self.run_seq(self.tmp / "nope", self.tmp / "o")[0], 2)
        self.assertEqual(self.run_seq(self.raw, self.tmp / "o", "--key", "green")[0], 2)
        self.assertEqual(self.run_seq(self.raw, self.tmp / "o", "--low", 200, "--high", 40)[0], 2)
        self.assertEqual(self.run_seq(self.raw, self.tmp / "o", "--every", 0)[0], 2)
        self.assertFalse((self.tmp / "o").exists())

    def test_folder_without_frames(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        Image.new("RGB", (W, H), GREEN).save(empty / "frame1.png")               # not a ^\d{6}\.png$ name
        code, _, err = self.run_seq(empty, self.tmp / "o")
        self.assertEqual(code, 1)
        self.assertIn("no frames", err)

    def test_only_six_digit_names_are_read(self):
        Image.new("RGB", (W, H), (255, 0, 0)).save(self.raw / "preview.png")
        Image.new("RGB", (W, H), (255, 0, 0)).save(self.raw / "0000001.png")
        out = self.tmp / "keyed"
        code, text, err = self.run_seq(self.raw, out)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(keyed(out)), 3)
        self.assertEqual(sorted(p.name for p in out.iterdir()), keyed(out))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg is not installed")
class TestClip(SeqCase):
    def make_clip(self, path, fps=12, frames=6):
        path.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
             f"color=c=0x00FF00:s={W}x{H}:r={fps}[bg];color=c=0x202020:s=60x80:r={fps}[fg];"
             f"[bg][fg]overlay=x=120+4*n:y=50", "-frames:v", str(frames),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return path

    def test_clip_is_decoded_and_keyed(self):
        clip = self.make_clip(self.tmp / "clips" / "shot_seedance25_v01.mp4")
        code, text, err = self.run_seq(clip)
        self.assertEqual(code, 0, err)
        out = self.tmp / "clips" / "shot_seedance25_v01"                          # CONVENTIONS §2 layout
        self.assertEqual(len(keyed(out / "raw")), 6)
        self.assertEqual(keyed(out), keyed(out / "raw"))
        with Image.open(out / "raw" / "000001.png") as im:
            self.assertEqual(im.mode, "RGB")
        al = np.asarray(Image.open(out / "000003.png"))[..., 3]
        self.assertEqual(int(al[5, 5]), 0)
        self.assertEqual(int(al[90, 158]), 255)
        self.assertEqual(warns(text), [])
        self.assertIn("'../../clips/shot_seedance25_v01/{n}.png'", text)
        self.assertIn("count: 6, fps: 12,", text.strip().splitlines()[-1])
        # a second run needs --overwrite, and then decodes again
        self.assertEqual(self.run_seq(clip)[0], 2)
        self.assertEqual(self.run_seq(clip, "--overwrite", "--every", 2)[0], 0)
        self.assertEqual(len(keyed(out)), 3)
        self.assertEqual(len(keyed(out / "raw")), 6)

    def test_explicit_out_dir(self):
        clip = self.make_clip(self.tmp / "c.mp4")
        code, text, err = self.run_seq(clip, self.tmp / "frames")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(keyed(self.tmp / "frames" / "raw")), 6)
        self.assertEqual(len(keyed(self.tmp / "frames")), 6)

    def test_not_a_video(self):
        bad = self.tmp / "broken.mp4"
        bad.write_bytes(b"not a video")
        code, _, err = self.run_seq(bad)
        self.assertEqual(code, 1)
        self.assertIn("ffmpeg", err)


class TestRembg(SeqCase):
    def setUp(self):
        super().setUp()
        self.raw = write_frames(self.tmp / "raw", moving(4))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.calls = {"sessions": [], "remove": []}
        fake = types.ModuleType("rembg")

        def new_session(name="u2net", *a, **k):
            self.calls["sessions"].append(name)
            return ("session", name)

        def remove(im, session=None, **k):
            self.calls["remove"].append(session)
            rgb = np.asarray(im.convert("RGB"), np.int16)
            alpha = ((rgb[..., 1] < 128) * 255).astype(np.uint8)                 # "the model": not green
            out = im.convert("RGBA")
            out.putalpha(Image.fromarray(alpha, "L"))
            return out

        fake.new_session, fake.remove = new_session, remove
        env = mock.patch.dict(os.environ, {"HOME": str(self.home), "U2NET_HOME": str(self.home / "u2")})
        mods = mock.patch.dict(sys.modules, {"rembg": fake})
        env.start(); mods.start()
        self.addCleanup(mods.stop); self.addCleanup(env.stop)

    def cache(self, rel):
        p = self.home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"onnx")

    def test_not_cached_is_refused(self):
        code, _, err = self.run_seq(self.raw, self.tmp / "keyed", "--method", "rembg")
        self.assertEqual(code, 2)
        self.assertIn("u2net.onnx", err)
        self.assertEqual(self.calls, {"sessions": [], "remove": []})
        self.assertFalse((self.tmp / "keyed").exists())

    def test_one_session_called_per_frame(self):
        self.cache(".u2net/u2net.onnx")
        code, text, err = self.run_seq(self.raw, self.tmp / "keyed", "--method", "rembg")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.calls["sessions"], ["u2net"])
        self.assertEqual(self.calls["remove"], [("session", "u2net")] * 4)
        al = np.asarray(Image.open(self.tmp / "keyed" / "000002.png"))[..., 3]
        self.assertEqual((int(al[3, 3]), int(al[90, 112])), (0, 255))
        self.assertIn("rembg u2net", text)
        self.assertEqual(warns(text), [])

    def test_other_model_and_cache_places(self):
        self.cache(".rembg/models/isnet-anime/isnet-anime.onnx")
        code, _, err = self.run_seq(self.raw, self.tmp / "k1", "--method", "rembg", "--rembg-model", "isnet-anime")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.calls["sessions"], ["isnet-anime"])
        self.cache("u2/models/silueta/silueta.onnx")
        code, _, err = self.run_seq(self.raw, self.tmp / "k2", "--method", "rembg", "--rembg-model", "silueta")
        self.assertEqual(code, 0, err)

    def test_start_frame_goes_through_the_same_session(self):
        self.cache(".u2net/u2net.onnx")
        start = self.tmp / "start.png"
        Image.fromarray(frame_big(100), "RGB").save(start)
        js = self.tmp / "r.json"
        code, _, err = self.run_seq(self.raw, self.tmp / "keyed", "--method", "rembg", "--start-frame", start,
                                    "--json", js)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.calls["sessions"]), 1)
        self.assertEqual(len(self.calls["remove"]), 5)
        self.assertGreater(json.loads(js.read_text())["start_iou"], 0.9)


if __name__ == "__main__":
    unittest.main()
