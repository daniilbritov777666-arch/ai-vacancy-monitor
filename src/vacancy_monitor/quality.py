from __future__ import annotations

import ast
import csv
import io
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


MAX_FILE_BYTES = 2 * 1024 * 1024
CODE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx"}
SECRET_ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:export\s+)?(?:[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|PRIVATE_KEY)[A-Z0-9_]*)\s*[=:]\s*['\"]?([^\s'\"]+)"
)


@dataclass(frozen=True)
class QualityIssue:
    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class QualityReport:
    passed: bool
    issues: tuple[QualityIssue, ...]

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "issues": [asdict(issue) for issue in self.issues],
        }


@dataclass(frozen=True)
class AIQualityReview:
    passed: bool
    issues: tuple[str, ...]
    repair_instructions_ru: str


def check_generated_package(generated_dir: Path, *, delivery_message: str | None = None) -> QualityReport:
    if not generated_dir.is_dir():
        return _report([QualityIssue("no_generated_files", "Папка результата отсутствует.")])

    files = sorted(path for path in generated_dir.rglob("*") if path.is_file())
    if not files:
        return _report([QualityIssue("no_generated_files", "Папка результата пуста.")])

    issues: list[QualityIssue] = []
    deliverable_files = [path for path in files if path.name.lower() != "summary.md"]
    if not deliverable_files:
        issues.append(QualityIssue("no_deliverable_files", "Нет отдельного файла результата кроме summary.md."))
    if delivery_message is not None and not delivery_message.strip():
        issues.append(QualityIssue("empty_delivery_message", "Сообщение сдачи заказчику пусто."))
    has_code = any(path.suffix.lower() in CODE_SUFFIXES for path in files)
    has_readme = any(path.name.lower().startswith("readme") for path in files)
    if has_code and not has_readme:
        issues.append(QualityIssue("missing_readme", "Для программного результата отсутствует README с запуском."))

    for path in files:
        relative = path.relative_to(generated_dir).as_posix()
        try:
            size = path.stat().st_size
        except OSError as exc:
            issues.append(QualityIssue("unreadable_file", f"Файл недоступен: {exc}.", relative))
            continue
        if size == 0:
            issues.append(QualityIssue("empty_file", "Файл пуст.", relative))
            continue
        if size > MAX_FILE_BYTES:
            issues.append(QualityIssue("file_too_large", "Файл превышает локальный лимит 2 МБ.", relative))
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        issues.extend(_check_text(path=path, relative=relative, text=text))

    return _report(issues)


def _check_text(*, path: Path, relative: str, text: str) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    if _contains_secret(text):
        issues.append(QualityIssue("secret_exposure", "Обнаружено заполненное значение секрета.", relative))

    suffix = path.suffix.lower()
    try:
        if suffix == ".py":
            ast.parse(text, filename=relative)
        elif suffix == ".json":
            json.loads(text)
        elif suffix == ".csv":
            _validate_csv(text)
    except (SyntaxError, json.JSONDecodeError, csv.Error, ValueError) as exc:
        code = {".py": "invalid_python", ".json": "invalid_json", ".csv": "invalid_csv"}[suffix]
        issues.append(QualityIssue(code, f"Ошибка формата: {exc}.", relative))
    return issues


def _contains_secret(text: str) -> bool:
    placeholders = {"", "changeme", "change_me", "example", "your_token", "your-secret", "<token>", "<secret>"}
    references = ("os.environ", "getenv(", "env.", "settings.", "config.")
    for match in SECRET_ASSIGNMENT.finditer(text):
        value = match.group(1).strip().lower()
        if value in placeholders or value.startswith(references):
            continue
        return True
    return False


def _validate_csv(text: str) -> None:
    rows = list(csv.reader(io.StringIO(text), strict=True))
    if not rows or not rows[0]:
        raise ValueError("нет заголовка")
    width = len(rows[0])
    if any(len(row) != width for row in rows[1:]):
        raise ValueError("строки содержат разное число колонок")


def _report(issues: list[QualityIssue]) -> QualityReport:
    return QualityReport(passed=not issues, issues=tuple(issues))
