"""OpenAlex collector (https://docs.openalex.org).

OpenAlex aggregates Crossref, PubMed, arXiv and more, and adds author
affiliations (institutions), which power the university/country search terms.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import time
from typing import Dict, List

from .. import http
from ..models import RawRecord
from ..settings import Settings
from .base import Collector, clean_text, register

log = logging.getLogger(__name__)

API = "https://api.openalex.org/works"

# Data-driven methods, searched in titles and abstracts...
_ML = ('("machine learning" OR "deep learning" OR "neural network" OR "artificial intelligence" '
       'OR "data-driven" OR "bayesian optimization" OR "active learning" OR "random forest" '
       'OR "gradient boosting" OR "graph neural" OR "language model" OR "generative model" '
       'OR chemometric OR QSAR OR "partial least squares" OR "self-driving" OR "autonomous laboratory" '
       'OR "interatomic potential" OR "high-throughput")')
# ...in works whose OpenAlex topic is in a chemistry field (Chemistry, Materials Science,
# Chemical Engineering, Pharmacology, Energy, Environmental Science), and in any field when
# the text is also about chemistry. The relevance model then decides.
CHEM_FIELDS = "16|25|15|30|21|23"
SEARCHES = (
    f"primary_topic.field.id:{CHEM_FIELDS},title_and_abstract.search:{_ML}",
    'title_and_abstract.search:("machine learning" OR "deep learning" OR "neural network" OR '
    '"graph neural" OR "language model" OR "generative model") AND (molecule OR molecular OR '
    'chemical OR chemistry OR catalyst OR catalysis OR reaction OR spectroscopy OR electrolyte '
    'OR polymer OR "drug discovery")',
)
WINDOW_DAYS = 14   # papers reach OpenAlex days after their publication date: look back this far
FIELDS = ("id,doi,display_name,authorships,primary_location,publication_date,type,"
          "primary_topic,abstract_inverted_index")

# Transparent-peer-review reports get their own DOIs (e.g.
# 10.1039/d3sc02440g/v1/review1) and OpenAlex serves them as works.
_PEER_REVIEW_DOI = re.compile(r"/v\d+/review", re.IGNORECASE)


@register
class OpenAlexCollector(Collector):
    name = "openalex"
    label = "OpenAlex"

    def fetch(self, since: dt.date, limit: int) -> List[RawRecord]:
        contact = Settings.load().contact_email
        since = min(since, dt.date.today() - dt.timedelta(days=WINDOW_DAYS))
        records: List[RawRecord] = []
        for search in SEARCHES:
            cursor, got = "*", 0
            while cursor and got < limit:
                try:
                    data = http.get_json(API, {
                        "filter": f"from_publication_date:{since.isoformat()},{search}",
                        "per-page": 200, "cursor": cursor, "select": FIELDS,
                        "mailto": contact or None,
                    })
                except http.FetchError as exc:
                    log.warning("OpenAlex query failed (%s): %s", search[:60], exc)
                    break
                results = data.get("results") or []
                for work in results:
                    record = work_to_record(work, self.name)
                    if record:
                        records.append(record)
                got += len(results)
                cursor = (data.get("meta") or {}).get("next_cursor") if results else None
                time.sleep(0.3)
        return records


def work_to_record(work: dict, source: str) -> RawRecord:
    """Convert an OpenAlex work object to a RawRecord (shared with backfill)."""
    title = clean_text(work.get("display_name"))
    if not title:
        return None  # type: ignore[return-value]
    authors: List[str] = []
    affiliations: List[str] = []
    for auth in work.get("authorships") or []:
        name = clean_text((auth.get("author") or {}).get("display_name"))
        if name:
            authors.append(name)
        for inst in auth.get("institutions") or []:
            inst_name = clean_text(inst.get("display_name"))
            if inst_name and inst_name not in affiliations:
                affiliations.append(inst_name)
    location = work.get("primary_location") or {}
    source_info = location.get("source") or {}
    doi = (work.get("doi") or "").replace("https://doi.org/", "")
    journal = clean_text(source_info.get("display_name"))
    if _PEER_REVIEW_DOI.search(doi):
        return None  # a peer-review report, not a paper
    # Corrupted OpenAlex merges: OSTI repository metadata fused with a
    # foreign publisher's DOI (and that paper's abstract). OSTI's own DOIs
    # start 10.2172; anything else on an OSTI record is a hijacked identity
    # that would block the real paper from the index.
    if journal and "OSTI OAI" in journal and doi and not doi.startswith("10.2172"):
        return None
    url = work.get("doi") or location.get("landing_page_url") or ""
    topic = work.get("primary_topic") or {}
    inverted = work.get("abstract_inverted_index")
    return RawRecord(
        title=title,
        abstract=_reconstruct_abstract(work.get("abstract_inverted_index")),
        authors=authors,
        journal=journal,
        publisher=clean_text(source_info.get("host_organization_name")),
        doi=doi,
        url=url,
        published=(work.get("publication_date") or "")[:10],
        affiliations=affiliations[:10],
        source=source,
        oa_type=work.get("type") or "",
        oa_field=" / ".join(x for x in ((topic.get("field") or {}).get("display_name"),
                                        (topic.get("subfield") or {}).get("display_name")) if x),
        oa_topic=topic.get("display_name") or "",
        oa_abstract=("yes" if inverted else "no") if "abstract_inverted_index" in work else "",
    )


def _reconstruct_abstract(inverted: object) -> str:
    """OpenAlex ships abstracts as {word: [positions]}; rebuild the text.

    Used only for classification, never stored.
    """
    if not isinstance(inverted, dict) or not inverted:
        return ""
    positions: Dict[int, str] = {}
    for word, indexes in inverted.items():
        for index in indexes:
            positions[index] = word
    return " ".join(positions[i] for i in sorted(positions))
