from datetime import datetime, timezone

from pcdiag.config import Config
from pcdiag.models import Timeline
from pcdiag.synthesize import _load_hours_fraction, run_synthesis


def cfg():
    return Config(now=datetime(2026, 7, 28, tzinfo=timezone.utc))


def test_load_hours_fraction():
    # 3 of 4 in evening/night (>=17 or <6)
    assert _load_hours_fraction([19, 21, 23, 10]) == 0.75
    assert _load_hours_fraction([]) == 0.0


def test_run_synthesis_empty_timeline_returns_empty():
    assert run_synthesis(Timeline(), [], cfg()) == []
