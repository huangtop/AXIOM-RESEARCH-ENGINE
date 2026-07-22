from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class SECCompanyFactsValidationError(ValueError):
    """Raised when a SEC Company Facts payload does not match the expected shape."""


@dataclass(frozen=True, slots=True)
class SECObservation:
    value: int | float | str
    accession_number: str | None = None
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    form: str | None = None
    filed: str | None = None
    start: str | None = None
    end: str | None = None
    frame: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SECObservation":
        if "val" not in payload:
            raise SECCompanyFactsValidationError("observation is missing val")
        value = payload["val"]
        if not isinstance(value, (int, float, str)) or isinstance(value, bool):
            raise SECCompanyFactsValidationError("observation val must be a number or string")
        fiscal_year = payload.get("fy")
        if fiscal_year is not None and not isinstance(fiscal_year, int):
            raise SECCompanyFactsValidationError("observation fy must be an integer")
        return cls(
            value=value,
            accession_number=_optional_string(payload.get("accn")),
            fiscal_year=fiscal_year,
            fiscal_period=_optional_string(payload.get("fp")),
            form=_optional_string(payload.get("form")),
            filed=_optional_string(payload.get("filed")),
            start=_optional_string(payload.get("start")),
            end=_optional_string(payload.get("end")),
            frame=_optional_string(payload.get("frame")),
        )


@dataclass(frozen=True, slots=True)
class SECUnitSeries:
    unit: str
    observations: tuple[SECObservation, ...]


@dataclass(frozen=True, slots=True)
class SECFact:
    taxonomy: str
    concept: str
    label: str
    description: str
    units: tuple[SECUnitSeries, ...]

    @property
    def observation_count(self) -> int:
        return sum(len(series.observations) for series in self.units)


@dataclass(frozen=True, slots=True)
class SECCompanyFacts:
    cik: str
    entity_name: str
    facts: tuple[SECFact, ...]
    raw_payload: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SECCompanyFacts":
        cik = _normalize_payload_cik(payload.get("cik"))
        entity_name = payload.get("entityName")
        if not isinstance(entity_name, str) or not entity_name.strip():
            raise SECCompanyFactsValidationError("entityName must be a non-empty string")
        raw_facts = payload.get("facts")
        if not isinstance(raw_facts, Mapping):
            raise SECCompanyFactsValidationError("facts must be an object")

        facts: list[SECFact] = []
        for taxonomy, concepts in raw_facts.items():
            if not isinstance(taxonomy, str) or not isinstance(concepts, Mapping):
                raise SECCompanyFactsValidationError("taxonomy entries must be objects")
            for concept, fact_payload in concepts.items():
                if not isinstance(concept, str) or not isinstance(fact_payload, Mapping):
                    raise SECCompanyFactsValidationError("fact entries must be objects")
                label = fact_payload.get("label", concept)
                description = fact_payload.get("description", "")
                units_payload = fact_payload.get("units")
                if not isinstance(label, str) or not isinstance(description, str):
                    raise SECCompanyFactsValidationError(
                        "fact label and description must be strings"
                    )
                if not isinstance(units_payload, Mapping):
                    raise SECCompanyFactsValidationError("fact units must be an object")
                unit_series: list[SECUnitSeries] = []
                for unit, observations_payload in units_payload.items():
                    if not isinstance(unit, str) or not isinstance(observations_payload, list):
                        raise SECCompanyFactsValidationError("unit observations must be arrays")
                    observations = tuple(
                        SECObservation.from_mapping(item)
                        for item in observations_payload
                        if isinstance(item, Mapping)
                    )
                    if len(observations) != len(observations_payload):
                        raise SECCompanyFactsValidationError("observations must be objects")
                    unit_series.append(SECUnitSeries(unit=unit, observations=observations))
                facts.append(
                    SECFact(
                        taxonomy=taxonomy,
                        concept=concept,
                        label=label,
                        description=description,
                        units=tuple(unit_series),
                    )
                )
        return cls(
            cik=cik,
            entity_name=entity_name.strip(),
            facts=tuple(facts),
            raw_payload=dict(payload),
        )

    @classmethod
    def from_json(cls, text: str) -> "SECCompanyFacts":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SECCompanyFactsValidationError("invalid Company Facts JSON") from exc
        if not isinstance(payload, Mapping):
            raise SECCompanyFactsValidationError("Company Facts payload must be an object")
        return cls.from_mapping(payload)

    @property
    def fact_count(self) -> int:
        return len(self.facts)

    @property
    def observation_count(self) -> int:
        return sum(fact.observation_count for fact in self.facts)

    def write_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.raw_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
        return target

    def find_fact(self, taxonomy: str, concept: str) -> SECFact | None:
        return next(
            (
                fact
                for fact in self.facts
                if fact.taxonomy == taxonomy and fact.concept == concept
            ),
            None,
        )


def normalize_cik(value: str | int) -> str:
    text = str(value).strip().upper()
    if text.startswith("CIK"):
        text = text[3:]
    if not text.isdigit():
        raise ValueError("CIK must contain digits only")
    number = int(text)
    if number <= 0 or number > 9_999_999_999:
        raise ValueError("CIK is outside the supported range")
    return f"{number:010d}"


def _normalize_payload_cik(value: object) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise SECCompanyFactsValidationError("cik must be a string or integer")
    try:
        return normalize_cik(value)
    except ValueError as exc:
        raise SECCompanyFactsValidationError("invalid cik") from exc


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SECCompanyFactsValidationError("optional observation fields must be strings")
    return value
