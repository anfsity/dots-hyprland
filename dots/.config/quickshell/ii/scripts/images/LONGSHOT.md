# Long screenshots

Press **Super+Shift+S**, choose **Long screenshot**, then select the scrolling
content. Scroll down manually, keeping some of the previous view visible.
Press **Super+Shift+S** again to finish. **Super+Shift+Alt+S** opens long screenshot
mode directly; press it again to finish.

The controller shows a live, scrollable preview, dimensions and alignment state.
It follows the latest capture until you scroll the preview yourself. The down
arrow resumes following. **Pause / Resume** lets you stop sampling while reading.
After saving, **Open image** opens the full-resolution result.
The controller uses opaque theme surfaces even when shell transparency is enabled.
Short captures use a shorter preview, and recovery instructions sit in a separate
high-contrast information box.

## Optional automatic scrolling

Manual scrolling remains the default. Click **Auto** in the controller, or press
**Super+Shift+Alt+A**, then move the pointer into the selected content and hold
it still briefly. Automatic capture sends one small continuous scroll, waits for
a stable frame, verifies the overlap, and only then scrolls again. The next step
adapts to the actual distance observed in the captured frames.

**Pause / Resume** also works in automatic mode. Click **Auto** again to return
to manual capture. Moving the pointer, using the physical mouse wheel/buttons,
or changing the active window pauses automatic scrolling. Window moves, resizes,
workspace changes and lost overlap also stop further input. Resume requires the
original window and capture geometry. No focus changes, pointer warps or key
presses are injected. Keep the pointer over the selected scrollable area.

Physical wheel/button takeover uses `hyprland/lib/longshot_input.lua`; deploy the
Hyprland configuration as well as Quickshell for these bindings. Touchpad scroll
gestures do not trigger wheel-detent bindings, so use **Pause**, move the pointer,
or switch back to manual mode before intervening with a touchpad.

After three stable scroll attempts without growth, a capture with at least two
accepted frames is saved automatically. This is a bottom-of-content heuristic;
very slow loading pages can require another capture. If nothing ever scrolls,
or the page never settles, automatic mode pauses for manual recovery instead.
Finishing in automatic mode saves only frames already settled and verified.

Automatic input requires Hyprland, PyWayland (already in the shell requirements)
and the compositor's `wlr-virtual-pointer` protocol. If unavailable, the controller
keeps manual capture available. Standalone opt-in: `longshot.sh --auto-scroll`;
physical wheel/button takeover is available through the Quickshell controller,
while pointer/window guards also apply to standalone capture.

The controller stays outside the selected region. If there is insufficient room,
a compact controller is used; if the selection covers the entire screen, use:

- **Super+Shift+Alt+P**: pause / resume.
- **Super+Shift+Alt+Escape**: cancel without saving.
- **Super+Shift+S**: finish and save.

The result panel appears after saving even for full-screen selections. Manual
mode injects no input events. Keep the selected window in place.

## Matching and rendering

Independent horizontal strips propose vertical motion using normalized FFT
correlation. The complete overlap is then checked in tiles, including a
contrast-normalized residual to distinguish similar paragraphs and line numbers.
Stationary header/footer bands and the scrollbar edge are excluded from matching.
The first header and final footer are retained once in the result.

Uncertain repeated content, missing overlap and reverse scrolling never append
unverified rows. The preview remains at the last accepted view. Scroll back
until the preview grows again, then continue with smaller movements. Fully
identical repeated rows contain no evidence of displacement; the capture waits
rather than inventing content. Complex sticky elements, reflow, zoom changes and
large animations can still require a tighter selection around the scrolling body.

A minimum-cost seam avoids strong text edges and chooses original source pixels.
The saved PNG is never geometrically resampled or feathered across text. Only
the bounded preview uses Lanczos resampling. Finalized image strips are stored
incrementally so every accepted frame does not copy the entire growing image.

## Saving and limits

PNG output is written atomically, copied to the clipboard and saved under
`screenSnip.savePath`, or `/tmp/quickshell/media/screenshot` when that path is empty.
Pausing does not finish capture. Finishing while paused saves the accepted view;
finishing during manual capture samples the last scroll once more. Cancelling leaves
the output and clipboard untouched. Exiting/reloading the owning shell cancels
an active session through stdin EOF.

At `maxShots` (80 accepted frames) or `maxPixels` (64 million output pixels), the
last safe image is saved. The controller reports partial results if the last
view could not be matched. Preview caching is limited to two small files under
Quickshell's private `media/longshot` cache directory.

Dependencies: `grim`, Python with Pillow and NumPy, `wl-copy` for clipboard,
and optionally `notify-send`. The shell's Python environment is used when present.

Settings under `screenSnip.longShot`: `captureInterval` (120 ms), `settleDelay`
(300 ms), `maxShots`, `maxPixels`, `minOverlap`, `maxOverlap`, `stitchThreshold`,
`trimRight` (0 automatically excludes the scrollbar edge), and `autoTrim` (true).
`autoSettleMs` (350 ms, allowed range 200–3000) sets the minimum automatic settling
time. Frame stability and overlap verification are still required after this delay.
Legacy `scrollClicks`, `scrollDelay` and `scrollMethod` remain ignored.

Standalone: `scripts/images/longshot.sh --region "100,100 900x600"`.
Ctrl+C finishes; SIGTERM cancels. Quickshell uses `--control-stdin` with line
commands `pause`, `resume`, `auto`, `manual`, `interrupt`, `finish` and `cancel`;
JSON progress events include state, dimensions, confidence, scrolling mode,
availability, recovery guidance and the preview path. `--preview-dir DIRECTORY`
enables alternating atomic preview PNGs. IPC equivalents live under `region`:
`longshot`, `autoLongshot`, `pauseLongshot`, `finishLongshot`, `cancelLongshot`.

Validation (from the repository root):

```sh
~/.local/state/quickshell/.venv/bin/python -B -m unittest discover \
  -s dots/.config/quickshell/ii/scripts/images/tests -v
~/.local/state/quickshell/.venv/bin/python -B tests/longshot-panel.py
lua tests/longshot-input.lua
```

Add `--artifacts DIRECTORY` to the panel test to retain a PNG of the real panel
rendered offscreen. Automatic session tests substitute the input driver and
screen capture executable. Tests never capture the desktop, change the clipboard
or inject input into the user's applications.
