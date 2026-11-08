--[[
Test CoachLink outside the game, with a fake ("mock") WoW API.

Run it with LuaJIT (WoW uses Lua 5.1, LuaJIT speaks the same language):

    luajit addon/tests/run_addon_test.lua [output-file]

What it does:
  1. Defines fake versions of every WoW function CoachLink calls, describing a
     made-up level 7 Undead Mage in Brill, with items in the bags and bank.
  2. Loads CoachLink.lua, fires game events (login, level up, quest turn-in,
     death, opening the bank, mailbox and Tailoring window, /played) and runs
     /coach, like a real play session.
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
    date = os.date
    GetTime = function() return 1000 end  -- seconds since the PC started; buffs end relative to it

    -- Units around the player that a test puts there: unit token -> { guid, name,
    -- level, classification, isPlayer, target ("player" when it attacks you) }.
    enemies = {}
    UnitName = function(unit) return enemies[unit] and enemies[unit].name or "Testchar" end
    GetRealmName = function() return "Testrealm" end
    UnitRace = function() return "Undead", "Scourge" end
    UnitClass = function() return "Mage", "MAGE" end
    UnitLevel = function(unit) return enemies[unit] and enemies[unit].level or 7 end
    UnitFactionGroup = function() return "Horde", "Horde" end
    GetGuildInfo = function() return nil end
    IsResting = function() return true end
    IsInInstance = function() return false, "none" end
    GetInstanceInfo = function() return "Tirisfal Glades" end
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
    -- Health, mana and the character-window stats.
    UnitHealth = function() return 150 end
    UnitHealthMax = function() return 180 end
    UnitPowerType = function() return 0, "MANA" end
    UnitPower = function() return 300 end
    UnitPowerMax = function() return 345 end
    UnitStat = function(_, index)
        local values = { 20, 22, 23, 31, 33 }
        return values[index], values[index]
    end
    SPELL_STAT4_NAME = "Intellect"   -- the game's own name for attribute 4
    UnitArmor = function() return 40, 45 end
    UnitResistance = function(_, index) return 0, index == 5 and 10 or 0 end  -- Shadow 10
    GetSpellBonusDamage = function() return 0 end
    GetSpellBonusHealing = function() return 0 end
    GetSpellCritChance = function() return 1.6 end
    GetCritChance = function() return 5 end
    GetDodgeChance = function() return 4.3 end
    UnitAttackPower = function() return 10, 0, 0 end
    GetManaRegen = function() return 2.5, 0 end

    -- Items, by link. The real game's links are longer, but contain "item:<id>".
    local items = {
        ["item:56"] = { "Apprentice's Robe", 1, 1, "Armor", "Cloth", "INVTYPE_CHEST", 1 },
        ["item:2132"] = { "Gnarled Staff", 2, 1, "Weapon", "Staves", "INVTYPE_2HWEAPON", 25 },
        ["item:2589"] = { "Linen Cloth", 1, 0, "Tradeskill", "Cloth", "", 13 },
        ["item:3300"] = { "Rabbit's Foot", 0, 0, "Junk", "Junk", "", 4 },
        ["item:6948"] = { "Hearthstone", 1, 0, "Miscellaneous", "Other", "", 0 },
        ["item:4689"] = { "Frayed Cloak", 2, 5, "Armor", "Cloth", "INVTYPE_CLOAK", 30 },
        ["item:117"] = { "Tough Jerky", 1, 1, "Consumable", "Food & Drink", "INVTYPE_NON_EQUIP_IGNORE", 1 },
    }
    INVTYPE_CHEST, INVTYPE_2HWEAPON, INVTYPE_CLOAK = "Chest", "Two-Hand", "Back"
    ITEM_MOD_STAMINA_SHORT, ITEM_MOD_INTELLECT_SHORT = "Stamina", "Intellect"
    local itemStats = {
        ["item:2132"] = { ITEM_MOD_STAMINA_SHORT = 2, ITEM_MOD_INTELLECT_SHORT = 1 },
        ["item:4689"] = { ITEM_MOD_STAMINA_SHORT = 1 },
    }

    -- What is in each container: bag number -> slot -> { link, count, bound, noValue }.
    bankContents = {
        [6] = { [1] = { "item:117", 4 } },
    }
    local containers = {
        [0] = {
            [1] = { "item:2589", 5 }, [2] = { "item:2589", 3 },
            [3] = { "item:3300", 2 }, [4] = { "item:6948", 1, true, true },
        },
        [1] = { [1] = { "item:4689", 1, true } },
    }
    local bagNames = { [0] = "Backpack", [1] = "Small Brown Pouch", [6] = "Bank Tab 1" }
    C_Container = {
        GetContainerNumSlots = function(bag)
            if bag == 0 then return 16 end
            if bag >= 1 and bag <= 4 then return 6 end
            if bag == 6 then return 28 end
            return 0
        end,
        GetContainerNumFreeSlots = function() return 3 end,
        GetBagName = function(bag) return bagNames[bag] end,
        GetContainerItemInfo = function(bag, slot)
            local contents = (bag >= 6) and bankContents[bag] or containers[bag]
            local stack = contents and contents[slot]
            if not stack then return nil end
            return { hyperlink = stack[1], stackCount = stack[2], isBound = stack[3] == true,
                hasNoValue = stack[4] == true, quality = items[stack[1]][2] }
        end,
    }
    C_Bank = {
        FetchPurchasedBankTabData = function(bankType)
            if bankType == 0 then return { { ID = 6, name = "Bank Tab 1", bankType = 0 } } end
            return {}
        end,
    }

    -- The mailbox: one letter from the auction house with gold and an item.
    GetInboxNumItems = function() return 1, 1 end
    GetInboxHeaderInfo = function()
        return nil, nil, "Auction House", "Auction successful: Linen Cloth", 1500, 0, 29.6, 1
    end
    GetInboxItem = function(_, attachment)
        if attachment == 1 then return "Copper Ore", 2770, nil, 4, 1, true end
        return nil
    end

    -- The Tailoring window: two learned recipes and one not learned yet.
    local recipes = {
        { name = "Bolt of Linen Cloth", learned = true, relativeDifficulty = 0, numSkillUps = 1 },
        { name = "Linen Cloak", learned = true, relativeDifficulty = 1, numSkillUps = 1 },
        { name = "Brown Linen Robe", learned = false, relativeDifficulty = 0 },
    }
    C_TradeSkillUI = {
        IsTradeSkillLinked = function() return false end,
        GetBaseProfessionInfo = function()
            return { professionName = "Tailoring", skillLevel = 23, maxSkillLevel = 75 }
        end,
        GetAllRecipeIDs = function() return { 1, 2, 3 } end,
        GetRecipeInfo = function(recipeID) return recipes[recipeID] end,
    }

    local questLog = {
        { title = "Tirisfal Glades", isHeader = true },
        { title = "Fields of Grief", questID = 365, level = 7, isHeader = false },
        { title = "Wanted: Maggot Eye", questID = 398, level = 10, isHeader = false, suggestedGroup = 3 },
        { title = "Hidden bookkeeping", questID = 999, level = 1, isHeader = false, isHidden = true },
    }
    GetQuestLogQuestText = function(index)
        if index == 2 then
            return "The fields need tending...", "Bring 10 Tirisfal Pumpkins to Farmer Solliden in Brill."
        end
        return "", ""
    end
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
        IsFailed = function() return false end,
        GetAllCompletedQuestIDs = function() return { 363, 364, 376 } end,
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
        -- Tree 900 is the talent tree, 1188 the Legacy "Adventure" tree.
        GetTreeNodes = function(treeID)
            if treeID == 1188 then return { 20 } end
            return { 10, 11 }
        end,
        GetNodeInfo = function(_, nodeID)
            if nodeID == 10 then
                return { activeRank = 2, maxRanks = 5, activeEntry = { entryID = 500 } }
            end
            if nodeID == 20 then
                return { activeRank = 1, maxRanks = 1, activeEntry = { entryID = 700 } }
            end
            return { activeRank = 0, maxRanks = 3 }
        end,
        GetEntryInfo = function(_, entryID) return { definitionID = entryID + 100 } end,
        GetDefinitionInfo = function(definitionID)
            if definitionID == 800 then return { spellID = 1, overrideName = "Quick Learner" } end
            return { spellID = 11071, overrideName = nil }
        end,
        GetConfigIDByTreeID = function(treeID) return treeID == 1188 and 88 or nil end,
    }
    local spellNames = { [116] = "Frostbolt", [133] = "Fireball", [11071] = "Frostbite" }
    C_Spell = { GetSpellName = function(spellID) return spellNames[spellID] end }

    -- Forever's Legacy system and the class challenges (achievements).
    Constants = { LegacyConsts = {
        LEGACY_REWARD_TRACK_FACTION_ID = 2802, LEGACY_TREE_PROFESSIONS_ID = 1187,
        LEGACY_TREE_ADVENTURE_ID = 1188, LEGACY_TREE_PROGRESSION_ID = 1189,
        LEGACY_DEFAULT_CATEGORY_MAGE = 15579,
    } }
    C_MajorFactions = { GetCurrentRenownLevel = function() return 2 end }
    GetCategoryNumAchievements = function(categoryID) return categoryID == 15579 and 2 or 0 end
    GetAchievementInfo = function(_, index)
        if index == 1 then
            return 1, "Untouchable", 10, false, nil, nil, nil, "Reach level 25 without dying."
        end
        return 2, "Arcane Student", 10, true, 7, 11, 26, "Learn 5 Arcane spells."
    end
    GetTotalAchievementPoints = function() return 10 end

    -- Reputation: a header, one faction, and a header the player collapsed.
    local factions = {
        { name = "Horde", isHeader = true },
        { name = "Undercity", reaction = 5, currentStanding = 3500,
            currentReactionThreshold = 3000, nextReactionThreshold = 9000 },
        { name = "Other", isHeader = true, isCollapsed = true },
    }
    FACTION_STANDING_LABEL5 = "Friendly"
    C_Reputation = {
        GetNumFactions = function() return #factions end,
        GetFactionDataByIndex = function(index) return factions[index] end,
    }
    C_CurrencyInfo = {
        GetCurrencyListSize = function() return 2 end,
        GetCurrencyListInfo = function(index)
            if index == 1 then return { name = "Miscellaneous", isHeader = true } end
            return { name = "Legacy Token", quantity = 3 }
        end,
    }

    -- Buffs: Arcane Intellect with 25 minutes left, and a campfire buff with no end.
    C_UnitAuras = {
        GetAuraDataByIndex = function(_, index, filter)
            if filter ~= "HELPFUL" then return nil end
            if index == 1 then return { name = "Arcane Intellect", expirationTime = 2500, applications = 0 } end
            if index == 2 then return { name = "Cozy Fire", expirationTime = 0 } end
            return nil
        end,
    }

    -- Action bars: two spells and the Hearthstone on the main bar, a macro on slot 61.
    local actions = { [1] = { "spell", 116 }, [2] = { "spell", 133 }, [12] = { "item", 6948 },
        [61] = { "macro", 1 } }
    GetActionInfo = function(slot)
        local action = actions[slot]
        if action then return action[1], action[2] end
        return nil
    end
    GetActionText = function(slot) return slot == 61 and "Sell Grays" or nil end

    IsInGroup = function() return false end
    IsInRaid = function() return false end
    GetNumGroupMembers = function() return 0 end
    UnitExists = function(unit) return enemies[unit] ~= nil end
    UnitGUID = function(unit) return enemies[unit] and enemies[unit].guid end
    UnitCanAttack = function(_, unit) return enemies[unit] ~= nil end
    UnitClassification = function(unit) return enemies[unit] and enemies[unit].classification or "normal" end
    UnitIsPlayer = function(unit) return enemies[unit] and enemies[unit].isPlayer == true end
    playerIsDead = false
    UnitIsDeadOrGhost = function(unit) return unit == "player" and playerIsDead end
    -- "nameplate1target" is "the unit nameplate1 is attacking".
    UnitIsUnit = function(unit, other)
        local attacker = enemies[unit:match("^(.-)target$") or ""]
        return other == "player" and attacker ~= nil and attacker.target == "player"
    end
    C_MountJournal = {
        GetMountIDs = function() return { 1, 2 } end,
        GetMountInfoByID = function(mountID)
            local collected = mountID == 1
            return mountID == 1 and "Skeletal Horse" or "Red Skeletal Horse",
                nil, nil, nil, nil, nil, nil, nil, nil, nil, collected
        end,
    }


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
    GetInventoryItemDurability = function(slot)
        if slot == 5 then return 30, 35 end
        return 50, 60
    end
    C_Item = {
        -- Same order as the real C_Item.GetItemInfo: name, link, quality, level,
        -- required level, type, sub-type, stack size, equip slot, icon, sell price.
        GetItemInfo = function(link)
            local item = items[link]
            return item[1], link, item[2], 1, item[3], item[4], item[5], 20, item[6], 0, item[7]
        end,
        GetDetailedItemLevelInfo = function(link) return link == "item:56" and 5 or 9 end,
        GetItemStats = function(link) return itemStats[link] or {} end,
        GetItemNameByID = function(itemID) return itemID == 6948 and "Hearthstone" or nil end,
    }

    Enum = {
        SpellBookSpellBank = { Player = 0, Pet = 1 },
        SpellBookItemType = { None = 0, Spell = 1, FutureSpell = 2 },
        BankType = { Character = 0, Account = 2 },
    }
    local spellBook = {
        { name = "Frostbolt", subName = "Rank 1", itemType = 1, isPassive = false },
        { name = "Fireball", itemType = 1, isPassive = false },
        { name = "Frost Nova", itemType = 2, isPassive = false },   -- not learned yet
        { name = "Shadow Resistance", itemType = 1, isPassive = true },
    }
    C_SpellBook = {
        GetNumSpellBookSkillLines = function() return 1 end,
        GetSpellBookSkillLineInfo = function()
            return { name = "Frost", itemIndexOffset = 0, numSpellBookItems = #spellBook }
        end,
        GetSpellBookItemInfo = function(index) return spellBook[index] end,
    }

    -- Fake frames. Any method CoachLink calls on a frame does nothing, except the
    -- few below that we want to watch. Frames made with CreateFrame are kept in
    -- createdFrames so the tests can look at them.
    strtrim = function(text) return (text:gsub("^%s+", ""):gsub("%s+$", "")) end
    InCombatLockdown = function() return false end
    CoachLinkAdvice = nil   -- the CoachLink_Advice addon (written by wow-coach) is not installed
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
    -- Logging out from the game menu or with /logout calls Logout(); /quit calls Quit().
    -- hooksecurefunc runs a function right after one of the game's own.
    Logout = function() end
    Quit = function() end
    -- Timers: C_Timer.After only queues the function; runTimers() runs the queue,
    -- like the game does a moment later.
    pendingTimers = {}
    tickers = {}
    C_Timer = {
        After = function(_, callback) table.insert(pendingTimers, callback) end,
        -- A repeating timer; tests run its callback by hand (tickers[1].callback()).
        NewTicker = function(_, callback)
            local ticker = { callback = callback, cancelled = false }
            ticker.Cancel = function(self) self.cancelled = true end
            table.insert(tickers, ticker)
            return ticker
        end,
    }
    -- /played: the game answers with TIME_PLAYED_MSG, which every chat window shows.
    playedRequests = 0
    RequestTimePlayed = function() playedRequests = playedRequests + 1 end
    Constants.ChatFrameConstants = { MaxChatWindows = 2 }
    local chatEvents = { TIME_PLAYED_MSG = true }
    ChatFrame1 = {
        IsEventRegistered = function(_, eventName) return chatEvents[eventName] == true end,
        RegisterEvent = function(_, eventName) chatEvents[eventName] = true end,
        UnregisterEvent = function(_, eventName) chatEvents[eventName] = nil end,
    }
    -- Getting items: the loot chat line, the quest reward window, vendors and mail.
    LOOT_ITEM_SELF = "You receive loot: %s."
    LOOT_ITEM_SELF_MULTIPLE = "You receive loot: %sx%d."
    GetTitleText = function() return "Fields of Grief" end
    GetNumQuestChoices = function() return 2 end
    GetNumQuestRewards = function() return 1 end
    local questItems = { choice = { "item:4689", "item:56" }, reward = { "item:117" } }
    GetQuestItemLink = function(kind, index) return questItems[kind] and questItems[kind][index] end
    GetQuestReward = function() end
    GetMerchantItemLink = function(index) return index == 3 and "item:4689" or "item:117" end
    C_MerchantFrame = { GetItemInfo = function() return { price = 250, stackCount = 1 } end }
    BuyMerchantItem = function() end
    TakeInboxItem = function() end
    AutoLootMailItem = function() end
    hooksecurefunc = function(name, hook)
        local original = _G[name]
        _G[name] = function(...)
            original(...)
            hook(...)
        end
    end
end

-- What the game looks like at PLAYER_LOGOUT on a real logout (seen 2026-11-07 and
-- 2026-11-08): the character is already unloaded, so most functions return 0 or nil.
local function unloadCharacter()
    UnitLevel = function() return 6 end
    UnitXP = function() return 0 end
    UnitXPMax = function() return 0 end
    GetMoney = function() return 0 end
    UnitHealthMax = function() return 0 end
    C_Container.GetContainerNumSlots = function() return 0 end
    C_Container.GetContainerNumFreeSlots = function() return 0 end
    C_SpellBook.GetSpellBookSkillLineInfo = function() return nil end
end

-- Run every queued timer (timers queued while running wait for the next call).
local function runTimers()
    local due = pendingTimers
    pendingTimers = {}
    for _, callback in ipairs(due) do
        callback()
    end
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
fire("PLAYER_LEVEL_UP", 8)   -- the game still says level 7 while this event runs
fire("QUEST_TURNED_IN", 364, 250, 0)
fire("PLAYER_DEAD")
fire("BANKFRAME_OPENED")       -- the player visits the bank...
fire("BANKFRAME_CLOSED")
fire("MAIL_INBOX_UPDATE")      -- ...a mailbox...
fire("TRADE_SKILL_SHOW")       -- ...opens Tailoring...
fire("TIME_PLAYED_MSG", 7200, 1800)   -- ...and types /played
bankContents[6][2] = { "item:2589", 1 }   -- changed after the bank was closed:
fire("BAG_UPDATE_DELAYED")                -- not seen, so not saved
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
check(#snapshot.spellBook == 3 and snapshot.spellBook[1].rank == "Rank 1"
    and snapshot.spellBook[1].tab == "Frost", "spellbook has tabs and ranks")
check(snapshot.spellBook[3].passive == true, "spellbook keeps passives, marked")
check(#snapshot.errors == 0, "no read errors: " .. table.concat(snapshot.errors, "; "))

-- Identity, place and stats
check(snapshot.faction == "Horde" and snapshot.classFile == "MAGE", "faction and class file read")
check(snapshot.guild == nil, "no guild means no guild table")
check(snapshot.resting == true, "resting read")
check(snapshot.instance == nil, "outside an instance there is no instance table")
local stats = snapshot.stats
check(stats.health == 150 and stats.healthMax == 180 and stats.powerType == "MANA", "health and mana read")
check(stats.attributes[4].name == "Intellect" and stats.attributes[4].value == 31, "attributes read")
check(stats.attributes[1].name == "Strength", "attribute name falls back to English")
check(stats.armor == 45 and stats.resistances[5].school == "Shadow"
    and stats.resistances[5].value == 10, "armor and resistances read")
check(stats.spellCrit == 1.6 and stats.attackPower == 10 and stats.manaRegen == 2.5, "other stats read")

-- Bags, gear
local backpack = snapshot.bags.containers[1]
check(#snapshot.bags.containers == 5, "every bag listed")
check(backpack.name == "Backpack" and backpack.slots == 16 and backpack.free == 12,
    "backpack named, empty slots counted")
check(backpack.items[1].name == "Linen Cloth" and backpack.items[1].count == 5
    and backpack.items[1].itemID == 2589 and backpack.items[1].sellPrice == 13, "bag item details read")
check(backpack.items[4].bound == true and backpack.items[4].noValue == true, "bound and no-value flags read")
check(backpack.items[1].equipSlot == nil, "cloth is not something you wear")
local cloak = snapshot.bags.containers[2].items[1]
check(cloak.equipSlot == "Back" and cloak.stats[1] == "+1 Stamina" and cloak.requiredLevel == 5,
    "a cloak in the bag has its slot, stats and required level")
check(snapshot.gear[1].durability == 30 and snapshot.gear[1].durabilityMax == 35, "gear durability read")
check(snapshot.gear[2].stats[1] == "+1 Intellect" and snapshot.gear[2].stats[2] == "+2 Stamina",
    "gear stats read, sorted")

-- Quests
check(snapshot.quests[1].zone == "Tirisfal Glades", "quest keeps its zone header")
check(snapshot.quests[1].objectivesText == "Bring 10 Tirisfal Pumpkins to Farmer Solliden in Brill.",
    "quest objectives text read")
check(snapshot.quests[2].suggestedGroup == 3, "group quest size read")
check(snapshot.completedQuests == 3, "completed quest count read")

-- Reputation, currencies, Legacy, buffs, action bars, collections
check(#snapshot.reputations == 2 and snapshot.reputations[1].name == "Undercity"
    and snapshot.reputations[1].standing == "Friendly" and snapshot.reputations[1].value == 500
    and snapshot.reputations[1].max == 6000 and snapshot.reputations[1].group == "Horde",
    "reputation read with standing and progress")
check(snapshot.reputations[2].collapsed == true, "a collapsed reputation header is marked")
check(#snapshot.currencies == 1 and snapshot.currencies[1].quantity == 3, "currencies read, headers skipped")
local legacy = snapshot.legacy
check(legacy.renown == 2 and legacy.points == 1, "Legacy level and points read")
check(#legacy.perks == 1 and legacy.perks[1].name == "Quick Learner"
    and legacy.perks[1].tree == "Adventure", "Legacy perk read with its tree")
check(#legacy.challenges == 2 and legacy.challenges[2].done == true
    and legacy.challenges[1].description == "Reach level 25 without dying.", "class challenges read")
check(#snapshot.auras == 2 and snapshot.auras[1].seconds == 1500 and snapshot.auras[2].seconds == nil,
    "buffs read with time left")
check(#snapshot.actionBars == 4 and snapshot.actionBars[1].name == "Frostbolt"
    and snapshot.actionBars[3].name == "Hearthstone" and snapshot.actionBars[4].name == "Sell Grays",
    "action bars read: spells, items and macros")
check(snapshot.group == nil and snapshot.pet == nil, "no group and no pet means no tables")
check(snapshot.achievementPoints == 10 and #snapshot.mounts == 1
    and snapshot.mounts[1] == "Skeletal Horse", "achievement points and owned mounts read")

-- Windows: bank, mail, recipes, /played
check(snapshot.bank and snapshot.bank.seenAt == FAKE_NOW, "bank remembered with the time")
check(#snapshot.bank.containers == 1 and snapshot.bank.containers[1].name == "Bank Tab 1"
    and snapshot.bank.containers[1].items[1].name == "Tough Jerky", "bank items read")
check(#snapshot.bank.containers[1].items == 1, "a change after the bank closed is not seen")
check(snapshot.mail.letters[1].sender == "Auction House" and snapshot.mail.letters[1].money == 1500
    and snapshot.mail.letters[1].items[1].name == "Copper Ore", "mail read with gold and items")
check(snapshot.recipes[1].profession == "Tailoring" and #snapshot.recipes[1].recipes == 2
    and snapshot.recipes[1].recipes[1].color == "orange", "learned recipes read with their color")
check(snapshot.timePlayed.total == 7200 and snapshot.timePlayed.thisLevel == 1800, "/played remembered")
local kinds = {}
for _, event in ipairs(character.history) do
    table.insert(kinds, event.kind)
end
check(table.concat(kinds, ",") == "login,level,quest,death", "history events in order")
check(character.history[4].text == "Died in Brill (level 7)", "death text")
check(character.history[2].text == "Reached level 8" and character.history[2].level == 8,
    "a level-up event stores the new level, not the old one")
check(#character.progress == 1, "the snapshot added one progress point")
local firstPoint = character.progress[1]
check(firstPoint.time == FAKE_NOW and firstPoint.reason == "coach", "progress point has time and reason")
check(firstPoint.level == 7 and firstPoint.xp == 1530 and firstPoint.xpMax == 2690,
    "progress point has level and XP")
check(firstPoint.money == 12345 and firstPoint.zone == "Tirisfal Glades"
    and firstPoint.subZone == "Brill", "progress point has gold and place")
check(firstPoint.questsDone == 1, "progress point counts complete quests")

local goodDB = CoachLinkDB


-------------------------------------------------------------------------------
-- Test 2: the plain-text export and /coach copy
-------------------------------------------------------------------------------

local text = namespace.formatSnapshotText(snapshot, character.history, FAKE_NOW + 600)
check(not text:find("|c", 1, true) and not text:find("|r", 1, true), "text has no color codes")
check(#text < 20000, "text is not huge (" .. #text .. " chars)")
check(text:find("^World of Warcraft: Forever character sheet") ~= nil, "text starts with a plain title")
check(not text:find("coach", 1, true) and not text:find("Please", 1, true),
    "text has no instructions for the AI, only data")
for _, fact in ipairs({
    "Testchar, level 7 Undead Mage", "Faction: Horde",
    "XP: 1530 / 2690", "rested XP 1200", "1160 to the next level", "Resting: yes",
    "Gold: 1g 23s 45c", "Time played: 2 h 0 min (this level 30 min",
    "Now in: Tirisfal Glades, Brill (map coordinates 61.3, 52.5)", "Hearthstone set to: Brill",
    "Health: 150 / 180", "Mana: 300 / 345", "Intellect 31", "Armor: 45", "Resistances: Shadow 10",
    "Spell damage bonus: 0 (all schools)", "Spell crit 1.6%", "dodge 4.3%",
    "Mana regen per 5 s: 12.5",
    "- Arcane Intellect (buff, 25 min left)", "- Cozy Fire (buff)",
    "[7] Fields of Grief (quest 365; DONE, ready to turn in; Tirisfal Glades)",
    "Goal: Bring 10 Tirisfal Pumpkins to Farmer Solliden in Brill.",
    "[ ] Maggot Eye's Paw: 0/1", "group quest for 3", "Quests completed so far (all time): 3",
    "Unspent talent points: 1", "Frost 2", "Frostbite (2/5)",
    "- Tailoring: 23/75", "Weapon Skills: Staves 35/35", "Class Skills: Frost",
    "Tailoring 23/75, 2 recipes", "- Bolt of Linen Cloth (orange)",
    "Chest: Apprentice's Robe (item level 5, common, durability 30/35)",
    "Main hand: Gnarled Staff (item level 9, uncommon, +1 Intellect, +2 Stamina",
    "15 free of 40 slots", "Backpack 16 slots (12 free)",
    "- Linen Cloth x8 (common, Tradeskill / Cloth, sells for 13c each)",
    "- Rabbit's Foot x2", "Gray (junk) items sell for 8c in total",
    "Hearthstone (common, Miscellaneous / Other, vendors won't buy it, soulbound)",
    "Frayed Cloak (item level 9, uncommon, Back, needs level 5, +1 Stamina",
    "Bank Tab 1 28 slots (27 free)", "- Tough Jerky x4",
    "- Auction successful: Linen Cloth (from Auction House, 15s attached, items: Copper Ore x4, 29 days left)",
    "Frost: Frostbolt (Rank 1), Fireball", "Passive: Shadow Resistance",
    "Main bar: 1 Frostbolt, 2 Fireball, 12 Hearthstone", "Slots 61-72: 1 Sell Grays",
    "- Undercity: Friendly 500/6000", "- Other: collapsed in your reputation window",
    "- Legacy Token: 3",
    "reward track level 2, 1 Legacy points to spend", "Quick Learner (Adventure, 1/1)",
    "- [ ] Untouchable: Reach level 25 without dying.", "- [x] Arcane Student",
    "Skeletal Horse", "Achievement points: 10",
    "Died in Brill (level 7) (10 min ago)",
}) do
    check(text:find(fact, 1, true) ~= nil, "text mentions: " .. fact)
end
check(not text:find("Red Skeletal Horse", 1, true), "mounts you don't own are left out")
check(not text:find("Brown Linen Robe", 1, true), "recipes you haven't learned are left out")
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
-- Talents and the Legacy perks both use the trait API, so both are listed.
check(#broken.errors == 2 and broken.errors[1]:find("^talents: ") ~= nil
    and broken.errors[2]:find("^legacy: ") ~= nil, "broken talent API recorded in errors")
check(broken.legacy and broken.legacy.renown == 2, "a section that broke halfway keeps what it read")
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

-- In some places the game hands addons "secret" values that can't be turned into text.
-- The fake game marks one place name and one old event as secret.
installFakeGame()
loadAddon()
local SECRET = "SECRET-VALUE"
issecretvalue = function(value) return value == SECRET end
GetSubZoneText = function() return SECRET end
fire("PLAYER_ENTERING_WORLD", true, false)
SlashCmdList.COACHLINK("")  -- save once, so the character has a saved entry
local savedEntry = CoachLinkDB.characters["Testchar-Testrealm"]
check(savedEntry.snapshot.subZone == "(hidden by the game)", "a hidden value is saved as a note")
savedEntry.history = savedEntry.history or {}
table.insert(savedEntry.history, { time = 1, kind = "death", text = SECRET })
createdFrames = {}
SlashCmdList.COACHLINK("copy")
local secretBox
for _, frame in ipairs(createdFrames) do
    if frame.type == "EditBox" then secretBox = frame end
end
check(secretBox ~= nil and secretBox.text:find("(hidden by the game)", 1, true) ~= nil,
    "/coach copy shows hidden values as a note instead of failing")
check(secretBox.text:find(SECRET, 1, true) == nil, "no secret value reaches the copy text")
issecretvalue = nil


-- A game version without one of our events must still load the addon.
installFakeGame()
local realCreateFrame = CreateFrame
CreateFrame = function(...)
    local frame = realCreateFrame(...)
    frame.RegisterEvent = function(_, eventName)
        if eventName == "TIME_PLAYED_MSG" then error("unknown event") end
        registeredEvents[eventName] = true
    end
    return frame
end
loadAddon()
SlashCmdList.COACHLINK("")
check(CoachLinkDB.characters["Testchar-Testrealm"].snapshot.level == 7,
    "an unknown event name does not stop the addon from loading")
check(registeredEvents.PLAYER_LOGOUT == true, "the other events are still registered")


-------------------------------------------------------------------------------
-- Test 4: the progress log
-------------------------------------------------------------------------------

installFakeGame()
loadAddon()
local now = FAKE_NOW
time = function() return now end
local function progressList() return CoachLinkDB.characters["Testchar-Testrealm"].progress end

SlashCmdList.COACHLINK("")
now = FAKE_NOW + 30
SlashCmdList.COACHLINK("")   -- nothing changed, 30 s later: a quick reload
check(#progressList() == 1, "same state within 60 s adds no new point")

now = FAKE_NOW + 120
SlashCmdList.COACHLINK("")   -- nothing changed, but 2 minutes later
check(#progressList() == 2, "same state after 60 s adds a point")

now = FAKE_NOW + 130
UnitXP = function() return 1600 end
SlashCmdList.COACHLINK("")   -- XP changed, only 10 s later
check(#progressList() == 3 and progressList()[3].xp == 1600, "a changed value adds a point at once")

-- The cap: 600 snapshots with growing gold keep only the newest 500.
for step = 1, 600 do
    now = FAKE_NOW + 1000 + step
    GetMoney = function() return 1000000 + step end
    SlashCmdList.COACHLINK("")
end
check(#progressList() == 500, "progress log is capped at 500 points")
check(progressList()[500].money == 1000600, "the newest point is kept")
check(progressList()[1].money == 1000101, "the oldest points are dropped")

-- A broken reader still gives a point with what is known.
installFakeGame()
C_QuestLog = nil
loadAddon()
SlashCmdList.COACHLINK("")
local partial = CoachLinkDB.characters["Testchar-Testrealm"].progress
check(#partial == 1 and partial[1].level == 7 and partial[1].zone == "Tirisfal Glades",
    "a broken quest reader still gives a progress point")
check(partial[1].questsDone == nil, "unknown quests are nil, not zero")


-------------------------------------------------------------------------------
-- Test 5: play time without typing /played
-------------------------------------------------------------------------------

installFakeGame()
loadAddon()
now = FAKE_NOW
time = function() return now end
fire("PLAYER_ENTERING_WORLD", true, false)   -- logging in
check(playedRequests == 0, "play time is not asked for during the loading screen")
runTimers()
check(playedRequests == 1, "play time is asked for a moment after logging in")
check(not ChatFrame1:IsEventRegistered("TIME_PLAYED_MSG"), "the chat window won't show the answer")
fire("TIME_PLAYED_MSG", 7200, 1800)
runTimers()
check(ChatFrame1:IsEventRegistered("TIME_PLAYED_MSG"), "after the answer, /played shows in chat again")

now = FAKE_NOW + 600                         -- 10 minutes of play later
SlashCmdList.COACHLINK("")
local played = CoachLinkDB.characters["Testchar-Testrealm"].snapshot.timePlayed
check(played.total == 7800 and played.thisLevel == 2400 and played.seenAt == FAKE_NOW + 600,
    "play time from this session is moved forward to the save time")

loadAddon()                                  -- after the reload
fire("PLAYER_ENTERING_WORLD", false, true)
runTimers()
check(playedRequests == 2, "play time is asked for again after a reload")
fire("PLAYER_ENTERING_WORLD", false, false)  -- a dungeon portal's loading screen
runTimers()
check(playedRequests == 2, "a loading screen inside the game does not ask again")
fire("TIME_PLAYED_MSG", 7800, 2400)
now = FAKE_NOW + 900
fire("PLAYER_LEVEL_UP", 8)                   -- 5 minutes later: level 8
runTimers()
check(playedRequests == 3, "a level-up asks again, since the time at this level restarts")
now = FAKE_NOW + 960
SlashCmdList.COACHLINK("")
played = CoachLinkDB.characters["Testchar-Testrealm"].snapshot.timePlayed
check(played.total == 8160 and played.thisLevel == 60, "after a level-up the level time restarts at 0")

-- No answer at all: the chat window must not stay quiet forever.
installFakeGame()
loadAddon()
fire("PLAYER_ENTERING_WORLD", true, false)
runTimers()                                  -- asks
runTimers()                                  -- the wait for the answer runs out
check(ChatFrame1:IsEventRegistered("TIME_PLAYED_MSG"), "without an answer, chat shows /played again")
-- The player types /played themselves: the answer is saved and shows in chat as usual.
fire("TIME_PLAYED_MSG", 100, 50)
check(ChatFrame1:IsEventRegistered("TIME_PLAYED_MSG"), "the player's own /played is not hidden")


-------------------------------------------------------------------------------
-- Test 6: why the character died
-------------------------------------------------------------------------------

installFakeGame()
loadAddon()
local clock = 1000
GetTime = function() return clock end
local function lastDeath()
    local history = CoachLinkDB.characters["Testchar-Testrealm"].history
    return history[#history]
end
enemies = {
    nameplate1 = { guid = "Creature-1", name = "Scarlet Warrior", level = 9,
        classification = "elite", target = "player" },
    nameplate2 = { guid = "Creature-2", name = "Scarlet Friar", level = 8,
        classification = "normal", target = "player" },
    nameplate3 = { guid = "Creature-3", name = "Duskbat", level = 5, target = "player" },
    nameplate4 = { guid = "Creature-4", name = "Rotting Ancestor", level = 6, target = "Farmer" },
}
enemies.target = enemies.nameplate1      -- the player targets the warrior
fire("PLAYER_REGEN_DISABLED")            -- combat starts: everyone attacking is noted
check(#tickers == 1, "in combat the addon keeps looking for attackers every second")
enemies.nameplate3 = nil                 -- the bat is killed...
clock = 1015                             -- ...and 15 s later the player dies
tickers[1].callback()
fire("PLAYER_DEAD")
local death = lastDeath()
check(death.kind == "death" and #death.attackers == 2, "a death lists the enemies attacking in the last 10 s")
check(death.attackers[1].name == "Scarlet Warrior" and death.attackers[1].level == 9
    and death.attackers[1].classification == "elite", "attackers have their level and elite mark")
check(death.text == "Died in Brill (level 7). Attacked by 2 enemies: Scarlet Warrior (level 9, elite), "
    .. "Scarlet Friar (level 8).", "the death text names the attackers: " .. death.text)
fire("PLAYER_REGEN_ENABLED")
check(tickers[1].cancelled, "out of combat the addon stops looking")

-- The game's death recap, when it has one, names the killing blow.
C_DeathRecap = {
    HasRecapEvents = function() return true end,
    GetRecapEvents = function()
        return {
            { event = "SWING_DAMAGE", sourceName = "Scarlet Warrior", amount = 45, timestamp = FAKE_NOW },
            { event = "SPELL_DAMAGE", spellName = "Holy Smite", sourceName = "Scarlet Friar",
                amount = 20, timestamp = FAKE_NOW - 2 },
        }
    end,
}
fire("PLAYER_DEAD")
runTimers()                              -- the recap is read a moment after dying
death = lastDeath()
check(death.killer and death.killer.name == "Scarlet Warrior" and death.killer.spell == "melee"
    and death.killer.amount == 45, "the killing blow comes from the death recap")
check(death.text:find("Killing blow: Scarlet Warrior (melee, 45 damage).", 1, true) ~= nil,
    "the death text names the killing blow: " .. death.text)

-- Dying soon after coming back to life (a "death loop").
time = function() return FAKE_NOW + 100 end
playerIsDead = true
fire("PLAYER_ALIVE")                     -- released the spirit: still a ghost, not alive
playerIsDead = false
time = function() return FAKE_NOW + 200 end
fire("PLAYER_UNGHOST")                   -- back in the body after the corpse run
time = function() return FAKE_NOW + 245 end
C_DeathRecap = {
    HasRecapEvents = function() return true end,
    GetRecapEvents = function()
        return { { event = "ENVIRONMENTAL_DAMAGE", environmentalType = "Falling", amount = 200,
            timestamp = FAKE_NOW + 245 } }
    end,
}
enemies = {}
clock = 1300                             -- the attackers from before were seen long ago
fire("PLAYER_DEAD")
runTimers()
death = lastDeath()
check(death.secondsSinceRevive == 45, "a death soon after coming back to life is marked")
check(death.text == "Died in Brill (level 7). Killing blow: falling (200 damage). "
    .. "45 s after coming back to life.", "the death text says how soon: " .. death.text)

-- An old recap (from an earlier death) is not used.
time = function() return FAKE_NOW + 2000 end
fire("PLAYER_DEAD")
runTimers()
check(lastDeath().killer == nil and lastDeath().secondsSinceRevive == nil,
    "an old death recap and an old revive are not used")


-------------------------------------------------------------------------------
-- Test 7: where new items came from
-------------------------------------------------------------------------------

installFakeGame()
loadAddon()
local function itemEvents()
    local found = {}
    for _, event in ipairs(CoachLinkDB.characters["Testchar-Testrealm"].history) do
        if event.kind == "item" then
            table.insert(found, event)
        end
    end
    return found
end
fire("PLAYER_ENTERING_WORLD", true, false)   -- creates the history
fire("CHAT_MSG_LOOT", "You receive loot: item:4689.", "Testchar")     -- a green cloak
fire("CHAT_MSG_LOOT", "You receive loot: item:2589x3.", "Testchar")   -- white cloth: not kept
fire("CHAT_MSG_LOOT", "Somebody receives loot: item:4689.", "Somebody")
local items = itemEvents()
check(#items == 1 and items[1].source == "loot" and items[1].item == "Frayed Cloak"
    and items[1].itemID == 4689 and items[1].quality == 2, "looting a green item is recorded")
check(items[1].text == "Looted: Frayed Cloak (green)", "loot text: " .. tostring(items[1].text))

GetQuestReward(2)                        -- the player picks the robe and completes the quest
items = itemEvents()
local reward = items[2]
check(reward and reward.source == "quest" and reward.quest == "Fields of Grief"
    and reward.item == "Apprentice's Robe", "a quest reward is recorded with the quest")
check(reward.choices[1] == "Frayed Cloak" and reward.choices[2] == "Apprentice's Robe"
    and reward.rewards[1] == "Tough Jerky", "the reward keeps every choice offered and the fixed rewards")
check(reward.text == "Quest reward (Fields of Grief): chose Apprentice's Robe over Frayed Cloak; "
    .. "also got Tough Jerky", "quest reward text: " .. tostring(reward.text))

BuyMerchantItem(3, 1)                    -- buys the cloak for 2s 50c
BuyMerchantItem(5, 4)                    -- buys food: not kept
items = itemEvents()
check(#items == 3 and items[3].source == "vendor" and items[3].price == 250
    and items[3].text == "Bought: Frayed Cloak (green) for 2s 50c", "buying gear is recorded with the price")

TakeInboxItem(1, 1)                      -- takes the ore from the auction house letter
items = itemEvents()
check(#items == 4 and items[4].source == "mail" and items[4].item == "Copper Ore" and items[4].count == 4
    and items[4].text == "From the mail (Auction House): Copper Ore x4", "an item taken from mail is recorded")
AutoLootMailItem(1)                      -- "take all" on the same letter
check(#itemEvents() == 5, "taking everything from a letter is recorded too")


-------------------------------------------------------------------------------
-- Test 8: a real logout, when the game has already unloaded the character
-------------------------------------------------------------------------------

local function savedCharacter() return CoachLinkDB.characters["Testchar-Testrealm"] end
-- A fake game whose clock the test can move with `now`.
local function installFakeGameWithClock()
    installFakeGame()
    now = FAKE_NOW
    time = function() return now end
end

-- No warning before the logout: the last full snapshot is kept.
installFakeGameWithClock()
loadAddon()
SlashCmdList.COACHLINK("")          -- a full snapshot at FAKE_NOW
loadAddon()                         -- after the reload: a new UI session, same saved data
now = FAKE_NOW + 600
unloadCharacter()
fire("PLAYER_LOGOUT")
local kept = savedCharacter().snapshot
check(kept.level == 7 and kept.xpMax == 2690 and kept.savedAt == FAKE_NOW,
    "an unloaded logout keeps the last full snapshot")
check(kept.loggedOutAt == FAKE_NOW + 600, "the kept snapshot notes when the player logged out")
check(#savedCharacter().progress == 1, "an unloaded logout adds no progress point")

-- Logging out with Logout(): the snapshot is read while the character is still there.
installFakeGameWithClock()
loadAddon()
SlashCmdList.COACHLINK("")
loadAddon()
now = FAKE_NOW + 600
GetMoney = function() return 20000 end
Logout()                            -- the player clicks Log Out
now = FAKE_NOW + 620
unloadCharacter()
fire("PLAYER_LOGOUT")
local beforeLogout = savedCharacter().snapshot
check(beforeLogout.money == 20000 and beforeLogout.savedAt == FAKE_NOW + 600
    and beforeLogout.reason == "logout", "Logout() saves the snapshot read when it was called")
check(beforeLogout.loggedOutAt == nil and #beforeLogout.errors == 0,
    "that snapshot is a normal one, with no read errors")
check(#savedCharacter().progress == 2 and savedCharacter().progress[2].money == 20000,
    "the snapshot from before the logout adds a progress point")

-- Quitting, and the logout countdown events, work the same way.
for _, startLogout in ipairs({
    function() Quit() end,
    function() fire("PLAYER_CAMPING") end,
    function() fire("PLAYER_QUITING") end,
}) do
    installFakeGameWithClock()
    loadAddon()
    now = FAKE_NOW + 600
    startLogout()
    unloadCharacter()
    fire("PLAYER_LOGOUT")
    check(savedCharacter().snapshot.level == 7 and savedCharacter().snapshot.savedAt == FAKE_NOW + 600,
        "a snapshot is read when the player starts to log out or quit")
end

-- A /reload with the game working is saved as before, even with a section broken.
installFakeGameWithClock()
C_SpellBook.GetSpellBookSkillLineInfo = function() return nil end
C_Container = nil
loadAddon()
SlashCmdList.COACHLINK("")
local reloaded = savedCharacter().snapshot
check(reloaded.reason == "coach" and reloaded.level == 7, "a broken bag API alone does not look unloaded")
for _, message in ipairs(reloaded.errors) do
    check(not message:find("^spells: "), "a missing spellbook line is skipped, not an error")
end

-- The very first save, unloaded and with nothing better: saved, so there is something.
installFakeGameWithClock()
loadAddon()
unloadCharacter()
fire("PLAYER_LOGOUT")
check(savedCharacter().snapshot.reason == "logout", "with nothing better, an unloaded snapshot is still saved")


-------------------------------------------------------------------------------
-- Test 9: asking the coach from the game
-------------------------------------------------------------------------------

installFakeGameWithClock()
local coach = loadAddon()
local reloads = 0
ReloadUI = function() reloads = reloads + 1; eventHandler(nil, "PLAYER_LOGOUT") end
check(coach.askCoach("  What should I do next?  ") == true, "a question is accepted")
local asked = savedCharacter()
check(#asked.questions == 1 and asked.questions[1].text == "What should I do next?"
    and asked.questions[1].askedAt == FAKE_NOW and asked.questions[1].id == FAKE_NOW .. "-1",
    "the question is saved with its time and id")
check(reloads == 1 and asked.snapshot.reason == "ask", "asking saves a snapshot (reason: ask) by reloading")

local ok, why = coach.askCoach("   ")
check(ok == false and why:find("type a question") and reloads == 1, "an empty question is refused, no reload")
InCombatLockdown = function() return true end
ok, why = coach.askCoach("Help!")
check(ok == false and why:find("after the fight") and reloads == 1, "no asking (and no reload) in combat")
InCombatLockdown = function() return false end

coach.askCoach(string.rep("a", 498) .. "\195\169\195\169")   -- 502 bytes, ending in "éé"
local long = savedCharacter().questions[2].text
check(#long == 500 and long:sub(-2) == "\195\169", "a long question is cut to 500 bytes, not inside a letter")
coach.askCoach(string.rep("b", 499) .. "\195\169")             -- 501 bytes: the é doesn't fit
check(#savedCharacter().questions[3].text == 499, "a letter that doesn't fit is dropped whole")

for number = 1, 25 do
    now = FAKE_NOW + number
    coach.askCoach("Question " .. number)
end
local questions = savedCharacter().questions
check(#questions == 20 and questions[20].text == "Question 25", "only the newest 20 questions are kept")

-- wow-coach answered the newest question: it is no longer open, and is dropped on the next ask.
CoachLinkAdvice = { formatVersion = 1, characters = { ["Testchar-Testrealm"] = {
    answers = { { questionId = questions[20].id, title = "Next steps", steps = { "Go to Brill" } } },
} } }
local open = coach.openQuestions()
check(#open == 19 and open[19].text == "Question 24", "answered questions are not open any more")
check(coach.myAdvice().answers[1].steps[1] == "Go to Brill", "the panel can read this character's advice")
CoachLinkAdvice.characters["Testchar-Testrealm"].answers = {}   -- the answer was pushed out...
CoachLinkAdvice.characters["Testchar-Testrealm"].answeredIds = { questions[20].id, 42 }
check(#coach.openQuestions() == 19, "...but answeredIds still marks the question answered")
coach.askCoach("One more")
check(#savedCharacter().questions == 20 and savedCharacter().questions[20].text == "One more",
    "asking again drops the answered question")
CoachLinkAdvice = { characters = { ["Someone-Else"] = { answers = {} } } }
check(coach.myAdvice() == nil, "advice for other characters is not shown")
CoachLinkAdvice = "broken"
check(coach.myAdvice() == nil and #coach.openQuestions() == 20, "a broken advice file is ignored")

-- The slash commands.
chat = {}
print = function(message) table.insert(chat, message) end
SlashCmdList.COACHLINK("ask Where is Brill?")
check(savedCharacter().questions[20].text == "Where is Brill?", "/coach ask keeps the question's capitals")
SlashCmdList.COACHLINK("ask")
check(chat[#chat]:find("type a question", 1, true) ~= nil, "/coach ask with no text says what to do")
SlashCmdList.COACHLINK("panel")
check(chat[#chat]:find("restart the game", 1, true) ~= nil, "/coach panel without the panel file asks for a restart")
coach.togglePanel = function() chat[#chat + 1] = "panel toggled" end
SlashCmdList.COACHLINK("PANEL")
check(chat[#chat] == "panel toggled", "/coach panel opens the panel when it is loaded")

-- /coach (and the "Save for the coach" key) reloads the UI, which is not allowed in a fight.
local reloadsBefore = reloads
InCombatLockdown = function() return true end
SlashCmdList.COACHLINK("")
check(reloads == reloadsBefore, "/coach does not reload the UI during a fight")
check(chat[#chat]:find("Can't save during a fight", 1, true) ~= nil,
    "/coach tells the player to press it again after the fight")
InCombatLockdown = function() return false end
SlashCmdList.COACHLINK("")
check(reloads == reloadsBefore + 1, "/coach reloads the UI again once the fight is over")
print = function() end


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
