# Changelog

All notable changes to DataDrivenChemistryPapers.

## [1.0.0] — 2026-07-20

Initial release.

### Added
- Zero-dependency Python pipeline: collect → dedupe → classify → store → generate.
- Collectors for arXiv, ChemRxiv, Crossref, OpenAlex, PubMed, Europe PMC,
  Semantic Scholar and DOAJ, behind a pluggable registry.
- Weighted keyword classifier enforcing the "ML applied to chemistry" rule,
  with negative terms for off-domain papers, chemistry-venue bonus, relevance
  scores (0–100), multi-category assignment and tags.
- DOI + normalized-title deduplication with a persisted, rebuildable seen-set.
- JSON storage sharded by publication month (no database).
- Static website: homepage, client-side search with filters, author and
  journal pages, category directory, year/month/day archive, about page;
  responsive, dark-mode aware, all links relative.
- Daily GitHub Actions workflow (tests → pipeline → auto-commit).
- 28 unit tests; README, ARCHITECTURE, PROJECT_STATUS documentation.

### Fixed (during initial verification)
- Publication dates more than a year in the future (bad API data) are clamped
  to the ingestion date.
- ChemRxiv/Semantic Scholar outages degrade gracefully instead of failing the
  run.
