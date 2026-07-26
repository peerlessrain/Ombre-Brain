import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def load_isolated_server(tmp_path, monkeypatch):
    monkeypatch.setenv("OMBRE_BUCKETS_DIR", str(tmp_path / "buckets"))
    monkeypatch.setenv("OMBRE_API_KEY", "")
    monkeypatch.setenv("OMBRE_HOOK_SKIP", "1")
    import server
    return importlib.reload(server)


class JsonRequest:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


@pytest.mark.asyncio
async def test_dashboard_hot_update_enables_tagging_client(tmp_path, monkeypatch):
    server = load_isolated_server(tmp_path, monkeypatch)
    server._require_auth = lambda _request: None

    assert server.dehydrator.api_available is False
    assert server.dehydrator.client is None

    response = await server.api_config_update(JsonRequest({
        "dehydration": {
            "api_key": "runtime-gemini-key",
            "model": "gemini-2.5-flash-lite",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "max_tokens": 1536,
            "temperature": 0.2,
        },
    }))
    payload = json.loads(response.body)

    assert payload["ok"] is True
    assert server.dehydrator.api_available is True
    assert server.dehydrator.client is not None
    assert server.dehydrator.model == "gemini-2.5-flash-lite"
    assert server.dehydrator.max_tokens == 1536
    assert server.dehydrator.temperature == 0.2


@pytest.mark.asyncio
async def test_short_grow_refuses_write_when_tagging_fails(tmp_path, monkeypatch):
    server = load_isolated_server(tmp_path, monkeypatch)

    async def noop_started():
        return None

    server.decay_engine.ensure_started = noop_started
    server.dehydrator.analyze = AsyncMock(side_effect=RuntimeError("tagger unavailable"))
    before = await server.bucket_mgr.list_all(include_archive=True)

    result = await server.grow(
        "TAGGING_FAIL_PROBE",
        agent_id="g",
        relationship_line="g_line",
    )
    after = await server.bucket_mgr.list_all(include_archive=True)

    assert "tagging" in result.lower() or "tagger" in result.lower()
    assert len(after) == len(before)


@pytest.mark.asyncio
async def test_pulse_reports_tagging_pipeline_state(tmp_path, monkeypatch):
    server = load_isolated_server(tmp_path, monkeypatch)

    status = await server.pulse(agent_id="g", relationship_line="g_line")
