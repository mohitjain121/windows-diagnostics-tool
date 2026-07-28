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
