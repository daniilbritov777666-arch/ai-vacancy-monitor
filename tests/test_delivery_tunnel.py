from vacancy_monitor.delivery_tunnel import parse_trycloudflare_url


def test_parse_trycloudflare_url_from_cloudflared_log_line():
    line = "INF +--------------------------------------------------------------------------------------------+ https://alpha-beta.trycloudflare.com"

    assert parse_trycloudflare_url(line) == "https://alpha-beta.trycloudflare.com"


def test_parse_trycloudflare_url_returns_none_without_url():
    assert parse_trycloudflare_url("starting tunnel") is None
