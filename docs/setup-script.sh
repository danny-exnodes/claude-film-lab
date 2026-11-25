#!/bin/bash
# Setup script v3 for the "Film Lab" cloud environment: sequential, every step time-boxed, never fails.
# Paste into the environment's Setup script (claude.ai: cloud environment menu -> Edit).
# The repo danny-exnodes/claude-film-lab does the rest at session start (.claude/hooks/session-start.sh):
# links /opt/byteplus/ark.py to the repo's tools/ark.py, exports FILM_LAB, CINECODE_FORMATS, CHROME_PATH,
# re-checks fonts/pip and prints the doctor report. Keep the pip pins below equal to requirements.txt.
log() { echo "[setup $(date +%T)] $*"; }
export DEBIAN_FRONTEND=noninteractive PIP_ROOT_USER_ACTION=ignore
# A slow mirror should fail fast and retry instead of stalling a whole step
APT_OPTS=(-o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 -o Acquire::Retries=3 -o DPkg::Lock::Timeout=60)
CHROME_LIBS=(libnss3 libgbm1 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libxfixes3 libdrm2
  libpango-1.0-0 libcairo2 libasound2t64 libcups2t64 libatk1.0-0t64 libatk-bridge2.0-0t64)
ARK_DIR="${ARK_DIR:-/opt/byteplus}"

have() { dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q "install ok installed"; }
# apt_group <name> <timeout s> <packages...>: install only the missing ones, one group per apt run,
# so a slow or failing group (the CJK fonts are ~90 MB) no longer takes the others down with it.
apt_group() {
  local name=$1 t=$2; shift 2
  local missing=() p
  for p in "$@"; do have "$p" || missing+=("$p"); done
  if [ ${#missing[@]} -eq 0 ]; then log "$name: already installed"; return; fi
  timeout "$t" apt-get install -y -qq --no-install-recommends "${APT_OPTS[@]}" "${missing[@]}" \
    >"/tmp/setup-apt-$name.log" 2>&1 \
    && log "$name: ok (${missing[*]})" || log "$name: FAILED (see /tmp/setup-apt-$name.log; the session hook retries fonts)"
}

# 1. System packages (apt update only when something is missing: it alone can take ~2 min on a slow mirror)
need_apt=0
for p in "${CHROME_LIBS[@]}" ffmpeg fonts-noto-cjk fonts-noto-core; do have "$p" || need_apt=1; done
if [ $need_apt = 1 ]; then
  timeout 300 apt-get update -qq "${APT_OPTS[@]}" >/tmp/setup-apt-update.log 2>&1 && log "apt update ok" || log "apt update slow/failed"
  apt_group chrome-libs 300 "${CHROME_LIBS[@]}"
  apt_group ffmpeg 420 ffmpeg
  apt_group fonts-cjk 600 fonts-noto-cjk
  apt_group fonts-core 420 fonts-noto-core
else
  log "apt: all packages already installed"
fi

# 2. Chrome for Testing, linked where cinecode looks for it (skipped when it already runs)
if google-chrome --version >/dev/null 2>&1; then
  log "chrome: already installed ($(google-chrome --version 2>/dev/null))"
else
  ( cd /opt && timeout 180 npx -y @puppeteer/browsers install chrome@stable --path /opt/cft >/tmp/setup-chrome.log 2>&1 \
    && ln -sf "$(ls -d /opt/cft/chrome/linux-*/chrome-linux64/chrome | head -1)" /usr/bin/google-chrome \
    && log "chrome: ok" ) || log "chrome: FAILED (see /tmp/setup-chrome.log)"
fi

# 3. Python packages (pins = requirements.txt of the repo, so the session hook has nothing left to install)
timeout 120 python3 -m pip install -q --break-system-packages pillow numpy "PyYAML==6.0.3" >/tmp/setup-pip.log 2>&1 \
  && log "python base: ok" || log "python base: FAILED (see /tmp/setup-pip.log)"
timeout 420 python3 -m pip install -q --break-system-packages "rembg[cpu]==2.0.87" >>/tmp/setup-pip.log 2>&1 \
  && log "rembg: ok" || log "rembg: FAILED (the session hook installs it from requirements.txt)"
# rembg's u2net model (~170 MB), so the first background removal does not stall a session
if [ -f /root/.rembg/models/u2net/u2net.onnx ] || [ -f /root/.u2net/u2net.onnx ]; then
  log "u2net: already cached"
else
  ( cd /tmp && timeout 240 python3 -c "from rembg import new_session; new_session('u2net')" >/tmp/setup-u2net.log 2>&1 ) \
    && log "u2net: ok" || log "u2net: FAILED (downloads on first use)"
fi

# 4. The cinecode skill, pinned to the commit the repo's tools/compose/inline.py is tested against
#    (tools/compose/cinecode.ref holds the same id; tests/test_compose.py fails when the two differ).
#    Never `git pull`: a template change upstream would only show up in the middle of composing a shot.
#    To move the pin: docs/RUNBOOK.md, "cinecode đổi template".
CINECODE_REF="${CINECODE_REF:-67f9807112b97ae253d4a5f0eccaccc46c3b2633}"
CINE=/root/.claude/skills/cinecode
if [ "$(git -C "$CINE" rev-parse HEAD 2>/dev/null)" = "$CINECODE_REF" ]; then
  log "cinecode: already at ${CINECODE_REF:0:7}"
else
  if [ ! -d "$CINE/.git" ]; then
    mkdir -p "$CINE" && git -C "$CINE" init -q && git -C "$CINE" remote add origin https://github.com/sarpstar/cinecode
  fi
  if timeout 90 git -C "$CINE" fetch -q --depth 1 origin "$CINECODE_REF" 2>/tmp/setup-cinecode.log \
     && git -C "$CINE" checkout -q -f --detach FETCH_HEAD 2>>/tmp/setup-cinecode.log; then
    log "cinecode: ok (pinned ${CINECODE_REF:0:7})"
  elif [ -f "$CINE/SKILL.md" ]; then
    log "cinecode: pin fetch FAILED, kept $(git -C "$CINE" rev-parse --short HEAD 2>/dev/null) (doctor warns; see /tmp/setup-cinecode.log)"
  else
    # Last resort so the skill exists at all: upstream HEAD, unpinned. doctor.sh then warns and tests inline.py on it.
    rm -rf "$CINE"
    timeout 90 git clone -q --depth 1 https://github.com/sarpstar/cinecode "$CINE" 2>>/tmp/setup-cinecode.log \
      && log "cinecode: UNPINNED upstream HEAD (pin fetch failed; doctor warns)" || log "cinecode: FAILED"
  fi
fi

# 5. BytePlus ModelArk client. The real client is the repo's tools/ark.py (models, budget and ledger rules);
#    this shim only finds it, so the environment never carries a second, drifting copy. The session hook
#    replaces the shim with a symlink. The key is attached by the network secret, never stored here.
mkdir -p "$ARK_DIR"
rm -f "$ARK_DIR/ark.py"   # it may be a symlink into a repo from an earlier session: never write through it
cat > "$ARK_DIR/ark.py" <<'PY'
#!/usr/bin/env python3
"""Shim for BytePlus ModelArk: runs tools/ark.py of the claude-film-lab repo (see its CLAUDE.md).

The Ark key is never read here: the cloud environment's network secret is attached by the agent proxy.
"""
import glob, os, sys

here = os.path.realpath(__file__)
cands = [os.path.join(os.environ.get("FILM_LAB", ""), "tools", "ark.py"),
         "/home/user/claude-film-lab/tools/ark.py"] + sorted(glob.glob("/home/user/*/tools/ark.py"))
for c in cands:
    lab = os.path.dirname(os.path.dirname(c))
    if os.path.isfile(c) and os.path.realpath(c) != here and os.path.isfile(os.path.join(lab, "tools", "doctor.sh")):
        os.execv(sys.executable, [sys.executable, c] + sys.argv[1:])
sys.exit("ark.py: the claude-film-lab repo is not in this session. Start the session with the repo "
         "danny-exnodes/claude-film-lab selected (its tools/ark.py holds the models, budget and ledger rules).")
PY
chmod +x "$ARK_DIR/ark.py"
log "ark.py shim: ok"

# 6. three.js for the TOON 3D looks of method: code (tools/toon/look3d.js), pinned and verified against the
#    repo's tools/toon/three.lock when the repo is there (the session hook re-runs it). Same version as cinecode's
#    starter. Renders never load three.js from a CDN.
THREE_VER="${THREE_VER:-0.186.1}"
THREE_DIR=/opt/film-lab/vendor/three
if [ -f "$THREE_DIR/build/three.module.js" ] && grep -q "\"version\": \"$THREE_VER\"" "$THREE_DIR/package.json" 2>/dev/null; then
  log "three.js: already $THREE_VER"
else
  tmp3=$(mktemp -d)
  if ( cd "$tmp3" && timeout 120 npm pack "three@$THREE_VER" --silent >/tmp/setup-three.log 2>&1 ) \
     && mkdir -p "$THREE_DIR.new" && tar xzf "$tmp3/three-$THREE_VER.tgz" -C "$THREE_DIR.new" --strip-components=1; then
    rm -rf "$THREE_DIR" && mv "$THREE_DIR.new" "$THREE_DIR" && log "three.js: ok ($THREE_VER)"
  else
    rm -rf "$THREE_DIR.new"; log "three.js: FAILED (see /tmp/setup-three.log; the session hook retries)"
  fi
  rm -rf "$tmp3"
fi

log "done"
exit 0
