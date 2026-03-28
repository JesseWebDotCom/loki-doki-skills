"""Home Assistant control skill."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.skills.base import BaseSkill
from app.skills.home_assistant_client import api_get, api_post, request_error_detail
from app.skills.types import AccountRecord


class HomeAssistantSkill(BaseSkill):
    """Control Home Assistant through its local REST API."""

    manifest: dict[str, Any] = {}

    async def execute(self, action: str, ctx: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Execute one Home Assistant action."""
        del kwargs
        self.validate_action(action)
        request_text = str(ctx.get("request_text", "")).strip()
        target = _resolve_target(ctx, request_text)
        if target.error:
            return _error_result(action, target.error)
        assert target.account is not None
        try:
            states = api_get(target.base_url, target.token, "/api/states")
            candidate_result = _entity_candidates(states, target.cleaned_request, target.default_area, action)
            if candidate_result["clarify"]:
                return _clarification_result(
                    action,
                    target.cleaned_request,
                    candidate_result["matches"],
                    target.account.label,
                )
            entity = candidate_result["entity"]
            if entity is None:
                return _error_result(action, "I couldn't match that request to a Home Assistant entity.")
            if action == "get_state":
                return _state_result(action, entity, target.account.label)
            if action == "set_level":
                percentage = _extract_percentage(target.cleaned_request)
                if percentage is None:
                    return _error_result(action, "Tell me the percentage you want, like 50%.")
                return _set_level_result(target, entity, percentage)
            return _toggle_result(action, target, entity)
        except Exception as error:
            return _error_result(action, request_error_detail(error))

    async def test_connection(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Run a read-only Home Assistant connectivity check."""
        account_context = ctx.get("context") or {}
        if not isinstance(account_context, dict):
            account_context = {}
        base_url = str(account_context.get("base_url") or "").strip()
        token = str(account_context.get("access_token") or "").strip()
        if not base_url or not token:
            return {"status": "error", "detail": "Home Assistant URL and token are required.", "data": {}}
        try:
            info = api_get(base_url, token, "/api/")
            states = api_get(base_url, token, "/api/states")
        except Exception as error:
            return {"status": "error", "detail": request_error_detail(error), "data": {}}
        location = ""
        version = ""
        if isinstance(info, dict):
            location = str(info.get("location_name") or "").strip()
            version = str(info.get("version") or "").strip()
        state_count = len(states) if isinstance(states, list) else 0
        detail_parts = ["Connected to Home Assistant"]
        if location:
            detail_parts.append(location)
        if version:
            detail_parts.append(f"v{version}")
        detail_parts.append(f"{state_count} entities visible")
        return {
            "status": "ok",
            "detail": " · ".join(detail_parts),
            "data": {"location_name": location, "version": version, "entity_count": state_count},
        }


@dataclass(frozen=True)
class _ResolvedTarget:
    account: AccountRecord | None
    base_url: str
    token: str
    default_area: str
    cleaned_request: str
    error: str = ""


def _resolve_target(ctx: dict[str, Any], request_text: str) -> _ResolvedTarget:
    account_manager = ctx.get("accounts")
    accounts = account_manager.list_accounts("home_assistant") if account_manager is not None else []
    enabled_accounts = [account for account in accounts if account.enabled]
    if enabled_accounts:
        matched = _match_account(enabled_accounts, request_text)
        if matched is None and len(enabled_accounts) == 1:
            matched = enabled_accounts[0]
        if matched is None:
            matched = next((account for account in enabled_accounts if account.is_default), None)
        if matched is None:
            labels = ", ".join(account.label for account in enabled_accounts[:3])
            return _ResolvedTarget(
                account=None,
                base_url="",
                token="",
                default_area="",
                cleaned_request=request_text,
                error=f"Choose which Home Assistant instance to use: {labels}.",
            )
        account_context = matched.context if isinstance(matched.context, dict) else {}
        base_url = str(account_context.get("base_url") or "").strip()
        token = str(account_context.get("access_token") or "").strip()
        if not base_url or not token:
            return _ResolvedTarget(
                account=matched,
                base_url="",
                token="",
                default_area="",
                cleaned_request=request_text,
                error=f"Finish configuring the {matched.label} Home Assistant account first.",
            )
        return _ResolvedTarget(
            account=matched,
            base_url=base_url,
            token=token,
            default_area=str(account_context.get("default_area") or "").strip(),
            cleaned_request=_strip_account_reference(request_text, matched),
        )
    base_url = str(ctx.get("base_url") or "").strip()
    token = str(ctx.get("access_token") or "").strip()
    if not base_url or not token:
        return _ResolvedTarget(
            account=None,
            base_url="",
            token="",
            default_area="",
            cleaned_request=request_text,
            error="Add your Home Assistant URL and access token in skill settings first.",
        )
    return _ResolvedTarget(
        account=AccountRecord(
            account_id="legacy",
            skill_id="home_assistant",
            label="Home Assistant",
            config={},
            context={},
            enabled=True,
            is_default=True,
            allowed_user_ids=(),
            health_status="ok",
            health_detail="",
        ),
        base_url=base_url,
        token=token,
        default_area=str(ctx.get("default_area") or "").strip(),
        cleaned_request=request_text,
    )


def _match_account(accounts: list[AccountRecord], request_text: str) -> AccountRecord | None:
    cleaned = f" {request_text.lower()} "
    matches: list[tuple[int, AccountRecord]] = []
    for account in accounts:
        aliases = _account_aliases(account)
        score = 0
        for alias in aliases:
            if not alias:
                continue
            if re.search(rf"\b(?:at|in|from|on)\s+{re.escape(alias)}\b", cleaned):
                score = max(score, len(alias.split()) + 3)
            elif re.search(rf"\b{re.escape(alias)}\b", cleaned):
                score = max(score, len(alias.split()) + 1)
        if score > 0:
            matches.append((score, account))
    matches.sort(key=lambda item: item[0], reverse=True)
    if len(matches) > 1 and matches[0][0] == matches[1][0]:
        return None
    return None if not matches else matches[0][1]


def _account_aliases(account: AccountRecord) -> list[str]:
    context = account.context if isinstance(account.context, dict) else {}
    raw_aliases = str(context.get("site_aliases") or "").strip()
    aliases = [account.label.strip().lower()]
    aliases.extend(part.strip().lower() for part in raw_aliases.split(",") if part.strip())
    return list(dict.fromkeys(alias for alias in aliases if alias))


def _strip_account_reference(request_text: str, account: AccountRecord) -> str:
    cleaned = request_text
    for alias in _account_aliases(account):
        cleaned = re.sub(rf"\b(?:at|in|from|on)\s+{re.escape(alias)}\b", " ", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split())


def _entity_candidates(
    states: Any,
    request_text: str,
    default_area: str,
    action: str,
) -> dict[str, Any]:
    if not isinstance(states, list):
        return {"entity": None, "matches": [], "clarify": False}
    words = [part for part in re.findall(r"[a-z0-9_']+", request_text.lower()) if part not in _STOP_WORDS]
    allowed_domains = _allowed_domains(action)
    matches: list[tuple[int, dict[str, Any]]] = []
    for item in states:
        if not isinstance(item, dict):
            continue
        entity_id = str(item.get("entity_id", "")).lower()
        if not entity_id:
            continue
        domain = entity_id.split(".", 1)[0]
        if allowed_domains and domain not in allowed_domains:
            continue
        attrs = item.get("attributes") or {}
        if not isinstance(attrs, dict):
            attrs = {}
        haystack = " ".join(
            part
            for part in [
                entity_id.replace("_", " "),
                str(attrs.get("friendly_name", "")).lower().replace("_", " "),
                str(attrs.get("area_id", "")).lower().replace("_", " "),
                str(attrs.get("device_class", "")).lower().replace("_", " "),
            ]
            if part
        )
        if not haystack:
            continue
        haystack_words = set(re.findall(r"[a-z0-9_']+", haystack))
        matched_words = [word for word in words if word in haystack_words]
        if len(words) >= 3 and len(matched_words) < 2:
            continue
        score = len(matched_words) * 3
        if default_area and default_area.lower() in haystack:
            score += 2
        if domain == "fan" and "fan" in words:
            score += 2
        if domain == "light" and ("light" in words or "lamp" in words):
            score += 2
        if domain == "switch" and ("switch" in words or "outlet" in words or "plug" in words):
            score += 2
        if score <= 0:
            continue
        matches.append((score, item))
    matches.sort(key=lambda item: item[0], reverse=True)
    if not matches:
        return {"entity": None, "matches": [], "clarify": False}
    if _needs_clarification(request_text, matches):
        return {
            "entity": None,
            "matches": _clarification_candidates([item[1] for item in matches[:3]]),
            "clarify": True,
        }
    return {
        "entity": matches[0][1],
        "matches": _clarification_candidates([matches[0][1]]),
        "clarify": False,
    }


def _needs_clarification(request_text: str, matches: list[tuple[int, dict[str, Any]]]) -> bool:
    """Return whether the top entity match is too ambiguous to execute safely."""
    if len(matches) < 2:
        return False
    words = [part for part in re.findall(r"[a-z0-9_']+", request_text.lower()) if part not in _STOP_WORDS]
    if len(words) < 2:
        return True
    return matches[0][0] - matches[1][0] <= 2


def _candidate_payload(entity: dict[str, Any]) -> dict[str, str]:
    """Return one JSON-safe clarification candidate."""
    return {
        "entity_id": str(entity.get("entity_id", "")).strip(),
        "friendly_name": _clarification_name(entity),
    }


def _clarification_candidates(entities: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return clarification candidates with labels that stay unique and readable."""
    payloads = [_candidate_payload(entity) for entity in entities]
    label_counts: dict[str, int] = {}
    for payload in payloads:
        label = str(payload.get("friendly_name") or "").strip().lower()
        if not label:
            continue
        label_counts[label] = label_counts.get(label, 0) + 1
    updated: list[dict[str, str]] = []
    for entity, payload in zip(entities, payloads):
        label = str(payload.get("friendly_name") or "").strip()
        if not label or label_counts.get(label.lower(), 0) > 1:
            payload = {**payload, "friendly_name": _entity_object_label(entity)}
        updated.append(payload)
    return updated


def _allowed_domains(action: str) -> set[str]:
    if action == "set_level":
        return {"fan", "light"}
    return {"light", "switch", "fan"}


def _extract_percentage(request_text: str) -> int | None:
    match = re.search(r"\b(?P<value>100|[1-9]?\d)\s*%", request_text)
    if match is None:
        return None
    return max(0, min(100, int(match.group("value"))))


def _toggle_result(action: str, target: _ResolvedTarget, entity: dict[str, Any]) -> dict[str, Any]:
    service = "turn_on" if action == "turn_on" else "turn_off"
    state = "on" if action == "turn_on" else "off"
    domain = str(entity.get("entity_id", "switch.unknown")).split(".", 1)[0]
    api_post(target.base_url, target.token, f"/api/services/{domain}/{service}", {"entity_id": entity["entity_id"]})
    summary = f"{_entity_name(entity)} is now {state}{_site_suffix(target.account.label)}."
    return _success_result(action, entity, summary, state, target.account.label)


def _set_level_result(target: _ResolvedTarget, entity: dict[str, Any], percentage: int) -> dict[str, Any]:
    entity_id = str(entity.get("entity_id", ""))
    domain = entity_id.split(".", 1)[0]
    if domain == "fan":
        api_post(target.base_url, target.token, "/api/services/fan/set_percentage", {"entity_id": entity_id, "percentage": percentage})
    elif domain == "light":
        api_post(target.base_url, target.token, "/api/services/light/turn_on", {"entity_id": entity_id, "brightness_pct": percentage})
    else:
        return _error_result("set_level", "That Home Assistant entity does not support percentage control.")
    summary = f"{_entity_name(entity)} is set to {percentage}%{_site_suffix(target.account.label)}."
    return _success_result("set_level", entity, summary, f"{percentage}%", target.account.label)


def _state_result(action: str, entity: dict[str, Any], account_label: str) -> dict[str, Any]:
    state = str(entity.get("state", "unknown"))
    attrs = entity.get("attributes") or {}
    percentage = ""
    if isinstance(attrs, dict):
        if attrs.get("percentage") not in (None, ""):
            percentage = f" at {attrs['percentage']}%"
        elif attrs.get("brightness") not in (None, ""):
            try:
                brightness = int(attrs["brightness"])
                percentage = f" at {round((brightness / 255) * 100)}%"
            except (TypeError, ValueError):
                percentage = ""
    summary = f"{_entity_name(entity)} is currently {state}{percentage}{_site_suffix(account_label)}."
    return _success_result(action, entity, summary, state, account_label)


def _entity_name(entity: dict[str, Any]) -> str:
    attrs = entity.get("attributes") or {}
    if isinstance(attrs, dict) and attrs.get("friendly_name"):
        return str(attrs["friendly_name"])
    return _entity_object_label(entity)


def _clarification_name(entity: dict[str, Any]) -> str:
    """Return a readable label for clarification prompts."""
    attrs = entity.get("attributes") or {}
    friendly_name = ""
    if isinstance(attrs, dict):
        friendly_name = str(attrs.get("friendly_name") or "").strip()
    if _generic_friendly_name(friendly_name, entity):
        return _entity_object_label(entity)
    return friendly_name or _entity_object_label(entity)


def _generic_friendly_name(friendly_name: str, entity: dict[str, Any]) -> bool:
    """Return whether a Home Assistant friendly name is too generic to disambiguate."""
    cleaned = " ".join(friendly_name.strip().lower().split())
    if not cleaned:
        return True
    entity_id = str(entity.get("entity_id", "")).strip().lower()
    domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
    generic_names = {
        domain,
        domain.replace("_", " "),
        domain.title(),
        domain.replace("_", " ").title(),
    }
    return cleaned in {name.lower() for name in generic_names if name}


def _entity_object_label(entity: dict[str, Any]) -> str:
    """Return one readable label derived from the entity id."""
    entity_id = str(entity.get("entity_id", "")).strip()
    if not entity_id or "." not in entity_id:
        return "That device"
    domain, object_id = entity_id.split(".", 1)
    object_label = object_id.replace("_", " ").strip()
    if not object_label:
        return domain.replace("_", " ").title() or "That device"
    return f"{object_label.title()} {domain.replace('_', ' ').title()}".strip()


def _site_suffix(label: str) -> str:
    if label in {"", "Home Assistant"}:
        return ""
    normalized = label.strip().lower()
    if normalized in {"home", "house", "work", "office"}:
        return f" at {label}"
    return f" on {label}"


def _success_result(
    action: str,
    entity: dict[str, Any],
    summary: str,
    state: str,
    account_label: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "skill": "home_assistant",
        "action": action,
        "data": {
            "entity_id": str(entity.get("entity_id", "")),
            "friendly_name": _entity_name(entity),
            "state": state,
            "summary": summary,
            "account_label": account_label,
        },
        "meta": {"source": "home_assistant"},
        "presentation": {"type": "entity_state_change" if action != "get_state" else "entity_state"},
        "errors": [],
    }


def _clarification_result(
    action: str,
    request_text: str,
    matches: list[dict[str, str]],
    account_label: str,
) -> dict[str, Any]:
    labels = [item["friendly_name"] for item in matches if item.get("friendly_name")]
    if not labels:
        detail = "I found more than one matching Home Assistant entity. Which one did you mean?"
    elif len(labels) == 1:
        detail = f"Did you mean {labels[0]}?"
    else:
        detail = f"Did you mean {', '.join(labels[:-1])}, or {labels[-1]}?"
    return {
        "ok": True,
        "skill": "home_assistant",
        "action": action,
        "data": {
            "summary": detail,
            "original_request": request_text,
            "account_label": account_label,
            "candidates": matches,
        },
        "meta": {"source": "home_assistant"},
        "presentation": {"type": "clarification"},
        "errors": [],
    }


def _error_result(action: str, detail: str) -> dict[str, Any]:
    return {
        "ok": False,
        "skill": "home_assistant",
        "action": action,
        "data": {},
        "meta": {"source": "home_assistant"},
        "presentation": {"type": "entity_state"},
        "errors": [detail],
    }


_STOP_WORDS = {
    "the",
    "a",
    "an",
    "please",
    "turn",
    "on",
    "off",
    "is",
    "are",
    "what",
    "status",
    "state",
    "of",
    "in",
    "my",
    "set",
    "to",
    "at",
    "from",
}
