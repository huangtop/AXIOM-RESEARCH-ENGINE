from __future__ import annotations

import shutil
from datetime import date, timedelta
from pathlib import Path


def prune_dated_snapshots(root: Path, *, retention_days: int, as_of: date | None = None) -> list[str]:
    if retention_days < 1:
        raise ValueError("retention_days must be positive")
    cutoff = (as_of or date.today()) - timedelta(days=retention_days - 1)
    removed: list[str] = []
    if not root.is_dir():
        return removed
    for path in root.iterdir():
        if not path.is_dir():
            continue
        try:
            snapshot_date = date.fromisoformat(path.name)
        except ValueError:
            continue
        if snapshot_date < cutoff:
            shutil.rmtree(path)
            removed.append(path.name)
    return sorted(removed)
