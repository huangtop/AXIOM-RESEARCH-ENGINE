from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models.universe import CompanyMaster, SecurityMaster
from .repository_layout import CanonicalRepositoryLayout


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
    """Company aggregate with its listed securities resolved."""

    company: CompanyMaster
    securities: tuple[SecurityMaster, ...]

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
            return next(
                (
                    item
                    for item in self.securities
                    if item.security_id == self.company.primary_security_id
                ),
                None,
            )
        return next((item for item in self.securities if item.primary_listing), None)


class UniverseRepository:
    """Read-only repository for company and security master data."""

    def __init__(
        self,
        *,
        companies: Iterable[CompanyMaster],
        securities: Iterable[SecurityMaster],
        validate: bool = True,
    ) -> None:
        self._companies = self._index_unique(companies, "company_id", "company")
        self._securities = self._index_unique(securities, "security_id", "security")
        self._ticker_index: dict[str, list[SecurityMaster]] = {}
        for security in self._securities.values():
            self._ticker_index.setdefault(security.ticker.upper(), []).append(security)
        if validate:
            self.validate_integrity()

    @classmethod
    def from_directory(
        cls, universe_dir: str | Path, *, validate: bool = True
    ) -> "UniverseRepository":
        layout = CanonicalRepositoryLayout.resolve(universe_dir)
        return cls(
            companies=cls._load_models(layout.companies_path, CompanyMaster),
            securities=cls._load_models(layout.securities_path, SecurityMaster),
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

    def get_security_by_ticker(self, ticker: str, *, exchange: str | None = None) -> SecurityMaster:
        matches = self._ticker_index.get(ticker.upper(), [])
        if exchange is not None:
            matches = [item for item in matches if item.exchange == exchange.upper()]
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
        return ResolvedCompany(company=company, securities=securities)

    def integrity_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        primary_claims: dict[str, list[str]] = {}
        for security in self._securities.values():
            if security.company_id not in self._companies:
                errors.append(
                    f"security {security.security_id} references missing company {security.company_id}"
                )
            if security.primary_listing:
                primary_claims.setdefault(security.company_id, []).append(security.security_id)

        for company in self._companies.values():
            primary_id = company.primary_security_id
            if primary_id is not None:
                security = self._securities.get(primary_id)
                if security is None:
                    errors.append(
                        f"company {company.company_id} references missing primary security {primary_id}"
                    )
                elif security.company_id != company.company_id:
                    errors.append(
                        f"company {company.company_id} primary security belongs to {security.company_id}"
                    )
                elif not security.primary_listing:
                    errors.append(
                        f"company {company.company_id} primary security {primary_id} is not marked primary_listing"
                    )
            claims = primary_claims.get(company.company_id, [])
            if len(claims) > 1:
                errors.append(f"company {company.company_id} has multiple primary listings")
            if primary_id is not None and claims and primary_id not in claims:
                errors.append(
                    f"company {company.company_id} primary security does not match primary_listing"
                )
        return tuple(errors)

    def validate_integrity(self) -> None:
        errors = self.integrity_errors()
        if errors:
            raise UniverseIntegrityError(errors)
