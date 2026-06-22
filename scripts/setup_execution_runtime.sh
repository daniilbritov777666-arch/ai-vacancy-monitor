#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIMA_VERSION="2.1.3"
DOCKER_VERSION="29.6.0"
LOCAL_BIN="$HOME/.local/bin"
LIMA_PREFIX="$HOME/.local/lima"

mkdir -p "$LOCAL_BIN"
export PATH="$LOCAL_BIN:/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"

if command -v brew >/dev/null 2>&1; then
  brew list colima >/dev/null 2>&1 && brew list docker >/dev/null 2>&1 || brew install colima docker

  if ! colima status >/dev/null 2>&1; then
    colima start --cpu 2 --memory 4 --disk 10
  fi
else
  if ! command -v limactl >/dev/null 2>&1; then
    mkdir -p "$LIMA_PREFIX"
    curl -fL --retry 3 \
      "https://github.com/lima-vm/lima/releases/download/v${LIMA_VERSION}/lima-${LIMA_VERSION}-Darwin-arm64.tar.gz" \
      -o /tmp/freelance-agent-lima.tar.gz
    tar -xzf /tmp/freelance-agent-lima.tar.gz -C "$LIMA_PREFIX"
    ln -sf "$LIMA_PREFIX/bin/limactl" "$LOCAL_BIN/limactl"
  fi

  if ! command -v docker >/dev/null 2>&1; then
    mkdir -p /tmp/freelance-agent-docker
    curl -fL --retry 3 \
      "https://download.docker.com/mac/static/stable/aarch64/docker-${DOCKER_VERSION}.tgz" \
      -o /tmp/freelance-agent-docker.tgz
    tar -xzf /tmp/freelance-agent-docker.tgz -C /tmp/freelance-agent-docker
    install -m 755 /tmp/freelance-agent-docker/docker/docker "$LOCAL_BIN/docker"
  fi

  if [[ -f "$HOME/.lima/freelance-agent/lima.yaml" ]]; then
    limactl start freelance-agent >/dev/null
  else
    limactl start --name=freelance-agent --vm-type=vz --cpus=2 --memory=4 --disk=10 \
      --tty=false --timeout=15m template:docker
  fi
  export DOCKER_HOST="unix://$HOME/.lima/freelance-agent/sock/docker.sock"
fi

docker build \
  -t freelance-agent-python-runner:3.12-v1 \
  "$ROOT_DIR/docker/execution-python-runner"
docker image inspect node:22-slim >/dev/null 2>&1 || docker pull node:22-slim

docker image inspect freelance-agent-python-runner:3.12-v1 >/dev/null
docker image inspect node:22-slim >/dev/null
docker version
