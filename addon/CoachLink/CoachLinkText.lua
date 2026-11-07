--[[
CoachLink text export: turns a snapshot into plain text for pasting into an AI chat.

This file is "pure": it only does string work on tables you hand it. It never
calls the game, so the test harness can check its output outside WoW.

WoW gives every file of an addon the same two values through `...`: the addon
name and one shared table. We put our function on that table (ns.formatSnapshotText)
so CoachLink.lua can call it.

No color codes and no Markdown, so the text looks the same in any chat.
]]

local _, ns = ...

local MAX_HISTORY_LINES = 10   -- keep the pasted text short
local WEAPON_SKILLS = "Weapon Skills"   -- Skills-tab headers, as the English client names them
local LANGUAGES = "Languages"
local QUALITY_WORDS = { [0] = "poor", "common", "uncommon", "rare", "epic", "legendary" }

local INTRO = {
    "This is my World of Warcraft: Forever character, exported by the CoachLink addon.",
    "Please be my coach: explain game terms simply and tell me my next 1-3 steps.",
    "I am fairly new to the game, so keep it short and friendly.",
}


-------------------------------------------------------------------------------
-- Small helpers
-------------------------------------------------------------------------------

-- Copper to "1g 23s 45c". Zero parts are left out, except that 0 copper is "0c".
local function moneyText(copper)
    local gold = math.floor(copper / 10000)
    local silver = math.floor((copper % 10000) / 100)
    local rest = copper % 100
    local parts = {}
    if gold > 0 then table.insert(parts, gold .. "g") end
    if silver > 0 then table.insert(parts, silver .. "s") end
    if rest > 0 or #parts == 0 then table.insert(parts, rest .. "c") end
    return table.concat(parts, " ")
end

-- "5 min ago", "3 h ago"... for history lines. A missing time gives "".
local function agoText(then_, now)
    if not then_ or not now then return "" end
    local seconds = math.max(0, now - then_)
    if seconds < 3600 then
        return math.floor(seconds / 60) .. " min ago"
    elseif seconds < 86400 then
        return math.floor(seconds / 3600) .. " h ago"
    end
    return math.floor(seconds / 86400) .. " d ago"
end

-- Add a section: a blank line, the header, then its lines. Empty sections are skipped.
local function addSection(out, header, lines)
    if #lines == 0 then return end
    table.insert(out, "")
    table.insert(out, header)
    for _, line in ipairs(lines) do
        table.insert(out, line)
    end
end


-------------------------------------------------------------------------------
-- One function per section. Each returns a list of lines.
-------------------------------------------------------------------------------

local function characterLines(snapshot)
    local lines = {}
    local who = (snapshot.name or "?") .. ", level " .. tostring(snapshot.level or "?")
    who = who .. " " .. (snapshot.race or "") .. " " .. (snapshot.class or "")
    if snapshot.realm then who = who .. " (realm " .. snapshot.realm .. ")" end
    table.insert(lines, who)

    if snapshot.xp and snapshot.xpMax and snapshot.xpMax > 0 then
        local line = string.format("XP: %d / %d (%d%%)", snapshot.xp, snapshot.xpMax,
            math.floor(snapshot.xp / snapshot.xpMax * 100))
        if snapshot.restedXP and snapshot.restedXP > 0 then
            line = line .. ", rested XP " .. snapshot.restedXP
        end
        table.insert(lines, line)
    end
    if snapshot.money then
        table.insert(lines, "Gold: " .. moneyText(snapshot.money))
    end
    if snapshot.bags then
        table.insert(lines, string.format("Bags: %d free of %d slots",
            snapshot.bags.free or 0, snapshot.bags.total or 0))
    end
    return lines
end

local function locationLines(snapshot)
    local lines = {}
    local place = snapshot.zone or ""
    if snapshot.subZone and snapshot.subZone ~= "" then
        place = place .. ", " .. snapshot.subZone
    end
    if place ~= "" then table.insert(lines, "Now in: " .. place) end
    if snapshot.hearth then table.insert(lines, "Hearthstone set to: " .. snapshot.hearth) end
    return lines
end

local function questLines(snapshot)
    local lines = {}
    for _, quest in ipairs(snapshot.quests or {}) do
        local line = string.format("- [%s] %s%s", tostring(quest.level or "?"),
            quest.title or "?", quest.complete and " (DONE, ready to turn in)" or "")
        table.insert(lines, line)
        for _, objective in ipairs(quest.objectives or {}) do
            table.insert(lines, "    " .. (objective.done and "[x] " or "[ ] ") .. (objective.text or ""))
        end
    end
    return lines
end

local function talentLines(snapshot)
    local talents = snapshot.talents
    if not talents then return {} end
    local lines = { "Unspent talent points: " .. tostring(talents.unspent or 0) }
    local trees = {}
    for _, tree in ipairs(talents.trees or {}) do
        table.insert(trees, (tree.name or "?") .. " " .. tostring(tree.spent or 0))
    end
    if #trees > 0 then table.insert(lines, "Points per tree: " .. table.concat(trees, ", ")) end
    local picked = {}
    for _, talent in ipairs(talents.picked or {}) do
        table.insert(picked, string.format("%s (%s/%s)", talent.name or "?",
            tostring(talent.rank or "?"), tostring(talent.maxRank or "?")))
    end
    if #picked > 0 then table.insert(lines, "Picked: " .. table.concat(picked, ", ")) end
    return lines
end

-- Skills worth showing: skip languages and 1/1 lines (you have them or not).
-- Professions are listed one per line, weapon skills together on one line.
local function skillLines(snapshot)
    local lines, weapons = {}, {}
    for _, skill in ipairs(snapshot.professions or {}) do
        local isLanguage = skill.category == LANGUAGES
        local isLevelable = skill.maxRank ~= 1
        if not isLanguage and isLevelable then
            local ranks = tostring(skill.rank or "?") .. "/" .. tostring(skill.maxRank or "?")
            if skill.category == WEAPON_SKILLS then
                table.insert(weapons, (skill.name or "?") .. " " .. ranks)
            else
                table.insert(lines, "- " .. (skill.name or "?") .. ": " .. ranks)
            end
        end
    end
    if #weapons > 0 then table.insert(lines, "Weapon skills: " .. table.concat(weapons, ", ")) end
    return lines
end

local function gearLines(snapshot)
    local lines = {}
    for _, item in ipairs(snapshot.gear or {}) do
        local details = {}
        if item.itemLevel then table.insert(details, "item level " .. item.itemLevel) end
        if item.quality and QUALITY_WORDS[item.quality] then
            table.insert(details, QUALITY_WORDS[item.quality])
        end
        local suffix = #details > 0 and (" (" .. table.concat(details, ", ") .. ")") or ""
        table.insert(lines, "- " .. (item.slot or "?") .. ": " .. (item.name or "?") .. suffix)
    end
    return lines
end

local function spellLines(snapshot)
    local spells = snapshot.spells or {}
    if #spells == 0 then return {} end
    return { table.concat(spells, ", ") }
end

-- The newest MAX_HISTORY_LINES events, oldest of those first.
local function historyLines(history, now)
    local lines = {}
    local first = math.max(1, #history - MAX_HISTORY_LINES + 1)
    for index = first, #history do
        local event = history[index]
        local ago = agoText(event.time, now)
        table.insert(lines, "- " .. (event.text or "?") .. (ago ~= "" and (" (" .. ago .. ")") or ""))
    end
    return lines
end

local function errorLines(snapshot)
    local lines = {}
    for _, message in ipairs(snapshot.errors or {}) do
        table.insert(lines, "- " .. tostring(message))
    end
    return lines
end


-------------------------------------------------------------------------------
-- The public function
-------------------------------------------------------------------------------

-- snapshot: the table CoachLink builds. history: list of events (may be empty).
-- now: Unix time, used for "5 min ago". Returns one string with "\n" line breaks.
function ns.formatSnapshotText(snapshot, history, now)
    local out = {}
    for _, line in ipairs(INTRO) do table.insert(out, line) end

    addSection(out, "== CHARACTER ==", characterLines(snapshot))
    addSection(out, "== LOCATION ==", locationLines(snapshot))
    addSection(out, "== QUESTS (" .. #(snapshot.quests or {}) .. ") ==", questLines(snapshot))
    addSection(out, "== TALENTS ==", talentLines(snapshot))
    addSection(out, "== PROFESSIONS AND SKILLS ==", skillLines(snapshot))
    addSection(out, "== GEAR ==", gearLines(snapshot))
    addSection(out, "== KNOWN SPELLS ==", spellLines(snapshot))
    addSection(out, "== RECENT EVENTS ==", historyLines(history or {}, now))
    addSection(out, "== READ ERRORS (the addon could not read these) ==", errorLines(snapshot))
    return table.concat(out, "\n")
end
