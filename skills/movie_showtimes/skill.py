import httpx
from core.base_skill import BaseSkill

class MovieShowtimesSkill(BaseSkill):
    manifest = {
        "id": "movie_showtimes",
        "domain": "movies",
        "title": "Movie Showtimes",
        "actions": {
            "get_showtimes": {},
        },
    }

    async def execute(self, action: str, ctx: dict, **kwargs) -> dict:
        self.validate_action(action)
        if action == "get_showtimes":
            return await self.get_showtimes(ctx, **kwargs)
        raise ValueError(f"Unhandled action: {action}")

    def _resolve_location(self, ctx: dict, location=None):
        if location: return location
        if "location" not in ctx or not ctx["location"]: raise ValueError("Movie showtimes skill requires location context")
        return ctx["location"]

    async def _fetch_from_provider(self, lat: float, lon: float, date: str, movie_title: str | None, preferred_theater: str | None) -> list[dict] | None:
        return None

    async def _fallback_web_search(self, ctx: dict, lat: float, lon: float, date: str, movie_title: str | None) -> list[dict]:
        skill_manager = ctx.get("skill_manager")
        if not skill_manager: return []
        query = f"movie showtimes near {lat},{lon} {date}"
        if movie_title: query = f"{movie_title} showtimes near {lat},{lon} {date}"
        try:
            result = await skill_manager.execute(skill_id="web_search", action="search", ctx=ctx, query=query, num_results=5)
            if result.get("ok") and result.get("data", {}).get("results"):
                return result["data"]["results"]
        except Exception:
            pass
        return []

    async def get_showtimes(self, ctx: dict, date: str = "today", movie_title: str | None = None, location=None, preferred_theater: str | None = None) -> dict:
        lat, lon = self._resolve_location(ctx, location)
        results = await self._fetch_from_provider(lat, lon, date, movie_title, preferred_theater)
        source = "showtimes_provider"
        used_fallback = False
        if not results:
            results = await self._fallback_web_search(ctx, lat, lon, date, movie_title)
            source = "web_search_fallback"
            used_fallback = True
        return {
            "ok": True,
            "skill": "movie_showtimes",
            "action": "get_showtimes",
            "data": {
                "date": date, "location": {"latitude": lat, "longitude": lon},
                "movie_title": movie_title, "preferred_theater": preferred_theater,
                "results": results, "used_fallback": used_fallback,
            },
            "meta": {"source": source, "cache_hit": False, "execution_mode": "detailed"},
            "presentation": {
                "type": "showtimes_list" if not used_fallback else "search_results",
                "max_voice_items": 3, "max_screen_items": 10,
                "speak_priority_fields": ["movie", "theater", "times"],
            },
            "errors": [],
        }
