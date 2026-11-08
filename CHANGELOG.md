# Changelog

All notable changes to this project are written here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **The WoW Coach app** (`wow-coach app`): your coach in its own window instead of a browser
  page ([guide](docs/desktop-app.md)). Install it with the `desktop` extra (Qt for Python).
  - A chat with your coach, and quick buttons: What next?, Check my gear, Spells to train,
    Plan my session, Why did I die?, Make gold, Explain a word.
  - "Game data: 12 min old" shows how fresh the coach's view is. It updates by itself whenever
    the game saves (press your new key in WoW, type `/coach`, or `/reload`), with a short
    "Got your latest game data" note. There is no refresh button, and a question is always
    asked right away.
  - **Keep on top of the game**: a small card above the game with the newest answer.
  - **Settings**, **ChatGPT** and **Privacy** pages. Settings save by themselves.
  - **Setup** page: checks the game folder, installs or updates CoachLink, creates the
    answers folder, and adds WoW Coach to your app menu or starts it when you log in (Linux
    and Windows).
  - It keeps running in the tray when you close the window, and only one copy runs at a time.
  - Light and dark mode follow your computer.
  - If it can't find your game (for example the game disk isn't connected yet), it asks
    you to choose the folder instead of not opening.
  - After you change the game folder, a **Restart WoW Coach** button applies it.
- **A step-by-step install guide for beginners** ([the app guide](docs/desktop-app.md)):
  separate sections for Windows, Linux and macOS, from opening a terminal and installing uv
  to the first chat, with what you should see after each step. The README now points
  beginners to the app first, and the "Pick your way" ways are numbered again (1: the app,
  2: paste, 3: connect an AI app, 4: skill and live mode, 5: the Claude Code agent). New app
  section in [Troubleshooting](docs/troubleshooting.md#the-wow-coach-app) and new words in the
  [glossary](docs/glossary.md).
- **`wow-coach-app`**: starts the app directly, without a console window on Windows. The app
  menu and log-in shortcuts use it.
- **"Save for the coach" key** in the addon (Options → Keybindings → CoachLink): one key does
  what `/coach` does.
- **Overlay mode: the coach on top of your game.** A key (**Ctrl+Shift+Space** at first)
  shows or hides the coach as a see-through panel over the game, with the cursor in the
  question box, so you can ask without leaving the game. Esc or the same key hides it and the
  game gets the keyboard back. Move and resize it; it remembers its place. Change the key and
  how see-through it is (60-100 %) in **Settings → Overlay**. It is just a window of WoW Coach:
  it never touches the game. Also in the tray menu and as an **Overlay** button on the Coach
  page. The key works by itself on Linux (through the desktop's global-shortcuts portal) and
  Windows; the command `wow-coach-app --toggle-overlay` works everywhere (on macOS it is the
  only way), and the Setup page has an **Overlay hotkey** card that shows the exact command
  to bind by hand. See [the guide](docs/desktop-app.md#overlay-mode-the-coach-on-top-of-your-game).
- **App size** in Settings: make WoW Coach 70 % to 130 % of its normal size, to take less
  room next to the game. It applies when WoW Coach starts again (a **Restart now** button is
  right there).
- **The coach uses tools, searches the web and shows its sources.** WoW Coach's own coach now
  works like your Claude coach: while it answers it can read your character's status, history
  and notes, look things up on the Warcraft Wiki, search the web and save your notebook (the
  last 20 versions of your notes are kept). Under each answer you see **Sources** (buttons that
  open the pages it used) and **What the coach looked up**, and the chat says what it is doing
  while it works. The links come from what was really searched and read, never from links the
  AI wrote. New **Coach tools** card in Settings to turn any of it off, and `wow-coach ask`
  prints a "Sources:" list ([privacy](docs/privacy.md)).
- **One chat history that any AI can use, and your Claude coach chats in the app.** WoW Coach
  keeps one chat file per character in a standard format (JSON Lines, documented in
  [the design notes](docs/design.md#the-data-folder-shared-storage)), so a new AI (Gemini, the
  Claude API...) can read and continue the same conversation. The app imports your
  `claude --agent wow-coach` chats from Claude Code's own session files (read only, every
  minute), shows the full history in the Coach page (tagged "from the game", "from your Claude
  coach", "from another app"), and gives the recent messages to the coach so it knows what you
  already talked about. Other players' names are still hidden. Turn it off with **Use my Claude
  coach chats** in Settings ([privacy](docs/privacy.md)).

### Fixed

- `/coach copy` no longer fails with "invalid value (secret) ... for 'concat'". WoW Forever
  hides some details from addons (for example during fights); those now show as "(hidden by
  the game)", in the copy text and in what the addon saves.
- wow-coach's own coach now sees the whole coach's notebook. It used to send only the first
  4 000 characters of a character's journal, so it missed your next steps, choices and
  progress. Long notes now keep their most useful sections whole, and sections about your
  computer (for example "## This computer") are never sent.
- `/coach` and the new key no longer reload the interface during a fight. They say "Can't save
  during a fight" instead.

### Removed

- The small-AI "triage" step and its "in your own words" text, plus the timer, quiet hours and
  cooldown for the coach speaking up by itself (see Changed).
- Reading answers aloud. Notifications still tell you when an answer is ready.
- Your own usage limits (calls per hour and per day). Only your ChatGPT plan's own limits
  apply.

### Changed

- **"Coach on its own" is now one setting, "When the game saves".** Choose Off, **Tell me
  what's worth knowing** (the default: one free notification listing what changed, such as a
  level-up, full bags, a finished quest or a death, worked out without any AI) or **Tell me
  and update my next steps** (the same, and after every save the coach
  is asked "Status updated: what next?"; the answer shows in the chat and on the keep-on-top
  card). The timer, quiet hours, the
  per-event rules, the waiting time between answers and the small-AI filter are gone, because
  the game only shares your data when it saves, so nothing could ever be live. "Stay quiet in
  dungeons and raids" stays. Older settings files still work and are mapped to the new choice.
- The Notebook page starts collapsed and opens sections when you click them.
- An At a glance summary of your notes (goal, next steps, where you are, choices, latest
  progress) on the Notebook page and beside the chat.
- The "From ChatGPT · 10 min ago" line under answers is gone; the time shows when you point at
  an answer.
- `wow-coach app` opens the new app when it is installed, and the browser window otherwise.
  `wow-coach app --browser` always opens the browser window. `--hidden` starts the app in the
  tray (used by "start when I log in").

## [0.9.0] - 2026-11-08

Your own coach with your ChatGPT plan: the coach window answers your questions from the game by
itself, shows the answer at once (no second reload), can notify you or read it aloud, and can
speak up when something happens, if you want it to.

### Added

- **The coach window** (`wow-coach app`): your own coach in a small page on your computer,
  answering with your ChatGPT plan ([guide](docs/coach-window.md)).
  - It answers questions from the game's Coach panel by itself as soon as the game saves them.
  - The answer shows at once in the window, so no second reload is needed. It can also
    notify you or read it aloud, and it is put in the panel for your next `/reload`.
  - Ask in the window too: type a question, or click "What next?".
- **Sign in with ChatGPT**: `wow-coach signin` and `wow-coach signout`, through OpenAI's own
  page. The sign-in is kept in your computer's password store, never in a file.
- **`wow-coach ask "..."`**: ask your coach in the terminal.
- **When the coach speaks up** (Settings in the window):
  - Per kind of event (you died, died again soon, levelled up, a quest is ready, bags nearly
    full, a new zone, unspent talent points, a gear hint, gear needs repair, a timer), choose
    off, a notification, or advice from the coach.
  - There are quiet hours, quiet in dungeons, a cooldown, and an optional small model that
    decides when the bigger one is worth asking, in your own words.
  - It is manual by default.
- **Limits that protect your plan:** calls per hour and per day (20 and 100 at first), and
  "Manage usage" links to your ChatGPT settings.
- **Privacy:** other players' names are replaced with "a player" before anything goes to the
  AI, unless you allow them. See the [privacy notice](docs/privacy.md) and
  [SECURITY.md](SECURITY.md).

## [0.8.0] - 2026-11-08

The Coach panel: your coach's next steps and answers inside the game, and a box to ask a
question. Restart the game once after updating.

### Added

- **The Coach panel**: a window inside the game with your coach's next steps and answers,
  and a box to ask your coach a question ([guide](docs/coach-panel.md)).
  - Open it with `/coach panel`, from the minimap's addon list, or with a key binding
    (Options, then Keybindings, then CoachLink).
  - `/coach ask <question>` asks without opening it.
  - While a question waits, a **Show answer (reloads)** button loads the answer in one click.
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
