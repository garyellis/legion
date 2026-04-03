"""Vulture whitelist — suppress false positives for dynamically used code.

Vulture reads this file to understand that certain symbols are used
even though they appear unreferenced in static analysis. Each line
"uses" a symbol so vulture considers it alive.
"""

# --- Pydantic model_config class variables ---
# Pydantic uses model_config at class construction time; vulture can't see this.
from legion.plumbing.config.base import LegionConfig
LegionConfig.model_config  # type: ignore[unused-ignore]

# --- CLI commands registered via @register_command decorator ---
# These are discovered dynamically by pkgutil.iter_modules + registry pattern.
from legion.cli.commands import architecture, lab, network, shout  # noqa: F401

# --- FastAPI route handlers (registered via @router decorators) ---
from legion.api import routes  # noqa: F401
from legion.api import deps, errors, websocket  # noqa: F401

# --- Slack command handlers (registered via @app.command decorators) ---
from legion.slack import commands  # noqa: F401

# --- Entry point functions referenced in pyproject.toml [project.scripts] ---
from legion.main import main  # noqa: F401

# --- Enum members (used at runtime via value matching) ---
# vulture can't see enum member usage through .value comparisons
from legion.core.network.dns_check import MigrationPhase
MigrationPhase.REDUCING_TTL
MigrationPhase.READY_TO_PIVOT
MigrationPhase.MIGRATING
MigrationPhase.CLEANUP

# --- __exit__ parameters (required by protocol but unused) ---
# exc_type, exc_val, exc_tb are required by context manager protocol
_.exc_type  # type: ignore[name-defined]
_.exc_val  # type: ignore[name-defined]
_.exc_tb  # type: ignore[name-defined]

# --- NamedTuple fields accessed externally ---
from legion.internal.architecture.type_check import TypeCheckResult
TypeCheckResult.return_code

from legion.internal.architecture.dead_code import DeadCodeResult
DeadCodeResult.return_code

from legion.internal.architecture.security_scan import SecurityScanResult
SecurityScanResult.return_code

from legion.internal.architecture.vuln_scan import VulnScanResult
VulnScanResult.return_code

