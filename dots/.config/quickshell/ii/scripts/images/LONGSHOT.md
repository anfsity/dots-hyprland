# Manual long screenshots

Press **Super+Shift+S**, choose **Long screenshot** in the selection toolbar,
then select the scrolling content. Scroll down manually, keeping some content
from the previous view visible. Press **Super+Shift+S** again to finish.

When there is room outside the selected region, a small panel shows the frame
count and **Finish / Cancel** buttons. It never covers the screenshot area.
For full-screen selections, use the shortcut to finish, or cancel via:

```sh
qs -c ii ipc call region cancelLongshot
```

Pausing does not stop capture. Identical views are ignored. Views without enough
matching content are skipped; scroll back toward the last captured view and
continue with smaller movements. Select the scrolling content without fixed
headers, footers, or unrelated animations for the best results.

The final PNG is copied to the clipboard and saved to `screenSnip.savePath`,
or `/tmp/quickshell/media/screenshot` when the save path is empty. Cancelling
does not save or change the clipboard. Reloading/exiting the shell cancels the
owned session. A session finishes automatically at `longShot.maxShots` accepted
frames (80 by default).

Dependencies: `grim`, Python with Pillow and NumPy, `wl-copy` for clipboard,
and optionally `notify-send`. The shell's Python virtual environment is used
when available. No scroll automation or `ydotool` is used.

Settings in `screenSnip.longShot`: `captureInterval` (120 ms), `settleDelay`,
`maxShots`, `minOverlap`, `maxOverlap`, `stitchThreshold`, and `trimRight`.
Legacy `scrollClicks`, `scrollDelay`, and `scrollMethod` are ignored.

Standalone use: `scripts/images/longshot.sh --region "100,100 900x600"`.
Ctrl+C finishes; SIGTERM cancels. Quickshell uses `--control-stdin` with line
commands `finish` and `cancel`; JSON progress events are written to stdout.

Validation:

```sh
~/.local/state/quickshell/.venv/bin/python -B -m unittest discover -s scripts/images/tests -v
```
