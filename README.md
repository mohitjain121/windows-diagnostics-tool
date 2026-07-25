# PC Health Intelligence

## Why this exists

Mohit's PC had been getting slower for a while. Everyday use started to lag, the
browser stuttered, more and more programs were launching at startup, and the
machine behaved strangely overnight around sleep. Diagnosing it by hand meant
hopping between a dozen built-in Windows tools and scattered log sources — slow,
tedious, and easy to lose the thread. So instead of chasing data across all
those places, he built one tool that pulls the signals together, correlates
them, and points to the likely cause — turning a long manual hunt into a single
report he can act on.

## What it does

An on-demand, **read-only** diagnostic. It collects system telemetry, lines it
up on one timeline, and produces a confidence-scored report with recommended
next steps. It never changes anything — it only observes, explains, and
recommends.

## Setup & run

Requirements: Windows 10/11 with PowerShell, and Python 3.11+.

```
pip install -r requirements.txt
python diagnose.py          # collect, analyze, open the report
```

Run from an **Administrator** terminal for full hardware/health access. The
report is saved to `reports/`. Run the tests with `python -m pytest`.

## What it detects

Recurring shutdowns and their nature, instability that follows a recent driver
or software change, storage / memory / hardware-error warning signs, sleep
stability problems, and startup and background bloat — each with supporting
evidence and a suggested action.

## What this tool uncovered (and what changed)

Pointed at a real, struggling PC, it broke one vague "my PC is slow" complaint
into distinct, fixable problems:

- **Background bloat and a network-filtering privacy tool** were dragging down
  the browser and the desktop → trimmed startup programs and removed the
  offending background service.
- **The "overnight shutdowns" were a sleep-stability issue, not failing
  hardware** — the machine couldn't stay asleep, driven by a virtualization-based
  security feature → adjusted the relevant sleep and wake settings.
- **Memory was running below its rated speed** → enabled its rated profile in
  firmware.
- **Firmware was out of date** → updated it.

Net result: a faster, quieter, more stable machine — backed by an evidence trail
instead of guesswork.

## Limitations

On-demand only (no live monitoring), best-effort thermals, and crash-dump
metadata only. See `docs/` for the full design and implementation plan.
