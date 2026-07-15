import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def load_isolated_server(tmp_path, monkeypatch):
    buckets_dir = tmp_path / "buckets"
    monkeypatch.setenv("OMBRE_BUCKETS_DIR", str(buckets_dir))
    monkeypatch.setenv("OMBRE_API_KEY", "")
    monkeypatch.setenv("OMBRE_HOOK_SKIP", "1")
    import server
    return importlib.reload(server)


def test_owner_lock_injects_configured_identity_and_rejects_cross_line(tmp_path, monkeypatch):
    monkeypatch.setenv("OMBRE_AGENT_ID", "g")
    monkeypatch.setenv("OMBRE_RELATIONSHIP_LINE", "g_line")
    monkeypatch.setenv("OMBRE_ENFORCE_OWNER", "true")
    server = load_isolated_server(tmp_path, monkeypatch)

    assert server._owner_context() == {"agent_id": "g", "relationship_line": "g_line"}
    assert server._owner_context("g", "g_line") == {"agent_id": "g", "relationship_line": "g_line"}

    with pytest.raises(ValueError, match="拒绝跨脑区访问"):
        server._owner_context("claude", "claude_line")
    with pytest.raises(ValueError, match="拒绝跨关系线访问"):
        server._owner_context("g", "claude_line")


@pytest.mark.asyncio
async def test_dedicated_process_can_disable_decay_without_changing_default_behavior(tmp_path, monkeypatch):
    monkeypatch.setenv("OMBRE_DISABLE_DECAY", "true")
    server = load_isolated_server(tmp_path, monkeypatch)

    await server.decay_engine.ensure_started()

    assert server.decay_engine.is_running is False
    assert server.decay_engine.status == "disabled"


def fake_context_with_headers(**headers):
    request = SimpleNamespace(headers={key.lower(): value for key, value in headers.items()})
    request_context = SimpleNamespace(request=request)
    return SimpleNamespace(request_context=request_context)


def test_read_mode_uses_explicit_argument_then_connection_header(tmp_path, monkeypatch):
    server = load_isolated_server(tmp_path, monkeypatch)
    ctx = fake_context_with_headers(**{"X-Ombre-Read-Mode": "passive"})

    assert server._resolve_read_mode("", ctx) == "passive"
    assert server._resolve_read_mode("normal", ctx) == "normal"
    assert server._resolve_read_mode("", None) == "normal"
    with pytest.raises(ValueError, match="read_mode"):
        server._resolve_read_mode("frozen", ctx)


@pytest.mark.asyncio
async def test_pulse_reports_decay_state_and_read_mode(tmp_path, monkeypatch):
    server = load_isolated_server(tmp_path, monkeypatch)

    status = await server.pulse(agent_id="g", relationship_line="g_line", read_mode="passive")
    assert "衰减引擎: 尚未启动" in status
    assert "读取模式: passive" in status

    monkeypatch.setenv("OMBRE_DISABLE_DECAY", "true")
    disabled = await server.pulse(agent_id="g", relationship_line="g_line")
    assert "衰减引擎: 已禁用" in disabled

    monkeypatch.delenv("OMBRE_DISABLE_DECAY")
    server.decay_engine._running = True
    running = await server.pulse(agent_id="g", relationship_line="g_line")
    assert "衰减引擎: 运行中" in running
    server.decay_engine._running = False


@pytest.mark.asyncio
async def test_breath_passive_skips_touch_but_normal_read_touches(tmp_path, monkeypatch):
    server = load_isolated_server(tmp_path, monkeypatch)
    server.decay_engine.ensure_started = noop_started
    bucket_id = await server.bucket_mgr.create(
        content="SEARCHABLE_CONTENT",
        tags=["verify"],
        importance=5,
        domain=["verify"],
        valence=0.5,
        arousal=0.3,
        name="searchable",
        agent_id="g",
        relationship_line="g_line",
        scope="agent_private",
        visibility="same_line",
    )
    bucket = await server.bucket_mgr.get(bucket_id)
    server.bucket_mgr.search = AsyncMock(return_value=[bucket])
    server.bucket_mgr.touch = AsyncMock(return_value=True)
    server.embedding_engine.search_similar = AsyncMock(return_value=[])
    server.dehydrator.dehydrate = AsyncMock(return_value="SEARCHABLE_CONTENT")

    passive = await server.breath(
        query="SEARCHABLE",
        agent_id="g",
        relationship_line="g_line",
        read_mode="passive",
    )
    assert bucket_id in passive
    server.bucket_mgr.touch.assert_not_called()

    normal = await server.breath(
        query="SEARCHABLE",
        agent_id="g",
        relationship_line="g_line",
        read_mode="normal",
    )
    assert bucket_id in normal
    server.bucket_mgr.touch.assert_awaited_once_with(bucket_id)


@pytest.mark.asyncio
async def test_memory_touch_only_updates_visible_requested_buckets(tmp_path, monkeypatch):
    server = load_isolated_server(tmp_path, monkeypatch)
    own_id = await server.bucket_mgr.create(
        content="OWN",
        tags=[], importance=5, domain=["verify"], valence=0.5, arousal=0.3,
        agent_id="g", relationship_line="g_line", scope="agent_private", visibility="same_line",
    )
    other_id = await server.bucket_mgr.create(
        content="OTHER",
        tags=[], importance=5, domain=["verify"], valence=0.5, arousal=0.3,
        agent_id="claude", relationship_line="claude_line", scope="agent_private", visibility="same_line",
    )
    original_touch = server.bucket_mgr.touch
    server.bucket_mgr.touch = AsyncMock(side_effect=original_touch)

    result = await server.memory_touch(
        f"{own_id},{other_id}",
        agent_id="g",
        relationship_line="g_line",
    )

    server.bucket_mgr.touch.assert_awaited_once_with(own_id)
    assert own_id in result
    assert other_id in result


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
async def test_bucket_get_returns_exact_full_metadata_without_touch(tmp_path, monkeypatch):
    server = load_isolated_server(tmp_path, monkeypatch)
    bucket_id = await server.bucket_mgr.create(
        content="EXACT [[BODY]]",
        tags=["verify"], importance=6, domain=["verify"], valence=0.4, arousal=0.7,
        name="exact_bucket", agent_id="g", relationship_line="g_line",
        scope="agent_private", visibility="same_line", source_module="hold",
        source_agent_model="codex",
    )
    server.bucket_mgr.touch = AsyncMock(return_value=True)

    result = __import__("json").loads(await server.bucket_get(bucket_id, "g", "g_line"))

    assert result["status"] == "ok"
    assert result["bucket_id"] == bucket_id
    assert result["content"] == "EXACT [[BODY]]"
    assert result["semantic_review"]["title"] == "exact_bucket"
    assert result["semantic_review"]["domain"] == ["verify"]
    assert result["semantic_review"]["perspective"]["memory_owner_agent"] == "g"
    assert result["semantic_review"]["perspective"]["source_agent_model"] == "codex"
    assert result["semantic_review"]["perspective"]["stored_explicitly"] is False
    assert result["metadata"]["source_module"] == "hold"
    assert result["metadata"]["agent_id"] == "g"
    assert result["metadata"]["relationship_line"] == "g_line"
    server.bucket_mgr.touch.assert_not_called()

    forbidden = __import__("json").loads(
        await server.bucket_get(bucket_id, "claude", "claude_line")
    )
    assert forbidden["status"] == "forbidden"


@pytest.mark.asyncio
async def test_verified_hold_stops_on_duplicate_without_writing(tmp_path, monkeypatch):
    server = load_isolated_server(tmp_path, monkeypatch)
    server.decay_engine.ensure_started = noop_started
    old_id = await server.bucket_mgr.create(
        content="SAME CONTENT",
        tags=[], importance=5, domain=["verify"], valence=0.5, arousal=0.3,
        agent_id="g", relationship_line="g_line", scope="agent_private",
        visibility="same_line", source_module="hold",
    )

    result = __import__("json").loads(
        await server.verified_hold("SAME CONTENT", "g", "g_line", source_agent_model="codex")
    )

    assert result["status"] == "duplicate_candidates"
    assert result["written"] is False
    assert result["candidates"][0]["bucket_id"] == old_id
    assert result["candidates"][0]["exact_match"] is True
    buckets = await server.bucket_mgr.list_all(include_archive=True)
    assert len([b for b in buckets if b["content"] == "SAME CONTENT"]) == 1


@pytest.mark.asyncio
async def test_verified_hold_writes_once_and_returns_verified_full_bucket(tmp_path, monkeypatch):
    server = load_isolated_server(tmp_path, monkeypatch)
    server.decay_engine.ensure_started = noop_started
    server.dehydrator.analyze = AsyncMock(side_effect=fake_analyze)
    server.embedding_engine.generate_and_store = AsyncMock(return_value=None)
    server.bucket_mgr.search = AsyncMock(return_value=[])

    result = __import__("json").loads(
        await server.verified_hold(
            "NEW VERIFIED CONTENT",
            "g",
            "g_line",
            source_agent_model="codex",
        )
    )

    assert result["status"] == "verified"
    assert result["written"] is True
    assert result["bucket"]["content"] == "NEW VERIFIED CONTENT"
    review = result["bucket"]["semantic_review"]
    assert review["title"] == "verify_bucket"
    assert review["domain"] == ["verify"]
    assert review["perspective"]["memory_owner_agent"] == "g"
    assert review["perspective"]["source_agent_model"] == "codex"
    assert "完整 content" in review["perspective"]["note"]
    meta = result["bucket"]["metadata"]
    assert meta["agent_id"] == "g"
    assert meta["relationship_line"] == "g_line"
    assert meta["scope"] == "agent_private"
    assert meta["visibility"] == "same_line"
    assert meta["source_module"] == "hold"
    assert meta["source_agent_model"] == "codex"


@pytest.mark.asyncio
async def test_verified_hold_fails_closed_when_duplicate_check_errors(tmp_path, monkeypatch):
    server = load_isolated_server(tmp_path, monkeypatch)
    server.decay_engine.ensure_started = noop_started
    server.bucket_mgr.list_all = AsyncMock(side_effect=RuntimeError("search unavailable"))
    server.bucket_mgr.create = AsyncMock()

    result = __import__("json").loads(
        await server.verified_hold("DO NOT WRITE", "g", "g_line")
    )

    assert result["status"] == "duplicate_check_failed"
    assert result["written"] is False
    server.bucket_mgr.create.assert_not_called()


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
