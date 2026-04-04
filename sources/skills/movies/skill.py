"""Movie lookup skill backed by the built-in search helper and Wikipedia Infobox scraping."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Awaitable, Callable

import httpx
from bs4 import BeautifulSoup

from app.skills.base import BaseSkill
from app.skills.local_runtime import parsed_search_results, title_case_phrase


@dataclass(frozen=True)
class ShowtimeRequest:
    """Parsed movie-showtimes request details."""

    movie_title: str
    location: str
    date_label: str
    time_after_label: str
    theater_name: str


class MoviesSkill(BaseSkill):
    """Return movie details and showtime summaries."""

    manifest: dict[str, Any] = {}

    async def execute(
        self,
        action: str,
        ctx: dict[str, Any],
        emit_progress: Callable[[str], Awaitable[None]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute the requested movie action."""
        del kwargs
        self.validate_action(action)
        request_text = str(ctx.get("request_text", "")).strip()

        async with httpx.AsyncClient(timeout=12.0) as client:
            if action == "get_showtimes":
                await emit_progress("Searching for local showtimes...")
                return await _showtimes_result(client, request_text, ctx)
            if action == "get_movie_details":
                await emit_progress("Fetching movie details...")
                return await _details_result(client, request_text)
        
        raise ValueError(f"Unhandled action: {action}")


async def _showtimes_result(client: httpx.AsyncClient, request_text: str, ctx: dict[str, Any]) -> dict[str, Any]:
    parsed = _parse_showtime_request(request_text, ctx)
    # Note: parsed_search_results is currently a sync wrapper around a search provider.
    # In a full async migration, this would also be awaited via client.
    search_results = _search_showtime_results(parsed)
    
    if not search_results:
        return _error_result(
            "get_showtimes",
            f"I couldn't find reliable movie showtimes for {_target_label(parsed)}. Try adding a theater name or city.",
        )
    filtered_results = _apply_time_filter(search_results, parsed.time_after_label)
    if not filtered_results:
        return _error_result(
            "get_showtimes",
            f"I found theaters for {_target_label(parsed)}, but nothing clearly matched after {parsed.time_after_label}.",
        )
    summary = _showtimes_summary(filtered_results, parsed)
    return {
        "ok": True,
        "skill": "movies",
        "action": "get_showtimes",
        "data": {
            "movie_title": parsed.movie_title,
            "location": parsed.location,
            "theater_name": parsed.theater_name,
            "date": parsed.date_label,
            "time_after": parsed.time_after_label,
            "results": filtered_results,
            "showtime_entries": [_showtime_entry(result) for result in filtered_results],
            "summary": summary,
        },
        "meta": {"source": "web_search"},
        "presentation": {"type": "movie_showtimes"},
        "errors": [],
    }


async def _details_result(client: httpx.AsyncClient, request_text: str) -> dict[str, Any]:
    title = _movie_title_from_request(request_text)
    if not title:
        return _error_result("get_movie_details", "Tell me which movie you want details for.")

    # Try Wikipedia Infobox first for deterministic metadata
    infobox = await _fetch_wikipedia_metadata(client, title)
    
    runtime = infobox.get("Running time", "") or infobox.get("Runtime", "")
    rating = _clean_rating(infobox.get("Rating", ""))
    
    # Fallback to search snippets if Wikipedia was sparse
    if not runtime or not rating:
        results = parsed_search_results(f"{title} movie runtime rating post credit scene", max_results=4)
        combined = " ".join(f"{item.get('title', '')} {item.get('snippet', '')}".strip() for item in results)
        if not runtime:
            runtime = _match_runtime(combined)
        if not rating:
            rating = _match_rating(combined)
        post_credit = _match_post_credit(combined)
    else:
        # Still search for post-credits as it's rarely in the primary infobox
        results = parsed_search_results(f"{title} post credit scene", max_results=2)
        combined = " ".join(f"{item.get('title', '')} {item.get('snippet', '')}".strip() for item in results)
        post_credit = _match_post_credit(combined)

    detail_parts = [part for part in [runtime, rating] if part]
    if post_credit:
        detail_parts.append(post_credit)
        
    summary = f"I found {title}"
    if detail_parts:
        summary += " with " + ", ".join(detail_parts) + "."
    else:
        summary += ", but the available sources were light on specifics."

    return {
        "ok": True,
        "skill": "movies",
        "action": "get_movie_details",
        "data": {
            "title": title,
            "runtime": runtime,
            "rating": rating,
            "post_credit": post_credit,
            "infobox_source": bool(infobox),
            "summary": summary,
        },
        "meta": {"source": "wikipedia + web_search" if infobox else "web_search"},
        "presentation": {"type": "movie_details"},
        "errors": [],
    }


async def _fetch_wikipedia_metadata(client: httpx.AsyncClient, title: str) -> dict[str, str]:
    """Search Wikipedia and scrape the infobox for movie details."""
    search_url = "https://en.wikipedia.org/w/api.php"
    params = {"action": "query", "list": "search", "srsearch": f"{title} (film)", "format": "json", "srlimit": 1}
    try:
        search_response = await client.get(search_url, params=params)
        results = search_response.json().get("query", {}).get("search", [])
        if not results:
            return {}
            
        real_title = results[0]["title"]
        summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{real_title.replace(' ', '_')}"
        summary_response = await client.get(summary_url)
        payload = summary_response.json()
        
        page_url = str(payload.get("content_urls", {}).get("desktop", {}).get("page", "")).strip()
        if not page_url:
            return {}
            
        page_response = await client.get(page_url)
        if page_response.status_code != 200:
            return {}
            
        return _scrape_infobox(page_response.text)
    except Exception:
        return {}


def _scrape_infobox(html_content: str) -> dict[str, str]:
    """Parse the Wikipedia infobox into a clean dictionary."""
    soup = BeautifulSoup(html_content, "html.parser")
    infobox = soup.find("table", {"class": "infobox"})
    if not infobox:
        return {}

    parsed: dict[str, str] = {}
    for row in infobox.find_all("tr"):
        label = row.find("th", {"class": "infobox-label"})
        value = row.find("td", {"class": "infobox-data"})
        if not label or not value:
            continue
        key = label.get_text(strip=True)
        cleaned_value = re.sub(r"\[.*?\]", "", value.get_text(separator=", ", strip=True)).strip(", ")
        if key and cleaned_value:
            parsed[key] = cleaned_value
    return parsed


def _clean_rating(value: str) -> str:
    if not value:
        return ""
    match = re.search(r"\b(G|PG|PG-13|R|NC-17)\b", value, flags=re.IGNORECASE)
    return f"rated {match.group(1).upper()}" if match else ""


def _movie_title_from_request(request_text: str) -> str:
    cleaned = re.sub(r"\s+", " ", request_text.strip(" ?!"))
    patterns = (
        r"(?i)(?:does|did|is|was)\s+(?P<title>.+?)\s+(?:have|has|got)\b",
        r"(?i)(?:what(?:'s| is) the runtime for|tell me about|movie details for|is)\s+(?P<title>.+)$",
        r"(?i)(?P<title>.+?)\s+(?:runtime|rating|post[- ]credit scene)s?$",
    )
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            return title_case_phrase(match.group("title").strip(" ."))
    return title_case_phrase(cleaned)


def _match_runtime(value: str) -> str:
    match = re.search(r"(?i)\b(\d{1,2}h(?:\s*\d{1,2}m)?|\d{2,3}\s*min(?:ute)?s?)\b", value)
    return match.group(1) if match else ""


def _match_rating(value: str) -> str:
    match = re.search(r"\b(G|PG|PG-13|R|NC-17|TV-MA)\b", value, flags=re.IGNORECASE)
    return f"rated {match.group(1).upper()}" if match else ""


def _match_post_credit(value: str) -> str:
    lowered = value.lower()
    if "no post-credit" in lowered or "no post credit" in lowered or "no end-credit" in lowered:
        return "no post-credit scene mentioned"
    if "post-credit scene" in lowered or "post credit scene" in lowered or "mid-credit scene" in lowered:
        return "a post-credit scene is mentioned"
    return ""


def _error_result(action: str, detail: str) -> dict[str, Any]:
    return {
        "ok": False,
        "skill": "movies",
        "action": action,
        "data": {},
        "meta": {"source": "web_search"},
        "presentation": {"type": "movie_details"},
        "errors": [detail],
    }


def _parse_showtime_request(request_text: str, ctx: dict[str, Any]) -> ShowtimeRequest:
    cleaned = " ".join(request_text.strip().split())
    lowered = cleaned.lower()
    date_label = _extract_date_label(lowered)
    time_after_label = _extract_time_after_label(lowered)
    movie_title, location = _extract_movie_title_and_location(cleaned, lowered)
    if not location:
        location = _extract_location_label(cleaned, lowered)
    theater_name = _extract_theater_name(cleaned)
    if not location:
        location = str(ctx.get("location") or "").strip()
    if not theater_name:
        theater_name = str(ctx.get("theater_name") or "").strip()
    return ShowtimeRequest(
        movie_title=movie_title,
        location=location,
        date_label=date_label,
        time_after_label=time_after_label,
        theater_name=theater_name,
    )


def _extract_movie_title_and_location(cleaned: str, lowered: str) -> tuple[str, str]:
    patterns = (
        r"(?i)\bshowtimes?\s+for\s+(?P<title>.+?)\s+in\s+(?P<location>.+?)(?:\s+(?:today|tonight|tomorrow|this weekend|after)\b|$)",
        r"(?i)\bmovies?\s+for\s+(?P<title>.+?)\s+in\s+(?P<location>.+?)(?:\s+(?:today|tonight|tomorrow|this weekend|after)\b|$)",
        r"(?i)\bplaying\s+(?P<title>.+?)\s+in\s+(?P<location>.+?)(?:\s+(?:today|tonight|tomorrow|this weekend|after)\b|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if not match:
            continue
        title = title_case_phrase(match.group("title").strip(" .,!?:;"))
        location = title_case_phrase(match.group("location").strip(" .,!?:;"))
        if title and location:
            return title, location
    return "", ""


def _extract_date_label(lowered: str) -> str:
    for token in ("tomorrow", "tonight", "today", "this weekend"):
        if token in lowered:
            return token
    return "today"


def _extract_time_after_label(lowered: str) -> str:
    match = re.search(r"\bafter\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", lowered)
    if not match:
        return ""
    value = re.sub(r"\s+", "", match.group(1).upper())
    return value.replace("PM", " PM").replace("AM", " AM")


def _extract_location_label(cleaned: str, lowered: str) -> str:
    patterns = (
        r"\bfor (?P<location>.+?)(?:\s+(?:today|tonight|tomorrow|this weekend|after)\b|$)",
        r"\bin (?P<location>.+?)(?:\s+(?:today|tonight|tomorrow|this weekend|after)\b|$)",
        r"\bnear (?P<location>.+?)(?:\s+(?:today|tonight|tomorrow|this weekend|after)\b|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            location = match.group("location").strip(" .,!?:;")
            if location and location not in {"movie showtimes", "showtimes"} and location not in _DATE_LABELS:
                return title_case_phrase(location)
    if any(token in lowered for token in ("showtimes", "movies", "playing")):
        return ""
    return title_case_phrase(cleaned)


def _extract_theater_name(cleaned: str) -> str:
    match = re.search(
        r"\b(?P<theater>(?:AMC|Regal|Cinemark|Showcase|Bow Tie|Cinepolis|Alamo Drafthouse|Marcus)[^,.;]*)",
        cleaned,
        flags=re.IGNORECASE,
    )
    return title_case_phrase(match.group("theater")) if match else ""


def _search_showtime_results(parsed: ShowtimeRequest) -> list[dict[str, str]]:
    queries = _candidate_showtime_queries(parsed)
    seen_keys: set[tuple[str, str]] = set()
    matched: list[dict[str, str]] = []
    for query in queries:
        for result in parsed_search_results(query, max_results=5):
            title = str(result.get("title", "")).strip()
            snippet = str(result.get("snippet", "")).strip()
            key = (title, snippet)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            if not _looks_like_showtime_result(title, snippet, parsed):
                continue
            matched.append(result)
            if len(matched) >= 5:
                return matched
    return matched


def _candidate_showtime_queries(parsed: ShowtimeRequest) -> list[str]:
    target = _target_label(parsed)
    movie_target = f"{parsed.movie_title} {target}".strip()
    queries = [
        f"{movie_target} movie showtimes {parsed.date_label}",
        f"{movie_target} theaters {parsed.date_label} showtimes",
    ]
    if parsed.time_after_label:
        queries.insert(1, f"{movie_target} movie showtimes {parsed.date_label} after {parsed.time_after_label}")
    if parsed.theater_name:
        theater_target = f"{parsed.theater_name} {parsed.movie_title}".strip()
        queries.insert(0, f"{theater_target} {parsed.date_label} showtimes")
    return [query.strip() for query in queries if query.strip()]


def _looks_like_showtime_result(title: str, snippet: str, parsed: ShowtimeRequest) -> bool:
    haystack = f"{title} {snippet}".lower()
    if _looks_like_article(haystack):
        return False
    if not any(signal in haystack for signal in _SHOWTIME_SIGNALS):
        return False
    if not (_contains_time(haystack) or _contains_theater(haystack)):
        return False
    if parsed.location and not _location_matches(haystack, parsed.location):
        return False
    return True


def _looks_like_article(haystack: str) -> bool:
    return any(token in haystack for token in _ARTICLE_SIGNALS)


def _contains_time(haystack: str) -> bool:
    return bool(re.search(r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\b|\b\d{1,2}\s*(?:am|pm)\b", haystack))


def _contains_theater(haystack: str) -> bool:
    return any(token in haystack for token in _THEATER_SIGNALS)


def _location_matches(haystack: str, location: str) -> bool:
    parts = [part.strip().lower() for part in re.split(r"[,/]", location) if part.strip()]
    words = [word for word in re.findall(r"[a-z0-9]+", location.lower()) if word not in _LOCATION_STOP_WORDS]
    return any(part in haystack for part in parts) or any(word in haystack for word in words)


def _apply_time_filter(results: list[dict[str, str]], time_after_label: str) -> list[dict[str, str]]:
    if not time_after_label:
        return results
    requested_minutes = _time_label_to_minutes(time_after_label)
    if requested_minutes is None:
        return results
    filtered = [
        result for result in results
        if any(minutes >= requested_minutes for minutes in _extract_times_as_minutes(_result_text(result)))
    ]
    return filtered or results


def _showtimes_summary(results: list[dict[str, str]], parsed: ShowtimeRequest) -> str:
    target = _showtime_target_label(parsed)
    lines: list[str] = []
    requested_minutes = _time_label_to_minutes(parsed.time_after_label) if parsed.time_after_label else None
    for result in results[:3]:
        title = str(result.get("title", "")).strip()
        snippet = str(result.get("snippet", "")).strip()
        times = _extract_display_times(_result_text(result))
        if requested_minutes is not None:
            times = [
                time_label
                for time_label in times
                if (_time_label_to_minutes(time_label) or -1) >= requested_minutes
            ]
        if times:
            lines.append(f"{title}: {', '.join(times[:4])}")
        elif snippet:
            lines.append(f"{title}: {snippet}")
        else:
            lines.append(title)
    summary = f"For {target} {parsed.date_label}, I found these showtimes: " + "; ".join(lines) + "."
    if parsed.time_after_label:
        summary = f"For {target} {parsed.date_label} after {parsed.time_after_label}, I found: " + "; ".join(lines) + "."
    return summary


def _target_label(parsed: ShowtimeRequest) -> str:
    target = f"{parsed.theater_name} {parsed.location}".strip()
    return target or "nearby theaters"


def _showtime_target_label(parsed: ShowtimeRequest) -> str:
    target = _target_label(parsed)
    if parsed.movie_title:
        if target == "nearby theaters":
            return f"{parsed.movie_title} near nearby theaters"
        return f"{parsed.movie_title} at {target}"
    return target


def _showtime_entry(result: dict[str, str]) -> dict[str, Any]:
    title = str(result.get("title", "")).strip()
    snippet = str(result.get("snippet", "")).strip()
    return {
        "title": title,
        "times": _extract_display_times(_result_text(result)),
        "snippet": snippet,
        "source": str(result.get("source", "")).strip(),
    }


def _result_text(result: dict[str, str]) -> str:
    return f"{result.get('title', '')} {result.get('snippet', '')}".strip()


def _extract_display_times(text: str) -> list[str]:
    seen: set[str] = set()
    matches = re.findall(r"\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?|\d{1,2}\s*(?:AM|PM|am|pm))\b", text)
    display: list[str] = []
    for match in matches:
        normalized = re.sub(r"\s+", " ", match.upper())
        if normalized in seen:
            continue
        seen.add(normalized)
        display.append(normalized.replace("PM", " PM").replace("AM", " AM"))
    return display


def _extract_times_as_minutes(text: str) -> list[int]:
    values: list[int] = []
    for match in _extract_display_times(text):
        minutes = _time_label_to_minutes(match)
        if minutes is not None:
            values.append(minutes)
    return values


def _time_label_to_minutes(label: str) -> int | None:
    normalized = re.sub(r"\s+", "", label.strip().lower())
    match = re.fullmatch(r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?(?P<period>am|pm)?", normalized)
    if not match:
        return None
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or "0")
    period = match.group("period")
    if period == "pm" and hour < 12:
        hour += 12
    if period == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


_SHOWTIME_SIGNALS = ("showtimes", "movie times", "theaters", "theatre", "cinema", "cinemark", "regal", "amc", "fandango")
_THEATER_SIGNALS = ("cinemark", "regal", "amc", "showcase", "bow tie", "cinepolis", "drafthouse", "theater", "theatre", "cinema")
_ARTICLE_SIGNALS = ("things we learned", "explained", "review", "ending", "trailer", "interview", "news", "celebrity", "swiftie", "tayvis", "backstage")
_LOCATION_STOP_WORDS = {"movie", "showtimes", "theaters", "theatre", "cinema", "after"}
_DATE_LABELS = {"today", "tonight", "tomorrow", "this weekend"}
