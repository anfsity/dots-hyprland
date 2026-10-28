#!/usr/bin/env python3
"""Check optional Skwd integration without changing the desktop or running a daemon."""

import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "dots/.config/quickshell/ii/scripts/wallpaper/skwd_picker.py"
spec = importlib.util.spec_from_file_location("skwd_picker", SOURCE)
picker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(picker)


class SkwdPickerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="skwd-integration-")
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        for mock in (patch.object(Path, "home", return_value=self.home),
                     patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.home / "config"),
                                             "XDG_CACHE_HOME": str(self.home / "cache"),
                                             "XDG_RUNTIME_DIR": str(self.home / "runtime")})):
            mock.start()
            self.addCleanup(mock.stop)

    def test_import_preserves_layout_and_replaces_trial_hook(self):
        trial = self.home / ".local/share/skwd-trial/config/config.json"
        trial.parent.mkdir(parents=True)
        seed = {"general": {"locale": "en-US"}, "library": {"folders": ["/art/中文's pictures"]},
                "components": {"wallpaperSelector": {"displayMode": "wall"}},
                "postProcessing": [{"command": "/obsolete/trial/apply-wallpaper %path%"}]}
        trial.write_text(json.dumps(seed))
        wrapper = self.home / "scripts with ' quotes/skwd-picker.sh"
        with patch.object(picker, "WRAPPER", wrapper):
            picker.create_config()
        config, _, _ = picker.get_paths()
        saved = json.loads((config / "config.json").read_text())
        self.assertEqual(saved["library"], seed["library"])
        self.assertEqual(saved["components"], seed["components"])
        self.assertEqual(saved["general"], seed["general"])
        self.assertTrue(saved["pickOnlyMode"])
        self.assertFalse(saved["postProcessOnRestore"])
        for hook in saved["postProcessing"]:
            self.assertEqual(shlex.split(hook["command"]), [str(wrapper), "--apply", "%path%"])
        saved["components"]["wallpaperSelector"]["displayMode"] = "hex"
        (config / "config.json").write_text(json.dumps(saved))
        picker.create_config()
        self.assertEqual(json.loads((config / "config.json").read_text())["components"]["wallpaperSelector"]["displayMode"], "hex")

    def test_missing_optional_package_can_close_without_starting_anything(self):
        with patch.object(picker, "find_binaries", side_effect=RuntimeError("not installed")), \
             patch.object(sys, "argv", [str(SOURCE), "--close"]), \
             patch.object(subprocess, "run") as run:
            self.assertEqual(picker.main(), 0)
            run.assert_not_called()
        with patch.object(picker.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Install skwd-wall-v2-bin"):
                picker.find_binaries()

    def test_apply_passes_unusual_filename_as_one_literal_argument(self):
        scripts = self.home / "scripts"
        switch = scripts / "colors/switchwall.sh"
        switch.parent.mkdir(parents=True)
        result = self.home / "arguments.json"
        switch.write_text(f"#!{sys.executable}\nimport json,sys\nfrom pathlib import Path\nPath({str(result)!r}).write_text(json.dumps(sys.argv[1:]))\n")
        switch.chmod(0o755)
        image = str(self.home / "中文's $(touch SHOULD_NOT_EXIST).png")
        with patch.object(picker, "SCRIPT", scripts / "wallpaper/skwd_picker.py"), \
             patch.object(sys, "argv", [str(SOURCE), "--apply", image]):
            self.assertEqual(picker.main(), 0)
        self.assertEqual(json.loads(result.read_text()), ["--image", image])

    def test_existing_picker_toggles_without_starting_another_daemon(self):
        bins = tuple(Path("/bin") / name for name in ("skwd-wall-v2", "skwd-walld", "skwd-helm"))
        with patch.object(picker, "run_control", return_value=subprocess.CompletedProcess([], 0)), \
             patch.object(picker, "create_config") as config, \
             patch.object(subprocess, "run") as run:
            picker.toggle_picker(bins, {})
            config.assert_not_called()
            run.assert_called_once_with(["/bin/skwd-helm", "ui", "toggle"], env={}, check=True)


if __name__ == "__main__":
    unittest.main()
