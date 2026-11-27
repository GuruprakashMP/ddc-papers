"""OpenAlex details (type, topic, abstract) of every stored paper, for `python -m ddc rescreen`.

    python tools/fetch_openalex_meta.py <project dir> <out.jsonl>

Asks OpenAlex for 50 DOIs per request (a list request each: about 1,600 for 80,000 papers),
resumes where a previous run stopped, and never writes to the project.
"""
import glob, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
SRC, OUT = sys.argv[1], sys.argv[2]
SELECT = "id,doi,type,primary_topic,primary_location,abstract_inverted_index"
if SRC.endswith(".json"):
    recs = [{"id": r["id"], "doi": r["doi"]} for r in json.load(open(SRC))]
else:
    recs = []
    for f in glob.glob(os.path.join(SRC, "data/papers/*/*.json")):
        for p in json.load(open(f)):
            doi = (p.get("doi") or "").lower()
            m = re.search(r"arxiv\.org/abs/([\w.\-/]+?)(v\d+)?$", p.get("url") or "")
            if not doi and m:
                doi = "10.48550/arxiv." + m.group(1).lower()
            recs.append({"id": p["id"], "doi": doi})
done = set()
if os.path.exists(OUT):
    for line in open(OUT):
        try:
            done.add(json.loads(line)["id"])
        except ValueError:
            pass
todo = [r for r in recs if r["id"] not in done]
out = open(OUT, "a")
for r in todo:
    if not r["doi"]:
        out.write(json.dumps({"id": r["id"], "doi": "", "status": "no-doi"}) + "\n")
todo = [r for r in todo if r["doi"]]
print(len(recs), "records,", len(done), "done,", len(todo), "to fetch", flush=True)

def text(inv):
    words = {}
    for w, pos in (inv or {}).items():
        for i in pos:
            if 0 <= i < 50000:
                words[i] = w
    return " ".join(words[i] for i in sorted(words))

for k in range(0, len(todo), 50):
    chunk = todo[k:k + 50]
    dois = "|".join(r["doi"].replace("|", "") for r in chunk)
    url = ("https://api.openalex.org/works?per_page=50&select=" + SELECT + "&filter=doi:" +
           urllib.parse.quote(dois, safe="/|:"))
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ddc-rescreen/1.0"}), timeout=60) as h:
                res = json.loads(h.read()).get("results") or []
            break
        except urllib.error.HTTPError as e:
            if e.code == 400 and len(chunk) > 1:     # a malformed DOI in the batch: skip batch, retry singles later
                res = None
                break
            time.sleep(5 * (attempt + 1))
        except Exception:
            time.sleep(5 * (attempt + 1))
    else:
        print("gave up on a batch", flush=True); continue
    if res is None:
        continue
    by = {}
    for d in res:
        key = (d.get("doi") or "").lower().replace("https://doi.org/", "")
        by[key] = d
    for r in chunk:
        d = by.get(r["doi"])
        rec = {"id": r["id"], "doi": r["doi"]}
        if not d:
            rec["status"] = "not-found"
        else:
            pt = d.get("primary_topic") or {}
            src = (d.get("primary_location") or {}).get("source") or {}
            rec.update(status="ok", type=d.get("type"), domain=(pt.get("domain") or {}).get("display_name"),
                       field=(pt.get("field") or {}).get("display_name"), subfield=(pt.get("subfield") or {}).get("display_name"),
                       topic=pt.get("display_name"), source=src.get("display_name"), source_type=src.get("type"),
                       abstract=text(d.get("abstract_inverted_index")))
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    out.flush()
    if (k // 50) % 40 == 0:
        print(f"{k + len(chunk)}/{len(todo)}", flush=True)
    time.sleep(0.25)
print("DONE", flush=True)
