"""Guardrails for local deploy-time migration wiring."""

from __future__ import annotations

from pathlib import Path


def _compose_text() -> str:
    repo_root = Path(__file__).resolve().parents[1]
    return (repo_root / "docker-compose.yml").read_text()


def test_local_compose_runs_migrations_before_api_startup() -> None:
    compose = _compose_text()

    assert "migrate:" in compose
    assert "command: legion-cli db upgrade" in compose
    assert "condition: service_completed_successfully" in compose


def test_local_compose_shares_db_url_between_api_and_migration_paths() -> None:
    compose = _compose_text()

    assert "DATABASE_URL:" in compose
    assert "LEGION_DB_URL:" in compose
    assert "<<: *legion-db-env" in compose
