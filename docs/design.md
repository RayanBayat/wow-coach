# How wow-coach works

This page explains the pieces of wow-coach, how data moves between them, and what we
verified about WoW Forever. You do not need it to use the project. It helps if you want to
fix something or add a feature.

## The idea in one paragraph

A World of Warcraft addon cannot talk to the internet or to other programs. The only thing it
can do outside the game is **save a Lua file when you log out or type `/reload`**. WoW calls
these files "SavedVariables". So the CoachLink addon writes a snapshot of your character
(level, zone, quests, talents, gear...) into that file. Then one of three things reads it:
you copy it from a window in the game (`/coach copy`), the `wow-coach` program reads the file
and hands it to an AI app (MCP), or an agent runs `wow-coach status`.

## The pieces

| Piece | Where | Language | Job |
|---|---|---|---|
| CoachLink addon | `addon/CoachLink/` | Lua | Builds the snapshot and history, saves them, shows the copy window |
| `wow-coach` program | `src/wow_coach/` | Python 3.14 | Finds and reads the saved file; commands `status`, `characters`, `progress`, `watch`, `check`, `mcp`, `wiki`; the MCP server; player notes and character journals; game lookups |
| Coach skill | `src/wow_coach/assets/skills/wow-coach/SKILL.md` | Markdown | Tells an AI how to coach, including how to plan toward a goal |
| Coach agent | `src/wow_coach/assets/agents/wow-coach.md` | Markdown | A Claude Code agent: runs a whole session (checks setup, starts live mode, asks which character to continue, greets, plans, says goodbye) and brings its own MCP server |
| Companion | `src/wow_coach/` (`companion.py`, `engine/`, `app/`, `ai/`, `triggers/`, `alerts.py`) | Python | wow-coach's own coach with the player's ChatGPT plan: `wow-coach signin`, `ask`, `app` (0.9.0) |
| Tests | `tests/`, `addon/tests/` | Python, Lua | Python tests, and a Lua test run with a fake WoW API |

## Settings, setup and the packaged Claude files

- `wow-coach setup` (`setup.py`) finds the game folder, installs or updates the addon from
  the GitHub release zip of the same version (`CoachLink-<version>.zip`), creates the notebook,
  and with `--claude-code` copies the agent and skill into `~/.claude`. It refuses zips with
  entries outside `CoachLink/` (zip slip), swaps the new addon in before deleting the old one,
  leaves symbolic links (developer copies) alone, and keeps a `.bak` of a different file it
  replaces. It writes only to the game's `Interface/AddOns/CoachLink`, the data folder and
  `~/.claude`.
- wow-coach's own files (settings, notes, journals, conversations, the usage log) live in the
  data folder: `~/.local/share/wow-coach` on Linux, `~/Library/Application Support/wow-coach` on
  macOS, `%LOCALAPPDATA%\wow-coach` on Windows, or the folder in `WOW_COACH_DATA_DIR`. The
  tests always set that variable, so they never touch real files.
- The game folder is picked in this order: `--wow-dir`, the `WOW_COACH_WOW_DIR` variable, the
  folder saved in `config.json` (data folder, override with `WOW_COACH_CONFIG_FILE`), then
  auto-detect.
- The agent and skill live inside the package (`src/wow_coach/assets/`) so that `pip` and
  `uvx` installs carry them. The agent starts the MCP server with `uvx` pinned to the release
  tag; `tests/test_release_pins.py` fails if that pin or a docs pin is not the project version.

## Data flow

```mermaid
flowchart LR
    A["CoachLink addon<br/>(in the game)"] -->|"logout, /reload, /coach"| B["CoachLink.lua<br/>(SavedVariables file)"]
    A -->|"/coach copy"| W["Copy window"]
    W -->|"you paste"| C["Any AI chat"]
    B -->|"read"| D["wow-coach program"]
    D -->|"MCP tools"| E["AI app"]
    D -->|"status / watch"| F["AI agent with the skill"]
    G["Coach skill"] -.->|"instructions"| E
    G -.->|"instructions"| F
    G -.->|"you paste once"| C
```

The addon never sends anything over the network. The AI app you choose sends what it reads to
its AI provider, like anything else you type there.

## Data contract: `CoachLink.lua` (formatVersion 1)

The addon owns this format. The Python reader must accept everything below and must not
crash on missing fields: every field except `savedAt` and `name` is optional, because any
game call can fail in a new game build.

```lua
CoachLinkDB = {
  ["formatVersion"] = 1,
  ["characters"] = {
    ["Testchar-SomeRealm"] = {         -- key is "Name-Realm"
      ["snapshot"] = { ... },          -- see the table below
      ["history"] = { {event}, ... },  -- oldest first, at most 500 entries (300 before 0.7.0)
      ["progress"] = { {point}, ... }, -- oldest first, at most 500 points (added in 0.5.0)
    },
  },
}
```

### Snapshot fields

| Field | Type | Meaning |
|---|---|---|
| `savedAt` | number | Unix time (seconds) when the snapshot was taken |
| `reason` | string | Why it was taken: `"logout"` (logout, exit or a plain `/reload`), `"coach"` (the `/coach` command) or `"ask"` (the player asked the coach a question, 0.8.0+) |
| `name`, `realm`, `race`, `class` | string | Character identity, in the game's language (for example `"Undead"`, `"Mage"`) |
| `classFile` | string | The class in English capitals, the same in every game language (`"MAGE"`) |
| `faction` | string | `"Horde"` or `"Alliance"` |
| `guild` | table | `{ name, rank }`. Missing when not in a guild |
| `level` | number | Character level (1-60) |
| `xp`, `xpMax` | number | XP into the current level, and XP needed for the next |
| `restedXP` | number | Bonus (rested) XP left. Missing means none |
| `resting` | bool | In an inn or a city, where rested XP builds up |
| `money` | number | Copper. 100 copper = 1 silver, 100 silver = 1 gold |
| `zone`, `subZone` | string | For example `"Tirisfal Glades"`, `"Brill"` |
| `mapID` | number | Map id used by the game's UI |
| `x`, `y` | number | Map coordinates 0-100 (missing inside dungeons) |
| `instance` | table | `{ name, type }` while inside a dungeon or raid (`type` is `"party"`, `"raid"`...) |
| `hearth` | string | Where the Hearthstone is set |
| `stats` | table | `{ health, healthMax, power, powerMax, powerType ("MANA"...), attributes = list of { name, value, base }, armor, resistances = list of { school, value }, spellDamage = list of { school, value }, healing, spellCrit, meleeCrit, dodge (percent), attackPower, manaRegen, manaRegenCasting (mana per second) }` |
| `bags` | table | `{ free = n, total = n, containers = list of container }`. `free`/`total` count the backpack and the four bags. `containers` (added in 0.6.0) also lists a reagent bag or keyring when the character has one |
| `quests` | list | `{ questID, title, level, zone, complete (bool), failed (bool), suggestedGroup, objectivesText, objectives = list of { text, done (bool) } }`. `zone` is the quest-log header it sits under; `objectivesText` is the short "Bring 10 ... to ... in Brill" summary, which names who to hand it in to; `suggestedGroup` is set for group quests |
| `completedQuests` | number | How many quests the character has ever finished |
| `talents` | table | `{ unspent = n, trees = list of { name, spent }, picked = list of { name, rank, maxRank } }` |
| `professions` | list | Every Skills-tab line, each name once: `{ name, rank, maxRank, category }`. `category` is the header the line sat under, in the game's language (`"Professions"`, `"Secondary Skills"`, `"Weapon Skills"`, `"Languages"`...). `category` is optional: older snapshots lack it and can list a profession twice |
| `recipes` | list | Remembered (see below). One entry per profession window opened: `{ profession, rank, maxRank, seenAt, recipes = list of { name, color, skillUps } }`. Only learned recipes. `color` is the recipe's color in the window: `"orange"` (sure skill-up), `"yellow"`, `"green"`, `"gray"` (no skill-up) |
| `gear` | list | One item (see below) per worn slot, plus `slot` (`"Chest"`), `durability` and `durabilityMax` |
| `bank` | table | Remembered. `{ seenAt, containers = list of container }`; a container from the account bank has `account = true` |
| `mail` | table | Remembered. `{ seenAt, letters = list of { sender, subject, money, cod, daysLeft, items = list of { name, count, quality } } }` |
| `timePlayed` | table | Play time: `{ total, thisLevel, seenAt }` (seconds). The addon asks the game for it (see "Remembered fields") |
| `spells` | list | Names of learned, active spells (strings) |
| `spellBook` | list | Every learned spellbook entry: `{ tab, name, rank, passive (bool) }` |
| `reputations` | list | `{ name, group, standing, value, max, atWar }`: `standing` is the game's word (`"Friendly"`), `value`/`max` the progress inside it. A header the player collapsed in the reputation window is `{ name, collapsed = true }`, because the game hides its factions |
| `currencies` | list | `{ name, quantity }` from the Currency tab |
| `legacy` | table | Forever's Legacy system: `{ renown (reward track level), points (unspent), perks = list of { tree, name, rank, maxRank }, challenges = list of { name, done, description } }` (the class challenges) |
| `auras` | list | Buffs and debuffs right now: `{ name, kind ("buff"/"debuff"), seconds (left; missing = no end), stacks }` |
| `actionBars` | list | `{ slot, kind ("spell", "item", "macro"...), name }`. Slots 1-12 are the main bar; the other bars follow in blocks of 12 |
| `group` | table | `{ kind ("party"/"raid"), members = list of { name, level, class } }`. Missing when alone |
| `pet` | table | `{ name, level, family }`. Missing without a pet |
| `achievementPoints` | number | Achievement points |
| `mounts` | list | Names of the mounts the character owns |
| `errors` | list | Strings naming sections the addon failed to read, for example `"talents: attempt to index nil"` |
| `loggedOutAt` | number | Unix time of a logout that found the character already unloaded (see "Logging out" below). The snapshot is then the last full one, from `savedAt`. Missing otherwise |

**Containers and items.** A container (a bag, a bank tab) is
`{ bag, name, slots, free, account, items = list of item }`. An item is
`{ slot, name, itemID, count, quality, itemLevel, requiredLevel, type, subType, equipSlot, stats, sellPrice, bound, noValue }`:
quality 0 gray, 1 white, 2 green, 3 blue, 4 purple, 5 orange; `type`/`subType` are the
game's words (`"Armor"`/`"Cloth"`, `"Tradeskill"`/`"Cloth"`); `equipSlot` (`"Chest"`) and
`stats` (a list of strings like `"+3 Stamina"`) only exist for things you can wear;
`sellPrice` is copper for one item; `noValue` means vendors won't buy it.

**Gear hints.** The report's "Gear hints" section (right after the bags; Python only, in
`report_gear_hints.py`, nothing new is saved) compares bag items with the character. It
lists armor and weapons whose type has no matching `Armor Proficiencies` or `Weapon Skills`
line in `professions` (skipped when the save has no such lines), and "possible upgrades":
a usable item whose `equipSlot` maps to a worn slot that is empty, holds a lower item
level, or holds a gray item. Rings and trinkets are compared with the weaker worn one;
one-hand, two-hand and main-hand weapons with the main hand. The section is only a hint:
the coach makes the final call, and it is left out when there is nothing to say.

**Remembered fields.** The bank, the mailbox and the recipe lists can only be read while
that window is open. The addon reads them at that moment and copies the last thing it saw
(with `seenAt`, Unix time) into every snapshot, so they can be days old. Missing means
"never seen yet".

Play time only reaches addons as the answer to `/played` (the `TIME_PLAYED_MSG` event). The
addon asks for it itself with `RequestTimePlayed()` 3 seconds after logging in, after a
`/reload` and after a level-up. Every chat window prints that answer, so the windows that
listen to `TIME_PLAYED_MSG` stop listening until the answer has arrived (or 10 seconds have
passed), then listen again; the player's own `/played` still shows as usual. An answer from
this session is moved forward to the save time (play time runs while you are logged in), so
`seenAt` is then the save time. An answer from an earlier session is not, because the
offline time is unknown.

All fields added in 0.6.0 are additive: `formatVersion` stays 1, older readers ignore them,
and saves from older addons simply lack them.

### History event fields

| Field | Type | Meaning |
|---|---|---|
| `time` | number | Unix time (seconds) |
| `kind` | string | `"level"`, `"death"`, `"quest"`, `"login"`, `"item"` (added in 0.7.0) |
| `text` | string | A sentence, for example `"Reached level 7"`, `"Died in Brill (level 6)"`. A death adds what is known: `"Died in Brill (level 6). Attacked by 2 enemies: Scarlet Warrior (level 9, elite), Scarlet Friar (level 8). Killing blow: Scarlet Warrior (melee, 45 damage). 40 s after coming back to life."` |
| `level` | number | Character level at the time. For a `"level"` event it is the level reached (saves from addon 0.6.0 and older store the level before it) |
| `zone` | string | Zone at the time |
| `attackers` | list | Death only (added in 0.7.0): the enemies seen attacking in the last 10 seconds, strongest first: `{ name, level, classification, isPlayer }`. `level` -1 means "??" (far above yours); `classification` is the game's word (`"normal"`, `"elite"`, `"rareelite"`, `"rare"`, `"worldboss"`...). Missing when none was seen |
| `killer` | table | Death only: the killing blow from the game's death recap, `{ name, spell, amount }`. `spell` is `"melee"` for a plain hit, or the cause for environment damage (`"falling"`, then without `name`). Missing when the game had no recap |
| `source` | string | Item only: where it came from: `"loot"`, `"quest"` (a quest reward), `"vendor"` (bought) or `"mail"` |
| `item`, `itemID`, `quality`, `count` | | Item only: the item's name, id, quality (0 gray ... 5 orange) and how many. For a quest reward `item` is the reward the player chose (missing when there was nothing to choose) |
| `quest`, `choices`, `rewards` | | Quest reward only: the quest's title, the names of every reward offered to choose from (in the window's order) and of the rewards everyone gets |
| `price` | number | Vendor only: what it cost, in copper |
| `from` | string | Mail only: who sent the letter |
| `secondsSinceRevive` | number | Death only: seconds since the character came back to life, when that was 5 minutes or less ago (a "death loop": coming back next to the same enemies) |

**Where items came from.** Loot comes from the chat line the game prints for your own loot
(`CHAT_MSG_LOOT` matching `LOOT_ITEM_SELF` / `LOOT_ITEM_SELF_MULTIPLE`, so other players'
loot lines don't match). The rest comes from `hooksecurefunc` on the game function the window
calls: `GetQuestReward(choice)` (the quest window's Complete Quest button), `BuyMerchantItem`
and `TakeInboxItem` / `AutoLootMailItem`. Loot and purchases are only kept for things you can
wear and for green or better items; quest rewards and mail are always kept. The hook runs on
the click, so a purchase the game then refuses (not enough gold, full bags) is still recorded.

**How a death is explained.** Since game version 12, addons can't read the combat log in
Forever: `COMBAT_LOG_EVENT_UNFILTERED` is marked restricted, and `GetCurrentEventInfo` only
exists in `C_CombatLogSecure` (Blizzard's own code), not in `C_CombatLog` (checked in the
Forever UI source, `Blizzard_APIDocumentationGenerated/CombatLog*Documentation.lua`). So the
addon can't see who hit you. Instead, while the player is in combat (`PLAYER_REGEN_DISABLED`
to `PLAYER_REGEN_ENABLED`), it looks every second at `target`, `focus`, `mouseover` and
`nameplate1`-`nameplate40`, and remembers each enemy whose target is the player
(`UnitIsUnit(unit .. "target", "player")`). Enemies without a name plate are only seen when
targeted. One second after `PLAYER_DEAD` it asks `C_DeathRecap.GetRecapEvents()` for the
killing blow (the first event, as in Blizzard's recap window) and only uses it if its
`timestamp` is within 30 seconds of now. Not verified in the game: whether Forever fills the
death recap (Blizzard's recap window only loads in retail), so `killer` may stay missing.
Coming back to life is `PLAYER_UNGHOST`, or `PLAYER_ALIVE` when the player is not a ghost.

### Progress point fields

One point is added to a character's `progress` list every time a snapshot is taken (logout,
`/reload`, `/coach`). It is a small copy of the numbers that show how far the character got,
so the coach can compare sessions without keeping every snapshot. `progress` is additive:
`formatVersion` stays 1, and saves from older addon versions simply have no `progress`.

| Field | Type | Meaning |
|---|---|---|
| `time` | number | Unix time (seconds) of the snapshot |
| `reason` | string | Same as the snapshot's `reason` |
| `level`, `xp`, `xpMax` | number | Level, XP into the level, XP needed for the next |
| `money` | number | Copper |
| `zone`, `subZone` | string | Where the character was |
| `questsDone` | number | How many quests in the log were complete (ready to turn in) at that moment. Missing when the quest log could not be read |

Every field is optional: if a game call fails, the point is still added with what is known.
The reader ignores points that look unloaded (see "Logging out" below).
Rules: at most 500 points (the oldest are dropped), and a point is **not** added when
`level`, `xp`, `xpMax`, `money`, `zone`, `subZone` and `questsDone` are all the same as in the
previous point and it was taken within 60 seconds of it (quick `/reload` series).

### How WoW Forever writes the file (seen 2026-11-06, build 1.60.1)

Checked against the game's own `Blizzard_CombatLog.lua` SavedVariables file:

- Windows line endings (`\r\n`), and the file starts with an empty line.
- No indentation.
- Keys are written as `["text"] = value,` or `[0] = value,` (number keys in brackets).
- List entries are written without a key, one per line, and holes are written as `nil,`.
  Older WoW versions add a comment after list entries: `value, -- [1]`. The reader accepts both.
- Strings use double quotes with backslash escapes (`\"`, `\\`, `\n`).
- Booleans are `true` / `false`; numbers can be integers, decimals, or negative.

## Verified facts about WoW Forever

- Forever (product code `wowf`, codename "camelot" in Blizzard's UI code) runs on the modern
  WoW engine. Its addon API is the retail-style one: `C_QuestLog.GetInfo`,
  `C_QuestLog.GetQuestObjectives`, `C_SkillInfo.GetSkillLineInfo`, `C_SpellBook`. Source:
  Blizzard's UI code, mirrored at https://github.com/Gethe/wow-ui-source (branch `forever`,
  build 1.60.1.70790), folder `Interface/AddOns/Blizzard_APIDocumentationGenerated/`.
- Forever talents are three classic-style trees built on the modern `C_Traits` system.
  Blizzard's Forever talent frame gets the config with
  `C_SpecializationInfo.GetCombatConfigIDForSpecGroup(C_SpecializationInfo.GetActiveSpecGroup())`
  and the per-tree points with `C_Traits.GetGroupDisplayInfoByTreeID` and
  `C_Traits.GetGroupCurrencyInfo`. Source: `Blizzard_PlayerSpells/Camelot/ClassTalents/` in the
  same branch.
- The addon's `.toc` interface number for Forever 1.60.1 is `16001`.
- On a real logout or quit (not `/reload`), the game has already unloaded most of the
  character when `PLAYER_LOGOUT` fires: `UnitXPMax` returns 0, every bag has 0 slots, max
  health is 0, `UnitLevel` can be wrong and `C_SpellBook.GetSpellBookSkillLineInfo` returns
  nil. Seen on 2026-11-07 and 2026-11-08 ([#2](https://github.com/RayanBayat/wow-coach/issues/2)).
- SavedVariables are written only on logout, `/reload`, or a clean game exit. Killing the game
  loses the write.
- New addon folders are only picked up after a full game restart, not a `/reload`.
- `/coach` saves by reloading the UI, so the file is written without logging out.
- The first `/coach` after you update the addon still saves with the old code, because the
  save runs before the reload.

## Coach panel: questions and advice (0.8.0)

The Coach panel (`CoachLinkPanel.lua`) shows advice inside the game and lets the player ask a
question. An addon can't use the network or read files while it runs, so questions and
answers travel through files (the plan: `docs/plans/coach-panel.md`).

**Questions (game to wow-coach).** `ns.askCoach(text)` (the panel's Ask button and
`/coach ask <text>`) adds the question to the character's saved table and reloads the UI,
so WoW writes it to disk with a snapshot whose `reason` is `"ask"`. It refuses an empty
question and does nothing in combat (`InCombatLockdown()`).

```lua
["questions"] = {                 -- in CoachLinkDB.characters["Name-Realm"], oldest first
  { ["id"] = "1794100000-1", ["text"] = "What should I do next?", ["askedAt"] = 1794100000 },
},
```

- At most 20 are kept, the newest. The text is at most 500 bytes, cut on a whole letter.
- `id` is "time-counter", unique per character.
- A question whose `id` is in the advice file's `answeredIds` (or is the `questionId` of an
  answer there) counts as answered, and is dropped the next time the player asks.
  `answeredIds` is kept separately because old answers are pushed out of the file.
- Python: `Character.questions`.

**Advice (wow-coach to game).** wow-coach writes a small data-only addon of its own into the
game folder: `Interface/AddOns/CoachLink_Advice/` with `CoachLink_Advice.toc` and
`Advice.lua`.
- It is not part of the CoachLink zip, so addon managers (the CurseForge app) never overwrite
  it.
- `CoachLink.toc` lists it under `## OptionalDeps`, so it loads first when it is there.
- A new addon folder is only noticed after a full game restart.

```lua
CoachLinkAdvice = {
  ["formatVersion"] = 1,
  ["writtenAt"] = 1794100100,
  ["characters"] = {
    ["Name-Realm"] = {
      ["basedOnSave"] = 1794100050,     -- savedAt of the snapshot the coach read
      ["answers"] = {                   -- oldest first, at most 10
        { ["answeredAt"] = 1794100090, ["source"] = "Claude Code coach", ["title"] = "Next steps",
          ["steps"] = { "...", "..." }, ["text"] = "...", ["warnings"] = { "..." },
          ["questionId"] = "1794100000-1", ["question"] = "What should I do next?",
          ["askedAt"] = 1794100000 },
      },
      ["plan"] = { ["goal"] = "Level 20 by Sunday", ["steps"] = { "..." }, ["updatedAt"] = 1794100090 },
      ["answeredIds"] = { "1794100000-1" },  -- every answered question id, newest last, at most 40
    },
  },
}
```

- Every field except `answeredAt` and `title` is optional.
- The limits (steps, lengths, file size) and the Python types are in
  `src/wow_coach/advice/contract.py`.
- The file is Lua that the game runs, so wow-coach writes it with a serializer that only
  produces tables, strings, numbers and booleans:
  - It escapes `\`, `"`, line breaks and control characters.
  - It doubles `|`, so text can't make WoW color codes or links.
  - It reads the result back before using it, and replaces the file in one step (atomically).
- The addon checks every level of the table before using it (`ns.myAdvice()`).

**The panel's view of CoachLink.lua.** `CoachLinkPanel.lua` gets `ns.askCoach`,
`ns.openQuestions` (questions without an answer yet), `ns.myAdvice` (this character's
`CoachLinkAdvice` entry, or nil), `ns.characterKey` and `ns.say`, and sets
`ns.togglePanel`, which `/coach panel` calls. The `.toc` names
`CoachLink_OnAddonCompartmentClick` for the minimap's addon list.

**The panel** (`CoachLinkPanel.lua`, `Bindings.xml`):
- **Opening it:** `/coach panel`, the minimap's addon list, or a key binding (Options, then
  Keybindings, then CoachLink).
- **What it shows:** the newest answer's steps (or the plan's), its text and warnings, the
  open questions, and a footer. The footer gives who wrote it, when, and the save it was based
  on, and ends with "AI can be wrong".
- **Combat:** it hides in combat and comes back after. Ask is disabled in combat.
- **Advice text:** it type-checks and cuts every advice field again. It removes any single
  `|` (doubled `||` from wow-coach stay, and WoW draws them as a plain `|`).
- **Settings:** remembered in `CoachLinkDB.settings.panel`: `point`, `relPoint`, `x`, `y`,
  `width`, `height`, `fontSize`, `open` and `lastSeenAnswerAt`. After a reload, a single chat
  line says when there is advice the player hasn't opened yet.

**Writing the advice** (`src/wow_coach/advice/`):
- **Where:** `writer.py` writes only inside `<AddOns>/CoachLink_Advice/`.
  - It refuses symlinks and junctions for the folder, the `.toc` and `Advice.lua`.
  - It never creates the game's own folders.
  - It replaces `Advice.lua` atomically, through a temp file in the same folder
    (`.tmp-*.part`).
- **The `.toc`:** `## Interface:` (copied from `CoachLink.toc` each time, else 16001),
  `## Title`, `## Notes`, `## Version` (wow-coach's), then `Advice.lua`. No SavedVariables.
- **Limits** (`limits.py`) are enforced by cutting:
  - Blank steps are dropped, and the first 5 steps and 5 warnings are kept, in the order to
    act in.
  - The newest 10 answers are kept, and a new answer to the same `questionId` replaces the
    old one.
  - The file is refused above 200,000 bytes.
- **Reading back:** the reader turns `||` back into `|`.
- **The coach's tools:** `questions_from_game` and `send_advice_to_game` (`advice/tools.py`)
  are the MCP tools. `wow-coach setup` creates the folder after installing the addon. The
  watcher adds "N open question(s)" to a save with `reason: ask`.
- **Tests:**
  - `tests/test_advice_luajit.py` loads written files in LuaJIT.
  - `tests/test_panel_end_to_end.py` writes an answer with the tool and has the real panel
    code show it.

## The companion: wow-coach's own coach (0.9.0)

`wow-coach signin`, `ask` and `app` let wow-coach answer by itself, using the player's
ChatGPT plan. The pieces (the plan, the rules and the reasons: `docs/plans/coach-panel.md`):

| Piece | Code | Job |
|---|---|---|
| Sign-in | `ai/chatgpt_signin.py`, `keychain.py` | Sign in with ChatGPT: OAuth with PKCE, a one-shot loopback server on 127.0.0.1:1455, the refresh token in the system keychain (never a file), a refresh lock file, revoke on sign-out. Details and what a real sign-in showed: `docs/plans/chatgpt-signin-notes.md` |
| The plan | `ai/chatgpt_plan.py`, `usage.py` | The Responses API with the plan token (`store: false`, streamed, JSON schema answers). Every attempt is counted in `usage.jsonl` before it is sent (only counted: wow-coach sets no limit of its own, the plan's own limit applies) |
| The engine | `engine/` | The prompt (coaching rules from the skill, then fenced data blocks: status, history, journal, player notes, conversation, question; about 12 000 tokens at most). The notes are sent section by section, most useful first, and sections about the player's computer never (`engine/notes_digest.py`). Other players' names are replaced with "a player". The answer is JSON (title, steps, text, warnings), written to the Coach panel's file. The conversation is one shared chat history per character, for any AI (see "The data folder: shared storage") |
| The tools | `tools/`, `engine/agent.py`, `engine/sources.py` | The built-in coach uses tools while answering, like the Claude coach does. See "The tool loop" below |
| Putting it together | `companion.py` | One builder for the CLI and the window: the same keychain entry, usage log and refresh lock. `LiveCoach` reads `settings.json` before every answer |
| Settings | `app_settings.py` | `settings.json` in the data folder, no secrets. Every value is checked; a damaged file gives the defaults |
| When to speak | `triggers/` | Two saves give events (death, level-up, quest ready, bags...). One setting, `on_save`: `off`, `notify` (default: one free notification listing what is worth knowing, no AI) or `advice` (the same plus one coach answer), and one switch, quiet in instances. The game only hands data out when it saves, so there is no timer, no quiet hours, no cooldown (a save with nothing new gives no events) and no triage. One save never costs more than one unasked AI call |
| The window | `app/` | A page on 127.0.0.1 (see below), and a watcher that answers the Coach panel's questions and runs "when the game saves" |
| Alerts | `alerts.py` | Desktop notifications through the system's own programs (`notify-send`, `osascript`, PowerShell) |

**The tool loop** (`engine/agent.py`, the loop documented in `ai/base.py`). The engine builds
the tools for the character (`tools/registry.py`: status, history, progress, read and save the
notes, search and read the Warcraft Wiki, find a quest by id; the same abilities as the MCP
server) and asks the AI with the tool list and, if allowed, the provider's own web search.
While the answer asks for tools, each one is run (`CoachTool.run`, which never raises: an
unknown tool name or unreadable arguments become a plain sentence the AI can act on) and the
results are sent back. At most 8 rounds, then one last ask without tools, so there is always an
answer. Failures degrade like this:
- the provider refuses the web search: the same round is asked again without it, and search
  stays off for the rest of that question;
- any other failure while tools are on: the whole question is asked once more the old way (no
  tools, no search), and logged. "Not signed in" and the plan limit are raised at once, because
  asking again cannot fix them;
- every tool output goes through the same hiding of other players' names as the prompt, and the
  notes tools never show or lose the notes' sections about the player's computer (they are left
  out of what is read and kept when the notes are saved).

Progress is reported through a callback, one plain sentence per lookup ("Searched the Warcraft
Wiki for ...", "Read your character journal", "Saved your character journal"). The app core
turns each into an `activity` event, which the Coach page shows in its typing bubble.

**Sources, always.** Under each answer the window lists the pages it came from. The list is
built by our own code and never from links the AI wrote (`engine/sources.py`): the web
search's own citations, plus the Warcraft Wiki pages a tool actually read (`read_wiki_page`).
Pages that a search or `find_quest` only *listed* count only when nothing was read. No repeats,
in the order used, at most 8, and only `http` and `https` links (so no `javascript:` or `file:`).
The same rule is applied again when the window reads them, whoever stored them. They are shown
as buttons with the page title (or the site) and the whole link as tooltip, and opened only on
a click. The CLI `ask` prints them as a "Sources:" list. The game's `Advice.lua` is unchanged.

**The settings that control it** (`app_settings.py`, all on by default): `use_tools` ("Let the
coach look things up"), `web_search` ("Let the coach search the web too"), `save_notes` ("Let
the coach update your notebook"; off leaves out the two save tools) and `show_lookups` ("Show
what the coach looked up"). With "send the coach's notes" off, the notes tools are left out
too. Every time the coach saves a notes file, the version it replaces goes to a `.history`
folder next to it, and the last 20 versions are kept.

**The window's safety rules** (`app/server.py`):
- **Where it listens:** 127.0.0.1 only, on a random port. The Host header must be exactly
  `127.0.0.1:<port>`, against DNS rebinding.
- **The start link:** it carries a one-time token in its `#fragment`, which the server never
  sees. The browser is given a private start page in a 0700 temp folder (a 0600 file with a
  meta refresh, deleted after 60 s), so the token never appears in a command line other users
  could read. The terminal prints the link too.
- **The session:** the page trades the token once for a random session secret. It keeps the
  secret in `sessionStorage` (this tab, this exact address, never sent by itself) and sends it
  as the `X-Wow-Coach-Session` header on every `/api` call, including the streamed events.
  There is no cookie: cookies are shared with every other port on 127.0.0.1.
  - The custom header also stops other websites: it forces a preflight, which the server
    answers with 405.
  - Pressing Enter in the terminal makes a fresh start link.
- **Where requests come from:** a matching `Origin` is required on changes. `Sec-Fetch-Site`
  `cross-site` or `same-site` is refused, except a top-level navigation to the page itself
  (the start page's `file://` hop), which holds no data.
- **Headers:** a strict Content-Security-Policy with no inline scripts, `nosniff`,
  `no-referrer`, `no-store`, `DENY` frames, and same-origin CORP and COOP.
- **Limits:** a 30 s timeout per request, at most 32 connections and 4 event streams, and
  every error is one JSON sentence (never a traceback).
- **Files and sizes:** a fixed list of static files, and capped request sizes.
- **AI text** reaches the page only through `textContent`. A test fails on `innerHTML` and
  similar.

**Alerts never use a shell.** AI text is passed as separate program arguments, on stdin, or
in an environment variable that a fixed script reads, and is cut and cleaned first. A
compliance test fails on `shell=True`, `os.system` and `os.popen`.

**Sign in with ChatGPT rules** (OpenAI's terms and UI guidelines):
- The app signs in under its own name, and uses only the official flow (never passwords or
  cookies).
- The privacy notice (`docs/privacy.md`) is shown before signing in.
- The wording is "Continue with ChatGPT", "You're using your ChatGPT plan", "Using ChatGPT
  plan" and "Manage usage".
- Plan use is free in wow-coach, and security problems are also reported to OpenAI
  (`SECURITY.md`).

## The desktop app (0.10.0)

`wow-coach app` opens a Qt window (`src/wow_coach/desktop/`, PySide6 from the optional
`desktop` extra). It is a second face for the same brain as the browser window: it builds the
same `AppCore` (`app/run.py` `build_core`) and the same `Watcher`, so answering, "when the game saves",
limits and alerts work exactly as above. There is no web server in the desktop app.

| Piece | Code | Job |
|---|---|---|
| The bridge | `desktop/bridge.py` | The only object the windows talk to. It reads `AppCore.state()` in a background thread (the save file may be on a slow disk), one read at a time with a "read again" flag, and turns the core's event mailbox into Qt signals. Network calls (models, sign-out) also run in the background |
| Typed state | `desktop/state.py` | `AppCore.state()`'s dict as small frozen dataclasses; anything missing or of the wrong type becomes a safe default |
| Look | `desktop/theme.py`, `desktop/assets/` | Every color as a named token, light and dark, one stylesheet; small SVG pictures for arrows and check marks |
| Pages | `desktop/pages/` | Coach (chat), Settings, ChatGPT, Setup, Privacy. Each redraws from the newest state and reacts to single events |
| Keep on top | `desktop/compact.py` | A frameless tool window that stays on top without taking focus. On Linux with Wayland the app runs through XWayland (`run.py` `platform_arguments`), because Wayland doesn't let apps keep their own window on top |
| Shell | `desktop/tray.py`, `desktop/single_instance.py` | Closing hides to the tray (or quits without one). A per-user local socket keeps one copy running; a second start asks the first to show its window |
| Setup | `desktop/setup_checks.py`, `desktop/shortcuts.py` | The same addon install code as `wow-coach setup`. App-menu and log-in shortcuts (`.desktop` files on Linux, `.lnk` through PowerShell with paths only in environment variables on Windows). A shortcut is never written when the program lives in a temporary uv cache |

**The chat.** The Coach page draws the character's chat history (`conversations/<key>.jsonl`,
the newest 200 messages that `AppCore.state()` sends as `conversation`), oldest at the top. An
answer with a structured `answer` keeps the parchment layout (title, numbered steps, warnings).
A plain-text reply (from the Claude coach) is a parchment bubble with the text, folded after 700
characters behind "Show more". Messages are tagged "from the game", "from your Claude coach" or
"from another app". Every message is drawn once: by `id`, and by answer time and title for an
answer that arrived both as a live event and as a stored message. Answers that only the game's
answer file has are placed among the messages by time. If older chats arrive later (the
importer finished after the first draw), the chat is drawn again in time order.

**Refreshing the game data.** Only the game can save the character, and only at a reload or a
logout. An outside program pressing keys in the game would break Blizzard's rules, so the app
never does. The addon has a "Save for the coach" key binding (the same as `/coach`). The app
has no refresh button: the watcher notices every save by itself and publishes a `save` event;
the window then re-reads the state, updates the freshness pill and shows a calm "Got your
latest game data" note for about 3 seconds. A question is never held back for a save: it is
asked right away with the data from the last one.

**What we tested and ruled out (2026-11-08):** the game's chat log (`/chatlog`,
`Logs/WoWChatLog.txt`) is not written while playing: it stayed empty through 30 minutes of
play, a `/reload` and turning logging off. WoW writes it at logout, so it can't carry live
questions or status. Showing answers inside the game without a reload (loading pre-made
"slot" addons on a timer) is possible but a gray area, and is not built.

**Safety:** AI and game text are shown as plain text only (never rich text, Markdown or
links). The only links opened are fixed ones in the code, plus OpenAI's sign-in page.

## The data folder: shared storage

wow-coach keeps everything it remembers in plain files in one folder, the **data folder**
(`~/.local/share/wow-coach` on Linux, `~/Library/Application Support/wow-coach` on macOS,
`%LOCALAPPDATA%\wow-coach` on Windows, or the folder in `WOW_COACH_DATA_DIR`). The files are
plain JSON, JSON Lines or Markdown on purpose: any AI provider added later (Gemini, the
Claude API...) and any other tool can read and write the same files, so a change of AI never
loses what the coach knows. Readers must ignore fields they don't know, treat a damaged file
as empty, and write by saving a temp file and renaming it over the old one. Files that two
programs may change are locked with `<file>.lock` (`filelock.py`).

| File | Format | What it holds |
|---|---|---|
| `settings.json` | JSON object | The choices made in the app (`app_settings.py`): `model`, `answer_questions_from_game`, `notify`, `share_other_player_names`, `send_coach_notes`, `use_claude_chats`, `triggers` (`on_save` and `quiet_in_instances`; the older per-event format is still read and mapped). Missing or wrong values mean the defaults |
| `config.json` | JSON object | `wow_dir`: the game folder saved by `wow-coach setup` (the `WOW_COACH_CONFIG_FILE` variable points to another file) |
| `coach-notes.md` | Markdown | The player notes (how the player likes to be coached). The `WOW_COACH_NOTES_FILE` variable points to another file |
| `characters/<Name-Realm>.md` | Markdown | The coach's journal of one character: goals, plans, decisions |
| `conversations/<Name-Realm>.jsonl` | JSON Lines, format v1 below | The chat history of one character, from every AI and every place |
| `import-state.json` | JSON object | How far each Claude Code transcript was read: `{"v": 1, "claude-code": {"<project>/<session>.jsonl": {"offset": bytes, "coach": true, "character": "Name"}}}` |
| `answered-questions.json` | JSON object | `{"Name-Realm": ["question id", ...]}`: game questions already answered, so none is answered (and paid for) twice |
| `hidden-names-v2.json` | JSON object | `{"Name-Realm": ["name", ...]}`: other players' names seen in earlier saves, kept hidden |
| `usage.jsonl` | JSON Lines | One line per AI call: `{"at": ISO time, "model", "input_tokens", "output_tokens"}` and `"tokens_only": true` for numbers that belong to an earlier counted call. No text |
| `welcome-seen.flag` | Text | Exists once the welcome message was dismissed |
| `instance.lock` | Lock file | Held by the running desktop app, so only one copy runs |
| `chatgpt-refresh.lock` | Lock file | Held while a ChatGPT sign-in renewal runs, shared by the app and the command line |
| `*.lock`, `.*.part` | Temporary | A lock, or a file being written; both disappear by themselves (a lock older than 30 s counts as left behind by a crash) |

The ChatGPT sign-in is not in this folder: it lives in the system password store.

### The chat history (`conversations/<Name-Realm>.jsonl`, format v1)

One message per line, oldest first:

```json
{"v": 1, "id": "app:3f2a9c0e...", "at": "2026-11-07T22:14:07.767Z", "role": "assistant",
 "content": "Next steps. Go to Brill; Train spells. You are level 7.",
 "source": "game", "provider": "chatgpt", "model": "gpt-...",
 "answer": {"title": "Next steps", "steps": ["Go to Brill", "Train spells"],
            "text": "You are level 7.", "warnings": []}}
```

| Field | Meaning |
|---|---|
| `v` | The format version, `1` |
| `id` | Unique and stable. The same message is never stored twice (`app:<random>`, `game:<question id>` for a question typed in the game, `claude-code:<line uuid>`, `outside:<hash>`) |
| `at` | ISO 8601 time in UTC. The file is kept in time order |
| `role` | `"user"` (the player) or `"assistant"` (a coach) |
| `content` | The message as plain text, always present. This is what any AI is given as the conversation, so it is the provider-neutral part. For a structured answer it is `title. step; step. text` |
| `source` | Where it happened: `"app"` (the window or `wow-coach ask`), `"game"` (the game's Coach panel), `"claude-code"` (imported from the player's Claude Code coach), `"outside"` (an answer another app wrote into `Advice.lua`) |
| `provider` | Who answered: `"chatgpt"`, `"claude-code"`, or a short id of a future provider; `null` for the player |
| `model` | The model id the provider reported, or `null` |
| `answer` | The structured coach answer (`title`, `steps`, `text`, `warnings`, and optionally `sources` and `lookups`), only for display; `null` otherwise |

The optional parts of `answer` (left out when empty; an older line simply lacks them):
`"sources": [{"title": "Abigail Shiel", "url": "https://warcraft.wiki.gg/wiki/Abigail_Shiel"}]`
(the pages the answer came from; `title` may be empty; a reader drops anything that is not an
`http` or `https` link) and `"lookups": [{"kind": "web", "text": "Read the Warcraft Wiki page
\"Abigail Shiel\""}]` (what the coach looked up or saved, as plain sentences; `kind` is `read`,
`write` or `web`).

Rules for every reader and writer:

- A line from an older wow-coach has only `role` and `content`. It reads with the defaults
  `source: "app"` and no provider, model or answer. Unknown fields are ignored; a damaged line
  is skipped and disappears at the next write.
- Append by reading the file, adding the messages whose `id` is new, sorting by `at`, keeping
  the newest 2 000 messages (and at most about 6 MB), and writing the whole file in one step
  while holding the lock. `engine/conversation.py` does this (`ChatMessage`, `read_messages`,
  `append_messages`).
- A message keeps at most 6 000 characters of `content`.
- The coach's prompt takes the newest messages from every source that fit its size cap and
  names the speaker: `Player:`, `Coach:`, `Coach (Claude Code):`, `Coach (another app):`.
  Other players' names are hidden there like everywhere else.

### Importing the Claude Code coach chats

`importers/claude_code.py` copies what the player said to their Claude coach
(`claude --agent wow-coach`) into the chat history. Claude Code writes every session as
`<config dir>/projects/<project>/<session>.jsonl` (`~/.claude`, or `CLAUDE_CONFIG_DIR`). The
format is Claude Code's own and not documented, so the importer trusts nothing:

- A session counts only if it has a line `{"type": "agent-setting", "agentSetting": "wow-coach"}`.
- From `user` lines it takes text the player typed (a string, or text blocks) and skips
  `isMeta` and `isSidechain` lines, tool results, notifications from other agents, and wrappers
  such as `<command-...>`, `<local-command...>`, `<system-reminder>` and interruption marks.
- From `assistant` lines it takes the text blocks only (never thinking or tool calls) and
  joins the blocks of one reply (they share `message.id`). A reply that may still be growing is
  kept for the next pass, unless Claude Code wrote its `turn_duration` end-of-turn line.
- The character comes from the session's tool calls (a tool name containing `wow-coach` with an
  input `character`), matched with `pick_character`; otherwise the most recently saved
  character.
- Each pass reads only new bytes (`import-state.json`) and ids are `claude-code:<line uuid>`,
  so importing is incremental and repeating it changes nothing. The desktop app runs it once at
  the start and then every 60 seconds in the watcher thread, unless the player turned off
  "Use my Claude coach chats" (`use_claude_chats`).

## Logging out

Because of the unloaded character at `PLAYER_LOGOUT` (above), the addon works like this
(code: `takeSnapshot`, `looksUnloaded` and "Logging out" in `CoachLink.lua`):

1. A snapshot **looks unloaded** when its bags have 0 slots in total, its max health is 0, or
   it needs 0 XP for the next level below level 60. A section that failed to read proves
   nothing, so a broken game function alone never makes a snapshot look unloaded.
2. When the player starts to log out or quit, the addon reads a snapshot while the character
   is still there: right after the game's `Logout()` or `Quit()` runs (the game menu buttons
   and `/logout`, `/camp`, `/quit` call them; `hooksecurefunc` runs our code after the game's
   own) and on the countdown events `PLAYER_CAMPING` and `PLAYER_QUITING`.
3. At `PLAYER_LOGOUT` the addon reads the game as before. If that looks unloaded, it saves
   the snapshot from step 2 instead (with the bank, mail, recipes and play time it has seen
   since). Without one, it keeps the last full snapshot, sets `loggedOutAt`, and adds no
   progress point. Only the very first save of a character is kept even when it looks
   unloaded, so there is something to show.
4. The Python reader shows a warning for a snapshot that looks unloaded (older addons saved
   them) and leaves such progress points out of `progress_summary`.

What we have not seen in the game yet: whether `PLAYER_CAMPING` fires for an instant logout
in an inn. The `Logout()` hook covers that case either way.

## The coach's memory: player notes and character journals

The coach keeps two kinds of Markdown file in the data folder (code: `notes.py`):

| File | Holds | Tools |
|---|---|---|
| `coach-notes.md` (the **player notes**) | The person: how much detail they want, click-by-click steps, Questie or not, solo or group, computer notes. Shared by all characters. Same file as in 0.4.0, so an existing notebook keeps working | `save_player_notes` |
| `characters/<Name-Realm>.md` (a **character journal**) | One character: choices (spec, professions), `## Goals` and plans, progress log, open advice | `save_coach_notes` |

- `read_coach_notes(character)` returns both, with headings, and says when the journal does not
  exist yet. Setup creates only the player notes; the coach creates a journal the first time
  it coaches a character.
- Journal file names come from `Name-Realm` with the characters `<>:"/\|?*` and control
  characters replaced by `_` (spaces stay), so they work on Windows, macOS and Linux.
  `WOW_COACH_NOTES_FILE` moves the player notes file, and the `characters` folder moves with it.
- A character is found by its name or `Name-Realm`, case-insensitive. Without a name the most
  recently saved character is used.
- `list_characters` shows each character's first bullet under `## Goals` (or "no journal yet").
  The progress numbers come from the addon's `progress` list, not from the journals:
  `progress_summary` (code: `format_progress` in `report.py`) groups points less than 30
  minutes apart into one play session, starts a session at its login event (from `history`)
  because a session often has just one save point, and estimates XP per hour of play from that.
- Each file is limited to 100 KB. Saving replaces the whole file.

## Game lookups (Warcraft Wiki)

The MCP server (and the `wow-coach wiki` command) can look up game facts so the coach does not
need slow, noisy web searches. Code: `web.py` (downloading), `wiki.py` (the three lookups),
`wikitext.py` (turning the wiki's source markup into plain text).

How it works, in plain words:

1. `search_wiki` asks the wiki's search API for page titles and shows a cleaned one-line
   snippet and the link for each.
2. `find_quest` finds a quest page by quest ID. A title search is unreliable: Forever reuses
   Classic quests (same ID) and their pages are called "Title (Classic)", while the plain
   title is often the Retail quest with a different ID. The status report shows each quest as
   "(quest 365)". Quest pages have a `Questbox` info box with an `id` field, so the tool runs
   the wiki's search (CirrusSearch) with `insource:"id = 365" insource:Questbox` and lists the
   pages found. For each it says whether the match snippet shows the `id = 365` line. If
   several pages match it says so; if none match it says so and suggests `search_wiki`
   (it never guesses). On the command line: `wow-coach wiki --quest 365`.
3. `read_wiki_page` asks the wiki's parse API for a page's source text, then `wikitext.py`
   pulls the info box (name, level, location...) out, turns coordinates like
   `{{co|61|52|Tirisfal Glades}}` into `Tirisfal Glades 61, 52`, turns links into their text,
   turns tables into `a | b | c` rows, and drops references and HTML.
   Version labels are kept: a banner such as `{{Forever only}}` becomes the note "Marked
   Forever-only on the wiki.", and `{{cw}}` / `{{fw}}` become `[Classic]` / `[Forever]`.
   `{{g|sod}}` (the wiki's game-name template) becomes "Season of Discovery", `{{g|forever}}`
   becomes "Forever".
   Templates the reader does not know never make text vanish silently:
   - Page furniture (navigation boxes, "External links" lists, reference lists, sort keys,
     season banners) is dropped.
   - A template with a plain argument leaves its last plain argument.
   - Any other template, such as an included list like `{{SoD Mage Scroll 20}}`, is first sent
     to the wiki's `action=expandtemplates` API. That is one extra request per page (at most 12
     templates, each answer cut at 3000 characters), and only for pages that have such
     templates. If it fails, the template shows as `[SoD Mage Scroll 20]` so the coach can see
     something was there.
4. Every answer ends with a `Source:` line.

Rules we follow:

- **Source and license.** Only the Warcraft Wiki (https://warcraft.wiki.gg), through its
  official MediaWiki API (`api.php`). Its text is CC BY-SA 4.0, so each answer shows the page
  link and "Warcraft Wiki, CC BY-SA 4.0". The saved responses in `tests/fixtures/wiki/` are
  short real samples used only to test the parser; they carry the same license and come from
  the wiki pages named in their file names.
- **Politeness.** The `User-Agent` is `wow-coach/<version> (+https://github.com/RayanBayat/wow-coach)`.
  Every call adds `maxlag=5` (the wiki may refuse us when its servers are busy). Answers are
  cached in memory for 1 hour, requests to one site are at least 0.5 s apart, and every request
  times out after 10 s. When a request fails the tool returns a plain sentence (for example
  "Warcraft Wiki didn't answer (timeout). Try again or use web search.") and never crashes.
- **robots.txt.** The wiki's `robots.txt` (checked 2026-11-07) allows ordinary agents and
  states `Content-Signal: search=yes, ai-train=no, use=reference`. Lookups for a player's
  question are reference use. We never train on wiki text, never save it to disk (the cache is
  memory only) and never copy the wiki in bulk.
- **Network access is only in `web.py`.** Everything else receives a `fetch` function, so tests
  use saved responses and never touch the internet.

### Why Wowhead is not included

Wowhead has handy public JSON endpoints (a search suggestion list and a tooltip service), and
we looked at using them. We decided not to, on 2026-11-07, for two reasons:

- Wowhead's terms of use (https://corp.fanbyte.com/legal/terms, linked from
  https://www.wowhead.com/forever/tos) say you may not "attempt to access or search the
  Service or download content from the Service using any engine, software, tool, agent,
  device or mechanism (including spiders, robots, crawlers, data mining tools or the like)
  other than the software and/or search agents provided by ZAM or other generally available
  third-party web browsers". A program that queries Wowhead for an AI is that kind of tool.
- Wowhead's pages answer automated requests with 403 (bot protection). Getting around that
  would break the first point and is something this project never does.

So there are no Wowhead tools. If Wowhead publishes an official, permitted API, this can be
revisited.

### What we never do

- Never get around a site's protection: no headless browsers, no cookie or token tricks, no
  pretending to be a web browser.
- Never use a site whose terms forbid automated access.
- Never hide where an answer came from: every lookup ends with a `Source:` line.

## Known limits

- The snapshot is only as fresh as the last logout, `/reload` or `/coach`.
- Quests under a collapsed quest-log header are not saved (`C_QuestLog.GetInfo` only walks
  shown entries). The same goes for factions under a collapsed reputation header; those
  headers are saved with `collapsed = true` so the coach can say so.
- The bank, mailbox and recipe lists are only as fresh as the last time the player opened
  that window.
- The Lua test uses a fake game API, so it proves our logic, not Blizzard's behavior.
- There is no live combat data.

## Safety

- The addon uses only the normal addon API. There is no memory reading, no injection and no
  automation, so it is allowed under Blizzard's addon rules like any other addon.
- Every part of the snapshot is read inside a protected call. If one game function breaks in a
  patch, that part is listed under `errors` and the rest still saves.
- The program only reads the saved file. Its only writes are the player notes file and the
  character journals.
- The addon uploads nothing. The program never sends your character anywhere. Its only
  internet use is the wiki lookups above, which send just the words being looked up.
