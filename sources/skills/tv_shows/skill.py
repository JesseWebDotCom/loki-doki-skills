"""TV show lookup skill backed by TVMaze."""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from typing import Any

from app.skills.base import BaseSkill
from app.skills.local_runtime import title_case_phrase

API_BASE = "https://api.tvmaze.com"
HEADERS = {"User-Agent": "LokiDoki/0.1 (tv_shows skill)"}


class TvShowsSkill(BaseSkill):
    """Return TV show and TV-person details from TVMaze."""

    manifest: dict[str, Any] = {}

    async def execute(self, action: str, ctx: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Execute the requested TV show action."""
        del kwargs
        self.validate_action(action)
        request_text = str(ctx.get("request_text", "")).strip()
        if action == "get_show_details":
            return _show_details_result(request_text)
        if action == "get_show_cast":
            return _show_cast_result(request_text)
        if action == "get_person_details":
            return _person_details_result(request_text)
        raise ValueError(f"Unhandled action: {action}")


def _show_details_result(request_text: str) -> dict[str, Any]:
    show_name = _show_name_from_request(request_text)
    if not show_name:
        return _error_result("get_show_details", "Tell me which TV show or series you want.")
    show = _tvmaze_json(f"/singlesearch/shows?q={urllib.parse.quote(show_name)}&embed=cast")
    if not show:
        return _error_result("get_show_details", f"I couldn't find a TV show named {show_name}.")
    summary = _show_summary(show)
    return {
        "ok": True,
        "skill": "tv_shows",
        "action": "get_show_details",
        "data": {
            "show_name": show.get("name", show_name),
            "premiered": str(show.get("premiered") or ""),
            "status": str(show.get("status") or ""),
            "genres": list(show.get("genres") or []),
            "network": _network_name(show),
            "summary": summary,
            "official_site": str(show.get("officialSite") or ""),
        },
        "meta": {"source": "tvmaze"},
        "presentation": {"type": "tv_show_details"},
        "errors": [],
    }


def _show_cast_result(request_text: str) -> dict[str, Any]:
    show_name = _show_name_from_request(request_text)
    if not show_name:
        return _error_result("get_show_cast", "Tell me which TV show cast you want.")
    show = _tvmaze_json(f"/singlesearch/shows?q={urllib.parse.quote(show_name)}&embed=cast")
    cast_items = list(show.get("_embedded", {}).get("cast", [])) if show else []
    if not show or not cast_items:
        return _error_result("get_show_cast", f"I couldn't find cast details for {show_name}.")
    cast = [_cast_entry(item) for item in cast_items[:8]]
    summary = _cast_summary(str(show.get("name") or show_name), cast)
    return {
        "ok": True,
        "skill": "tv_shows",
        "action": "get_show_cast",
        "data": {
            "show_name": str(show.get("name") or show_name),
            "cast": cast,
            "summary": summary,
        },
        "meta": {"source": "tvmaze"},
        "presentation": {"type": "tv_show_cast"},
        "errors": [],
    }


def _person_details_result(request_text: str) -> dict[str, Any]:
    person_name = _person_name_from_request(request_text)
    if not person_name:
        return _error_result("get_person_details", "Tell me which actor or actress you want.")
    matches = _tvmaze_json(f"/search/people?q={urllib.parse.quote(person_name)}")
    if not isinstance(matches, list) or not matches:
        return _error_result("get_person_details", f"I couldn't find a TV-focused performer named {person_name}.")
    person = dict(matches[0].get("person") or {})
    details = _tvmaze_json(f"/people/{person.get('id')}?embed=castcredits") if person.get("id") else {}
    credits = list(details.get("_embedded", {}).get("castcredits", [])) if isinstance(details, dict) else []
    shows = _credit_show_names(credits)
    summary = _person_summary(person, shows)
    return {
        "ok": True,
        "skill": "tv_shows",
        "action": "get_person_details",
        "data": {
            "person_name": str(person.get("name") or person_name),
            "birthday": str(person.get("birthday") or ""),
            "country": str((person.get("country") or {}).get("name") or ""),
            "shows": shows[:6],
            "summary": summary,
        },
        "meta": {"source": "tvmaze"},
        "presentation": {"type": "tv_person_details"},
        "errors": [],
    }


def _tvmaze_json(path: str) -> dict[str, Any] | list[Any]:
    request = urllib.request.Request(f"{API_BASE}{path}", headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}


def _show_name_from_request(request_text: str) -> str:
    cleaned = " ".join(request_text.strip(" ?!").split())
    # If user says 'the show X', treat as 'the tv show X' for better matching
    cleaned = re.sub(r"(?i)\bthe show ([a-z0-9 ']+)", r"the tv show \1", cleaned)
    cleaned = re.sub(r"(?i)\bshow ([a-z0-9 ']+)", r"tv show \1", cleaned)
    patterns = (
        r"(?i)(?:cast of|who was in|who starred in|who was on)\s+(?:the\s+)?(?:tv\s+show\s+|tv\s+series\s+|show\s+|series\s+)?(?P<name>.+)$",
        r"(?i)(?:tell me about|show details for|series details for)\s+(?:the\s+)?(?:tv\s+show\s+|tv\s+series\s+|show\s+|series\s+)?(?P<name>.+)$",
        r"(?i)(?:tv\s+show|tv\s+series|show|series)\s+(?:details\s+for\s+)?(?P<name>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            return title_case_phrase(match.group("name").strip(" .,:;"))
    return ""


def _person_name_from_request(request_text: str) -> str:
    cleaned = " ".join(request_text.strip(" ?!").split())
    patterns = (
        r"(?i)(?:tv\s+actor|tv\s+actress)\s+(?P<name>.+)$",
        r"(?i)(?:what\s+(?:show|shows|series)\s+was|what\s+tv\s+show\s+was)\s+(?P<name>.+?)\s+(?:in|on)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            return title_case_phrase(match.group("name").strip(" .,:;"))
    return ""


def _show_summary(show: dict[str, Any]) -> str:
    name = str(show.get("name") or "This show")
    premiered = str(show.get("premiered") or "an unknown date")
    status = str(show.get("status") or "unknown status").lower()
    genres = ", ".join(show.get("genres") or []) or "TV"
    network = _network_name(show) or "an unknown network"
    blurb = _plain_text(str(show.get("summary") or ""))
    lead = f"{name} premiered on {premiered} on {network}. It is listed as {genres} and is currently {status}."
    return f"{lead} {blurb}".strip()


def _cast_summary(show_name: str, cast: list[dict[str, str]]) -> str:
    if not cast:
        return f"I couldn't find cast details for {show_name}."
    names = ", ".join(item["person_name"] for item in cast[:5])
    return f"The main cast for {show_name} includes {names}."


def _person_summary(person: dict[str, Any], shows: list[str]) -> str:
    name = str(person.get("name") or "This performer")
    birthday = str(person.get("birthday") or "")
    country = str((person.get("country") or {}).get("name") or "")
    parts = [f"{name} is listed in TVMaze"]
    if birthday:
        parts.append(f"with a birthday of {birthday}")
    if country:
        parts.append(f"from {country}")
    lead = " ".join(parts) + "."
    if shows:
        return f"{lead} TVMaze links them to shows like {', '.join(shows[:5])}."
    return lead


def _cast_entry(item: dict[str, Any]) -> dict[str, str]:
    person = dict(item.get("person") or {})
    character = dict(item.get("character") or {})
    return {
        "person_name": str(person.get("name") or ""),
        "character_name": str(character.get("name") or ""),
    }


def _credit_show_names(credits: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for credit in credits:
        show = dict((credit.get("_links") or {}).get("show") or {})
        name = str(show.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _network_name(show: dict[str, Any]) -> str:
    network = dict(show.get("network") or show.get("webChannel") or {})
    return str(network.get("name") or "")


def _plain_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(value))).strip()


def _error_result(action: str, detail: str) -> dict[str, Any]:
    return {
        "ok": False,
        "skill": "tv_shows",
        "action": action,
        "data": {},
        "meta": {"source": "tvmaze"},
        "presentation": {"type": "tv_show_details"},
        "errors": [detail],
    }
