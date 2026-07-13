"""Owner-isolated, append-only diary storage for Ombre Brain.

Diary entries live beside memory buckets on the same persistent volume, but
they are deliberately excluded from BucketManager so they never decay,
surface, merge, or affect memory statistics.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import frontmatter


SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class DiaryStore:
    def __init__(self, buckets_dir: str):
        self.base_dir = Path(buckets_dir).resolve() / "diary"

    def append(
        self,
        *,
        content: str,
        agent_id: str,
        relationship_line: str,
        title: str = "",
        entry_date: str = "",
        mood: str = "",
        tags: list[str] | None = None,
        source_module: str = "diary",
        source_agent_model: str = "",
    ) -> dict:
        body = str(content or "").strip()
        if not body:
            raise ValueError("日记内容不能为空")
        if len(body) > 100_000:
            raise ValueError("单篇日记不能超过 100000 字符")

        owner = _validate_owner(agent_id, relationship_line)
        local_now = datetime.now(SHANGHAI)
        day = _validate_date(entry_date or local_now.date().isoformat())
        entry_id = uuid.uuid4().hex[:12]
        clean_title = str(title or "").strip()[:120]
        clean_mood = str(mood or "").strip()[:80]
        clean_tags = _normalize_tags(tags)
        written_at = local_now.isoformat(timespec="seconds")

        metadata = {
            "id": entry_id,
            "type": "diary",
            "date": day,
            "written_at": written_at,
            "updated_at": written_at,
            "title": clean_title,
            "mood": clean_mood,
            "tags": clean_tags,
            "agent_id": owner["agent_id"],
            "relationship_line": owner["relationship_line"],
            "scope": "agent_private",
            "visibility": "same_line",
            "source_module": str(source_module or "diary").strip()[:80],
            "source_agent_model": str(source_agent_model or "").strip()[:120],
        }

        target_dir = self._owner_dir(**owner) / day[:4]
        target_dir.mkdir(parents=True, exist_ok=True)
        target = _safe_child(target_dir, f"{day}_{entry_id}.md")
        temp = _safe_child(target_dir, f".{day}_{entry_id}.tmp")
        rendered = frontmatter.dumps(frontmatter.Post(body, **metadata))
        try:
            temp.write_text(rendered, encoding="utf-8")
            os.replace(temp, target)
        finally:
            if temp.exists():
                temp.unlink(missing_ok=True)
        return self._load(target)

    def list_entries(
        self,
        *,
        agent_id: str,
        relationship_line: str,
        date_from: str = "",
        date_to: str = "",
        limit: int = 60,
    ) -> list[dict]:
        owner = _validate_owner(agent_id, relationship_line)
        start = _validate_date(date_from) if date_from else ""
        end = _validate_date(date_to) if date_to else ""
        if start and end and start > end:
            raise ValueError("date_from 不能晚于 date_to")
        safe_limit = max(1, min(int(limit or 60), 365))
        owner_dir = self._owner_dir(**owner)
        if not owner_dir.exists():
            return []

        entries: list[dict] = []
        for path in owner_dir.rglob("*.md"):
            entry = self._load(path)
            if not entry:
                continue
            if entry.get("agent_id") != owner["agent_id"]:
                continue
            if entry.get("relationship_line") != owner["relationship_line"]:
                continue
            day = str(entry.get("date") or "")
            if start and day < start:
                continue
            if end and day > end:
                continue
            entries.append(entry)

        entries.sort(
            key=lambda item: (str(item.get("date") or ""), str(item.get("written_at") or ""), str(item.get("id") or "")),
            reverse=True,
        )
        return entries[:safe_limit]

    def get(
        self,
        entry_id: str,
        *,
        agent_id: str,
        relationship_line: str,
    ) -> dict | None:
        owner = _validate_owner(agent_id, relationship_line)
        clean_id = str(entry_id or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{12}", clean_id):
            return None
        owner_dir = self._owner_dir(**owner)
        if not owner_dir.exists():
            return None
        for path in owner_dir.rglob(f"*_{clean_id}.md"):
            entry = self._load(path)
            if (
                entry
                and entry.get("agent_id") == owner["agent_id"]
                and entry.get("relationship_line") == owner["relationship_line"]
            ):
                return entry
        return None

    def _owner_dir(self, *, agent_id: str, relationship_line: str) -> Path:
        return _safe_child(self.base_dir, agent_id, relationship_line)

    @staticmethod
    def _load(path: Path) -> dict | None:
        try:
            post = frontmatter.load(path)
            return {**dict(post.metadata), "content": post.content}
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


def _normalize_tags(tags: list[str] | None) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        values = re.split(r"[,，、]", tags)
    else:
        values = list(tags)
    result: list[str] = []
    for value in values:
        clean = str(value or "").strip()[:40]
        if clean and clean not in result:
            result.append(clean)
        if len(result) >= 20:
            break
    return result


def _safe_child(base: Path, *parts: str) -> Path:
    root = base.resolve()
    target = root.joinpath(*parts).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("日记路径越界") from exc
    return target
