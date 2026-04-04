"""Local personal reminders skill."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from app.skills.base import BaseSkill
from app.skills.local_runtime import compact_slug, read_user_list, title_case_phrase, write_user_list

STATE_KEY = "reminders"


class RemindersSkill(BaseSkill):
    """Persist personal reminders in SQLite-backed skill state."""

    manifest: dict[str, Any] = {}

    async def execute(self, action: str, ctx: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Execute one reminder action."""
        del kwargs
        self.validate_action(action)
        request_text = str(ctx.get("request_text", "")).strip()
        user_id = str(ctx.get("user_id", "")).strip()
        if action == "add_reminder":
            return _add_reminder(ctx, user_id, request_text)
        if action == "list_reminders":
            return _list_reminders(ctx, user_id, request_text)
        raise ValueError(f"Unhandled action: {action}")


def _add_reminder(ctx: dict[str, Any], user_id: str, request_text: str) -> dict[str, Any]:
    database_path = str(ctx.get("database_path", "")).strip()
    reminder_text = _extract_reminder_text(request_text)
    if not reminder_text:
        return _error_result("add_reminder", "Tell me what you want to be reminded about.")
    when_label = _extract_when_label(request_text) or "later"
    reminders = read_user_list(user_id, STATE_KEY, database_path=database_path)
    reminders.append(
        {
            "id": compact_slug(f"{reminder_text}-{datetime.now(tz=timezone.utc).isoformat()}"),
            "text": reminder_text,
            "when": when_label,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        }
    )
    write_user_list(user_id, STATE_KEY, reminders, database_path=database_path)
    return _success_result("add_reminder", f"Okay, I'll remember {reminder_text} for {when_label}.", reminders)


def _list_reminders(ctx: dict[str, Any], user_id: str, request_text: str) -> dict[str, Any]:
    database_path = str(ctx.get("database_path", "")).strip()
    reminders = read_user_list(user_id, STATE_KEY, database_path=database_path)
    filter_hint = _extract_when_label(request_text)
    visible = [item for item in reminders if filter_hint in str(item.get("when", "")).lower()] if filter_hint else reminders
    if not visible:
        return _success_result("list_reminders", "You don't have any reminders queued up right now.", [])
    preview = "; ".join(f"{item['text']} ({item['when']})" for item in visible[:3])
    return _success_result("list_reminders", f"Your reminders: {preview}.", visible)


def _extract_reminder_text(request_text: str) -> str:
    match = re.search(r"(?i)(?:remind me to|set a reminder to)\s+(?P<task>.+?)(?:\s+(?:today|tomorrow|tonight|at)\b.*)?$", request_text.strip())
    return title_case_phrase(match.group("task")) if match else ""


def _extract_when_label(request_text: str) -> str:
    match = re.search(r"(?i)\b(today|tomorrow|tonight)\b(?:\s+at\s+([a-z0-9: ]+(?:am|pm)?))?", request_text)
    if not match:
        return ""
    day = match.group(1).lower()
    time_label = (match.group(2) or "").strip()
    return day if not time_label else f"{day} at {time_label}"


def _success_result(action: str, summary: str, reminders: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": True,
        "skill": "reminders",
        "action": action,
        "data": {"summary": summary, "reminders": reminders},
        "meta": {"source": "local_skill_state"},
        "presentation": {"type": "reminders"},
        "errors": [],
    }


def _error_result(action: str, detail: str) -> dict[str, Any]:
    return {
        "ok": False,
        "skill": "reminders",
        "action": action,
        "data": {},
        "meta": {"source": "local_skill_state"},
        "presentation": {"type": "reminders"},
        "errors": [detail],
    }
