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
