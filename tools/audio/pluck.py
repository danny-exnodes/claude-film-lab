"""Physically modelled plucked strings (extended Karplus-Strong waveguide) for AI Film Lab: guqin, pipa, koto.

Mono float32 at 48 kHz, numpy + scipy only (numba is optional), no samples, no network.

    import pluck as P
    x = P.pluck("guqin", "D3", 4, vel=.7, bend=[(0.6, 0), (1.2, 2)], vib=(5, .25, 1.4))   # slide up a tone + vibrato
    y = P.pluck("guqin", "D3", 3, harmonic=2)      # harmonic: sounds one octave above the open string D3
    z = P.pluck("pipa", "E4", 1.5, trem=14)        # lunzhi tremolo
    s = P.strum("koto", ["D3", "A3", "D4"], 3)

Length: a held note is exactly round(dur * SR) + round(release * SR) samples (release 0.25 s, harmonics 0.8 s);
dur=None rings for the preset's t60. The same arguments and seed give the same samples: there is no global
random state. numba is optional and off by default: FILM_AUDIO_ENGINE=numba compiles the sample loop for notes
whose pitch moves (bend, vib, glide) when numba imports; otherwise, and always for constant-pitch notes, numpy
and scipy do the work. `engine()` names the kernel in use. The numpy engine is the reference: its output is the
same with or without numba installed; the numba kernel differs from it in the last bits (about 2e-9) and is
not faster once a note is under a few seconds, so it is opt-in.

Adapted from core/audio/pluck.py of lemomo-ai/lemo-opuscar, Copyright (c) 2026 LemoLab, MIT License (see
THIRD_PARTY.md). Kept: the string model (3rd-order Lagrange fractional delay, one-pole loss filter, first-order
allpass stiffness, pluck-position comb, body resonances), the guqin/pipa/koto preset values, the pitch-curve and
excitation recipes, the level rule. Changed: numba is no longer required (a constant-pitch note is one
scipy.signal.lfilter call on the closed-loop transfer function, a moving pitch runs block by block, or in the
numba kernel when available); the module-level random generator is replaced by a per-call seed; the output
length is exact; `harmonic` takes the partial number (2 = octave, 3 = octave + fifth, 4 = two octaves above
the written open string) instead of a flag; the other presets, the sawari buzz and the modal instruments
(kalimba, music box) are not ported.
"""
import os
import sys

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import butter, lfilter, sosfilt

try:
    from . import sfx as _sfx
except ImportError:                                     # run or loaded as a plain script
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import sfx as _sfx

SR = _sfx.SR
midi = _sfx.midi
hz = _sfx.hz
nsamp = _sfx.nsamp

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name(m):
    k = int(round(float(m)))
    return f"{NOTE_NAMES[k % 12]}{k // 12 - 1}"


# t60: seconds to -60 dB at 220 Hz (higher notes decay faster); damp: loss low-pass 0..0.9 (higher = darker);
# pos: pluck position (0.5 = middle of the string, smaller = nearer the bridge = brighter); exc: finger or pick;
# nap/ap: allpass stages and coefficient (string stiffness); body: resonances (Hz, Q, gain); bmix: body share.
PRESETS = {
    "guqin": dict(t60=7.0, damp=.45, pos=.13, exc="finger", nap=1, ap=-.05, bright=.35,
                  body=[(95, 5, 1), (210, 6, .8), (420, 6, .5), (820, 5, .35), (1500, 4, .2)], bmix=.55, noise=.02, slide_noise=.5),
    "pipa":  dict(t60=2.8, damp=.18, pos=.09, exc="pick", nap=2, ap=-.12, bright=.8,
                  body=[(190, 7, 1), (420, 7, .8), (900, 6, .6), (1900, 5, .4), (3300, 4, .25)], bmix=.45, noise=.05, slide_noise=0.0),
    "koto":  dict(t60=3.5, damp=.3, pos=.22, exc="pick", nap=1, ap=-.06, bright=.55,
                  body=[(140, 6, 1), (300, 6, .8), (640, 5, .5), (1300, 4, .3)], bmix=.5, noise=.03, slide_noise=0.0),
}
OVERRIDES = ("t60", "damp", "pos", "bright", "bmix", "noise")
HARMONICS = (2, 3, 4)
RELEASE, RELEASE_HARMONIC = 0.25, 0.8


# ---------------------------------------------------------------- waveguide kernels
def _lagrange(fr):
    """3rd-order Lagrange taps for a read `fr` (0..1) past the second of four consecutive samples."""
    return (-fr * (fr - 1) * (fr - 2) / 6, (fr + 1) * (fr - 1) * (fr - 2) / 2,
            -(fr + 1) * fr * (fr - 2) / 2, (fr + 1) * fr * (fr - 1) / 6)


def _loop_const(exc, d, g, p, ap, nap):
    """Constant delay: the loop y = exc + g * allpass^nap(lowpass(delay(y))) as one IIR filter."""
    m = int(np.ceil(d))
    c0, c1, c2, c3 = _lagrange(m - d)
    den = np.array([1.0, -p])
    num_ap = np.array([1.0])
    for _ in range(nap):
        den = np.convolve(den, [1.0, ap])
        num_ap = np.convolve(num_ap, [ap, 1.0])
    fb = np.zeros(m + 2)
    fb[m - 2:m + 2] = (c3, c2, c1, c0)                  # taps at delays m-2, m-1, m, m+1
    fb = g * (1 - p) * np.convolve(fb, num_ap)
    a = np.zeros(max(len(den), len(fb)))
    a[:len(den)] = den
    a[:len(fb)] -= fb
    return lfilter(den, a, exc)


def _loop_blocks(exc, D, g, p, ap, nap):
    """Time-varying delay in numpy: blocks shorter than the shortest delay only read finished samples."""
    n = len(exc)
    M = np.ceil(D).astype(np.int64)
    c0, c1, c2, c3 = _lagrange(M - D)
    pad = int(M.max()) + 2
    buf = np.zeros(pad + n)
    idx = np.arange(n) + pad - M                        # position of the tap at delay M
    step = max(1, int(M.min()) - 3)
    zl = np.zeros(1)
    za = [np.zeros(1) for _ in range(nap)]
    for s in range(0, n, step):
        e = min(n, s + step)
        i = idx[s:e]
        v = c0[s:e] * buf[i - 1] + c1[s:e] * buf[i] + c2[s:e] * buf[i + 1] + c3[s:e] * buf[i + 2]
        v, zl = lfilter([1 - p], [1.0, -p], v, zi=zl)
        v = g * v
        for k in range(nap):
            v, za[k] = lfilter([ap, 1.0], [1.0, ap], v, zi=za[k])
        buf[pad + s:pad + e] = exc[s:e] + v
    return buf[pad:]


def _loop_py(exc, D, g, p, ap, nap):
    """The same loop sample by sample (compiled by numba when available)."""
    n = len(exc)
    size = 1
    while size < int(D.max()) + 16:
        size *= 2
    mask = size - 1
    buf = np.zeros(size)
    out = np.zeros(n)
    st_x = np.zeros(8)
    st_y = np.zeros(8)
    low = 0.0
    for i in range(n):
        r = i - D[i]
        ri = int(np.floor(r))
        fr = r - ri
        x0 = buf[(ri - 1) & mask]
        x1 = buf[ri & mask]
        x2 = buf[(ri + 1) & mask]
        x3 = buf[(ri + 2) & mask]
        v = (-fr * (fr - 1) * (fr - 2) / 6) * x0 + ((fr + 1) * (fr - 1) * (fr - 2) / 2) * x1 \
            + (-(fr + 1) * fr * (fr - 2) / 2) * x2 + ((fr + 1) * fr * (fr - 1) / 6) * x3
        low = (1 - p) * v + p * low
        s = g * low
        for k in range(nap):
            y = ap * s + st_x[k] - ap * st_y[k]
            st_x[k] = s
            st_y[k] = y
            s = y
        o = exc[i] + s
        buf[i & mask] = o
        out[i] = o
    return out


_KERNEL = {}


def _moving_kernel():
    if "fn" not in _KERNEL:
        fn, name = _loop_blocks, "numpy"
        if os.environ.get("FILM_AUDIO_ENGINE", "").lower() == "numba":
            try:
                from numba import njit
                fn, name = njit(cache=True)(_loop_py), "numba"
            except Exception:                           # numba missing or unusable: the numpy blocks do the job
                pass
        _KERNEL["fn"], _KERNEL["name"] = fn, name
    return _KERNEL["fn"]


def engine():
    """"numpy" (default) or "numba" (FILM_AUDIO_ENGINE=numba and numba imports): the kernel for moving pitches."""
    _moving_kernel()
    return _KERNEL["name"]


# ---------------------------------------------------------------- string
def _ap_delay(a, f):
    w = 2 * np.pi * np.atleast_1d(f) / SR
    ph = np.angle((a + np.exp(-1j * w)) / (1 + a * np.exp(-1j * w)))
    return -ph / w


def _lp_delay(p, f):
    w = 2 * np.pi * np.atleast_1d(f) / SR
    return -np.angle((1 - p) / (1 - p * np.exp(-1j * w))) / w


def _body(x, modes, mix):
    y = np.zeros_like(x)
    for f, q, a in modes:
        if f >= SR / 2 * .95:
            continue
        bw = f / q
        lo, hi = max(20, f - bw / 2), min(SR / 2 * .98, f + bw / 2)
        y += a * sosfilt(butter(1, [lo, hi], "band", fs=SR, output="sos"), x)
    return x * (1 - mix) + y * mix * 2.5


def _excite(kind, period, vel, pos, bright, noise, rng):
    """Initial displacement: a triangle set by the pluck position, a little noise, low-passed by velocity."""
    n = max(4, int(period))
    k = min(n - 1, max(1, int(round(pos * n))))
    tri = np.concatenate([np.linspace(0, 1, k, endpoint=False), np.linspace(1, 0, n - k)])
    e = tri - tri.mean()
    if kind == "pick":
        e = e + .4 * np.diff(np.concatenate([[0], tri])) * n / 6
    e = e + noise * rng.standard_normal(n) * (1 + vel)
    fc = float(np.clip(700 + 15000 * bright * vel ** 1.3, 400, SR / 2 * .9))
    e = sosfilt(butter(2, fc, "low", fs=SR, output="sos"), np.concatenate([e, np.zeros(n)]))[:n]
    d = int(round(pos * n))
    e2 = e.copy()
    if 0 < d < n:
        e2[d:] -= e[:-d] * .6
    return e2 / (np.abs(e2).max() + 1e-9)


def _pitch_curve(m, n, bend, vib, glide):
    t = np.arange(n) / SR
    c = np.full(n, float(m))
    if bend:
        bt, bv = zip(*sorted((float(a), float(b)) for a, b in bend))
        c += np.interp(t, bt, bv)
    if glide:
        c += (midi(glide[0]) - m) * np.clip(t / max(float(glide[1]), 1e-3), 0, 1) ** 1.5
    if vib:
        rate, depth = float(vib[0]), float(vib[1])
        start = float(vib[2]) if len(vib) > 2 else .3
        c += depth * np.clip((t - start) / .4, 0, 1) * np.sin(2 * np.pi * rate * np.maximum(t - start, 0))
    return c


def sounding_midi(pitch, harmonic=None):
    """The pitch that is heard: the written pitch, or the chosen partial of it for a harmonic."""
    return midi(pitch) + (12 * np.log2(_partial(harmonic)) if harmonic else 0.0)


def _partial(harmonic):
    if harmonic is True:
        return 2
    if isinstance(harmonic, bool) or harmonic not in HARMONICS:
        raise ValueError(f"harmonic must be true or one of {HARMONICS} (2 = octave, 3 = octave + fifth, 4 = two octaves)")
    return int(harmonic)


def length(preset, dur=None, harmonic=None, release=None):
    """Samples pluck() returns for these arguments."""
    if dur is None:
        return nsamp(PRESETS[preset]["t60"])
    rel = release if release is not None else (RELEASE_HARMONIC if harmonic else RELEASE)
    return nsamp(dur) + nsamp(rel)


def _string(preset, m, dur, vel, harmonic, bend, vib, glide, trem, release, rng, kw):
    q = dict(PRESETS[preset])
    q.update(kw)
    n = length(preset, dur, harmonic, release)
    if harmonic:                                        # pure, bell-like: plucked in the middle, no stiffness, no noise
        m = m + 12 * np.log2(_partial(harmonic))
        q.update(damp=min(.85, q["damp"] + .3), pos=.5, bright=.15, nap=0, noise=0.0)
    f0 = float(hz(m))
    if f0 >= SR / 12:
        raise ValueError(f"pitch too high for the string model ({f0:.0f} Hz)")
    moving = bool(bend or vib or glide)
    damp, ap, nap = q["damp"], q["ap"], q["nap"]
    t60 = q["t60"] * (1.8 if harmonic else 1) * (220 / max(f0, 30)) ** .35
    g = 10 ** (-3 / (t60 * f0))
    exc = np.zeros(n)
    hits = [0.0]
    if trem:
        hits = list(np.arange(0, dur, 1 / float(trem)))
    for i, at in enumerate(hits):
        v = vel * (1 if i == 0 else .75 + .2 * rng.random())
        pos = q["pos"] * (1 + .15 * (rng.random() - .5) * (i > 0))
        e = _excite(q["exc"], SR / f0, v, pos, q["bright"], q["noise"], rng) * v
        s = nsamp(at)
        k = max(0, min(len(e), n - s))
        exc[s:s + k] += e[:k]
    if moving:
        pc = _pitch_curve(m, n, bend, vib, glide)
        f = hz(pc)
        if f.max() >= SR / 12:
            raise ValueError("pitch curve goes too high for the string model")
        D = np.maximum(SR / f - _lp_delay(damp, f) - (nap * _ap_delay(ap, f) if nap else 0), 4.0)
        y = _moving_kernel()(exc, D, g, damp, ap, nap)
    else:
        d = SR / f0 - float(_lp_delay(damp, f0)[0]) - (nap * float(_ap_delay(ap, f0)[0]) if nap else 0)
        y = _loop_const(exc, max(d, 4.0), g, damp, ap, nap)
    if harmonic:
        y = sosfilt(butter(2, f0 * .7, "high", fs=SR, output="sos"), y)
    if moving and q.get("slide_noise"):                 # silk-string friction while the finger slides
        speed = np.abs(np.gradient(pc)) * SR            # semitones per second
        nz = sosfilt(butter(2, [900, 4500], "band", fs=SR, output="sos"), rng.standard_normal(n))
        env = uniform_filter1d(np.minimum(speed / 8, 1), size=480, mode="constant")
        y += q["slide_noise"] * .04 * vel * nz * env * np.exp(-np.arange(n) / (SR * t60 * .6))
    y = _body(y, q["body"], q["bmix"])
    if dur is not None:                                 # note-off: damp the string over the release
        dn = nsamp(dur)
        rel = (n - dn) / SR
        if dn < n:
            y[dn:] *= np.exp(-6.9 * np.arange(n - dn) / SR / max(rel, .01))
    return y


def pluck(preset, pitch, dur=None, vel=.8, harmonic=None, bend=None, vib=None, glide=None, trem=None,
          release=None, seed=0, **kw):
    """One plucked note.

    preset: guqin, pipa or koto. pitch: 'D3', 'F#4', 'Bb2' or a MIDI number (C4 = 60, fractions allowed).
    dur: seconds the note is held (None = let it ring for the preset's t60). vel: 0..1.
    harmonic: True or 2 (octave above the written pitch), 3 (octave + fifth), 4 (two octaves).
    bend: [(t, semitones), ...] piecewise linear, held after the last point. vib: (Hz, depth in semitones[, start s]).
    glide: (target pitch, seconds). trem: re-plucks per second (needs dur). release: seconds after dur.
    seed: every random detail (string noise, tremolo accents) comes from it.
    kw: preset overrides t60, damp, pos, bright, bmix, noise.
    """
    if preset not in PRESETS:
        raise KeyError(f"unknown preset {preset!r}; available: {', '.join(PRESETS)}")
    bad = sorted(set(kw) - set(OVERRIDES))
    if bad:
        raise TypeError(f"unknown option(s) {', '.join(bad)}; preset overrides: {', '.join(OVERRIDES)}")
    if dur is not None and not dur > 0:
        raise ValueError("dur must be positive")
    if trem and dur is None:
        raise ValueError("trem needs dur")
    if release is not None and release < 0:
        raise ValueError("release must not be negative")
    m = midi(pitch)
    vel = float(np.clip(vel, .01, 1))
    rng = _sfx.rng_for(seed, "pluck", preset)
    y = _string(preset, m, dur, vel, harmonic, bend, vib, glide, trem, release, rng, kw)
    y = sosfilt(butter(1, 25, "high", fs=SR, output="sos"), y)
    k = min(len(y), 960)
    y[-k:] *= np.linspace(1, 0, k)                      # 20 ms to zero at the very end
    # level: the loudest 0.1 s window sits at 0.1 rms at vel 0.8, the peak never above 0.9
    w = int(.1 * SR)
    if len(y) > w:
        cs = np.concatenate([[0.0], np.cumsum(y[:int(1.5 * SR)] ** 2)])
        r = np.sqrt(max((cs[w:] - cs[:-w]).max() / w, 0.0) + 1e-12)
    else:
        r = np.abs(y).max() + 1e-9
    y = y * (.1 / r) * (vel / .8) ** 1.2
    pk = np.abs(y).max()
    if pk > .9:
        y *= .9 / pk
    return y.astype(np.float32)


def strum_length(preset, count, dur, spread=.025, harmonic=None, release=None):
    return length(preset, dur, harmonic, release) + max(0, count - 1) * nsamp(spread)


def strum(preset, pitches, dur, vel=.8, spread=.025, up=False, seed=0, **kw):
    """Strum or arpeggio: the pitches one after another, `spread` seconds apart (up=True: last pitch first)."""
    ps = list(pitches)[::-1] if up else list(pitches)
    if not ps:
        raise ValueError("strum needs at least one pitch")
    step = nsamp(spread)
    xs = [pluck(preset, p, dur, vel * (1 - .05 * i), seed=seed + 7919 * i, **kw) for i, p in enumerate(ps)]
    out = np.zeros(len(xs[0]) + (len(xs) - 1) * step, np.float32)
    for i, x in enumerate(xs):
        out[i * step:i * step + len(x)] += x
    return out * np.float32(1 / np.sqrt(len(xs)))
