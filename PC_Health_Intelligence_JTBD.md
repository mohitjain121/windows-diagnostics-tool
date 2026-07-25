# PC Health Intelligence

## Purpose

Build an intelligent PC diagnostics capability that continuously
monitors system health, explains problems before they become failures,
and converts scattered Windows telemetry into clear, actionable
insights.

## Job To Be Done

When my PC becomes slow, unstable, or starts crashing, automatically
collect relevant diagnostics, correlate the evidence, identify the most
likely root cause, explain the reasoning, and recommend the next
actions. The goal is to replace manual debugging across multiple Windows
tools with a single trustworthy diagnostic report.

## Core Capabilities

-   Monitor hardware health (CPU, GPU, RAM, SSD, motherboard, thermals).
-   Analyse Windows health, drivers, updates, crashes, and reliability.
-   Correlate signals across logs instead of reporting isolated events.
-   Detect performance regressions, hardware failures, driver
    instability, and resource bottlenecks.
-   Maintain historical trends to explain **what changed** and **when**.
-   Generate confidence-scored root cause analyses with supporting
    evidence.
-   Notify only for meaningful issues such as recurring crashes,
    LiveKernelEvents, SMART degradation, WHEA errors, thermal
    throttling, or abnormal performance regressions.

## Outputs

Produce concise reports containing: - Overall health score - Critical
and emerging issues - Likely root causes - Supporting evidence -
Confidence level - Recommended actions - Historical comparison with
previous reports

Support both on-demand diagnostics and proactive alerts when new
high-confidence issues are detected.

## Principles

-   Prioritise explanation over raw data.
-   Correlate multiple signals before reaching conclusions.
-   Minimise false positives and alert fatigue.
-   Surface only actionable insights.
-   Continuously improve accuracy using historical system behaviour.

## Non-Goals

This capability should **not** automatically modify the system, install
or remove drivers, change BIOS settings, overclock hardware, terminate
processes, or repair issues. Its responsibility is to **observe,
analyse, explain, prioritise, and recommend**.
