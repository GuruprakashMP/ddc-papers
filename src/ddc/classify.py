"""Relevance classification.

Implements the project's core filtering rule: a paper is indexed only when a
*data-driven method* (ML/AI/statistics) is applied to a *chemistry problem*.
Papers that are purely ML, or purely chemistry, or whose primary domain is
another field (medicine, finance, generic CS...) are rejected.

The classifier only ever sees text transiently (title + abstract); the
abstract is never stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .keywords import CHEM_TERMS, CHEM_VENUE_HINTS, ML_TERMS, NEGATIVE_TERMS
from .models import RawRecord

# Scoring shape: base + 4*ml + 3*chem, capped at 100.  The caps keep a paper
# with many weak matches from outscoring one with a few highly specific ones.
_BASE = 20
_ML_CAP = 10
_CHEM_CAP = 12
_VENUE_BONUS = 6
_TITLE_BONUS = 1  # extra point when a term appears in the title

# Minimum evidence on each side of the "ML applied to chemistry" rule.
_MIN_ML_POINTS = 2
_MIN_CHEM_POINTS = 2


def _compile(vocab: Dict[str, object]) -> List[Tuple[re.Pattern, str]]:
    """Compile phrases to word-boundary patterns allowing suffixes.

    "catalyst" matches "catalysts", "electrocatalys" matches
    "electrocatalysis" / "electrocatalyst".
    """
    compiled = []
    for phrase in vocab:
        pattern = re.compile(r"\b" + re.escape(phrase) + r"\w*", re.IGNORECASE)
        compiled.append((pattern, phrase))
    return compiled


_ML_PATTERNS = _compile(ML_TERMS)
_CHEM_PATTERNS = _compile(CHEM_TERMS)
_NEG_PATTERNS = _compile(NEGATIVE_TERMS)


@dataclass
class Classification:
    accepted: bool
    score: int
    categories: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    reason: str = ""


def _match_side(
    patterns: List[Tuple[re.Pattern, str]],
    vocab: Dict[str, Tuple[int, str, str]],
    title: str,
    text: str,
) -> Tuple[int, Dict[str, int], Dict[str, int]]:
    """Score one vocabulary side.

    Returns (points, tag_points, category_points).  Multiple phrases mapping
    to the same tag (spelling variants) count once, at their best weight.
    """
    tag_points: Dict[str, int] = {}
    category_points: Dict[str, int] = {}
    for pattern, phrase in patterns:
        if not pattern.search(text):
            continue
        weight, tag, category = vocab[phrase]
        if pattern.search(title):
            weight += _TITLE_BONUS
        if weight > tag_points.get(tag, 0):
            tag_points[tag] = weight
        category_points[category] = max(category_points.get(category, 0), weight)
    return sum(tag_points.values()), tag_points, category_points


def classify(record: RawRecord) -> Classification:
    """Score a raw record and derive its categories and tags."""
    title = record.title or ""
    text = f"{title}\n{record.abstract or ''}"
    if not title.strip():
        return Classification(False, 0, reason="empty title")

    ml_pts, ml_tags, ml_cats = _match_side(_ML_PATTERNS, ML_TERMS, title, text)
    chem_pts, chem_tags, chem_cats = _match_side(_CHEM_PATTERNS, CHEM_TERMS, title, text)

    journal_lower = (record.journal or "").lower()
    venue_is_chem = any(h in journal_lower for h in CHEM_VENUE_HINTS)
    if venue_is_chem:
        chem_pts += 2  # a chemistry venue is itself evidence of chemistry focus

    if ml_pts < _MIN_ML_POINTS:
        return Classification(False, 0, reason="no data-driven method detected")
    if chem_pts < _MIN_CHEM_POINTS:
        return Classification(False, 0, reason="no chemistry application detected")

    penalty = 0
    for pattern, phrase in _NEG_PATTERNS:
        if pattern.search(text):
            p = NEGATIVE_TERMS[phrase]
            if pattern.search(title):
                p *= 2  # off-domain signal in the title is strong evidence
            penalty += p

    score = _BASE + 4 * min(ml_pts, _ML_CAP) + 3 * min(chem_pts, _CHEM_CAP)
    if venue_is_chem:
        score += _VENUE_BONUS
    score -= penalty
    score = max(0, min(100, score))

    # Categories/tags ordered by evidence strength; chemistry side first so a
    # paper reads as "chemistry problem + ML method", mirroring the spec.
    categories = _ranked(chem_cats) + [c for c in _ranked(ml_cats) if c not in chem_cats]
    tags = _ranked(chem_tags) + [t for t in _ranked(ml_tags) if t not in chem_tags]

    # Drop the generic umbrella categories when specific ones exist.
    for generic in ("Chemistry", "Molecular Science"):
        if generic in categories and len(categories) > 1:
            categories.remove(generic)

    return Classification(
        accepted=True,
        score=score,
        categories=categories[:8],
        tags=tags[:12],
    )


def _ranked(points: Dict[str, int]) -> List[str]:
    return [k for k, _ in sorted(points.items(), key=lambda kv: (-kv[1], kv[0]))]
