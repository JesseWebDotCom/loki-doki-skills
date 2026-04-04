import pytest
import respx
from unittest.mock import MagicMock, AsyncMock

from sources.skills.home_assistant.skill import HomeAssistantSkill

@pytest.fixture
def skill():
    s = HomeAssistantSkill()
    s.manifest = {
        "id": "home_assistant",
        "actions": {
            "turn_on": {},
            "turn_off": {},
            "get_state": {}
        }
    }
    return s

@pytest.fixture
def ctx():
    # Mock context with an HA account
    mock_accounts = MagicMock()
    mock_accounts.resolve.return_value = {
        "id": "ha_main",
        "url": "http://192.168.1.100:8123",
        "token": "secret_token"
    }
    return {
        "accounts": mock_accounts,
        "user": {"id": "test_user"}
    }

@pytest.mark.asyncio
@respx.mock
async def test_turn_on_success(skill, ctx):
    # Mock HA service call
    respx.post("http://192.168.1.100:8123/api/services/light/turn_on").respond(status_code=200)
    
    emit_progress = AsyncMock()
    result = await skill.execute("turn_on", ctx, emit_progress, target_entity="light.living_room")
    
    assert result["ok"] is True
    assert result["data"]["entity_id"] == "light.living_room"
    assert result["data"]["state"] == "on"
    emit_progress.assert_called_with("Turning on light.living_room...")

@pytest.mark.asyncio
@respx.mock
async def test_get_state_success(skill, ctx):
    # Mock HA state retrieval
    respx.get("http://192.168.1.100:8123/api/states/sensor.temperature").respond(
        json={
            "state": "22.5",
            "attributes": {"unit_of_measurement": "°C", "friendly_name": "Living Room Temp"}
        }
    )
    
    emit_progress = AsyncMock()
    result = await skill.execute("get_state", ctx, emit_progress, target_entity="sensor.temperature")
    
    assert result["ok"] is True
    assert result["data"]["state"] == "22.5"
    assert "Living Room Temp" in result["data"]["attributes"]["friendly_name"]
    emit_progress.assert_called_with("Checking status of sensor.temperature...")

@pytest.mark.asyncio
async def test_no_account_error(skill):
    # Context with no resolvable account
    mock_accounts = MagicMock()
    mock_accounts.resolve.return_value = None
    ctx = {"accounts": mock_accounts}
    
    emit_progress = AsyncMock()
    with pytest.raises(ValueError, match="No Home Assistant account available"):
        await skill.execute("turn_on", ctx, emit_progress, target_entity="light.any")
