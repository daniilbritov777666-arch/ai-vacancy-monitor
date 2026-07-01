#!/bin/zsh
set -euo pipefail

ROOT_DIR="${0:A:h:h}"
PROFILE_DIR="${MARKETPLACE_BROWSER_PROFILE_DIR:-$HOME/.codex/marketplace-browser-profile}"
CHROME="${MARKETPLACE_BROWSER_EXECUTABLE_PATH:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

cd "$ROOT_DIR"
python3 -m pip install -r requirements.txt
mkdir -p "$PROFILE_DIR"

"$CHROME" \
  --user-data-dir="$PROFILE_DIR" \
  --no-first-run \
  'https://www.fl.ru/login/' \
  'https://freelance.ru/login/' \
  'https://www.weblancer.net/account/login/'
