# ◆ KOANFORGE // JAVA

**A terminal-first Java Koans dojo: write Java directly in your terminal, run automatic tests, track progress, and master core Java concepts.**

Designed to build fluency in the areas that matter most when implementing data structures like `MyHashMap` from scratch: core syntax, `return`/`break`, variable scope, constructors, reference aliasing, linked-list traversal, node removal, safe hash indexing, rehashing on resize, generics, and fail-fast exceptions.

---

## Requirements

- **JDK 17+**: `java` and `javac` must be available on your `PATH`.
- **Python 3.10+**.
- **Textual (`textual[syntax]>=8.0.0`)** for the full-screen terminal UI and tree-sitter Java syntax highlighting.
- Windows Terminal / PowerShell 7+, VS Code integrated terminal, macOS Terminal, iTerm2, or any modern UTF-8 terminal.

---

## Quick Start

### Windows (PowerShell / Windows Terminal)

```powershell
cd koanforge-java
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python koan.py doctor
.\.venv\Scripts\python koan.py
```

Or simply run `.\start.bat` (which uses `.venv` automatically if present, or installs `requirements.txt` if needed).

### macOS / Linux

```bash
cd koanforge-java
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python koan.py doctor
./.venv/bin/python koan.py
```

Or run `bash start.sh`.

---

## Terminal UI & Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `↑` / `↓` (`j` / `k` in sidebar) | Navigate exercises in the sidebar or move cursor in the editor |
| `Enter` | Open selected exercise from the sidebar; insert newline (with auto-indent) in editor |
| `Esc` | Return focus from the editor or test output back to the Exercise Navigator |
| `Ctrl+S` / `Ctrl+R` | **Save `Solution.java` + run `javac` + run `KoanTest` immediately** |
| `Ctrl+T` / `F2` | Cycle progressive hints for the current exercise |
| `Ctrl+A` | Toggle debounced Auto-test on edit (ON by default, 1.5s after typing stops) |
| `Ctrl+N` | Save changes and advance to the next exercise |
| `Ctrl+L` | Focus Test Results panel to scroll through long output |
| `F3` | Expand / restore the Test Results panel height |
| `Ctrl+B` / `F4` | Show / hide the Exercise Navigator sidebar |
| `Ctrl+O` | Open `Solution.java` in `$EDITOR` / Notepad |
| `Ctrl+Z` / `Ctrl+Y` | Undo / Redo in the Java code editor |
| `?` / `F1` | Open or close the Keyboard Shortcuts & Help modal |
| `Ctrl+Q` | Save any pending edits and quit |

### Workspace & External Editor Sync

- Solutions are stored in `workspace/<slug>/Solution.java` and progress in `workspace/.progress.json`.
- You can edit code either inside the built-in Java editor or in an external IDE (IntelliJ IDEA, VS Code, etc.).
- When `Solution.java` is modified externally, KoanForge detects the change and automatically re-runs the tests.
- If you have unsaved in-memory edits when an external change happens, KoanForge alerts you and preserves your draft in `Solution.recovery.java` if you leave the lesson, ensuring work is never silently overwritten.

---

## CLI Commands

```bash
python koan.py tui                        # Launch interactive TUI (default)
python koan.py list                       # List all exercises and completion status
python koan.py doctor                     # Check Python, java, javac, Textual, and workspace
python koan.py run 01-equals-or-assign    # Compile and test a single exercise
python koan.py watch 11-traverse-node     # Watch file changes and re-run tests in console
python koan.py new 19-my-exercise         # Scaffold a new custom exercise
python koan.py reset 01-equals-or-assign --yes  # Reset ONE exercise solution & progress
```

---

## Curriculum Overview

| Track | Exercises | Focus |
|---|---:|---|
| `SYNTAX` | 01–10 | Assignment vs. comparison, branching, loops, scope, `this`, reference aliasing, array indexing, `equals()` |
| `FLOW` | 11–15 | Singly linked list traversal, update-or-insert (`put`), head removal, middle node removal, non-negative hash index |
| `STRUCTURES` | 16–18 | Rehashing chains on resize, generic `Box<T>`, fail-fast validation with exceptions |

---

## Running Automated Tests

```powershell
.\.venv\Scripts\python -m pytest -v
# or via stdlib unittest:
.\.venv\Scripts\python -m unittest discover -s tests -v
```
