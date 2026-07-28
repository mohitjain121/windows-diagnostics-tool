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


def test_norm_crashes_reads_actual_time_and_flags():
    raw = {
        "collector": "crashes",
        "collected_at": "2026-07-28T00:00:00Z",
        "elevated": True, "ok": True, "error": None,
        "data": [
            {"when": "2026-07-27T17:02:24Z", "kind": "unexpected_shutdown",
             "event_id": 41, "source": "Kernel-Power", "bugcheck_code": None,
             "message": "rebooted without cleanly shutting down",
             "sleep_in_progress": 0, "power_button": 0},
            {"when": "2026-07-27T17:02:30Z", "kind": "dirty_shutdown",
             "event_id": 6008, "source": "EventLog", "bugcheck_code": None,
             "message": "previous shutdown unexpected",
             "actual_when": "2026-07-27T14:21:09Z", "actual_local_hour": 19},
        ],
    }
    from pcdiag.collectors import parse_collector_result
    from pcdiag.normalize import build_timeline
    t = build_timeline({"crashes": parse_collector_result(raw)})
    kp = [c for c in t.crashes if c.event_id == 41][0]
    assert kp.sleep_in_progress == 0 and kp.power_button == 0
    dirty = [c for c in t.crashes if c.event_id == 6008][0]
    assert dirty.actual_local_hour == 19
    assert dirty.actual_when is not None and dirty.actual_when.hour == 14


def test_norm_memory_config_not_overclocked():
    raw = {"collector":"memory_config","collected_at":"2026-07-28T00:00:00Z",
           "elevated":True,"ok":True,"error":None,
           "data":[{"dimm_count":2,"rated_mts":4800,"configured_mts":4800,"part_number":"EXAMPLE"}]}
    from pcdiag.collectors import parse_collector_result
    from pcdiag.normalize import build_timeline
    t = build_timeline({"memory_config": parse_collector_result(raw)})
    assert t.memory_config.dimm_count == 2
    assert t.memory_config.overclocked is False


def test_norm_memory_config_overclocked_when_above_jedec():
    raw = {"collector":"memory_config","collected_at":"2026-07-28T00:00:00Z",
           "elevated":True,"ok":True,"error":None,
           "data":[{"dimm_count":2,"rated_mts":6000,"configured_mts":6000,"part_number":"EXAMPLE"}]}
    from pcdiag.collectors import parse_collector_result
    from pcdiag.normalize import build_timeline
    t = build_timeline({"memory_config": parse_collector_result(raw)})
    assert t.memory_config.overclocked is True


def test_norm_thermal_splits_events_and_temps():
    raw = {"collector":"thermal","collected_at":"2026-07-28T00:00:00Z",
           "elevated":True,"ok":True,"error":None,
           "data":[
             {"type":"event","when":"2026-07-27T17:00:00Z","kind":"throttle","source":"Kernel-Processor-Power","detail":"processor throttled"},
             {"type":"temp","name":"ACPI thermal zone","value":68.0,"unit":"C"}
           ]}
    from pcdiag.collectors import parse_collector_result
    from pcdiag.normalize import build_timeline
    t = build_timeline({"thermal": parse_collector_result(raw)})
    assert len(t.thermal_events) == 1 and t.thermal_events[0].kind == "throttle"
    assert len(t.sensors) == 1 and t.sensors[0].kind == "temp" and t.sensors[0].value == 68.0


def test_norm_sensors():
    raw = {"collector":"sensors","collected_at":"2026-07-28T00:00:00Z",
           "elevated":True,"ok":True,"error":None,
           "data":[{"name":"+12V","kind":"voltage","value":11.6,"unit":"V","min":11.4,"max":12.1}]}
    from pcdiag.collectors import parse_collector_result
    from pcdiag.normalize import build_timeline
    t = build_timeline({"sensors": parse_collector_result(raw)})
    assert t.sensors[0].name == "+12V" and t.sensors[0].min == 11.4
