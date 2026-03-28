# LokiDoki Skills

Skills for [LokiDoki](https://github.com/JesseWebDotCom/loki-doki), the local AI platform for the home.

This repo is the official installable skills catalog for [LokiDoki](https://github.com/JesseWebDotCom/loki-doki).

## Browse Skills

<table>
<tr><td align="center" valign="top" width="160"><a href="./skills/family_calendar/"><img src="./skills/family_calendar/logo.svg" alt="Family Calendar" width="72" height="72"><br><strong>Family Calendar</strong></a></td><td align="center" valign="top" width="160"><a href="./skills/home_assistant/"><img src="./skills/home_assistant/logo.svg" alt="Home Assistant" width="72" height="72"><br><strong>Home Assistant</strong></a></td><td align="center" valign="top" width="160"><a href="./skills/movies/"><img src="./skills/movies/logo.svg" alt="Movies" width="72" height="72"><br><strong>Movies</strong></a></td><td align="center" valign="top" width="160"><a href="./skills/reminders/"><img src="./skills/reminders/logo.svg" alt="Reminders" width="72" height="72"><br><strong>Reminders</strong></a></td><td align="center" valign="top" width="160"><a href="./skills/shopping_list/"><img src="./skills/shopping_list/logo.svg" alt="Shopping List" width="72" height="72"><br><strong>Shopping List</strong></a></td><td align="center" valign="top" width="160"><a href="./skills/weather/"><img src="./skills/weather/logo.svg" alt="Weather" width="72" height="72"><br><strong>Weather</strong></a></td></tr>
</table>

## How To Create

- Add a new folder under `sources/skills/<your-skill-id>/`
- Include a `manifest.json`, `skill.py`, and a required logo image
- Run `python scripts/build_index.py` to regenerate the catalog, item pages, and `index.json`
- Commit the generated changes and open a pull request

