from __future__ import annotations

import pytest
import typer

from legion.cli_dev.commands import architecture as architecture_cmd
from legion.internal.architecture.type_check import TypeCheckError, TypeCheckResult


def _recording_stub(calls: list[str], name: str, value):
    def _stub(*_args, **_kwargs):
        calls.append(name)
        return value

    return _stub


class TestArchitectureGate:
    def test_gate_runs_required_checks_in_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        monkeypatch.setattr(
            architecture_cmd,
            "find_uncovered_directories",
            _recording_stub(calls, "find_uncovered_directories", set()),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "find_violations",
            _recording_stub(calls, "find_violations", []),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "find_banned_import_violations",
            _recording_stub(calls, "find_banned_import_violations", []),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "find_dangerous_call_violations",
            _recording_stub(calls, "find_dangerous_call_violations", []),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "run_type_check",
            _recording_stub(
                calls,
                "run_type_check",
                TypeCheckResult(success=True, errors=[], stdout="", stderr="", return_code=0),
            ),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "find_circular_imports",
            _recording_stub(calls, "find_circular_imports", []),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "check_staged_files",
            _recording_stub(calls, "check_staged_files", []),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "print_message",
            _recording_stub(calls, "print_message", None),
        )
        monkeypatch.setattr(architecture_cmd, "render_error", lambda *_args, **_kwargs: None)

        architecture_cmd.architecture_gate()

        assert calls == [
            "find_uncovered_directories",
            "find_violations",
            "find_banned_import_violations",
            "find_dangerous_call_violations",
            "run_type_check",
            "find_circular_imports",
            "check_staged_files",
            "print_message",
        ]

    def test_gate_reports_uncovered_top_level_modules(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        monkeypatch.setattr(
            architecture_cmd,
            "find_uncovered_directories",
            _recording_stub(calls, "find_uncovered_directories", {"legion/example.py"}),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "find_violations",
            _recording_stub(calls, "find_violations", []),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "find_banned_import_violations",
            _recording_stub(calls, "find_banned_import_violations", []),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "find_dangerous_call_violations",
            _recording_stub(calls, "find_dangerous_call_violations", []),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "run_type_check",
            _recording_stub(
                calls,
                "run_type_check",
                TypeCheckResult(success=True, errors=[], stdout="", stderr="", return_code=0),
            ),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "find_circular_imports",
            _recording_stub(calls, "find_circular_imports", []),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "check_staged_files",
            _recording_stub(calls, "check_staged_files", []),
        )

        rendered: list[str] = []
        monkeypatch.setattr(
            architecture_cmd,
            "render_error",
            lambda message, **_kwargs: rendered.append(message),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "print_message",
            lambda *_args, **_kwargs: rendered.append("unexpected-success"),
        )

        with pytest.raises(typer.Exit) as exc_info:
            architecture_cmd.architecture_gate()

        assert exc_info.value.exit_code == 1
        assert len(rendered) == 1
        assert "legion/example.py" in rendered[0]

    def test_gate_fails_on_typecheck_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        monkeypatch.setattr(
            architecture_cmd,
            "find_uncovered_directories",
            _recording_stub(calls, "find_uncovered_directories", set()),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "find_violations",
            _recording_stub(calls, "find_violations", []),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "find_banned_import_violations",
            _recording_stub(calls, "find_banned_import_violations", []),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "find_dangerous_call_violations",
            _recording_stub(calls, "find_dangerous_call_violations", []),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "run_type_check",
            _recording_stub(
                calls,
                "run_type_check",
                TypeCheckResult(
                    success=False,
                    errors=[
                        TypeCheckError(
                            file="legion/example.py",
                            line=1,
                            column=1,
                            severity="error",
                            code="misc",
                            message="boom",
                        )
                    ],
                    stdout="",
                    stderr="",
                    return_code=1,
                ),
            ),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "find_circular_imports",
            _recording_stub(calls, "find_circular_imports", []),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "check_staged_files",
            _recording_stub(calls, "check_staged_files", []),
        )

        rendered: list[str] = []
        monkeypatch.setattr(
            architecture_cmd,
            "render_error",
            lambda message, **_kwargs: rendered.append(message),
        )
        monkeypatch.setattr(
            architecture_cmd,
            "print_message",
            lambda *_args, **_kwargs: rendered.append("unexpected-success"),
        )

        with pytest.raises(typer.Exit) as exc_info:
            architecture_cmd.architecture_gate()

        assert exc_info.value.exit_code == 1
        assert len(rendered) == 1
        assert "Type checking errors found" in rendered[0]
