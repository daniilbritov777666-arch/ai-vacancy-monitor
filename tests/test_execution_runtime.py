import json
import subprocess
from datetime import UTC, datetime

from vacancy_monitor.execution_runtime import write_execution_runtime_health


class FakeRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, *, timeout):
        self.calls.append(argv)
        if argv[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(argv, 0, stdout="27.5.1|27.5.1", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")


def test_runtime_health_reports_versions_and_images(tmp_path):
    path = tmp_path / "execution_runtime_health.json"
    runner = FakeRunner()

    report = write_execution_runtime_health(
        path=path,
        python_image="python-runner:test",
        node_image="node:test",
        runner=runner,
        now=datetime(2026, 6, 22, 20, 0, tzinfo=UTC),
    )

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert report["available"] is True
    assert stored["client_version"] == "27.5.1"
    assert stored["server_version"] == "27.5.1"
    assert stored["images"] == {"python-runner:test": True, "node:test": True}
    assert "environment" not in stored
