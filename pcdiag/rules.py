from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable

from pcdiag.config import Config
from pcdiag.correlate import cluster_by_time, most_recent_change_before
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


# Change types that represent a deliberate, attributable action worth blaming
# for a crash: real driver-package installs and MSI product install/removal.
# Background churn (Windows/OS updates and Microsoft Store app auto-updates,
# both of which install constantly) is excluded from suspect selection to avoid
# spurious correlations; those still appear in the change timeline for context.
_IMPACTFUL_CHANGES = ("driver", "install", "uninstall")


def _rule_change_vs_symptom(timeline: Timeline, config: Config) -> list[Finding]:
    suspects = [c for c in timeline.changes if c.change_type in _IMPACTFUL_CHANGES]
    if not suspects or not timeline.crashes:
        return []
    clusters = cluster_by_time(timeline.crashes, config.cluster_window_hours)
    findings: list[Finding] = []
    for cluster in clusters:
        if len(cluster) < config.min_cluster_size:
            continue
        onset = min(c.when for c in cluster)
        suspect = most_recent_change_before(
            suspects, onset, config.change_window_days)
        if suspect is None:
            continue
        # Require strong temporal proximity: a change days before the cluster is
        # not a credible trigger. Only blame changes close to the onset.
        if (onset - suspect.when) > timedelta(hours=config.cluster_window_hours):
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


def _rule_unexpected_shutdowns(timeline: Timeline, config: Config) -> list[Finding]:
    dirty = [c for c in timeline.crashes
             if c.kind in ("unexpected_shutdown", "dirty_shutdown")]
    # Count distinct shutdown events (41 and 6008 are paired per event).
    kernel_power = [c for c in dirty if c.event_id == 41]
    count = len(kernel_power) if kernel_power else len(dirty)
    if count < config.min_cluster_size:
        return []
    has_bugcheck = any(c.bugcheck_code for c in timeline.crashes)
    has_dump = bool(timeline.minidumps)
    conf = Confidence.HIGH if count >= 4 else Confidence.MEDIUM
    detail = f"{count} unexpected shutdowns (Kernel-Power 41) in the last 30 days"
    if not has_bugcheck and not has_dump:
        detail += " with no bugcheck code and no crash dump"
        rec = ("Unexpected shutdowns with no bugcheck and no memory dump usually mean "
               "the machine lost power or hard-hung instantly rather than hitting a "
               "software BSOD. Prime suspects: PSU / power delivery, memory "
               "instability (test with EXPO/DOCP disabled), thermals, or a GPU hard-hang. "
               "Enable a kernel/complete memory dump and check PSU + temperatures.")
    else:
        rec = ("Recurring unexpected shutdowns point to power, thermal, or hardware "
               "faults. Correlate with WHEA, memory, and thermal findings and inspect "
               "the crash dumps for a consistent bugcheck code.")
    return [Finding(
        id="unexpected_shutdowns", title="Recurring unexpected shutdowns",
        category="stability", severity=Severity.CRITICAL, confidence=conf,
        evidence=[Evidence(label="Dirty shutdowns", detail=detail,
                           when=max(c.when for c in dirty))],
        recommendation=rec)]


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


RULES: list[Callable[[Timeline, Config], list[Finding]]] = [
    _rule_gpu_driver_instability,
    _rule_change_vs_symptom,
    _rule_unexpected_shutdowns,
    _rule_whea_hardware,
    _rule_ssd_degradation,
    _rule_memory_errors,
    _rule_failed_updates,
]


def run_rules(timeline: Timeline, config: Config) -> list[Finding]:
    findings: list[Finding] = []
    for rule in RULES:
        findings.extend(rule(timeline, config))
    findings.sort(
        key=lambda f: f.severity.weight * f.confidence.multiplier, reverse=True
    )
    return findings
