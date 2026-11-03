-- Run with: lua tests/super-key.lua
local source = debug.getinfo(1, "S").source:sub(2)
local root = source:match("^(.*)/tests/[^/]+$") or "."
local install = dofile(root .. "/dots/.config/hypr/hyprland/lib/super_key.lua")
local event, mouse, superBindings, interrupts, mightTrigger, panelOpen

hl = {
    dsp = { global = function(name) return name end },
    dispatch = function(name)
        assert(name == "quickshell:searchToggleReleaseInterrupt")
        interrupts = interrupts + 1
        mightTrigger = false
    end,
    on = function(name, callback)
        assert(name == "input.keyboard.key")
        event = callback
    end,
    bind = function(key, callback, options)
        if key:match("^SUPER %+ SUPER_") then
            assert(options.transparent)
            superBindings[key] = callback
            return
        end
        assert(options.ignore_mods and options.transparent and options.non_consuming)
        mouse[key] = callback
    end,
}

local function reset()
    mouse, interrupts, mightTrigger, panelOpen = {}, 0, true, false
    superBindings = {}
    install()
end

local function pressSuper(key)
    event(key, 0, 1)
    superBindings["SUPER + SUPER_" .. (key == 134 and "R" or "L")]()
    mightTrigger = true -- GlobalShortcut.searchToggleRelease.onPressed
end

local function releaseSuper(key)
    event(key, 0, 0)
    if mightTrigger then panelOpen = not panelOpen end
    mightTrigger = true -- GlobalShortcut.searchToggleRelease.onReleased
end

for _, super in ipairs({ 133, 134, 8 }) do -- standard and remapped/virtual keys
    reset()
    pressSuper(super)
    event(super, 0, 2) -- holding/repeating Super must not cancel its tap
    releaseSuper(super)
    assert(panelOpen and interrupts == 0, "a lone Super tap must open search")

    for _, key in ipairs({ 10, 19, 36, 38, 50 }) do -- 1, 0, Return, A, Shift
        for _, superFirst in ipairs({ false, true }) do
            reset()
            pressSuper(super)
            event(key, 0, 1)
            event(key, 0, 2)
            if superFirst then releaseSuper(super) end
            event(key, 0, 0)
            if not superFirst then releaseSuper(super) end
            assert(not panelOpen, "a Super chord must not open search")
            assert(interrupts == 1, "only another key press cancels the tap")

            pressSuper(super)
            releaseSuper(super)
            assert(panelOpen, "a tap after a chord must work")
        end
    end

    reset()
    pressSuper(super)
    releaseSuper(super)
    pressSuper(super)
    releaseSuper(super)
    assert(not panelOpen, "a second lone tap must close search")

    reset()
    for key in pairs(mouse) do
        mouse[key]()
        assert(interrupts == 0, "ordinary mouse input must not cancel anything")
        pressSuper(super)
        mouse[key]()
        releaseSuper(super)
        assert(not panelOpen, "Super + " .. key .. " must not open search")
        interrupts = 0
    end
end

reset()
event(38, 0, 1)
event(38, 0, 0)
assert(interrupts == 0, "ordinary typing must not send shell shortcuts")
print("Super tap/chord regression checks passed")
