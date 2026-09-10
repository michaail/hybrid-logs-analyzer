#!/usr/bin/env python3
"""Run scoped quality checks after an agent writes project source files."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOTS = (PROJECT_ROOT / "src" / "api", PROJECT_ROOT / "src" / "model_validator")
FRONTEND_ROOT = PROJECT_ROOT / "frontend" / "src"
PATCH_PATH_PATTERN = re.compile(r"^\*\*\* (?:Add|Update) File: (.+)$", re.MULTILINE)
PATH_KEYS = {"file_path", "filePath", "path", "target_file", "targetFile"}


def _candidate_paths(value: Any) -> Iterable[str]:
    """Yield file paths from a Cursor post-tool-use payload."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in PATH_KEYS and isinstance(item, str):
                yield item
            yield from _candidate_paths(item)
    elif isinstance(value, list):
        for item in value:
            yield from _candidate_paths(item)


def _paths_from_patch(value: Any) -> Iterable[str]:
    """Yield file paths declared in an ApplyPatch payload."""
    if isinstance(value, dict):
        for item in value.values():
            yield from _paths_from_patch(item)
    elif isinstance(value, list):
        for item in value:
            yield from _paths_from_patch(item)
    elif isinstance(value, str):
        yield from PATCH_PATH_PATTERN.findall(value)


def _project_path(path_string: str) -> Path:
    """Resolve an absolute or project-relative tool path."""
    path = Path(path_string)
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _is_within(path: Path, root: Path) -> bool:
    """Return whether a path belongs to a checked source root."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _frontend_command(script: str) -> list[str]:
    """Run a frontend script with the Node version pinned in frontend/.nvmrc."""
    nvm_command = (
        'export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"; '
        'if [ ! -s "$NVM_DIR/nvm.sh" ]; then '
        'echo "nvm is required to run frontend checks." >&2; exit 127; fi; '
        '. "$NVM_DIR/nvm.sh"; '
        f'nvm exec --silent "$(cat frontend/.nvmrc)" npm --prefix frontend run {script}'
    )
    return ["bash", "-lc", nvm_command]


def _run_check(label: str, command: list[str]) -> tuple[bool, str]:
    """Run one check and retain diagnostics for the editing agent."""
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=110,
        )
    except OSError as error:
        return False, f"{label}: could not start ({error})"
    except subprocess.TimeoutExpired:
        return False, f"{label}: timed out after 110 seconds"

    if result.returncode == 0:
        return True, f"{label}: passed"

    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    return False, f"{label}: failed (exit {result.returncode})\n{output[-6000:]}"


def main() -> None:
    """Emit post-edit quality results as Cursor additional context."""
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as error:
        print(json.dumps({"additional_context": f"Quality hook input was invalid: {error}"}))
        return

    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except json.JSONDecodeError:
            tool_input = {"patch": tool_input}

    path_strings = {*_candidate_paths(tool_input), *_paths_from_patch(tool_input)}
    edited_paths = {_project_path(path_string) for path_string in path_strings}
    backend_changed = any(
        _is_within(path, root) for path in edited_paths for root in BACKEND_ROOTS
    )
    frontend_changed = any(_is_within(path, FRONTEND_ROOT) for path in edited_paths)

    if not backend_changed and not frontend_changed:
        print("{}")
        return

    changed_display = ", ".join(
        str(path.relative_to(PROJECT_ROOT))
        for path in sorted(edited_paths)
        if _is_within(path, FRONTEND_ROOT)
        or any(_is_within(path, root) for root in BACKEND_ROOTS)
    )
    checks: list[tuple[str, list[str]]] = []
    if backend_changed:
        python = PROJECT_ROOT / ".venv" / "bin" / "python"
        interpreter = str(python) if python.is_file() else sys.executable
        checks.extend(
            [
                ("Backend Ruff", [interpreter, "-m", "ruff", "check", "src/api", "src/model_validator"]),
                ("Backend mypy", [interpreter, "-m", "mypy", "src/api", "src/model_validator"]),
            ]
        )
    if frontend_changed:
        checks.extend(
            [
                ("Frontend ESLint", _frontend_command("lint")),
                ("Frontend TypeScript", _frontend_command("typecheck")),
            ]
        )

    results = [_run_check(label, command) for label, command in checks]
    passed = all(result[0] for result in results)
    summary = "passed" if passed else "failed"
    details = "\n\n".join(result[1] for result in results)
    print(
        json.dumps(
            {
                "additional_context": (
                    f"Post-edit quality checks {summary} for {changed_display}:\n{details}"
                )
            }
        )
    )


if __name__ == "__main__":
    main()
