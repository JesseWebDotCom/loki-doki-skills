"""Weather skill backed by Open-Meteo."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

import httpx

from app.skills.base import BaseSkill


class WeatherSkill(BaseSkill):
    """Return current weather and forecasts."""

    async def execute(
        self,
        action: str,
        ctx: dict[str, Any],
        emit_progress: Callable[[str], Awaitable[None]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute the requested weather action."""
        self.validate_action(action)
        if action == "get_current":
            await emit_progress("Checking current weather...")
            return await self.get_current(ctx, **kwargs)
        if action == "get_forecast":
            await emit_progress("Fetching weather forecast...")
            return await self.get_forecast(ctx, **kwargs)
        raise ValueError(f"Unhandled action: {action}")

    def _resolve_location(self, ctx: dict[str, Any], location: tuple[float, float] | None = None) -> tuple[float, float] | None:
        if location:
            return location
        # Check ctx['location'] which is usually injected by the context manager/geo provider
        loc = ctx.get("location")
        if not loc or not isinstance(loc, (list, tuple)) or len(loc) < 2:
            return None
        return (float(loc[0]), float(loc[1]))

    async def get_current(self, ctx: dict[str, Any], location: tuple[float, float] | None = None) -> dict[str, Any]:
        res = self._resolve_location(ctx, location)
        if res is None:
            return {
                "ok": False,
                "skill": "weather",
                "action": "get_current",
                "result": {},
                "errors": ["Location not found. Please set a home location or provide coordinates."],
            }
        lat, lon = res
        async with httpx.AsyncClient(timeout=4.0) as client:
            response = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={"latitude": lat, "longitude": lon, "current_weather": True},
            )
            payload = response.json()
        current = payload.get("current_weather", {})
        return {
            "ok": True,
            "skill": "weather",
            "action": "get_current",
            "data": {
                "temperature": current.get("temperature"),
                "windspeed": current.get("windspeed"),
                "weathercode": current.get("weathercode"),
                "location": {"latitude": lat, "longitude": lon},
            },
            "meta": {"source": "open_meteo", "cache_hit": False, "execution_mode": "fast"},
            "presentation": {
                "type": "weather_current",
                "max_voice_items": 1,
                "max_screen_items": 1,
                "speak_priority_fields": ["temperature", "weathercode", "windspeed"],
            },
            "errors": [],
        }

    async def get_forecast(
        self, ctx: dict[str, Any], date: str = "today", location: tuple[float, float] | None = None
    ) -> dict[str, Any]:
        res = self._resolve_location(ctx, location)
        if res is None:
            return {
                "ok": False,
                "skill": "weather",
                "action": "get_forecast",
                "result": {},
                "errors": ["Location not found. Please set a home location or provide coordinates."],
            }
        lat, lon = res
        async with httpx.AsyncClient(timeout=4.0) as client:
            response = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat, "longitude": lon,
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "timezone": "auto",
                },
            )
            payload = response.json()
        return {
            "ok": True,
            "skill": "weather",
            "action": "get_forecast",
            "data": {"date": date, "location": {"latitude": lat, "longitude": lon}, "daily": payload.get("daily", {})},
            "meta": {"source": "open_meteo", "cache_hit": False, "execution_mode": "detailed"},
            "presentation": {
                "type": "weather_forecast",
                "max_voice_items": 1,
                "max_screen_items": 5,
                "speak_priority_fields": ["date", "daily"],
            },
            "errors": [],
        }
