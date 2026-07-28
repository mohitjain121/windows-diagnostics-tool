from __future__ import annotations

from pathlib import Path

from pcdiag.collectors import CollectorResult
from pcdiag.config import Config
from pcdiag.normalize import build_timeline
from pcdiag.report import render_report
from pcdiag.rules import run_rules
from pcdiag.score import health_score
from pcdiag.synthesize import run_synthesis

COLLECTOR_NAMES = [
    "system_snapshot", "crashes", "livekernel_display", "whea", "minidump",
    "drivers", "changes", "updates", "reliability", "storage_smart", "memory_diag",
    "memory_config", "thermal",
]


def run_pipeline(results: dict[str, CollectorResult], out_dir: Path,
                 config: Config) -> tuple[Path, Path, int]:
    timeline = build_timeline(results)
    findings = run_rules(timeline, config)
    diagnoses = run_synthesis(timeline, findings, config)
    score = health_score(findings)
    html_path, json_path = render_report(
        findings, timeline, score, out_dir,
        generated_at=config.now, diagnoses=diagnoses)
    return html_path, json_path, score
