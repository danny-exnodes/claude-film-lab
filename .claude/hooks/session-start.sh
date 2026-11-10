#!/bin/bash
# SessionStart hook for AI Film Lab cloud sessions (synchronous).
# Installs what the environment setup script does not, links the repo's ark.py
# into /opt/byteplus and prints a quick doctor report.
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"
LAB="$PWD"

# apt packages: install only what is missing
if ! fc-list 2>/dev/null | grep -qi "Noto Serif CJK"; then
  apt-get update -qq >/dev/null
  apt-get install -y -qq fonts-noto-cjk >/dev/null
fi

# pip into the system Python: rerun only when requirements change
pyhashes="$(python3 -I -c 'import sysconfig; print(sysconfig.get_path("purelib"))')/.film-lab-session-start.sha256"
if ! sha256sum --check --status "$pyhashes" 2>/dev/null; then
  rm -f "$pyhashes"
  python3 -m pip install -q --root-user-action=ignore -r requirements.txt >/dev/null
  sha256sum .claude/hooks/session-start.sh requirements.txt > "$pyhashes"
fi

# rembg model: optional prefetch (best effort, ~170 MB, cached with the container)
if [ ! -f /root/.rembg/models/u2net/u2net.onnx ] && [ ! -f ~/.u2net/u2net.onnx ]; then
  (cd /tmp && python3 -c "from rembg import new_session; new_session('u2net')" >/dev/null 2>&1) \
    || echo "film-lab: u2net prefetch failed; rembg will download it on first use"
fi

# ark.py: keep the environment's original once, then point /opt/byteplus/ark.py at the repo
mkdir -p /opt/byteplus
if [ -f /opt/byteplus/ark.py ] && [ ! -L /opt/byteplus/ark.py ] && [ ! -e /opt/byteplus/ark.py.orig ]; then
  cp -p /opt/byteplus/ark.py /opt/byteplus/ark.py.orig
fi
ln -sfn "$LAB/tools/ark.py" /opt/byteplus/ark.py

# cinecode keeps saved formats in ~/.cinecode/formats, which dies with the container:
# keep them in the repo instead (docs/CONVENTIONS.md §9)
mkdir -p "$LAB/formats"
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export FILM_LAB=\"$LAB\"" >> "$CLAUDE_ENV_FILE"
  echo "export CINECODE_FORMATS=\"$LAB/formats\"" >> "$CLAUDE_ENV_FILE"
fi

"$LAB/tools/doctor.sh" --quick || true
