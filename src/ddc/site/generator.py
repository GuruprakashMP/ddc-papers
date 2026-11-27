"""Generate the static website from the JSON paper store.

Output layout (all inside the project root, so the folder can be served by GitHub Pages):

    index.html                 front page: the papers added most recently (app.js)
    search.html                search with filters (app.js + worker.js)
    authors.html, journals.html  author and journal directories and pages (app.js)
    about.html                 what the index is, how papers are chosen, privacy
    categories/index.html      the chemistry areas and data-driven methods, with counts
    archive/<YYYY>/<MM>/index.html  every paper of a month, by day (plain HTML)
    feed.xml, sitemap.xml      Atom feed of the latest papers; sitemap for search engines
    assets/                    style.css, app.js, worker.js, fonts (copied from the package)
    assets/data/manifest.json  what the data files are (format 2, below)
    assets/data/feed.json      the papers added in the last FEED_DAYS days (front page)
    assets/data/papers-<YYYY>.json  the papers published in a year (search, authors, journals)
    assets/data/aff-<YYYY>.json     their affiliations, searched once loaded

Format 2 data files are compact: a paper is the array
    [id, title, authors, journal, published, doi, categories, url, toc, abstract]
with ``journal`` an index into the file's own "j" list, ``categories`` indices into the
manifest's "categories" list (taxonomy.ALL_NAMES), ``url`` only for a paper without a DOI,
``toc`` the publisher's graphic (or "") and ``abstract`` "o" when OpenAlex has the
abstract, "c" when it does not (so the browser asks Crossref), "" when not known. A year
file's row adds, for a paper dated after the day it was added (an issue date ahead), that
day, to sort by; feed rows add the day it was added and the number of authors not listed. Every file's
manifest entry carries a hash of its content ("v"), so browsers can keep files that did
not change between daily builds (worker.js).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple
from xml.sax.saxutils import escape as xml_esc

from ..models import Paper, normalize_doi
from ..settings import ASSETS_SRC_DIR, SITE_DIR, Settings
from ..store import PaperStore
from ..taxonomy import ALL_NAMES, AREAS, AREA_NAMES, METHODS, area_of
from .html import (AUTHORS_SHOWN, _q, esc, month_name, page, page_head, paper_card,
                   paper_link, pretty_date, short_date, txt)

log = logging.getLogger(__name__)

FORMAT = 2
# The front page lists the papers that entered the index in the last FEED_DAYS days
# (Paper.added), at least FEED_MIN of them, newest first.
FEED_DAYS = 30
FEED_MIN = 200
# ... counting only papers published at most NEW_DAYS before the day they were added.
NEW_DAYS = 90
FRONT_CARDS = 50      # cards in the front page's HTML (app.js shows the rest)
ATOM_ENTRIES = 100
CODE = {name: i for i, name in enumerate(ALL_NAMES)}


def generate_site(settings: Settings, out_dir: Path = SITE_DIR) -> None:
    papers = PaperStore().load_all()
    log.info("Generating site for %d papers -> %s", len(papers), out_dir)
    names = journal_names(papers)
    for p in papers:   # display forms only: the store keeps what the sources said
        p.journal = names.get(p.journal, p.journal)
        p.title = display_title(p.title)

    _clean_generated(out_dir)
    _copy_assets(out_dir)
    now = dt.datetime.now(dt.timezone.utc)
    generated = now.strftime("%Y-%m-%d %H:%M UTC")
    tocs = _load_tocs() if settings.toc_graphics else {}
    data_dir = out_dir / "assets" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    years = _write_data_shards(papers, data_dir, tocs)
    feed = feed_papers(papers, now.date())
    feed_entry = _write_feed(feed, data_dir, generated, tocs, len(papers))
    manifest = {"format": FORMAT, "generated": generated, "total": len(papers),
                "categories": ALL_NAMES, "areas": len(AREA_NAMES),
                "years": years, "feed": feed_entry}
    (data_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    base = (settings.site_base_url or "").rstrip("/") + "/" if settings.site_base_url else ""
    ctx = dict(site_title=settings.site_title, tagline=settings.site_tagline,
               index_key=settings.index_key, contact_email=settings.contact_email,
               base_url=base)

    _write(out_dir / "index.html", _homepage(papers, feed, now, tocs, ctx))
    for kind, title, lede in (
            ("search", "Search", "Search every paper in the database by title, author, "
                                 "journal, affiliation or DOI, and filter by area, method and year."),
            ("journals", "Journals", "Every journal with papers in the database."),
            ("authors", "Authors", "Every author of a paper in the database.")):
        _write(out_dir / f"{kind}.html", _js_page(kind, title, lede, ctx))
    _write(out_dir / "about.html", _about_page(papers, settings, ctx, tocs))
    _write(out_dir / "categories" / "index.html", _categories_page(papers, ctx))
    months = _write_archive(papers, out_dir, ctx, tocs)
    if base:
        _write(out_dir / "feed.xml", _atom(feed[:ATOM_ENTRIES], now, base, ctx))
        _write(out_dir / "sitemap.xml", _sitemap(base, months, now))
    log.info("Site generation complete")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load_tocs() -> Dict[str, str]:
    """{doi: graphic url} recorded by toc.update(), each checked again by toc.image_ok, so
    an entry recorded by an older rule (a cover picture, say) is never shown."""
    from ..toc import image_ok, load
    out = {}
    for doi, v in load().items():
        if isinstance(v, dict) and isinstance(v.get("img"), str):
            url = image_ok(str(v.get("pub", "")), v["img"])
            if url:
                out[normalize_doi(doi)] = url
    return out


_REPOSITORY = re.compile(r"^(arXiv|bioRxiv|medRxiv|ChemRxiv|chemRxiv|Zenodo|Research Square|"
                         r"Preprints\.org|TechRxiv|SSRN|Figshare|Europe PMC)\s*\(.*\)$", re.I)


def journal_names(papers: List[Paper]) -> Dict[str, str]:
    """{name as stored: name to show}, merging spellings of one journal.

    Sources disagree on case ("Analytical chemistry" from PubMed, "Analytical Chemistry"
    from Crossref) and repositories carry their host ("arXiv (Cornell University)"). Names
    that differ only in case, in "&" for "and" or in such a suffix become one: the most
    capitalised spelling, then the most used.
    """
    use = Counter(p.journal for p in papers if p.journal)
    def key(name: str) -> str:
        m = _REPOSITORY.match(name)
        base = m.group(1) if m else name
        return re.sub(r"\s+", " ", base.replace("&", "and")).strip().casefold()
    groups: Dict[str, List[str]] = defaultdict(list)
    for name in use:
        groups[key(name)].append(name)
    out = {}
    for names in groups.values():
        def rank(n):
            m = _REPOSITORY.match(n)
            shown = m.group(1) if m else n
            return (sum(ch.isupper() for ch in shown), use[n], -len(shown))
        best = max(names, key=rank)
        m = _REPOSITORY.match(best)
        best = m.group(1) if m else best
        best = _PROPER.get(best.casefold(), best)
        for n in names:
            out[n] = best
    return out


_PROPER = {"arxiv": "arXiv", "chemrxiv": "ChemRxiv", "biorxiv": "bioRxiv", "medrxiv": "medRxiv",
           "zenodo": "Zenodo", "techrxiv": "TechRxiv", "figshare": "Figshare"}

_TRAILING_DOT = re.compile(r"(?<![.\s])\.$")


def display_title(title: str) -> str:
    """A title as shown: without the full stop PubMed puts at the end of every title."""
    t = (title or "").strip()
    return _TRAILING_DOT.sub("", t) if not t.endswith(("et al.", "etc.", "e.g.", "i.e.")) else t


def _toc_of(p: Paper, tocs: Dict[str, str]) -> str:
    return tocs.get(normalize_doi(p.doi), "") if p.doi else ""


def _clean_generated(out_dir: Path) -> None:
    """Remove fully regenerated output so stale pages never linger.

    Only touches what the generator owns completely (the archive tree, the data files and
    the copied assets), never source code or stored data.
    """
    archive = out_dir / "archive"
    if archive.exists():
        _rmtree_robust(archive)
    data_dir = out_dir / "assets" / "data"
    if data_dir.exists():
        for stale in data_dir.glob("*.json"):
            stale.unlink()


def _rmtree_robust(path: Path) -> None:
    """rmtree that survives transient locks (OneDrive/antivirus on Windows)."""
    import time
    for attempt in range(3):
        try:
            shutil.rmtree(path)
            return
        except OSError:
            time.sleep(0.5 * (attempt + 1))
    for file in sorted(path.rglob("*"), reverse=True):
        try:
            if file.is_file():
                file.unlink()
            else:
                file.rmdir()
        except OSError:
            log.warning("Could not remove %s (locked); continuing", file)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _copy_assets(out_dir: Path) -> None:
    """Copy assets/ (with its fonts/ folder) from the package."""
    dest = out_dir / "assets"
    dest.mkdir(parents=True, exist_ok=True)
    for asset in ASSETS_SRC_DIR.rglob("*"):
        if asset.is_file() and "__pycache__" not in asset.parts:
            target = dest / asset.relative_to(ASSETS_SRC_DIR)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(asset, target)


def _dump(path: Path, payload) -> str:
    """Write compact JSON; return a short hash of it (the manifest's "v")."""
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha1(data).hexdigest()[:12]


def _abstract_code(p: Paper) -> str:
    return {"yes": "o", "no": "c"}.get(p.oa_abstract or "", "")


def _row(p: Paper, journals: Dict[str, int], tocs: Dict[str, str],
         authors_max: int = 0) -> list:
    if p.journal not in journals:
        journals[p.journal] = len(journals)
    authors = p.authors[:authors_max] if authors_max else p.authors
    return [p.id, p.title, authors, journals[p.journal], p.published or "", p.doi or "",
            [CODE[c] for c in p.categories if c in CODE],
            p.url if (p.url and not p.doi) else "", _toc_of(p, tocs), _abstract_code(p)]


def _sort_date(p: Paper) -> str:
    """The date a list "newest first" goes by: publication, or the day the paper was added
    when the publisher dates it later (an issue date ahead)."""
    pub = p.published or ""
    return p.added if p.added and p.added < pub else pub


def _write_data_shards(papers: List[Paper], data_dir: Path,
                       tocs: Dict[str, str]) -> List[dict]:
    by_year: Dict[int, List[Paper]] = defaultdict(list)
    for p in papers:
        by_year[p.year].append(p)
    years = []
    for year, items in sorted(by_year.items(), reverse=True):
        items.sort(key=lambda p: (_sort_date(p), p.id), reverse=True)
        journals: Dict[str, int] = {}
        rows = []
        for p in items:
            row = _row(p, journals, tocs)
            if _sort_date(p) != (p.published or ""):
                row.append(_sort_date(p))     # [10]: the date to sort by, when it differs
            rows.append(row)
        name = f"papers-{year}.json"
        entry = {"year": year, "count": len(items), "file": name,
                 "v": _dump(data_dir / name, {"j": list(journals), "p": rows})}
        affs = [" | ".join(p.affiliations or []) for p in items]
        if any(affs):
            aname = f"aff-{year}.json"
            entry.update(aff=aname, av=_dump(data_dir / aname, affs))
        years.append(entry)
    return years


def _new_when_added(p: Paper) -> bool:
    """Published at most NEW_DAYS before it was added: news, not an older paper found late
    (those are in the database and the search, not on the front page)."""
    if not p.added or not p.published:
        return True
    try:
        added = dt.date.fromisoformat(p.added[:10])
        pub = dt.date.fromisoformat((p.published + "-01-01")[:10] if len(p.published) == 4
                                    else (p.published + "-01")[:10] if len(p.published) == 7
                                    else p.published[:10])
    except ValueError:
        return True
    return (added - pub).days <= NEW_DAYS


def feed_papers(papers: List[Paper], today: dt.date) -> List[Paper]:
    """New papers (see _new_when_added) added in the FEED_DAYS days up to ``today``,
    newest first.

    Fewer than FEED_MIN there: the newest FEED_MIN additions, plus the rest of the oldest
    day taken, so the list always holds every paper added since its oldest date (the
    front page says "added since <that date>").
    """
    since = (today - dt.timedelta(days=FEED_DAYS - 1)).isoformat()
    ordered = sorted((p for p in papers if _new_when_added(p)),
                     key=lambda p: (p.added or "", p.published or "", p.id), reverse=True)
    recent = [p for p in ordered if (p.added or "") >= since]
    if len(recent) >= FEED_MIN or len(ordered) <= FEED_MIN:
        return recent if len(recent) >= FEED_MIN else ordered
    last_day = ordered[FEED_MIN - 1].added or ""
    return [p for p in ordered if (p.added or "") >= last_day]


def _write_feed(feed: List[Paper], data_dir: Path, generated: str,
                tocs: Dict[str, str], total: int) -> dict:
    """feed.json: what the front page lists, small enough to load at once."""
    journals: Dict[str, int] = {}
    rows = []
    for p in feed:
        row = _row(p, journals, tocs, authors_max=AUTHORS_SHOWN)
        row += [p.added or "", max(0, len(p.authors) - AUTHORS_SHOWN)]
        rows.append(row)
    payload = {"format": FORMAT, "generated": generated, "days": FEED_DAYS, "total": total,
               "j": list(journals), "p": rows}
    return {"file": "feed.json", "count": len(rows), "v": _dump(data_dir / "feed.json", payload)}


# ---------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------

def _day_groups(papers: List[Paper]) -> List[Tuple[str, List[Paper]]]:
    groups: Dict[str, List[Paper]] = defaultdict(list)
    for p in papers:
        groups[p.added or ""].append(p)
    return sorted(groups.items(), reverse=True)


def _homepage(papers: List[Paper], feed: List[Paper], now: dt.datetime,
              tocs: Dict[str, str], ctx: dict) -> str:
    oldest = min((p.added for p in feed if p.added), default="")
    cards = []
    for day, items in _day_groups(feed[:FRONT_CARDS]):
        cards.append(f'<h2 class="day-h" data-day="{esc(day)}">{esc(pretty_date(day) or "Recently")}</h2>')
        cards.extend(paper_card(p, toc=_toc_of(p, tocs)) for p in items)
    lede = (f"{len(feed):,} new paper{'' if len(feed) == 1 else 's'} added since {esc(short_date(oldest))} · "
            f"{len(papers):,} in the database · updated daily") if papers else ""
    base = ctx["base_url"]
    jsonld = ""
    if base:
        data = {
            "@context": "https://schema.org", "@type": "Dataset",
            "name": ctx["site_title"],
            "description": (f"{ctx['tagline']}. Bibliographic records (title, authors, journal, "
                            "date, DOI) of papers that apply machine learning, AI or other "
                            "data-driven methods to chemistry, classified by chemistry area and "
                            "method and updated daily."),
            "url": base, "isAccessibleForFree": True,
            "creator": {"@type": "Person", "name": "Guruprakash M P",
                        "url": "https://guruprakashmp.github.io/"},
            "dateModified": now.date().isoformat(),
            "keywords": ["data-driven chemistry", "machine learning", "artificial intelligence",
                         "cheminformatics", "catalysis", "computational chemistry"],
            "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json",
                              "contentUrl": base + "assets/data/manifest.json"}],
        }
        jsonld = ('<script type="application/ld+json">'
                  + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + "</script>")
    content = f"""
<div class="page-head front-head">
  <h1>Latest papers</h1>
  <p class="lede" id="lede">{lede}</p>
</div>
<div id="app" data-page="feed">
  <div id="results">
  {''.join(cards) if cards else '<p class="empty">No papers yet.</p>'}
  </div>
  <p class="more"><a class="btn" href="search.html">Search all {len(papers):,} papers</a></p>
</div>"""
    return page(title=f"{ctx['site_title']}: {ctx['tagline']}", content=content, depth=0,
                active="index.html", path="", head_extra=jsonld, **ctx)


def _js_page(kind: str, title: str, lede: str, ctx: dict) -> str:
    content = f"""
{page_head(esc(title), esc(lede))}
<div id="app" data-page="{kind}">
  <noscript><p>This page needs JavaScript. The <a href="archive/index.html">archive</a>
  lists every paper by date without it.</p></noscript>
  <p class="loading">Loading…</p>
</div>"""
    return page(title=f"{title} · {ctx['site_title']}", content=content, depth=0,
                active=f"{kind}.html", path=f"{kind}.html", description=lede, **ctx)


def _categories_page(papers: List[Paper], ctx: dict) -> str:
    counts = Counter(c for p in papers for c in set(p.categories))

    def tiles(items, param):
        return "\n".join(
            f'<li><span><a href="../search.html?{param}={esc(_q(name))}">{esc(name)}</a>'
            f'<span class="d">{esc(desc)}</span></span><span class="n">{counts.get(name, 0):,}</span></li>'
            for name, desc in items)

    content = f"""
{page_head("Categories", "Each paper has one chemistry area and the data-driven methods it uses. "
           "Choose one to see its papers.")}
<h2 class="sec-h">Chemistry areas</h2>
<ul class="tile-list">{tiles(AREAS, "area")}</ul>
<h2 class="sec-h">Data-driven methods</h2>
<ul class="tile-list">{tiles(METHODS, "method")}</ul>"""
    return page(title=f"Categories · {ctx['site_title']}", content=content, depth=1,
                active="categories/index.html", path="categories/index.html",
                description="The chemistry areas and data-driven methods papers are classified by.",
                **ctx)


def _about_page(papers: List[Paper], settings: Settings, ctx: dict,
                tocs: Dict[str, str]) -> str:
    n_toc = sum(1 for p in papers if _toc_of(p, tocs))
    email = settings.contact_email
    contact = (f' Write to <a href="mailto:{esc(email)}">{esc(email)}</a> to have a record '
               f"corrected, added or removed." if email else "")
    content = f"""
{page_head("About")}
<div class="prose">
<p><strong>{esc(ctx['site_title'])}</strong> is an open database of research papers that apply
machine learning, artificial intelligence or other data-driven methods to chemistry. It holds
{len(papers):,} papers and is updated every day.</p>

<h2 id="scope">What is included</h2>
<p>A paper is included when a data-driven method is central to it (machine learning, deep
learning, language models, chemometrics, Bayesian optimization, data mining, automated or
high-throughput experimentation guided by algorithms) and the problem it studies is chemistry:
molecules, reactions and synthesis, catalysis, materials chemistry, electrochemistry, polymers,
chemical analysis, computational chemistry, medicinal chemistry of small molecules,
environmental and chemical engineering. Medicine, biology without small-molecule chemistry,
engineering and physics outside chemistry, and papers that mention AI only in passing are not
included. Each paper has one chemistry area and the methods it uses; see the
<a href="categories/index.html">categories</a>.</p>

<h2 id="method">How papers are found</h2>
<p>A daily job reads new records from open scholarly metadata services (OpenAlex, Crossref,
ChemRxiv, arXiv, Europe PMC, PubMed, Semantic Scholar and DOAJ), removes duplicates and
decides whether each paper belongs. Its title or abstract must name a data-driven method; a
model trained on papers labelled against the rules above then judges the title, abstract,
journal and OpenAlex topic. Like any automatic screen it can
miss a paper or let one through.{contact}</p>

<h2 id="data">What is stored</h2>
<p>Bibliographic metadata only: title, authors, journal, dates, DOI and categories. Every paper
links to its publisher. Abstracts and graphics are not stored: when you press
<em>Show abstract</em>, your browser asks <a href="https://openalex.org/">OpenAlex</a> or
<a href="https://www.crossref.org/">Crossref</a> for it, and graphical abstracts
({n_toc:,} papers have one, from Wiley and Elsevier journals) load from the publisher's own
server and remain its property.</p>

<h2 id="privacy">Privacy</h2>
<p>No cookies and no tracking. The papers you mark read or save and the journals you follow
stay in your browser's local storage and are never sent anywhere. To count visitors, your
browser asks a public counter (abacus.jasoncameron.dev) to add one on your first visit and only
reads the total afterwards; that service sees the request, as any website does.</p>
</div>"""
    return page(title=f"About · {ctx['site_title']}", content=content, depth=0,
                active="about.html", path="about.html",
                description=f"What {ctx['site_title']} includes, how papers are found and what is stored.",
                **ctx)


def _write_archive(papers: List[Paper], out_dir: Path, ctx: dict,
                   tocs: Dict[str, str]) -> List[Tuple[str, str]]:
    """Archive pages; returns [(path, last added date)] of the month pages for the sitemap."""
    by_year: Dict[int, Dict[int, List[Paper]]] = defaultdict(lambda: defaultdict(list))
    for p in papers:
        parts = (p.published or "").split("-")
        month = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        by_year[p.year][month].append(p)

    year_items = "\n".join(
        f'<li><a href="{y}/index.html">{y}</a>'
        f'<span class="n">{sum(len(v) for v in months.values()):,}</span></li>'
        for y, months in sorted(by_year.items(), reverse=True))
    content = f"""
{page_head("Archive", "Every paper in the database by publication date: year, month, then day.")}
<ul class="tile-list">{year_items or '<li>The archive is empty.</li>'}</ul>"""
    _write(out_dir / "archive" / "index.html",
           page(title=f"Archive · {ctx['site_title']}", content=content, depth=1,
                active="archive/index.html", path="archive/index.html", **ctx))

    month_pages: List[Tuple[str, str]] = []
    for year, months in by_year.items():
        month_items = "\n".join(
            f'<li><a href="{m:02d}/index.html">{esc(month_name(m))}</a>'
            f'<span class="n">{len(items):,}</span></li>'
            for m, items in sorted(months.items(), reverse=True))
        content = f"""
{page_head(f"{year}", crumb='<a href="../index.html">Archive</a>')}
<ul class="tile-list">{month_items}</ul>"""
        _write(out_dir / "archive" / str(year) / "index.html",
               page(title=f"{year} · {ctx['site_title']}", content=content, depth=2,
                    active="archive/index.html", path=f"archive/{year}/index.html", **ctx))

        for m, items in months.items():
            by_day: Dict[str, List[Paper]] = defaultdict(list)
            for p in items:
                by_day[p.published or f"{year}-{m:02d}"].append(p)
            sections = []
            for day, day_papers in sorted(by_day.items(), reverse=True):
                label = pretty_date(day) if day.count("-") == 2 else f"{month_name(m)} {year}"
                sections.append(
                    f'<h2 class="day-h">{esc(label)} · {len(day_papers)}</h2>'
                    + "\n".join(paper_card(p, root="../../../", toc=_toc_of(p, tocs))
                                for p in day_papers))
            path = f"archive/{year}/{m:02d}/index.html"
            crumb = (f'<a href="../../index.html">Archive</a> / '
                     f'<a href="../index.html">{year}</a>')
            content = f"""
{page_head(f"{esc(month_name(m))} {year}", f"{len(items):,} papers published this month.", crumb)}
{''.join(sections)}"""
            _write(out_dir / path,
                   page(title=f"{month_name(m)} {year} · {ctx['site_title']}",
                        content=content, depth=3, active="archive/index.html", path=path,
                        body_page="static",
                        description=f"Data-driven chemistry papers published in {month_name(m)} {year}.",
                        **ctx))
            month_pages.append((path, max((p.added or "" for p in items), default="")))
    return month_pages


# ---------------------------------------------------------------------------
# feed and sitemap
# ---------------------------------------------------------------------------

def _atom(feed: List[Paper], now: dt.datetime, base: str, ctx: dict) -> str:
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    entries = []
    for p in feed:
        link = paper_link(p) or base
        added = f"{p.added}T00:00:00Z" if p.added else stamp
        authors = "".join(f"<author><name>{xml_esc(a)}</name></author>" for a in p.authors[:5])
        area = area_of(p.categories)
        cats = "".join(f'<category term="{xml_esc(c)}"/>' for c in p.categories)
        summary = ", ".join(x for x in (p.journal, f"published {pretty_date(p.published)}"
                                        if p.published else "", area) if x)
        entries.append(
            f"<entry><title>{xml_esc(p.title)}</title><link href=\"{xml_esc(link)}\"/>"
            f"<id>{xml_esc(link if p.doi else base + '#' + p.id)}</id><updated>{added}</updated>"
            f"{authors}{cats}<summary>{xml_esc(summary)}</summary></entry>")
    return (f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<feed xmlns="http://www.w3.org/2005/Atom">'
            f"<title>{xml_esc(ctx['site_title'])}: latest papers</title>"
            f"<subtitle>{xml_esc(ctx['tagline'])}</subtitle>"
            f'<link href="{xml_esc(base)}"/><link rel="self" href="{xml_esc(base)}feed.xml"/>'
            f"<id>{xml_esc(base)}</id><updated>{stamp}</updated>"
            + "".join(entries) + "</feed>\n")


def _sitemap(base: str, months: List[Tuple[str, str]], now: dt.datetime) -> str:
    today = now.date().isoformat()
    urls = [("", today), ("search.html", ""), ("journals.html", ""), ("authors.html", ""),
            ("categories/index.html", today), ("archive/index.html", today),
            ("about.html", today)]
    urls += sorted(months, reverse=True)
    body = "".join(
        f"<url><loc>{xml_esc(base + path)}</loc>{f'<lastmod>{d}</lastmod>' if d else ''}</url>"
        for path, d in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + body + "</urlset>\n")
