from __future__ import annotations

from datetime import timedelta


def cluster_by_time(events: list, window_hours: int) -> list[list]:
    items = sorted(events, key=lambda e: e.when)
    clusters: list[list] = []
    current: list = []
    for ev in items:
        if not current or (ev.when - current[-1].when) <= timedelta(hours=window_hours):
            current.append(ev)
        else:
            clusters.append(current)
            current = [ev]
    if current:
        clusters.append(current)
    return clusters


def most_recent_change_before(changes: list, when, window_days: int):
    horizon = when - timedelta(days=window_days)
    candidates = [c for c in changes if horizon < c.when <= when]
    if not candidates:
        return None
    return max(candidates, key=lambda c: c.when)
