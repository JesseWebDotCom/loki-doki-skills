"""Installable weather skill package."""

from __future__ import annotations

import re
from typing import Any

from app.skills.base import BaseSkill
from app.subsystems.text.web_search import search_web


class WeatherSkill(BaseSkill):
    """Return a structured weather report."""

    manifest: dict[str, Any] = {}

    async def execute(self, action: str, ctx: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Execute the requested weather action."""
        self.validate_action(action)
        if action != "get_weather":
            raise ValueError(f"Unhandled action: {action}")
        request_text = str(ctx.get("request_text") or "").strip().lower()
        requested_location = str(kwargs.get("location") or ctx.get("location") or "local").strip()
        date_hint = str(kwargs.get("date") or "today").strip()
        result = search_web(f"weather in {requested_location} {date_hint}".strip())
        metadata = result.metadata or {}
        if not metadata:
            return {
                "ok": False,
                "skill": "weather",
                "action": "get_weather",
                "data": {"location": requested_location},
                "meta": {"source": result.source},
                "presentation": {"type": "weather_report"},
                "errors": ["Weather data is unavailable right now."],
            }
        resolved_location = _preferred_location(requested_location, str(metadata.get("location") or ""))
        return {
            "ok": True,
            "skill": "weather",
            "action": "get_weather",
            "data": {
                "location": resolved_location,
                "condition": metadata.get("description", "current conditions"),
                "current_temp_f": metadata.get("current_temp_f", ""),
                "high_temp_f": metadata.get("high_temp_f", ""),
                "low_temp_f": metadata.get("low_temp_f", ""),
                "chance_of_rain": metadata.get("chance_of_rain", ""),
                "peak_chance_of_rain": metadata.get("peak_chance_of_rain", metadata.get("chance_of_rain", "")),
                "chance_of_snow": metadata.get("chance_of_snow", ""),
                "chance_of_sleet": metadata.get("chance_of_sleet", ""),
                "wind_mph": metadata.get("wind_mph", ""),
                "wind_direction": metadata.get("wind_direction", ""),
                "date": date_hint,
                "summary": _weather_summary(metadata, request_text, resolved_location),
            },
            "meta": {"source": result.source, "cache_hit": False},
            "presentation": {"type": "weather_report"},
            "errors": [],
        }


def _weather_summary(metadata: dict[str, Any], request_text: str, location_label: str) -> str:
    """Return a more conversational reply matched to the user's ask."""
    location = _display_location(location_label or str(metadata.get("location") or "your area"))
    condition = str(metadata.get("description") or "current conditions").lower()
    high = str(metadata.get("high_temp_f") or "?")
    low = str(metadata.get("low_temp_f") or "?")
    if _mentions(request_text, ("snow", "snowing", "flurries", "blizzard")):
        chance = _int_value(metadata.get("chance_of_snow"))
        if chance > 0 or "snow" in condition:
            return f"It does look like snow is possible in {location}. The forecast shows {condition} with about a {chance}% chance of snow, plus a high of {high} F and a low of {low} F."
        return f"I don't see snow in the forecast for {location} right now. It looks {condition}, with a high of {high} F and a low of {low} F."
    if _mentions(request_text, ("rain", "umbrella", "raining", "storm")):
        chance = _int_value(metadata.get("chance_of_rain"))
        if chance >= 30 or "rain" in condition or "storm" in condition:
            return f"Rain looks possible in {location}. The forecast has about a {chance}% chance of rain, with {condition} conditions and temperatures from {low} F to {high} F."
        return f"I don't see much rain risk in {location} right now. The forecast looks {condition}, with only about a {chance}% chance of rain."
    if _mentions(request_text, ("sleet", "icy", "freezing rain")):
        chance = _int_value(metadata.get("chance_of_sleet"))
        if chance > 0 or "sleet" in condition:
            return f"Sleet is in the mix for {location}. The forecast shows about a {chance}% chance, with a high of {high} F and a low of {low} F."
        return f"I don't see sleet called out in the current {location} forecast. It looks {condition}, with temperatures between {low} F and {high} F."
    average_rain = _int_value(metadata.get("chance_of_rain"))
    peak_rain = _int_value(metadata.get("peak_chance_of_rain"))
    if peak_rain >= 60:
        return (
            f"In {location}, it's {condition} with a high of {high} F and a low of {low} F. "
            f"Rain risk builds later, with around a {average_rain}% overall chance and peaks near {peak_rain}%."
        )
    return f"In {location}, it's {condition} with a high of {high} F and a low of {low} F."


def _mentions(request_text: str, tokens: tuple[str, ...]) -> bool:
    """Return whether any token appears in the original weather request."""
    return any(re.search(rf"\b{re.escape(token)}\b", request_text) for token in tokens)


def _int_value(value: Any) -> int:
    """Return a best-effort integer chance value."""
    text = str(value or "").strip()
    return int(text) if text.isdigit() else 0


def _display_location(location: str) -> str:
    """Return a user-facing location label."""
    stripped = location.strip()
    return stripped.title() if stripped.islower() else stripped


def _preferred_location(requested_location: str, provider_location: str) -> str:
    """Prefer the more specific location label when the provider response is vague."""
    requested = requested_location.strip()
    provider = provider_location.strip()
    if requested and "," in requested:
        return requested
    return provider or requested or "local"
