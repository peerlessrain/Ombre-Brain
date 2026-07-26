from datetime import datetime, timedelta

import pytest

from utils import SHANGHAI, now_iso, parse_stored_datetime


def test_now_iso_is_explicit_shanghai_time():
    value = now_iso()
    parsed = datetime.fromisoformat(value)

    assert parsed.utcoffset() == timedelta(hours=8)
    assert abs((datetime.now(SHANGHAI) - parsed).total_seconds()) < 2


def test_legacy_offsetless_bucket_time_is_interpreted_as_utc():
    parsed = parse_stored_datetime("2026-07-26T12:00:00")

    assert parsed.utcoffset() == timedelta(0)
    assert parsed.astimezone(SHANGHAI).hour == 20


@pytest.mark.asyncio
async def test_new_bucket_timestamps_include_shanghai_offset(bucket_mgr):
    bucket_id = await bucket_mgr.create(
        name="时区测试",
        content="新桶应保存明确的东八区偏移。",
        domain=["测试"],
        tags=["时区"],
    )
    bucket = await bucket_mgr.get(bucket_id)

    assert bucket["metadata"]["created"].endswith("+08:00")
    assert bucket["metadata"]["last_active"].endswith("+08:00")
