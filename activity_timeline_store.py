"""Owner-isolated activity timeline snapshots for Ombre Brain.

These day snapshots are a read-only mirror of timeline-for-agent data. They
live outside memory buckets and diary entries, so they never surface, decay,
merge, or affect memory statistics.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path


SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ActivityTimelineStore:
    def __init__(self, buckets_dir: str):
        self.base_dir = Path(buckets_dir).resolve() / "activity_timeline"

    def sync_day(
        self,
        *,
        date: str,
        events: list[dict],
        agent_id: str,
        relationship_line: str,
        status: str = "draft",
        timezone_name: str = "Asia/Shanghai",
        source_module: str = "timeline-for-agent",
        source_agent_model: str = "",
    ) -> dict:
        owner = _validate_owner(agent_id, relationship_line)
        day = _validate_date(date)
        clean_events = _normalize_events(events)
        local_now = datetime.now(SHANGHAI).isoformat(timespec="seconds")
        payload = {
            "type": "activity_timeline",
            "date": day,
            "status": str(status or "draft").strip()[:24],
            "timezone": str(timezone_name or "Asia/Shanghai").strip()[:80],
            "events": clean_events,
            "event_count": len(clean_events),
            "agent_id": owner["agent_id"],
            "relationship_line": owner["relationship_line"],
            "scope": "agent_private",
            "visibility": "same_line",
            "source_module": str(source_module or "timeline-for-agent").strip()[:80],
            "source_agent_model": str(source_agent_model or "").strip()[:120],
            "synced_at": local_now,
        }

        target_dir = self._owner_dir(**owner) / day[:4]
        target_dir.mkdir(parents=True, exist_ok=True)
        target = _safe_child(target_dir, f"{day}.json")
        temp = _safe_child(target_dir, f".{day}.tmp")
        try:
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, target)
        finally:
            if temp.exists():
                temp.unlink(missing_ok=True)
        return payload

    def list_days(
        self,
        *,
        agent_id: str,
        relationship_line: str,
        date_from: str = "",
        date_to: str = "",
        limit: int = 90,
    ) -> list[dict]:
        owner = _validate_owner(agent_id, relationship_line)
        start = _validate_date(date_from) if date_from else ""
        end = _validate_date(date_to) if date_to else ""
        if start and end and start > end:
            raise ValueError("date_from 不能晚于 date_to")
        safe_limit = max(1, min(int(limit or 90), 366))
        owner_dir = self._owner_dir(**owner)
        if not owner_dir.exists():
            return []

        days = []
        for path in owner_dir.rglob("*.json"):
            item = self._load(path)
            if not item:
                continue
            if item.get("agent_id") != owner["agent_id"] or item.get("relationship_line") != owner["relationship_line"]:
                continue
            day = str(item.get("date") or "")
            if start and day < start:
                continue
            if end and day > end:
                continue
            days.append(item)
        days.sort(key=lambda item: str(item.get("date") or ""), reverse=True)
        return days[:safe_limit]

    def _owner_dir(self, *, agent_id: str, relationship_line: str) -> Path:
        return _safe_child(self.base_dir, agent_id, relationship_line)

    @staticmethod
    def _load(path: Path) -> dict | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except Exception:
            return None


def _validate_owner(agent_id: str, relationship_line: str) -> dict:
    agent = str(agent_id or "").strip().lower()
    line = str(relationship_line or "").strip().lower()
    expected = {"claude": "claude_line", "g": "g_line", "glm": "glm_interim"}
    if agent not in expected:
        raise ValueError("agent_id 只允许 claude、g 或 glm")
    if line != expected[agent]:
        raise ValueError(f"relationship_line 与 {agent} 不匹配")
    return {"agent_id": agent, "relationship_line": line}


def _validate_date(value: str) -> str:
    day = str(value or "").strip()
    if not DATE_RE.fullmatch(day):
        raise ValueError("日期必须是 YYYY-MM-DD")
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("日期不是有效日历日期") from exc
    return day


def _normalize_events(events: list[dict]) -> list[dict]:
    if not isinstance(events, list):
        raise ValueError("events 必须是数组")
    if len(events) > 200:
        raise ValueError("单日时间线不能超过 200 个时间块")
    result = []
    allowed = {
        "id", "startAt", "endAt", "title", "note", "categoryId",
        "subcategoryId", "eventNodeId", "tags", "confidence", "sourceMessageIds",
    }
    for index, raw in enumerate(events):
        if not isinstance(raw, dict):
            raise ValueError(f"events[{index}] 必须是对象")
        item = {key: raw.get(key) for key in allowed if key in raw}
        start = str(item.get("startAt") or "").strip()
        end = str(item.get("endAt") or "").strip()
        if not start or not end:
            raise ValueError(f"events[{index}] 缺少 startAt 或 endAt")
        for key in ("id", "startAt", "endAt", "title", "categoryId", "subcategoryId", "eventNodeId"):
            if key in item:
                item[key] = str(item.get(key) or "").strip()[:300]
        item["note"] = str(item.get("note") or "").strip()[:5000]
        item["tags"] = [str(tag or "").strip()[:80] for tag in (item.get("tags") or []) if str(tag or "").strip()][:30]
        item["sourceMessageIds"] = [str(value or "").strip()[:200] for value in (item.get("sourceMessageIds") or []) if str(value or "").strip()][:50]
        result.append(item)
    result.sort(key=lambda item: (str(item.get("startAt") or ""), str(item.get("endAt") or ""), str(item.get("id") or "")))
    return result


def _safe_child(base: Path, *parts: str) -> Path:
    root = base.resolve()
    target = root.joinpath(*parts).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("时间线路径越界") from exc
    return target
