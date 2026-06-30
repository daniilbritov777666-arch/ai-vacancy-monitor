#!/bin/zsh
set -eu

PROFILE_DIR="${FREELANCEHUNT_BROWSER_PROFILE_DIR:-$HOME/.codex/freelancehunt-browser-profile}"
CHROME_BIN="${FREELANCEHUNT_BROWSER_EXECUTABLE_PATH:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
LOGIN_URL="https://freelancehunt.com/profile/login"

if [[ ! -x "$CHROME_BIN" ]]; then
  echo "Google Chrome not found: $CHROME_BIN" >&2
  exit 1
fi

mkdir -p "$PROFILE_DIR"
exec "$CHROME_BIN" \
  --user-data-dir="$PROFILE_DIR" \
  --no-first-run \
  --no-default-browser-check \
  "$LOGIN_URL"
