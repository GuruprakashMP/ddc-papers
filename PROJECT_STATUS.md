# Project Status

_Last updated: 2026-07-20_

## Completed

- [x] Core data model (`Paper`, `RawRecord`), DOI/title normalization, stable ids
- [x] Zero-dependency HTTP client with retries/backoff/gzip (`http.py`)
- [x] 8 collectors: arXiv, ChemRxiv, Crossref, OpenAlex, PubMed, Europe PMC,
      Semantic Scholar, DOAJ — pluggable registry, one-file extension
- [x] Keyword classifier (ML×chemistry rule, negative terms, venue bonus,
      0–100 relevance score, multi-category, tags)
- [x] Deduplication across sources and days (persisted seen-set, rebuildable)
- [x] JSON storage sharded by publication month
- [x] Static site generator: homepage, search, authors, journals, categories,
      archive (year→month→day), about — relative links, dark mode, responsive
- [x] Client-side search/filter app (vanilla JS, per-year JSON shards)
- [x] CLI: `run`, `collect`, `build`, `stats`
- [x] GitHub Actions daily workflow (tests → pipeline → auto-commit)
- [x] Unit tests: 28 passing (classifier, models, store, generator)
- [x] Verified end-to-end 2026-07-20: 626 collected → 176 indexed, site
      renders and filters correctly in the browser

## Known issues

- **ChemRxiv** returns HTTP 403 (Cloudflare bot protection) from at least some
  networks; may or may not work from GitHub Actions runners. Not critical:
  ChemRxiv DOIs also arrive via Crossref/OpenAlex. Consider an API token or
  the Figshare mirror if it persists.
- **Semantic Scholar** keyless tier is aggressively rate-limited (429); the
  collector skips gracefully. Optional: request a free API key and add it as a
  header for much higher limits.
- **Crossref** metadata usually lacks abstracts, so title-only classification
  accepts few of its results; most publisher papers arrive via OpenAlex
  instead (which reconstructs abstracts). Tuning opportunity.
- **arXiv** failed locally only due to this machine's missing SSL root certs
  (32-bit Python 3.9); expected to work in CI.

## Pending / ideas

- [ ] Semantic Scholar API key support (env var → header)
- [ ] Static per-category pages for SEO (currently category → search link)
- [ ] `sitemap.xml` once the final public URL is known (`site_base_url` setting)
- [ ] RSS/Atom feed of newly indexed papers
- [ ] Research-group pages (needs affiliation data quality work)
- [ ] Shard the search index further if the yearly JSON exceeds a few MB

## Next implementation step

Deploy: copy `ddc_papers/` into the GitHub Pages repository, move
`.github/workflows/ddc-daily.yml` to the repo root, push, and trigger the
workflow once from the Actions tab to confirm CI behaviour of all sources.
