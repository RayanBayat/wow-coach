--[[
CoachLinkPanel: the Coach panel (addon 0.8.0). Placeholder until it is built
(docs/plans/coach-panel.md, workstream A). CoachLink.lua gives this file
ns.askCoach, ns.openQuestions, ns.myAdvice, ns.characterKey and ns.say, and
expects it to set ns.togglePanel.
]]

local _, ns = ...

-- Clicking CoachLink in the minimap's addon list (the .toc names this function).
function CoachLink_OnAddonCompartmentClick()
    if ns.togglePanel then
        ns.togglePanel()
    end
end
