from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_setup_script_has_safe_idempotent_contract():
    text = (ROOT / "scripts" / "setup_execution_runtime.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert "command -v brew" in text
    assert "brew install colima docker" in text
    assert "colima start" in text
    assert "--cpu 2" in text
    assert "--memory 4" in text
    assert "--disk 10" in text
    assert "docker build" in text
    assert "docker pull node:22-slim" in text
    assert "docker image inspect" in text
    assert "docker system prune" not in text
    assert "--privileged" not in text


def test_python_runner_pins_pytest_and_uses_unprivileged_user():
    dockerfile = (ROOT / "docker" / "execution-python-runner" / "Dockerfile").read_text(encoding="utf-8")
    requirements = (ROOT / "docker" / "execution-python-runner" / "requirements.txt").read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in dockerfile
    assert "USER 65534:65534" in dockerfile
    assert "pytest==" in requirements


def test_launch_agent_runner_exposes_homebrew_tools():
    text = (ROOT / "scripts" / "run_local_agent.sh").read_text(encoding="utf-8")
    assert 'export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"' in text
