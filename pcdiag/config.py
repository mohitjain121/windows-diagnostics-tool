from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Config:
    now: datetime
    change_window_days: int = 7
    cluster_window_hours: int = 48
    min_cluster_size: int = 2


def default_config() -> Config:
    return Config(now=datetime.now(timezone.utc))
