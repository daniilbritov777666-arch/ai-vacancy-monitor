import json
from pathlib import Path

import pytest

from vacancy_monitor.delivery_gateway import (
    DeliveryReadinessError,
    build_delivery_gateway_url,
    require_public_dir,
    verify_public_archive,
)


def test_build_delivery_gateway_url_normalizes_base_url():
    url = build_delivery_gateway_url(
        base_url="http://127.0.0.1:8787/",
        order_id="order-1",
        filename="delivery_package.zip",
    )

    assert url == "http://127.0.0.1:8787/order-1/delivery_package.zip"


def test_require_public_dir_creates_directory(tmp_path):
    public_dir = tmp_path / "public"

    result = require_public_dir(public_dir)

    assert result == public_dir
    assert public_dir.is_dir()


def test_require_public_dir_rejects_file(tmp_path):
    public_dir = tmp_path / "public"
    public_dir.write_text("not a directory", encoding="utf-8")

    with pytest.raises(RuntimeError, match="DELIVERY_PUBLIC_DIR"):
        require_public_dir(public_dir)


class _HeadResponse:
    def __init__(self, *, status: int, content_length: int):
        self.status_code = status
        self.headers = {"Content-Length": str(content_length)}


def test_verify_public_archive_writes_ready_report(tmp_path):
    archive_path = tmp_path / "delivery_package.zip"
    archive_path.write_bytes(b"archive")
    report_path = tmp_path / "delivery_readiness.json"
    requests = []

    def requester(url, *, headers, timeout, allow_redirects):
        requests.append((url, headers, timeout, allow_redirects))
        return _HeadResponse(status=200, content_length=archive_path.stat().st_size)

    report = verify_public_archive(
        public_url="https://files.example.ru/order-1/delivery_package.zip",
        archive_path=archive_path,
        report_path=report_path,
        timeout_seconds=4,
        requester=requester,
    )

    assert report["ready"] is True
    assert report["status_code"] == 200
    assert report["expected_bytes"] == 7
    assert report["remote_bytes"] == 7
    assert requests[0][0] == "https://files.example.ru/order-1/delivery_package.zip"
    assert requests[0][2] == 4
    assert requests[0][3] is True
    assert json.loads(report_path.read_text(encoding="utf-8"))["ready"] is True


def test_verify_public_archive_blocks_size_mismatch_and_writes_report(tmp_path):
    archive_path = tmp_path / "delivery_package.zip"
    archive_path.write_bytes(b"archive")
    report_path = tmp_path / "delivery_readiness.json"

    with pytest.raises(DeliveryReadinessError, match="размер"):
        verify_public_archive(
            public_url="https://files.example.ru/order-1/delivery_package.zip",
            archive_path=archive_path,
            report_path=report_path,
            requester=lambda url, **kwargs: _HeadResponse(status=200, content_length=3),
        )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ready"] is False
    assert report["error_type"] == "ContentLengthMismatch"
    assert report["expected_bytes"] == 7
    assert report["remote_bytes"] == 3


def test_verify_public_archive_blocks_transport_error_and_writes_report(tmp_path):
    archive_path = tmp_path / "delivery_package.zip"
    archive_path.write_bytes(b"archive")
    report_path = tmp_path / "delivery_readiness.json"

    def requester(url, **kwargs):
        raise TimeoutError("tunnel timeout")

    with pytest.raises(DeliveryReadinessError, match="недоступен"):
        verify_public_archive(
            public_url="https://files.example.ru/order-1/delivery_package.zip",
            archive_path=archive_path,
            report_path=report_path,
            requester=requester,
        )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ready"] is False
    assert report["error_type"] == "TimeoutError"


def test_verify_public_archive_blocks_missing_url_and_writes_report(tmp_path):
    archive_path = tmp_path / "delivery_package.zip"
    archive_path.write_bytes(b"archive")
    report_path = tmp_path / "delivery_readiness.json"

    with pytest.raises(DeliveryReadinessError, match="ссылка"):
        verify_public_archive(
            public_url="",
            archive_path=archive_path,
            report_path=report_path,
        )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ready"] is False
    assert report["error_type"] == "MissingPublicUrl"
