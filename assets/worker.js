/* Search engine of the paper index, run off the page's main thread so typing stays smooth.
 *
 * It loads assets/data/manifest.json and the per-year data files (newest years first, then
 * the rest, then the affiliations), and answers the search, author and journal pages.
 * Data files are kept in the browser's Cache Storage under their content hash (the
 * manifest's "v"), so a returning visitor downloads only the files that changed since the
 * last visit: usually just the current year's. Without Cache Storage (an insecure origin,
 * a private window), files come from the network as usual. */
"use strict";

var CACHE = "ddc-papers-data";
var FIRST_YEARS = 3;
var M = null;            // the manifest
var NAMES = [];          // category names; index = code in the data files
var N_AREAS = 0;
var P = [];              // the papers
var state = { years: 0, totalYears: 0, complete: false, affiliations: false };
var keep = {};           // cache keys of the current data files

function fold(s) {
  s = String(s == null ? "" : s);
  if (s.normalize) s = s.normalize("NFD").replace(/[̀-ͯ]/g, "");
  return s.replace(/[‐-―−]/g, "-").toLowerCase();
}

function getJSON(file, v) {
  var url = new URL("data/" + file + (v ? "?v=" + v : ""), self.location.href).href;
  keep[url] = 1;
  function net() {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error(file + " " + r.status);
      return r;
    });
  }
  if (!v || !self.caches) return net().then(function (r) { return r.json(); });
  return caches.open(CACHE).then(function (cache) {
    return cache.match(url).then(function (hit) {
      if (hit) return hit.json().catch(function () { return fromNet(cache); });
      return fromNet(cache);
    });
  }, function () { return net().then(function (r) { return r.json(); }); });
  function fromNet(cache) {
    return net().then(function (r) {
      cache.put(url, r.clone()).catch(function () {});
      return r.json();
    });
  }
}

function prune() {
  if (!self.caches) return;
  caches.open(CACHE).then(function (cache) {
    return cache.keys().then(function (reqs) {
      reqs.forEach(function (req) { if (!keep[req.url]) cache.delete(req); });
    });
  }).catch(function () {});
}

/* A paper from a format 2 row: [id, title, authors, journal, published, doi, categories,
 * url, toc, abstract] (see ddc/site/generator.py), or from an older file's object. */
function fromRow(r, journals) {
  return { id: r[0], title: r[1] || "", authors: r[2] || [], journal: journals[r[3]] || "",
           published: r[4] || "", doi: r[5] || "", cats: r[6] || [], url: r[7] || "",
           toc: r[8] || "", ab: r[9] || "", sd: r[10] || r[4] || "" };
}
function fromObject(o) {
  var cats = [];
  (o.categories || []).forEach(function (c) { var i = NAMES.indexOf(c); if (i !== -1) cats.push(i); });
  return { id: o.id, title: o.title || "", authors: o.authors || [], journal: o.journal || "",
           published: o.published || "", doi: o.doi || "", cats: cats,
           url: o.doi ? "" : (o.url || ""), toc: o.toc || "", ab: "", sd: o.published || "" };
}
function index(p) {
  var names = p.cats.map(function (c) { return NAMES[c] || ""; }).join(" ");
  p.year = (p.published || "").slice(0, 4);
  p.t = fold(p.title);
  p.hay = p.t + " \u0001 " + fold(p.authors.join(" ; ")) + " \u0001 " + fold(p.journal) + " " +
    fold(p.doi) + " " + fold(names) + " " + p.published;
  return p;
}

function loadYears(list) {
  return Promise.all(list.map(function (y) {
    return getJSON(y.file, y.v).then(function (d) {
      var rows = Array.isArray(d) ? d.map(fromObject) : (d.p || []).map(function (r) { return fromRow(r, d.j || []); });
      return rows.map(index);
    }).catch(function () { return []; });
  })).then(function (parts) {
    parts.forEach(function (rows) { for (var i = 0; i < rows.length; i++) P.push(rows[i]); });
    state.years += list.length;
  });
}

function loadAffiliations(list) {
  var byId = {};
  P.forEach(function (p) { byId[p.id] = p; });
  return Promise.all(list.filter(function (y) { return y.aff; }).map(function (y) {
    return Promise.all([getJSON(y.file, y.v), getJSON(y.aff, y.av)]).then(function (both) {
      var d = both[0], affs = both[1];
      if (!d || !Array.isArray(d.p) || !Array.isArray(affs)) return;
      d.p.forEach(function (r, i) {
        var p = byId[r[0]];
        if (p && affs[i]) p.hay += " \u0001 " + fold(affs[i]);
      });
    }).catch(function () {});
  }));
}

function counts() {
  var area = {}, method = {}, year = {}, journal = {};
  P.forEach(function (p) {
    p.cats.forEach(function (c) { if (c < N_AREAS) area[c] = (area[c] || 0) + 1; else method[c] = (method[c] || 0) + 1; });
    if (p.year) year[p.year] = (year[p.year] || 0) + 1;
    if (p.journal) journal[p.journal] = (journal[p.journal] || 0) + 1;
  });
  var journals = Object.keys(journal).sort(function (a, b) { return journal[b] - journal[a] || (a < b ? -1 : 1); })
    .map(function (j) { return [j, journal[j]]; });
  return { area: area, method: method, year: year, journals: journals };
}

function progress() {
  self.postMessage({ t: "progress", papers: P.length, total: M ? M.total : 0, years: state.years,
                     totalYears: state.totalYears, complete: state.complete,
                     affiliations: state.affiliations, generated: M ? M.generated : "",
                     names: NAMES, areas: N_AREAS, counts: counts() });
}

function init() {
  fetch(new URL("data/manifest.json", self.location.href).href, { cache: "no-cache" })
    .then(function (r) { if (!r.ok) throw new Error("manifest.json " + r.status); return r.json(); })
    .then(function (man) {
      M = man;
      NAMES = Array.isArray(man.categories) ? man.categories : [];
      N_AREAS = man.areas || 0;
      var years = (man.years || []).slice().sort(function (a, b) { return b.year - a.year; });
      state.totalYears = years.length;
      return loadYears(years.slice(0, FIRST_YEARS)).then(function () {
        P.sort(byNew);
        state.complete = years.length <= FIRST_YEARS;
        progress();
        if (state.complete) return;
        return loadYears(years.slice(FIRST_YEARS)).then(function () {
          P.sort(byNew);
          state.complete = true;
          progress();
        });
      }).then(function () {
        return loadAffiliations(years);
      }).then(function () {
        state.affiliations = true;
        progress();
        prune();
      });
    })
    .catch(function (err) { self.postMessage({ t: "error", message: String(err && err.message || err) }); });
}

/* Newest first by the date in [10] (the day added, for a paper dated ahead), else published. */
function byNew(a, b) {
  return a.sd < b.sd ? 1 : a.sd > b.sd ? -1 : (a.id < b.id ? 1 : -1);
}

/* Words and "quoted phrases"; every one must occur. */
function parse(q) {
  var out = [], re = /"([^"]+)"|(\S+)/g, m;
  q = fold(q);
  while ((m = re.exec(q))) out.push((m[1] || m[2]).trim());
  return out.filter(Boolean);
}

function filter(m) {
  var terms = parse(m.q || "");
  var area = m.area === "" || m.area == null ? -1 : NAMES.indexOf(m.area);
  var method = m.method === "" || m.method == null ? -1 : NAMES.indexOf(m.method);
  if ((m.area && area === -1) || (m.method && method === -1)) return [];
  var out = [];
  for (var i = 0; i < P.length; i++) {
    var p = P[i];
    if (m.year && p.year !== m.year) continue;
    if (m.journal && p.journal !== m.journal) continue;
    if (m.author && p.authors.indexOf(m.author) === -1) continue;
    if (area !== -1 && p.cats.indexOf(area) === -1) continue;
    if (method !== -1 && p.cats.indexOf(method) === -1) continue;
    var ok = true;
    for (var k = 0; k < terms.length; k++) if (p.hay.indexOf(terms[k]) === -1) { ok = false; break; }
    if (ok) out.push(p);
  }
  if (m.sort === "old") out.reverse();
  else if (m.sort === "best" && terms.length) {
    var score = function (p) {
      var s = 0;
      for (var k = 0; k < terms.length; k++) if (p.t.indexOf(terms[k]) !== -1) s += 3;
      if (terms.length > 1 && p.t.indexOf(terms.join(" ")) !== -1) s += 4;
      return s;
    };
    out = out.map(function (p, i) { return [score(p), i, p]; })
      .sort(function (a, b) { return b[0] - a[0] || a[1] - b[1]; })
      .map(function (x) { return x[2]; });
  }
  return out;
}

function plain(p) {
  return { id: p.id, title: p.title, authors: p.authors, journal: p.journal, published: p.published,
           doi: p.doi, cats: p.cats, url: p.url, toc: p.toc, ab: p.ab };
}

function answer(m) {
  var reply = { t: "r", id: m.id, complete: state.complete, affiliations: state.affiliations };
  if (m.kind === "names") {
    var field = m.field === "authors" ? "authors" : "journal";
    var tally = {};
    filter({ area: m.area }).forEach(function (p) {
      if (field === "authors") p.authors.forEach(function (a) { tally[a] = (tally[a] || 0) + 1; });
      else if (p.journal) tally[p.journal] = (tally[p.journal] || 0) + 1;
    });
    var names = Object.keys(tally);
    var needle = fold(m.q || "").trim();
    var hits = needle ? names.filter(function (n) { return fold(n).indexOf(needle) !== -1; }) : names;
    hits.sort(function (a, b) { return tally[b] - tally[a] || (a < b ? -1 : a > b ? 1 : 0); });
    reply.total = hits.length;
    reply.all = names.length;
    reply.items = hits.slice(0, m.limit || 300).map(function (n) { return [n, tally[n]]; });
  } else {
    var found = filter(m);
    reply.total = found.length;
    reply.items = found.slice(0, m.limit || 50).map(plain);
    if (m.journals) {
      var j = {};
      found.forEach(function (p) { if (p.journal) j[p.journal] = (j[p.journal] || 0) + 1; });
      reply.journals = Object.keys(j).sort(function (a, b) { return j[b] - j[a]; }).slice(0, 8)
        .map(function (n) { return [n, j[n]]; });
    }
  }
  self.postMessage(reply);
}

self.onmessage = function (e) {
  var m = e.data || {};
  if (m.t === "init") init();
  else if (m.t === "q") answer(m);
};
