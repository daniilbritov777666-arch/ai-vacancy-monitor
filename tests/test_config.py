from vacancy_monitor.config import Config


def test_default_sources_are_project_feeds_only(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.delenv("TELEGRAM_CHANNELS", raising=False)

    config = Config.from_env()

    assert config.channels == []
    assert "https://www.fl.ru/rss/projects.xml" in config.rss_feeds
    assert config.public_project_sources == ["freelance_ru", "pchel"]
    assert config.public_source_probes == ["kwork", "workzilla"]


def test_public_sources_read_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("PUBLIC_PROJECT_SOURCES", "pchel")
    monkeypatch.setenv("PUBLIC_SOURCE_PROBES", "workzilla")

    config = Config.from_env()

    assert config.public_project_sources == ["pchel"]
    assert config.public_source_probes == ["workzilla"]


def test_autopilot_config_defaults(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.delenv("AUTO_MODE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    config = Config.from_env()

    assert config.auto_mode == "off"
    assert config.auto_max_price_rub == 15000
    assert config.openai_model
    assert config.openai_base_url == "https://api.openai.com/v1"
    assert config.openai_api_key is None


def test_autopilot_config_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("AUTO_MODE", "autopilot")
    monkeypatch.setenv("AUTO_MAX_PRICE_RUB", "9000")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    config = Config.from_env()

    assert config.auto_mode == "autopilot"
    assert config.auto_max_price_rub == 9000
    assert config.openai_model == "gpt-test"
    assert config.openai_base_url == "https://api.example.com/v1"
    assert config.openai_api_key == "sk-test"


def test_autopilot_mode_enables_autonomous_actions_by_default(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("AUTO_MODE", "autopilot")

    config = Config.from_env()

    assert config.auto_outreach_enabled is True
    assert config.auto_conversation_enabled is True
    assert config.auto_reply_enabled is True
    assert config.auto_execution_enabled is True
    assert config.auto_execution_draft_enabled is True
    assert config.auto_delivery_enabled is True
    assert config.auto_quality_enabled is True
    assert config.auto_quality_max_repairs == 2
    assert config.auto_payment_watch_enabled is True
    assert config.auto_payment_reminder_enabled is True
    assert config.auto_revision_enabled is True
    assert config.auto_revision_per_order_limit == 3
    assert config.auto_status_report_enabled is True
    assert config.freelancehunt_api_source_enabled is True
    assert config.freelancehunt_api_pages == 1
    assert config.agent_queue_enabled is True
    assert config.agent_queue_path == config.orders_path / "agent_jobs.sqlite3"
    assert config.agent_jobs_per_cycle == 3
    assert config.agent_job_max_attempts == 4
    assert config.agent_job_lease_seconds == 600
    assert config.execution_verify_enabled is True
    assert config.execution_runtime == "docker"
    assert config.execution_python_image == "freelance-agent-python-runner:3.12-v1"
    assert config.execution_node_image == "node:22-slim"
    assert config.execution_timeout_seconds == 120
    assert config.execution_memory_mb == 512
    assert config.execution_cpus == 1.0
    assert config.execution_max_output_bytes == 65536


def test_autopilot_mode_allows_explicit_autonomous_flag_override(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("AUTO_MODE", "autopilot")
    monkeypatch.setenv("AUTO_DELIVERY_ENABLED", "false")
    monkeypatch.setenv("AUTO_REVISION_ENABLED", "false")
    monkeypatch.setenv("AUTO_STATUS_REPORT_ENABLED", "false")
    monkeypatch.setenv("AGENT_QUEUE_ENABLED", "false")

    config = Config.from_env()

    assert config.auto_outreach_enabled is True
    assert config.auto_delivery_enabled is False
    assert config.auto_revision_enabled is False
    assert config.auto_status_report_enabled is False
    assert config.agent_queue_enabled is False


def test_agent_queue_config_reads_and_bounds_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("ORDERS_PATH", str(tmp_path / "orders"))
    monkeypatch.setenv("AGENT_QUEUE_PATH", str(tmp_path / "custom.sqlite3"))
    monkeypatch.setenv("AGENT_JOBS_PER_CYCLE", "99")
    monkeypatch.setenv("AGENT_JOB_MAX_ATTEMPTS", "20")
    monkeypatch.setenv("AGENT_JOB_LEASE_SECONDS", "5")

    config = Config.from_env()

    assert config.agent_queue_path == tmp_path / "custom.sqlite3"
    assert config.agent_jobs_per_cycle == 20
    assert config.agent_job_max_attempts == 8
    assert config.agent_job_lease_seconds == 30


def test_execution_verifier_config_bounds_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("EXECUTION_TIMEOUT_SECONDS", "999")
    monkeypatch.setenv("EXECUTION_MEMORY_MB", "10")
    monkeypatch.setenv("EXECUTION_CPUS", "5")
    monkeypatch.setenv("EXECUTION_MAX_OUTPUT_BYTES", "100")

    config = Config.from_env()

    assert config.execution_timeout_seconds == 600
    assert config.execution_memory_mb == 128
    assert config.execution_cpus == 2.0
    assert config.execution_max_output_bytes == 4096


def test_freelancehunt_config_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("FREELANCEHUNT_API_TOKEN", "fh-token")
    monkeypatch.setenv("FREELANCEHUNT_BID_SAFE_TYPE", "split")
    monkeypatch.setenv("FREELANCEHUNT_BID_DAYS", "3")

    config = Config.from_env()

    assert config.freelancehunt_api_token == "fh-token"
    assert config.freelancehunt_bid_safe_type == "split"
    assert config.freelancehunt_bid_days == 3


def test_auto_outreach_config_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("AUTO_OUTREACH_ENABLED", "true")
    monkeypatch.setenv("AUTO_OUTREACH_DAILY_LIMIT", "4")
    monkeypatch.setenv("AUTO_OUTREACH_MAX_AGE_HOURS", "36")

    config = Config.from_env()

    assert config.auto_outreach_enabled is True
    assert config.auto_outreach_daily_limit == 4
    assert config.auto_outreach_max_age_hours == 36


def test_smtp_config_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.ru")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USERNAME", "robot@example.ru")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM", "robot@example.ru")
    monkeypatch.setenv("SMTP_USE_SSL", "true")

    config = Config.from_env()

    assert config.smtp_host == "smtp.example.ru"
    assert config.smtp_port == 465
    assert config.smtp_username == "robot@example.ru"
    assert config.smtp_password == "secret"
    assert config.smtp_from == "robot@example.ru"
    assert config.smtp_use_ssl is True


def test_delivery_public_link_config_reads_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("DELIVERY_PUBLIC_BASE_URL", "https://files.example.ru/freelance/")
    monkeypatch.setenv("DELIVERY_PUBLIC_DIR", str(tmp_path / "public"))
    monkeypatch.setenv("DELIVERY_GATEWAY_ENABLED", "true")
    monkeypatch.setenv("DELIVERY_GATEWAY_HOST", "127.0.0.1")
    monkeypatch.setenv("DELIVERY_GATEWAY_PORT", "8787")
    monkeypatch.setenv("DELIVERY_TUNNEL_ENABLED", "true")

    config = Config.from_env()

    assert config.delivery_public_base_url == "https://files.example.ru/freelance"
    assert config.delivery_public_dir == tmp_path / "public"
    assert config.delivery_gateway_enabled is True
    assert config.delivery_gateway_host == "127.0.0.1"
    assert config.delivery_gateway_port == 8787
    assert config.delivery_tunnel_enabled is True
    assert config.delivery_public_verify_enabled is True


def test_imap_config_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("IMAP_HOST", "imap.example.ru")
    monkeypatch.setenv("IMAP_PORT", "993")
    monkeypatch.setenv("IMAP_USERNAME", "robot@example.ru")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")
    monkeypatch.setenv("IMAP_FOLDER", "Freelance")
    monkeypatch.setenv("IMAP_USE_SSL", "true")

    config = Config.from_env()

    assert config.imap_host == "imap.example.ru"
    assert config.imap_port == 993
    assert config.imap_username == "robot@example.ru"
    assert config.imap_password == "secret"
    assert config.imap_folder == "Freelance"
    assert config.imap_use_ssl is True


def test_payment_config_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("YOOKASSA_SHOP_ID", "shop-1")
    monkeypatch.setenv("YOOKASSA_SECRET_KEY", "secret")
    monkeypatch.setenv("PAYMENT_RETURN_URL", "https://example.ru/payment-return")
    monkeypatch.setenv("PAYMENT_INSTRUCTIONS_RU", "Перевод на карту РФ после проверки результата.")

    config = Config.from_env()

    assert config.yookassa_shop_id == "shop-1"
    assert config.yookassa_secret_key == "secret"
    assert config.payment_return_url == "https://example.ru/payment-return"
    assert config.payment_instructions_ru == "Перевод на карту РФ после проверки результата."


def test_conversation_config_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("AUTO_CONVERSATION_ENABLED", "true")

    config = Config.from_env()

    assert config.auto_conversation_enabled is True


def test_auto_reply_and_execution_config_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("AUTO_REPLY_ENABLED", "true")
    monkeypatch.setenv("AUTO_REPLY_DAILY_LIMIT", "7")
    monkeypatch.setenv("AUTO_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("AUTO_EXECUTION_DRAFT_ENABLED", "true")
    monkeypatch.setenv("AUTO_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("AUTO_DELIVERY_DAILY_LIMIT", "2")
    monkeypatch.setenv("AUTO_QUALITY_ENABLED", "true")
    monkeypatch.setenv("AUTO_QUALITY_MAX_REPAIRS", "4")
    monkeypatch.setenv("AUTO_PAYMENT_WATCH_ENABLED", "true")
    monkeypatch.setenv("AUTO_REVISION_ENABLED", "true")
    monkeypatch.setenv("AUTO_REVISION_DAILY_LIMIT", "3")
    monkeypatch.setenv("AUTO_REVISION_PER_ORDER_LIMIT", "2")
    monkeypatch.setenv("AUTO_STATUS_REPORT_ENABLED", "true")
    monkeypatch.setenv("AUTO_STATUS_REPORT_INTERVAL_MINUTES", "30")

    config = Config.from_env()

    assert config.auto_reply_enabled is True
    assert config.auto_reply_daily_limit == 7
    assert config.auto_execution_enabled is True
    assert config.auto_execution_draft_enabled is True
    assert config.auto_delivery_enabled is True
    assert config.auto_delivery_daily_limit == 2
    assert config.auto_quality_enabled is True
    assert config.auto_quality_max_repairs == 4
    assert config.auto_payment_watch_enabled is True
    assert config.auto_revision_enabled is True
    assert config.auto_revision_daily_limit == 3
    assert config.auto_revision_per_order_limit == 2
    assert config.auto_status_report_enabled is True
    assert config.auto_status_report_interval_minutes == 30


def test_quality_repair_limit_is_bounded(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "150761046")
    monkeypatch.setenv("AUTO_QUALITY_MAX_REPAIRS", "99")

    config = Config.from_env()

    assert config.auto_quality_max_repairs == 5
