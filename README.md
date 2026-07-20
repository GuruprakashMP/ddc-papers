# DataDrivenChemistryPapers

A fully automated, continuously updated public index of scientific papers where
**AI / Machine Learning / data-driven methods are applied to chemistry
problems** — catalysis, reaction prediction, retrosynthesis, molecule
generation, ML potentials, spectroscopy, electrochemistry, polymers, materials
chemistry and more.

* **No papers are hosted.** Only bibliographic metadata (title, authors,
  journal, date, DOI, link) is stored; every card links straight to the
  original publisher or preprint server.
* **Zero dependencies.** The entire pipeline is standard-library Python; no
  `pip install`, no database — everything is JSON + static HTML, perfect for
  GitHub Pages.
* **Fully automatic.** A GitHub Actions workflow collects, deduplicates,
  classifies, stores, regenerates the site, and commits — every day.

## Quick start (local)

```bash
cd ddc_papers
# Windows:  set PYTHONPATH=src        PowerShell:  $env:PYTHONPATH="src"
export PYTHONPATH=src

python -m ddc run            # collect + rebuild the website
python -m ddc run --days 7   # look further back on the first run
python -m ddc build          # rebuild website only, from stored data
python -m ddc stats          # index statistics
python -m unittest discover -s tests   # run the test suite

python -m http.server 8760   # then open http://localhost:8760
```

(The search/authors/journals pages fetch JSON, so view the site over HTTP,
not `file://`.)

## Deploying (own GitHub repository + Pages)

1. Create a public repository on GitHub (e.g. `ddc-papers`) and push this
   folder's contents to it (everything at the repo root).
2. On GitHub: **Settings → Pages → Source: Deploy from a branch → `main` /
   `/ (root)` → Save**.
3. The site is live at `https://<user>.github.io/<repo-name>/` within a
   minute or two.
4. The workflow in `.github/workflows/ddc-daily.yml` runs every day at
   05:00 UTC (or trigger it manually from the **Actions** tab) and commits
   new papers automatically — no maintenance needed.

## How papers are selected

A paper is indexed only when it matches **both** sides of the core rule:

* a **data-driven method** (ML, deep learning, LLMs, GNNs, Bayesian
  optimization, active learning, ...) **and**
* a **chemistry problem** (catalysis, synthesis, property prediction,
  spectroscopy, DFT, polymers, ...).

Papers whose primary field is medicine, finance, generic computer vision/NLP,
etc. are penalised and excluded. Every accepted paper gets a **relevance
score** (0–100; ≥90 extremely relevant, ≥70 very relevant), multiple
**categories**, and **tags** — see `src/ddc/keywords.py` to tune the
vocabulary.

## Sources

Direct: **arXiv**, **ChemRxiv**. Aggregators: **Crossref**, **OpenAlex**,
**PubMed**, **Europe PMC**, **Semantic Scholar**, **DOAJ** — which legally
provide the metadata of ACS, RSC, Wiley, Springer Nature, Elsevier, MDPI,
Frontiers, Taylor & Francis, IOP, AIP and essentially every DOI-issuing
publisher.

### Adding a new source

Create one file in `src/ddc/collectors/` with a `@register`-decorated
`Collector` subclass, import it in `collectors/__init__.py`, and add its name
to `enabled_sources` in `config/settings.json`. Nothing else changes.

## Project layout

```
config/settings.json    site title, thresholds, enabled sources
src/ddc/                pipeline package (stdlib only)
  collectors/           one module per metadata source
  site/                 static site generator + CSS/JS assets
data/papers/YYYY/MM.json  the index (metadata only)
data/state/seen.json    dedup keys of every paper ever seen
tests/                  unit tests (unittest)
index.html, search.html, archive/, ...   the generated website
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for design decisions,
[PROJECT_STATUS.md](PROJECT_STATUS.md) for current state, and
[CHANGELOG.md](CHANGELOG.md) for history.
