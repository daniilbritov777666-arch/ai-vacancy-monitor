from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


class BrowserSubmissionError(RuntimeError):
    pass


class BrowserSessionUnauthenticated(BrowserSubmissionError):
    pass


class BrowserCaptchaRequired(BrowserSubmissionError):
    pass


@dataclass(frozen=True)
class BrowserBidRequest:
    order_id: str
    project_id: str
    project_url: str
    amount: int
    currency: str
    days: int
    safe_type: str
    comment: str


@dataclass(frozen=True)
class BrowserBidResult:
    status: str
    project_id: str
    submitted: bool
    bid_reference: str | None = None


class FreelancehuntBrowserClient:
    def __init__(
        self,
        *,
        profile_dir: Path,
        artifacts_dir: Path,
        live_submit: bool,
        timeout_seconds: int = 120,
        worker_command: list[str] | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.profile_dir = profile_dir
        self.artifacts_dir = artifacts_dir
        self.live_submit = live_submit
        self.timeout_seconds = timeout_seconds
        self.worker_command = worker_command or [
            sys.executable,
            "-m",
            "vacancy_monitor.freelancehunt_browser_worker",
        ]
        self.runner = runner

    def submit_bid(self, request: BrowserBidRequest) -> BrowserBidResult:
        payload = {
            "request": asdict(request),
            "profile_dir": str(self.profile_dir),
            "artifacts_dir": str(self.artifacts_dir),
            "live_submit": self.live_submit,
        }
        completed = self.runner(
            self.worker_command,
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        try:
            response = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise BrowserSubmissionError("browser worker returned invalid JSON") from exc

        status = str(response.get("status") or "worker_error")
        if status == "unauthenticated":
            raise BrowserSessionUnauthenticated("Freelancehunt browser profile is not authenticated")
        if status == "captcha_required":
            raise BrowserCaptchaRequired("Freelancehunt requires CAPTCHA")
        if completed.returncode != 0:
            raise BrowserSubmissionError(f"browser worker failed: {status}")
        return BrowserBidResult(
            status=status,
            project_id=str(response.get("project_id") or request.project_id),
            submitted=bool(response.get("submitted")),
            bid_reference=response.get("bid_reference"),
        )
