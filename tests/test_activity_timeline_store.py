from activity_timeline_store import ActivityTimelineStore


def test_activity_timeline_store_upserts_day_and_isolates_owner(tmp_path):
    store = ActivityTimelineStore(str(tmp_path))
    first = store.sync_day(
        date="2026-07-13",
        events=[{"id": "a", "startAt": "2026-07-13T01:00:00Z", "endAt": "2026-07-13T02:00:00Z", "title": "吃饭"}],
        agent_id="g",
        relationship_line="g_line",
    )
    assert first["event_count"] == 1
    store.sync_day(
        date="2026-07-13",
        events=[{"id": "b", "startAt": "2026-07-13T03:00:00Z", "endAt": "2026-07-13T04:00:00Z", "title": "改代码"}],
        agent_id="g",
        relationship_line="g_line",
        status="final",
    )
    days = store.list_days(agent_id="g", relationship_line="g_line")
    assert len(days) == 1
    assert days[0]["events"][0]["id"] == "b"
    assert days[0]["status"] == "final"
    assert store.list_days(agent_id="claude", relationship_line="claude_line") == []


def test_activity_timeline_store_validates_input(tmp_path):
    store = ActivityTimelineStore(str(tmp_path))
    try:
        store.sync_day(date="2026-02-30", events=[], agent_id="g", relationship_line="g_line")
        assert False, "invalid date should fail"
    except ValueError:
        pass
    try:
        store.sync_day(date="2026-07-13", events=[{}], agent_id="g", relationship_line="g_line")
        assert False, "missing times should fail"
    except ValueError:
        pass
