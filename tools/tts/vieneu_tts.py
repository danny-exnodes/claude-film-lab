#!/usr/bin/env python3
"""Vietnamese narration with VieNeu-TTS, local on CPU, no API key, no per-character cost (AI Film Lab).

  python3 tools/tts/vieneu_tts.py --script projects/<p>/ep<NN>-<slug>/script.md --out out/<p>/ep<NN>/vo --voice "Thái Sơn"
  python3 tools/tts/vieneu_tts.py --lines audio/vo-lines.json --out out/<p>/ep<NN>/vo --voice "Thái Sơn" [--only VO3 VO7]
  python3 tools/tts/vieneu_tts.py --script .../script.md --out ... --dry-run          # parse + normalise only, no model
  python3 tools/tts/vieneu_tts.py --list-voices [--gender male] [--region nam]
  python3 tools/tts/vieneu_tts.py --audition "Thái Sơn,Đức Trí" --text "Câu một." --text "Câu hai." --out .../audition

Input
  --lines   cinecode vo-lines.json: {"lines": [{"id": "VO1", "text": "..."}]} (optional per line: "start_s", "slot_s")
  --script  script.md: narration lines "[mm:ss] text" (same rules as tools/check_episode.py: headings, blockquotes,
            HTML comments, code fences, front matter and rules are not narration). Ids VO1, VO2, ... in order.
  --text    one line given on the command line (repeatable; ids T1, T2, ...)
Output (in --out)
  <id>.wav (mono, 24-bit PCM, the model's native rate: 48 kHz for v3 Turbo, 24 kHz for v3 Nano) and tts-log.json
  (a list, one entry per id: id, text, spoken, file, duration_s, voice, model, version, licence, ...). Audition mode
  writes <voice-slug>_<id>.wav and audition-log.json with per-file stats (RMS, peak, clipping) and render speed.
  A table of real durations vs the script's time slots is printed; a line longer than its slot is flagged OVER.

Text normalisation (Vietnamese): pronunciation map first (--pron CSV "term,doc", e.g. Hán Việt names), then
abbreviations (TCN, SCN), Roman numerals and ordinals (thế kỷ IV -> thế kỷ thứ tư), dates, times, percentages, units
(km, m, kg, °C, ...), decimals (3,5), thousands (3.000) and plain numbers/years, read the Southern way
(ngàn, lẻ) with --numbers nam (default) or the Northern way (nghìn, linh) with --numbers bac.

Licence rule (docs/TTS.md): only Apache-2.0 models whose preset voices allow commercial use are wired in:
v3 Turbo (final) and v3 Nano (fast draft). VieNeu-TTS 0.3B and the legacy 0.5B presets (voices.json says
CC BY-NC 4.0) are not offered. The library's audio watermark (resemble-perth) is applied whenever it is installed.

Not installed? pip install vieneu==3.8.3 (see tools/tts/README.md); the tool prints the hint and exits 3.
"""
import argparse, csv, json, os, re, shutil, subprocess, sys, time, unicodedata, wave

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))
import check_episode  # noqa: E402  (tools/check_episode.py: the one script.md parser)

VIENEU_PIN = "3.8.3"
INSTALL_HINT = (f"vieneu is not installed. Install it once per session (about 2 min, ~300 MB of models on first use):\n"
                f"  pip install vieneu=={VIENEU_PIN}\n"
                f"  # optional, keeps the library's audio watermark on (CPU torch, ~1 GB):\n"
                f"  pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu && pip install resemble-perth==1.0.1\n"
                f"See tools/tts/README.md.")

MODES = {
    "v3turbo": {"repo": "pnnbao-ump/VieNeu-TTS-v3-Turbo", "licence": "Apache-2.0", "rate": 48000,
                "codec": "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX (Apache-2.0)", "use": "final"},
    "v3nano": {"repo": "pnnbao-ump/VieNeu-TTS-v3-Nano", "licence": "Apache-2.0", "rate": 24000,
               "codec": "", "use": "draft (preview model, lower quality)"},
}
EXIT_MISSING = 3
OVER_MARGIN_S = 0.0


# --- input ------------------------------------------------------------------------------------------------------
def nfc(s):
    return unicodedata.normalize("NFC", s)


def parse_script(text):
    """Narration lines of a script.md -> [{"id": "VO<n>", "text", "start_s"}] (rules of tools/check_episode.py)."""
    out = []
    for _, line in check_episode.narration_lines(nfc(text)):
        m = check_episode.RE_MARK.match(line)
        if not m or not m.group(3).strip():
            continue                                    # check_episode.py reports these; nothing to say here
        out.append({"id": f"VO{len(out) + 1}", "text": m.group(3).strip(),
                    "start_s": int(m.group(1)) * 60 + int(m.group(2))})
    return out


def episode_length(script_path):
    """length_s from the EPISODE.md next to script.md (None if absent)."""
    path = os.path.join(os.path.dirname(os.path.abspath(script_path)), "EPISODE.md")
    try:
        fm, _ = check_episode.split_front_matter(check_episode.read_text(path))
    except OSError:
        return None
    m = re.search(r"^length_s:\s*([0-9.]+)\s*(?:#.*)?$", fm or "", re.M)
    return float(m.group(1)) if m else None


def load_lines(path):
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    lines = data["lines"] if isinstance(data, dict) else data
    out = []
    for i, ln in enumerate(lines, 1):
        if not isinstance(ln, dict) or not str(ln.get("text", "")).strip():
            raise ValueError(f"{path}: line {i} has no text")
        out.append({"id": str(ln.get("id") or f"VO{i}"), "text": nfc(str(ln["text"]).strip()),
                    **{k: float(ln[k]) for k in ("start_s", "slot_s") if ln.get(k) not in (None, "")}})
    return out


def add_slots(lines, length_s=None):
    """slot_s = time until the next line's mark (or until length_s for the last one), when marks are known."""
    for i, ln in enumerate(lines):
        if "slot_s" in ln or "start_s" not in ln:
            continue
        nxt = lines[i + 1].get("start_s") if i + 1 < len(lines) else length_s
        if nxt is not None:
            ln["slot_s"] = round(float(nxt) - ln["start_s"], 3)
    return lines


# --- Vietnamese text normalisation -------------------------------------------------------------------------------
DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
DIALECT = {"nam": {"thousand": "ngàn", "odd": "lẻ"}, "bac": {"thousand": "nghìn", "odd": "linh"}}
ORDINAL = {1: "nhất", 4: "tư"}
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
ABBR = [(r"\bTCN\b", "trước Công nguyên"), (r"\bSCN\b", "sau Công nguyên"), (r"\bv\.v\.?", "vân vân")]
UNITS = [  # longest first; matched only right after a number
    ("km²", "ki lô mét vuông"), ("km2", "ki lô mét vuông"), ("m²", "mét vuông"), ("m2", "mét vuông"),
    ("km/h", "ki lô mét một giờ"), ("°C", "độ xê"), ("km", "ki lô mét"), ("cm", "xen ti mét"), ("mm", "mi li mét"),
    ("kg", "ki lô gam"), ("ha", "héc ta"), ("ml", "mi li lít"), ("m", "mét"), ("g", "gam"), ("l", "lít"),
    ("%", "phần trăm"),
]
ORDINAL_WORDS = r"thế kỷ thứ|thế kỉ thứ|thế kỷ|thế kỉ|thứ|chương|quyển|hồi|tập|phần"


def _three(n, full, d):
    """0..999 -> words. full=True reads leading zeros ('không trăm', 'lẻ') inside a larger number."""
    h, t, u = n // 100, n // 10 % 10, n % 10
    w = []
    if h or full:
        w += [DIGITS[h], "trăm"]
    if t == 0:
        if u and (h or full):
            w.append(d["odd"])
        if u:
            w.append(DIGITS[u])
        return w
    w += ["mười"] if t == 1 else [DIGITS[t], "mươi"]
    if u == 1 and t > 1:
        w.append("mốt")
    elif u == 5:
        w.append("lăm")
    elif u:
        w.append(DIGITS[u])
    return w


def num_words(n, dialect="nam"):
    """Non-negative integer -> Vietnamese words (2024 -> hai ngàn không trăm hai mươi bốn)."""
    d = DIALECT[dialect]
    n = int(n)
    if n == 0:
        return "không"
    if n >= 10 ** 15:
        return " ".join(DIGITS[int(c)] for c in str(n))
    groups = []
    while n:
        groups.append(n % 1000)
        n //= 1000
    names = ["", d["thousand"], "triệu", "tỷ", d["thousand"] + " tỷ"]
    w = []
    top = len(groups) - 1
    for i in range(top, -1, -1):
        g = groups[i]
        if g == 0:
            continue
        w += _three(g, full=i < top, d=d)
        if names[i]:
            w.append(names[i])
    return " ".join(w)


def ordinal_words(n, dialect="nam"):
    return ORDINAL.get(n) or num_words(n, dialect)


def month_words(m, dialect="nam"):
    return "tư" if m == 4 else num_words(m, dialect)


def roman_to_int(s):
    if not re.fullmatch(r"M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})", s) or not s:
        return None
    total = 0
    for i, ch in enumerate(s):
        v = ROMAN[ch]
        total += -v if i + 1 < len(s) and ROMAN[s[i + 1]] > v else v
    return total


def read_pron(path):
    """CSV with header term,doc -> [(term, doc)] longest term first. Blank lines and '#' comments skipped."""
    if not path:
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows or [c.strip().lower() for c in rows[0][:2]] != ["term", "doc"]:
        raise ValueError(f"{path}: header must be 'term,doc'")
    out = []
    for r in rows[1:]:
        if not r or not r[0].strip() or r[0].lstrip().startswith("#"):
            continue
        if len(r) < 2 or not r[1].strip():
            raise ValueError(f"{path}: '{r[0]}' has no reading")
        out.append((nfc(r[0].strip()), nfc(r[1].strip())))
    return sorted(out, key=lambda p: -len(p[0]))


def apply_pron(text, pron):
    for term, doc in pron:
        text = re.sub(rf"(?<!\w){re.escape(term)}(?!\w)", doc, text)
    return text


def _int_of(s):
    return int(s.replace(".", ""))


def normalize_vi(text, pron=(), dialect="nam"):
    """Narration text -> the words the model should say. Keeps diacritics and punctuation."""
    t = nfc(text)
    t = re.sub(r"\*\*|__|(?<!\w)[*_](?=\w)|(?<=\w)[*_](?!\w)", "", t)          # markdown emphasis
    t = apply_pron(t, pron)
    for rx, rep in ABBR:
        t = re.sub(rx, rep, t)
    nw = lambda n: num_words(n, dialect)  # noqa: E731

    def ordinal(m):
        word, val = m.group(1), m.group(2)
        n = int(val) if val.isdigit() else roman_to_int(val)
        if n is None:
            return m.group(0)
        lw = word.lower()
        if lw.endswith("thứ"):                       # thứ IV, thế kỷ thứ 4
            return f"{word} {ordinal_words(n, dialect)}"
        if lw.startswith("thế k"):                   # thế kỷ IV -> thế kỷ thứ tư
            return f"{word} thứ {ordinal_words(n, dialect)}"
        return f"{word} {nw(n)}"
    t = re.sub(rf"(?<!\w)((?i:{ORDINAL_WORDS}))\s+([IVXLCDM]+|\d+)(?!\w)", ordinal, t)

    t = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{3,4})\b",
               lambda m: f"{nw(int(m.group(1)))} tháng {month_words(int(m.group(2)), dialect)} năm {nw(int(m.group(3)))}", t)
    t = re.sub(r"\b(\d{1,2})/(\d{1,2})\b(?![/\d])",
               lambda m: f"{nw(int(m.group(1)))} tháng {month_words(int(m.group(2)), dialect)}", t)
    t = re.sub(r"\b(\d{1,2})h(\d{2})\b", lambda m: f"{nw(int(m.group(1)))} giờ {nw(int(m.group(2)))} phút", t)
    t = re.sub(r"\b(\d{1,2})h\b", lambda m: f"{nw(int(m.group(1)))} giờ", t)
    t = re.sub(r"(?<=\d)\s*[-–]\s*(?=\d)", " đến ", t)                        # 300-400 dặm

    num = r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?"
    def number(m):
        whole = nw(_int_of(m.group(1)))
        if m.group(2):
            frac = m.group(2)
            whole += " phẩy " + (nw(int(frac)) if not frac.startswith("0") else " ".join(DIGITS[int(c)] for c in frac))
        unit = m.group(3)
        if unit:
            whole += " " + dict(UNITS)[unit]
        return whole
    unit_rx = "|".join(re.escape(u) for u, _ in UNITS)
    t = re.sub(rf"(?<![\w.,]){num}(?:\s?({unit_rx})(?![\w²]))?", number, t)
    return re.sub(r"[ \t]+", " ", t).strip()


# --- audio helpers (numpy only) ----------------------------------------------------------------------------------
def write_wav24(path, wav, rate):
    import numpy as np
    x = np.clip(np.asarray(wav, dtype=np.float64).reshape(-1), -1.0, 1.0)
    i = np.round(x * 8388607.0).astype("<i4")
    b = i.view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    tmp = path + ".part"
    with wave.open(tmp, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(3)
        w.setframerate(int(rate))
        w.writeframes(b)
    os.replace(tmp, path)


def read_wav(path):
    import numpy as np
    with wave.open(path, "rb") as w:
        n, sw, rate, ch = w.getnframes(), w.getsampwidth(), w.getframerate(), w.getnchannels()
        raw = w.readframes(n)
    if sw == 3:
        a = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        i = (a[:, 0].astype(np.int32) | (a[:, 1].astype(np.int32) << 8) | (a[:, 2].astype(np.int32) << 16))
        x = np.where(i & 0x800000, i - (1 << 24), i) / 8388608.0
    elif sw == 2:
        x = np.frombuffer(raw, "<i2") / 32768.0
    else:
        raise ValueError(f"{path}: unsupported sample width {sw}")
    return x.reshape(-1, ch).mean(axis=1), rate


def audio_stats(wav, rate):
    """duration, RMS/peak in dBFS, clipped samples, leading/trailing silence (below -45 dBFS)."""
    import numpy as np
    x = np.asarray(wav, dtype=np.float64).reshape(-1)
    if not len(x):
        return {"duration_s": 0.0, "rms_dbfs": None, "peak_dbfs": None, "clipped": 0}
    db = lambda v: round(20 * np.log10(max(v, 1e-9)), 1)  # noqa: E731
    loud = np.nonzero(np.abs(x) > 10 ** (-45 / 20))[0]
    return {"duration_s": round(len(x) / rate, 3), "rms_dbfs": db(float(np.sqrt(np.mean(x ** 2)))),
            "peak_dbfs": db(float(np.max(np.abs(x)))), "clipped": int(np.sum(np.abs(x) >= 0.999)),
            "lead_silence_s": round(loud[0] / rate, 3) if len(loud) else None,
            "tail_silence_s": round((len(x) - 1 - loud[-1]) / rate, 3) if len(loud) else None}


def atempo(path, speed):
    """Post-process speed change with ffmpeg atempo (pitch kept). Used when the model has no native speed."""
    if not shutil.which("ffmpeg"):
        sys.exit("--speed needs ffmpeg for this model")
    tmp = path + ".tempo.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-filter:a", f"atempo={speed}", "-c:a", "pcm_s24le", tmp],
                   check=True)
    os.replace(tmp, path)


# --- engine ------------------------------------------------------------------------------------------------------
def voice_meta(description):
    """'Nam · Nam · Phong cách kể chuyện' -> (gender, region, style). Gender first, region second."""
    parts = [p.strip() for p in (description or "").split("·")]
    g = {"nam": "male", "nữ": "female"}.get(parts[0].lower(), "") if parts else ""
    r = {"bắc": "bac", "trung": "trung", "nam": "nam"}.get(parts[1].lower(), "") if len(parts) > 1 else ""
    return g, r, parts[2] if len(parts) > 2 else ""


def slug(s):
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    return re.sub(r"[^a-z0-9]+", "-", "".join(c for c in s if not unicodedata.combining(c)).lower()).strip("-")


class VieneuEngine:
    """Thin wrapper around vieneu.Vieneu so the CLI can be tested with a fake engine."""

    def __init__(self, mode="v3turbo", precision="int8", threads=0):
        # huggingface_hub >= 2 stores blobs in a sharded store; onnxruntime then rejects the backbone's external
        # data (".data escapes model directory"). Real files in the snapshot folder avoid that (docs/RUNBOOK.md).
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        try:
            import vieneu
        except ImportError:
            print(INSTALL_HINT, file=sys.stderr)
            sys.exit(EXIT_MISSING)
        import importlib.metadata as md
        self.mode, self.precision = mode, precision
        self.version = md.version("vieneu")
        kw = {"threads": threads}
        if mode == "v3turbo":
            kw["precision"] = precision
        try:
            self.tts = vieneu.Vieneu(mode=mode, **kw)
        except Exception as e:  # noqa: BLE001
            if "escapes model directory" in str(e):
                sys.exit(f"{e}\n-> stale symlinked HF cache: see docs/RUNBOOK.md (VieNeu: External data path escapes)")
            raise
        self.rate = int(self.tts.sample_rate)
        self.watermark = bool(getattr(self.tts, "watermarker", None))
        self.repo = MODES[mode]["repo"]
        self.revision = self._revision()

    def _revision(self):
        try:
            from huggingface_hub import hf_hub_download
            p = hf_hub_download(self.repo, "config.json")
            return os.path.basename(os.path.dirname(p))
        except Exception:  # noqa: BLE001
            return ""

    def voices(self):
        out = []
        for _, name in self.tts.list_preset_voices():
            desc = self.tts._preset_voices.get(name, {}).get("description", "")
            g, r, style = voice_meta(desc)
            out.append({"name": name, "gender": g, "region": r, "style": style, "description": desc})
        return out

    def default_voice(self):
        return getattr(self.tts, "_default_voice", None)

    def resolve(self, name):
        return self.tts.resolve_voice_name(name)

    def synth(self, text, voice, seed=None, speed=1.0):
        import numpy as np
        if seed is not None:
            np.random.seed(seed)          # v3 Turbo samples with np.random: same seed + text + voice = same take
        kw = {"voice": voice}
        if self.mode == "v3nano":
            kw.update(speed=speed, seed=seed)
        wav = self.tts.infer(text, **kw)
        return np.asarray(wav, dtype=np.float32), self.rate

    def native_speed(self):
        return self.mode == "v3nano"


# --- CLI ---------------------------------------------------------------------------------------------------------
def collect_lines(a):
    length = a.length
    if a.script:
        with open(a.script, encoding="utf-8-sig") as f:
            lines = parse_script(f.read())
        if length is None:
            length = episode_length(a.script)
        if not lines:
            sys.exit(f"{a.script}: no narration lines with a [mm:ss] mark")
    elif a.lines:
        lines = load_lines(a.lines)
    elif a.text:
        lines = [{"id": f"T{i}", "text": nfc(t)} for i, t in enumerate(a.text, 1)]
    else:
        sys.exit("give --script, --lines or --text")
    add_slots(lines, length)
    if a.only:
        keep = {x for o in a.only for x in o.split(",") if x}
        unknown = keep - {ln["id"] for ln in lines}
        if unknown:
            sys.exit(f"--only: unknown id(s) {', '.join(sorted(unknown))}")
        lines = [ln for ln in lines if ln["id"] in keep]
    return lines


def fit_label(dur, slot):
    if slot is None:
        return ""
    if dur > slot + OVER_MARGIN_S:
        return f"OVER +{dur - slot:.1f} s"
    return f"ok ({slot - dur:.1f} s spare)"


def print_table(rows):
    print(f"{'id':<6} {'mark':>6} {'slot':>6} {'dur':>6}  fit")
    for r in rows:
        mark = f"{int(r['start_s']) // 60:02d}:{int(r['start_s']) % 60:02d}" if r.get("start_s") is not None else "-"
        slot = f"{r['slot_s']:.1f}" if r.get("slot_s") is not None else "-"
        dur = f"{r['duration_s']:.2f}" if r.get("duration_s") is not None else "-"
        print(f"{r['id']:<6} {mark:>6} {slot:>6} {dur:>6}  {r.get('fit', '')}")


def merge_log(path, entries):
    log = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            log = json.load(f)
        if not isinstance(log, list):
            log = []
    ids = {e["id"] for e in entries}
    log = [e for e in log if e.get("id") not in ids] + entries
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return log


def entry_for(ln, spoken, path, dur, eng, voice, seed, speed):
    return {"id": ln["id"], "text": ln["text"], "spoken": spoken, "file": path, "duration_s": round(dur, 3),
            "seconds": round(dur, 2), "start_s": ln.get("start_s"), "slot_s": ln.get("slot_s"),
            "fit": fit_label(dur, ln.get("slot_s")), "engine": "vieneu", "mode": eng.mode, "voice": voice,
            "model": eng.repo, "model_revision": eng.revision,
            "precision": eng.precision if eng.mode == "v3turbo" else "",
            "version": f"vieneu {eng.version}", "licence": MODES[eng.mode]["licence"],
            "codec": MODES[eng.mode]["codec"], "watermark": eng.watermark, "sample_rate": eng.rate,
            "seed": seed, "speed": speed, "chars": len(spoken)}


def run_lines(a, lines, pron, make_engine):
    for ln in lines:
        ln["spoken"] = normalize_vi(ln["text"], pron, a.numbers)
    if a.dry_run:
        for ln in lines:
            print(f"{ln['id']}: {ln['spoken']}")
        print(f"dry run: {len(lines)} line(s), mode {a.mode}, voice {a.voice or '(model default)'}; nothing rendered")
        print_table(lines)
        return 0
    eng = make_engine(a)
    voice = a.voice or eng.default_voice()
    os.makedirs(a.out, exist_ok=True)
    entries, total_audio, total_cpu = [], 0.0, 0.0
    for ln in lines:
        path = os.path.join(a.out, f"{ln['id']}.wav")
        t0 = time.time()
        wav, rate = eng.synth(ln["spoken"], voice, seed=a.seed, speed=a.speed)
        total_cpu += time.time() - t0
        write_wav24(path, wav, rate)
        if a.speed != 1.0 and not eng.native_speed():
            atempo(path, a.speed)
            wav, rate = read_wav(path)
        dur = len(wav) / rate
        total_audio += dur
        e = entry_for(ln, ln["spoken"], path, dur, eng, voice, a.seed, a.speed)
        entries.append(e)
        print(f"{ln['id']}: {path}  {dur:.2f} s  {e['fit']}", flush=True)
    merge_log(os.path.join(a.out, "tts-log.json"), entries)
    print_table(entries)
    over = [e["id"] for e in entries if e["fit"].startswith("OVER")]
    speed_x = total_audio / total_cpu if total_cpu else 0
    print(f"total {total_audio:.1f} s of audio in {total_cpu:.1f} s compute ({speed_x:.2f} s audio per s) · voice {voice}"
          f" · {eng.repo} ({MODES[eng.mode]['licence']}) · watermark {'on' if eng.watermark else 'OFF (resemble-perth not installed)'}")
    if over:
        print(f"OVER slot: {', '.join(over)} -> shorten the line or move the next mark")
    return 1 if over and a.strict else 0


def pick_voices(spec, eng):
    """'Thái Sơn,Đức Trí' or 'male', 'male-nam', 'all' -> list of voice names (Southern first)."""
    vs = eng.voices()
    names = {v["name"] for v in vs}
    want = [s.strip() for s in spec.split(",") if s.strip()]
    if len(want) == 1 and want[0] in ("all", "male", "female", "male-nam", "female-nam"):
        g = {"male": "male", "female": "female", "male-nam": "male", "female-nam": "female"}.get(want[0])
        sel = [v for v in vs if (not g or v["gender"] == g) and (not want[0].endswith("-nam") or v["region"] == "nam")]
        order = {"nam": 0, "trung": 1, "bac": 2}
        return [v["name"] for v in sorted(sel, key=lambda v: order.get(v["region"], 3))]
    bad = [w for w in want if w not in names and not eng.resolve(w)]
    if bad:
        sys.exit(f"unknown voice(s): {', '.join(bad)}. --list-voices shows the presets")
    return want


def run_audition(a, lines, pron, make_engine):
    eng = make_engine(a)
    voices = pick_voices(a.audition, eng)
    meta = {v["name"]: v for v in eng.voices()}
    for ln in lines:
        ln["spoken"] = normalize_vi(ln["text"], pron, a.numbers)
    os.makedirs(a.out, exist_ok=True)
    rows = []
    print(f"{'voice':<16} {'g':<6} {'reg':<5} {'id':<4} {'dur':>6} {'rms':>6} {'peak':>6} {'clip':>5} {'x rt':>5}")
    for v in voices:
        for ln in lines:
            path = os.path.join(a.out, f"{slug(v)}_{ln['id']}.wav")
            t0 = time.time()
            wav, rate = eng.synth(ln["spoken"], v, seed=a.seed, speed=a.speed)
            cpu = time.time() - t0
            write_wav24(path, wav, rate)
            st = audio_stats(wav, rate)
            m = meta.get(v, {})
            row = {"voice": v, "gender": m.get("gender", ""), "region": m.get("region", ""), "style": m.get("style", ""),
                   "id": ln["id"], "text": ln["text"], "file": path, "compute_s": round(cpu, 2),
                   "audio_per_compute_s": round(st["duration_s"] / cpu, 3) if cpu else None, **st}
            rows.append(row)
            print(f"{v:<16} {row['gender']:<6} {row['region']:<5} {ln['id']:<4} {st['duration_s']:>6.2f} "
                  f"{st['rms_dbfs']:>6} {st['peak_dbfs']:>6} {st['clipped']:>5} {row['audio_per_compute_s']:>5}", flush=True)
    log = {"mode": eng.mode, "model": eng.repo, "model_revision": eng.revision, "precision": eng.precision,
           "version": f"vieneu {eng.version}", "licence": MODES[eng.mode]["licence"], "watermark": eng.watermark,
           "sample_rate": eng.rate, "seed": a.seed, "threads": a.threads, "cpu_count": os.cpu_count(), "takes": rows}
    with open(os.path.join(a.out, "audition-log.json"), "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    tot_a = sum(r["duration_s"] for r in rows)
    tot_c = sum(r["compute_s"] for r in rows)
    print(f"{len(rows)} take(s), {tot_a:.1f} s audio in {tot_c:.1f} s compute = {tot_a / tot_c:.2f} s audio per s"
          f" · log {os.path.join(a.out, 'audition-log.json')} · the user picks by ear")
    return 0


def list_voices(a, make_engine):
    eng = make_engine(a)
    print(f"{eng.repo} · vieneu {eng.version} · {MODES[eng.mode]['licence']} · default {eng.default_voice()}")
    for v in eng.voices():
        if a.gender and v["gender"] != a.gender or a.region and v["region"] != a.region:
            continue
        print(f"  {v['name']:<16} {v['gender']:<7} {v['region']:<6} {v['style']}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    src = p.add_mutually_exclusive_group()
    src.add_argument("--script", help="script.md with [mm:ss] narration lines")
    src.add_argument("--lines", help="cinecode vo-lines.json")
    src.add_argument("--text", action="append", help="a line of text (repeatable)")
    p.add_argument("--out", help="output folder, e.g. out/<project>/ep<NN>/vo")
    p.add_argument("--voice", help="preset voice name (see --list-voices); default: the model's default")
    p.add_argument("--only", nargs="+", help="ids to (re)render, e.g. --only VO3 VO7 (or VO3,VO7)")
    p.add_argument("--speed", type=float, default=1.0,
                   help="v3nano: native; v3turbo: ffmpeg atempo after synthesis (0.8-1.2 recommended)")
    p.add_argument("--seed", type=int, default=1234, help="same seed + text + voice = same take (default 1234)")
    p.add_argument("--pron", help="pronunciation map CSV 'term,doc' (Hán Việt names), applied before normalisation")
    p.add_argument("--numbers", choices=["nam", "bac"], default="nam",
                   help="read numbers the Southern way (ngàn, lẻ; default) or Northern way (nghìn, linh)")
    p.add_argument("--length", type=float, help="episode length in s (slot of the last line); default from EPISODE.md")
    p.add_argument("--mode", choices=sorted(MODES), default="v3turbo", help="v3turbo = final (default), v3nano = draft")
    p.add_argument("--precision", choices=["int8", "fp32"], default="int8",
                   help="v3turbo CPU backbone: int8 (default, needs a VNNI CPU) or fp32 (slower)")
    p.add_argument("--threads", type=int, default=0, help="ONNX intra-op threads (0 = library default)")
    p.add_argument("--dry-run", action="store_true", help="parse + normalise + print; no model is loaded")
    p.add_argument("--strict", action="store_true", help="exit 1 when a line is longer than its slot")
    p.add_argument("--list-voices", action="store_true")
    p.add_argument("--gender", choices=["male", "female"], help="--list-voices filter")
    p.add_argument("--region", choices=["bac", "trung", "nam"], help="--list-voices filter")
    p.add_argument("--audition", help="voices to compare: 'Thái Sơn,Đức Trí' or male | male-nam | female | all")
    return p


def main(argv=None, make_engine=None):
    a = build_parser().parse_args(argv)
    make_engine = make_engine or (lambda args: VieneuEngine(args.mode, args.precision, args.threads))
    if a.speed <= 0:
        sys.exit("--speed must be > 0")
    if a.list_voices:
        return list_voices(a, make_engine)
    try:
        pron = read_pron(a.pron)
    except (OSError, ValueError) as e:
        sys.exit(f"--pron: {e}")
    lines = collect_lines(a)
    if not a.out and not a.dry_run:
        sys.exit("--out is required")
    if a.audition:
        if a.dry_run:
            sys.exit("--audition renders audio; drop --dry-run")
        return run_audition(a, lines, pron, make_engine)
    return run_lines(a, lines, pron, make_engine)


if __name__ == "__main__":
    sys.exit(main())
