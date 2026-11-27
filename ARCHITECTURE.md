# Architecture

Design decisions and their rationale. The guiding constraints:
GitHub Pages (static hosting only), GitHub Actions (free CI), zero manual
work, no copyright exposure, easy to extend.

## Pipeline

```
collect (8 sources, isolated)
   ↓
deduplicate  (DOI key + normalized-title key, persisted in seen.json)
   ↓
classify     (OpenAlex details by DOI → rules → relevance model → area + methods)
   ↓
store        (JSON shards data/papers/YYYY/MM.json)
   ↓
generate     (static HTML + per-year JSON for client-side search)
   ↓
commit       (GitHub Actions)
```

## Key decisions

### Standard library only
The pipeline uses `urllib` instead of `requests`, `unittest` instead of
pytest, and string templates instead of Jinja. **Why:** nothing to install
locally or in CI, nothing to break in five years, and the project stays
copy-paste portable. `src/ddc/http.py` wraps urllib with retries, backoff,
gzip and a polite User-Agent.

### Aggregators instead of publisher scraping
ACS/RSC/Wiley/Elsevier/... have no free search APIs and scraping them is
fragile and legally murky. Their metadata is *already* legally distributed by
Crossref, OpenAlex, PubMed, Europe PMC, Semantic Scholar and DOAJ, which we
query instead. Publisher coverage is therefore complete while staying 100 %
legal. Papers keep their true journal/publisher fields; `source` records which
API found them first.

### Metadata only, abstracts are transient
Abstracts are fetched for classification but **never written to disk** -
`Paper` has no abstract field by design. This eliminates copyright risk while
keeping classification quality high.

### Trained relevance model, run with the standard library
`relevance.py` first applies rules (a DOI or arXiv identifier is required; OpenAlex
types that are not research, and titles such as "Correction to", are refused), then
a logistic regression over TF-IDF features of title, abstract, journal and OpenAlex
type and topic. The categorizer picks one area (multinomial model) and the methods
(names in the text, plus a per-method model). Weights are JSON files next to the
module, trained by `tools/train_models.py` (scikit-learn, development only) from
`data/labels/gold.json`. **Why:** a keyword score let through about 44% off-topic
papers (measured on a labelled sample of the store); the model is measured on the
same labels, needs no API key and runs in milliseconds. `classify.py` (keywords)
remains as the fallback when the weight files are missing. Records turned down are
remembered for 60 days in `data/state/rejected.json`, so they are not judged daily.
The OpenAlex lookups of a daily run stop after 20 minutes (`LOOKUP_BUDGET`); records not yet
looked up are not judged and wait for the next run, so the workflow stays inside its time limit.

`python -m ddc rescreen --meta <OpenAlex details>` judges the whole store again.

### Deduplication via a persisted seen-set
`data/state/seen.json` maps `doi:<normalized>` and `title:<sha1>` keys to
paper ids. Two keys catch both re-encounters across sources and
preprint-vs-journal duplicates with different DOIs. O(1) lookups, no database.
If the file is ever lost or corrupted it is rebuilt from the shards.

### JSON sharded by publication month
One file per month (`data/papers/2026/07.json`) keeps daily git diffs small
and files bounded. The site generator writes *separate* compact per-year
shards (`assets/data/papers-YYYY.json`) for the browser, so the stored format
and the served format can evolve independently.

### Hybrid static/client-side site
* **Static HTML** (SEO, works without JS): archive year→month→day,
  categories, about, and the newest additions as a fallback on the front page.
* **Front page** (`index.html` + `assets/app.js`): the papers added in the last
  30 days, at least the newest 200 in whole days (`assets/data/feed.json`, written by the generator), with read / unread,
  saved papers, followed journals, "new since your last visit", a title and author
  filter and keyboard shortcuts (j / k / s / r / a / o). The visitor's marks live in
  the browser's localStorage under `gp.idx.<index_key>.` (all tools on
  guruprakashmp.github.io share one origin). The Abstract button fetches one
  abstract by DOI from OpenAlex, then Crossref, in the visitor's browser; nothing
  is stored.
* **Client-side JS** (`assets/app.js`, vanilla; search in `assets/worker.js`, a Web
  Worker that keeps the data files in Cache Storage by content hash, so a returning
  visitor downloads only changed files): search with filters
  (area, method, year, journal, sort), author pages
  (`authors.html?a=Name`) and journal pages (`journals.html?j=Name`).
  **Why client-side for authors/journals:** thousands of authors would mean
  tens of thousands of static pages regenerated and committed daily; query-
  param pages give every author/journal a stable URL at zero repo cost.
* The index's own links are **relative**, so it works at any base path. The site is
  self-contained: its stylesheet, scripts and fonts (Inter, Source Serif 4, SIL Open
  Font License) are in `assets/`. Data files are compact (format 2, described in
  `generator.py`); affiliations are separate files, searched once loaded.
* Graphical abstracts open in a zoom view (wheel, pinch, buttons, drag). The footer
  shows a visitor count (abacus.jasoncameron.dev, one count per browser). `feed.xml`
  (Atom), `sitemap.xml` and schema.org Dataset markup help discovery.

### Generated site lives at the project root
`index.html` etc. sit next to `src/` and `data/` so that copying the single
`ddc_papers/` folder into a Pages repository is the whole deployment. The
extra served files (`src/`, `tests/`) are harmless.

### Failure isolation
Every collector runs inside try/except in the pipeline; HTTP calls retry with
backoff and treat 429/5xx as transient. A source being down (or rate-limited,
like keyless Semantic Scholar) can never block the daily run.

### Dates
Source APIs occasionally return garbage dates (e.g. year 2035); the pipeline
clamps anything unparseable or more than a year in the future to the ingestion
date. Month-only dates (DOAJ) become the 1st of the month.

### Historical backfill
`backfill.py` complements the forward-looking daily pipeline with a one-time
(but resumable) sweep of the field's history via OpenAlex cursor pagination:
18 broad-recall topic queries per year (precision comes from the classifier,
not the query), plus the complete works of the pioneers in
`config/pioneers.json`. It checkpoints (shards + seen-set) after every query,
so interrupting and re-running is always safe - already-ingested papers are
skipped as duplicates.

### Table-of-contents graphics
`toc.py` reads, once a day, the RSS feeds of the ACS, Wiley and RSC journals that
have papers added in the last 60 days (RSC journal code and ACS CODEN from the DOI,
Wiley's electronic ISSN from Crossref, cached in `data/state/toc_sources.json`),
takes each item's DOI and graphic URL, and keeps those of indexed papers in
`data/state/toc.json`. Only URLs on the publisher's own HTTPS hosts are kept. The
generator adds them to `feed.json`, the year shards and the archive cards; the
browser loads the image from the publisher (`referrerpolicy="no-referrer"`).

### Progressive loading in the browser
`app.js` fetches the manifest, renders as soon as the newest three year-shards
arrive, then streams the remaining years in the background and refreshes
counts/filters when complete. First paint stays fast regardless of index size.

## Extension points

| Want to... | Touch |
|---|---|
| Add a source | new module in `src/ddc/collectors/` + one import + settings |
| Tune relevance | label more papers in `data/labels/gold.json`, run `tools/train_models.py` |
| Change the categories | `src/ddc/taxonomy.py`, then relabel and retrain |
| Change look | `src/ddc/site/assets/style.css` |
| Add a page | `src/ddc/site/generator.py` |
