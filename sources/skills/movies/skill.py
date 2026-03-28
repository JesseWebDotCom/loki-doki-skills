"""Movie lookup skill backed by the built-in search helper."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.skills.base import BaseSkill
from app.skills.local_runtime import parsed_search_results, title_case_phrase


class MoviesSkill(BaseSkill):
    """Return movie details and showtime summaries."""

    manifest: dict[str, Any] = {}

    async def execute(self, action: str, ctx: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Execute the requested movie action."""
        del kwargs
        self.validate_action(action)
        request_text = str(ctx.get("request_text", "")).strip()
        if action == "get_showtimes":
            return _showtimes_result(request_text, ctx)
        if action == "get_movie_details":
            return _details_result(request_text)
        raise ValueError(f"Unhandled action: {action}")


@dataclass(frozen=True)
class ShowtimeRequest:
    """Parsed movie-showtimes request details."""

    movie_title: str
    location: str
    date_label: str
    time_after_label: str
    theater_name: str


def _showtimes_result(request_text: str, ctx: dict[str, Any]) -> dict[str, Any]:
    parsed = _parse_showtime_request(request_text, ctx)
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


def _details_result(request_text: str) -> dict[str, Any]:
    title = _movie_title_from_request(request_text)
    if not title:
        return _error_result("get_movie_details", "Tell me which movie you want details for.")
    results = parsed_search_results(f"{title} runtime rating post credit scene", max_results=4)
    if not results:
        return _error_result("get_movie_details", f"I couldn't find movie details for {title}.")
    combined = " ".join(f"{item.get('title', '')} {item.get('snippet', '')}".strip() for item in results)
    runtime = _match_runtime(combined)
    rating = _match_rating(combined)
    post_credit = _match_post_credit(combined)
    detail_parts = [part for part in [runtime, rating] if part]
    if post_credit:
        detail_parts.append(post_credit)
    summary = f"I found {title}"
    if detail_parts:
        summary += " with " + ", ".join(detail_parts) + "."
    else:
        summary += ", but the top search results were light on specifics."
    return {
        "ok": True,
        "skill": "movies",
        "action": "get_movie_details",
        "data": {
            "title": title,
            "runtime": runtime,
            "rating": rating,
            "post_credit": post_credit,
            "results": results,
            "summary": summary,
        },
        "meta": {"source": "web_search"},
        "presentation": {"type": "movie_details"},
        "errors": [],
    }


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
    """Extract location, date, time window, and theater hints from a request."""
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
    """Return a likely movie title and location from a showtimes request."""
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
    """Return the requested date window."""
    for token in ("tomorrow", "tonight", "today", "this weekend"):
        if token in lowered:
            return token
    return "today"


def _extract_time_after_label(lowered: str) -> str:
    """Return an 'after X' time hint when present."""
    match = re.search(r"\bafter\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", lowered)
    if not match:
        return ""
    value = re.sub(r"\s+", "", match.group(1).upper())
    return value.replace("PM", " PM").replace("AM", " AM")


def _extract_location_label(cleaned: str, lowered: str) -> str:
    """Return a likely city/location phrase from a showtimes request."""
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
    """Return a known theater-brand phrase when present."""
    match = re.search(
        r"\b(?P<theater>(?:AMC|Regal|Cinemark|Showcase|Bow Tie|Cinepolis|Alamo Drafthouse|Marcus)[^,.;]*)",
        cleaned,
        flags=re.IGNORECASE,
    )
    return title_case_phrase(match.group("theater")) if match else ""


def _search_showtime_results(parsed: ShowtimeRequest) -> list[dict[str, str]]:
    """Search for showtimes and keep only likely theater/showtime results."""
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
    """Return stronger showtime-specific search query variants."""
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
    """Return whether a search result looks like a real showtimes result."""
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
    """Return whether the result looks like commentary/news instead of listings."""
    return any(token in haystack for token in _ARTICLE_SIGNALS)


def _contains_time(haystack: str) -> bool:
    """Return whether the text contains a likely movie time."""
    return bool(re.search(r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\b|\b\d{1,2}\s*(?:am|pm)\b", haystack))


def _contains_theater(haystack: str) -> bool:
    """Return whether the text contains a likely theater signal."""
    return any(token in haystack for token in _THEATER_SIGNALS)


def _location_matches(haystack: str, location: str) -> bool:
    """Return whether a result matches the requested location closely enough."""
    parts = [part.strip().lower() for part in re.split(r"[,/]", location) if part.strip()]
    words = [word for word in re.findall(r"[a-z0-9]+", location.lower()) if word not in _LOCATION_STOP_WORDS]
    return any(part in haystack for part in parts) or any(word in haystack for word in words)


def _apply_time_filter(results: list[dict[str, str]], time_after_label: str) -> list[dict[str, str]]:
    """Filter results by the requested lower time bound when possible."""
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
    """Return a concise natural-language summary of showtimes results."""
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
    """Return the user-facing showtimes target label."""
    target = f"{parsed.theater_name} {parsed.location}".strip()
    return target or "nearby theaters"


def _showtime_target_label(parsed: ShowtimeRequest) -> str:
    """Return the user-facing target label including movie title when known."""
    target = _target_label(parsed)
    if parsed.movie_title:
        if target == "nearby theaters":
            return f"{parsed.movie_title} near nearby theaters"
        return f"{parsed.movie_title} at {target}"
    return target


def _showtime_entry(result: dict[str, str]) -> dict[str, Any]:
    """Return structured showtime entry facts for character rendering."""
    title = str(result.get("title", "")).strip()
    snippet = str(result.get("snippet", "")).strip()
    return {
        "title": title,
        "times": _extract_display_times(_result_text(result)),
        "snippet": snippet,
        "source": str(result.get("source", "")).strip(),
    }


def _result_text(result: dict[str, str]) -> str:
    """Return combined title and snippet text."""
    return f"{result.get('title', '')} {result.get('snippet', '')}".strip()


def _extract_display_times(text: str) -> list[str]:
    """Return compact unique time strings from one result."""
    seen: set[str] = set()
    matches = re.findall(r"\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?|\d{1,2}\s*(?:AM|PM|am|pm))\b", text)
    display: list[str] = []
    for match in matches:
        normalized = re.sub(r"\s+", "", match.upper())
        if normalized in seen:
            continue
        seen.add(normalized)
        display.append(normalized.replace("PM", " PM").replace("AM", " AM"))
    return display


def _extract_times_as_minutes(text: str) -> list[int]:
    """Return times from text converted to minutes after midnight."""
    values: list[int] = []
    for match in _extract_display_times(text):
        minutes = _time_label_to_minutes(match)
        if minutes is not None:
            values.append(minutes)
    return values


def _time_label_to_minutes(label: str) -> int | None:
    """Convert a compact time label into minutes after midnight."""
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


_SHOWTIME_SIGNALS = (
    "showtimes",
    "movie times",
    "theaters",
    "theatre",
    "cinema",
    "cinemark",
    "regal",
    "amc",
    "fandango",
)

_THEATER_SIGNALS = (
    "cinemark",
    "regal",
    "amc",
    "showcase",
    "bow tie",
    "cinepolis",
    "drafthouse",
    "theater",
    "theatre",
    "cinema",
)

_ARTICLE_SIGNALS = (
    "things we learned",
    "explained",
    "review",
    "ending",
    "trailer",
    "interview",
    "news",
    "celebrity",
    "swiftie",
    "tayvis",
    "backstage",
)

_LOCATION_STOP_WORDS = {"movie", "showtimes", "theaters", "theatre", "cinema", "after"}
_DATE_LABELS = {"today", "tonight", "tomorrow", "this weekend"}
