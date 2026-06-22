#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v brew >/dev/null 2>&1; then
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

if [[ -x /opt/homebrew/bin/brew ]]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

brew list colima >/dev/null 2>&1 && brew list docker >/dev/null 2>&1 || brew install colima docker

if ! colima status >/dev/null 2>&1; then
  colima start --cpu 2 --memory 4 --disk 10
fi

docker build \
  -t freelance-agent-python-runner:3.12-v1 \
  "$ROOT_DIR/docker/execution-python-runner"
docker image inspect node:22-slim >/dev/null 2>&1 || docker pull node:22-slim

docker image inspect freelance-agent-python-runner:3.12-v1 >/dev/null
docker image inspect node:22-slim >/dev/null
docker version
