from datetime import datetime, timezone

from pcdiag.models import (
    CrashEvent, MemoryConfig, SensorReading, ThermalEvent, Timeline,
)


def test_crashevent_new_fields_default_none():
    c = CrashEvent(when=datetime(2026, 7, 27, tzinfo=timezone.utc),
                   kind="unexpected_shutdown", event_id=41, source="Kernel-Power",
                   bugcheck_code=None, message="x")
    assert c.actual_when is None
    assert c.actual_local_hour is None
    assert c.sleep_in_progress is None
    assert c.power_button is None


def test_timeline_new_collections_default_empty():
    t = Timeline()
    assert t.memory_config is None
    assert t.thermal_events == []
    assert t.sensors == []


def test_new_dataclasses_construct():
    mc = MemoryConfig(dimm_count=2, rated_mts=4800, configured_mts=4800,
                      part_number="EXAMPLE-KIT", overclocked=False)
    te = ThermalEvent(when=datetime(2026, 7, 27, tzinfo=timezone.utc),
                      kind="throttle", source="Kernel-Processor-Power", detail="x")
    sr = SensorReading(name="+12V", kind="voltage", value=11.6, unit="V")
    assert mc.overclocked is False and te.kind == "throttle" and sr.min is None
