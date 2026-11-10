#!/bin/bash
# AI Film Lab environment check. Free checks only (no image/video is generated).
#   tools/doctor.sh           full check
#   tools/doctor.sh --quick   local checks + Ark ping (used by the SessionStart hook)
# Never prints or searches for API keys.
set -u
LAB="$(cd "$(dirname "$0")/.." && pwd)"
QUICK=0; [ "${1:-}" = "--quick" ] && QUICK=1
fails=0
ok()   { printf '  OK    %-22s %s\n' "$1" "$2"; }
bad()  { printf '  FAIL  %-22s %s\n' "$1" "$2"; fails=$((fails+1)); }
warn() { printf '  WARN  %-22s %s\n' "$1" "$2"; }

echo "AI Film Lab doctor ($( [ $QUICK = 1 ] && echo quick || echo full ))"
v=$(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}'); [ -n "$v" ] && ok ffmpeg "$v" || bad ffmpeg "not installed"
v=$(google-chrome --version 2>/dev/null); [ -n "$v" ] && ok chrome "$v" || bad chrome "google-chrome not found"
n=$(fc-list 2>/dev/null | grep -ci "Noto Serif CJK"); [ "$n" -gt 0 ] && ok font-cjk "Noto Serif CJK x$n" || bad font-cjk "missing: apt-get install -y fonts-noto-cjk"
v=$(python3 -c "import importlib.metadata as m, importlib.util as u; assert u.find_spec('rembg'); print(m.version('rembg'))" 2>/dev/null) && ok rembg "$v" || bad rembg "missing: python3 -m pip install -r requirements.txt"
v=$(python3 -c "import yaml; print(yaml.__version__)" 2>/dev/null) && ok pyyaml "$v" || bad pyyaml "missing: python3 -m pip install -r requirements.txt"
{ [ -f /root/.rembg/models/u2net/u2net.onnx ] || [ -f ~/.u2net/u2net.onnx ]; } && ok rembg-model "u2net cached" || warn rembg-model "u2net not cached (downloads on first use)"
[ -f /root/.claude/skills/cinecode/SKILL.md ] && ok skill-cinecode "present" || bad skill-cinecode "/root/.claude/skills/cinecode/SKILL.md missing"
if [ "$(readlink -f /opt/byteplus/ark.py 2>/dev/null)" = "$LAB/tools/ark.py" ]; then ok ark.py "/opt/byteplus/ark.py -> repo"; else bad ark.py "/opt/byteplus/ark.py is not the repo version (run .claude/hooks/session-start.sh)"; fi

out=$(python3 "$LAB/tools/ark.py" ping 2>&1); rc=$?
if [ $rc = 0 ]; then ok ark-ping "$(echo "$out" | grep -c -v '^#') models visible"; else bad ark-ping "$(echo "$out" | head -1 | cut -c1-120)"; fi

if [ $QUICK = 0 ]; then
  # Video: an invalid resolution is rejected before billing; ModelNotOpen means not activated.
  python3 - "$LAB/tools/ark.py" <<'PY'
import sys
src = open(sys.argv[1]).read().split('\np = argparse.ArgumentParser(')[0]
g = {'__name__': 'ark'}; exec(src, g)
for m in [g['VIDEO_DEFAULT']]:
    try:
        g['call']("POST", "/contents/generations/tasks", {"model": m, "content": [{"type": "text", "text": "x"}], "duration": 5, "resolution": "9999p"})
        print(f"  WARN  {'video-model':22} {m}: unexpected task created")
    except SystemExit as e:
        s = str(e)
        if "ModelNotOpen" in s: print(f"  FAIL  {'video-model':22} {m} not activated in Ark Console")
        elif "InvalidParameter" in s: print(f"  OK    {'video-model':22} {m} activated")
        else: print(f"  WARN  {'video-model':22} {m}: {s[:100]}")
print(f"  INFO  {'image-models':22} cannot be checked for free (validation runs before activation); see docs/MODELS.md")
PY
  rf=$(curl -sS --max-time 5 "${HTTPS_PROXY:-http://127.0.0.1:0}/__agentproxy/status" 2>/dev/null | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('recentRelayFailures') or []))" 2>/dev/null)
  [ "$rf" = "0" ] && ok proxy "no recent relay failures" || warn proxy "relay failures: ${rf:-unknown} (curl \$HTTPS_PROXY/__agentproxy/status)"
fi
[ $fails = 0 ] && echo "Result: all checks passed" || echo "Result: $fails check(s) failed - see docs/RUNBOOK.md"
exit $fails
