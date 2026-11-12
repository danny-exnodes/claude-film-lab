"""tools/audio: plucked strings, procedural foley and the score renderer. No network, numeric checks only."""
import importlib.util, json, os, re, sys, time, unittest, wave
from pathlib import Path
from unittest import mock

import numpy as np

import helpers

AUDIO = helpers.TOOLS / "audio"
sys.path.insert(0, str(AUDIO))
import pluck  # noqa: E402
import sfx    # noqa: E402

score = helpers.load("audio/score.py", "film_audio_score")
SR = 48000
CINECODE_MIX = Path("/root/.claude/skills/cinecode/scripts/mix.py")


def f0(x, guess):
    """Fundamental by autocorrelation with parabolic refinement, searched within a fifth of the guess."""
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    ac = np.fft.irfft(np.abs(np.fft.rfft(x * np.hanning(n), 2 * n)) ** 2)[:n]
    a, b = int(SR / (guess * 1.4)), int(SR / (guess / 1.4))
    k = a + int(np.argmax(ac[a:b]))
    y0, y1, y2 = ac[k - 1], ac[k], ac[k + 1]
    return SR / (k + 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2))


def centroid(x):
    s = np.abs(np.fft.rfft(np.asarray(x, dtype=np.float64))) ** 2
    return float((s * np.fft.rfftfreq(len(x), 1 / SR)).sum() / s.sum())


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width == 2:
        v = np.frombuffer(raw, dtype="<i2").astype(np.int64)
    else:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int64)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        v = np.where(v >= 1 << 23, v - (1 << 24), v)
    return v.reshape(-1, ch), rate, width


class TestPitchNames(unittest.TestCase):
    def test_names_and_numbers(self):
        self.assertEqual(pluck.midi("A4"), 69)
        self.assertEqual(pluck.midi("D3"), 50)
        self.assertEqual(pluck.midi("F#4"), 66)
        self.assertEqual(pluck.midi("Bb2"), 46)
        self.assertEqual(pluck.midi(60), 60)
        self.assertEqual(pluck.midi(60.5), 60.5)
        self.assertAlmostEqual(float(pluck.hz(69)), 440.0)
        self.assertEqual(pluck.note_name(50), "D3")

    def test_bad_pitches(self):
        for bad in ("H3", "D", "", "D#", None, True, 200, -1):
            with self.assertRaises(ValueError, msg=repr(bad)):
                pluck.midi(bad)


class TestPluck(unittest.TestCase):
    def test_pitch_within_one_percent(self):
        for preset in ("guqin", "pipa", "koto"):
            for note in ("D2", "D3", "A3", "F#4", "C5"):
                target = float(pluck.hz(pluck.midi(note)))
                x = pluck.pluck(preset, note, 1.0)
                got = f0(x[2400:SR], target)
                self.assertLess(abs(got / target - 1), 0.01, f"{preset} {note}: {got:.2f} Hz, wanted {target:.2f}")

    def test_midi_number_and_name_are_the_same_note(self):
        self.assertEqual(pluck.pluck("guqin", "D3", 0.5).tobytes(), pluck.pluck("guqin", 50, 0.5).tobytes())

    def test_bend_ends_on_the_target_pitch(self):
        x = pluck.pluck("guqin", "D3", 3, bend=[(0.4, 0), (0.9, 2)])
        start, end = float(pluck.hz(pluck.midi("D3"))), float(pluck.hz(pluck.midi("E3")))
        self.assertLess(abs(f0(x[2400:int(0.38 * SR)], start) / start - 1), 0.01)
        self.assertLess(abs(f0(x[int(1.2 * SR):int(2.2 * SR)], end) / end - 1), 0.01)

    def test_glide_reaches_its_target(self):
        x = pluck.pluck("koto", "A3", 2.5, glide=("G3", 0.5))
        end = float(pluck.hz(pluck.midi("G3")))
        self.assertLess(abs(f0(x[int(0.9 * SR):int(1.9 * SR)], end) / end - 1), 0.01)

    def test_harmonic_partials(self):
        base = float(pluck.hz(pluck.midi("D3")))
        for h, ratio in ((True, 2), (2, 2), (3, 3), (4, 4)):
            x = pluck.pluck("guqin", "D3", 1.5, harmonic=h)
            self.assertLess(abs(f0(x[2400:SR], base * ratio) / (base * ratio) - 1), 0.01, f"harmonic {h}")
        self.assertAlmostEqual(pluck.sounding_midi("D3", 2), 62.0)            # octave
        self.assertAlmostEqual(pluck.sounding_midi("D3", 3), 69.02, places=2)   # octave + fifth: A4
        with self.assertRaises(ValueError):
            pluck.pluck("guqin", "D3", 1, harmonic=5)

    def test_lengths_are_exact(self):
        self.assertEqual(len(pluck.pluck("guqin", "D3", 2.0)), 2 * SR + int(0.25 * SR))
        self.assertEqual(len(pluck.pluck("guqin", "D3", 1.0, harmonic=2)), SR + int(0.8 * SR))
        self.assertEqual(len(pluck.pluck("pipa", "E4", 0.333, release=0.1)), round(0.333 * SR) + round(0.1 * SR))
        self.assertEqual(len(pluck.pluck("pipa", "E4")), int(2.8 * SR))       # dur=None: the preset's t60
        self.assertEqual(len(pluck.pluck("guqin", "D3", 1.0, bend=[(0, 0), (0.5, 1)])), pluck.length("guqin", 1.0))
        self.assertEqual(len(pluck.strum("koto", ["D3", "A3", "D4"], 1.0, spread=0.03)),
                         pluck.strum_length("koto", 3, 1.0, 0.03))

    def test_output_is_float32_finite_unclipped_without_dc(self):
        for kw in ({}, {"trem": 14}, {"vib": (5, 0.3, 0.2)}, {"harmonic": 2}):
            x = pluck.pluck("pipa", "E4", 1.0, vel=1.0, **kw)
            self.assertEqual(x.dtype, np.float32)
            self.assertTrue(np.isfinite(x).all())
            self.assertLessEqual(float(np.abs(x).max()), 0.9 + 1e-6)
            self.assertLess(abs(float(x.mean())), 1e-4)
            self.assertEqual(float(x[-1]), 0.0)

    def test_same_seed_same_bytes_other_seed_differs(self):
        kw = dict(dur=1.0, trem=12, vel=0.7)
        a = pluck.pluck("pipa", "E4", seed=5, **kw)
        self.assertEqual(a.tobytes(), pluck.pluck("pipa", "E4", seed=5, **kw).tobytes())
        self.assertNotEqual(a.tobytes(), pluck.pluck("pipa", "E4", seed=6, **kw).tobytes())
        b = pluck.pluck("guqin", "D3", 1.0, bend=[(0.2, 0), (0.6, 2)], seed=5)
        self.assertEqual(b.tobytes(), pluck.pluck("guqin", "D3", 1.0, bend=[(0.2, 0), (0.6, 2)], seed=5).tobytes())

    def test_decay_roughly_matches_the_preset(self):
        for preset in ("guqin", "pipa", "koto"):
            x = pluck.pluck(preset, "A3", None).astype(np.float64)            # 220 Hz: t60 is the preset value
            r1 = np.sqrt((x[int(0.3 * SR):int(0.5 * SR)] ** 2).mean())
            r2 = np.sqrt((x[int(1.3 * SR):int(1.5 * SR)] ** 2).mean())
            t60 = 60 / (20 * np.log10(r1 / r2))
            want = pluck.PRESETS[preset]["t60"]
            self.assertTrue(0.65 * want < t60 < 1.35 * want, f"{preset}: measured {t60:.2f} s, preset {want}")

    def test_pipa_is_brighter_than_guqin(self):
        self.assertGreater(centroid(pluck.pluck("pipa", "D4", 1.5)), 1.3 * centroid(pluck.pluck("guqin", "D4", 1.5)))

    def test_the_two_numpy_kernels_agree(self):
        exc = np.zeros(SR // 2)
        exc[:120] = np.random.default_rng(1).standard_normal(120)
        a = pluck._loop_const(exc, 327.3, 0.999, 0.45, -0.05, 1)
        b = pluck._loop_blocks(exc, np.full(len(exc), 327.3), 0.999, 0.45, -0.05, 1)
        c = pluck._loop_py(exc[:3000], np.full(3000, 327.3), 0.999, 0.45, -0.05, 1)
        self.assertLess(float(np.abs(a - b).max()), 1e-9)
        self.assertLess(float(np.abs(a[:3000] - c).max()), 1e-9)

    def test_a_four_second_guqin_note_is_fast(self):
        t = time.perf_counter()
        pluck.pluck("guqin", "D3", 4, bend=[(0.6, 0), (1.2, 2)], vib=(5, 0.25, 1.4))
        pluck.pluck("guqin", "D3", 4)
        self.assertLess(time.perf_counter() - t, 2.0)

    def test_bad_arguments(self):
        with self.assertRaises(KeyError):
            pluck.pluck("erhu", "D3", 1)
        with self.assertRaises(ValueError):
            pluck.pluck("guqin", "X9", 1)
        with self.assertRaises(ValueError):
            pluck.pluck("guqin", "D3", 0)
        with self.assertRaises(ValueError):
            pluck.pluck("guqin", "D3", trem=12)
        with self.assertRaises(TypeError):
            pluck.pluck("guqin", "D3", 1, buzz=0.5)


class TestEngines(unittest.TestCase):
    NOTE = dict(preset="guqin", pitch="D3", dur=1.0, bend=[(0.2, 0), (0.6, 2)], vib=(5, 0.2, 0.3))

    def setUp(self):
        pluck._KERNEL.clear()

    def tearDown(self):
        pluck._KERNEL.clear()

    def test_default_engine_is_numpy(self):
        with mock.patch.dict(os.environ, {"FILM_AUDIO_ENGINE": ""}):
            self.assertEqual(pluck.engine(), "numpy")

    def test_works_with_numba_absent(self):
        with mock.patch.dict(os.environ, {"FILM_AUDIO_ENGINE": ""}):
            want = pluck.pluck(**self.NOTE)
        pluck._KERNEL.clear()
        with mock.patch.dict(sys.modules, {"numba": None}), mock.patch.dict(os.environ, {"FILM_AUDIO_ENGINE": "numba"}):
            self.assertEqual(pluck.engine(), "numpy")                 # asked for numba, import blocked: numpy does it
            got = pluck.pluck(**self.NOTE)
            flat = pluck.pluck("pipa", "E4", 0.5)
        self.assertEqual(got.tobytes(), want.tobytes())
        self.assertEqual(flat.tobytes(), pluck.pluck("pipa", "E4", 0.5).tobytes())

    def test_modules_import_without_numba(self):
        with mock.patch.dict(sys.modules, {"numba": None}):
            for name in ("sfx", "pluck", "score"):
                spec = importlib.util.spec_from_file_location(f"film_audio_nonumba_{name}", AUDIO / f"{name}.py")
                spec.loader.exec_module(importlib.util.module_from_spec(spec))

    @unittest.skipUnless(importlib.util.find_spec("numba"), "numba is not installed")
    def test_numba_engine_matches_numpy_closely(self):
        with mock.patch.dict(os.environ, {"FILM_AUDIO_ENGINE": ""}):
            want = pluck.pluck(**self.NOTE)
        pluck._KERNEL.clear()
        with mock.patch.dict(os.environ, {"FILM_AUDIO_ENGINE": "numba"}):
            self.assertEqual(pluck.engine(), "numba")
            got = pluck.pluck(**self.NOTE)
        self.assertLess(float(np.abs(got - want).max()), 1e-5)


class TestFoley(unittest.TestCase):
    def test_every_sound_is_clean(self):
        self.assertEqual(set(sfx.SOUNDS), {"wind", "fire", "drone", "brush_air", "whoosh", "hoof", "ink_drop", "gong", "drum",
                                           "drum_roll", "ember", "thump", "footstep", "cloth_flap", "water_ring"})
        for name, spec in sfx.SOUNDS.items():
            dur = min(spec["dur"], 2.0)
            for intensity in (0.0, 0.5, 1.0):
                x = spec["fn"](dur=dur, intensity=intensity, seed=3)
                self.assertEqual(x.dtype, np.float32, name)
                self.assertEqual(x.ndim, 1, name)
                self.assertEqual(len(x), round(dur * SR), name)
                self.assertTrue(np.isfinite(x).all(), name)
                self.assertLess(float(np.abs(x).max()), 1.0, name)
                self.assertGreater(float(np.abs(x).max()), 0.3, name)
                self.assertLess(abs(float(x.mean())), 2e-3, name)

    def test_default_durations(self):
        for name, spec in sfx.SOUNDS.items():
            if spec["dur"] <= 2:
                self.assertEqual(len(spec["fn"]()), round(spec["dur"] * SR), name)

    def test_odd_durations_are_exact(self):
        for name in ("hoof", "brush_air", "whoosh", "wind", "drum_roll"):
            self.assertEqual(len(sfx.SOUNDS[name]["fn"](dur=0.3777)), round(0.3777 * SR), name)

    def test_seeded(self):
        for name, spec in sfx.SOUNDS.items():
            dur = min(spec["dur"], 1.0)
            a = spec["fn"](dur=dur, seed=1)
            self.assertEqual(a.tobytes(), spec["fn"](dur=dur, seed=1).tobytes(), name)
            self.assertNotEqual(a.tobytes(), spec["fn"](dur=dur, seed=2).tobytes(), name)

    def test_intensity_and_pitch_change_the_sound(self):
        self.assertGreater(float(np.abs(sfx.hoof(intensity=1.0)).max()), float(np.abs(sfx.hoof(intensity=0.1)).max()))
        self.assertGreater(centroid(sfx.hoof(pitch=1.6)), centroid(sfx.hoof(pitch=0.7)))
        self.assertGreater(centroid(sfx.footstep(surface="stone")), centroid(sfx.footstep(surface="earth")))
        with self.assertRaises(ValueError):
            sfx.footstep(surface="snow")

    def test_drone_pitch_is_a_note(self):
        x = sfx.drone(dur=2.0, pitch="D2", fade_s=0.2)
        target = float(pluck.hz(pluck.midi("D2")))
        self.assertLess(abs(f0(x[int(0.5 * SR):int(1.5 * SR)], target) / target - 1), 0.01)

    def test_beds_fade_in_and_out(self):
        for fn in (sfx.wind, sfx.fire, sfx.drone):
            x = fn(dur=3.0, fade_s=1.0)
            self.assertLess(float(np.abs(x[:240]).max()), 0.02)
            self.assertLess(float(np.abs(x[-240:]).max()), 0.02)

    def test_bricks(self):
        loud = np.sin(2 * np.pi * 220 * np.arange(SR) / SR) * 2.5
        lim = sfx.limit(loud, 0.9)
        self.assertLessEqual(float(np.abs(lim).max()), 0.9 + 1e-9)
        quiet = loud * 0.1
        self.assertTrue(np.array_equal(sfx.limit(quiet, 0.9), quiet))
        st = np.stack([loud, loud * 0.5], axis=1)
        out = sfx.limit(st, 0.9)
        self.assertLessEqual(float(np.abs(out).max()), 0.9 + 1e-9)
        self.assertTrue(np.allclose(out[1000:-1000, 1] * 2, out[1000:-1000, 0]))        # one linked gain
        self.assertLess(float(np.abs(sfx.compress(loud)).max()), float(np.abs(loud).max()))
        buf = sfx.stereo(1.0)
        span = sfx.add(buf, np.ones(100, dtype=np.float32), 0.5, gain=0.5, pan=-1.0)
        self.assertEqual(span, (SR // 2, SR // 2 + 100))
        self.assertAlmostEqual(float(buf[SR // 2, 0]), 0.5 * 1.41421356, places=5)
        self.assertAlmostEqual(float(buf[SR // 2, 1]), 0.0, places=6)
        self.assertFalse(buf[:SR // 2].any())
        self.assertIsNone(sfx.add(buf, np.ones(10, dtype=np.float32), 5.0))
        centre = sfx.stereo(0.1)
        sfx.add(centre, np.ones(10, dtype=np.float32), 0.0)
        self.assertAlmostEqual(float(centre[0, 0]), 1.0, places=5)
        self.assertEqual(sfx.rng_for(3, "a").random(), sfx.rng_for(3, "a").random())
        self.assertNotEqual(sfx.rng_for(3, "a").random(), sfx.rng_for(3, "b").random())


BASE = {
    "length_s": 6, "seed": 7, "scale": ["D", "F", "G", "A", "C"],
    "music": [{"t": 0.5, "inst": "guqin", "pitch": "D3", "dur": 1.0, "vel": 0.7, "pan": -0.2, "shot": "s01"},
              {"t": 4.2, "inst": "pipa", "pitch": "A3", "dur": 0.5, "trem": 12, "gain": 0.8}],
    "foley": [{"t": 0.0, "sound": "wind", "dur": 2.5, "intensity": 0.3, "gain": 0.3, "fade_s": 0.3},
              {"t": 1.9, "sound": "hoof", "gain": 0.6, "pan": 0.3, "shot": "s02"},
              {"t": 4.5, "sound": "ink_drop", "gain": 0.5}],
    "silence": [{"from": 3.0, "to": 4.0}],
}


class TestRoomAndTimbre(unittest.TestCase):
    """Owner's listening notes on the first demo (2026-11-11): the wind read as noise, the gong had no ring."""

    @staticmethod
    def level(x, at, width=0.1):
        a = int(at * sfx.SR)
        return float(np.sqrt(np.mean(x[a:a + int(width * sfx.SR)].astype(np.float64) ** 2)))

    def test_wind_is_a_low_rush_not_hiss(self):
        x = sfx.wind(dur=10, intensity=0.3, seed=3).astype(np.float64)
        power = np.abs(np.fft.rfft(x)) ** 2
        f = np.fft.rfftfreq(len(x), 1 / sfx.SR)
        self.assertLess(power[f > 1000].sum() / power.sum(), 0.02)          # the first version had 8.6 % up there
        centroid = (f * power).sum() / power.sum()
        self.assertTrue(150 < centroid < 500, centroid)                     # audible on small speakers, not a rumble
        half = sfx.SR // 2
        gusts = [np.sqrt(np.mean(x[i:i + half] ** 2)) for i in range(sfx.SR, len(x) - sfx.SR, half)]
        self.assertGreater(20 * np.log10(max(gusts) / min(gusts)), 4)       # it swells and drops, it is not a constant bed

    def test_gong_rings_on(self):
        g = sfx.gong(dur=6, intensity=0.5, seed=3)
        first = self.level(g, 0.0)
        for at in (3, 4):                                                   # the first version was 26-31 dB down here
            self.assertGreater(20 * np.log10(self.level(g, at) / first), -20, at)
        self.assertEqual(sfx.SOUNDS["gong"]["dur"], 8.0)
        self.assertGreater(sfx.SOUNDS["gong"]["reverb"], 0.2)               # score.py gives it a room by default

    def test_gong_is_metal_not_a_wooden_bar(self):
        """Third listen: 'like knocking on wood'. A gong has a sustaining fundamental, an octave partial and no click."""
        g = sfx.gong(dur=8, intensity=0.5, seed=3).astype(np.float64)
        power = np.abs(np.fft.rfft(g)) ** 2
        f = np.fft.rfftfreq(len(g), 1 / sfx.SR)
        self.assertAlmostEqual(float(f[np.argmax(power)]), 196.0, delta=3)   # the fundamental is the strongest partial
        octave = power[(f > 380) & (f < 405)].sum()
        bar = power[(f > 520) & (f < 560)].sum()                             # 2.76 x f0, where a bar's second mode sits
        self.assertGreater(octave, 20 * bar)
        self.assertGreater(20 * np.log10(self.level(g, 5) / self.level(g, 0.05)), -10)   # still ringing after 5 s
        self.assertLess(self.level(g, 0, 0.005), self.level(g, 0.05, 0.05))  # a soft mallet: no click louder than the tone

    def test_reverb_keeps_length_and_peak_and_fills_the_tail(self):
        x = sfx.drum(dur=2.0, intensity=0.6, seed=1)
        y = sfx.reverb(x, 0.4, 2.4, seed=1)
        self.assertEqual((len(y), y.dtype), (len(x), np.float32))
        self.assertAlmostEqual(float(np.abs(y).max()), float(np.abs(x).max()), places=4)
        self.assertGreater(self.level(y, 1.2), self.level(x, 1.2) * 3)      # the room is still sounding after the hit
        self.assertEqual(float(np.abs(y[-1])), 0.0)                         # and is faded out at the sound's end
        self.assertTrue(np.array_equal(y, sfx.reverb(x, 0.4, 2.4, seed=1)))
        self.assertFalse(np.array_equal(y, sfx.reverb(x, 0.4, 2.4, seed=2)))
        self.assertTrue(np.array_equal(sfx.reverb(x, 0.0), x))


class ScoreCase(helpers.TmpDirCase, unittest.TestCase):
    def write(self, data, name="score.json"):
        p = self.tmp / name
        p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        return str(p)

    def run_score(self, data, *args):
        return helpers.run_main(score.main, [self.write(data), *args])

    def variant(self, **changes):
        d = json.loads(json.dumps(BASE))
        d.update(changes)
        return d


class TestScoreValidation(ScoreCase):
    def refused(self, data, *needles):
        out = self.tmp / "out"
        code, _, err = self.run_score(data, "--out", str(out))
        self.assertEqual(code, 2, err)
        for n in needles:
            self.assertIn(n, err)
        self.assertFalse(out.exists(), "nothing may be written when the score is refused")
        return err

    def test_unknown_instrument(self):
        self.refused(self.variant(music=[{"t": 0, "inst": "erhu", "pitch": "D3"}]), "music[0]", "unknown instrument 'erhu'")

    def test_unknown_sound(self):
        self.refused(self.variant(foley=[{"t": 0, "sound": "laser"}]), "foley[0]", "unknown sound 'laser'")

    def test_bad_pitch(self):
        self.refused(self.variant(music=[{"t": 0, "inst": "guqin", "pitch": "H3", "dur": 1}]), "music[0]", "bad pitch")
        self.refused(self.variant(music=[{"t": 0, "inst": "guqin", "dur": 1}]), "pitch is missing")
        self.refused(self.variant(foley=[{"t": 0, "sound": "drone", "pitch": "Z1"}]), "foley[0]", "bad pitch")
        self.refused(self.variant(foley=[{"t": 0, "sound": "hoof", "pitch": "D3"}]), "multiplier")

    def test_negative_time(self):
        self.refused(self.variant(foley=[{"t": -0.5, "sound": "hoof"}]), "foley[0]", "negative time")

    def test_event_past_length(self):
        self.refused(self.variant(foley=[{"t": 6.0, "sound": "hoof"}]), "foley[0]", "past length_s")
        self.refused(self.variant(music=[{"t": 99, "inst": "gong"}]), "music[0]", "past length_s")

    def test_unknown_keys(self):
        self.refused(self.variant(tempo_bpm=90), "unknown key 'tempo_bpm'")
        self.refused(self.variant(foley=[{"t": 0, "sound": "hoof", "volume": 2}]), "foley[0]", "unknown key 'volume'")
        self.refused(self.variant(music=[{"t": 0, "inst": "guqin", "pitch": "D3", "surface": "stone"}]), "unknown key 'surface'")
        self.refused(self.variant(foley=[{"t": 0, "sound": "hoof", "surface": "stone"}]), "unknown key 'surface'")

    def test_bad_values(self):
        self.refused(self.variant(length_s=0), "length_s")
        self.refused(self.variant(length_s=100000), "length_s")
        self.refused(self.variant(seed=-1), "seed")
        self.refused(self.variant(scale=["Q"]), "scale")
        self.refused(self.variant(silence=[{"from": 4, "to": 3}]), "silence[0]")
        self.refused(self.variant(silence=[{"from": 4, "to": 30}]), "silence[0]")
        self.refused(self.variant(foley=[{"t": 0, "sound": "hoof", "pan": 2}]), "pan")
        self.refused(self.variant(foley=[{"t": 0, "sound": "hoof", "gain": 0}]), "gain")
        self.refused(self.variant(foley=[{"t": 0, "sound": "footstep", "surface": "snow"}]), "surface")
        self.refused(self.variant(foley=[{"t": "0", "sound": "hoof"}]), "t must be a number")
        self.refused(self.variant(foley=[{"sound": "hoof"}]), "t is missing")
        self.refused(self.variant(foley=[{"beat": 2, "sound": "hoof"}]), "tempo")
        self.refused(self.variant(music=[{"t": 0, "inst": "guqin", "pitch": "D3", "dur": 1, "harmonic": 7}]), "harmonic")
        self.refused(self.variant(music=[{"t": 0, "inst": "guqin", "pitch": "D3", "dur": 1, "bend": [[0, 1, 2]]}]), "bend")
        self.refused(self.variant(music=[{"t": 0, "inst": "guqin", "pitch": "D3", "dur": 1, "glide": 3}]), "glide")
        self.refused(self.variant(music=[{"t": 0, "inst": "pipa", "pitch": "D3", "trem": 12}]), "trem needs dur")
        self.refused(self.variant(music=["x"]), "music[0]", "must be an object")
        self.refused(self.variant(music={"t": 0}), "music", "must be a list")

    def test_every_problem_is_listed_at_once(self):
        err = self.refused(self.variant(music=[{"t": -1, "inst": "erhu", "pitch": "D3"}, {"t": 0, "inst": "guqin", "pitch": "H3", "dur": 1}],
                                        foley=[{"t": 0, "sound": "laser"}, {"t": 50, "sound": "hoof", "bogus": 1}]),
                           "unknown instrument", "negative time", "bad pitch", "unknown sound", "past length_s", "unknown key 'bogus'")
        self.assertIn("6 error(s)", err)

    def test_event_inside_a_silence_is_an_error(self):
        err = self.refused(self.variant(foley=[{"t": 3.2, "sound": "hoof"}]), "foley[0]", "inside the silence 3-4 s")
        self.assertIn("allow_in_silence", err)
        self.refused(self.variant(music=[{"t": 2.5, "inst": "guqin", "pitch": "D3", "dur": 1.0}]), "music[0]", "inside the silence")
        self.refused(self.variant(foley=[{"t": 0, "sound": "wind", "dur": 6}]), "inside the silence")   # a bed across the window

    def test_unreadable_score(self):
        code, _, err = helpers.run_main(score.main, [str(self.tmp / "missing.json"), "--dry-run"])
        self.assertEqual(code, 2)
        code, _, err = self.run_score("{not json", "--dry-run")
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)
        code, _, err = self.run_score("[1, 2]", "--dry-run")
        self.assertEqual(code, 2)
        code, _, err = self.run_score(BASE)
        self.assertEqual(code, 2)
        self.assertIn("--out", err)

    def test_pitch_curve_too_high_is_refused_before_rendering(self):
        """The base pitch passes, the bend, vibrato or glide does not: an ERROR at validation, not a traceback."""
        for opt in ({"bend": [[0, 0], [1, 24]]}, {"vib": [5, 2, 0]}, {"glide": ["B7", 0.5], "vib": [5, 0.5, 0]}):
            ev = dict({"t": 0, "inst": "guqin", "pitch": "A#7", "dur": 1.5}, **opt)
            err = self.refused(self.variant(music=[ev, {"t": 0, "inst": "erhu", "pitch": "D3"}]),
                               "music[0]", "too high for the string model", "unknown instrument")
            self.assertNotIn("Traceback", err)
        code, _, err = self.run_score(self.variant(music=[{"t": 0, "inst": "guqin", "pitch": "D3", "dur": 1,
                                                           "bend": [[0, 0], [0.5, 12]], "vib": [5, 0.3]}]), "--dry-run")
        self.assertEqual(code, 0, err)

    def test_out_that_is_a_file_is_refused(self):
        target = self.tmp / "audio"
        target.write_text("keep", encoding="utf-8")
        code, _, err = self.run_score(BASE, "--out", str(target))
        self.assertEqual(code, 2, err)
        self.assertIn("not a folder", err)
        self.assertEqual(target.read_text(encoding="utf-8"), "keep")

    def test_score_with_a_bom_and_crlf_is_read(self):
        p = self.tmp / "bom.json"
        p.write_bytes(b"\xef\xbb\xbf" + json.dumps(BASE, indent=1).replace("\n", "\r\n").encode("utf-8"))
        code, out, err = helpers.run_main(score.main, [str(p), "--dry-run"])
        self.assertEqual(code, 0, err)

    def test_very_short_sounds_render(self):
        """A few samples of any sound or note must render (ink_drop under 18 ms used to crash after validation)."""
        for n in (1, 3, 480):
            for name, spec in sfx.SOUNDS.items():
                x = spec["fn"](dur=n / sfx.SR, seed=1)
                self.assertEqual(len(x), n, name)
                self.assertTrue(np.all(np.isfinite(x)), name)
            for kw in ({}, {"bend": [(0, 0), (1, 2)]}, {"harmonic": 2}):
                x = pluck.pluck("guqin", "D3", n / sfx.SR, release=0, **kw)
                self.assertEqual(len(x), n)
                self.assertTrue(np.all(np.isfinite(x)))
        out = self.tmp / "short"
        code, _, err = self.run_score({"length_s": 1, "foley": [{"t": 0, "sound": "ink_drop", "dur": 0.01}],
                                       "music": [{"t": 0, "inst": "guqin", "pitch": "D3", "dur": 0.00002, "release": 0.00002,
                                                  "bend": [[0, 0], [1, 2]]}]}, "--out", str(out))
        self.assertEqual(code, 0, err)
        self.refused({"length_s": 1, "music": [{"t": 0, "inst": "koto", "pitches": ["D3", "A3"], "dur": 0.000001, "release": 0}]},
                     "music[0]", "would be empty")

    def test_scale_and_tail_are_warnings(self):
        d = self.variant(music=[{"t": 0, "inst": "guqin", "pitch": "E3", "dur": 1}, {"t": 5.5, "inst": "guqin", "pitch": "D3", "dur": 2},
                                {"t": 1.2, "inst": "guqin", "pitch": "D3", "dur": 1, "harmonic": 3}])
        code, out, err = self.run_score(d, "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("WARN music[0]: E3 is outside the scale", err)
        self.assertIn("WARN music[1]", err)
        self.assertIn("past length_s", err)
        self.assertNotIn("music[2]", err)                 # D3 harmonic 3 sounds A4: inside D F G A C
        self.assertIn("2 warning(s)", out)


class TestScoreReverb(ScoreCase):
    refused = TestScoreValidation.refused

    def test_reverb_keys_are_checked(self):
        self.refused(self.variant(music=[{"t": 1, "inst": "guqin", "pitch": "D3", "dur": 2, "reverb": 1.5}]), "music[0]", "reverb")
        self.refused(self.variant(music=[{"t": 1, "inst": "gong", "room_s": 0.1}]), "music[0]", "room_s")

    def test_a_dry_gong_differs_from_the_default_one_and_plucks_are_dry_by_default(self):
        np_, pluck_, sfx_ = score._libs()
        def one(ev, kind="music"):
            _, cues, _ = score.validate({"length_s": 10, "seed": 1, kind: [ev]})
            return score._synth(cues[0], pluck_, sfx_), score._synth_dry(cues[0], pluck_, sfx_)
        wet, dry = one({"t": 0, "inst": "gong", "dur": 3})
        self.assertFalse(np.array_equal(wet, dry))
        wet, dry = one({"t": 0, "inst": "gong", "dur": 3, "reverb": 0})
        self.assertTrue(np.array_equal(wet, dry))
        wet, dry = one({"t": 0, "inst": "guqin", "pitch": "D3", "dur": 2})
        self.assertTrue(np.array_equal(wet, dry))
        wet, dry = one({"t": 0, "inst": "guqin", "pitch": "D3", "dur": 2, "reverb": 0.2})
        self.assertFalse(np.array_equal(wet, dry))
        self.assertEqual(len(wet), len(dry))


class TestScoreRender(ScoreCase):
    def test_dry_run_writes_nothing_and_lists_cues_by_time(self):
        out = self.tmp / "out"
        code, text, err = self.run_score(BASE, "--out", str(out), "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertFalse(out.exists())
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["score.json"])
        rows = [l for l in text.splitlines() if re.match(r"\s+\d+\.\d{3}\s", l)]
        self.assertEqual(len(rows), 5)
        times = [float(r.split()[0]) for r in rows]
        self.assertEqual(times, sorted(times))
        self.assertTrue(any("hoof" in r and r.rstrip().endswith("s02") for r in rows))
        self.assertTrue(any("guqin" in r and "D3" in r and r.rstrip().endswith("s01") for r in rows))
        self.assertIn("nothing written", text)

    def test_template_passes_dry_run(self):
        code, text, err = helpers.run_main(score.main, [str(helpers.REPO / "templates" / "episode" / "score.json"), "--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")

    def render(self, data=BASE, *args, name="out"):
        out = self.tmp / name
        code, text, err = self.run_score(data, "--out", str(out), *args)
        self.assertEqual(code, 0, err)
        return out, text, err

    def test_stems_log_and_snippet(self):
        out, text, _ = self.render()
        self.assertEqual(sorted(p.name for p in out.iterdir()),
                         ["ambience.wav", "foley.wav", "mix-snippet.json", "music.wav", "preview.wav", "score-log.json"])
        data = {}
        for name in ("music", "foley", "ambience", "preview"):
            v, rate, width = read_wav(out / f"{name}.wav")
            self.assertEqual((rate, width, v.shape), (SR, 3, (6 * SR, 2)), name)
            self.assertLess(int(np.abs(v).max()), (1 << 23) - 1, f"{name} clips")
            self.assertLess(abs(float(v.mean())) / (1 << 23), 1e-3, f"{name} has a DC offset")
            data[name] = v
        for name in ("music", "foley", "ambience"):
            self.assertTrue(data[name].any(), name)
        # the silence window is exact digital silence in every file
        for name, v in data.items():
            self.assertFalse(v[3 * SR:4 * SR].any(), name)
            self.assertTrue(v[:3 * SR].any())
        # the stems sum to the preview (the limiter does nothing below its ceiling); 2 LSB for rounding
        total = data["music"] + data["foley"] + data["ambience"]
        self.assertLess(int(np.abs(total).max()), int(0.9 * (1 << 23)))
        self.assertLessEqual(int(np.abs(total - data["preview"]).max()), 2)
        # events sit where the score says: the hoof starts at 1.9 s on the foley stem, panned right
        f = data["foley"]
        self.assertFalse(f[:int(1.9 * SR)].any())
        self.assertTrue(f[int(1.9 * SR):int(1.9 * SR) + 480].any())
        self.assertGreater(int(np.abs(f[int(1.9 * SR):int(2.4 * SR), 1]).max()), int(np.abs(f[int(1.9 * SR):int(2.4 * SR), 0]).max()))
        # the first note is D3 on the music stem
        d3 = float(pluck.hz(pluck.midi("D3")))
        self.assertLess(abs(f0(data["music"][int(0.6 * SR):int(1.4 * SR), 0], d3) / d3 - 1), 0.01)

        log = json.loads((out / "score-log.json").read_text(encoding="utf-8"))
        self.assertEqual(log["licence"], "synthesised by tools/audio, no samples")
        self.assertEqual(log["version"], score.TOOL_VERSION)
        self.assertEqual((log["seed"], log["sample_rate"], log["bits"], log["length_s"]), (7, SR, 24, 6.0))
        self.assertEqual({k: v["events"] for k, v in log["stems"].items()}, {"music": 2, "foley": 2, "ambience": 1})
        for name, st in log["stems"].items():
            self.assertEqual(st["duration_s"], 6.0)
            self.assertLess(st["peak_dbfs"], 0)
            self.assertLess(st["rms_dbfs"], st["peak_dbfs"])
            want = 20 * np.log10(np.abs(data[name]).max() / (1 << 23))
            self.assertAlmostEqual(st["peak_dbfs"], want, delta=0.02)
        self.assertEqual(log["silence"], [{"from": 3.0, "to": 4.0, "exact_zero": True, "allowed_events": 0}])
        self.assertEqual(len(log["cues"]), 5)
        self.assertEqual(log["cues"][0]["name"], "wind")
        self.assertIn("not the master", log["preview"]["note"])

        snip = json.loads((out / "mix-snippet.json").read_text(encoding="utf-8"))
        self.assertEqual([(l["bus"], l["at"], l["gain_db"]) for l in snip["layers"]],
                         [("music", 0.0, 0), ("foley", 0.0, 0), ("ambience", 0.0, 0)])
        for layer in snip["layers"]:
            self.assertTrue(os.path.isfile(layer["file"]), layer["file"])
            self.assertEqual(set(layer), {"file", "at", "gain_db", "bus"})
        self.assertIn('"bus": "foley"', text)

    @unittest.skipUnless(CINECODE_MIX.is_file(), "cinecode is not installed")
    def test_snippet_uses_buses_and_fields_cinecode_mix_knows(self):
        src = CINECODE_MIX.read_text(encoding="utf-8")
        buses = set(re.findall(r'"(\w+)":\s*-?\d+', re.search(r"BUS_DB\s*=\s*\{([^}]*)\}", src).group(1)))
        self.assertTrue(set(score.BUS.values()) <= buses, buses)
        for field in ("file", "at", "gain_db", "bus"):
            self.assertTrue(re.search(rf"""L(\.get\(|\[)["']{field}["']""", src), f"mix.py no longer reads {field!r}")
        # and mix.py itself lists the pasted layers (--list stops before ffmpeg and writes nothing)
        out, _, _ = self.render()
        snip = json.loads((out / "mix-snippet.json").read_text(encoding="utf-8"))
        plan = self.tmp / "mix.json"
        plan.write_text(json.dumps({"duration": 6.0, "out": str(self.tmp / "mix-v1.wav"), "layers": snip["layers"]}))
        import subprocess
        r = subprocess.run([sys.executable, str(CINECODE_MIX), str(plan), "--list"], capture_output=True, text=True, cwd=str(self.tmp))
        self.assertEqual(r.returncode, 0, r.stderr)
        for bus in ("music", "foley", "ambience"):
            self.assertRegex(r.stdout, rf"0\.00\s+0\.0\s+{bus}\s+\S+{bus}\.wav")
        self.assertFalse((self.tmp / "mix-v1.wav").exists())

    def test_same_seed_is_byte_identical_and_another_seed_is_not(self):
        a, _, _ = self.render(name="a")
        b, _, _ = self.render(name="b")
        c, _, _ = self.render(BASE, "--seed", "8", name="c")
        for name in ("music.wav", "foley.wav", "ambience.wav", "preview.wav", "score-log.json"):
            self.assertEqual((a / name).read_bytes(), (b / name).read_bytes(), name)
        for name in ("music.wav", "foley.wav", "ambience.wav"):
            self.assertNotEqual((a / name).read_bytes(), (c / name).read_bytes(), name)
        self.assertEqual(json.loads((c / "score-log.json").read_text())["seed"], 8)

    def test_existing_outputs_are_refused(self):
        out, _, _ = self.render()
        before = {p.name: p.read_bytes() for p in out.iterdir()}
        code, _, err = self.run_score(BASE, "--out", str(out))
        self.assertEqual(code, 2)
        self.assertIn("already exist", err)
        self.assertIn("music.wav", err)
        self.assertEqual(before, {p.name: p.read_bytes() for p in out.iterdir()})
        only = self.tmp / "only-log"
        only.mkdir()
        (only / "score-log.json").write_text("{}")
        code, _, err = self.run_score(BASE, "--out", str(only))
        self.assertEqual(code, 2)
        self.assertEqual([p.name for p in only.iterdir()], ["score-log.json"])
        code, _, err = self.run_score(BASE, "--out", str(out), "--overwrite")
        self.assertEqual(code, 0, err)
        self.assertEqual(before["music.wav"], (out / "music.wav").read_bytes())

    def test_allowed_event_may_sound_in_the_silence(self):
        d = self.variant(music=[{"t": 3.2, "inst": "gong", "dur": 0.6, "allow_in_silence": True}], foley=[])
        out, text, _ = self.render(d)
        v, _, _ = read_wav(out / "music.wav")
        self.assertTrue(v[int(3.2 * SR):int(3.8 * SR)].any())
        self.assertFalse(v[3 * SR:int(3.2 * SR)].any())
        self.assertFalse(v[int(3.8 * SR):4 * SR].any())
        log = json.loads((out / "score-log.json").read_text())
        self.assertEqual(log["silence"][0]["exact_zero"], False)
        self.assertEqual(log["silence"][0]["allowed_events"], 1)
        self.assertEqual(log["stems"]["foley"]["peak_dbfs"], None)
        snip = json.loads((out / "mix-snippet.json").read_text())
        self.assertEqual([l["bus"] for l in snip["layers"]], ["music"])       # silent stems are not offered to the mix

    def test_substems_sixteen_bit_beat_and_strum(self):
        d = {"length_s": 4, "tempo": 120, "seed": 1,
             "music": [{"beat": 2, "inst": "koto", "pitches": ["D3", "A3", "D4"], "dur": 1.0, "spread": 0.03},
                       {"t": 0.2, "inst": "drum", "vel": 0.8}],
             "foley": [{"t": 3.5, "sound": "gong", "dur": 2.0, "seed": 4}, {"t": 0.1, "sound": "drone", "dur": 1.0, "fade_s": 0.2}]}
        out, text, err = self.render(d, "--stems", "--bits", "16")
        self.assertEqual(sorted(p.name for p in (out / "stems").iterdir()),
                         ["foley-drone.wav", "foley-gong.wav", "music-drum.wav", "music-koto.wav"])
        self.assertIn("WARN foley[0]", err)                                   # the gong rings past the end: faded
        music, rate, width = read_wav(out / "music.wav")
        self.assertEqual((rate, width, len(music)), (SR, 2, 4 * SR))
        koto, _, _ = read_wav(out / "stems" / "music-koto.wav")
        self.assertFalse(koto[:SR].any())                                     # beat 2 at 120 bpm = 1.0 s
        self.assertTrue(koto[SR:SR + 480].any())
        drum, _, _ = read_wav(out / "stems" / "music-drum.wav")
        self.assertLessEqual(int(np.abs(koto + drum - music).max()), 2)
        gong, _, _ = read_wav(out / "foley.wav")
        self.assertEqual(int(np.abs(gong[-1]).max()), 0)
        amb, _, _ = read_wav(out / "ambience.wav")
        self.assertTrue(amb.any())                                            # a drone in "foley" is a bed
        log = json.loads((out / "score-log.json").read_text())
        self.assertEqual(log["substems"]["music-koto"]["events"], 1)
        self.assertEqual(log["bits"], 16)

    def test_a_hot_stem_is_lowered_not_clipped(self):
        d = {"length_s": 2, "music": [{"t": 0, "inst": "drum", "vel": 1.0, "gain": 2.0}] * 3}
        out, _, err = self.render(d)
        self.assertIn("lowered by", err)
        v, _, _ = read_wav(out / "music.wav")
        self.assertLess(int(np.abs(v).max()), (1 << 23) - 1)
        pv, _, _ = read_wav(out / "preview.wav")
        self.assertLessEqual(int(np.abs(pv).max()), int(0.9 * (1 << 23)) + 1)
        log = json.loads((out / "score-log.json").read_text())
        self.assertLess(log["stems"]["music"]["gain_db"], 0)

    def test_event_seed_pins_a_sound_against_reordering(self):
        one = self.variant(foley=[{"t": 0.2, "sound": "hoof", "seed": 9}], music=[])
        two = self.variant(foley=[{"t": 5.0, "sound": "ember"}, {"t": 0.2, "sound": "hoof", "seed": 9}], music=[])
        a, _, _ = self.render(one, name="a")
        b, _, _ = self.render(two, name="b")
        va, _, _ = read_wav(a / "foley.wav")
        vb, _, _ = read_wav(b / "foley.wav")
        self.assertTrue(np.array_equal(va[:SR], vb[:SR]))


if __name__ == "__main__":
    unittest.main()
