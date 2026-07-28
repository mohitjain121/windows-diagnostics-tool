from datetime import datetime, timezone

from pcdiag.config import Config
from pcdiag.models import Timeline
from pcdiag.synthesize import _load_hours_fraction, run_synthesis


def cfg():
    return Config(now=datetime(2026, 7, 28, tzinfo=timezone.utc))


def test_load_hours_fraction():
    # 3 of 4 in evening/night (>=17 or <6)
    assert _load_hours_fraction([19, 21, 23, 10]) == 0.75
    assert _load_hours_fraction([]) == 0.0


def test_run_synthesis_empty_timeline_returns_empty():
    assert run_synthesis(Timeline(), [], cfg()) == []


def test_power_loss_diagnosis_full():  # uses scenario_power_loss fixtures
    import json
    from pathlib import Path
    from pcdiag.collectors import parse_collector_result
    from pcdiag.normalize import build_timeline
    from pcdiag.rules import run_rules

    fx = Path(__file__).parent / "fixtures" / "scenario_power_loss"
    results = {}
    for name in ("crashes", "memory_config", "system_snapshot", "changes"):
        results[name] = parse_collector_result(json.loads((fx / f"{name}.json").read_text("utf-8")))
    timeline = build_timeline(results)
    findings = run_rules(timeline, cfg())
    diagnoses = run_synthesis(timeline, findings, cfg())

    power = [d for d in diagnoses if d.id == "power_loss"]
    assert power, "expected a power_loss diagnosis"
    d = power[0]
    assert d.confidence.value == "high"          # 4 KP-41, no WHEA
    assert d.timing is not None                  # evening/night clustered
    assert any("Software BSOD" in r for r in d.ruled_out)
    assert any("RAM errors" in r for r in d.ruled_out)
    assert any("Sleep/resume" in r for r in d.ruled_out)
    tiers = {s.tier for s in d.action_plan}
    assert tiers == {1, 2, 3}
    # iGPU present in snapshot -> integrated-graphics isolation step exists
    assert any("integrated" in s.detail.lower() for s in d.action_plan)
    # a tuning utility change is present -> uninstall step exists
    assert any("uninstall" in s.title.lower() for s in d.action_plan)


def test_power_loss_absent_when_bugcheck_present():
    from pcdiag.models import CrashEvent
    from pcdiag.rules import Confidence, Evidence, Finding, Severity
    t = Timeline()
    t.crashes.append(CrashEvent(when=datetime(2026,7,27,tzinfo=timezone.utc),
        kind="bugcheck", event_id=1001, source="WER", bugcheck_code="0x9f", message="x"))
    finding = Finding(id="unexpected_shutdowns", title="x", category="stability",
        severity=Severity.CRITICAL, confidence=Confidence.HIGH,
        evidence=[Evidence(label="l", detail="d")], recommendation="r")
    from pcdiag.synthesize import _synthesize_power_loss
    assert _synthesize_power_loss(t, [finding], cfg()) is None


def test_power_loss_no_integrated_step_for_discrete_vega_only():
    """Regression: discrete GPU with Vega in name should not trigger integrated-GPU step."""
    from pcdiag.models import CrashEvent, SystemSnapshot
    from pcdiag.rules import Confidence, Evidence, Finding, Severity

    t = Timeline()
    # Single discrete GPU with "Vega" in its name (real discrete GPUs can have Vega)
    t.snapshot = SystemSnapshot(
        cpu_name="Example CPU",
        gpu_names=["Example Radeon RX Vega 0000"],  # discrete only, but contains "Vega"
        ram_total_gb=32.0,
        os_caption="Windows",
        os_build="00000",
        uptime_hours=1.0,
        cpu_load_pct=5.0,
        mem_used_pct=30.0,
        system_disk_free_pct=50.0
    )
    # Add 4 KP-41 events in evening hours to trigger diagnosis
    for hour in [19, 20, 21, 23]:
        t.crashes.append(CrashEvent(
            when=datetime(2026, 7, 20, hour, 0, 0, tzinfo=timezone.utc),
            kind="unexpected_shutdown",
            event_id=41,
            source="Kernel-Power",
            bugcheck_code=None,
            message="rebooted",
            actual_local_hour=hour,
            sleep_in_progress=0,
            power_button=0
        ))

    finding = Finding(id="unexpected_shutdowns", title="x", category="stability",
        severity=Severity.CRITICAL, confidence=Confidence.HIGH,
        evidence=[Evidence(label="l", detail="d")], recommendation="r")

    from pcdiag.synthesize import _synthesize_power_loss
    diag = _synthesize_power_loss(t, [finding], cfg())
    assert diag is not None, "expected power_loss diagnosis"
    # Assert NO integrated-graphics step exists
    assert not any("integrated" in s.detail.lower() for s in diag.action_plan), \
        "Should not have integrated-graphics step for discrete-only GPU"
