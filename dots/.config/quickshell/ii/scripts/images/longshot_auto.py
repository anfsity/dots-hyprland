"""Guarded, frame-paced automatic scrolling for long screenshots.

The virtual pointer sends continuous axis events only. It never moves the real
pointer, changes focus or sends keys. PyWayland is loaded only on opt-in.
Protocol: https://github.com/swaywm/wlr-protocols/blob/master/unstable/wlr-virtual-pointer-unstable-v1.xml
"""

import json
import os
import shutil
import subprocess
import time

import numpy as np


class AutoScrollError(Exception):
    """Stop automatic input while keeping the accepted screenshot available."""


def query_desktop(command):
    result = subprocess.run(["hyprctl", "-j", command], check=True,
                            capture_output=True, text=True, timeout=1)
    return json.loads(result.stdout)


def desktop_state():
    return query_desktop("activewindow"), query_desktop("cursorpos")


def snapshot_target():
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
        try:
            return query_desktop("activewindow")
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return None


def window_identity(window):
    return tuple(window.get(key) for key in ("address", "at", "size", "workspace", "fullscreen"))


class ScrollTarget:
    def __init__(self, region, window):
        origin, size = region.split()
        self.x, self.y = map(int, origin.split(","))
        self.width, self.height = map(int, size.split("x"))
        self.window = window_identity(window)
        at, extent = window.get("at", [0, 0]), window.get("size", [0, 0])
        self.window_bounds = (*at, *extent)
        cx, cy = self.x + self.width / 2, self.y + self.height / 2
        self.valid = bool(window.get("address")) and (
            at[0] <= cx < at[0] + extent[0] and at[1] <= cy < at[1] + extent[1])
        self.pointer = None

    def check(self, window, pointer, arming=False):
        if not self.valid or window_identity(window) != self.window:
            raise AutoScrollError("The capture window changed. Resume in the original window or use manual scrolling.")
        x, y = pointer["x"], pointer["y"]
        inside = self.x <= x < self.x + self.width and self.y <= y < self.y + self.height
        wx, wy, ww, wh = self.window_bounds
        inside = inside and wx <= x < wx + ww and wy <= y < wy + wh
        if arming:
            if inside:
                self.pointer = (x, y)
            return inside
        if not inside or self.pointer is None or abs(x - self.pointer[0]) + abs(y - self.pointer[1]) > 3:
            raise AutoScrollError("Pointer moved. Resume auto-scroll or continue manually.")
        return True


def virtual_pointer_protocol():
    """Declare the v1 client wire requests; PyWayland ships no wlr extensions."""
    from pywayland.protocol.wayland import WlSeat
    from pywayland.protocol_core import Argument, ArgumentType as T, Interface, Proxy

    class Pointer(Interface):
        name = "zwlr_virtual_pointer_v1"
        version = 1

    class PointerProxy(Proxy):
        interface = Pointer

    # Request order is part of the wire protocol, including unused requests.
    requests = [("motion", (T.Uint, T.Fixed, T.Fixed)),
                ("motion_absolute", (T.Uint,) * 5), ("button", (T.Uint,) * 3),
                ("axis", (T.Uint, T.Uint, T.Fixed)), ("frame", ()),
                ("axis_source", (T.Uint,)), ("axis_stop", (T.Uint, T.Uint)),
                ("axis_discrete", (T.Uint, T.Uint, T.Fixed, T.Int)), ("destroy", ())]

    def register(opcode, name, types):
        def request(self, *args):
            self._marshal(opcode, *args)
            if name == "destroy":
                self._destroy()
        request.__name__ = name
        Pointer.request(*(Argument(t) for t in types))(request)
        setattr(PointerProxy, name, request)

    for opcode, (name, types) in enumerate(requests):
        register(opcode, name, types)
    Pointer.proxy_class = PointerProxy
    Pointer._gen_c()

    class Manager(Interface):
        name = "zwlr_virtual_pointer_manager_v1"
        version = 1

    class ManagerProxy(Proxy):
        interface = Manager

        @Manager.request(Argument(T.Object, interface=WlSeat, nullable=True),
                         Argument(T.NewId, interface=Pointer))
        def create_virtual_pointer(self, seat=None):
            return self._marshal_constructor(0, Pointer, seat)

        @Manager.request()
        def destroy(self):
            self._marshal(1)
            self._destroy()

    Manager.proxy_class = ManagerProxy
    Manager._gen_c()
    return Manager


class DesktopScroller:
    def __init__(self, region, window):
        self.display = None
        self.pointer = None
        self.manager = None
        if not window or not shutil.which("hyprctl") or not os.environ.get("WAYLAND_DISPLAY"):
            raise AutoScrollError("Auto-scroll is unavailable. Continue with manual scrolling.")
        try:
            self.target = ScrollTarget(region, window)
            from pywayland.client import Display
            manager_type = virtual_pointer_protocol()
            self.display = Display()
            self.display.connect()
            self.registry = self.display.get_registry()

            def global_added(registry, name, interface, version):
                if interface == manager_type.name:
                    self.manager = registry.bind(name, manager_type, 1)
            self.registry.dispatcher["global"] = global_added
            self.display.roundtrip()
            if self.manager is None:
                raise AutoScrollError("Auto-scroll is unavailable. Continue with manual scrolling.")
            self.pointer = self.manager.create_virtual_pointer()
            self.display.roundtrip()
            self.arm_position = None
            self.arm_since = None
        except Exception as error:
            self.close()
            if isinstance(error, AutoScrollError):
                raise
            raise AutoScrollError("Auto-scroll is unavailable. Continue with manual scrolling.") from error

    def check(self, arming=False):
        try:
            ready = self.target.check(*desktop_state(), arming=arming)
            if arming:
                now = time.monotonic()
                position = self.target.pointer if ready else None
                if position != self.arm_position or position is None:
                    self.arm_position, self.arm_since = position, now
                    return False
                return now - self.arm_since >= 0.4
            return ready
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            raise AutoScrollError("Auto-scroll is unavailable. Continue with manual scrolling.") from error

    def arm(self):
        self.arm_position = None
        self.arm_since = None

    def scroll(self, amount):
        self.check()
        timestamp = int(time.monotonic() * 1000) & 0xffffffff
        # Continuous events bypass wheel key bindings, including the physical
        # wheel shortcut that gives the user immediate control of the capture.
        self.pointer.axis_source(2)
        self.pointer.axis(timestamp, 0, amount)
        self.pointer.frame()
        self.pointer.axis_stop(timestamp, 0)
        self.pointer.frame()
        self.display.roundtrip()

    def close(self):
        if self.display is not None:
            self.display.disconnect()
            self.display = None
            self.pointer = None


class AutoPacer:
    """Permit one scroll per settled, verified frame; adapt to observed motion."""
    def __init__(self, frame_height, settle_ms=350):
        self.target_shift = frame_height * 0.28
        self.settle_seconds = settle_ms / 1000
        self.amount = min(40.0, max(8.0, frame_height * 0.07))
        self.last_frame = None
        self.started = None
        self.stable = 0
        self.unchanged_steps = 0

    def begin(self, now):
        self.started = now
        self.last_frame = None
        self.stable = 0

    def settled(self, frame, now):
        # Downsample comparisons and ignore tiny cursor/animation changes.
        sample = frame[::4, ::4].astype(np.int16)
        if self.last_frame is not None:
            changed = np.mean(np.max(np.abs(sample - self.last_frame), axis=2) > 10)
            self.stable = self.stable + 1 if changed < 0.003 else 0
        self.last_frame = sample
        return now - self.started >= self.settle_seconds and self.stable >= 2

    def timed_out(self, now):
        return now - self.started > max(3.0, self.settle_seconds * 5)

    def accepted(self, result, shift):
        if result == "added":
            self.unchanged_steps = 0
            if shift > 0:
                factor = max(0.5, min(1.4, self.target_shift / shift))
                self.amount = max(8.0, min(120.0, self.amount * factor))
        elif result == "unchanged":
            self.unchanged_steps += 1
        return self.unchanged_steps >= 3
