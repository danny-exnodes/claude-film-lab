"""Procedural foley and mixing bricks for AI Film Lab (numpy + scipy only, no samples, no network).

Every named sound returns mono float32 at 48 kHz, exactly round(dur * SR) samples, peak below 1.0, and is a pure
function of its arguments: the same (dur, intensity, pitch, seed) gives the same samples, there is no global
random state.

    import sfx
    x = sfx.hoof(intensity=.7, seed=3)             # dry wood knock with a mountain echo tail
    w = sfx.wind(dur=20, intensity=.4, seed=1)     # ambience bed
    buf = sfx.stereo(30.0)                         # (N, 2) float32 of zeros
    sfx.add(buf, x, at=12.4, gain=.6, pan=.1)      # constant-power pan, sample position round(at * SR)

Building bricks (SR, t_, env_exp, bp/lp/hp, noise, brown, norm, compress, limit, add) are adapted from
core/audio/sfx.py of lemomo-ai/lemo-opuscar, Copyright (c) 2026 LemoLab, MIT License (see THIRD_PARTY.md).
Changes: the module-level random generator is gone (every noise source takes a seeded generator), compress() is
vectorised (no per-sample Python loop), limit() takes stereo with one linked gain, add() rounds the start
sample and returns the span it wrote, and the toy-brick effects of the source are not ported. The named foley
below (wind, brush_air, hoof, ink_drop, gong, drum, drum_roll, drone, fire, ember, whoosh, thump, footstep,
cloth_flap, water_ring) is written for this lab's style table (styles/thuy-mac/sound.md); only thump() follows
the source's recipe.
"""
import re
import zlib

import numpy as np
from scipy.ndimage import maximum_filter1d, uniform_filter1d
from scipy.signal import butter, lfilter, sosfilt

SR = 48000
PEAK = 0.9          # a sound at intensity 1.0 peaks here


# ---------------------------------------------------------------- bricks
def nsamp(d):
    """Seconds -> samples, the one rounding rule of this package."""
    return int(round(float(d) * SR))


def t_(d):
    return np.arange(nsamp(d)) / SR


def env_exp(d, tau):
    return np.exp(-t_(d) / tau)


def _edge(f):
    return float(min(max(f, 5.0), SR / 2 * 0.98))


def bp(x, lo, hi, o=2):
    lo, hi = _edge(lo), _edge(hi)
    if hi <= lo * 1.01:
        hi = min(lo * 1.2, SR / 2 * 0.99)
    return sosfilt(butter(o, [lo, hi], "band", fs=SR, output="sos"), x)


def lp(x, f, o=2):
    return sosfilt(butter(o, _edge(f), "low", fs=SR, output="sos"), x)


def hp(x, f, o=2):
    return sosfilt(butter(o, _edge(f), "high", fs=SR, output="sos"), x)


def rng_for(seed, *salt):
    """A generator that depends only on the seed and the salt (names are hashed with crc32, never hash())."""
    words = [int(seed) & 0xFFFFFFFF]
    for s in salt:
        words.append(zlib.crc32(s.encode("utf-8")) if isinstance(s, str) else int(s) & 0xFFFFFFFF)
    return np.random.default_rng(np.random.SeedSequence(words))


def noise(d, rng):
    return rng.standard_normal(nsamp(d))


def norm(x, p=1.0):
    m = np.abs(x).max() if len(x) else 0.0
    return x * (p / m) if m > 0 else x


def brown(d, rng):
    w = np.cumsum(noise(d, rng))
    if len(w) > 1:
        w = w - np.linspace(w[0], w[-1], len(w))
    return norm(hp(w, 20))


def fade(x, fin=0.0, fout=0.0):
    """Raised-cosine fades in place on a copy; fades longer than half the sound are shortened."""
    y = np.array(x, dtype=np.float64)
    n = len(y)
    a, b = min(nsamp(fin), n // 2), min(nsamp(fout), n // 2)
    if a > 0:
        y[:a] *= 0.5 - 0.5 * np.cos(np.pi * np.arange(a) / a)
    if b > 0:
        y[n - b:] *= 0.5 + 0.5 * np.cos(np.pi * (np.arange(b) + 1) / b)
    return y


def compress(x, thr=0.25, ratio=3.5, att=0.004, rel=0.08):
    """Feed-forward compressor. Envelope = peak held over the attack window, then a one-pole release."""
    ax = np.abs(np.asarray(x, dtype=np.float64))
    if ax.ndim == 2:
        ax = ax.max(axis=1)
    held = maximum_filter1d(ax, size=max(1, nsamp(att)), mode="constant")
    r = np.exp(-1.0 / (rel * SR))
    env = np.maximum(held, lfilter([1 - r], [1, -r], held))
    g = np.where(env > thr, (thr + (env - thr) / ratio) / np.maximum(env, 1e-9), 1.0)
    return x * (g[:, None] if np.ndim(x) == 2 else g)


def limit(x, ceil=0.9, look=0.005):
    """Look-ahead peak limiter. Mono (N,) or stereo (N, 2) with one linked gain; never exceeds ceil;
    samples whose neighbourhood stays under ceil pass unchanged, and zeros stay zeros."""
    x = np.asarray(x)
    pk = np.abs(x).max(axis=1) if x.ndim == 2 else np.abs(x)
    if not len(pk) or pk.max() <= ceil:
        return x.copy()
    n = max(1, nsamp(look))
    m = maximum_filter1d(pk.astype(np.float64), size=2 * n + 1, mode="constant")
    g = np.minimum(1.0, ceil / np.maximum(m, 1e-12))
    g = uniform_filter1d(g, size=n, mode="nearest")
    return (x * (g[:, None] if x.ndim == 2 else g)).astype(x.dtype)


def stereo(d):
    return np.zeros((nsamp(d), 2), dtype=np.float32)


def add(buf, x, at, gain=1.0, pan=0.0):
    """Mix mono x into the stereo buffer at `at` seconds (constant-power pan, centre = unity on both sides).
    Returns the (start, end) sample span written, or None when x falls outside the buffer."""
    s = nsamp(at)
    if s >= len(buf) or s + len(x) <= 0:
        return None
    if s < 0:
        x, s = x[-s:], 0
    e = min(len(buf), s + len(x))
    left, right = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    seg = np.asarray(x[:e - s], dtype=np.float64) * gain * 1.41421356
    buf[s:e, 0] += (seg * left).astype(buf.dtype)
    buf[s:e, 1] += (seg * right).astype(buf.dtype)
    return s, e


# ---------------------------------------------------------------- helpers of the named sounds
def _amt(intensity):
    return float(min(1.0, max(0.0, intensity)))


def _mult(pitch):
    p = float(pitch)
    if not 0.1 <= p <= 10:
        raise ValueError(f"pitch multiplier {pitch!r} out of range 0.1..10")
    return p


def _finish(x, n, intensity, tail=0.008):
    """Exact length, DC removed, short fade at the end, level by intensity (0 -> 0.45, 1 -> 0.9 peak)."""
    y = np.zeros(n)
    k = min(n, len(x))
    y[:k] = x[:k]
    if n > 64:
        y = hp(y, 25, 1)
        y -= y.mean()
    y = fade(y, 0.0, min(tail, n / SR / 4))
    y = norm(y, PEAK * (0.5 + 0.5 * _amt(intensity)))
    return y.astype(np.float32)


def _modes(n, parts, glide=None):
    """Sum of decaying sines: parts = [(Hz, amplitude, tau s, phase)]; glide = per-sample frequency factor."""
    t = np.arange(n) / SR
    y = np.zeros(n)
    for f, a, tau, ph in parts:
        if f >= SR / 2 * 0.9:
            continue
        phase = 2 * np.pi * f * (np.cumsum(glide) / SR if glide is not None else t) + ph
        y += a * np.sin(phase) * np.exp(-t / tau)
    return y


def _band_sweep(n, f_from, f_to, width, rng, curve=1.0):
    """Noise band whose centre glides from f_from to f_to: low-passed noise times a sine chirp (no block seams)."""
    u = (np.arange(n) / max(1, n - 1)) ** curve
    f = f_from * (f_to / f_from) ** u
    carrier = np.sin(2 * np.pi * np.cumsum(f) / SR + rng.random() * 6.283)
    return lp(rng.standard_normal(n), width, 2) * carrier


def _slow(n, rate, rng):
    """Smooth random curve in 0..1 that changes about `rate` times a second."""
    k = max(4, int(n / SR * rate) + 3)
    pts = rng.random(k)
    x = np.interp(np.linspace(0, k - 1, n), np.arange(k), pts)
    w = max(1, int(SR / rate / 2))
    return uniform_filter1d(x, size=w, mode="nearest")


_NOTE = re.compile(r"\s*([A-Ga-g])([#sb]*)(-?\d+)\s*")


def midi(p):
    """'D3', 'F#4', 'Bb2' or a MIDI number (C4 = 60, fractions allowed) -> MIDI number as float."""
    if isinstance(p, bool):
        raise ValueError(f"cannot parse pitch {p!r}")
    if isinstance(p, (int, float, np.integer, np.floating)):
        v = float(p)
    else:
        m = _NOTE.fullmatch(str(p))
        if not m:
            raise ValueError(f"cannot parse pitch {p!r}")
        v = float(12 * (int(m.group(3)) + 1) + {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[m.group(1).upper()]
                  + m.group(2).count("#") + m.group(2).count("s") - m.group(2).count("b"))
    if not 0 <= v <= 127:
        raise ValueError(f"pitch {p!r} outside MIDI 0..127")
    return v


def hz(m):
    return 440.0 * 2 ** ((np.asarray(m, dtype=np.float64) - 69) / 12)


# ---------------------------------------------------------------- beds
def wind(dur=10.0, intensity=0.5, pitch=1.0, seed=0, fade_s=1.5):
    """Mountain wind bed: low band-passed noise with slow gusts and a faint higher whistle band."""
    n, a, p = nsamp(dur), _amt(intensity), _mult(pitch)
    rng = rng_for(seed, "wind")
    gust = 0.45 + 0.55 * _slow(n, 0.35, rng)
    body = bp(rng.standard_normal(n), 110 * p, (500 + 700 * a) * p) * gust
    air = bp(rng.standard_normal(n), 900 * p, 2600 * p) * (_slow(n, 0.6, rng) ** 2) * (0.10 + 0.35 * a)
    return _finish(fade(body / (np.abs(body).max() + 1e-9) + air / (np.abs(air).max() + 1e-9) * (0.15 + 0.3 * a),
                        fade_s, fade_s), n, intensity, tail=0)


def fire(dur=10.0, intensity=0.5, pitch=1.0, seed=0, fade_s=1.0):
    """Fire bed: low rumble, soft hiss and sparse seeded crackles."""
    n, a, p = nsamp(dur), _amt(intensity), _mult(pitch)
    rng = rng_for(seed, "fire")
    rumble = lp(brown(n / SR, rng), 260 * p) * (0.6 + 0.4 * _slow(n, 1.5, rng))
    hiss = bp(rng.standard_normal(n), 2500 * p, 9000 * p) * 0.05 * (0.5 + 0.5 * _slow(n, 3, rng))
    imp = np.zeros(n)
    k = rng.poisson((4 + 22 * a) * n / SR)
    if k and n:
        pos = rng.integers(0, n, k)
        np.add.at(imp, pos, rng.choice([-1.0, 1.0], k) * rng.random(k) ** 2.5)
    r = np.exp(-1.0 / (0.0015 * SR))
    crack = hp(lfilter([1.0], [1.0, -r], imp), 1100 * p)
    crack = crack / (np.abs(crack).max() + 1e-9)
    return _finish(fade(rumble * 0.7 + hiss + crack * (0.35 + 0.5 * a), fade_s, fade_s), n, intensity, tail=0)


def drone(dur=8.0, intensity=0.5, pitch="D2", seed=0, fade_s=1.5):
    """Bowed low drone (a synthesised approximation, not a real bowed instrument): two slightly detuned
    saw-like voices, slow bow-pressure movement, a little bow noise. pitch is a note name or MIDI number."""
    n, a = nsamp(dur), _amt(intensity)
    f0 = float(hz(midi(pitch)))
    rng = rng_for(seed, "drone")
    t = np.arange(n) / SR
    y = np.zeros(n)
    for cents, amp in ((-4.0, 1.0), (5.0, 0.8)):
        fv = f0 * 2 ** (cents / 1200) * (1 + 0.0015 * (2 * _slow(n, 0.7, rng) - 1))
        ph = 2 * np.pi * np.cumsum(fv) / SR + rng.random() * 6.283
        for k in range(1, 15):
            if f0 * k > 2600:
                break
            y += amp * np.sin(k * ph) / k ** (1.15 - 0.25 * a) * (0.75 + 0.25 * np.sin(2 * np.pi * (0.05 + 0.013 * k) * t + k))
    bow = 0.55 + 0.45 * _slow(n, 0.5, rng)
    y = lp(y, 700 + 1500 * a) * bow
    y = y / (np.abs(y).max() + 1e-9) + bp(rng.standard_normal(n), 1500, 4200) * 0.012 * bow
    return _finish(fade(y, fade_s, fade_s), n, intensity, tail=0)


# ---------------------------------------------------------------- events
def brush_air(dur=0.5, intensity=0.5, pitch=1.0, seed=0):
    """'Gió bút': the air of a brush stroke, for tail/hair sway (strip-warp) and cloth. Peaks at 40 % of dur."""
    n, a, p = nsamp(dur), _amt(intensity), _mult(pitch)
    rng = rng_for(seed, "brush_air")
    u = np.arange(n) / max(1, n - 1)
    env = np.sin(np.pi * np.clip(u, 0, 1) ** 0.76) ** 2
    y = _band_sweep(n, 700 * p, (2600 + 2400 * a) * p, 900, rng) + 0.35 * _band_sweep(n, 2500 * p, 6500 * p, 1800, rng)
    return _finish(y * env, n, intensity)


def whoosh(dur=1.2, intensity=0.5, pitch=1.0, seed=0, rise=True):
    """Smoke or mist rising: a low noise band that climbs and swells, then lets go (rise=False falls)."""
    n, a, p = nsamp(dur), _amt(intensity), _mult(pitch)
    rng = rng_for(seed, "whoosh")
    lo, hi = 140 * p, (900 + 1700 * a) * p
    u = np.arange(n) / max(1, n - 1)
    y = _band_sweep(n, lo if rise else hi, hi if rise else lo, 260, rng, curve=1.4) + 0.5 * lp(rng.standard_normal(n), 220 * p)
    env = np.where(u < 0.72, (u / 0.72) ** 2, np.cos((u - 0.72) / 0.28 * np.pi / 2) ** 2)
    return _finish(y * (env if rise else env[::-1]), n, intensity)


def hoof(dur=0.6, intensity=0.5, pitch=1.0, seed=0):
    """Hoof on stone: a short dry wood knock with a faint mountain echo tail."""
    n, a, p = nsamp(dur), _amt(intensity), _mult(pitch)
    rng = rng_for(seed, "hoof")
    j = 1 + 0.06 * (rng.random(4) - 0.5)
    k = min(n, nsamp(0.09))
    knock = _modes(k, [(820 * p * j[0], 1.0, 0.014, 0), (1370 * p * j[1], 0.6, 0.010, 1), (2210 * p * j[2], 0.3 + 0.4 * a, 0.006, 2),
                       (190 * p * j[3], 0.5, 0.020, 0)])
    knock += hp(rng.standard_normal(k), 2400) * np.exp(-np.arange(k) / (0.0015 * SR)) * (0.3 + 0.5 * a)
    y = np.zeros(n)
    y[:k] = knock
    wet = lp(y, 1500)
    for delay, g in ((0.105, 0.20), (0.235, 0.09), (0.37, 0.04)):
        d = nsamp(delay)
        if d < n:
            y[d:] += g * wet[:n - d]
    return _finish(y, n, intensity)


def ink_drop(dur=0.5, intensity=0.5, pitch=1.0, seed=0):
    """A drop of ink for an eye opening or closing: a small 'tink' and a wet tail."""
    n, a, p = nsamp(dur), _amt(intensity), _mult(pitch)
    rng = rng_for(seed, "ink_drop")
    t = np.arange(n) / SR
    f = 2350 * p * (1 + 0.03 * rng.random())
    tink = np.sin(2 * np.pi * f * t) * np.exp(-t / 0.035) + 0.35 * np.sin(2 * np.pi * f * 2.76 * t) * np.exp(-t / 0.012)
    d = min(n, nsamp(0.018))
    tb = np.arange(n - d) / SR
    bub = np.sin(2 * np.pi * (520 * p * tb + 0.5 * 5200 * p * tb ** 2)) * np.exp(-tb / 0.045)
    wet = bp(rng.standard_normal(n - d), 350 * p, 1500 * p) * np.exp(-tb / 0.03)
    y = tink * (0.6 + 0.4 * a)
    y[d:] += 0.8 * bub + 0.5 * wet / (np.abs(wet).max() + 1e-9)
    return _finish(y, n, intensity)


def gong(dur=4.0, intensity=0.5, pitch=1.0, seed=0):
    """Small gong, one stroke (a synthesised approximation): inharmonic partials with beating pairs."""
    n, a, p = nsamp(dur), _amt(intensity), _mult(pitch)
    rng = rng_for(seed, "gong")
    t = np.arange(n) / SR
    f0 = 392.0 * p
    glide = 1 + 0.012 * (1 + a) * np.exp(-t / 0.25)          # the pitch settles after the stroke
    parts = []
    for i, r in enumerate((1.0, 1.52, 2.08, 2.71, 3.46, 4.38, 5.47, 6.9)):
        amp = (1.0 if i == 0 else (0.55 + 0.5 * a) / (i ** (1.35 - 0.6 * a)))
        tau = 1.5 / (1 + 0.55 * i)
        for det in (1.0, 1.0 + 0.003 * (1 + rng.random())):
            parts.append((f0 * r * det, amp * 0.5, tau, rng.random() * 6.283))
    y = _modes(n, parts, glide)
    k = min(n, nsamp(0.03))
    y[:k] += bp(rng.standard_normal(k), 600, 5000) * np.exp(-np.arange(k) / (0.004 * SR)) * (0.3 + 0.6 * a) * 2
    y[:min(n, 96)] *= np.linspace(0, 1, min(n, 96))
    return _finish(y, n, intensity, tail=0.05)


def drum(dur=0.8, intensity=0.5, pitch=1.0, seed=0):
    """Frame drum, one hit: membrane modes with a quick pitch drop and a hand slap."""
    n, a, p = nsamp(dur), _amt(intensity), _mult(pitch)
    rng = rng_for(seed, "drum")
    t = np.arange(n) / SR
    glide = 1 + 0.10 * (0.5 + a) * np.exp(-t / 0.018)
    f0 = 96.0 * p * (1 + 0.02 * (rng.random() - 0.5))
    y = _modes(n, [(f0, 1.0, 0.20, 0), (f0 * 1.59, 0.55, 0.11, 0.5), (f0 * 2.14, 0.35, 0.07, 1), (f0 * 2.30, 0.25, 0.06, 2),
                   (f0 * 2.65, 0.2 * (0.5 + a), 0.045, 3), (f0 * 2.92, 0.15 * (0.5 + a), 0.04, 4)], glide)
    k = min(n, nsamp(0.05))
    y[:k] += lp(rng.standard_normal(k), 1200 + 2600 * a) * np.exp(-np.arange(k) / (0.007 * SR)) * (0.25 + 0.5 * a)
    return _finish(y, n, intensity)


def drum_roll(dur=2.0, intensity=0.5, pitch=1.0, seed=0, rate=12.0, swell=True):
    """Frame drum roll: seeded hits at about `rate` per second, swelling to the end when swell is true."""
    n, a = nsamp(dur), _amt(intensity)
    if not 1 <= float(rate) <= 40:
        raise ValueError("rate must be within 1..40 hits per second")
    rng = rng_for(seed, "drum_roll")
    y = np.zeros(n + nsamp(0.5))
    i, at = 0, 0.0
    while at < dur:
        u = at / max(dur, 1e-6)
        level = (0.25 + 0.75 * u ** 1.5) if swell else 1.0
        h = drum(0.5, intensity=a * (0.7 + 0.3 * rng.random()), pitch=_mult(pitch) * (1 + 0.03 * (i % 2)), seed=int(rng.integers(1 << 31)))
        s = nsamp(at)
        y[s:s + len(h)] += h * level * (0.8 + 0.2 * rng.random())
        at += (1.0 / float(rate)) * (1 + 0.08 * (rng.random() - 0.5))
        i += 1
    return _finish(y[:n], n, intensity, tail=0.03)


def ember(dur=0.25, intensity=0.5, pitch=1.0, seed=0):
    """One ember tick: a tiny bright crack with a short high ping."""
    n, a, p = nsamp(dur), _amt(intensity), _mult(pitch)
    rng = rng_for(seed, "ember")
    t = np.arange(n) / SR
    y = hp(rng.standard_normal(n), 1800 * p) * np.exp(-t / 0.0025)
    y = y / (np.abs(y).max() + 1e-9) + (0.25 + 0.3 * a) * np.sin(2 * np.pi * 4100 * p * (1 + 0.2 * rng.random()) * t) * np.exp(-t / 0.012)
    d = nsamp(0.03 + 0.03 * rng.random())
    if d < n:                                                  # a second, smaller pop
        y[d:] += 0.35 * hp(rng.standard_normal(n - d), 2500 * p) * np.exp(-t[:n - d] / 0.002)
    return _finish(y, n, intensity)


def thump(dur=0.4, intensity=0.5, pitch=1.0, seed=0):
    """Heavy soft impact: a low sine that drops, with a little low noise."""
    n, a, p = nsamp(dur), _amt(intensity), _mult(pitch)
    rng = rng_for(seed, "thump")
    t = np.arange(n) / SR
    y = np.sin(2 * np.pi * 70 * p * t * (1 - 0.3 * np.minimum(t, 1.0))) * np.exp(-t / 0.07)
    y += lp(rng.standard_normal(n), 300 * p) * np.exp(-t / 0.02) * (0.3 + 0.4 * a)
    return _finish(y, n, intensity)


SURFACES = ("earth", "stone")


def footstep(dur=0.3, intensity=0.5, pitch=1.0, seed=0, surface="earth"):
    """One footstep on earth (dull thud + grit) or on stone (short click + scuff)."""
    if surface not in SURFACES:
        raise ValueError(f"unknown surface {surface!r}; one of {', '.join(SURFACES)}")
    n, a, p = nsamp(dur), _amt(intensity), _mult(pitch)
    rng = rng_for(seed, "footstep", surface)
    t = np.arange(n) / SR
    if surface == "earth":
        y = np.sin(2 * np.pi * 85 * p * t * (1 - 0.8 * np.minimum(t, 0.5))) * np.exp(-t / 0.035)
        grit = bp(rng.standard_normal(n), 300 * p, 2200 * p) * np.exp(-t / 0.03) * (rng.random(n) > 0.6)
        y += norm(lp(grit, 2500)) * (0.45 + 0.4 * a)
    else:
        y = _modes(n, [(640 * p, 0.8, 0.012, 0), (1150 * p, 0.6, 0.009, 1), (150 * p, 0.5, 0.02, 0)])
        y += hp(rng.standard_normal(n), 1600 * p) * np.exp(-t / 0.004) * (0.4 + 0.5 * a)
        y += bp(rng.standard_normal(n), 2000 * p, 6000 * p) * np.exp(-((t - 0.05) / 0.025) ** 2) * 0.12
    return _finish(y, n, intensity)


def cloth_flap(dur=0.4, intensity=0.5, pitch=1.0, seed=0):
    """Cloth flap: two soft bumps of low-mid noise."""
    n, a, p = nsamp(dur), _amt(intensity), _mult(pitch)
    rng = rng_for(seed, "cloth_flap")
    u = np.arange(n) / max(1, n - 1)
    env = np.exp(-((u - 0.18) / 0.09) ** 2) + 0.7 * np.exp(-((u - 0.5) / 0.14) ** 2)
    y = bp(rng.standard_normal(n), 140 * p, (1200 + 1400 * a) * p) + 0.3 * lp(rng.standard_normal(n), 160 * p)
    return _finish(y * env, n, intensity)


def water_ring(dur=1.5, intensity=0.5, pitch=1.0, seed=0):
    """A drop on still water and its ring: a rising 'plip', two small bubbles and a soft ripple."""
    n, a, p = nsamp(dur), _amt(intensity), _mult(pitch)
    rng = rng_for(seed, "water_ring")
    t = np.arange(n) / SR
    y = np.sin(2 * np.pi * (620 * p * t + 0.5 * 9000 * p * t ** 2)) * np.exp(-t / 0.03)
    for delay, f in ((0.07 + 0.03 * rng.random(), 900), (0.16 + 0.05 * rng.random(), 1250)):
        d = nsamp(delay)
        if d < n:
            tb = t[:n - d]
            y[d:] += 0.45 * np.sin(2 * np.pi * (f * p * tb + 0.5 * 5000 * p * tb ** 2)) * np.exp(-tb / 0.022)
    ripple = bp(rng.standard_normal(n), 400 * p, 1600 * p) * np.exp(-t / (0.25 + 0.3 * a)) * (0.5 + 0.5 * np.sin(2 * np.pi * 7 * t) ** 2)
    y += ripple / (np.abs(ripple).max() + 1e-9) * (0.12 + 0.15 * a)
    return _finish(y, n, intensity)


# name -> function, default duration (s), bed (goes to the ambience stem), pitch kind, extra keyword arguments
SOUNDS = {
    "wind":       dict(fn=wind, dur=10.0, bed=True, pitch="mult", extra=("fade_s",)),
    "fire":       dict(fn=fire, dur=10.0, bed=True, pitch="mult", extra=("fade_s",)),
    "drone":      dict(fn=drone, dur=8.0, bed=True, pitch="note", extra=("fade_s",)),
    "brush_air":  dict(fn=brush_air, dur=0.5, bed=False, pitch="mult", extra=()),
    "whoosh":     dict(fn=whoosh, dur=1.2, bed=False, pitch="mult", extra=("rise",)),
    "hoof":       dict(fn=hoof, dur=0.6, bed=False, pitch="mult", extra=()),
    "ink_drop":   dict(fn=ink_drop, dur=0.5, bed=False, pitch="mult", extra=()),
    "gong":       dict(fn=gong, dur=4.0, bed=False, pitch="mult", extra=()),
    "drum":       dict(fn=drum, dur=0.8, bed=False, pitch="mult", extra=()),
    "drum_roll":  dict(fn=drum_roll, dur=2.0, bed=False, pitch="mult", extra=("rate", "swell")),
    "ember":      dict(fn=ember, dur=0.25, bed=False, pitch="mult", extra=()),
    "thump":      dict(fn=thump, dur=0.4, bed=False, pitch="mult", extra=()),
    "footstep":   dict(fn=footstep, dur=0.3, bed=False, pitch="mult", extra=("surface",)),
    "cloth_flap": dict(fn=cloth_flap, dur=0.4, bed=False, pitch="mult", extra=()),
    "water_ring": dict(fn=water_ring, dur=1.5, bed=False, pitch="mult", extra=()),
}
