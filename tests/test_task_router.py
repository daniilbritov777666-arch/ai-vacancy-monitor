from vacancy_monitor.models import Post
from vacancy_monitor.order_models import make_order_from_post
from vacancy_monitor.task_router import TaskType, route_order_task


def _order(text: str, category: str):
    return make_order_from_post(
        Post(
            source="freelancehunt.com/projects.rss",
            post_id=f"freelancehunt.com/projects.rss:https://freelancehunt.com/project/task/{abs(hash((text, category))) % 100000}.html",
            url="https://freelancehunt.com/project/task/123456.html",
            text=text,
            published_at="2026-06-26T12:00:00+03:00",
        ),
        category=category,
        risks=[],
    )


def test_routes_telegram_bot_before_secondary_spreadsheet_mentions():
    route = route_order_task(
        _order("Нужен Telegram-бот для заявок с записью в Google Sheets.", "Telegram-боты")
    )

    assert route.task_type == TaskType.TELEGRAM_BOT
    assert route.verifier_profile == "code"
    assert route.confidence >= 0.7


def test_routes_parser_and_dashboard_as_distinct_task_types():
    parser_route = route_order_task(_order("Нужен парсер каталога с выгрузкой в CSV.", "Автоматизации/парсеры"))
    dashboard_route = route_order_task(_order("Собрать дашборд по продажам в Google Sheets.", "Таблицы и дашборды"))

    assert parser_route.task_type == TaskType.PARSER
    assert parser_route.verifier_profile == "code"
    assert dashboard_route.task_type == TaskType.DASHBOARD
    assert dashboard_route.verifier_profile == "spreadsheet"


def test_routes_content_website_and_integration():
    assert route_order_task(_order("Написать текст для лендинга на 3000 знаков.", "Тексты/контент")).task_type == TaskType.CONTENT
    assert route_order_task(_order("Сверстать небольшой сайт на HTML/CSS.", "Сайты")).task_type == TaskType.WEBSITE
    assert route_order_task(_order("Интеграция CRM с API и webhook.", "Интеграции")).task_type == TaskType.INTEGRATION
