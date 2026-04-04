# ADR-NNNN: [Short Title]

**Status**: PROPOSED | ACCEPTED | DEPRECATED | SUPERSEDED
**Date**: YYYY-MM-DD
**Author**: [name or agent]

<!--
WRITING GUIDELINES — delete this block before merging.

Aim for high signal, low noise. Every sentence should earn its place.
Think from first principles — start from the actual constraints and
requirements, not convention. What does the system require? What breaks
if we don't do this?

- State the problem before the solution. A reader who doesn't know
  the codebase should understand WHY after reading Context alone.
- Prefer concrete statements over vague ones. Name the files, the
  layers, the constraints. "We chose X because of Y" beats
  "after careful consideration we decided to go with X."
- No filler. Cut "in order to", "it should be noted that",
  "as mentioned above". If a sentence doesn't change the reader's
  understanding, delete it.
- Alternatives must have real rejection reasons, not strawmen.
  "Rejected: more complex" is not a reason. What complexity?
  What would break?
- Consequences should be honest. If something is a trade-off,
  say so. The goal is informed future decisions, not justification.
-->

## Context

What problem does this solve? What forces or constraints led here?
A non-team-member should understand the situation from this section alone.

## Decision

What did we decide, and why? Be specific — name files, layers,
patterns. Lead with the what, follow with the key design choices.

## Dependency Details (if adding a package)

| Field | Value |
|:------|:------|
| Package | `package-name` |
| Version | `>=X.Y,<X+1` |
| License | MIT / Apache-2.0 / etc. |
| PyPI downloads/month | ~N |
| Maintainers | N active |
| Transitive deps | N |
| Last release | YYYY-MM-DD |
| Known CVEs | None / list |

## Alternatives Considered

Each alternative needs a concrete rejection reason.
"Too complex" is not enough — say what breaks or what cost it adds.

1. **Alternative A** — why rejected
2. **Alternative B** — why rejected

## Consequences

Be honest about trade-offs. This section helps future decisions.

- What does this enable?
- What does it cost? (complexity, migration, API changes)
- What follow-up work does it create?

## References

- Links to relevant issues, PRs, or docs
