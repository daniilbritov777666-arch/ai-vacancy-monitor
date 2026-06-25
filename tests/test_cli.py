from vacancy_monitor.cli import run_monitor
from vacancy_monitor.models import Post
from vacancy_monitor.state import SeenState


def suitable_post(post_id: str) -> Post:
    source, number = post_id.rsplit("/", 1)
    return Post(
        source=source,
        post_id=post_id,
        url=f"https://example.com/{post_id}",
        text="Нужен Telegram-бот для приема заявок и запись в Google Sheets, бюджет 15000.",
        published_at=None,
    )


def test_first_run_seeds_posts_without_sending(tmp_path):
    sent = []
    state_path = tmp_path / "seen_posts.json"

    summary = run_monitor(
        channels=["sample"],
        state_path=state_path,
        fetch_posts=lambda channel: [suitable_post("sample/1")],
        send_message=sent.append,
        send_first_run=False,
    )

    assert summary.sent == 0
    assert summary.seeded == 1
    assert sent == []
    assert SeenState.load(state_path).contains("sample/1") is True


def test_sends_only_new_matching_posts(tmp_path):
    sent = []
    state_path = tmp_path / "seen_posts.json"
    state = SeenState({"sample/1"})
    state.save(state_path)

    summary = run_monitor(
        channels=["sample"],
        state_path=state_path,
        fetch_posts=lambda channel: [suitable_post("sample/1"), suitable_post("sample/2")],
        send_message=sent.append,
        send_first_run=False,
    )

    assert summary.sent == 1
    assert "sample/2" in sent[0]
    assert SeenState.load(state_path).contains("sample/2") is True


def test_sends_new_matching_rss_posts(tmp_path):
    sent = []
    state_path = tmp_path / "seen_posts.json"
    SeenState({"sample/1"}).save(state_path)

    summary = run_monitor(
        channels=[],
        rss_feeds=["https://example.com/rss"],
        state_path=state_path,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [suitable_post("rss/1")],
        send_message=sent.append,
        send_first_run=False,
    )

    assert summary.sent == 1
    assert "rss/1" in sent[0]


def test_sends_new_matching_public_project(tmp_path):
    matched = []
    state_path = tmp_path / "seen_posts.json"
    SeenState({"existing"}).save(state_path)

    summary = run_monitor(
        channels=[],
        public_project_sources=["freelance_ru"],
        state_path=state_path,
        fetch_posts=lambda channel: [],
        fetch_public_posts=lambda source: [suitable_post("freelance_ru/2")],
        send_message=lambda text: None,
        send_first_run=False,
        on_match=lambda post, result: matched.append(post.post_id),
    )

    assert summary.sent == 1
    assert matched == ["freelance_ru/2"]


def test_public_source_failure_does_not_block_other_sources(tmp_path):
    matched = []
    state_path = tmp_path / "seen_posts.json"
    SeenState({"existing"}).save(state_path)

    def fetch_public(source):
        if source == "pchel":
            raise RuntimeError("offline")
        return [suitable_post("freelance_ru/3")]

    summary = run_monitor(
        channels=[],
        public_project_sources=["pchel", "freelance_ru"],
        state_path=state_path,
        fetch_posts=lambda channel: [],
        fetch_public_posts=fetch_public,
        send_message=lambda text: None,
        send_first_run=False,
        on_match=lambda post, result: matched.append(post.post_id),
    )

    assert summary.errors == 1
    assert matched == ["freelance_ru/3"]


def test_run_monitor_processes_stronger_matches_before_lower_priority_posts(tmp_path):
    matched = []
    state_path = tmp_path / "seen_posts.json"
    SeenState({"existing"}).save(state_path)
    high_priority = Post(
        source="freelancehunt",
        post_id="freelancehunt/high",
        url="https://example.com/high",
        text="Разовая задача: Telegram-бот для заявок, API интеграция и Google Sheets. Бюджет 15000 руб.",
        published_at=None,
    )
    low_priority = Post(
        source="freelancehunt",
        post_id="freelancehunt/low",
        url="https://example.com/low",
        text="Разовая задача: подготовить текст для страницы. Бюджет 8000 руб.",
        published_at=None,
    )

    summary = run_monitor(
        channels=[],
        rss_feeds=["freelancehunt"],
        state_path=state_path,
        fetch_posts=lambda channel: [],
        fetch_rss_posts=lambda feed: [high_priority, low_priority],
        send_message=lambda text: None,
        send_first_run=False,
        on_match=lambda post, result: matched.append((post.post_id, result.score)),
    )

    assert summary.sent == 2
    assert [post_id for post_id, _score in matched] == ["freelancehunt/high", "freelancehunt/low"]
    assert matched[0][1] > matched[1][1]
