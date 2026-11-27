/* Paper index front end: the front page's list of recently added papers, the search,
 * journal and author pages, the zoom view of graphical abstracts, and the Show abstract /
 * Save / Mark read buttons of every paper card (the archive's cards get them too).
 * Vanilla JS, no dependencies.
 *
 * Data: assets/data/feed.json (papers added in the last 30 days) for the front page; the
 * search, journal and author pages ask worker.js, which loads the per-year data files.
 *
 * What a visitor marks (read, saved, followed journals, the last visit) is kept in
 * localStorage under "gp.idx.<index key>." (the site shares its origin with other pages,
 * so the names carry a prefix). Every access is guarded: without storage the marks last
 * for the page only. Nothing is sent anywhere, except an abstract request (OpenAlex or
 * Crossref, when asked for) and the visitor counter. */
(function () {
  "use strict";

  var body = document.body;
  var app = document.getElementById("app");
  var KEY = body.getAttribute("data-index-key") || "index";
  var SITE = body.getAttribute("data-site-title") || document.title;
  var ROOT = body.getAttribute("data-root") || "";
  var PAGE = app ? app.getAttribute("data-page") : (body.getAttribute("data-page") || "");
  var FEED_PAGE = 60;       // front page cards per "Show more"
  var PAGE_SIZE = 50;       // search results per "Show more"
  var AUTHORS_SHOWN = 12;
  var READ_MAX = 20000;     // read marks kept (oldest dropped first)
  var SAVED_MAX = 2000;
  var VISIT_GAP = 30 * 60 * 1000;   // a page load after 30 min without one starts a new visit
  var COUNTER = "https://abacus.jasoncameron.dev/";
  var COUNTER_KEY = "guruprakashmp-github-io/ddc-papers";

  // ---------------------------------------------------------------- utils
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  /* Text from the data as shown: an em dash becomes a spaced hyphen (the record itself,
   * and every link and search built from it, keeps the publisher's text). */
  function nd(s) { return String(s == null ? "" : s).replace(/\s*—\s*/g, " - ").trim(); }
  function tx(s) { return esc(nd(s)); }
  function params() { return new URLSearchParams(location.search); }
  function fmt(n) { return Number(n).toLocaleString("en-US"); }
  function plural(n, one, many) { return fmt(n) + " " + (n === 1 ? one : (many || one + "s")); }
  function toSet(list) { var s = {}; for (var i = 0; i < list.length; i++) s[list[i]] = 1; return s; }
  function isStr(v) { return typeof v === "string" && v.length > 0; }
  function $(id) { return document.getElementById(id); }
  /* Mirror of ddc.models.normalize_author, for names arriving in a link (?a=). */
  function normalizeAuthor(name) {
    if (!name) return "";
    var n = String(name);
    if (n.normalize) n = n.normalize("NFC");
    n = n.replace(/ /g, " ").replace(/[​-‍﻿]/g, "");
    n = n.replace(/[‐-―−﹘﹣－]/g, "-").replace(/\s+/g, " ").trim();
    var prev = null;
    while (prev !== n) {
      prev = n;
      n = n.replace(/^(?:prof(?:essor)?|dr|doctor|mr|mrs|ms|miss|sir|dame|rev)\.?\s+/i, "").trim();
      n = n.replace(/^[.,;\s]+/, "").trim();
    }
    n = n.replace(/[,;\s]+$/, "").trim();
    return n || String(name).replace(/\s+/g, " ").trim();
  }

  var MONTHS = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"];
  var DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  function ymd(iso) { var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ""); return m ? [+m[1], +m[2], +m[3]] : null; }
  function prettyDate(iso) {
    var d = ymd(iso);
    if (d) return d[2] + " " + MONTHS[d[1] - 1] + " " + d[0];
    var p = String(iso || "").split("-");
    return p.length === 2 ? MONTHS[+p[1] - 1] + " " + p[0] : (iso || "");
  }
  function shortDate(iso) {
    var d = ymd(iso);
    return d ? d[2] + " " + MONTHS[d[1] - 1].slice(0, 3) + " " + d[0] : prettyDate(iso);
  }
  function localToday() { var d = new Date(); return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()); }
  function daysAgo(iso) { var d = ymd(iso); return d ? Math.round((localToday() - Date.UTC(d[0], d[1] - 1, d[2])) / 864e5) : NaN; }
  /* A day heading: Today, Yesterday, the weekday within a week, else the date. */
  function dayLabel(iso) {
    var n = daysAgo(iso), d = ymd(iso);
    if (!d) return "Earlier";
    if (n === 0) return "Today";
    if (n === 1) return "Yesterday";
    var wd = DAYS[new Date(Date.UTC(d[0], d[1] - 1, d[2])).getUTCDay()];
    var date = d[2] + " " + MONTHS[d[1] - 1] + (d[0] !== new Date().getFullYear() ? " " + d[0] : "");
    return n > 1 && n < 7 ? wd + ", " + date : date;
  }
  /* manifest/feed "generated" is "YYYY-MM-DD HH:MM UTC". */
  function parseGenerated(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(s || "");
    return m ? Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) : NaN;
  }
  function agoTime(ms) {
    var s = (Date.now() - ms) / 1000;
    if (!(s >= -300)) return "";
    if (s < 90) return "just now";
    var min = s / 60;
    if (min < 60) return Math.round(min) + " min ago";
    var h = min / 60;
    if (h < 36) return Math.round(h) + " h ago";
    var d = Math.round(h / 24);
    return d + (d === 1 ? " day ago" : " days ago");
  }
  function visitWhen(ms) {
    var d = new Date(ms);
    var iso = d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2);
    var n = daysAgo(iso);
    return n === 0 ? "earlier today" : n === 1 ? "yesterday" : n < 14 ? n + " days ago" : prettyDate(iso);
  }

  // ---------------------------------------------------------------- local storage
  var NS = "gp.idx." + KEY + ".";
  var storageOK = (function () {
    try {
      var k = NS + "probe";
      window.localStorage.setItem(k, "1");
      window.localStorage.removeItem(k);
      return true;
    } catch (e) { return false; }
  })();
  var mem = {};
  function sget(name, fallback) {
    if (storageOK) {
      try {
        var v = window.localStorage.getItem(NS + name);
        return v == null ? fallback : JSON.parse(v);
      } catch (e) { return fallback; }
    }
    return Object.prototype.hasOwnProperty.call(mem, name) ? mem[name] : fallback;
  }
  function sset(name, value) {
    mem[name] = value;
    if (!storageOK) return false;
    try { window.localStorage.setItem(NS + name, JSON.stringify(value)); return true; }
    catch (e) { return false; }
  }

  // Every change re-reads storage first, so two open tabs never undo each other's marks.
  function readList() { var a = sget("read", []); return Array.isArray(a) ? a.filter(isStr) : []; }
  function savedList() {
    var a = sget("saved", []);
    return Array.isArray(a) ? a.filter(function (p) { return p && isStr(p.id) && typeof p.title === "string"; }) : [];
  }
  function followList() { var a = sget("follow", []); return Array.isArray(a) ? a.filter(isStr) : []; }
  var readSet = toSet(readList());
  var savedSet = toSet(savedList().map(function (p) { return p.id; }));
  function isRead(id) { return readSet[id] === 1; }
  function isSaved(id) { return savedSet[id] === 1; }
  function setRead(ids, on) {
    var list = readList(), set = toSet(list);
    ids.forEach(function (id) {
      if (on && set[id] !== 1) { list.push(id); set[id] = 1; }
      else if (!on && set[id] === 1) delete set[id];
    });
    if (!on) list = list.filter(function (id) { return set[id] === 1; });
    if (list.length > READ_MAX) list = list.slice(list.length - READ_MAX);
    sset("read", list);
    readSet = toSet(list);
  }
  function metaOf(p) {
    var m = { id: p.id, title: p.title, journal: p.journal || "", published: p.published || "",
              doi: p.doi || "", url: p.url || "", savedAt: Date.now() };
    if (Array.isArray(p.authors)) {
      m.authors = p.authors.slice(0, AUTHORS_SHOWN);
      var more = (p.na || 0) + Math.max(0, p.authors.length - AUTHORS_SHOWN);
      if (more) m.na = more;
    } else if (p.authorsText) m.authorsText = p.authorsText;
    if (p.added) m.added = p.added;
    if (p.toc) m.toc = p.toc;
    if (p.ab) m.ab = p.ab;
    return m;
  }
  function setSaved(p, on) {
    var list = savedList().filter(function (s) { return s.id !== p.id; });
    if (on) list.unshift(metaOf(p));
    if (list.length > SAVED_MAX) list = list.slice(0, SAVED_MAX);
    sset("saved", list);
    savedSet = toSet(list.map(function (s) { return s.id; }));
  }
  function reloadState() {
    readSet = toSet(readList());
    savedSet = toSet(savedList().map(function (p) { return p.id; }));
  }

  // ---------------------------------------------------------------- data rows
  /* A paper from a data row (ddc/site/generator.py, format 2):
   * [id, title, authors, journal, published, doi, categories, url, toc, abstract(, added, na)] */
  function fromRow(r, journals) {
    return { id: r[0], title: r[1] || "", authors: r[2] || [], journal: journals[r[3]] || "",
             published: r[4] || "", doi: r[5] || "", cats: r[6] || [], url: r[7] || "",
             toc: r[8] || "", ab: r[9] || "", added: r[10] || "", na: r[11] || 0 };
  }
  function feedPapers(d) {
    if (d && Array.isArray(d.p)) return d.p.map(function (r) { return fromRow(r, d.j || []); });
    if (d && Array.isArray(d.papers)) {   // an older build's feed.json
      return d.papers.map(function (o) {
        return { id: o.id, title: o.title || "", authors: o.authors || [], journal: o.journal || "",
                 published: o.published || "", doi: o.doi || "", cats: [], url: o.url || "",
                 toc: o.toc || "", ab: "", added: o.added || "", na: o.na || 0 };
      });
    }
    return [];
  }

  // ---------------------------------------------------------------- paper cards
  var known = {};
  var ICON = {
    full: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M9.5 2.5h4v4M13.5 2.5 7.5 8.5M12 9.5V13a.5.5 0 0 1-.5.5h-8A.5.5 0 0 1 3 13V5a.5.5 0 0 1 .5-.5H7" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    abs: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4h10M3 8h10M3 12h6" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    save: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 2.5h7v11L8 11l-3.5 2.5z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
    saved: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 2.5h7v11L8 11l-3.5 2.5z" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>',
    read: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 8.5 3 3 6-7" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'
  };
  function paperLink(p) { return p.doi ? "https://doi.org/" + p.doi : (p.url || ""); }
  function authorsHtml(p) {
    if (!Array.isArray(p.authors)) return tx(p.authorsText || "");
    var s = p.authors.slice(0, AUTHORS_SHOWN).map(function (a) {
      return '<a href="' + ROOT + "authors.html?a=" + encodeURIComponent(a) + '">' + tx(a) + "</a>";
    }).join(", ");
    var more = (p.na || 0) + Math.max(0, p.authors.length - AUTHORS_SHOWN);
    if (more) s += " and " + more + " more";
    return s;
  }
  function timeHtml(p) {
    var pub = p.published || "";
    var t = pub ? "Published " + prettyDate(pub) : "";
    if (p.added) t += (t ? ", " : "") + "added " + prettyDate(p.added);
    return '<time datetime="' + esc(pub) + '" title="' + esc(t) + '">' + esc(shortDate(pub)) + "</time>";
  }
  function tocLarge(url) {
    if (/onlinelibrary\.wiley\.com\//.test(url)) return url.replace(/-m\.(png|jpe?g|gif)$/i, ".$1");
    if (/^https:\/\/ars\.els-cdn\.com\/.*-ga1\.jpg$/.test(url)) return url.replace(/\.jpg$/, "_lrg.jpg");
    return url;
  }
  function tocPublisher(url) {
    return /wiley\.com\//.test(url) ? "Wiley" : /els-cdn\.com\//.test(url) ? "Elsevier" : "the publisher";
  }
  function tocFigure(p) {
    if (!p.toc || !/^https:\/\//.test(p.toc)) return "";
    var big = tocLarge(p.toc);
    return '<figure class="toc"><a class="toc-btn" href="' + esc(big) + '" data-zoom="' + esc(big) +
      '" target="_blank" rel="noopener" aria-label="Enlarge the graphical abstract"><img src="' + esc(p.toc) +
      '" alt="Graphical abstract (' + esc(tocPublisher(p.toc)) + ')" loading="lazy" decoding="async" referrerpolicy="no-referrer"></a></figure>';
  }
  function actionButtons(id) {
    var r = isRead(id), s = isSaved(id);
    return '<button type="button" class="act" data-act="abstract" aria-expanded="false" title="Show the abstract (a)">' + ICON.abs + "<span>Show abstract</span></button>" +
      '<button type="button" class="act" data-act="save" aria-pressed="' + s + '" title="' + (s ? "Remove from saved (s)" : "Save this paper (s)") + '">' +
      (s ? ICON.saved : ICON.save) + "<span>" + (s ? "Saved" : "Save") + "</span></button>" +
      '<button type="button" class="act" data-act="read" aria-pressed="' + r + '" title="' + (r ? "Mark as unread (r)" : "Mark as read (r)") + '">' +
      ICON.read + "<span>" + (r ? "Read" : "Mark read") + "</span></button>";
  }
  function renderCard(p, opts) {
    known[p.id] = p;
    var link = paperLink(p);
    var title = link ? '<a href="' + esc(link) + '" target="_blank" rel="noopener">' + tx(p.title) + "</a>" : tx(p.title);
    var journal = p.journal ? '<a class="jbadge" href="' + ROOT + "journals.html?j=" + encodeURIComponent(p.journal) + '">' + tx(p.journal) + "</a>" : "";
    var isNew = opts && opts.isNew ? '<span class="tag-new">New</span>' : "";
    var fig = tocFigure(p);
    return '<article class="card' + (fig ? " has-toc" : "") + (isRead(p.id) ? " is-read" : "") +
      '" data-id="' + esc(p.id) + '" data-doi="' + esc(p.doi || "") + '" tabindex="-1">' + fig +
      '<div class="body"><p class="meta">' + isNew + journal + timeHtml(p) + "</p>" +
      '<h3 class="title">' + title + "</h3>" +
      '<p class="authors">' + authorsHtml(p) + "</p>" +
      '<div class="actions">' +
      (link ? '<a class="act act-full" href="' + esc(link) + '" target="_blank" rel="noopener">' + ICON.full + "<span>Full text</span></a>" : "") +
      actionButtons(p.id) + (p.doi ? '<span class="doi">' + esc(p.doi) + "</span>" : "") +
      "</div></div></article>";
  }
  /* A server-rendered card (front page before the feed loads, archive) as a paper record. */
  function paperFromCard(card) {
    var id = card.getAttribute("data-id");
    if (known[id]) return known[id];
    var t = card.querySelector(".title"), a = card.querySelector(".title a");
    var j = card.querySelector(".jbadge"), tm = card.querySelector("time");
    var au = card.querySelector(".authors"), img = card.querySelector(".toc img");
    var p = {
      id: id, title: t ? t.textContent.trim() : "", authorsText: au ? au.textContent.trim() : "",
      journal: j ? j.textContent.trim() : "", published: tm ? tm.getAttribute("datetime") || "" : "",
      doi: card.getAttribute("data-doi") || "", url: a ? a.getAttribute("href") || "" : "",
      toc: img ? img.getAttribute("src") || "" : "", ab: ""
    };
    known[id] = p;
    return p;
  }
  /* Server-rendered cards get the buttons that need this script. */
  function enhance(scope) {
    [].forEach.call((scope || document).querySelectorAll(".card[data-id]"), function (card) {
      var actions = card.querySelector(".actions");
      if (!actions || actions.querySelector("[data-act]")) return;
      var id = card.getAttribute("data-id"), doi = actions.querySelector(".doi");
      var full = actions.querySelector(".act-full");
      if (full && !full.querySelector("svg")) full.innerHTML = ICON.full + "<span>" + full.textContent + "</span>";
      var tmp = document.createElement("div");
      tmp.innerHTML = actionButtons(id);
      while (tmp.firstChild) actions.insertBefore(tmp.firstChild, doi || null);
      card.setAttribute("tabindex", "-1");
      card.classList.toggle("is-read", isRead(id));
    });
  }
  function syncCard(card) {
    var id = card.getAttribute("data-id"), r = isRead(id), s = isSaved(id);
    card.classList.toggle("is-read", r);
    var sb = card.querySelector('[data-act="save"]'), rb = card.querySelector('[data-act="read"]');
    if (sb) {
      sb.setAttribute("aria-pressed", String(s));
      sb.title = s ? "Remove from saved (s)" : "Save this paper (s)";
      sb.innerHTML = (s ? ICON.saved : ICON.save) + "<span>" + (s ? "Saved" : "Save") + "</span>";
    }
    if (rb) {
      rb.setAttribute("aria-pressed", String(r));
      rb.title = r ? "Mark as unread (r)" : "Mark as read (r)";
      rb.innerHTML = ICON.read + "<span>" + (r ? "Read" : "Mark read") + "</span>";
    }
  }
  function syncAllCards() { [].forEach.call(document.querySelectorAll(".card[data-id]"), syncCard); }

  // ---------------------------------------------------------------- abstracts
  /* Asked for by DOI, on click (or a moment before: when the pointer reaches the button).
   * "ab" says where an abstract is: "o" OpenAlex has it, "c" OpenAlex has none so ask
   * Crossref, "" not known (OpenAlex, then Crossref). Kept in this page's memory only. */
  var absCache = {};
  function getJSON(url) {
    return fetch(url).then(function (r) {
      if (r.status === 404) return null;
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }
  function doiPath(doi) { return String(doi).trim().split("/").map(encodeURIComponent).join("/"); }
  function squash(s) { return String(s || "").replace(/\s+/g, " ").trim(); }
  function cleanAbstract(t) {
    t = squash(t).replace(/^(?:High Resolution Image\s+)?Download MS PowerPoint Slide\s+/i, "");
    return t.replace(/^(?:Abstract|Summary|Graphical abstract)\s*[:.]?\s+/i, "").trim();
  }
  function fromInverted(inv) {
    if (!inv || typeof inv !== "object") return "";
    var words = [];
    Object.keys(inv).forEach(function (w) {
      var pos = inv[w];
      if (Array.isArray(pos)) pos.forEach(function (i) { if (typeof i === "number" && i >= 0 && i < 50000) words[i] = w; });
    });
    return cleanAbstract(words.filter(function (w) { return w != null; }).join(" "));
  }
  function fromJats(xml) {
    var doc;
    try { doc = new DOMParser().parseFromString("<div>" + xml + "</div>", "text/html"); }
    catch (e) { return []; }
    var out = [];
    (function walk(node) {
      for (var c = node.firstElementChild; c; c = c.nextElementSibling) {
        var n = c.tagName.toLowerCase().replace(/^jats:/, "");
        if (n === "title") {
          var tt = squash(c.textContent);
          if (tt && !/^(abstract|summary|graphical abstract)[:.]?$/i.test(tt)) out.push({ title: tt });
        } else if (n === "p") {
          var tp = squash(c.textContent);
          if (tp) out.push({ text: tp });
        } else walk(c);
      }
    })(doc.body);
    if (!out.length) {
      var all = cleanAbstract(doc.body.textContent);
      return all ? [{ text: all }] : [];
    }
    var merged = [];
    out.forEach(function (x) {
      var last = merged[merged.length - 1];
      if (x.text && last && last.title && !last.text) last.text = x.text;
      else merged.push(x);
    });
    if (merged[0] && merged[0].text && !merged[0].title) merged[0].text = cleanAbstract(merged[0].text);
    return merged.filter(function (x) { return x.text || x.title; });
  }
  function getAbstract(p) {
    if (!p.doi) return Promise.resolve({ none: true });
    var k = String(p.doi).toLowerCase();
    if (absCache[k]) return absCache[k];
    var errors = 0, path = doiPath(p.doi);
    function openalex() {
      return getJSON("https://api.openalex.org/works/doi:" + path + "?select=id,abstract_inverted_index").then(function (j) {
        var t = j && fromInverted(j.abstract_inverted_index);
        return t ? { paras: [{ text: t }], source: "OpenAlex", href: (j.id && /^https:\/\/openalex\.org\//.test(j.id)) ? j.id : "https://openalex.org/" } : null;
      }, function () { errors++; return null; });
    }
    function crossref() {
      return getJSON("https://api.crossref.org/works/" + path).then(function (j) {
        var a = j && j.message && j.message.abstract;
        var paras = typeof a === "string" ? fromJats(a) : [];
        return paras.length ? { paras: paras, source: "Crossref", href: "https://api.crossref.org/works/" + path } : null;
      }, function () { errors++; return null; });
    }
    var order = p.ab === "c" ? [crossref] : p.ab === "o" ? [openalex, crossref] : [openalex, crossref];
    var pr = order[0]().then(function (r) {
      if (r || order.length < 2 || (p.ab === "o" && !errors)) return r;
      return order[1]();
    }).then(function (r) {
      if (r) return r;
      if (errors) { delete absCache[k]; return { error: true }; }
      return { none: true };
    });
    absCache[k] = pr;
    return pr;
  }
  var absSeq = 0;
  function toggleAbstract(card, p, retry) {
    var btn = card.querySelector('[data-act="abstract"]');
    if (!btn) return;
    var box = card.querySelector(".abstract");
    if (!box) {
      box = document.createElement("div");
      box.className = "abstract";
      box.id = "abs-" + (++absSeq);
      box.setAttribute("aria-live", "polite");
      card.querySelector(".body").appendChild(box);
      btn.setAttribute("aria-controls", box.id);
    }
    var label = btn.querySelector("span") || btn;
    if (!retry && btn.getAttribute("aria-expanded") === "true") {
      box.hidden = true; btn.setAttribute("aria-expanded", "false"); label.textContent = "Show abstract";
      return;
    }
    box.hidden = false; btn.setAttribute("aria-expanded", "true"); label.textContent = "Hide abstract";
    if (box.getAttribute("data-state") === "done") return;
    box.innerHTML = '<p class="note">Loading the abstract…</p>';
    getAbstract(p).then(function (r) {
      box.innerHTML = "";
      if (r.paras) {
        r.paras.forEach(function (x) {
          var el = document.createElement("p");
          if (x.title) { var b = document.createElement("strong"); b.textContent = nd(x.title) + " "; el.appendChild(b); }
          if (x.text) el.appendChild(document.createTextNode(nd(x.text)));
          box.appendChild(el);
        });
        var src = document.createElement("p");
        src.className = "src";
        src.appendChild(document.createTextNode("Abstract from "));
        var a = document.createElement("a");
        a.href = r.href; a.target = "_blank"; a.rel = "noopener"; a.textContent = r.source;
        src.appendChild(a);
        box.appendChild(src);
        box.setAttribute("data-state", "done");
      } else if (r.none) {
        box.innerHTML = '<p class="note">No abstract is available for this paper. Use Full text to read it at the publisher.</p>';
        box.setAttribute("data-state", "done");
      } else {
        box.innerHTML = '<p class="note">Could not reach OpenAlex or Crossref for the abstract. ' +
          '<button type="button" class="linkbtn" data-act="abstract-retry">Try again</button></p>';
        box.removeAttribute("data-state");
      }
    });
  }
  function prefetchAbstract(e) {
    var b = e.target && e.target.closest ? e.target.closest('[data-act="abstract"]') : null;
    var card = b && b.closest(".card[data-id]");
    if (!card || b.getAttribute("aria-expanded") === "true") return;
    var p = known[card.getAttribute("data-id")] || paperFromCard(card);
    if (p.doi) getAbstract(p);
  }
  document.addEventListener("pointerover", prefetchAbstract, { passive: true });
  document.addEventListener("focusin", prefetchAbstract);

  // ---------------------------------------------------------------- zoom view
  /* Graphical abstracts open full screen: wheel, pinch, + and - zoom; drag pans; double
   * click or double tap switches between fitted and 2.5 times; Esc closes. */
  var Z = null;
  function zoomBuild() {
    var el = document.createElement("div");
    el.className = "zoom";
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-modal", "true");
    el.setAttribute("aria-label", "Graphical abstract");
    el.innerHTML = '<div class="zoom-stage"><img alt="" referrerpolicy="no-referrer" draggable="false"></div>' +
      '<p class="zoom-cap"></p><button type="button" class="zoom-close" aria-label="Close">✕</button>' +
      '<div class="zoom-bar"><button type="button" data-z="out" aria-label="Zoom out">−</button>' +
      '<button type="button" data-z="fit">Fit</button><button type="button" data-z="in" aria-label="Zoom in">+</button></div>';
    document.body.appendChild(el);
    var z = { el: el, stage: el.querySelector(".zoom-stage"), img: el.querySelector("img"),
              cap: el.querySelector(".zoom-cap"), s: 1, x: 0, y: 0, fit: 1, w: 0, h: 0,
              pts: {}, last: null, pinch: null, tap: 0, back: null };
    function apply() { z.img.style.transform = "translate(" + z.x + "px," + z.y + "px) scale(" + z.s + ")"; }
    function fitNow() {
      if (!z.w) return;
      var vw = z.stage.clientWidth, vh = z.stage.clientHeight;
      z.fit = Math.min((vw - 32) / z.w, (vh - 120) / z.h, 3);
      z.s = z.fit; z.x = (vw - z.w * z.s) / 2; z.y = (vh - z.h * z.s) / 2 + 10;
      apply();
    }
    function zoomAt(f, cx, cy) {
      var s = Math.max(z.fit * 0.5, Math.min(z.s * f, Math.max(6, z.fit * 8)));
      z.x = cx - (cx - z.x) * s / z.s; z.y = cy - (cy - z.y) * s / z.s; z.s = s;
      apply();
    }
    z.fitNow = fitNow;
    z.img.addEventListener("load", function () { z.w = z.img.naturalWidth; z.h = z.img.naturalHeight; fitNow(); });
    z.img.addEventListener("error", function () {
      if (z.back && z.img.src !== z.back) { var b = z.back; z.back = null; z.img.src = b; }
    });
    z.stage.addEventListener("wheel", function (e) {
      e.preventDefault();
      var r = z.stage.getBoundingClientRect();
      zoomAt(Math.exp(-e.deltaY * (e.deltaMode === 1 ? 0.05 : 0.0015)), e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });
    z.stage.addEventListener("pointerdown", function (e) {
      z.stage.setPointerCapture && z.stage.setPointerCapture(e.pointerId);
      z.pts[e.pointerId] = [e.clientX, e.clientY];
      var ids = Object.keys(z.pts);
      if (ids.length === 2) {
        var a = z.pts[ids[0]], b = z.pts[ids[1]];
        z.pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), s: z.s };
      } else {
        z.last = [e.clientX, e.clientY];
        var now = Date.now();
        if (now - z.tap < 300) {
          var r = z.stage.getBoundingClientRect();
          if (z.s > z.fit * 1.2) fitNow(); else zoomAt(2.5 * z.fit / z.s, e.clientX - r.left, e.clientY - r.top);
          z.tap = 0;
        } else z.tap = now;
      }
      z.stage.classList.add("dragging");
    });
    z.stage.addEventListener("pointermove", function (e) {
      if (!z.pts[e.pointerId]) return;
      z.pts[e.pointerId] = [e.clientX, e.clientY];
      var ids = Object.keys(z.pts);
      if (ids.length === 2 && z.pinch) {
        var a = z.pts[ids[0]], b = z.pts[ids[1]], r = z.stage.getBoundingClientRect();
        var d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        zoomAt((z.pinch.s * d / z.pinch.d) / z.s, (a[0] + b[0]) / 2 - r.left, (a[1] + b[1]) / 2 - r.top);
      } else if (z.last) {
        z.x += e.clientX - z.last[0]; z.y += e.clientY - z.last[1];
        z.last = [e.clientX, e.clientY];
        apply();
      }
    });
    function up(e) {
      delete z.pts[e.pointerId];
      if (Object.keys(z.pts).length < 2) z.pinch = null;
      if (!Object.keys(z.pts).length) { z.last = null; z.stage.classList.remove("dragging"); }
    }
    z.stage.addEventListener("pointerup", up);
    z.stage.addEventListener("pointercancel", up);
    el.addEventListener("click", function (e) {
      var t = e.target;
      if (t.closest(".zoom-close")) { zoomClose(); return; }
      var b = t.closest("[data-z]");
      if (!b) return;
      var w = z.stage.clientWidth / 2, h = z.stage.clientHeight / 2, k = b.getAttribute("data-z");
      if (k === "fit") fitNow(); else zoomAt(k === "in" ? 1.5 : 1 / 1.5, w, h);
    });
    el.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.preventDefault(); zoomClose(); }
      else if (e.key === "+" || e.key === "=") zoomAt(1.5, z.stage.clientWidth / 2, z.stage.clientHeight / 2);
      else if (e.key === "-") zoomAt(1 / 1.5, z.stage.clientWidth / 2, z.stage.clientHeight / 2);
      else if (e.key === "0") fitNow();
      else if (e.key === "Tab") {   // keep focus inside the viewer
        var f = [].slice.call(el.querySelectorAll("button")), i = f.indexOf(document.activeElement);
        e.preventDefault();
        f[(i + (e.shiftKey ? -1 : 1) + f.length) % f.length].focus();
      }
    });
    window.addEventListener("resize", function () { if (el.classList.contains("open")) fitNow(); });
    return z;
  }
  function zoomOpen(big, small, caption, opener) {
    if (!Z) Z = zoomBuild();
    Z.opener = opener || null;
    Z.w = 0; Z.back = small && small !== big ? small : null;
    Z.img.removeAttribute("style");
    Z.img.alt = caption ? "Graphical abstract: " + caption : "Graphical abstract";
    Z.cap.textContent = caption ? nd(caption) : "";
    Z.el.classList.add("open");
    document.documentElement.style.overflow = "hidden";
    Z.img.src = big;
    if (Z.img.complete && Z.img.naturalWidth) { Z.w = Z.img.naturalWidth; Z.h = Z.img.naturalHeight; Z.fitNow(); }
    Z.el.querySelector(".zoom-close").focus();
  }
  function zoomClose() {
    if (!Z) return;
    Z.el.classList.remove("open");
    Z.img.removeAttribute("src");
    document.documentElement.style.overflow = "";
    if (Z.opener && Z.opener.focus) Z.opener.focus();
  }

  // ---------------------------------------------------------------- actions & keys
  var onChange = null;
  function act(card, what) {
    var id = card.getAttribute("data-id");
    var p = known[id] || paperFromCard(card);
    if (what === "save") { setSaved(p, !isSaved(id)); syncCard(card); }
    else if (what === "read") { setRead([id], !isRead(id)); syncCard(card); }
    else if (what === "abstract") toggleAbstract(card, p, false);
    else if (what === "abstract-retry") toggleAbstract(card, p, true);
    if ((what === "save" || what === "read") && onChange) onChange();
  }
  // A graphic the publisher's server does not deliver is removed, never shown broken.
  document.addEventListener("error", function (e) {
    var t = e.target;
    if (!t || t.tagName !== "IMG" || !t.closest) return;
    var fig = t.closest(".toc");
    if (!fig) return;
    var card = fig.closest(".card");
    fig.parentNode.removeChild(fig);
    if (card) card.classList.remove("has-toc");
  }, true);
  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey) return;
    var t = e.target && e.target.closest ? e.target : null;
    if (!t) return;
    var card = t.closest(".card[data-id]");
    var zoom = t.closest("[data-zoom]");
    if (zoom && card) {
      e.preventDefault();
      var img = zoom.querySelector("img"), p = known[card.getAttribute("data-id")] || paperFromCard(card);
      setCurrent(card, false);
      zoomOpen(zoom.getAttribute("data-zoom"), img ? img.currentSrc || img.src : "", p.title, zoom);
      return;
    }
    var b = t.closest("[data-act]");
    if (card) setCurrent(card, false);
    if (b && card) { e.preventDefault(); act(card, b.getAttribute("data-act")); }
  });

  var current = null;
  function cards() { return [].slice.call(document.querySelectorAll("#main .card[data-id]")); }
  function setCurrent(card, scroll) {
    if (current && current !== card) current.classList.remove("is-current");
    current = card;
    if (!card) return;
    card.classList.add("is-current");
    if (scroll) {
      if (!card.hasAttribute("tabindex")) card.setAttribute("tabindex", "-1");
      try { card.focus({ preventScroll: true }); } catch (e) { card.focus(); }
      card.scrollIntoView({ block: "nearest" });
    }
  }
  document.addEventListener("keydown", function (e) {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
    if (Z && Z.el.classList.contains("open")) return;
    var t = e.target;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    var k = e.key;
    if (["j", "k", "s", "r", "a", "o", "z"].indexOf(k) === -1) return;
    var list = cards();
    if (!list.length) return;
    if (current && !current.isConnected) current = null;
    var i = current ? list.indexOf(current) : -1;
    e.preventDefault();
    if (k === "j" || k === "k") {
      if (k === "j" && i === list.length - 1) {
        var more = $("more-btn");
        if (more) { more.click(); list = cards(); }
      }
      var next = i === -1 ? 0 : (k === "j" ? Math.min(i + 1, list.length - 1) : Math.max(i - 1, 0));
      setCurrent(list[next], true);
      return;
    }
    if (i === -1) return;
    if (k === "o") {
      var a = current.querySelector(".act-full");
      if (a) window.open(a.href, "_blank", "noopener");
      return;
    }
    if (k === "z") {
      var zb = current.querySelector("[data-zoom]");
      if (zb) zb.click();
      return;
    }
    act(current, { s: "save", r: "read", a: "abstract" }[k]);
  });
  window.addEventListener("storage", function (e) {
    if (e.key && e.key.indexOf(NS) === 0) { reloadState(); syncAllCards(); if (onChange) onChange(); }
  });
  function keysHint() {
    return '<p class="keys"><kbd>j</kbd> <kbd>k</kbd> next and previous · <kbd>a</kbd> abstract · ' +
      '<kbd>s</kbd> save · <kbd>r</kbd> mark read · <kbd>z</kbd> enlarge the graphic · <kbd>o</kbd> open the paper</p>';
  }

  // ---------------------------------------------------------------- visitor counter
  /* One count per browser, wherever on the site it first arrives; later pages only read
   * the total, at most every few hours. A browser that keeps no site data is not counted
   * (it would be counted on every page). The number shows only when the counter answers. */
  function visitors() {
    var el = $("visitors");
    if (!el || !window.fetch) return;
    function show(v) { el.textContent = plural(v, "visitor"); el.hidden = false; }
    var counted = !!sget("counted", 0) || !storageOK, cached = sget("visitors", null), now = Date.now();
    if (counted && cached && typeof cached.v === "number" && now - cached.at < 6 * 3600 * 1000) { show(cached.v); return; }
    fetch(COUNTER + (counted ? "get/" : "hit/") + COUNTER_KEY).then(function (r) {
      return r.ok ? r.json() : null;
    }).then(function (j) {
      if (!j || typeof j.value !== "number") return;
      if (!counted) sset("counted", now);
      sset("visitors", { v: j.value, at: now });
      show(j.value);
    }).catch(function () {});
  }

  // ---------------------------------------------------------------- the search worker
  function startWorker(onProgress) {
    var w;
    try { w = new Worker(ROOT + "assets/worker.js"); } catch (e) { return null; }
    var seq = 0, cbs = {};
    w.onmessage = function (e) {
      var m = e.data || {};
      if (m.t === "r") { var cb = cbs[m.id]; delete cbs[m.id]; if (cb) cb(m); }
      else onProgress(m);
    };
    w.onerror = function () { onProgress({ t: "error", message: "the search engine could not start" }); };
    w.postMessage({ t: "init" });
    return {
      ask: function (q, cb) { q.t = "q"; q.id = ++seq; cbs[q.id] = cb; w.postMessage(q); return q.id; }
    };
  }
  function loadState(m) {
    if (m.t === "error") return "";
    if (!m.complete) return "Loading older years…";
    if (!m.affiliations) return "Loading affiliations…";
    return "";
  }
  function fail(msg) {
    app.innerHTML = '<p class="empty">Could not load the database (' + esc(msg) + "). " +
      'The <a href="' + ROOT + 'archive/index.html">archive</a> lists every paper by date.</p>';
  }

  // ---------------------------------------------------------------- front page
  function snapshot(papers) {
    var day = "";
    papers.forEach(function (p) { if (p.added && p.added > day) day = p.added; });
    var ids = papers.filter(function (p) { return p.added === day; }).map(function (p) { return p.id; });
    return { at: Date.now(), day: day, ids: ids.slice(0, 5000) };
  }
  /* The previous visit's snapshot (newest "added" day and the ids added that day), or null
   * on a first visit in this browser. A visit ends after VISIT_GAP without a page load. */
  function trackVisit(papers) {
    var v = sget("visit", null), now = Date.now(), base = null;
    var valid = function (s) { return s && typeof s.day === "string" && Array.isArray(s.ids) && typeof s.at === "number"; };
    if (v && typeof v.at === "number" && valid(v.cur)) base = now - v.at > VISIT_GAP ? v.cur : (valid(v.base) ? v.base : null);
    sset("visit", { at: now, base: base, cur: snapshot(papers) });
    return base;
  }

  var SEARCH_ICON = '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="m10.5 10.5 3 3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';

  function feedPage() {
    var S = { papers: [], base: null, newSet: {}, baseIds: {}, view: "all", journal: "", q: "",
              shown: FEED_PAGE, undo: null, oldest: "", generated: "", total: 0 };
    enhance(app);

    function isNew(p) {
      if (!S.base || !p.added) return false;
      return p.added > S.base.day || (p.added === S.base.day && S.baseIds[p.id] !== 1);
    }

    function build() {
      app.innerHTML =
        '<div class="toolbar" id="toolbar">' +
        '<div class="chips-wrap"><button type="button" class="scroll-btn" data-scroll="-1" aria-label="Scroll the journals left" hidden>‹</button>' +
        '<div class="chips" id="jchips" role="group" aria-label="Journals"></div>' +
        '<button type="button" class="scroll-btn" data-scroll="1" aria-label="Scroll the journals right" hidden>›</button></div>' +
        '<div class="toolbar-r"><div class="filter">' + SEARCH_ICON +
        '<input type="search" id="feed-q" placeholder="Filter by title or author" aria-label="Filter by title or author" autocomplete="off"></div>' +
        '<button type="button" class="btn btn-dark" id="journals-btn" aria-expanded="false" aria-controls="journals-panel">Journals <span class="n" id="follow-n" hidden></span></button></div>' +
        "</div>" +
        '<div class="panel" id="journals-panel" hidden></div>' +
        '<div class="subbar"><div class="tabs" id="tabs" role="group" aria-label="Show"></div>' +
        '<div class="subbar-r"><span id="undo-wrap"></span><button type="button" class="linkbtn" id="mark-all" hidden></button></div></div>' +
        '<p class="status" id="status" aria-live="polite"></p>' +
        '<div id="results"></div><p class="more" id="more-wrap"></p>' + keysHint();
      var timer;
      $("feed-q").addEventListener("input", function (e) {
        clearTimeout(timer);
        timer = setTimeout(function () { S.q = e.target.value; S.shown = FEED_PAGE; render(); }, 120);
      });
      var chips = $("jchips");
      chips.addEventListener("scroll", scrollButtons, { passive: true });
      window.addEventListener("resize", scrollButtons);
      app.addEventListener("click", function (e) {
        var t = e.target.closest ? e.target.closest("button") : null;
        if (!t || !app.contains(t) || t.closest(".card")) return;
        if (t.hasAttribute("data-view")) setView(t.getAttribute("data-view"));
        else if (t.hasAttribute("data-journal")) {
          var j = t.getAttribute("data-journal");
          S.journal = S.journal === j || j === "" ? "" : j; S.shown = FEED_PAGE; render();
        }
        else if (t.hasAttribute("data-scroll")) chips.scrollBy({ left: +t.getAttribute("data-scroll") * chips.clientWidth * 0.8, behavior: "smooth" });
        else if (t.id === "journals-btn") togglePanel();
        else if (t.id === "follow-done") togglePanel(false);
        else if (t.id === "follow-clear") { sset("follow", []); renderPanel(); if (S.view === "following") S.view = "all"; render(); }
        else if (t.id === "show-new") setView("new");
        else if (t.id === "mark-all") markAll();
        else if (t.id === "undo-btn") undoMarkAll();
        else if (t.id === "more-btn") { S.shown += FEED_PAGE; renderList(); }
      });
      app.addEventListener("change", function (e) {
        var t = e.target;
        if (!t || !t.hasAttribute || !t.hasAttribute("data-follow")) return;
        var had = followList().length, list = followList().filter(function (j) { return j !== t.value; });
        if (t.checked) list.push(t.value);
        sset("follow", list);
        if (!had && list.length && S.view === "all") S.view = "following";
        if (!list.length && S.view === "following") S.view = "all";
        sset("view", S.view);
        render();
      });
      var tb = $("toolbar");
      if (window.IntersectionObserver) {
        var sentinel = document.createElement("div");
        tb.parentNode.insertBefore(sentinel, tb);
        new IntersectionObserver(function (en) { tb.classList.toggle("stuck", !en[0].isIntersecting); }).observe(sentinel);
      }
    }
    function scrollButtons() {
      var c = $("jchips"), btns = app.querySelectorAll(".scroll-btn");
      if (!c || btns.length < 2) return;
      var over = c.scrollWidth > c.clientWidth + 4;
      btns[0].hidden = !over || c.scrollLeft < 4;
      btns[1].hidden = !over || c.scrollLeft + c.clientWidth >= c.scrollWidth - 4;
    }
    function setView(v) {
      S.view = S.view === v && v !== "all" ? "all" : v;
      sset("view", S.view);
      S.shown = FEED_PAGE;
      render();
    }
    function inView(p, view) {
      if (view === "unread") return !isRead(p.id);
      if (view === "new") return S.newSet[p.id] === 1;
      if (view === "following") return followList().indexOf(p.journal) !== -1;
      return true;
    }
    function terms() { var q = S.q.toLowerCase().trim(); return q ? q.split(/\s+/) : []; }
    function textMatch(p, tq) {
      if (!tq.length) return true;
      var hay = (p.title + " " + (Array.isArray(p.authors) ? p.authors.join(" ") : (p.authorsText || "")) + " " + p.journal).toLowerCase();
      for (var i = 0; i < tq.length; i++) if (hay.indexOf(tq[i]) === -1) return false;
      return true;
    }
    function listFor(view, withJournal) {
      var tq = terms(), src = view === "saved" ? savedList() : S.papers;
      return src.filter(function (p) {
        return (view === "saved" || inView(p, view)) && textMatch(p, tq) &&
          (!withJournal || !S.journal || p.journal === S.journal);
      });
    }
    function validView() {
      if (S.view === "new" && !S.base) S.view = "all";
      if (S.view === "following" && !followList().length) S.view = "all";
      if (["all", "unread", "new", "saved", "following"].indexOf(S.view) === -1) S.view = "all";
    }

    function renderTabs() {
      var views = [["all", "All"], ["unread", "Unread"]];
      if (S.base) views.push(["new", "New"]);
      views.push(["saved", "Saved"]);
      if (followList().length) views.push(["following", "Following"]);
      $("tabs").innerHTML = views.map(function (v) {
        return '<button type="button" class="tab" data-view="' + v[0] + '" aria-pressed="' + (S.view === v[0]) + '">' +
          v[1] + ' <span class="n">' + fmt(listFor(v[0], true).length) + "</span></button>";
      }).join("");
    }
    function renderChips() {
      var counts = {}, f = followList(), all = listFor(S.view, false);
      all.forEach(function (p) { if (p.journal) counts[p.journal] = (counts[p.journal] || 0) + 1; });
      var names = Object.keys(counts).sort(function (a, b) {
        return (f.indexOf(b) !== -1) - (f.indexOf(a) !== -1) || counts[b] - counts[a] || a.localeCompare(b);
      });
      if (S.journal && !counts[S.journal]) { names.unshift(S.journal); counts[S.journal] = 0; }
      $("jchips").innerHTML = '<button type="button" class="chip" data-journal="" aria-pressed="' + !S.journal + '">All journals <span class="n">' +
        fmt(all.length) + "</span></button>" + names.map(function (j) {
          return '<button type="button" class="chip" data-journal="' + esc(j) + '" aria-pressed="' + (S.journal === j) + '"' +
            ' title="' + tx(j) + (f.indexOf(j) !== -1 ? ', a journal you follow' : "") + '"><span class="cn">' + tx(j) + '</span><span class="n">' + fmt(counts[j]) + "</span></button>";
        }).join("");
      var n = $("follow-n");
      n.hidden = !f.length; n.textContent = f.length;
      scrollButtons();
    }
    function togglePanel(force) {
      var panel = $("journals-panel"), btn = $("journals-btn");
      var open = typeof force === "boolean" ? force : panel.hidden;
      panel.hidden = !open;
      btn.setAttribute("aria-expanded", String(open));
      if (open) { renderPanel(); var i = $("follow-q"); if (i) i.focus(); }
      else btn.focus();
    }
    function renderPanel() {
      var panel = $("journals-panel");
      if (panel.hidden) return;
      var f = followList(), counts = {};
      S.papers.forEach(function (p) { if (p.journal) counts[p.journal] = (counts[p.journal] || 0) + 1; });
      f.forEach(function (j) { if (!counts[j]) counts[j] = 0; });
      var names = Object.keys(counts).sort(function (a, b) { return a.localeCompare(b); });
      var prev = $("follow-q"), q = prev ? prev.value : "";
      panel.innerHTML =
        '<div class="panel-head"><p>Follow journals to see only their papers under <strong>Following</strong>. ' +
        "The number is how many papers each has in this list.</p>" +
        '<p><button type="button" class="btn btn-small" id="follow-done">Done</button> ' +
        (f.length ? '<button type="button" class="linkbtn" id="follow-clear">Unfollow all</button>' : "") + "</p></div>" +
        '<input type="search" id="follow-q" placeholder="Find a journal" aria-label="Find a journal" autocomplete="off" value="' + esc(q) + '">' +
        '<ul class="jlist" id="follow-list">' + names.map(function (j) {
          return '<li><label><input type="checkbox" data-follow value="' + esc(j) + '"' + (f.indexOf(j) !== -1 ? " checked" : "") +
            "> <span>" + tx(j) + '</span><span class="n">' + fmt(counts[j]) + "</span></label></li>";
        }).join("") + "</ul>";
      var input = $("follow-q");
      function filter() {
        var n = input.value.toLowerCase().trim();
        [].forEach.call(panel.querySelectorAll("#follow-list li"), function (li) {
          li.hidden = !!n && li.textContent.toLowerCase().indexOf(n) === -1;
        });
      }
      input.addEventListener("input", filter);
      filter();
    }
    function renderStatus() {
      var html = "", newCount = 0;
      S.papers.forEach(function (p) { if (S.newSet[p.id] === 1) newCount++; });
      if (S.base) {
        var when = visitWhen(S.base.at);
        if (S.base.day && S.oldest && S.base.day < S.oldest)
          html = "Your last visit (" + esc(when) + ") was before this list starts.";
        else if (newCount)
          html = "<strong>" + fmt(newCount) + " new</strong> since your last visit (" + esc(when) + "). " +
            (S.view !== "new" ? '<button type="button" class="linkbtn" id="show-new">Show only those</button>' : "");
        else html = "Nothing new since your last visit (" + esc(when) + "). The database is updated once a day.";
      }
      if (!storageOK)
        html += ' <span class="warn">This browser keeps no data for this site, so read and saved marks last only until you leave the page.</span>';
      $("status").innerHTML = html;
      $("status").hidden = !html;
    }
    function renderList() {
      var list = listFor(S.view, true);
      var unread = 0;
      list.forEach(function (p) { if (!isRead(p.id)) unread++; });
      var shown = Math.min(S.shown, list.length), html = "", day = null;
      for (var i = 0; i < shown; i++) {
        var p = list[i];
        if (S.view !== "saved") {
          var d = p.added || "";
          if (d !== day) {
            day = d;
            var n = 0;
            for (var k = i; k < list.length && (list[k].added || "") === d; k++) n++;
            html += '<h2 class="day-h">' + esc(dayLabel(d)) + ' <span class="n">· ' + fmt(n) + "</span></h2>";
          }
        }
        html += renderCard(p, { isNew: S.newSet[p.id] === 1 });
      }
      if (!list.length) {
        html = '<p class="empty">' + (S.view === "saved" && !savedList().length
          ? "No saved papers yet. Press Save on a paper (or <kbd>s</kbd>) to keep it here."
          : "No papers match.") + "</p>";
      }
      $("results").innerHTML = html;
      current = null;
      var mb = $("mark-all");
      mb.hidden = !unread;
      mb.textContent = "Mark all " + fmt(unread) + " as read";
      $("more-wrap").innerHTML = list.length > shown
        ? '<button type="button" class="btn" id="more-btn">Show more (' + fmt(list.length - shown) + " more)</button>" : "";
    }
    function markAll() {
      var ids = listFor(S.view, true).filter(function (p) { return !isRead(p.id); }).map(function (p) { return p.id; });
      if (!ids.length) return;
      S.undo = ids;
      setRead(ids, true);
      render();
      $("undo-wrap").innerHTML = "Marked " + fmt(ids.length) + " as read. " +
        '<button type="button" class="linkbtn" id="undo-btn">Undo</button>';
    }
    function undoMarkAll() {
      if (S.undo) setRead(S.undo, false);
      S.undo = null;
      render();
    }
    function render() {
      validView();
      renderStatus();
      renderTabs();
      renderChips();
      renderPanel();
      $("undo-wrap").innerHTML = "";
      renderList();
    }
    function lede() {
      var el = $("lede"), ms = parseGenerated(S.generated);
      if (!el) return;
      var parts = [plural(S.papers.length, "new paper") + " added since " + shortDate(S.oldest)];
      if (S.total) parts.push(fmt(S.total) + " in the database");
      var ago = isNaN(ms) ? "" : agoTime(ms);
      parts.push(ago ? "updated " + ago : "updated daily");
      el.textContent = parts.join(" · ");
      if (!isNaN(ms)) el.title = "Last update " + S.generated;
    }
    function start(papers, feed) {
      S.papers = papers;
      S.generated = feed.generated || "";
      S.total = feed.total || 0;
      S.oldest = papers.reduce(function (m, p) { return p.added && (!m || p.added < m) ? p.added : m; }, "");
      S.base = trackVisit(papers);
      if (S.base) {
        S.baseIds = toSet(S.base.ids);
        papers.forEach(function (p) { if (isNew(p)) S.newSet[p.id] = 1; });
      }
      S.view = String(sget("view", "all"));
      build();
      lede();
      onChange = function () { renderStatus(); renderTabs(); renderChips(); updateMarkAll(); };
      render();
    }
    function updateMarkAll() {
      var unread = listFor(S.view, true).filter(function (p) { return !isRead(p.id); }).length, mb = $("mark-all");
      mb.hidden = !unread;
      mb.textContent = "Mark all " + fmt(unread) + " as read";
    }
    fetch(ROOT + "assets/data/feed.json").then(function (r) {
      if (!r.ok) throw new Error("feed.json " + r.status);
      return r.json();
    }).then(function (feed) {
      var papers = feedPapers(feed);
      if (!papers.length) throw new Error("feed.json has no papers");
      papers.sort(function (a, b) {
        return (b.added || "").localeCompare(a.added || "") || (b.published || "").localeCompare(a.published || "") ||
          (b.id < a.id ? -1 : b.id > a.id ? 1 : 0);
      });
      start(papers, feed);
    }).catch(function () {
      // Keep the cards that came with the page (they have their buttons already).
    });
  }

  // ---------------------------------------------------------------- search page
  function option(v, label) { return '<option value="' + esc(v) + '">' + tx(label) + "</option>"; }
  function setSelect(sel, value) {
    if (!value) return;
    for (var i = 0; i < sel.options.length; i++) if (sel.options[i].value === value) { sel.value = value; return; }
  }

  function searchPage(W) {
    var q = params(), shown = PAGE_SIZE, info = null, lastId = 0, timer = null;
    app.innerHTML =
      '<div class="search-bar">' +
      '<input type="search" id="f-q" aria-label="Search" placeholder="Search titles, authors, journals, affiliations or DOIs" autocomplete="off">' +
      '<select id="f-area" aria-label="Chemistry area"><option value="">All chemistry areas</option></select>' +
      '<select id="f-method" aria-label="Method"><option value="">All methods</option></select>' +
      '<select id="f-year" aria-label="Year"><option value="">All years</option></select>' +
      '<select id="f-journal" aria-label="Journal"><option value="">All journals</option></select>' +
      '<select id="f-sort" aria-label="Order"><option value="new">Newest first</option><option value="old">Oldest first</option><option value="best">Best match</option></select>' +
      "</div>" +
      '<div class="result-meta"><span id="result-count">Loading the database…</span><span id="load-state" class="load-state"></span>' +
      '<a href="search.html" id="clear">Clear</a></div>' +
      '<div id="results"></div><p class="more" id="more-wrap"></p>' + keysHint();
    var F = { q: $("f-q"), area: $("f-area"), method: $("f-method"), year: $("f-year"), journal: $("f-journal"), sort: $("f-sort") };
    F.q.value = q.get("q") || q.get("author") || "";
    setSelect(F.sort, q.get("sort"));
    F.q.addEventListener("input", function () { clearTimeout(timer); shown = PAGE_SIZE; timer = setTimeout(run, 120); });
    ["area", "method", "year", "journal", "sort"].forEach(function (k) {
      F[k].addEventListener("change", function () { shown = PAGE_SIZE; run(); });
    });
    app.addEventListener("click", function (e) {
      if (e.target && e.target.id === "more-btn") { shown += PAGE_SIZE; run(); }
    });

    function fillOptions(m) {
      var c = m.counts, names = m.names, nA = m.areas;
      var keep = { area: F.area.value || q.get("area"), method: F.method.value || q.get("method"),
                   year: F.year.value || q.get("year"), journal: F.journal.value || q.get("journal") };
      F.area.innerHTML = '<option value="">All chemistry areas</option>' + names.slice(0, nA).map(function (n, i) {
        return option(n, n + " (" + fmt(c.area[i] || 0) + ")");
      }).join("");
      F.method.innerHTML = '<option value="">All methods</option>' + names.slice(nA).map(function (n, i) {
        return option(n, n + " (" + fmt(c.method[nA + i] || 0) + ")");
      }).join("");
      F.year.innerHTML = '<option value="">All years</option>' + Object.keys(c.year).sort().reverse().map(function (y) {
        return option(y, y + " (" + fmt(c.year[y]) + ")");
      }).join("");
      F.journal.innerHTML = '<option value="">All journals</option>' + c.journals.map(function (j) {
        return option(j[0], nd(j[0]) + " (" + fmt(j[1]) + ")");
      }).join("");
      Object.keys(keep).forEach(function (k) { setSelect(F[k], keep[k]); });
    }
    function currentQuery() {
      return { kind: "search", q: F.q.value, area: F.area.value, method: F.method.value,
               year: F.year.value, journal: F.journal.value, sort: F.sort.value, limit: shown };
    }
    function updateURL(c) {
      var u = new URLSearchParams();
      ["q", "area", "method", "year", "journal"].forEach(function (k) { if (c[k]) u.set(k, c[k]); });
      if (c.sort && c.sort !== "new") u.set("sort", c.sort);
      var s = u.toString();
      try { history.replaceState(null, "", location.pathname + (s ? "?" + s : "")); } catch (e) {}
    }
    function run() {
      if (!info) return;
      var c = currentQuery();
      updateURL(c);
      lastId = W.ask(c, function (r) {
        if (r.id !== lastId) return;
        $("result-count").textContent = plural(r.total, "paper") + (r.complete ? "" : " so far");
        $("results").innerHTML = r.items.map(function (p) { return renderCard(p); }).join("") ||
          '<p class="empty">No papers match. Try fewer words or another filter.</p>';
        current = null;
        $("more-wrap").innerHTML = r.total > r.items.length
          ? '<button type="button" class="btn" id="more-btn">Show more (' + fmt(r.total - r.items.length) + " more)</button>" : "";
      });
    }
    return function (m) {
      if (m.t === "error") { fail(m.message); return; }
      info = m;
      fillOptions(m);
      $("load-state").textContent = loadState(m);
      run();
    };
  }

  // ---------------------------------------------------------------- journal and author pages
  function directoryPage(W, kind) {
    var isAuthor = kind === "authors";
    var q = params();
    var selected = q.get(isAuthor ? "a" : "j");
    if (selected) return detailPage(W, kind, isAuthor ? normalizeAuthor(selected) : selected);
    var word = isAuthor ? "authors" : "journals", info = null, lastId = 0, timer = null;
    app.innerHTML = '<div class="search-bar">' +
      '<input type="search" id="d-q" aria-label="Find ' + (isAuthor ? "an author" : "a journal") + '" placeholder="Find ' +
      (isAuthor ? "an author" : "a journal") + '" autocomplete="off">' +
      '<select id="d-area" aria-label="Chemistry area"><option value="">All chemistry areas</option></select></div>' +
      '<div class="result-meta"><span id="result-count">Loading the database…</span><span id="load-state" class="load-state"></span></div>' +
      '<ul class="dir-list" id="dir-list"></ul>';
    var qi = $("d-q"), area = $("d-area");
    qi.value = q.get("q") || "";
    qi.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(run, 120); });
    area.addEventListener("change", run);
    function run() {
      if (!info) return;
      var limit = qi.value.trim() ? 500 : 300;
      lastId = W.ask({ kind: "names", field: kind, q: qi.value, area: area.value, limit: limit }, function (r) {
        if (r.id !== lastId) return;
        var areaQ = area.value ? "&area=" + encodeURIComponent(area.value) : "";
        $("result-count").textContent = qi.value.trim()
          ? plural(r.total, isAuthor ? "author" : "journal") + " match"
          : fmt(r.all) + " " + word + (area.value ? " in " + nd(area.value) : "") +
            (r.all > r.items.length ? ", the " + fmt(r.items.length) + " with most papers shown: type to find others" : "");
        $("dir-list").innerHTML = r.items.map(function (x) {
          return '<li><a href="?' + (isAuthor ? "a" : "j") + "=" + encodeURIComponent(x[0]) + areaQ + '">' + tx(x[0]) +
            '</a><span class="n">' + fmt(x[1]) + "</span></li>";
        }).join("") + (r.total > r.items.length ? '<li class="more-note">and ' + fmt(r.total - r.items.length) + " more: type more of the name</li>" : "");
      });
    }
    return function (m) {
      if (m.t === "error") { fail(m.message); return; }
      info = m;
      var keep = area.value || q.get("area");
      area.innerHTML = '<option value="">All chemistry areas</option>' + m.names.slice(0, m.areas).map(function (n) { return option(n, n); }).join("");
      setSelect(area, keep);
      $("load-state").textContent = loadState(m);
      run();
    };
  }

  function detailPage(W, kind, name) {
    var isAuthor = kind === "authors", area = params().get("area") || "", shown = PAGE_SIZE, lastId = 0, info = null;
    document.title = nd(name) + " · " + SITE;
    var h1 = document.querySelector(".page-head h1"), lede = document.querySelector(".page-head p");
    if (h1) h1.textContent = nd(name);
    if (lede) lede.textContent = isAuthor ? "Papers in the database with this author." : "Papers in the database from this journal.";
    var head = document.querySelector(".page-head");
    if (head && !head.querySelector(".crumb")) {
      var c = document.createElement("p");
      c.className = "crumb";
      c.innerHTML = '<a href="' + ROOT + kind + '.html">' + (isAuthor ? "Authors" : "Journals") + "</a>";
      head.insertBefore(c, head.firstChild);
    }
    app.innerHTML = '<div class="result-meta"><span id="result-count">Loading the database…</span><span id="load-state" class="load-state"></span></div>' +
      '<div id="results"></div><p class="more" id="more-wrap"></p>' + keysHint();
    app.addEventListener("click", function (e) {
      if (e.target && e.target.id === "more-btn") { shown += PAGE_SIZE; run(); }
    });
    function run() {
      if (!info) return;
      var c = { kind: "search", sort: "new", limit: shown, area: area, journals: isAuthor };
      if (isAuthor) c.author = name; else c.journal = name;
      lastId = W.ask(c, function (r) {
        if (r.id !== lastId) return;
        var all = area ? ' · <a href="?' + (isAuthor ? "a" : "j") + "=" + encodeURIComponent(name) + '">all areas</a>' : "";
        var where = r.journals && r.journals.length ? " · mostly in " + r.journals.slice(0, 3).map(function (j) {
          return '<a href="' + ROOT + "journals.html?j=" + encodeURIComponent(j[0]) + '">' + tx(j[0]) + "</a>";
        }).join(", ") : "";
        $("result-count").innerHTML = esc(plural(r.total, "paper")) + (area ? " in " + tx(area) : "") +
          (r.complete ? "" : " so far") + all + where;
        $("results").innerHTML = r.items.map(function (p) { return renderCard(p); }).join("") ||
          '<p class="empty">No papers ' + (r.complete ? "found." : "found yet.") + "</p>";
        current = null;
        $("more-wrap").innerHTML = r.total > r.items.length
          ? '<button type="button" class="btn" id="more-btn">Show more (' + fmt(r.total - r.items.length) + " more)</button>" : "";
      });
    }
    return function (m) {
      if (m.t === "error") { fail(m.message); return; }
      info = m;
      $("load-state").textContent = loadState(m);
      run();
    };
  }

  // ---------------------------------------------------------------- boot
  var top = document.querySelector(".top");
  function topHeight() { if (top) document.documentElement.style.setProperty("--top-h", top.offsetHeight + "px"); }
  topHeight();
  window.addEventListener("resize", topHeight);
  visitors();

  if (PAGE === "feed") { feedPage(); return; }
  if (PAGE === "static" || !PAGE) { enhance(document); return; }
  var handler = null;
  var W = startWorker(function (m) { if (handler) handler(m); });
  if (!W) { fail("this browser cannot run the search"); return; }
  if (PAGE === "search") handler = searchPage(W);
  else if (PAGE === "authors" || PAGE === "journals") handler = directoryPage(W, PAGE);
})();
