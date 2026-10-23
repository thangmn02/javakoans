"""KoanForge Textual TUI — full-screen Java learning dojo and code workspace."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path
from typing import Callable

from rich.console import Group
from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import App as TextualApp, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Footer, Label, ListItem, ListView, RichLog, Static, TextArea
from textual.widgets.text_area import TextAreaTheme

from .core import (
    ROOT,
    CheckResult,
    Lesson,
    all_lessons,
    check,
    prepare,
    progress,
    read_solution,
    solution_file,
    source_hash,
    write_solution,
    write_text_atomic,
)

ANSI = re.compile(r"\x1b\[[0-9;]*m")

# Legacy helper functions kept for backward compatibility and width tests.
def visible_length(s: str) -> int:
    raw = ANSI.sub("", s)
    return sum(
        2 if unicodedata.east_asian_width(c) in "WF" else 0 if unicodedata.combining(c) else 1
        for c in raw
    )


def crop(s: str, n: int) -> str:
    """Crop plain text to a terminal display width; source code is not modified."""
    if n <= 0:
        return ""
    out: list[str] = []
    used = 0
    for ch in s:
        width = (
            2
            if unicodedata.east_asian_width(ch) in "WF"
            else 0
            if unicodedata.combining(ch)
            else 1
        )
        if used + width > n:
            break
        out.append(ch)
        used += width
    return "".join(out)


class Editor:
    """In-memory line buffer retained for backward compatibility with unit tests."""

    def __init__(self, source: str):
        self.lines = source.split("\n")
        if self.lines and self.lines[-1] == "":
            self.lines.pop()
        if not self.lines:
            self.lines = [""]
        self.y = 0
        self.x = 0
        self.top = 0
        self.left = 0
        self.dirty = False

    def serialize(self) -> str:
        return "\n".join(self.lines) + "\n"

    def refresh(self, source: str) -> None:
        self.__init__(source)

    def keep_visible(self, height: int, width: int) -> None:
        if self.y < self.top:
            self.top = self.y
        if self.y >= self.top + height:
            self.top = self.y - height + 1
        if self.x < self.left:
            self.left = self.x
        if self.x >= self.left + width:
            self.left = self.x - width + 1

    def handle(self, key: str) -> None:
        if key == "UP":
            self.y = max(0, self.y - 1)
        elif key == "DOWN":
            self.y = min(len(self.lines) - 1, self.y + 1)
        elif key == "LEFT":
            if self.x > 0:
                self.x -= 1
            elif self.y > 0:
                self.y -= 1
                self.x = len(self.lines[self.y])
        elif key == "RIGHT":
            if self.x < len(self.lines[self.y]):
                self.x += 1
            elif self.y < len(self.lines) - 1:
                self.y += 1
                self.x = 0
        elif key == "HOME":
            self.x = 0
        elif key == "END":
            self.x = len(self.lines[self.y])
        elif key == "DELETE":
            if self.x < len(self.lines[self.y]):
                s = self.lines[self.y]
                self.lines[self.y] = s[: self.x] + s[self.x + 1 :]
                self.dirty = True
            elif self.y < len(self.lines) - 1:
                self.lines[self.y] += self.lines.pop(self.y + 1)
                self.dirty = True
        elif key == "BACKSPACE":
            if self.x > 0:
                s = self.lines[self.y]
                self.lines[self.y] = s[: self.x - 1] + s[self.x :]
                self.x -= 1
                self.dirty = True
            elif self.y > 0:
                self.x = len(self.lines[self.y - 1])
                self.lines[self.y - 1] += self.lines.pop(self.y)
                self.y -= 1
                self.dirty = True
        elif key == "ENTER":
            s = self.lines[self.y]
            indentation = len(s) - len(s.lstrip(" "))
            indent = " " * indentation
            if s[: self.x].rstrip().endswith("{"):
                indent += "    "
            self.lines[self.y] = s[: self.x]
            self.lines.insert(self.y + 1, indent + s[self.x :])
            self.y += 1
            self.x = len(indent)
            self.dirty = True
        elif key == "TAB":
            self.insert("    ")
        elif len(key) == 1 and ord(key) >= 32:
            self.insert(key)
        self.x = min(self.x, len(self.lines[self.y]))

    def insert(self, text: str) -> None:
        s = self.lines[self.y]
        self.lines[self.y] = s[: self.x] + text + s[self.x :]
        self.x += len(text)
        self.dirty = True


# Custom syntax theme matching KoanForge dojo palette
KOANFORGE_EDITOR_THEME = TextAreaTheme(
    name="koanforge",
    base_style=Style(color="#e8effc", bgcolor="#0e121e"),
    gutter_style=Style(color="#6e82a0", bgcolor="#0e121e"),
    cursor_style=Style(color="#0e121e", bgcolor="#60e2df", bold=True),
    cursor_line_style=Style(bgcolor="#19253a"),
    cursor_line_gutter_style=Style(color="#60e2df", bgcolor="#19253a", bold=True),
    bracket_matching_style=Style(color="#ffc66d", bgcolor="#263859", bold=True),
    selection_style=Style(bgcolor="#284268"),
    syntax_styles={
        "keyword": Style(color="#c89bff", bold=True),
        "type": Style(color="#60e2df"),
        "type.builtin": Style(color="#60e2df", bold=True),
        "function.method": Style(color="#7cc7ff"),
        "function.builtin": Style(color="#7cc7ff"),
        "string": Style(color="#85efa5"),
        "string.escape": Style(color="#ffc66d"),
        "number": Style(color="#ffc66d"),
        "constant": Style(color="#ffc66d"),
        "constant.builtin": Style(color="#ffc66d", bold=True),
        "boolean": Style(color="#ffc66d", bold=True),
        "comment": Style(color="#7f93ae", italic=True),
        "operator": Style(color="#60e2df"),
        "variable.builtin": Style(color="#c89bff", italic=True),
        "attribute": Style(color="#ffc66d"),
    },
)


class JavaCodeEditor(TextArea):
    """Java code editor with smart auto-indentation and Escape-to-navigator support."""

    # Remove Ctrl+A from TextArea's line-start binding so App's Ctrl+A (Toggle Auto-test) works
    # while Home still moves to start of line and F7 selects all.
    BINDINGS = [
        Binding("home", "cursor_line_start", "Line Start", show=False),
        Binding("end,ctrl+e", "cursor_line_end", "Line End", show=False),
    ]

    class EscapePressed(events.Message):
        """Emitted when the user presses Escape inside the editor."""

    class CursorMoved(events.Message):
        """Emitted when cursor location changes."""

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self.post_message(self.EscapePressed())
            return

        if not self.read_only and event.key == "enter":
            event.stop()
            event.prevent_default()
            self._restart_blink()
            start, end = self.selection
            row, col = start
            line = self.document.get_line(row) if row < self.document.line_count else ""
            indentation = len(line) - len(line.lstrip(" "))
            indent = " " * indentation
            if line[:col].rstrip().endswith("{"):
                indent += "    "
            self._replace_via_keyboard("\n" + indent, start, end)
            return

        await super()._on_key(event)

    def _on_text_area_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        self.post_message(self.CursorMoved())


class LessonListItem(ListItem):
    """Selectable sidebar item representing a single Java exercise."""

    def __init__(self, lesson_index: int, lesson: Lesson, solved: bool) -> None:
        super().__init__(id=f"lesson-item-{lesson.slug}", classes="lesson-item")
        self.lesson_index = lesson_index
        self.lesson = lesson
        self.solved = solved
        self._label = Label(self._format_label(solved), classes="lesson-label")

    @staticmethod
    def _format_label(solved: bool, idx: int = 0, short: str = "") -> Text:
        t = Text(no_wrap=True, overflow="ellipsis")
        mark = "✓" if solved else "◇"
        mark_style = "bold #85efa5" if solved else "#7f93ae"
        num_style = "bold #60e2df" if solved else "#9fb3ce"
        title_style = "#e8effc" if not solved else "#b9f5cc"
        t.append(f" {mark} ", style=mark_style)
        t.append(f"{idx + 1:02d} ", style=num_style)
        t.append(short, style=title_style)
        return t

    def compose(self) -> ComposeResult:
        self._label.update(
            self._format_label(self.solved, self.lesson_index, self.lesson.short_title)
        )
        yield self._label

    def set_solved(self, solved: bool) -> None:
        self.solved = solved
        self._label.update(
            self._format_label(self.solved, self.lesson_index, self.lesson.short_title)
        )


class TrackHeaderItem(ListItem):
    """Non-selectable track group header inside the Exercise Navigator."""

    def __init__(self, category: str) -> None:
        super().__init__(classes="track-header", disabled=True)
        self.category = category

    def compose(self) -> ComposeResult:
        t = Text(f"── {self.category} ", style="bold #c89bff", no_wrap=True, overflow="ellipsis")
        yield Label(t)


class HelpModal(ModalScreen[None]):
    """Keyboard shortcuts & workflow reference modal."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
        Binding("question_mark", "dismiss", "Close"),
        Binding("f1", "dismiss", "Close"),
        Binding("enter", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        content = Text()
        content.append("◆ KOANFORGE // KEYBOARD SHORTCUTS & WORKFLOW\n\n", style="bold #60e2df")

        rows = [
            ("Up / Down (j / k)", "Navigate exercises in sidebar or move cursor in editor"),
            ("Enter", "Open selected exercise & focus Java editor"),
            ("Escape", "Return focus from editor/output to exercise navigator"),
            ("Ctrl+S / Ctrl+R", "Save Solution.java and run javac + KoanTest immediately"),
            ("Ctrl+T / F2", "Cycle progressive hints for the current exercise"),
            ("Ctrl+N", "Save changes and advance to the next exercise"),
            ("Ctrl+A", "Toggle 1.5s debounced auto-test on edit (ON by default)"),
            ("Ctrl+L / F3", "Focus / expand Test Results panel for scrolling"),
            ("Ctrl+B / F4", "Toggle Exercise Navigator sidebar (useful on narrow screens)"),
            ("Ctrl+O", "Open Solution.java in external $EDITOR / Notepad"),
            ("Ctrl+Z / Ctrl+Y", "Undo / Redo inside the Java editor"),
            ("? / F1", "Open or close this Help overlay"),
            ("Ctrl+Q", "Save pending edits and quit KoanForge"),
        ]
        for key, desc in rows:
            content.append(f"  {key:<20}", style="bold #ffc66d")
            content.append(f"{desc}\n", style="#e8effc")

        content.append("\nWORKFLOW & FILE WATCHER\n", style="bold #c89bff")
        content.append(
            "  • Edit code directly in the built-in Java editor or in an external IDE.\n"
            "  • External saves are detected automatically; if you have unsaved in-memory\n"
            "    edits, KoanForge warns you and backs up your draft to Solution.recovery.java\n"
            "    when switching lessons so work is never lost.\n\n",
            style="#9fb3ce",
        )
        content.append("Press Esc, Enter, or ? to close.", style="italic #7f93ae")

        with Vertical(id="help-dialog"):
            yield Static(content, id="help-body")

    def action_dismiss(self) -> None:
        self.dismiss(None)


class KoanForgeApp(TextualApp[int]):
    """Production Textual TUI for KoanForge Java."""

    TITLE = "KOANFORGE // JAVA TERMINAL DOJO"

    CSS = """
    Screen {
        background: #0e121e;
        color: #e8effc;
        layout: vertical;
    }

    #top-header {
        height: 3;
        width: 100%;
        background: #131929;
        color: #e8effc;
        padding: 0 1;
        border-bottom: solid #24324d;
    }

    Screen.compact-height #top-header {
        height: 1;
        border-bottom: none;
    }

    #body-container {
        width: 100%;
        height: 1fr;
        layout: horizontal;
    }

    #sidebar {
        width: 30;
        min-width: 24;
        max-width: 36;
        height: 100%;
        background: #111726;
        border-right: solid #24324d;
        layout: vertical;
    }

    #sidebar.collapsed {
        display: none;
    }

    #sidebar-header {
        height: 1;
        width: 100%;
        background: #172034;
        color: #60e2df;
        padding: 0 1;
        text-style: bold;
    }

    #lesson-list {
        width: 100%;
        height: 1fr;
        background: #111726;
        border: none;
        padding: 0;
        scrollbar-size-vertical: 1;
    }

    #lesson-list:focus {
        border: none;
    }

    ListItem.track-header {
        height: 1;
        background: #141c2e;
        color: #c89bff;
        padding: 0 1;
    }

    ListItem.lesson-item {
        height: 1;
        padding: 0;
        background: #111726;
        color: #e8effc;
    }

    ListItem.lesson-item:hover {
        background: #182338;
    }

    ListItem.lesson-item.-highlight {
        background: #1e2e43;
        color: #60e2df;
        text-style: bold;
    }

    #lesson-list:focus > ListItem.lesson-item.-highlight {
        background: #243b57;
        color: #60e2df;
        text-style: bold;
    }

    .lesson-label {
        width: 100%;
        height: 1;
    }

    #workspace {
        width: 1fr;
        height: 100%;
        layout: vertical;
        background: #0e121e;
    }

    #lesson-brief {
        width: 100%;
        height: auto;
        max-height: 6;
        background: #131929;
        padding: 0 1;
        border-bottom: solid #1f2b42;
        overflow-y: auto;
    }

    Screen.compact-height #lesson-brief {
        max-height: 3;
        border-bottom: none;
    }

    #editor-toolbar {
        width: 100%;
        height: 1;
        background: #172034;
        color: #ffc66d;
        padding: 0 1;
    }

    #hint-banner {
        width: 100%;
        height: auto;
        max-height: 3;
        background: #241f14;
        color: #ffc66d;
        padding: 0 1;
        border-bottom: solid #4a3b1a;
        display: none;
    }

    #hint-banner.visible {
        display: block;
    }

    #code-editor {
        width: 100%;
        height: 1fr;
        min-height: 5;
        background: #0e121e;
        border: none;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
    }

    #code-editor:focus {
        border-left: tall #60e2df;
    }

    #results-panel {
        width: 100%;
        height: 8;
        min-height: 4;
        background: #101624;
        border-top: solid #24324d;
        layout: vertical;
    }

    Screen.compact-height #results-panel {
        height: 5;
    }

    #results-panel.expanded {
        height: 60%;
    }

    #results-header {
        width: 100%;
        height: 1;
        background: #161f33;
        padding: 0 1;
    }

    #results-log {
        width: 100%;
        height: 1fr;
        background: #101624;
        color: #e8effc;
        border: none;
        padding: 0 1;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
    }

    #results-log:focus {
        border-left: tall #c89bff;
        background: #131b2c;
    }

    #status-footer {
        width: 100%;
        height: 1;
        background: #172034;
        color: #e8effc;
        padding: 0 1;
    }

    HelpModal {
        align: center middle;
        background: rgba(8, 11, 20, 0.82);
    }

    #help-dialog {
        width: 76;
        max-width: 96%;
        height: auto;
        max-height: 90%;
        background: #131929;
        border: round #60e2df;
        padding: 1 2;
    }

    #help-body {
        width: 100%;
        height: auto;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "save_and_test", "Save & Test", priority=True),
        Binding("ctrl+r", "save_and_test", "Re-run Test", show=False, priority=True),
        Binding("ctrl+t", "cycle_hint", "Hint", priority=True),
        Binding("f2", "cycle_hint", "Hint", show=False, priority=True),
        Binding("ctrl+n", "next_lesson", "Next", priority=True),
        Binding("ctrl+a", "toggle_autotest", "Auto-Test", priority=True),
        Binding("ctrl+l", "focus_results", "Output", priority=True),
        Binding("f3", "toggle_expand_results", "Expand Output", show=False, priority=True),
        Binding("ctrl+b", "toggle_sidebar", "Sidebar", priority=True),
        Binding("f4", "toggle_sidebar", "Sidebar", show=False, priority=True),
        Binding("ctrl+o", "external_editor", "Ext Editor", show=False, priority=True),
        Binding("f1", "show_help", "Help", priority=True),
        Binding("question_mark", "show_help", "Help", show=False),
        Binding("ctrl+q", "quit_app", "Quit", priority=True),
    ]

    selected_index: reactive[int] = reactive(0)
    active_focus: reactive[str] = reactive("menu")
    is_dirty: reactive[bool] = reactive(False)
    autotest: reactive[bool] = reactive(True)
    hint_step: reactive[int] = reactive(0)
    is_testing: reactive[bool] = reactive(False)
    sidebar_collapsed: reactive[bool] = reactive(False)
    results_expanded: reactive[bool] = reactive(False)
    external_conflict: reactive[bool] = reactive(False)
    status_message: reactive[str] = reactive(
        "Use ↑/↓ to select an exercise, then press Enter to open it."
    )

    # Debounce interval (seconds) before auto-saving & running tests after typing stops.
    AUTOTEST_DEBOUNCE: float = 1.5
    WATCH_INTERVAL: float = 0.45
    NARROW_WIDTH: int = 94
    COMPACT_HEIGHT: int = 26

    def __init__(
        self,
        *,
        lessons: list[Lesson] | None = None,
        runner: Callable[..., CheckResult] | None = None,
        autotest_debounce: float | None = None,
        open_initial: bool = False,
    ) -> None:
        super().__init__()
        self.lessons: list[Lesson] = lessons if lessons is not None else all_lessons()
        if not self.lessons:
            raise RuntimeError("No exercises found in exercises/")
        self._runner: Callable[..., CheckResult] = runner or check
        if autotest_debounce is not None:
            self.AUTOTEST_DEBOUNCE = autotest_debounce
        self._open_initial = open_initial

        # Compatibility attributes for callers/tests inspecting App state directly
        self.selected: int = 0
        self.focus_area: str = "menu"
        self.latest: CheckResult | None = None
        self.last_mtime: int = 0
        self.last_edit_at: float = 0.0
        self._loaded_lesson_slug: str | None = None
        self._loaded_newline: str = "\n"
        self._clean_text: str = ""
        self._sidebar_user_override: bool | None = None

        # Concurrency &latest-version test tracking
        self._test_lock = threading.Lock()
        self._test_seq: int = 0
        self._pending_retest: bool = False
        self._lesson_list_indices: list[int] = []  # lesson_idx -> ListView row index
        self._row_to_lesson: dict[int, int] = {}  # ListView row index -> lesson_idx
        self._item_widgets: dict[str, LessonListItem] = {}

    @property
    def lesson(self) -> Lesson:
        return self.lessons[self.selected_index]

    @property
    def focus(self) -> str:
        """Backward-compatible focus state name ('menu', 'editor', 'results')."""
        return self.active_focus

    @focus.setter
    def focus(self, value: str) -> None:
        self.active_focus = value

    def compose(self) -> ComposeResult:
        yield Static("", id="top-header")
        with Horizontal(id="body-container"):
            with Vertical(id="sidebar"):
                yield Static("TRACKS / EXERCISES", id="sidebar-header")
                yield ListView(*self._build_sidebar_items(), id="lesson-list")
            with Vertical(id="workspace"):
                yield Static("", id="lesson-brief")
                yield Static("", id="editor-toolbar")
                yield Static("", id="hint-banner")
                editor = JavaCodeEditor(
                    "",
                    language="java",
                    theme="monokai",
                    tab_behavior="indent",
                    show_line_numbers=True,
                    soft_wrap=False,
                    highlight_cursor_line=True,
                    id="code-editor",
                )
                editor.register_theme(KOANFORGE_EDITOR_THEME)
                editor.theme = "koanforge"
                editor.indent_width = 4
                yield editor
                with Vertical(id="results-panel"):
                    yield Static("", id="results-header")
                    yield RichLog(
                        highlight=False,
                        markup=False,
                        wrap=True,
                        auto_scroll=False,
                        min_width=40,
                        id="results-log",
                    )
        yield Static("", id="status-footer")

    def _build_sidebar_items(self) -> list[ListItem]:
        marks = progress()
        items: list[ListItem] = []
        self._lesson_list_indices.clear()
        self._row_to_lesson.clear()
        self._item_widgets.clear()
        last_cat: str | None = None
        row_idx = 0
        for idx, lesson in enumerate(self.lessons):
            if lesson.category != last_cat:
                last_cat = lesson.category
                items.append(TrackHeaderItem(lesson.category))
                row_idx += 1
            solved = bool(marks.get(lesson.slug, {}).get("solved"))
            item = LessonListItem(idx, lesson, solved)
            items.append(item)
            self._lesson_list_indices.append(row_idx)
            self._row_to_lesson[row_idx] = idx
            self._item_widgets[lesson.slug] = item
            row_idx += 1
        return items

    def on_mount(self) -> None:
        self._apply_responsive_layout(self.size.width, self.size.height)
        self._preview_lesson(self.selected_index)
        list_view = self.query_one("#lesson-list", ListView)
        if self._lesson_list_indices:
            list_view.index = self._lesson_list_indices[self.selected_index]

        if self._open_initial:
            self.open_selected_lesson()
        else:
            list_view.focus()
            self.active_focus = "menu"

        self.set_interval(0.25, self._on_periodic_tick)
        self._refresh_all_panels()

    def on_resize(self, event: events.Resize) -> None:
        self._apply_responsive_layout(event.size.width, event.size.height)
        self._refresh_all_panels()

    def _apply_responsive_layout(self, width: int, height: int) -> None:
        if height < self.COMPACT_HEIGHT:
            self.screen.add_class("compact-height")
        else:
            self.screen.remove_class("compact-height")

        sidebar = self.query_one("#sidebar", Vertical)
        if self._sidebar_user_override is not None:
            should_collapse = self._sidebar_user_override
        else:
            # On narrow terminals (<94 cols), collapse the sidebar while editing
            # so the Java editor gets the full width, and show it when navigating.
            should_collapse = width < self.NARROW_WIDTH and self.active_focus == "editor"

        self.sidebar_collapsed = should_collapse
        if should_collapse:
            sidebar.add_class("collapsed")
        else:
            sidebar.remove_class("collapsed")

    # ------------------------------------------------------------------
    # Lesson lifecycle: preview, load/open, save, preserve, external sync
    # ------------------------------------------------------------------

    def _preview_lesson(self, index: int) -> None:
        """Load the selected lesson into the workspace preview without running javac."""
        index = max(0, min(len(self.lessons) - 1, index))
        self.selected_index = index
        self.selected = index
        lesson = self.lessons[index]
        file_path = prepare(lesson)
        raw = read_solution(lesson)
        self._loaded_newline = "\r\n" if "\r\n" in raw else "\n"
        normalized = raw.replace("\r\n", "\n")
        try:
            self.last_mtime = file_path.stat().st_mtime_ns
        except OSError:
            self.last_mtime = 0
        self._loaded_lesson_slug = lesson.slug
        self._clean_text = self.query_one("#code-editor", JavaCodeEditor).text
        self.is_dirty = False
        self.external_conflict = False
        self.hint_step = 0

        editor = self.query_one("#code-editor", JavaCodeEditor)
        self._clean_text = normalized
        editor.load_text(normalized)
        editor.move_cursor((0, 0))

        # Show cached status from progress if available before a live test run
        marks = progress().get(lesson.slug, {})
        if marks.get("last_status"):
            status = marks["last_status"]
            passed = int(marks.get("last_passed", 0))
            failed = int(marks.get("last_failed", 0))
            summary = (
                "All assertions passed previously. Press Enter to edit or Ctrl+S to re-verify."
                if status == "passed"
                else "Press Enter to edit Solution.java or Ctrl+S to compile and run tests."
            )
            self.latest = CheckResult(status, [summary], passed=passed, failed=failed, elapsed=0.0)
        else:
            self.latest = None

        self._refresh_all_panels()

    def open_selected_lesson(self, run_check: bool = True) -> None:
        """Open the selected lesson in the editor and trigger a background check."""
        lesson = self.lesson
        if self._loaded_lesson_slug != lesson.slug:
            self._preview_lesson(self.selected_index)

        self.active_focus = "editor"
        self.focus_area = "editor"
        self._apply_responsive_layout(self.size.width, self.size.height)

        editor = self.query_one("#code-editor", JavaCodeEditor)
        editor.focus()
        self.status_message = (
            f"Editing {lesson.slug} · Ctrl+S save & test · Ctrl+T hint · Esc navigator"
        )
        self._refresh_all_panels()
        if run_check:
            self.trigger_check()

    def _current_editor_text(self) -> str:
        editor = self.query_one("#code-editor", JavaCodeEditor)
        text = editor.text
        if not text.endswith("\n"):
            text += "\n"
        if self._loaded_newline == "\r\n":
            return text.replace("\n", "\r\n")
        return text

    def save_current(self, run_check: bool = True, force_write: bool = False) -> bool:
        """Save editor buffer to workspace/<slug>/Solution.java."""
        lesson = self.lesson
        if self._loaded_lesson_slug != lesson.slug:
            return False
        f = solution_file(lesson)
        if self.is_dirty or force_write or self.external_conflict:
            editor = self.query_one("#code-editor", JavaCodeEditor)
            content = self._current_editor_text()
            write_solution(lesson, content)
            try:
                self.last_mtime = f.stat().st_mtime_ns
            except OSError:
                pass
            self._clean_text = editor.text
            self.is_dirty = False
            self.external_conflict = False
            self.status_message = f"Saved workspace/{lesson.slug}/Solution.java."
        if run_check:
            self.trigger_check()
        self._refresh_all_panels()
        return True

    def preserve_on_leave(self) -> None:
        """Never lose user edits when switching exercises, returning to menu, or quitting."""
        if not self.is_dirty or self._loaded_lesson_slug is None:
            return
        lesson = next((l for l in self.lessons if l.slug == self._loaded_lesson_slug), self.lesson)
        content = self._current_editor_text()
        if self.external_conflict:
            recovery = solution_file(lesson).with_name("Solution.recovery.java")
            write_text_atomic(recovery, content)
            self.status_message = (
                f"External conflict detected; saved in-memory draft to {recovery.name}."
            )
        else:
            write_solution(lesson, content)
            try:
                self.last_mtime = solution_file(lesson).stat().st_mtime_ns
            except OSError:
                pass
            self.status_message = f"Auto-saved changes to {lesson.slug}/Solution.java."
        self._clean_text = self.query_one("#code-editor", JavaCodeEditor).text
        self.is_dirty = False
        self.external_conflict = False

    def check_external_changes(self) -> bool:
        """Detect external modifications to Solution.java without clobbering dirty edits."""
        if self._loaded_lesson_slug is None:
            return False
        lesson = self.lesson
        if lesson.slug != self._loaded_lesson_slug:
            return False
        f = solution_file(lesson)
        try:
            mtime = f.stat().st_mtime_ns
        except FileNotFoundError:
            return False
        if self.last_mtime and mtime != self.last_mtime:
            self.last_mtime = mtime
            if self.is_dirty:
                self.external_conflict = True
                self.status_message = (
                    "External file change detected while buffer has unsaved edits! "
                    "Press Ctrl+S to overwrite disk, or leave to save Solution.recovery.java."
                )
                self._refresh_all_panels()
                return True

            raw = read_solution(lesson)
            self._loaded_newline = "\r\n" if "\r\n" in raw else "\n"
            normalized = raw.replace("\r\n", "\n")
            editor = self.query_one("#code-editor", JavaCodeEditor)
            cursor = editor.cursor_location
            self._clean_text = normalized
            editor.load_text(normalized)
            max_row = max(0, editor.document.line_count - 1)
            row = min(cursor[0], max_row)
            col = min(cursor[1], len(editor.document.get_line(row)))
            editor.move_cursor((row, col))
            self.external_conflict = False
            self.status_message = "Watcher: external file change loaded; running tests..."
            self._refresh_all_panels()
            self.trigger_check()
            return True
        return False

    # ------------------------------------------------------------------
    # Background compilation & test runner (non-overlapping, latest-wins)
    # ------------------------------------------------------------------

    def trigger_check(self) -> None:
        """Run javac + KoanTest on a background thread without blocking input or focus."""
        lesson = self.lesson
        source = self._current_editor_text()
        expected_hash = source_hash(source)

        with self._test_lock:
            self._test_seq += 1
            seq = self._test_seq
            if self.is_testing:
                self._pending_retest = True
                return
            self.is_testing = True
            self._pending_retest = False

        self.status_message = f"Compiling & testing {lesson.slug}..."
        self._refresh_header_and_toolbar()
        self._refresh_results_header()

        def worker() -> None:
            result = self._runner(lesson, source=source)
            try:
                self.call_from_thread(self._on_check_completed, lesson.slug, seq, expected_hash, result)
            except RuntimeError:
                # App already shut down
                pass

        threading.Thread(target=worker, name=f"koanforge-check-{seq}", daemon=True).start()

    def _on_check_completed(
        self, slug: str, seq: int, tested_hash: str, result: CheckResult
    ) -> None:
        with self._test_lock:
            retest = self._pending_retest
            self._pending_retest = False
            self.is_testing = False

        # Update sidebar badge immediately if solved
        marks = progress()
        solved = bool(marks.get(slug, {}).get("solved")) or result.status == "passed"
        if slug in self._item_widgets:
            self._item_widgets[slug].set_solved(solved)

        # Only apply to the active results view if the user is still on the same lesson
        if self.lesson.slug == slug:
            current_hash = source_hash(self._current_editor_text())
            if current_hash != tested_hash and retest:
                # Source changed while javac was running; launch a fresh test for latest source
                self.latest = result
                self._refresh_all_panels()
                self.trigger_check()
                return

            self.latest = result
            if result.status == "passed":
                self.status_message = (
                    f"PASS · All {result.passed} assertions passed in {result.elapsed:.2f}s! Progress saved."
                )
            elif result.status == "compile-error":
                self.status_message = (
                    f"COMPILE ERROR · {len(result.diagnostics) or 1} compiler diagnostic(s). Check Test Results below."
                )
            elif result.status == "failed":
                self.status_message = (
                    f"FAIL · {result.passed} passed, {result.failed} failed ({result.elapsed:.2f}s)."
                )
            else:
                self.status_message = f"{result.status.upper()} · See Test Results panel below."
            self._refresh_all_panels()
        elif retest:
            self.trigger_check()

    def _on_periodic_tick(self) -> None:
        self.check_external_changes()
        if (
            self.autotest
            and self.is_dirty
            and not self.external_conflict
            and not self.is_testing
            and self.last_edit_at > 0.0
            and (time.monotonic() - self.last_edit_at) >= self.AUTOTEST_DEBOUNCE
        ):
            self.save_current(run_check=True)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        current = event.text_area.text
        if current == self._clean_text:
            self.is_dirty = False
            self._refresh_header_and_toolbar()
            return
        self.is_dirty = True
        self.last_edit_at = time.monotonic()
        self._refresh_header_and_toolbar()

    def on_java_code_editor_cursor_moved(self, event: JavaCodeEditor.CursorMoved) -> None:
        self._refresh_header_and_toolbar()

    def on_java_code_editor_escape_pressed(self, event: JavaCodeEditor.EscapePressed) -> None:
        self.action_focus_navigator()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item is None:
            return
        if isinstance(event.item, LessonListItem):
            new_idx = event.item.lesson_index
            if new_idx != self.selected_index:
                self.preserve_on_leave()
                self._preview_lesson(new_idx)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, LessonListItem):
            if event.item.lesson_index != self.selected_index:
                self.preserve_on_leave()
                self._preview_lesson(event.item.lesson_index)
            self.open_selected_lesson(run_check=True)

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        widget_id = event.widget.id or ""
        if widget_id == "code-editor":
            self.active_focus = "editor"
            self.focus_area = "editor"
        elif widget_id == "results-log":
            self.active_focus = "results"
            self.focus_area = "results"
        elif widget_id == "lesson-list":
            self.active_focus = "menu"
            self.focus_area = "menu"
        self._apply_responsive_layout(self.size.width, self.size.height)
        self._refresh_header_and_toolbar()
        self._refresh_footer()

    def on_key(self, event: events.Key) -> None:
        if self.active_focus == "menu":
            if event.key == "j":
                event.stop()
                self.query_one("#lesson-list", ListView).action_cursor_down()
            elif event.key == "k":
                event.stop()
                self.query_one("#lesson-list", ListView).action_cursor_up()
        elif self.active_focus == "results" and event.key == "escape":
            event.stop()
            self.action_focus_navigator()

    # ------------------------------------------------------------------
    # Actions & keyboard shortcuts
    # ------------------------------------------------------------------

    def action_focus_navigator(self) -> None:
        """Return from editor or output to the Exercise Navigator sidebar."""
        self.preserve_on_leave()
        self.active_focus = "menu"
        self.focus_area = "menu"
        if self._sidebar_user_override is True:
            self._sidebar_user_override = None
        self._apply_responsive_layout(self.size.width, self.size.height)
        list_view = self.query_one("#lesson-list", ListView)
        if self._lesson_list_indices:
            list_view.index = self._lesson_list_indices[self.selected_index]
        list_view.focus()
        self.status_message = "Exercise Navigator · ↑/↓ select · Enter edit · Ctrl+S test · ? help"
        self._refresh_all_panels()

    def action_save_and_test(self) -> None:
        self.save_current(run_check=True, force_write=True)

    def action_cycle_hint(self) -> None:
        hints = self.lesson.hints
        if not hints:
            self.status_message = "No hints available for this exercise."
            self._refresh_all_panels()
            return
        self.hint_step = (self.hint_step + 1) % (len(hints) + 1)
        if self.hint_step == 0:
            self.status_message = "Hints hidden."
        else:
            self.status_message = f"Showing hint {self.hint_step}/{len(hints)}."
        self._refresh_all_panels()

    def action_next_lesson(self) -> None:
        self.preserve_on_leave()
        next_idx = (self.selected_index + 1) % len(self.lessons)
        self._preview_lesson(next_idx)
        list_view = self.query_one("#lesson-list", ListView)
        if self._lesson_list_indices:
            list_view.index = self._lesson_list_indices[next_idx]
        self.open_selected_lesson(run_check=True)

    def action_toggle_autotest(self) -> None:
        self.autotest = not self.autotest
        state = "ON" if self.autotest else "OFF"
        self.status_message = f"Auto-test on edit ({self.AUTOTEST_DEBOUNCE:.1f}s debounce): {state}"
        self._refresh_all_panels()

    def action_focus_results(self) -> None:
        if self.active_focus == "results":
            self.query_one("#code-editor", JavaCodeEditor).focus()
            self.status_message = "Returned focus to Java editor."
        else:
            self.query_one("#results-log", RichLog).focus()
            self.status_message = "Test Results focused · ↑/↓/PgUp/PgDn scroll · F3 expand · Esc navigator"
        self._refresh_all_panels()

    def action_toggle_expand_results(self) -> None:
        self.results_expanded = not self.results_expanded
        panel = self.query_one("#results-panel", Vertical)
        if self.results_expanded:
            panel.add_class("expanded")
            self.query_one("#results-log", RichLog).focus()
            self.status_message = "Expanded Test Results panel (press F3 to restore)."
        else:
            panel.remove_class("expanded")
            self.status_message = "Restored Test Results panel height."
        self._refresh_all_panels()

    def action_toggle_sidebar(self) -> None:
        current = self.sidebar_collapsed
        self._sidebar_user_override = not current
        self._apply_responsive_layout(self.size.width, self.size.height)
        state = "hidden" if self.sidebar_collapsed else "visible"
        self.status_message = f"Exercise Navigator sidebar {state} (Ctrl+B to toggle)."
        self._refresh_all_panels()

    def action_external_editor(self) -> None:
        self.preserve_on_leave()
        f = prepare(self.lesson)
        program = os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "vi")
        args = shlex.split(program, posix=os.name != "nt") + [str(f)]
        try:
            with self.suspend():
                subprocess.call(args)
        except Exception:
            # If suspend is unavailable (e.g. headless test or GUI editor like Notepad), launch non-blocking
            try:
                subprocess.Popen(args)
                self.status_message = f"Launched external editor: {program}"
                self._refresh_all_panels()
                return
            except OSError as e:
                self.status_message = f"Could not launch editor: {e}"
                self._refresh_all_panels()
                return
        self.last_mtime = 0  # Force reload on return
        self.check_external_changes()

    def action_show_help(self) -> None:
        if isinstance(self.screen, HelpModal):
            self.screen.dismiss(None)
        else:
            self.push_screen(HelpModal())

    def action_quit_app(self) -> None:
        self.preserve_on_leave()
        self.exit(0)

    # ------------------------------------------------------------------
    # Rendering helpers for custom Static / RichLog panels
    # ------------------------------------------------------------------

    def _refresh_all_panels(self) -> None:
        if not self.is_mounted:
            return
        self._refresh_header_and_toolbar()
        self._refresh_lesson_brief()
        self._refresh_hint_banner()
        self._refresh_results_header()
        self._refresh_results_log()
        self._refresh_footer()

    def _refresh_header_and_toolbar(self) -> None:
        if not self.is_mounted:
            return
        marks = progress()
        total = len(self.lessons)
        solved_count = sum(1 for l in self.lessons if marks.get(l.slug, {}).get("solved"))
        lesson = self.lesson
        is_solved = bool(marks.get(lesson.slug, {}).get("solved"))

        # Top header bar (1 or 2 lines depending on terminal height)
        bar_width = 12 if self.size.width >= 96 else 8
        filled = int(round((solved_count / max(1, total)) * bar_width))
        pbar = "█" * filled + "░" * (bar_width - filled)

        line1 = Text(no_wrap=True, overflow="ellipsis")
        line1.append("◆ KOANFORGE ", style="bold #60e2df")
        if self.size.width >= 88:
            line1.append("JAVA // TERMINAL DOJO  ", style="bold #c89bff")
        line1.append(f"[{lesson.category}] ", style="bold #ffc66d")
        line1.append(f"#{self.selected_index + 1:02d}/{total:02d} ", style="bold #e8effc")
        line1.append(
            "● SOLVED  " if is_solved else "◇ PRACTICE  ",
            style="bold #85efa5" if is_solved else "#7f93ae",
        )
        line1.append(f"{pbar} {solved_count}/{total} solved", style="bold #85efa5")

        if self.size.height < self.COMPACT_HEIGHT:
            self.query_one("#top-header", Static).update(line1)
        else:
            line2 = Text(no_wrap=True, overflow="ellipsis")
            status_style = (
                "bold #ff727e"
                if self.external_conflict
                else "bold #85efa5"
                if self.status_message.startswith("PASS")
                else "#9fb3ce"
            )
            line2.append(self.status_message, style=status_style)
            self.query_one("#top-header", Static).update(Group(line1, line2))

        # Editor toolbar
        editor = self.query_one("#code-editor", JavaCodeEditor)
        row, col = editor.cursor_location
        avail_w = self.size.width if self.sidebar_collapsed else max(40, self.size.width - 30)
        if avail_w >= 86:
            rel_path = f"workspace/{lesson.slug}/Solution.java"
        elif avail_w >= 76:
            rel_path = f"{lesson.slug}/Solution.java"
        else:
            rel_path = "Solution.java"
        tb = Text(no_wrap=True, overflow="ellipsis")
        tb.append(" CODE ", style="bold #0e121e on #60e2df")
        tb.append(" ")
        if self.external_conflict:
            tb.append("⚠ CONFLICT ", style="bold #ff727e")
        elif self.is_dirty:
            tb.append("● unsaved ", style="bold #ffc66d")
        else:
            tb.append("● saved ", style="bold #85efa5")
        tb.append("· ", style="#6e82a0")
        tb.append(
            f"AUTO {'ON' if self.autotest else 'OFF'} ",
            style="bold #60e2df" if self.autotest else "#7f93ae",
        )
        tb.append("· ", style="#6e82a0")
        tb.append(f"Ln {row + 1}, Col {col + 1} ", style="#c89bff")
        tb.append("· ", style="#6e82a0")
        tb.append(rel_path, style="#9fb3ce")
        self.query_one("#editor-toolbar", Static).update(tb)

    def _refresh_lesson_brief(self) -> None:
        lesson = self.lesson
        compact = self.size.height < self.COMPACT_HEIGHT
        lines: list[Text] = []

        title_line = Text(overflow="fold")
        title_line.append(lesson.title, style="bold #e8effc")
        title_line.append(f"  [Level {lesson.level}]", style="#c89bff")
        title_line.append("  —  ", style="#6e82a0")
        title_line.append(lesson.objective, style="bold #60e2df")
        lines.append(title_line)

        if not compact:
            for item in lesson.instructions:
                inst = Text(overflow="fold")
                inst.append("  • ", style="bold #60e2df")
                inst.append(item, style="#b8c7de")
                lines.append(inst)
        elif lesson.instructions:
            inst = Text(overflow="fold")
            inst.append("  • ", style="bold #60e2df")
            inst.append("  |  ".join(lesson.instructions), style="#b8c7de")
            lines.append(inst)

        self.query_one("#lesson-brief", Static).update(Group(*lines))

    def _refresh_hint_banner(self) -> None:
        banner = self.query_one("#hint-banner", Static)
        hints = self.lesson.hints
        if self.hint_step <= 0 or not hints:
            banner.remove_class("visible")
            banner.update("")
            return
        idx = min(self.hint_step, len(hints)) - 1
        t = Text( overflow="fold")
        t.append(f"💡 HINT {idx + 1}/{len(hints)}: ", style="bold #ffc66d")
        t.append(hints[idx], style="#ffe3b3")
        t.append("  (Ctrl+T for next)", style="italic #9fb3ce")
        banner.update(t)
        banner.add_class("visible")

    def _refresh_results_header(self) -> None:
        hdr = Text(no_wrap=True, overflow="ellipsis")
        hdr.append("TEST RESULTS ", style="bold #c89bff")

        if self.is_testing:
            hdr.append(" ⟳ RUNNING JAVAC & TESTS... ", style="bold #0e121e on #ffc66d")
        elif self.latest is None:
            hdr.append(" ◇ NOT RUN ", style="bold #7f93ae")
            hdr.append("  Press Ctrl+S to compile and run assertions.", style="#7f93ae")
        else:
            res = self.latest
            status_map = {
                "passed": (" ✓ PASS ", "bold #0e121e on #85efa5"),
                "failed": (" ✗ FAIL ", "bold #0e121e on #ff727e"),
                "compile-error": (" ⚙ COMPILE ERROR ", "bold #0e121e on #ff727e"),
                "runtime-error": (" ⚠ RUNTIME ERROR ", "bold #0e121e on #ffc66d"),
                "timeout": (" ⏱ TIMEOUT ", "bold #0e121e on #ffc66d"),
                "missing-jdk": (" ⚠ MISSING JDK ", "bold #0e121e on #ff727e"),
            }
            badge_text, badge_style = status_map.get(
                res.status, (f" {res.status.upper()} ", "bold #e8effc")
            )
            hdr.append(badge_text, style=badge_style)
            hdr.append(
                f"  {res.passed} passed · {res.failed} failed · {res.elapsed:.2f}s",
                style="bold #85efa5" if res.status == "passed" else "#e8effc",
            )
            if self.results_expanded:
                hdr.append("  [EXPANDED - F3]", style="bold #60e2df")

        self.query_one("#results-header", Static).update(hdr)

    def _refresh_results_log(self) -> None:
        log = self.query_one("#results-log", RichLog)
        log.clear()

        if self.latest is None:
            log.write(
                Text(
                    "Open an exercise with Enter or press Ctrl+S to compile Solution.java and run KoanTest.",
                    style="#7f93ae",
                )
            )
            return

        res = self.latest

        if res.status == "compile-error":
            if res.diagnostics:
                for d in res.diagnostics:
                    fname = Path(d.file).name
                    loc = f"{fname}:{d.line}" + (f":{d.column}" if d.column else "")
                    line = Text()
                    line.append("✗ ", style="bold #ff727e")
                    line.append(f"[{loc}] ", style="bold #ffc66d")
                    line.append(f"{d.kind}: ", style="bold #ff727e")
                    line.append(d.message, style="#e8effc")
                    log.write(line)
                log.write(Text("─" * 48, style="#24324d"))
            for raw_line in res.details:
                style = "#ff727e" if "error:" in raw_line else "#9fb3ce"
                log.write(Text(raw_line, style=style))
            return

        if res.assertions:
            for a in res.assertions:
                row = Text()
                if a.passed:
                    row.append("✓ PASS  ", style="bold #85efa5")
                    row.append(a.name, style="#d6f5e0")
                    log.write(row)
                else:
                    row.append("✗ FAIL  ", style="bold #ff727e")
                    row.append(a.name, style="bold #ffd6da")
                    if a.expected is not None and a.actual is not None:
                        row.append("  →  expected ", style="#9fb3ce")
                        row.append(repr(a.expected), style="bold #85efa5")
                        row.append(", got ", style="#9fb3ce")
                        row.append(repr(a.actual), style="bold #ff727e")
                    elif a.message:
                        row.append(f"  —  {a.message}", style="#ffc66d")
                    log.write(row)

            if res.output:
                log.write(Text("── Program Output / Stack Trace ──", style="bold #c89bff"))
                for extra in res.output:
                    log.write(Text(extra, style="#ffc66d"))
            return

        for line in res.details:
            style = (
                "bold #85efa5"
                if line.startswith("✓")
                else "bold #ff727e"
                if line.startswith("✗") or "Exception" in line or "Error" in line
                else "#9fb3ce"
            )
            log.write(Text(line, style=style))

    def _refresh_footer(self) -> None:
        w = self.size.width
        f = Text(no_wrap=True, overflow="ellipsis")

        if w < 112:
            # Compact contextual shortcuts on 80-col and 100-col terminals so nothing overflows
            if self.active_focus == "menu":
                pairs = [
                    ("↑↓", "select"),
                    ("Enter", "edit"),
                    ("^S", "test"),
                    ("^N", "next"),
                    ("^B", "panel"),
                    ("?", "help"),
                    ("^Q", "quit"),
                ]
            else:
                pairs = [
                    ("Esc", "list"),
                    ("^S", "test"),
                    ("^T", "hint"),
                    ("^N", "next"),
                    ("^A", "auto"),
                    ("^L", "logs"),
                    ("?", "help"),
                    ("^Q", "quit"),
                ]
        elif w < 136:
            pairs = [
                ("↑↓", "nav"),
                ("Enter", "edit"),
                ("Esc", "list"),
                ("^S", "save/test"),
                ("^T", "hint"),
                ("^N", "next"),
                ("^A", "auto"),
                ("^L", "output"),
                ("?", "help"),
                ("^Q", "quit"),
            ]
        else:
            pairs = [
                ("↑↓", "navigate"),
                ("Enter", "edit"),
                ("Esc", "list"),
                ("Ctrl+S", "save/test"),
                ("Ctrl+T", "hint"),
                ("Ctrl+N", "next"),
                ("Ctrl+A", "auto"),
                ("Ctrl+L", "output"),
                ("Ctrl+B", "sidebar"),
                ("?", "help"),
                ("Ctrl+Q", "quit"),
            ]

        for i, (key, label) in enumerate(pairs):
            if i > 0:
                f.append(" · ", style="#6e82a0")
            f.append(key, style="bold #60e2df")
            f.append(f" {label}", style="#e8effc")

        self.query_one("#status-footer", Static).update(f)


class App(KoanForgeApp):
    """Entry-point TUI class kept as `engine.tui.App` for CLI compatibility."""

    def run(self, *args, **kwargs) -> int:  # type: ignore[override]
        # Preserve non-interactive terminal guard when invoked without headless test runner
        if not kwargs.get("headless", False) and (
            not sys.stdin.isatty() or not sys.stdout.isatty()
        ):
            print("TUI requires an interactive terminal. Try: python koan.py list")
            return 2
        res = super().run(*args, **kwargs)
        return 0 if res is None else int(res)
