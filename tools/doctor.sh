#!/bin/bash
# AI Film Lab environment check. No image or video is generated.
#   tools/doctor.sh           full check
#   tools/doctor.sh --quick   local checks + Ark ping (used by the SessionStart hook)
#   tools/doctor.sh [--quick] --episode DIR   also judge the narration watermark for that episode (FAIL past G3)
#   tools/doctor.sh -h        this text
# Quick mode only reads: local tools, the ark.py link, GET /models.
# Full mode adds a real import of rembg, the agent proxy status and ONE request to the video endpoint:
# a POST with an invalid resolution ("9999p") that Ark rejects before it creates a task. Should Ark
# ever accept it, doctor FAILs and prints the task id so it can be cancelled in the Ark console.
# Full mode also launches headless Chrome once through CHROME_PATH (when set) and renders a data: page.
# The exit code is the number of FAIL lines. Never prints or searches for API keys.
# ARK_DIR (default /opt/byteplus) is where the ark.py link lives; tests point it elsewhere.
set -u
LAB="$(cd "$(dirname "$0")/.." && pwd)"
ARK_DIR="${ARK_DIR:-/opt/byteplus}"
usage() { sed -n '2,/^set -u$/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'; }
QUICK=0 EPISODE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --quick) QUICK=1 ;;
    --episode) [ $# -ge 2 ] && [ -n "$2" ] || { usage >&2; exit 2; }; EPISODE=$2; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
  shift
done
# --episode DIR: "<G3 date or -> <narration lines>" of that episode (tools/status.py reads EPISODE.md), before any check
EP_INFO=""
if [ -n "$EPISODE" ]; then
  EP_INFO=$(python3 - "$LAB/tools" "$EPISODE" 2>&1 <<'PY'
import os, sys
sys.path.insert(0, sys.argv[1])
import check_episode, status
try:
    meta, _ = status.load_episode(sys.argv[2])
except status.Usage as e:
    sys.exit(str(e))
try:
    n = sum(1 for _ in check_episode.narration_lines(check_episode.read_text(os.path.join(sys.argv[2], "script.md"))))
except (OSError, ValueError, check_episode.CheckError):
    n = 0
print(status.gate_dates(meta, [])["G3"] or "-", n)
PY
  ) || { echo "doctor: --episode: $(echo "$EP_INFO" | tail -1 | cut -c1-160)" >&2; exit 2; }
fi
fails=0
ok()   { printf '  OK    %-22s %s\n' "$1" "$2"; }
bad()  { printf '  FAIL  %-22s %s\n' "$1" "$2"; fails=$((fails+1)); }
warn() { printf '  WARN  %-22s %s\n' "$1" "$2"; }

echo "AI Film Lab doctor ($( [ $QUICK = 1 ] && echo quick || echo full ))"
v=$(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}'); [ -n "$v" ] && ok ffmpeg "$v" || bad ffmpeg "not installed"
v=$(google-chrome --version 2>/dev/null); [ -n "$v" ] && ok chrome "$v" || bad chrome "google-chrome not found"
n=$(fc-list 2>/dev/null | grep -ci "Noto Serif CJK"); [ "$n" -gt 0 ] && ok font-cjk "Noto Serif CJK x$n" || bad font-cjk "missing: apt-get install -y fonts-noto-cjk"
v=$(ffprobe -version 2>/dev/null | head -1 | awk '{print $3}'); [ -n "$v" ] && ok ffprobe "$v" || warn ffprobe "not installed (check_episode.py --probe needs it)"
v=$(node --version 2>/dev/null); nmaj=${v#v}; nmaj=${nmaj%%.*}
case "$nmaj" in
  ""|*[!0-9]*) bad node "not installed: cinecode's capture needs Node 22+" ;;
  *) if [ "$nmaj" -ge 22 ]; then ok node "$v"; else bad node "$v is too old: cinecode's capture needs Node 22+"; fi ;;
esac
# rembg: quick mode only looks the modules up (fast); full mode really imports them (1-12 s)
if [ $QUICK = 1 ]; then
  v=$(python3 -c "
import importlib.metadata as m, importlib.util as u, sys
miss = [n for n in ('rembg', 'onnxruntime', 'PIL', 'numpy') if u.find_spec(n) is None]
if miss: sys.exit('missing module(s) ' + ', '.join(miss))
print(m.version('rembg'))" 2>&1) && ok rembg "$v" || bad rembg "$(echo "$v" | tail -1 | cut -c1-80): python3 -m pip install -r requirements.txt"
else
  v=$(python3 -c "
import rembg, onnxruntime, importlib.metadata as m
print(m.version('rembg'), '+ onnxruntime', onnxruntime.__version__, '(imported)')" 2>&1) && ok rembg "$v" || bad rembg "import fails ($(echo "$v" | tail -1 | cut -c1-80)): python3 -m pip install -r requirements.txt"
fi
v=$(python3 -c "import yaml; print(yaml.__version__)" 2>/dev/null) && ok pyyaml "$v" || bad pyyaml "missing: python3 -m pip install -r requirements.txt"
{ [ -f /root/.rembg/models/u2net/u2net.onnx ] || [ -f ~/.u2net/u2net.onnx ]; } && ok rembg-model "u2net cached" || warn rembg-model "u2net not cached (downloads on first use)"
# Narration (tools/tts/vieneu_tts.py): vieneu and its audio watermark (resemble-perth on CPU torch), pinned in
# requirements-tts.txt and installed by docs/setup-script.sh. Quick mode looks the modules up, full mode imports them.
# Missing = WARN (only narration needs them); the watermark is a FAIL with --episode DIR once G3 is dated and the
# episode has narration: a final take without it must be read again (#37).
tts_hint="pip install --break-system-packages -r requirements-tts.txt, CPU torch first (tools/tts/README.md)"
pymods() {  # <distributions a,b> <modules...>: "a X + b Y" or exit 1 with why (quick: looked up, full: imported)
  python3 - "$QUICK" "$@" 2>&1 <<'PY'
import importlib.metadata as m, importlib.util as u, sys
quick, mods = sys.argv[1] == "1", sys.argv[3:]
if quick:
    miss = [n for n in mods if u.find_spec(n) is None]
    if miss:
        sys.exit("missing module(s) " + ", ".join(miss))
else:
    try:
        for n in mods:
            __import__(n)
    except Exception as e:
        sys.exit(f"import fails ({type(e).__name__}: {(str(e).splitlines() or [''])[0]})")
def ver(d):
    try:
        return m.version(d)
    except m.PackageNotFoundError:
        return "?"
print(" + ".join(f"{d} {ver(d)}" for d in sys.argv[2].split(",")) + ("" if quick else " (imported)"))
PY
}
v=$(pymods vieneu vieneu); rc=$?
tts_pin=$(sed -n -E 's/^vieneu==([^[:space:]#]+).*/\1/p' "$LAB/requirements-tts.txt" 2>/dev/null)
hub="${HF_HUB_CACHE:-${HF_HOME:-$HOME/.cache/huggingface}/hub}"
if ls -d "$hub"/models--pnnbao-ump--VieNeu-TTS-v3-Turbo/snapshots/*/ >/dev/null 2>&1; then model="v3 Turbo model cached"
else model="v3 Turbo model not cached (~300 MB on first use; FILM_TTS_PREFETCH=1 in docs/setup-script.sh)"; fi
if [ $rc != 0 ]; then warn tts "$(echo "$v" | tail -1 | cut -c1-60): narration needs it; $tts_hint"
elif [ "${v%% (imported)}" = "vieneu $tts_pin" ]; then ok tts "$v, $model"
else warn tts "$v, pinned $tts_pin in requirements-tts.txt; $model"; fi
v=$(pymods resemble-perth,torch perth torch); rc=$?
read -r ep_g3 ep_lines <<< "$(echo "${EP_INFO:-- 0}" | tail -1)"
if [ $rc = 0 ]; then ok tts-watermark "$v"
elif [ "$ep_g3" != "-" ] && [ "${ep_lines:-0}" -gt 0 ]; then
  bad tts-watermark "$(echo "$v" | tail -1 | cut -c1-50); $EPISODE passed G3 ($ep_g3) with narration: final takes need it; $tts_hint"
else warn tts-watermark "$(echo "$v" | tail -1 | cut -c1-50): narration drafts read without it; $tts_hint"; fi
# cinecode is pinned (tools/compose/cinecode.ref = CINECODE_REF in docs/setup-script.sh). A different HEAD is only a
# warning; what decides is the compose-kit check below, which runs inline.py on the template that is installed.
CINE="${CINECODE_DIR:-$HOME/.claude/skills/cinecode}"   # /root/... in the cloud; CINECODE_DIR elsewhere and in tests
pin=$(tr -d '[:space:]' < "$LAB/tools/compose/cinecode.ref" 2>/dev/null)
if [ -f "$CINE/SKILL.md" ]; then
  head=$(git -C "$CINE" rev-parse HEAD 2>/dev/null)
  if [ -n "$head" ] && [ "$head" = "$pin" ]; then ok skill-cinecode "pinned ${pin:0:7}"
  elif [ -z "$head" ]; then warn skill-cinecode "present, not a git clone: cannot compare with pin ${pin:0:7}"
  else warn skill-cinecode "HEAD ${head:0:7} differs from pin ${pin:0:7} (docs/RUNBOOK.md: cinecode đổi template)"; fi
  # compose kit against the installed Quick template (free, no browser): lint, then --init on a temporary copy
  tmpd=$(mktemp -d)
  if ! out=$(python3 "$LAB/tools/compose/inline.py" --lint 2>&1); then bad compose-kit "$(echo "$out" | head -1 | cut -c1-120)"
  elif ! cp "$CINE/templates/quick/film.html" "$tmpd/film.html" 2>/dev/null; then bad compose-kit "cinecode templates/quick/film.html missing"
  elif ! out=$(python3 "$LAB/tools/compose/inline.py" "$tmpd/film.html" --init 2>&1); then bad compose-kit "inline.py --init fails on the installed cinecode template: $(echo "$out" | head -1 | cut -c1-90)"
  elif echo "$out" | grep -q WARNING || ! echo "$out" | grep -q "1080x1920 -> 1920x1080"; then bad compose-kit "inline.py --init no longer rewrites the cinecode template as expected (run tests/test_compose.py)"
  else ok compose-kit "$(python3 "$LAB/tools/compose/inline.py" --lint | cut -d: -f1), --init ok on installed template"; fi
  rm -rf "$tmpd"
else
  bad skill-cinecode "$CINE/SKILL.md missing"
fi
# three.js for the TOON 3D looks (method: code): pinned in tools/toon/three.lock. Missing = WARN (only the 3D styles
# need it); present with another hash = FAIL (a render would silently change).
tdir=$(dirname "$(dirname "${FILM_THREE:-/opt/film-lab/vendor/three/build/three.module.js}")")
out=$(FILM_THREE_DIR="$tdir" "$LAB/tools/toon/install_three.sh" --check 2>&1)
if [ $? = 0 ]; then ok three "$(echo "$out" | sed 's/^three: //')"
elif echo "$out" | grep -q "hash differs"; then bad three "$(echo "$out" | head -1 | cut -c1-110); run tools/toon/install_three.sh"
else warn three "not installed: the 3D code styles need it; run tools/toon/install_three.sh"; fi
if [ $QUICK = 0 ]; then
  # WebGL2 in headless Chromium (software, SwiftShader): the TOON 3D looks render through it
  v=$(cd "$LAB" && timeout 60 node -e "
const { chromium } = require('playwright');
(async () => { const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const p = await b.newPage(); const v = await p.evaluate(() => { const c = document.createElement('canvas').getContext('webgl2');
  return c ? c.getParameter(c.VERSION) : ''; }); await b.close(); console.log(v); })().catch((e) => { console.log(''); });" 2>/dev/null)
  case "$v" in *"WebGL 2"*) ok webgl "$v" ;; *) bad webgl "no WebGL2 in headless Chromium (the 3D code styles cannot render; docs/RUNBOOK.md)" ;; esac
fi
# The ark.py link is shared by every session in the container and belongs to the main checkout. In a linked
# git worktree it must stay there: never repoint it at work in progress.
MAIN=$(git -C "$LAB" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) && MAIN=$(dirname "$MAIN") || MAIN=""
target=$(readlink -f "$ARK_DIR/ark.py" 2>/dev/null)
if [ -n "$target" ] && [ "$target" = "$LAB/tools/ark.py" ]; then ok ark.py "$ARK_DIR/ark.py -> repo"
elif [ -n "$target" ] && [ -n "$MAIN" ] && [ "$target" = "$MAIN/tools/ark.py" ]; then ok ark.py "$ARK_DIR/ark.py -> main checkout (linked worktree)"
else bad ark.py "$ARK_DIR/ark.py is not the repo version (run CLAUDE_CODE_REMOTE=true ${MAIN:-$LAB}/.claude/hooks/session-start.sh)"; fi
# Session variables the skills rely on (the hook writes them to CLAUDE_ENV_FILE)
envcheck() {  # <check name> <variable> <test flag> <value to export when missing>
  local val=${!2:-}
  if [ -n "$val" ] && [ "$3" "$val" ]; then ok "$1" "$2=$val"; else warn "$1" "$2 unset or wrong; paste: export $2=\"$4\""; fi
}
envcheck env-film-lab FILM_LAB -d "${MAIN:-$LAB}"
envcheck env-formats CINECODE_FORMATS -d "${MAIN:-$LAB}/formats"
[ "$(id -u)" != "0" ] || envcheck env-chrome-path CHROME_PATH -x "${MAIN:-$LAB}/tools/compose/chrome-root.sh"

# Machine: Python version, free disk, which setup script the environment ran, and (full mode) a real headless Chrome
# launch through CHROME_PATH. FILM_SETUP_STAMP (default /opt/film-lab/setup-script.version) is for tests.
pyv=$(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null)
pmaj=${pyv%%.*}; pmin=${pyv#*.}; pmin=${pmin%%.*}
case "$pmaj.$pmin" in
  *[!0-9.]*|.*|*.) bad python "python3 not found or unreadable version '${pyv}'" ;;
  *) if [ "$pmaj" -gt 3 ] || { [ "$pmaj" = 3 ] && [ "$pmin" -ge 10 ]; }; then ok python "$pyv"
     else bad python "$pyv is too old: the tools need Python 3.10+"; fi ;;
esac
kb=$(df -Pk "$LAB" 2>/dev/null | awk 'NR == 2 {print $4}')
case "$kb" in
  ""|*[!0-9]*) warn disk "cannot read the free space of $LAB" ;;
  *) gb=$(awk -v k="$kb" 'BEGIN {printf "%.1f", k / 1048576}')
     if [ "$kb" -lt 5242880 ]; then warn disk "only $gb GB free for out/ (renders, clips): keep 5 GB or more"
     else ok disk "$gb GB free"; fi ;;
esac
want=$(sed -n -E 's/^SETUP_VERSION=([0-9]+).*/\1/p' "$LAB/docs/setup-script.sh" 2>/dev/null | head -1)
stamp="${FILM_SETUP_STAMP:-/opt/film-lab/setup-script.version}"
have=$( { tr -d '[:space:]' < "$stamp"; } 2>/dev/null )
if [ -z "$want" ]; then warn setup-script "docs/setup-script.sh has no SETUP_VERSION line"
elif [ -z "$have" ]; then warn setup-script "no stamp $stamp: the environment ran a setup script older than v$want (paste docs/setup-script.sh into the environment)"
elif [ "$have" != "$want" ]; then warn setup-script "the environment ran setup script v$have, the repo has v$want: paste docs/setup-script.sh into the environment"
else ok setup-script "v$want"; fi
if [ $QUICK = 0 ]; then
  if [ -z "${CHROME_PATH:-}" ]; then printf '  INFO  %-22s %s\n' chrome-launch "CHROME_PATH unset: headless launch not tried"
  elif [ ! -x "$CHROME_PATH" ]; then bad chrome-launch "CHROME_PATH=$CHROME_PATH is not an executable file"
  else
    cprof=$(mktemp -d)
    v=$(timeout 60 "$CHROME_PATH" --headless=new --disable-gpu --no-first-run --user-data-dir="$cprof" \
        --dump-dom 'data:text/html,<p>film-lab-chrome-ok</p>' 2>&1); crc=$?
    rm -rf "$cprof"
    case "$v" in
      *film-lab-chrome-ok*) ok chrome-launch "headless page rendered via $CHROME_PATH" ;;
      *) [ $crc = 124 ] && v="no page within 60 s"
         bad chrome-launch "headless launch failed (rc $crc): $(echo "$v" | grep -v '^[[:space:]]*$' | tail -1 | cut -c1-90)" ;;
    esac
  fi
fi

# Ark: one GET /models. Each model line is "id domain task_types status"; comment lines start with '#'.
unreachable() {  # one line for a network failure, whether ark.py exits cleanly or with a traceback
  local why
  why=$(echo "$1" | grep -v '^[[:space:]]' | tail -1 | sed -E -e 's/^network error: *//' -e 's/^[A-Za-z_.]+(Error|Exception): *//' | cut -c1-100)
  echo "Ark host unreachable: ${why:-no answer}"
}
ping_failure() {  # one line for a failed `ark.py ping`: no answer, an answer that is not a model list, or a bug
  local last why
  if echo "$1" | grep -q '^network error'; then unreachable "$1"; return; fi
  if ! echo "$1" | grep -q '^Traceback'; then echo "$1" | head -1 | cut -c1-120; return; fi   # e.g. HTTP 401: ...
  last=$(echo "$1" | grep -v '^[[:space:]]' | tail -1)
  why=$(echo "$last" | sed -E 's/^[A-Za-z_.]+(Error|Exception)?: *//' | cut -c1-80)
  case "$last" in
    *JSONDecodeError*|*"Expecting value"*) echo "Ark host answered, but not with JSON (proxy or error page?): $why" ;;
    *AttributeError*|*TypeError*|*KeyError*) echo "Ark host answered with JSON that is not a model list: $why" ;;
    *URLError*|*ConnectionError*|*ConnectionRefused*|*TimeoutError*|*OSError*|*socket*|*RemoteDisconnected*|*HTTPException*|*IncompleteRead*)
      unreachable "$1" ;;
    *) echo "ark.py ping crashed: $(echo "$last" | cut -c1-100)" ;;
  esac
}
out=$(timeout 20 python3 "$LAB/tools/ark.py" ping --all 2>&1); rc=$?
if [ $rc = 124 ]; then bad ark-ping "Ark host unreachable: no answer within 20 s"
elif [ $rc != 0 ]; then bad ark-ping "$(ping_failure "$out")"
else
  rows=$(echo "$out" | grep -v -e '^#' -e '^[[:space:]]*$')
  live=$(echo "$rows" | awk 'NF && $NF != "Shutdown"' | wc -l)
  defaults=$(sed -n -E 's/^(VIDEO_DEFAULT|IMAGE_FAST|LAMBDA_DEFAULT) *= *"([^"]+)".*/\2/p' "$LAB/tools/ark.py")
  dead=$(for m in $defaults; do echo "$rows" | awk -v m="$m" '$1 == m && $NF == "Shutdown" {print $1}'; done | sort -u | xargs)
  if [ -z "$rows" ]; then bad ark-ping "no model listed by /models (account without access?)"
  elif [ -n "$dead" ]; then bad ark-ping "default model listed as Shutdown: $dead (docs/MODELS.md, tools/ark.py)"
  elif [ "$live" = 0 ]; then bad ark-ping "no model in service: every listed model is Shutdown"
  else ok ark-ping "$live models visible"; fi
fi

if [ $QUICK = 0 ]; then
  # Video: one POST with an invalid resolution, which Ark rejects before it creates (and bills) a task.
  # Status: 0 = InvalidParameter (model activated), 4 = Ark accepted the task (prints its id), 5 = a 2xx answer that
  # is not a JSON object (a task may exist all the same), 1 = anything else.
  out=$(timeout 60 python3 - "$LAB/tools/ark.py" 2>&1 <<'PY'
import importlib.util, json, sys
m = "video model"
try:
    spec = importlib.util.spec_from_file_location("film_ark_doctor", sys.argv[1])
    ark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ark)
    m = ark.VIDEO_DEFAULT
    r = ark.call("POST", "/contents/generations/tasks",
                 {"model": m, "content": [{"type": "text", "text": "x"}], "duration": 5, "resolution": "9999p"})
    if isinstance(r, dict):
        print(r.get("id") or "(no id in the answer)"); code = 4
    else:
        print(f"JSON {type(r).__name__}, not an object"); code = 5
except json.JSONDecodeError as e:   # call() decodes only 2xx answers: Ark (or a proxy page) said yes in another format
    print(f"not JSON: {e.msg}"); code = 5
except SystemExit as e:
    s = " ".join(str(e).split())
    if "ModelNotOpen" in s: print(f"{m} not activated in Ark Console"); code = 1   # first: its text may name parameters
    elif "InvalidParameter" in s: print(f"{m} activated"); code = 0
    elif s.startswith("network error"): print("Ark host unreachable: " + s[len("network error"):].lstrip(": ")[:100]); code = 1
    else: print(f"{m}: {s[:100]}"); code = 1
except OSError as e:   # URLError, timeouts, refused connections
    print("Ark host unreachable: " + " ".join(str(getattr(e, "reason", e)).split())[:100]); code = 1
except Exception as e:
    print(f"probe failed: {type(e).__name__}: {' '.join(str(e).split())[:100]}"); code = 1
sys.exit(code)
PY
  ); rc=$?
  out=$(echo "$out" | tail -1 | cut -c1-160)
  case $rc in
    0) ok video-model "$out" ;;
    4) bad video-model "unexpected task $out created: it may be billed, cancel it in the Ark console" ;;
    5) bad video-model "Ark accepted the probe with an answer that is not a task object ($out): a task may exist and be billed, check the Ark console" ;;
    124) bad video-model "Ark host unreachable: no answer within 60 s" ;;
    *) bad video-model "${out:-probe failed (rc $rc)}" ;;
  esac
  printf '  INFO  %-22s %s\n' image-models "cannot be checked for free (validation runs before activation); see docs/MODELS.md"
  rf=$(curl -sS --max-time 5 "${HTTPS_PROXY:-http://127.0.0.1:0}/__agentproxy/status" 2>/dev/null | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('recentRelayFailures') or []))" 2>/dev/null)
  [ "$rf" = "0" ] && ok proxy "no recent relay failures" || warn proxy "relay failures: ${rf:-unknown} (curl \$HTTPS_PROXY/__agentproxy/status)"
fi
[ $fails = 0 ] && echo "Result: all checks passed" || echo "Result: $fails check(s) failed - see docs/RUNBOOK.md"
exit $fails
