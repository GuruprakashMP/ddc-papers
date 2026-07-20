# Changelog

All notable changes to DataDrivenChemistryPapers.

## [1.1.0] — 2026-07-20

### Added
- **Historical backfill** (`python -m ddc backfill`): walks OpenAlex with
  cursor pagination, year by year from 1990, through 18 broad ML×chemistry
  queries; checkpointed and safely resumable.
- **Pioneer harvesting**: complete publication lists of ~20 field pioneers
  (Sigman, Doyle, Coley, Jensen, Aspuru-Guzik, Cronin, ...) from
  `config/pioneers.json`, filtered by the same classifier.
- Classifier vocabulary for the pre-deep-learning era: chemometrics, PLS,
  PCA, multivariate regression, Hammett analysis, linear free energy
  relationships, Sterimol parameters (new categories: "Chemometrics &
  Statistics", "Physical Organic Chemistry").
- Progressive loading on search/authors/journals pages: the newest three
  year-shards render instantly, the full archive streams in the background —
  keeps the UI fast at tens of thousands of papers.

### Changed
- Pipeline ingestion extracted into a reusable `process_records()` shared by
  the daily run and the backfill.

## [1.0.0] — 2026-07-20

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
