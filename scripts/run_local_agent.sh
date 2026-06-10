#!/bin/zsh
set -u

PROJECT_DIR="${PROJECT_DIR:-/Users/daniilbritov/Documents/Даня_Vibe_Code}"
cd "$PROJECT_DIR" || exit 78

export TELEGRAM_BOT_TOKEN="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.telegram-token -w 2>/dev/null || true)"
export OPENAI_API_KEY="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.openai-api-key -w 2>/dev/null || true)"
export FREELANCEHUNT_API_TOKEN="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.freelancehunt-token -w 2>/dev/null || true)"
export YOOKASSA_SHOP_ID="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.yookassa-shop-id -w 2>/dev/null || true)"
export YOOKASSA_SECRET_KEY="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.yookassa-secret-key -w 2>/dev/null || true)"

exec /usr/bin/env PYTHONPATH=src /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m vacancy_monitor.local_agent_cli
