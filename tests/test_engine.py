"""Engine, CLI, and inline editor unit tests."""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from engine import core
from engine.tui import Editor, crop, visible_length
import koan


def _fake_subprocess_run(cmd, *args, **kwargs):
    """Deterministic fastjavac/java simulator for sandbox-safe unit tests when real javac is slow/blocked."""
    exe = Path(cmd[0]).name.lower()
    if exe.startswith("javac"):
        # Inspect the Solution.java snapshot being compiled
        sol_candidates = [Path(p) for p in cmd if str(p).endswith("Solution.java")]
        code = sol_candidates[0].read_text(encoding="utf-8") if sol_candidates else ""
        if "this is not Java" in code or "SYNTAX_ERROR" in code:
            err = f"{sol_candidates[0]}:1: error: ';' expected\npublic class Solution {{this is not Java}}\n                       ^\n1 error\n"
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=err)
        # Write a marker file in output dir so simulated java knows what was compiled
        if "-d" in cmd:
            out_dir = Path(cmd[cmd.index("-d") + 1])
            (out_dir / "_compiled_solution.txt").write_text(code, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    if exe.startswith("java"):
        if "-version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr='openjdk version "21.0.12"\n')
        cp_dir = Path(cmd[cmd.index("-cp") + 1]) if "-cp" in cmd else None
        code = ""
        if cp_dir and (cp_dir / "_compiled_solution.txt").exists():
            code = (cp_dir / "_compiled_solution.txt").read_text(encoding="utf-8")
        if "INFINITE_LOOP" in code:
            raise subprocess.TimeoutExpired(cmd, timeout=kwargs.get("timeout", 9.0))
        if "RUNTIME_CRASH" in code:
            return subprocess.CompletedProcess(
                cmd, 1, stdout="", stderr="Exception in thread \"main\" java.lang.RuntimeException: boom\n\tat Solution.same(Solution.java:3)\n"
            )
        if "return a == b;" in code:
            out = (
                "PASS\tEqual numbers\n"
                "PASS\tDifferent numbers\n"
                "PASS\tEqual negative numbers\n"
                "RESULT\t3\t0\n"
            )
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
        out = (
            "FAIL\tEqual numbers\tExpected: true, got: false\n"
            "PASS\tDifferent numbers\n"
            "FAIL\tEqual negative numbers\tCondition returned false\n"
            "RESULT\t1\t2\n"
        )
        return subprocess.CompletedProcess(cmd, 1, stdout=out, stderr="")

    return subprocess.CompletedProcess(cmd, 0, stdout="Python 3.13\n", stderr="")


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name)
        self.p1 = patch.object(core, "WORKSPACE", self.ws)
        self.p2 = patch.object(core, "STATE", self.ws / ".progress.json")
        self.p3 = patch.object(core.subprocess, "run", side_effect=_fake_subprocess_run)
        self.p1.start()
        self.p2.start()
        self.p3.start()
        self.addCleanup(self.p1.stop)
        self.addCleanup(self.p2.stop)
        self.addCleanup(self.p3.stop)

    def test_lessons_have_metadata_and_failing_starter(self):
        lessons = core.all_lessons()
        self.assertGreaterEqual(len(lessons), 18)
        lesson = lessons[0]
        self.assertEqual("01 · Assign or compare?", lesson.title)
        self.assertEqual("Assign or compare?", lesson.short_title)
        self.assertTrue(core.prepare(lesson).exists())
        result = core.check(lesson)
        self.assertEqual("failed", result.status)
        self.assertGreater(result.failed, 0)
        self.assertEqual(3, len(result.assertions))
        self.assertFalse(result.assertions[0].passed)
        self.assertEqual("true", result.assertions[0].expected)
        self.assertEqual("false", result.assertions[0].actual)

    def test_successful_solution_is_recorded(self):
        lesson = core.all_lessons()[0]
        f = core.prepare(lesson)
        f.write_text(
            "public class Solution { static boolean same(int a,int b) { return a == b; } }\n",
            encoding="utf-8",
        )
        r = core.check(lesson)
        self.assertEqual("passed", r.status)
        self.assertEqual(3, r.passed)
        self.assertEqual(0, r.failed)
        self.assertTrue(core.progress()[lesson.slug]["solved"])

    def test_compiler_error_and_structured_diagnostics(self):
        lesson = core.all_lessons()[0]
        core.prepare(lesson).write_text(
            "public class Solution {this is not Java}", encoding="utf-8"
        )
        r = core.check(lesson)
        self.assertEqual("compile-error", r.status)
        self.assertEqual(1, len(r.diagnostics))
        self.assertEqual(1, r.diagnostics[0].line)
        self.assertIn("';' expected", r.diagnostics[0].message)

    def test_runtime_error_and_timeout(self):
        lesson = core.all_lessons()[0]
        r_crash = core.check(lesson, source="public class Solution { // RUNTIME_CRASH\n}\n")
        self.assertEqual("runtime-error", r_crash.status)
        self.assertTrue(any("RuntimeException" in line for line in r_crash.details))

        r_timeout = core.check(lesson, source="public class Solution { // INFINITE_LOOP\n}\n")
        self.assertEqual("timeout", r_timeout.status)
        self.assertTrue(any("timed out" in line for line in r_timeout.details))

    def test_cli_commands_list_doctor_new_reset(self):
        with patch.object(koan, "WORKSPACE", self.ws):
            buf = io.StringIO()
            with patch.object(sys, "argv", ["koan.py", "list"]), redirect_stdout(buf):
                rc = koan.main()
            self.assertEqual(0, rc)
            self.assertIn("01-equals-or-assign", buf.getvalue())

            buf = io.StringIO()
            with patch.object(sys, "argv", ["koan.py", "doctor"]), redirect_stdout(buf):
                rc = koan.main()
            self.assertEqual(0, rc)
            self.assertIn("Lessons:", buf.getvalue())

            # Test reset on a temporary workspace lesson
            lesson = core.all_lessons()[0]
            sol = core.prepare(lesson)
            core.save_progress(lesson.slug, core.CheckResult("passed", [], 3, 0, 0.1))
            self.assertTrue(sol.exists())
            with patch.object(sys, "argv", ["koan.py", "reset", lesson.slug, "--yes"]), redirect_stdout(io.StringIO()):
                rc = koan.main()
            self.assertEqual(0, rc)
            self.assertFalse(sol.exists())
            self.assertNotIn(lesson.slug, core.progress())


class EditorAndUnicodeTests(unittest.TestCase):
    def test_type_enter_backspace_and_serialize(self):
        e = Editor("first\nsecond\n")
        e.handle("END")
        e.handle("!")
        self.assertEqual("first!", e.lines[0])
        e.handle("ENTER")
        self.assertEqual(["first!", "", "second"], e.lines)
        e.handle("BACKSPACE")
        self.assertEqual(["first!", "second"], e.lines)
        self.assertEqual(6, e.x)
        self.assertEqual("first!\nsecond\n", e.serialize())

    def test_unicode_display_width_and_cropping(self):
        # Combining characters have 0 extra width; CJK/fullwidth have width 2
        composed = "e\u0301"  # e + combining acute accent
        self.assertEqual(1, visible_length(composed))
        cjk = "日本語"
        self.assertEqual(6, visible_length(cjk))
        self.assertEqual("日本", crop(cjk, 5))


if __name__ == "__main__":
    unittest.main()
