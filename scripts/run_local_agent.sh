#!/bin/zsh
set -u

PROJECT_DIR="${PROJECT_DIR:-/Users/daniilbritov/Documents/Даня_Vibe_Code}"
cd "$PROJECT_DIR" || exit 78

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"

if command -v limactl >/dev/null 2>&1; then
  if ! limactl list freelance-agent --format '{{.Status}}' 2>/dev/null | grep -q Running; then
    limactl start freelance-agent >/dev/null
  fi
  export DOCKER_HOST="unix://$HOME/.lima/freelance-agent/sock/docker.sock"
fi

export TELEGRAM_BOT_TOKEN="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.telegram-token -w 2>/dev/null || true)"
export OPENAI_API_KEY="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.openai-api-key -w 2>/dev/null || true)"
export FREELANCEHUNT_API_TOKEN="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.freelancehunt-token -w 2>/dev/null || true)"
export YOOKASSA_SHOP_ID="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.yookassa-shop-id -w 2>/dev/null || true)"
export YOOKASSA_SECRET_KEY="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.yookassa-secret-key -w 2>/dev/null || true)"
export PAYMENT_RETURN_URL="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.payment-return-url -w 2>/dev/null || true)"
export PAYMENT_INSTRUCTIONS_RU="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.payment-instructions-ru -w 2>/dev/null || true)"
export SMTP_HOST="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.smtp-host -w 2>/dev/null || true)"
export SMTP_USERNAME="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.smtp-username -w 2>/dev/null || true)"
export SMTP_PASSWORD="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.smtp-password -w 2>/dev/null || true)"
export SMTP_FROM="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.smtp-from -w 2>/dev/null || true)"
export GITHUB_EMAIL_BRIDGE_TOKEN="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.github-email-bridge-token -w 2>/dev/null || true)"
export IMAP_HOST="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.imap-host -w 2>/dev/null || true)"
export IMAP_USERNAME="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.imap-username -w 2>/dev/null || true)"
export IMAP_PASSWORD="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.imap-password -w 2>/dev/null || true)"
export IMAP_FOLDER="$(security find-generic-password -a vacancy-agent -s com.codex.vacancy-agent.imap-folder -w 2>/dev/null || true)"

exec /usr/bin/env PYTHONPATH=src /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m vacancy_monitor.local_agent_cli
