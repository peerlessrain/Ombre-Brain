from diary_store import DiaryStore


def test_diary_store_keeps_full_text_and_owner_isolation(tmp_path):
    store = DiaryStore(str(tmp_path))
    g_entry = store.append(
        content="第一段。\n\n第二段完整保留。",
        title="学会分气泡",
        entry_date="2026-07-13",
        tags=["微信", "第一次"],
        agent_id="g",
        relationship_line="g_line",
        source_module="cyberboss",
    )
    store.append(
        content="小克的日记。",
        entry_date="2026-07-13",
        agent_id="claude",
        relationship_line="claude_line",
    )

    assert g_entry["content"] == "第一段。\n\n第二段完整保留。"
    assert g_entry["type"] == "diary"
    assert g_entry["scope"] == "agent_private"
    assert store.list_entries(agent_id="g", relationship_line="g_line") == [g_entry]
    assert len(store.list_entries(agent_id="claude", relationship_line="claude_line")) == 1
    assert list((tmp_path / "diary" / "g" / "g_line" / "2026").glob("2026-07-13_*.md"))


def test_diary_store_validates_owner_date_and_range(tmp_path):
    store = DiaryStore(str(tmp_path))
    for day in ("2026-07-11", "2026-07-13", "2026-07-12"):
        store.append(
            content=day,
            entry_date=day,
            agent_id="g",
            relationship_line="g_line",
        )

    rows = store.list_entries(
        agent_id="g",
        relationship_line="g_line",
        date_from="2026-07-12",
        date_to="2026-07-13",
    )
    assert [row["date"] for row in rows] == ["2026-07-13", "2026-07-12"]

    try:
        store.append(
            content="wrong owner",
            agent_id="g",
            relationship_line="claude_line",
        )
    except ValueError as exc:
        assert "不匹配" in str(exc)
    else:
        raise AssertionError("owner mismatch must be rejected")

    try:
        store.append(
            content="bad date",
            entry_date="2026-02-30",
            agent_id="g",
            relationship_line="g_line",
        )
    except ValueError as exc:
        assert "有效" in str(exc)
    else:
        raise AssertionError("invalid calendar date must be rejected")
