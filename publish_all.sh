#!/bin/bash
set -e

COMMIT_MSG="$1"
if [ -z "$COMMIT_MSG" ]; then
    read -r -p "Enter commit message: " COMMIT_MSG
    if [ -z "$COMMIT_MSG" ]; then
        echo "Error: Commit message cannot be empty."
        exit 1
    fi
fi

sync_repo() {
    local repo_dir="$1"
    echo "🚀 Syncing $repo_dir..."
    if [ ! -d "$repo_dir" ]; then
        echo "⚠️  Directory not found: $repo_dir (skipping)"
        return
    fi
    cd "$repo_dir"
    if [ -n "$(git status --porcelain)" ]; then
        git add .
        git commit -m "$COMMIT_MSG"
        git push origin main
        echo "✅ Successfully pushed changes for $repo_dir."
    else
        echo "⏭️  No uncommitted changes in $repo_dir (skipping push)."
    fi
    echo ""
}

sync_repo "$HOME/Projects/loki-doki"

echo "🚀 Generating skill files in loki-doki-skills repo..."
cd ~/Projects/loki-doki-skills

# ---------------------------------------------------------
# 1. WEATHER SKILL
# ---------------------------------------------------------
echo "Scaffolding Weather skill..."
mkdir -p skills/weather

cat << 'EOF' > skills/weather/manifest.json
{
  "schema_version": 1,
  "id": "weather",
  "title": "Weather",
  "domain": "weather",
  "description": "Current weather and short forecast.",
  "version": "1.0.0",
  "load_type": "lazy",
  "account_mode": "none",
  "system": false,
  "enabled_by_default": true,
  "required_context": ["location"],
  "optional_context": ["timezone", "units"],
  "permissions": {
    "default": "all_users"
  },
  "runtime_dependencies": [
    { "package": "httpx", "version": ">=0.27.0" }
  ],
  "skill_dependencies": {
    "required": [],
    "optional": []
  },
  "actions": {
    "get_current": {
      "title": "Get Current Weather",
      "description": "Return current weather conditions.",
      "enabled": true,
      "required_context": ["location"],
      "optional_context": ["timezone", "units"],
      "timeout_ms": 4000,
      "cache_ttl_sec": 600,
      "phrases": ["what's the weather", "current weather", "weather right now"],
      "keywords": ["weather", "temperature", "forecast", "outside"],
      "negative_keywords": ["movie", "calendar", "light"],
      "required_entities": [],
      "optional_entities": []
    },
    "get_forecast": {
      "title": "Get Forecast",
      "description": "Return forecast for a date or short range.",
      "enabled": true,
      "required_context": ["location"],
      "optional_context": ["timezone", "units"],
      "timeout_ms": 4000,
      "cache_ttl_sec": 1800,
      "phrases": ["weather tomorrow", "forecast", "will it rain", "do I need an umbrella"],
      "keywords": ["forecast", "tomorrow", "rain", "umbrella", "weather"],
      "negative_keywords": ["movie", "calendar", "showtimes"],
      "required_entities": [],
      "optional_entities": ["date"]
    }
  }
}
EOF

cat << 'EOF' > skills/weather/skill.py
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
EOF

# ---------------------------------------------------------
# 2. HOME ASSISTANT SKILL
# ---------------------------------------------------------
echo "Scaffolding Home Assistant skill..."
mkdir -p skills/home_assistant

cat << 'EOF' > skills/home_assistant/manifest.json
{
  "schema_version": 1,
  "id": "home_assistant",
  "title": "Home Assistant",
  "domain": "smart_home",
  "description": "Control and query Home Assistant devices.",
  "version": "1.0.0",
  "load_type": "warm",
  "account_mode": "multiple",
  "system": false,
  "enabled_by_default": false,
  "required_context": [],
  "optional_context": ["site", "room", "user_id"],
  "permissions": {"default": "trusted_users"},
  "runtime_dependencies": [{ "package": "httpx", "version": ">=0.27.0" }],
  "skill_dependencies": {"required": [], "optional": []},
  "actions": {
    "turn_on": {
      "title": "Turn On",
      "enabled": true,
      "required_context": [],
      "optional_context": ["site", "room"],
      "timeout_ms": 4000,
      "cache_ttl_sec": 0,
      "phrases": ["turn on", "switch on", "enable"],
      "keywords": ["turn on", "light", "lamp", "switch", "fan"],
      "required_entities": ["target_entity"],
      "optional_entities": ["site", "room"]
    },
    "turn_off": {
      "title": "Turn Off",
      "enabled": true,
      "required_context": [],
      "optional_context": ["site", "room"],
      "timeout_ms": 4000,
      "cache_ttl_sec": 0,
      "phrases": ["turn off", "switch off", "disable"],
      "keywords": ["turn off", "light", "lamp", "switch", "fan"],
      "required_entities": ["target_entity"],
      "optional_entities": ["site", "room"]
    },
    "get_state": {
      "title": "Get State",
      "enabled": true,
      "required_context": [],
      "optional_context": ["site", "room"],
      "timeout_ms": 4000,
      "cache_ttl_sec": 5,
      "phrases": ["is the", "what is the status of", "what's the status of"],
      "keywords": ["status", "state", "on", "off", "temperature"],
      "required_entities": ["target_entity"],
      "optional_entities": ["site", "room"]
    }
  }
}
EOF

cat << 'EOF' > skills/home_assistant/skill.py
import httpx
from core.base_skill import BaseSkill

class HomeAssistantSkill(BaseSkill):
    manifest = {
        "id": "home_assistant",
        "domain": "smart_home",
        "title": "Home Assistant",
        "actions": {"turn_on": {}, "turn_off": {}, "get_state": {}},
    }

    async def execute(self, action: str, ctx: dict, **kwargs) -> dict:
        self.validate_action(action)
        if action == "turn_on": return await self.turn_on(ctx, **kwargs)
        if action == "turn_off": return await self.turn_off(ctx, **kwargs)
        if action == "get_state": return await self.get_state(ctx, **kwargs)
        raise ValueError(f"Unhandled action: {action}")

    def _resolve_account(self, ctx: dict, account_id: str | None) -> dict:
        account = ctx["accounts"].resolve("home_assistant", account_id)
        if not account: raise ValueError("No Home Assistant account available")
        return account

    async def turn_on(self, ctx: dict, target_entity: str, account_id: str | None = None) -> dict:
        account = self._resolve_account(ctx, account_id)
        domain = target_entity.split(".")[0]
        async with httpx.AsyncClient(timeout=4.0) as client:
            await client.post(
                f"{account['url']}/api/services/{domain}/turn_on",
                headers={"Authorization": f"Bearer {account['token']}", "Content-Type": "application/json"},
                json={"entity_id": target_entity},
            )
        return {
            "ok": True, "skill": "home_assistant", "action": "turn_on",
            "data": {"entity_id": target_entity, "account": account["id"], "state": "on"},
            "meta": {"source": "home_assistant", "cache_hit": False, "execution_mode": "fast"},
            "presentation": {"type": "entity_state_change", "max_voice_items": 1, "max_screen_items": 1, "speak_priority_fields": ["entity_id", "state"]},
            "errors": [],
        }

    async def turn_off(self, ctx: dict, target_entity: str, account_id: str | None = None) -> dict:
        account = self._resolve_account(ctx, account_id)
        domain = target_entity.split(".")[0]
        async with httpx.AsyncClient(timeout=4.0) as client:
            await client.post(
                f"{account['url']}/api/services/{domain}/turn_off",
                headers={"Authorization": f"Bearer {account['token']}", "Content-Type": "application/json"},
                json={"entity_id": target_entity},
            )
        return {
            "ok": True, "skill": "home_assistant", "action": "turn_off",
            "data": {"entity_id": target_entity, "account": account["id"], "state": "off"},
            "meta": {"source": "home_assistant", "cache_hit": False, "execution_mode": "fast"},
            "presentation": {"type": "entity_state_change", "max_voice_items": 1, "max_screen_items": 1, "speak_priority_fields": ["entity_id", "state"]},
            "errors": [],
        }

    async def get_state(self, ctx: dict, target_entity: str, account_id: str | None = None) -> dict:
        account = self._resolve_account(ctx, account_id)
        async with httpx.AsyncClient(timeout=4.0) as client:
            response = await client.get(
                f"{account['url']}/api/states/{target_entity}",
                headers={"Authorization": f"Bearer {account['token']}", "Content-Type": "application/json"},
            )
            payload = response.json()
        return {
            "ok": True, "skill": "home_assistant", "action": "get_state",
            "data": {"entity_id": target_entity, "state": payload.get("state"), "attributes": payload.get("attributes", {}), "account": account["id"]},
            "meta": {"source": "home_assistant", "cache_hit": False, "execution_mode": "fast"},
            "presentation": {"type": "entity_state", "max_voice_items": 1, "max_screen_items": 1, "speak_priority_fields": ["entity_id", "state"]},
            "errors": [],
        }
EOF

# ---------------------------------------------------------
# 3. MOVIE SHOWTIMES SKILL
# ---------------------------------------------------------
echo "Scaffolding Movie Showtimes skill..."
mkdir -p skills/movie_showtimes

cat << 'EOF' > skills/movie_showtimes/manifest.json
{
  "schema_version": 1,
  "id": "movie_showtimes",
  "title": "Movie Showtimes",
  "domain": "movies",
  "description": "Find movie showtimes by location and date.",
  "version": "1.0.0",
  "load_type": "lazy",
  "account_mode": "none",
  "system": false,
  "enabled_by_default": true,
  "required_context": ["location"],
  "optional_context": ["preferred_theater", "date"],
  "permissions": {
    "default": "all_users"
  },
  "runtime_dependencies": [
    { "package": "httpx", "version": ">=0.27.0" }
  ],
  "skill_dependencies": {
    "required": [],
    "optional": [
      { "id": "web_search", "reason": "Fallback when primary showtimes provider is unavailable" }
    ]
  },
  "actions": {
    "get_showtimes": {
      "title": "Get Showtimes",
      "description": "Return movie showtimes for the given date and location.",
      "enabled": true,
      "required_context": ["location"],
      "optional_context": ["preferred_theater", "date"],
      "timeout_ms": 5000,
      "cache_ttl_sec": 900,
      "phrases": [
        "what movies are playing", "movie showtimes", "what's playing near me"
      ],
      "keywords": ["movie", "movies", "showtimes", "theater", "playing", "tonight", "today"],
      "negative_keywords": ["review", "cast", "actor", "rent", "buy", "stream"],
      "required_entities": [],
      "optional_entities": ["movie_title", "date"]
    }
  }
}
EOF

cat << 'EOF' > skills/movie_showtimes/skill.py
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
EOF

sync_repo "$HOME/Projects/loki-doki-skills"

sync_repo "$HOME/Projects/loki-doki-characters"

echo "✅ All done! Repositories have been fully updated and pushed."