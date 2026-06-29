from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from vacancy_monitor.public_sources import (
    PUBLIC_SOURCE_URLS,
    SourceContractError,
    fetch_public_project_posts,
    parse_freelance_ru,
    parse_pchel,
    parse_weblancer,
    probe_public_source,
)


MOSCOW = ZoneInfo("Europe/Moscow")


FREELANCE_RU_HTML = """
<div class="task-feed-list">
  <article class="task-card">
    <a class="task-card__title-link" href="/task/view/3272">Настроить Telegram-бота</a>
    <p class="task-card__desc">Нужна интеграция с Google Sheets. Пишите: client@example.ru</p>
    <div class="task-card__chips"><span>Программирование</span></div>
    <span class="task-card__foot-item" title="20.06.2026 17:52">сегодня</span>
    <div class="task-card__budget">15 000 руб.</div>
  </article>
</div>
"""


PCHEL_HTML = """
<div id="projects-list">
  <div class="project-block project-block2">
    <input type="hidden" name="project_id" value="1625919">
    <div class="project-title"><a href="/jobs/website-development/dorabotka-sayta-1625919/">Доработка сайта</a></div>
    <div class="project-text"><p>Добавить API и автоматическую выгрузку.</p></div>
    <div class="project-tags">Категория: Разработка сайтов</div>
    <div class="project-athor"><div class="price"><span>Бюджет:</span> 12 000 руб.</div></div>
    <div class="date">Сегодня</div>
  </div>
</div>
"""


WEBLANCER_HTML = """
<div class="space-y-3">
  <article class="bg-white p-6 rounded-md shadow">
    <h2 class="text-xl font-semibold">
      <a href="/freelance/sozdanie-botov-61/telegram-bot-dlya-zayavok-1268001/">Telegram-бот для заявок</a>
    </h2>
    <span>15 000 ₽</span>
    <p>Разовая задача: интеграция с API и Google Sheets.</p>
    <div>Создание ботов Python</div>
    <time>29.06.2026</time>
  </article>
</div>
"""


def test_parse_freelance_ru_extracts_project_fields():
    posts = parse_freelance_ru(FREELANCE_RU_HTML, fetched_at=datetime(2026, 6, 20, 18, 0, tzinfo=MOSCOW))

    assert len(posts) == 1
    assert posts[0].post_id == "freelance_ru:3272"
    assert posts[0].url == "https://freelance.ru/task/view/3272"
    assert "Настроить Telegram-бота" in posts[0].text
    assert "15 000 руб." in posts[0].text
    assert "client@example.ru" in posts[0].text
    assert posts[0].published_at == "2026-06-20T17:52:00+03:00"


def test_parse_pchel_extracts_project_fields():
    posts = parse_pchel(PCHEL_HTML, fetched_at=datetime(2026, 6, 20, 18, 0, tzinfo=MOSCOW))

    assert len(posts) == 1
    assert posts[0].post_id == "pchel:1625919"
    assert posts[0].url == "https://pchel.net/jobs/website-development/dorabotka-sayta-1625919/"
    assert "Добавить API" in posts[0].text
    assert "Разработка сайтов" in posts[0].text
    assert "12 000 руб." in posts[0].text
    assert posts[0].published_at == "2026-06-20T18:00:00+03:00"


def test_parse_weblancer_extracts_project_fields():
    posts = parse_weblancer(WEBLANCER_HTML, fetched_at=datetime(2026, 6, 29, 20, 0, tzinfo=MOSCOW))

    assert len(posts) == 1
    assert posts[0].post_id == "weblancer:1268001"
    assert posts[0].url == (
        "https://www.weblancer.net/freelance/sozdanie-botov-61/telegram-bot-dlya-zayavok-1268001/"
    )
    assert "Telegram-бот для заявок" in posts[0].text
    assert "15 000 ₽" in posts[0].text
    assert "Google Sheets" in posts[0].text
    assert posts[0].published_at == "2026-06-29T00:00:00+03:00"


@pytest.mark.parametrize(
    "parser",
    [parse_freelance_ru, parse_pchel, parse_weblancer],
)
def test_parser_raises_when_required_project_container_disappears(parser):
    with pytest.raises(SourceContractError):
        parser("<html><body>changed</body></html>", fetched_at=datetime(2026, 6, 20, tzinfo=MOSCOW))


class FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


def test_fetch_public_project_posts_uses_registry_timeout_and_user_agent(monkeypatch):
    calls = []

    def fake_get(url, *, timeout, headers):
        calls.append((url, timeout, headers))
        return FakeResponse(FREELANCE_RU_HTML)

    monkeypatch.setattr("vacancy_monitor.public_sources.requests.get", fake_get)

    posts = fetch_public_project_posts("freelance_ru")

    assert posts[0].post_id == "freelance_ru:3272"
    assert calls[0][0] == PUBLIC_SOURCE_URLS["freelance_ru"]
    assert calls[0][1] == 20
    assert "User-Agent" in calls[0][2]


def test_kwork_probe_reports_client_rendered_without_returning_posts(monkeypatch):
    monkeypatch.setattr(
        "vacancy_monitor.public_sources.requests.get",
        lambda *args, **kwargs: FakeResponse("<html><wants-view></wants-view></html>"),
    )

    health = probe_public_source("kwork")

    assert health.status == "client_rendered"
    assert health.posts == 0
    assert health.error is None


def test_workzilla_probe_reports_examples_only(monkeypatch):
    monkeypatch.setattr(
        "vacancy_monitor.public_sources.requests.get",
        lambda *args, **kwargs: FakeResponse("<title>Примеры заданий | Workzilla</title>"),
    )

    health = probe_public_source("workzilla")

    assert health.status == "examples_only"
    assert health.posts == 0
