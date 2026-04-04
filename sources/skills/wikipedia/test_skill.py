import pytest
import httpx
import respx
from unittest.mock import MagicMock

from sources.skills.wikipedia.skill import WikipediaSkill

@pytest.fixture
def skill():
    s = WikipediaSkill()
    s.manifest = {
        "id": "wikipedia",
        "actions": {
            "lookup_article": {}
        }
    }
    return s

@pytest.mark.asyncio
@respx.mock
async def test_lookup_article_success(skill):
    # Mock Wikipedia Summary API
    respx.get("https://en.wikipedia.org/api/rest_v1/page/summary/Dune").respond(
        json={
            "type": "standard",
            "title": "Dune (novel)",
            "displaytitle": "<i>Dune</i> (novel)",
            "description": "1965 science fiction novel by Frank Herbert",
            "extract": "Dune is a 1965 science-fiction novel by American author Frank Herbert...",
            "content_urls": {
                "desktop": {"page": "https://en.wikipedia.org/wiki/Dune_(novel)"}
            }
        }
    )
    
    # Mock Wikipedia Desktop Page for Infobox scraping
    respx.get("https://en.wikipedia.org/wiki/Dune_(novel)").respond(
        text="""
        <table class="infobox">
            <tr><th class="infobox-label">Author</th><td class="infobox-data">Frank Herbert</td></tr>
            <tr><th class="infobox-label">Genre</th><td class="infobox-data">Science fiction</td></tr>
        </table>
        """
    )
    
    ctx = {"request_text": "look up Dune"}
    emit_progress = MagicMock()
    
    result = await skill.execute("lookup_article", ctx, emit_progress)
    
    assert result["ok"] is True
    assert result["data"]["title"] == "Dune (novel)"
    assert result["data"]["infobox"]["Author"] == "Frank Herbert"
    assert "Science fiction" in result["data"]["infobox"]["Genre"]
    emit_progress.assert_called_with("Searching Wikipedia for 'Dune'...")

@pytest.mark.asyncio
@respx.mock
async def test_lookup_article_disambiguation_retry(skill):
    # Mock disambiguation first
    respx.get("https://en.wikipedia.org/api/rest_v1/page/summary/Mercury").respond(
        json={"type": "disambiguation"}
    )
    
    # Mock fallback search
    respx.get("https://en.wikipedia.org/w/api.php").respond(
        json={
            "query": {
                "search": [{"title": "Mercury (element)"}]
            }
        }
    )
    
    # Mock final summary
    respx.get("https://en.wikipedia.org/api/rest_v1/page/summary/Mercury_(element)").respond(
        json={
            "type": "standard",
            "title": "Mercury (element)",
            "extract": "Mercury is a chemical element...",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Mercury_(element)"}}
        }
    )
    
    ctx = {"request_text": "Mercury"}
    emit_progress = MagicMock()
    
    result = await skill.execute("lookup_article", ctx, emit_progress)
    
    assert result["ok"] is True
    assert result["data"]["title"] == "Mercury (element)"

@pytest.mark.asyncio
async def test_empty_query(skill):
    ctx = {"request_text": ""}
    emit_progress = MagicMock()
    result = await skill.execute("lookup_article", ctx, emit_progress)
    assert result["ok"] is False
    assert "Tell me what you want to look up" in result["errors"][0]
