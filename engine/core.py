"""KoanForge engine: lessons, workspace files, javac/java runner, progress.

This module is deliberately UI-agnostic: the CLI (koan.py) and the Textual TUI
(engine/tui.py) both build on it, and it has no third-party dependencies.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXERCISES = ROOT / "exercises"
WORKSPACE = ROOT / "workspace"
STATE = WORKSPACE / ".progress.json"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

#: Seconds allowed for javac. A cold JVM on Windows can need several seconds.
COMPILE_TIMEOUT = 30.0
#: Seconds allowed for running the tests (guards against infinite loops).
RUN_TIMEOUT = 9.0

# Force UTF-8 on every JVM stream. Without this, on Windows a *piped* JVM
# writes System.out in the ANSI code page (e.g. cp1252), which garbles the
# Vietnamese assertion names and javac's source-line echo.
_JVM_UTF8 = ['-Dfile.encoding=UTF-8', '-Dstdout.encoding=UTF-8', '-Dstderr.encoding=UTF-8',
             '-Dsun.stdout.encoding=UTF-8', '-Dsun.stderr.encoding=UTF-8',
             # English javac diagnostics regardless of OS locale (parseable, consistent UI).
             '-Duser.language=en', '-Duser.country=US']

_progress_lock = threading.Lock()
_DIAG = re.compile(r'^(?P<file>.*?\.java):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<kind>error|warning):\s*(?P<msg>.*)$')
_EXPECTED = re.compile(r'^Expected:\s?(?P<expected>.*), got:\s?(?P<actual>.*)$')


@dataclass
class Lesson:
    slug: str
    title: str
    category: str
    objective: str
    instructions: list[str]
    hints: list[str]
    path: Path
    level: int = 1

    @property
    def short_title(self) -> str:
        """Title without the leading ``"01 · "`` number prefix."""
        return self.title.split('·', 1)[-1].strip() if '·' in self.title else self.title


@dataclass
class Assertion:
    """One KoanChecks assertion parsed from the test program output."""
    name: str
    passed: bool
    message: str = ''
    expected: str | None = None
    actual: str | None = None


@dataclass
class Diagnostic:
    """One javac diagnostic with a file/line reference."""
    file: str
    line: int
    column: int | None
    kind: str
    message: str


@dataclass
class CheckResult:
    status: str
    details: list[str]
    passed: int = 0
    failed: int = 0
    elapsed: float = 0
    assertions: list[Assertion] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    #: Non-assertion program output (System.out prints, stack traces, stderr).
    output: list[str] = field(default_factory=list)
    #: SHA-1 of the exact source text that was compiled (if known).
    source_hash: str | None = None


def source_hash(text: str) -> str:
    return hashlib.sha1(text.encode('utf-8')).hexdigest()


def all_lessons() -> list[Lesson]:
    result = []
    for folder in sorted(EXERCISES.iterdir()):
        if not folder.is_dir() or not SLUG.fullmatch(folder.name):
            continue
        mf = folder / 'lesson.json'
        if not mf.exists():
            continue
        data = json.loads(mf.read_text(encoding='utf-8'))
        if not (folder / 'Starter.java').exists() or not (folder / 'KoanTest.java').exists():
            raise ValueError(f'Missing Starter.java or KoanTest.java in {folder}')
        result.append(Lesson(folder.name, data['title'], data['category'], data['objective'],
                             data['instructions'], data.get('hints', []), folder, data.get('level', 1)))
    return result


def solution_file(lesson: Lesson) -> Path:
    return WORKSPACE / lesson.slug / 'Solution.java'


def prepare(lesson: Lesson) -> Path:
    """Create the workspace solution from the starter if (and only if) missing."""
    f = solution_file(lesson)
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text((lesson.path / 'Starter.java').read_text(encoding='utf-8'), encoding='utf-8')
    return f


def read_solution(lesson: Lesson) -> str:
    """Read the workspace solution exactly (newline style preserved)."""
    with open(prepare(lesson), encoding='utf-8', newline='') as fh:
        return fh.read()


def write_text_atomic(path: Path, text: str) -> None:
    """Write via temp file + rename so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as fh:
            fh.write(text)
        for attempt in range(20):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:  # Windows: file briefly locked by a reader / AV scanner
                if attempt == 19:
                    raise
                time.sleep(0.05)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_solution(lesson: Lesson, text: str) -> Path:
    f = solution_file(lesson)
    write_text_atomic(f, text)
    return f


def progress() -> dict:
    if not STATE.exists():
        return {}
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_progress(slug: str, result: CheckResult):
    with _progress_lock:
        p = progress()
        e = p.setdefault(slug, {})
        e['attempts'] = e.get('attempts', 0) + 1
        e['last_status'] = result.status
        e['last_passed'] = result.passed
        e['last_failed'] = result.failed
        e['last_tested'] = int(time.time())
        if result.status == 'passed':
            e['solved'] = True
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        write_text_atomic(STATE, json.dumps(p, indent=2, ensure_ascii=False))


def parse_diagnostics(lines: list[str]) -> list[Diagnostic]:
    out = []
    for line in lines:
        m = _DIAG.match(line.strip())
        if m:
            out.append(Diagnostic(m['file'], int(m['line']), int(m['col']) if m['col'] else None,
                                  'warning' if m['kind'] == 'warning' else 'error', m['msg']))
    return out


def parse_assertion(line: str) -> Assertion | None:
    if line.startswith('PASS\t'):
        return Assertion(line.split('\t', 1)[1], True)
    if line.startswith('FAIL\t'):
        parts = line.split('\t', 2)
        msg = parts[2] if len(parts) > 2 else ''
        m = _EXPECTED.match(msg)
        return Assertion(parts[1], False, msg, m['expected'] if m else None, m['actual'] if m else None)
    return None


def check(lesson: Lesson, timeout: float | None = None, record: bool = True,
          source: str | None = None) -> CheckResult:
    """Compile and run the lesson tests.

    ``source`` -- if given, that exact text is compiled (from a private
    snapshot) instead of the workspace file, so a result always corresponds
    to a known source version even if the file changes during compilation.
    ``timeout`` overrides both compile and run time limits (legacy argument).
    """
    file = prepare(lesson)
    if source is None:
        source = read_solution(lesson)
    digest = source_hash(source)
    compile_timeout = timeout or COMPILE_TIMEOUT
    run_timeout = timeout or RUN_TIMEOUT
    start = time.monotonic()
    phase = 'compile'
    try:
        with tempfile.TemporaryDirectory(prefix='koanforge_') as td:
            src_dir = Path(td) / 'src'
            out_dir = Path(td) / 'classes'
            src_dir.mkdir()
            out_dir.mkdir()
            snapshot = src_dir / 'Solution.java'
            snapshot.write_text(source, encoding='utf-8', newline='')
            cmd = ['javac', *('-J' + o for o in _JVM_UTF8), '-encoding', 'UTF-8', '-Xlint:none',
                   '-d', str(out_dir), str(ROOT / 'engine' / 'KoanChecks.java'),
                   str(snapshot), str(lesson.path / 'KoanTest.java')]
            c = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                               errors='replace', timeout=compile_timeout, cwd=ROOT,
                               creationflags=_NO_WINDOW)
            if c.returncode != 0:
                raw = (c.stderr or c.stdout).replace(str(snapshot), str(file)).strip().splitlines()
                out = CheckResult('compile-error', raw or ['Compilation failed'],
                                  elapsed=time.monotonic() - start, diagnostics=parse_diagnostics(raw))
            else:
                phase = 'run'
                # Java is executed locally as the current user, not a security sandbox.
                r = subprocess.run(['java', *_JVM_UTF8, '-cp', str(out_dir), 'KoanTest'],
                                   capture_output=True, text=True, encoding='utf-8', errors='replace',
                                   timeout=run_timeout, cwd=ROOT, creationflags=_NO_WINDOW)
                details: list[str] = []
                assertions: list[Assertion] = []
                output: list[str] = []
                passed = failed = 0
                has_result = False
                for line in r.stdout.splitlines():
                    a = parse_assertion(line)
                    if a is not None:
                        assertions.append(a)
                        details.append(('✓  ' if a.passed else '✗  ') + a.name + ('' if a.passed or not a.message else ' — ' + a.message))
                    elif line.startswith('RESULT\t'):
                        fields = line.split('\t')
                        if len(fields) >= 3:
                            passed, failed = int(fields[1]), int(fields[2])
                            has_result = True
                    elif line.strip():
                        details.append(line)
                        output.append(line)
                if r.stderr.strip():
                    details += r.stderr.strip().splitlines()
                    output += r.stderr.strip().splitlines()
                if has_result and failed == 0 and r.returncode == 0 and passed > 0:
                    status = 'passed'
                elif has_result:
                    status = 'failed'
                else:
                    status = 'runtime-error'
                    passed = sum(a.passed for a in assertions)
                    failed = sum(not a.passed for a in assertions)
                    details.append(f'Program exited with code {r.returncode}')
                    output.append(f'Program exited with code {r.returncode}')
                out = CheckResult(status, details, passed, failed, time.monotonic() - start, assertions,
                                  output=output)
    except FileNotFoundError as e:
        out = CheckResult('missing-jdk', [f'Java not found: {e}', 'Install JDK 17+ and put java and javac on your PATH'])
    except subprocess.TimeoutExpired:
        if phase == 'compile':
            msg = f'javac did not respond within {compile_timeout:.0f}s (machine busy or broken JDK).'
        else:
            msg = f'Test run timed out after {run_timeout:.0f}s: look for an infinite loop or blocking code.'
        out = CheckResult('timeout', [msg], elapsed=time.monotonic() - start)
    except Exception as e:
        out = CheckResult('runner-error', [f'Runner error: {type(e).__name__}: {e}'])
    out.source_hash = digest
    if record:
        save_progress(lesson.slug, out)
    return out


# Do not flash a console window when javac/java are spawned from a GUI-less host.
_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def doctor() -> list[str]:
    info = []
    import sys
    for exe in ['python', 'java', 'javac']:
        command = [sys.executable, '--version'] if exe == 'python' else [exe, '-version']
        try:
            r = subprocess.run(command, capture_output=True, text=True, timeout=10)
            info.append(f'{exe:6} {((r.stdout or r.stderr).strip().splitlines() or ["unknown"])[0]}')
        except FileNotFoundError:
            info.append(f'{exe:6} MISSING')
        except subprocess.TimeoutExpired:
            info.append(f'{exe:6} TIMEOUT')
    try:
        import textual
        info.append(f'textual {getattr(textual, "__version__", "installed")}')
    except ImportError:
        info.append('textual MISSING (the TUI needs: pip install -r requirements.txt)')
    info.append(f'Lessons: {len(all_lessons())}')
    info.append(f'Workspace: {WORKSPACE}')
    return info
