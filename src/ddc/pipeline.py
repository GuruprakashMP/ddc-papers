"""Daily pipeline orchestrator.

    collect -> deduplicate -> classify -> store -> generate site

Each source is isolated: a failing API is logged and skipped, never fatal.
:func:`process_records` is the shared ingestion path used by both the daily
run and the historical backfill (see :mod:`ddc.backfill`).
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Dict, List

from typing import Optional, Tuple

from . import relevance
from .classify import classify
from .collectors import enabled_collectors
from .models import (Paper, RawRecord, dedupe_keys, make_paper_id,
                     normalize_author, normalize_doi)
from .settings import Settings
from .store import PaperStore

log = logging.getLogger(__name__)


# Seconds the daily run may spend on OpenAlex lookups (8 a second), so a large batch can
# never push the workflow past its time limit; the rest wait for the next run.
LOOKUP_BUDGET = 20 * 60


@dataclass
class PipelineResult:
    collected: int = 0
    duplicates: int = 0
    rejected: int = 0
    added: int = 0
    deferred: int = 0
    per_source: Dict[str, int] = field(default_factory=dict)

    def merge(self, other: "PipelineResult") -> None:
        self.collected += other.collected
        self.duplicates += other.duplicates
        self.rejected += other.rejected
        self.added += other.added
        self.deferred += other.deferred
        for k, v in other.per_source.items():
            self.per_source[k] = self.per_source.get(k, 0) + v

    def summary(self) -> str:
        per_source = ", ".join(f"{k}: {v}" for k, v in sorted(self.per_source.items()))
        return (f"collected {self.collected} ({per_source}); "
                f"{self.duplicates} duplicates, {self.rejected} off-topic, "
                f"{self.added} added to index"
                + (f", {self.deferred} kept for the next run" if self.deferred else ""))


def _sane_date(published: str, today: str) -> str:
    """Guard against garbage dates from source APIs (e.g. year 2035).

    Journal issues are often dated a few months ahead, so allow up to one year
    in the future; anything beyond that (or unparseable) falls back to today.
    """
    try:
        year = int((published or "")[:4])
    except ValueError:
        return today
    if not published or not (1900 <= year <= int(today[:4]) + 1):
        return today
    return published


def collect_records(settings: Settings, since: dt.date) -> List[RawRecord]:
    """Query every enabled source, isolating failures per source."""
    records: List[RawRecord] = []
    for collector in enabled_collectors(settings.enabled_sources):
        try:
            found = collector.fetch(since, settings.max_results_per_source)
            log.info("%s: %d records", collector.name, len(found))
            records.extend(found)
        except Exception as exc:  # noqa: BLE001 - one source must never kill the run
            log.error("%s failed, continuing without it: %s", collector.name, exc)
    return records


def judge(record: RawRecord, settings: Optional[Settings] = None) -> Tuple[bool, float, List[str], str]:
    """(accepted, probability, categories, reason) for one record.

    The rules of relevance.gate first, then the relevance model and the categorizer. Without
    the model files, the older keyword rules of classify.py decide.
    """
    reason = relevance.gate(record.title, record.doi, record.url, record.oa_type)
    if reason:
        return False, 0.0, [], reason
    evidence = relevance.method_evidence(record.title, record.abstract)
    if not evidence:
        return False, 0.0, [], "no data-driven method named"
    model = relevance.model()
    if model is None:
        verdict = classify(record)
        floor = settings.min_relevance_score if settings else 40
        ok = verdict.accepted and verdict.score >= floor
        return ok, verdict.score / 100.0, verdict.categories, verdict.reason
    counts = relevance.features(record.title, record.abstract, record.journal, record.oa_type,
                                record.oa_field, record.oa_topic)
    p = model.probability(counts)
    if p < model.threshold:
        return False, p, [], "below the relevance threshold"
    if evidence < 2 and p < relevance.WEAK_THRESHOLD:
        return False, p, [], "no data-driven method named clearly"
    cat = relevance.categorizer()
    return True, p, cat.categories(counts, record.title, record.abstract) if cat else [], ""


def process_records(
    records: List[RawRecord],
    settings: Settings,
    store: PaperStore,
    seen: Dict[str, str],
    rejected: Optional[Dict[str, str]] = None,
    lookup: bool = False,
) -> PipelineResult:
    """Dedupe, classify and store a batch of raw records.

    Mutates ``seen`` (and ``rejected``, the keys of records turned down recently, which are
    not judged again) in place; the caller persists them (so a backfill can checkpoint
    between batches). ``lookup`` asks OpenAlex for the details the model reads (type, topic,
    abstract) of new records that lack them.
    """
    today = dt.date.today().isoformat()
    result = PipelineResult(collected=len(records))
    accepted: List[Paper] = []
    rejected = rejected if rejected is not None else {}

    fresh: List[RawRecord] = []
    batch_keys = set()
    for record in records:
        keys = dedupe_keys(record.doi, record.title)
        if not keys:  # no DOI and a too-short title: cannot dedupe safely
            continue
        if any(k in seen or k in rejected or k in batch_keys for k in keys):
            result.duplicates += 1
            continue
        batch_keys.update(keys)
        fresh.append(record)
    if lookup:
        from .enrich import enrich
        late = enrich(fresh, budget=LOOKUP_BUDGET)
        if late:
            result.deferred = len(late)
            fresh = [r for r in fresh if id(r) not in late]

    for record in fresh:
        keys = dedupe_keys(record.doi, record.title)
        ok, prob, categories, _reason = judge(record, settings)
        if not ok:
            result.rejected += 1
            for key in keys:
                rejected[key] = today
            continue

        published = _sane_date(record.published, today)
        # Normalize here rather than per collector: this is the one path both
        # the daily run and the backfill go through, so all 8 sources are
        # covered. Author names never feed paper ids or dedupe keys (those
        # derive from DOI/title), so this cannot disturb identity or the
        # seen-set.
        authors = []
        for raw_author in record.authors[:30]:
            cleaned = normalize_author(raw_author)
            if cleaned and cleaned not in authors:
                authors.append(cleaned)
        paper = Paper(
            id=make_paper_id(record.doi, record.title),
            title=record.title,
            authors=authors,
            journal=record.journal,
            publisher=record.publisher,
            published=published,
            year=int(published[:4]),
            doi=normalize_doi(record.doi),
            url=record.url,
            source=record.source,
            categories=categories,
            tags=[],
            relevance_score=int(round(prob * 100)),
            affiliations=record.affiliations,
            added=today,
            oa_abstract=record.oa_abstract,
        )
        for key in keys:
            seen[key] = paper.id
        accepted.append(paper)
        result.per_source[record.source] = result.per_source.get(record.source, 0) + 1

    result.added = store.add(accepted)
    return result


def run(days_back: int = 0, generate: bool = True) -> PipelineResult:
    """Execute the full daily pipeline and return a summary."""
    settings = Settings.load()
    since = dt.date.today() - dt.timedelta(
        days=days_back or settings.collect_days_back)
    log.info("Collecting papers published since %s", since.isoformat())

    records = collect_records(settings, since)

    store = PaperStore()
    seen = store.load_seen()
    rejected = store.load_rejected()
    result = process_records(records, settings, store, seen, rejected, lookup=True)
    store.save_seen(seen)
    store.save_rejected(rejected)
    log.info("Pipeline: %s", result.summary())

    if settings.toc_graphics:
        # TOC graphics are a bonus: nothing here may stop the daily update.
        try:
            from .toc import update as update_toc
            update_toc(store.load_all())
        except Exception:  # noqa: BLE001
            log.exception("toc: update failed; continuing without new graphics")

    if generate:
        from .site.generator import generate_site
        generate_site(settings)
    return result
