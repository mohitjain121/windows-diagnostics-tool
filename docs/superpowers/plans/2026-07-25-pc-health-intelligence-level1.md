# PC Health Intelligence — Level 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An on-demand Windows diagnostic tool that collects system telemetry, correlates it on one timeline, identifies likely root causes (especially crashes tied to recent driver/software changes) with confidence and evidence, and produces a self-contained HTML report.

**Architecture:** Four-stage pipeline — PowerShell collectors emit normalized JSON → Python normalizer builds a typed UTC timeline → a deterministic rules engine produces confidence-scored Findings → a renderer writes an HTML report + JSON sidecar. Each stage has a JSON/dataclass boundary so it is testable in isolation.

**Tech Stack:** Python 3.11+, PowerShell 5.1/7 (`powershell.exe`), Jinja2 (HTML template), pytest (fixture-based tests). Standard library elsewhere.

## Global Constraints

- **Never modify the system.** Collectors only read. No install/uninstall, no config/registry writes, no process kills. Read-only WMI/CIM/event-log/file queries only.
- **Python 3.11+** (uses `datetime.UTC`, `dataclasses`, `enum`, `typing`).
- **Runtime deps:** `jinja2` only. **Dev deps:** `pytest`. Pin in `requirements.txt`.
- **Collector JSON contract (every collector, verbatim):** each PowerShell collector prints ONE JSON object to stdout:
  ```json
  { "collector": "<name>", "collected_at": "<ISO-8601 UTC>", "elevated": <bool>, "ok": <bool>, "error": <string|null>, "data": [ ... ] }
  ```
  On any failure the collector still prints this object with `"ok": false` and `"error"` set — it never throws to stderr-only.
- **All timestamps normalized to timezone-aware UTC `datetime`** in Python before correlation.
- **Runs without admin.** Elevation is detected and reported, never required. Missing-because-unelevated signals degrade gracefully.
- **Determinism:** the rules engine is a pure function of the Timeline. No wall-clock reads inside rules except a single injected `now` in `Config`.
- **Tests never call PowerShell.** They load captured JSON fixtures from `tests/fixtures/`.

---

### Task 1: Project scaffold + collector runner + first collector (system snapshot)

Establishes the repo layout, the `CollectorResult` contract, the `powershell.exe` invocation harness, and the fixture-testing pattern that every later task reuses.

**Files:**
- Create: `requirements.txt`
- Create: `pcdiag/__init__.py`
- Create: `pcdiag/collectors.py`
- Create: `collectors/system_snapshot.ps1`
- Create: `tests/__init__.py`
- Create: `tests/fixtures/system_snapshot.json`
- Create: `tests/test_collectors.py`

**Interfaces:**
- Produces:
  - `CollectorResult` dataclass: `collector: str`, `collected_at: datetime`, `elevated: bool`, `ok: bool`, `error: str | None`, `data: list[dict]`.
  - `parse_collector_result(raw: dict) -> CollectorResult` — parses one collector JSON object; coerces `collected_at` to aware UTC datetime.
  - `run_collector(name: str, scripts_dir: Path = Path("collectors"), timeout: float = 60.0) -> CollectorResult` — invokes `powershell.exe -NoProfile -ExecutionPolicy Bypass -File <scripts_dir>/<name>.ps1`, parses stdout JSON. On non-zero exit / timeout / bad JSON returns a `CollectorResult` with `ok=False` and `error` set.

- [ ] **Step 1: Create `requirements.txt`**

```
jinja2==3.1.4
pytest==8.3.2
```

- [ ] **Step 2: Write the failing test for `parse_collector_result`**

Create `tests/test_collectors.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

from pcdiag.collectors import parse_collector_result

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_parse_collector_result_reads_contract_fields():
    result = parse_collector_result(load_fixture("system_snapshot"))
    assert result.collector == "system_snapshot"
    assert result.ok is True
    assert result.error is None
    assert result.collected_at.tzinfo is not None
    assert result.collected_at.utcoffset() == timezone.utc.utcoffset(datetime.now(timezone.utc))
    assert isinstance(result.data, list)
    assert result.data[0]["cpu_name"]


def test_parse_collector_result_carries_failure():
    raw = {
        "collector": "x", "collected_at": "2026-07-20T10:00:00Z",
        "elevated": False, "ok": False, "error": "boom", "data": [],
    }
    result = parse_collector_result(raw)
    assert result.ok is False
    assert result.error == "boom"
    assert result.data == []
```

- [ ] **Step 3: Create the fixture `tests/fixtures/system_snapshot.json`**

```json
{
  "collector": "system_snapshot",
  "collected_at": "2026-07-25T09:15:00Z",
  "elevated": false,
  "ok": true,
  "error": null,
  "data": [
    {
      "cpu_name": "Example CPU 8-Core",
      "gpu_names": ["Example GX Graphics"],
      "ram_total_gb": 32.0,
      "os_caption": "Windows 11 Pro",
      "os_build": "26200",
      "uptime_hours": 5.2,
      "cpu_load_pct": 12.0,
      "mem_used_pct": 41.0,
      "system_disk_free_pct": 55.0
    }
  ]
}
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `python -m pytest tests/test_collectors.py -v`
Expected: FAIL with `ModuleNotFoundError: pcdiag.collectors`.

- [ ] **Step 5: Implement `pcdiag/collectors.py`**

Create `pcdiag/__init__.py` (empty) and `tests/__init__.py` (empty), then `pcdiag/collectors.py`:

```python
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class CollectorResult:
    collector: str
    collected_at: datetime
    elevated: bool
    ok: bool
    error: str | None
    data: list[dict] = field(default_factory=list)


def _parse_iso_utc(value: str) -> datetime:
    # Accept trailing "Z" and offset forms; always return aware UTC.
    text = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_collector_result(raw: dict) -> CollectorResult:
    return CollectorResult(
        collector=raw["collector"],
        collected_at=_parse_iso_utc(raw["collected_at"]),
        elevated=bool(raw.get("elevated", False)),
        ok=bool(raw.get("ok", False)),
        error=raw.get("error"),
        data=list(raw.get("data") or []),
    )


def _failed(name: str, error: str) -> CollectorResult:
    return CollectorResult(
        collector=name,
        collected_at=datetime.now(timezone.utc),
        elevated=False,
        ok=False,
        error=error,
        data=[],
    )


def run_collector(
    name: str,
    scripts_dir: Path = Path("collectors"),
    timeout: float = 60.0,
) -> CollectorResult:
    script = scripts_dir / f"{name}.ps1"
    if not script.exists():
        return _failed(name, f"collector script not found: {script}")
    try:
        proc = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(script),
            ],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return _failed(name, f"collector timed out after {timeout}s")
    except OSError as exc:
        return _failed(name, f"failed to launch powershell: {exc}")
    if proc.returncode != 0 and not proc.stdout.strip():
        return _failed(name, f"exit {proc.returncode}: {proc.stderr.strip()[:500]}")
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return _failed(name, f"invalid JSON from collector: {exc}")
    return parse_collector_result(raw)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_collectors.py -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Create the `system_snapshot` collector**

Create `collectors/system_snapshot.ps1`:

```powershell
$ErrorActionPreference = 'Stop'
function Test-Elevated {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
}
$out = [ordered]@{
  collector = 'system_snapshot'
  collected_at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  elevated = Test-Elevated
  ok = $true
  error = $null
  data = @()
}
try {
  $os  = Get-CimInstance Win32_OperatingSystem
  $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
  $gpu = @(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name })
  $ram = [math]::Round(($os.TotalVisibleMemorySize * 1KB) / 1GB, 1)
  $memUsedPct = [math]::Round(
    (1 - ($os.FreePhysicalMemory / $os.TotalVisibleMemorySize)) * 100, 1)
  $uptime = ((Get-Date) - $os.LastBootUpTime).TotalHours
  $sys = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($env:SystemDrive)'"
  $freePct = if ($sys) { [math]::Round(($sys.FreeSpace / $sys.Size) * 100, 1) } else { $null }
  $cpuLoad = (Get-CimInstance Win32_Processor |
    Measure-Object -Property LoadPercentage -Average).Average
  $out.data = @([ordered]@{
    cpu_name = $cpu.Name.Trim()
    gpu_names = $gpu
    ram_total_gb = $ram
    os_caption = $os.Caption
    os_build = $os.BuildNumber
    uptime_hours = [math]::Round($uptime, 1)
    cpu_load_pct = $cpuLoad
    mem_used_pct = $memUsedPct
    system_disk_free_pct = $freePct
  })
} catch {
  $out.ok = $false
  $out.error = $_.Exception.Message
}
$out | ConvertTo-Json -Depth 6 -Compress
```

- [ ] **Step 8: Manually smoke-test the collector on this machine**

Run: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File collectors/system_snapshot.ps1`
Expected: one line of JSON with `"ok": true` and a populated `data` array. If real values differ from the fixture, that is fine — the fixture is a frozen contract sample, not this machine's data.

- [ ] **Step 9: Commit**

```bash
git add requirements.txt pcdiag tests collectors
git commit -m "feat: collector runner + system_snapshot collector"
```

---

### Task 2: Normalizer domain models + Timeline skeleton

Turns collector JSON into typed objects on one UTC timeline. Starts with the `system_snapshot` and the empty-timeline shape; later tasks add event types.

**Files:**
- Create: `pcdiag/models.py`
- Create: `pcdiag/normalize.py`
- Create: `tests/test_normalize.py`

**Interfaces:**
- Consumes: `CollectorResult` (Task 1).
- Produces (in `pcdiag/models.py`):
  - `@dataclass SystemSnapshot`: `cpu_name: str`, `gpu_names: list[str]`, `ram_total_gb: float`, `os_caption: str`, `os_build: str`, `uptime_hours: float`, `cpu_load_pct: float | None`, `mem_used_pct: float | None`, `system_disk_free_pct: float | None`.
  - `@dataclass CrashEvent`: `when: datetime`, `kind: str`, `event_id: int`, `source: str`, `bugcheck_code: str | None`, `message: str`.
  - `@dataclass DisplayResetEvent`: `when: datetime`, `device: str`, `event_id: int`.
  - `@dataclass WheaError`: `when: datetime`, `severity: str`, `error_source: str`, `event_id: int`.
  - `@dataclass Driver`: `name: str`, `version: str`, `provider: str`, `install_date: datetime | None`, `device_class: str`.
  - `@dataclass ChangeEntry`: `when: datetime`, `change_type: str` (one of `install`/`update`/`uninstall`/`driver`/`os_update`), `name: str`, `version: str | None`, `source: str`.
  - `@dataclass Disk`: `model: str`, `wear_pct: float | None`, `reallocated_sectors: int | None`, `read_errors: int | None`, `write_errors: int | None`, `temperature_c: float | None`, `predictive_failure: bool`.
  - `@dataclass MemoryDiagResult`: `when: datetime`, `result: str`.
  - `@dataclass MinidumpFile`: `when: datetime`, `filename: str`, `bugcheck_code: str | None`.
  - `@dataclass CollectorMeta`: `name: str`, `ok: bool`, `elevated: bool`, `error: str | None`.
  - `@dataclass Timeline`: `snapshot: SystemSnapshot | None`, `crashes: list[CrashEvent]`, `display_resets: list[DisplayResetEvent]`, `whea_errors: list[WheaError]`, `drivers: list[Driver]`, `changes: list[ChangeEntry]`, `disks: list[Disk]`, `memory_diags: list[MemoryDiagResult]`, `minidumps: list[MinidumpFile]`, `meta: list[CollectorMeta]`. All list fields `default_factory=list`.
- Produces (in `pcdiag/normalize.py`):
  - `build_timeline(results: dict[str, CollectorResult]) -> Timeline` — dispatches each result by name into the matching Timeline field; unknown/failed collectors still contribute a `CollectorMeta`. In this task only `system_snapshot` is wired; other fields stay empty.

- [ ] **Step 1: Write the failing test**

Create `tests/test_normalize.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError: pcdiag.normalize`.

- [ ] **Step 3: Implement `pcdiag/models.py`**

```python
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
```

- [ ] **Step 4: Implement `pcdiag/normalize.py` (system_snapshot only)**

```python
from __future__ import annotations

from datetime import datetime, timezone

from pcdiag.collectors import CollectorResult
from pcdiag.models import CollectorMeta, SystemSnapshot, Timeline


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


# name -> normalizer function. Later tasks register more entries here.
NORMALIZERS = {
    "system_snapshot": _norm_system_snapshot,
}


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
    return timeline
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_normalize.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pcdiag/models.py pcdiag/normalize.py tests/test_normalize.py
git commit -m "feat: domain models + timeline normalizer (system snapshot)"
```

---

### Task 3: Crash + display-reset collectors and normalization

Adds the two collectors central to BSOD/GPU-hang diagnosis and normalizes them onto the timeline.

**Files:**
- Create: `collectors/crashes.ps1`
- Create: `collectors/livekernel_display.ps1`
- Create: `tests/fixtures/crashes.json`
- Create: `tests/fixtures/livekernel_display.json`
- Modify: `pcdiag/normalize.py` (add two normalizers + registry entries)
- Modify: `tests/test_normalize.py` (add cases)

**Interfaces:**
- Consumes: `CollectorResult`, `Timeline`, `CrashEvent`, `DisplayResetEvent`.
- Produces: normalizers `_norm_crashes` and `_norm_livekernel_display`, registered under keys `"crashes"` and `"livekernel_display"`. Crash data rows carry `{when, kind, event_id, source, bugcheck_code, message}`; display rows carry `{when, device, event_id}`.

- [ ] **Step 1: Create fixtures**

`tests/fixtures/crashes.json`:

```json
{
  "collector": "crashes",
  "collected_at": "2026-07-25T09:16:00Z",
  "elevated": true,
  "ok": true,
  "error": null,
  "data": [
    {"when": "2026-07-23T02:11:07Z", "kind": "bugcheck", "event_id": 1001, "source": "BugCheck", "bugcheck_code": "0x116", "message": "The computer has rebooted from a bugcheck. 0x00000116"},
    {"when": "2026-07-23T02:10:55Z", "kind": "unexpected_shutdown", "event_id": 41, "source": "Kernel-Power", "bugcheck_code": null, "message": "The system rebooted without cleanly shutting down first."},
    {"when": "2026-07-22T21:03:12Z", "kind": "bugcheck", "event_id": 1001, "source": "BugCheck", "bugcheck_code": "0x116", "message": "The computer has rebooted from a bugcheck. 0x00000116"}
  ]
}
```

`tests/fixtures/livekernel_display.json`:

```json
{
  "collector": "livekernel_display",
  "collected_at": "2026-07-25T09:16:05Z",
  "elevated": false,
  "ok": true,
  "error": null,
  "data": [
    {"when": "2026-07-23T02:10:40Z", "device": "nvlddmkm", "event_id": 4101},
    {"when": "2026-07-22T21:02:50Z", "device": "nvlddmkm", "event_id": 4101},
    {"when": "2026-07-22T19:44:10Z", "device": "nvlddmkm", "event_id": 4101}
  ]
}
```

- [ ] **Step 2: Write failing tests**

Append to `tests/test_normalize.py`:

```python
def test_build_timeline_maps_crashes_and_display_resets():
    timeline = build_timeline(results_from("crashes", "livekernel_display"))
    assert len(timeline.crashes) == 3
    assert timeline.crashes[0].bugcheck_code == "0x116"
    assert all(c.when.tzinfo is not None for c in timeline.crashes)
    assert len(timeline.display_resets) == 3
    assert timeline.display_resets[0].device == "nvlddmkm"
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/test_normalize.py::test_build_timeline_maps_crashes_and_display_resets -v`
Expected: FAIL (crashes list empty).

- [ ] **Step 4: Add normalizers to `pcdiag/normalize.py`**

Add imports `CrashEvent, DisplayResetEvent` from `pcdiag.models`, then:

```python
def _norm_crashes(result: CollectorResult, timeline: Timeline) -> None:
    for row in result.data:
        when = _iso(row.get("when"))
        if when is None:
            continue
        timeline.crashes.append(CrashEvent(
            when=when,
            kind=row.get("kind", "unknown"),
            event_id=int(row.get("event_id") or 0),
            source=row.get("source", ""),
            bugcheck_code=row.get("bugcheck_code"),
            message=row.get("message", ""),
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
```

Register them:

```python
NORMALIZERS = {
    "system_snapshot": _norm_system_snapshot,
    "crashes": _norm_crashes,
    "livekernel_display": _norm_livekernel_display,
}
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_normalize.py -v`
Expected: PASS (all cases).

- [ ] **Step 6: Create `collectors/crashes.ps1`**

```powershell
$ErrorActionPreference = 'Stop'
function Test-Elevated {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
}
$out = [ordered]@{
  collector='crashes'; collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  elevated=Test-Elevated; ok=$true; error=$null; data=@()
}
try {
  $since = (Get-Date).AddDays(-30)
  $rows = @()
  $filter = @{ LogName='System'; Id=@(41,1001,6008); StartTime=$since }
  $events = Get-WinEvent -FilterHashtable $filter -ErrorAction SilentlyContinue
  foreach ($e in $events) {
    $kind = switch ($e.Id) { 41 {'unexpected_shutdown'} 1001 {'bugcheck'} 6008 {'dirty_shutdown'} default {'unknown'} }
    $bc = $null
    if ($e.Id -eq 1001) {
      $m = [regex]::Match($e.Message, '0x[0-9A-Fa-f]{8}')
      if ($m.Success) { $bc = '0x' + [Convert]::ToInt32($m.Value,16).ToString('x') }
    }
    $rows += [ordered]@{
      when = $e.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
      kind = $kind; event_id = $e.Id
      source = $e.ProviderName; bugcheck_code = $bc
      message = ($e.Message -split "`n")[0].Trim()
    }
  }
  $out.data = @($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
```

- [ ] **Step 7: Create `collectors/livekernel_display.ps1`**

```powershell
$ErrorActionPreference = 'Stop'
function Test-Elevated {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
}
$out = [ordered]@{
  collector='livekernel_display'; collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  elevated=Test-Elevated; ok=$true; error=$null; data=@()
}
try {
  $since = (Get-Date).AddDays(-30)
  $rows = @()
  $filter = @{ LogName='System'; ProviderName='Display'; Id=4101; StartTime=$since }
  $events = Get-WinEvent -FilterHashtable $filter -ErrorAction SilentlyContinue
  foreach ($e in $events) {
    $device = 'display'
    $m = [regex]::Match($e.Message, '([A-Za-z0-9_]+)\s+stopped responding')
    if ($m.Success) { $device = $m.Groups[1].Value }
    $rows += [ordered]@{
      when = $e.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
      device = $device; event_id = $e.Id
    }
  }
  $out.data = @($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
```

- [ ] **Step 8: Smoke-test both collectors**

Run each with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File collectors/<name>.ps1` and confirm `"ok": true`. (Empty `data` is valid on a healthy machine.)

- [ ] **Step 9: Commit**

```bash
git add collectors/crashes.ps1 collectors/livekernel_display.ps1 tests/fixtures pcdiag/normalize.py tests/test_normalize.py
git commit -m "feat: crash + display-reset collectors and normalization"
```

---

### Task 4: Driver + Change Ledger collectors and normalization

Adds the two inputs that let the engine say "this changed right before the crashes."

**Files:**
- Create: `collectors/drivers.ps1`
- Create: `collectors/changes.ps1`
- Create: `tests/fixtures/drivers.json`
- Create: `tests/fixtures/changes.json`
- Modify: `pcdiag/normalize.py`
- Modify: `tests/test_normalize.py`

**Interfaces:**
- Consumes: `CollectorResult`, `Timeline`, `Driver`, `ChangeEntry`.
- Produces: normalizers `_norm_drivers`, `_norm_changes` registered as `"drivers"`, `"changes"`. Driver rows: `{name, version, provider, install_date, device_class}`. Change rows: `{when, change_type, name, version, source}` where `change_type ∈ {install, update, uninstall, driver, os_update}`.

- [ ] **Step 1: Create fixtures**

`tests/fixtures/drivers.json`:

```json
{
  "collector": "drivers",
  "collected_at": "2026-07-25T09:17:00Z",
  "elevated": false,
  "ok": true,
  "error": null,
  "data": [
    {"name": "Example GX Graphics", "version": "32.0.15.6636", "provider": "Example Graphics Vendor", "install_date": "2026-07-22T00:00:00Z", "device_class": "Display"},
    {"name": "Example Audio Device", "version": "6.0.9502.1", "provider": "Example Vendor", "install_date": "2025-11-02T00:00:00Z", "device_class": "MEDIA"}
  ]
}
```

`tests/fixtures/changes.json`:

```json
{
  "collector": "changes",
  "collected_at": "2026-07-25T09:17:10Z",
  "elevated": false,
  "ok": true,
  "error": null,
  "data": [
    {"when": "2026-07-22T18:30:00Z", "change_type": "driver", "name": "Example GX Display Driver", "version": "566.36", "source": "setupapi"},
    {"when": "2026-07-19T12:00:00Z", "change_type": "update", "name": "Steam", "version": "3.1", "source": "program-inventory"},
    {"when": "2026-07-10T08:00:00Z", "change_type": "os_update", "name": "KB5041234", "version": null, "source": "windows-update"}
  ]
}
```

- [ ] **Step 2: Write failing test**

Append to `tests/test_normalize.py`:

```python
def test_build_timeline_maps_drivers_and_changes():
    timeline = build_timeline(results_from("drivers", "changes"))
    gpu = [d for d in timeline.drivers if d.device_class == "Display"]
    assert gpu and gpu[0].install_date is not None
    driver_changes = [c for c in timeline.changes if c.change_type == "driver"]
    assert driver_changes and driver_changes[0].name == "Example GX Display Driver"
    assert driver_changes[0].when.tzinfo is not None
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/test_normalize.py::test_build_timeline_maps_drivers_and_changes -v`
Expected: FAIL.

- [ ] **Step 4: Add normalizers to `pcdiag/normalize.py`**

Add imports `Driver, ChangeEntry`, then:

```python
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
```

Register `"drivers": _norm_drivers, "changes": _norm_changes` in `NORMALIZERS`.

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_normalize.py -v`
Expected: PASS.

- [ ] **Step 6: Create `collectors/drivers.ps1`**

```powershell
$ErrorActionPreference = 'Stop'
function Test-Elevated {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
}
$out = [ordered]@{
  collector='drivers'; collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  elevated=Test-Elevated; ok=$true; error=$null; data=@()
}
try {
  $rows = @()
  $drivers = Get-CimInstance Win32_PnPSignedDriver -ErrorAction SilentlyContinue |
    Where-Object { $_.DeviceName -and $_.DriverVersion }
  foreach ($d in $drivers) {
    $inst = $null
    if ($d.DriverDate) {
      try { $inst = ([datetime]$d.DriverDate).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') } catch {}
    }
    $rows += [ordered]@{
      name = $d.DeviceName; version = $d.DriverVersion
      provider = $d.DriverProviderName; install_date = $inst
      device_class = $d.DeviceClass
    }
  }
  $out.data = @($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
```

- [ ] **Step 7: Create `collectors/changes.ps1`**

```powershell
$ErrorActionPreference = 'Stop'
function Test-Elevated {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
}
$out = [ordered]@{
  collector='changes'; collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
  elevated=Test-Elevated; ok=$true; error=$null; data=@()
}
try {
  $since = (Get-Date).AddDays(-60)
  $rows = @()

  # Software install/update/uninstall from Program-Inventory operational log.
  $pi = Get-WinEvent -FilterHashtable @{
    LogName='Microsoft-Windows-Application-Experience/Program-Inventory'
    Id=@(903,904,905,906); StartTime=$since } -ErrorAction SilentlyContinue
  foreach ($e in $pi) {
    $ct = switch ($e.Id) { 903 {'install'} 904 {'update'} 905 {'uninstall'} 906 {'uninstall'} default {'install'} }
    $name = ($e.Message -split "`n")[0].Trim()
    $rows += [ordered]@{
      when = $e.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
      change_type = $ct; name = $name; version = $null; source = 'program-inventory'
    }
  }

  # MSI installs/removals from Application log.
  $msi = Get-WinEvent -FilterHashtable @{
    LogName='Application'; ProviderName='MsiInstaller'; Id=@(11707,11724); StartTime=$since
  } -ErrorAction SilentlyContinue
  foreach ($e in $msi) {
    $ct = if ($e.Id -eq 11724) { 'uninstall' } else { 'install' }
    $rows += [ordered]@{
      when = $e.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
      change_type = $ct; name = (($e.Message -split "`n")[0].Trim()); version = $null; source = 'msi'
    }
  }

  # Driver installs from setupapi.dev.log (parse install sections).
  $log = Join-Path $env:windir 'INF\setupapi.dev.log'
  if (Test-Path $log) {
    $lines = Get-Content $log -ErrorAction SilentlyContinue
    for ($i=0; $i -lt $lines.Count; $i++) {
      if ($lines[$i] -match '>>>\s+\[Device Install .*\]') {
        $tsMatch = $null
        for ($j=$i+1; $j -lt [math]::Min($i+4,$lines.Count); $j++) {
          $tm = [regex]::Match($lines[$j], '>>>\s+Section start (\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})')
          if ($tm.Success) { $tsMatch = $tm.Groups[1].Value; break }
        }
        if ($tsMatch) {
          $dt = [datetime]::ParseExact($tsMatch,'yyyy/MM/dd HH:mm:ss',$null)
          if ($dt -ge $since) {
            $nm = [regex]::Match($lines[$i], '\[Device Install \(.*?\) - (.*?)\]')
            $rows += [ordered]@{
              when = $dt.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
              change_type = 'driver'; name = ($(if($nm.Success){$nm.Groups[1].Value}else{'driver'}))
              version = $null; source = 'setupapi'
            }
          }
        }
      }
    }
  }

  # OS updates from Windows Update history.
  try {
    $searcher = (New-Object -ComObject Microsoft.Update.Session).CreateUpdateSearcher()
    $count = $searcher.GetTotalHistoryCount()
    if ($count -gt 0) {
      $hist = $searcher.QueryHistory(0, [math]::Min($count,100))
      foreach ($h in $hist) {
        if ($h.Date -ge $since -and $h.Title) {
          $kb = [regex]::Match($h.Title, 'KB\d+')
          $rows += [ordered]@{
            when = ([datetime]$h.Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
            change_type = 'os_update'
            name = ($(if($kb.Success){$kb.Value}else{$h.Title})); version = $null; source = 'windows-update'
          }
        }
      }
    }
  } catch {}

  $out.data = @($rows | Sort-Object when -Descending)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
```

- [ ] **Step 8: Smoke-test both collectors**

Run each; confirm `"ok": true`. The `changes` collector is the richest — verify it returns entries and that your recent GPU driver update appears (as a `driver` or `os_update` row).

- [ ] **Step 9: Commit**

```bash
git add collectors/drivers.ps1 collectors/changes.ps1 tests/fixtures pcdiag/normalize.py tests/test_normalize.py
git commit -m "feat: driver + change-ledger collectors and normalization"
```

---

### Task 5: Rules framework — Finding model, severity/confidence, scoring, registry

Builds the deterministic engine's skeleton and a trivial rule to prove the wiring, plus the health score.

**Files:**
- Create: `pcdiag/config.py`
- Create: `pcdiag/rules.py`
- Create: `pcdiag/score.py`
- Create: `tests/test_score.py`
- Create: `tests/test_rules.py`

**Interfaces:**
- Consumes: `Timeline` and its members (Tasks 2–4).
- Produces:
  - `pcdiag/config.py`: `@dataclass Config`: `now: datetime`, `change_window_days: int = 7`, `cluster_window_hours: int = 48`, `min_cluster_size: int = 2`. Helper `default_config() -> Config` using `datetime.now(timezone.utc)`.
  - `pcdiag/rules.py`:
    - `class Severity(Enum)` with members `CRITICAL`, `WARNING`, `INFO`; property `weight` → 40/20/5.
    - `class Confidence(Enum)` with members `HIGH`, `MEDIUM`, `LOW`; property `multiplier` → 1.0/0.6/0.3; property `label` → "HIGH"/"MEDIUM"/"LOW".
    - `@dataclass Evidence`: `label: str`, `detail: str`, `when: datetime | None = None`.
    - `@dataclass Finding`: `id: str`, `title: str`, `category: str`, `severity: Severity`, `confidence: Confidence`, `evidence: list[Evidence]`, `recommendation: str`.
    - `RULES: list[Callable[[Timeline, Config], list[Finding]]]` (starts with one trivial rule).
    - `run_rules(timeline: Timeline, config: Config) -> list[Finding]` — runs every rule, concatenates, sorts by `(severity.weight * confidence.multiplier)` descending.
  - `pcdiag/score.py`: `health_score(findings: list[Finding]) -> int` → `max(0, round(100 - sum(f.severity.weight * f.confidence.multiplier for f in findings)))`.

- [ ] **Step 1: Write the failing scoring test**

Create `tests/test_score.py`:

```python
from pcdiag.rules import Confidence, Evidence, Finding, Severity
from pcdiag.score import health_score


def _finding(sev, conf):
    return Finding(id="x", title="t", category="c", severity=sev,
                   confidence=conf, evidence=[], recommendation="r")


def test_health_score_full_when_no_findings():
    assert health_score([]) == 100


def test_health_score_deducts_severity_times_confidence():
    findings = [_finding(Severity.CRITICAL, Confidence.HIGH)]  # 40 * 1.0
    assert health_score(findings) == 60


def test_health_score_floors_at_zero():
    findings = [_finding(Severity.CRITICAL, Confidence.HIGH)] * 5
    assert health_score(findings) == 0
```

- [ ] **Step 2: Write the failing rules-framework test**

Create `tests/test_rules.py`:

```python
from datetime import datetime, timezone

from pcdiag.config import Config
from pcdiag.models import Timeline
from pcdiag.rules import Confidence, Severity, run_rules


def cfg():
    return Config(now=datetime(2026, 7, 25, tzinfo=timezone.utc))


def test_run_rules_sorts_by_weighted_severity():
    findings = run_rules(Timeline(), cfg())
    weights = [f.severity.weight * f.confidence.multiplier for f in findings]
    assert weights == sorted(weights, reverse=True)


def test_severity_and_confidence_weights():
    assert Severity.CRITICAL.weight == 40
    assert Confidence.HIGH.multiplier == 1.0
    assert Confidence.LOW.label == "LOW"
```

- [ ] **Step 3: Run both to verify they fail**

Run: `python -m pytest tests/test_score.py tests/test_rules.py -v`
Expected: FAIL with import errors.

- [ ] **Step 4: Implement `pcdiag/config.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Config:
    now: datetime
    change_window_days: int = 7
    cluster_window_hours: int = 48
    min_cluster_size: int = 2


def default_config() -> Config:
    return Config(now=datetime.now(timezone.utc))
```

- [ ] **Step 5: Implement `pcdiag/rules.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable

from pcdiag.config import Config
from pcdiag.models import Timeline


class Severity(Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"

    @property
    def weight(self) -> int:
        return {"critical": 40, "warning": 20, "info": 5}[self.value]


class Confidence(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def multiplier(self) -> float:
        return {"high": 1.0, "medium": 0.6, "low": 0.3}[self.value]

    @property
    def label(self) -> str:
        return self.value.upper()


@dataclass
class Evidence:
    label: str
    detail: str
    when: datetime | None = None


@dataclass
class Finding:
    id: str
    title: str
    category: str
    severity: Severity
    confidence: Confidence
    evidence: list[Evidence] = field(default_factory=list)
    recommendation: str = ""


def _rule_healthy_placeholder(timeline: Timeline, config: Config) -> list[Finding]:
    # Real rules are added in Tasks 6 and 8. Returns nothing.
    return []


RULES: list[Callable[[Timeline, Config], list[Finding]]] = [
    _rule_healthy_placeholder,
]


def run_rules(timeline: Timeline, config: Config) -> list[Finding]:
    findings: list[Finding] = []
    for rule in RULES:
        findings.extend(rule(timeline, config))
    findings.sort(
        key=lambda f: f.severity.weight * f.confidence.multiplier, reverse=True
    )
    return findings
```

- [ ] **Step 6: Implement `pcdiag/score.py`**

```python
from __future__ import annotations

from pcdiag.rules import Finding


def health_score(findings: list[Finding]) -> int:
    deduction = sum(f.severity.weight * f.confidence.multiplier for f in findings)
    return max(0, round(100 - deduction))
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_score.py tests/test_rules.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pcdiag/config.py pcdiag/rules.py pcdiag/score.py tests/test_score.py tests/test_rules.py
git commit -m "feat: rules framework, severity/confidence model, scoring"
```

---

### Task 6: Flagship rules — GPU driver instability + generic change-vs-symptom

The rules that directly diagnose the user's live problem. Includes a shared clustering helper.

**Files:**
- Create: `pcdiag/correlate.py`
- Modify: `pcdiag/rules.py` (add two rules + register)
- Modify: `tests/test_rules.py`
- Create: `tests/fixtures/scenario_gpu_crash/` with `crashes.json`, `livekernel_display.json`, `drivers.json`, `changes.json` (copies of the Task 3–4 fixtures — they already describe a post-driver-update GPU crash cluster)

**Interfaces:**
- Consumes: `Timeline`, `Config`, `Finding`, `Evidence`, `Severity`, `Confidence`.
- Produces:
  - `pcdiag/correlate.py`:
    - `cluster_by_time(events, window_hours) -> list[list]` — groups timestamp-bearing objects (each has a `.when`) into clusters where consecutive events are within `window_hours`. Input pre-sorted or not; function sorts by `.when`.
    - `most_recent_change_before(changes, when, window_days) -> ChangeEntry | None` — the latest change whose `.when` is in `(when - window_days, when]`.
  - `pcdiag/rules.py`: `_rule_gpu_driver_instability`, `_rule_change_vs_symptom`, both registered in `RULES`.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_rules.py`:

```python
import json
from pathlib import Path

from pcdiag.collectors import parse_collector_result
from pcdiag.normalize import build_timeline

FIXTURES = Path(__file__).parent / "fixtures"


def scenario(folder, *names):
    out = {}
    for name in names:
        raw = json.loads((FIXTURES / folder / f"{name}.json").read_text("utf-8"))
        out[name] = parse_collector_result(raw)
    return build_timeline(out)


def test_gpu_driver_instability_high_confidence():
    timeline = scenario("scenario_gpu_crash", "crashes",
                        "livekernel_display", "drivers", "changes")
    findings = run_rules(timeline, cfg())
    gpu = [f for f in findings if f.id == "gpu_driver_instability"]
    assert gpu, "expected a GPU driver instability finding"
    assert gpu[0].confidence == Confidence.HIGH
    assert gpu[0].severity == Severity.CRITICAL
    assert any("566.36" in e.detail or "0x116" in e.detail for e in gpu[0].evidence)


def test_change_vs_symptom_names_recent_change():
    timeline = scenario("scenario_gpu_crash", "crashes", "changes")
    findings = run_rules(timeline, cfg())
    generic = [f for f in findings if f.id == "change_vs_symptom"]
    assert generic
    assert any("Example GX" in e.detail for e in generic[0].evidence)
```

- [ ] **Step 2: Create the scenario fixtures**

Copy the four fixture files into `tests/fixtures/scenario_gpu_crash/`:

```bash
mkdir -p tests/fixtures/scenario_gpu_crash
cp tests/fixtures/crashes.json tests/fixtures/livekernel_display.json \
   tests/fixtures/drivers.json tests/fixtures/changes.json \
   tests/fixtures/scenario_gpu_crash/
```

Note: `cfg()` uses `now = 2026-07-25`; the fixtures place the GPU driver change on 2026-07-22 and crashes on 2026-07-22/23 — inside the default 7-day window.

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/test_rules.py -k "gpu or change_vs" -v`
Expected: FAIL (no such findings).

- [ ] **Step 4: Implement `pcdiag/correlate.py`**

```python
from __future__ import annotations

from datetime import timedelta


def cluster_by_time(events: list, window_hours: int) -> list[list]:
    items = sorted(events, key=lambda e: e.when)
    clusters: list[list] = []
    current: list = []
    for ev in items:
        if not current or (ev.when - current[-1].when) <= timedelta(hours=window_hours):
            current.append(ev)
        else:
            clusters.append(current)
            current = [ev]
    if current:
        clusters.append(current)
    return clusters


def most_recent_change_before(changes: list, when, window_days: int):
    horizon = when - timedelta(days=window_days)
    candidates = [c for c in changes if horizon < c.when <= when]
    if not candidates:
        return None
    return max(candidates, key=lambda c: c.when)
```

- [ ] **Step 5: Implement the two rules in `pcdiag/rules.py`**

Add imports at top: `from pcdiag.correlate import cluster_by_time, most_recent_change_before`. Then add:

```python
_GPU_KEYWORDS = ("nvidia", "nvlddmkm", "amd", "amdkmdag", "radeon", "geforce", "display")


def _is_gpu_change(change) -> bool:
    text = f"{change.name} {change.source}".lower()
    return change.change_type == "driver" and any(k in text for k in _GPU_KEYWORDS)


def _rule_gpu_driver_instability(timeline: Timeline, config: Config) -> list[Finding]:
    if not timeline.display_resets and not timeline.crashes:
        return []
    gpu_changes = [c for c in timeline.changes if _is_gpu_change(c)]
    gpu_driver = next((d for d in timeline.drivers
                       if d.device_class.lower() == "display"), None)
    if not gpu_changes and not (gpu_driver and gpu_driver.install_date):
        return []

    change_when = None
    change_label = None
    if gpu_changes:
        recent = max(gpu_changes, key=lambda c: c.when)
        change_when, change_label = recent.when, f"{recent.name} {recent.version or ''}".strip()
    elif gpu_driver and gpu_driver.install_date:
        change_when = gpu_driver.install_date
        change_label = f"{gpu_driver.name} {gpu_driver.version}"

    resets_after = [r for r in timeline.display_resets if r.when >= change_when]
    tdr_bugchecks = [c for c in timeline.crashes
                     if c.bugcheck_code in ("0x116", "0x117") and c.when >= change_when]

    signals = 0
    evidence = [Evidence(label="GPU driver change",
                         detail=f"{change_label} installed", when=change_when)]
    if resets_after:
        signals += 1
        evidence.append(Evidence(
            label="Display resets (TDR)",
            detail=f"{len(resets_after)} display-driver resets after the change",
            when=resets_after[-1].when))
    if tdr_bugchecks:
        signals += 1
        evidence.append(Evidence(
            label="GPU bugchecks",
            detail=f"{len(tdr_bugchecks)} x {tdr_bugchecks[0].bugcheck_code} bugchecks after the change",
            when=tdr_bugchecks[-1].when))

    if signals == 0:
        return []
    confidence = Confidence.HIGH if signals >= 2 else Confidence.MEDIUM
    return [Finding(
        id="gpu_driver_instability",
        title="GPU driver instability after a recent driver change",
        category="graphics",
        severity=Severity.CRITICAL,
        confidence=confidence,
        evidence=evidence,
        recommendation=(
            "Roll back the GPU driver to the previous stable version, or do a "
            "clean reinstall with DDU. Test stability before installing a newer build."),
    )]


def _rule_change_vs_symptom(timeline: Timeline, config: Config) -> list[Finding]:
    if not timeline.changes or not timeline.crashes:
        return []
    clusters = cluster_by_time(timeline.crashes, config.cluster_window_hours)
    findings: list[Finding] = []
    for cluster in clusters:
        if len(cluster) < config.min_cluster_size:
            continue
        onset = min(c.when for c in cluster)
        suspect = most_recent_change_before(
            timeline.changes, onset, config.change_window_days)
        if suspect is None:
            continue
        findings.append(Finding(
            id="change_vs_symptom",
            title="Crash cluster follows a recent system change",
            category="stability",
            severity=Severity.WARNING,
            confidence=Confidence.MEDIUM,
            evidence=[
                Evidence(label="Crash cluster",
                         detail=f"{len(cluster)} crashes starting", when=onset),
                Evidence(label="Preceding change",
                         detail=f"{suspect.change_type}: {suspect.name} {suspect.version or ''}".strip(),
                         when=suspect.when),
            ],
            recommendation=(
                f"Review the change '{suspect.name}' made on "
                f"{suspect.when.date()}; if the crashes began right after it, "
                "consider reverting it and retesting."),
        ))
    return findings
```

Register both in `RULES` (keep the placeholder or remove it — either is fine):

```python
RULES: list[Callable[[Timeline, Config], list[Finding]]] = [
    _rule_gpu_driver_instability,
    _rule_change_vs_symptom,
]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_rules.py -v`
Expected: PASS. Also run full suite: `python -m pytest -v`.

- [ ] **Step 7: Commit**

```bash
git add pcdiag/correlate.py pcdiag/rules.py tests/test_rules.py tests/fixtures/scenario_gpu_crash
git commit -m "feat: GPU driver instability + change-vs-symptom rules"
```

---

### Task 7: Remaining collectors and their normalization

Adds whea, storage/SMART, reliability, updates, minidump, memory_diag. Each follows the Task 1 contract and Task 2 normalizer pattern.

**Files:**
- Create: `collectors/whea.ps1`, `collectors/storage_smart.ps1`, `collectors/reliability.ps1`, `collectors/updates.ps1`, `collectors/minidump.ps1`, `collectors/memory_diag.ps1`
- Create fixtures: `tests/fixtures/whea.json`, `storage_smart.json`, `minidump.json`, `memory_diag.json`
- Modify: `pcdiag/normalize.py` (add normalizers + registry)
- Modify: `tests/test_normalize.py`

**Interfaces:**
- Consumes: `Timeline`, `WheaError`, `Disk`, `MemoryDiagResult`, `MinidumpFile`, `ChangeEntry`.
- Produces: normalizers registered as `"whea"`, `"storage_smart"`, `"reliability"`, `"updates"`, `"minidump"`, `"memory_diag"`. `reliability` and `updates` feed `timeline.changes` (reliability adds failed-update/app-crash context is out of scope here; `updates` appends `os_update` changes to complement the `changes` collector). WHEA rows: `{when, severity, error_source, event_id}`. Storage rows: `{model, wear_pct, reallocated_sectors, read_errors, write_errors, temperature_c, predictive_failure}`. Minidump rows: `{when, filename, bugcheck_code}`. Memory rows: `{when, result}`.

- [ ] **Step 1: Create fixtures**

`tests/fixtures/whea.json`:

```json
{"collector":"whea","collected_at":"2026-07-25T09:18:00Z","elevated":true,"ok":true,"error":null,
 "data":[{"when":"2026-07-24T14:02:00Z","severity":"corrected","error_source":"PCI Express","event_id":17}]}
```

`tests/fixtures/storage_smart.json`:

```json
{"collector":"storage_smart","collected_at":"2026-07-25T09:18:10Z","elevated":true,"ok":true,"error":null,
 "data":[{"model":"Example NVMe SSD 1TB","wear_pct":6.0,"reallocated_sectors":0,"read_errors":0,"write_errors":0,"temperature_c":41.0,"predictive_failure":false}]}
```

`tests/fixtures/minidump.json`:

```json
{"collector":"minidump","collected_at":"2026-07-25T09:18:20Z","elevated":false,"ok":true,"error":null,
 "data":[{"when":"2026-07-23T02:11:00Z","filename":"072326-11234-01.dmp","bugcheck_code":null}]}
```

`tests/fixtures/memory_diag.json`:

```json
{"collector":"memory_diag","collected_at":"2026-07-25T09:18:30Z","elevated":false,"ok":true,"error":null,
 "data":[{"when":"2026-07-20T07:00:00Z","result":"The Windows Memory Diagnostic tested the computer's memory and detected no errors."}]}
```

- [ ] **Step 2: Write failing test**

Append to `tests/test_normalize.py`:

```python
def test_build_timeline_maps_remaining_collectors():
    timeline = build_timeline(
        results_from("whea", "storage_smart", "minidump", "memory_diag"))
    assert timeline.whea_errors[0].error_source == "PCI Express"
    assert timeline.disks[0].wear_pct == 6.0
    assert timeline.minidumps[0].filename.endswith(".dmp")
    assert "no errors" in timeline.memory_diags[0].result
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/test_normalize.py::test_build_timeline_maps_remaining_collectors -v`
Expected: FAIL.

- [ ] **Step 4: Add normalizers to `pcdiag/normalize.py`**

Add imports `WheaError, Disk, MemoryDiagResult, MinidumpFile`, then:

```python
def _norm_whea(result: CollectorResult, timeline: Timeline) -> None:
    for row in result.data:
        when = _iso(row.get("when"))
        if when is None:
            continue
        timeline.whea_errors.append(WheaError(
            when=when, severity=row.get("severity", ""),
            error_source=row.get("error_source", ""),
            event_id=int(row.get("event_id") or 0)))


def _norm_storage_smart(result: CollectorResult, timeline: Timeline) -> None:
    for row in result.data:
        timeline.disks.append(Disk(
            model=row.get("model", ""),
            wear_pct=row.get("wear_pct"),
            reallocated_sectors=row.get("reallocated_sectors"),
            read_errors=row.get("read_errors"),
            write_errors=row.get("write_errors"),
            temperature_c=row.get("temperature_c"),
            predictive_failure=bool(row.get("predictive_failure", False))))


def _norm_minidump(result: CollectorResult, timeline: Timeline) -> None:
    for row in result.data:
        when = _iso(row.get("when"))
        if when is None:
            continue
        timeline.minidumps.append(MinidumpFile(
            when=when, filename=row.get("filename", ""),
            bugcheck_code=row.get("bugcheck_code")))


def _norm_memory_diag(result: CollectorResult, timeline: Timeline) -> None:
    for row in result.data:
        when = _iso(row.get("when"))
        if when is None:
            continue
        timeline.memory_diags.append(MemoryDiagResult(
            when=when, result=row.get("result", "")))


def _norm_updates(result: CollectorResult, timeline: Timeline) -> None:
    for row in result.data:
        when = _iso(row.get("when"))
        if when is None:
            continue
        timeline.changes.append(ChangeEntry(
            when=when, change_type="os_update",
            name=row.get("name", ""), version=row.get("version"),
            source="updates"))


def _norm_reliability(result: CollectorResult, timeline: Timeline) -> None:
    # Reliability records enrich change context; map failed installs as changes.
    for row in result.data:
        when = _iso(row.get("when"))
        if when is None or row.get("change_type") is None:
            continue
        timeline.changes.append(ChangeEntry(
            when=when, change_type=row.get("change_type"),
            name=row.get("name", ""), version=row.get("version"),
            source="reliability"))
```

Register all six in `NORMALIZERS`:

```python
    "whea": _norm_whea,
    "storage_smart": _norm_storage_smart,
    "minidump": _norm_minidump,
    "memory_diag": _norm_memory_diag,
    "updates": _norm_updates,
    "reliability": _norm_reliability,
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_normalize.py -v`
Expected: PASS.

- [ ] **Step 6: Create `collectors/whea.ps1`**

```powershell
$ErrorActionPreference = 'Stop'
function Test-Elevated { $id=[Security.Principal.WindowsIdentity]::GetCurrent();
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
$out=[ordered]@{collector='whea';collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ');elevated=Test-Elevated;ok=$true;error=$null;data=@()}
try {
  $since=(Get-Date).AddDays(-30); $rows=@()
  $ev=Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Microsoft-Windows-WHEA-Logger';StartTime=$since} -ErrorAction SilentlyContinue
  foreach ($e in $ev) {
    $sev = switch ($e.Id) { {$_ -in 17,47} {'corrected'} {$_ -in 18,19} {'uncorrected'} default {'informational'} }
    $rows += [ordered]@{ when=$e.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); severity=$sev; error_source=(($e.Message -split "`n")[0].Trim()); event_id=$e.Id }
  }
  $out.data=@($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
```

- [ ] **Step 7: Create `collectors/storage_smart.ps1`**

```powershell
$ErrorActionPreference = 'Stop'
function Test-Elevated { $id=[Security.Principal.WindowsIdentity]::GetCurrent();
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
$out=[ordered]@{collector='storage_smart';collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ');elevated=Test-Elevated;ok=$true;error=$null;data=@()}
try {
  $rows=@()
  foreach ($d in (Get-PhysicalDisk -ErrorAction SilentlyContinue)) {
    $rc = $d | Get-StorageReliabilityCounter -ErrorAction SilentlyContinue
    $pf = $false
    try { $pf = ($d.HealthStatus -ne 'Healthy') } catch {}
    $rows += [ordered]@{
      model=$d.FriendlyName
      wear_pct=$(if($rc){$rc.Wear}else{$null})
      reallocated_sectors=$null
      read_errors=$(if($rc){$rc.ReadErrorsTotal}else{$null})
      write_errors=$(if($rc){$rc.WriteErrorsTotal}else{$null})
      temperature_c=$(if($rc){$rc.Temperature}else{$null})
      predictive_failure=$pf
    }
  }
  $out.data=@($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
```

- [ ] **Step 8: Create `collectors/minidump.ps1`**

```powershell
$ErrorActionPreference = 'Stop'
function Test-Elevated { $id=[Security.Principal.WindowsIdentity]::GetCurrent();
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
$out=[ordered]@{collector='minidump';collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ');elevated=Test-Elevated;ok=$true;error=$null;data=@()}
try {
  $rows=@(); $dir=Join-Path $env:windir 'Minidump'
  if (Test-Path $dir) {
    foreach ($f in (Get-ChildItem $dir -Filter *.dmp -ErrorAction SilentlyContinue)) {
      $rows += [ordered]@{ when=$f.LastWriteTimeUtc.ToString('yyyy-MM-ddTHH:mm:ssZ'); filename=$f.Name; bugcheck_code=$null }
    }
  }
  $out.data=@($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
```

- [ ] **Step 9: Create `collectors/memory_diag.ps1`**

```powershell
$ErrorActionPreference = 'Stop'
function Test-Elevated { $id=[Security.Principal.WindowsIdentity]::GetCurrent();
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
$out=[ordered]@{collector='memory_diag';collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ');elevated=Test-Elevated;ok=$true;error=$null;data=@()}
try {
  $rows=@()
  $ev=Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Microsoft-Windows-MemoryDiagnostics-Results'} -MaxEvents 20 -ErrorAction SilentlyContinue
  foreach ($e in $ev) {
    $rows += [ordered]@{ when=$e.TimeCreated.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); result=(($e.Message -split "`n")[0].Trim()) }
  }
  $out.data=@($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
```

- [ ] **Step 10: Create `collectors/updates.ps1`**

```powershell
$ErrorActionPreference = 'Stop'
function Test-Elevated { $id=[Security.Principal.WindowsIdentity]::GetCurrent();
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
$out=[ordered]@{collector='updates';collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ');elevated=Test-Elevated;ok=$true;error=$null;data=@()}
try {
  $rows=@(); $since=(Get-Date).AddDays(-60)
  $searcher=(New-Object -ComObject Microsoft.Update.Session).CreateUpdateSearcher()
  $count=$searcher.GetTotalHistoryCount()
  if ($count -gt 0) {
    foreach ($h in $searcher.QueryHistory(0,[math]::Min($count,100))) {
      if ($h.Date -ge $since -and $h.Title) {
        $kb=[regex]::Match($h.Title,'KB\d+')
        $rows += [ordered]@{ when=([datetime]$h.Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); name=$(if($kb.Success){$kb.Value}else{$h.Title}); version=$null }
      }
    }
  }
  $out.data=@($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
```

- [ ] **Step 11: Create `collectors/reliability.ps1`**

```powershell
$ErrorActionPreference = 'Stop'
function Test-Elevated { $id=[Security.Principal.WindowsIdentity]::GetCurrent();
  (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) }
$out=[ordered]@{collector='reliability';collected_at=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ');elevated=Test-Elevated;ok=$true;error=$null;data=@()}
try {
  $rows=@()
  $recs=Get-CimInstance Win32_ReliabilityRecords -ErrorAction SilentlyContinue
  foreach ($r in $recs) {
    # SourceName 'Microsoft-Windows-WindowsUpdateClient' with EventIdentifier 20 == install failure.
    $ct=$null
    if ($r.SourceName -like '*WindowsUpdate*' -and $r.message -match 'fail') { $ct='update' }
    if ($ct) {
      $when=[Management.ManagementDateTimeConverter]::ToDateTime($r.TimeGenerated).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
      $rows += [ordered]@{ when=$when; change_type=$ct; name=$r.ProductName; version=$null }
    }
  }
  $out.data=@($rows)
} catch { $out.ok=$false; $out.error=$_.Exception.Message }
$out | ConvertTo-Json -Depth 6 -Compress
```

- [ ] **Step 12: Smoke-test all six collectors**

Run each; confirm `"ok": true`. Note `whea`, `storage_smart`, and full `reliability` data are richer when run elevated — that is expected and handled by elevation reporting.

- [ ] **Step 13: Commit**

```bash
git add collectors tests/fixtures pcdiag/normalize.py tests/test_normalize.py
git commit -m "feat: whea, storage/SMART, minidump, memory, updates, reliability collectors"
```

---

### Task 8: Remaining rules — shutdown pattern, WHEA, SMART, memory, failed-update

Completes the Level 1 rule set.

**Files:**
- Modify: `pcdiag/rules.py`
- Modify: `tests/test_rules.py`
- Create: `tests/fixtures/scenario_ssd_wear.json`, `tests/fixtures/scenario_whea.json`

**Interfaces:**
- Consumes: `Timeline`, `Config`, existing `Finding`/`Severity`/`Confidence`.
- Produces rules `_rule_unexpected_shutdowns`, `_rule_whea_hardware`, `_rule_ssd_degradation`, `_rule_memory_errors`, `_rule_failed_updates`, all registered in `RULES`.

- [ ] **Step 1: Create scenario fixtures**

`tests/fixtures/scenario_ssd_wear.json`:

```json
{"collector":"storage_smart","collected_at":"2026-07-25T09:20:00Z","elevated":true,"ok":true,"error":null,
 "data":[{"model":"Example SSD 240","wear_pct":88.0,"reallocated_sectors":120,"read_errors":5,"write_errors":9,"temperature_c":52.0,"predictive_failure":true}]}
```

`tests/fixtures/scenario_whea.json`:

```json
{"collector":"whea","collected_at":"2026-07-25T09:20:10Z","elevated":true,"ok":true,"error":null,
 "data":[
  {"when":"2026-07-24T10:00:00Z","severity":"uncorrected","error_source":"Processor Core","event_id":18},
  {"when":"2026-07-24T11:00:00Z","severity":"uncorrected","error_source":"Processor Core","event_id":18},
  {"when":"2026-07-24T12:00:00Z","severity":"uncorrected","error_source":"Processor Core","event_id":18}]}
```

- [ ] **Step 2: Write failing tests**

Append to `tests/test_rules.py`:

```python
def single(name):
    raw = json.loads((FIXTURES / f"{name}.json").read_text("utf-8"))
    return build_timeline({parse_collector_result(raw).collector: parse_collector_result(raw)})


def test_ssd_degradation_flagged():
    timeline = single("scenario_ssd_wear")
    findings = run_rules(timeline, cfg())
    assert any(f.id == "ssd_degradation" for f in findings)


def test_whea_hardware_high_when_uncorrected_repeats():
    timeline = single("scenario_whea")
    findings = run_rules(timeline, cfg())
    whea = [f for f in findings if f.id == "whea_hardware"]
    assert whea and whea[0].confidence == Confidence.HIGH
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/test_rules.py -k "ssd or whea" -v`
Expected: FAIL.

- [ ] **Step 4: Implement the five rules in `pcdiag/rules.py`**

```python
def _rule_unexpected_shutdowns(timeline: Timeline, config: Config) -> list[Finding]:
    dirty = [c for c in timeline.crashes
             if c.kind in ("unexpected_shutdown", "dirty_shutdown")]
    if len(dirty) < config.min_cluster_size:
        return []
    conf = Confidence.HIGH if len(dirty) >= 4 else Confidence.MEDIUM
    return [Finding(
        id="unexpected_shutdowns", title="Recurring unexpected shutdowns",
        category="stability", severity=Severity.WARNING, confidence=conf,
        evidence=[Evidence(label="Dirty shutdowns",
                           detail=f"{len(dirty)} unexpected shutdowns in the last 30 days",
                           when=max(c.when for c in dirty))],
        recommendation=("Unexpected shutdowns point to power, thermal, or hardware "
                        "faults. Check PSU/power settings and correlate with WHEA and "
                        "thermal findings."))]


def _rule_whea_hardware(timeline: Timeline, config: Config) -> list[Finding]:
    if not timeline.whea_errors:
        return []
    uncorrected = [w for w in timeline.whea_errors if w.severity == "uncorrected"]
    if uncorrected:
        conf = Confidence.HIGH if len(uncorrected) >= 2 else Confidence.MEDIUM
        sev = Severity.CRITICAL
        detail = f"{len(uncorrected)} uncorrected hardware errors ({uncorrected[0].error_source})"
    else:
        if len(timeline.whea_errors) < 3:
            return []
        conf, sev = Confidence.LOW, Severity.WARNING
        detail = f"{len(timeline.whea_errors)} corrected hardware errors"
    return [Finding(
        id="whea_hardware", title="Hardware errors reported by WHEA",
        category="hardware", severity=sev, confidence=conf,
        evidence=[Evidence(label="WHEA errors", detail=detail,
                           when=max(w.when for w in timeline.whea_errors))],
        recommendation=("Uncorrected WHEA errors indicate failing CPU/memory/PCIe "
                        "hardware. Run memory diagnostics, reseat components, and check "
                        "temperatures; if persistent, test/replace the implicated part."))]


def _rule_ssd_degradation(timeline: Timeline, config: Config) -> list[Finding]:
    findings = []
    for disk in timeline.disks:
        reasons = []
        if disk.predictive_failure:
            reasons.append("SMART predictive-failure flag set")
        if disk.wear_pct is not None and disk.wear_pct >= 80:
            reasons.append(f"wear at {disk.wear_pct}%")
        if (disk.reallocated_sectors or 0) > 0:
            reasons.append(f"{disk.reallocated_sectors} reallocated sectors")
        if (disk.read_errors or 0) + (disk.write_errors or 0) > 0:
            reasons.append(f"{(disk.read_errors or 0)+(disk.write_errors or 0)} I/O errors")
        if not reasons:
            continue
        conf = Confidence.HIGH if disk.predictive_failure else Confidence.MEDIUM
        findings.append(Finding(
            id="ssd_degradation", title=f"Storage health degraded: {disk.model}",
            category="storage", severity=Severity.CRITICAL, confidence=conf,
            evidence=[Evidence(label="SMART", detail="; ".join(reasons))],
            recommendation=("Back up data now and plan to replace this drive. Failing "
                            "storage can cause freezes, corruption, and boot failures.")))
    return findings


def _rule_memory_errors(timeline: Timeline, config: Config) -> list[Finding]:
    mem_bugchecks = [c for c in timeline.crashes
                     if c.bugcheck_code in ("0x1a", "0x50", "0x4e", "0x1e")]
    failed_diag = [m for m in timeline.memory_diags if "no errors" not in m.result.lower()]
    if not mem_bugchecks and not failed_diag:
        return []
    signals = (1 if mem_bugchecks else 0) + (1 if failed_diag else 0)
    conf = Confidence.MEDIUM if signals >= 2 else Confidence.LOW
    ev = []
    if mem_bugchecks:
        ev.append(Evidence(label="Memory bugchecks",
                           detail=f"{len(mem_bugchecks)} memory-related bugchecks",
                           when=max(c.when for c in mem_bugchecks)))
    if failed_diag:
        ev.append(Evidence(label="Memory diagnostic", detail=failed_diag[0].result,
                           when=failed_diag[0].when))
    return [Finding(
        id="memory_errors", title="Possible RAM instability",
        category="memory", severity=Severity.WARNING, confidence=conf, evidence=ev,
        recommendation=("Run an extended Windows Memory Diagnostic or MemTest86 overnight. "
                        "If errors appear, test one stick at a time and check XMP/EXPO settings."))]


def _rule_failed_updates(timeline: Timeline, config: Config) -> list[Finding]:
    failed = [c for c in timeline.changes
              if c.source == "reliability" and c.change_type == "update"]
    if len(failed) < 2:
        return []
    return [Finding(
        id="failed_updates", title="Repeated failed updates",
        category="updates", severity=Severity.INFO, confidence=Confidence.MEDIUM,
        evidence=[Evidence(label="Failed updates",
                           detail=f"{len(failed)} failed update attempts",
                           when=max(c.when for c in failed))],
        recommendation=("Run the Windows Update troubleshooter and check disk space; "
                        "repeated update failures can leave the system in an inconsistent state."))]
```

Add all five to `RULES`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest -v`
Expected: PASS (entire suite).

- [ ] **Step 6: Commit**

```bash
git add pcdiag/rules.py tests/test_rules.py tests/fixtures/scenario_ssd_wear.json tests/fixtures/scenario_whea.json
git commit -m "feat: shutdown, WHEA, SSD, memory, failed-update rules"
```

---

### Task 9: Report renderer — HTML + JSON sidecar with Change Timeline

Renders findings, score, and the change timeline into a self-contained HTML file plus a JSON sidecar.

**Files:**
- Create: `templates/report.html.j2`
- Create: `pcdiag/report.py`
- Create: `tests/test_report.py`

**Interfaces:**
- Consumes: `list[Finding]`, `Timeline`, `health_score`, `Config`.
- Produces: `render_report(findings: list[Finding], timeline: Timeline, score: int, out_dir: Path, generated_at: datetime) -> tuple[Path, Path]` returning `(html_path, json_path)`. Writes `report.html` (self-contained) and `report.json`. Also `findings_to_dicts(findings) -> list[dict]` and `timeline_summary(timeline) -> dict` used by the JSON sidecar.

- [ ] **Step 1: Write failing test**

Create `tests/test_report.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_report.py -v`
Expected: FAIL (`ModuleNotFoundError: pcdiag.report`).

- [ ] **Step 3: Create `templates/report.html.j2`**

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PC Health Report — {{ generated_at }}</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; margin: 0; padding: 2rem;
         background: #f6f7f9; color: #1a1a1a; }
  @media (prefers-color-scheme: dark){ body{ background:#15171a; color:#e8e8e8; } .card{ background:#1e2126 !important; } }
  .score { font-size: 3rem; font-weight: 700; }
  .card { background:#fff; border-radius:12px; padding:1rem 1.25rem; margin:.75rem 0;
          box-shadow:0 1px 3px rgba(0,0,0,.08); }
  .sev-critical{ border-left:6px solid #d92d20; }
  .sev-warning{ border-left:6px solid #f79009; }
  .sev-info{ border-left:6px solid #2e90fa; }
  .badge{ display:inline-block; padding:.1rem .5rem; border-radius:999px;
          font-size:.75rem; font-weight:600; background:#eee; color:#333; }
  .evidence{ font-size:.9rem; opacity:.9; margin:.25rem 0; }
  .rec{ margin-top:.5rem; font-style:italic; }
  table{ border-collapse:collapse; width:100%; font-size:.85rem; }
  td,th{ text-align:left; padding:.3rem .5rem; border-bottom:1px solid rgba(128,128,128,.25); }
  h1{ margin:.2rem 0; } .muted{ opacity:.7; font-size:.85rem; }
</style></head><body>
  <h1>PC Health Report</h1>
  <div class="muted">Generated {{ generated_at }}</div>
  <div class="card"><div class="score">{{ score }}<span style="font-size:1rem">/100</span></div>
    <div class="muted">Overall health score</div></div>

  <h2>Issues ({{ findings|length }})</h2>
  {% if not findings %}<div class="card">No issues detected. ✅</div>{% endif %}
  {% for f in findings %}
  <div class="card sev-{{ f.severity.value }}">
    <span class="badge">{{ f.severity.value|upper }}</span>
    <span class="badge">{{ f.confidence.label }} confidence</span>
    <strong> {{ f.title }}</strong>
    {% for e in f.evidence %}
      <div class="evidence">• <b>{{ e.label }}:</b> {{ e.detail }}{% if e.when %} <span class="muted">({{ e.when }})</span>{% endif %}</div>
    {% endfor %}
    <div class="rec">→ {{ f.recommendation }}</div>
  </div>
  {% endfor %}

  <h2>Change Timeline</h2>
  <div class="card">
    {% if changes %}<table><tr><th>When</th><th>Type</th><th>What</th><th>Source</th></tr>
      {% for c in changes %}<tr><td>{{ c.when }}</td><td>{{ c.change_type }}</td><td>{{ c.name }} {{ c.version or '' }}</td><td>{{ c.source }}</td></tr>{% endfor %}
    </table>{% else %}<div class="muted">No recorded changes.</div>{% endif %}
  </div>

  <h2>Collectors</h2>
  <div class="card"><table><tr><th>Collector</th><th>Status</th><th>Elevated</th><th>Note</th></tr>
    {% for m in meta %}<tr><td>{{ m.name }}</td><td>{{ 'ok' if m.ok else 'FAILED' }}</td><td>{{ m.elevated }}</td><td class="muted">{{ m.error or '' }}</td></tr>{% endfor %}
  </table></div>
</body></html>
```

- [ ] **Step 4: Implement `pcdiag/report.py`**

```python
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from pcdiag.models import Timeline
from pcdiag.rules import Finding

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def findings_to_dicts(findings: list[Finding]) -> list[dict]:
    return [{
        "id": f.id, "title": f.title, "category": f.category,
        "severity": f.severity.value, "confidence": f.confidence.value,
        "evidence": [{"label": e.label, "detail": e.detail,
                      "when": e.when.isoformat() if e.when else None} for e in f.evidence],
        "recommendation": f.recommendation,
    } for f in findings]


def timeline_summary(timeline: Timeline) -> dict:
    return {
        "crashes": len(timeline.crashes),
        "display_resets": len(timeline.display_resets),
        "whea_errors": len(timeline.whea_errors),
        "changes": len(timeline.changes),
        "disks": len(timeline.disks),
    }


def render_report(findings: list[Finding], timeline: Timeline, score: int,
                  out_dir: Path, generated_at: datetime) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)),
                      autoescape=select_autoescape(["html"]))
    template = env.get_template("report.html.j2")
    changes = sorted(timeline.changes, key=lambda c: c.when, reverse=True)
    html = template.render(
        findings=findings, score=score,
        generated_at=generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        changes=changes, meta=timeline.meta)
    html_path = out_dir / "report.html"
    json_path = out_dir / "report.json"
    html_path.write_text(html, encoding="utf-8")
    json_path.write_text(json.dumps({
        "generated_at": generated_at.isoformat(),
        "score": score,
        "findings": findings_to_dicts(findings),
        "timeline_summary": timeline_summary(timeline),
    }, indent=2), encoding="utf-8")
    return html_path, json_path
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_report.py -v`
Expected: PASS. (Requires `pip install -r requirements.txt` for Jinja2.)

- [ ] **Step 6: Commit**

```bash
git add templates/report.html.j2 pcdiag/report.py tests/test_report.py
git commit -m "feat: HTML + JSON report renderer with change timeline"
```

---

### Task 10: Orchestrator CLI — end-to-end `diagnose`

Wires collectors → normalize → rules → score → report, with elevation detection and a `--no-open` flag. Includes an integration test that runs the whole pipeline from fixtures (no PowerShell).

**Files:**
- Create: `diagnose.py`
- Create: `pcdiag/pipeline.py`
- Create: `README.md`
- Create: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `pcdiag/pipeline.py`: `COLLECTOR_NAMES: list[str]` (all 11), and `run_pipeline(results: dict[str, CollectorResult], out_dir: Path, config: Config) -> tuple[Path, Path, int]` returning `(html_path, json_path, score)`. This is the pure, testable core (no I/O beyond writing the report).
  - `diagnose.py`: CLI `main()` that runs every collector via `run_collector`, calls `run_pipeline`, prints the score + top findings to the console, and opens the HTML unless `--no-open`.

- [ ] **Step 1: Write failing integration test**

Create `tests/test_pipeline.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

from pcdiag.collectors import parse_collector_result
from pcdiag.config import Config
from pcdiag.pipeline import run_pipeline

FIXTURES = Path(__file__).parent / "fixtures" / "scenario_gpu_crash"


def _results():
    out = {}
    for name in ("crashes", "livekernel_display", "drivers", "changes"):
        raw = json.loads((FIXTURES / f"{name}.json").read_text("utf-8"))
        out[name] = parse_collector_result(raw)
    return out


def test_pipeline_end_to_end_flags_gpu(tmp_path):
    cfg = Config(now=datetime(2026, 7, 25, tzinfo=timezone.utc))
    html, jsn, score = run_pipeline(_results(), tmp_path, cfg)
    assert html.exists() and jsn.exists()
    assert score < 100
    data = json.loads(jsn.read_text("utf-8"))
    assert any(f["id"] == "gpu_driver_instability" for f in data["findings"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL (`ModuleNotFoundError: pcdiag.pipeline`).

- [ ] **Step 3: Implement `pcdiag/pipeline.py`**

```python
from __future__ import annotations

from pathlib import Path

from pcdiag.collectors import CollectorResult
from pcdiag.config import Config
from pcdiag.normalize import build_timeline
from pcdiag.report import render_report
from pcdiag.rules import run_rules
from pcdiag.score import health_score

COLLECTOR_NAMES = [
    "system_snapshot", "crashes", "livekernel_display", "whea", "minidump",
    "drivers", "changes", "updates", "reliability", "storage_smart", "memory_diag",
]


def run_pipeline(results: dict[str, CollectorResult], out_dir: Path,
                 config: Config) -> tuple[Path, Path, int]:
    timeline = build_timeline(results)
    findings = run_rules(timeline, config)
    score = health_score(findings)
    html_path, json_path = render_report(
        findings, timeline, score, out_dir, generated_at=config.now)
    return html_path, json_path, score
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS.

- [ ] **Step 5: Implement `diagnose.py`**

```python
from __future__ import annotations

import argparse
import webbrowser
from pathlib import Path

from pcdiag.collectors import run_collector
from pcdiag.config import default_config
from pcdiag.pipeline import COLLECTOR_NAMES, run_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="PC Health Intelligence — Level 1")
    parser.add_argument("--out", default="reports", help="output directory")
    parser.add_argument("--no-open", action="store_true", help="do not open the report")
    args = parser.parse_args()

    print("Collecting diagnostics (this may take a minute)...")
    results = {}
    for name in COLLECTOR_NAMES:
        results[name] = run_collector(name)
        status = "ok" if results[name].ok else f"FAILED: {results[name].error}"
        print(f"  - {name}: {status}")

    config = default_config()
    html_path, json_path, score = run_pipeline(results, Path(args.out), config)

    print(f"\nHealth score: {score}/100")
    print(f"Report: {html_path}")
    if not any(r.elevated for r in results.values()):
        print("Note: run as Administrator for SMART/WHEA/full event access.")
    if not args.no_open:
        webbrowser.open(html_path.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Create `README.md`**

```markdown
# PC Health Intelligence — Level 1

On-demand Windows diagnostic tool. Collects crash/driver/change/hardware
telemetry, correlates it on one timeline, and produces a self-contained HTML
report with confidence-scored root causes. **Read-only — never modifies the system.**

## Requirements
- Windows 10/11, PowerShell 5.1+
- Python 3.11+

## Setup
    pip install -r requirements.txt

## Run
    python diagnose.py            # collect, analyze, open report
    python diagnose.py --no-open  # write reports/ without opening

Run from an **Administrator** terminal for full SMART/WHEA/event-log access.

## Test
    python -m pytest -v

## What it detects (Level 1)
GPU driver instability after a driver change, crash clusters following any
system change, recurring unexpected shutdowns, WHEA hardware errors, SSD SMART
degradation, RAM instability, and repeated failed updates.

## Limitations
No live monitoring (on-demand only), best-effort thermals, minidump metadata
only (no deep stack parsing). See `docs/superpowers/specs/` for the design.
```

- [ ] **Step 7: Run the full test suite**

Run: `python -m pytest -v`
Expected: PASS (all tests across every file).

- [ ] **Step 8: End-to-end manual run on this machine**

Run: `python diagnose.py --no-open`
Expected: each collector prints `ok` (some may note elevation), a score prints, and `reports/report.html` + `reports/report.json` exist. Open the HTML and confirm the score, any findings, the Change Timeline (your recent GPU driver update should appear), and the collectors table render.

- [ ] **Step 9: Commit**

```bash
git add diagnose.py pcdiag/pipeline.py README.md tests/test_pipeline.py
git commit -m "feat: end-to-end diagnose CLI + pipeline + README"
```

---

## Self-Review Notes

- **Spec coverage:** on-demand run (Task 10), Python+PowerShell (all), deterministic rules (Tasks 5–6, 8), HTML+JSON output (Task 9), all 11 collectors (Tasks 1, 3, 4, 7), Change Ledger (Task 4) + Change Timeline panel (Task 9), 7 rules incl. GPU flagship + generic change-vs-symptom (Tasks 6, 8), scoring (Task 5), elevation reporting (collectors + Task 10), fixture-based tests (every task), 7-day correlation window (`Config`, Task 5). Thermals intentionally out of Level 1 per spec §8.
- **Type consistency:** `CollectorResult`, `Timeline` + members, `Config`, `Severity`/`Confidence`/`Evidence`/`Finding`, `run_rules`, `health_score`, `render_report`, `run_pipeline`, `run_collector` names are used identically across tasks.
- **Placeholder scan:** the only intentionally-empty function, `_rule_healthy_placeholder`, is replaced by real rules in Task 6; safe to remove then.
```
