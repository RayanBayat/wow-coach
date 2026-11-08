# Changelog

All notable changes to this project are written here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **The Coach panel**: a window inside the game with your coach's next steps and answers,
  and a box to ask your coach a question ([guide](docs/coach-panel.md)).
  - Open it with `/coach panel`, from the minimap's addon list, or with a key binding
    (Options, then Keybindings, then CoachLink).
  - `/coach ask <question>` asks without opening it.
  - It hides in combat.
  - Restart the game once after updating: the addon has new files.
- Two new tools for your coach (MCP): `questions_from_game` reads the questions you asked in
  the panel, and `send_advice_to_game` shows the coach's answer and next steps in the panel.
- `wow-coach setup` creates `Interface/AddOns/CoachLink_Advice`. That is a small data-only
  addon where wow-coach writes the coach's answers safely; addon managers never overwrite it.
- `wow-coach watch` says how many questions are waiting when you asked one
  (`reason: ask; 1 open question`).

## [0.7.0] - 2026-11-08

Fixes and additions from the first evenings of real play: logging out no longer empties your
save, deaths and new items say what happened, play time keeps itself up to date, and the
report flags gear you can't use or should wear.

### Added

- Deaths in the history say who was attacking you: each enemy's name, level and whether it is
  an elite, the killing blow when the game's death recap has one, and how soon after coming
  back to life you died again. (The game no longer lets addons read the combat log, so the
  addon notes the enemies that have you as their target while you fight.)
  ([#4](https://github.com/RayanBayat/wow-coach/issues/4))

- The history records where new items came from: green or better loot and gear you loot, quest
  rewards (with the choice you made and the other choices), gear and bags you buy (with the
  price), and items you take from the mail. The history now keeps the newest 500 events
  instead of 300 ([#5](https://github.com/RayanBayat/wow-coach/issues/5)).

- A **Gear hints** section in the status report, right after the bags. It lists bag items your
  character can't use (armor without the proficiency, weapons without the weapon skill), and
  possible upgrades: something usable for an empty slot, or with a higher item level than what
  you wear, or replacing a gray item ([#6](https://github.com/RayanBayat/wow-coach/issues/6)).
- Quest IDs in the status report and in `/coach copy` ("Fields of Grief (quest 365)"), and a
  new lookup, `find_quest` (MCP) and `wow-coach wiki --quest 365`. It finds a quest's Warcraft
  Wiki page by its ID, so the coach reads the Classic page Forever uses, not a Retail page with
  the same title ([#8](https://github.com/RayanBayat/wow-coach/issues/8)).

### Changed

- Play time stays up to date without typing `/played`: the addon asks the game for it after
  you log in, after a `/reload` and after a level-up, and keeps the answer out of your chat
  window ([#9](https://github.com/RayanBayat/wow-coach/issues/9)).

- `wow-coach watch` prints its start line to the error output instead of the normal output, and
  without the game folder. Under Claude Code's Monitor, only real saves now reach the coach, so
  restarting the watcher every 30 minutes no longer sends the coach a message
  ([#10](https://github.com/RayanBayat/wow-coach/issues/10)).

### Fixed

- Wiki pages no longer lose text from templates the reader doesn't know. Game names such as
  `{{g|forever}}` become "Forever", content the wiki fills in from other pages (for example the
  scroll lists on "Comprehend Scroll") is asked from the wiki in one extra request, and any
  other unknown template leaves its text or its name in brackets instead of nothing
  ([#7](https://github.com/RayanBayat/wow-coach/issues/7)).
- Logging out or quitting no longer replaces your last good snapshot with an almost empty one
  (wrong level, no gold, no bags or gear). On a real logout the game unloads the character
  before the addon's last chance to save, so the addon now also reads your character when you
  start to log out or quit, and keeps the last full snapshot if it has nothing better. The
  status report warns about empty saves made by older versions, and `progress_summary`
  ignores them, so it no longer reports things like "level 10 to 9"
  ([#2](https://github.com/RayanBayat/wow-coach/issues/2)).
- A level-up in the history now stores the level reached. Before, it stored the level before
  the level-up ([#3](https://github.com/RayanBayat/wow-coach/issues/3)).

## [0.6.0] - 2026-11-08

The addon now saves everything about your character, and `/coach copy` gives only your data.

### Added

- The snapshot holds every item in your bags (count, quality, type, vendor price, stats and
  needed level for things you can wear, soulbound and "vendors won't buy it"), plus the reagent
  bag and keyring when you have them.
- The bank, mailbox and each profession's recipe list (with the recipe colors) are read when
  you open that window and remembered with the time you saw them, so they are in every
  snapshot after that. Play time is remembered from `/played`.
- Stats (health, mana, attributes, armor, resistances, spell damage, crit, dodge, attack power,
  mana regeneration), buffs and debuffs with the time left, faction, guild, resting, and the
  dungeon you are in.
- Quests: the quest-log zone, the short goal text that says who to hand the quest in to,
  group quest size, failed quests, and how many quests you have ever completed.
- Gear: stats and durability. The full spellbook by tab with ranks and passives, what sits on
  every action bar, reputations, currencies, Forever's Legacy system (reward track level,
  points to spend, perks and your class challenges), your group, your pet, achievement points
  and the mounts you own.
- The status report (`character_status`, `wow-coach status`) shows all of it, including the
  total vendor value of your gray items and skills such as languages.
- `/coach help` says how the bank, mail, recipes and play time get included.

### Changed

- `/coach copy` no longer starts with instructions for the AI ("Please be my coach..."). The
  text is a plain title and your character's data, so you decide what to ask.
- The text is longer now; the copy window has no length limit.

All new fields are additive: `formatVersion` stays 1 and older saves still work.

## [0.5.0] - 2026-11-07

Every character now has its own memory, and each coaching session starts by choosing one.

### Added

- A progress log per character. The addon adds a small point (level, XP, gold, place, quests
  ready to turn in) every time it saves, at most 500 points, skipping an identical point
  within 60 seconds. It is optional data: `formatVersion` stays 1, and older saves still work.
- `progress_summary` (MCP tool) and `wow-coach progress [--character NAME] [--days N]`: when
  and where you last played, play sessions, levels, XP, gold, XP per hour, quests turned in,
  deaths, and what changed since the previous session.
- `wow-coach characters`: your characters, most recently played first, with level, class, zone,
  when you last played and your goal. The MCP tool `list_characters` shows the same, including
  the first goal from each character's journal.
- Character journals: one file per character in the data folder (`characters/<Name-Realm>.md`).
- `save_player_notes` (MCP tool): saves the player notes shared by all characters.
- The Claude Code agent now asks which character to continue (clickable options, or a numbered
  list when the session cannot show them), then greets you with where you were and what
  changed. It loads the skill itself if it was not preloaded.
- `wow-coach check` lists the character journals that exist.
- The skill explains player notes versus journals and choosing a character, with separate
  templates for both.

### Changed

- **`save_coach_notes` now saves the journal of one character**, not the shared notebook
  (new optional `character` argument; default is the most recently saved character).
  `read_coach_notes` returns the player notes and that character's journal, with headings.
  Your existing notebook (`coach-notes.md`) is kept as the player notes; nothing is moved. Use
  `save_player_notes` to change it.
- `wow-coach setup` creates the player notes file only; the coach creates a journal when it
  first coaches a character.
- The skill uses `--quiet` for live mode, like the agent.
- If the addon cannot read the quest log, `quests` is now missing from the snapshot instead of
  an empty or partial list.

### Notes

- Adding the progress log needs only `/reload` in game; no new addon file was added.

## [0.4.0] - 2026-11-07

### Added

- A ready-made Claude Code agent. After `wow-coach setup --claude-code`, `claude --agent
  wow-coach` starts a session that checks your setup, starts live mode when the game runs,
  reads your character and notebook, and greets you with your progress. It brings its own
  wow-coach connection. Guide: `docs/claude-code-agent.md`.
- `wow-coach setup`: finds your game folder, installs or updates the CoachLink addon from the
  release zip, creates your notebook, and (with `--claude-code`) installs the agent and skill.
  Plain-language steps with OK or PROBLEM for each; safe to run again. Flags: `--wow-dir`,
  `--yes`, `--claude-code`, `--skip-addon`.
- Saved settings: setup remembers the game folder in `config.json` next to the notebook
  (override the file with `WOW_COACH_CONFIG_FILE`). The game folder is now picked from
  `--wow-dir`, then `WOW_COACH_WOW_DIR`, then the saved setting, then auto-detect.
- Goals and plans: the skill has a new "Goals and plans" section (make the goal measurable,
  research, write a dated plan, today's next steps, track progress), and the notebook
  template has a "## Goals" section.
- A test that fails when the agent file, the addon or the docs pin a version other than the
  project's, so a release cannot ship a stale pin.

### Changed

- The skill moved from `skills/wow-coach/` to `src/wow_coach/assets/skills/wow-coach/` so that
  installs of the package carry it. Download it from the new path if you used the old link.

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
