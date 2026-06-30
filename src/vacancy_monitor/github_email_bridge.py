from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable
from uuid import uuid4

import requests

from vacancy_monitor.order_models import Order


class GitHubEmailBridge:
    def __init__(
        self,
        *,
        repo: str,
        token: str,
        workflow: str,
        dispatch_ref: str,
        source_ref: str,
        from_email: str,
        session=None,
        encryptor: Callable[[str, bytes], str] | None = None,
        sleep: Callable[[float], None] = default_sleep,
        job_id_factory: Callable[[], str] | None = None,
        poll_interval_seconds: float = 3,
        max_poll_attempts: int = 60,
    ) -> None:
        self.repo = repo
        self.token = token
        self.workflow = workflow
        self.dispatch_ref = dispatch_ref
        self.source_ref = source_ref
        self.from_email = from_email
        self.session = session or requests.Session()
        self.encryptor = encryptor or _seal_for_github
        self.sleep = sleep
        self.job_id_factory = job_id_factory or (lambda: uuid4().hex[:16])
        self.poll_interval_seconds = poll_interval_seconds
        self.max_poll_attempts = max_poll_attempts

    def send(self, order: Order, text: str, *, attachments: list[Path] | None = None) -> None:
        if attachments:
            raise ValueError("GitHub email bridge does not accept attachments")
        if not order.contact or order.contact.channel != "email":
            raise RuntimeError("order has no email contact")

        job_id = self.job_id_factory()
        payload = json.dumps(
            {
                "to": order.contact.value,
                "subject": f"Отклик на проект: {order.category}",
                "text": text,
                "message_id": self._message_id(order),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        api = f"https://api.github.com/repos/{self.repo}"
        key_response = self.session.get(f"{api}/actions/secrets/public-key", headers=headers, timeout=20)
        key_response.raise_for_status()
        public_key = key_response.json()
        encrypted_value = self.encryptor(public_key["key"], payload)
        secret_response = self.session.put(
            f"{api}/actions/secrets/EMAIL_BRIDGE_PAYLOAD",
            headers=headers,
            json={"encrypted_value": encrypted_value, "key_id": public_key["key_id"]},
            timeout=20,
        )
        secret_response.raise_for_status()
        dispatch_response = self.session.post(
            f"{api}/actions/workflows/{self.workflow}/dispatches",
            headers=headers,
            json={
                "ref": self.dispatch_ref,
                "inputs": {"job_id": job_id, "source_ref": self.source_ref},
            },
            timeout=20,
        )
        dispatch_response.raise_for_status()
        self._wait_for_run(api=api, headers=headers, job_id=job_id)

    def _wait_for_run(self, *, api: str, headers: dict[str, str], job_id: str) -> None:
        expected_name = f"email-bridge-{job_id}"
        for _ in range(self.max_poll_attempts):
            response = self.session.get(
                f"{api}/actions/workflows/{self.workflow}/runs",
                headers=headers,
                params={"event": "workflow_dispatch", "branch": self.dispatch_ref, "per_page": 20},
                timeout=20,
            )
            response.raise_for_status()
            run = next(
                (
                    item
                    for item in response.json().get("workflow_runs", [])
                    if item.get("display_title") == expected_name or item.get("name") == expected_name
                ),
                None,
            )
            if run and run.get("status") == "completed":
                if run.get("conclusion") != "success":
                    raise RuntimeError(f"email bridge workflow failed: {run.get('conclusion')}")
                return
            self.sleep(self.poll_interval_seconds)
        raise TimeoutError(f"email bridge workflow did not finish: {job_id}")

    def _message_id(self, order: Order) -> str:
        digest = hashlib.sha256(order.order_id.encode("utf-8")).hexdigest()[:24]
        domain = self.from_email.rsplit("@", 1)[-1] if "@" in self.from_email else "localhost"
        return f"<{digest}@{domain}>"


def _seal_for_github(public_key: str, payload: bytes) -> str:
    from nacl.public import PublicKey, SealedBox

    key = PublicKey(base64.b64decode(public_key))
    return base64.b64encode(SealedBox(key).encrypt(payload)).decode("ascii")
