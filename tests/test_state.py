from vacancy_monitor.state import SeenState


def test_seen_state_round_trips_ids(tmp_path):
    path = tmp_path / "seen_posts.json"
    state = SeenState.load(path)

    assert state.contains("sample/1") is False

    state.add("sample/1")
    state.save(path)

    loaded = SeenState.load(path)
    assert loaded.contains("sample/1") is True
