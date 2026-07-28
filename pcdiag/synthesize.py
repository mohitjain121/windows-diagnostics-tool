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


_DISCRETE_GPU = ("radeon rx", "radeon pro", "geforce", "rtx", "gtx", "arc a")
_INTEGRATED_GPU = ("radeon graphics", "radeon(tm) graphics", "uhd graphics",
                   "iris", "hd graphics")
_TUNING_TOOLS = ("ryzen master", "afterburner", "overclock", "tuning",
                 "precision boost", "wattman")

_MEM_BUGCHECKS = ("0x1a", "0x50", "0x4e", "0x1e")


def _has_discrete_gpu(timeline: Timeline) -> bool:
    if not timeline.snapshot:
        return False
    for name in timeline.snapshot.gpu_names:
        name_lower = name.lower()
        if any(k in name_lower for k in _DISCRETE_GPU):
            return True
    return False


def _has_integrated_gpu(timeline: Timeline) -> bool:
    if not timeline.snapshot:
        return False
    for name in timeline.snapshot.gpu_names:
        name_lower = name.lower()
        # Integrated GPU is present if this name contains an integrated marker
        # AND does NOT contain a discrete marker (to exclude discrete cards like "Radeon RX Vega")
        has_integrated_marker = any(k in name_lower for k in _INTEGRATED_GPU)
        has_discrete_marker = any(k in name_lower for k in _DISCRETE_GPU)
        if has_integrated_marker and not has_discrete_marker:
            return True
    return False


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
