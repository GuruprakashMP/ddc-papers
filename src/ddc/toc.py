"""Table-of-contents graphics (graphical abstracts) shown on the paper cards.

Two sources, both checked on 2026-11-24 to deliver the journal's own graphical abstract:

* Wiley: each journal's RSS feed links the graphical abstract of its recent articles
  (file names "...-gra-0001-m.png" or "...-toc-0001-m.png"). An item without one links a
  standard journal picture ("...-blkfxd-...") instead; those look like a cover page and are
  never used (IMAGE_NAME).
* Elsevier: an article's graphical abstract is published at
  https://ars.els-cdn.com/content/image/1-s2.0-<PII>-ga1.jpg, and Crossref gives the PII. Not
  every article has one, so the address is checked before it is recorded; an article without
  one is checked once more two weeks later (the graphic can appear after online publication).

Not available here: ACS (its servers answer automated requests with HTTP 403), RSC (its feeds
carry no graphic), Springer Nature, MDPI, arXiv and ChemRxiv (no graphical abstract published in
a form that can be found automatically).

Only addresses are stored (data/state/toc.json); images are never downloaded or copied: the
website shows them from the publisher's own server. Every failure is logged and skipped, so this
step never stops the daily update.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import logging
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

from . import http
from .models import Paper, normalize_doi
from .settings import STATE_DIR

log = logging.getLogger(__name__)

TOC_FILE = STATE_DIR / "toc.json"              # {doi: {"img": url, "pub": "Wiley", "seen": date}}
SOURCES_FILE = STATE_DIR / "toc_sources.json"  # {"Wiley|<journal>": feed url or ""}
CHECKED_FILE = STATE_DIR / "toc_checked.json"  # {doi: [last checked date, times]} (Elsevier misses)

LOOKBACK_DAYS = 60      # Wiley journals with papers added in this window get their feed read
MAX_FEEDS = 150         # per run, the journals with the most recent papers first
PAUSE_SECONDS = 1.0     # between two requests to the same service
MAX_FEED_BYTES = 12 * 1024 * 1024
GIVE_UP_AFTER = 3       # a source whose first 3 requests all fail is skipped for the run
ELSEVIER_PER_RUN = 600  # Elsevier articles checked per run, newest first
RECHECK_DAYS = 14       # an Elsevier article without a graphic is checked again once after this

WILEY_HOSTS = ("onlinelibrary.wiley.com", ".onlinelibrary.wiley.com")
ELSEVIER_GA = "https://ars.els-cdn.com/content/image/1-s2.0-{pii}-ga1.jpg"
IMAGE_NAME = {
    "Wiley": re.compile(r"-(?:gra|toc)-\d{4}-m\.(?:png|jpe?g|gif)$", re.I),
    "Elsevier": re.compile(r"^/content/image/1-s2\.0-S[0-9X]{16}-ga1\.jpg$"),
}


def publisher_of(doi: str) -> Optional[str]:
    prefix = normalize_doi(doi).split("/", 1)[0]
    return {"10.1002": "Wiley", "10.1016": "Elsevier"}.get(prefix)


def image_ok(pub: str, url: str) -> Optional[str]:
    """The URL (as HTTPS) when it is that publisher's graphical abstract on its own host."""
    url = html.unescape((url or "").strip())
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    if not url.startswith("https://") or len(url) > 600:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if pub == "Wiley":
        if not any(host == h or (h.startswith(".") and host.endswith(h)) for h in WILEY_HOSTS):
            return None
        return url if IMAGE_NAME["Wiley"].search(parts.path) else None
    if pub == "Elsevier":
        return url if host == "ars.els-cdn.com" and IMAGE_NAME["Elsevier"].match(parts.path) else None
    return None


# ---------------------------------------------------------------------------
# Wiley: journal RSS feeds
# ---------------------------------------------------------------------------

def wiley_feed(issn: str) -> str:
    return f"https://onlinelibrary.wiley.com/feed/{issn.replace('-', '')}/most-recent"


def _wiley_feed_from_crossref(doi: str) -> Optional[str]:
    """Wiley addresses feeds by the journal's electronic ISSN, which Crossref lists."""
    try:
        msg = http.get_json(f"https://api.crossref.org/works/{normalize_doi(doi)}")["message"]
    except (http.FetchError, KeyError, TypeError) as exc:
        log.info("toc: no ISSN for %s (%s)", doi, exc)
        return None
    types = msg.get("issn-type") or []
    issn = next((t.get("value") for t in types if t.get("type") == "electronic"), None)
    issn = issn or next(iter(msg.get("ISSN") or []), None)
    return wiley_feed(issn) if issn else None


def choose_feeds(papers: Iterable[Paper], today: dt.date, sources: Dict[str, str]) -> List[str]:
    """Feeds of the Wiley journals with papers added in the last LOOKBACK_DAYS, busiest first."""
    since = (today - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
    counts: Counter = Counter()
    sample: Dict[str, str] = {}
    for p in papers:
        if publisher_of(p.doi) != "Wiley" or (p.added or "") < since:
            continue
        counts[p.journal] += 1
        sample.setdefault(p.journal, p.doi)
    feeds: List[str] = []
    for journal, _n in counts.most_common():
        key = f"Wiley|{journal}"
        if key not in sources:
            sources[key] = _wiley_feed_from_crossref(sample[journal]) or ""
        url = sources[key]
        if url and url not in feeds:
            feeds.append(url)
        if len(feeds) >= MAX_FEEDS:
            break
    return feeds


_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>?#&]+", re.I)
_IMG_RE = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.I)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_feed(pub: str, data: bytes) -> Dict[str, str]:
    """{doi: graphic url} for the items of an RSS 2.0, RSS 1.0 (RDF) or Atom feed."""
    root = ET.fromstring(data)
    out: Dict[str, str] = {}
    for item in root.iter():
        if _local(item.tag) not in ("item", "entry"):
            continue
        fields: Dict[str, List[str]] = {}
        for child in item:
            name = _local(child.tag)
            text = (child.text or "").strip()
            if name == "link" and not text:
                text = child.get("href", "")
            fields.setdefault(name, []).append(text)
        doi = _item_doi(fields)
        img = _item_image(pub, fields)
        if doi and img:
            out[doi] = img
    return out


def describe_first_item(data: bytes) -> str:
    """What the first item of a feed holds, so a feed whose format changed shows up in the log."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        return f"not XML ({exc}): {data[:200]!r}"
    for item in root.iter():
        if _local(item.tag) in ("item", "entry"):
            parts = []
            for child in item:
                text = (child.text or "").strip().replace("\n", " ")
                parts.append(f"<{_local(child.tag)}> {text[:160]}")
            return " | ".join(parts)[:1500]
    return f"no item; root <{root.tag}>, {len(data)} bytes"


def _item_doi(fields: Dict[str, List[str]]) -> str:
    for name in ("doi", "identifier", "guid", "link"):
        for text in fields.get(name, []):
            m = _DOI_RE.search(text)
            if m:
                return normalize_doi(m.group(0).rstrip(".,;)"))
    return ""


def _item_image(pub: str, fields: Dict[str, List[str]]) -> Optional[str]:
    for name in ("encoded", "description", "summary", "content"):
        for text in fields.get(name, []):
            for src in _IMG_RE.findall(html.unescape(text)):
                ok = image_ok(pub, src)
                if ok:
                    return ok
    return None


# ---------------------------------------------------------------------------
# Elsevier: graphical abstract by PII
# ---------------------------------------------------------------------------

def elsevier_pii(doi: str) -> Optional[str]:
    """The article's PII (e.g. S0308814626043049) from Crossref's alternative ids."""
    msg = http.get_json(f"https://api.crossref.org/works/{normalize_doi(doi)}")["message"]
    for alt in msg.get("alternative-id") or []:
        pii = re.sub(r"[^0-9A-Z]", "", str(alt).upper())
        if re.fullmatch(r"S[0-9X]{16}", pii):
            return pii
    return None


def image_exists(url: str) -> bool:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": http.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200 and (resp.headers.get("Content-Type") or "").startswith("image/")
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404, 410):
            return False
        raise http.FetchError(f"HTTP {exc.code} for {url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise http.FetchError(f"{exc} for {url}") from exc


def elsevier_candidates(papers: Iterable[Paper], toc: Dict[str, dict],
                        checked: Dict[str, list], today: dt.date) -> List[str]:
    """Elsevier DOIs to check now: never checked, or missed once more than RECHECK_DAYS ago."""
    out = []
    for p in sorted(papers, key=lambda p: (p.added or "", p.published or ""), reverse=True):
        doi = normalize_doi(p.doi)
        if publisher_of(doi) != "Elsevier" or doi in toc:
            continue
        seen = checked.get(doi)
        if seen:
            last, times = seen[0], seen[1]
            if times >= 2 or (today - dt.date.fromisoformat(last)).days < RECHECK_DAYS:
                continue
        out.append(doi)
        if len(out) >= ELSEVIER_PER_RUN:
            break
    return out


# ---------------------------------------------------------------------------
# the daily update
# ---------------------------------------------------------------------------

def load(path: Optional[Path] = None) -> Dict[str, dict]:
    path = path or TOC_FILE      # read at call time, so a changed TOC_FILE is honoured
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")


def _fetch_feed(url: str) -> bytes:
    return http.get_bytes(url, headers={"Accept": "application/rss+xml, application/xml, text/xml"},
                          retries=2)


def update(papers: List[Paper], today: Optional[dt.date] = None,
           elsevier_limit: Optional[int] = None) -> Dict[str, int]:
    """Read the Wiley feeds and check Elsevier graphics for indexed papers. Returns counts."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    sources = load(SOURCES_FILE)
    checked = load(CHECKED_FILE)
    indexed = {normalize_doi(p.doi) for p in papers if p.doi}
    stats: Counter = Counter()
    # Drop what is no longer listed or no longer passes the checks (e.g. Wiley "blkfxd" pictures).
    toc = {doi: v for doi, v in load().items()
           if doi in indexed and isinstance(v, dict) and image_ok(v.get("pub", ""), v.get("img", ""))}

    feeds = choose_feeds(papers, today, sources)
    _save(SOURCES_FILE, sources)
    misses = 0
    for i, url in enumerate(feeds):
        if misses >= GIVE_UP_AFTER and not stats["Wiley feeds read"]:
            stats["Wiley feeds skipped"] += 1
            continue
        if i:
            time.sleep(PAUSE_SECONDS)
        try:
            data = _fetch_feed(url)
            if len(data) > MAX_FEED_BYTES:
                raise ValueError(f"{len(data)} bytes")
            items = parse_feed("Wiley", data)
        except (http.FetchError, ET.ParseError, ValueError) as exc:
            stats["Wiley feeds failed"] += 1
            misses += 1
            log.info("toc: Wiley feed %s failed: %s", url, str(exc)[:160])
            continue
        stats["Wiley feeds read"] += 1
        stats["Wiley items with a graphic"] += len(items)
        for doi, img in items.items():
            if doi in indexed:
                if (toc.get(doi) or {}).get("img") != img:
                    stats["Wiley graphics recorded"] += 1
                toc[doi] = {"img": img, "pub": "Wiley", "seen": today.isoformat()}

    todo = elsevier_candidates(papers, toc, checked, today)
    if elsevier_limit is not None:
        todo = todo[:elsevier_limit]
    misses = 0
    for doi in todo:
        if misses >= GIVE_UP_AFTER and not stats["Elsevier checked"]:
            stats["Elsevier skipped"] += 1
            continue
        try:
            pii = elsevier_pii(doi)
            url = ELSEVIER_GA.format(pii=pii) if pii else None
            found = bool(url) and image_exists(url)
        except (http.FetchError, KeyError, TypeError, ValueError) as exc:
            stats["Elsevier failed"] += 1
            misses += 1
            log.info("toc: Elsevier %s failed: %s", doi, str(exc)[:160])
            time.sleep(PAUSE_SECONDS)
            continue
        stats["Elsevier checked"] += 1
        if found:
            toc[doi] = {"img": url, "pub": "Elsevier", "seen": today.isoformat()}
            stats["Elsevier graphics recorded"] += 1
            checked.pop(doi, None)
        else:
            checked[doi] = [today.isoformat(), (checked.get(doi) or [None, 0])[1] + 1]
        time.sleep(PAUSE_SECONDS / 2)

    _save(TOC_FILE, toc)
    _save(CHECKED_FILE, {d: v for d, v in checked.items() if d in indexed})
    stats["papers with a graphic"] = len(toc)
    log.info("toc: %s", ", ".join(f"{k}: {v}" for k, v in sorted(stats.items())) or "nothing to do")
    return dict(stats)
