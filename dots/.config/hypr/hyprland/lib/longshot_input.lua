-- Automatic capture sends continuous virtual-pointer axes. These bindings
-- observe physical wheel detents and buttons without consuming user input.
return function()
    local interrupt = hl.dsp.global("quickshell:regionLongShotInterrupt")
    local function takeControl()
        hl.dispatch(interrupt)
    end
    for _, key in ipairs({ "mouse_up", "mouse_down", "mouse_left", "mouse_right",
        "mouse:272", "mouse:273", "mouse:274" }) do
        hl.bind(key, takeControl, { ignore_mods = true, transparent = true, non_consuming = true })
    end
end
