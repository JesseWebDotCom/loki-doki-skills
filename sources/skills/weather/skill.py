import httpx
from core.base_skill import BaseSkill

class WeatherSkill(BaseSkill):
    manifest = {
        "id": "weather",
        "domain": "weather",
        "title": "Weather",
        "actions": {"get_current": {}, "get_forecast": {}},
    }

    async def execute(self, action: str, ctx: dict, **kwargs) -> dict:
        self.validate_action(action)
        if action == "get_current":
            return await self.get_current(ctx, **kwargs)
        if action == "get_forecast":
            return await self.get_forecast(ctx, **kwargs)
        raise ValueError(f"Unhandled action: {action}")

    def _resolve_location(self, ctx: dict, location: tuple[float, float] | None = None) -> tuple[float, float]:
        if location:
            return location
        if "location" not in ctx or not ctx["location"]:
            raise ValueError("Weather skill requires location context")
        return ctx["location"]

    async def get_current(self, ctx: dict, location: tuple[float, float] | None = None) -> dict:
        lat, lon = self._resolve_location(ctx, location)
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

    async def get_forecast(self, ctx: dict, date: str = "today", location: tuple[float, float] | None = None) -> dict:
        lat, lon = self._resolve_location(ctx, location)
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
