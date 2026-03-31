# Building LokiDoki Skills

LokiDoki skills are lightweight, sandboxed Python packages that fetch data or execute actions. Because LokiDoki is designed to run efficiently on Raspberry Pi hardware, skills must follow specific architectural patterns to minimize latency.

## The Core Philosophy

1. **Skills return facts, not prose.** It is the Response Generator's job to turn the structured facts you return into a natural, conversational response that matches the user's chosen Persona.
2. **Fast Mode vs Detailed Mode.** When making network calls or heavy API requests, split your capability into a "fast" action (returns a quick summary in < 500ms) and a "detailed" action (fetches deep data but takes slightly longer). Let LokiDoki's deterministic router decide which one to use based on the user's prompt.
3. **Use the built-in system skills.** Don't write custom code to search the web or ping the LLM. Use the `skill_manager` passed into your execution context to call `web_search` or other required skills directly.

---

## 1. Directory Structure

Building a skill requires creating a directory inside the `/skills/` folder of this repository containing two primary files:

```text
skills/
  my_new_skill/
    manifest.json
    skill.py
    assets/
      icon.png
```

---

## 2. A "Hello World" Example

Below is a complete, working example of a simple "Hello World" skill. 

It exposes a single action that takes an optional name from the user's query and returns a structured greeting.

### `manifest.json`
The manifest tells LokiDoki's router exactly when to trigger your skill using deterministic `phrases` and `keywords`.

```json
{
  "schema_version": 1,
  "id": "hello_world",
  "title": "Hello World",
  "domain": "utilities",
  "description": "A simple hello world skill to demonstrate the framework.",
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
  "runtime_dependencies": [],
  "skill_dependencies": {
    "required": [],
    "optional": []
  },
  "actions": {
    "greet": {
      "title": "Greet User",
      "description": "Return a friendly hello world greeting.",
      "enabled": true,
      "required_context": [],
      "optional_context": [],
      "timeout_ms": 2000,
      "cache_ttl_sec": 0,
      "phrases": [
        "say hello",
        "run hello world"
      ],
      "keywords": ["hello", "world", "greet"],
      "negative_keywords": ["goodbye", "stop", "cancel"],
      "example_utterances": [
        "run hello world for jesse",
        "say hello"
      ],
      "required_entities": [],
      "optional_entities": ["query"]
    }
  }
}
```

### `skill.py`
Your Python implementation must subclass `BaseSkill` and implement the `execute` method. You must return a strict dictionary envelope conforming to the LokiDoki standard.

```python
from core.base_skill import BaseSkill

class HelloWorldSkill(BaseSkill):
    async def execute(self, action: str, ctx: dict, **kwargs) -> dict:
        self.validate_action(action)
        
        if action == "greet":
            return await self.greet(ctx, **kwargs)
            
        raise ValueError(f"Unhandled action: {action}")

    async def greet(self, ctx: dict, **kwargs) -> dict:
        # Extract the 'query' entity if the user provided one (e.g., "say hello to Jesse")
        query = kwargs.get("query", "").strip()
        
        target_name = query if query else "World"
        greeting_message = f"Hello, {target_name}!"

        # Return the standard LokiDoki result envelope
        return {
            "ok": True,
            "skill": "hello_world",
            "action": "greet",
            "data": {
                "greeting": greeting_message,
                "target": target_name
            },
            "meta": {
                "source": "local",
                "cache_hit": False,
                "execution_mode": "fast"
            },
            "presentation": {
                "type": "standard",
                "max_voice_items": 1,
                "max_screen_items": 1,
                "speak_priority_fields": ["greeting"]
            },
            "errors": []
        }
```

---

## 3. Advanced Example: The Fast / Detailed Pattern

For real-world skills that fetch data (like the Wikipedia or Weather skills), you must implement the **Two-Mode Pattern**.

In your `manifest.json`, define **two actions** (`quick_lookup` and `detailed_lookup`) using negative keywords to keep them separated:

```json
  "actions": {
    "quick_lookup": {
      "phrases": ["who is", "what is"],
      "keywords": ["who", "what"],
      "negative_keywords": ["details", "timeline", "deep dive"],
      "required_entities": ["query"]
    },
    "detailed_lookup": {
      "phrases": ["details about", "deep dive on"],
      "keywords": ["details", "timeline"],
      "required_entities": ["query"]
    }
  }
```

In your `skill.py`, explicitly return your `"execution_mode"` in the meta block so developers can debug latency paths:

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
                skill_manager = ctx.get("skill_manager")
                return await skill_manager.execute(skill_id="web_search", action="search", ctx=ctx, query=query, num_results=3)
                
            data = resp.json()
            clean_data = {"title": data.get("title"), "extract": data.get("extract")}
            
            # 2. Only do the heavy scrape if the router requested detailed mode
            if is_detailed:
                clean_data["infobox"] = await self._heavy_html_scrape(data.get("url"))

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
```

## 4. Testing Your Skill
To test your skill locally without pushing to GitHub:
1. Copy your new skill folder directly into your LokiDoki installation's `data/skills/installed/` directory.
2. Restart your LokiDoki instance.
3. Open your browser, go to **Settings > Administration > Prompt Lab**.
4. Run test queries to verify the Router selects your action and outputs the correct JSON envelope!