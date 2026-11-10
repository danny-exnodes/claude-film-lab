#!/usr/bin/env python3
"""Wire the COMPOSE 2.5D toolkit (tools/compose/*.js) into a cinecode Quick film.html. Standard library only; free.

  python3 tools/compose/inline.py <film>/film.html --init [--anchors projects/<p>/<ep<NN>|q<NN>-t<NN>>-<slug>/anchors.json]
  python3 tools/compose/inline.py <film>/film.html [--anchors ...]      # refresh the kit / anchors after a change
  python3 tools/compose/inline.py --lint                                # check the kit itself (no film)

What it does (idempotent; run it again after any change to tools/compose/ or anchors.json):
  1. Inlines the kit as one <script> block before the film's own script (between compose-kit markers), with
     anchors.json embedded as COMPOSE.ANCHORS. film.html stays one self-contained file (cinecode Quick mode).
  2. Sets the page's default size to 1920x1080 (the template's default is 1080x1920); --size WxH for another.
  3. Chains the plates into READY: loadType(TYPE).then(loadFormulas).then(loadPlates), so every plate is decoded and
     every texture prebuilt before READY resolves (else capture reports `deterministic: NO`).
  4. --init only, on a fresh film.html (cinecode's example scenes still present): replaces the FILM section from
     "Cues are shared" to the HELPERS line with .claude/skills/film-compose-shot/templates/plates-film-section.js, adds
     the 'plates' look and fills STATE.md's Format line (when it is still the placeholder).
  5. Refuses a kit or FILM section that uses Math.random, Date or performance.now (frames must be pure functions of
     time and SEED).
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
TEMPLATE = REPO / ".claude" / "skills" / "film-compose-shot" / "templates" / "plates-film-section.js"
ORDER = ["core.js", "plates.js", "stage.js", "breath.js", "strip-warp.js", "eyelid.js", "mist.js", "embers.js", "glow.js"]
BEGIN, END = "<!-- compose-kit begin", "<!-- compose-kit end -->"
FORBIDDEN = re.compile(r"Math\.random|\bDate\b|performance\.now")
FILM_START, FILM_END = "// ============================== FILM", "// ============================== HELPERS (picture)"
REGION_START = "// Cues are shared by picture and sound"
LOOK_LINE = "const LOOK_ID = new URLSearchParams(location.search).get('look') || 'cinematic-realistic';"
PLATES_LOOK = ("// 'plates' look (film-compose-shot): the painted plates carry the texture; no bloom, no paper or halftone pass.\n"
               "LOOKS.plates = { grade: 'contrast(1.03) saturate(0.97)', bloom: 0, texture: null, vignette: 0.22, grain: 0.025, "
               "grainHold: 1, hold: 24, line: 0, steps: 0,\n"
               "  palette: { bg: '#efe7d6', ink: '#1a1714', accent: '#b02e22', dim: '#8c8475' } };\n")


def code_only(src):
    """JavaScript without its comments (good enough for the lint: the kit has no '//' inside strings)."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(line.split("//", 1)[0] for line in src.splitlines())


def lint(name, src):
    bad = [f"{name}:{i}: {line.strip()}" for i, line in enumerate(code_only(src).splitlines(), 1) if FORBIDDEN.search(line)]
    return bad


def kit_source():
    parts, errors = [], []
    for f in ORDER:
        src = (HERE / f).read_text(encoding="utf-8")
        errors += lint(f, src)
        parts.append(f"// ---- tools/compose/{f}\n{src.rstrip()}\n")
    return "\n".join(parts), errors


def version():
    m = re.search(r"C\.VERSION = '([^']+)'", (HERE / "core.js").read_text(encoding="utf-8"))
    return m[1] if m else "?"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("film", nargs="?", help="the film's film.html")
    ap.add_argument("--anchors", help="anchors.json to embed as COMPOSE.ANCHORS")
    ap.add_argument("--init", action="store_true", help="fresh film: put the plates FILM section in place of the examples")
    ap.add_argument("--size", default="1920x1080", help="the page's default WxH (default 1920x1080)")
    ap.add_argument("--lint", action="store_true", help="only check the kit")
    a = ap.parse_args()

    kit, errors = kit_source()
    if errors:
        sys.exit("FAILED: the kit uses time or randomness that is not seeded:\n  " + "\n  ".join(errors))
    if a.lint:
        print(f"compose kit v{version()}: {len(ORDER)} files, lint ok")
        return
    if not a.film:
        ap.error("film.html is required (or --lint)")
    film = Path(a.film).resolve()
    html = film.read_text(encoding="utf-8")
    notes = []

    # 4. --init: the template FILM section in place of the examples
    if a.init:
        if "function fieldGathers" not in html:
            sys.exit("FAILED: --init is for a fresh film.html (cinecode's example scenes are gone already); "
                     "run without --init to refresh the kit")
        i, j = html.find(REGION_START), html.find(FILM_END)
        if i < 0 or j < 0:
            sys.exit("FAILED: film.html does not look like cinecode's Quick template (markers not found)")
        html = html[:i] + TEMPLATE.read_text(encoding="utf-8").rstrip() + "\n\n" + html[j:]
        notes.append(f"FILM section: {TEMPLATE.relative_to(REPO)} in place of the example scenes")
        if LOOK_LINE in html:
            html = html.replace(LOOK_LINE, PLATES_LOOK + LOOK_LINE.replace("'cinematic-realistic';", "'plates';"))
            notes.append("look: 'plates' added and made the default")
        state = film.parent / "STATE.md"
        if state.exists():
            s = state.read_text(encoding="utf-8")
            if "<length, aspect, size, fps>" in s:
                m = re.search(r"const DURATION = ([\d.]+)", html)
                w, h = a.size.split("x")
                state.write_text(s.replace("<length, aspect, size, fps>",
                                           f"{m[1] if m else '?'} s, 16:9, {w}x{h}, 24 fps"), encoding="utf-8")
                notes.append(f"STATE.md Format: 16:9, {w}x{h}")

    # 1. the kit block (and the anchors) before the film's own script
    anchors = ""
    if a.anchors:
        data = json.loads(Path(a.anchors).read_text(encoding="utf-8"))
        anchors = f"COMPOSE.ANCHORS = {json.dumps(data, ensure_ascii=False, separators=(',', ':'))};\n"
        notes.append(f"anchors: {a.anchors} ({len(data.get('plates', data))} plate(s))")
    block = (f"{BEGIN} v{version()}: tools/compose/inline.py writes this block; never edit it by hand -->\n"
             f"<script>\n{kit}\n{anchors}</script>\n{END}\n")
    if BEGIN in html:
        b, e = html.find(BEGIN), html.find(END)
        if e < 0:
            sys.exit("FAILED: a compose-kit begin marker without its end marker; fix film.html by hand")
        if not anchors:                          # keep anchors embedded earlier when none are given now
            old = re.search(r"COMPOSE\.ANCHORS = .*?;\n", html[b:e])
            if old:
                block = block.replace("</script>\n" + END, old[0] + "</script>\n" + END)
        html = html[:b] + block + html[e + len(END) + 1:]
    else:
        k = html.find("<script>", html.find("<body"))
        if k < 0:
            sys.exit("FAILED: no <script> after <body> in film.html")
        html = html[:k] + block + html[k:]
    notes.append(f"kit v{version()} inlined ({len(kit) // 1024} KB)")

    # 2. default size
    w, h = a.size.split("x")
    size_re = re.compile(r"const W = \+q\.get\('w'\) \|\| (\d+), H = \+q\.get\('h'\) \|\| (\d+)")
    m = size_re.search(html)
    if m and (m[1], m[2]) != (w, h):
        html = size_re.sub(f"const W = +q.get('w') || {w}, H = +q.get('h') || {h}", html, count=1)
        notes.append(f"default size {m[1]}x{m[2]} -> {w}x{h}")

    # 3. READY waits for the plates
    ready = re.search(r"^window\.READY = loadType\(TYPE\)\.then\(loadFormulas\)(\.then\(loadPlates\))?", html, re.M)
    if not ready:
        sys.exit("FAILED: READY line not found; chain loadPlates into window.READY by hand")
    if not ready[1]:
        html = html[:ready.end()] + ".then(loadPlates)" + html[ready.end():]
        notes.append("READY: .then(loadPlates) chained")
    if not re.search(r"^(async )?function loadPlates\b", html, re.M):
        notes.append("WARNING: no function loadPlates in the FILM section (templates/plates-film-section.js has one)")

    # 5. the FILM section's own determinism
    s, e = html.find(FILM_START), html.find(FILM_END)
    if s >= 0 and e > s:
        bad = lint("film.html FILM", html[s:e])
        if bad:
            sys.exit("FAILED: the FILM section uses unseeded time or randomness (use COMPOSE.rng/noise, rng(), t):\n  "
                     + "\n  ".join(bad))

    film.write_text(html, encoding="utf-8")
    print(f"{film}: " + " · ".join(notes))


if __name__ == "__main__":
    main()
