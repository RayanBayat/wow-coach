--[[
Test the Coach panel (CoachLinkPanel.lua) outside the game, with a fake WoW API.

    luajit addon/tests/run_panel_test.lua

What it does:
  1. Defines a small fake game: frames that remember what the panel did to them,
     a clock, a chat log and a /reload counter.
  2. Loads CoachLinkText.lua, CoachLink.lua and CoachLinkPanel.lua in the .toc
     order, like WoW does.
  3. Opens, closes, asks, fights, resizes and feeds it broken advice files, and
     checks what the player would see.

It does NOT prove the real game behaves like these fakes (see the "check in game"
list in the panel's report). The look of the panel can only be judged in game.
]]

local ADDON_FILES = {
    "addon/CoachLink/CoachLinkText.lua",
    "addon/CoachLink/CoachLink.lua",
    "addon/CoachLink/CoachLinkPanel.lua",
}
local FAKE_NOW = 1793995200  -- a fixed time, so the output is the same every run
local ANSWER_AT = FAKE_NOW - 5 * 60  -- an answer written 5 minutes ago

local failures = 0

local function check(condition, description)
    if condition then
        io.stdout:write("ok   " .. description .. "\n")
    else
        io.stdout:write("FAIL " .. description .. "\n")
        failures = failures + 1
    end
end

-- True when `haystack` contains `needle` as plain text (not a pattern).
local function has(haystack, needle)
    return type(haystack) == "string" and haystack:find(needle, 1, true) ~= nil
end


-------------------------------------------------------------------------------
-- The fake game
-------------------------------------------------------------------------------

local eventHandler   -- the OnEvent script CoachLink.lua registers (it does not use ours)
local panelEvents    -- the events the panel registered, name -> true
local panelHandler   -- the panel's own OnEvent script
local chat           -- lines printed in the chat window
local reloads        -- how many times ReloadUI was called
local inCombat       -- what InCombatLockdown answers
local framesCreated  -- every frame made with CreateFrame, in order

local function newFrame(frameType, name, parent, template)
    local frame = {
        type = frameType, name = name, parent = parent, template = template,
        scripts = {}, events = {}, points = {}, shown = false, enabled = true,
        width = 100, height = 20, text = "", fontSize = nil,
    }
    return frame
end

local frameMethods = {
    RegisterEvent = function(self, eventName) self.events[eventName] = true end,
    SetScript = function(self, scriptName, handler) self.scripts[scriptName] = handler end,
    GetScript = function(self, scriptName) return self.scripts[scriptName] end,
    SetText = function(self, text) self.text = text end,
    GetText = function(self) return self.text end,
    Show = function(self)
        local was = self.shown
        self.shown = true
        if not was and self.scripts.OnShow then self.scripts.OnShow(self) end
    end,
    Hide = function(self)
        local was = self.shown
        self.shown = false
        if was and self.scripts.OnHide then self.scripts.OnHide(self) end
    end,
    IsShown = function(self) return self.shown end,
    SetEnabled = function(self, enabled) self.enabled = enabled and true or false end,
    Enable = function(self) self.enabled = true end,
    Disable = function(self) self.enabled = false end,
    IsEnabled = function(self) return self.enabled end,
    SetSize = function(self, width, height) self.width, self.height = width, height end,
    SetWidth = function(self, width) self.width = width end,
    SetHeight = function(self, height) self.height = height end,
    GetWidth = function(self) return self.width end,
    GetHeight = function(self) return self.height end,
    ClearAllPoints = function(self) self.points = {} end,
    SetPoint = function(self, point, relativeTo, relativePoint, x, y)
        -- SetPoint("CENTER"), SetPoint("TOPLEFT", 22, -20) and the long form are all legal.
        if type(relativeTo) == "number" then
            x, y, relativeTo, relativePoint = relativeTo, relativePoint, nil, nil
        end
        table.insert(self.points, { point, relativeTo, relativePoint or point, x or 0, y or 0 })
    end,
    GetPoint = function(self, index)
        local p = self.points[index or 1]
        if not p then return nil end
        return p[1], p[2], p[3], p[4], p[5]
    end,
    SetFont = function(self, path, size) self.fontPath, self.fontSize = path, size end,
    GetFont = function(self) return self.fontPath or "Fonts\\Fake.ttf", self.fontSize or 12, "" end,
    GetStringHeight = function(self) return 14 * (1 + select(2, tostring(self.text):gsub("\n", ""))) end,
    SetResizeBounds = function(self, minW, minH, maxW, maxH) self.resizeBounds = { minW, minH, maxW, maxH } end,
    StartSizing = function(self, point) self.sizing = point end,
    StopMovingOrSizing = function(self) self.sizing = nil end,
    SetFocus = function(self) self.focused = true end,
    ClearFocus = function(self) self.focused = false end,
    HasFocus = function(self) return self.focused == true end,
    CreateFontString = function(self, name, _, template)
        local fontString = newFrame("FontString", name, self, template)
        table.insert(framesCreated, fontString)
        if name then _G[name] = fontString end
        return setmetatable(fontString, getmetatable(self))
    end,
}
local frameLook = {
    __index = function(_, methodName)
        return frameMethods[methodName] or function() end
    end,
}

local function installFakeGame()
    for name in pairs(_G) do
        if type(name) == "string" and name:find("^CoachLink") then
            _G[name] = nil   -- frames and functions of the previous session
        end
    end
    CoachLinkDB = nil
    CoachLinkAdvice = nil
    framesCreated = {}
    chat = {}
    reloads = 0
    inCombat = false
    panelHandler = nil
    SlashCmdList = {}
    UISpecialFrames = {}
    UIParent = setmetatable(newFrame("Frame", "UIParent"), frameLook)
    UIParent.shown = true

    print = function(message) table.insert(chat, message) end
    time = function() return FAKE_NOW end
    date = os.date
    strtrim = function(text) return (text:gsub("^%s+", ""):gsub("%s+$", "")) end
    UnitName = function() return "Testchar" end
    GetRealmName = function() return "Testrealm" end
    InCombatLockdown = function() return inCombat end
    GameFontHighlight = setmetatable(newFrame("Font", "GameFontHighlight"), frameLook)
    ChatFontNormal = {}
    hooksecurefunc = function() end

    CreateFrame = function(frameType, name, parent, template)
        local frame = setmetatable(newFrame(frameType, name, parent, template), frameLook)
        table.insert(framesCreated, frame)
        if name then _G[name] = frame end
        return frame
    end
    -- CoachLink.lua's own snapshot code is not under test here: give it a ReloadUI
    -- that only counts, and no events to save from.
    ReloadUI = function() reloads = reloads + 1 end
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

-- The panel's own event frame (CoachLink.lua has another one, for the snapshot).
local function findPanelEventFrame()
    return CoachLinkPanelEvents
end

-- Start a fresh game session with the panel loaded. Returns the shared table.
local function startSession()
    installFakeGame()
    local namespace = loadAddon()
    local eventFrame = findPanelEventFrame()
    panelHandler = eventFrame and eventFrame.scripts.OnEvent
    panelEvents = eventFrame and eventFrame.events
    return namespace
end

local function fire(eventName, ...)
    assert(panelHandler, "the panel registered no event handler")
    panelHandler(nil, eventName, ...)
end

local function lastChat()
    return chat[#chat]
end

local function chatHas(needle)
    for _, line in ipairs(chat) do
        if has(line, needle) then return true end
    end
    return false
end

local function count(needle)
    local found = 0
    for _, line in ipairs(chat) do
        if has(line, needle) then found = found + 1 end
    end
    return found
end

local function advice(overrides)
    local answer = {
        answeredAt = ANSWER_AT, title = "Next steps", source = "Claude Code coach",
        steps = { "Turn in Fields of Grief in Brill.", "Buy a Hearthstone." },
        text = "You are close to level 8.", warnings = { "Do not pull the Scarlet patrol." },
        questionId = "1-1", question = "What should I do next?", askedAt = ANSWER_AT - 30,
    }
    for key, value in pairs(overrides or {}) do answer[key] = value end
    return {
        formatVersion = 1,
        characters = { ["Testchar-Testrealm"] = {
            basedOnSave = FAKE_NOW - 600,
            answers = { answer },
            plan = { goal = "Level 20", steps = { "Plan step one", "Plan step two" }, updatedAt = ANSWER_AT },
        } },
    }
end

local function panel() return CoachLinkPanel end
local function stepsText() return CoachLinkPanelSteps.text end
local function bodyText() return CoachLinkPanelBody.text end
local function footerText() return CoachLinkPanelFooter.text end

-- Type `text` in the ask box and click the button, like the player.
local function typeAndClick(text)
    CoachLinkPanelAskBox:SetText(text)
    CoachLinkPanelAskButton.scripts.OnClick(CoachLinkPanelAskButton)
end


-------------------------------------------------------------------------------
-- Test 1: loading, toggling, Esc
-------------------------------------------------------------------------------

local coach = startSession()
check(type(coach.togglePanel) == "function", "the panel sets ns.togglePanel")
check(panelEvents and panelEvents.PLAYER_REGEN_DISABLED and panelEvents.PLAYER_REGEN_ENABLED
    and panelEvents.PLAYER_ENTERING_WORLD, "the panel listens to combat start, combat end and login")
check(CoachLinkPanel == nil or not CoachLinkPanel.shown, "nothing is shown before the player asks")

coach.togglePanel()
check(panel() and panel().shown == true, "toggling opens the panel")
coach.togglePanel()
check(panel().shown == false, "toggling again closes it")
coach.togglePanel()
local escapes = 0
for _, name in ipairs(UISpecialFrames) do
    if name == "CoachLinkPanel" then escapes = escapes + 1 end
end
check(escapes == 1, "Esc closes the panel (listed once in UISpecialFrames)")
check(panel().resizeBounds ~= nil and panel().resizeBounds[1] > 0, "the panel has a minimum size")
check(CoachLinkPanelResize ~= nil and CoachLinkPanelResize.scripts.OnMouseDown ~= nil,
    "the panel has a resize grip")

local usesOnUpdate = false
for _, frame in ipairs(framesCreated) do
    if frame.scripts.OnUpdate then usesOnUpdate = true end
end
check(not usesOnUpdate, "no frame uses OnUpdate")

CoachLinkPanelResize.scripts.OnMouseDown(CoachLinkPanelResize)
check(panel().sizing == "BOTTOMRIGHT", "the grip starts resizing from the bottom right")
CoachLinkPanelResize.scripts.OnMouseUp(CoachLinkPanelResize)
check(rawget(panel(), "sizing") == nil, "letting go stops resizing")


-------------------------------------------------------------------------------
-- Test 2: no advice, then steps from an answer, then the plan fallback
-------------------------------------------------------------------------------

check(has(bodyText(), "ask") and has(bodyText(), "/reload"),
    "with no advice the panel explains how to ask and that answers need a /reload")
check(has(stepsText(), "No steps"), "with no advice there are no steps")

CoachLinkAdvice = advice()
panel():Hide()
coach.togglePanel()
check(has(stepsText(), "1. Turn in Fields of Grief in Brill.")
    and has(stepsText(), "2. Buy a Hearthstone."), "the answer's steps are numbered")
check(not has(stepsText(), "Plan step"), "the plan is not used when the answer has steps")
check(has(bodyText(), "You asked: What should I do next?"), "the question is shown above the answer")
check(has(bodyText(), "Next steps") and has(bodyText(), "You are close to level 8."),
    "the answer's title and text are shown")
check(has(bodyText(), "Do not pull the Scarlet patrol."), "the answer's warnings are shown")
check(has(footerText(), "Claude Code coach"), "the footer names the source")
check(has(footerText(), "5 min ago"), "the footer says how long ago the answer was written")
check(has(footerText(), "based on your save from " .. os.date("%H:%M", FAKE_NOW - 600)),
    "the footer says which save the answer is based on")
check(has(footerText(), "AI can be wrong."), "the footer warns that AI can be wrong")

CoachLinkAdvice = advice({ steps = {} })
panel():Hide()
coach.togglePanel()
check(has(stepsText(), "1. Plan step one"), "with no answer steps, the plan's steps are used")

-- Only a plan, no answers at all.
CoachLinkAdvice = advice()
CoachLinkAdvice.characters["Testchar-Testrealm"].answers = nil
panel():Hide()
coach.togglePanel()
check(has(stepsText(), "1. Plan step one"), "a plan alone still shows its steps")


-------------------------------------------------------------------------------
-- Test 3: waiting questions
-------------------------------------------------------------------------------

coach = startSession()
CoachLinkDB = { characters = { ["Testchar-Testrealm"] = { questions = {
    { id = "9-1", text = "Where is Brill?", askedAt = FAKE_NOW - 60 },
} } } }
coach.togglePanel()
check(has(bodyText(), "Waiting for your coach: Where is Brill?"), "an unanswered question shows as waiting")

CoachLinkAdvice = advice({ questionId = "9-1" })
panel():Hide()
coach.togglePanel()
check(not has(bodyText(), "Waiting for your coach"), "an answered question is not shown as waiting")


-------------------------------------------------------------------------------
-- Test 4: asking
-------------------------------------------------------------------------------

coach = startSession()
coach.togglePanel()
typeAndClick("  What next?  ")
check(reloads == 1, "the Ask button asks the coach (and reloads the UI)")
check(CoachLinkDB.characters["Testchar-Testrealm"].questions[1].text == "What next?",
    "the question is saved through askCoach")

reloads = 0
CoachLinkPanelAskBox:SetText("Second question")
CoachLinkPanelAskBox.scripts.OnEnterPressed(CoachLinkPanelAskBox)
check(reloads == 1, "Enter in the box also asks")

typeAndClick("   ")
check(reloads == 1 and has(CoachLinkPanelStatus.text, "type a question"),
    "an empty question is refused and the reason is shown in the panel")

CoachLinkPanelAskBox.focused = true
CoachLinkPanelAskBox.scripts.OnEscapePressed(CoachLinkPanelAskBox)
check(CoachLinkPanelAskBox.focused == false and panel().shown == true,
    "Esc in the box only clears the focus")
check(CoachLinkPanelAskButton.text:find("Ask (saves and reloads)", 1, true) ~= nil,
    "the button says that asking saves and reloads")


-------------------------------------------------------------------------------
-- Test 5: combat
-------------------------------------------------------------------------------

coach = startSession()
coach.togglePanel()
inCombat = true
fire("PLAYER_REGEN_DISABLED")
check(panel().shown == false, "the panel hides when combat starts")
check(CoachLinkPanelAskButton.enabled == false, "Ask is disabled in combat")
coach.togglePanel()
check(panel().shown == false, "the panel never opens in combat")
check(chatHas("fight"), "the player is told why it did not open")
inCombat = false
fire("PLAYER_REGEN_ENABLED")
check(panel().shown == true, "the panel comes back after the fight")
check(CoachLinkPanelAskButton.enabled == true, "Ask works again after the fight")

-- A panel that was closed stays closed after a fight.
panel():Hide()
inCombat = true
fire("PLAYER_REGEN_DISABLED")
inCombat = false
fire("PLAYER_REGEN_ENABLED")
check(panel().shown == false, "a closed panel does not pop up after a fight")

-- Player closed it, then a fight: still closed (the memory of "was open" is not stale).
coach.togglePanel()
fire("PLAYER_REGEN_DISABLED")
fire("PLAYER_REGEN_ENABLED")
panel():Hide()
fire("PLAYER_REGEN_DISABLED")
fire("PLAYER_REGEN_ENABLED")
check(panel().shown == false, "closing after a fight is remembered")

-- Asking in combat is refused with the reason, even if the button were clicked.
coach.togglePanel()
inCombat = true
typeAndClick("Help")
check(reloads == 0 and has(CoachLinkPanelStatus.text, "fight"), "an ask in combat is refused with a reason")
inCombat = false


-------------------------------------------------------------------------------
-- Test 6: remembered position, size, font size and "open"
-------------------------------------------------------------------------------

coach = startSession()
CoachLinkDB = { formatVersion = 3, characters = { ["Other-Realm"] = { keep = "me" } } }
coach.togglePanel()
panel():ClearAllPoints()
panel():SetPoint("TOPLEFT", UIParent, "BOTTOMLEFT", 120, 640)
panel():SetSize(500, 420)
panel().scripts.OnDragStop(panel())
local saved = CoachLinkDB.settings and CoachLinkDB.settings.panel
check(saved and saved.point == "TOPLEFT" and saved.x == 120 and saved.y == 640,
    "the position is saved after dragging")
CoachLinkPanelResize.scripts.OnMouseUp(CoachLinkPanelResize)
check(saved.width == 500 and saved.height == 420, "the size is saved after resizing")
check(saved.open == true, "'open' is saved")
check(CoachLinkDB.formatVersion == 3 and CoachLinkDB.characters["Other-Realm"].keep == "me",
    "other saved keys are left alone")

local before = CoachLinkPanelBody.fontSize
CoachLinkPanelFontBigger.scripts.OnClick(CoachLinkPanelFontBigger)
check(CoachLinkPanelBody.fontSize == before + 1 and saved.fontSize == before + 1,
    "A+ makes the text bigger and saves it")
CoachLinkPanelFontSmaller.scripts.OnClick(CoachLinkPanelFontSmaller)
CoachLinkPanelFontSmaller.scripts.OnClick(CoachLinkPanelFontSmaller)
check(CoachLinkPanelBody.fontSize == before - 1, "A- makes the text smaller")
for _ = 1, 40 do CoachLinkPanelFontSmaller.scripts.OnClick(CoachLinkPanelFontSmaller) end
check(CoachLinkPanelBody.fontSize >= 8, "the text cannot get unreadably small")
for _ = 1, 60 do CoachLinkPanelFontBigger.scripts.OnClick(CoachLinkPanelFontBigger) end
check(CoachLinkPanelBody.fontSize <= 24, "the text cannot get absurdly big")
CoachLinkPanelFontSmaller.scripts.OnClick(CoachLinkPanelFontSmaller)
local savedFont = saved.fontSize

-- A new session (a /reload): the panel comes back where it was, because it was open.
local keptDB = CoachLinkDB
coach = startSession()
CoachLinkDB = keptDB
fire("PLAYER_ENTERING_WORLD", false, true)
check(panel() and panel().shown == true, "a panel that was open reopens after a reload")
local p = panel().points[1]
check(p and p[1] == "TOPLEFT" and p[4] == 120 and p[5] == 640, "the saved position is restored")
check(panel().width == 500 and panel().height == 420, "the saved size is restored")
check(CoachLinkPanelBody.fontSize == savedFont, "the saved font size is restored")

-- Closed by the player: it stays closed after the next reload.
panel():Hide()
check(keptDB.settings.panel.open == false, "closing the panel is remembered")
keptDB = CoachLinkDB
coach = startSession()
CoachLinkDB = keptDB
fire("PLAYER_ENTERING_WORLD", false, true)
check(panel() == nil or panel().shown ~= true, "a closed panel stays closed after a reload")

-- Nonsense in the saved settings is ignored.
coach = startSession()
CoachLinkDB = { settings = { panel = { point = 5, x = "far", width = -1, height = 1e9, fontSize = "huge", open = "yes" } } }
fire("PLAYER_ENTERING_WORLD", true, false)
local okShow = pcall(coach.togglePanel)
check(okShow and panel().shown == true, "bad saved settings do not break the panel")
check(panel().width >= 300 and panel().width <= 1000 and panel().height >= 250 and panel().height <= 1000,
    "a bad saved size is replaced by a sensible one")

-- A saved settings table with a wrong shape is replaced, not crashed on.
coach = startSession()
CoachLinkDB = { settings = "oops" }
fire("PLAYER_ENTERING_WORLD", true, false)
okShow = pcall(coach.togglePanel)
check(okShow and panel().shown == true, "a settings value of the wrong type does not break the panel")


-------------------------------------------------------------------------------
-- Test 7: the addon list entry in the minimap
-------------------------------------------------------------------------------

coach = startSession()
CoachLink_OnAddonCompartmentClick("CoachLink", "LeftButton")
check(panel() and panel().shown == true, "a click in the minimap's addon list opens the panel")
CoachLink_OnAddonCompartmentClick("CoachLink", "LeftButton")
check(panel().shown == false, "a second click closes it")


-------------------------------------------------------------------------------
-- Test 8: broken advice never errors
-------------------------------------------------------------------------------

local function openWith(adviceValue)
    coach = startSession()
    CoachLinkAdvice = adviceValue
    local ok, err = pcall(coach.togglePanel)
    return ok, err
end

local broken = {
    "a string instead of a table",
    42,
    { characters = "no" },
    { characters = { ["Testchar-Testrealm"] = "no" } },
    { characters = { ["Testchar-Testrealm"] = { answers = "no", plan = "no" } } },
    { characters = { ["Testchar-Testrealm"] = { answers = { "x", 5, true, {} }, plan = { steps = "no" } } } },
    { characters = { ["Testchar-Testrealm"] = { answers = { { steps = "go", text = 7, title = {}, warnings = 3,
        source = false, answeredAt = "yesterday", question = {}, questionId = {} } },
        basedOnSave = "never" } } },
    { characters = { ["Testchar-Testrealm"] = { answers = { { steps = { 1, {}, false, "ok step" },
        warnings = { {}, 5, "ok warning" }, answeredAt = 0 / 0 } } } } },
    { characters = { ["Testchar-Testrealm"] = { answers = { { answeredAt = 1 / 0, basedOnSave = -1e300 } },
        basedOnSave = 1 / 0 } } },
}
for index, value in ipairs(broken) do
    local ok, err = openWith(value)
    check(ok and panel().shown == true, "broken advice #" .. index .. " does not error" .. (ok and "" or ": " .. tostring(err)))
end
local ok = openWith(broken[8])
check(ok and has(stepsText(), "1. ok step"), "wrong-typed steps are skipped, good ones kept")

-- Huge strings are cut.
local huge = string.rep("x", 100000)
local hugeSteps = {}
for i = 1, 500 do hugeSteps[i] = huge end
local okHuge, errHuge = openWith(advice({ title = huge, text = huge, source = huge, question = huge,
    steps = hugeSteps, warnings = hugeSteps }))
check(okHuge, "huge strings do not error" .. (okHuge and "" or ": " .. tostring(errHuge)))
check(#bodyText() < 40000 and #stepsText() < 10000 and #footerText() < 1000,
    "huge strings are cut to a sensible length")

-- Colour codes and links in the file cannot style or link anything.
openWith(advice({ text = "Hi |cffff0000red|r |Hitem:19019|h[Sword]|h || bars", steps = { "|cff00ff00go|r" } }))
check(not has(bodyText(), "|c") and not has(bodyText(), "|H") and has(bodyText(), "||"),
    "single | escapes are removed from the answer text, doubled ones kept")
check(not has(stepsText(), "|c"), "colour codes are removed from the steps")

-- A broken questions list is ignored by the panel.
coach = startSession()
CoachLinkDB = { characters = { ["Testchar-Testrealm"] = { questions = { {}, "x", { id = 1, text = {} } } } } }
check(pcall(coach.togglePanel), "a broken questions list does not error")


-------------------------------------------------------------------------------
-- Test 9: the new-advice chat line
-------------------------------------------------------------------------------

coach = startSession()
CoachLinkAdvice = advice()
fire("PLAYER_ENTERING_WORLD", true, false)
fire("PLAYER_ENTERING_WORLD", false, false)   -- a later loading screen
check(count("your coach has new advice: /coach panel") == 1, "the new-advice line is printed once")

coach = startSession()
CoachLinkAdvice = advice()
CoachLinkDB = { settings = { panel = { lastSeenAnswerAt = ANSWER_AT } } }
fire("PLAYER_ENTERING_WORLD", true, false)
check(count("new advice") == 0, "no line when the answer was already seen")

coach = startSession()
fire("PLAYER_ENTERING_WORLD", true, false)
check(count("new advice") == 0, "no line when there is no advice")

coach = startSession()
CoachLinkAdvice = advice()
fire("PLAYER_ENTERING_WORLD", true, false)
coach.togglePanel()
check(CoachLinkDB.settings.panel.lastSeenAnswerAt == ANSWER_AT, "showing the panel marks the answer as seen")
local again = CoachLinkDB
coach = startSession()
CoachLinkDB = again
CoachLinkAdvice = advice()
fire("PLAYER_ENTERING_WORLD", false, true)
check(count("new advice") == 0, "after it was seen, the next login stays quiet")

coach = startSession()
CoachLinkAdvice = advice({ answeredAt = ANSWER_AT + 100 })
CoachLinkDB = { settings = { panel = { lastSeenAnswerAt = ANSWER_AT } } }
fire("PLAYER_ENTERING_WORLD", false, true)
check(count("new advice") == 1, "a newer answer is announced again")

-- An error inside a handler is caught.
coach = startSession()
CoachLinkAdvice = setmetatable({}, { __index = function() error("boom") end })
check(pcall(fire, "PLAYER_ENTERING_WORLD", true, false), "an error in an event handler does not escape")
check(chatHas("error"), "...and the player is told about it")


-------------------------------------------------------------------------------
-- Test 10: the rules
-------------------------------------------------------------------------------

-- The key binding: the strings the game shows, and the XML that runs /coach panel.
check(type(BINDING_HEADER_COACHLINK) == "string" and type(BINDING_NAME_COACHLINK_TOGGLE) == "string",
    "the key binding has a header and a name")
local bindingsFile = assert(io.open("addon/CoachLink/Bindings.xml", "r"))
local bindingsXml = bindingsFile:read("*a")
bindingsFile:close()
check(has(bindingsXml, 'name="COACHLINK_TOGGLE"') and has(bindingsXml, 'SlashCmdList.COACHLINK("panel")'),
    "Bindings.xml toggles the panel through /coach panel")

-- Opening at login must not happen during a fight.
coach = startSession()
CoachLinkDB = { settings = { panel = { open = true } } }
inCombat = true
fire("PLAYER_ENTERING_WORLD", true, false)
check(panel() == nil or panel().shown ~= true, "the panel does not reopen at login while in combat")
inCombat = false
fire("PLAYER_REGEN_ENABLED")
check(panel() and panel().shown == true, "it opens when the fight ends")



-------------------------------------------------------------------------------
-- Optional: show a real Advice.lua written by wow-coach (tests/test_panel_end_to_end.py)
--   luajit addon/tests/run_panel_test.lua --advice-file PATH STEP_TEXT BODY_TEXT
-------------------------------------------------------------------------------

if arg and arg[1] == "--advice-file" then
    startSession()
    dofile(arg[2])   -- sets CoachLinkAdvice, as the game does when it loads CoachLink_Advice
    fire("PLAYER_ENTERING_WORLD", true, false)
    SlashCmdList.COACHLINK("panel")
    check(panel() and panel().shown == true, "a real Advice.lua: the panel opens")
    check(has(stepsText(), arg[3]), "a real Advice.lua: the panel shows the step")
    check(has(bodyText(), arg[4]), "a real Advice.lua: the panel shows the text")
end

if failures > 0 then
    io.stdout:write(failures .. " check(s) FAILED\n")
    os.exit(1)
end
io.stdout:write("ALL PASSED\n")
