--[[
Test CoachLink outside the game, with a fake ("mock") WoW API.

Run it with LuaJIT (WoW uses Lua 5.1, LuaJIT speaks the same language):

    luajit addon/tests/run_addon_test.lua [output-file]

What it does:
  1. Defines fake versions of every WoW function CoachLink calls, describing a
     made-up level 7 Undead Mage in Brill.
  2. Loads CoachLink.lua, fires game events (login, level up, quest turn-in,
     death) and runs /coach, like a real play session.
  3. Checks the resulting CoachLinkDB table.
  4. Checks the plain-text export and /coach copy (the copy window).
  5. Runs again with the talent API broken, to prove one failing section is
     recorded in snapshot.errors instead of breaking the whole snapshot.
  6. If an output file is given, writes CoachLinkDB there in the same text
     format WoW Forever uses (Windows line endings, no indentation), so the
     Python reader can be tested against real addon output.

It does NOT prove the real game API behaves like these fakes; that is checked
in game (see docs/worklog.md).
]]

-- Same order as in CoachLink.toc.
local ADDON_FILES = { "addon/CoachLink/CoachLinkText.lua", "addon/CoachLink/CoachLink.lua" }
local FAKE_NOW = 1793995200  -- a fixed time, so the output is the same every run

local failures = 0

-- Uses io.stdout instead of print, because the fake game below silences print.
local function check(condition, description)
    if condition then
        io.stdout:write("ok   " .. description .. "\n")
    else
        io.stdout:write("FAIL " .. description .. "\n")
        failures = failures + 1
    end
end


-------------------------------------------------------------------------------
-- The fake game
-------------------------------------------------------------------------------

local eventHandler   -- the OnEvent script CoachLink registers
local registeredEvents = {}

local function installFakeGame()
    CoachLinkDB = nil
    registeredEvents = {}
    SlashCmdList = {}

    print = function() end  -- keep CoachLink's chat messages out of the test output
    time = function() return FAKE_NOW end

    UnitName = function() return "Testchar" end
    GetRealmName = function() return "Testrealm" end
    UnitRace = function() return "Undead", "Scourge" end
    UnitClass = function() return "Mage", "MAGE" end
    UnitLevel = function() return 7 end
    UnitXP = function() return 1530 end
    UnitXPMax = function() return 2690 end
    GetXPExhaustion = function() return 1200 end
    GetMoney = function() return 12345 end           -- 1g 23s 45c
    GetRealZoneText = function() return "Tirisfal Glades" end
    GetSubZoneText = function() return "Brill" end
    GetBindLocation = function() return "Brill" end

    C_Map = {
        GetBestMapForUnit = function() return 1420 end,
        GetPlayerMapPosition = function()
            return { GetXY = function() return 0.6125, 0.5250 end }
        end,
    }
    C_Container = {
        GetContainerNumSlots = function(bag) return bag == 0 and 16 or 6 end,
        GetContainerNumFreeSlots = function() return 3 end,
    }

    local questLog = {
        { title = "Tirisfal Glades", isHeader = true },
        { title = "Fields of Grief", questID = 365, level = 7, isHeader = false },
        { title = "Wanted: Maggot Eye", questID = 398, level = 10, isHeader = false },
    }
    C_QuestLog = {
        GetNumQuestLogEntries = function() return #questLog, 2 end,
        GetInfo = function(index) return questLog[index] end,
        IsComplete = function(questID) return questID == 365 end,
        GetQuestObjectives = function(questID)
            if questID == 365 then
                return { { text = "Tirisfal Pumpkin: 10/10", finished = true } }
            end
            return { { text = "Maggot Eye's Paw: 0/1", finished = false } }
        end,
        GetTitleForQuestID = function() return "The Mindless Ones" end,
    }

    C_SpecializationInfo = {
        GetActiveSpecGroup = function() return 1 end,
        GetCombatConfigIDForSpecGroup = function() return 77 end,
    }
    C_Traits = {
        GetConfigInfo = function() return { treeIDs = { 900 } } end,
        GetTreeCurrencyInfo = function() return { { quantity = 1 } } end,
        GetGroupDisplayInfoByTreeID = function()
            return {
                { groupID = 1, displayName = "Arcane" },
                { groupID = 2, displayName = "Fire" },
                { groupID = 3, displayName = "Frost" },
            }
        end,
        GetGroupCurrencyInfo = function()
            return {
                { traitNodeGroupID = 1, currencyInfos = { { spent = 0 } } },
                { traitNodeGroupID = 3, currencyInfos = { { spent = 2 } } },
            }
        end,
        GetTreeNodes = function() return { 10, 11 } end,
        GetNodeInfo = function(_, nodeID)
            if nodeID == 10 then
                return { activeRank = 2, maxRanks = 5, activeEntry = { entryID = 500 } }
            end
            return { activeRank = 0, maxRanks = 3 }
        end,
        GetEntryInfo = function() return { definitionID = 600 } end,
        GetDefinitionInfo = function() return { spellID = 11071, overrideName = nil } end,
    }
    C_Spell = { GetSpellName = function() return "Frostbite" end }

    -- Shaped like the real game's list (seen 2026-11-07): headers, then their lines.
    -- The real game lists each profession twice, so Tailoring is here twice too.
    local skillLines = {
        { name = "Class Skills", isHeader = true },
        { name = "Frost", isHeader = false, rank = 1, maxRank = 1 },
        { name = "Professions", isHeader = true },
        { name = "Tailoring", isHeader = false, rank = 23, maxRank = 75 },
        { name = "Tailoring", isHeader = false, rank = 23, maxRank = 75 },
        { name = "Weapon Skills", isHeader = true },
        { name = "Staves", isHeader = false, rank = 35, maxRank = 35 },
    }
    C_SkillInfo = {
        GetNumSkillLines = function() return #skillLines end,
        GetSkillLineInfo = function(index) return skillLines[index] end,
    }

    local equipped = { [5] = "item:56", [16] = "item:2132" }
    GetInventoryItemLink = function(_, slot) return equipped[slot] end
    C_Item = {
        GetItemInfo = function(link)
            if link == "item:56" then return "Apprentice's Robe", link, 1 end
            return "Gnarled Staff", link, 2
        end,
        GetDetailedItemLevelInfo = function(link) return link == "item:56" and 5 or 9 end,
    }

    Enum = {
        SpellBookSpellBank = { Player = 0, Pet = 1 },
        SpellBookItemType = { None = 0, Spell = 1, FutureSpell = 2 },
    }
    local spellBook = {
        { name = "Frostbolt", itemType = 1, isPassive = false },
        { name = "Fireball", itemType = 1, isPassive = false },
        { name = "Frost Nova", itemType = 2, isPassive = false },   -- not learned yet
        { name = "Shadow Resistance", itemType = 1, isPassive = true },
    }
    C_SpellBook = {
        GetNumSpellBookSkillLines = function() return 1 end,
        GetSpellBookSkillLineInfo = function()
            return { itemIndexOffset = 0, numSpellBookItems = #spellBook }
        end,
        GetSpellBookItemInfo = function(index) return spellBook[index] end,
    }

    -- Fake frames. Any method CoachLink calls on a frame does nothing, except the
    -- few below that we want to watch. Frames made with CreateFrame are kept in
    -- createdFrames so the tests can look at them.
    strtrim = function(text) return (text:gsub("^%s+", ""):gsub("%s+$", "")) end
    UIParent = {}
    UISpecialFrames = {}
    ChatFontNormal = {}
    createdFrames = {}
    local frameMethods = {
        RegisterEvent = function(_, eventName) registeredEvents[eventName] = true end,
        SetScript = function(self, scriptName, handler)
            if scriptName == "OnEvent" then eventHandler = handler end
            self.scripts[scriptName] = handler
        end,
        SetText = function(self, text) self.text = text end,
        GetText = function(self) return self.text end,
        Show = function(self) self.shown = true end,
        Hide = function(self) self.shown = false end,
        IsShown = function(self) return self.shown end,
        SetFocus = function(self) self.focused = true end,
        HighlightText = function(self) self.highlighted = true end,
        CreateFontString = function() return CreateFrame("FontString") end,
    }
    local frameLook = {
        __index = function(_, methodName)
            return frameMethods[methodName] or function() end
        end,
    }
    CreateFrame = function(frameType, name, parent, template)
        local frame = setmetatable({ type = frameType, name = name, scripts = {} }, frameLook)
        frame.template = template
        table.insert(createdFrames, frame)
        if name then _G[name] = frame end
        return frame
    end
    ReloadUI = function() eventHandler(nil, "PLAYER_LOGOUT") end
end

local function fire(eventName, ...)
    assert(registeredEvents[eventName], "CoachLink does not listen to " .. eventName)
    eventHandler(nil, eventName, ...)
end

-- WoW hands every addon file the addon name and one shared table; do the same.
local function loadAddon()
    local namespace = {}
    for _, file in ipairs(ADDON_FILES) do
        local chunk = assert(loadfile(file))
        chunk("CoachLink", namespace)
    end
    return namespace
end


-------------------------------------------------------------------------------
-- Write a table the way WoW does: CRLF, no indentation, ["key"] = value,
-------------------------------------------------------------------------------

local function sortedKeys(tbl)
    local keys = {}
    for key in pairs(tbl) do
        table.insert(keys, key)
    end
    table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
    return keys
end

-- A string, number or boolean as Lua source text.
local function scalarText(value)
    if type(value) == "string" then
        -- %q quotes and escapes; it writes a newline as "\" + newline, WoW writes "\n".
        local quoted = string.format("%q", value):gsub("\\\n", "\\n")
        return quoted
    end
    return tostring(value)
end

-- Turn a whole table into WoW-style text, one value or brace per line.
local function serialize(name, value)
    local out = { "" }  -- WoW files start with an empty line

    -- Write one value. Tables write their list items first (no key), then
    -- their keyed fields, and call emit again for every nested value.
    local function emit(prefix, val, suffix)
        if type(val) ~= "table" then
            table.insert(out, prefix .. scalarText(val) .. suffix)
            return
        end
        table.insert(out, prefix .. "{")
        local count = #val
        for index = 1, count do
            emit("", val[index], ",")
        end
        for _, key in ipairs(sortedKeys(val)) do
            local isListItem = type(key) == "number" and key >= 1 and key <= count
            if not isListItem then
                local keyText = type(key) == "string" and string.format("[%q]", key)
                    or "[" .. tostring(key) .. "]"
                emit(keyText .. " = ", val[key], ",")
            end
        end
        table.insert(out, "}" .. suffix)
    end
    emit(name .. " = ", value, "")
    return table.concat(out, "\r\n") .. "\r\n"
end


-------------------------------------------------------------------------------
-- Test 1: a normal session
-------------------------------------------------------------------------------

installFakeGame()
local namespace = loadAddon()
fire("PLAYER_ENTERING_WORLD", true, false)
fire("PLAYER_LEVEL_UP", 7)
fire("QUEST_TURNED_IN", 364, 250, 0)
fire("PLAYER_DEAD")
SlashCmdList.COACHLINK("")   -- the player types /coach

local character = CoachLinkDB and CoachLinkDB.characters["Testchar-Testrealm"]
check(CoachLinkDB.formatVersion == 1, "formatVersion is 1")
check(character ~= nil, "character stored under Name-Realm")
local snapshot = character.snapshot
check(snapshot.reason == "coach", "/coach marks the snapshot reason")
check(snapshot.savedAt == FAKE_NOW, "savedAt is the current time")
check(snapshot.level == 7 and snapshot.class == "Mage", "identity read")
check(snapshot.money == 12345 and snapshot.restedXP == 1200, "money and rested XP read")
check(snapshot.zone == "Tirisfal Glades" and snapshot.subZone == "Brill", "zone read")
check(math.abs(snapshot.x - 61.25) < 0.001, "map x converted to 0-100")
check(snapshot.bags.total == 40 and snapshot.bags.free == 15, "bags counted")
check(#snapshot.quests == 2, "quest headers skipped, 2 quests kept")
check(snapshot.quests[1].complete == true, "complete quest marked")
check(snapshot.quests[2].objectives[1].done == false, "objective progress read")
check(snapshot.talents.unspent == 1, "unspent talent points read")
check(#snapshot.talents.trees == 3 and snapshot.talents.trees[3].spent == 2, "points per tree read")
check(snapshot.talents.trees[2].spent == 0, "tree with no currency info counts 0")
check(#snapshot.talents.picked == 1 and snapshot.talents.picked[1].name == "Frostbite",
    "picked talent named")
check(#snapshot.professions == 3, "skill headers skipped, the second Tailoring dropped")
check(snapshot.professions[2].name == "Tailoring" and snapshot.professions[2].category == "Professions",
    "skill line saved with its header as category")
check(snapshot.professions[3].category == "Weapon Skills", "category follows the latest header")
check(#snapshot.gear == 2 and snapshot.gear[1].slot == "Chest", "gear read in slot order")
check(#snapshot.spells == 2, "only learned, active spells listed")
check(#snapshot.errors == 0, "no read errors")
local kinds = {}
for _, event in ipairs(character.history) do
    table.insert(kinds, event.kind)
end
check(table.concat(kinds, ",") == "login,level,quest,death", "history events in order")
check(character.history[4].text == "Died in Brill (level 7)", "death text")

local goodDB = CoachLinkDB


-------------------------------------------------------------------------------
-- Test 2: the plain-text export and /coach copy
-------------------------------------------------------------------------------

local text = namespace.formatSnapshotText(snapshot, character.history, FAKE_NOW + 600)
check(not text:find("|c", 1, true) and not text:find("|r", 1, true), "text has no color codes")
check(#text < 6000, "text is short enough (" .. #text .. " chars)")
for _, fact in ipairs({
    "Testchar, level 7 Undead Mage",
    "XP: 1530 / 2690", "rested XP 1200",
    "Gold: 1g 23s 45c",
    "Now in: Tirisfal Glades, Brill", "Hearthstone set to: Brill",
    "Bags: 15 free of 40",
    "[7] Fields of Grief (DONE", "[ ] Maggot Eye's Paw: 0/1",
    "Unspent talent points: 1", "Frost 2", "Frostbite (2/5)",
    "- Tailoring: 23/75", "Weapon skills: Staves 35/35",
    "Chest: Apprentice's Robe (item level 5, common)",
    "Frostbolt, Fireball",
    "Died in Brill (level 7) (10 min ago)",
}) do
    check(text:find(fact, 1, true) ~= nil, "text mentions: " .. fact)
end
check(not text:find("Frost: 1/1", 1, true), "1/1 skill lines are left out")
check(not text:find("READ ERRORS", 1, true), "no error section when all reads worked")

local dbBefore = serialize("CoachLinkDB", CoachLinkDB)
createdFrames = {}
SlashCmdList.COACHLINK("copy")
local window, editBox = nil, nil
for _, frame in ipairs(createdFrames) do
    if frame.name == "CoachLinkCopyFrame" then window = frame end
    if frame.type == "EditBox" then editBox = frame end
end
check(window ~= nil and window.shown == true, "/coach copy shows the window")
check(editBox ~= nil and editBox.text:find("Testchar, level 7", 1, true) ~= nil,
    "/coach copy fills the edit box")
check(editBox.focused and editBox.highlighted, "edit box is focused and highlighted")
check(UISpecialFrames[1] == "CoachLinkCopyFrame", "Esc closes the window")
check(serialize("CoachLinkDB", CoachLinkDB) == dbBefore, "/coach copy leaves CoachLinkDB alone")
local frameCount = #createdFrames
SlashCmdList.COACHLINK("export")
check(#createdFrames == frameCount and window.shown, "/coach export reuses the same window")

-- Print what a player would paste, if asked: luajit run_addon_test.lua out.lua --show
if arg and arg[2] == "--show" then
    io.stdout:write("\n----- copied text -----\n" .. text .. "\n-----------------------\n\n")
end

-- The chat messages of /coach help and of a window failure.
local chat = {}
print = function(message) table.insert(chat, message) end
SlashCmdList.COACHLINK("help")
check(table.concat(chat, "\n"):find("/coach copy", 1, true) ~= nil, "/coach help mentions copy")
installFakeGame()
print = function(message) table.insert(chat, message) end
loadAddon()
chat = {}
CreateFrame = function() error("no UI today") end   -- after loading, so only the window fails
SlashCmdList.COACHLINK("copy")
check(chat[1] and chat[1]:find("could not open the copy window", 1, true) ~= nil,
    "a window that cannot be built gives a chat message, not an error")

-- After an update with only a /reload, WoW hasn't loaded the new text file yet.
installFakeGame()
chat = {}
print = function(message) table.insert(chat, message) end
local onlyMainFile = {}
local mainChunk = assert(loadfile("addon/CoachLink/CoachLink.lua"))
mainChunk("CoachLink", onlyMainFile)
SlashCmdList.COACHLINK("copy")
check(chat[1] and chat[1]:find("restart the game", 1, true) ~= nil,
    "copy without the text file asks for a game restart")
print = function() end


-------------------------------------------------------------------------------
-- Test 3: one broken game API must not break the rest
-------------------------------------------------------------------------------

installFakeGame()
C_Traits = nil  -- pretend a patch removed the talent API
namespace = loadAddon()
SlashCmdList.COACHLINK("")
local broken = CoachLinkDB.characters["Testchar-Testrealm"].snapshot
check(#broken.errors == 1 and broken.errors[1]:find("^talents: ") ~= nil,
    "broken talent API recorded in errors")
check(broken.level == 7 and #broken.quests == 2, "other sections still saved")

createdFrames = {}
SlashCmdList.COACHLINK("copy")   -- the copy text must still appear, with the error listed
local brokenBox
for _, frame in ipairs(createdFrames) do
    if frame.type == "EditBox" then brokenBox = frame end
end
check(brokenBox ~= nil and brokenBox.text:find("READ ERRORS", 1, true) ~= nil
    and brokenBox.text:find("talents: ", 1, true) ~= nil, "copy text lists the read error")
check(brokenBox.text:find("Testchar, level 7", 1, true) ~= nil, "copy text still has the other facts")


-------------------------------------------------------------------------------
-- Optional: write the good session in WoW's file format
-------------------------------------------------------------------------------

local outputPath = arg and arg[1]
if outputPath then
    local file = assert(io.open(outputPath, "wb"))
    file:write(serialize("CoachLinkDB", goodDB))
    file:close()
    io.stdout:write("wrote " .. outputPath .. "\n")
end

io.stdout:write(failures == 0 and "ALL PASSED\n" or (failures .. " FAILED\n"))
os.exit(failures == 0 and 0 or 1)
