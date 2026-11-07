# Changelog

All notable changes to this project are written here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [0.3.0] - 2026-11-07

### Added

- Game lookups for the coach, so it no longer needs slow web searches for basic facts:
  - MCP tools `search_wiki` and `read_wiki_page` (Warcraft Wiki). They answer where an NPC
    stands, what a vendor sells and who gives a quest, mark Forever-only, Classic-only and
    Retail-only text, and always end with the page link and the license (CC BY-SA 4.0).
  - `wow-coach wiki QUERY` searches the wiki, and `wow-coach wiki --page TITLE [--section NAME]`
    reads a page.
  - Answers are cached for an hour, requests are limited to about two per second, and a wiki
    that does not answer produces a plain message instead of an error.
- The coach skill now says to look things up with these tools first, and to cite the link.

### Notes

- Wowhead is not used: its terms of use forbid automated access. The reasons are in
  `docs/design.md`.

## [0.2.0] - 2026-11-07

### Added

- `/coach copy` (alias `/coach export`) opens a window with your character as text, already
  selected, so you can paste it into any AI chat.
- A `wow-coach` command with four parts: `status` (prints your character), `watch` (prints a
  line each time CoachLink saves), `check` (tests the setup) and `mcp` (starts the MCP server).
- Coach notes tools for MCP apps: `read_coach_notes` and `save_coach_notes`, so the coach
  remembers your choices between sessions.
- The game folder is found automatically on Windows, macOS and Linux (Wine).
- A generic Agent Skill (`skills/wow-coach/SKILL.md`) that works for any player and any agent,
  including a live mode that answers each `/coach` on its own.
- Guides for installing the addon and for connecting any AI, plus a "How it works" page.
- Continuous integration (Python tests on Windows, macOS and Linux; addon tests) and a
  release workflow that publishes `CoachLink-<version>.zip`.
- Professions now carry a `category` (the header on the Skills tab), so weapon skills and
  languages are shown apart from real professions.

### Changed

- The skill moved from `skill/` to `skills/wow-coach/` so its folder name matches its name,
  as the Agent Skills specification asks.

### Fixed

- Skill lines are saved once each; before, some professions appeared twice.

## [0.1.0] - 2026-11-06

First version.

### Added

- The CoachLink addon: saves a snapshot of your character at logout, on `/reload` and on
  `/coach`, plus a history of logins, level-ups, quest turn-ins and deaths.
- An MCP server with three read-only tools: `list_characters`, `character_status` and
  `recent_history`.
- A coach skill with teaching style, proactive checks and verified WoW Forever facts.
