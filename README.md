# LokiDoki Skills Repository

This repository contains community and core skills for **LokiDoki**, the private, local-first AI platform for your home.

LokiDoki skills are lightweight, sandboxed Python packages that fetch data or execute actions. They return structured JSON facts, which LokiDoki's core Response Generator then translates into natural language for the user.

---

## Creating a Skill

Building a skill requires creating a directory inside `/skills/` containing two files: a `manifest.json` and a `skill.py`.

### 1. Directory Structure
```text
skills/
  my_new_skill/
    manifest.json
    skill.py
    assets/
      icon.png
```

### 2. The Fast / Detailed Execution Pattern (Crucial)
Because LokiDoki is designed to run efficiently on Raspberry Pi hardware, we strictly enforce a **Two-Mode Pattern** to minimize latency. When querying external APIs or scraping web pages, you should split your capability into two actions:

1. **Fast Mode (`quick_lookup`)**: Uses lightweight APIs to return a simple summary almost instantly (< 500ms).
2. **Detailed Mode (`detailed_lookup`)**: Scrapes deeper HTML, fetches relational data, or calls slower APIs. Takes slightly longer but returns rich facts.

By splitting these up, LokiDoki's deterministic router can instantly answer simple questions ("Who is X?", "What's the weather?") via the fast path, while reserving the heavy, slow path for deep-dive questions ("Give me all the details on X", "What is the 7-day forecast?").

### 3. Writing the `manifest.json`

The manifest tells LokiDoki's router exactly when to trigger your skill using deterministic `phrases` and `keywords`.

```json
{
  "schema_version": 1,
  "id": "example_wikipedia",
  "title": "Wikipedia",
  "domain": "knowledge",
  "description": "Fetch summaries and infobox details from Wikipedia.",
  "version": "1.0.0",
  "load_type": "lazy",
  "account_mode": "none",
  "system": false,
  "enabled_by_default": true,
  "required_context": [],
  "optional_context": [],
  "permissions": {
    "default": "all_users"
  },
  "runtime_dependencies": [
    { "package": "httpx", "version": ">=0.27.0" },
    { "package": "beautifulsoup4", "version": ">=4.12.0" }
  ],
  "skill_dependencies": {
    "required": [],
    "optional": [
      { "id": "web_search", "reason": "Fallback when exact match fails" }
    ]
  },
  "actions": {
    "quick_lookup": {
      "title": "Quick Lookup",
      "description": "Get a fast summary of an article.",
      "enabled": true,
      "required_context": [],
      "optional_context": [],
      "timeout_ms": 5000,
      "cache_ttl_sec": 3600,
      "phrases": ["who is", "what is"],
      "keywords": ["who", "what"],
      "negative_keywords": ["details", "timeline", "deep dive"],
      "required_entities": ["query"],
      "optional_entities": []
    },
    "detailed_lookup": {
      "title": "Detailed Lookup",
      "description": "Get a summary plus detailed facts.",
      "enabled": true,
      "required_context": [],
      "optional_context": [],
      "timeout_ms": 8000,
      "cache_ttl_sec": 3600,
      "phrases": ["details about", "deep dive on"],
      "keywords": ["details", "timeline"],
      "negative_keywords": [],
      "required_entities": ["query"],
      "optional_entities": []
    }
  }
}
```

### 4. Writing the `skill.py`

Your Python implementation must subclass `BaseSkill` and implement the `execute` method. You must return a strict dictionary envelope, ensuring that you declare `"execution_mode": "fast" | "detailed"` in the `meta` block.

```python
import httpx
from core.base_skill import BaseSkill

class WikipediaSkill(BaseSkill):
    async def execute(self, action: str, ctx: dict, **kwargs) -> dict:
        self.validate_action(action)
        
        query = kwargs.get("query", "").strip()
        if not query:
            return {"ok": False, "errors": ["No query provided."]}
            
        if action == "quick_lookup":
            return await self.lookup(query, is_detailed=False, ctx=ctx)
        if action == "detailed_lookup":
            return await self.lookup(query, is_detailed=True, ctx=ctx)
            
        raise ValueError(f"Unhandled action: {action}")

    async def lookup(self, query: str, is_detailed: bool, ctx: dict) -> dict:
        # 1. Always do the fast API fetch
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://api.example.com/summary/{query}")
            if resp.status_code != 200:
                # Seamless fallback to DuckDuckGo if built-in web_search is installed
                return await self._fallback_web_search(ctx, query)
                
            data = resp.json()
            clean_data = {"title": data.get("title"), "extract": data.get("extract")}
            
            # 2. Only do the heavy scrape if the router requested detailed mode
            if is_detailed:
                clean_data["infobox"] = await self._heavy_html_scrape(data.get("url"))

            # 3. Return the standard LokiDoki result envelope
            return {
                "ok": True,
                "skill": "wikipedia",
                "action": "detailed_lookup" if is_detailed else "quick_lookup",
                "data": clean_data,
                "meta": {
                    "source": "wikipedia",
                    "cache_hit": False,
                    "execution_mode": "detailed" if is_detailed else "fast"
                },
                "presentation": {
                    "type": "wikipedia_summary",
                    "max_voice_items": 1,
                    "max_screen_items": 1,
                    "speak_priority_fields": ["title", "extract"]
                },
                "errors": []
            }

    async def _fallback_web_search(self, ctx: dict, query: str) -> dict:
        """Ask the core web_search skill to handle this instead."""
        skill_manager = ctx.get("skill_manager")
        if not skill_manager:
            return {"ok": False, "errors": ["Not found and no fallback available."]}
            
        try:
            return await skill_manager.execute(
                skill_id="web_search",
                action="search",
                ctx=ctx,
                query=query,
                num_results=3,
            )
        except Exception:
            return {"ok": False, "errors": ["Fallback failed."]}
```

### 5. Testing Your Skill
To test your skill locally:
1. Copy your skill directory into your LokiDoki installation's `data/skills/installed/` folder.
2. Restart your LokiDoki instance.
3. Navigate to **Settings > Administration > Prompt Lab**.
4. Run test queries and check the **Execution mode** indicator in the Routing Trace panel to verify your routing separates simple and detailed queries correctly.