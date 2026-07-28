from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SystemSnapshot:
    cpu_name: str
    gpu_names: list[str]
    ram_total_gb: float
    os_caption: str
    os_build: str
    uptime_hours: float
    cpu_load_pct: float | None
    mem_used_pct: float | None
    system_disk_free_pct: float | None


@dataclass
class CrashEvent:
    when: datetime
    kind: str
    event_id: int
    source: str
    bugcheck_code: str | None
    message: str
    actual_when: datetime | None = None
    actual_local_hour: int | None = None
    sleep_in_progress: int | None = None
    power_button: int | None = None


@dataclass
class DisplayResetEvent:
    when: datetime
    device: str
    event_id: int


@dataclass
class WheaError:
    when: datetime
    severity: str
    error_source: str
    event_id: int


@dataclass
class Driver:
    name: str
    version: str
    provider: str
    install_date: datetime | None
    device_class: str


@dataclass
class ChangeEntry:
    when: datetime
    change_type: str  # install | update | uninstall | driver | os_update
    name: str
    version: str | None
    source: str


@dataclass
class Disk:
    model: str
    wear_pct: float | None
    reallocated_sectors: int | None
    read_errors: int | None
    write_errors: int | None
    temperature_c: float | None
    predictive_failure: bool


@dataclass
class MemoryDiagResult:
    when: datetime
    result: str


@dataclass
class MinidumpFile:
    when: datetime
    filename: str
    bugcheck_code: str | None


@dataclass
class MemoryConfig:
    dimm_count: int
    rated_mts: int | None
    configured_mts: int | None
    part_number: str
    overclocked: bool | None


@dataclass
class ThermalEvent:
    when: datetime
    kind: str  # throttle | critical
    source: str
    detail: str


@dataclass
class SensorReading:
    name: str
    kind: str  # temp | fan | voltage | clock
    value: float
    unit: str
    min: float | None = None
    max: float | None = None


@dataclass
class CollectorMeta:
    name: str
    ok: bool
    elevated: bool
    error: str | None


@dataclass
class Timeline:
    snapshot: SystemSnapshot | None = None
    crashes: list[CrashEvent] = field(default_factory=list)
    display_resets: list[DisplayResetEvent] = field(default_factory=list)
    whea_errors: list[WheaError] = field(default_factory=list)
    drivers: list[Driver] = field(default_factory=list)
    changes: list[ChangeEntry] = field(default_factory=list)
    disks: list[Disk] = field(default_factory=list)
    memory_diags: list[MemoryDiagResult] = field(default_factory=list)
    minidumps: list[MinidumpFile] = field(default_factory=list)
    meta: list[CollectorMeta] = field(default_factory=list)
    memory_config: MemoryConfig | None = None
    thermal_events: list[ThermalEvent] = field(default_factory=list)
    sensors: list[SensorReading] = field(default_factory=list)
