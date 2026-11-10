#!/bin/bash
# AI Film Lab environment check. No image or video is generated.
#   tools/doctor.sh           full check
#   tools/doctor.sh --quick   local checks + Ark ping (used by the SessionStart hook)
#   tools/doctor.sh -h        this text
# Quick mode only reads: local tools, the ark.py link, GET /models.
# Full mode adds a real import of rembg, the agent proxy status and ONE request to the video endpoint:
# a POST with an invalid resolution ("9999p") that Ark rejects before it creates a task. Should Ark
# ever accept it, doctor FAILs and prints the task id so it can be cancelled in the Ark console.
# The exit code is the number of FAIL lines. Never prints or searches for API keys.
# ARK_DIR (default /opt/byteplus) is where the ark.py link lives; tests point it elsewhere.
set -u
LAB="$(cd "$(dirname "$0")/.." && pwd)"
ARK_DIR="${ARK_DIR:-/opt/byteplus}"
usage() { sed -n '2,/^set -u$/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'; }
QUICK=0
[ $# -le 1 ] || { usage >&2; exit 2; }
case "${1:-}" in
  "") ;;
  --quick) QUICK=1 ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac
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
# cinecode is pinned (tools/compose/cinecode.ref = CINECODE_REF in docs/setup-script.sh). A different HEAD is only a
# warning; what decides is the compose-kit check below, which runs inline.py on the template that is installed.
CINE=/root/.claude/skills/cinecode
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

# Ark: one GET /models. Each model line is "id domain task_types status"; comment lines start with '#'.
unreachable() {  # one line for a network failure, whether ark.py exits cleanly or with a traceback
  local why
  why=$(echo "$1" | grep -v '^[[:space:]]' | tail -1 | sed -E -e 's/^network error: *//' -e 's/^[A-Za-z_.]+(Error|Exception): *//' | cut -c1-100)
  echo "Ark host unreachable: ${why:-no answer}"
}
out=$(timeout 20 python3 "$LAB/tools/ark.py" ping --all 2>&1); rc=$?
if [ $rc = 124 ]; then bad ark-ping "Ark host unreachable: no answer within 20 s"
elif [ $rc != 0 ]; then
  if echo "$out" | grep -q -e 'Traceback' -e 'network error'; then bad ark-ping "$(unreachable "$out")"
  else bad ark-ping "$(echo "$out" | head -1 | cut -c1-120)"; fi
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
  # Status: 0 = InvalidParameter (model activated), 4 = Ark accepted the task (prints its id), 1 = anything else.
  out=$(timeout 60 python3 - "$LAB/tools/ark.py" 2>&1 <<'PY'
import importlib.util, sys
m = "video model"
try:
    spec = importlib.util.spec_from_file_location("film_ark_doctor", sys.argv[1])
    ark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ark)
    m = ark.VIDEO_DEFAULT
    r = ark.call("POST", "/contents/generations/tasks",
                 {"model": m, "content": [{"type": "text", "text": "x"}], "duration": 5, "resolution": "9999p"})
    print((r or {}).get("id") or "(no id in the answer)")
    code = 4
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
    124) bad video-model "Ark host unreachable: no answer within 60 s" ;;
    *) bad video-model "${out:-probe failed (rc $rc)}" ;;
  esac
  printf '  INFO  %-22s %s\n' image-models "cannot be checked for free (validation runs before activation); see docs/MODELS.md"
  rf=$(curl -sS --max-time 5 "${HTTPS_PROXY:-http://127.0.0.1:0}/__agentproxy/status" 2>/dev/null | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('recentRelayFailures') or []))" 2>/dev/null)
  [ "$rf" = "0" ] && ok proxy "no recent relay failures" || warn proxy "relay failures: ${rf:-unknown} (curl \$HTTPS_PROXY/__agentproxy/status)"
fi
[ $fails = 0 ] && echo "Result: all checks passed" || echo "Result: $fails check(s) failed - see docs/RUNBOOK.md"
exit $fails
