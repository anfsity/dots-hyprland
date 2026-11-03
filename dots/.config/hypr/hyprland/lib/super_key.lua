-- GlobalShortcut releases also fire after a Super chord. Cancel the shell's
-- pending tap on other input, including keys with no configured binding.
return function()
    local held = {}
    local lastPressedKey
    local interrupt = hl.dsp.global("quickshell:searchToggleReleaseInterrupt")

    local function cancelTap()
        if next(held) then
            hl.dispatch(interrupt)
        end
    end

    hl.on("input.keyboard.key", function(keycode, _, state)
        if state == 1 then
            cancelTap()
            lastPressedKey = keycode
        elseif state == 0 then
            held[keycode] = nil
        end
    end)

    -- The input event precedes bind dispatch. Learn the actual Super keycode
    -- from its keysym binding so remapped and virtual keyboards work too.
    local function superPressed()
        if lastPressedKey then
            held[lastPressedKey] = true
        end
    end
    hl.bind("SUPER + SUPER_L", superPressed, { transparent = true })
    hl.bind("SUPER + SUPER_R", superPressed, { transparent = true })

    for _, key in ipairs({ "mouse:272", "mouse:273", "mouse:274", "mouse:275",
        "mouse:276", "mouse:277", "mouse:278", "mouse:279",
        "mouse_up", "mouse_down", "mouse_left", "mouse_right" }) do
        hl.bind(key, cancelTap, { ignore_mods = true, transparent = true, non_consuming = true })
    end
end
