from __future__ import annotations

import csv
import json
import os
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError

from .models.universe import CompanyMaster, SecurityMaster, ValuationProfileAssignment
from .universe_repository import UniverseIntegrityError, UniverseRepository


class UniverseImportError(RuntimeError):
    """Base error for Universe import operations."""


class UniverseImportFormatError(UniverseImportError, ValueError):
    """Raised when an import file cannot be interpreted."""


class UniverseImportConflictError(UniverseImportError, ValueError):
    """Raised when incoming records conflict with canonical records."""


class ImportMode(StrEnum):
    MERGE = "merge"
    REPLACE = "replace"


class ConflictPolicy(StrEnum):
    ERROR = "error"
    REPLACE = "replace"


@dataclass(frozen=True, slots=True)
class UniverseImportBundle:
    companies: tuple[CompanyMaster, ...] = ()
    securities: tuple[SecurityMaster, ...] = ()
    valuation_profile_assignments: tuple[ValuationProfileAssignment, ...] = ()


@dataclass(frozen=True, slots=True)
class UniverseImportReport:
    source_path: Path
    mode: ImportMode
    dry_run: bool
    incoming_companies: int
    incoming_securities: int
    incoming_valuation_profile_assignments: int
    output_companies: int
    output_securities: int
    output_valuation_profile_assignments: int
    written_files: tuple[Path, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(slots=True)
class UniverseImporter:
    """Parse, validate and atomically write canonical Universe master data."""

    universe_dir: Path
    mode: ImportMode = ImportMode.MERGE
    conflict_policy: ConflictPolicy = ConflictPolicy.ERROR
    _warnings: list[str] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.universe_dir = Path(self.universe_dir)

    def import_file(self, source_path: str | Path, *, dry_run: bool = True) -> UniverseImportReport:
        source = Path(source_path)
        bundle = self.read(source)
        return self.apply(bundle, source_path=source, dry_run=dry_run)

    def read(self, source_path: str | Path) -> UniverseImportBundle:
        path = Path(source_path)
        suffix = path.suffix.lower()
        if suffix == ".json":
            records = self._read_json(path)
        elif suffix == ".csv":
            records = self._read_csv(path)
        else:
            raise UniverseImportFormatError(
                f"unsupported Universe import format {suffix!r}; expected .json or .csv"
            )
        return self._parse_records(records, path)

    def apply(
        self,
        bundle: UniverseImportBundle,
        *,
        source_path: str | Path,
        dry_run: bool = True,
    ) -> UniverseImportReport:
        self._warnings.clear()
        existing = self._load_existing() if self.mode == ImportMode.MERGE else UniverseImportBundle()

        companies = self._combine(existing.companies, bundle.companies, "company_id", "company")
        securities = self._combine(existing.securities, bundle.securities, "security_id", "security")
        assignments = self._combine(
            existing.valuation_profile_assignments,
            bundle.valuation_profile_assignments,
            "assignment_id",
            "valuation profile assignment",
        )

        staged = UniverseImportBundle(
            companies=tuple(companies),
            securities=tuple(securities),
            valuation_profile_assignments=tuple(assignments),
        )
        self._validate_staged(staged)

        written: tuple[Path, ...] = ()
        if not dry_run:
            written = self._write_atomic(staged)

        return UniverseImportReport(
            source_path=Path(source_path),
            mode=self.mode,
            dry_run=dry_run,
            incoming_companies=len(bundle.companies),
            incoming_securities=len(bundle.securities),
            incoming_valuation_profile_assignments=len(bundle.valuation_profile_assignments),
            output_companies=len(staged.companies),
            output_securities=len(staged.securities),
            output_valuation_profile_assignments=len(staged.valuation_profile_assignments),
            written_files=written,
            warnings=tuple(self._warnings),
        )

    def _read_json(self, path: Path) -> list[dict[str, Any]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UniverseImportFormatError(f"cannot read Universe JSON import: {path}") from exc

        if isinstance(payload, list):
            return [self._require_mapping(item, path) for item in payload]
        if not isinstance(payload, dict):
            raise UniverseImportFormatError("Universe JSON must be an object or an array")

        records: list[dict[str, Any]] = []
        keys = {
            "companies": "company",
            "securities": "security",
            "valuation_profile_assignments": "valuation_profile_assignment",
        }
        unknown = set(payload) - set(keys) - {"schema_version", "source"}
        if unknown:
            raise UniverseImportFormatError(
                f"unknown top-level Universe import keys: {', '.join(sorted(unknown))}"
            )
        for key, record_type in keys.items():
            values = payload.get(key, [])
            if not isinstance(values, list):
                raise UniverseImportFormatError(f"{key} must be a JSON array")
            for item in values:
                record = self._require_mapping(item, path)
                record["record_type"] = record_type
                records.append(record)
        return records

    def _read_csv(self, path: Path) -> list[dict[str, Any]]:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames is None or "record_type" not in reader.fieldnames:
                    raise UniverseImportFormatError("Universe CSV requires a record_type column")
                return [self._clean_csv_row(row) for row in reader]
        except OSError as exc:
            raise UniverseImportFormatError(f"cannot read Universe CSV import: {path}") from exc

    @staticmethod
    def _require_mapping(item: Any, path: Path) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise UniverseImportFormatError(f"records in {path} must be JSON objects")
        return dict(item)

    @staticmethod
    def _clean_csv_row(row: dict[str, str | None]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        list_fields = {
            "aliases",
            "classification_ids",
            "valuation_profile_ids",
            "source_ids",
        }
        json_fields = {"metadata"}
        boolean_fields = {"primary_listing"}
        integer_fields = {"priority", "founded_year"}
        float_fields = {"confidence"}

        for key, raw in row.items():
            value = "" if raw is None else raw.strip()
            if value == "":
                continue
            if key in list_fields:
                cleaned[key] = [item.strip() for item in value.split("|") if item.strip()]
            elif key in json_fields:
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise UniverseImportFormatError(f"invalid JSON in CSV column {key}") from exc
                if not isinstance(parsed, dict):
                    raise UniverseImportFormatError(f"CSV column {key} must contain a JSON object")
                cleaned[key] = parsed
            elif key in boolean_fields:
                normalized = value.lower()
                if normalized not in {"true", "false", "1", "0", "yes", "no"}:
                    raise UniverseImportFormatError(f"invalid boolean in CSV column {key}: {value}")
                cleaned[key] = normalized in {"true", "1", "yes"}
            elif key in integer_fields:
                cleaned[key] = int(value)
            elif key in float_fields:
                cleaned[key] = float(value)
            else:
                cleaned[key] = value
        return cleaned

    def _parse_records(
        self, records: Iterable[dict[str, Any]], source_path: Path
    ) -> UniverseImportBundle:
        companies: list[CompanyMaster] = []
        securities: list[SecurityMaster] = []
        assignments: list[ValuationProfileAssignment] = []
        model_by_type = {
            "company": (CompanyMaster, companies),
            "security": (SecurityMaster, securities),
            "valuation_profile_assignment": (ValuationProfileAssignment, assignments),
        }

        for row_number, raw_record in enumerate(records, start=1):
            record = dict(raw_record)
            record_type = str(record.pop("record_type", "")).strip().lower()
            if record_type not in model_by_type:
                raise UniverseImportFormatError(
                    f"{source_path}: record {row_number} has invalid record_type {record_type!r}"
                )
            model_type, destination = model_by_type[record_type]
            try:
                destination.append(model_type.model_validate(record))
            except (ValidationError, ValueError, TypeError) as exc:
                raise UniverseImportFormatError(
                    f"{source_path}: record {row_number} failed {record_type} validation: {exc}"
                ) from exc

        self._assert_unique(companies, "company_id", "incoming company")
        self._assert_unique(securities, "security_id", "incoming security")
        self._assert_unique(assignments, "assignment_id", "incoming assignment")
        return UniverseImportBundle(tuple(companies), tuple(securities), tuple(assignments))

    def _load_existing(self) -> UniverseImportBundle:
        return UniverseImportBundle(
            companies=tuple(self._load_models("companies.json", CompanyMaster)),
            securities=tuple(self._load_models("securities.json", SecurityMaster)),
            valuation_profile_assignments=tuple(
                self._load_models(
                    "valuation_profile_assignments.json", ValuationProfileAssignment
                )
            ),
        )

    def _load_models(self, filename: str, model_type: Any) -> list[Any]:
        path = self.universe_dir / filename
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UniverseImportFormatError(f"cannot read canonical Universe file: {path}") from exc
        if not isinstance(payload, list):
            raise UniverseImportFormatError(f"canonical Universe file must be an array: {path}")
        return [model_type.model_validate(item) for item in payload]

    def _combine(self, existing: Iterable[Any], incoming: Iterable[Any], key: str, label: str) -> list[Any]:
        result = {getattr(item, key): item for item in existing}
        for item in incoming:
            item_id = getattr(item, key)
            current = result.get(item_id)
            if current is not None and current != item:
                if self.conflict_policy == ConflictPolicy.ERROR:
                    raise UniverseImportConflictError(
                        f"incoming {label} conflicts with canonical record: {item_id}"
                    )
                self._warnings.append(f"replaced existing {label}: {item_id}")
            result[item_id] = item
        return [result[item_id] for item_id in sorted(result)]

    @staticmethod
    def _assert_unique(records: Iterable[Any], key: str, label: str) -> None:
        seen: set[str] = set()
        for item in records:
            item_id = getattr(item, key)
            if item_id in seen:
                raise UniverseImportConflictError(f"duplicate {label} ID: {item_id}")
            seen.add(item_id)

    def _validate_staged(self, bundle: UniverseImportBundle) -> None:
        classifications = UniverseRepository._load_models(
            self.universe_dir / "classifications.json",
            __import__(
                "axiom_engine.models.universe", fromlist=["ClassificationNode"]
            ).ClassificationNode,
        )
        valuation_profiles = UniverseRepository._load_models(
            self.universe_dir / "valuation_profile_catalog.json",
            __import__(
                "axiom_engine.models.valuation_catalog",
                fromlist=["ValuationProfileCatalogEntry"],
            ).ValuationProfileCatalogEntry,
        )
        try:
            UniverseRepository(
                companies=bundle.companies,
                securities=bundle.securities,
                classifications=classifications,
                valuation_profile_assignments=bundle.valuation_profile_assignments,
                valuation_profiles=valuation_profiles,
                validate=True,
            )
        except UniverseIntegrityError as exc:
            raise UniverseImportError(str(exc)) from exc

    def _write_atomic(self, bundle: UniverseImportBundle) -> tuple[Path, ...]:
        self.universe_dir.mkdir(parents=True, exist_ok=True)
        payloads = {
            "companies.json": bundle.companies,
            "securities.json": bundle.securities,
            "valuation_profile_assignments.json": bundle.valuation_profile_assignments,
        }
        temp_paths: list[tuple[Path, Path]] = []
        try:
            for filename, records in payloads.items():
                target = self.universe_dir / filename
                fd, temp_name = tempfile.mkstemp(
                    prefix=f".{filename}.", suffix=".tmp", dir=self.universe_dir
                )
                temp = Path(temp_name)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(
                        [record.model_dump(mode="json") for record in records],
                        handle,
                        ensure_ascii=False,
                        indent=2,
                    )
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                temp_paths.append((temp, target))
            for temp, target in temp_paths:
                os.replace(temp, target)
        finally:
            for temp, _ in temp_paths:
                temp.unlink(missing_ok=True)
        return tuple(target for _, target in temp_paths)
