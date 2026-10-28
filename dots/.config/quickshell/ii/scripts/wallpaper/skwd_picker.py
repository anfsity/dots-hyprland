#!/usr/bin/env python3
"""Run Skwd as an optional picker while end-4 owns wallpaper application."""

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

SERVICE = "illogical-impulse-skwd.service"
SCRIPT = Path(__file__).resolve()
WRAPPER = SCRIPT.with_name("skwd-picker.sh")


def get_paths():
    home = Path.home()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    cache_home = Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    return config_home / "illogical-impulse/skwd-wall", cache_home / "illogical-impulse/skwd-wall", runtime


def find_binaries():
    names = ("skwd-wall-v2", "skwd-walld", "skwd-helm")
    binaries = [shutil.which(name) for name in names]
    if all(binaries):
        return tuple(Path(binary) for binary in binaries)
    # The portable trial uses the same upstream binaries as the Arch packages.
    portable = Path.home() / ".local/share/skwd-trial/root/usr/bin"
    if all((portable / name).is_file() for name in names):
        return tuple(portable / name for name in names)
    raise RuntimeError("Install skwd-wall-v2-bin (with skwd-deck-bin and skwd-paper-bin) to use Skwd Wall.")


def create_environment(binaries):
    config, cache, runtime = get_paths()
    env = dict(os.environ)
    env.update(SKWD_WALL_V2_CONFIG=str(config), SKWD_WALL_V2_CACHE=str(cache),
               SKWD_WALL_V2_SOCK=str(runtime / "illogical-impulse-skwd.sock"),
               SKWD_WALL_V2_INSTANCE="illogical-impulse")
    binary_dir = binaries[0].parent
    env["PATH"] = str(binary_dir) + os.pathsep + env.get("PATH", "")
    lib_dir = binary_dir.parent / "lib/skwd-paper"
    if lib_dir.is_dir():
        env["LD_LIBRARY_PATH"] = str(lib_dir) + (os.pathsep + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    return env


def create_config():
    config, cache, _ = get_paths()
    config.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    path = config / "config.json"
    trial = Path.home() / ".local/share/skwd-trial/config/config.json"
    if path.exists():
        data = json.loads(path.read_text())
    elif trial.exists():
        data = json.loads(trial.read_text())
    else:
        shell_path = config.parent / "config.json"
        shell = json.loads(shell_path.read_text())
        wallpaper = Path(shell["background"]["wallpaperPath"])
        pictures = Path(subprocess.check_output(["xdg-user-dir", "PICTURES"], text=True).strip())
        folders = list(dict.fromkeys(str(folder) for folder in (pictures / "Wallpapers", wallpaper.parent) if folder.is_dir()))
        data = {"library": {"folders": folders}, "general": {"locale": "en-US"},
                "components": {"wallpaperSelector": {"displayMode": "wall"}},
                "theme": {"policy": "off"}}
    original = json.dumps(data, sort_keys=True)
    apply_command = shlex.join([str(WRAPPER), "--apply"]) + " %path%"
    data.update(pickOnlyMode=True, postProcessOnRestore=False,
                postProcessing=[{"type": kind, "command": apply_command} for kind in ("static", "video")])
    data.setdefault("paths", {})["cache"] = str(cache)
    if not path.exists() or json.dumps(data, sort_keys=True) != original:
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        temporary.chmod(0o600)
        temporary.replace(path)


def run_control(helm, env, *arguments):
    return subprocess.run([str(helm), *arguments], env=env, capture_output=True, text=True)


def close_picker(binaries, env):
    run_control(binaries[2], env, "ui", "close")
    subprocess.run(["systemctl", "--user", "stop", SERVICE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def toggle_picker(binaries, env):
    picker, _, helm = binaries
    if run_control(helm, env, "ui", "state").returncode == 0:
        subprocess.run([str(helm), "ui", "toggle"], env=env, check=True)
        return
    create_config()
    active = subprocess.run(["systemctl", "--user", "is-active", "--quiet", SERVICE]).returncode == 0
    if not active:
        command = ["systemd-run", "--user", "--collect", "--unit=" + SERVICE,
                   "--description=illogical-impulse Skwd wallpaper picker"]
        for name in ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR", "ILLOGICAL_IMPULSE_VIRTUAL_ENV"):
            if name in env:
                command.append(f"--setenv={name}={env[name]}")
        subprocess.run([*command, str(WRAPPER), "--daemon"], check=True)
    deadline = time.monotonic() + 5
    while not Path(env["SKWD_WALL_V2_SOCK"]).exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("Skwd wallpaper service did not become ready.")
        time.sleep(0.05)
    _, cache, _ = get_paths()
    with (cache / "picker.log").open("a") as log:
        process = subprocess.Popen([str(picker)], env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=log, start_new_session=True)
    deadline = time.monotonic() + 5
    while run_control(helm, env, "ui", "state").returncode != 0:
        if process.poll() is not None or time.monotonic() >= deadline:
            raise RuntimeError(f"Skwd picker could not start. See {cache / 'picker.log'}.")
        time.sleep(0.05)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--toggle", action="store_true")
    actions.add_argument("--close", action="store_true")
    actions.add_argument("--daemon", action="store_true")
    actions.add_argument("--apply", metavar="IMAGE")
    args = parser.parse_args()
    if args.apply:
        switch = SCRIPT.parent.parent / "colors/switchwall.sh"
        return subprocess.run([str(switch), "--image", args.apply]).returncode
    try:
        binaries = find_binaries()
    except RuntimeError:
        if args.close:
            return 0
        raise
    env = create_environment(binaries)
    if args.daemon:
        os.execve(binaries[1], [str(binaries[1])], env)
    if args.close:
        close_picker(binaries, env)
    else:
        toggle_picker(binaries, env)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        subprocess.run(["notify-send", "Wallpaper picker", f"{error}\nOpening the built-in selector."], check=False)
        sys.exit(1)
