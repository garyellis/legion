"""Tests for FilterService."""

import pytest

from legion.domain.filter_rule import FilterAction, FilterRule
from legion.services.exceptions import FilterError
from legion.services.filter_service import FilterService


@pytest.fixture()
def svc():
    return FilterService()


class TestFilterService:
    def test_single_matching_rule(self, svc):
        rules = [
            FilterRule(
                channel_mapping_id="cm-1", pattern="CRITICAL",
                action=FilterAction.TRIAGE,
            ),
        ]
        assert svc.evaluate("CRITICAL: disk full", rules) == FilterAction.TRIAGE

    def test_higher_priority_wins(self, svc):
        rules = [
            FilterRule(
                channel_mapping_id="cm-1", pattern=".*",
                action=FilterAction.TRIAGE, priority=1,
            ),
            FilterRule(
                channel_mapping_id="cm-1", pattern="heartbeat",
                action=FilterAction.IGNORE, priority=10,
            ),
        ]
        assert svc.evaluate("heartbeat check", rules) == FilterAction.IGNORE

    def test_no_matching_rules_returns_none(self, svc):
        rules = [
            FilterRule(
                channel_mapping_id="cm-1", pattern="CRITICAL",
                action=FilterAction.TRIAGE,
            ),
        ]
        assert svc.evaluate("INFO: all systems normal", rules) is None

    def test_ignore_action_returned(self, svc):
        rules = [
            FilterRule(
                channel_mapping_id="cm-1", pattern="test-alert",
                action=FilterAction.IGNORE,
            ),
        ]
        assert svc.evaluate("test-alert fired", rules) == FilterAction.IGNORE

    def test_invalid_regex_raises_filter_error(self, svc):
        rules = [
            FilterRule(
                channel_mapping_id="cm-1", pattern="[invalid",
                action=FilterAction.TRIAGE,
            ),
        ]
        with pytest.raises(FilterError, match="Invalid regex"):
            svc.evaluate("some text", rules)

    def test_empty_rules_returns_none(self, svc):
        assert svc.evaluate("any message", []) is None

    def test_first_match_wins_at_same_priority(self, svc):
        rules = [
            FilterRule(
                channel_mapping_id="cm-1", pattern="error",
                action=FilterAction.TRIAGE, priority=5,
            ),
            FilterRule(
                channel_mapping_id="cm-1", pattern="error",
                action=FilterAction.IGNORE, priority=5,
            ),
        ]
        result = svc.evaluate("error occurred", rules)
        assert result is not None  # one of the two matches
