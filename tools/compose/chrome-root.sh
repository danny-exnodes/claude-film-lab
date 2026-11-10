#!/bin/sh
# Chrome for cinecode's capture.mjs in a cloud container that runs as root: Chrome refuses root without
# --no-sandbox, and capture.mjs takes only CHROME_PATH (make.py passes no --flags). Use:
#   export CHROME_PATH=<repo>/tools/compose/chrome-root.sh      (the session hook can export it)
# CHROME_REAL overrides the browser (default: google-chrome, else Playwright's Chromium in /opt/pw-browsers).
real="${CHROME_REAL:-}"
if [ -z "$real" ]; then
  for c in /usr/bin/google-chrome /usr/bin/google-chrome-stable /usr/bin/chromium /opt/pw-browsers/chromium-*/chrome-linux64/chrome; do
    [ -x "$c" ] && real="$c" && break
  done
fi
[ -n "$real" ] || { echo "chrome-root.sh: no Chrome/Chromium found; set CHROME_REAL" >&2; exit 127; }
exec "$real" --no-sandbox "$@"
