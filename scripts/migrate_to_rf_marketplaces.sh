#!/bin/zsh
set -eu

PLIST="${1:-$HOME/Library/LaunchAgents/com.codex.vacancy-agent.plist}"
PLIST_BUDDY="/usr/libexec/PlistBuddy"

if [[ ! -f "$PLIST" ]]; then
  print -u2 "LaunchAgent plist not found: $PLIST"
  exit 1
fi

set_env() {
  local key="$1"
  local value="$2"
  if ! "$PLIST_BUDDY" -c "Set :EnvironmentVariables:$key $value" "$PLIST" 2>/dev/null; then
    "$PLIST_BUDDY" -c "Add :EnvironmentVariables:$key string $value" "$PLIST"
  fi
}

set_env RSS_FEEDS "https://www.fl.ru/rss/projects.xml"
set_env PUBLIC_PROJECT_SOURCES "freelance_ru,pchel,weblancer"
set_env MARKETPLACE_BROWSER_ENABLED "true"
set_env MARKETPLACE_BROWSER_LIVE_SUBMIT "false"
set_env MARKETPLACE_BROWSER_PROFILE_DIR "$HOME/.codex/marketplace-browser-profile"
set_env MARKETPLACE_BROWSER_HEADLESS "false"
set_env PUBLIC_SOURCE_PROBES "kwork,workzilla"
set_env FREELANCEHUNT_API_SOURCE_ENABLED "false"
set_env FREELANCEHUNT_BID_API_ENABLED "false"

plutil -lint "$PLIST"
print "RF marketplace configuration applied: $PLIST"
print "Restart: launchctl kickstart -k gui/$(id -u)/com.codex.vacancy-agent"
