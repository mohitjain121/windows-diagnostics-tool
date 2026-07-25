from __future__ import annotations

from pcdiag.rules import Finding


def health_score(findings: list[Finding]) -> int:
    deduction = sum(f.severity.weight * f.confidence.multiplier for f in findings)
    return max(0, round(100 - deduction))
