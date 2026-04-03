"""Dead code detection via vulture.

Invokes vulture programmatically and returns structured results that
can be consumed by CLI commands. Advisory only — not a CI gate.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

from legion.internal.architecture.dependency_check import PACKAGE_ROOT

PROJECT_ROOT = PACKAGE_ROOT.parent

# vulture output: "file.py:42: unused function 'foo' (80% confidence)"
_VULTURE_RE = re.compile(
    r"^(.+?):(\d+): unused (\w+(?:\s\w+)*) '(.+?)' \((\d+)% confidence\)$"
)


class DeadCodeItem(NamedTuple):
    file: str
    line: int
    name: str
    item_type: str      # "function", "import", "variable", "class", etc.
    confidence: int     # vulture confidence percentage


class DeadCodeResult(NamedTuple):
    success: bool       # True if no dead code found
    items: list[DeadCodeItem]
    stdout: str
    stderr: str
    return_code: int


def _parse_vulture_output(output: str) -> list[DeadCodeItem]:
    """Parse vulture output lines into structured items."""
    items: list[DeadCodeItem] = []
    for line in output.splitlines():
        match = _VULTURE_RE.match(line.strip())
        if not match:
            continue
        items.append(
            DeadCodeItem(
                file=match.group(1),
                line=int(match.group(2)),
                item_type=match.group(3),
                name=match.group(4),
                confidence=int(match.group(5)),
            )
        )
    return items


def run_dead_code_check(
    paths: list[str] | None = None,
    *,
    min_confidence: int = 80,
) -> DeadCodeResult:
    """Run vulture on the specified paths or the entire legion package.

    Args:
        paths: Specific files or directories to check. Defaults to the
               legion package directory.
        min_confidence: Minimum confidence threshold (0-100).

    Returns:
        Structured result with parsed items and raw output.
    """
    targets = paths or [str(PACKAGE_ROOT)]

    # Include whitelist if it exists
    whitelist = PROJECT_ROOT / "vulture_whitelist.py"

    all_paths = list(targets)
    if whitelist.is_file():
        all_paths.append(str(whitelist))

    cmd = [
        sys.executable, "-m", "vulture",
        *all_paths,
        f"--min-confidence={min_confidence}",
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )

    items = _parse_vulture_output(result.stdout)

    return DeadCodeResult(
        success=result.returncode == 0,
        items=items,
        stdout=result.stdout,
        stderr=result.stderr,
        return_code=result.returncode,
    )


def format_dead_code(result: DeadCodeResult) -> str:
    """Format dead code results into a human-readable report."""
    if result.success:
        return "No dead code found."

    lines = ["\nPotentially unused code found:\n"]

    for item in result.items:
        lines.append(
            f"  {item.file}:{item.line}  "
            f"unused {item.item_type} '{item.name}' "
            f"({item.confidence}% confidence)"
        )

    lines.append(f"\n{len(result.items)} item(s) found.")
    lines.append(
        "Add false positives to vulture_whitelist.py to suppress."
    )

    return "\n".join(lines)
