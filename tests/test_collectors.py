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
