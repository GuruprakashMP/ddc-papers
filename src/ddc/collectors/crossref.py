"""Crossref collector (https://api.crossref.org).

Crossref carries the metadata of essentially every DOI-issuing publisher -
ACS, RSC, Wiley, Springer Nature, Elsevier, MDPI, Taylor & Francis, IOP, AIP
and more - so this single collector legally covers all of them.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from typing import List

from .. import http
from ..models import RawRecord
from ..settings import Settings
from .base import Collector, clean_text, register

log = logging.getLogger(__name__)

API = "https://api.crossref.org/works"

QUERIES = (
    '"machine learning" chemistry',
    '"machine learning" catalysis',
    '"deep learning" molecular',
    '"neural network" chemical reaction',
    '"bayesian optimization" synthesis',
)


# Every new paper of these journals (by ISSN) is read; the relevance model keeps the
# data-driven chemistry ones. Keyword queries alone missed most of them.
VENUES = {
    "1549-960X": "J. Chem. Inf. Model.", "1549-9626": "J. Chem. Theory Comput.",
    "2635-098X": "Digital Discovery", "2057-3960": "npj Comput. Mater.",
    "2632-2153": "Mach. Learn.: Sci. Technol.", "1758-2946": "J. Cheminform.",
    "2522-5839": "Nat. Mach. Intell.", "2662-8457": "Nat. Comput. Sci.",
    "2770-9019": "APL Mach. Learn.", "2949-7477": "Artif. Intell. Chem.",
    "1520-5126": "J. Am. Chem. Soc.", "2155-5435": "ACS Catal.", "2041-6539": "Chem. Sci.",
    "2374-7951": "ACS Cent. Sci.", "1948-7185": "J. Phys. Chem. Lett.",
    "1520-5002": "Chem. Mater.", "1089-7690": "J. Chem. Phys.", "1463-9084": "Phys. Chem. Chem. Phys.",
    "2691-3704": "JACS Au", "1521-3773": "Angew. Chem. Int. Ed.",
}


@register
class CrossrefCollector(Collector):
    name = "crossref"
    label = "Crossref (ACS, RSC, Wiley, Springer Nature, Elsevier, ...)"

    def fetch(self, since: dt.date, limit: int) -> List[RawRecord]:
        contact = Settings.load().contact_email
        rows = max(20, limit // len(QUERIES))
        records: List[RawRecord] = []
        for query in QUERIES:
            try:
                data = http.get_json(API, {
                    "query.bibliographic": query,
                    "filter": f"from-created-date:{since.isoformat()},type:journal-article",
                    "rows": rows,
                    "sort": "indexed",
                    "order": "desc",
                    "select": "DOI,title,author,container-title,publisher,"
                              "issued,created,URL,abstract",
                    "mailto": contact or None,
                })
            except http.FetchError as exc:
                log.warning("Crossref query failed (%s): %s", query, exc)
                continue
            for item in (data.get("message") or {}).get("items") or []:
                record = self._to_record(item)
                if record:
                    records.append(record)
            time.sleep(1.0)  # Crossref politeness
        records.extend(self.venue_papers(since, contact))
        return records

    def venue_papers(self, since: dt.date, contact: str = "", prefix: str = "") -> List[RawRecord]:
        """Every article indexed since ``since`` in VENUES (or with a DOI ``prefix``)."""
        out: List[RawRecord] = []
        targets = [f"prefix:{prefix}"] if prefix else [f"issn:{issn}" for issn in VENUES]
        for target in targets:
            cursor = "*"
            for _ in range(20):          # at most 20 pages of 200 per journal and run
                try:
                    data = http.get_json(API, {
                        "filter": f"from-created-date:{since.isoformat()},{target}"
                                  + ("" if prefix else ",type:journal-article"),
                        "rows": 200, "cursor": cursor,
                        "select": "DOI,title,author,container-title,publisher,issued,created,URL,abstract,type",
                        "mailto": contact or None,
                    })
                except http.FetchError as exc:
                    log.warning("Crossref %s failed: %s", target, exc)
                    break
                msg = data.get("message") or {}
                items = msg.get("items") or []
                for item in items:
                    record = self._to_record(item)
                    if record:
                        out.append(record)
                cursor = msg.get("next-cursor")
                time.sleep(1.0)
                if len(items) < 200 or not cursor:
                    break
        return out

    def _to_record(self, item: dict) -> RawRecord:
        titles = item.get("title") or []
        title = clean_text(titles[0]) if titles else ""
        if not title:
            return None  # type: ignore[return-value]
        authors = []
        for a in item.get("author") or []:
            name = clean_text(f"{a.get('given', '')} {a.get('family', '')}")
            if name:
                authors.append(name)
        containers = item.get("container-title") or []
        doi = item.get("DOI") or ""
        return RawRecord(
            title=title,
            abstract=clean_text(item.get("abstract")),
            authors=authors,
            journal=clean_text(containers[0]) if containers else "",
            publisher=clean_text(item.get("publisher")),
            doi=doi,
            url=item.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
            published=_issued_date(item),
            source=self.name,
        )


def _issued_date(item: dict) -> str:
    for key in ("issued", "created"):
        parts = ((item.get(key) or {}).get("date-parts") or [[]])[0]
        if parts and parts[0]:
            year = int(parts[0])
            month = int(parts[1]) if len(parts) > 1 else 1
            day = int(parts[2]) if len(parts) > 2 else 1
            try:
                return dt.date(year, month, day).isoformat()
            except ValueError:
                continue
    return ""
