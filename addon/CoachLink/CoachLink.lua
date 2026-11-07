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
  * /coach saves a snapshot right now by reloading the UI (takes a few seconds).
  * /coach copy shows the character as plain text in a window, to paste into
    any AI chat. It reads the game right now, so it needs no reload. The
    text itself is made by CoachLinkText.lua.

The exact data format is documented in docs/project-knowledge.md
("Data contract"). If you change what is saved here, update that file and
the Python reader too.

Every part of the snapshot is read inside pcall ("protected call"), so if
one game function breaks in a new patch, the rest still gets saved and the
failure is written to snapshot.errors instead of crashing the addon.
]]

-- WoW passes every file of the addon the same table here; CoachLinkText.lua
-- (loaded first, see the .toc) puts ns.formatSnapshotText on it.
local _, ns = ...

local ADDON_NAME = "CoachLink"
local FORMAT_VERSION = 1    -- bump when the saved format changes
local MAX_HISTORY = 300     -- keep only the newest history events

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

-- Backpack (0) plus the four bag slots (1-4).
local FIRST_BAG, LAST_BAG = 0, 4

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
    CoachLinkDB.characters[key] = entry
    return entry
end

-- Run reader(snapshot) safely. If it fails, note the error and carry on.
local function readSection(snapshot, sectionName, reader)
    local ok, err = pcall(reader, snapshot)
    if not ok then
        table.insert(snapshot.errors, sectionName .. ": " .. tostring(err))
    end
end


-------------------------------------------------------------------------------
-- Snapshot sections. Each one fills a few fields of the snapshot table.
-------------------------------------------------------------------------------

local function readIdentity(snapshot)
    snapshot.name = UnitName("player")
    snapshot.realm = GetRealmName()
    snapshot.race = UnitRace("player")      -- localized, e.g. "Undead"
    snapshot.class = UnitClass("player")    -- localized, e.g. "Mage"
    snapshot.level = UnitLevel("player")
end

local function readExperience(snapshot)
    snapshot.xp = UnitXP("player")
    snapshot.xpMax = UnitXPMax("player")
    snapshot.restedXP = GetXPExhaustion()   -- nil when you have no rested XP
    snapshot.money = GetMoney()             -- in copper
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
end

local function readBags(snapshot)
    local free, total = 0, 0
    for bag = FIRST_BAG, LAST_BAG do
        total = total + (C_Container.GetContainerNumSlots(bag) or 0)
        free = free + (C_Container.GetContainerNumFreeSlots(bag) or 0)
    end
    snapshot.bags = { free = free, total = total }
end

local function readQuests(snapshot)
    snapshot.quests = {}
    local numEntries = C_QuestLog.GetNumQuestLogEntries()
    for index = 1, numEntries do
        local info = C_QuestLog.GetInfo(index)
        -- The quest log mixes zone headers ("Tirisfal Glades") with real quests.
        if info and not info.isHeader then
            local quest = {
                questID = info.questID,
                title = info.title,
                level = info.level,
                complete = C_QuestLog.IsComplete(info.questID) == true,
                objectives = {},
            }
            local objectives = C_QuestLog.GetQuestObjectives(info.questID) or {}
            for _, objective in ipairs(objectives) do
                table.insert(quest.objectives, {
                    text = objective.text,
                    done = objective.finished == true,
                })
            end
            table.insert(snapshot.quests, quest)
        end
    end
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

    -- Every talent you have at least one rank in.
    for _, nodeID in ipairs(C_Traits.GetTreeNodes(treeID)) do
        local node = C_Traits.GetNodeInfo(configID, nodeID)
        if node and node.activeRank > 0 and node.activeEntry then
            local entry = C_Traits.GetEntryInfo(configID, node.activeEntry.entryID)
            local definition = C_Traits.GetDefinitionInfo(entry.definitionID)
            local name = definition.overrideName
            if not name or name == "" then
                name = C_Spell.GetSpellName(definition.spellID)
            end
            table.insert(talents.picked, {
                name = name or ("spell " .. tostring(definition.spellID)),
                rank = node.activeRank,
                maxRank = node.maxRanks,
            })
        end
    end
end

-- Every line of the Skills tab: professions, weapon skills, languages...
-- The tab is a list of headers ("Professions", "Weapon Skills") each followed by
-- its lines, so each line is saved with the header above it as its `category`.
-- The game lists each profession twice, so a name already saved is skipped.
local function readProfessions(snapshot)
    snapshot.professions = {}
    local category = nil
    local seen = {}
    for index = 1, C_SkillInfo.GetNumSkillLines() do
        local line = C_SkillInfo.GetSkillLineInfo(index)
        if line and line.isHeader then
            category = line.name
        elseif line and not seen[line.name] then
            seen[line.name] = true
            table.insert(snapshot.professions, {
                name = line.name,
                rank = line.rank,
                maxRank = line.maxRank,
                category = category,
            })
        end
    end
end

local function readGear(snapshot)
    snapshot.gear = {}
    for _, slot in ipairs(GEAR_SLOTS) do
        local link = GetInventoryItemLink("player", slot.id)
        if link then
            local name, _, quality = C_Item.GetItemInfo(link)
            table.insert(snapshot.gear, {
                slot = slot.name,
                name = name or link,
                itemLevel = C_Item.GetDetailedItemLevelInfo(link),
                quality = quality,
            })
        end
    end
end

-- Names of the spells you know, so the coach can tell what you still need to train.
local function readSpells(snapshot)
    snapshot.spells = {}
    local seen = {}
    local playerBank = Enum.SpellBookSpellBank.Player
    for lineIndex = 1, C_SpellBook.GetNumSpellBookSkillLines() do
        local line = C_SpellBook.GetSpellBookSkillLineInfo(lineIndex)
        for offset = 1, line.numSpellBookItems do
            local item = C_SpellBook.GetSpellBookItemInfo(line.itemIndexOffset + offset, playerBank)
            local isKnownSpell = item and item.itemType == Enum.SpellBookItemType.Spell
            if isKnownSpell and not item.isPassive and not seen[item.name] then
                seen[item.name] = true
                table.insert(snapshot.spells, item.name)
            end
        end
    end
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
    readSection(snapshot, "bags", readBags)
    readSection(snapshot, "quests", readQuests)
    readSection(snapshot, "talents", readTalents)
    readSection(snapshot, "professions", readProfessions)
    readSection(snapshot, "gear", readGear)
    readSection(snapshot, "spells", readSpells)

    return snapshot
end

-- Build a full snapshot and store it for this character.
local function takeSnapshot(reason)
    characterTable().snapshot = buildSnapshot(reason)
end

-- Add one event (level up, death, quest...) to this character's history.
local function addHistory(kind, text)
    local history = characterTable().history
    table.insert(history, {
        time = time(),
        kind = kind,
        text = text,
        level = UnitLevel("player"),
        zone = GetRealZoneText(),
    })
    while #history > MAX_HISTORY do
        table.remove(history, 1)  -- drop the oldest
    end
end


-------------------------------------------------------------------------------
-- Game events
-------------------------------------------------------------------------------

local handlers = {}

-- Note: snapshots are only taken in PLAYER_LOGOUT. WoW writes the file only at
-- logout or /reload anyway, so a snapshot taken earlier would just be replaced.

-- Fires on login and on every loading screen (isInitialLogin is false on /reload).
function handlers.PLAYER_ENTERING_WORLD(isInitialLogin)
    if isInitialLogin then
        addHistory("login", "Logged in")
    end
end

function handlers.PLAYER_LEVEL_UP(newLevel)
    addHistory("level", "Reached level " .. tostring(newLevel))
end

function handlers.PLAYER_DEAD()
    local place = GetSubZoneText()
    if place == "" then
        place = GetRealZoneText()
    end
    addHistory("death", "Died in " .. place .. " (level " .. UnitLevel("player") .. ")")
end

function handlers.QUEST_TURNED_IN(questID, xpReward)
    local title = C_QuestLog.GetTitleForQuestID(questID) or ("quest #" .. tostring(questID))
    local text = "Turned in: " .. title
    if xpReward and xpReward > 0 then
        text = text .. " (+" .. xpReward .. " XP)"
    end
    addHistory("quest", text)
end

-- Fires right before WoW writes SavedVariables: on logout, /reload and exit.
function handlers.PLAYER_LOGOUT()
    takeSnapshot(pendingReason)
end

local eventFrame = CreateFrame("Frame")
for eventName in pairs(handlers) do
    eventFrame:RegisterEvent(eventName)
end
eventFrame:SetScript("OnEvent", function(_, eventName, ...)
    local ok, err = pcall(handlers[eventName], ...)
    if not ok then
        say("error in " .. eventName .. ": " .. tostring(err))
    end
end)


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
    local characters = CoachLinkDB and CoachLinkDB.characters
    local entry = characters and characters[characterKey()]
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
