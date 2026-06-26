from pathlib import Path

import pytest

from vacancy_monitor.delivery_gateway import build_delivery_gateway_url, require_public_dir


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
