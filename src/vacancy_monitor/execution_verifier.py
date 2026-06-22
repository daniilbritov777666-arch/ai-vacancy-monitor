from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from time import monotonic
from typing import Callable


class VerificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"


class ProjectType(StrEnum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    STATIC = "static"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class VerificationIssue:
    code: str
    message: str


@dataclass(frozen=True)
class CommandResult:
    name: str
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ExecutionVerificationReport:
    status: VerificationStatus
    project_type: ProjectType
    commands: tuple[CommandResult, ...]
    issues: tuple[VerificationIssue, ...]
    started_at: str
    finished_at: str
    duration_seconds: float
    runtime: dict

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "project_type": self.project_type.value,
            "commands": [asdict(command) for command in self.commands],
            "issues": [asdict(issue) for issue in self.issues],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "runtime": self.runtime,
        }


Runner = Callable[..., subprocess.CompletedProcess]


def detect_project_type(generated_dir: Path) -> ProjectType:
    files = [path for path in generated_dir.rglob("*") if path.is_file()]
    has_python = any(path.suffix.lower() == ".py" or path.name in {"pyproject.toml", "setup.py", "requirements.txt"} for path in files)
    has_javascript = any(path.suffix.lower() in {".js", ".mjs", ".cjs"} or path.name == "package.json" for path in files)
    if has_python and has_javascript:
        return ProjectType.UNSUPPORTED
    if has_python:
        return ProjectType.PYTHON
    if has_javascript:
        return ProjectType.JAVASCRIPT
    return ProjectType.STATIC


class DockerExecutionVerifier:
    def __init__(
        self,
        *,
        python_image: str = "freelance-agent-python-runner:3.12-v1",
        node_image: str = "node:22-slim",
        timeout_seconds: int = 120,
        memory_mb: int = 512,
        cpus: float = 1.0,
        max_output_bytes: int = 65536,
        runner: Runner = subprocess.run,
    ) -> None:
        self.python_image = python_image
        self.node_image = node_image
        self.timeout_seconds = timeout_seconds
        self.memory_mb = memory_mb
        self.cpus = cpus
        self.max_output_bytes = max_output_bytes
        self.runner = runner

    def verify(self, generated_dir: Path) -> ExecutionVerificationReport:
        started = datetime.now(tz=UTC)
        started_clock = monotonic()
        symlinks = [path for path in generated_dir.rglob("*") if path.is_symlink()]
        project_type = detect_project_type(generated_dir)
        if symlinks:
            return self._report(started, started_clock, VerificationStatus.UNSUPPORTED, project_type, (), (
                VerificationIssue("symlink_forbidden", "Символические ссылки запрещены в исполняемом пакете."),
            ), {})
        if project_type == ProjectType.UNSUPPORTED:
            return self._report(started, started_clock, VerificationStatus.UNSUPPORTED, project_type, (), (
                VerificationIssue("mixed_runtime", "Смешанный Python/JavaScript пакет не поддерживается."),
            ), {})
        if project_type == ProjectType.STATIC:
            return self._report(started, started_clock, VerificationStatus.PASSED, project_type, (), (), {"name": "none"})

        image = self.python_image if project_type == ProjectType.PYTHON else self.node_image
        try:
            inspect = self._run(["docker", "image", "inspect", image])
        except (OSError, subprocess.TimeoutExpired) as exc:
            return self._runtime_unavailable(started, started_clock, project_type, exc)
        if inspect.returncode != 0:
            return self._runtime_unavailable(started, started_clock, project_type, RuntimeError("container image unavailable"))

        commands = self._commands(generated_dir, project_type, image)
        results: list[CommandResult] = []
        for name, argv in commands:
            try:
                completed = self._run(argv)
            except subprocess.TimeoutExpired:
                return self._report(started, started_clock, VerificationStatus.FAILED, project_type, tuple(results), (
                    VerificationIssue("execution_timeout", "Контейнер превысил лимит времени выполнения."),
                ), {"name": "docker", "image": image})
            except OSError as exc:
                return self._runtime_unavailable(started, started_clock, project_type, exc)
            result = CommandResult(
                name=name,
                exit_code=completed.returncode,
                stdout=self._truncate(completed.stdout or ""),
                stderr=self._truncate(completed.stderr or ""),
            )
            results.append(result)
            if completed.returncode != 0:
                return self._report(started, started_clock, VerificationStatus.FAILED, project_type, tuple(results), (
                    VerificationIssue("command_failed", f"Проверка {name} завершилась с кодом {completed.returncode}."),
                ), {"name": "docker", "image": image})
        return self._report(started, started_clock, VerificationStatus.PASSED, project_type, tuple(results), (), {"name": "docker", "image": image})

    def _commands(self, generated_dir: Path, project_type: ProjectType, image: str) -> list[tuple[str, list[str]]]:
        base = self._docker_base(generated_dir, image)
        if project_type == ProjectType.PYTHON:
            ast_code = "import ast,pathlib; [ast.parse(p.read_text(), filename=str(p)) for p in pathlib.Path('/workspace').rglob('*.py')]"
            commands = [("python_ast", base + ["python", "-c", ast_code])]
            has_tests = any(
                path.is_file() and (path.name.startswith("test_") or path.name.endswith("_test.py"))
                for path in generated_dir.rglob("*.py")
            ) or (generated_dir / "tests").is_dir()
            if has_tests:
                commands.append(("pytest", base + ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "/workspace"]))
            return commands
        return [
            (
                f"node_check:{path.relative_to(generated_dir).as_posix()}",
                base + ["node", "--check", f"/workspace/{path.relative_to(generated_dir).as_posix()}"],
            )
            for path in sorted(generated_dir.rglob("*"))
            if path.is_file() and path.suffix.lower() in {".js", ".mjs", ".cjs"}
        ]

    def _docker_base(self, generated_dir: Path, image: str) -> list[str]:
        return [
            "docker", "run", "--rm", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "64", "--cpus", str(self.cpus),
            "--memory", f"{self.memory_mb}m", "--memory-swap", f"{self.memory_mb}m",
            "--user", "65534:65534", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--mount", f"type=bind,src={generated_dir.resolve()},dst=/workspace,readonly",
            "-e", "PYTHONDONTWRITEBYTECODE=1", image,
        ]

    def _run(self, argv: list[str]) -> subprocess.CompletedProcess:
        return self.runner(argv, timeout=self.timeout_seconds)

    def _truncate(self, value: str) -> str:
        return value.encode("utf-8")[: self.max_output_bytes].decode("utf-8", errors="replace")

    def _runtime_unavailable(self, started, started_clock, project_type, error):
        return self._report(started, started_clock, VerificationStatus.RUNTIME_UNAVAILABLE, project_type, (), (
            VerificationIssue("runtime_unavailable", f"Контейнерный runtime недоступен: {type(error).__name__}."),
        ), {"name": "docker"})

    @staticmethod
    def _report(started, started_clock, status, project_type, commands, issues, runtime):
        finished = datetime.now(tz=UTC)
        return ExecutionVerificationReport(
            status=status,
            project_type=project_type,
            commands=commands,
            issues=issues,
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            duration_seconds=round(monotonic() - started_clock, 3),
            runtime=runtime,
        )
