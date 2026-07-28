# Root-Cause Diagnosis + Tiered Action Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic synthesis layer that turns collected signals into a Primary Diagnosis (root cause, timing, ruled-out reasoning, Tier 1/2/3 action plan) rendered at the top of the report, plus the new collectors that feed it.

**Architecture:** Keep the existing pipeline (collectors → normalize → Timeline → rules → report). Add (1) new baseline collectors (`memory_config`, `thermal`, expanded `crashes`) plus an opt-in `sensors` collector, (2) a `pcdiag/synthesize.py` layer that runs after rules and emits ranked `Diagnosis` objects, and (3) report/template rendering for the diagnoses. Scoring, existing rules, and findings are untouched; all changes are additive and backward-compatible.

**Tech Stack:** Python 3.11+ (dataclasses, Jinja2), PowerShell 5.1 collectors emitting JSON, pytest. Opt-in sensor backend via LibreHardwareMonitorLib (.NET DLL) loaded through PowerShell `Add-Type`.

## Global Constraints

- **Deterministic only** — no LLM, no network calls; same inputs → same report.
- **On-demand, read-only** — the tool observes; it never changes configuration.
- **Zero-dependency baseline** — `python diagnose.py` with no flags loads no kernel driver and adds no runtime dependency beyond today's.
- **Public GitHub repo — nothing personal** — no hardcoded machine specs, owner identity, or real captured telemetry in source, tests, or fixtures. Hardware-specific steps are driven by vendor detection (AMD/NVIDIA/Intel), never a hardcoded model. All fixtures are synthetic and anonymized.
- **`Diagnosis`/`ActionStep` live in `pcdiag/synthesize.py`**, not `models.py`, because they reference the `Severity`/`Confidence` enums defined in `pcdiag/rules.py` (putting them in `models.py` would create a circular import: `rules` → `models` → `rules`).
- Direct PSU telemetry is out of scope; rail-voltage (12V sag) is the PSU proxy and only under `--sensors`.
- Follow existing collector JSON shape exactly: `{collector, collected_at, elevated, ok, error, data:[...]}` with UTC ISO timestamps `yyyy-MM-ddTHH:mm:ssZ`.

---

### Task 1: Data model additions

**Files:**
- Modify: `pcdiag/models.py` (add fields to `CrashEvent`, add `MemoryConfig`, `ThermalEvent`, `SensorReading`, add fields to `Timeline`)
- Test: `tests/test_models.py` (create)

**Interfaces:**
- Produces: `MemoryConfig(dimm_count:int, rated_mts:int|None, configured_mts:int|None, part_number:str, overclocked:bool|None)`; `ThermalEvent(when:datetime, kind:str, source:str, detail:str)`; `SensorReading(name:str, kind:str, value:float, unit:str, min:float|None=None, max:float|None=None)`. `CrashEvent` gains `actual_when:datetime|None=None, actual_local_hour:int|None=None, sleep_in_progress:int|None=None, power_button:int|None=None`. `Timeline` gains `memory_config:MemoryConfig|None=None, thermal_events:list[ThermalEvent]`, `sensors:list[SensorReading]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL with `ImportError` / `TypeError` (new names/fields not defined).

- [ ] **Step 3: Add the fields and dataclasses**

In `pcdiag/models.py`, add the four optional fields to the end of `CrashEvent`:

```python
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
```

Add three new dataclasses (place after `MinidumpFile`):

```python
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
```

Add three fields to `Timeline` (alongside the existing `field(default_factory=list)` members):

```python
    memory_config: "MemoryConfig | None" = None
    thermal_events: list["ThermalEvent"] = field(default_factory=list)
    sensors: list["SensorReading"] = field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add pcdiag/models.py tests/test_models.py
git commit -m "feat: add diagnosis-supporting fields to data model"
```

---

### Task 2: Expand crashes collector + normalizer (real crash times, sleep/power flags)

**Files:**
- Modify: `collectors/crashes.ps1` (add Event 41 XML props + Event 6008 real crash time/local hour)
- Modify: `pcdiag/normalize.py:51-63` (`_norm_crashes`)
- Create: `tests/fixtures/scenario_power_loss/crashes.json` (synthetic)
- Test: `tests/test_normalize.py` (extend)

**Interfaces:**
- Consumes: `CrashEvent` optional fields from Task 1.
- Produces: `crashes.json` rows may carry `actual_when` (UTC ISO), `actual_local_hour` (0–23 int), `sleep_in_progress` (int), `power_button` (int). `_norm_crashes` maps them onto `CrashEvent`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_normalize.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_normalize.py::test_norm_crashes_reads_actual_time_and_flags -v`
Expected: FAIL (`actual_local_hour`/`sleep_in_progress` are `None`).

- [ ] **Step 3: Update `_norm_crashes`**

Replace `pcdiag/normalize.py:51-63` with:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_normalize.py -v`
Expected: PASS (all normalize tests).

- [ ] **Step 5: Update the collector script**

Replace `collectors/crashes.ps1` body (the `try {...}` block) with logic that reads Event 41 EventData and Event 6008 inserted strings:

```powershell
try {
  $since = (Get-Date).AddDays(-30)
  $rows = @()
  $filter = @{ LogName='System'; Id=@(41,1001,6008); StartTime=$since }
  $events = Get-WinEvent -FilterHashtable $filter -ErrorAction SilentlyContinue
  foreach ($e in $events) {
    $kind = switch ($e.Id) { 41 {'unexpected_shutdown'} 1001 {'bugcheck'} 6008 {'dirty_shutdown'} default {'unknown'} }
    $row = [ordered]@{
      when = $e.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
      kind = $kind; event_id = $e.Id
      source = $e.ProviderName; bugcheck_code = $null
      message = ($e.Message -split "`n")[0].Trim()
    }
    if ($e.Id -eq 1001) {
      $m = [regex]::Match($e.Message, '0x[0-9A-Fa-f]{8}')
      if ($m.Success) { $row.bugcheck_code = '0x' + [Convert]::ToInt32($m.Value,16).ToString('x') }
    }
    if ($e.Id -eq 41) {
      try {
        $x = [xml]$e.ToXml(); $d = @{}
        foreach ($p in $x.Event.EventData.Data) { $d[$p.Name] = $p.'#text' }
        if ($d.ContainsKey('SleepInProgress')) { $row.sleep_in_progress = [int]$d['SleepInProgress'] }
        if ($d.ContainsKey('PowerButtonTimestamp')) { $row.power_button = [int64]$d['PowerButtonTimestamp'] }
      } catch {}
    }
    if ($e.Id -eq 6008) {
      # Properties[0]=time string, [1]=date string (localized); combine via Get-Date.
      try {
        $ts = $e.Properties[0].Value; $ds = $e.Properties[1].Value
        $actual = Get-Date ("$ds $ts")
        $row.actual_when = $actual.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        $row.actual_local_hour = $actual.Hour
      } catch {}
    }
    $rows += $row
  }
  $out.data = @($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
```

(Leave the header/`$out`/footer of the script unchanged.)

- [ ] **Step 6: Create the synthetic fixture** (used by later tasks)

```json
// tests/fixtures/scenario_power_loss/crashes.json
{
  "collector": "crashes",
  "collected_at": "2026-07-28T00:00:00Z",
  "elevated": true, "ok": true, "error": null,
  "data": [
    {"when":"2026-07-13T15:00:00Z","kind":"dirty_shutdown","event_id":6008,"source":"EventLog","bugcheck_code":null,"message":"unexpected","actual_when":"2026-07-13T15:00:00Z","actual_local_hour":20},
    {"when":"2026-07-13T15:00:05Z","kind":"unexpected_shutdown","event_id":41,"source":"Kernel-Power","bugcheck_code":null,"message":"rebooted","sleep_in_progress":0,"power_button":0},
    {"when":"2026-07-15T14:30:00Z","kind":"dirty_shutdown","event_id":6008,"source":"EventLog","bugcheck_code":null,"message":"unexpected","actual_when":"2026-07-15T14:30:00Z","actual_local_hour":21},
    {"when":"2026-07-15T14:30:05Z","kind":"unexpected_shutdown","event_id":41,"source":"Kernel-Power","bugcheck_code":null,"message":"rebooted","sleep_in_progress":0,"power_button":0},
    {"when":"2026-07-20T18:00:00Z","kind":"dirty_shutdown","event_id":6008,"source":"EventLog","bugcheck_code":null,"message":"unexpected","actual_when":"2026-07-20T18:00:00Z","actual_local_hour":23},
    {"when":"2026-07-20T18:00:05Z","kind":"unexpected_shutdown","event_id":41,"source":"Kernel-Power","bugcheck_code":null,"message":"rebooted","sleep_in_progress":0,"power_button":0},
    {"when":"2026-07-27T17:02:00Z","kind":"dirty_shutdown","event_id":6008,"source":"EventLog","bugcheck_code":null,"message":"unexpected","actual_when":"2026-07-27T17:02:00Z","actual_local_hour":19},
    {"when":"2026-07-27T17:02:05Z","kind":"unexpected_shutdown","event_id":41,"source":"Kernel-Power","bugcheck_code":null,"message":"rebooted","sleep_in_progress":0,"power_button":0}
  ]
}
```

- [ ] **Step 7: Commit**

```bash
git add collectors/crashes.ps1 pcdiag/normalize.py tests/test_normalize.py tests/fixtures/scenario_power_loss/crashes.json
git commit -m "feat: collect real crash times and Event 41 sleep/power flags"
```

---

### Task 3: Memory-config collector + normalizer

**Files:**
- Create: `collectors/memory_config.ps1`
- Modify: `pcdiag/normalize.py` (add `_norm_memory_config`, register in `NORMALIZERS`)
- Create: `tests/fixtures/scenario_power_loss/memory_config.json`
- Test: `tests/test_normalize.py` (extend)

**Interfaces:**
- Consumes: `MemoryConfig` from Task 1.
- Produces: `memory_config.json` single-row `data` with keys `dimm_count`, `rated_mts`, `configured_mts`, `part_number`. `_norm_memory_config` computes `overclocked = configured_mts > 5600` and sets `timeline.memory_config`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_normalize.py::test_norm_memory_config_not_overclocked -v`
Expected: FAIL (`_norm_memory_config` not registered; `memory_config` is `None`).

- [ ] **Step 3: Add the normalizer and register it**

Add to `pcdiag/normalize.py` (import `MemoryConfig` in the models import block), then:

```python
def _norm_memory_config(result: CollectorResult, timeline: Timeline) -> None:
    if not result.data:
        return
    row = result.data[0]
    configured = row.get("configured_mts")
    overclocked = None
    if configured is not None:
        overclocked = int(configured) > 5600  # DDR5 JEDEC ceiling
    timeline.memory_config = MemoryConfig(
        dimm_count=int(row.get("dimm_count") or 0),
        rated_mts=row.get("rated_mts"),
        configured_mts=configured,
        part_number=row.get("part_number", ""),
        overclocked=overclocked,
    )
```

Add `"memory_config": _norm_memory_config,` to the `NORMALIZERS` dict.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_normalize.py -v`
Expected: PASS.

- [ ] **Step 5: Create the collector script**

```powershell
# collectors/memory_config.ps1
$ErrorActionPreference = 'Stop'
function Test-Elevated { $id=[Security.Principal.WindowsIdentity]::GetCurrent();
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
$out=[ordered]@{collector='memory_config';collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ');elevated=Test-Elevated;ok=$true;error=$null;data=@()}
try {
  $dimms = @(Get-CimInstance Win32_PhysicalMemory -ErrorAction SilentlyContinue)
  if ($dimms.Count -gt 0) {
    $rated = ($dimms | Measure-Object -Property Speed -Maximum).Maximum
    $configured = ($dimms | Measure-Object -Property ConfiguredClockSpeed -Maximum).Maximum
    $part = ($dimms[0].PartNumber | ForEach-Object { $_.Trim() })
    $out.data = @([ordered]@{
      dimm_count = $dimms.Count
      rated_mts = [int]$rated
      configured_mts = [int]$configured
      part_number = "$part"
    })
  }
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
```

- [ ] **Step 6: Create the synthetic fixture**

```json
// tests/fixtures/scenario_power_loss/memory_config.json
{"collector":"memory_config","collected_at":"2026-07-28T00:00:00Z","elevated":true,"ok":true,"error":null,
 "data":[{"dimm_count":2,"rated_mts":4800,"configured_mts":4800,"part_number":"EXAMPLE-KIT"}]}
```

- [ ] **Step 7: Commit**

```bash
git add collectors/memory_config.ps1 pcdiag/normalize.py tests/test_normalize.py tests/fixtures/scenario_power_loss/memory_config.json
git commit -m "feat: add memory-config collector (rated vs configured speed)"
```

---

### Task 4: Thermal collector + normalizer

**Files:**
- Create: `collectors/thermal.ps1`
- Modify: `pcdiag/normalize.py` (add `_norm_thermal`, register)
- Create: `tests/fixtures/scenario_thermal/thermal.json`
- Test: `tests/test_normalize.py` (extend)

**Interfaces:**
- Consumes: `ThermalEvent`, `SensorReading` from Task 1.
- Produces: `thermal.json` rows each tagged `"type": "event"` or `"type": "temp"`. `event` rows → `timeline.thermal_events` (`kind`, `source`, `detail`, `when`); `temp` rows → `timeline.sensors` as `SensorReading(kind="temp")`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_normalize.py::test_norm_thermal_splits_events_and_temps -v`
Expected: FAIL (`thermal_events`/`sensors` empty).

- [ ] **Step 3: Add the normalizer and register it**

Add to `pcdiag/normalize.py` (import `ThermalEvent`, `SensorReading`):

```python
def _norm_thermal(result: CollectorResult, timeline: Timeline) -> None:
    for row in result.data:
        if row.get("type") == "temp":
            timeline.sensors.append(SensorReading(
                name=row.get("name", "thermal zone"), kind="temp",
                value=float(row.get("value") or 0.0), unit=row.get("unit", "C")))
        elif row.get("type") == "event":
            when = _iso(row.get("when"))
            if when is None:
                continue
            timeline.thermal_events.append(ThermalEvent(
                when=when, kind=row.get("kind", "throttle"),
                source=row.get("source", ""), detail=row.get("detail", "")))
```

Add `"thermal": _norm_thermal,` to `NORMALIZERS`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_normalize.py -v`
Expected: PASS.

- [ ] **Step 5: Create the collector script**

```powershell
# collectors/thermal.ps1
$ErrorActionPreference = 'Stop'
function Test-Elevated { $id=[Security.Principal.WindowsIdentity]::GetCurrent();
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
$out=[ordered]@{collector='thermal';collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ');elevated=Test-Elevated;ok=$true;error=$null;data=@()}
try {
  $rows=@()
  $since=(Get-Date).AddDays(-30)
  $ev = Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Microsoft-Windows-Kernel-Processor-Power';StartTime=$since} -ErrorAction SilentlyContinue |
        Where-Object { $_.Id -in 86,87,88 }
  foreach ($e in $ev) {
    $rows += [ordered]@{ type='event'; when=$e.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ');
                         kind='throttle'; source=$e.ProviderName; detail=(($e.Message -split "`n")[0].Trim()) }
  }
  # Best-effort ACPI zone temperature (deci-Kelvin -> Celsius). Often unavailable.
  try {
    $tz = Get-CimInstance -Namespace root/WMI -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop
    foreach ($z in $tz) {
      $c = [math]::Round(($z.CurrentTemperature / 10.0) - 273.15, 1)
      $rows += [ordered]@{ type='temp'; name='ACPI thermal zone'; value=$c; unit='C' }
    }
  } catch {}
  $out.data=@($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
```

- [ ] **Step 6: Create the synthetic fixture**

```json
// tests/fixtures/scenario_thermal/thermal.json
{"collector":"thermal","collected_at":"2026-07-28T00:00:00Z","elevated":true,"ok":true,"error":null,
 "data":[
   {"type":"event","when":"2026-07-27T16:00:00Z","kind":"throttle","source":"Kernel-Processor-Power","detail":"processor throttled due to thermal"},
   {"type":"event","when":"2026-07-27T16:05:00Z","kind":"throttle","source":"Kernel-Processor-Power","detail":"processor throttled due to thermal"}
 ]}
```

- [ ] **Step 7: Commit**

```bash
git add collectors/thermal.ps1 pcdiag/normalize.py tests/test_normalize.py tests/fixtures/scenario_thermal/thermal.json
git commit -m "feat: add thermal collector (throttle events + best-effort zone temp)"
```

---

### Task 5: Synthesis scaffolding — Diagnosis/ActionStep, registry, ranking, load-hours helper

**Files:**
- Create: `pcdiag/synthesize.py`
- Test: `tests/test_synthesize.py` (create)

**Interfaces:**
- Consumes: `Timeline`, `Finding` (from `pcdiag.rules`), `Config`, `Severity`, `Confidence`.
- Produces: `ActionStep`, `Diagnosis` dataclasses; `run_synthesis(timeline, findings, config) -> list[Diagnosis]` (sorted by `severity.weight * confidence.multiplier`, descending); `_load_hours_fraction(hours: list[int]) -> float`; module-level `SYNTHESIZERS: list[Callable[[Timeline, list[Finding], Config], Diagnosis | None]]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_synthesize.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_synthesize.py -v`
Expected: FAIL (`ModuleNotFoundError: pcdiag.synthesize`).

- [ ] **Step 3: Create the scaffolding**

```python
# pcdiag/synthesize.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from pcdiag.config import Config
from pcdiag.models import Timeline
from pcdiag.rules import Confidence, Finding, Severity


@dataclass
class ActionStep:
    tier: int
    title: str
    detail: str
    effort: str
    rationale: str


@dataclass
class Diagnosis:
    id: str
    title: str
    root_cause: str
    confidence: Confidence
    severity: Severity
    whats_happening: str
    timing: str | None = None
    ruled_out: list[str] = field(default_factory=list)
    action_plan: list[ActionStep] = field(default_factory=list)
    supporting_finding_ids: list[str] = field(default_factory=list)


def _load_hours_fraction(hours: list[int]) -> float:
    """Fraction of crash hours falling in evening (17-22) or night (22-6)."""
    if not hours:
        return 0.0
    load = sum(1 for h in hours if h >= 17 or h < 6)
    return load / len(hours)


# Registered synthesizers are added by later tasks.
SYNTHESIZERS: list[Callable[[Timeline, list[Finding], Config], "Diagnosis | None"]] = []


def run_synthesis(timeline: Timeline, findings: list[Finding],
                  config: Config) -> list[Diagnosis]:
    out: list[Diagnosis] = []
    for synth in SYNTHESIZERS:
        result = synth(timeline, findings, config)
        if result is not None:
            out.append(result)
    out.sort(key=lambda d: d.severity.weight * d.confidence.multiplier, reverse=True)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_synthesize.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add pcdiag/synthesize.py tests/test_synthesize.py
git commit -m "feat: add synthesis scaffolding (Diagnosis, registry, ranking)"
```

---

### Task 6: Power-loss synthesizer

**Files:**
- Modify: `pcdiag/synthesize.py` (add `_synthesize_power_loss`, GPU/tuning detection, action plan; register)
- Modify: `tests/fixtures/scenario_power_loss/` — add `system_snapshot.json`, `changes.json`
- Test: `tests/test_synthesize.py` (extend)

**Interfaces:**
- Consumes: `unexpected_shutdowns` finding (id) from `pcdiag.rules`; `timeline.crashes[].actual_local_hour`, `timeline.memory_config`, `timeline.snapshot.gpu_names`, `timeline.changes`.
- Produces: a `Diagnosis(id="power_loss", severity=CRITICAL)` when the instant-power-loss signature holds; `None` otherwise.

- [ ] **Step 1: Write the failing test**

```python
def test_power_loss_diagnosis_full(  # uses scenario_power_loss fixtures
):
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
    from pcdiag.models import CrashEvent, Timeline
    from pcdiag.rules import Confidence, Evidence, Finding, Severity
    t = Timeline()
    t.crashes.append(CrashEvent(when=datetime(2026,7,27,tzinfo=timezone.utc),
        kind="bugcheck", event_id=1001, source="WER", bugcheck_code="0x9f", message="x"))
    finding = Finding(id="unexpected_shutdowns", title="x", category="stability",
        severity=Severity.CRITICAL, confidence=Confidence.HIGH,
        evidence=[Evidence(label="l", detail="d")], recommendation="r")
    from pcdiag.synthesize import _synthesize_power_loss
    assert _synthesize_power_loss(t, [finding], cfg()) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_synthesize.py::test_power_loss_absent_when_bugcheck_present -v`
Expected: FAIL (`_synthesize_power_loss` not defined).

- [ ] **Step 3: Add GPU/tuning detection helpers, the action plan, and the synthesizer**

Append to `pcdiag/synthesize.py`:

```python
_DISCRETE_GPU = ("radeon rx", "radeon pro", "geforce", "rtx", "gtx", "arc a")
_INTEGRATED_GPU = ("radeon graphics", "radeon(tm) graphics", "uhd graphics",
                   "iris", "hd graphics", "vega")
_TUNING_TOOLS = ("ryzen master", "afterburner", "overclock", "tuning",
                 "precision boost", "wattman")

_MEM_BUGCHECKS = ("0x1a", "0x50", "0x4e", "0x1e")


def _has_discrete_gpu(timeline: Timeline) -> bool:
    if not timeline.snapshot:
        return False
    names = " ".join(timeline.snapshot.gpu_names).lower()
    return any(k in names for k in _DISCRETE_GPU)


def _has_integrated_gpu(timeline: Timeline) -> bool:
    if not timeline.snapshot:
        return False
    names = " ".join(timeline.snapshot.gpu_names).lower()
    return any(k in names for k in _INTEGRATED_GPU)


def _tuning_change(timeline: Timeline):
    for c in timeline.changes:
        if any(k in c.name.lower() for k in _TUNING_TOOLS):
            return c
    return None


def _power_loss_action_plan(timeline: Timeline) -> list[ActionStep]:
    steps: list[ActionStep] = []
    has_dgpu = _has_discrete_gpu(timeline)
    if has_dgpu:
        steps.append(ActionStep(
            tier=1, title="Reset GPU tuning to default", effort="free",
            detail="In your GPU control panel (AMD Adrenalin / NVIDIA app / "
                   "MSI Afterburner), clear any undervolt or overclock profile.",
            rationale="An unstable GPU undervolt/overclock surfaces as an instant "
                      "crash under load with no bugcheck."))
    tuning = _tuning_change(timeline)
    if tuning is not None:
        steps.append(ActionStep(
            tier=1, title="Uninstall the CPU/GPU tuning utility", effort="free",
            detail=f"Remove '{tuning.name}'; it can apply background tuning profiles.",
            rationale="Its install correlates with the onset of the crash cluster."))
    if has_dgpu:
        steps.append(ActionStep(
            tier=1, title="Clean-reinstall the GPU driver", effort="free",
            detail="Use DDU in safe mode, then install the latest stable driver.",
            rationale="Rules out a corrupt driver state without changing hardware."))
    steps.append(ActionStep(
        tier=1, title="Update motherboard firmware (BIOS/AGESA)", effort="free",
        detail="Flash the newest stable BIOS for your board.",
        rationale="Platform/AGESA updates frequently fix load-stability faults."))
    steps.append(ActionStep(
        tier=2, title="Reseat and re-cable power", effort="10 min",
        detail="Reseat the 24-pin, CPU EPS, and GPU power. Run the GPU on TWO "
               "separate PCIe cables, not one daisy-chained cable.",
        rationale="Transient spikes on a shared/daisy-chained cable trip the PSU's "
                  "over-current protection, cutting power instantly."))
    steps.append(ActionStep(
        tier=2, title="Check the PSU against the load", effort="10 min",
        detail="Note the PSU make, wattage, and age; a quality unit sized for the "
               "GPU + CPU is required.",
        rationale="A marginal or aging PSU trips protection under transient load."))
    steps.append(ActionStep(
        tier=3, title="Cap GPU power and retest", effort="isolation",
        detail="Lower the GPU power limit ~15-20% or set a frame cap; run as usual.",
        rationale="If the crashes stop, power delivery / GPU transients are confirmed."))
    if _has_integrated_gpu(timeline):
        steps.append(ActionStep(
            tier=3, title="Run on integrated graphics", effort="isolation",
            detail="Remove the discrete GPU and run on the CPU's integrated "
                   "graphics for a day.",
            rationale="Crashes vanishing points to the GPU or its power; crashes "
                      "continuing points to PSU/board/CPU."))
    steps.append(ActionStep(
        tier=3, title="Reproduce with a stress test", effort="isolation",
        detail="Run OCCT's Power test to trigger the fault on demand.",
        rationale="Turns an intermittent crash into a repeatable one for isolation."))
    return steps


def _synthesize_power_loss(timeline: Timeline, findings: list[Finding],
                           config: Config) -> "Diagnosis | None":
    if not any(f.id == "unexpected_shutdowns" for f in findings):
        return None
    if any(c.bugcheck_code for c in timeline.crashes) or timeline.minidumps:
        return None
    kp41 = [c for c in timeline.crashes if c.event_id == 41]
    n = len(kp41)
    hours = [c.actual_local_hour for c in timeline.crashes
             if c.actual_local_hour is not None]
    timing = None
    if hours and _load_hours_fraction(hours) >= 0.6:
        timing = ("Crashes cluster in evening/late-night hours — typically active "
                  "or GPU-load time — not at boot or idle.")
    ruled = ["Software BSOD / bad driver — no bugcheck code or crash dump on any event"]
    if not timeline.whea_errors:
        ruled.append("CPU/PCIe hardware faults — no WHEA machine-check errors logged")
    if not timeline.display_resets:
        ruled.append("GPU driver timeout (TDR) — no display-reset events")
    mem_bugchecks = [c for c in timeline.crashes if c.bugcheck_code in _MEM_BUGCHECKS]
    failed_diag = [m for m in timeline.memory_diags
                   if "no errors" not in m.result.lower()]
    if not mem_bugchecks and not failed_diag:
        line = "RAM errors — no memory bugchecks or diagnostic failures"
        mc = timeline.memory_config
        if mc and mc.overclocked is False:
            line += " (memory at rated speed, not overclocked)"
        ruled.append(line)
    if not any((c.sleep_in_progress or 0) for c in timeline.crashes):
        ruled.append("Sleep/resume — no crashes during sleep transitions")
    conf = Confidence.HIGH if (n >= 4 and not timeline.whea_errors) else Confidence.MEDIUM
    return Diagnosis(
        id="power_loss",
        title="Instant power loss / hard-hang under load",
        root_cause="Likely PSU / power-delivery or a GPU transient power spike.",
        confidence=conf, severity=Severity.CRITICAL,
        whats_happening=(f"{n} unexpected shutdowns (Kernel-Power 41) with no bugcheck "
                         "and no crash dump — the system cut out instantly rather than "
                         "hitting a software BSOD."),
        timing=timing, ruled_out=ruled,
        action_plan=_power_loss_action_plan(timeline),
        supporting_finding_ids=[f.id for f in findings
                                if f.id in ("unexpected_shutdowns", "change_vs_symptom")])


SYNTHESIZERS.append(_synthesize_power_loss)
```

- [ ] **Step 4: Create the supporting fixtures**

```json
// tests/fixtures/scenario_power_loss/system_snapshot.json
{"collector":"system_snapshot","collected_at":"2026-07-28T00:00:00Z","elevated":true,"ok":true,"error":null,
 "data":[{"cpu_name":"Example CPU 8-Core","gpu_names":["Example Radeon Graphics","Example Radeon RX 0000"],
          "ram_total_gb":32.0,"os_caption":"Windows","os_build":"00000","uptime_hours":1.0,
          "cpu_load_pct":5.0,"mem_used_pct":30.0,"system_disk_free_pct":50.0}]}
```

```json
// tests/fixtures/scenario_power_loss/changes.json
{"collector":"changes","collected_at":"2026-07-28T00:00:00Z","elevated":true,"ok":true,"error":null,
 "data":[{"when":"2026-07-25T12:00:00Z","change_type":"install","name":"Example Tuning Utility","version":"1.0","source":"msi"}]}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_synthesize.py -v`
Expected: PASS (power-loss full + bugcheck-absent + scaffolding tests).

- [ ] **Step 6: Commit**

```bash
git add pcdiag/synthesize.py tests/test_synthesize.py tests/fixtures/scenario_power_loss/system_snapshot.json tests/fixtures/scenario_power_loss/changes.json
git commit -m "feat: power-loss synthesizer with tiered action plan"
```

---

### Task 7: Software-BSOD synthesizer

**Files:**
- Modify: `pcdiag/synthesize.py` (add bugcheck family map, `_synthesize_software_bsod`; register)
- Create: `tests/fixtures/scenario_software_bsod/crashes.json`, `minidump.json`, `changes.json`
- Test: `tests/test_synthesize.py` (extend)

**Interfaces:**
- Consumes: `timeline.crashes[].bugcheck_code`, `timeline.minidumps`, `timeline.changes` (via `correlate.most_recent_change_before`).
- Produces: `Diagnosis(id="software_bsod", severity=CRITICAL)` when a bugcheck/dump exists; `None` otherwise.

- [ ] **Step 1: Write the failing test**

```python
def test_software_bsod_classifies_and_correlates():
    import json
    from pathlib import Path
    from pcdiag.collectors import parse_collector_result
    from pcdiag.normalize import build_timeline
    from pcdiag.rules import run_rules

    fx = Path(__file__).parent / "fixtures" / "scenario_software_bsod"
    results = {n: parse_collector_result(json.loads((fx / f"{n}.json").read_text("utf-8")))
               for n in ("crashes", "minidump", "changes")}
    timeline = build_timeline(results)
    diagnoses = run_synthesis(timeline, run_rules(timeline, cfg()), cfg())

    bsod = [d for d in diagnoses if d.id == "software_bsod"]
    assert bsod, "expected a software_bsod diagnosis"
    assert "DRIVER_POWER_STATE_FAILURE" in bsod[0].root_cause
    assert any(s.tier == 1 for s in bsod[0].action_plan)


def test_software_bsod_absent_without_bugcheck_or_dump():
    from pcdiag.synthesize import _synthesize_software_bsod
    from pcdiag.models import Timeline
    assert _synthesize_software_bsod(Timeline(), [], cfg()) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_synthesize.py::test_software_bsod_absent_without_bugcheck_or_dump -v`
Expected: FAIL (`_synthesize_software_bsod` not defined).

- [ ] **Step 3: Add the family map and synthesizer**

Append to `pcdiag/synthesize.py` (add `from pcdiag.correlate import most_recent_change_before` to the imports):

```python
# bugcheck code -> (name, plain-language cause, family tag)
_BUGCHECK_FAMILIES = {
    "0x9f": ("DRIVER_POWER_STATE_FAILURE", "a driver stalled during a sleep/wake power transition", "driver_power"),
    "0x116": ("VIDEO_TDR_ERROR", "the display driver timed out and could not recover", "gpu"),
    "0x117": ("VIDEO_TDR_TIMEOUT_DETECTED", "the display driver stopped responding", "gpu"),
    "0x1a": ("MEMORY_MANAGEMENT", "a memory-management fault", "memory"),
    "0x50": ("PAGE_FAULT_IN_NONPAGED_AREA", "an invalid memory access (RAM or a driver)", "memory"),
    "0x4e": ("PFN_LIST_CORRUPT", "a corrupted memory page list (often RAM)", "memory"),
    "0x1e": ("KMODE_EXCEPTION_NOT_HANDLED", "an unhandled kernel exception (often a driver)", "driver"),
    "0xd1": ("DRIVER_IRQL_NOT_LESS_OR_EQUAL", "a driver accessed memory at the wrong IRQL", "driver"),
}


def _bsod_action_plan(family: str, suspect) -> list[ActionStep]:
    steps: list[ActionStep] = []
    steps.append(ActionStep(
        tier=1, title="Identify the faulting driver", effort="free",
        detail="Open the crash dump in WinDbg and run `!analyze -v` to see the "
               "module named in the bugcheck.",
        rationale="Names the exact driver instead of guessing."))
    if suspect is not None:
        steps.append(ActionStep(
            tier=1, title="Roll back the recently changed driver", effort="free",
            detail=f"'{suspect.name}' changed just before the crashes; roll it back "
                   "or clean-reinstall the previous stable version.",
            rationale="The change lines up with the onset of the bugchecks."))
    if family == "memory":
        steps.append(ActionStep(
            tier=1, title="Test the RAM", effort="overnight",
            detail="Run MemTest86 for several passes.",
            rationale="Memory bugchecks are frequently bad RAM or an unstable profile."))
        steps.append(ActionStep(
            tier=2, title="Disable the memory overclock", effort="10 min",
            detail="Turn off EXPO/XMP in firmware and retest; then test one stick at a time.",
            rationale="An aggressive memory profile causes memory-family bugchecks."))
    elif family == "gpu":
        steps.append(ActionStep(
            tier=1, title="Clean-reinstall the GPU driver", effort="free",
            detail="Use DDU, then install the latest stable driver.",
            rationale="TDR bugchecks are usually a bad or corrupt display driver."))
    elif family == "driver_power":
        steps.append(ActionStep(
            tier=2, title="Update chipset, GPU, network, and storage drivers", effort="20 min",
            detail="0x9F is a power-transition stall; update the drivers involved in "
                   "sleep/wake (chipset, GPU, NIC, NVMe).",
            rationale="A single lagging driver blocks the power transition."))
    else:
        steps.append(ActionStep(
            tier=2, title="Update or remove the flagged driver", effort="20 min",
            detail="Update the driver named by `!analyze -v`; if recently added, remove it.",
            rationale="Driver-family bugchecks resolve by fixing the named module."))
    return steps


def _synthesize_software_bsod(timeline: Timeline, findings: list[Finding],
                              config: Config) -> "Diagnosis | None":
    coded = [c for c in timeline.crashes if c.bugcheck_code]
    dumps = timeline.minidumps
    if not coded and not dumps:
        return None
    # Most recent bugcheck code from crashes, else from a dump.
    if coded:
        latest = max(coded, key=lambda c: c.when)
        code = (latest.bugcheck_code or "").lower()
        onset = latest.when
    else:
        latest = max(dumps, key=lambda d: d.when)
        code = (latest.bugcheck_code or "").lower()
        onset = latest.when
    name, cause, family = _BUGCHECK_FAMILIES.get(
        code, ("Unexpected bugcheck", "an unclassified kernel fault", "driver"))
    suspect = most_recent_change_before(
        [c for c in timeline.changes if c.change_type in ("driver", "install", "uninstall")],
        onset, config.change_window_days)
    count = len(coded) if coded else len(dumps)
    code_label = code if code else "unknown"
    return Diagnosis(
        id="software_bsod",
        title="Software BSOD (kernel bugcheck)",
        root_cause=f"{name} — {cause}.",
        confidence=Confidence.HIGH if count >= 2 else Confidence.MEDIUM,
        severity=Severity.CRITICAL,
        whats_happening=(f"{count} bugcheck crash(es); the most recent was {code_label} "
                         f"({name}). Windows captured a dump, so this is a software/driver "
                         "fault, not an instant power loss."),
        ruled_out=[], action_plan=_bsod_action_plan(family, suspect),
        supporting_finding_ids=[f.id for f in findings
                                if f.id in ("gpu_driver_instability", "change_vs_symptom",
                                            "memory_errors")])


SYNTHESIZERS.append(_synthesize_software_bsod)
```

- [ ] **Step 4: Create the fixtures**

```json
// tests/fixtures/scenario_software_bsod/crashes.json
{"collector":"crashes","collected_at":"2026-07-28T00:00:00Z","elevated":true,"ok":true,"error":null,
 "data":[
   {"when":"2026-07-20T05:00:00Z","kind":"bugcheck","event_id":1001,"source":"WER","bugcheck_code":"0x9f","message":"bugcheck 0x9f"},
   {"when":"2026-07-26T06:30:00Z","kind":"bugcheck","event_id":1001,"source":"WER","bugcheck_code":"0x9f","message":"bugcheck 0x9f"}
 ]}
```

```json
// tests/fixtures/scenario_software_bsod/minidump.json
{"collector":"minidump","collected_at":"2026-07-28T00:00:00Z","elevated":true,"ok":true,"error":null,
 "data":[{"when":"2026-07-26T06:30:00Z","filename":"072600-00000-01.dmp","bugcheck_code":"0x9f"}]}
```

```json
// tests/fixtures/scenario_software_bsod/changes.json
{"collector":"changes","collected_at":"2026-07-28T00:00:00Z","elevated":true,"ok":true,"error":null,
 "data":[{"when":"2026-07-25T20:00:00Z","change_type":"driver","name":"Example Display Driver","version":"1.2","source":"pnp"}]}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_synthesize.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pcdiag/synthesize.py tests/test_synthesize.py tests/fixtures/scenario_software_bsod/
git commit -m "feat: software-BSOD synthesizer with bugcheck classification"
```

---

### Task 8: Thermal synthesizer

**Files:**
- Modify: `pcdiag/synthesize.py` (add `_synthesize_thermal`; register)
- Test: `tests/test_synthesize.py` (extend, reuse `scenario_thermal/thermal.json`)

**Interfaces:**
- Consumes: `timeline.thermal_events`, `timeline.sensors` (kind=="temp").
- Produces: `Diagnosis(id="thermal")` when throttle/critical events exist or a temp exceeds threshold; `None` otherwise.

- [ ] **Step 1: Write the failing test**

```python
def test_thermal_diagnosis_from_throttle_events():
    import json
    from pathlib import Path
    from pcdiag.collectors import parse_collector_result
    from pcdiag.normalize import build_timeline

    fx = Path(__file__).parent / "fixtures" / "scenario_thermal"
    t = build_timeline({"thermal": parse_collector_result(
        json.loads((fx / "thermal.json").read_text("utf-8")))})
    diagnoses = run_synthesis(t, [], cfg())
    thermal = [d for d in diagnoses if d.id == "thermal"]
    assert thermal, "expected a thermal diagnosis"
    assert any(s.tier == 1 for s in thermal[0].action_plan)


def test_thermal_absent_when_no_signals():
    from pcdiag.synthesize import _synthesize_thermal
    from pcdiag.models import Timeline
    assert _synthesize_thermal(Timeline(), [], cfg()) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_synthesize.py::test_thermal_absent_when_no_signals -v`
Expected: FAIL (`_synthesize_thermal` not defined).

- [ ] **Step 3: Add the synthesizer**

Append to `pcdiag/synthesize.py`:

```python
_CPU_TEMP_LIMIT = 95.0
_GPU_TEMP_LIMIT = 100.0


def _synthesize_thermal(timeline: Timeline, findings: list[Finding],
                        config: Config) -> "Diagnosis | None":
    events = timeline.thermal_events
    hot = [s for s in timeline.sensors
           if s.kind == "temp" and s.value >= _CPU_TEMP_LIMIT]
    critical = [e for e in events if e.kind == "critical"]
    if not events and not hot:
        return None
    n = len(events)
    detail_bits = []
    if n:
        detail_bits.append(f"{n} thermal throttle/critical event(s)")
    if hot:
        detail_bits.append(f"a sensor reached {max(s.value for s in hot):.0f}°C")
    steps = [
        ActionStep(tier=1, title="Clean dust and improve airflow", effort="free",
                   detail="Clear dust from heatsinks/fans and confirm intake/exhaust airflow.",
                   rationale="Blocked airflow is the most common cause of throttling."),
        ActionStep(tier=2, title="Reseat the cooler and repaste", effort="30 min",
                   detail="Remount the CPU cooler with fresh thermal paste.",
                   rationale="Poor cooler contact or dried paste drives temps into throttle."),
        ActionStep(tier=2, title="Set an aggressive fan curve", effort="10 min",
                   detail="Raise the fan curve in firmware or the vendor utility.",
                   rationale="Ramps cooling earlier so the chip does not reach its limit."),
        ActionStep(tier=3, title="Verify VRM/case cooling", effort="isolation",
                   detail="On compact boards, add airflow over the VRM and check case fans.",
                   rationale="VRM overheating can shut the system down under sustained load."),
    ]
    return Diagnosis(
        id="thermal",
        title="Overheating / thermal throttling",
        root_cause="The CPU/GPU is reaching its thermal limit under load.",
        confidence=Confidence.HIGH if (critical or hot) else Confidence.MEDIUM,
        severity=Severity.CRITICAL if critical else Severity.WARNING,
        whats_happening="; ".join(detail_bits) + ".",
        ruled_out=[], action_plan=steps, supporting_finding_ids=[])


SYNTHESIZERS.append(_synthesize_thermal)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_synthesize.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pcdiag/synthesize.py tests/test_synthesize.py
git commit -m "feat: thermal synthesizer"
```

---

### Task 9: Report rendering — diagnoses hero + secondary + sensors table

**Files:**
- Modify: `pcdiag/report.py` (`render_report` signature, `diagnoses_to_dicts`, JSON)
- Modify: `templates/report.html.j2` (hero + secondary cards + sensors table)
- Test: `tests/test_report.py` (extend)

**Interfaces:**
- Consumes: `Diagnosis`, `ActionStep` from `pcdiag.synthesize`.
- Produces: `render_report(findings, timeline, score, out_dir, generated_at, diagnoses=None)`; JSON top-level key `"diagnoses"`.

- [ ] **Step 1: Write the failing test**

```python
def test_render_report_includes_primary_diagnosis(tmp_path):
    import json
    from datetime import datetime, timezone
    from pcdiag.models import Timeline
    from pcdiag.report import render_report
    from pcdiag.rules import Confidence, Severity
    from pcdiag.synthesize import ActionStep, Diagnosis

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
    from datetime import datetime, timezone
    from pcdiag.models import Timeline
    from pcdiag.report import render_report
    html_path, _ = render_report([], Timeline(), 90, tmp_path,
        generated_at=datetime(2026, 7, 28, tzinfo=timezone.utc))
    assert "Primary Diagnosis" not in html_path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report.py -v`
Expected: FAIL (`render_report` has no `diagnoses` param / template lacks the section).

- [ ] **Step 3: Update `report.py`**

Add a serializer and thread `diagnoses` through. Insert `diagnoses_to_dicts` after `findings_to_dicts`:

```python
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
```

Change the `render_report` signature and body:

```python
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
```

- [ ] **Step 4: Update the template**

In `templates/report.html.j2`, add these styles inside the `<style>` block (before `</style>`):

```css
  .hero { border-left: 6px solid #7c3aed; }
  .hero h3 { margin:.2rem 0 .4rem; font-size:1.25rem; }
  .rootcause { font-weight:600; margin:.2rem 0 .5rem; }
  .tier { margin:.5rem 0; }
  .tier h4 { margin:.4rem 0 .2rem; font-size:.95rem; }
  .step { margin:.25rem 0 .25rem .5rem; padding-left:.6rem; border-left:2px solid rgba(124,58,237,.35); }
  .step .why { color:var(--muted); font-size:.85rem; }
  .ruled li { margin:.15rem 0; }
```

Insert the Primary Diagnosis block immediately after the score card `</div>` and before `<h2>Issues ...`:

```html
  {% if diagnoses %}
  {% set primary = diagnoses[0] %}
  <h2>Primary Diagnosis</h2>
  <div class="card hero sev-{{ primary.severity.value }}">
    <span class="badge {{ primary.severity.value }}">{{ primary.severity.value|upper }}</span>
    <span class="badge">{{ primary.confidence.label }} confidence</span>
    <h3>{{ primary.title }}</h3>
    <div class="rootcause">Root cause: {{ primary.root_cause }}</div>
    <div class="evidence">{{ primary.whats_happening }}</div>
    {% if primary.timing %}<div class="evidence"><b>Timing:</b> {{ primary.timing }}</div>{% endif %}
    {% if primary.ruled_out %}
      <div class="rec"><b>Ruled out</b><ul class="ruled">
        {% for r in primary.ruled_out %}<li>{{ r }}</li>{% endfor %}
      </ul></div>
    {% endif %}
    <div class="rec"><b>Action plan</b>
      {% for tier in [1, 2, 3] %}
        {% set steps = primary.action_plan | selectattr('tier', 'equalto', tier) | list %}
        {% if steps %}
        <div class="tier"><h4>Tier {{ tier }}</h4>
          {% for s in steps %}
          <div class="step"><b>{{ s.title }}</b> <span class="muted">({{ s.effort }})</span><br>
            {{ s.detail }}<br><span class="why">Why: {{ s.rationale }}</span></div>
          {% endfor %}
        </div>
        {% endif %}
      {% endfor %}
    </div>
  </div>
  {% if diagnoses|length > 1 %}
  <h2>Other diagnoses</h2>
  {% for d in diagnoses[1:] %}
  <div class="card sev-{{ d.severity.value }}">
    <span class="badge {{ d.severity.value }}">{{ d.severity.value|upper }}</span>
    <span class="badge">{{ d.confidence.label }} confidence</span>
    <strong> {{ d.title }}</strong>
    <div class="rootcause">Root cause: {{ d.root_cause }}</div>
    <div class="evidence">{{ d.whats_happening }}</div>
  </div>
  {% endfor %}
  {% endif %}
  {% endif %}
```

Add a Sensors table before `<h2>Collectors</h2>`:

```html
  {% if sensors %}
  <h2>Sensors <span class="muted">(best-effort)</span></h2>
  <div class="card"><table><tr><th>Sensor</th><th>Type</th><th>Value</th></tr>
    {% for s in sensors %}<tr><td>{{ s.name }}</td><td>{{ s.kind }}</td><td>{{ s.value }} {{ s.unit }}</td></tr>{% endfor %}
  </table></div>
  {% endif %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_report.py -v`
Expected: PASS (existing + 2 new). The existing `test_render_report_writes_html_and_json` still passes because `diagnoses` defaults to `None`.

- [ ] **Step 6: Commit**

```bash
git add pcdiag/report.py templates/report.html.j2 tests/test_report.py
git commit -m "feat: render Primary Diagnosis, secondary diagnoses, sensors table"
```

---

### Task 10: Pipeline + CLI wiring (collectors, synthesis, --sensors)

**Files:**
- Modify: `pcdiag/pipeline.py` (`COLLECTOR_NAMES`, call `run_synthesis`, pass `diagnoses`)
- Modify: `diagnose.py` (`--sensors` flag, optional `sensors` collector, unavailable note)
- Create: `collectors/sensors.ps1` (opt-in, best-effort, graceful skip)
- Modify: `pcdiag/normalize.py` (add `_norm_sensors`, register)
- Test: `tests/test_pipeline.py` (extend), `tests/test_normalize.py` (extend)

**Interfaces:**
- Consumes: `run_synthesis` (Task 5), `render_report(..., diagnoses=...)` (Task 9), `SensorReading` (Task 1).
- Produces: `run_pipeline` returns `(html_path, json_path, score)` unchanged but the report now contains diagnoses. `sensors.json` rows: `{name, kind, value, unit, min?, max?}`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pipeline.py`:

```python
def test_pipeline_emits_diagnoses_for_power_loss(tmp_path):
    import json
    from pathlib import Path
    from datetime import datetime, timezone
    from pcdiag.collectors import parse_collector_result
    from pcdiag.config import Config
    from pcdiag.pipeline import run_pipeline

    fx = Path(__file__).parent / "fixtures" / "scenario_power_loss"
    results = {n: parse_collector_result(json.loads((fx / f"{n}.json").read_text("utf-8")))
               for n in ("crashes", "memory_config", "system_snapshot", "changes")}
    cfg = Config(now=datetime(2026, 7, 28, tzinfo=timezone.utc))
    html_path, json_path, score = run_pipeline(results, tmp_path, cfg)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["diagnoses"], "pipeline should surface a diagnosis"
    assert data["diagnoses"][0]["id"] == "power_loss"
```

Add to `tests/test_normalize.py`:

```python
def test_norm_sensors():
    raw = {"collector":"sensors","collected_at":"2026-07-28T00:00:00Z",
           "elevated":True,"ok":True,"error":None,
           "data":[{"name":"+12V","kind":"voltage","value":11.6,"unit":"V","min":11.4,"max":12.1}]}
    from pcdiag.collectors import parse_collector_result
    from pcdiag.normalize import build_timeline
    t = build_timeline({"sensors": parse_collector_result(raw)})
    assert t.sensors[0].name == "+12V" and t.sensors[0].min == 11.4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pipeline.py::test_pipeline_emits_diagnoses_for_power_loss tests/test_normalize.py::test_norm_sensors -v`
Expected: FAIL (pipeline doesn't call `run_synthesis`; `_norm_sensors` not registered).

- [ ] **Step 3: Wire the pipeline**

In `pcdiag/pipeline.py`: add `"memory_config", "thermal"` to `COLLECTOR_NAMES` (append after `"memory_diag"`), import and call synthesis:

```python
from pcdiag.synthesize import run_synthesis
```

```python
def run_pipeline(results: dict[str, CollectorResult], out_dir: Path,
                 config: Config) -> tuple[Path, Path, int]:
    timeline = build_timeline(results)
    findings = run_rules(timeline, config)
    diagnoses = run_synthesis(timeline, findings, config)
    score = health_score(findings)
    html_path, json_path = render_report(
        findings, timeline, score, out_dir,
        generated_at=config.now, diagnoses=diagnoses)
    return html_path, json_path, score
```

- [ ] **Step 4: Add the sensors normalizer**

In `pcdiag/normalize.py` (import `SensorReading` if not already), add and register:

```python
def _norm_sensors(result: CollectorResult, timeline: Timeline) -> None:
    for row in result.data:
        timeline.sensors.append(SensorReading(
            name=row.get("name", ""), kind=row.get("kind", "temp"),
            value=float(row.get("value") or 0.0), unit=row.get("unit", ""),
            min=row.get("min"), max=row.get("max")))
```

Add `"sensors": _norm_sensors,` to `NORMALIZERS`.

- [ ] **Step 5: Add the `--sensors` flag and opt-in collector**

In `diagnose.py`, add the argument and conditionally append the collector:

```python
    parser.add_argument("--sensors", action="store_true",
                        help="opt-in deep hardware sensors (loads a signed driver; needs admin)")
```

Replace the collection loop to build the name list and note unavailable sensors:

```python
    collector_names = list(COLLECTOR_NAMES)
    if args.sensors:
        collector_names.append("sensors")

    print("Collecting diagnostics (this may take a minute)...")
    results = {}
    for name in collector_names:
        results[name] = run_collector(name)
        status = "ok" if results[name].ok else f"FAILED: {results[name].error}"
        print(f"  - {name}: {status}")

    if args.sensors and results.get("sensors") and not results["sensors"].data:
        print("Note: deep sensors unavailable (LibreHardwareMonitorLib.dll missing); "
              "using baseline signals.")
```

- [ ] **Step 6: Create the opt-in sensors collector**

```powershell
# collectors/sensors.ps1  (opt-in; loads LibreHardwareMonitorLib if present)
$ErrorActionPreference = 'Stop'
function Test-Elevated { $id=[Security.Principal.WindowsIdentity]::GetCurrent();
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
$out=[ordered]@{collector='sensors';collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ');elevated=Test-Elevated;ok=$true;error=$null;data=@()}
try {
  $dll = Join-Path $PSScriptRoot '..\tools\LibreHardwareMonitorLib.dll'
  if (-not (Test-Path $dll)) {
    $out.error = 'LibreHardwareMonitorLib.dll not found; deep sensors skipped'
    $out | ConvertTo-Json -Depth 6 -Compress; return
  }
  Add-Type -Path $dll
  $computer = New-Object LibreHardwareMonitor.Hardware.Computer
  $computer.IsCpuEnabled = $true; $computer.IsGpuEnabled = $true
  $computer.IsMotherboardEnabled = $true; $computer.IsMemoryEnabled = $true
  $computer.Open()
  $rows=@()
  foreach ($hw in $computer.Hardware) {
    $hw.Update()
    foreach ($sh in $hw.SubHardware) { $sh.Update() }
    foreach ($s in $hw.Sensors) {
      if ($null -eq $s.Value) { continue }
      $kind = switch ("$($s.SensorType)") { 'Temperature' {'temp'} 'Fan' {'fan'} 'Voltage' {'voltage'} 'Clock' {'clock'} default {$null} }
      if ($null -eq $kind) { continue }
      $unit = switch ($kind) { 'temp' {'C'} 'fan' {'RPM'} 'voltage' {'V'} 'clock' {'MHz'} }
      $rows += [ordered]@{ name="$($hw.Name) $($s.Name)"; kind=$kind; value=[math]::Round([double]$s.Value,2); unit=$unit }
    }
  }
  $computer.Close()
  $out.data=@($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
```

- [ ] **Step 7: Run the full test suite**

Run: `python -m pytest -q`
Expected: PASS (all tests, including existing ones).

- [ ] **Step 8: Commit**

```bash
git add pcdiag/pipeline.py pcdiag/normalize.py diagnose.py collectors/sensors.ps1 tests/test_pipeline.py tests/test_normalize.py
git commit -m "feat: wire synthesis into pipeline and add opt-in --sensors backend"
```

---

### Task 11: Docs + end-to-end verification

**Files:**
- Modify: `README.md` (document diagnosis + `--sensors`)
- Verify: full run on the real machine

**Interfaces:** none (docs + verification).

- [ ] **Step 1: Update the README**

In `README.md`, under "Setup & run", add:

```
python diagnose.py            # baseline: collect, diagnose, open the report
python diagnose.py --sensors  # opt-in: also read temps/fans/voltages via
                              # LibreHardwareMonitor (needs admin + the DLL in tools/)
```

Under "What it detects", add a line:

```
It now also synthesizes a Primary Diagnosis — a ranked root-cause verdict with
the reasoning it ruled out and a Tier 1/2/3 action plan — from the collected
signals (all offline, deterministic).
```

- [ ] **Step 2: Run the whole suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 3: Run the tool end-to-end**

Run: `python diagnose.py --no-open`
Expected: prints collector statuses including `memory_config: ok` and `thermal: ok`, a health score, and writes `reports/report.html`. Open `reports/report.json` and confirm a `"diagnoses"` array is present.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document Primary Diagnosis and --sensors backend"
```

---

## Self-Review

**Spec coverage:**
- Data model (CrashEvent fields, MemoryConfig, ThermalEvent, SensorReading, ActionStep, Diagnosis) → Task 1 + Task 5 (ActionStep/Diagnosis in synthesize.py per Global Constraints).
- Expanded crashes (6008 real time, local hour, Event 41 flags) → Task 2.
- memory_config collector → Task 3. thermal collector → Task 4. sensors collector (opt-in) → Task 10.
- Synthesis registry + ranking + load-hours helper → Task 5.
- power_loss synthesizer (timing, ruled-out, tiers, iGPU/tuning gating) → Task 6.
- software_bsod synthesizer (bugcheck families, driver correlation) → Task 7.
- thermal synthesizer → Task 8.
- Report hero + secondary + sensors table + JSON `diagnoses` → Task 9.
- Pipeline wiring + `--sensors` CLI → Task 10. Docs + e2e → Task 11.

**Placeholder scan:** No TBD/TODO; every code step has concrete code; fixtures are fully specified and synthetic.

**Type consistency:** `Diagnosis`/`ActionStep` defined in Task 5, imported from `pcdiag.synthesize` in Tasks 6–10; `render_report(..., diagnoses=None)` defined in Task 9 and called with `diagnoses=diagnoses` in Task 10; `run_synthesis` signature identical in Tasks 5 and 10; new `Timeline`/`CrashEvent` fields from Task 1 are consumed with the same names throughout.
