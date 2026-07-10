import importlib
from unittest.mock import AsyncMock

import pytest


def load_isolated_server(tmp_path, monkeypatch):
    buckets_dir = tmp_path / "buckets"
    monkeypatch.setenv("OMBRE_BUCKETS_DIR", str(buckets_dir))
    monkeypatch.setenv("OMBRE_API_KEY", "")
    monkeypatch.setenv("OMBRE_HOOK_SKIP", "1")
    import server
    return importlib.reload(server)


async def noop_started():
    return None


async def fake_analyze(content):
    return {
        "domain": ["verify"],
        "valence": 0.5,
        "arousal": 0.3,
        "importance": 5,
        "tags": ["verify"],
        "suggested_name": "verify_bucket",
    }


class FakeRequest:
    def __init__(self, body, cookies=None):
        self.path_params = {"bucket_id": body.pop("_bucket_id")}
        self.cookies = cookies or {}
        self.headers = {}
        self._body = body

    async def json(self):
        return self._body


@pytest.mark.asyncio
async def test_hold_always_creates_new_bucket_and_never_merges(tmp_path, monkeypatch):
    server = load_isolated_server(tmp_path, monkeypatch)
    server.decay_engine.ensure_started = noop_started
    server.dehydrator.analyze = AsyncMock(side_effect=fake_analyze)
    server.dehydrator.merge = AsyncMock(return_value="SHOULD_NOT_MERGE")
    server.embedding_engine.generate_and_store = AsyncMock(return_value=None)

    old_id = await server.bucket_mgr.create(
        content="OLD_CONTENT",
        tags=["verify"],
        importance=5,
        domain=["verify"],
        valence=0.5,
        arousal=0.3,
        name="old",
        agent_id="claude",
        relationship_line="claude_line",
        scope="agent_private",
        visibility="same_line",
    )
    old_bucket = await server.bucket_mgr.get(old_id)
    old_bucket["score"] = 100
    server.bucket_mgr.search = AsyncMock(return_value=[old_bucket])

    result = await server.hold("NEW_CONTENT", agent_id="claude", relationship_line="claude_line")

    server.dehydrator.merge.assert_not_called()
    unchanged = await server.bucket_mgr.get(old_id)
    assert unchanged["content"] == "OLD_CONTENT"
    created = [b for b in await server.bucket_mgr.list_all(include_archive=True) if b["content"] == "NEW_CONTENT"]
    assert len(created) == 1
    assert "新建" in result
    assert f"可能与已有 bucket {old_id} 相关" in result


@pytest.mark.asyncio
async def test_glm_hold_defaults_to_interim_manual_only(tmp_path, monkeypatch):
    server = load_isolated_server(tmp_path, monkeypatch)
    server.decay_engine.ensure_started = noop_started
    server.dehydrator.analyze = AsyncMock(side_effect=fake_analyze)
    server.embedding_engine.generate_and_store = AsyncMock(return_value=None)
    server.bucket_mgr.search = AsyncMock(return_value=[])

    await server.hold(
        "GLM_CONTENT",
        agent_id="glm",
        relationship_line="glm_interim",
    )

    buckets = await server.bucket_mgr.list_all(include_archive=True)
    created = next(b for b in buckets if b["content"] == "GLM_CONTENT")
    meta = created["metadata"]
    assert meta["agent_id"] == "glm"
    assert meta["relationship_line"] == "glm_interim"
    assert meta["visibility"] == "manual_only"


@pytest.mark.asyncio
async def test_auto_merge_safety_gate_blocks_sensitive_buckets(tmp_path, monkeypatch):
    server = load_isolated_server(tmp_path, monkeypatch)
    owner = {"agent_id": "g", "relationship_line": "g_line"}

    cross_id = await server.bucket_mgr.create(
        content="cross",
        tags=[],
        importance=5,
        domain=["verify"],
        valence=0.5,
        arousal=0.3,
        name="cross",
        agent_id="claude",
        relationship_line="claude_line",
        scope="agent_private",
        visibility="same_line",
    )
    high_id = await server.bucket_mgr.create(
        content="high",
        tags=[],
        importance=9,
        domain=["verify"],
        valence=0.5,
        arousal=0.3,
        name="high",
        agent_id="g",
        relationship_line="g_line",
        scope="agent_private",
        visibility="same_line",
    )
    i_id = await server.bucket_mgr.create(
        content="i",
        tags=["__i__"],
        importance=6,
        domain=["self"],
        valence=0.5,
        arousal=0.3,
        name="i",
        bucket_type="i",
        agent_id="g",
        relationship_line="g_line",
        scope="agent_private",
        visibility="same_agent",
    )
    letter_id = await server.bucket_mgr.create(
        content="letter",
        tags=["__letter__"],
        importance=10,
        domain=["letter"],
        valence=0.5,
        arousal=0.3,
        name="letter",
        bucket_type="letter",
        agent_id="g",
        relationship_line="g_line",
        scope="agent_private",
        visibility="same_line",
    )
    anchor_id = await server.bucket_mgr.create(
        content="anchor",
        tags=[],
        importance=5,
        domain=["verify"],
        valence=0.5,
        arousal=0.3,
        name="anchor",
        agent_id="g",
        relationship_line="g_line",
        scope="agent_private",
        visibility="same_line",
    )
    assert (await server.bucket_mgr.set_anchor(anchor_id, True))["ok"]
    legacy_id = await server.bucket_mgr.create(
        content="legacy",
        tags=[],
        importance=5,
        domain=["verify"],
        valence=0.5,
        arousal=0.3,
        name="legacy",
    )

    for bid in (cross_id, high_id, i_id, letter_id, anchor_id, legacy_id):
        bucket = await server.bucket_mgr.get(bid)
        assert server._can_auto_merge_into(bucket, owner) is False


@pytest.mark.asyncio
async def test_i_letter_anchor_update_delete_tools(tmp_path, monkeypatch):
    server = load_isolated_server(tmp_path, monkeypatch)
    server.embedding_engine.generate_and_store = AsyncMock(return_value=None)

    i_id = await server.bucket_mgr.create(
        content="I old",
        tags=["__i__", "aspect:values"],
        importance=6,
        domain=["self"],
        valence=0.5,
        arousal=0.3,
        name="i old",
        bucket_type="i",
        agent_id="claude",
        relationship_line="claude_line",
        scope="agent_private",
        visibility="same_agent",
    )
    assert "已修改" in await server.i_update(i_id, title="I new", content="I new content", aspect="style", agent_id="claude")
    i_bucket = await server.bucket_mgr.get(i_id)
    assert i_bucket["metadata"]["name"] == "I new"
    assert i_bucket["content"] == "I new content"
    assert "aspect:style" in i_bucket["metadata"]["tags"]

    letter_id = await server.bucket_mgr.create(
        content="letter old",
        tags=["__letter__"],
        importance=10,
        domain=["letter"],
        valence=0.5,
        arousal=0.3,
        name="letter old",
        bucket_type="letter",
        agent_id="claude",
        relationship_line="claude_line",
        scope="agent_private",
        visibility="same_line",
    )
    assert "已修改" in await server.letter_update(letter_id, title="letter new", content="letter new content", agent_id="claude")
    letter_bucket = await server.bucket_mgr.get(letter_id)
    assert letter_bucket["metadata"]["title"] == "letter new"
    assert letter_bucket["content"] == "letter new content"

    anchor_id = await server.bucket_mgr.create(
        content="anchor old",
        tags=["a"],
        importance=8,
        domain=["anchor"],
        valence=0.5,
        arousal=0.3,
        name="anchor old",
        agent_id="claude",
        relationship_line="claude_line",
        scope="agent_private",
        visibility="same_line",
    )
    assert (await server.bucket_mgr.set_anchor(anchor_id, True))["ok"]
    assert "已修改" in await server.anchor_update(anchor_id, name="anchor new", content="anchor new content", agent_id="claude")
    anchor_bucket = await server.bucket_mgr.get(anchor_id)
    assert anchor_bucket["metadata"]["name"] == "anchor new"
    assert anchor_bucket["content"] == "anchor new content"

    assert "已删除 I" in await server.i_delete(i_id, agent_id="claude")
    assert "已删除 letter" in await server.letter_delete(letter_id, agent_id="claude")
    assert "已删除 anchor" in await server.anchor_delete(anchor_id, agent_id="claude")


@pytest.mark.asyncio
async def test_dashboard_patch_updates_ownership_metadata(tmp_path, monkeypatch):
    server = load_isolated_server(tmp_path, monkeypatch)
    bid = await server.bucket_mgr.create(
        content="patch content",
        tags=[],
        importance=5,
        domain=["verify"],
        valence=0.5,
        arousal=0.3,
        name="patch",
        agent_id="claude",
        relationship_line="claude_line",
        scope="agent_private",
        visibility="same_line",
    )
    token = server._create_session()
    request = FakeRequest({
        "_bucket_id": bid,
        "agent_id": "g",
        "relationship_line": "g_line",
        "scope": "agent_private",
        "visibility": "same_line",
        "notes": "moved by test",
    }, cookies={"ombre_session": token})

    response = await server.api_bucket_update(request)

    assert response.status_code == 200
    updated = await server.bucket_mgr.get(bid)
    meta = updated["metadata"]
    assert meta["agent_id"] == "g"
    assert meta["relationship_line"] == "g_line"
    assert meta["scope"] == "agent_private"
    assert meta["visibility"] == "same_line"
    assert meta["notes"] == "moved by test"


@pytest.mark.asyncio
async def test_retired_ownership_values_are_rejected_without_touching_old_data(tmp_path, monkeypatch):
    server = load_isolated_server(tmp_path, monkeypatch)

    with pytest.raises(ValueError):
        await server.bucket_mgr.create(content="shared", agent_id="ayu", relationship_line="shared")
    with pytest.raises(ValueError):
        await server.bucket_mgr.create(content="project", agent_id="system", relationship_line="project", scope="project")
    with pytest.raises(ValueError):
        await server.hold("invalid", agent_id="claude", relationship_line="claude_line", visibility="shared")

    legacy_shared = {
        "metadata": {
            "agent_id": "ayu",
            "relationship_line": "shared",
            "scope": "shared_about_ayu",
            "visibility": "shared",
        }
    }
    legacy_project = {
        "metadata": {
            "agent_id": "system",
            "relationship_line": "project",
            "scope": "project",
            "visibility": "same_line",
        }
    }
    claude_ctx = server._owner_context("claude", "claude_line")
    assert server._bucket_visible_to_context(legacy_shared, claude_ctx) is False
    assert server._bucket_visible_to_context(legacy_project, claude_ctx) is False


@pytest.mark.asyncio
async def test_dashboard_patch_rejects_retired_ownership_values(tmp_path, monkeypatch):
    server = load_isolated_server(tmp_path, monkeypatch)
    bid = await server.bucket_mgr.create(content="keep", agent_id="claude", relationship_line="claude_line")
    token = server._create_session()
    request = FakeRequest({
        "_bucket_id": bid,
        "agent_id": "ayu",
        "relationship_line": "shared",
        "scope": "shared_about_ayu",
        "visibility": "shared",
    }, cookies={"ombre_session": token})

    response = await server.api_bucket_update(request)

    assert response.status_code == 400
    unchanged = await server.bucket_mgr.get(bid)
    assert unchanged["metadata"]["agent_id"] == "claude"
    assert unchanged["metadata"]["relationship_line"] == "claude_line"
