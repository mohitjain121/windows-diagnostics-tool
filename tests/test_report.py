import json
from datetime import datetime, timezone

from pcdiag.models import Timeline
from pcdiag.report import render_report
from pcdiag.rules import Confidence, Evidence, Finding, Severity
from pcdiag.synthesize import ActionStep, Diagnosis


def test_render_report_writes_html_and_json(tmp_path):
    findings = [Finding(
        id="gpu_driver_instability", title="GPU driver instability",
        category="graphics", severity=Severity.CRITICAL, confidence=Confidence.HIGH,
        evidence=[Evidence(label="TDR", detail="3 display resets")],
        recommendation="Roll back the driver.")]
    html_path, json_path = render_report(
        findings, Timeline(), 60, tmp_path,
        generated_at=datetime(2026, 7, 25, tzinfo=timezone.utc))
    assert html_path.exists() and json_path.exists()
    html = html_path.read_text(encoding="utf-8")
    assert "GPU driver instability" in html
    assert "60" in html
    assert "http://" not in html and "https://" not in html  # self-contained
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["score"] == 60
    assert data["findings"][0]["id"] == "gpu_driver_instability"


def test_render_report_includes_primary_diagnosis(tmp_path):
    d = Diagnosis(
        id="power_loss", title="Instant power loss / hard-hang under load",
        root_cause="Likely PSU / power-delivery.", confidence=Confidence.HIGH,
        severity=Severity.CRITICAL, whats_happening="4 unexpected shutdowns...",
        timing="Crashes cluster in evening hours.",
        ruled_out=["Software BSOD — no dump"],
        action_plan=[ActionStep(tier=1, title="Reset GPU tuning", detail="do x",
                                effort="free", rationale="because y")],
        supporting_finding_ids=["unexpected_shutdowns"])
    html_path, json_path = render_report(
        [], Timeline(), 45, tmp_path,
        generated_at=datetime(2026, 7, 28, tzinfo=timezone.utc), diagnoses=[d])
    html = html_path.read_text(encoding="utf-8")
    assert "Primary Diagnosis" in html
    assert "Instant power loss" in html
    assert "Reset GPU tuning" in html
    assert "Ruled out" in html
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["diagnoses"][0]["id"] == "power_loss"
    assert data["diagnoses"][0]["action_plan"][0]["tier"] == 1


def test_render_report_no_diagnosis_section_when_empty(tmp_path):
    html_path, _ = render_report([], Timeline(), 90, tmp_path,
        generated_at=datetime(2026, 7, 28, tzinfo=timezone.utc))
    assert "Primary Diagnosis" not in html_path.read_text(encoding="utf-8")
