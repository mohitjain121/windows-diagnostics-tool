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
    parser.add_argument("--sensors", action="store_true",
                        help="opt-in deep hardware sensors (loads a signed driver; needs admin)")
    args = parser.parse_args()

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
