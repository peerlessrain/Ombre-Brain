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


def test_diary_update_patches_only_supplied_fields_and_can_move_date(tmp_path):
    store = DiaryStore(str(tmp_path))
    entry = store.append(
        content="原文",
        title="原标题",
        entry_date="2026-07-13",
        mood="开心",
        tags=["保留", "旧标签"],
        agent_id="g",
        relationship_line="g_line",
        source_agent_model="old-model",
    )

    updated = store.update(
        entry["id"],
        agent_id="g",
        relationship_line="g_line",
        entry_date="2026-07-14",
        content="修正后的原文",
        tags=[],
    )

    assert updated["id"] == entry["id"]
    assert updated["date"] == "2026-07-14"
    assert updated["content"] == "修正后的原文"
    assert updated["tags"] == []
    assert updated["title"] == "原标题"
    assert updated["mood"] == "开心"
    assert updated["source_agent_model"] == "old-model"
    assert not list((tmp_path / "diary" / "g" / "g_line" / "2026").glob(f"2026-07-13_{entry['id']}.md"))
    assert list((tmp_path / "diary" / "g" / "g_line" / "2026").glob(f"2026-07-14_{entry['id']}.md"))


def test_diary_append_same_day_and_exact_owner_isolated_delete(tmp_path):
    store = DiaryStore(str(tmp_path))
    first = store.append(
        content="同一天的第一篇",
        entry_date="2026-07-13",
        agent_id="g",
        relationship_line="g_line",
    )
    second = store.append(
        content="同一天的第二篇",
        entry_date="2026-07-13",
        agent_id="g",
        relationship_line="g_line",
    )
    assert first["id"] != second["id"]
    assert len(store.list_entries(agent_id="g", relationship_line="g_line")) == 2

    assert store.delete(
        first["id"],
        agent_id="claude",
        relationship_line="claude_line",
    ) is None
    assert store.get(first["id"], agent_id="g", relationship_line="g_line")
    assert store.delete(first["id"], agent_id="g", relationship_line="g_line") == first["id"]
    assert store.get(first["id"], agent_id="g", relationship_line="g_line") is None
    assert store.get(second["id"], agent_id="g", relationship_line="g_line") == second
