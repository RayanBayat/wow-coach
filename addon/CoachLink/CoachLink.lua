--[[
CoachLink: saves a snapshot of your character for the wow-coach MCP server.

How it works, in plain words:
  * WoW lets an addon keep one Lua table that survives between sessions
    ("SavedVariables"). Ours is called CoachLinkDB (declared in CoachLink.toc).
  * WoW writes that table to disk only when you log out, type /reload, or
    exit the game normally. The file is
    WTF/Account/<account>/SavedVariables/CoachLink.lua
  * So this addon fills CoachLinkDB with a snapshot of your character right
    before WoW writes it (the PLAYER_LOGOUT event, which also fires on
    /reload). The coach on your PC then reads that file.
  * The snapshot holds everything the game lets an addon see: level, gold,
    every item in your bags, gear, quests, talents, spells, stats,
    reputations, buffs, action bars and more.
  * A few things can only be read while a window is open: the bank, the
    mailbox and each profession's recipe list. The addon reads them when you
    open that window and keeps the last thing it saw (with the time) in every
    snapshot. Play time is only told to addons as the answer to /played, so
    the addon asks for it itself (after login, /reload and level-ups) and
    keeps that answer out of the chat window.
  * /coach saves a snapshot right now by reloading the UI (takes a few seconds).
  * /coach copy shows the character as plain text in a window, to paste into
    any AI chat. It reads the game right now, so it needs no reload. The
    text itself is made by CoachLinkText.lua.

The exact data format is documented in docs/design.md ("Data contract").
If you change what is saved here, update that file and the Python reader too.

Every part of the snapshot is read inside pcall ("protected call"), so if
one game function breaks in a new patch, the rest still gets saved and the
failure is written to snapshot.errors instead of crashing the addon.
]]

-- WoW passes every file of the addon the same table here; CoachLinkText.lua
-- (loaded first, see the .toc) puts ns.formatSnapshotText on it.
local _, ns = ...

local ADDON_NAME = "CoachLink"
local FORMAT_VERSION = 1    -- bump when the saved format changes in a way old readers can't handle
local MAX_HISTORY = 300     -- keep only the newest history events
local MAX_PROGRESS = 500    -- keep only the newest progress points
-- A new progress point that looks the same as the last one, and comes this soon
-- after it, is skipped (quick /reload series would otherwise fill the log).
local DUPLICATE_WINDOW_SECONDS = 60

-- Equipment slot numbers used by GetInventoryItemLink, with readable names.
local GEAR_SLOTS = {
    { id = 1,  name = "Head" },
    { id = 2,  name = "Neck" },
    { id = 3,  name = "Shoulders" },
    { id = 4,  name = "Shirt" },
    { id = 5,  name = "Chest" },
    { id = 6,  name = "Waist" },
    { id = 7,  name = "Legs" },
    { id = 8,  name = "Feet" },
    { id = 9,  name = "Wrists" },
    { id = 10, name = "Hands" },
    { id = 11, name = "Ring 1" },
    { id = 12, name = "Ring 2" },
    { id = 13, name = "Trinket 1" },
    { id = 14, name = "Trinket 2" },
    { id = 15, name = "Back" },
    { id = 16, name = "Main hand" },
    { id = 17, name = "Off hand" },
    { id = 18, name = "Ranged (wand)" },
    { id = 19, name = "Tabard" },
}

-- Backpack (0) plus the four bag slots (1-4). These count as "your bags".
local FIRST_BAG, LAST_BAG = 0, 4
-- Extra containers some characters have, read only when they have slots.
local REAGENT_BAG, KEYRING = 5, -1
-- If the bank-tab API is missing, the character bank tabs are these containers.
local FIRST_BANK_TAB, LAST_BANK_TAB = 6, 14

-- The five main attributes, in the game's order (UnitStat index 1-5).
local ATTRIBUTES = { "Strength", "Agility", "Stamina", "Intellect", "Spirit" }
-- Magic schools: resistance index 1-6 and spell-damage index 2-7 follow this order.
local SCHOOLS = { "Holy", "Fire", "Nature", "Frost", "Shadow", "Arcane" }
-- Recipe colors in the profession window, from the game's difficulty number.
local RECIPE_COLORS = { [0] = "orange", [1] = "yellow", [2] = "green", [3] = "gray" }
-- Forever's Legacy system (the Y key) is three trait trees plus a reward track.
-- These ids come from the game's Constants.LegacyConsts (used when it is missing).
local LEGACY_TREES = {
    { id = 1187, name = "Professions" },
    { id = 1188, name = "Adventure" },
    { id = 1189, name = "Progression" },
}
local LEGACY_REWARD_TRACK_FACTION = 2802
local MAX_ACTION_SLOTS = 180     -- every action bar slot the game has
local MAX_AURAS = 40             -- buffs or debuffs read per kind
local MAX_MAIL_ATTACHMENTS = 16  -- attachments per letter (ATTACHMENTS_MAX_RECEIVE)
local MAX_LEVEL = 60             -- Forever's level cap: below it, every level needs XP
-- Asking the game for the play time: wait this long after a loading screen or a
-- level-up first, and show /played answers in chat again if none came this long after.
local PLAYED_ASK_DELAY_SECONDS = 3
local PLAYED_ANSWER_WAIT_SECONDS = 10

-- Why the next snapshot is taken. /coach sets this to "coach" before reloading.
local pendingReason = "logout"


-------------------------------------------------------------------------------
-- Small helpers
-------------------------------------------------------------------------------

-- Print a message in the chat window, with the addon name in front.
local function say(message)
    print("|cff66ccffCoachLink:|r " .. message)
end

-- The key we store a character under, e.g. "Testchar-Stormrage".
local function characterKey()
    return UnitName("player") .. "-" .. GetRealmName()
end

-- Make sure CoachLinkDB has the shape we expect, and return this character's table.
local function characterTable()
    CoachLinkDB = CoachLinkDB or {}
    CoachLinkDB.formatVersion = FORMAT_VERSION
    CoachLinkDB.characters = CoachLinkDB.characters or {}

    local key = characterKey()
    local entry = CoachLinkDB.characters[key] or {}
    entry.history = entry.history or {}
    entry.progress = entry.progress or {}
    CoachLinkDB.characters[key] = entry
    return entry
end

-- This character's saved table, WITHOUT creating anything in CoachLinkDB (nil if none).
local function savedEntry()
    local characters = CoachLinkDB and CoachLinkDB.characters
    return characters and characters[characterKey()]
end

-- Run reader(snapshot) safely. If it fails, note the error and carry on.
local function readSection(snapshot, sectionName, reader)
    local ok, err = pcall(reader, snapshot)
    if not ok then
        table.insert(snapshot.errors, sectionName .. ": " .. tostring(err))
    end
end

-- The game's own text for a name like "INVTYPE_CHEST" ("Chest"), or nil.
local function gameText(globalName)
    local text = _G[globalName]
    if type(text) == "string" and text ~= "" then
        return text
    end
    return nil
end

-- 3 -> "3", 4.25 -> "4.3" (one decimal is plenty for stats).
local function numberText(value)
    if value == math.floor(value) then
        return tostring(value)
    end
    return string.format("%.1f", value)
end


-------------------------------------------------------------------------------
-- Items: one description used for bags, bank and gear
-------------------------------------------------------------------------------

-- An item's stats as short lines, e.g. { "+3 Stamina", "+2 Intellect" }, or nil.
-- The game gives keys like "ITEM_MOD_STAMINA_SHORT"; their text is the stat name.
local function itemStats(link)
    local stats = C_Item.GetItemStats(link)
    if not stats then
        return nil
    end
    local lines = {}
    for key, value in pairs(stats) do
        local sign = value > 0 and "+" or ""
        table.insert(lines, sign .. numberText(value) .. " " .. (gameText(key) or key))
    end
    table.sort(lines)  -- pairs() has no fixed order; sorting keeps the text stable
    if #lines == 0 then
        return nil
    end
    return lines
end

-- Everything the game tells us about an item, from its link.
local function describeItem(link)
    local name, _, quality, _, requiredLevel, itemType, itemSubType, _, equipLoc, _, sellPrice =
        C_Item.GetItemInfo(link)
    local item = {
        -- The link looks like "|cff...|Hitem:2589:...|h[Linen Cloth]|h|r".
        name = name or string.match(link, "%[(.-)%]") or link,
        itemID = tonumber(string.match(link, "item:(%d+)")),
        quality = quality,
        itemLevel = C_Item.GetDetailedItemLevelInfo(link),
        requiredLevel = requiredLevel,
        type = itemType,        -- e.g. "Armor", "Trade Goods", "Quest"
        subType = itemSubType,  -- e.g. "Cloth", "Cloth" (yes, both can be "Cloth")
        sellPrice = sellPrice,  -- copper for ONE item at a vendor
    }
    -- Things you can't wear have no slot ("" or INVTYPE_NON_EQUIP_IGNORE).
    if equipLoc and equipLoc ~= "" and equipLoc ~= "INVTYPE_NON_EQUIP_IGNORE" then
        item.equipSlot = gameText(equipLoc) or equipLoc  -- e.g. "Chest"
        local ok, stats = pcall(itemStats, link)
        if ok then
            item.stats = stats
        end
    end
    return item
end

-- Every item in one container (a bag, a bank tab...), with free slots counted.
local function readContainer(bagID)
    local slots = C_Container.GetContainerNumSlots(bagID) or 0
    local container = { bag = bagID, slots = slots, free = 0, items = {} }
    local okName, bagName = pcall(C_Container.GetBagName, bagID)
    if okName then
        container.name = bagName
    end
    for slot = 1, slots do
        local info = C_Container.GetContainerItemInfo(bagID, slot)
        if info and info.hyperlink then
            local item = describeItem(info.hyperlink)
            item.slot = slot
            item.count = info.stackCount or 1
            item.bound = info.isBound == true
            item.noValue = info.hasNoValue == true  -- vendors won't buy it
            item.quality = item.quality or info.quality
            if info.itemName and item.name == info.hyperlink then
                item.name = info.itemName
            end
            table.insert(container.items, item)
        else
            container.free = container.free + 1
        end
    end
    return container
end


-------------------------------------------------------------------------------
-- Snapshot sections. Each one fills a few fields of the snapshot table.
-------------------------------------------------------------------------------

local function readIdentity(snapshot)
    snapshot.name = UnitName("player")
    snapshot.realm = GetRealmName()
    snapshot.race = UnitRace("player")      -- localized, e.g. "Undead"
    local className, classFile = UnitClass("player")
    snapshot.class = className              -- localized, e.g. "Mage"
    snapshot.classFile = classFile          -- always English, e.g. "MAGE"
    snapshot.level = UnitLevel("player")
    local _, factionName = UnitFactionGroup("player")
    snapshot.faction = factionName          -- e.g. "Horde"
    local guildName, rankName = GetGuildInfo("player")
    if guildName then
        snapshot.guild = { name = guildName, rank = rankName }
    end
end

local function readExperience(snapshot)
    snapshot.xp = UnitXP("player")
    snapshot.xpMax = UnitXPMax("player")
    snapshot.restedXP = GetXPExhaustion()   -- nil when you have no rested XP
    snapshot.money = GetMoney()             -- in copper
    snapshot.resting = IsResting() == true  -- in an inn or a city: rested XP builds up
end

local function readLocation(snapshot)
    snapshot.zone = GetRealZoneText()
    snapshot.subZone = GetSubZoneText()
    snapshot.hearth = GetBindLocation()

    local mapID = C_Map.GetBestMapForUnit("player")
    snapshot.mapID = mapID
    if mapID then
        -- Inside dungeons there is often no position, so this can be nil.
        local position = C_Map.GetPlayerMapPosition(mapID, "player")
        if position then
            local x, y = position:GetXY()
            snapshot.x = x * 100
            snapshot.y = y * 100
        end
    end

    local inInstance, instanceType = IsInInstance()
    if inInstance then
        snapshot.instance = { name = GetInstanceInfo(), type = instanceType }
    end
end

-- Health, mana and the numbers on the character window's stat list.
local function readStats(snapshot)
    local _, powerToken = UnitPowerType("player")
    local stats = {
        health = UnitHealth("player"),
        healthMax = UnitHealthMax("player"),
        power = UnitPower("player"),
        powerMax = UnitPowerMax("player"),
        powerType = powerToken,             -- "MANA", "RAGE", "ENERGY"...
        attributes = {},
        resistances = {},
        spellDamage = {},
    }
    snapshot.stats = stats

    for index, englishName in ipairs(ATTRIBUTES) do
        local base, value = UnitStat("player", index)
        table.insert(stats.attributes, {
            name = gameText("SPELL_STAT" .. index .. "_NAME") or englishName,
            value = value,
            base = base,
        })
    end
    local _, armor = UnitArmor("player")
    stats.armor = armor

    for index, school in ipairs(SCHOOLS) do
        local _, total = UnitResistance("player", index)
        table.insert(stats.resistances, { school = school, value = total })
        table.insert(stats.spellDamage, { school = school, value = GetSpellBonusDamage(index + 1) })
    end
    stats.healing = GetSpellBonusHealing()
    stats.spellCrit = GetSpellCritChance()   -- percent
    stats.meleeCrit = GetCritChance()        -- percent
    stats.dodge = GetDodgeChance()           -- percent
    local base, positive, negative = UnitAttackPower("player")
    stats.attackPower = base + positive + negative
    -- Mana per second: outside combat, and while casting (the "5 second rule").
    local regenResting, regenCasting = GetManaRegen()
    stats.manaRegen = regenResting
    stats.manaRegenCasting = regenCasting
end

-- Your bags: the free/total count (as before) and every item in them.
local function readBags(snapshot)
    local free, total = 0, 0
    local containers = {}
    for bag = FIRST_BAG, LAST_BAG do
        total = total + (C_Container.GetContainerNumSlots(bag) or 0)
        free = free + (C_Container.GetContainerNumFreeSlots(bag) or 0)
        if (C_Container.GetContainerNumSlots(bag) or 0) > 0 then
            table.insert(containers, readContainer(bag))
        end
    end
    for _, extra in ipairs({ REAGENT_BAG, KEYRING }) do
        local ok, slots = pcall(C_Container.GetContainerNumSlots, extra)
        if ok and slots and slots > 0 then
            table.insert(containers, readContainer(extra))
        end
    end
    snapshot.bags = { free = free, total = total, containers = containers }
end

-- The quest log: every quest you have, its objectives and where to hand it in.
local function readQuests(snapshot)
    -- Built in a local list and stored at the end: if the game breaks halfway,
    -- snapshot.quests stays nil ("unknown") instead of a misleading short list.
    local quests = {}
    local header = nil
    local numEntries = C_QuestLog.GetNumQuestLogEntries()
    for index = 1, numEntries do
        local info = C_QuestLog.GetInfo(index)
        -- The quest log mixes zone headers ("Tirisfal Glades") with real quests,
        -- and has hidden entries the game uses for its own bookkeeping.
        if info and info.isHeader then
            header = info.title
        elseif info and not info.isHidden then
            local quest = {
                questID = info.questID,
                title = info.title,
                level = info.level,
                zone = header,
                complete = C_QuestLog.IsComplete(info.questID) == true,
                failed = C_QuestLog.IsFailed(info.questID) == true,
                objectives = {},
            }
            if info.suggestedGroup and info.suggestedGroup > 1 then
                quest.suggestedGroup = info.suggestedGroup  -- "group quest (3)"
            end
            -- The short summary under "Quest Objectives", e.g. "Bring 10 Tirisfal
            -- Pumpkins to Farmer Solliden in Brill." Says who to hand it in to.
            local okText, _, objectivesText = pcall(GetQuestLogQuestText, index)
            if okText and objectivesText and objectivesText ~= "" then
                quest.objectivesText = objectivesText
            end
            local objectives = C_QuestLog.GetQuestObjectives(info.questID) or {}
            for _, objective in ipairs(objectives) do
                table.insert(quest.objectives, {
                    text = objective.text,
                    done = objective.finished == true,
                })
            end
            table.insert(quests, quest)
        end
    end
    snapshot.quests = quests
    -- How many quests this character has ever finished (just the number).
    local okDone, doneIDs = pcall(C_QuestLog.GetAllCompletedQuestIDs)
    if okDone and doneIDs then
        snapshot.completedQuests = #doneIDs
    end
end

-- The name of a trait-tree node's chosen entry (a talent or a Legacy perk).
local function traitName(configID, node)
    local entry = C_Traits.GetEntryInfo(configID, node.activeEntry.entryID)
    local definition = C_Traits.GetDefinitionInfo(entry.definitionID)
    local name = definition.overrideName
    if (not name or name == "") and definition.spellID then
        name = C_Spell.GetSpellName(definition.spellID)
    end
    return name or ("trait " .. tostring(definition.spellID or node.ID))
end

-- Every node of a trait tree you have at least one rank in.
local function pickedTraits(configID, treeID)
    local picked = {}
    for _, nodeID in ipairs(C_Traits.GetTreeNodes(treeID)) do
        local node = C_Traits.GetNodeInfo(configID, nodeID)
        if node and node.activeRank > 0 and node.activeEntry then
            table.insert(picked, {
                name = traitName(configID, node),
                rank = node.activeRank,
                maxRank = node.maxRanks,
            })
        end
    end
    return picked
end

-- Forever has three classic talent trees (e.g. Arcane, Fire, Frost) built on
-- the modern "traits" system. This mirrors how Blizzard's own Forever talent
-- window reads them (Blizzard_PlayerSpells/Camelot/ClassTalents).
local function readTalents(snapshot)
    local talents = { unspent = 0, trees = {}, picked = {} }
    snapshot.talents = talents

    local configID = C_SpecializationInfo.GetCombatConfigIDForSpecGroup(
        C_SpecializationInfo.GetActiveSpecGroup())
    if not configID then
        return  -- no talents yet (below the first talent level)
    end
    local treeID = C_Traits.GetConfigInfo(configID).treeIDs[1]

    -- Unspent points.
    local currency = C_Traits.GetTreeCurrencyInfo(configID, treeID, false)
    if currency and currency[1] then
        talents.unspent = currency[1].quantity
    end

    -- Points spent per tree. Each tree is a "group" in the traits system.
    local groups = C_Traits.GetGroupDisplayInfoByTreeID(treeID)
    local groupIDs = {}
    for _, group in ipairs(groups) do
        table.insert(groupIDs, group.groupID)
    end
    local spentByGroup = {}
    for _, info in ipairs(C_Traits.GetGroupCurrencyInfo(configID, groupIDs)) do
        local first = info.currencyInfos and info.currencyInfos[1]
        spentByGroup[info.traitNodeGroupID] = first and first.spent or 0
    end
    for _, group in ipairs(groups) do
        table.insert(talents.trees, {
            name = group.displayName,
            spent = spentByGroup[group.groupID] or 0,
        })
    end

    talents.picked = pickedTraits(configID, treeID)
end

-- Every line of the Skills tab: professions, weapon skills, languages...
-- The tab is a list of headers ("Professions", "Weapon Skills") each followed by
-- its lines, so each line is saved with the header above it as its `category`.
-- The game lists each profession twice, so a name already saved is skipped.
local function readProfessions(snapshot)
    snapshot.professions = {}
    local category = nil
    local seenNames = {}
    for index = 1, C_SkillInfo.GetNumSkillLines() do
        local line = C_SkillInfo.GetSkillLineInfo(index)
        if line and line.isHeader then
            category = line.name
        elseif line and not seenNames[line.name] then
            seenNames[line.name] = true
            table.insert(snapshot.professions, {
                name = line.name,
                rank = line.rank,
                maxRank = line.maxRank,
                category = category,
            })
        end
    end
end

-- What you wear: each item with its stats and how worn it is (durability).
local function readGear(snapshot)
    snapshot.gear = {}
    for _, slot in ipairs(GEAR_SLOTS) do
        local link = GetInventoryItemLink("player", slot.id)
        if link then
            local item = describeItem(link)
            item.slot = slot.name
            local current, maximum = GetInventoryItemDurability(slot.id)
            item.durability = current
            item.durabilityMax = maximum
            table.insert(snapshot.gear, item)
        end
    end
end

-- The spellbook. `spells` lists the names of learned, active spells (what the
-- coach checks against the trainer list). `spellBook` has every entry with its
-- spellbook tab and rank, passives included.
local function readSpells(snapshot)
    snapshot.spells = {}
    snapshot.spellBook = {}
    local seenNames = {}
    local playerBank = Enum.SpellBookSpellBank.Player
    for lineIndex = 1, C_SpellBook.GetNumSpellBookSkillLines() do
        -- nil when the game has already unloaded the spellbook (seen at logout).
        local line = C_SpellBook.GetSpellBookSkillLineInfo(lineIndex) or { numSpellBookItems = 0 }
        for offset = 1, line.numSpellBookItems do
            local item = C_SpellBook.GetSpellBookItemInfo(line.itemIndexOffset + offset, playerBank)
            local isKnownSpell = item and item.itemType == Enum.SpellBookItemType.Spell
            if isKnownSpell then
                local rank = item.subName
                table.insert(snapshot.spellBook, {
                    tab = line.name,
                    name = item.name,
                    rank = (rank and rank ~= "") and rank or nil,
                    passive = item.isPassive == true,
                })
                if not item.isPassive and not seenNames[item.name] then
                    seenNames[item.name] = true
                    table.insert(snapshot.spells, item.name)
                end
            end
        end
    end
end

-- Reputation with every faction the reputation window shows.
-- Factions under a header you collapsed in that window are not shown by the
-- game, so they are missing here too; the header is marked `collapsed`.
local function readReputations(snapshot)
    local reputations = {}
    local group = nil
    for index = 1, C_Reputation.GetNumFactions() do
        local faction = C_Reputation.GetFactionDataByIndex(index)
        if faction and faction.isHeader and not faction.isHeaderWithRep then
            group = faction.name
            if faction.isCollapsed then
                table.insert(reputations, { name = faction.name, collapsed = true })
            end
        elseif faction and faction.name and faction.name ~= "" then
            local bottom = faction.currentReactionThreshold or 0
            table.insert(reputations, {
                name = faction.name,
                group = group,
                standing = gameText("FACTION_STANDING_LABEL" .. tostring(faction.reaction)),
                value = (faction.currentStanding or 0) - bottom,
                max = (faction.nextReactionThreshold or 0) - bottom,
                atWar = faction.atWarWith == true,
            })
        end
    end
    snapshot.reputations = reputations
end

-- Currencies from the Currency tab (Forever-specific tokens and the like).
local function readCurrencies(snapshot)
    local currencies = {}
    for index = 1, C_CurrencyInfo.GetCurrencyListSize() do
        local info = C_CurrencyInfo.GetCurrencyListInfo(index)
        if info and not info.isHeader and info.name and info.name ~= "" then
            table.insert(currencies, { name = info.name, quantity = info.quantity })
        end
    end
    snapshot.currencies = currencies
end

-- Forever's Legacy system (Y key): reward-track level, unspent Legacy points,
-- the perks you picked and this class's Legacy challenges.
local function readLegacy(snapshot)
    local consts = Constants and Constants.LegacyConsts or {}
    local legacy = { perks = {}, challenges = {} }
    snapshot.legacy = legacy

    legacy.renown = C_MajorFactions.GetCurrentRenownLevel(
        consts.LEGACY_REWARD_TRACK_FACTION_ID or LEGACY_REWARD_TRACK_FACTION)

    local treeIDs = {
        consts.LEGACY_TREE_PROFESSIONS_ID, consts.LEGACY_TREE_ADVENTURE_ID,
        consts.LEGACY_TREE_PROGRESSION_ID,
    }
    for index, tree in ipairs(LEGACY_TREES) do
        local treeID = treeIDs[index] or tree.id
        local configID = C_Traits.GetConfigIDByTreeID(treeID)
        if configID then
            if legacy.points == nil then
                local currency = C_Traits.GetTreeCurrencyInfo(configID, treeID, false)
                legacy.points = currency and currency[1] and currency[1].quantity
            end
            for _, perk in ipairs(pickedTraits(configID, treeID)) do
                perk.tree = tree.name
                table.insert(legacy.perks, perk)
            end
        end
    end

    -- Class challenges are achievements in one category per class.
    local categoryID = consts["LEGACY_DEFAULT_CATEGORY_" .. tostring(snapshot.classFile)]
    if categoryID then
        for index = 1, (GetCategoryNumAchievements(categoryID)) or 0 do
            local _, name, _, completed, _, _, _, description = GetAchievementInfo(categoryID, index)
            if name then
                table.insert(legacy.challenges, {
                    name = name, done = completed == true, description = description,
                })
            end
        end
    end
end

-- Buffs and debuffs on you right now, with the seconds left (nil = no end).
local function readAuras(snapshot)
    local auras = {}
    local now = GetTime()
    for _, kind in ipairs({ { filter = "HELPFUL", name = "buff" }, { filter = "HARMFUL", name = "debuff" } }) do
        for index = 1, MAX_AURAS do
            local aura = C_UnitAuras.GetAuraDataByIndex("player", index, kind.filter)
            if not aura then
                break
            end
            local seconds = nil
            if aura.expirationTime and aura.expirationTime > 0 then
                seconds = math.floor(aura.expirationTime - now)
            end
            table.insert(auras, {
                name = aura.name, kind = kind.name, seconds = seconds,
                stacks = (aura.applications and aura.applications > 1) and aura.applications or nil,
            })
        end
    end
    snapshot.auras = auras
end

-- What sits on your action bars, slot by slot (empty slots are left out).
-- Slots 1-12 are the main bar; the other bars follow in blocks of 12.
local function readActionBars(snapshot)
    local actions = {}
    for slot = 1, MAX_ACTION_SLOTS do
        local kind, id = GetActionInfo(slot)
        if kind then
            local name = nil
            if kind == "spell" then
                name = C_Spell.GetSpellName(id)
            elseif kind == "item" then
                name = C_Item.GetItemNameByID(id)
            elseif kind == "summonmount" then
                name = C_MountJournal.GetMountInfoByID(id)
            end
            name = name or GetActionText(slot) or (kind .. " " .. tostring(id))
            table.insert(actions, { slot = slot, kind = kind, name = name })
        end
    end
    snapshot.actionBars = actions
end

-- The party or raid you are in, if any.
local function readGroup(snapshot)
    if not IsInGroup() then
        return
    end
    local isRaid = IsInRaid()
    local unitPrefix = isRaid and "raid" or "party"
    local count = isRaid and GetNumGroupMembers() or (GetNumGroupMembers() - 1)
    local group = { kind = unitPrefix, members = {} }
    for index = 1, count do
        local unit = unitPrefix .. index
        if UnitExists(unit) and not UnitIsUnit(unit, "player") then
            table.insert(group.members, {
                name = UnitName(unit), level = UnitLevel(unit), class = UnitClass(unit),
            })
        end
    end
    snapshot.group = group
end

-- A hunter's or warlock's pet (or any other pet you have out).
local function readPet(snapshot)
    if UnitExists("pet") then
        snapshot.pet = {
            name = UnitName("pet"), level = UnitLevel("pet"), family = UnitCreatureFamily("pet"),
        }
    end
end

local function readAchievements(snapshot)
    snapshot.achievementPoints = GetTotalAchievementPoints()
end

-- The mounts you own, by name.
local function readMounts(snapshot)
    local mounts = {}
    for _, mountID in ipairs(C_MountJournal.GetMountIDs() or {}) do
        local name, _, _, _, _, _, _, _, _, _, isCollected = C_MountJournal.GetMountInfoByID(mountID)
        if isCollected and name then
            table.insert(mounts, name)
        end
    end
    table.sort(mounts)
    snapshot.mounts = mounts
end


-------------------------------------------------------------------------------
-- Things the game only shows while a window is open
-------------------------------------------------------------------------------

-- The bank, the mailbox and the recipe list can only be read while that window
-- is open, and play time only arrives when you type /played. So we read them at
-- that moment and remember what we saw, with the time (`seenAt`). Every snapshot
-- carries the last thing we saw. `seen` holds what was read in this session;
-- before that, the previous saved snapshot is used.
local seen = {}
local seenErrors = {}    -- problems while reading those windows, added to the next snapshot
local bankIsOpen = false

-- The last bank/mail/recipes/timePlayed we saw: this session, or the saved snapshot.
local function lastSeen(name)
    if seen[name] ~= nil then
        return seen[name]
    end
    local entry = savedEntry()
    return entry and entry.snapshot and entry.snapshot[name]
end

-- Run reader() safely. Failures are kept for the next snapshot (not printed in
-- chat: the bank is re-read on every bag change, and chat spam helps nobody).
local function rememberSafely(name, reader)
    local ok, err = pcall(reader)
    if ok then
        seenErrors[name] = nil
    else
        seenErrors[name] = name .. ": " .. tostring(err)
    end
end

-- The bank containers: the bank tabs you bought (character and account bank).
local function bankContainers()
    local containers = {}
    if C_Bank and C_Bank.FetchPurchasedBankTabData and Enum.BankType then
        for _, bankType in ipairs({ Enum.BankType.Character, Enum.BankType.Account }) do
            local okTabs, tabs = pcall(C_Bank.FetchPurchasedBankTabData, bankType)
            for _, tab in ipairs(okTabs and tabs or {}) do
                table.insert(containers, {
                    id = tab.ID, name = tab.name, account = bankType == Enum.BankType.Account,
                })
            end
        end
    end
    if #containers == 0 then
        for bagID = FIRST_BANK_TAB, LAST_BANK_TAB do
            if (C_Container.GetContainerNumSlots(bagID) or 0) > 0 then
                table.insert(containers, { id = bagID, account = false })
            end
        end
    end
    return containers
end

local function readBank()
    local bank = { seenAt = time(), containers = {} }
    for _, tab in ipairs(bankContainers()) do
        local container = readContainer(tab.id)
        if tab.name and tab.name ~= "" then
            container.name = tab.name
        end
        container.account = tab.account
        table.insert(bank.containers, container)
    end
    seen.bank = bank
end

local function readMail()
    local mail = { seenAt = time(), letters = {} }
    local shown = GetInboxNumItems()
    for index = 1, shown do
        local _, _, sender, subject, money, cod, daysLeft, itemCount = GetInboxHeaderInfo(index)
        local letter = {
            sender = sender, subject = subject, money = money, cod = cod,
            daysLeft = daysLeft and math.floor(daysLeft) or nil, items = {},
        }
        if itemCount then
            for attachment = 1, MAX_MAIL_ATTACHMENTS do
                local name, _, _, count, quality = GetInboxItem(index, attachment)
                if name then
                    table.insert(letter.items, { name = name, count = count, quality = quality })
                end
            end
        end
        table.insert(mail.letters, letter)
    end
    seen.mail = mail
end

-- Add or replace one profession in the remembered recipe lists.
local function rememberRecipes(profession)
    local list = {}
    for _, old in ipairs(lastSeen("recipes") or {}) do
        if old.profession ~= profession.profession then
            table.insert(list, old)
        end
    end
    table.insert(list, profession)
    seen.recipes = list
end

-- The open profession window: every recipe you know and its color.
local function readRecipes()
    local ui = C_TradeSkillUI
    local isSomeoneElses = (ui.IsTradeSkillLinked and ui.IsTradeSkillLinked())
        or (ui.IsTradeSkillGuild and ui.IsTradeSkillGuild())
        or (ui.IsNPCCrafting and ui.IsNPCCrafting())
    if isSomeoneElses then
        return  -- a linked or guild recipe list: not this character's recipes
    end
    local info = ui.GetBaseProfessionInfo()
    if not info or not info.professionName or info.professionName == "" then
        return
    end
    local profession = {
        profession = info.professionName, rank = info.skillLevel,
        maxRank = info.maxSkillLevel, seenAt = time(), recipes = {},
    }
    local recipeIDs = (ui.GetAllRecipeIDs or ui.GetFilteredRecipeIDs)() or {}
    for _, recipeID in ipairs(recipeIDs) do
        local recipe = ui.GetRecipeInfo(recipeID)
        if recipe and recipe.learned then
            table.insert(profession.recipes, {
                name = recipe.name,
                color = RECIPE_COLORS[recipe.relativeDifficulty],
                skillUps = recipe.numSkillUps,
            })
        end
    end
    rememberRecipes(profession)
end

-- The play time right now. Play time runs while you are logged in, so an answer
-- from this session is moved forward to now. One from the saved snapshot is not:
-- we can't know how long you were offline since.
local function currentTimePlayed()
    local played = seen.timePlayed
    if not played then
        return lastSeen("timePlayed")
    end
    local passed = time() - played.seenAt
    return { total = played.total + passed, thisLevel = played.thisLevel + passed, seenAt = time() }
end

-- Asking for the play time ourselves (like typing /played), without the answer
-- showing in chat. Chat windows print every TIME_PLAYED_MSG, so the windows that
-- listen to it stop listening until our answer has arrived. `playedQuestion` is
-- that question while it is out: { quietWindows = the windows to turn back on }.
local playedQuestion = nil

-- The chat windows (ChatFrame1, ChatFrame2...) that exist.
local function chatWindows()
    local chatConstants = Constants and Constants.ChatFrameConstants
    local count = (chatConstants and chatConstants.MaxChatWindows) or NUM_CHAT_WINDOWS or 10
    local windows = {}
    for index = 1, count do
        local window = _G["ChatFrame" .. index]
        if window and window.IsEventRegistered then
            table.insert(windows, window)
        end
    end
    return windows
end

-- Let the chat windows show /played answers again, if `question` is still the open one.
local function closePlayedQuestion(question)
    if playedQuestion ~= question then
        return  -- already closed, or a newer question is out
    end
    for _, window in ipairs(question.quietWindows) do
        window:RegisterEvent("TIME_PLAYED_MSG")
    end
    playedQuestion = nil
end

local function askPlayedQuietly()
    if playedQuestion or not RequestTimePlayed then
        return
    end
    local question = { quietWindows = {} }
    for _, window in ipairs(chatWindows()) do
        if window:IsEventRegistered("TIME_PLAYED_MSG") then
            window:UnregisterEvent("TIME_PLAYED_MSG")
            table.insert(question.quietWindows, window)
        end
    end
    playedQuestion = question
    RequestTimePlayed()
    -- If no answer comes, don't leave /played silent in chat.
    C_Timer.After(PLAYED_ANSWER_WAIT_SECONDS, function() closePlayedQuestion(question) end)
end

-- Ask a moment from now: right after a loading screen or a level-up the game may
-- not be ready to answer.
local function askPlayedSoon()
    C_Timer.After(PLAYED_ASK_DELAY_SECONDS, askPlayedQuietly)
end

-- Copy everything remembered into the snapshot.
local function copyRemembered(snapshot)
    snapshot.bank = lastSeen("bank")
    snapshot.mail = lastSeen("mail")
    snapshot.recipes = lastSeen("recipes")
    snapshot.timePlayed = currentTimePlayed()
end

-- The snapshot section: what was remembered, plus any problems reading it.
local function readRemembered(snapshot)
    copyRemembered(snapshot)
    for _, message in pairs(seenErrors) do
        table.insert(snapshot.errors, message)
    end
end


-------------------------------------------------------------------------------
-- Deaths: who was attacking you
-------------------------------------------------------------------------------

-- Since game version 12, addons can't read the combat log, so they can't see who
-- hit you. What an addon can see is which enemies around you have you as their
-- target. So while you are in combat the addon looks every second at your target,
-- focus, mouseover and every enemy with a name plate, and remembers the ones
-- attacking you. When you die, the ones seen in the last few seconds are saved.
-- The game's death recap (the "what killed me" list) adds the killing blow when
-- the game has one.

local ATTACKER_SCAN_SECONDS = 1
local RECENT_ATTACK_SECONDS = 10    -- attackers seen this recently count for a death
local FORGET_ATTACK_SECONDS = 60    -- older ones are dropped
local DEATH_LOOP_SECONDS = 300      -- a death this soon after coming back to life is marked
local RECAP_DELAY_SECONDS = 1       -- the death recap arrives a moment after dying
local RECAP_MAX_AGE_SECONDS = 30    -- an older recap belongs to an earlier death
local MAX_NAMEPLATES = 40
-- The game's classification words, in plain English ("normal" and weak mobs get none).
local CLASSIFICATION_WORDS = {
    elite = "elite", rareelite = "rare elite", rare = "rare", worldboss = "boss",
}

-- The units we can look at: target, focus, mouseover and nameplate1..40.
local WATCHED_UNITS = { "target", "focus", "mouseover" }
for index = 1, MAX_NAMEPLATES do
    table.insert(WATCHED_UNITS, "nameplate" .. index)
end

local recentAttackers = {}  -- GUID (or name) -> { name, level, classification, isPlayer, lastSeen }
local attackerTicker = nil  -- the every-second look while in combat
local lastRevivedAt = nil   -- when you last came back to life (this session)

-- In some places (dungeon fights) the game hides unit details from addons as
-- "secret" values. We skip those instead of failing on them.
local function isSecret(value)
    return issecretvalue ~= nil and issecretvalue(value)
end

-- Remember `unit` if it is an enemy that is attacking you right now.
local function noteIfAttacking(unit, now)
    if not UnitExists(unit) or not UnitCanAttack("player", unit) then
        return
    end
    if UnitIsDeadOrGhost(unit) or not UnitIsUnit(unit .. "target", "player") then
        return
    end
    local name, key = UnitName(unit), UnitGUID(unit)
    if not name or isSecret(name) or isSecret(key) then
        return
    end
    recentAttackers[key or name] = {
        name = name,
        level = UnitLevel(unit),
        classification = UnitClassification(unit),
        isPlayer = UnitIsPlayer(unit) == true,
        lastSeen = now,
    }
end

-- One look around for attackers; also forgets the ones not seen for a while.
local function scanForAttackers()
    local now = GetTime()
    for _, unit in ipairs(WATCHED_UNITS) do
        pcall(noteIfAttacking, unit, now)  -- a unit can vanish or be unreadable: skip it
    end
    for key, attacker in pairs(recentAttackers) do
        if now - attacker.lastSeen > FORGET_ATTACK_SECONDS then
            recentAttackers[key] = nil
        end
    end
end

-- The attackers seen in the last RECENT_ATTACK_SECONDS, strongest first, or nil.
local function attackersJustNow()
    local now = GetTime()
    local list = {}
    for _, attacker in pairs(recentAttackers) do
        if now - attacker.lastSeen <= RECENT_ATTACK_SECONDS then
            table.insert(list, {
                name = attacker.name, level = attacker.level,
                classification = attacker.classification, isPlayer = attacker.isPlayer or nil,
            })
        end
    end
    table.sort(list, function(a, b)
        if (a.level or 0) ~= (b.level or 0) then
            return (a.level or 0) > (b.level or 0)
        end
        return a.name < b.name
    end)
    return #list > 0 and list or nil
end

-- "Scarlet Warrior (level 9, elite)"
local function attackerText(attacker)
    local details = {}
    if attacker.level == -1 then
        table.insert(details, "level ?? (far above yours)")  -- the skull in the game
    elseif attacker.level then
        table.insert(details, "level " .. attacker.level)
    end
    if attacker.isPlayer then
        table.insert(details, "player")
    elseif CLASSIFICATION_WORDS[attacker.classification] then
        table.insert(details, CLASSIFICATION_WORDS[attacker.classification])
    end
    if #details == 0 then
        return attacker.name
    end
    return attacker.name .. " (" .. table.concat(details, ", ") .. ")"
end

-- The killing blow from the game's death recap: { name, spell, amount }, or nil.
-- Like Blizzard's own recap window, the first event is the one that killed you.
local function killingBlow()
    local recap = C_DeathRecap
    if not (recap and recap.HasRecapEvents and recap.HasRecapEvents()) then
        return nil
    end
    local blow = (recap.GetRecapEvents() or {})[1]
    if not blow or not blow.timestamp or math.abs(time() - blow.timestamp) > RECAP_MAX_AGE_SECONDS then
        return nil  -- no recap for this death (yet), or one from an earlier death
    end
    local spell = blow.spellName
    if blow.event == "SWING_DAMAGE" then
        spell = "melee"
    elseif blow.event == "ENVIRONMENTAL_DAMAGE" then
        spell = string.lower(tostring(blow.environmentalType or "environment"))  -- "falling"
    end
    local name = nil
    if not blow.hideCaster and blow.event ~= "ENVIRONMENTAL_DAMAGE" then
        name = blow.sourceName
    end
    return { name = name, spell = spell, amount = blow.amount }
end

-- "Scarlet Warrior (melee, 45 damage)", or "falling (200 damage)" with no one to name.
local function killerText(killer)
    local damage = killer.amount and (killer.amount .. " damage") or nil
    if not killer.name then
        return (killer.spell or "unknown") .. (damage and (" (" .. damage .. ")") or "")
    end
    local how = { killer.spell or "unknown", damage }
    return killer.name .. " (" .. table.concat(how, ", ") .. ")"
end

-- The history sentence for a death, from what is known about it.
local function deathText(death)
    local parts = { "Died in " .. death.place .. " (level " .. tostring(death.level) .. ")" }
    if death.attackers then
        local names = {}
        for _, attacker in ipairs(death.attackers) do
            table.insert(names, attackerText(attacker))
        end
        local enemies = #names == 1 and "1 enemy" or (#names .. " enemies")
        table.insert(parts, "Attacked by " .. enemies .. ": " .. table.concat(names, ", "))
    end
    if death.killer then
        table.insert(parts, "Killing blow: " .. killerText(death.killer))
    end
    if death.secondsSinceRevive then
        table.insert(parts, death.secondsSinceRevive .. " s after coming back to life")
    end
    if #parts == 1 then
        return parts[1]  -- nothing more known: the plain sentence, as before
    end
    return table.concat(parts, ". ") .. "."
end


-------------------------------------------------------------------------------
-- Snapshot and history
-------------------------------------------------------------------------------

-- Read the game right now and return a full snapshot table. Saves nothing.
local function buildSnapshot(reason)
    local snapshot = { savedAt = time(), reason = reason, errors = {} }

    readSection(snapshot, "identity", readIdentity)
    readSection(snapshot, "experience", readExperience)
    readSection(snapshot, "location", readLocation)
    readSection(snapshot, "stats", readStats)
    readSection(snapshot, "bags", readBags)
    readSection(snapshot, "quests", readQuests)
    readSection(snapshot, "talents", readTalents)
    readSection(snapshot, "professions", readProfessions)
    readSection(snapshot, "gear", readGear)
    readSection(snapshot, "spells", readSpells)
    readSection(snapshot, "reputations", readReputations)
    readSection(snapshot, "currencies", readCurrencies)
    readSection(snapshot, "legacy", readLegacy)
    readSection(snapshot, "auras", readAuras)
    readSection(snapshot, "actionBars", readActionBars)
    readSection(snapshot, "group", readGroup)
    readSection(snapshot, "pet", readPet)
    readSection(snapshot, "achievements", readAchievements)
    readSection(snapshot, "mounts", readMounts)
    readSection(snapshot, "remembered", readRemembered)

    return snapshot
end

-- How many quests in the snapshot are complete (ready to turn in). nil when
-- the quests could not be read, so "unknown" is never mistaken for "zero".
local function countCompleteQuests(snapshot)
    if not snapshot.quests then
        return nil
    end
    local done = 0
    for _, quest in ipairs(snapshot.quests) do
        if quest.complete then
            done = done + 1
        end
    end
    return done
end

-- One compact point of the progress log, made from a snapshot. A section that
-- failed to read leaves its fields nil, so the point holds what is known.
local function buildProgressPoint(snapshot)
    return {
        time = snapshot.savedAt,
        reason = snapshot.reason,
        level = snapshot.level,
        xp = snapshot.xp,
        xpMax = snapshot.xpMax,
        money = snapshot.money,
        zone = snapshot.zone,
        subZone = snapshot.subZone,
        questsDone = countCompleteQuests(snapshot),
    }
end

-- The fields that say "the character moved on". Time and reason are left out
-- on purpose: only a real change in the game should make a new point.
local PROGRESS_FIELDS = { "level", "xp", "xpMax", "money", "zone", "subZone", "questsDone" }

-- True when `point` shows nothing new compared with `previous` and was taken
-- within DUPLICATE_WINDOW_SECONDS of it.
local function isDuplicatePoint(previous, point)
    if not previous or not previous.time or not point.time then
        return false
    end
    if point.time - previous.time > DUPLICATE_WINDOW_SECONDS then
        return false
    end
    for _, field in ipairs(PROGRESS_FIELDS) do
        if previous[field] ~= point[field] then
            return false
        end
    end
    return true
end

-- Add a point to the character's progress log (oldest dropped past the cap).
local function addProgressPoint(entry, snapshot)
    local point = buildProgressPoint(snapshot)
    local progress = entry.progress
    if isDuplicatePoint(progress[#progress], point) then
        return
    end
    table.insert(progress, point)
    while #progress > MAX_PROGRESS do
        table.remove(progress, 1)  -- drop the oldest
    end
end

-- True when the game had already unloaded the character while the snapshot was
-- read. That happens at PLAYER_LOGOUT on a real logout or quit (not on /reload):
-- max XP 0, no bag slots, no max health, even a wrong level. A character in the
-- world always has a backpack and health, and needs XP for the next level below
-- the cap. A section that failed to read (nil) proves nothing either way, so a
-- broken game function alone never makes a snapshot look unloaded.
local function looksUnloaded(snapshot)
    if snapshot.bags and snapshot.bags.total == 0 then
        return true
    end
    if snapshot.stats and snapshot.stats.healthMax == 0 then
        return true
    end
    return snapshot.xpMax == 0 and (snapshot.level or 0) < MAX_LEVEL
end

-- A snapshot read when the player started to log out or quit, while the game
-- still had the character (see "Logging out" below). nil until then.
local snapshotBeforeLogout = nil

-- Store `snapshot` for this character and log a progress point.
local function saveSnapshot(entry, snapshot)
    entry.snapshot = snapshot
    -- The log is a bonus: if it fails, the snapshot above is already saved.
    local ok, err = pcall(addProgressPoint, entry, snapshot)
    if not ok then
        table.insert(snapshot.errors, "progress: " .. tostring(err))
    end
end

-- Build a full snapshot and save it. If the game has already unloaded the
-- character, save the best snapshot we have instead of an almost empty one.
local function takeSnapshot(reason)
    local entry = characterTable()
    local snapshot = buildSnapshot(reason)
    if not looksUnloaded(snapshot) then
        saveSnapshot(entry, snapshot)
    elseif snapshotBeforeLogout then
        -- Windows opened after it was read (bank, mail...) are still worth keeping.
        copyRemembered(snapshotBeforeLogout)
        saveSnapshot(entry, snapshotBeforeLogout)
    elseif entry.snapshot and not looksUnloaded(entry.snapshot) then
        -- Keep the last full snapshot; only note the logout. No progress point:
        -- nothing new is known about the character.
        copyRemembered(entry.snapshot)
        entry.snapshot.loggedOutAt = time()
    else
        saveSnapshot(entry, snapshot)  -- nothing better (the very first save)
    end
end

-- Add one event (level up, death, quest...) to this character's history.
-- `extra` holds more fields for this event (optional); it can also replace
-- `level`, for events where UnitLevel is not up to date yet.
-- Returns the event table, so a caller can add details that arrive later.
local function addHistory(kind, text, extra)
    local history = characterTable().history
    local event = {
        time = time(),
        kind = kind,
        text = text,
        level = UnitLevel("player"),
        zone = GetRealZoneText(),
    }
    for key, value in pairs(extra or {}) do
        event[key] = value
    end
    table.insert(history, event)
    while #history > MAX_HISTORY do
        table.remove(history, 1)  -- drop the oldest
    end
    return event
end


-------------------------------------------------------------------------------
-- Game events
-------------------------------------------------------------------------------

local handlers = {}

-- Note: snapshots are only taken in PLAYER_LOGOUT. WoW writes the file only at
-- logout or /reload anyway, so a snapshot taken earlier would just be replaced.

-- Fires on login, after /reload and on every loading screen (dungeon portals...).
function handlers.PLAYER_ENTERING_WORLD(isInitialLogin, isReloadingUi)
    if isInitialLogin then
        addHistory("login", "Logged in")
    end
    if isInitialLogin or isReloadingUi then
        askPlayedSoon()  -- so every snapshot has the play time without typing /played
    end
end

function handlers.PLAYER_LEVEL_UP(newLevel)
    -- While this event runs, UnitLevel still returns the old level.
    addHistory("level", "Reached level " .. tostring(newLevel), { level = newLevel })
    -- The time at this level starts again at 0.
    local played = currentTimePlayed()
    if played and seen.timePlayed then
        seen.timePlayed = { total = played.total, thisLevel = 0, seenAt = time() }
    end
    askPlayedSoon()
end

-- You died: save where, who was attacking you, and (a moment later, when the
-- game has it) the killing blow from the death recap. See "Deaths" above.
function handlers.PLAYER_DEAD()
    scanForAttackers()  -- one last look
    local place = GetSubZoneText()
    if place == "" then
        place = GetRealZoneText()
    end
    local death = { place = place, level = UnitLevel("player"), attackers = attackersJustNow() }
    if lastRevivedAt and time() - lastRevivedAt <= DEATH_LOOP_SECONDS then
        death.secondsSinceRevive = time() - lastRevivedAt
    end
    local event = addHistory("death", deathText(death), {
        attackers = death.attackers, secondsSinceRevive = death.secondsSinceRevive,
    })
    C_Timer.After(RECAP_DELAY_SECONDS, function()
        local ok, blow = pcall(killingBlow)
        if ok and blow then
            death.killer = blow
            event.killer = blow
            event.text = deathText(death)
        end
    end)
end

-- Combat starts and ends ("regen" = health and mana coming back, which stops in combat).
function handlers.PLAYER_REGEN_DISABLED()
    scanForAttackers()
    if not attackerTicker then
        attackerTicker = C_Timer.NewTicker(ATTACKER_SCAN_SECONDS, scanForAttackers)
    end
end

function handlers.PLAYER_REGEN_ENABLED()
    if attackerTicker then
        attackerTicker:Cancel()
        attackerTicker = nil
    end
end

-- Back in your body after the corpse run, or at the spirit healer.
function handlers.PLAYER_UNGHOST()
    lastRevivedAt = time()
end

-- Fires when you release your spirit (you become a ghost, not alive yet) and when
-- another player resurrects you. Only the second one counts as coming back.
function handlers.PLAYER_ALIVE()
    if not UnitIsDeadOrGhost("player") then
        lastRevivedAt = time()
    end
end

function handlers.QUEST_TURNED_IN(questID, xpReward)
    local title = C_QuestLog.GetTitleForQuestID(questID) or ("quest #" .. tostring(questID))
    local text = "Turned in: " .. title
    if xpReward and xpReward > 0 then
        text = text .. " (+" .. xpReward .. " XP)"
    end
    addHistory("quest", text)
end

-- The bank window: read it when it opens, and again after every change while open.
function handlers.BANKFRAME_OPENED()
    bankIsOpen = true
    rememberSafely("bank", readBank)
end

function handlers.BANKFRAME_CLOSED()
    bankIsOpen = false
end

function handlers.BAG_UPDATE_DELAYED()
    if bankIsOpen then
        rememberSafely("bank", readBank)
    end
end

-- Fires when the mailbox's letters arrive or change (only while it is open).
function handlers.MAIL_INBOX_UPDATE()
    rememberSafely("mail", readMail)
end

-- A profession window opened, or its recipe list changed.
function handlers.TRADE_SKILL_SHOW()
    rememberSafely("recipes", readRecipes)
end

function handlers.TRADE_SKILL_LIST_UPDATE()
    rememberSafely("recipes", readRecipes)
end

-- The answer to /played (ours or the player's): total play time and time at this
-- level, in seconds.
function handlers.TIME_PLAYED_MSG(totalSeconds, levelSeconds)
    seen.timePlayed = { total = totalSeconds, thisLevel = levelSeconds, seenAt = time() }
    local question = playedQuestion
    if question then
        -- On the next frame: a window turned back on during this event could still show it.
        C_Timer.After(0, function() closePlayedQuestion(question) end)
    end
end

-- Fires right before WoW writes SavedVariables: on logout, /reload and exit.
function handlers.PLAYER_LOGOUT()
    takeSnapshot(pendingReason)
end


-------------------------------------------------------------------------------
-- Logging out: read the character while the game still has it
-------------------------------------------------------------------------------

-- At PLAYER_LOGOUT on a real logout the character is already gone (see
-- looksUnloaded), so we also read a snapshot when the player starts to log out.
-- If they cancel and keep playing, a later logout reads a newer one.
local function readBeforeLogout()
    local snapshot = buildSnapshot("logout")
    if not looksUnloaded(snapshot) then
        snapshotBeforeLogout = snapshot
    end
end

-- The 20-second logout and quit countdowns.
handlers.PLAYER_CAMPING = readBeforeLogout
handlers.PLAYER_QUITING = readBeforeLogout  -- (the game's own spelling)

local eventFrame = CreateFrame("Frame")
for eventName in pairs(handlers) do
    -- The game throws an error for an event name it doesn't know (a future patch
    -- could rename one). Skip that event instead of breaking the whole addon.
    local ok = pcall(eventFrame.RegisterEvent, eventFrame, eventName)
    if not ok then
        say("this game version has no " .. eventName .. " event; that part is not saved.")
    end
end
eventFrame:SetScript("OnEvent", function(_, eventName, ...)
    local ok, err = pcall(handlers[eventName], ...)
    if not ok then
        say("error in " .. eventName .. ": " .. tostring(err))
    end
end)

-- In an inn or a city the logout is instant, with no countdown event. The game
-- menu's Log Out and Exit Game buttons and /logout, /camp and /quit all call the
-- game's Logout() or Quit(). hooksecurefunc runs our function right after the
-- game's own, without changing what it does.
for _, functionName in ipairs({ "Logout", "Quit" }) do
    if type(_G[functionName]) == "function" then
        hooksecurefunc(functionName, function()
            pcall(readBeforeLogout)  -- never let our reading get in the way of logging out
        end)
    end
end


-------------------------------------------------------------------------------
-- The copy window (/coach copy)
-------------------------------------------------------------------------------

local COPY_FRAME_NAME = "CoachLinkCopyFrame"
local COPY_HELP_TEXT = "Press Ctrl+C to copy (Cmd+C on a Mac), then paste it into your AI chat. "
    .. "Press Esc to close."

local copyFrame   -- created the first time it is needed, then reused

-- A plain dialog look (same textures Blizzard's own dialogs use).
local WINDOW_BACKDROP = {
    bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background",
    edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
    tile = true, tileSize = 32, edgeSize = 32,
    insets = { left = 11, right = 12, top = 12, bottom = 11 },
}

-- The window itself: movable, with a close button and the help label.
local function createWindow()
    local frame = CreateFrame("Frame", COPY_FRAME_NAME, UIParent, "BackdropTemplate")
    frame:SetSize(640, 480)
    frame:SetPoint("CENTER")
    frame:SetFrameStrata("DIALOG")
    frame:SetBackdrop(WINDOW_BACKDROP)
    frame:SetClampedToScreen(true)   -- can't be dragged off screen
    frame:SetMovable(true)
    frame:EnableMouse(true)
    frame:RegisterForDrag("LeftButton")
    frame:SetScript("OnDragStart", frame.StartMoving)
    frame:SetScript("OnDragStop", frame.StopMovingOrSizing)

    local closeButton = CreateFrame("Button", nil, frame, "UIPanelCloseButton")
    closeButton:SetPoint("TOPRIGHT", -6, -6)

    local label = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    label:SetPoint("TOPLEFT", 22, -20)
    label:SetWidth(560)
    label:SetJustifyH("LEFT")
    label:SetText(COPY_HELP_TEXT)

    -- Esc closes the window: WoW hides every frame named in UISpecialFrames.
    table.insert(UISpecialFrames, COPY_FRAME_NAME)
    frame:Hide()
    return frame
end

-- The big text box inside a scroll frame, so long text can be scrolled.
local function createEditBox(frame)
    local scroll = CreateFrame("ScrollFrame", COPY_FRAME_NAME .. "Scroll", frame,
        "UIPanelScrollFrameTemplate")
    scroll:SetPoint("TOPLEFT", 22, -62)
    scroll:SetPoint("BOTTOMRIGHT", -42, 22)

    local editBox = CreateFrame("EditBox", nil, scroll)
    editBox:SetMultiLine(true)
    editBox:SetMaxLetters(0)      -- 0 = no limit: the full sheet is long
    editBox:SetAutoFocus(false)   -- we focus it ourselves when the window opens
    editBox:SetFontObject(ChatFontNormal)
    editBox:SetWidth(560)
    editBox:SetScript("OnEscapePressed", function() frame:Hide() end)
    scroll:SetScrollChild(editBox)
    frame.editBox = editBox
end

-- Show the window with `text` selected, ready for Ctrl+C.
local function showCopyWindow(text)
    if not copyFrame then
        -- Only keep the window once it is complete, so a failed build is retried.
        local frame = createWindow()
        createEditBox(frame)
        copyFrame = frame
    end
    copyFrame.editBox:SetText(text)
    copyFrame:Show()
    copyFrame.editBox:SetFocus()
    copyFrame.editBox:HighlightText()   -- select everything
end

-- This character's saved history, WITHOUT creating anything in CoachLinkDB.
local function savedHistory()
    local entry = savedEntry()
    return entry and entry.history or {}
end

-- /coach copy: read the game now, make the text, show it. Never throws.
local function copyCommand()
    -- WoW only reads a new addon file (CoachLinkText.lua) after a full game
    -- restart; a /reload is not enough. Say that plainly instead of failing.
    if not ns.formatSnapshotText then
        say("please restart the game once to finish updating CoachLink, then try /coach copy again.")
        return
    end
    local ok, err = pcall(function()
        local snapshot = buildSnapshot("copy")
        local text = ns.formatSnapshotText(snapshot, savedHistory(), time())
        showCopyWindow(text)
    end)
    if not ok then
        say("could not open the copy window: " .. tostring(err))
    end
end


-------------------------------------------------------------------------------
-- /coach command
-------------------------------------------------------------------------------

SLASH_COACHLINK1 = "/coach"
SlashCmdList.COACHLINK = function(argument)
    argument = string.lower(strtrim(argument or ""))
    if argument == "help" then
        say("/coach: save your character for the coach on this PC (reloads the UI, a few seconds).")
        say("/coach copy (or /coach export): show your character as text to copy into any AI chat. No reload.")
        say("/coach help: show this list.")
        say("The bank, mailbox and recipes are saved when you open them. Play time is saved by itself.")
        return
    end
    if argument == "copy" or argument == "export" then
        copyCommand()
        return
    end
    say("saving your character for the coach...")
    pendingReason = "coach"
    ReloadUI()  -- triggers PLAYER_LOGOUT, which takes the snapshot and writes the file
end
