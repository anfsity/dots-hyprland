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
from PIL import Image, ImageDraw, ImageFont

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from longshot_capture import ManualStitcher
from longshot_stitch import match_scroll, detect_direction, stitch


class StitchTests(unittest.TestCase):
    def setUp(self):
        self.content = np.random.default_rng(24).integers(
            0, 256, (900, 96, 3), dtype=np.uint8)
        self.stitcher = ManualStitcher(self.content[:240])

    def test_pauses_backtracking_and_recovery(self):
        for offset, expected in [(0, "unchanged"), (80, "added"),
                                 (80, "unchanged"), (40, "backtracking"),
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

    def test_fixed_header_and_footer_appear_only_once(self):
        header, footer = self.content[500:526], self.content[600:620]
        def view(y):
            return np.concatenate([header, self.content[y:y + 200], footer])
        stitcher = ManualStitcher(view(0))
        for y in (31, 67, 121, 158):
            self.assertEqual(stitcher.add(view(y)), "added")
            np.testing.assert_array_equal(stitcher.image,
                np.concatenate([header, self.content[:y + 200], footer]))

    def test_repetitive_content_is_rejected_instead_of_guessed(self):
        tile = self.content[:36]
        page = np.tile(tile, (20, 1, 1))
        stitcher = ManualStitcher(page[:240])
        self.assertEqual(stitcher.add(page[13:253]), "ambiguous")
        self.assertEqual(stitcher.height, 240)
        self.assertEqual(stitcher.frames, 1)

    def test_local_animation_does_not_override_scrolling_content(self):
        frame = self.content[60:300].copy()
        frame[20:50, :18] = 0
        result = match_scroll(self.content[:240], frame)
        self.assertEqual(result.status, "added")
        self.assertEqual(result.shift, 60)

    def test_still_page_with_an_animation_is_not_appended(self):
        frame = self.content[:240].copy()
        frame[20:40, :12] = 255
        self.assertEqual(self.stitcher.add(frame), "unchanged")
        self.assertEqual(self.stitcher.frames, 1)

    def test_lost_overlap_recovers_without_adding_missing_rows(self):
        self.assertEqual(self.stitcher.add(self.content[450:690]), "no-overlap")
        self.assertEqual(self.stitcher.height, 240)
        self.assertEqual(self.stitcher.add(self.content[70:310]), "added")
        np.testing.assert_array_equal(self.stitcher.image, self.content[:310])

    def test_image_size_limit_preserves_the_last_good_frame(self):
        stitcher = ManualStitcher(self.content[:240], max_pixels=96 * 300)
        self.assertEqual(stitcher.add(self.content[40:280]), "added")
        self.assertEqual(stitcher.add(self.content[80:320]), "limit")
        np.testing.assert_array_equal(stitcher.image, self.content[:280])

    def test_many_small_scrolls_do_not_drift_or_duplicate_rows(self):
        for offset in range(3, 100, 3):
            self.assertEqual(self.stitcher.add(self.content[offset:offset + 240]), "added")
        np.testing.assert_array_equal(self.stitcher.image, self.content[:339])

    def test_direction_is_checked_both_ways(self):
        self.assertEqual(detect_direction(self.content[:240], self.content[60:300]), "down")
        self.assertEqual(detect_direction(self.content[60:300], self.content[:240]), "up")

    def test_blank_frames_are_not_fabricated_into_a_match(self):
        before = np.full((240, 96, 3), 255, dtype=np.uint8)
        after = np.full_like(before, 200)
        self.assertNotEqual(match_scroll(before, after).status, "added")


class RenderedTextTests(unittest.TestCase):
    def setUp(self):
        page = Image.new("RGB", (640, 1800), "#fafbfd")
        draw = ImageDraw.Draw(page)
        font = ImageFont.load_default(size=16)
        for index, y in enumerate(range(28, 1760, 40)):
            draw.text((22, y), f"{index:02d}  A repeated paragraph with a unique line number.",
                      fill="#28334e", font=font)
        self.page = np.asarray(page)

    def test_similar_paragraphs_use_unique_glyphs_to_disambiguate(self):
        stitcher = ManualStitcher(self.page[:480])
        for offset in (67, 142, 221, 309):
            self.assertEqual(stitcher.add(self.page[offset:offset + 480]), "added")
            np.testing.assert_array_equal(stitcher.image, self.page[:offset + 480])

    def test_text_with_fixed_toolbars_and_a_changing_scrollbar(self):
        header = np.full((40, 640, 3), [32, 46, 76], dtype=np.uint8)
        footer = np.full((24, 640, 3), [219, 224, 240], dtype=np.uint8)
        def view(y):
            frame = np.concatenate([header, self.page[y:y + 480], footer])
            frame[45:520, -5:] = 240
            frame[45 + y // 8:90 + y // 8, -5:] = 110
            return frame
        stitcher = ManualStitcher(view(0))
        for offset in (67, 142, 221):
            self.assertEqual(stitcher.add(view(offset)), "added")
        np.testing.assert_array_equal(stitcher.image[:, :-5],
            np.concatenate([header, self.page[:701], footer])[:, :-5])

    def test_brightness_changes_do_not_blur_or_resample_the_text(self):
        frame = np.clip(self.page[77:557].astype(np.float32) * 0.97 + 3, 0, 255).astype(np.uint8)
        stitcher = ManualStitcher(self.page[:480])
        self.assertEqual(stitcher.add(frame), "added")
        self.assertEqual(stitcher.height, 557)
        # Every saved pixel comes from an aligned source; no ghosted average.
        aligned_old = np.concatenate([self.page[:480], frame[403:]])
        aligned_new = np.concatenate([self.page[:77], frame])
        self.assertTrue(np.all((stitcher.image == aligned_old) | (stitcher.image == aligned_new)))

    def test_preview_keeps_its_aspect_ratio_across_many_seams(self):
        stitcher = ManualStitcher(self.page[:480])
        for offset in range(3, 70, 3):
            self.assertEqual(stitcher.add(self.page[offset:offset + 480]), "added")
        preview = stitcher.preview()
        self.assertEqual(preview.height, round(stitcher.height * preview.width / stitcher.width))


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

    def start(self, *extra, script=None):
        environment = dict(os.environ, PATH=f"{self.directory}:{os.environ['PATH']}",
                           XDG_CONFIG_HOME=str(self.directory), LONGSHOT_TEST_DIR=str(self.directory),
                           HYPRLAND_INSTANCE_SIGNATURE="")
        self.process = subprocess.Popen([
            sys.executable, "-u", str(script or SCRIPTS / "longshot_capture.py"),
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

    def send(self, command):
        self.process.stdin.write((command + "\n").encode())
        self.process.stdin.flush()

    def test_pause_stops_capture_and_finish_uses_the_accepted_view(self):
        self.start("--interval", "200")
        self.wait_for_frames(2)
        self.send("pause")
        while self.event().get("status") != "paused":
            pass
        count = (self.directory / "counter").read_text()
        # Wait using the progress protocol, not a fragile fixed startup sleep.
        self.send("pause")
        self.send("finish")
        self.assertEqual(self.process.wait(timeout=5), 0)
        self.assertEqual((self.directory / "counter").read_text(), count)
        with Image.open(self.directory / "result.png") as image:
            np.testing.assert_array_equal(np.asarray(image), self.content[:320])

    def test_resume_continues_matching(self):
        self.start("--interval", "100")
        self.wait_for_frames(2)
        self.send("pause")
        while self.event().get("status") != "paused":
            pass
        self.send("resume")
        self.wait_for_frames(3)
        self.send("finish")
        self.assertEqual(self.process.wait(timeout=5), 0)

    def test_preview_is_small_valid_and_uses_only_two_files(self):
        preview = self.directory / "preview"
        self.start("--preview-dir", str(preview), "--max-shots", "3")
        self.assertEqual(self.process.wait(timeout=5), 0)
        self.assertEqual(len(list(preview.glob("*.png"))), 2)
        self.assertEqual(list(preview.glob("*.tmp")), [])
        for path in preview.glob("*.png"):
            with Image.open(path) as image:
                self.assertLessEqual(image.width, 192)
                self.assertLessEqual(image.height, 4096)

    def test_size_limit_saves_without_exceeding_budget(self):
        self.start("--max-pixels", str(96 * 350))
        self.assertEqual(self.process.wait(timeout=5), 0)
        events = [json.loads(line) for line in self.process.stdout]
        self.assertTrue(events[-1]["limited"])
        with Image.open(self.directory / "result.png") as image:
            np.testing.assert_array_equal(np.asarray(image), self.content[:320])


if __name__ == "__main__":
    unittest.main()
