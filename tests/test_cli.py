from vacancy_monitor.cli import run_monitor
from vacancy_monitor.models import Post
from vacancy_monitor.state import SeenState


def suitable_post(post_id: str) -> Post:
    return Post(
        source="sample",
        post_id=post_id,
        url=f"https://t.me/sample/{post_id.rsplit('/', 1)[-1]}",
        text="Нужен лендинг на Tilda для курса, бюджет 15000.",
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
