from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from pcdiag.models import Timeline
from pcdiag.rules import Finding

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def findings_to_dicts(findings: list[Finding]) -> list[dict]:
    return [{
        "id": f.id, "title": f.title, "category": f.category,
        "severity": f.severity.value, "confidence": f.confidence.value,
        "evidence": [{"label": e.label, "detail": e.detail,
                      "when": e.when.isoformat() if e.when else None} for e in f.evidence],
        "recommendation": f.recommendation,
    } for f in findings]


def diagnoses_to_dicts(diagnoses: list) -> list[dict]:
    return [{
        "id": d.id, "title": d.title, "root_cause": d.root_cause,
        "severity": d.severity.value, "confidence": d.confidence.value,
        "whats_happening": d.whats_happening, "timing": d.timing,
        "ruled_out": list(d.ruled_out),
        "action_plan": [{"tier": s.tier, "title": s.title, "detail": s.detail,
                         "effort": s.effort, "rationale": s.rationale}
                        for s in d.action_plan],
        "supporting_finding_ids": list(d.supporting_finding_ids),
    } for d in diagnoses]


def timeline_summary(timeline: Timeline) -> dict:
    return {
        "crashes": len(timeline.crashes),
        "display_resets": len(timeline.display_resets),
        "whea_errors": len(timeline.whea_errors),
        "changes": len(timeline.changes),
        "disks": len(timeline.disks),
    }


def render_report(findings: list[Finding], timeline: Timeline, score: int,
                  out_dir: Path, generated_at: datetime,
                  diagnoses: list | None = None) -> tuple[Path, Path]:
    diagnoses = diagnoses or []
    out_dir.mkdir(parents=True, exist_ok=True)
    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)),
                      autoescape=select_autoescape(["html"]))
    template = env.get_template("report.html.j2")
    changes = sorted(timeline.changes, key=lambda c: c.when, reverse=True)
    html = template.render(
        findings=findings, score=score, diagnoses=diagnoses,
        sensors=timeline.sensors,
        generated_at=generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        changes=changes, meta=timeline.meta)
    html_path = out_dir / "report.html"
    json_path = out_dir / "report.json"
    html_path.write_text(html, encoding="utf-8")
    json_path.write_text(json.dumps({
        "generated_at": generated_at.isoformat(),
        "score": score,
        "diagnoses": diagnoses_to_dicts(diagnoses),
        "findings": findings_to_dicts(findings),
        "timeline_summary": timeline_summary(timeline),
    }, indent=2), encoding="utf-8")
    return html_path, json_path
