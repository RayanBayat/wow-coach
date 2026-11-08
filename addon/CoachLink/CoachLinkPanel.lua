--[[
CoachLinkPanel: the Coach panel (addon 0.8.0).

A window inside the game that shows what your coach wrote (next steps, the latest
answer, who wrote it and when) and has a box to ask a question. Open it with
/coach panel, the minimap's addon list or a key you choose in Options > Keybindings.

How the pieces fit (docs/design.md, "Coach panel"):
  - CoachLink.lua gives us ns.askCoach, ns.openQuestions, ns.myAdvice, ns.say.
  - The advice comes from a file wow-coach wrote outside the game, so every field
    is checked before we show it (see "Reading the advice").
  - The panel never opens in combat, and it only reloads the UI through
    ns.askCoach, when the player clicks Ask or presses Enter in the box.

Rules for this file (docs/plans/coach-panel.md, section 3): no secure templates, no
protected calls, no OnUpdate, no clicking buttons for the player, no chat sending.
Everything happens in reply to an event or to the player's own click.
]]

local _, ns = ...


-------------------------------------------------------------------------------
-- Text the player sees (all of it here, ready for other languages later)
-------------------------------------------------------------------------------

local TEXT = {
    title = "Coach",
    stepsHeader = "Next steps",
    noSteps = "No steps yet.",
    smallerFont = "A-",
    biggerFont = "A+",
    askLabel = "Ask your coach:",
    askButton = "Ask (saves and reloads)",
    youAsked = "You asked: ",
    warningsHeader = "Be careful",
    waiting = "Waiting for your coach: %s. When your coach says the answer is ready, click Show answer.",
    showAnswer = "Show answer (reloads)",
    howTo = "No advice from your coach yet.\n\n"
        .. "Type a question below and press Ask, or ask your coach on the PC. "
        .. "Answers appear here after your next /reload.",
    fromSource = "From %s",
    writtenAgo = "written %s",
    basedOnSave = "based on your save from %s",
    aiCanBeWrong = "AI can be wrong.",
    justNow = "just now",
    minutesAgo = "%d min ago",
    hoursAgo = "%d h ago",
    daysAgo = "%d days ago",
    newAdvice = "your coach has new advice: /coach panel",
    noOpenInCombat = "the Coach panel can't open during a fight.",
    panelError = "Coach panel error in %s: %s",
    bindingHeader = "CoachLink",
    bindingToggle = "Show or hide the Coach panel",
    bindingSave = "Save for the coach (reloads the interface)",
}

-- The key binding names the game looks up (see Bindings.xml).
BINDING_HEADER_COACHLINK = TEXT.bindingHeader
BINDING_NAME_COACHLINK_TOGGLE = TEXT.bindingToggle
BINDING_NAME_COACHLINK_SAVE = TEXT.bindingSave


-------------------------------------------------------------------------------
-- Numbers and limits
-------------------------------------------------------------------------------

local PANEL_NAME = "CoachLinkPanel"

local DEFAULT_WIDTH, DEFAULT_HEIGHT = 460, 520
local MIN_WIDTH, MIN_HEIGHT = 340, 340
local MAX_WIDTH, MAX_HEIGHT = 900, 900
local DEFAULT_FONT_SIZE, MIN_FONT_SIZE, MAX_FONT_SIZE = 13, 8, 24
local FALLBACK_FONT = "Fonts\\FRIZQT__.TTF"

-- How much of the advice file we show. The file comes from outside the game, so
-- we never trust its sizes.
local MAX_STEPS = 10
local MAX_WARNINGS = 10
local MAX_SCANNED = 50          -- list entries looked at, good or bad
local MAX_STEP_BYTES = 300
local MAX_TEXT_BYTES = 4000
local MAX_SHORT_BYTES = 120     -- title, source
local MAX_QUESTION_BYTES = 500

-- The anchor names SetPoint understands. A saved position is only used if its
-- anchors are in this list.
local ANCHORS = {
    TOPLEFT = true, TOP = true, TOPRIGHT = true, LEFT = true, CENTER = true,
    RIGHT = true, BOTTOMLEFT = true, BOTTOM = true, BOTTOMRIGHT = true,
}
local MAX_OFFSET = 10000   -- pixels; larger saved offsets are nonsense

local WINDOW_BACKDROP = {   -- the same dialog look as the copy window
    bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background",
    edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
    tile = true, tileSize = 32, edgeSize = 32,
    insets = { left = 11, right = 12, top = 12, bottom = 11 },
}


-------------------------------------------------------------------------------
-- Saved settings (CoachLinkDB.settings.panel)
-------------------------------------------------------------------------------

-- Keys: point, relPoint, x, y (position), width, height, fontSize, open (was it
-- showing), lastSeenAnswerAt (the newest answer the player has had on screen).

-- True for a real, finite number (not NaN, not infinity).
local function isNumber(value)
    return type(value) == "number" and value == value and value > -math.huge and value < math.huge
end

-- `value` kept between low and high, or `default` if it is not a number.
local function numberBetween(value, low, high, default)
    if not isNumber(value) then
        return default
    end
    return math.max(low, math.min(high, value))
end

-- The saved panel settings if they exist, else an empty table. Creates nothing.
local function savedSettings()
    local db = CoachLinkDB
    local settings = type(db) == "table" and db.settings
    local panelSettings = type(settings) == "table" and settings.panel
    return type(panelSettings) == "table" and panelSettings or {}
end

-- The saved panel settings, created if missing. Only CoachLinkDB.settings.panel is
-- touched; if one of the levels holds something odd we can't save, so we hand back
-- a throwaway table (the panel then just forgets its position).
local function settingsToWrite()
    if CoachLinkDB == nil then
        CoachLinkDB = {}
    end
    if type(CoachLinkDB) ~= "table" then
        return {}
    end
    if CoachLinkDB.settings == nil then
        CoachLinkDB.settings = {}
    end
    if type(CoachLinkDB.settings) ~= "table" then
        return {}
    end
    if CoachLinkDB.settings.panel == nil then
        CoachLinkDB.settings.panel = {}
    end
    if type(CoachLinkDB.settings.panel) ~= "table" then
        return {}
    end
    return CoachLinkDB.settings.panel
end

local function fontSize()
    local size = numberBetween(savedSettings().fontSize, MIN_FONT_SIZE, MAX_FONT_SIZE, DEFAULT_FONT_SIZE)
    return math.floor(size)
end


-------------------------------------------------------------------------------
-- Reading the advice (untrusted: it comes from a file outside the game)
-------------------------------------------------------------------------------

-- The first `limit` bytes of `text`, without cutting a UTF-8 letter in half (a
-- letter is a lead byte plus 0-3 continuation bytes, which are 128-191).
local function cutText(text, limit)
    if #text <= limit then
        return text
    end
    local cut = string.sub(text, 1, limit)
    local last = #cut
    while last > 0 and string.byte(cut, last) >= 128 and string.byte(cut, last) < 192 do
        last = last - 1
    end
    if last > 0 then
        local lead = string.byte(cut, last)
        local size = (lead >= 240 and 4) or (lead >= 224 and 3) or (lead >= 192 and 2) or 1
        if last + size - 1 > #cut then
            cut = string.sub(cut, 1, last - 1)
        end
    end
    return cut
end

-- A cleaned string, or nil if `value` is not a usable string. In WoW text "|" starts
-- a color code or a link, and "||" shows one "|". We drop every single "|" (so the
-- file can't color or link anything) and keep the doubled ones.
local function cleanText(value, limit)
    if type(value) ~= "string" then
        return nil
    end
    local text = cutText(value, limit)
    text = text:gsub("\1", "")      -- \1 is our stand-in below, so remove real ones first
    text = text:gsub("||", "\1")
    text = text:gsub("|", "")
    text = text:gsub("\1", "||")
    text = strtrim(text)
    if text == "" then
        return nil
    end
    return text
end

-- A new list with the usable strings of `list` (at most `count`, each cut to `limit`).
local function cleanList(list, count, limit)
    local clean = {}
    if type(list) ~= "table" then
        return clean
    end
    for index = 1, MAX_SCANNED do
        if #clean >= count then
            break
        end
        local text = cleanText(list[index], limit)
        if text then
            table.insert(clean, text)
        end
    end
    return clean
end

-- A time stamp (seconds since 1970) or nil.
local function cleanTime(value)
    if isNumber(value) and value > 0 and value < 1e11 then
        return value
    end
    return nil
end

-- The newest answer in this character's advice: the one with the biggest
-- answeredAt, and among equals the last. Returns a cleaned copy, or nil.
local function newestAnswer(mine)
    if type(mine) ~= "table" or type(mine.answers) ~= "table" then
        return nil
    end
    local best, bestTime
    for index = 1, MAX_SCANNED do
        local answer = mine.answers[index]
        if type(answer) == "table" then
            local answeredAt = cleanTime(answer.answeredAt) or 0
            if not best or answeredAt >= bestTime then
                best, bestTime = answer, answeredAt
            end
        end
    end
    if not best then
        return nil
    end
    return {
        title = cleanText(best.title, MAX_SHORT_BYTES),
        text = cleanText(best.text, MAX_TEXT_BYTES),
        source = cleanText(best.source, MAX_SHORT_BYTES),
        question = cleanText(best.question, MAX_QUESTION_BYTES),
        steps = cleanList(best.steps, MAX_STEPS, MAX_STEP_BYTES),
        warnings = cleanList(best.warnings, MAX_WARNINGS, MAX_STEP_BYTES),
        answeredAt = cleanTime(best.answeredAt),
    }
end

-- The steps to show: the newest answer's, else the plan's.
local function stepsToShow(answer, mine)
    if answer and #answer.steps > 0 then
        return answer.steps
    end
    if type(mine) == "table" and type(mine.plan) == "table" then
        return cleanList(mine.plan.steps, MAX_STEPS, MAX_STEP_BYTES)
    end
    return {}
end

-- The questions that wait for an answer, as cleaned strings.
local function waitingQuestions()
    local texts = {}
    for _, question in ipairs(ns.openQuestions()) do
        local text = type(question) == "table" and cleanText(question.text, MAX_QUESTION_BYTES)
        if text then
            table.insert(texts, text)
        end
    end
    return texts
end


-------------------------------------------------------------------------------
-- Building the texts (pure: they only turn data into strings)
-------------------------------------------------------------------------------

-- "1. first step" lines, or the "no steps" text.
local function stepsText(steps)
    if #steps == 0 then
        return TEXT.noSteps
    end
    local lines = {}
    for number, step in ipairs(steps) do
        table.insert(lines, number .. ". " .. step)
    end
    return table.concat(lines, "\n")
end

-- The scrolling part: the question, the answer, warnings, then waiting questions.
local function bodyText(answer, waiting)
    local parts = {}
    if not answer then
        table.insert(parts, TEXT.howTo)
    else
        if answer.question then
            table.insert(parts, TEXT.youAsked .. answer.question)
        end
        if answer.title then
            table.insert(parts, answer.title)
        end
        if answer.text then
            table.insert(parts, answer.text)
        end
        if #answer.warnings > 0 then
            local lines = { TEXT.warningsHeader }
            for _, warning in ipairs(answer.warnings) do
                table.insert(lines, "- " .. warning)
            end
            table.insert(parts, table.concat(lines, "\n"))
        end
    end
    for _, question in ipairs(waiting) do
        table.insert(parts, string.format(TEXT.waiting, question))
    end
    return table.concat(parts, "\n\n")
end

-- "5 min ago", "2 h ago", ...
local function ageText(seconds)
    local minutes = math.floor(math.max(0, seconds) / 60)
    if minutes < 1 then
        return TEXT.justNow
    elseif minutes < 60 then
        return string.format(TEXT.minutesAgo, minutes)
    elseif minutes < 60 * 24 then
        return string.format(TEXT.hoursAgo, math.floor(minutes / 60))
    end
    return string.format(TEXT.daysAgo, math.floor(minutes / (60 * 24)))
end

-- The line under the answer: who wrote it, when, from which save, and the warning.
-- Empty when there is nothing to describe.
local function footerText(answer, mine, steps, now)
    if not answer and #steps == 0 then
        return ""
    end
    local pieces = {}
    if answer and answer.source then
        table.insert(pieces, string.format(TEXT.fromSource, answer.source))
    end
    if answer and answer.answeredAt then
        table.insert(pieces, string.format(TEXT.writtenAgo, ageText(now - answer.answeredAt)))
    end
    local savedAt = type(mine) == "table" and cleanTime(mine.basedOnSave)
    if savedAt then
        table.insert(pieces, string.format(TEXT.basedOnSave, date("%H:%M", savedAt)))
    end
    local line = table.concat(pieces, ", ")
    if line ~= "" then
        line = line .. ". "
    end
    return line .. TEXT.aiCanBeWrong
end

-- The newest answer's time, or nil (used for "new advice" and "seen").
local function newestAnswerTime()
    local answer = newestAnswer(ns.myAdvice())
    return answer and answer.answeredAt
end


-------------------------------------------------------------------------------
-- The window
-------------------------------------------------------------------------------

local panel                 -- the window; created the first time it is opened
local reopenAfterCombat = false
local hidingForCombat = false   -- true while WE hide it, so OnHide doesn't call it "closed"

local function playerIsInCombat()
    return InCombatLockdown() and true or false
end

-- Save where the window is and how big. Called after the player drags or resizes it.
local function saveLook()
    if not panel then
        return
    end
    local point, _, relPoint, x, y = panel:GetPoint(1)
    local settings = settingsToWrite()
    if point and ANCHORS[point] and ANCHORS[relPoint] and isNumber(x) and isNumber(y) then
        settings.point, settings.relPoint, settings.x, settings.y = point, relPoint, x, y
    end
    settings.width = panel:GetWidth()
    settings.height = panel:GetHeight()
end

-- Put the window where it was (or in the middle) and at its saved size.
local function restoreLook(frame)
    local saved = savedSettings()
    frame:SetSize(
        numberBetween(saved.width, MIN_WIDTH, MAX_WIDTH, DEFAULT_WIDTH),
        numberBetween(saved.height, MIN_HEIGHT, MAX_HEIGHT, DEFAULT_HEIGHT)
    )
    frame:ClearAllPoints()
    local x = numberBetween(saved.x, -MAX_OFFSET, MAX_OFFSET, nil)
    local y = numberBetween(saved.y, -MAX_OFFSET, MAX_OFFSET, nil)
    if ANCHORS[saved.point] and ANCHORS[saved.relPoint] and x and y then
        frame:SetPoint(saved.point, UIParent, saved.relPoint, x, y)
    else
        frame:SetPoint("CENTER")
    end
end

-- Make the text fit the window. Runs when the window or the text changes size.
local function layoutText()
    if not panel then
        return
    end
    local innerWidth = math.max(100, panel:GetWidth() - 40)
    panel.steps:SetWidth(innerWidth)
    panel.footer:SetWidth(innerWidth)
    panel.status:SetWidth(math.max(60, innerWidth - 180))   -- leaves room for the Show answer button
    local scrollWidth = math.max(100, panel.scroll:GetWidth())
    panel.content:SetWidth(scrollWidth)
    panel.body:SetWidth(scrollWidth)
    panel.content:SetHeight(panel.body:GetStringHeight() + 8)
end

-- Use the saved text size on every text in the panel.
local function applyFontSize()
    if not panel then
        return
    end
    local size = fontSize()
    local ok, path = pcall(function() return (GameFontHighlight:GetFont()) end)
    local fontPath = (ok and path) or FALLBACK_FONT
    panel.steps:SetFont(fontPath, size, "")
    panel.body:SetFont(fontPath, size, "")
    panel.status:SetFont(fontPath, size, "")
    panel.footer:SetFont(fontPath, math.max(MIN_FONT_SIZE, size - 2), "")
    layoutText()
end

-- Fill the panel with the current advice and questions.
local function refresh()
    if not panel then
        return
    end
    local mine = ns.myAdvice()
    local answer = newestAnswer(mine)
    local steps = stepsToShow(answer, mine)
    panel.steps:SetText(stepsText(steps))
    local waiting = waitingQuestions()
    panel.body:SetText(bodyText(answer, waiting))
    panel.showAnswer:SetShown(#waiting > 0)
    panel.footer:SetText(footerText(answer, mine, steps, time()))
    panel.scroll:SetVerticalScroll(0)
    layoutText()
end

-- The Ask box and button only work out of combat.
local function updateAskEnabled()
    if panel then
        local canClick = not playerIsInCombat()
        panel.askButton:SetEnabled(canClick)
        panel.showAnswer:SetEnabled(canClick)
    end
end

-- Reload the UI so the game reads the answer wow-coach wrote. Only from the player's
-- click, and never in combat.
local function showAnswerFromClick()
    if playerIsInCombat() then
        return
    end
    ReloadUI()
end

-- Ask the coach with what is typed in the box. ns.askCoach saves the question and
-- reloads the UI; this runs only from the player's click or Enter.
local function askFromBox()
    panel.status:SetText("")
    local asked, reason = ns.askCoach(panel.askBox:GetText())
    if not asked then
        panel.status:SetText(reason or "")
        layoutText()
    end
end

local function changeFontSize(change)
    local size = math.floor(numberBetween(fontSize() + change, MIN_FONT_SIZE, MAX_FONT_SIZE, DEFAULT_FONT_SIZE))
    settingsToWrite().fontSize = size
    applyFontSize()
end

-- Remember that the player has seen the newest answer (so we stop announcing it).
local function markAnswerSeen()
    local answeredAt = newestAnswerTime()
    if answeredAt and answeredAt > numberBetween(savedSettings().lastSeenAnswerAt, 0, 1e11, 0) then
        settingsToWrite().lastSeenAnswerAt = answeredAt
    end
end

local function onShow()
    settingsToWrite().open = true
    panel.status:SetText("")
    updateAskEnabled()
    refresh()
    markAnswerSeen()
end

local function onHide()
    panel.askBox:ClearFocus()
    if not hidingForCombat then
        settingsToWrite().open = false   -- the player closed it
    end
end

-- The small buttons and the text in the title row.
local function createTitleRow(frame)
    local closeButton = CreateFrame("Button", nil, frame, "UIPanelCloseButton")
    closeButton:SetPoint("TOPRIGHT", -6, -6)

    local title = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    title:SetPoint("TOPLEFT", 20, -18)
    title:SetText(TEXT.title)

    local bigger = CreateFrame("Button", PANEL_NAME .. "FontBigger", frame, "UIPanelButtonTemplate")
    bigger:SetSize(28, 22)
    bigger:SetPoint("TOPRIGHT", -44, -14)
    bigger:SetText(TEXT.biggerFont)
    bigger:SetScript("OnClick", function() changeFontSize(1) end)

    local smaller = CreateFrame("Button", PANEL_NAME .. "FontSmaller", frame, "UIPanelButtonTemplate")
    smaller:SetSize(28, 22)
    smaller:SetPoint("RIGHT", bigger, "LEFT", -4, 0)
    smaller:SetText(TEXT.smallerFont)
    smaller:SetScript("OnClick", function() changeFontSize(-1) end)
end

-- Next steps, the scrolling answer and the footer.
local function createReadingArea(frame)
    local header = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    header:SetPoint("TOPLEFT", 20, -48)
    header:SetText(TEXT.stepsHeader)

    local steps = frame:CreateFontString(PANEL_NAME .. "Steps", "OVERLAY", "GameFontHighlight")
    steps:SetPoint("TOPLEFT", header, "BOTTOMLEFT", 0, -4)
    steps:SetJustifyH("LEFT")
    steps:SetJustifyV("TOP")

    -- The answer can be long, so it sits in a scroll frame (same template as the copy window).
    local scroll = CreateFrame("ScrollFrame", PANEL_NAME .. "Scroll", frame, "UIPanelScrollFrameTemplate")
    scroll:SetPoint("TOPLEFT", steps, "BOTTOMLEFT", 0, -12)
    scroll:SetPoint("BOTTOMRIGHT", -36, 122)
    local content = CreateFrame("Frame", PANEL_NAME .. "Content", scroll)
    content:SetSize(100, 10)
    scroll:SetScrollChild(content)
    local body = content:CreateFontString(PANEL_NAME .. "Body", "OVERLAY", "GameFontHighlight")
    body:SetPoint("TOPLEFT")
    body:SetJustifyH("LEFT")
    body:SetJustifyV("TOP")
    scroll:SetScript("OnSizeChanged", layoutText)

    local footer = frame:CreateFontString(PANEL_NAME .. "Footer", "OVERLAY", "GameFontNormalSmall")
    footer:SetPoint("BOTTOMLEFT", 20, 76)
    footer:SetHeight(40)
    footer:SetJustifyH("LEFT")
    footer:SetJustifyV("TOP")

    frame.steps, frame.scroll, frame.content, frame.body, frame.footer = steps, scroll, content, body, footer
end

-- The question box, the Ask button and the line that says why an ask was refused.
local function createAskRow(frame)
    local status = frame:CreateFontString(PANEL_NAME .. "Status", "OVERLAY", "GameFontNormal")
    status:SetPoint("BOTTOMLEFT", 20, 58)
    status:SetJustifyH("LEFT")

    local askButton = CreateFrame("Button", PANEL_NAME .. "AskButton", frame, "UIPanelButtonTemplate")
    askButton:SetSize(170, 26)
    askButton:SetPoint("BOTTOMRIGHT", -24, 24)
    askButton:SetText(TEXT.askButton)
    askButton:SetScript("OnClick", askFromBox)

    local askBox = CreateFrame("EditBox", PANEL_NAME .. "AskBox", frame, "InputBoxTemplate")
    askBox:SetHeight(26)
    askBox:SetPoint("BOTTOMLEFT", 28, 24)
    askBox:SetPoint("BOTTOMRIGHT", askButton, "BOTTOMLEFT", -8, 0)
    askBox:SetAutoFocus(false)
    askBox:SetMaxLetters(500)
    askBox:SetScript("OnEnterPressed", askFromBox)
    askBox:SetScript("OnEscapePressed", function(box) box:ClearFocus() end)

    -- Shown only while a question waits for its answer (see refresh).
    local showAnswer = CreateFrame("Button", PANEL_NAME .. "ShowAnswer", frame, "UIPanelButtonTemplate")
    showAnswer:SetSize(170, 22)
    showAnswer:SetPoint("BOTTOMRIGHT", -24, 54)
    showAnswer:SetText(TEXT.showAnswer)
    showAnswer:SetScript("OnClick", showAnswerFromClick)
    showAnswer:Hide()

    frame.status, frame.askButton, frame.askBox, frame.showAnswer = status, askButton, askBox, showAnswer
end

-- A small grip in the bottom right corner. Dragging it resizes the window (the
-- same textures Blizzard's own resize buttons use).
local function createResizeGrip(frame)
    local grip = CreateFrame("Button", PANEL_NAME .. "Resize", frame)
    grip:SetSize(16, 16)
    grip:SetPoint("BOTTOMRIGHT", -6, 6)
    grip:SetNormalTexture("Interface\\ChatFrame\\UI-ChatIM-SizeGrabber-Up")
    grip:SetHighlightTexture("Interface\\ChatFrame\\UI-ChatIM-SizeGrabber-Highlight")
    grip:SetPushedTexture("Interface\\ChatFrame\\UI-ChatIM-SizeGrabber-Down")
    grip:SetScript("OnMouseDown", function() frame:StartSizing("BOTTOMRIGHT", true) end)
    grip:SetScript("OnMouseUp", function()
        frame:StopMovingOrSizing()
        saveLook()
    end)
end

-- Build the window (once). Returns it.
local function createPanel()
    local frame = CreateFrame("Frame", PANEL_NAME, UIParent, "BackdropTemplate")
    frame:SetFrameStrata("DIALOG")
    frame:SetBackdrop(WINDOW_BACKDROP)
    frame:SetClampedToScreen(true)      -- can't be dragged off screen
    frame:SetMovable(true)
    frame:SetResizable(true)
    frame:SetResizeBounds(MIN_WIDTH, MIN_HEIGHT, MAX_WIDTH, MAX_HEIGHT)
    frame:EnableMouse(true)
    frame:RegisterForDrag("LeftButton")
    frame:SetScript("OnDragStart", frame.StartMoving)
    frame:SetScript("OnDragStop", function()
        frame:StopMovingOrSizing()
        saveLook()
    end)
    restoreLook(frame)

    createTitleRow(frame)
    createReadingArea(frame)
    createAskRow(frame)
    createResizeGrip(frame)

    panel = frame   -- the helpers below use `panel`
    frame:SetScript("OnShow", onShow)
    frame:SetScript("OnHide", onHide)
    frame:SetScript("OnSizeChanged", layoutText)
    table.insert(UISpecialFrames, PANEL_NAME)   -- Esc closes it
    frame:Hide()
    applyFontSize()
    return frame
end

-- Show the panel, unless the player is in combat.
local function openPanel()
    if playerIsInCombat() then
        ns.say(TEXT.noOpenInCombat)
        return
    end
    if not panel then
        local ok, err = pcall(createPanel)
        if not ok then
            panel = nil   -- try again next time
            ns.say(string.format(TEXT.panelError, "createPanel", tostring(err)))
            return
        end
    end
    panel:Show()
end

local function togglePanel()
    if panel and panel:IsShown() then
        panel:Hide()
    else
        openPanel()
    end
end

ns.togglePanel = togglePanel

-- Clicking CoachLink in the minimap's addon list (the .toc names this function).
function CoachLink_OnAddonCompartmentClick()
    togglePanel()
end


-------------------------------------------------------------------------------
-- Events: login, and combat starting and ending
-------------------------------------------------------------------------------

local handlers = {}
local announcedThisSession = false

-- Hide for the fight and remember to bring it back.
function handlers.PLAYER_REGEN_DISABLED()
    if panel and panel:IsShown() then
        reopenAfterCombat = true
        hidingForCombat = true
        panel:Hide()
        hidingForCombat = false
    end
    updateAskEnabled()
end

function handlers.PLAYER_REGEN_ENABLED()
    updateAskEnabled()
    if reopenAfterCombat then
        reopenAfterCombat = false
        openPanel()
    end
end

-- Once per login or reload: bring the panel back if it was open, else say if the
-- coach has written something new.
function handlers.PLAYER_ENTERING_WORLD()
    if announcedThisSession then
        return   -- later loading screens (instances, etc.) are not a new login
    end
    announcedThisSession = true
    if savedSettings().open == true then
        if playerIsInCombat() then
            reopenAfterCombat = true
        else
            openPanel()
            return   -- it shows the answer itself
        end
    end
    local answeredAt = newestAnswerTime()
    if answeredAt and answeredAt > numberBetween(savedSettings().lastSeenAnswerAt, 0, 1e11, 0) then
        ns.say(TEXT.newAdvice)
    end
end

local eventFrame = CreateFrame("Frame", PANEL_NAME .. "Events")
for eventName in pairs(handlers) do
    -- An event name the game doesn't know would raise an error: skip it quietly.
    pcall(eventFrame.RegisterEvent, eventFrame, eventName)
end
eventFrame:SetScript("OnEvent", function(_, eventName, ...)
    local ok, err = pcall(handlers[eventName], ...)
    if not ok then
        ns.say(string.format(TEXT.panelError, eventName, tostring(err)))
    end
end)
