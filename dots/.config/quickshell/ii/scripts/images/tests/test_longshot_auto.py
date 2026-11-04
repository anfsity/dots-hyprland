"""Auto-scroll pacing and session controls; all desktop input is substituted."""

import json
from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image

import test_longshot_capture as manual_tests
from longshot_auto import AutoPacer, AutoScrollError, ScrollTarget


class PacerTests(unittest.TestCase):
    def test_waits_for_a_stable_frame_and_minimum_delay(self):
        pacer = AutoPacer(800)
        still = np.zeros((240, 96, 3), dtype=np.uint8)
        changed = np.full_like(still, 200)
        pacer.begin(0)
        self.assertFalse(pacer.settled(still, 0.1))
        self.assertFalse(pacer.settled(still, 0.2))
        self.assertFalse(pacer.settled(changed, 0.4))
        self.assertFalse(pacer.settled(changed, 0.5))
        self.assertTrue(pacer.settled(changed, 0.6))
        self.assertTrue(pacer.timed_out(3.1))

    def test_observed_shift_adapts_the_next_step_with_bounds(self):
        pacer = AutoPacer(800)
        original = pacer.amount
        pacer.accepted("added", 500)
        self.assertLess(pacer.amount, original)
        for _ in range(30):
            pacer.accepted("added", 1)
        self.assertEqual(pacer.amount, 120)
        for _ in range(30):
            pacer.accepted("added", 1000)
        self.assertEqual(pacer.amount, 8)

    def test_bottom_requires_three_independent_scrolls_without_growth(self):
        pacer = AutoPacer(800)
        self.assertFalse(pacer.accepted("unchanged", 0))
        self.assertFalse(pacer.accepted("unchanged", 0))
        self.assertTrue(pacer.accepted("unchanged", 0))
        pacer.accepted("added", 80)
        self.assertFalse(pacer.accepted("unchanged", 0))


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.window = {"address": "0x123", "at": [-300, 0], "size": [500, 600],
                       "workspace": {"id": 2}, "fullscreen": 0}
        self.target = ScrollTarget("-200,100 96x240", self.window)

    def test_arming_waits_for_pointer_inside_region(self):
        self.assertFalse(self.target.check(self.window, {"x": 1, "y": 1}, arming=True))
        self.assertTrue(self.target.check(self.window, {"x": -150, "y": 200}, arming=True))
        self.assertTrue(self.target.check(self.window, {"x": -150, "y": 200}))

    def test_user_pointer_movement_stops_input_even_inside_the_region(self):
        self.target.check(self.window, {"x": -150, "y": 200}, arming=True)
        with self.assertRaisesRegex(AutoScrollError, "Pointer moved"):
            self.target.check(self.window, {"x": -140, "y": 200})

    def test_focus_workspace_geometry_changes_and_missing_window_stop_input(self):
        for changes in ({"address": "0x456"}, {"at": [-299, 0]},
                        {"size": [501, 600]}, {"workspace": {"id": 3}},
                        {"fullscreen": 1}, {"address": None}):
            with self.subTest(changes=changes), self.assertRaises(AutoScrollError):
                self.target.check(dict(self.window, **changes), {"x": -150, "y": 200}, arming=True)

    def test_does_not_arm_over_an_unrelated_window(self):
        target = ScrollTarget("1000,1000 96x240", self.window)
        with self.assertRaises(AutoScrollError):
            target.check(self.window, {"x": 1050, "y": 1100}, arming=True)

    def test_pointer_must_be_inside_the_target_window_even_for_a_wider_selection(self):
        target = ScrollTarget("-400,100 400x240", self.window)
        self.assertFalse(target.check(self.window, {"x": -350, "y": 200}, arming=True))
        self.assertTrue(target.check(self.window, {"x": -250, "y": 200}, arming=True))


class AutoSessionTests(unittest.TestCase):
    def setUp(self):
        self.session = manual_tests.SessionTests()
        self.session.setUp()
        self.addCleanup(self.session.tearDown)
        self.directory = self.session.directory
        Image.fromarray(self.session.content[350:590]).save(self.directory / "3.png")
        grim = self.directory / "grim"
        grim.write_text(f"#!{sys.executable}\n" + '''import os
from pathlib import Path
import sys
d = Path(os.environ["LONGSHOT_TEST_DIR"])
counter = d / "scroll-count"
n = int(counter.read_text()) if counter.exists() else 0
index = min(n, 2)
if (d / "lose-overlap").exists() and n > 1: index = 3
sys.stdout.buffer.write((d / f"{index}.png").read_bytes())
''')
        self.wrapper = self.directory / "backend.py"
        self.wrapper.write_text(f"import sys\nsys.path.insert(0, {str(manual_tests.SCRIPTS)!r})\n" + '''
import os
from pathlib import Path
import longshot_capture as backend
from longshot_auto import AutoScrollError
d = Path(os.environ["LONGSHOT_TEST_DIR"])
backend.snapshot_target = lambda: {"address": "capture-target"}
class FakeScroller:
    def __init__(self, region, window):
        assert window == {"address": "capture-target"}
        (d / "driver-created").touch()
        if (d / "unavailable").exists():
            raise AutoScrollError("Auto-scroll is unavailable. Continue with manual scrolling.")
    def arm(self): pass
    def check(self, arming=False):
        if (d / "changed-window").exists():
            raise AutoScrollError("The capture window changed. Resume in the original window or use manual scrolling.")
        return not (d / "pointer-outside").exists()
    def scroll(self, amount):
        self.check()
        counter = d / "scroll-count"
        n = int(counter.read_text()) if counter.exists() else 0
        counter.write_text(str(n + 1))
    def close(self): pass
backend.DesktopScroller = FakeScroller
sys.exit(backend.main())
''')

    def start(self, *extra):
        self.session.start("--auto-settle", "200", *extra, script=self.wrapper)

    def until(self, predicate):
        for _ in range(100):
            event = self.session.event()
            self.assertNotEqual(event["event"], "error", event)
            if predicate(event):
                return event
        self.fail("Expected event did not arrive")

    def finish(self):
        self.session.send("finish")
        self.assertEqual(self.session.process.wait(timeout=5), 0)

    def test_manual_is_default_and_never_constructs_or_uses_input(self):
        self.start()
        first = self.session.event()
        self.assertFalse(first["automatic"])
        self.session.send("cancel")
        self.assertEqual(self.session.process.wait(timeout=5), 0)
        self.assertFalse((self.directory / "scroll-count").exists())
        self.assertFalse((self.directory / "driver-created").exists())

    def test_auto_paces_verified_frames_and_finishes_after_repeated_still_views(self):
        self.start("--auto-scroll")
        done = self.until(lambda event: event["event"] == "done")
        self.assertTrue(done["bottomReached"])
        self.assertEqual(done["frames"], 3)
        self.assertEqual((self.directory / "scroll-count").read_text(), "5")
        self.assertEqual(self.session.process.wait(timeout=5), 0)
        with Image.open(self.directory / "result.png") as image:
            np.testing.assert_array_equal(np.asarray(image), self.session.content[:400])

    def test_user_input_pauses_and_finish_saves_only_the_verified_view(self):
        self.start("--auto-scroll")
        self.session.wait_for_frames(2)
        self.session.send("interrupt")
        event = self.until(lambda event: event.get("status") == "paused")
        self.assertIn("Manual input", event["message"])
        count = (self.directory / "scroll-count").read_text()
        self.finish()
        self.assertEqual((self.directory / "scroll-count").read_text(), count)
        with Image.open(self.directory / "result.png") as image:
            np.testing.assert_array_equal(np.asarray(image), self.session.content[:320])

    def test_auto_can_be_selected_paused_resumed_and_switched_back_to_manual(self):
        self.start()
        self.session.event()
        self.session.send("auto")
        self.session.wait_for_frames(2)
        self.session.send("pause")
        self.until(lambda event: event.get("status") == "paused")
        self.session.send("resume")
        self.session.wait_for_frames(3)
        self.session.send("manual")
        event = self.until(lambda event: event.get("automatic") is False)
        self.assertNotEqual(event["status"], "paused")
        self.finish()

    def test_lost_overlap_pauses_before_sending_another_scroll(self):
        (self.directory / "lose-overlap").touch()
        self.start("--auto-scroll")
        event = self.until(lambda event: event.get("status") == "paused")
        self.assertIn("Alignment lost", event["message"])
        self.assertEqual(event["frames"], 2)
        self.assertEqual((self.directory / "scroll-count").read_text(), "2")
        self.finish()
        with Image.open(self.directory / "result.png") as image:
            np.testing.assert_array_equal(np.asarray(image), self.session.content[:320])

    def test_window_change_pauses_without_more_input(self):
        self.start("--auto-scroll")
        self.session.wait_for_frames(2)
        (self.directory / "changed-window").touch()
        event = self.until(lambda event: event.get("status") == "paused")
        self.assertIn("window changed", event["message"])
        count = (self.directory / "scroll-count").read_text()
        self.finish()
        self.assertEqual((self.directory / "scroll-count").read_text(), count)

    def test_arming_outside_content_never_sends_a_scroll(self):
        (self.directory / "pointer-outside").touch()
        self.start("--auto-scroll")
        self.until(lambda event: event.get("status") == "auto-arming")
        self.assertFalse((self.directory / "scroll-count").exists())
        self.session.send("cancel")
        self.assertEqual(self.session.process.wait(timeout=5), 0)

    def test_unavailable_auto_input_keeps_manual_capture_alive(self):
        (self.directory / "unavailable").touch()
        self.start("--auto-scroll")
        event = self.until(lambda event: event.get("autoAvailable") is False)
        self.assertFalse(event["automatic"])
        self.assertIn("unavailable", event["message"])
        self.assertIsNone(self.session.process.poll())
        self.assertFalse((self.directory / "scroll-count").exists())
        self.session.send("cancel")
        self.assertEqual(self.session.process.wait(timeout=5), 0)


if __name__ == "__main__":
    unittest.main()
