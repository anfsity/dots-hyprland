#!/usr/bin/env python3
"""Capture a region while the user scrolls down manually.

Quickshell sends finish/cancel on stdin. In a standalone session, Ctrl+C saves
the result and SIGTERM cancels. No mouse or keyboard events are injected.
"""

import argparse
import io
import json
import os
from pathlib import Path
import re
import select
import shutil
import signal
import subprocess
import sys
import time

import numpy as np
from PIL import Image

from longshot_stitch import ManualStitcher


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}), flush=True)


def notify(title, body):
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", "Long screenshot", title, body],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def capture(region):
    result = subprocess.run(["grim", "-g", region, "-"], capture_output=True,
                            check=True, timeout=10)
    with Image.open(io.BytesIO(result.stdout)) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8)


def read_config():
    config_path = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    try:
        data = json.loads((config_path / "illogical-impulse/config.json").read_text())
        return data.get("screenSnip", {})
    except (OSError, ValueError):
        return {}


def parse_args(argv=None):
    config = read_config()
    settings = config.get("longShot", {})
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", help="X,Y WxH; select with slurp if omitted")
    parser.add_argument("--control-stdin", action="store_true",
                        help="read finish/cancel from stdin (for Quickshell)")
    parser.add_argument("--interval", type=int, default=settings.get("captureInterval", 120))
    parser.add_argument("--settle-delay", type=int, default=settings.get("settleDelay", 300))
    parser.add_argument("--max-shots", type=int, default=settings.get("maxShots", 80))
    parser.add_argument("--min-overlap", type=int, default=settings.get("minOverlap", 40))
    parser.add_argument("--max-overlap", type=int, default=settings.get("maxOverlap", 0))
    parser.add_argument("--threshold", type=float, default=settings.get("stitchThreshold", 0.8))
    parser.add_argument("--trim-right", type=int, default=settings.get("trimRight", 0))
    parser.add_argument("--max-pixels", type=int, default=settings.get("maxPixels", 64_000_000))
    parser.add_argument("--no-auto-trim", action="store_true", default=not settings.get("autoTrim", True))
    parser.add_argument("--preview-dir", type=Path)
    parser.add_argument("--output")
    parser.add_argument("--no-copy", action="store_true")
    parser.add_argument("--no-notify", action="store_true")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args(argv)
    if args.interval < 30 or args.settle_delay < 0 or args.max_shots < 2:
        parser.error("interval must be >= 30 ms, settle delay >= 0, max shots >= 2")
    if args.min_overlap < 4 or args.max_overlap < 0 or args.trim_right < 0:
        parser.error("invalid overlap or trim settings")
    if args.max_overlap and args.max_overlap < args.min_overlap:
        parser.error("max overlap must be zero or at least min overlap")
    if not 0 < args.threshold <= 1:
        parser.error("threshold must be in (0, 1]")
    if args.max_pixels < 1:
        parser.error("max pixels must be positive")
    args.save_path = config.get("savePath", "")
    return args


def run(args):
    if not shutil.which("grim"):
        raise ValueError("grim is not installed")
    if not args.region:
        args.region = subprocess.check_output(["slurp"], text=True).strip()
    if not re.fullmatch(r"(-?\d+),(-?\d+) ([1-9]\d*)x([1-9]\d*)", args.region):
        raise ValueError("Invalid capture region; expected X,Y WxH")
    command = None
    paused = False
    paused_at_finish = False

    def handle_signal(signum, _frame):
        nonlocal command, paused_at_finish
        command = "finish" if signum == signal.SIGINT else "cancel"
        paused_at_finish = paused

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    control_buffer = b""

    def wait_control(seconds):
        nonlocal command, control_buffer, paused, paused_at_finish
        if command:
            return
        if not args.control_stdin:
            time.sleep(seconds)
            return
        readable, _, _ = select.select([sys.stdin], [], [], seconds)
        if readable:
            chunk = os.read(sys.stdin.fileno(), 4096)
            if not chunk:
                command = "cancel"  # The owning shell exited/reloaded.
                return
            control_buffer += chunk
            while b"\n" in control_buffer:
                line, control_buffer = control_buffer.split(b"\n", 1)
                action = line.strip().decode("ascii", errors="ignore")
                if action == "cancel":
                    command = action
                elif not command:
                    if action == "finish":
                        paused_at_finish = paused
                        command = action
                    elif action in {"pause", "resume"}:
                        paused = action == "pause"

    wait_control(args.settle_delay / 1000)
    if command:
        emit("cancelled")
        return 0
    stitcher = ManualStitcher(capture(args.region), args.min_overlap,
                             args.max_overlap, args.threshold, args.trim_right,
                             args.max_pixels, not args.no_auto_trim)
    status = "waiting"
    preview_revision = 0
    preview_path = ""
    limit_reached = False
    if args.preview_dir:
        args.preview_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    def progress(update_preview=False):
        nonlocal preview_revision, preview_path
        if update_preview and args.preview_dir:
            # Alternating paths invalidate QML's cache without accumulating files.
            path = args.preview_dir / f"preview-{preview_revision % 2}.png"
            temporary = path.with_suffix(".tmp")
            stitcher.preview().save(temporary, format="PNG")
            temporary.replace(path)
            preview_path = str(path)
            preview_revision += 1
        emit("progress", frames=stitcher.frames, width=stitcher.width,
             height=stitcher.height, frameHeight=stitcher.frame_height, status="paused" if paused else status,
             confidence=round(stitcher.last_match.confidence, 3),
             fixedTop=stitcher.last_match.fixed_top,
             fixedBottom=stitcher.last_match.fixed_bottom,
             warning=status in {"no-overlap", "ambiguous", "backtracking"},
             preview=preview_path, revision=preview_revision)

    progress(True)
    next_capture = time.monotonic() + args.interval / 1000
    reported_paused = False
    while command != "cancel" and stitcher.frames < args.max_shots:
        wait_control(max(0, next_capture - time.monotonic()) if not paused else 0.25)
        if command == "cancel":
            break
        if paused != reported_paused:
            reported_paused = paused
            progress()
        if paused and command != "finish":
            continue
        # Finishing while paused saves only content the user already accepted.
        if command == "finish" and paused_at_finish:
            break
        started = time.monotonic()
        result = stitcher.add(capture(args.region))
        next_capture = started + args.interval / 1000
        if result == "limit":
            limit_reached = True
            break
        next_status = "capturing" if result in {"added", "unchanged"} else result
        if result == "added" or next_status != status:
            status = next_status
            progress(result == "added")
        if command == "finish":
            break

    if command == "cancel":
        emit("cancelled")
        return 0
    emit("saving")
    if stitcher.frames < 2:
        raise ValueError("No overlapping scroll captured; select scrolling content and scroll down slowly")
    directory = Path(args.save_path or "/tmp/quickshell/media/screenshot").expanduser()
    output = Path(args.output).expanduser() if args.output else directory / (
        f"longshot-{time.strftime('%Y-%m-%d_%H.%M.%S')}-{time.time_ns() % 1000000000:09d}.png")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".part")
    try:
        Image.fromarray(stitcher.image).save(temporary, format="PNG")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    copy_failed = False
    if not args.no_copy:
        try:
            with output.open("rb") as image:
                subprocess.run(["wl-copy", "--type", "image/png"], stdin=image,
                               check=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            copy_failed = True
    emit("done", output=str(output), frames=stitcher.frames,
         height=stitcher.height, width=stitcher.width,
         copied=not args.no_copy and not copy_failed,
         truncated=status in {"no-overlap", "ambiguous", "backtracking"},
         limited=limit_reached or stitcher.frames >= args.max_shots)
    if not args.no_notify:
        details = f"{stitcher.frames} frames · {stitcher.height} px\nSaved: {output}"
        if status in {"no-overlap", "ambiguous", "backtracking"}:
            details += "\nLast view did not overlap; saved through the last matching frame."
        if limit_reached or stitcher.frames >= args.max_shots:
            details += "\nCapture size limit reached; saved through the last accepted frame."
        if copy_failed:
            details += "\nClipboard copy failed."
        notify("Long screenshot ready", details)
    if args.open:
        subprocess.Popen(["xdg-open", str(output)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    return 0


def main(argv=None):
    args = parse_args(argv)
    try:
        return run(args)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        emit("error", message=str(error))
        if not args.no_notify:
            notify("Long screenshot failed", str(error))
        return 1


if __name__ == "__main__":
    sys.exit(main())
