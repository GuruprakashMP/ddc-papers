"""ChemRxiv preprints, read from Crossref by ChemRxiv's DOI prefix (10.26434).

ChemRxiv's own API refuses automated clients (HTTP 403), but every preprint is registered
with Crossref. All new ones are read; the relevance model keeps the data-driven ones.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import List

from ..models import RawRecord
from ..settings import Settings
from .base import Collector, register
from .crossref import CrossrefCollector

log = logging.getLogger(__name__)

PREFIX = "10.26434"


@register
class ChemrxivCollector(Collector):
    name = "chemrxiv"
    label = "ChemRxiv (through Crossref)"

    def fetch(self, since: dt.date, limit: int) -> List[RawRecord]:
        records = CrossrefCollector().venue_papers(since, Settings.load().contact_email, prefix=PREFIX)
        out = []
        for r in records:
            r.source = self.name
            r.journal = r.journal or "ChemRxiv"
            out.append(r)
        return out[: max(limit, 1)]
