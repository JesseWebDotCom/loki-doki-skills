"""Shared household shopping list skill."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from app.skills.base import BaseSkill
from app.skills.local_runtime import compact_slug, read_shared_list, title_case_phrase, write_shared_list

STATE_KEY = "shopping_list"


class ShoppingListSkill(BaseSkill):
    """Persist a shared shopping list in SQLite-backed skill state."""

    manifest: dict[str, Any] = {}

    async def execute(self, action: str, ctx: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Execute one shopping-list action."""
        del kwargs
        self.validate_action(action)
        request_text = str(ctx.get("request_text", "")).strip()
        if action == "add_item":
            return _add_item(ctx, request_text)
        if action == "remove_item":
            return _remove_item(ctx, request_text)
        if action == "list_items":
            return _list_items(ctx)
        raise ValueError(f"Unhandled action: {action}")


def _add_item(ctx: dict[str, Any], request_text: str) -> dict[str, Any]:
    database_path = str(ctx.get("database_path", "")).strip()
    item_name = _extract_item(request_text, ("add", "put", "buy"))
    if not item_name:
        return _error_result("add_item", "Tell me what item you want to add to the shopping list.")
    items = read_shared_list(STATE_KEY, database_path=database_path)
    items.append({"id": compact_slug(f"{item_name}-{datetime.now(tz=timezone.utc).isoformat()}"), "name": item_name})
    write_shared_list(STATE_KEY, items, database_path=database_path)
    return _success_result("add_item", f"I added {item_name} to the shopping list.", items)


def _remove_item(ctx: dict[str, Any], request_text: str) -> dict[str, Any]:
    database_path = str(ctx.get("database_path", "")).strip()
    item_name = _extract_item(request_text, ("remove", "take off", "cross off"))
    if not item_name:
        return _error_result("remove_item", "Tell me which shopping-list item you want to remove.")
    items = read_shared_list(STATE_KEY, database_path=database_path)
    remaining = [item for item in items if str(item.get("name", "")).lower() != item_name.lower()]
    write_shared_list(STATE_KEY, remaining, database_path=database_path)
    return _success_result("remove_item", f"I removed {item_name} from the shopping list.", remaining)


def _list_items(ctx: dict[str, Any]) -> dict[str, Any]:
    items = read_shared_list(STATE_KEY, database_path=str(ctx.get("database_path", "")).strip())
    if not items:
        return _success_result("list_items", "The shopping list is empty right now.", [])
    preview = ", ".join(str(item.get("name", "")) for item in items[:6])
    return _success_result("list_items", f"On the shopping list: {preview}.", items)


def _extract_item(request_text: str, verbs: tuple[str, ...]) -> str:
    escaped = "|".join(re.escape(item) for item in verbs)
    match = re.search(rf"(?i)(?:{escaped})\s+(?P<item>.+?)(?:\s+(?:to|from)\s+the shopping list|\s*$)", request_text.strip())
    return title_case_phrase(match.group("item")) if match else ""


def _success_result(action: str, summary: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": True,
        "skill": "shopping_list",
        "action": action,
        "data": {"summary": summary, "items": items},
        "meta": {"source": "local_skill_state"},
        "presentation": {"type": "shopping_list"},
        "errors": [],
    }


def _error_result(action: str, detail: str) -> dict[str, Any]:
    return {
        "ok": False,
        "skill": "shopping_list",
        "action": action,
        "data": {},
        "meta": {"source": "local_skill_state"},
        "presentation": {"type": "shopping_list"},
        "errors": [detail],
    }
