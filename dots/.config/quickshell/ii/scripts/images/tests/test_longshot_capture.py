"""Run with the shell's Python environment: python -m unittest discover -s .../tests."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from longshot_capture import ManualStitcher


class StitchTests(unittest.TestCase):
    def setUp(self):
        self.content = np.random.default_rng(24).integers(
            0, 256, (900, 96, 3), dtype=np.uint8)
        self.stitcher = ManualStitcher(self.content[:240])

    def test_pauses_backtracking_and_recovery(self):
        for offset, expected in [(0, "unchanged"), (80, "added"),
                                 (80, "unchanged"), (40, "no-overlap"),
                                 (80, "unchanged"), (160, "added"),
                                 (600, "no-overlap"), (200, "added")]:
            with self.subTest(offset=offset):
                self.assertEqual(self.stitcher.add(self.content[offset:offset + 240]), expected)
                if expected == "added":
                    np.testing.assert_array_equal(self.stitcher.image, self.content[:offset + 240])
        self.assertEqual(self.stitcher.frames, 4)

    def test_fractional_scale_brightness_changes(self):
        frame = self.content[80:320].astype(np.float32)
        frame = np.clip(frame * 0.95 + 4, 0, 255).astype(np.uint8)
        self.assertEqual(self.stitcher.add(frame), "added")
        self.assertEqual(self.stitcher.image.shape[0], 320)

    def test_changed_dimensions_fail(self):
        with self.assertRaisesRegex(ValueError, "changed size"):
            self.stitcher.add(self.content[:200])


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.content = np.random.default_rng(37).integers(
            0, 256, (600, 96, 3), dtype=np.uint8)
        for index, offset in enumerate((0, 80, 160)):
            Image.fromarray(self.content[offset:offset + 240]).save(self.directory / f"{index}.png")
        # Substitute only the capture executable; use the real backend and stdin protocol.
        grim = self.directory / "grim"
        grim.write_text(f"#!{sys.executable}\n" + '''import os
from pathlib import Path
import sys
d = Path(os.environ["LONGSHOT_TEST_DIR"])
counter = d / "counter"
i = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(i + 1))
sys.stdout.buffer.write((d / f"{min(i, 2)}.png").read_bytes())
''')
        grim.chmod(0o755)
        self.process = None

    def tearDown(self):
        if self.process:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=5)
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                if stream and not stream.closed:
                    stream.close()
        self.temp.cleanup()

    def start(self, *extra):
        environment = dict(os.environ, PATH=f"{self.directory}:{os.environ['PATH']}",
                           XDG_CONFIG_HOME=str(self.directory), LONGSHOT_TEST_DIR=str(self.directory))
        self.process = subprocess.Popen([
            sys.executable, "-u", str(SCRIPTS / "longshot_capture.py"),
            "--region", "-200,100 96x240", "--control-stdin", "--interval", "30",
            "--settle-delay", "0", "--no-copy", "--no-notify",
            "--output", str(self.directory / "result.png"), *extra,
        ], env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def event(self):
        readable, _, _ = select.select([self.process.stdout], [], [], 5)
        self.assertTrue(readable, "backend did not report progress")
        line = self.process.stdout.readline()
        self.assertTrue(line, "backend exited before reporting progress")
        return json.loads(line)

    def wait_for_frames(self, frames):
        while True:
            event = self.event()
            self.assertNotEqual(event["event"], "error", event)
            if event.get("frames", 0) >= frames:
                return

    def test_finish_captures_last_scroll_and_saves_exact_result(self):
        self.start()
        self.wait_for_frames(2)
        self.process.stdin.write(b"finish\n")
        self.process.stdin.flush()
        self.assertEqual(self.process.wait(timeout=5), 0)
        with Image.open(self.directory / "result.png") as image:
            np.testing.assert_array_equal(np.asarray(image), self.content[:400])

    def test_cancel_leaves_no_output(self):
        self.start()
        self.wait_for_frames(2)
        self.process.stdin.write(b"cancel\n")
        self.process.stdin.flush()
        self.assertEqual(self.process.wait(timeout=5), 0)
        self.assertFalse((self.directory / "result.png").exists())

    def test_owner_exit_cancels(self):
        self.start()
        self.wait_for_frames(2)
        self.process.stdin.close()
        self.assertEqual(self.process.wait(timeout=5), 0)
        self.assertFalse((self.directory / "result.png").exists())

    def test_limit_counts_accepted_frames(self):
        self.start("--max-shots", "2")
        self.assertEqual(self.process.wait(timeout=5), 0)
        with Image.open(self.directory / "result.png") as image:
            np.testing.assert_array_equal(np.asarray(image), self.content[:320])


if __name__ == "__main__":
    unittest.main()
