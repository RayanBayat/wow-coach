# AGENTS.md: wow-coach

wow-coach lets an AI see a World of Warcraft: Forever character. The CoachLink addon saves a
snapshot, a Python program (`wow-coach`) reads it and serves it to AI apps, and a generic Agent
Skill teaches an AI how to coach. This file is for contributors, human or AI.

Read `docs/design.md` before changing anything: it has the data contract and the verified game
facts. Users' docs start at `README.md`.

## Layout

| Path | What |
|---|---|
| `addon/CoachLink/` | The WoW addon (Lua 5.1): `CoachLink.toc`, `CoachLink.lua` (snapshot, history, questions), `CoachLinkText.lua` (`/coach copy` text), `CoachLinkPanel.lua` and `Bindings.xml` (the Coach panel) |
| `addon/tests/run_addon_test.lua`, `run_panel_test.lua` | Run the addon and the Coach panel against a fake WoW API |
| `src/wow_coach/` | Python package: Lua-table parser, saved-file finder and loader, report (`report*.py`, incl. `report_gear_hints`), `cli`, `watch`, `notes`, saved settings (`config`, `datafolder`), `setup` (the `wow-coach setup` command), packaged-file reader (`assets`), MCP `server`; the Coach panel's questions and answers: `advice/` (contract, safe Lua writer, reader, tools); wow-coach's own AI connection: `ai/` (contract, `FakeProvider`); game lookups: `web` (polite fetcher), `wiki` (search, read and find-quest tools), `wikitext` (wiki markup to plain text) |
| `tests/` | pytest. `test_addon_contract.py` runs the Lua test and reads its output with the Python code. `tests/fixtures/wiki/` holds real wiki responses; tests never use the network |
| `src/wow_coach/assets/` | Claude files shipped inside the package so `wow-coach setup` can copy them: `skills/wow-coach/SKILL.md` (the Agent Skill; folder name must equal `name`) and `agents/wow-coach.md` (the Claude Code agent) |
| `docs/` | User guides, `design.md` (how it works), `troubleshooting.md`, `glossary.md` |
| `.github/workflows/` | `ci.yml` (tests) and `release.yml` (builds `CoachLink-<version>.zip` on a `v*` tag) |
| `CHANGELOG.md` | Keep a Changelog format |

## Commands

```
uv sync --frozen
uv run pytest -q && uv run mypy src && uv run ruff check . && uv run ruff format --check .
luajit addon/tests/run_addon_test.lua
```

## Rules

- **Beginner-readable everything.** Code, comments and docs should make sense to a
  first-year CS student: short functions, clear names, comments that say why. Docs are
  written for people who have never coded: short sentences, each technical word explained,
  numbered steps, one-line commands in their own block.
- **The data contract is shared.** If you change what the addon saves, update `docs/design.md`,
  the addon, the Python reader, the fake API in the Lua test, and the tests, all in the same
  commit. Bump `FORMAT_VERSION` / `SUPPORTED_FORMAT_VERSION` for breaking changes.
- **Verify game APIs against Blizzard's own Forever UI code**
  (https://github.com/Gethe/wow-ui-source, branch `forever`), not memory or retail docs. Wrap
  every new snapshot section in `readSection` (a protected call).
- **Addon API only.** Never memory reading, injection or automation (ban risk).
- **Verify app-specific docs.** Config formats for third-party apps change; check the vendor's
  official page and link it. If you can't verify something, say so in the doc.
- **Python:** uv, exact version pins, `mypy --strict`, ruff, test first (TDD).
- **Commits:** Conventional Commits, one logical change per commit.
- **Update `CHANGELOG.md`** with every user-visible change, under an `[Unreleased]` heading
  until released. Releasing = bump the version in `pyproject.toml`, `CoachLink.toc`, the `@vX.Y.Z` pin
  in `src/wow_coach/assets/agents/wow-coach.md` and every `@vX.Y.Z` in the docs and skill
  (`tests/test_release_pins.py` fails if one is missed), run `uv lock`, move the changelog
  section under the version, tag `vX.Y.Z`; the release workflow does the rest. The setup
  command downloads `CoachLink-<version>.zip` from that tag's release, so the release must
  exist before users run setup.
