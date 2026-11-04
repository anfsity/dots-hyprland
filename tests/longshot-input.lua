-- Run with: lua tests/longshot-input.lua
local bindings, interrupts = {}, 0
hl = {
    dsp = { global = function(name) return name end },
    dispatch = function(name)
        assert(name == "quickshell:regionLongShotInterrupt")
        interrupts = interrupts + 1
    end,
    bind = function(key, callback, options)
        assert(options.ignore_mods and options.transparent and options.non_consuming)
        bindings[key] = callback
    end,
}
dofile("dots/.config/hypr/hyprland/lib/longshot_input.lua")()
for _, key in ipairs({"mouse_up", "mouse_down", "mouse_left", "mouse_right",
    "mouse:272", "mouse:273", "mouse:274"}) do
    assert(bindings[key], "missing interruption binding for " .. key)
    local before = interrupts
    bindings[key]()
    assert(interrupts == before + 1)
end
print("Long screenshot manual input interruption checks passed")
