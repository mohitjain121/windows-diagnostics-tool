# PC Health Intelligence — Level 1 Design Spec

**Date:** 2026-07-25
**Status:** Approved for planning
**Source brief:** `PC_Health_Intelligence_JTBD.md`

## 1. Problem & Goal

The user is experiencing recurring PC crashes that worsened after a recent
graphics driver update. Diagnosing this manually — reading Event Viewer,
crash dumps, and scattered Windows logs — is slow and exhausting.

**Goal:** an on-demand tool that collects the relevant Windows telemetry in
one shot, correlates it on a common timeline, identifies the most likely root
cause with a confidence level and supporting evidence, and produces a single
human-readable report with recommended actions.

**Explicit non-goal (from the brief):** the tool never modifies the system.
It does not install/remove drivers, change settings, kill processes, or repair
anything. It only **observes, analyses, explains, prioritises, and recommends.**

## 2. Foundational Decisions (locked)

| Decision | Choice | Rationale |
|---|---|---|
| Run model | **On-demand snapshot** | True bare-minimum; no service, no persistence, no background cost. History/monitoring are later levels. |
| Stack | **Python brain + PowerShell collectors** | PowerShell/WMI/`Get-WinEvent` reach telemetry natively; Python owns correlation, scoring, testing, and rendering. |
| Reasoning | **Deterministic rule engine** | Transparent, testable, offline, no hallucination. Every verdict traces to concrete evidence. Aligns with "minimise false positives." |
| Output | **Self-contained HTML report + JSON sidecar** | Human-readable and shareable; JSON enables future run-to-run diffing. |

## 3. Architecture

A four-stage pipeline. Each stage is an independent unit with a JSON contract
at its boundary, so any stage can be tested or replaced in isolation.

```
[Collectors]      →  [Normalizer]   →  [Correlation/Rules]  →  [Report]
 PowerShell           Python            Python                  HTML + JSON
 emit raw JSON        typed models      Findings + score        renderer
```

- **Collectors (PowerShell):** one small script per data domain. Each *only*
  gathers and prints normalized JSON to stdout — no logic. All Windows-specific
  access is isolated here.
- **Normalizer (Python):** parses collector JSON into typed domain objects
  (`CrashEvent`, `Driver`, `Disk`, `WheaError`, `ChangeEntry`, …) and places
  every event on one common **UTC timeline** — the correlation substrate.
- **Correlation / Rules engine (Python):** deterministic rules turn signals
  into `Finding`s. The brain. Pure function of evidence.
- **Report (Python):** computes the health score, renders a self-contained
  HTML file (inline CSS, no external deps, theme-aware) + a JSON sidecar, and
  opens it.

**Orchestrator:** a `diagnose` CLI runs the stages end to end. Runs **without
admin**, but detects elevation and records in the report which signals were
degraded because they required it (SMART counters, some logs).

### Design principles

- Collectors are "dumb" so their output can be captured as test fixtures.
- The rules engine is a pure function: same logs in → same verdict out.
- No Finding is emitted below a LOW-confidence threshold (anti-alert-fatigue).
- The tool is honest about what it cannot measure (see thermals, §5).

## 4. Collectors (Level 1 set)

Each collector is an independent PowerShell unit emitting normalized JSON.

| Collector | Source | Catches |
|---|---|---|
| **reliability** | `Win32_ReliabilityRecords` (Reliability Monitor) | app crashes, hangs, failed updates, "what changed when" |
| **crashes** | `Get-WinEvent` System log: Event **41** (Kernel-Power/unexpected shutdown), **1001** (BugCheck + code), **6008** | BSODs, dirty shutdowns |
| **livekernel / display** | `Get-WinEvent` **4101** (display driver reset/TDR), LiveKernelReports folder, `nvlddmkm`/`amdkmdag` events | GPU driver "stopped responding," TDR timeouts |
| **whea** | `Get-WinEvent` **WHEA-Logger** (17/18/19/46/47) | CPU / PCIe / memory hardware errors |
| **minidump** | enumerate `C:\Windows\Minidump`, `MEMORY.DMP` metadata | crash frequency, timestamps (deep dump parsing is Level 2) |
| **drivers** | `Win32_PnPSignedDriver` | driver versions + install dates |
| **updates** | Windows Update history / CBS | recent OS & driver update timing |
| **storage/SMART** | `Get-PhysicalDisk` + `Get-StorageReliabilityCounter` | SSD wear, reallocated sectors, read/write errors, temp |
| **memory diag** | Event **1201 / 1101** MemoryDiagnostics-Results | RAM test results, if present |
| **system snapshot** | CIM CPU/RAM/GPU, uptime, current CPU/mem/disk load | inventory + point-in-time resource state |
| **changes** (Change Ledger) | see §4.1 | unified software + driver + OS change timeline |

### 4.1 The Change Ledger (`changes` collector)

A first-class concept, not a bolt-on. Unifies three change streams into one
chronological ledger; each entry carries `{timestamp, type, name, version,
source}`.

| Change stream | Source | Captures |
|---|---|---|
| **Software install / update / uninstall** | `Microsoft-Windows-Application-Experience/Program-Inventory` log (Event **903** installed, **904** updated, **905/906** removed) + `MsiInstaller` events (11707 install, 11724 removal) in the Application log | third-party apps/tools, with when and which version |
| **Driver changes** | `C:\Windows\INF\setupapi.dev.log` (device/driver install timeline) + `Win32_PnPSignedDriver` install dates | every driver install/update — including the GPU driver update |
| **Windows / OS updates** | Windows Update history + CBS | KB / cumulative updates, WU-delivered drivers |

Plus registry `Uninstall` keys as a **current-state cross-check** (what is
installed now + version) to reconcile against the event stream.

The Change Ledger is the **backbone timeline** the crash/error timeline is
overlaid against. It powers a generic change-vs-symptom correlation rule
(§5), of which the GPU-driver case is the highest-confidence instance.

**Level 1 scope honesty:** the ledger is reconstructed from what Windows
already logs — it does *not* install a real-time watcher. Because Windows
retains these logs, an on-demand scan still reconstructs weeks of history.
Real-time change capture is Level 2/3.

## 5. Rules Engine

Rules are data-driven. Each rule inspects the normalized timeline and, if its
evidence pattern matches, emits a `Finding {category, severity, confidence,
evidence[], recommendation}`. Confidence derives from how many independent
signals corroborate, and whether there is a temporal link to a change.

**Correlation window:** a change is considered a suspect for a symptom cluster
if it precedes the cluster's onset within a configurable window, default
**7 days** (`--change-window-days`). The GPU flagship rule uses the same window
for "recent driver install."

### Confidence model

- **LOW** — single weak signal.
- **MEDIUM** — one strong signal, or two weak signals.
- **HIGH** — multiple corroborating signals with a temporal link (e.g.
  change-then-crash).
- Nothing below LOW is surfaced.

### Level 1 rules

1. **GPU driver instability (flagship).** Recent GPU driver install
   (`drivers`/`changes` InstallDate within the correlation window) **+** cluster of TDR/4101 or
   LiveKernelEvent-141 **+** crashes clustered *after* the install →
   **GPU driver instability, HIGH**. Evidence: driver version/date + crash
   timestamps. Recommendation: roll back / DDU clean reinstall of prior driver.
2. **Generic change-vs-symptom.** For any crash/error cluster, look back over
   the Change Ledger for a change preceding onset; if found, name it as prime
   suspect. (GPU case is instance #1; also catches "app update started hangs,"
   "KB broke it.")
3. **Unexpected-shutdown pattern.** Clustering of Event 41 / 6008.
4. **WHEA hardware-error escalation.** Recurring WHEA-Logger errors → hardware
   fault suspicion (CPU/PCIe/memory).
5. **SSD SMART degradation.** Wear, reallocated sectors, read/write error
   growth, predictive-failure status.
6. **Memory-error correlation.** Memory-associated bugcheck codes / WHEA
   memory errors / MemoryDiagnostics results.
7. **Failed-update loop.** Repeated failed installs/updates in reliability +
   update history.

Every Finding is a pure function of evidence — same logs in, same verdict out.

## 6. Report, Scoring, Testing

### Scoring
Health score starts at 100; each active Finding deducts a weight of
`severity × confidence`. Report shows the score, then Critical → Emerging
issues ranked, each expandable to its evidence table and recommendation.

### Report
Self-contained HTML (inline CSS, no external requests, light/dark aware),
opens in the browser. Includes a **Change Timeline** panel; every crash-related
Finding cites its correlated change as evidence. A JSON sidecar is written
next to the HTML for future run-to-run diffing.

### Testing
Collectors are dumb, so real collector JSON is snapshotted as **fixtures** and
the rules engine is unit-tested deterministically ("given these logs, assert
GPU-instability HIGH"). No mocking of Windows; no flaky tests. TDD-friendly.

## 7. Repo Shape

```
collectors/*.ps1            # one PowerShell script per domain
pcdiag/
  normalize.py              # collector JSON → typed models + timeline
  rules.py                  # correlation rules → Findings
  score.py                  # health score
  report.py                 # HTML + JSON rendering
templates/report.html.j2    # self-contained HTML template
tests/fixtures/             # captured collector JSON
tests/                      # rules-engine unit tests
diagnose.py                 # CLI entry point
```

## 8. Known Limitations (Level 1)

- **Thermals:** native Windows exposes almost no reliable temperature/
  throttling data (`MSAcpi_ThermalZoneTemperature` usually absent or bogus).
  Level 1 reports thermals **best-effort** and says "not available" rather than
  guessing. Real thermal monitoring needs vendor sensors (Level 2 optional).
- **Crash dumps:** Level 1 uses minidump *metadata* (count/timestamps/bugcheck
  code). Deep stack/module parsing (WinDbg-style) is Level 2.
- **No real-time capture:** all history is reconstructed from retained Windows
  logs; nothing is watched live. Always-on monitoring + proactive alerts are
  Level 2/3.
- **Elevation:** some signals (SMART counters, certain logs) require admin;
  when absent, the tool degrades gracefully and states so in the report.

## 9. Build Order (recommendation)

1. Pipeline skeleton + orchestrator + `system snapshot` collector.
2. `crashes`, `livekernel/display`, `drivers`, and `changes` collectors.
3. Flagship **GPU driver instability** rule + generic change-vs-symptom rule
   (directly addresses the live problem).
4. HTML report + JSON sidecar with Change Timeline panel.
5. Remaining collectors (whea, storage/SMART, reliability, updates, minidump,
   memory diag) and their rules.
6. Fixture-based test suite throughout.
