"""Wikipedia lookup skill backed by public Wikipedia APIs."""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from typing import Any

from app.skills.base import BaseSkill
from app.skills.local_runtime import title_case_phrase

SEARCH_URL = "https://en.wikipedia.org/w/api.php"
SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary"
HEADERS = {"User-Agent": "LokiDoki/0.1 (wikipedia skill)"}


class WikipediaSkill(BaseSkill):
    """Return structured Wikipedia summaries."""

    manifest: dict[str, Any] = {}

    async def execute(self, action: str, ctx: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Execute the requested Wikipedia action."""
        del kwargs
        self.validate_action(action)
        if action != "lookup_article":
            raise ValueError(f"Unhandled action: {action}")
        request_text = str(ctx.get("request_text", "")).strip()
        return _lookup_result(request_text)


def _lookup_result(request_text: str) -> dict[str, Any]:
    query = _article_query(request_text)
    if not query:
        return _error_result("Tell me what you want to look up on Wikipedia.")
    title = _search_title(query)
    if not title:
        return _error_result(f"I couldn't find a matching Wikipedia article for {query}.")
    summary = _summary_payload(title)
    if not summary:
        return _error_result(f"I found {title}, but I couldn't retrieve the article summary.")
    extract = str(summary.get("extract") or "").strip()
    description = str(summary.get("description") or "").strip()
    display_title = str(summary.get("title") or title)
    content_urls = dict(summary.get("content_urls") or {})
    reply = _summary_text(display_title, description, extract, content_urls)
    return {
        "ok": True,
        "skill": "wikipedia",
        "action": "lookup_article",
        "data": {
            "query": query,
            "title": display_title,
            "description": description,
            "extract": extract,
            "content_urls": dict(summary.get("content_urls") or {}),
            "summary": reply,
        },
        "meta": {"source": "wikipedia"},
        "presentation": {"type": "wikipedia_summary"},
        "errors": [],
    }


def _search_title(query: str) -> str:
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "utf8": "1",
            "srlimit": "1",
        }
    )
    payload = _json_request(f"{SEARCH_URL}?{params}")
    search = list(payload.get("query", {}).get("search", [])) if isinstance(payload, dict) else []
    if not search:
        return ""
    return str(search[0].get("title") or "").strip()


def _summary_payload(title: str) -> dict[str, Any]:
    encoded_title = urllib.parse.quote(title.replace(" ", "_"))
    payload = _json_request(f"{SUMMARY_URL}/{encoded_title}")
    return payload if isinstance(payload, dict) else {}


def _json_request(url: str) -> dict[str, Any] | list[Any]:
    request = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}


def _article_query(request_text: str) -> str:
    cleaned = " ".join(request_text.strip(" ?!").split())
    lowered = cleaned.lower()
    prefixes = (
        "look up on wikipedia ",
        "look this up on wikipedia ",
        "look up ",
        "wikipedia article for ",
        "on wikipedia ",
        "wikipedia ",
        "wiki ",
    )
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return _apply_media_hint(
                title_case_phrase(cleaned[len(prefix) :].strip(" .,:;")),
                lowered,
            )
    patterns = (
        r"(?i)(?:tell me about|what is|what was|who is|who was)\s+(?:the\s+)?(?:tv\s+show\s+|tv\s+series\s+|show\s+|series\s+)?(?P<query>.+)$",
        r"(?i)(?:cast of|who was in|who starred in)\s+(?:the\s+)?(?:tv\s+show\s+|tv\s+series\s+|show\s+|series\s+)?(?P<query>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            return _apply_media_hint(title_case_phrase(match.group("query").strip(" .,:;")), lowered)
    return _apply_media_hint(title_case_phrase(cleaned), lowered)


def _apply_media_hint(query: str, lowered_request: str) -> str:
    """Bias ambiguous searches toward the medium mentioned in the request."""
    if not query:
        return ""
    if any(token in lowered_request for token in ("tv show", "tv series", "series", "sitcom")):
        return f"{query} TV series"
    return query


def _summary_text(title: str, description: str, extract: str, content_urls: dict[str, Any] | None = None) -> str:
    clean_extract = _plain_text(extract)
    url = ""
    if content_urls and "desktop" in content_urls:
        url = content_urls["desktop"].get("page", "")

    header = f"### {title}"
    if description:
        header += f"\n*{description}*"
    
    source_link = f"\n\n[Read more on Wikipedia]({url})" if url else ""
    return f"{header}\n\n{clean_extract}{source_link}".strip()


def _plain_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(value))).strip()


def _error_result(detail: str) -> dict[str, Any]:
    return {
        "ok": False,
        "skill": "wikipedia",
        "action": "lookup_article",
        "data": {},
        "meta": {"source": "wikipedia"},
        "presentation": {"type": "wikipedia_summary"},
        "errors": [detail],
    }
