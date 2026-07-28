from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from pcdiag.config import Config
from pcdiag.models import Timeline
from pcdiag.rules import Confidence, Finding, Severity


@dataclass
class ActionStep:
    tier: int
    title: str
    detail: str
    effort: str
    rationale: str


@dataclass
class Diagnosis:
    id: str
    title: str
    root_cause: str
    confidence: Confidence
    severity: Severity
    whats_happening: str
    timing: str | None = None
    ruled_out: list[str] = field(default_factory=list)
    action_plan: list[ActionStep] = field(default_factory=list)
    supporting_finding_ids: list[str] = field(default_factory=list)


def _load_hours_fraction(hours: list[int]) -> float:
    """Fraction of crash hours falling in evening (17-22) or night (22-6)."""
    if not hours:
        return 0.0
    load = sum(1 for h in hours if h >= 17 or h < 6)
    return load / len(hours)


# Registered synthesizers are added by later tasks.
SYNTHESIZERS: list[Callable[[Timeline, list[Finding], Config], "Diagnosis | None"]] = []


def run_synthesis(timeline: Timeline, findings: list[Finding],
                  config: Config) -> list[Diagnosis]:
    out: list[Diagnosis] = []
    for synth in SYNTHESIZERS:
        result = synth(timeline, findings, config)
        if result is not None:
            out.append(result)
    out.sort(key=lambda d: d.severity.weight * d.confidence.multiplier, reverse=True)
    return out
