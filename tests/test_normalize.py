import json
from pathlib import Path

from pcdiag.collectors import parse_collector_result
from pcdiag.normalize import build_timeline

FIXTURES = Path(__file__).parent / "fixtures"


def results_from(*names):
    out = {}
    for name in names:
        raw = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
        out[name] = parse_collector_result(raw)
    return out


def test_build_timeline_maps_system_snapshot():
    timeline = build_timeline(results_from("system_snapshot"))
    assert timeline.snapshot is not None
    assert timeline.snapshot.cpu_name == "Example CPU 8-Core"
    assert timeline.snapshot.gpu_names == ["Example GX Graphics"]
    assert timeline.crashes == []
    meta = {m.name: m for m in timeline.meta}
    assert meta["system_snapshot"].ok is True


def test_build_timeline_maps_crashes_and_display_resets():
    timeline = build_timeline(results_from("crashes", "livekernel_display"))
    assert len(timeline.crashes) == 3
    assert timeline.crashes[0].bugcheck_code == "0x116"
    assert all(c.when.tzinfo is not None for c in timeline.crashes)
    assert len(timeline.display_resets) == 3
    assert timeline.display_resets[0].device == "exgpuvd"


def test_build_timeline_maps_drivers_and_changes():
    timeline = build_timeline(results_from("drivers", "changes"))
    gpu = [d for d in timeline.drivers if d.device_class == "Display"]
    assert gpu and gpu[0].install_date is not None
    driver_changes = [c for c in timeline.changes if c.change_type == "driver"]
    assert driver_changes and "exgpuvd" in driver_changes[0].name
    assert driver_changes[0].when.tzinfo is not None


def test_build_timeline_maps_remaining_collectors():
    timeline = build_timeline(
        results_from("whea", "storage_smart", "minidump", "memory_diag"))
    assert timeline.whea_errors[0].error_source == "PCI Express"
    assert timeline.disks[0].wear_pct == 6.0
    assert timeline.minidumps[0].filename.endswith(".dmp")
    assert "no errors" in timeline.memory_diags[0].result
