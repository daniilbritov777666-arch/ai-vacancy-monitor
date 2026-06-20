from pathlib import Path

from vacancy_monitor.quality import check_generated_package


def _write(root: Path, name: str, content: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_valid_python_package_passes_local_quality_check(tmp_path):
    _write(tmp_path, "bot.py", "def main():\n    return 'ok'\n")
    _write(tmp_path, "README.md", "# Запуск\n\n`python bot.py`\n")
    _write(tmp_path, ".env.example", "TELEGRAM_BOT_TOKEN=\n")

    report = check_generated_package(tmp_path)

    assert report.passed is True
    assert report.issues == ()


def test_empty_and_invalid_files_fail_local_quality_check(tmp_path):
    _write(tmp_path, "empty.txt", "")
    _write(tmp_path, "broken.py", "def broken(:\n")
    _write(tmp_path, "broken.json", "{not json}")
    _write(tmp_path, "broken.csv", "name,value\nfirst,1,extra\n")

    report = check_generated_package(tmp_path)

    assert report.passed is False
    assert {issue.code for issue in report.issues} >= {
        "empty_file",
        "invalid_python",
        "invalid_json",
        "invalid_csv",
        "missing_readme",
    }


def test_filled_secret_is_blocked_but_env_example_placeholder_is_allowed(tmp_path):
    _write(tmp_path, "README.md", "# Result\n")
    _write(tmp_path, ".env.example", "API_TOKEN=\n")
    _write(tmp_path, "config.txt", "OPENAI_API_KEY=sk-live-secret-value\n")

    report = check_generated_package(tmp_path)

    assert report.passed is False
    assert any(issue.code == "secret_exposure" and issue.path == "config.txt" for issue in report.issues)


def test_environment_variable_lookup_is_not_treated_as_embedded_secret(tmp_path):
    _write(tmp_path, "bot.py", "import os\n\ntoken = os.environ['TELEGRAM_BOT_TOKEN']\n")
    _write(tmp_path, "README.md", "# Запуск\n")

    report = check_generated_package(tmp_path)

    assert not any(issue.code == "secret_exposure" for issue in report.issues)


def test_missing_generated_directory_fails(tmp_path):
    report = check_generated_package(tmp_path / "missing")

    assert report.passed is False
    assert report.issues[0].code == "no_generated_files"


def test_summary_without_deliverable_and_empty_delivery_message_fail(tmp_path):
    _write(tmp_path, "summary.md", "Описание результата.\n")

    report = check_generated_package(tmp_path, delivery_message="")

    assert {issue.code for issue in report.issues} >= {"no_deliverable_files", "empty_delivery_message"}
