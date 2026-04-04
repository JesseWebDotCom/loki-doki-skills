import pytest
import respx
from unittest.mock import MagicMock, AsyncMock

from sources.skills.weather.skill import WeatherSkill

@pytest.fixture
def skill():
    s = WeatherSkill()
    s.manifest = {
        "id": "weather",
        "actions": {
            "get_current": {},
            "get_forecast": {}
        }
    }
    return s

@pytest.fixture
def ctx():
    # Context with a fixed location as a list (standard Geo provider output)
    return {"location": [34.05, -118.24], "user": {"id": "test_user"}}

@pytest.mark.asyncio
@respx.mock
async def test_get_current_success(skill, ctx):
    # Mock Open-Meteo current
    respx.get("https://api.open-meteo.com/v1/forecast").respond(
        json={
            "current_weather": {
                "temperature": 72.5,
                "windspeed": 10.2,
                "weathercode": 0
            }
        }
    )
    
    emit_progress = AsyncMock()
    result = await skill.execute("get_current", ctx, emit_progress)
    
    assert result["ok"] is True
    assert result["data"]["temperature"] == 72.5
    assert result["data"]["weathercode"] == 0
    emit_progress.assert_called_with("Checking current weather...")

@pytest.mark.asyncio
@respx.mock
async def test_get_forecast_success(skill, ctx):
    # Mock Open-Meteo forecast
    respx.get("https://api.open-meteo.com/v1/forecast").respond(
        json={
            "daily": {
                "time": ["2026-04-03"],
                "temperature_2m_max": [75.0],
                "temperature_2m_min": [60.0],
                "precipitation_probability_max": [0]
            }
        }
    )
    
    emit_progress = AsyncMock()
    result = await skill.execute("get_forecast", ctx, emit_progress, date="tomorrow")
    
    assert result["ok"] is True
    assert result["data"]["daily"]["temperature_2m_max"][0] == 75.0
    emit_progress.assert_called_with("Fetching weather forecast...")

@pytest.mark.asyncio
async def test_missing_location_error(skill):
    # Context with no location
    ctx = {}
    emit_progress = AsyncMock()
    with pytest.raises(ValueError, match="Weather skill requires location context"):
        await skill.execute("get_current", ctx, emit_progress)
