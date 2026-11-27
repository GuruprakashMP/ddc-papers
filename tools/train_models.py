"""Train and cross-validate the relevance model (and, with CAT_EXPORT, the categorizer).

    python tools/train_models.py <work dir> [src/ddc/relevance_model.json]
    CAT_EXPORT=src/ddc/category_model.json THRESHOLD=0.6 VERSION=<date> python tools/train_models.py ...

Needs scikit-learn, numpy and scipy (development only; the site and the daily job use the
exported JSON with the standard library). The work dir holds batches/b*.json (labelled
papers with title, journal, abstract), labels/A_b*.json (their labels, as data/labels/
gold.json), recall_pool.json, and meta.jsonl / pool_meta.jsonl from
tools/fetch_openalex_meta.py.
"""
import glob, json, math, os, sys
from collections import Counter
import numpy as np
from scipy.sparse import csr_matrix
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import roc_auc_score

D = sys.argv[1]
EXPORT = sys.argv[2] if len(sys.argv) > 2 else ""
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
from ddc.relevance import features, gate

items = {it["id"]: it for f in sorted(glob.glob(D + "/batches/b*.json")) for it in json.load(open(f))}
labels = {}
for f in glob.glob(D + "/labels/A_b*.json"):
    for r in json.load(open(f)):
        labels[r["id"]] = r
for f in glob.glob(D + "/labels/final_*.json"):        # adjudicated corrections, if any
    for r in json.load(open(f)):
        labels[r["id"]] = r
meta = {}
for name in ("meta.jsonl", "pool_meta.jsonl"):
    p = os.path.join(D, name)
    if os.path.exists(p):
        for line in open(p):
            try:
                r = json.loads(line); meta[r["id"]] = r
            except ValueError:
                pass
pool = {r["id"]: r for r in json.load(open(D + "/recall_pool.json"))}
store = {}
for f in glob.glob(os.path.join(ROOT, "data/papers/*/*.json")):
    for p in json.load(open(f)):
        store[p["id"]] = p

def record(i):
    it, m = items[i], meta.get(i, {})
    ab = m.get("abstract") or it.get("abstract") or ""
    if len(it.get("abstract") or "") > len(ab):
        ab = it["abstract"]
    oa_type = m.get("type") or it.get("openalex_type") or ""
    field = " / ".join(x for x in (m.get("field"), m.get("subfield")) if x)
    if i in store:
        doi, url = store[i].get("doi", ""), store[i].get("url", "")
    else:
        doi, url = pool[i]["doi"], ""
    return dict(title=it["title"], abstract=ab, journal=it["journal"], oa_type=oa_type,
                oa_field=field, oa_topic=m.get("topic") or "", doi=doi, url=url)

ids = sorted(labels)
recs = {i: record(i) for i in ids}
y = np.array([1 if labels[i]["relevant"] == "yes" else 0 for i in ids])
gated = np.array([bool(gate(recs[i]["title"], recs[i]["doi"], recs[i]["url"], recs[i]["oa_type"])) for i in ids])
print(f"{len(ids)} labelled, {y.sum()} yes; gate excludes {gated.sum()} ({y[gated].sum()} of them labelled yes)")
feats = [features(recs[i]["title"], recs[i]["abstract"], recs[i]["journal"], recs[i]["oa_type"],
                  recs[i]["oa_field"], recs[i]["oa_topic"]) for i in ids]

def vectorize(train_idx, min_df=2):
    df = Counter()
    for k in train_idx:
        df.update(feats[k].keys())
    terms = sorted(t for t, c in df.items() if c >= min_df)
    index = {t: j for j, t in enumerate(terms)}
    n = len(train_idx)
    idf = np.array([math.log((1 + n) / (1 + df[t])) + 1 for t in terms])
    return terms, index, idf

def matrix(rows, index, idf):
    data, ri, ci = [], [], []
    for r, k in enumerate(rows):
        vec = {}
        for t, c in feats[k].items():
            j = index.get(t)
            if j is not None:
                vec[j] = (1 + math.log(c)) * idf[j]
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        for j, v in vec.items():
            data.append(v / norm); ri.append(r); ci.append(j)
    return csr_matrix((data, (ri, ci)), shape=(len(rows), len(index)))

C_GRID = [float(c) for c in os.environ.get("CGRID", "2,4,8,16").split(",")]
skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=7)
best = None
for C in C_GRID:
    oof = np.zeros(len(ids))
    for tr, te in skf.split(np.zeros(len(ids)), y):
        if os.environ.get("DROP_UNSURE"):
            tr = np.array([k for k in tr if labels[ids[k]]["relevant"] != "unsure"])
        terms, index, idf = vectorize(tr)
        clf = LogisticRegression(C=C, max_iter=4000, solver="liblinear")
        clf.fit(matrix(tr, index, idf), y[tr])
        oof[te] = clf.predict_proba(matrix(te, index, idf))[:, 1]
    oof[gated] = 0.0
    auc = roc_auc_score(y, oof)
    print(f"C={C}: CV AUC {auc:.4f}")
    if best is None or auc > best[0]:
        best = (auc, C, oof.copy())
auc, C, oof = best
print(f"best C={C} AUC={auc:.4f}")
is_pool = np.array([i.startswith("R") for i in ids])
for th in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
    pred = oof >= th
    tp = (pred & (y == 1)).sum(); fp = (pred & (y == 0)).sum(); fn = (~pred & (y == 1)).sum()
    out = f"th {th}: precision {tp/(tp+fp):.3f} recall {tp/(tp+fn):.3f} kept {pred.mean():.3f}"
    for name, mask in (("store", ~is_pool), ("pool", is_pool)):
        p2 = pred & mask; tp2 = (p2 & (y == 1)).sum(); fp2 = (p2 & (y == 0)).sum(); fn2 = (~pred & mask & (y == 1)).sum()
        out += f" | {name} P {tp2/max(1,tp2+fp2):.3f} R {tp2/max(1,tp2+fn2):.3f}"
    print(out)
json.dump({i: float(p) for i, p in zip(ids, oof)}, open(D + "/oof.json", "w"))

if EXPORT:
    allidx = np.arange(len(ids))
    if os.environ.get("DROP_UNSURE"):
        allidx = np.array([k for k in allidx if labels[ids[k]]["relevant"] != "unsure"])
    terms, index, idf = vectorize(allidx)
    clf = LogisticRegression(C=C, max_iter=4000, solver="liblinear").fit(matrix(allidx, index, idf), y)
    w = clf.coef_[0]
    th = float(os.environ.get("THRESHOLD", "0.5"))
    data = {"version": os.environ.get("VERSION", ""), "terms": terms,
            "idf": [round(float(v), 4) for v in idf], "w": [round(float(v), 4) for v in w],
            "b": round(float(clf.intercept_[0]), 5), "threshold": th,
            "trained_on": int(len(ids)), "cv_auc": round(float(auc), 4), "C": C}
    json.dump(data, open(EXPORT, "w"), ensure_ascii=False, separators=(",", ":"))
    print("exported", EXPORT, len(terms), "terms", os.path.getsize(EXPORT) // 1024, "KB")
    top = np.argsort(w)
    print("most negative:", [terms[j] for j in top[:40]])
    print("most positive:", [terms[j] for j in top[-40:]])

# ---------------------------------------------------------------- categories (area + methods)
CAT_EXPORT = os.environ.get("CAT_EXPORT", "")
if CAT_EXPORT:
    from ddc.taxonomy import AREA_NAMES, METHOD_NAMES
    yes_idx = np.array([k for k in range(len(ids)) if labels[ids[k]]["relevant"] == "yes"
                        and labels[ids[k]].get("area") in AREA_NAMES])
    ya = np.array([AREA_NAMES.index(labels[ids[k]]["area"]) for k in yes_idx])
    ym = np.array([[1 if m in labels[ids[k]].get("methods", []) else 0 for m in METHOD_NAMES] for k in yes_idx])
    df = Counter()
    for k in yes_idx:
        df.update(feats[k].keys())
    vocab = [t for t, c in df.most_common(8000) if c >= 3]
    vindex = {t: j for j, t in enumerate(vocab)}
    n = len(yes_idx)
    vidf = np.array([math.log((1 + n) / (1 + df[t])) + 1 for t in vocab])
    X = matrix(yes_idx, vindex, vidf)
    # cross-validated quality
    acc, f1s = [], np.zeros(len(METHOD_NAMES))
    pa = np.zeros(n, dtype=int); pm = np.zeros((n, len(METHOD_NAMES)))
    for tr, te in StratifiedKFold(5, shuffle=True, random_state=3).split(np.zeros(n), ya):
        ca = LogisticRegression(C=8, max_iter=4000).fit(X[tr], ya[tr])
        pa[te] = ca.predict(X[te])
        for j in range(len(METHOD_NAMES)):
            if ym[tr, j].sum() >= 5:
                cm = LogisticRegression(C=8, max_iter=4000, solver="liblinear").fit(X[tr], ym[tr, j])
                pm[te, j] = cm.predict_proba(X[te])[:, 1]
    print(f"area: CV accuracy {np.mean(pa == ya):.3f} on {n} papers")
    pred = pm >= 0.4
    for r in range(n):
        if not pred[r].any():
            pred[r, pm[r].argmax()] = True
    exact = np.mean((pred == (ym == 1)).all(axis=1))
    tp = (pred & (ym == 1)).sum(); fp = (pred & (ym == 0)).sum(); fn = (~pred & (ym == 1)).sum()
    print(f"methods: micro precision {tp/(tp+fp):.3f} recall {tp/(tp+fn):.3f}, exact set {exact:.3f}")
    for j, m in enumerate(METHOD_NAMES):
        t2 = (pred[:, j] & (ym[:, j] == 1)).sum(); f2 = (pred[:, j] & (ym[:, j] == 0)).sum(); n2 = ym[:, j].sum()
        print(f"   {m:40s} n={n2:4d} P {t2/max(1,t2+f2):.2f} R {t2/max(1,n2):.2f}")
    ca = LogisticRegression(C=8, max_iter=4000).fit(X, ya)
    mw, mb = [], []
    for j in range(len(METHOD_NAMES)):
        cm = LogisticRegression(C=8, max_iter=4000, solver="liblinear").fit(X, ym[:, j])
        mw.append([round(float(v), 3) for v in cm.coef_[0]]); mb.append(round(float(cm.intercept_[0]), 4))
    json.dump({"terms": vocab, "idf": [round(float(v), 4) for v in vidf],
               "areas": AREA_NAMES, "area_w": [[round(float(v), 3) for v in row] for row in ca.coef_],
               "area_b": [round(float(v), 4) for v in ca.intercept_],
               "methods": METHOD_NAMES, "method_w": mw, "method_b": mb, "method_threshold": 0.4,
               "trained_on": int(n)}, open(CAT_EXPORT, "w"), separators=(",", ":"))
    print("exported", CAT_EXPORT, os.path.getsize(CAT_EXPORT) // 1024, "KB")
