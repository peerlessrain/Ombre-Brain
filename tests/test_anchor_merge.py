import importlib
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_grow_does_not_merge_into_anchor_bucket(tmp_path, monkeypatch):
    buckets_dir = tmp_path / "buckets"
    monkeypatch.setenv("OMBRE_BUCKETS_DIR", str(buckets_dir))
    monkeypatch.setenv("OMBRE_API_KEY", "")
    monkeypatch.setenv("OMBRE_HOOK_SKIP", "1")

    import server

    server = importlib.reload(server)

    async def noop_started():
        return None

    async def fake_analyze(content):
        return {
            "domain": ["verify"],
            "valence": 0.5,
            "arousal": 0.3,
            "importance": 5,
            "tags": ["verify"],
            "suggested_name": "anchor_merge_probe",
        }

    server.decay_engine.ensure_started = noop_started
    server.dehydrator.analyze = AsyncMock(side_effect=fake_analyze)
    server.dehydrator.merge = AsyncMock(return_value="SHOULD_NOT_MERGE")
    server.embedding_engine.generate_and_store = AsyncMock(return_value=None)

    anchor_id = await server.bucket_mgr.create(
        content="ANCHOR_ORIGINAL_CONTENT",
        tags=["verify"],
        importance=8,
        domain=["verify"],
        valence=0.5,
        arousal=0.3,
        name="anchor probe",
    )
    anchor_result = await server.bucket_mgr.set_anchor(anchor_id, True)
    assert anchor_result["ok"]
    anchor_bucket = await server.bucket_mgr.get(anchor_id)
    anchor_bucket["score"] = 100
    server.bucket_mgr.search = AsyncMock(return_value=[anchor_bucket])

    result = await server.grow("ANCHOR_NEW_CONTENT", agent_id="claude", relationship_line="claude_line")

    server.dehydrator.merge.assert_not_called()
    updated_anchor = await server.bucket_mgr.get(anchor_id)
    assert updated_anchor["content"] == "ANCHOR_ORIGINAL_CONTENT"
    assert "ANCHOR_NEW_CONTENT" not in updated_anchor["content"]

    all_buckets = await server.bucket_mgr.list_all(include_archive=True)
    created = [b for b in all_buckets if b["content"] == "ANCHOR_NEW_CONTENT"]
    assert len(created) == 1
    assert created[0]["id"] != anchor_id
    assert "新建" in result
