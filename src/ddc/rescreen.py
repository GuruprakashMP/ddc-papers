"""Judge every stored paper again with the current relevance model and categorizer.

    python -m ddc rescreen --meta openalex.jsonl [--labels data/labels/gold.json] [--dry-run]

``--meta`` is a JSON-lines file of OpenAlex details by paper id ({"id", "status", "type",
"field", "subfield", "topic", "abstract"}), as written by tools/fetch_openalex_meta.py.
Papers labelled by hand (``--labels``) keep their label. Papers turned down are removed
from the store; their keys stay in seen.json, so the collectors do not bring them back.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Dict, Optional

from .models import RawRecord
from .pipeline import judge
from .store import PaperStore
from .taxonomy import AREA_NAMES, METHOD_NAMES


def load_meta(path: Path) -> Dict[str, dict]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("id"):
            out[r["id"]] = r
    return out


def rescreen(meta_path: Path, labels_path: Optional[Path] = None, dry_run: bool = False) -> Counter:
    store = PaperStore()
    papers = store.load_all()
    meta = load_meta(meta_path)
    gold = json.loads(labels_path.read_text(encoding="utf-8")) if labels_path else {}
    report: Counter = Counter()
    kept = []
    for p in papers:
        m = meta.get(p.id, {})
        abstract = m.get("abstract") or ""
        if m.get("status") == "ok":
            p.oa_abstract = "yes" if abstract else "no"
        g = gold.get(p.id)
        if g and g.get("relevant") in ("yes", "no", "unsure"):
            ok = g["relevant"] == "yes" and g.get("area") in AREA_NAMES
            cats = ([g["area"]] + [x for x in g.get("methods", []) if x in METHOD_NAMES]) if ok else []
            prob, reason = (1.0, "") if ok else (0.0, "labelled out of scope")
            report["labelled"] += 1
        else:
            rec = RawRecord(title=p.title, source=p.source, abstract=abstract, journal=p.journal,
                            doi=p.doi, url=p.url, oa_type=m.get("type") or "",
                            oa_field=" / ".join(x for x in (m.get("field"), m.get("subfield")) if x),
                            oa_topic=m.get("topic") or "")
            ok, prob, cats, reason = judge(rec)
        if ok:
            p.categories, p.tags, p.relevance_score = cats, [], int(round(prob * 100))
            kept.append(p)
            report["kept"] += 1
            report["area: " + (cats[0] if cats else "none")] += 1
        else:
            report["removed"] += 1
            report["removed: " + (reason.split(" (")[0] if reason else "model")] += 1
    report["before"] = len(papers)
    if not dry_run:
        store.rewrite(kept)
    return report
