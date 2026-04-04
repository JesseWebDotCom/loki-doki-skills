import pytest
import respx
from unittest.mock import MagicMock

from sources.skills.tv_shows.skill import TvShowsSkill

@pytest.fixture
def skill():
    s = TvShowsSkill()
    s.manifest = {
        "id": "tv_shows",
        "actions": {
            "get_show_details": {},
            "get_show_cast": {},
            "get_person_details": {}
        }
    }
    return s

@pytest.mark.asyncio
@respx.mock
async def test_get_show_details_success(skill):
    # Mock TVMaze singlesearch
    respx.get("https://api.tvmaze.com/singlesearch/shows?q=Sopranos&embed=cast").respond(
        json={
            "name": "The Sopranos",
            "premiered": "1999-01-10",
            "status": "Ended",
            "genres": ["Drama", "Crime"],
            "network": {"name": "HBO"},
            "summary": "<p>Tony Soprano is a family man...</p>",
            "officialSite": "http://www.hbo.com/the-sopranos"
        }
    )
    
    ctx = {"request_text": "tell me about the show Sopranos"}
    emit_progress = MagicMock()
    
    result = await skill.execute("get_show_details", ctx, emit_progress)
    
    assert result["ok"] is True
    assert result["data"]["show_name"] == "The Sopranos"
    assert "HBO" in result["data"]["network"]
    assert "Tony Soprano" in result["data"]["summary"]

@pytest.mark.asyncio
@respx.mock
async def test_get_show_cast_success(skill):
    # Mock TVMaze singlesearch with cast
    respx.get("https://api.tvmaze.com/singlesearch/shows?q=Breaking%20Bad&embed=cast").respond(
        json={
            "name": "Breaking Bad",
            "status": "Ended",
            "_embedded": {
                "cast": [
                    {
                        "person": {"name": "Bryan Cranston"},
                        "character": {"name": "Walter White"}
                    },
                    {
                        "person": {"name": "Aaron Paul"},
                        "character": {"name": "Jesse Pinkman"}
                    }
                ]
            }
        }
    )
    
    ctx = {"request_text": "cast of Breaking Bad"}
    emit_progress = MagicMock()
    
    result = await skill.execute("get_show_cast", ctx, emit_progress)
    
    assert result["ok"] is True
    assert result["data"]["show_name"] == "Breaking Bad"
    assert any(c["person_name"] == "Bryan Cranston" for c in result["data"]["cast"])

@pytest.mark.asyncio
@respx.mock
async def test_get_person_details_success(skill):
    # Mock TVMaze person search
    respx.get("https://api.tvmaze.com/search/people?q=Pedro%20Pascal").respond(
        json=[
            {
                "person": {
                    "id": 123,
                    "name": "Pedro Pascal",
                    "birthday": "1975-04-02",
                    "country": {"name": "Chile"}
                }
            }
        ]
    )
    # Mock person details with cast credits
    respx.get("https://api.tvmaze.com/people/123?embed=castcredits").respond(
        json={
            "name": "Pedro Pascal",
            "_embedded": {
                "castcredits": [
                    {"_links": {"show": {"name": "The Last of Us", "href": "..."}}},
                    {"_links": {"show": {"name": "The Mandalorian", "href": "..."}}}
                ]
            }
        }
    )
    
    ctx = {"request_text": "tv actor Pedro Pascal"}
    emit_progress = MagicMock()
    
    result = await skill.execute("get_person_details", ctx, emit_progress)
    
    assert result["ok"] is True
    assert result["data"]["person_name"] == "Pedro Pascal"
    assert "The Last of Us" in result["data"]["shows"]

@pytest.mark.asyncio
@respx.mock
async def test_show_not_found(skill):
    # Mock TVMaze singlesearch returning 404 or empty
    respx.get("https://api.tvmaze.com/singlesearch/shows?q=NonExistent&embed=cast").respond(status_code=404)
    
    ctx = {"request_text": "show NonExistent"}
    emit_progress = MagicMock()
    
    result = await skill.execute("get_show_details", ctx, emit_progress)
    assert result["ok"] is False
    assert "couldn't find a TV show" in result["errors"][0]
