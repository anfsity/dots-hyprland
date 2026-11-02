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

from longshot_stitch import best_overlap, gray


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}), flush=True)


def notify(title, body):
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", "Long screenshot", title, body],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class ManualStitcher:
    """Append matching new rows; pauses and backtracking add no frames."""

    def __init__(self, first, min_overlap=40, max_overlap=0, threshold=0.8,
                 trim_right=0):
        self.image = first
        self.last_gray = gray(first)
        self.frames = 1
        self.min_overlap = min_overlap
        self.max_overlap = max_overlap
        self.threshold = threshold
        self.trim_right = trim_right

    def add(self, frame):
        if frame.shape != self.last_gray.shape + (3,):
            raise ValueError("The capture region changed size")
        next_gray = gray(frame)
        if float(np.abs(self.last_gray - next_gray).mean()) < 0.5:
            return "unchanged"
        overlap, correlation = best_overlap(
            self.last_gray, next_gray, min_overlap=self.min_overlap,
            max_overlap=self.max_overlap, trim_right=self.trim_right)
        if overlap >= frame.shape[0] - 1 and correlation >= self.threshold:
            return "unchanged"
        if overlap < self.min_overlap or correlation < self.threshold:
            return "no-overlap"
        self.image = np.vstack((self.image, frame[overlap:]))
        self.last_gray = next_gray
        self.frames += 1
        return "added"


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
    parser.add_argument("--output")
    parser.add_argument("--no-copy", action="store_true")
    parser.add_argument("--no-notify", action="store_true")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args(argv)
    if args.interval < 30 or args.settle_delay < 0 or args.max_shots < 2:
        parser.error("interval must be >= 30 ms, settle delay >= 0, max shots >= 2")
    if args.min_overlap < 4 or args.max_overlap < 0 or args.trim_right < 0:
        parser.error("invalid overlap or trim settings")
    if not 0 < args.threshold <= 1:
        parser.error("threshold must be in (0, 1]")
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

    def handle_signal(signum, _frame):
        nonlocal command
        command = "finish" if signum == signal.SIGINT else "cancel"

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    control_buffer = b""

    def wait_control(seconds):
        nonlocal command, control_buffer
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
                if line.strip() in (b"finish", b"cancel"):
                    command = line.strip().decode()

    wait_control(args.settle_delay / 1000)
    if command == "cancel":
        emit("cancelled")
        return 0
    stitcher = ManualStitcher(capture(args.region), args.min_overlap,
                             args.max_overlap, args.threshold, args.trim_right)
    warning = False

    def progress():
        emit("progress", frames=stitcher.frames, height=stitcher.image.shape[0],
             warning=warning)

    progress()
    while command != "cancel" and stitcher.frames < args.max_shots:
        wait_control(0 if command == "finish" else args.interval / 1000)
        if command == "cancel":
            break
        # Capture again on finish to include the user's last scroll.
        result = stitcher.add(capture(args.region))
        next_warning = result == "no-overlap"
        if result == "added" or next_warning != warning:
            warning = next_warning
            progress()
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
    Image.fromarray(stitcher.image).save(output, format="PNG")
    copy_failed = False
    if not args.no_copy:
        try:
            with output.open("rb") as image:
                subprocess.run(["wl-copy", "--type", "image/png"], stdin=image,
                               check=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            copy_failed = True
    emit("done", output=str(output), frames=stitcher.frames,
         height=stitcher.image.shape[0], copied=not args.no_copy and not copy_failed)
    if not args.no_notify:
        details = f"{stitcher.frames} frames · {stitcher.image.shape[0]} px\nSaved: {output}"
        if warning:
            details += "\nLast view did not overlap; saved through the last matching frame."
        if stitcher.frames >= args.max_shots:
            details += "\nFrame limit reached."
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
