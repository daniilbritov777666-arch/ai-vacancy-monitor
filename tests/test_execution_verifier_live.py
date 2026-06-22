import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from vacancy_monitor.execution_verifier import DockerExecutionVerifier, VerificationStatus


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_CONTAINER_TESTS") != "1",
    reason="requires the local isolated container runtime",
)


@pytest.fixture
def workspace_tmp_path():
    with TemporaryDirectory(dir=Path.cwd()) as directory:
        yield Path(directory)


def test_live_verifier_accepts_valid_python_package(workspace_tmp_path):
    (workspace_tmp_path / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (workspace_tmp_path / "test_app.py").write_text(
        "from app import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )

    report = DockerExecutionVerifier(timeout_seconds=30).verify(workspace_tmp_path)

    assert report.status == VerificationStatus.PASSED


def test_live_verifier_rejects_invalid_python(workspace_tmp_path):
    (workspace_tmp_path / "app.py").write_text("def broken(:\n    pass\n", encoding="utf-8")

    report = DockerExecutionVerifier(timeout_seconds=30).verify(workspace_tmp_path)

    assert report.status == VerificationStatus.FAILED
    assert report.commands[0].name == "python_ast"


def test_live_verifier_blocks_network_and_workspace_writes(workspace_tmp_path):
    (workspace_tmp_path / "test_sandbox.py").write_text(
        "from pathlib import Path\n"
        "import socket\n\n"
        "def test_network_is_blocked():\n"
        "    with socket.socket() as sock:\n"
        "        sock.settimeout(1)\n"
        "        with __import__('pytest').raises(OSError):\n"
        "            sock.connect(('1.1.1.1', 53))\n\n"
        "def test_workspace_is_read_only():\n"
        "    with __import__('pytest').raises(OSError):\n"
        "        Path('/workspace/forbidden.txt').write_text('no')\n",
        encoding="utf-8",
    )

    report = DockerExecutionVerifier(timeout_seconds=30).verify(workspace_tmp_path)

    assert report.status == VerificationStatus.PASSED


def test_live_verifier_stops_timed_out_tests(workspace_tmp_path):
    (workspace_tmp_path / "test_timeout.py").write_text(
        "def test_never_finishes():\n    while True:\n        pass\n",
        encoding="utf-8",
    )

    report = DockerExecutionVerifier(timeout_seconds=2).verify(workspace_tmp_path)

    assert report.status == VerificationStatus.FAILED
    assert report.issues[0].code == "execution_timeout"
