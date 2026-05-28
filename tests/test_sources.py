from vacancy_monitor.sources import parse_rss_xml, parse_telegram_html


HTML = """
<div class="tgme_widget_message" data-post="sample/42">
  <a class="tgme_widget_message_date" href="https://t.me/sample/42">
    <time datetime="2026-05-28T09:00:00+00:00"></time>
  </a>
  <div class="tgme_widget_message_text">
    Нужен Telegram бот для записи клиентов.<br/>Бюджет 10000.
  </div>
</div>
<div class="tgme_widget_message" data-post="sample/43">
  <a class="tgme_widget_message_date" href="https://t.me/sample/43"></a>
  <div class="tgme_widget_message_text">Senior Java fulltime.</div>
</div>
"""


def test_parse_telegram_html_extracts_posts():
    posts = parse_telegram_html("sample", HTML)

    assert len(posts) == 2
    assert posts[0].source == "sample"
    assert posts[0].post_id == "sample/42"
    assert posts[0].url == "https://t.me/sample/42"
    assert "Telegram бот" in posts[0].text
    assert "Бюджет 10000" in posts[0].text
    assert posts[0].published_at == "2026-05-28T09:00:00+00:00"


def test_parse_rss_xml_extracts_project_posts():
    xml = """
    <rss><channel>
      <item>
        <title>Сделать лендинг на Tilda</title>
        <link>https://example.com/project/1</link>
        <description>Разовая задача, бюджет 10000 руб.</description>
        <pubDate>Thu, 28 May 2026 11:30:00 +0000</pubDate>
        <guid>project-1</guid>
      </item>
    </channel></rss>
    """

    posts = parse_rss_xml("test-rss", xml)

    assert len(posts) == 1
    assert posts[0].source == "test-rss"
    assert posts[0].post_id == "test-rss:project-1"
    assert posts[0].url == "https://example.com/project/1"
    assert "Сделать лендинг" in posts[0].text
    assert "бюджет 10000" in posts[0].text
