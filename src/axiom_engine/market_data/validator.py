from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import MarketObservation, MarketProvenance, TradingStatus


class MarketDataValidationError(RuntimeError):
    pass


def validate_market_data(root: str | Path = "data/market_data") -> dict[str, Any]:
    root = Path(root)
    try:
        observations_raw = json.loads((root / "market_observations.json").read_text(encoding="utf-8"))
        statuses_raw = json.loads((root / "trading_statuses.json").read_text(encoding="utf-8"))
        provenance_raw = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketDataValidationError(f"cannot read market data bundle: {root}") from exc
    observations = [MarketObservation.model_validate(x) for x in observations_raw]
    statuses = [TradingStatus.model_validate(x) for x in statuses_raw]
    provenance = [MarketProvenance.model_validate(x) for x in provenance_raw]
    for name, values in (
        ("market_observation_id", [x.market_observation_id for x in observations]),
        ("trading_status_id", [x.trading_status_id for x in statuses]),
        ("provenance_id", [x.provenance_id for x in provenance]),
    ):
        if len(values) != len(set(values)):
            raise MarketDataValidationError(f"duplicate {name}")
    known = {x.provenance_id for x in provenance}
    for item in [*observations, *statuses]:
        if set(item.provenance_ids) - known:
            raise MarketDataValidationError("market item missing provenance")
    expected = {
        "observation_count": len(observations),
        "trading_status_count": len(statuses),
        "company_count": len({x.company_id for x in [*observations, *statuses]}),
        "security_count": len({x.security_id for x in [*observations, *statuses]}),
        "metric_count": len({x.metric for x in observations}),
        "provenance_count": len(provenance),
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise MarketDataValidationError(f"manifest {key} mismatch")
    return expected
