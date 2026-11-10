#!/bin/bash
# SessionStart hook for AI Film Lab cloud sessions (synchronous).
# Links the repo's ark.py into /opt/byteplus, exports the session variables, installs what the
# environment setup script does not, and prints a quick doctor report.
# Cheap, critical steps run first so a failed install never leaves the session half set up.
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"
LAB="$PWD"

# 1. ark.py: keep the environment's original once, then point /opt/byteplus/ark.py at the repo
mkdir -p /opt/byteplus
if [ -f /opt/byteplus/ark.py ] && [ ! -L /opt/byteplus/ark.py ] && [ ! -e /opt/byteplus/ark.py.orig ]; then
  cp -p /opt/byteplus/ark.py /opt/byteplus/ark.py.orig
fi
ln -sfn "$LAB/tools/ark.py" /opt/byteplus/ark.py

# 2. Session variables. cinecode keeps saved formats in ~/.cinecode/formats, which dies with the
#    container: keep them in the repo (docs/CONVENTIONS.md §9). Chrome refuses to run as root without
#    --no-sandbox, and cinecode's capture.mjs only reads CHROME_PATH.
mkdir -p "$LAB/formats"
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export FILM_LAB=\"$LAB\"" >> "$CLAUDE_ENV_FILE"
  echo "export CINECODE_FORMATS=\"$LAB/formats\"" >> "$CLAUDE_ENV_FILE"
  if [ "$(id -u)" = "0" ]; then
    echo "export CHROME_PATH=\"$LAB/tools/compose/chrome-root.sh\"" >> "$CLAUDE_ENV_FILE"
  fi
fi

# 3. apt packages: install only what is missing. grep reads the whole list (no -q): with pipefail,
#    `grep -q` closing the pipe early makes fc-list exit 141 and the test always "fails".
if ! fc-list : family 2>/dev/null | grep -i "Noto Serif CJK" >/dev/null; then
  { apt-get update -qq >/dev/null && apt-get install -y -qq fonts-noto-cjk >/dev/null; } \
    || echo "film-lab: fonts-noto-cjk install failed (doctor will report font-cjk FAIL)"
fi

# 4. pip into the system Python: rerun only when requirements change
pyhashes="$(python3 -I -c 'import sysconfig; print(sysconfig.get_path("purelib"))')/.film-lab-session-start.sha256"
if ! sha256sum --check --status "$pyhashes" 2>/dev/null; then
  rm -f "$pyhashes"
  python3 -m pip install -q --root-user-action=ignore -r requirements.txt >/dev/null
  sha256sum .claude/hooks/session-start.sh requirements.txt > "$pyhashes"
fi

# 5. rembg model: optional prefetch (best effort, ~170 MB, cached with the container)
if [ ! -f /root/.rembg/models/u2net/u2net.onnx ] && [ ! -f ~/.u2net/u2net.onnx ]; then
  (cd /tmp && python3 -c "from rembg import new_session; new_session('u2net')" >/dev/null 2>&1) \
    || echo "film-lab: u2net prefetch failed; rembg will download it on first use"
fi

# 6. Project data lives on Google Drive (docs/CONVENTIONS.md §11), never in the repo: remind to pull it
if [ -z "$(ls -A "$LAB/projects" 2>/dev/null)" ]; then
  echo "film-lab: projects/ is empty - project data lives on Drive ClaudeFilmLab/<ProjectName>/; pull it first (film-pipeline §0, PROJECT.md first)"
fi

"$LAB/tools/doctor.sh" --quick || true
