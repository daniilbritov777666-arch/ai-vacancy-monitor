from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class BrowserOutreachRequest:
    order_id: str
    channel: str
    project_url: str
    message: str
    amount_rub: int
    days: int


@dataclass(frozen=True)
class BrowserConversationRequest:
    order_id: str
    channel: str
    project_url: str


@dataclass(frozen=True)
class BrowserReplyRequest:
    order_id: str
    channel: str
    project_url: str
    message: str


class MarketplaceBrowserClient:
    def __init__(
        self,
        *,
        profile_dir: Path,
        executable_path: str,
        headless: bool,
        live_submit: bool,
        timeout_seconds: int,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.profile_dir = profile_dir
        self.executable_path = executable_path
        self.headless = headless
        self.live_submit = live_submit
        self.timeout_seconds = timeout_seconds
        self.runner = runner

    def submit(self, request: BrowserOutreachRequest, *, artifacts_dir: Path) -> dict:
        return self._run("submit_outreach", request, artifacts_dir=artifacts_dir)

    def list_messages(self, request: BrowserConversationRequest, *, artifacts_dir: Path) -> dict:
        return self._run("list_messages", request, artifacts_dir=artifacts_dir)

    def send_reply(self, request: BrowserReplyRequest, *, artifacts_dir: Path) -> dict:
        return self._run("send_reply", request, artifacts_dir=artifacts_dir)

    def _run(
        self,
        operation: str,
        request: BrowserOutreachRequest | BrowserConversationRequest | BrowserReplyRequest,
        *,
        artifacts_dir: Path,
    ) -> dict:
        payload = {
            "operation": operation,
            "request": asdict(request),
            "profile_dir": str(self.profile_dir),
            "artifacts_dir": str(artifacts_dir),
            "executable_path": self.executable_path,
            "headless": self.headless,
            "live_submit": self.live_submit,
        }
        completed = self.runner(
            [sys.executable, "-m", "vacancy_monitor.marketplace_browser_worker"],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        try:
            result = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError):
            return {"status": "worker_error", "submitted": False, "error_type": "InvalidWorkerOutput"}
        return result if isinstance(result, dict) else {"status": "worker_error", "submitted": False}
