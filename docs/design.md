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
| `wow-coach` program | `src/wow_coach/` | Python 3.14 | Finds and reads the saved file; commands `status`, `watch`, `check`, `mcp`; the MCP server; coach notes |
| Coach skill | `skills/wow-coach/SKILL.md` | Markdown | Tells an AI how to coach |
| Tests | `tests/`, `addon/tests/` | Python, Lua | Python tests, and a Lua test run with a fake WoW API |

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
      ["history"] = { {event}, ... },  -- oldest first, at most 300 entries
    },
  },
}
```

### Snapshot fields

| Field | Type | Meaning |
|---|---|---|
| `savedAt` | number | Unix time (seconds) when the snapshot was taken |
| `reason` | string | Why it was taken: `"logout"` (logout, exit or a plain `/reload`) or `"coach"` (the `/coach` command) |
| `name`, `realm`, `race`, `class` | string | Character identity, in the game's language (for example `"Undead"`, `"Mage"`) |
| `level` | number | Character level (1-60) |
| `xp`, `xpMax` | number | XP into the current level, and XP needed for the next |
| `restedXP` | number | Bonus (rested) XP left. Missing means none |
| `money` | number | Copper. 100 copper = 1 silver, 100 silver = 1 gold |
| `zone`, `subZone` | string | For example `"Tirisfal Glades"`, `"Brill"` |
| `mapID` | number | Map id used by the game's UI |
| `x`, `y` | number | Map coordinates 0-100 (missing inside dungeons) |
| `hearth` | string | Where the Hearthstone is set |
| `bags` | table | `{ free = n, total = n }` bag slots |
| `quests` | list | `{ questID, title, level, complete (bool), objectives = list of { text, done (bool) } }` |
| `talents` | table | `{ unspent = n, trees = list of { name, spent }, picked = list of { name, rank, maxRank } }` |
| `professions` | list | Every Skills-tab line, each name once: `{ name, rank, maxRank, category }`. `category` is the header the line sat under, in the game's language (`"Professions"`, `"Secondary Skills"`, `"Weapon Skills"`, `"Languages"`...). `category` is optional: older snapshots lack it and can list a profession twice. The report hides lines whose maxRank is 1, shows weapon skills on their own line and hides languages |
| `gear` | list | `{ slot, name, itemLevel, quality }`; quality 0 gray, 1 white, 2 green, 3 blue, 4 purple, 5 orange |
| `spells` | list | Names of known spells (strings) |
| `errors` | list | Strings naming sections the addon failed to read, for example `"talents: attempt to index nil"` |

### History event fields

| Field | Type | Meaning |
|---|---|---|
| `time` | number | Unix time (seconds) |
| `kind` | string | `"level"`, `"death"`, `"quest"`, `"login"` |
| `text` | string | A sentence, for example `"Reached level 7"`, `"Died in Brill (level 6)"` |
| `level` | number | Character level at the time |
| `zone` | string | Zone at the time |

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
- SavedVariables are written only on logout, `/reload`, or a clean game exit. Killing the game
  loses the write.
- New addon folders are only picked up after a full game restart, not a `/reload`.
- `/coach` saves by reloading the UI, so the file is written without logging out.
- The first `/coach` after you update the addon still saves with the old code, because the
  save runs before the reload.

## Known limits

- The snapshot is only as fresh as the last logout, `/reload` or `/coach`.
- Quests under a collapsed quest-log header are not saved (`C_QuestLog.GetInfo` only walks
  shown entries).
- The Lua test uses a fake game API, so it proves our logic, not Blizzard's behavior.
- There is no live combat data.

## Safety

- The addon uses only the normal addon API. There is no memory reading, no injection and no
  automation, so it is allowed under Blizzard's addon rules like any other addon.
- Every part of the snapshot is read inside a protected call. If one game function breaks in a
  patch, that part is listed under `errors` and the rest still saves.
- The program only reads the saved file. Its only write is the coach notes file.
- Nothing is uploaded by the addon or the program.
