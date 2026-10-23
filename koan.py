#!/usr/bin/env python3
"""KoanForge: Java koans, terminal code editor, file watcher, and automatic tests."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time

from pathlib import Path
import subprocess

from engine.core import (
    EXERCISES,
    ROOT,
    WORKSPACE,
    all_lessons,
    check,
    doctor,
    prepare,
    progress,
    solution_file,
)


def _ensure_tui_environment() -> None:
    """Allow `py koan.py` / `python koan.py` to work directly without activating .venv."""
    try:
        import textual  # noqa: F401
        return
    except ImportError:
        pass

    # 1. If local .venv exists with textual installed, add its site-packages or re-exec it
    win_site = ROOT / ".venv" / "Lib" / "site-packages"
    if win_site.is_dir():
        sys.path.insert(0, str(win_site))
        try:
            import textual  # noqa: F401
            return
        except ImportError:
            pass

    for unix_site in (ROOT / ".venv").glob("lib/python*/site-packages"):
        sys.path.insert(0, str(unix_site))
        try:
            import textual  # noqa: F401
            return
        except ImportError:
            pass

    # 2. Otherwise auto-install requirements.txt into the current interpreter
    req = ROOT / "requirements.txt"
    if req.exists():
        print("Installing KoanForge TUI dependencies (first-time setup)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req)])


def lookup(slug: str):
    for lesson in all_lessons():
        if lesson.slug == slug:
            return lesson
    raise SystemExit(f"Exercise not found: {slug}. Run `python koan.py list` to see available lessons.")


def print_result(lesson, result) -> int:
    print(f"\n━━ {lesson.title} ━━")
    print(f"{result.status.upper()} | {result.passed} PASS, {result.failed} FAIL | {result.elapsed:.2f}s")
    for x in result.details:
        print("  " + x)
    print("File:", solution_file(lesson))
    return 0 if result.status == "passed" else 1


def watch(lesson, interval: float = 0.45) -> int:
    f = prepare(lesson)
    prev = -1
    print(f"Watching {f}\nPress Ctrl+C to stop. Save the file to re-run tests.\n")
    try:
        while True:
            try:
                current = f.stat().st_mtime_ns
            except FileNotFoundError:
                current = -2
            if current != prev:
                prev = current
                print("\033[2J\033[H", end="")
                print_result(lesson, check(lesson))
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


def new_lesson(slug: str) -> int:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", slug):
        raise SystemExit("Slug must contain only lowercase letters, digits, and hyphens.")
    folder = EXERCISES / slug
    if folder.exists():
        raise SystemExit(f"Exercise already exists: {slug}")
    folder.mkdir(parents=True)
    data = {
        "title": slug.replace("-", " ").title(),
        "category": "CUSTOM",
        "level": 2,
        "objective": "Custom exercise objective designed by you.",
        "instructions": [
            "Implement a method that satisfies your specification.",
            "Edit assertions in KoanTest.java to verify expected behavior.",
        ],
        "hints": ["Start with normal inputs, outputs, and boundary edge cases."],
    }
    (folder / "lesson.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (folder / "Starter.java").write_text(
        "public class Solution {\n    static int answer() {\n        // TODO\n        return 0;\n    }\n}\n",
        encoding="utf-8",
    )
    (folder / "KoanTest.java").write_text(
        'public class KoanTest {\n    public static void main(String[] args) {\n        KoanChecks.eq("Sample assertion", 42, Solution.answer());\n        KoanChecks.done();\n    }\n}\n',
        encoding="utf-8",
    )
    print("Created new exercise:", folder)
    print("Customize lesson.json, Starter.java, KoanTest.java; then run: python koan.py run", slug)
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except OSError:
            pass
    parser = argparse.ArgumentParser(description="KOANFORGE — Java terminal dojo")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("tui", help="Open full-screen interactive TUI + inline Java editor")
    sub.add_parser("list", help="List lesson status")
    sub.add_parser("doctor", help="Check JDK and environment")
    p = sub.add_parser("run", help="Compile and test one lesson")
    p.add_argument("slug")
    p = sub.add_parser("watch", help="Watch file changes and auto-test")
    p.add_argument("slug")
    p = sub.add_parser("new", help="Scaffold an original custom lesson")
    p.add_argument("slug")
    p = sub.add_parser("reset", help="Reset ONE lesson workspace, requiring --yes")
    p.add_argument("slug")
    p.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    if args.command in (None, "tui"):
        _ensure_tui_environment()
        from engine.tui import App

        return App().run()
    if args.command == "doctor":
        _ensure_tui_environment()
        for x in doctor():
            print(x)
        return 0
    if args.command == "list":
        state = progress()
        for i, l in enumerate(all_lessons(), 1):
            info = state.get(l.slug, {})
            mark = "✓" if info.get("solved") else "·"
            print(f"{mark} {i:02d} {l.slug:25} [{l.category:10}] {l.title}")
        return 0
    if args.command == "run":
        lesson = lookup(args.slug)
        return print_result(lesson, check(lesson))
    if args.command == "watch":
        return watch(lookup(args.slug))
    if args.command == "new":
        return new_lesson(args.slug)
    if args.command == "reset":
        if not args.yes:
            raise SystemExit("This deletes your personal solution for the lesson. Pass --yes to confirm.")
        l = lookup(args.slug)
        f = solution_file(l)
        if f.exists():
            f.unlink()
        state = progress()
        state.pop(l.slug, None)
        p = WORKSPACE / ".progress.json"
        if p.exists():
            p.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Reset", l.slug)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
