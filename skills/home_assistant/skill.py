import httpx
from core.base_skill import BaseSkill

class HomeAssistantSkill(BaseSkill):
    manifest = {
        "id": "home_assistant",
        "domain": "smart_home",
        "title": "Home Assistant",
        "actions": {"turn_on": {}, "turn_off": {}, "get_state": {}},
    }

    async def execute(self, action: str, ctx: dict, emit_progress, **kwargs) -> dict:
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
