"""Comprehensive Textual TUI regression tests for KoanForge."""
from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import ListView, RichLog, Static

from engine import core
from engine.core import Assertion, CheckResult, Diagnostic, Lesson
from engine.tui import HelpModal, JavaCodeEditor, KoanForgeApp, LessonListItem


def _mock_runner(lesson: Lesson, source: str | None = None, **kwargs) -> CheckResult:
    """Fast deterministic runner that inspects the Java source and records progress."""
    code = source if source is not None else core.read_solution(lesson)
    digest = core.source_hash(code)

    if "COMPILE_ERR" in code:
        diag = Diagnostic(str(core.solution_file(lesson)), 3, 9, "error", "';' expected")
        res = CheckResult(
            "compile-error",
            [f"{diag.file}:3: error: ';' expected", "        return a = b", "                    ^"],
            0,
            0,
            0.12,
            diagnostics=[diag],
            source_hash=digest,
        )
    elif "LONG_OUTPUT" in code:
        assertions = [
            Assertion(f"Assertion #{i:02d}", i % 3 != 0, "Expected: 42, got: 0", "42", "0")
            for i in range(1, 31)
        ]
        details = [f"Line {i}" for i in range(1, 31)]
        res = CheckResult(
            "failed",
            details,
            passed=20,
            failed=10,
            elapsed=0.25,
            assertions=assertions,
            output=[f"stdout log line {i}" for i in range(1, 15)],
            source_hash=digest,
        )
    elif "return a == b;" in code or "// SOLVED" in code:
        assertions = [
            Assertion("Equal numbers", True),
            Assertion("Different numbers", True),
            Assertion("Equal negative numbers", True),
        ]
        res = CheckResult(
            "passed",
            ["✓  Equal numbers", "✓  Different numbers", "✓  Equal negative numbers"],
            passed=3,
            failed=0,
            elapsed=0.08,
            assertions=assertions,
            source_hash=digest,
        )
    else:
        assertions = [
            Assertion("Equal numbers", False, "Expected: true, got: false", "true", "false"),
            Assertion("Different numbers", True),
        ]
        res = CheckResult(
            "failed",
            ["✗  Equal numbers — Expected: true, got: false", "✓  Different numbers"],
            passed=1,
            failed=1,
            elapsed=0.09,
            assertions=assertions,
            source_hash=digest,
        )

    core.save_progress(lesson.slug, res)
    return res


class TuiRegressionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        self.p1 = patch.object(core, "WORKSPACE", self.ws)
        self.p2 = patch.object(core, "STATE", self.ws / ".progress.json")
        self.p1.start()
        self.p2.start()
        self.addCleanup(self.p1.stop)
        self.addCleanup(self.p2.stop)

    async def _wait_for_check(self, app: KoanForgeApp, pilot) -> None:
        for _ in range(50):
            await pilot.pause(0.03)
            expected = core.source_hash(app._current_editor_text())
            if (
                not app.is_testing
                and app.latest is not None
                and app.latest.source_hash == expected
            ):
                return

    async def test_responsive_dimensions_and_live_resize_no_overlap(self):
        """Verify 80x24, 100x30, 120x35, 160x45 layouts and live resizing have no overlaps."""
        app = KoanForgeApp(runner=_mock_runner)
        sizes = [(80, 24), (100, 30), (120, 35), (160, 45), (80, 24)]
        async with app.run_test(size=sizes[0]) as pilot:
            for w, h in sizes:
                await pilot.resize_terminal(w, h)
                await pilot.pause(0.05)

                self.assertEqual((w, h), (app.size.width, app.size.height))
                header = app.query_one("#top-header", Static)
                editor = app.query_one("#code-editor", JavaCodeEditor)
                results = app.query_one("#results-panel")
                footer = app.query_one("#status-footer", Static)

                # Every core region must stay strictly inside the terminal viewport
                for widget in (header, editor, results, footer):
                    reg = widget.region
                    self.assertGreaterEqual(reg.x, 0)
                    self.assertGreaterEqual(reg.y, 0)
                    self.assertLessEqual(reg.right, w)
                    self.assertLessEqual(reg.bottom, h)
                    self.assertGreater(reg.width, 0)
                    self.assertGreater(reg.height, 0)

                # Header, editor, results, and footer must stack vertically without overlapping
                self.assertLessEqual(header.region.bottom, editor.region.y)
                self.assertLessEqual(editor.region.bottom, results.region.y)
                self.assertLessEqual(results.region.bottom, footer.region.y)

                # Editor must receive the largest vertical workspace share on standard screens
                if h >= 30:
                    self.assertGreaterEqual(editor.region.height, results.region.height)

            # On 80x24, opening the editor auto-collapses the sidebar to maximize code width
            await pilot.press("enter")
            await pilot.pause(0.05)
            self.assertTrue(app.sidebar_collapsed)
            self.assertEqual(80, app.query_one("#code-editor").region.width)

            # Pressing Escape returns to navigator and restores the sidebar automatically
            await pilot.press("escape")
            await pilot.pause(0.05)
            self.assertFalse(app.sidebar_collapsed)
            self.assertEqual("menu", app.active_focus)

    async def test_navigation_selection_and_track_skipping(self):
        """Up/Down and j/k navigate all 18 lessons while skipping track group headers."""
        app = KoanForgeApp(runner=_mock_runner)
        async with app.run_test(size=(120, 35)) as pilot:
            self.assertEqual(0, app.selected_index)
            await pilot.press("down")
            await pilot.pause(0.02)
            self.assertEqual(1, app.selected_index)
            await pilot.press("j")
            await pilot.pause(0.02)
            self.assertEqual(2, app.selected_index)
            await pilot.press("k")
            await pilot.pause(0.02)
            self.assertEqual(1, app.selected_index)

            # Navigate all the way to lesson 18 (crossing FLOW and STRUCTURES headers)
            for _ in range(20):
                await pilot.press("down")
            await pilot.pause(0.05)
            self.assertEqual(len(app.lessons) - 1, app.selected_index)
            self.assertEqual("18-withdraw-exception", app.lesson.slug)

    async def test_open_edit_save_compile_error_and_pass_lifecycle(self):
        """Opening, editing Java, triggering compile error, fixing to pass, and persisting progress."""
        app = KoanForgeApp(runner=_mock_runner, autotest_debounce=10.0)
        async with app.run_test(size=(120, 35)) as pilot:
            # Open lesson 01
            await pilot.press("enter")
            await self._wait_for_check(app, pilot)
            self.assertEqual("editor", app.active_focus)
            self.assertEqual("failed", app.latest.status)

            editor = app.query_one("#code-editor", JavaCodeEditor)
            # Introduce a syntax error and press Ctrl+S
            editor.load_text("public class Solution { // COMPILE_ERR\n}\n")
            app.is_dirty = True
            await pilot.press("ctrl+s")
            await self._wait_for_check(app, pilot)
            self.assertFalse(app.is_dirty)
            self.assertEqual("compile-error", app.latest.status)
            self.assertEqual(1, len(app.latest.diagnostics))

            # Fix the code so all assertions pass
            solved_code = (
                "public class Solution {\n"
                "    static boolean same(int a, int b) {\n"
                "        return a == b;\n"
                "    }\n"
                "}\n"
            )
            editor.load_text(solved_code)
            app.is_dirty = True
            await pilot.press("ctrl+s")
            await self._wait_for_check(app, pilot)

            self.assertEqual("passed", app.latest.status)
            self.assertEqual(3, app.latest.passed)
            self.assertEqual("editor", app.active_focus)
            # Progress file and sidebar badge updated immediately
            self.assertTrue(core.progress()["01-equals-or-assign"]["solved"])
            self.assertTrue(app._item_widgets["01-equals-or-assign"].solved)

    async def test_autotest_debounce_and_toggle(self):
        """Auto-test runs automatically after debounce and can be toggled with Ctrl+A."""
        app = KoanForgeApp(runner=_mock_runner, autotest_debounce=0.15)
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.press("enter")
            await self._wait_for_check(app, pilot)
            self.assertEqual("failed", app.latest.status)

            # Toggle auto-test OFF with Ctrl+A
            await pilot.press("ctrl+a")
            await pilot.pause(0.02)
            self.assertFalse(app.autotest)

            # Toggle auto-test back ON with Ctrl+A
            await pilot.press("ctrl+a")
            await pilot.pause(0.02)
            self.assertTrue(app.autotest)

            # Edit buffer to a passing solution and wait for periodic tick to auto-save & test
            editor = app.query_one("#code-editor", JavaCodeEditor)
            editor.text = "public class Solution { static boolean same(int a, int b) { return a == b; } }\n"
            app.is_dirty = True
            app.last_edit_at = time.monotonic() - 1.0
            app._on_periodic_tick()
            await self._wait_for_check(app, pilot)

            self.assertFalse(app.is_dirty)
            self.assertEqual("passed", app.latest.status)

    async def test_hints_long_output_scrolling_and_help_modal(self):
        """Ctrl+T cycles hints, long test output populates RichLog, and ? opens HelpModal."""
        app = KoanForgeApp(runner=_mock_runner)
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.press("enter")
            await self._wait_for_check(app, pilot)

            # Cycle hints with Ctrl+T
            self.assertEqual(0, app.hint_step)
            await pilot.press("ctrl+t")
            await pilot.pause(0.02)
            self.assertEqual(1, app.hint_step)
            self.assertTrue(app.query_one("#hint-banner").has_class("visible"))

            # Trigger long test output
            editor = app.query_one("#code-editor", JavaCodeEditor)
            editor.load_text("public class Solution { // LONG_OUTPUT\n}\n")
            app.is_dirty = True
            await pilot.press("ctrl+s")
            await self._wait_for_check(app, pilot)
            log = app.query_one("#results-log", RichLog)
            self.assertGreaterEqual(len(log.lines), 30)

            # Focus output panel with Ctrl+L and expand with F3
            await pilot.press("ctrl+l")
            await pilot.pause(0.02)
            self.assertEqual("results", app.active_focus)
            await pilot.press("f3")
            await pilot.pause(0.02)
            self.assertTrue(app.results_expanded)

            # Open and close Help modal with F1 / Escape
            await pilot.press("f1")
            await pilot.pause(0.05)
            self.assertIsInstance(app.screen, HelpModal)
            await pilot.press("escape")
            await pilot.pause(0.05)
            self.assertNotIsInstance(app.screen, HelpModal)

    async def test_external_file_changes_and_conflict_recovery(self):
        """External edits reload clean buffers and protect dirty buffers via Solution.recovery.java."""
        app = KoanForgeApp(runner=_mock_runner, autotest_debounce=10.0)
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.press("enter")
            await self._wait_for_check(app, pilot)
            sol = core.solution_file(app.lesson)

            # 1. Clean buffer: external modification reloads automatically and runs tests
            time.sleep(0.02)
            sol.write_text("public class Solution { // SOLVED\n}\n", encoding="utf-8")
            changed = app.check_external_changes()
            self.assertTrue(changed)
            await self._wait_for_check(app, pilot)
            self.assertEqual("passed", app.latest.status)
            self.assertIn("// SOLVED", app.query_one("#code-editor", JavaCodeEditor).text)

            # 2. Dirty buffer: external modification flags conflict instead of overwriting in-memory work
            editor = app.query_one("#code-editor", JavaCodeEditor)
            editor.load_text("public class Solution { // MY_UNSAVED_DRAFT\n}\n")
            app.is_dirty = True
            time.sleep(0.02)
            sol.write_text("public class Solution { // EXTERNAL_IDE_EDIT\n}\n", encoding="utf-8")
            changed = app.check_external_changes()
            self.assertTrue(changed)
            self.assertTrue(app.external_conflict)
            self.assertIn("MY_UNSAVED_DRAFT", editor.text)

            # Leaving the lesson preserves in-memory draft to Solution.recovery.java without clobbering disk
            await pilot.press("ctrl+n")
            await self._wait_for_check(app, pilot)
            recovery = sol.with_name("Solution.recovery.java")
            self.assertTrue(recovery.exists())
            self.assertIn("MY_UNSAVED_DRAFT", recovery.read_text(encoding="utf-8"))
            self.assertIn("EXTERNAL_IDE_EDIT", sol.read_text(encoding="utf-8"))

    async def test_switching_lessons_and_clean_exit_preserve_edits(self):
        """Switching lessons or pressing Ctrl+Q saves any unsaved edits cleanly."""
        app = KoanForgeApp(runner=_mock_runner, autotest_debounce=10.0)
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.press("enter")
            await self._wait_for_check(app, pilot)
            editor = app.query_one("#code-editor", JavaCodeEditor)
            editor.load_text("public class Solution { // SAVED_ON_QUIT\n}\n")
            app.is_dirty = True

            await pilot.press("ctrl+q")
            await pilot.pause(0.05)

            sol = core.solution_file(app.lessons[0])
            self.assertIn("SAVED_ON_QUIT", sol.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
