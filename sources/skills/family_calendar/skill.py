"""Local shared family calendar skill."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from app.skills.base import BaseSkill
from app.skills.local_runtime import compact_slug, read_shared_list, title_case_phrase, write_shared_list

STATE_KEY = "family_calendar_events"


class FamilyCalendarSkill(BaseSkill):
    """Persist a simple shared family calendar in SQLite-backed skill state."""

    manifest: dict[str, Any] = {}

    async def execute(self, action: str, ctx: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Execute one calendar action."""
        del kwargs
        self.validate_action(action)
        request_text = str(ctx.get("request_text", "")).strip()
        if action == "add_event":
            return _add_event(ctx, request_text)
        if action == "get_agenda":
            return _get_agenda(ctx, request_text)
        raise ValueError(f"Unhandled action: {action}")


def _add_event(ctx: dict[str, Any], request_text: str) -> dict[str, Any]:
    database_path = str(ctx.get("database_path", "")).strip()
    title = _extract_title(request_text)
    if not title:
        return _error_result("add_event", "Tell me what event you want to add to the family calendar.")
    when_label = _extract_when_label(request_text) or "sometime soon"
    events = read_shared_list(STATE_KEY, database_path=database_path)
    events.append(
        {
            "id": compact_slug(f"{title}-{datetime.now(tz=timezone.utc).isoformat()}"),
            "title": title,
            "when": when_label,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        }
    )
    write_shared_list(STATE_KEY, events, database_path=database_path)
    summary = f"I added {title} to the family calendar for {when_label}."
    return _success_result("add_event", summary, events)


def _get_agenda(ctx: dict[str, Any], request_text: str) -> dict[str, Any]:
    database_path = str(ctx.get("database_path", "")).strip()
    filter_hint = _request_filter(request_text)
    events = read_shared_list(STATE_KEY, database_path=database_path)
    visible = [item for item in events if filter_hint in str(item.get("when", "")).lower()] if filter_hint else events
    if not visible:
        detail = "There is nothing on the family calendar"
        if filter_hint:
            detail += f" for {filter_hint}"
        return _success_result("get_agenda", detail + ".", [])
    preview = "; ".join(f"{item['title']} ({item['when']})" for item in visible[:3])
    summary = f"On the family calendar: {preview}."
    return _success_result("get_agenda", summary, visible)


def _extract_title(request_text: str) -> str:
    match = re.search(r"(?i)(?:add|put|schedule)\s+(?P<title>.+?)(?:\s+(?:on|for|at)\s+.+)?(?:\s+to the family calendar|\s+on the calendar|\s*$)", request_text.strip())
    return title_case_phrase(match.group("title")) if match else ""


def _extract_when_label(request_text: str) -> str:
    match = re.search(r"(?i)\b(today|tomorrow|tonight|this weekend|next week)\b(?:\s+at\s+([a-z0-9: ]+(?:am|pm)?))?", request_text)
    if not match:
        return ""
    day = match.group(1).lower()
    time_label = (match.group(2) or "").strip()
    return day if not time_label else f"{day} at {time_label}"


def _request_filter(request_text: str) -> str:
    lowered = request_text.lower()
    for token in ("today", "tomorrow", "tonight", "this weekend", "next week"):
        if token in lowered:
            return token
    return ""


def _success_result(action: str, summary: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": True,
        "skill": "family_calendar",
        "action": action,
        "data": {"summary": summary, "events": events},
        "meta": {"source": "local_skill_state"},
        "presentation": {"type": "calendar_agenda"},
        "errors": [],
    }


def _error_result(action: str, detail: str) -> dict[str, Any]:
    return {
        "ok": False,
        "skill": "family_calendar",
        "action": action,
        "data": {},
        "meta": {"source": "local_skill_state"},
        "presentation": {"type": "calendar_agenda"},
        "errors": [detail],
    }
