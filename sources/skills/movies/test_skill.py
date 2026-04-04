import pytest
import httpx
import respx
from unittest.mock import MagicMock, patch

from sources.skills.movies.skill import MoviesSkill

@pytest.fixture
def skill():
    s = MoviesSkill()
    s.manifest = {
        "id": "movies",
        "actions": {
            "get_showtimes": {},
            "get_movie_details": {}
        }
    }
    return s

@pytest.mark.asyncio
@respx.mock
async def test_get_movie_details_wikipedia_and_search(skill):
    # Mock Wikipedia search
    respx.get("https://en.wikipedia.org/w/api.php").respond(
        json={
            "query": {
                "search": [{"title": "Dune (2021 film)"}]
            }
        }
    )
    # Mock Wikipedia summary
    respx.get("https://en.wikipedia.org/api/rest_v1/page/summary/Dune_(2021_film)").respond(
        json={
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Dune_(2021_film)"}}
        }
    )
    # Mock Wikipedia page content (infobox)
    respx.get("https://en.wikipedia.org/wiki/Dune_(2021_film)").respond(
        text="""
        <table class="infobox">
            <tr><th class="infobox-label">Running time</th><td class="infobox-data">155 minutes</td></tr>
            <tr><th class="infobox-label">Rating</th><td class="infobox-data">PG-13</td></tr>
        </table>
        """
    )
    
    # Mock search results for post-credits
    mock_search = [
        {"title": "Dune post credit scene", "snippet": "There is no post-credit scene in Dune Part One."}
    ]
    
    with patch("sources.skills.movies.skill.parsed_search_results", return_value=mock_search):
        ctx = {"request_text": "runtime for Dune"}
        emit_progress = MagicMock()
        
        result = await skill.execute("get_movie_details", ctx, emit_progress)
        
        assert result["ok"] is True
        assert "155 minutes" in result["data"]["runtime"]
        assert "PG-13" in result["data"]["rating"]
        assert "no post-credit scene" in result["data"]["post_credit"]
        emit_progress.assert_called_with("Fetching movie details...")

@pytest.mark.asyncio
async def test_get_showtimes_with_search(skill):
    # Mock search results for showtimes
    mock_search = [
        {
            "title": "AMC Milford 12 - Dune showtimes",
            "snippet": "1:10 PM, 4:30 PM, 7:45 PM",
            "url": "https://example.com/showtimes"
        }
    ]
    
    with patch("sources.skills.movies.skill.parsed_search_results", return_value=mock_search):
        ctx = {"request_text": "Dune showtimes in Milford", "location": "Milford, CT"}
        emit_progress = MagicMock()
        
        result = await skill.execute("get_showtimes", ctx, emit_progress)
        
        assert result["ok"] is True
        assert result["data"]["movie_title"] == "Dune"
        assert len(result["data"]["results"]) > 0
        assert "1:10 PM" in result["data"]["summary"]
        emit_progress.assert_called_with("Searching for local showtimes...")

@pytest.mark.asyncio
async def test_invalid_action(skill):
    ctx = {"request_text": "hello"}
    emit_progress = MagicMock()
    with pytest.raises(ValueError, match="Unknown action"):
        await skill.execute("invalid_action", ctx, emit_progress)
