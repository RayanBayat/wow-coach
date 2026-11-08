--[[
CoachLink text export: turns a snapshot into plain text for pasting into an AI chat.

This file is "pure": it only does string work on tables you hand it. It never
calls the game, so the test harness can check its output outside WoW.

WoW gives every file of an addon the same two values through `...`: the addon
name and one shared table. We put our function on that table (ns.formatSnapshotText)
so CoachLink.lua can call it.

The text is only your character's data: no instructions for the AI, so you can
ask it whatever you like. No color codes and no Markdown, so it looks the same
in any chat.
]]

local _, ns = ...

local MAX_HISTORY_LINES = 10   -- recent events shown at the end
-- Skills-tab headers, as the English client names them.
local WEAPON_SKILLS = "Weapon Skills"
local LANGUAGES = "Languages"
local QUALITY_WORDS = { [0] = "poor", "common", "uncommon", "rare", "epic", "legendary" }
local GRAY_QUALITY = 0
local MAIN_BAR_SLOTS = 12


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

-- "5 min ago", "3 h ago"... A missing time gives "".
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

-- A length of time: "2 d 3 h", "4 h 10 min", "25 min", "40 s".
local function durationText(seconds)
    seconds = math.max(0, math.floor(seconds))
    local days = math.floor(seconds / 86400)
    local hours = math.floor((seconds % 86400) / 3600)
    local minutes = math.floor((seconds % 3600) / 60)
    if days > 0 then return days .. " d " .. hours .. " h" end
    if hours > 0 then return hours .. " h " .. minutes .. " min" end
    if minutes > 0 then return minutes .. " min" end
    return seconds .. " s"
end

-- 3 -> "3", 4.25 -> "4.3".
local function numberText(value)
    if value == math.floor(value) then return tostring(value) end
    return string.format("%.1f", value)
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

-- Join the non-empty strings of a list with ", ".
local function joinParts(parts)
    local kept = {}
    for _, part in ipairs(parts) do
        if part and part ~= "" then table.insert(kept, part) end
    end
    return table.concat(kept, ", ")
end


-------------------------------------------------------------------------------
-- Items: shared by gear, bags, bank and mail
-------------------------------------------------------------------------------

-- "(item level 5, common, Chest, needs level 10, +3 Stamina)" or "".
-- showSlot = false leaves out the slot word (gear lines already start with it).
local function itemDetails(item, extra, showSlot)
    local details = {}
    -- Item level only matters for things you wear; cloth and food have one too.
    if item.itemLevel and item.equipSlot then table.insert(details, "item level " .. item.itemLevel) end
    if item.quality and QUALITY_WORDS[item.quality] then
        table.insert(details, QUALITY_WORDS[item.quality])
    end
    if item.equipSlot and showSlot ~= false then table.insert(details, item.equipSlot) end
    if item.requiredLevel and item.requiredLevel > 1 then
        table.insert(details, "needs level " .. item.requiredLevel)
    end
    for _, stat in ipairs(item.stats or {}) do table.insert(details, stat) end
    for _, part in ipairs(extra or {}) do table.insert(details, part) end
    if #details == 0 then return "" end
    return " (" .. table.concat(details, ", ") .. ")"
end

-- Count each item once across many containers: same name and quality = one line.
local function groupItems(containers)
    local groups, order = {}, {}
    for _, container in ipairs(containers or {}) do
        for _, item in ipairs(container.items or {}) do
            local key = tostring(item.name) .. "|" .. tostring(item.quality)
            if not groups[key] then
                groups[key] = { item = item, count = 0, stacks = 0 }
                table.insert(order, key)
            end
            groups[key].count = groups[key].count + (item.count or 1)
            groups[key].stacks = groups[key].stacks + 1
        end
    end
    local list = {}
    for _, key in ipairs(order) do table.insert(list, groups[key]) end
    return list
end

-- One line per item group: "- Linen Cloth x14 (common, Trade Goods, sells for 13c each)".
local function itemGroupLines(containers)
    local lines = {}
    for _, group in ipairs(groupItems(containers)) do
        local item = group.item
        local extra = {}
        if item.type and item.type ~= "" then
            local kind = item.type
            if item.subType and item.subType ~= "" and item.subType ~= item.type then
                kind = kind .. " / " .. item.subType
            end
            table.insert(extra, kind)
        end
        if item.noValue then
            table.insert(extra, "vendors won't buy it")
        elseif item.sellPrice and item.sellPrice > 0 then
            table.insert(extra, "sells for " .. moneyText(item.sellPrice) .. " each")
        end
        if item.bound then table.insert(extra, "soulbound") end
        local count = group.count > 1 and (" x" .. group.count) or ""
        table.insert(lines, "- " .. tostring(item.name or "?") .. count .. itemDetails(item, extra))
    end
    return lines
end

-- "Backpack 16 slots (3 free), Small Brown Pouch 6 slots (0 free)".
local function containerSummary(containers)
    local parts = {}
    for _, container in ipairs(containers or {}) do
        local name = container.name or ("bag " .. tostring(container.bag))
        if container.account then name = name .. " [account bank]" end
        table.insert(parts, string.format("%s %d slots (%d free)", name,
            container.slots or 0, container.free or 0))
    end
    return table.concat(parts, ", ")
end

-- Vendor value of the gray (junk) items: what "sell your grays" is worth.
local function junkValue(containers)
    local copper = 0
    for _, container in ipairs(containers or {}) do
        for _, item in ipairs(container.items or {}) do
            if item.quality == GRAY_QUALITY and not item.noValue then
                copper = copper + (item.sellPrice or 0) * (item.count or 1)
            end
        end
    end
    return copper
end


-------------------------------------------------------------------------------
-- One function per section. Each returns a list of lines.
-------------------------------------------------------------------------------

local function characterLines(snapshot, now)
    local lines = {}
    local who = (snapshot.name or "?") .. ", level " .. tostring(snapshot.level or "?")
    who = who .. " " .. (snapshot.race or "") .. " " .. (snapshot.class or "")
    if snapshot.realm then who = who .. " (realm " .. snapshot.realm .. ")" end
    table.insert(lines, who)
    if snapshot.faction then table.insert(lines, "Faction: " .. snapshot.faction) end
    if snapshot.guild and snapshot.guild.name then
        table.insert(lines, "Guild: " .. snapshot.guild.name ..
            (snapshot.guild.rank and (" (rank " .. snapshot.guild.rank .. ")") or ""))
    end

    if snapshot.xp and snapshot.xpMax and snapshot.xpMax > 0 then
        local line = string.format("XP: %d / %d (%d%%), %d to the next level", snapshot.xp,
            snapshot.xpMax, math.floor(snapshot.xp / snapshot.xpMax * 100), snapshot.xpMax - snapshot.xp)
        if snapshot.restedXP and snapshot.restedXP > 0 then
            line = line .. ", rested XP " .. snapshot.restedXP
        end
        table.insert(lines, line)
    end
    if snapshot.resting then
        table.insert(lines, "Resting: yes (in an inn or a city, rested XP builds up)")
    end
    if snapshot.money then
        table.insert(lines, "Gold: " .. moneyText(snapshot.money))
    end
    local played = snapshot.timePlayed
    if played and played.total then
        table.insert(lines, "Time played: " .. durationText(played.total) .. " (this level "
            .. durationText(played.thisLevel or 0) .. "; as of " .. agoText(played.seenAt, now) .. ")")
    end
    if snapshot.achievementPoints then
        table.insert(lines, "Achievement points: " .. snapshot.achievementPoints)
    end
    return lines
end

local function locationLines(snapshot)
    local lines = {}
    local place = snapshot.zone or ""
    if snapshot.subZone and snapshot.subZone ~= "" then
        place = place .. ", " .. snapshot.subZone
    end
    if snapshot.x and snapshot.y then
        place = place .. string.format(" (map coordinates %.1f, %.1f)", snapshot.x, snapshot.y)
    end
    if place ~= "" then table.insert(lines, "Now in: " .. place) end
    if snapshot.instance and snapshot.instance.name then
        table.insert(lines, "Inside: " .. snapshot.instance.name ..
            (snapshot.instance.type and (" (" .. snapshot.instance.type .. ")") or ""))
    end
    if snapshot.hearth then table.insert(lines, "Hearthstone set to: " .. snapshot.hearth) end
    return lines
end

local function statLines(snapshot)
    local stats = snapshot.stats
    if not stats then return {} end
    local lines = {}
    if stats.healthMax then
        table.insert(lines, "Health: " .. tostring(stats.health or "?") .. " / " .. stats.healthMax)
    end
    if stats.powerMax and stats.powerMax > 0 then
        local kind = stats.powerType and (stats.powerType:sub(1, 1) .. stats.powerType:sub(2):lower()) or "Power"
        table.insert(lines, kind .. ": " .. tostring(stats.power or "?") .. " / " .. stats.powerMax)
    end
    local attributes = {}
    for _, attribute in ipairs(stats.attributes or {}) do
        table.insert(attributes, tostring(attribute.name) .. " " .. tostring(attribute.value))
    end
    if #attributes > 0 then table.insert(lines, table.concat(attributes, ", ")) end
    if stats.armor then table.insert(lines, "Armor: " .. stats.armor) end

    local resist = {}
    for _, entry in ipairs(stats.resistances or {}) do
        if entry.value and entry.value > 0 then
            table.insert(resist, entry.school .. " " .. entry.value)
        end
    end
    if #resist > 0 then table.insert(lines, "Resistances: " .. table.concat(resist, ", ")) end

    local damage, allSame, firstValue = {}, true, nil
    for _, entry in ipairs(stats.spellDamage or {}) do
        firstValue = firstValue or entry.value
        if entry.value ~= firstValue then allSame = false end
        table.insert(damage, entry.school .. " " .. tostring(entry.value))
    end
    if #damage > 0 then
        if allSame then
            table.insert(lines, "Spell damage bonus: " .. tostring(firstValue) .. " (all schools)")
        else
            table.insert(lines, "Spell damage bonus: " .. table.concat(damage, ", "))
        end
    end
    local other = {}
    if stats.spellCrit then table.insert(other, "Spell crit " .. numberText(stats.spellCrit) .. "%") end
    if stats.meleeCrit then table.insert(other, "melee crit " .. numberText(stats.meleeCrit) .. "%") end
    if stats.dodge then table.insert(other, "dodge " .. numberText(stats.dodge) .. "%") end
    if stats.attackPower then table.insert(other, "attack power " .. stats.attackPower) end
    if stats.healing then table.insert(other, "healing bonus " .. stats.healing) end
    if #other > 0 then table.insert(lines, joinParts(other)) end
    if stats.manaRegen then
        table.insert(lines, "Mana regen per 5 s: " .. numberText(stats.manaRegen * 5) ..
            " (while casting: " .. numberText((stats.manaRegenCasting or 0) * 5) .. ")")
    end
    return lines
end

local function auraLines(snapshot)
    local lines = {}
    for _, aura in ipairs(snapshot.auras or {}) do
        local details = { aura.kind }
        if aura.stacks then table.insert(details, aura.stacks .. " stacks") end
        if aura.seconds then table.insert(details, durationText(aura.seconds) .. " left") end
        table.insert(lines, "- " .. tostring(aura.name or "?") .. " (" .. joinParts(details) .. ")")
    end
    return lines
end

local function questLines(snapshot)
    local lines = {}
    for _, quest in ipairs(snapshot.quests or {}) do
        local tags = {}
        -- The ID tells apart quests with the same title (Classic and Retail wiki pages).
        if quest.questID then table.insert(tags, "quest " .. quest.questID) end
        if quest.complete then table.insert(tags, "DONE, ready to turn in") end
        if quest.failed then table.insert(tags, "FAILED") end
        if quest.suggestedGroup then table.insert(tags, "group quest for " .. quest.suggestedGroup) end
        if quest.zone then table.insert(tags, quest.zone) end
        local suffix = #tags > 0 and (" (" .. table.concat(tags, "; ") .. ")") or ""
        table.insert(lines, string.format("- [%s] %s%s", tostring(quest.level or "?"),
            quest.title or "?", suffix))
        if quest.objectivesText then
            table.insert(lines, "    Goal: " .. (quest.objectivesText:gsub("%s+", " ")))
        end
        for _, objective in ipairs(quest.objectives or {}) do
            table.insert(lines, "    " .. (objective.done and "[x] " or "[ ] ") .. (objective.text or ""))
        end
    end
    if snapshot.completedQuests then
        table.insert(lines, "Quests completed so far (all time): " .. snapshot.completedQuests)
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

-- Every Skills-tab line. Skills you level up (professions, cooking...) get a
-- line each; the rest (weapon skills, languages, armor types...) share one line
-- per Skills-tab header.
local function skillLines(snapshot)
    local lines, groups, order = {}, {}, {}
    for _, skill in ipairs(snapshot.professions or {}) do
        local ranks = tostring(skill.rank or "?") .. "/" .. tostring(skill.maxRank or "?")
        local category = skill.category or "Other"
        local levelable = skill.maxRank and skill.maxRank > 1
        if levelable and category ~= WEAPON_SKILLS and category ~= LANGUAGES then
            table.insert(lines, "- " .. (skill.name or "?") .. ": " .. ranks)
        else
            local text = (skill.name or "?") .. (levelable and (" " .. ranks) or "")
            if not groups[category] then
                groups[category] = {}
                table.insert(order, category)
            end
            table.insert(groups[category], text)
        end
    end
    for _, category in ipairs(order) do
        table.insert(lines, category .. ": " .. table.concat(groups[category], ", "))
    end
    return lines
end

local function recipeLines(snapshot, now)
    local lines = {}
    for _, profession in ipairs(snapshot.recipes or {}) do
        local header = tostring(profession.profession or "?")
        if profession.rank then
            header = header .. " " .. profession.rank .. "/" .. tostring(profession.maxRank or "?")
        end
        table.insert(lines, header .. ", " .. #(profession.recipes or {}) .. " recipes (seen "
            .. agoText(profession.seenAt, now) .. "; orange = sure skill-up, yellow = likely, green = rare, gray = never):")
        for _, recipe in ipairs(profession.recipes or {}) do
            table.insert(lines, "- " .. tostring(recipe.name or "?") ..
                (recipe.color and (" (" .. recipe.color .. ")") or ""))
        end
    end
    return lines
end

local function gearLines(snapshot)
    local lines = {}
    for _, item in ipairs(snapshot.gear or {}) do
        local extra = {}
        if item.durability and item.durabilityMax then
            table.insert(extra, "durability " .. item.durability .. "/" .. item.durabilityMax)
        end
        table.insert(lines, "- " .. (item.slot or "?") .. ": " .. (item.name or "?")
            .. itemDetails(item, extra, false))
    end
    return lines
end

local function bagLines(snapshot)
    local bags = snapshot.bags
    if not bags then return {} end
    local lines = {}
    table.insert(lines, string.format("%d free of %d slots", bags.free or 0, bags.total or 0))
    if bags.containers and #bags.containers > 0 then
        table.insert(lines, "Bags: " .. containerSummary(bags.containers))
        local junk = junkValue(bags.containers)
        if junk > 0 then
            table.insert(lines, "Gray (junk) items sell for " .. moneyText(junk) .. " in total")
        end
        for _, line in ipairs(itemGroupLines(bags.containers)) do table.insert(lines, line) end
    end
    return lines
end

local function bankLines(snapshot, now)
    local bank = snapshot.bank
    if not bank then
        return { "Not seen yet: open your bank once and the addon remembers it." }
    end
    local lines = { "Seen " .. agoText(bank.seenAt, now) .. ". " .. containerSummary(bank.containers) }
    for _, line in ipairs(itemGroupLines(bank.containers)) do table.insert(lines, line) end
    if #lines == 1 then table.insert(lines, "(empty)") end
    return lines
end

local function mailLines(snapshot, now)
    local mail = snapshot.mail
    if not mail then
        return { "Not seen yet: open a mailbox once and the addon remembers it." }
    end
    local letters = mail.letters or {}
    local count = #letters == 1 and "1 letter" or (#letters .. " letters")
    local lines = { "Seen " .. agoText(mail.seenAt, now) .. ", " .. count }
    for _, letter in ipairs(letters) do
        local parts = { "from " .. tostring(letter.sender or "?") }
        if letter.money and letter.money > 0 then table.insert(parts, moneyText(letter.money) .. " attached") end
        if letter.cod and letter.cod > 0 then table.insert(parts, "cash on delivery " .. moneyText(letter.cod)) end
        local items = {}
        for _, item in ipairs(letter.items or {}) do
            table.insert(items, tostring(item.name) .. ((item.count or 1) > 1 and (" x" .. item.count) or ""))
        end
        if #items > 0 then table.insert(parts, "items: " .. table.concat(items, ", ")) end
        if letter.daysLeft then table.insert(parts, letter.daysLeft .. " days left") end
        table.insert(lines, "- " .. tostring(letter.subject or "(no subject)") .. " (" .. joinParts(parts) .. ")")
    end
    return lines
end

-- Spells by spellbook tab, with ranks; passives on their own line.
local function spellLines(snapshot)
    if not snapshot.spellBook then
        local spells = snapshot.spells or {}
        if #spells == 0 then return {} end
        return { table.concat(spells, ", ") }
    end
    local lines, byTab, order, passives = {}, {}, {}, {}
    for _, spell in ipairs(snapshot.spellBook) do
        local text = tostring(spell.name or "?") .. (spell.rank and (" (" .. spell.rank .. ")") or "")
        if spell.passive then
            table.insert(passives, text)
        else
            local tab = spell.tab or "Other"
            if not byTab[tab] then
                byTab[tab] = {}
                table.insert(order, tab)
            end
            table.insert(byTab[tab], text)
        end
    end
    for _, tab in ipairs(order) do
        table.insert(lines, tab .. ": " .. table.concat(byTab[tab], ", "))
    end
    if #passives > 0 then table.insert(lines, "Passive: " .. table.concat(passives, ", ")) end
    return lines
end

-- "Main bar: 1 Frostbolt, 2 Fireball" and "Slots 61-72: ..." for the other bars.
local function actionBarLines(snapshot)
    local lines, bars, order = {}, {}, {}
    for _, action in ipairs(snapshot.actionBars or {}) do
        local bar = math.floor((action.slot - 1) / MAIN_BAR_SLOTS)
        if not bars[bar] then
            bars[bar] = {}
            table.insert(order, bar)
        end
        local key = action.slot - bar * MAIN_BAR_SLOTS
        table.insert(bars[bar], key .. " " .. tostring(action.name))
    end
    for _, bar in ipairs(order) do
        local label = bar == 0 and "Main bar" or string.format("Slots %d-%d",
            bar * MAIN_BAR_SLOTS + 1, (bar + 1) * MAIN_BAR_SLOTS)
        table.insert(lines, label .. ": " .. table.concat(bars[bar], ", "))
    end
    return lines
end

local function reputationLines(snapshot)
    local lines = {}
    for _, faction in ipairs(snapshot.reputations or {}) do
        if faction.collapsed then
            table.insert(lines, "- " .. tostring(faction.name) .. ": collapsed in your reputation window, not read")
        else
            local text = "- " .. tostring(faction.name) .. ": " .. tostring(faction.standing or "?")
            if faction.max and faction.max > 0 then
                text = text .. " " .. tostring(faction.value or 0) .. "/" .. faction.max
            end
            if faction.atWar then text = text .. " (at war)" end
            table.insert(lines, text)
        end
    end
    return lines
end

local function currencyLines(snapshot)
    local lines = {}
    for _, currency in ipairs(snapshot.currencies or {}) do
        table.insert(lines, "- " .. tostring(currency.name) .. ": " .. tostring(currency.quantity or 0))
    end
    return lines
end

local function legacyLines(snapshot)
    local legacy = snapshot.legacy
    if not legacy then return {} end
    local lines = {}
    local summary = {}
    if legacy.renown then table.insert(summary, "reward track level " .. legacy.renown) end
    if legacy.points then table.insert(summary, legacy.points .. " Legacy points to spend") end
    if #summary > 0 then table.insert(lines, joinParts(summary)) end
    local perks = {}
    for _, perk in ipairs(legacy.perks or {}) do
        table.insert(perks, string.format("%s (%s, %s/%s)", tostring(perk.name), tostring(perk.tree),
            tostring(perk.rank or "?"), tostring(perk.maxRank or "?")))
    end
    if #perks > 0 then table.insert(lines, "Perks: " .. table.concat(perks, ", ")) end
    for _, challenge in ipairs(legacy.challenges or {}) do
        table.insert(lines, "- " .. (challenge.done and "[x] " or "[ ] ") .. tostring(challenge.name) ..
            ((challenge.description and challenge.description ~= "") and (": " .. challenge.description) or ""))
    end
    return lines
end

local function groupAndPetLines(snapshot)
    local lines = {}
    local group = snapshot.group
    if group then
        local members = {}
        for _, member in ipairs(group.members or {}) do
            table.insert(members, string.format("%s (level %s %s)", tostring(member.name),
                tostring(member.level or "?"), tostring(member.class or "")))
        end
        table.insert(lines, "In a " .. tostring(group.kind) .. ": " .. table.concat(members, ", "))
    end
    local pet = snapshot.pet
    if pet then
        table.insert(lines, "Pet: " .. tostring(pet.name) .. ", level " .. tostring(pet.level or "?") ..
            (pet.family and (" " .. pet.family) or ""))
    end
    return lines
end

local function mountLines(snapshot)
    local mounts = snapshot.mounts or {}
    if #mounts == 0 then return {} end
    return { table.concat(mounts, ", ") }
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
-- CoachLink.lua uses this for the prices in the history ("Bought: ... for 2s 50c").
ns.moneyText = moneyText

function ns.formatSnapshotText(snapshot, history, now)
    local out = {}
    local made = (date and now) and (", " .. date("%Y-%m-%d %H:%M", now)) or ""
    table.insert(out, "World of Warcraft: Forever character sheet (CoachLink addon" .. made .. ")")

    addSection(out, "== CHARACTER ==", characterLines(snapshot, now))
    addSection(out, "== LOCATION ==", locationLines(snapshot))
    addSection(out, "== STATS ==", statLines(snapshot))
    addSection(out, "== BUFFS AND DEBUFFS ==", auraLines(snapshot))
    addSection(out, "== QUESTS (" .. #(snapshot.quests or {}) .. ") ==", questLines(snapshot))
    addSection(out, "== TALENTS ==", talentLines(snapshot))
    addSection(out, "== PROFESSIONS AND SKILLS ==", skillLines(snapshot))
    addSection(out, "== RECIPES ==", recipeLines(snapshot, now))
    addSection(out, "== GEAR (equipped) ==", gearLines(snapshot))
    addSection(out, "== BAGS ==", bagLines(snapshot))
    addSection(out, "== BANK ==", bankLines(snapshot, now))
    addSection(out, "== MAIL ==", mailLines(snapshot, now))
    addSection(out, "== SPELLS ==", spellLines(snapshot))
    addSection(out, "== ACTION BARS ==", actionBarLines(snapshot))
    addSection(out, "== REPUTATION ==", reputationLines(snapshot))
    addSection(out, "== CURRENCIES ==", currencyLines(snapshot))
    addSection(out, "== LEGACY ==", legacyLines(snapshot))
    addSection(out, "== GROUP AND PET ==", groupAndPetLines(snapshot))
    addSection(out, "== MOUNTS ==", mountLines(snapshot))
    addSection(out, "== RECENT EVENTS ==", historyLines(history or {}, now))
    addSection(out, "== READ ERRORS (the addon could not read these) ==", errorLines(snapshot))
    return table.concat(out, "\n")
end
