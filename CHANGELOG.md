# Changelog

## 0.4.0 — Research Foundation

### Added
- Canonical research models: `InvestmentThesis`, `ResearchDriver`, `Catalyst`, `DriverImpact`, `ResearchSnapshot`, and `ResearchRevision`.
- Research ingestion staging models: `RawArticle`, `EntityMention`, `ExtractedClaim`, and `ArticleAdmission`.
- Research summary CLI command.
- NVIDIA seed graph covering Blackwell, Vera Rubin qualification, future-period estimates, and valuation links.
- Public JSON builder support for research data.
- GitHub Actions release checks.

### Preserved
- v0.3 multi-model valuation: Forward PE, Forward PS, EV/EBITDA, and Forward PB.
- Execution/snapshot separation and snapshot deduplication.

### Fixed in verified artifact
- The complete repository includes `src/axiom_engine/io.py`.
- The verified artifact does not depend on the earlier incomplete update-only patch.
