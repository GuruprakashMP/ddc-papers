# Changelog

All notable changes to DataDrivenChemistryPapers.

## [2.0.0] - 2026-11-27

### Changed
- **Stricter, measured selection.** A labelled sample showed that about 44% of the
  stored papers were outside data-driven chemistry and that the daily job found only
  28% of recent papers in core journals. Papers are now chosen by a trained relevance
  model with hard rules (DOI or arXiv identifier required; the title or abstract must
  name a data-driven method; datasets, software, editorials, corrections and peer
  reviews refused), and the whole store was judged
  again with it (`python -m ddc rescreen`). Hand labels: `data/labels/gold.json`.
- **New categories:** one chemistry area (12) and the data-driven methods (11) per
  paper (`src/ddc/taxonomy.py`).
- **Collection:** OpenAlex searches every chemistry field over a 14-day window with
  paging; Crossref reads every new paper of 20 journals where data-driven chemistry is
  common; ChemRxiv is read through Crossref (its API refuses automated clients).
  OpenAlex lookups of a daily run stop after 20 minutes; the rest wait for the next run.
- **New look:** a light, self-contained design (own fonts, no shared theme, no Tools
  menu), the name shown once, cards with large graphical abstracts that open in a zoom
  view, journal chips, day headings, no keywords, scores or source labels.
- **Faster pages:** compact data files (28 MB instead of 53 MB before the rescreen),
  search in a Web Worker, data kept in the browser's Cache Storage by content hash,
  abstracts fetched from the right service and started on hover.
- **Graphical abstracts:** Wiley cover pictures are refused; Elsevier graphical
  abstracts are found by PII.

### Added
- Visitor count in the footer, Atom feed (`feed.xml`), `sitemap.xml`, Dataset markup.

## [1.3.0] - 2026-11-20

### Added
- **Table-of-contents graphics** (`src/ddc/toc.py`, `python -m ddc toc`). Every daily
  run reads the RSS feeds of the ACS, Wiley and RSC journals with papers added here
  in the last 60 days and records, for papers in the index, the address of the
  graphic each feed item links (`data/state/toc.json`). Only the address is stored;
  pages show the image from the publisher's own HTTPS host, credited ("Graphic:
  Wiley") and linked to the paper, and drop it if it does not load. A blocked feed
  is logged and skipped; after 3 failures in a row with no success a publisher is
  skipped for that run. `toc_graphics` in the settings turns it off.
  On the first runs (2026-11-20) only Wiley gave graphics: ACS answers GitHub's
  servers with HTTP 403, and RSC's feeds (read over plain HTTP, as feeds.rsc.org
  breaks off HTTPS from there) carry no graphic. A run logs the first item of any
  feed that yields none, so a change of format shows up.

### Changed
- A more structured look (shared GP Tools theme): header band with labelled
  figures (papers indexed, added since, last update, sources), the page title in
  the band on every other page, a filter sidebar on the front page, cards with
  icon buttons and the graphic beside the text, a four-column footer.
- No em dashes in anything shown: titles, journals, authors and abstracts that
  contain one are shown with a spaced hyphen (the stored record is unchanged), and
  docs and code comments no longer use them.

## [1.2.0] - 2026-11-19

### Added
- **Front page in the GP Tools theme.** The shared top bar (GP icon, Tools menu of
  every tool on guruprakashmp.github.io), a starfield header band and the shared
  footer, served once by the main site. Every page uses it.
- **A reading list of recent additions** (`assets/data/feed.json`): the papers added
  in the last 30 days (at least the newest 200, whole days), newest first, each with its journal badge, how long ago it
  was published, Full text (DOI), Abstract, Save and Mark read. Read papers are
  dimmed and listed below a "You're all caught up" divider; "N new since your last
  visit"; Saved, Unread, New and Following views; journal chips with counts and a
  list of journals to follow; a title and author filter; "Updated X ago"; keys
  j / k / s / r / a / o. Marks stay in the browser (localStorage, `gp.idx.ddc.`).
- **Abstract on click**, fetched by DOI from OpenAlex (`abstract_inverted_index`),
  else Crossref; "No abstract available" when neither has one. Not stored.
- Search, author, journal and archive cards get the same buttons.

### Changed
- About and Categories texts: no em dashes; "one or more categories" (many papers
  have exactly one).

## [1.1.1] - 2026-07-28

### Fixed
- **One researcher is now one author page.** Publisher metadata carries
  Unicode dashes and honorifics, so the same person fragmented across
  several pages - the U+2010 spelling of a hyphenated name and the ASCII
  spelling everyone types were different keys. 12,015 stored names were rewritten
  (Aspuru-Guzik, Gómez-Bombarelli, Reymond and more).

  New `models.normalize_author` (NFC, Unicode dashes -> ASCII `-`,
  invisible-space cleanup, leading honorifics dropped) is applied in
  `pipeline.process_records`, the single path shared by the daily run and
  the backfill. `tools/normalize_authors.py` migrates already-stored
  shards; it is idempotent, dry-run by default, and verifies each write.
  `app.js` normalizes the incoming `?a=` value so pre-existing links and
  bookmarks still resolve.
- Deliberately not merged: initials vs full given names, and hyphen-less
  spellings - those would fuse distinct researchers, since surnames like
  "Li", "Hu" and "Wu" occur as complete names in this data. A trailing
  period is preserved because many names legitimately end in an initial.
- Paper ids and `data/state/seen.json` are byte-identical before and after
  the migration: author names never feed identity or dedupe keys.

## [1.1.0] - 2026-07-20

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
  year-shards render instantly, the full archive streams in the background -
  keeps the UI fast at tens of thousands of papers.

### Changed
- Pipeline ingestion extracted into a reusable `process_records()` shared by
  the daily run and the backfill.

## [1.0.0] - 2026-07-20

## [1.0.0] - 2026-07-20

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
