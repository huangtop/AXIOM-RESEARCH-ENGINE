from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models.universe import (
    ClassificationNode,
    ClassificationType,
    CompanyMaster,
    SecurityMaster,
    ValuationProfileAssignment,
)
from .models.valuation_catalog import ValuationProfileCatalogEntry


class UniverseRepositoryError(RuntimeError):
    """Base error for Universe repository operations."""


class UniverseRecordNotFoundError(UniverseRepositoryError, LookupError):
    """Raised when a requested Universe record cannot be found."""


class UniverseAmbiguousLookupError(UniverseRepositoryError, LookupError):
    """Raised when a ticker lookup matches more than one security."""


class UniverseIntegrityError(UniverseRepositoryError, ValueError):
    """Raised when Universe records contain broken references."""

    def __init__(self, errors: Iterable[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("Universe integrity validation failed:\n- " + "\n- ".join(self.errors))


@dataclass(frozen=True, slots=True)
class ResolvedCompany:
    """Company aggregate with Universe references resolved."""

    company: CompanyMaster
    securities: tuple[SecurityMaster, ...]
    classifications: tuple[ClassificationNode, ...]
    valuation_assignments: tuple[ValuationProfileAssignment, ...]
    valuation_profiles: tuple[ValuationProfileCatalogEntry, ...]

    @property
    def company_id(self) -> str:
        return self.company.company_id

    @property
    def name(self) -> str:
        return self.company.display_name or self.company.legal_name

    @property
    def research_level(self):
        return self.company.research_level

    @property
    def primary_security(self) -> SecurityMaster | None:
        if self.company.primary_security_id is not None:
            for security in self.securities:
                if security.security_id == self.company.primary_security_id:
                    return security
        return next((security for security in self.securities if security.primary_listing), None)

    @property
    def themes(self) -> tuple[ClassificationNode, ...]:
        return tuple(
            item
            for item in self.classifications
            if item.classification_type == ClassificationType.THEME
        )

    @property
    def business_model_ids(self) -> tuple[str, ...]:
        seen: set[str] = set()
        values: list[str] = []
        for profile in self.valuation_profiles:
            for business_model_id in profile.business_model_ids:
                if business_model_id not in seen:
                    seen.add(business_model_id)
                    values.append(business_model_id)
        return tuple(values)

    @property
    def primary_valuation_profile(self) -> ValuationProfileCatalogEntry | None:
        for assignment in self.valuation_assignments:
            if assignment.applicability == "primary":
                return next(
                    (
                        profile
                        for profile in self.valuation_profiles
                        if profile.profile_id == assignment.profile_id
                    ),
                    None,
                )
        return self.valuation_profiles[0] if self.valuation_profiles else None

    @property
    def primary_model_types(self) -> tuple[str, ...]:
        profile = self.primary_valuation_profile
        if profile is None:
            return ()
        policies = sorted(profile.model_policy, key=lambda item: item.priority)
        return tuple(
            policy.model_type for policy in policies if policy.applicability == "primary"
        )


class UniverseRepository:
    """Read-only repository for AXIOM Market Universe data."""

    def __init__(
        self,
        *,
        companies: Iterable[CompanyMaster],
        securities: Iterable[SecurityMaster],
        classifications: Iterable[ClassificationNode],
        valuation_profile_assignments: Iterable[ValuationProfileAssignment],
        valuation_profiles: Iterable[ValuationProfileCatalogEntry],
        validate: bool = True,
    ) -> None:
        self._companies = self._index_unique(companies, "company_id", "company")
        self._securities = self._index_unique(securities, "security_id", "security")
        self._classifications = self._index_unique(
            classifications, "classification_id", "classification"
        )
        self._valuation_assignments = self._index_unique(
            valuation_profile_assignments, "assignment_id", "valuation assignment"
        )
        self._valuation_profiles = self._index_unique(
            valuation_profiles, "profile_id", "valuation profile"
        )
        self._ticker_index: dict[str, list[SecurityMaster]] = {}
        for security in self._securities.values():
            self._ticker_index.setdefault(security.ticker.upper(), []).append(security)
        if validate:
            self.validate_integrity()

    @classmethod
    def from_directory(
        cls, universe_dir: str | Path, *, validate: bool = True
    ) -> "UniverseRepository":
        root = Path(universe_dir)
        return cls(
            companies=cls._load_models(root / "companies.json", CompanyMaster),
            securities=cls._load_models(root / "securities.json", SecurityMaster),
            classifications=cls._load_models(
                root / "classifications.json", ClassificationNode
            ),
            valuation_profile_assignments=cls._load_models(
                root / "valuation_profile_assignments.json",
                ValuationProfileAssignment,
            ),
            valuation_profiles=cls._load_models(
                root / "valuation_profile_catalog.json",
                ValuationProfileCatalogEntry,
            ),
            validate=validate,
        )

    @staticmethod
    def _load_models(path: Path, model_type):
        if not path.is_file():
            raise UniverseRepositoryError(f"required Universe file is missing: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UniverseRepositoryError(f"cannot read Universe file: {path}") from exc
        if not isinstance(payload, list):
            raise UniverseRepositoryError(f"Universe file must contain a JSON array: {path}")
        return [model_type.model_validate(item) for item in payload]

    @staticmethod
    def _index_unique(records: Iterable, field: str, label: str) -> dict[str, object]:
        result: dict[str, object] = {}
        for record in records:
            key = getattr(record, field)
            if key in result:
                raise UniverseIntegrityError([f"duplicate {label} ID: {key}"])
            result[key] = record
        return result

    def list_companies(self) -> tuple[CompanyMaster, ...]:
        return tuple(self._companies.values())

    def list_securities(self) -> tuple[SecurityMaster, ...]:
        return tuple(self._securities.values())

    def get_company_by_id(self, company_id: str) -> CompanyMaster:
        try:
            return self._companies[company_id]
        except KeyError as exc:
            raise UniverseRecordNotFoundError(f"company not found: {company_id}") from exc

    def get_security_by_id(self, security_id: str) -> SecurityMaster:
        try:
            return self._securities[security_id]
        except KeyError as exc:
            raise UniverseRecordNotFoundError(f"security not found: {security_id}") from exc

    def get_security_by_ticker(
        self, ticker: str, *, exchange: str | None = None
    ) -> SecurityMaster:
        matches = self._ticker_index.get(ticker.upper(), [])
        if exchange is not None:
            exchange_code = exchange.upper()
            matches = [item for item in matches if item.exchange == exchange_code]
        if not matches:
            suffix = f" on {exchange.upper()}" if exchange else ""
            raise UniverseRecordNotFoundError(
                f"security not found for ticker {ticker.upper()}{suffix}"
            )
        if len(matches) > 1:
            raise UniverseAmbiguousLookupError(
                f"ticker {ticker.upper()} matches multiple securities; provide exchange"
            )
        return matches[0]

    def resolve_company(self, identifier: str, *, exchange: str | None = None) -> ResolvedCompany:
        if identifier.startswith("company:"):
            company = self.get_company_by_id(identifier)
        elif identifier.startswith("security:"):
            company = self.get_company_by_id(self.get_security_by_id(identifier).company_id)
        else:
            company = self.get_company_by_id(
                self.get_security_by_ticker(identifier, exchange=exchange).company_id
            )

        securities = tuple(
            item for item in self._securities.values() if item.company_id == company.company_id
        )
        classifications = tuple(
            self._classifications[item_id] for item_id in company.classification_ids
        )
        assignments = tuple(
            sorted(
                (
                    item
                    for item in self._valuation_assignments.values()
                    if item.company_id == company.company_id
                ),
                key=lambda item: item.priority,
            )
        )
        profiles = tuple(
            self._valuation_profiles[item.profile_id] for item in assignments
        )
        return ResolvedCompany(
            company=company,
            securities=securities,
            classifications=classifications,
            valuation_assignments=assignments,
            valuation_profiles=profiles,
        )

    def integrity_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        primary_security_claims: dict[str, list[str]] = {}

        for security in self._securities.values():
            if security.company_id not in self._companies:
                errors.append(
                    f"security {security.security_id} references missing company {security.company_id}"
                )
            if security.primary_listing:
                primary_security_claims.setdefault(security.company_id, []).append(
                    security.security_id
                )

        for company in self._companies.values():
            if company.primary_security_id is not None:
                security = self._securities.get(company.primary_security_id)
                if security is None:
                    errors.append(
                        f"company {company.company_id} references missing primary security "
                        f"{company.primary_security_id}"
                    )
                elif security.company_id != company.company_id:
                    errors.append(
                        f"company {company.company_id} primary security belongs to "
                        f"{security.company_id}"
                    )
            if len(primary_security_claims.get(company.company_id, [])) > 1:
                errors.append(
                    f"company {company.company_id} has multiple primary listings"
                )
            for classification_id in company.classification_ids:
                if classification_id not in self._classifications:
                    errors.append(
                        f"company {company.company_id} references missing classification "
                        f"{classification_id}"
                    )
            for profile_id in company.valuation_profile_ids:
                if profile_id not in self._valuation_profiles:
                    errors.append(
                        f"company {company.company_id} references missing valuation profile "
                        f"{profile_id}"
                    )

        assignment_pairs: set[tuple[str, str]] = set()
        for assignment in self._valuation_assignments.values():
            if assignment.company_id not in self._companies:
                errors.append(
                    f"assignment {assignment.assignment_id} references missing company "
                    f"{assignment.company_id}"
                )
            if assignment.profile_id not in self._valuation_profiles:
                errors.append(
                    f"assignment {assignment.assignment_id} references missing profile "
                    f"{assignment.profile_id}"
                )
            pair = (assignment.company_id, assignment.profile_id)
            if pair in assignment_pairs:
                errors.append(
                    f"duplicate company/profile assignment: {assignment.company_id} -> "
                    f"{assignment.profile_id}"
                )
            assignment_pairs.add(pair)

        for company in self._companies.values():
            assigned_profile_ids = {
                assignment.profile_id
                for assignment in self._valuation_assignments.values()
                if assignment.company_id == company.company_id
            }
            declared_profile_ids = set(company.valuation_profile_ids)
            if assigned_profile_ids != declared_profile_ids:
                errors.append(
                    f"company {company.company_id} valuation profile declarations do not match "
                    "valuation_profile_assignments"
                )

        return tuple(errors)

    def validate_integrity(self) -> None:
        errors = self.integrity_errors()
        if errors:
            raise UniverseIntegrityError(errors)
