"""Wikipedia lookup skill backed by public Wikipedia APIs and Infobox scraping."""

from __future__ import annotations

import html
import re
from typing import Any, Awaitable, Callable

import httpx
from bs4 import BeautifulSoup

from app.skills.base import BaseSkill
from app.skills.local_runtime import title_case_phrase


class WikipediaSkill(BaseSkill):
    """Return rich Wikipedia summaries including infobox metadata."""

    manifest: dict[str, Any] = {}

    async def execute(
        self,
        action: str,
        ctx: dict[str, Any],
        emit_progress: Callable[[str], Awaitable[None]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute the requested Wikipedia action."""
        del kwargs
        self.validate_action(action)
        if action != "lookup_article":
            raise ValueError(f"Unhandled action: {action}")

        request_text = str(ctx.get("request_text", "")).strip()
        query = _article_query(request_text)
        if not query:
            return _error_result("lookup_article", "Tell me what you want to look up on Wikipedia.")

        await emit_progress(f"Searching Wikipedia for '{query}'...")
        return await self._lookup_article_result(query, action)

    async def _lookup_article_result(self, query: str, action: str) -> dict[str, Any]:
        # Try original, then title case
        attempts = [query, query.title()] if not any(c.isupper() for c in query) else [query]
        headers = {"User-Agent": "LokiDoki/1.0 (info@lokidoki.app)"}
        payload = None

        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=10.0) as client:
            for attempt in attempts:
                formatted_query = attempt.replace(" ", "_")
                summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{formatted_query}"
                try:
                    response = await client.get(summary_url)
                    if response.status_code == 200:
                        payload = response.json()
                        if payload.get("type") != "disambiguation":
                            break
                except httpx.RequestError:
                    continue

            if not payload or payload.get("type") == "disambiguation":
                # Final attempt: use search API to find the real title
                search_url = "https://en.wikipedia.org/w/api.php"
                params = {"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 1}
                try:
                    search_response = await client.get(search_url, params=params)
                    search_data = search_response.json()
                    results = search_data.get("query", {}).get("search", [])
                    if results:
                        real_title = results[0]["title"]
                        summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{real_title.replace(' ', '_')}"
                        summary_response = await client.get(summary_url)
                        if summary_response.status_code == 200:
                            payload = summary_response.json()
                except Exception:
                    pass

        if not payload or payload.get("type") == "disambiguation":
            return _error_result(action, f"I couldn't find a specific Wikipedia article for '{query}'.")

        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=10.0) as client:
            page_url = str(payload.get("content_urls", {}).get("desktop", {}).get("page", "")).strip()
            infobox = await _fetch_infobox(client, page_url) if page_url else {}

            extract = str(payload.get("extract") or "").strip()
            description = str(payload.get("description") or "").strip()
            display_title = str(payload.get("title") or query)
            content_urls = dict(payload.get("content_urls") or {})
            
            reply = _summary_markdown(display_title, description, extract, content_urls)

            return {
                "ok": True,
                "skill": "wikipedia",
                "action": action,
                "data": {
                    "query": query,
                    "title": display_title,
                    "description": description,
                    "extract": extract,
                    "infobox": infobox,
                    "thumbnail": _thumbnail_payload(payload),
                    "content_urls": content_urls,
                    "summary": reply,
                },
                "meta": {"source": "wikipedia"},
                "presentation": {"type": "wikipedia_summary"},
                "errors": [],
            }


async def _fetch_infobox(client: httpx.AsyncClient, page_url: str) -> dict[str, str]:
    """Return a cleaned infobox payload when the page has one."""
    try:
        response = await client.get(page_url)
    except httpx.RequestError:
        return {}
    if response.status_code != 200:
        return {}
    return _scrape_infobox(response.text)


def _scrape_infobox(html_content: str) -> dict[str, str]:
    """Parse the right-column Wikipedia infobox into a clean dictionary."""
    soup = BeautifulSoup(html_content, "html.parser")
    infobox = soup.find("table", {"class": "infobox"})
    if not infobox:
        return {}

    for hidden in infobox.find_all(["sup", "span", "div", "style"]):
        classes = hidden.get("class", [])
        if any(item in ["reference", "noprint", "metadata"] for item in classes):
            hidden.decompose()
            continue
        if hidden.has_attr("style") and "display:none" in hidden.get("style", "").replace(" ", ""):
            hidden.decompose()

    for line_break in infobox.find_all("br"):
        line_break.replace_with(", ")
    for list_item in infobox.find_all("li"):
        list_item.insert_after(", ")
        list_item.unwrap()

    parsed: dict[str, str] = {}
    for row in infobox.find_all("tr"):
        label = row.find("th", {"class": "infobox-label"})
        value = row.find("td", {"class": "infobox-data"})
        if not label or not value:
            continue
        key = re.sub(r"\[.*?\]", "", label.get_text(separator=" ", strip=True)).strip()
        cleaned_value = re.sub(r"\[.*?\]", "", value.get_text(separator=", ", strip=True)).strip(", ")
        cleaned_value = re.sub(r",\s*,", ",", cleaned_value).strip(", ")
        if key and cleaned_value:
            parsed[key] = cleaned_value
    return parsed


def _thumbnail_payload(payload: dict[str, Any]) -> dict[str, str]:
    source = str(payload.get("thumbnail", {}).get("source", "")).strip()
    return {"url": source} if source else {}


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


def _summary_markdown(title: str, description: str, extract: str, content_urls: dict[str, Any] | None = None) -> str:
    clean_extract = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(extract))).strip()
    url = ""
    if content_urls and "desktop" in content_urls:
        url = content_urls["desktop"].get("page", "")

    header = f"### {title}"
    if description:
        header += f"\n*{description}*"
    
    source_link = f"\n\n[Read more on Wikipedia]({url})" if url else ""
    return f"{header}\n\n{clean_extract}{source_link}".strip()


def _error_result(action: str, detail: str) -> dict[str, Any]:
    return {
        "ok": False,
        "skill": "wikipedia",
        "action": action,
        "data": {},
        "meta": {"source": "wikipedia"},
        "presentation": {"type": "wikipedia_summary"},
        "errors": [detail],
    }
