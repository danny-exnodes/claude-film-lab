#!/bin/bash
# AI Film Lab CI: the free checks, the same on a laptop, in a cloud session and on GitHub Actions.
#   tools/ci.sh                          run every step
#   tools/ci.sh --install                pip install requirements-ci.txt first (a fresh CI runner)
#   tools/ci.sh [--install] -- ARGS...   unit tests ARGS instead of the whole suite, e.g. -- test_ark test_docs -v
#   tools/ci.sh -h                       this text
# Steps: python >= 3.10, `bash -n` on every shell script, the compose kit lint, the unit tests.
# Nothing is paid or sent anywhere: ARK_BASE points at a closed local port (tests/helpers.py does the same).
# Tests that need Chrome, Playwright, rembg, cinecode, VieNeu or torch skip when those are missing.
# Exit code: 0 every step passed, 1 a step failed, 2 usage error.
set -u
LAB="$(cd "$(dirname "$0")/.." && pwd)"
usage() { sed -n '2,/^set -u$/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'; }
INSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --install) INSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    --) shift; break ;;
    *) usage >&2; exit 2 ;;
  esac
done
export ARK_BASE="http://127.0.0.1:9/never-call-the-real-api" LANG="${LANG:-C.UTF-8}" PYTHONDONTWRITEBYTECODE=1
unset ARK_API_KEY
cd "$LAB" || exit 1
step() { echo "ci: $*"; }
fail() { echo "ci: FAILED: $*" >&2; exit 1; }

pyv=$(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null) || fail "python3 not found"
maj=${pyv%%.*}; rest=${pyv#*.}; min=${rest%%.*}
{ [ "$maj" -gt 3 ] || { [ "$maj" = 3 ] && [ "$min" -ge 10 ]; }; } || fail "python $pyv is too old (3.10+ needed)"
step "python $pyv"

if [ $INSTALL = 1 ]; then
  python3 -m pip install -q -r requirements-ci.txt || fail "pip install -r requirements-ci.txt"
  step "installed requirements-ci.txt"
fi

scripts=$(git ls-files '*.sh' 2>/dev/null)
[ -n "$scripts" ] || scripts=$(find . -name '*.sh' -not -path './out/*' -not -path './projects/*' | sed 's#^\./##' | sort)
bad=""
for s in $scripts; do bash -n "$s" 2>&1 || bad="$bad $s"; done
[ -z "$bad" ] || fail "bash -n:$bad"
step "bash -n ok ($(echo "$scripts" | wc -w) scripts)"

out=$(python3 tools/compose/inline.py --lint 2>&1) || fail "compose kit lint: $(echo "$out" | head -3)"
step "$out"

if [ $# -gt 0 ]; then
  (cd tests && python3 -m unittest "$@") || fail "unit tests"
else
  python3 -m unittest discover -s tests || fail "unit tests"
fi
step "all steps passed"
