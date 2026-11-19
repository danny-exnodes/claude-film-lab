#!/usr/bin/env python3
"""Wire the COMPOSE 2.5D toolkit (tools/compose/*.js) into a cinecode Quick film.html. Standard library only; free.

  python3 tools/compose/inline.py <film>/film.html --init [--anchors projects/<p>/<ep<NN>|q<NN>-t<NN>>-<slug>/anchors.json]
  python3 tools/compose/inline.py <film>/film.html [--anchors ...]      # refresh the kit / anchors after a change
  python3 tools/compose/inline.py --lint                                # check the kit itself (no film)
  python3 tools/compose/inline.py <film>/film.html --init --toon         # method: code (characters drawn in code)

--toon (method: code, .claude/skills/film-compose-shot/references/code-method.md): the TOON kit (tools/toon/*.js, in
TOON_ORDER) is inlined after the COMPOSE kit, with TOON.THREE_URL = file://$FILM_THREE (default
/opt/film-lab/vendor/three/build/three.module.js); READY chains loadToon instead of loadPlates; --init puts
templates/toon-film-section.js in place and adds the 'toon' look (the style draws its own texture). A film that already
carries the TOON kit keeps it on a refresh without --toon.

What it does (idempotent; run it again after any change to tools/compose/ or anchors.json):
  1. Inlines the kit as one <script> block before the film's own script (between compose-kit markers), with
     anchors.json embedded as COMPOSE.ANCHORS. film.html stays one self-contained file (cinecode Quick mode).
     Files are inlined in ORDER; an OPTIONAL one (cloth.js, pose.js) that is not there yet is skipped, any other
     missing file is `FAILED`. --lint prints how many files were inlined.
  2. Sets the page's default size to 1920x1080 (the template's default is 1080x1920); --size WxH for another.
  3. Chains the plates into READY: loadType(TYPE).then(loadFormulas).then(loadPlates), so every plate is decoded and
     every texture prebuilt before READY resolves (else capture reports `deterministic: NO`).
  4. --init only, on a fresh film.html (cinecode's example scenes still present): replaces the FILM section from
     "Cues are shared" to the HELPERS line with .claude/skills/film-compose-shot/templates/plates-film-section.js, adds
     the 'plates' look and fills STATE.md's Format line (when it is still the placeholder).
  5. Refuses a kit or FILM section that uses Math.random, Date or performance.now (frames must be pure functions of
     time and SEED).
  6. Rewrites `qc: qc.warnings` in READY's return to `qc: COMPOSE.report().concat(qc.warnings)`: a headless capture
     never shows console.warn, so the kit's warnings travel in READY's qc list, which make.py prints (`compose: ...`
     lines first). Prints a WARNING line when that text is not found (a cinecode template change).

Anchors: the begin marker records where they came from (`anchors=<path as given> sha=<8 hex>`). A refresh without
--anchors reads that file again when it exists (`anchors: refreshed from <path>`), else keeps what is embedded
(`anchors: kept from the earlier embed`; also for films inlined before the source was recorded).
Every argument is checked and every edit is made in memory first: an error is `FAILED: <reason>`, exit 1, and neither
film.html nor STATE.md is changed. STATE.md is written after film.html.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
TEMPLATE = REPO / ".claude" / "skills" / "film-compose-shot" / "templates" / "plates-film-section.js"
TOON_TEMPLATE = TEMPLATE.parent / "toon-film-section.js"
TOON_DIR = HERE.parent / "toon"
# tools/toon/*.js for method: code, inlined after ORDER with --toon (tests/js/toon.test.cjs loads the same list)
TOON_ORDER = ["rig.js", "motion.js", "project.js", "look2d.js", "look3d.js", "post.js", "toon.js"]
TOON_MARK = "// ---- tools/toon/"
THREE_DEFAULT = "/opt/film-lab/vendor/three/build/three.module.js"
# cloth.js cuts its region out of the plate at load, so it comes after strip-warp.js and eyelid.js, which sample the
# whole plate in their own prepare step.
ORDER = ["core.js", "plates.js", "stage.js", "breath.js", "strip-warp.js", "foliage.js", "eyelid.js", "cloth.js",
         "pose.js", "mist.js", "embers.js", "glow.js", "smoke.js", "fire.js"]
# Registered in ORDER and in motions.json ahead of their files: skipped while the file is not there. Any other file
# of ORDER that is missing fails the run.
OPTIONAL = {"cloth.js", "pose.js"}
BEGIN, END = "<!-- compose-kit begin", "<!-- compose-kit end -->"
# the begin marker: version, and where the embedded anchors came from (absent in films inlined by kit 1.0.0)
MARKER = re.compile(re.escape(BEGIN) + r" v(\S+?)(?: anchors=(.*?) sha=([0-9a-f]{8}))?: ")
EMBED = re.compile(r"COMPOSE\.ANCHORS = .*?;\n")
QC_OLD, QC_NEW = "qc: qc.warnings", "qc: COMPOSE.report().concat(qc.warnings)"
QC_TOON = "qc: COMPOSE.report().concat(TOON.report(), qc.warnings)"
FORBIDDEN = re.compile(r"Math\.random|\bDate\b|performance\.now")
FILM_START, FILM_END = "// ============================== FILM", "// ============================== HELPERS (picture)"
REGION_START = "// Cues are shared by picture and sound"
LOOK_LINE = "const LOOK_ID = new URLSearchParams(location.search).get('look') || 'cinematic-realistic';"
PLATES_LOOK = ("// 'plates' look (film-compose-shot): the painted plates carry the texture; no bloom, no paper or halftone pass.\n"
               "LOOKS.plates = { grade: 'contrast(1.03) saturate(0.97)', bloom: 0, texture: null, vignette: 0.22, grain: 0.025, "
               "grainHold: 1, hold: 24, line: 0, steps: 0,\n"
               "  palette: { bg: '#efe7d6', ink: '#1a1714', accent: '#b02e22', dim: '#8c8475' } };\n")
TOON_LOOK = ("// 'toon' look (method: code): the style pack's TOON look draws its own texture, grain and holds; no pass on top.\n"
             "LOOKS.toon = { grade: '', bloom: 0, texture: null, vignette: 0, grain: 0, grainHold: 1, hold: 24, line: 0, steps: 0,\n"
             "  palette: { bg: '#101418', ink: '#f4f1ea', accent: '#f2b84b', dim: '#5c6670' } };\n")


def code_only(src):
    """JavaScript without its comments (good enough for the lint: the kit has no '//' inside strings)."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(line.split("//", 1)[0] for line in src.splitlines())


def lint(name, src):
    bad = [f"{name}:{i}: {line.strip()}" for i, line in enumerate(code_only(src).splitlines(), 1) if FORBIDDEN.search(line)]
    return bad


def kit_source(toon=False):
    """-> (the kit as one script, lint errors, files inlined, optional files that are not there).
    toon: also the TOON kit (tools/toon/, TOON_ORDER) after the COMPOSE files."""
    parts, errors, used, skipped = [], [], [], []
    for f in ORDER:
        path = HERE / f
        if f in OPTIONAL and not path.is_file():
            skipped.append(f)
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            fail(f"kit file tools/compose/{f}: cannot be read ({getattr(e, 'strerror', None) or e})")
        errors += lint(f, src)
        parts.append(f"// ---- tools/compose/{f}\n{src.rstrip()}\n")
        used.append(f)
    for f in (TOON_ORDER if toon else []):
        try:
            src = (TOON_DIR / f).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            fail(f"kit file tools/toon/{f}: cannot be read ({getattr(e, 'strerror', None) or e})")
        errors += lint("toon/" + f, src)
        parts.append(f"{TOON_MARK}{f}\n{src.rstrip()}\n")
        used.append("toon/" + f)
    if toon:
        three = os.environ.get("FILM_THREE", THREE_DEFAULT)
        url = three if three.startswith("file://") else "file://" + three
        parts.append(f"TOON.THREE_URL = {json.dumps(url)};\n")
    return "\n".join(parts), errors, used, skipped


def toon_version():
    m = re.search(r"T\.VERSION = '([^']+)'", (TOON_DIR / "rig.js").read_text(encoding="utf-8"))
    return m[1] if m else "?"


def version():
    m = re.search(r"C\.VERSION = '([^']+)'", (HERE / "core.js").read_text(encoding="utf-8"))
    return m[1] if m else "?"


def fail(msg):
    sys.exit("FAILED: " + msg)


def read_anchors(path):
    """anchors.json -> (the `COMPOSE.ANCHORS = ...;` line, number of plates, first 8 hex of the file's sha256)."""
    try:
        raw = Path(path).read_bytes()
    except OSError as e:
        fail(f"anchors {path}: cannot be read ({e.strerror or e})")
    try:
        data = json.loads(raw)
    except ValueError as e:
        fail(f"anchors {path}: not JSON ({e})")
    if not isinstance(data, dict):
        fail(f"anchors {path}: must be a JSON object of plates (tools/layers/anchors.py writes one), "
             f"not a {type(data).__name__}")
    plates = data["plates"] if isinstance(data.get("plates"), dict) else data
    # inside <script>: "</" would close the block and "<!--" would open a comment state; both escapes are plain
    # characters again once JavaScript has read the string
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/").replace("<!--", "<\\!--")
    return f"COMPOSE.ANCHORS = {text};\n", len(plates), hashlib.sha256(raw).hexdigest()[:8]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("film", nargs="?", help="the film's film.html")
    ap.add_argument("--anchors", help="anchors.json to embed as COMPOSE.ANCHORS")
    ap.add_argument("--init", action="store_true", help="fresh film: put the plates FILM section in place of the examples")
    ap.add_argument("--size", default="1920x1080", help="the page's default WxH (default 1920x1080)")
    ap.add_argument("--lint", action="store_true", help="only check the kit")
    ap.add_argument("--toon", action="store_true", help="method: code: inline the TOON kit (tools/toon/) too")
    a = ap.parse_args()

    kit, errors, used, skipped = kit_source(toon=a.toon)
    toon_used = []
    if a.lint and (TOON_DIR / "toon.js").is_file():   # the TOON kit is linted too, and counted apart
        _k, terr, tused, _s = kit_source(toon=True)
        errors += [e for e in terr if e.startswith("toon/")]
        toon_used = [f for f in tused if f.startswith("toon/")]
    if errors:
        sys.exit("FAILED: the kit uses time or randomness that is not seeded:\n  " + "\n  ".join(errors))
    if a.lint:
        print(f"compose kit v{version()}: {len(used)} files, lint ok"
              + (f" (optional, not there yet: {', '.join(skipped)})" if skipped else "")
              + (f"; toon v{toon_version()}: {len(toon_used)} files, lint ok" if toon_used else ""))
        return
    if not a.film:
        ap.error("film.html is required (or --lint)")

    # Every argument is checked, and every edit made in memory, before anything is written.
    size = re.fullmatch(r"([1-9]\d*)x([1-9]\d*)", a.size)
    if not size:
        fail(f"--size must be WxH in pixels, e.g. 1920x1080 (got {a.size!r})")
    w, h = size[1], size[2]
    given = None
    if a.anchors:
        if any(x in a.anchors for x in ("-->", "--!>", "\n", "\r", " sha=")):
            fail(f"--anchors {a.anchors!r}: this path cannot be recorded in film.html; rename the file")
        given = read_anchors(a.anchors)
    film = Path(a.film).resolve()
    try:
        html = film.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        fail(f"{a.film}: cannot be read ({getattr(e, 'strerror', None) or e})")
    notes, warnings, state_edit = [], [], None
    toon = a.toon or TOON_MARK in html            # a film that carries the TOON kit keeps it on a refresh
    if toon and not a.toon:
        kit, errors, used, skipped = kit_source(toon=True)
        if errors:
            sys.exit("FAILED: the kit uses time or randomness that is not seeded:\n  " + "\n  ".join(errors))

    # 4. --init: the template FILM section in place of the examples
    if a.init:
        if "function fieldGathers" not in html:
            sys.exit("FAILED: --init is for a fresh film.html (cinecode's example scenes are gone already); "
                     "run without --init to refresh the kit")
        i, j = html.find(REGION_START), html.find(FILM_END)
        if i < 0 or j < 0:
            sys.exit("FAILED: film.html does not look like cinecode's Quick template (markers not found)")
        tpl = TOON_TEMPLATE if toon else TEMPLATE
        html = html[:i] + tpl.read_text(encoding="utf-8").rstrip() + "\n\n" + html[j:]
        notes.append(f"FILM section: {tpl.relative_to(REPO)} in place of the example scenes")
        if LOOK_LINE in html:
            name = "toon" if toon else "plates"
            html = html.replace(LOOK_LINE, (TOON_LOOK if toon else PLATES_LOOK) + LOOK_LINE.replace("'cinematic-realistic';", f"'{name}';"))
            notes.append(f"look: '{name}' added and made the default")
        state = film.parent / "STATE.md"
        if state.exists():
            try:
                s = state.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                fail(f"{state}: cannot be read ({getattr(e, 'strerror', None) or e})")
            if "<length, aspect, size, fps>" in s:
                m = re.search(r"const DURATION = ([\d.]+)", html)
                state_edit = (state, s.replace("<length, aspect, size, fps>",
                                               f"{m[1] if m else '?'} s, 16:9, {w}x{h}, 24 fps"))
                notes.append(f"STATE.md Format: 16:9, {w}x{h}")

    # 1. the kit block (and the anchors) before the film's own script
    b = e = -1
    old_version = source = sha = None
    old_embed = ""
    if BEGIN in html:
        b, e = html.find(BEGIN), html.find(END)
        if e < 0:
            sys.exit("FAILED: a compose-kit begin marker without its end marker; fix film.html by hand")
        marker = MARKER.match(html, b)
        if marker:
            old_version, source, sha = marker.groups()
        found = EMBED.search(html[b:e])
        old_embed = found[0] if found else ""
    anchors = ""
    if given:
        (anchors, n, sha), source = given, a.anchors
        notes.append(f"anchors: {a.anchors} ({n} plate(s))")
    elif source and Path(source).is_file():     # the file may have changed since: never keep a stale embed silently
        anchors, n, sha = read_anchors(source)
        notes.append(f"anchors: refreshed from {source} ({n} plate(s), "
                     f"{'unchanged' if anchors == old_embed else 'changed'})")
    elif old_embed:
        anchors = old_embed
        notes.append("anchors: kept from the earlier embed"
                     + (f" ({source} is not there now)" if source else " (its source was not recorded; pass --anchors)"))
    else:
        source = sha = None
    origin = f" anchors={source} sha={sha}" if source and anchors else ""
    block = (f"{BEGIN} v{version()}{origin}: tools/compose/inline.py writes this block; never edit it by hand -->\n"
             f"<script>\n{kit}\n{anchors}</script>\n{END}\n")
    if b >= 0:
        rest = html[e + len(END):]
        html = html[:b] + block + (rest[1:] if rest.startswith("\n") else rest)   # at most the one newline we wrote
    else:
        k = html.find("<script>", html.find("<body"))
        if k < 0:
            sys.exit("FAILED: no <script> after <body> in film.html")
        html = html[:k] + block + html[k:]
    came_from = f"v{old_version} -> " if old_version and old_version != version() else ""
    notes.append(f"kit {came_from}v{version()}" + (f" + toon v{toon_version()}" if toon else "")
                 + f" inlined ({len(used)} files, {len(kit) // 1024} KB)")

    # 2. default size
    size_re = re.compile(r"const W = \+q\.get\('w'\) \|\| (\d+), H = \+q\.get\('h'\) \|\| (\d+)")
    m = size_re.search(html)
    if m and (m[1], m[2]) != (w, h):
        html = size_re.sub(f"const W = +q.get('w') || {w}, H = +q.get('h') || {h}", html, count=1)
        notes.append(f"default size {m[1]}x{m[2]} -> {w}x{h}")

    # 3. READY waits for the plates (or, with the TOON kit, for loadToon: three.js before the first frame)
    loader = "loadToon" if toon else "loadPlates"
    ready = re.search(r"^window\.READY = loadType\(TYPE\)\.then\(loadFormulas\)(\.then\((loadPlates|loadToon)\))?", html, re.M)
    if not ready:
        sys.exit(f"FAILED: READY line not found; chain {loader} into window.READY by hand")
    if not ready[1]:
        html = html[:ready.end()] + f".then({loader})" + html[ready.end():]
        notes.append(f"READY: .then({loader}) chained")
    elif ready[2] != loader:
        html = html[:ready.start(1)] + f".then({loader})" + html[ready.end(1):]
        notes.append(f"READY: .then({ready[2]}) -> .then({loader})")
    ready = re.search(r"^window\.READY = loadType\(TYPE\)", html, re.M)
    if not re.search(rf"^(async )?function {loader}\b", html, re.M):
        tpl = "toon-film-section.js" if toon else "plates-film-section.js"
        warnings.append(f"WARNING: no function {loader} in the FILM section (templates/{tpl} has one)")

    # 6. READY's qc list carries the kit's warnings (compose lines first: make.py prints only the first few)
    head, tail = html[:ready.start()], html[ready.start():]
    want = QC_TOON if toon else QC_NEW
    if want not in tail:
        have = QC_NEW if QC_NEW in tail else QC_TOON if QC_TOON in tail else QC_OLD if QC_OLD in tail else None
        if have:
            html = head + tail.replace(have, want, 1)
            notes.append("READY qc: COMPOSE.report()" + (" + TOON.report()" if toon else "") + " first")
        else:
            warnings.append(f"WARNING: `{QC_OLD}` not found in READY's return: the kit's warnings will not reach a "
                            f"headless run (cinecode changed its template? docs/RUNBOOK.md); add `{want}` by hand")

    # 5. the FILM section's own determinism
    s, e = html.find(FILM_START), html.find(FILM_END)
    if s >= 0 and e > s:
        bad = lint("film.html FILM", html[s:e])
        if bad:
            sys.exit("FAILED: the FILM section uses unseeded time or randomness (use COMPOSE.rng/noise, rng(), t):\n  "
                     + "\n  ".join(bad))

    try:                                        # write_text truncates the file before it encodes: check first
        html.encode("utf-8")
    except UnicodeEncodeError as e:
        fail(f"film.html would not be valid UTF-8 ({e.reason}: {e.object[max(0, e.start - 30):e.start + 1]!a}); "
             "a lone surrogate in an anchors.json key or in the --anchors path? Nothing was written")
    film.write_text(html, encoding="utf-8")
    if state_edit:                              # after film.html: a failed run must not leave STATE.md ahead of it
        state_edit[0].write_text(state_edit[1], encoding="utf-8")
    print(f"{film}: " + " · ".join(notes))
    for line in warnings:
        print(line)


if __name__ == "__main__":
    main()
