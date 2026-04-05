"""Filter service — evaluates filter rules against message text.

Pure evaluation logic, no persistence or side effects.
"""

from __future__ import annotations

import logging
import re
import time

from legion.domain.filter_rule import FilterAction, FilterRule
from legion.plumbing import telemetry
from legion.services.exceptions import FilterError

logger = logging.getLogger(__name__)


class FilterService:
    """Evaluates filter rules against message text."""

    def evaluate(
        self, message_text: str, rules: list[FilterRule]
    ) -> FilterAction | None:
        """Evaluate rules against message text.

        Rules are sorted by priority (highest first). Returns the action
        of the first matching rule, or None if no rules match.
        """
        start = time.perf_counter()
        try:
            sorted_rules = sorted(rules, key=lambda r: r.priority, reverse=True)

            for rule in sorted_rules:
                try:
                    if re.search(rule.pattern, message_text):
                        logger.debug(
                            "Rule %s matched: pattern=%r action=%s",
                            rule.id, rule.pattern, rule.action.value,
                        )
                        telemetry.filter_evaluations_total.labels(
                            rule.action.value,
                        ).inc()
                        return rule.action
                except re.error as exc:
                    raise FilterError(
                        f"Invalid regex in rule {rule.id}: {rule.pattern!r}"
                    ) from exc

            telemetry.filter_evaluations_total.labels("none").inc()
            return None
        finally:
            telemetry.filter_evaluation_duration_seconds.observe(
                time.perf_counter() - start,
            )
