import subprocess

from vacancy_monitor.execution_verifier import (
    DockerExecutionVerifier,
    ProjectType,
    VerificationStatus,
    detect_project_type,
)


class FakeRunner:
    def __init__(self, results=None):
        self.calls = []
        self.results = list(results or [])

    def __call__(self, argv, *, timeout):
        self.calls.append((argv, timeout))
        if self.results:
            return self.results.pop(0)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


def test_detect_project_types(tmp_path):
    python_dir = tmp_path / "python"
    python_dir.mkdir()
    (python_dir / "app.py").write_text("print('ok')\n")
    js_dir = tmp_path / "js"
    js_dir.mkdir()
    (js_dir / "app.js").write_text("console.log('ok')\n")
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "result.md").write_text("ready\n")
    mixed_dir = tmp_path / "mixed"
    mixed_dir.mkdir()
    (mixed_dir / "app.py").write_text("print('ok')\n")
    (mixed_dir / "app.js").write_text("console.log('ok')\n")

    assert detect_project_type(python_dir) == ProjectType.PYTHON
    assert detect_project_type(js_dir) == ProjectType.JAVASCRIPT
    assert detect_project_type(static_dir) == ProjectType.STATIC
    assert detect_project_type(mixed_dir) == ProjectType.UNSUPPORTED


def test_symlink_is_rejected_before_runner(tmp_path):
    target = tmp_path / "outside.py"
    target.write_text("print('outside')\n")
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "link.py").symlink_to(target)
    runner = FakeRunner()

    report = DockerExecutionVerifier(runner=runner).verify(generated)

    assert report.status == VerificationStatus.UNSUPPORTED
    assert report.issues[0].code == "symlink_forbidden"
    assert runner.calls == []


def test_python_verifier_uses_hardened_readonly_container(tmp_path):
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "app.py").write_text("print('ok')\n")
    (generated / "test_app.py").write_text("def test_ok(): assert True\n")
    runner = FakeRunner()
    verifier = DockerExecutionVerifier(runner=runner, timeout_seconds=90)

    report = verifier.verify(generated)

    assert report.status == VerificationStatus.PASSED
    assert runner.calls[0][0] == ["docker", "image", "inspect", "freelance-agent-python-runner:3.12-v1"]
    run_argv = runner.calls[1][0]
    for expected in [
        "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--pids-limit", "64",
        "--cpus", "1.0", "--memory", "512m", "--memory-swap", "512m",
        "--user", "65534:65534",
    ]:
        assert expected in run_argv
    assert f"type=bind,src={generated.resolve()},dst=/workspace,readonly" in run_argv
    assert any("ast.parse" in item for item in run_argv)
    assert "PYTHONDONTWRITEBYTECODE=1" in run_argv
    assert any("pytest" in item for item in runner.calls[2][0])


def test_nonzero_command_fails_and_truncates_output(tmp_path):
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "app.js").write_text("broken(\n")
    runner = FakeRunner([
        subprocess.CompletedProcess([], 0, stdout="image", stderr=""),
        subprocess.CompletedProcess([], 1, stdout="x" * 100, stderr="syntax error"),
    ])

    report = DockerExecutionVerifier(runner=runner, max_output_bytes=20).verify(generated)

    assert report.status == VerificationStatus.FAILED
    assert report.issues[0].code == "command_failed"
    assert report.commands[-1].stdout == "x" * 20


def test_static_package_passes_without_runner(tmp_path):
    (tmp_path / "result.md").write_text("ready\n")
    runner = FakeRunner()

    report = DockerExecutionVerifier(runner=runner).verify(tmp_path)

    assert report.status == VerificationStatus.PASSED
    assert report.project_type == ProjectType.STATIC
    assert runner.calls == []
