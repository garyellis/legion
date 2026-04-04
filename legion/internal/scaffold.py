from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_SURFACES = ("cli", "cli_dev")

_FUTURE = "from __future__ import annotations\n"

CORE_TEMPLATES: dict[str, str] = {
    "__init__.py": "",
    "client.py": _FUTURE,
    "models.py": _FUTURE,
}

SERVICE_TEMPLATE = (
    "from __future__ import annotations\n"
    "\n"
    "import logging\n"
    "\n"
    "logger = logging.getLogger(__name__)\n"
)

REPOSITORY_TEMPLATE = (
    "from __future__ import annotations\n"
    "\n"
    "from abc import ABC, abstractmethod\n"
)

DOMAIN_TEMPLATE = (
    "from __future__ import annotations\n"
    "\n"
    "from pydantic import BaseModel\n"
)

TEST_STUB = _FUTURE


# ---------------------------------------------------------------------------
# Path generation
# ---------------------------------------------------------------------------


def core_paths(name: str, root: Path) -> list[Path]:
    """Return the list of files that ``scaffold core <name>`` would create."""
    return [
        root / "legion" / "core" / name / "__init__.py",
        root / "legion" / "core" / name / "client.py",
        root / "legion" / "core" / name / "models.py",
        root / "tests" / f"test_core_{name}.py",
    ]


def service_paths(name: str, root: Path) -> list[Path]:
    """Return the list of files that ``scaffold service <name>`` would create."""
    return [
        root / "legion" / "services" / f"{name}_service.py",
        root / "legion" / "services" / f"{name}_repository.py",
        root / "tests" / f"test_services_{name}.py",
    ]


def domain_paths(name: str, root: Path) -> list[Path]:
    """Return the list of files that ``scaffold domain <name>`` would create."""
    return [
        root / "legion" / "domain" / f"{name}.py",
        root / "tests" / f"test_domain_{name}.py",
    ]


def command_paths(surface: str, group: str, name: str, root: Path) -> list[Path]:
    """Return the list of files that ``scaffold command`` would create."""
    return [
        root / "legion" / surface / "commands" / f"{name}.py",
    ]


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def command_template(group: str, name: str) -> str:
    return (
        "from __future__ import annotations\n"
        "\n"
        "from legion.plumbing.registry import register_command\n"
        "\n"
        "\n"
        f'@register_command("{group}", "{name}")\n'
        f"def {name}() -> None:\n"
        '    """TODO: Add description."""\n'
        "    pass\n"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def check_existing(paths: list[Path]) -> list[Path]:
    """Return paths that already exist."""
    return [p for p in paths if p.exists()]


def write_file(path: Path, content: str) -> None:
    """Write content to path, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
