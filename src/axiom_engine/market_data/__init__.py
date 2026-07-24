"""Canonical Market Data Layer with V021 compatibility.

The V025.5 API is exposed through ``build_market_data`` and ``write_template``.
Repositories that still contain the V021 importer/models/validator modules keep
using their original API through ``import_market_data`` and the legacy model and
exception exports.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .core import (
    MarketDataError,
    build_market_data,
    validate_market_data as _validate_canonical_market_data,
    write_template,
)

try:  # V021 compatibility modules remain in upgraded repositories.
    from .importer import (
        MarketDataImportError,
        import_market_data as _import_legacy_market_data,
        load_market_data_source,
    )
    from .models import (
        MarketDataSource,
        MarketImportReport,
        MarketObservation,
        MarketProvenance,
        TradingStatus,
    )
    from .validator import (
        MarketDataValidationError,
        validate_market_data as _validate_legacy_market_data,
    )
    _HAS_LEGACY_PIPELINE = True
except ImportError:  # Fresh V025.5-only installations.
    MarketDataImportError = MarketDataError
    MarketDataValidationError = MarketDataError
    MarketDataSource = MarketImportReport = MarketObservation = None
    MarketProvenance = TradingStatus = None
    load_market_data_source = None
    _import_legacy_market_data = None
    _validate_legacy_market_data = None
    _HAS_LEGACY_PIPELINE = False


def import_market_data(*args: Any, **kwargs: Any) -> Any:
    """Run the V021 importer when its calling contract is used.

    New canonical ingestion should call :func:`build_market_data` directly.
    The dispatch keeps historical code and tests working without changing the
    V025.5 canonical output contract.
    """
    legacy_keys = {"company_registry_dir", "dry_run"}
    if _HAS_LEGACY_PIPELINE and (args or legacy_keys.intersection(kwargs)):
        return _import_legacy_market_data(*args, **kwargs)
    return build_market_data(*args, **kwargs)


def validate_market_data(output_dir: str | Path = "data/market_data") -> dict[str, Any]:
    """Validate either a V021 or V025.5 market-data bundle."""
    root = Path(output_dir)
    if _HAS_LEGACY_PIPELINE and (root / "market_observations.json").exists():
        return _validate_legacy_market_data(root)
    return _validate_canonical_market_data(root)


__all__ = [
    "MarketDataError",
    "MarketDataImportError",
    "MarketDataValidationError",
    "MarketDataSource",
    "MarketImportReport",
    "MarketObservation",
    "MarketProvenance",
    "TradingStatus",
    "build_market_data",
    "import_market_data",
    "load_market_data_source",
    "validate_market_data",
    "write_template",
]
