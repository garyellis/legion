from __future__ import annotations

from pathlib import Path

import pytest
import typer

from legion.cli_dev.commands.scaffold import (
    scaffold_command,
    scaffold_core,
    scaffold_domain,
    scaffold_service,
)
from legion.internal.scaffold import (
    CORE_TEMPLATES,
    DOMAIN_TEMPLATE,
    REPOSITORY_TEMPLATE,
    SERVICE_TEMPLATE,
    TEST_STUB,
    command_paths,
    command_template,
    core_paths,
    domain_paths,
    service_paths,
)


# ---------------------------------------------------------------------------
# Path generation tests
# ---------------------------------------------------------------------------


class TestCorePathGeneration:
    def test_returns_four_paths(self, tmp_path: Path) -> None:
        paths = core_paths("foo", root=tmp_path)
        assert len(paths) == 4

    def test_init_file(self, tmp_path: Path) -> None:
        paths = core_paths("foo", root=tmp_path)
        assert paths[0] == tmp_path / "legion" / "core" / "foo" / "__init__.py"

    def test_client_file(self, tmp_path: Path) -> None:
        paths = core_paths("foo", root=tmp_path)
        assert paths[1] == tmp_path / "legion" / "core" / "foo" / "client.py"

    def test_models_file(self, tmp_path: Path) -> None:
        paths = core_paths("foo", root=tmp_path)
        assert paths[2] == tmp_path / "legion" / "core" / "foo" / "models.py"

    def test_test_file(self, tmp_path: Path) -> None:
        paths = core_paths("foo", root=tmp_path)
        assert paths[3] == tmp_path / "tests" / "test_core_foo.py"


class TestServicePathGeneration:
    def test_returns_three_paths(self, tmp_path: Path) -> None:
        paths = service_paths("bar", root=tmp_path)
        assert len(paths) == 3

    def test_service_file(self, tmp_path: Path) -> None:
        paths = service_paths("bar", root=tmp_path)
        assert paths[0] == tmp_path / "legion" / "services" / "bar_service.py"

    def test_repository_file(self, tmp_path: Path) -> None:
        paths = service_paths("bar", root=tmp_path)
        assert paths[1] == tmp_path / "legion" / "services" / "bar_repository.py"

    def test_test_file(self, tmp_path: Path) -> None:
        paths = service_paths("bar", root=tmp_path)
        assert paths[2] == tmp_path / "tests" / "test_services_bar.py"


class TestDomainPathGeneration:
    def test_returns_two_paths(self, tmp_path: Path) -> None:
        paths = domain_paths("baz", root=tmp_path)
        assert len(paths) == 2

    def test_domain_file(self, tmp_path: Path) -> None:
        paths = domain_paths("baz", root=tmp_path)
        assert paths[0] == tmp_path / "legion" / "domain" / "baz.py"

    def test_test_file(self, tmp_path: Path) -> None:
        paths = domain_paths("baz", root=tmp_path)
        assert paths[1] == tmp_path / "tests" / "test_domain_baz.py"


class TestCommandPathGeneration:
    def test_returns_one_path(self, tmp_path: Path) -> None:
        paths = command_paths("cli_dev", "tools", "hello", root=tmp_path)
        assert len(paths) == 1

    def test_command_file(self, tmp_path: Path) -> None:
        paths = command_paths("cli_dev", "tools", "hello", root=tmp_path)
        assert paths[0] == tmp_path / "legion" / "cli_dev" / "commands" / "hello.py"

    def test_cli_surface(self, tmp_path: Path) -> None:
        paths = command_paths("cli", "ops", "deploy", root=tmp_path)
        assert paths[0] == tmp_path / "legion" / "cli" / "commands" / "deploy.py"


# ---------------------------------------------------------------------------
# Template content tests
# ---------------------------------------------------------------------------


class TestTemplates:
    def test_core_templates_have_future_annotations(self) -> None:
        for name in ("client.py", "models.py"):
            assert "from __future__ import annotations" in CORE_TEMPLATES[name]

    def test_core_init_is_empty(self) -> None:
        assert CORE_TEMPLATES["__init__.py"] == ""

    def test_service_template_has_logger(self) -> None:
        assert "import logging" in SERVICE_TEMPLATE
        assert "logger = logging.getLogger(__name__)" in SERVICE_TEMPLATE

    def test_repository_template_has_abc(self) -> None:
        assert "from abc import ABC, abstractmethod" in REPOSITORY_TEMPLATE

    def test_domain_template_has_pydantic(self) -> None:
        assert "from pydantic import BaseModel" in DOMAIN_TEMPLATE

    def test_command_template_has_register(self) -> None:
        content = command_template("mygroup", "myname")
        assert '@register_command("mygroup", "myname")' in content
        assert "def myname() -> None:" in content
        assert "from __future__ import annotations" in content


# ---------------------------------------------------------------------------
# Dry-run tests (should NOT create files)
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_core_dry_run_creates_no_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.scaffold._project_root", lambda: tmp_path
        )
        scaffold_core(name="phantom", dry_run=True)
        assert not (tmp_path / "legion" / "core" / "phantom").exists()

    def test_service_dry_run_creates_no_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.scaffold._project_root", lambda: tmp_path
        )
        scaffold_service(name="phantom", dry_run=True)
        assert not (tmp_path / "legion" / "services" / "phantom_service.py").exists()

    def test_domain_dry_run_creates_no_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.scaffold._project_root", lambda: tmp_path
        )
        scaffold_domain(name="phantom", dry_run=True)
        assert not (tmp_path / "legion" / "domain" / "phantom.py").exists()

    def test_command_dry_run_creates_no_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.scaffold._project_root", lambda: tmp_path
        )
        scaffold_command(surface="cli_dev", group="test", name="phantom", dry_run=True)
        assert not (tmp_path / "legion" / "cli_dev" / "commands" / "phantom.py").exists()


# ---------------------------------------------------------------------------
# File creation tests
# ---------------------------------------------------------------------------


class TestFileCreation:
    def test_core_creates_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.scaffold._project_root", lambda: tmp_path
        )
        scaffold_core(name="newmod", dry_run=False)
        for p in core_paths("newmod", root=tmp_path):
            assert p.exists(), f"Expected {p} to exist"

    def test_service_creates_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.scaffold._project_root", lambda: tmp_path
        )
        scaffold_service(name="newsvc", dry_run=False)
        for p in service_paths("newsvc", root=tmp_path):
            assert p.exists(), f"Expected {p} to exist"

    def test_domain_creates_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.scaffold._project_root", lambda: tmp_path
        )
        scaffold_domain(name="newdom", dry_run=False)
        for p in domain_paths("newdom", root=tmp_path):
            assert p.exists(), f"Expected {p} to exist"

    def test_command_creates_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.scaffold._project_root", lambda: tmp_path
        )
        scaffold_command(surface="cli_dev", group="ops", name="hello", dry_run=False)
        for p in command_paths("cli_dev", "ops", "hello", root=tmp_path):
            assert p.exists(), f"Expected {p} to exist"

    def test_core_file_contents(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.scaffold._project_root", lambda: tmp_path
        )
        scaffold_core(name="mycore", dry_run=False)
        client = (tmp_path / "legion" / "core" / "mycore" / "client.py").read_text()
        assert "from __future__ import annotations" in client

    def test_service_file_contents(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.scaffold._project_root", lambda: tmp_path
        )
        scaffold_service(name="mysvc", dry_run=False)
        svc = (tmp_path / "legion" / "services" / "mysvc_service.py").read_text()
        assert "logger = logging.getLogger(__name__)" in svc


# ---------------------------------------------------------------------------
# Overwrite refusal tests
# ---------------------------------------------------------------------------


class TestOverwriteRefusal:
    def test_core_refuses_overwrite(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.scaffold._project_root", lambda: tmp_path
        )
        scaffold_core(name="existing", dry_run=False)
        with pytest.raises(typer.Exit):
            scaffold_core(name="existing", dry_run=False)

    def test_service_refuses_overwrite(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.scaffold._project_root", lambda: tmp_path
        )
        scaffold_service(name="existing", dry_run=False)
        with pytest.raises(typer.Exit):
            scaffold_service(name="existing", dry_run=False)

    def test_domain_refuses_overwrite(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.scaffold._project_root", lambda: tmp_path
        )
        scaffold_domain(name="existing", dry_run=False)
        with pytest.raises(typer.Exit):
            scaffold_domain(name="existing", dry_run=False)

    def test_command_refuses_overwrite(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.scaffold._project_root", lambda: tmp_path
        )
        scaffold_command(surface="cli_dev", group="g", name="existing", dry_run=False)
        with pytest.raises(typer.Exit):
            scaffold_command(surface="cli_dev", group="g", name="existing", dry_run=False)


# ---------------------------------------------------------------------------
# Invalid surface test
# ---------------------------------------------------------------------------


class TestInvalidSurface:
    def test_rejects_invalid_surface(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "legion.cli_dev.commands.scaffold._project_root", lambda: tmp_path
        )
        with pytest.raises(typer.Exit):
            scaffold_command(surface="slack", group="g", name="cmd", dry_run=False)
