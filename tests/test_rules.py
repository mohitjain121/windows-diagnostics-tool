import json
from datetime import datetime, timezone
from pathlib import Path

from pcdiag.collectors import parse_collector_result
from pcdiag.config import Config
from pcdiag.models import Timeline
from pcdiag.normalize import build_timeline
from pcdiag.rules import Confidence, Severity, run_rules

FIXTURES = Path(__file__).parent / "fixtures"


def cfg():
    return Config(now=datetime(2026, 7, 25, tzinfo=timezone.utc))


def scenario(folder, *names):
    out = {}
    for name in names:
        raw = json.loads((FIXTURES / folder / f"{name}.json").read_text("utf-8"))
        out[name] = parse_collector_result(raw)
    return build_timeline(out)


def single(name):
    raw = json.loads((FIXTURES / f"{name}.json").read_text("utf-8"))
    result = parse_collector_result(raw)
    return build_timeline({result.collector: result})


def test_run_rules_sorts_by_weighted_severity():
    findings = run_rules(Timeline(), cfg())
    weights = [f.severity.weight * f.confidence.multiplier for f in findings]
    assert weights == sorted(weights, reverse=True)


def test_severity_and_confidence_weights():
    assert Severity.CRITICAL.weight == 40
    assert Confidence.HIGH.multiplier == 1.0
    assert Confidence.LOW.label == "LOW"


def test_gpu_driver_instability_high_confidence():
    timeline = scenario("scenario_gpu_crash", "crashes",
                        "livekernel_display", "drivers", "changes")
    findings = run_rules(timeline, cfg())
    gpu = [f for f in findings if f.id == "gpu_driver_instability"]
    assert gpu, "expected a GPU driver instability finding"
    assert gpu[0].confidence == Confidence.HIGH
    assert gpu[0].severity == Severity.CRITICAL
    assert any("566.36" in e.detail or "0x116" in e.detail or "exgpuvd" in e.detail
               for e in gpu[0].evidence)


def test_change_vs_symptom_names_recent_change():
    timeline = scenario("scenario_gpu_crash", "crashes", "changes")
    findings = run_rules(timeline, cfg())
    generic = [f for f in findings if f.id == "change_vs_symptom"]
    assert generic
    assert any("Example" in e.detail or "exgpuvd" in e.detail for e in generic[0].evidence)


def test_ssd_degradation_flagged():
    timeline = single("scenario_ssd_wear")
    findings = run_rules(timeline, cfg())
    assert any(f.id == "ssd_degradation" for f in findings)


def test_whea_hardware_high_when_uncorrected_repeats():
    timeline = single("scenario_whea")
    findings = run_rules(timeline, cfg())
    whea = [f for f in findings if f.id == "whea_hardware"]
    assert whea and whea[0].confidence == Confidence.HIGH


def test_unexpected_shutdowns_flagged_without_bugcheck():
    timeline = single("scenario_hard_shutdowns")
    findings = run_rules(timeline, cfg())
    shutdown = [f for f in findings if f.id == "unexpected_shutdowns"]
    assert shutdown, "expected an unexpected-shutdowns finding"
    assert shutdown[0].confidence == Confidence.HIGH  # 5 events >= 4
    assert shutdown[0].severity == Severity.CRITICAL
    # No bugcheck / no dump -> the hard-power-off interpretation should appear.
    assert "no bugcheck" in shutdown[0].evidence[0].detail
    assert "PSU" in shutdown[0].recommendation
