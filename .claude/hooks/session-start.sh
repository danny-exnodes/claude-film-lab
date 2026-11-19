#!/bin/bash
# SessionStart hook for AI Film Lab cloud sessions (synchronous).
# Links the repo's ark.py into /opt/byteplus, exports the session variables, installs what the
# environment setup script does not, and prints a quick doctor report.
# Cheap, critical steps run first so a failed install never leaves the session half set up. From the
# variables step on, every way out (a failed or timed-out install included) prints the doctor report
# and exits 0: the report is what tells the session what is broken.
# In a linked git worktree the shared ark.py link is left alone: it belongs to the main checkout.
# Overrides, for tests only: ARK_DIR (default /opt/byteplus), FILM_LAB_STAMP (default: in site-packages).
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"
LAB="$PWD"
ARK_DIR="${ARK_DIR:-/opt/byteplus}"

# 1. ark.py: keep the environment's original once, then point $ARK_DIR/ark.py at the repo. The link is
#    shared by every session in the container, so a linked worktree (work in progress) never moves it.
gitdir=$(git rev-parse --path-format=absolute --git-dir 2>/dev/null || true)
gitcommon=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)
if [ -n "$gitdir" ] && [ "$gitdir" != "$gitcommon" ]; then
  echo "film-lab: linked git worktree - $ARK_DIR/ark.py stays on the main checkout ($(dirname "$gitcommon"))"
else
  mkdir -p "$ARK_DIR"
  if [ -f "$ARK_DIR/ark.py" ] && [ ! -L "$ARK_DIR/ark.py" ] && [ ! -e "$ARK_DIR/ark.py.orig" ]; then
    cp -p "$ARK_DIR/ark.py" "$ARK_DIR/ark.py.orig"
  fi
  ln -sfn "$LAB/tools/ark.py" "$ARK_DIR/ark.py"
fi

# 2. Session variables. cinecode keeps saved formats in ~/.cinecode/formats, which dies with the
#    container: keep them in the repo (docs/CONVENTIONS.md §9). Chrome refuses to run as root without
#    --no-sandbox, and cinecode's capture.mjs only reads CHROME_PATH.
#    Exported here too, so the doctor this hook starts can check them.
mkdir -p "$LAB/formats"
export FILM_LAB="$LAB" CINECODE_FORMATS="$LAB/formats" FILM_THREE="${FILM_THREE:-/opt/film-lab/vendor/three/build/three.module.js}"
[ "$(id -u)" != "0" ] || export CHROME_PATH="$LAB/tools/compose/chrome-root.sh"
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export FILM_LAB=\"$FILM_LAB\"" >> "$CLAUDE_ENV_FILE"
  echo "export CINECODE_FORMATS=\"$CINECODE_FORMATS\"" >> "$CLAUDE_ENV_FILE"
  echo "export FILM_THREE=\"$FILM_THREE\"" >> "$CLAUDE_ENV_FILE"
  if [ "$(id -u)" = "0" ]; then
    echo "export CHROME_PATH=\"$CHROME_PATH\"" >> "$CLAUDE_ENV_FILE"
  fi
fi

# From here on the hook always ends with the doctor report and exit 0, whatever fails below.
report() {
  trap - EXIT
  "$LAB/tools/doctor.sh" --quick || true
  exit 0
}
trap report EXIT

# 3. apt packages: install only what is missing. grep reads the whole list (no -q): with pipefail,
#    `grep -q` closing the pipe early makes fc-list exit 141 and the test always "fails".
if ! fc-list : family 2>/dev/null | grep -i "Noto Serif CJK" >/dev/null; then
  { timeout 120 apt-get update -qq >/dev/null && timeout 300 apt-get install -y -qq fonts-noto-cjk >/dev/null; } \
    || echo "film-lab: fonts-noto-cjk install failed (doctor will report font-cjk FAIL)"
fi

# 4. pip into the system Python: rerun only when requirements change. The stamp is written only after a
#    successful install, so a failed one is retried at the next start.
pyhashes="${FILM_LAB_STAMP:-$(python3 -I -c 'import sysconfig; print(sysconfig.get_path("purelib"))')/.film-lab-session-start.sha256}"
if ! sha256sum --check --status "$pyhashes" 2>/dev/null; then
  rm -f "$pyhashes"
  rc=0
  timeout 600 python3 -m pip install -q --root-user-action=ignore -r requirements.txt >/dev/null || rc=$?
  if [ $rc = 0 ]; then
    sha256sum .claude/hooks/session-start.sh requirements.txt > "$pyhashes"
  else
    echo "film-lab: pip install failed (rc $rc) - doctor reports what is missing; the next session start retries (docs/RUNBOOK.md)"
  fi
fi

# 5. rembg model: optional prefetch (best effort, ~170 MB, cached with the container)
if [ ! -f /root/.rembg/models/u2net/u2net.onnx ] && [ ! -f ~/.u2net/u2net.onnx ]; then
  (cd /tmp && timeout 240 python3 -c "from rembg import new_session; new_session('u2net')" >/dev/null 2>&1) \
    || echo "film-lab: u2net prefetch failed; rembg will download it on first use"
fi

# 5b. three.js for the TOON 3D looks (method: code): pinned in tools/toon/three.lock, best effort
if [ "$FILM_THREE" = "/opt/film-lab/vendor/three/build/three.module.js" ] && ! "$LAB/tools/toon/install_three.sh" --check >/dev/null 2>&1; then
  timeout 150 "$LAB/tools/toon/install_three.sh" >/dev/null 2>&1 \
    || echo "film-lab: three.js install failed (doctor reports three; tools/toon/install_three.sh)"
fi

# 6. Project data lives on Google Drive (docs/CONVENTIONS.md §11), never in the repo: remind to pull it
if [ -z "$(ls -A "$LAB/projects" 2>/dev/null)" ]; then
  echo "film-lab: projects/ is empty - project data lives on Drive ClaudeFilmLab/<ProjectName>/; pull it first (film-pipeline §0, PROJECT.md first)"
fi

# 7. The doctor report: printed by the EXIT trap set after step 2.
