"""OpenAlex details for records that did not come from OpenAlex.

The relevance model reads a work's OpenAlex type and topic and its abstract; records from
Crossref, ChemRxiv, arXiv or PubMed are looked up by DOI (one request per work, which
OpenAlex serves without charge). Failures only leave the fields empty.
"""

from __future__ import annotations

import logging
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Set

from . import http
from .models import RawRecord, normalize_doi

log = logging.getLogger(__name__)

API = "https://api.openalex.org/works/doi:"
SELECT = "type,primary_topic,abstract_inverted_index"
RATE = 8.0   # requests per second, below OpenAlex's limit of 10

_lock = threading.Lock()
_next = [0.0]


def _slot() -> None:
    with _lock:
        now = time.monotonic()
        t = max(now, _next[0])
        _next[0] = t + 1.0 / RATE
    if t > now:
        time.sleep(t - now)


def _text(inv) -> str:
    words = {}
    for w, pos in (inv or {}).items():
        for i in pos if isinstance(pos, list) else []:
            if isinstance(i, int) and 0 <= i < 50000:
                words[i] = w
    return " ".join(words[i] for i in sorted(words))


def _one(record: RawRecord) -> None:
    doi = normalize_doi(record.doi)
    if not doi or record.oa_type:
        return
    _slot()
    try:
        work = http.get_json(API + urllib.parse.quote(doi, safe="/"), {"select": SELECT})
    except http.FetchError:
        return
    if not isinstance(work, dict):
        return
    topic = work.get("primary_topic") or {}
    record.oa_type = work.get("type") or ""
    record.oa_field = " / ".join(x for x in ((topic.get("field") or {}).get("display_name"),
                                             (topic.get("subfield") or {}).get("display_name")) if x)
    record.oa_topic = topic.get("display_name") or ""
    abstract = _text(work.get("abstract_inverted_index"))
    record.oa_abstract = "yes" if abstract else "no"
    if len(abstract) > len(record.abstract or ""):
        record.abstract = abstract


def enrich(records: List[RawRecord], workers: int = 4,
           budget: Optional[float] = None) -> Set[int]:
    """Look up the records that lack OpenAlex details, for at most ``budget`` seconds.

    Returns the ``id()`` of the records left unlooked-up when the budget ran out, so the
    caller can keep them for a later run instead of judging them without the details."""
    todo = [r for r in records if r.doi and not r.oa_type]
    if not todo:
        return set()
    log.info("OpenAlex details for %d records", len(todo))
    deadline = time.monotonic() + budget if budget else None
    late: Set[int] = set()

    def one(record: RawRecord) -> None:
        if deadline is not None and time.monotonic() >= deadline:
            late.add(id(record))
            return
        _one(record)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, todo))
    if late:
        log.info("OpenAlex details: time budget reached, %d records kept for the next run", len(late))
    return late
