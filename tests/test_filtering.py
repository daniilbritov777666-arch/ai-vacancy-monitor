from vacancy_monitor.filtering import evaluate_post, format_match_message
from vacancy_monitor.models import Post


def make_post(text: str) -> Post:
    return Post(
        source="test",
        post_id="test/1",
        url="https://t.me/s/test/1",
        text=text,
        published_at="2026-05-28T10:00:00+00:00",
    )


def test_rejects_plain_website_task_outside_current_scope():
    post = make_post(
        "Нужен лендинг на Tilda для онлайн-школы. Есть структура, оплатим 15000, "
        "можно без сложного кода, важно быстро собрать и оформить."
    )

    result = evaluate_post(post)

    assert result.accepted is False
    assert "не IT-заказ" in result.risks


def test_rejects_senior_fulltime_developer_vacancy():
    post = make_post(
        "Ищем Senior Python Backend Developer fulltime в офис. Опыт 5+ лет, "
        "Kubernetes, highload, микросервисы."
    )

    result = evaluate_post(post)

    assert result.accepted is False
    assert "senior/middle/fulltime" in result.risks


def test_rejects_suspicious_sales_without_fixed_pay():
    post = make_post(
        "Нужны люди в продажи без оклада, доход только процент, вложения окупаются быстро."
    )

    result = evaluate_post(post)

    assert result.accepted is False
    assert "нет фиксированной оплаты" in result.risks


def test_rejects_copywriting_and_smm_tasks():
    post = make_post(
        "Разовая задача: написать 10 постов для Telegram и сделать SMM-контент-план. "
        "Оплата 7000 руб."
    )

    result = evaluate_post(post)

    assert result.accepted is False
    assert "контент/smm/маркетинг" in result.risks


def test_rejects_long_term_remote_roles_even_when_ai_related():
    post = make_post(
        "Постоянная удаленная работа 5/2: вести AI-контент и Telegram Ads, оклад 60000 руб."
    )

    result = evaluate_post(post)

    assert result.accepted is False
    assert "долгосрочная занятость" in result.risks


def test_accepts_one_off_automation_task():
    post = make_post(
        "Разовая задача: сделать Telegram-бота для приема заявок, интеграция с Google Sheets, "
        "оплата 15000 руб., срок 3 дня."
    )

    result = evaluate_post(post)

    assert result.accepted is True
    assert "боты" in result.reasons
    assert "автоматизация/интеграции" in result.reasons


def test_rejects_technical_task_when_it_is_long_term_support():
    post = make_post(
        "Нужен специалист по Битрикс24 на постоянную поддержку: мелкие доработки каждый месяц, "
        "оплата договорная."
    )

    result = evaluate_post(post)

    assert result.accepted is False
    assert "долгосрочная занятость" in result.risks


def test_rejects_platform_limit_bypass_tasks():
    post = make_post(
        "Сгенерировать 900 сервисных ключей для API Вконтакте. Нужны дополнительные "
        "ключи для увеличения скорости парсинга, через любой аккаунт зайти в раздел разработчиков. "
        "Бюджет 5000 руб."
    )

    result = evaluate_post(post)

    assert result.accepted is False
    assert "обход ограничений платформ" in result.risks


def test_rejects_marketplace_product_selection_vacancy():
    post = make_post(
        "Требуется специалист по подбору товаров для маркетплейсов. Задачи: находить "
        "востребованные товары, искать поставщиков, заносить данные в рабочие таблицы. "
        "Доход: от 70 000 ₽, свободный график, обучение предоставляется, перспективы роста."
    )

    result = evaluate_post(post)

    assert result.accepted is False
    assert "постоянная вакансия/подработка" in result.risks
    assert "не IT-заказ" in result.risks


def test_rejects_pc_support_not_project_delivery():
    post = make_post(
        "Пропал интернет. Без видимой причины перестали открываться все сайты. "
        "Бюджет 500 руб."
    )

    result = evaluate_post(post)

    assert result.accepted is False
    assert "не IT-заказ" in result.risks


def test_rejects_word_formatting_without_spreadsheet_deliverable():
    post = make_post(
        "Режактиров WORD файла. Есть ворд документ. Нужно оформить таблицу. "
        "Бюджет 1000 руб."
    )

    result = evaluate_post(post)

    assert result.accepted is False
    assert "не IT-заказ" in result.risks


def test_rejects_autocad_drawing_edits():
    post = make_post("Внести изменения в чертежи АР AutoCAD, кладочные планы, окна. Оплата 7000 руб.")

    result = evaluate_post(post)

    assert result.accepted is False
    assert "не IT-заказ" in result.risks


def test_rejects_call_listening_and_table_filling():
    post = make_post("Прослушать звонки и заполнить таблицу по шаблону. Оплата 5000 руб.")

    result = evaluate_post(post)

    assert result.accepted is False
    assert "не IT-заказ" in result.risks


def test_rejects_manual_copy_paste_and_data_entry():
    post = make_post(
        "Простая работа по копированию и вставке данных. Задачи ввода данных в Excel. "
        "Бюджет 700 UAH."
    )

    result = evaluate_post(post)

    assert result.accepted is False
    assert "не IT-заказ" in result.risks


def test_rejects_legal_claim_work():
    post = make_post("Подать в суд на туркомпанию, работа за процент от полученного без предоплаты.")

    result = evaluate_post(post)

    assert result.accepted is False
    assert "не IT-заказ" in result.risks


def test_rejects_legal_claim_work_even_with_documents_and_amount():
    post = make_post(
        "Подача в суд на туркомпанию. Оплатили тур стоимостью 302 000 руб., "
        "есть документы подписанные от турагента."
    )

    result = evaluate_post(post)

    assert result.accepted is False
    assert "не IT-заказ" in result.risks


def test_rejects_html_site_edit_without_automation_scope():
    post = make_post("Отредактировать HTML сайт, поправить блоки и тексты. Оплата 3000 руб.")

    result = evaluate_post(post)

    assert result.accepted is False
    assert "не IT-заказ" in result.risks


def test_rejects_article_proofreading_without_it_deliverable():
    post = make_post("Проверка и редактура английской версии статьи. Оплата 4000 руб.")

    result = evaluate_post(post)

    assert result.accepted is False
    assert "контент/smm/маркетинг" in result.risks


def test_accepts_google_sheets_dashboard_task():
    post = make_post(
        "Разовая задача: собрать дашборд в Google Sheets, формулы и отчет по заявкам. "
        "Бюджет 12000 руб."
    )

    result = evaluate_post(post)

    assert result.accepted is True
    assert "таблицы/дашборды" in result.reasons


def test_accepts_freelancehunt_telegram_bot_task_with_uah_budget():
    post = make_post(
        "Потрібно розробити Telegram-бота для прийому заявок. Оплата 3000UAH, "
        "разовий проект."
    )

    result = evaluate_post(post)

    assert result.accepted is True
    assert "боты" in result.reasons
    assert "есть сигнал оплаты" in result.reasons


def test_accepts_freelancehunt_parser_task_with_eur_budget():
    post = make_post("Потрібно зробити парсер відкритого каталогу товарів. 150EUR за готовий результат.")

    result = evaluate_post(post)

    assert result.accepted is True
    assert "автоматизация/интеграции" in result.reasons
    assert "есть сигнал оплаты" in result.reasons


def test_rejects_cloudflare_bot_attack_task_not_telegram_bot_work():
    post = make_post("Необходимо настроить Cloudflare от бот-атак, консультация. 1000UAH.")

    result = evaluate_post(post)

    assert result.accepted is False
    assert "администрирование/защита сайта" in result.risks


def test_accepts_one_off_content_task_with_fixed_deliverable():
    post = make_post(
        "Разовая задача: подготовить текст для лендинга Telegram-бота и описание сценариев "
        "автоматизации. Бюджет 8000 руб."
    )

    result = evaluate_post(post)

    assert result.accepted is True
    assert "тексты/контент" in result.reasons


def test_rejects_non_content_projects_that_only_mention_text_or_documents():
    posts = [
        make_post(
            "Нужен верстальщик под Amazon KDP и PDF. Книга содержит 60 страниц текста. "
            "Бюджет 150 EUR."
        ),
        make_post(
            "Найти в Польше фирму, которая сделает сертификацию оборудования. "
            "Все требования описаны в документе. Бюджет 2500 UAH."
        ),
        make_post(
            "Создать 3D визуализацию тестового оборудования. Все детали в документе. "
            "Бюджет 3000 UAH."
        ),
    ]

    results = [evaluate_post(post) for post in posts]

    assert all(result.accepted is False for result in results)
    assert all("тексты/контент" not in result.reasons for result in results)


def test_rejects_physical_funnel_as_crm_signal():
    post = make_post(
        "Найти фирму для сертификации установки: монета вращается по поверхности воронки. "
        "Бюджет 2500 UAH."
    )

    result = evaluate_post(post)

    assert result.accepted is False
    assert "crm/no-code" not in result.reasons


def test_rejects_ukrainian_word_robota_as_crm_robot_signal():
    post = make_post("Разова робота: перенести коробки на склад. Оплата 1000 UAH.")

    result = evaluate_post(post)

    assert result.accepted is False
    assert "crm/no-code" not in result.reasons


def test_formats_actionable_telegram_message():
    post = make_post("Нужно настроить CRM Bitrix24: воронка, роботы, триггеры. Бюджет 20000.")
    result = evaluate_post(post)

    message = format_match_message(post, result)

    assert "Подходит" in message
    assert "Что я помогу сделать" in message
    assert "Отклик заказчику" in message
    assert post.url in message
