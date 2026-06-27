from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_CHANNELS: list[str] = []

DEFAULT_RSS_FEEDS = [
    "https://www.fl.ru/rss/projects.xml",
    "https://freelancehunt.com/projects.rss",
]
DEFAULT_PUBLIC_PROJECT_SOURCES = ["freelance_ru", "pchel"]
DEFAULT_PUBLIC_SOURCE_PROBES = ["kwork", "workzilla"]


@dataclass(frozen=True)
class Config:
    bot_token: str
    chat_id: str
    channels: list[str]
    rss_feeds: list[str]
    state_path: Path
    send_first_run: bool
    orders_path: Path
    auto_mode: str = "off"
    auto_max_price_rub: int = 15000
    openai_model: str = "gpt-4.1-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str | None = None
    freelancehunt_api_token: str | None = None
    freelancehunt_bid_safe_type: str = "employer"
    freelancehunt_bid_days: int = 2
    auto_outreach_enabled: bool = False
    auto_outreach_daily_limit: int = 3
    auto_outreach_max_age_hours: int = 24
    auto_conversation_enabled: bool = False
    auto_reply_enabled: bool = False
    auto_reply_daily_limit: int = 10
    auto_execution_enabled: bool = False
    auto_execution_draft_enabled: bool = False
    auto_delivery_enabled: bool = False
    auto_delivery_daily_limit: int = 5
    auto_quality_enabled: bool = False
    auto_quality_max_repairs: int = 2
    auto_payment_watch_enabled: bool = False
    auto_payment_reminder_enabled: bool = False
    auto_revision_enabled: bool = False
    auto_revision_daily_limit: int = 5
    auto_revision_per_order_limit: int = 3
    auto_status_report_enabled: bool = False
    auto_status_report_interval_minutes: int = 360
    public_project_sources: list[str] = field(default_factory=list)
    public_source_probes: list[str] = field(default_factory=list)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str | None = None
    smtp_use_ssl: bool = False
    imap_host: str | None = None
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"
    imap_use_ssl: bool = True
    yookassa_shop_id: str | None = None
    yookassa_secret_key: str | None = None
    payment_return_url: str = "https://example.ru/payment-return"
    payment_instructions_ru: str = ""
    delivery_public_base_url: str | None = None
    delivery_public_dir: Path | None = None
    delivery_gateway_enabled: bool = False
    delivery_gateway_host: str = "127.0.0.1"
    delivery_gateway_port: int = 8787
    delivery_tunnel_enabled: bool = False
    delivery_public_verify_enabled: bool = False
    agent_queue_enabled: bool = False
    agent_queue_path: Path | None = None
    agent_jobs_per_cycle: int = 3
    agent_job_max_attempts: int = 4
    agent_job_lease_seconds: int = 600
    execution_verify_enabled: bool = False
    execution_runtime: str = "docker"
    execution_python_image: str = "freelance-agent-python-runner:3.12-v1"
    execution_node_image: str = "node:22-slim"
    execution_timeout_seconds: int = 120
    execution_memory_mb: int = 512
    execution_cpus: float = 1.0
    execution_max_output_bytes: int = 65536

    @classmethod
    def from_env(cls) -> "Config":
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        channels = _csv(os.environ.get("TELEGRAM_CHANNELS")) or DEFAULT_CHANNELS
        rss_feeds = _csv(os.environ.get("RSS_FEEDS")) or DEFAULT_RSS_FEEDS
        public_project_sources = _csv(os.environ.get("PUBLIC_PROJECT_SOURCES")) or DEFAULT_PUBLIC_PROJECT_SOURCES
        public_source_probes = _csv(os.environ.get("PUBLIC_SOURCE_PROBES")) or DEFAULT_PUBLIC_SOURCE_PROBES
        smtp_host = os.environ.get("SMTP_HOST", "").strip() or None
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_username = os.environ.get("SMTP_USERNAME", "").strip()
        smtp_password = os.environ.get("SMTP_PASSWORD", "")
        smtp_from = os.environ.get("SMTP_FROM", "").strip() or None
        smtp_use_ssl = _env_bool("SMTP_USE_SSL")
        imap_host = os.environ.get("IMAP_HOST", "").strip() or None
        imap_port = int(os.environ.get("IMAP_PORT", "993"))
        imap_username = os.environ.get("IMAP_USERNAME", "").strip()
        imap_password = os.environ.get("IMAP_PASSWORD", "")
        imap_folder = os.environ.get("IMAP_FOLDER", "INBOX").strip() or "INBOX"
        imap_use_ssl = _env_bool("IMAP_USE_SSL", default=True)
        yookassa_shop_id = os.environ.get("YOOKASSA_SHOP_ID", "").strip() or None
        yookassa_secret_key = os.environ.get("YOOKASSA_SECRET_KEY", "").strip() or None
        payment_return_url = os.environ.get("PAYMENT_RETURN_URL", "https://example.ru/payment-return").strip()
        payment_instructions_ru = os.environ.get("PAYMENT_INSTRUCTIONS_RU", "").strip()
        delivery_public_base_url = os.environ.get("DELIVERY_PUBLIC_BASE_URL", "").strip().rstrip("/") or None
        delivery_public_dir_raw = os.environ.get("DELIVERY_PUBLIC_DIR", "").strip()
        delivery_public_dir = Path(delivery_public_dir_raw) if delivery_public_dir_raw else None
        delivery_gateway_enabled = _env_bool("DELIVERY_GATEWAY_ENABLED")
        delivery_gateway_host = os.environ.get("DELIVERY_GATEWAY_HOST", "127.0.0.1").strip() or "127.0.0.1"
        delivery_gateway_port = int(os.environ.get("DELIVERY_GATEWAY_PORT", "8787"))
        delivery_tunnel_enabled = _env_bool("DELIVERY_TUNNEL_ENABLED")
        delivery_public_verify_enabled = _env_bool(
            "DELIVERY_PUBLIC_VERIFY_ENABLED",
            default=delivery_tunnel_enabled,
        )
        state_path = Path(os.environ.get("STATE_PATH", "data/seen_posts.json"))
        send_first_run = os.environ.get("SEND_FIRST_RUN", "").lower() in {"1", "true", "yes"}
        orders_path = Path(os.environ.get("ORDERS_PATH", "orders"))
        auto_mode = os.environ.get("AUTO_MODE", "off").strip().lower()
        auto_max_price_rub = int(os.environ.get("AUTO_MAX_PRICE_RUB", "15000"))
        openai_model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini").strip()
        openai_base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
        openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip() or None
        freelancehunt_api_token = os.environ.get("FREELANCEHUNT_API_TOKEN", "").strip() or None
        freelancehunt_bid_safe_type = os.environ.get("FREELANCEHUNT_BID_SAFE_TYPE", "employer").strip()
        freelancehunt_bid_days = int(os.environ.get("FREELANCEHUNT_BID_DAYS", "2"))
        autonomous_default = auto_mode == "autopilot"
        auto_outreach_enabled = _env_bool("AUTO_OUTREACH_ENABLED", default=autonomous_default)
        auto_outreach_daily_limit = int(os.environ.get("AUTO_OUTREACH_DAILY_LIMIT", "3"))
        auto_outreach_max_age_hours = int(os.environ.get("AUTO_OUTREACH_MAX_AGE_HOURS", "24"))
        auto_conversation_enabled = _env_bool("AUTO_CONVERSATION_ENABLED", default=autonomous_default)
        auto_reply_enabled = _env_bool("AUTO_REPLY_ENABLED", default=autonomous_default)
        auto_reply_daily_limit = int(os.environ.get("AUTO_REPLY_DAILY_LIMIT", "10"))
        auto_execution_enabled = _env_bool("AUTO_EXECUTION_ENABLED", default=autonomous_default)
        auto_execution_draft_enabled = _env_bool("AUTO_EXECUTION_DRAFT_ENABLED", default=autonomous_default)
        auto_delivery_enabled = _env_bool("AUTO_DELIVERY_ENABLED", default=autonomous_default)
        auto_delivery_daily_limit = int(os.environ.get("AUTO_DELIVERY_DAILY_LIMIT", "5"))
        auto_quality_enabled = _env_bool("AUTO_QUALITY_ENABLED", default=autonomous_default)
        auto_quality_max_repairs = min(5, max(0, int(os.environ.get("AUTO_QUALITY_MAX_REPAIRS", "2"))))
        auto_payment_watch_enabled = _env_bool("AUTO_PAYMENT_WATCH_ENABLED", default=autonomous_default)
        auto_payment_reminder_enabled = _env_bool("AUTO_PAYMENT_REMINDER_ENABLED", default=autonomous_default)
        auto_revision_enabled = _env_bool("AUTO_REVISION_ENABLED", default=autonomous_default)
        auto_revision_daily_limit = int(os.environ.get("AUTO_REVISION_DAILY_LIMIT", "5"))
        auto_revision_per_order_limit = min(10, max(0, int(os.environ.get("AUTO_REVISION_PER_ORDER_LIMIT", "3"))))
        auto_status_report_enabled = _env_bool("AUTO_STATUS_REPORT_ENABLED", default=autonomous_default)
        auto_status_report_interval_minutes = int(os.environ.get("AUTO_STATUS_REPORT_INTERVAL_MINUTES", "360"))
        agent_queue_enabled = _env_bool("AGENT_QUEUE_ENABLED", default=autonomous_default)
        agent_queue_path = Path(os.environ.get("AGENT_QUEUE_PATH", str(orders_path / "agent_jobs.sqlite3")))
        agent_jobs_per_cycle = min(20, max(1, int(os.environ.get("AGENT_JOBS_PER_CYCLE", "3"))))
        agent_job_max_attempts = min(8, max(1, int(os.environ.get("AGENT_JOB_MAX_ATTEMPTS", "4"))))
        agent_job_lease_seconds = min(3600, max(30, int(os.environ.get("AGENT_JOB_LEASE_SECONDS", "600"))))
        execution_verify_enabled = _env_bool("EXECUTION_VERIFY_ENABLED", default=autonomous_default)
        execution_runtime = os.environ.get("EXECUTION_RUNTIME", "docker").strip().lower()
        execution_python_image = os.environ.get("EXECUTION_PYTHON_IMAGE", "freelance-agent-python-runner:3.12-v1").strip()
        execution_node_image = os.environ.get("EXECUTION_NODE_IMAGE", "node:22-slim").strip()
        execution_timeout_seconds = min(600, max(10, int(os.environ.get("EXECUTION_TIMEOUT_SECONDS", "120"))))
        execution_memory_mb = min(2048, max(128, int(os.environ.get("EXECUTION_MEMORY_MB", "512"))))
        execution_cpus = min(2.0, max(0.25, float(os.environ.get("EXECUTION_CPUS", "1.0"))))
        execution_max_output_bytes = min(262144, max(4096, int(os.environ.get("EXECUTION_MAX_OUTPUT_BYTES", "65536"))))

        if not bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
        if not chat_id:
            raise RuntimeError("TELEGRAM_CHAT_ID is required")
        if auto_mode not in {"off", "draft", "autopilot"}:
            raise RuntimeError("AUTO_MODE must be off, draft, or autopilot")
        if freelancehunt_bid_safe_type not in {"employer", "developer", "split", "employer_cashless"}:
            raise RuntimeError("FREELANCEHUNT_BID_SAFE_TYPE must be employer, developer, split, or employer_cashless")

        return cls(
            bot_token=bot_token,
            chat_id=chat_id,
            channels=channels,
            rss_feeds=rss_feeds,
            state_path=state_path,
            send_first_run=send_first_run,
            orders_path=orders_path,
            auto_mode=auto_mode,
            auto_max_price_rub=auto_max_price_rub,
            openai_model=openai_model,
            openai_base_url=openai_base_url,
            openai_api_key=openai_api_key,
            freelancehunt_api_token=freelancehunt_api_token,
            freelancehunt_bid_safe_type=freelancehunt_bid_safe_type,
            freelancehunt_bid_days=freelancehunt_bid_days,
            auto_outreach_enabled=auto_outreach_enabled,
            auto_outreach_daily_limit=auto_outreach_daily_limit,
            auto_outreach_max_age_hours=auto_outreach_max_age_hours,
            auto_conversation_enabled=auto_conversation_enabled,
            auto_reply_enabled=auto_reply_enabled,
            auto_reply_daily_limit=auto_reply_daily_limit,
            auto_execution_enabled=auto_execution_enabled,
            auto_execution_draft_enabled=auto_execution_draft_enabled,
            auto_delivery_enabled=auto_delivery_enabled,
            auto_delivery_daily_limit=auto_delivery_daily_limit,
            auto_quality_enabled=auto_quality_enabled,
            auto_quality_max_repairs=auto_quality_max_repairs,
            auto_payment_watch_enabled=auto_payment_watch_enabled,
            auto_payment_reminder_enabled=auto_payment_reminder_enabled,
            auto_revision_enabled=auto_revision_enabled,
            auto_revision_daily_limit=auto_revision_daily_limit,
            auto_revision_per_order_limit=auto_revision_per_order_limit,
            auto_status_report_enabled=auto_status_report_enabled,
            auto_status_report_interval_minutes=auto_status_report_interval_minutes,
            public_project_sources=public_project_sources,
            public_source_probes=public_source_probes,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_username=smtp_username,
            smtp_password=smtp_password,
            smtp_from=smtp_from,
            smtp_use_ssl=smtp_use_ssl,
            imap_host=imap_host,
            imap_port=imap_port,
            imap_username=imap_username,
            imap_password=imap_password,
            imap_folder=imap_folder,
            imap_use_ssl=imap_use_ssl,
            yookassa_shop_id=yookassa_shop_id,
            yookassa_secret_key=yookassa_secret_key,
            payment_return_url=payment_return_url,
            payment_instructions_ru=payment_instructions_ru,
            delivery_public_base_url=delivery_public_base_url,
            delivery_public_dir=delivery_public_dir,
            delivery_gateway_enabled=delivery_gateway_enabled,
            delivery_gateway_host=delivery_gateway_host,
            delivery_gateway_port=delivery_gateway_port,
            delivery_tunnel_enabled=delivery_tunnel_enabled,
            delivery_public_verify_enabled=delivery_public_verify_enabled,
            agent_queue_enabled=agent_queue_enabled,
            agent_queue_path=agent_queue_path,
            agent_jobs_per_cycle=agent_jobs_per_cycle,
            agent_job_max_attempts=agent_job_max_attempts,
            agent_job_lease_seconds=agent_job_lease_seconds,
            execution_verify_enabled=execution_verify_enabled,
            execution_runtime=execution_runtime,
            execution_python_image=execution_python_image,
            execution_node_image=execution_node_image,
            execution_timeout_seconds=execution_timeout_seconds,
            execution_memory_mb=execution_memory_mb,
            execution_cpus=execution_cpus,
            execution_max_output_bytes=execution_max_output_bytes,
        )


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip().lstrip("@") for item in value.split(",") if item.strip()]


def _env_bool(name: str, *, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes"}
