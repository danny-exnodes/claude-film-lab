#!/usr/bin/env python3
"""Render an episode's code music and event foley from a JSON score into stems (AI Film Lab).

Local and free: numpy + scipy synthesis (tools/audio/pluck.py, tools/audio/sfx.py), no samples, no network, no API.

  python3 tools/audio/score.py SCORE.json --dry-run                 # validate, print the cue list, write nothing
  python3 tools/audio/score.py SCORE.json --out <media>/audio       # music.wav foley.wav ambience.wav preview.wav
  python3 tools/audio/score.py SCORE.json --out DIR --stems         # + DIR/stems/<list>-<name>.wav, one per instrument/sound
  python3 tools/audio/score.py SCORE.json --out DIR --seed 11       # another take of every random detail

SCORE.json
  {"length_s": 60, "seed": 7, "tempo": 90, "scale": ["D", "F", "G", "A", "C"],
   "music":   [{"t": 3.0, "inst": "guqin", "pitch": "D3", "dur": 4, "vel": 0.7, "pan": -0.2, "shot": "s01"}],
   "foley":   [{"t": 12.4, "sound": "hoof", "gain": 0.6, "pan": 0.1, "shot": "s03"}],
   "silence": [{"from": 20.0, "to": 23.5}]}
  music   inst = guqin | pipa | koto (pluck.py; options pitch or pitches, dur, vel, harmonic, bend, vib, glide, trem,
          release, spread, up, t60, damp, pos, bright, bmix, noise) or gong | drum | drum_roll | drone (sfx.py, vel = intensity).
  foley   sound = any name of sfx.SOUNDS (dur, intensity, pitch and the sound's own options). wind, fire and drone are
          beds: they go to ambience.wav; every other sound goes to foley.wav. Everything in "music" goes to music.wav.
  common  t (seconds) or beat (needs "tempo": t = beat * 60 / tempo), gain (linear, default 1), pan (-1..1), shot,
          note (free text), seed (pins this event's random detail), allow_in_silence.
  scale   pitch names; a music pitch outside it is a WARN. silence: true digital silence; an event that sounds
          inside a window is an ERROR unless it carries "allow_in_silence": true.

Output (in --out): music.wav, foley.wav, ambience.wav (stereo, 48 kHz, 24-bit PCM, or --bits 16), preview.wav (the
three stems summed and peak-limited: a rough listen, NOT the master; cinecode masters to -14 LUFS), score-log.json
(per file: peak dBFS, RMS, duration, events; seed, tool version, engine, licence note) and mix-snippet.json (layers
for cinecode's audio/mix.json: file, at, gain_db, bus). Existing output files are refused unless --overwrite.
The same score and seed give byte-identical files.

Exit codes: 0 ok · 2 input error or refused output (every problem is listed, nothing is written).
"""
import argparse
import hashlib
import json
import os
import re
import sys
import wave
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TOOL_VERSION = "1.0.0"
LICENCE = "synthesised by tools/audio, no samples"
MAX_LENGTH_S = 600
STEMS = ("music", "foley", "ambience")
BUS = {"music": "music", "foley": "foley", "ambience": "ambience"}     # bus names of cinecode scripts/mix.py
STEM_CEIL = 0.97
PREVIEW_CEIL = 0.9
TOP_KEYS = {"length_s", "seed", "tempo", "scale", "music", "foley", "silence", "note"}
COMMON_KEYS = {"t", "beat", "gain", "pan", "shot", "note", "seed", "allow_in_silence", "dur", "pitch"}
PLUCK_KEYS = {"inst", "pitches", "vel", "harmonic", "bend", "vib", "glide", "trem", "release", "spread", "up",
              "t60", "damp", "pos", "bright", "bmix", "noise"}
MUSIC_SOUNDS = ("gong", "drum", "drum_roll", "drone")
_PC = re.compile(r"\s*([A-Ga-g])([#sb]*)(-?\d+)?\s*")


def _libs():
    """numpy/scipy and the synthesis modules, imported on first use (a broken score fails before they load)."""
    import numpy as np
    import pluck
    import sfx
    return np, pluck, sfx


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def _pitch_class(name):
    m = _PC.fullmatch(str(name))
    if not m:
        raise ValueError(f"cannot parse scale pitch {name!r}")
    return ({"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[m.group(1).upper()]
            + m.group(2).count("#") + m.group(2).count("s") - m.group(2).count("b")) % 12


class Problems:
    def __init__(self):
        self.errors, self.warnings = [], []

    def error(self, where, msg):
        self.errors.append(f"{where}: {msg}")

    def warn(self, where, msg):
        self.warnings.append(f"{where}: {msg}")


def _event_seed(score_seed, kind, index, ev):
    key = f"{score_seed}:{kind}:seed{ev['seed']}" if "seed" in ev else f"{score_seed}:{kind}:{index}"
    return zlib.crc32(key.encode("utf-8"))


def _check_range(P, where, ev, key, lo, hi, lo_open=False):
    if key not in ev:
        return True
    v = ev[key]
    if not _num(v) or v > hi or v < lo or (lo_open and v == lo):
        P.error(where, f"{key} must be a number {'above' if lo_open else 'from'} {lo} to {hi} (got {v!r})")
        return False
    return True


def _check_pluck_options(P, where, ev, pluck):
    ok = True
    if "pitch" in ev and "pitches" in ev:
        P.error(where, "give pitch or pitches, not both")
        ok = False
    if "pitch" not in ev and "pitches" not in ev:
        P.error(where, "pitch is missing")
        return False
    pitches = ev.get("pitches", [ev.get("pitch")])
    if not isinstance(pitches, list) or not pitches:
        P.error(where, "pitches must be a non-empty list")
        return False
    for p in pitches:
        try:
            if isinstance(p, bool) or not isinstance(p, (str, int, float)):
                raise ValueError(f"cannot parse pitch {p!r}")
            h = ev.get("harmonic")
            part = 1 if not h else (2 if h is True else h if h in pluck.HARMONICS and not isinstance(h, bool) else 1)
            if float(pluck.hz(pluck.midi(p))) * part >= pluck.SR / 12:
                raise ValueError(f"pitch {p!r} is too high for the string model")
        except ValueError as e:
            P.error(where, f"bad pitch: {e}")
            ok = False
    if "pitches" in ev and "dur" not in ev:
        P.error(where, "pitches (strum) needs dur")
        ok = False
    if "harmonic" in ev and ev["harmonic"] is not False:
        h = ev["harmonic"]
        if h is not True and (isinstance(h, bool) or h not in pluck.HARMONICS):
            P.error(where, f"harmonic must be true or one of {list(pluck.HARMONICS)} (got {h!r})")
            ok = False
    if "bend" in ev:
        b = ev["bend"]
        if not (isinstance(b, list) and b and all(isinstance(x, list) and len(x) == 2 and _num(x[0]) and _num(x[1])
                                                   and x[0] >= 0 and abs(x[1]) <= 24 for x in b)):
            P.error(where, "bend must be a list of [seconds >= 0, semitones within +-24] pairs")
            ok = False
    if "vib" in ev:
        v = ev["vib"]
        if not (isinstance(v, list) and len(v) in (2, 3) and all(_num(x) for x in v) and 0 < v[0] <= 20
                and 0 <= v[1] <= 2 and (len(v) == 2 or v[2] >= 0)):
            P.error(where, "vib must be [Hz 0..20, depth 0..2 semitones] or [Hz, depth, start s]")
            ok = False
    if "glide" in ev:
        g = ev["glide"]
        try:
            if not (isinstance(g, list) and len(g) == 2 and _num(g[1]) and g[1] > 0
                    and isinstance(g[0], (str, int, float)) and not isinstance(g[0], bool)):
                raise ValueError("glide must be [target pitch, seconds > 0]")
            if float(pluck.hz(pluck.midi(g[0]))) >= pluck.SR / 12:
                raise ValueError("glide target is too high for the string model")
        except ValueError as e:
            P.error(where, f"bad glide: {e}")
            ok = False
    if "trem" in ev:
        ok &= _check_range(P, where, ev, "trem", 0, 40, lo_open=True)
        if "dur" not in ev:
            P.error(where, "trem needs dur")
            ok = False
    if "up" in ev and not isinstance(ev["up"], bool):
        P.error(where, "up must be true or false")
        ok = False
    for key, lo, hi, lo_open in (("vel", 0, 1, True), ("release", 0, 10, False), ("spread", 0, 1, False),
                                 ("t60", 0.05, 30, False), ("damp", 0, 0.9, False), ("pos", 0.02, 0.5, False),
                                 ("bright", 0, 1, False), ("bmix", 0, 1, False), ("noise", 0, 1, False)):
        ok &= _check_range(P, where, ev, key, lo, hi, lo_open)
    return ok


def _check_sound_options(P, where, ev, spec, sfx, pluck):
    ok = True
    if "pitch" in ev:
        p = ev["pitch"]
        if spec["pitch"] == "note":
            try:
                if isinstance(p, bool) or not isinstance(p, (str, int, float)):
                    raise ValueError(f"cannot parse pitch {p!r}")
                if not 20 <= float(pluck.hz(pluck.midi(p))) <= 1000:
                    raise ValueError(f"pitch {p!r} is outside 20..1000 Hz")
            except ValueError as e:
                P.error(where, f"bad pitch: {e}")
                ok = False
        elif not _num(p) or not 0.25 <= p <= 4:
            P.error(where, f"pitch of this sound is a multiplier from 0.25 to 4 (got {p!r})")
            ok = False
    for key, lo, hi, lo_open in (("intensity", 0, 1, False), ("vel", 0, 1, True), ("fade_s", 0, 60, False), ("rate", 1, 40, False)):
        ok &= _check_range(P, where, ev, key, lo, hi, lo_open)
    for key in ("rise", "swell"):
        if key in ev and not isinstance(ev[key], bool):
            P.error(where, f"{key} must be true or false")
            ok = False
    if "surface" in ev and ev["surface"] not in sfx.SURFACES:
        P.error(where, f"unknown surface {ev['surface']!r} (one of: {', '.join(sfx.SURFACES)})")
        ok = False
    return ok


def validate(score, seed=None):
    """Check the whole score. Returns (Problems, cues, length in samples); cues are render-ready, sorted by time."""
    np, pluck, sfx = _libs()
    P = Problems()
    cues = []
    if not isinstance(score, dict):
        P.error("score", "the file must hold one JSON object")
        return P, cues, 0
    for k in sorted(set(score) - TOP_KEYS):
        P.error("score", f"unknown key {k!r} (known: {', '.join(sorted(TOP_KEYS))})")
    length_s = score.get("length_s")
    if not _num(length_s) or not 0 < length_s <= MAX_LENGTH_S:
        P.error("score", f"length_s must be a number above 0 up to {MAX_LENGTH_S} (got {length_s!r})")
        length_s = None
    n_total = sfx.nsamp(length_s) if length_s else 0
    score_seed = score.get("seed", 0) if seed is None else seed
    if isinstance(score_seed, bool) or not isinstance(score_seed, int) or score_seed < 0:
        P.error("score", f"seed must be a whole number >= 0 (got {score_seed!r})")
        score_seed = 0
    tempo = score.get("tempo")
    if tempo is not None and (not _num(tempo) or not 20 <= tempo <= 300):
        P.error("score", f"tempo must be a number from 20 to 300 beats per minute (got {tempo!r})")
        tempo = None
    scale = None
    if "scale" in score:
        try:
            if not isinstance(score["scale"], list) or not score["scale"]:
                raise ValueError("scale must be a non-empty list of pitch names")
            scale = {_pitch_class(p) for p in score["scale"]}
        except ValueError as e:
            P.error("score", str(e))
    windows = []
    sil = score.get("silence", [])
    if not isinstance(sil, list):
        P.error("silence", "must be a list")
        sil = []
    for i, w in enumerate(sil):
        where = f"silence[{i}]"
        if not isinstance(w, dict) or set(w) - {"from", "to", "note"}:
            P.error(where, 'must be {"from": seconds, "to": seconds}')
            continue
        a, b = w.get("from"), w.get("to")
        if not (_num(a) and _num(b) and 0 <= a < b) or (length_s and b > length_s):
            P.error(where, f"needs 0 <= from < to <= length_s (got from {a!r} to {b!r})")
            continue
        windows.append((sfx.nsamp(a), sfx.nsamp(b), a, b))

    for kind in ("music", "foley"):
        events = score.get(kind, [])
        if not isinstance(events, list):
            P.error(kind, "must be a list")
            continue
        for i, ev in enumerate(events):
            where = f"{kind}[{i}]"
            if not isinstance(ev, dict):
                P.error(where, "must be an object")
                continue
            name_key = "inst" if kind == "music" else "sound"
            name = ev.get(name_key)
            ok = True
            hashable = isinstance(name, str)
            if kind == "music":
                is_pluck = hashable and name in pluck.PRESETS
                known = is_pluck or (hashable and name in MUSIC_SOUNDS)
                if not known:
                    P.error(where, f"unknown instrument {name!r} (one of: {', '.join(list(pluck.PRESETS) + list(MUSIC_SOUNDS))})")
            else:
                is_pluck = False
                known = hashable and name in sfx.SOUNDS
                if not known:
                    P.error(where, f"unknown sound {name!r} (one of: {', '.join(sfx.SOUNDS)})")
            spec = sfx.SOUNDS[name] if known and not is_pluck else None
            if known:
                allowed = COMMON_KEYS | ({"inst"} | PLUCK_KEYS if is_pluck else
                                         {name_key, "vel" if kind == "music" else "intensity"} | set(spec["extra"]))
                for k in sorted(set(ev) - allowed):
                    P.error(where, f"unknown key {k!r} for {name}")
                    ok = False
            # time
            t = None
            if "t" in ev and "beat" in ev:
                P.error(where, "give t or beat, not both")
            elif "beat" in ev:
                if tempo is None:
                    P.error(where, 'beat needs "tempo" in the score')
                elif not _num(ev["beat"]):
                    P.error(where, f"beat must be a number (got {ev['beat']!r})")
                else:
                    t = ev["beat"] * 60.0 / tempo
            elif "t" not in ev:
                P.error(where, "t is missing")
            elif not _num(ev["t"]):
                P.error(where, f"t must be a number (got {ev['t']!r})")
            else:
                t = ev["t"]
            if t is not None and t < 0:
                P.error(where, f"negative time {t:g} s")
                t = None
            elif t is not None and length_s and t >= length_s:
                P.error(where, f"starts at {t:g} s, past length_s {length_s:g}")
                t = None
            ok &= _check_range(P, where, ev, "gain", 0, 4, lo_open=True)
            ok &= _check_range(P, where, ev, "pan", -1, 1)
            ok &= _check_range(P, where, ev, "dur", 0, MAX_LENGTH_S, lo_open=True)
            if "seed" in ev and (isinstance(ev["seed"], bool) or not isinstance(ev["seed"], int) or ev["seed"] < 0):
                P.error(where, "seed must be a whole number >= 0")
                ok = False
            if "allow_in_silence" in ev and not isinstance(ev["allow_in_silence"], bool):
                P.error(where, "allow_in_silence must be true or false")
                ok = False
            if "shot" in ev and not isinstance(ev["shot"], str):
                P.error(where, "shot must be text")
                ok = False
            if not known:
                continue
            if is_pluck:
                ok &= _check_pluck_options(P, where, ev, pluck)
            elif spec is not None:
                ok &= _check_sound_options(P, where, ev, spec, sfx, pluck)
            if not ok or t is None or not n_total:
                continue
            # length in samples, exactly what the renderer will produce
            if is_pluck:
                harmonic = ev.get("harmonic") or None
                if "pitches" in ev:
                    n = pluck.strum_length(name, len(ev["pitches"]), ev["dur"], ev.get("spread", 0.025), harmonic, ev.get("release"))
                else:
                    n = pluck.length(name, ev.get("dur"), harmonic, ev.get("release"))
                one = pluck.length(name, ev.get("dur"), harmonic, ev.get("release"))
                if one <= 0:
                    P.error(where, "the sound would be empty (dur too short)")
                    continue
                high = [p for p in ev.get("pitches", [ev.get("pitch")])
                        if pluck.peak_hz(p, one, harmonic, ev.get("bend"), ev.get("vib"), ev.get("glide")) >= pluck.SR / 12]
                if high:                                 # the base pitch passed: the bend, vib or glide carries it too high
                    P.error(where, f"bend/vib/glide takes {'+'.join(str(p) for p in high)} too high for the string model "
                                   f"(limit {pluck.SR / 12:g} Hz)")
                    continue
                shown = "+".join(str(p) for p in ev.get("pitches", [ev.get("pitch")]))
                if harmonic:
                    shown += f" h{2 if harmonic is True else harmonic}"
                heard = [pluck.sounding_midi(p, harmonic) for p in ev.get("pitches", [ev.get("pitch")])]
                if "glide" in ev:
                    heard.append(pluck.midi(ev["glide"][0]))
                stem = "music"
            else:
                n = sfx.nsamp(ev.get("dur", spec["dur"]))
                shown = str(ev.get("pitch", "")) if spec["pitch"] == "note" or "pitch" in ev else ""
                heard = [pluck.midi(ev.get("pitch", "D2"))] if spec["pitch"] == "note" else []
                stem = "music" if kind == "music" else ("ambience" if spec["bed"] else "foley")
            if n <= 0:
                P.error(where, "the sound would be empty (dur too short)")
                continue
            if scale is not None and kind == "music":
                off = sorted({pluck.note_name(m) for m in heard if int(round(m)) % 12 not in scale})
                if off:
                    P.warn(where, f"{', '.join(off)} is outside the scale")
            s0 = sfx.nsamp(t)
            cut = s0 + n > n_total
            if cut:
                P.warn(where, f"{name} at {t:g} s rings {(s0 + n - n_total) / sfx.SR:.2f} s past length_s: its tail is faded out at the end")
                n = n_total - s0
            if n <= 0:
                P.error(where, f"starts at {t:g} s, past length_s {length_s:g}")
                continue
            inside = False
            for z0, z1, a, b in windows:
                if s0 < z1 and s0 + n > z0:
                    if ev.get("allow_in_silence"):
                        inside = True
                    else:
                        P.error(where, f"{name} at {t:g} s sounds until {(s0 + n) / sfx.SR:.2f} s, inside the silence {a:g}-{b:g} s "
                                       '(shorten or move it, or set "allow_in_silence": true)')
            cues.append(dict(kind=kind, index=i, where=where, name=name, pluck=is_pluck, stem=stem, t=float(t), start=s0,
                             samples=n, cut=cut, shown=shown, shot=ev.get("shot", ""), gain=float(ev.get("gain", 1.0)),
                             pan=float(ev.get("pan", 0.0)), seed=_event_seed(score_seed, kind, i, ev), ev=ev,
                             in_silence=inside))
    cues.sort(key=lambda c: (c["start"], c["kind"], c["index"]))
    return P, cues, n_total


def _synth(cue, pluck, sfx):
    ev, name = cue["ev"], cue["name"]
    if cue["pluck"]:
        kw = {k: ev[k] for k in ("bend", "vib", "glide", "trem", "release", "t60", "damp", "pos", "bright", "bmix", "noise") if k in ev}
        if ev.get("harmonic"):
            kw["harmonic"] = ev["harmonic"]
        for k in ("bend", "vib", "glide"):
            if k in kw:
                kw[k] = [tuple(x) for x in kw[k]] if k == "bend" else tuple(kw[k])
        if "pitches" in ev:
            return pluck.strum(name, ev["pitches"], ev["dur"], ev.get("vel", 0.8), spread=ev.get("spread", 0.025),
                               up=ev.get("up", False), seed=cue["seed"], **kw)
        return pluck.pluck(name, ev["pitch"], ev.get("dur"), ev.get("vel", 0.8), seed=cue["seed"], **kw)
    spec = sfx.SOUNDS[name]
    kw = {k: ev[k] for k in spec["extra"] if k in ev}
    if "pitch" in ev:
        kw["pitch"] = ev["pitch"]
    level = ev.get("vel" if cue["kind"] == "music" else "intensity", 0.5)
    return spec["fn"](dur=ev.get("dur", spec["dur"]), intensity=level, seed=cue["seed"], **kw)


def render(cues, n_total, substems=False):
    """Returns {"stems": {name: (N, 2) float32}, "sub": {label: buffer}, "premix", "preview", "gain_db": {stem: dB}}."""
    np, pluck, sfx = _libs()
    stems = {s: np.zeros((n_total, 2), dtype=np.float32) for s in STEMS}
    sub, sub_of = {}, {}
    for cue in cues:
        x = _synth(cue, pluck, sfx)
        full = cue["samples"] if not cue["cut"] else None
        if full is not None and len(x) != full:
            raise RuntimeError(f"{cue['where']}: rendered {len(x)} samples, expected {full}")
        if cue["cut"]:
            x = sfx.fade(x[:cue["samples"]], 0.0, 0.03).astype(np.float32)
        sfx.add(stems[cue["stem"]], x, cue["start"] / sfx.SR, cue["gain"], cue["pan"])
        if substems:
            label = f"{cue['kind']}-{cue['name']}"
            if label not in sub:
                sub[label] = np.zeros((n_total, 2), dtype=np.float32)
                sub_of[label] = cue["stem"]
            sfx.add(sub[label], x, cue["start"] / sfx.SR, cue["gain"], cue["pan"])
    gain_db = {}
    for s in STEMS:
        pk = float(np.abs(stems[s]).max()) if n_total else 0.0
        if pk > STEM_CEIL:                       # one linear gain for the whole stem: zeros stay zeros
            k = np.float32(STEM_CEIL / pk)
            stems[s] *= k
            for label, owner in sub_of.items():
                if owner == s:
                    sub[label] *= k
            gain_db[s] = round(20 * float(np.log10(k)), 2)
        else:
            gain_db[s] = 0.0
    premix = stems["music"] + stems["foley"] + stems["ambience"]
    return dict(stems=stems, sub=sub, premix=premix, preview=sfx.limit(premix, PREVIEW_CEIL), gain_db=gain_db)


def pcm_bytes(x, bits):
    np = _libs()[0]
    full = (1 << (bits - 1)) - 1
    v = np.clip(np.rint(np.asarray(x, dtype=np.float64) * full), -full, full).astype("<i4")
    if bits == 16:
        return v.astype("<i2").tobytes()
    return v.view(np.uint8).reshape(-1, 4)[:, :3].tobytes()


def write_wav(path, x, bits):
    sr = _libs()[2].SR
    with wave.open(path, "wb") as w:
        w.setnchannels(x.shape[1] if x.ndim == 2 else 1)
        w.setsampwidth(bits // 8)
        w.setframerate(sr)
        w.writeframes(pcm_bytes(x, bits))


def stats(x, events=None):
    np, _, sfx = _libs()
    pk = float(np.abs(x).max()) if len(x) else 0.0
    rms = float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2))) if len(x) else 0.0
    d = dict(peak_dbfs=round(20 * float(np.log10(pk)), 2) if pk > 0 else None,
             rms_dbfs=round(20 * float(np.log10(rms)), 2) if rms > 0 else None,
             duration_s=round(len(x) / sfx.SR, 6), dc=round(float(np.mean(x)), 7) if len(x) else 0.0)
    if events is not None:
        d["events"] = events
    return d


def cue_table(cues, sr):
    rows = [f"{'t (s)':>8}  {'stem':<8} {'name':<10} {'pitch':<12} {'len (s)':>7}  {'gain':>5} {'pan':>5}  shot"]
    for c in cues:
        rows.append(f"{c['t']:8.3f}  {c['stem']:<8} {c['name']:<10} {c['shown'][:12]:<12} {c['samples'] / sr:7.2f}  "
                    f"{c['gain']:5.2f} {c['pan']:+5.2f}  {c['shot'] or '-'}{'  [in silence]' if c['in_silence'] else ''}")
    return "\n".join(rows)


def mix_snippet(out_dir, counts):
    layers = [{"file": os.path.abspath(os.path.join(out_dir, f"{s}.wav")).replace(os.sep, "/"), "at": 0.0, "gain_db": 0,
               "bus": BUS[s]} for s in STEMS if counts[s]]
    return {"note": "paste these layers into audio/mix.json of the film (cinecode scripts/mix.py); set gain_db by ear and by qc.py",
            "layers": layers}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("score")
    ap.add_argument("--out", help="output folder, e.g. out/<project>/<episode>/audio")
    ap.add_argument("--stems", action="store_true", help="also write one file per instrument/sound in <out>/stems/")
    ap.add_argument("--dry-run", action="store_true", help="validate and print the cue list; write nothing")
    ap.add_argument("--seed", type=int, help="replace the score's seed")
    ap.add_argument("--overwrite", action="store_true", help="replace existing output files")
    ap.add_argument("--bits", type=int, choices=(16, 24), default=24)
    a = ap.parse_args(argv)

    try:
        with open(a.score, "rb") as fh:
            raw = fh.read()
        score = json.loads(raw.decode("utf-8-sig"))       # a BOM from a Windows editor is not an error
    except (OSError, ValueError) as e:
        print(f"score: cannot read {a.score}: {e}", file=sys.stderr)
        return 2
    if a.seed is not None and a.seed < 0:
        print("score: --seed must be >= 0", file=sys.stderr)
        return 2
    if not a.dry_run and not a.out:
        print("score: --out DIR is required (or --dry-run)", file=sys.stderr)
        return 2
    if not a.dry_run and os.path.exists(a.out) and not os.path.isdir(a.out):
        print(f"score: --out {a.out} exists and is not a folder", file=sys.stderr)
        return 2
    np, pluck, sfx = _libs()
    P, cues, n_total = validate(score, a.seed)
    for w in P.warnings:
        print(f"WARN {w}", file=sys.stderr)
    if P.errors:
        for e in P.errors:
            print(f"ERROR {e}", file=sys.stderr)
        print(f"score: {len(P.errors)} error(s), nothing written", file=sys.stderr)
        return 2
    seed = score.get("seed", 0) if a.seed is None else a.seed
    counts = {s: sum(1 for c in cues if c["stem"] == s) for s in STEMS}
    print(cue_table(cues, sfx.SR))
    print(f"score: {len(cues)} events ({', '.join(f'{s} {counts[s]}' for s in STEMS)}), {n_total / sfx.SR:g} s, seed {seed}, "
          f"{len(score.get('silence', []))} silence window(s), {len(P.warnings)} warning(s)")
    if a.dry_run:
        print("score: dry run, nothing written")
        return 0

    labels = sorted({f"{c['kind']}-{c['name']}" for c in cues}) if a.stems else []
    names = [f"{s}.wav" for s in STEMS] + ["preview.wav", "score-log.json", "mix-snippet.json"] \
        + [os.path.join("stems", f"{label}.wav") for label in labels]
    existing = [n for n in names if os.path.exists(os.path.join(a.out, n))]
    if existing and not a.overwrite:
        print(f"score: refused, {len(existing)} output file(s) already exist in {a.out}: {', '.join(existing)}\n"
              "  render a new version into a new folder (e.g. audio/v02), or pass --overwrite", file=sys.stderr)
        return 2

    moving = any(c["pluck"] and any(k in c["ev"] for k in ("bend", "vib", "glide")) for c in cues)
    try:
        r = render(cues, n_total, substems=a.stems)
    except (ValueError, RuntimeError) as e:              # a sound refused its arguments: nothing was written yet
        print(f"ERROR render: {e}\nscore: 1 error(s), nothing written", file=sys.stderr)
        return 2
    os.makedirs(os.path.join(a.out, "stems") if labels else a.out, exist_ok=True)
    files = {}
    for s in STEMS:
        write_wav(os.path.join(a.out, f"{s}.wav"), r["stems"][s], a.bits)
        files[s] = dict(file=f"{s}.wav", **stats(r["stems"][s], counts[s]), gain_db=r["gain_db"][s])
        if r["gain_db"][s]:
            print(f"WARN {s}: the stem peaked above {STEM_CEIL}, lowered by {-r['gain_db'][s]:.2f} dB (lower the event gains)",
                  file=sys.stderr)
    write_wav(os.path.join(a.out, "preview.wav"), r["preview"], a.bits)
    sub_files = {}
    for label in labels:
        write_wav(os.path.join(a.out, "stems", f"{label}.wav"), r["sub"][label], a.bits)
        sub_files[label] = dict(file=f"stems/{label}.wav", **stats(r["sub"][label],
                                sum(1 for c in cues if f"{c['kind']}-{c['name']}" == label)))
    windows = []
    for w in score.get("silence", []):
        z0, z1 = sfx.nsamp(w["from"]), sfx.nsamp(w["to"])
        windows.append({"from": w["from"], "to": w["to"], "exact_zero": bool(not np.any(r["premix"][z0:z1])),
                        "allowed_events": sum(1 for c in cues if c["in_silence"] and c["start"] < z1 and c["start"] + c["samples"] > z0)})
    log = {
        "tool": "tools/audio/score.py", "version": TOOL_VERSION, "licence": LICENCE,
        "score_sha256": hashlib.sha256(raw).hexdigest(), "seed": seed, "length_s": n_total / sfx.SR,
        "sample_rate": sfx.SR, "bits": a.bits, "channels": 2,
        "engine": {"constant_pitch": "scipy.signal.lfilter", "moving_pitch": pluck.engine() if moving else None},
        "stems": files,
        "preview": dict(file="preview.wav", **stats(r["preview"], len(cues)),
                        premix_peak_dbfs=stats(r["premix"])["peak_dbfs"], limiter_ceiling=PREVIEW_CEIL,
                        note="rough mix for listening, not the master (cinecode masters to -14 LUFS)"),
        "substems": sub_files, "silence": windows, "warnings": P.warnings,
        "cues": [dict(t=round(c["t"], 6), stem=c["stem"], name=c["name"], pitch=c["shown"], length_s=round(c["samples"] / sfx.SR, 6),
                      gain=c["gain"], pan=c["pan"], shot=c["shot"], seed=c["seed"]) for c in cues],
    }
    with open(os.path.join(a.out, "score-log.json"), "w", encoding="utf-8") as fh:
        json.dump(log, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    snippet = mix_snippet(a.out, counts)
    with open(os.path.join(a.out, "mix-snippet.json"), "w", encoding="utf-8") as fh:
        json.dump(snippet, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    for s in STEMS:
        f = files[s]
        print(f"  {f['file']:<13} events {f['events']:>3}  peak {f['peak_dbfs'] if f['peak_dbfs'] is not None else '-inf':>7} dBFS  "
              f"rms {f['rms_dbfs'] if f['rms_dbfs'] is not None else '-inf':>7} dBFS")
    pv = log["preview"]
    print(f"  {'preview.wav':<13} events {len(cues):>3}  peak {pv['peak_dbfs'] if pv['peak_dbfs'] is not None else '-inf':>7} dBFS  "
          f"rms {pv['rms_dbfs'] if pv['rms_dbfs'] is not None else '-inf':>7} dBFS  (rough mix, not the master)")
    for w in windows:
        print(f"  silence {w['from']:g}-{w['to']:g} s: {'exact zeros' if w['exact_zero'] else 'holds ' + str(w['allowed_events']) + ' allowed event(s)'}")
    print(f"score: wrote {len(names)} files to {a.out}; layers for audio/mix.json (cinecode mix.py):")
    print(json.dumps(snippet["layers"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
