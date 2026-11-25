#!/bin/bash
# Install the pinned three.js (tools/toon/three.lock) for the TOON 3D looks, and verify it. Free; needs the npm registry.
#   tools/toon/install_three.sh            install when missing or wrong, then verify (exit 0 = ready)
#   tools/toon/install_three.sh --check    verify only (exit 1 = missing or hash mismatch)
# Target: $FILM_THREE_DIR (default /opt/film-lab/vendor/three). Renders never load three.js from a CDN.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
LOCK="$HERE/three.lock"
DIR="${FILM_THREE_DIR:-/opt/film-lab/vendor/three}"
[ -f "$LOCK" ] && grep -q '^sha256 ' "$LOCK" || { echo "three: $LOCK missing or has no sha256 line"; exit 1; }
VER=$(awk '$1 == "version" {print $2}' "$LOCK")
verify() {
  local ok=0 f want have
  while read -r _ f want; do
    have=$(sha256sum "$DIR/$f" 2>/dev/null | awk '{print $1}')
    if [ -z "$have" ]; then echo "three: $DIR/$f missing"; ok=1
    elif [ "$have" != "$want" ]; then echo "three: $DIR/$f hash differs from tools/toon/three.lock"; ok=1; fi
  done < <(awk '$1 == "sha256"' "$LOCK")
  return $ok
}
if [ "${1:-}" = "--check" ]; then verify && echo "three: $VER ok ($DIR)"; exit $?; fi
if verify >/dev/null; then echo "three: $VER already installed ($DIR)"; exit 0; fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
( cd "$tmp" && timeout 120 npm pack "three@$VER" --silent >/dev/null 2>"$tmp/npm.log" ) \
  || { echo "three: npm pack three@$VER failed: $(tail -1 "$tmp/npm.log")"; exit 1; }
mkdir -p "$DIR.new" && tar xzf "$tmp/three-$VER.tgz" -C "$DIR.new" --strip-components=1 \
  || { echo "three: cannot unpack"; rm -rf "$DIR.new"; exit 1; }
rm -rf "$DIR" && mv "$DIR.new" "$DIR"
verify && echo "three: $VER installed ($DIR)"
