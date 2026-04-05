"""Tests for FilterService."""

from __future__ import annotations

import pytest

from legion.domain.filter_rule import FilterAction, FilterRule
from legion.services.exceptions import FilterError
from legion.services.filter_service import FilterService


class _RecorderMetric:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def labels(self, *args: object) -> _RecorderMetric:
        self.calls.append(("labels", args))
        return self

    def inc(self, *args: object) -> None:
        self.calls.append(("inc", args))

    def observe(self, *args: object) -> None:
        self.calls.append(("observe", args))


@pytest.fixture()
def svc() -> FilterService:
    return FilterService()


class TestFilterService:
    def test_single_matching_rule(self, svc: FilterService) -> None:
        rules = [
            FilterRule(
                channel_mapping_id="cm-1",
                pattern="CRITICAL",
                action=FilterAction.TRIAGE,
            ),
        ]
        assert svc.evaluate("CRITICAL: disk full", rules) == FilterAction.TRIAGE

    def test_matching_rule_records_outcome_and_duration(
        self,
        svc: FilterService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        evaluations = _RecorderMetric()
        duration = _RecorderMetric()
        monkeypatch.setattr(
            "legion.services.filter_service.telemetry.filter_evaluations_total",
            evaluations,
        )
        monkeypatch.setattr(
            "legion.services.filter_service.telemetry.filter_evaluation_duration_seconds",
            duration,
        )
        rules = [
            FilterRule(
                channel_mapping_id="cm-1",
                pattern="CRITICAL",
                action=FilterAction.TRIAGE,
            ),
        ]

        result = svc.evaluate("CRITICAL: disk full", rules)

        assert result == FilterAction.TRIAGE
        assert ("labels", ("TRIAGE",)) in evaluations.calls
        assert ("inc", ()) in evaluations.calls
        assert sum(1 for name, _args in duration.calls if name == "observe") == 1

    def test_higher_priority_wins(self, svc: FilterService) -> None:
        rules = [
            FilterRule(
                channel_mapping_id="cm-1",
                pattern=".*",
                action=FilterAction.TRIAGE,
                priority=1,
            ),
            FilterRule(
                channel_mapping_id="cm-1",
                pattern="heartbeat",
                action=FilterAction.IGNORE,
                priority=10,
            ),
        ]
        assert svc.evaluate("heartbeat check", rules) == FilterAction.IGNORE

    def test_no_matching_rules_returns_none_and_records_metrics(
        self,
        svc: FilterService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        evaluations = _RecorderMetric()
        duration = _RecorderMetric()
        monkeypatch.setattr(
            "legion.services.filter_service.telemetry.filter_evaluations_total",
            evaluations,
        )
        monkeypatch.setattr(
            "legion.services.filter_service.telemetry.filter_evaluation_duration_seconds",
            duration,
        )
        rules = [
            FilterRule(
                channel_mapping_id="cm-1",
                pattern="CRITICAL",
                action=FilterAction.TRIAGE,
            ),
        ]

        assert svc.evaluate("INFO: all systems normal", rules) is None
        assert ("labels", ("none",)) in evaluations.calls
        assert ("inc", ()) in evaluations.calls
        assert sum(1 for name, _args in duration.calls if name == "observe") == 1

    def test_ignore_action_returned(self, svc: FilterService) -> None:
        rules = [
            FilterRule(
                channel_mapping_id="cm-1",
                pattern="test-alert",
                action=FilterAction.IGNORE,
            ),
        ]
        assert svc.evaluate("test-alert fired", rules) == FilterAction.IGNORE

    def test_invalid_regex_raises_filter_error_and_records_duration(
        self,
        svc: FilterService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        duration = _RecorderMetric()
        monkeypatch.setattr(
            "legion.services.filter_service.telemetry.filter_evaluation_duration_seconds",
            duration,
        )
        rules = [
            FilterRule(
                channel_mapping_id="cm-1",
                pattern="[invalid",
                action=FilterAction.TRIAGE,
            ),
        ]

        with pytest.raises(FilterError, match="Invalid regex"):
            svc.evaluate("some text", rules)

        assert sum(1 for name, _args in duration.calls if name == "observe") == 1

    def test_empty_rules_returns_none(self, svc: FilterService) -> None:
        assert svc.evaluate("any message", []) is None

    def test_first_match_wins_at_same_priority(self, svc: FilterService) -> None:
        rules = [
            FilterRule(
                channel_mapping_id="cm-1",
                pattern="error",
                action=FilterAction.TRIAGE,
                priority=5,
            ),
            FilterRule(
                channel_mapping_id="cm-1",
                pattern="error",
                action=FilterAction.IGNORE,
                priority=5,
            ),
        ]
        result = svc.evaluate("error occurred", rules)
        assert result is not None
