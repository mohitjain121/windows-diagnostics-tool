from __future__ import annotations

from datetime import datetime, timezone

from pcdiag.collectors import CollectorResult
from pcdiag.models import (
    ChangeEntry,
    CollectorMeta,
    CrashEvent,
    Disk,
    DisplayResetEvent,
    Driver,
    MemoryDiagResult,
    MinidumpFile,
    SystemSnapshot,
    Timeline,
    WheaError,
)


def _iso(value) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _norm_system_snapshot(result: CollectorResult, timeline: Timeline) -> None:
    if not result.data:
        return
    row = result.data[0]
    timeline.snapshot = SystemSnapshot(
        cpu_name=row.get("cpu_name", ""),
        gpu_names=list(row.get("gpu_names") or []),
        ram_total_gb=float(row.get("ram_total_gb") or 0.0),
        os_caption=row.get("os_caption", ""),
        os_build=str(row.get("os_build", "")),
        uptime_hours=float(row.get("uptime_hours") or 0.0),
        cpu_load_pct=row.get("cpu_load_pct"),
        mem_used_pct=row.get("mem_used_pct"),
        system_disk_free_pct=row.get("system_disk_free_pct"),
    )


def _norm_crashes(result: CollectorResult, timeline: Timeline) -> None:
    for row in result.data:
        when = _iso(row.get("when"))
        if when is None:
            continue
        hour = row.get("actual_local_hour")
        timeline.crashes.append(CrashEvent(
            when=when,
            kind=row.get("kind", "unknown"),
            event_id=int(row.get("event_id") or 0),
            source=row.get("source", ""),
            bugcheck_code=row.get("bugcheck_code"),
            message=row.get("message", ""),
            actual_when=_iso(row.get("actual_when")),
            actual_local_hour=int(hour) if hour is not None else None,
            sleep_in_progress=row.get("sleep_in_progress"),
            power_button=row.get("power_button"),
        ))


def _norm_livekernel_display(result: CollectorResult, timeline: Timeline) -> None:
    for row in result.data:
        when = _iso(row.get("when"))
        if when is None:
            continue
        timeline.display_resets.append(DisplayResetEvent(
            when=when,
            device=row.get("device", ""),
            event_id=int(row.get("event_id") or 0),
        ))


def _norm_drivers(result: CollectorResult, timeline: Timeline) -> None:
    for row in result.data:
        timeline.drivers.append(Driver(
            name=row.get("name", ""),
            version=str(row.get("version", "")),
            provider=row.get("provider", ""),
            install_date=_iso(row.get("install_date")),
            device_class=row.get("device_class", ""),
        ))


def _norm_changes(result: CollectorResult, timeline: Timeline) -> None:
    for row in result.data:
        when = _iso(row.get("when"))
        if when is None:
            continue
        timeline.changes.append(ChangeEntry(
            when=when,
            change_type=row.get("change_type", "install"),
            name=row.get("name", ""),
            version=row.get("version"),
            source=row.get("source", ""),
        ))


def _norm_whea(result: CollectorResult, timeline: Timeline) -> None:
    for row in result.data:
        when = _iso(row.get("when"))
        if when is None:
            continue
        timeline.whea_errors.append(WheaError(
            when=when,
            severity=row.get("severity", ""),
            error_source=row.get("error_source", ""),
            event_id=int(row.get("event_id") or 0),
        ))


def _norm_storage_smart(result: CollectorResult, timeline: Timeline) -> None:
    for row in result.data:
        timeline.disks.append(Disk(
            model=row.get("model", ""),
            wear_pct=row.get("wear_pct"),
            reallocated_sectors=row.get("reallocated_sectors"),
            read_errors=row.get("read_errors"),
            write_errors=row.get("write_errors"),
            temperature_c=row.get("temperature_c"),
            predictive_failure=bool(row.get("predictive_failure", False)),
        ))


def _norm_minidump(result: CollectorResult, timeline: Timeline) -> None:
    for row in result.data:
        when = _iso(row.get("when"))
        if when is None:
            continue
        timeline.minidumps.append(MinidumpFile(
            when=when,
            filename=row.get("filename", ""),
            bugcheck_code=row.get("bugcheck_code"),
        ))


def _norm_memory_diag(result: CollectorResult, timeline: Timeline) -> None:
    for row in result.data:
        when = _iso(row.get("when"))
        if when is None:
            continue
        timeline.memory_diags.append(MemoryDiagResult(
            when=when,
            result=row.get("result", ""),
        ))


def _norm_updates(result: CollectorResult, timeline: Timeline) -> None:
    for row in result.data:
        when = _iso(row.get("when"))
        if when is None:
            continue
        timeline.changes.append(ChangeEntry(
            when=when,
            change_type="os_update",
            name=row.get("name", ""),
            version=row.get("version"),
            source="updates",
        ))


def _norm_reliability(result: CollectorResult, timeline: Timeline) -> None:
    # Reliability records enrich change context; map failed installs as changes.
    for row in result.data:
        when = _iso(row.get("when"))
        if when is None or row.get("change_type") is None:
            continue
        timeline.changes.append(ChangeEntry(
            when=when,
            change_type=row.get("change_type"),
            name=row.get("name", ""),
            version=row.get("version"),
            source="reliability",
        ))


# name -> normalizer function.
NORMALIZERS = {
    "system_snapshot": _norm_system_snapshot,
    "crashes": _norm_crashes,
    "livekernel_display": _norm_livekernel_display,
    "drivers": _norm_drivers,
    "changes": _norm_changes,
    "whea": _norm_whea,
    "storage_smart": _norm_storage_smart,
    "minidump": _norm_minidump,
    "memory_diag": _norm_memory_diag,
    "updates": _norm_updates,
    "reliability": _norm_reliability,
}


def _dedupe_changes(timeline: Timeline) -> None:
    # Multiple collectors (changes, updates, reliability) can report the same
    # change; collapse duplicates keyed by (minute-precision time, type, name).
    seen: set[tuple] = set()
    unique = []
    for c in sorted(timeline.changes, key=lambda c: c.when, reverse=True):
        key = (c.when.replace(second=0, microsecond=0), c.change_type, c.name)
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)
    timeline.changes = unique


def build_timeline(results: dict[str, CollectorResult]) -> Timeline:
    timeline = Timeline()
    for name, result in results.items():
        timeline.meta.append(
            CollectorMeta(name=name, ok=result.ok,
                          elevated=result.elevated, error=result.error)
        )
        fn = NORMALIZERS.get(name)
        if fn and result.ok:
            fn(result, timeline)
    _dedupe_changes(timeline)
    return timeline
