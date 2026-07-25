import json
from datetime import datetime, timezone

from pcdiag.models import Timeline
from pcdiag.report import render_report
from pcdiag.rules import Confidence, Evidence, Finding, Severity


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
