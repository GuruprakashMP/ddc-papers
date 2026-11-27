"""HTML building blocks shared by all generated pages.

Plain string templates (no template engine) keep the project dependency-free. All dynamic
text goes through :func:`esc` (or :func:`txt`). Links inside the index are relative, so the
pages work at any base path (e.g. ``https://user.github.io/repo/``).

The site is self-contained: its stylesheet, script and fonts are served from ``assets/``.
The only other hosts a page talks to are the publishers' servers (for table-of-contents
graphics), OpenAlex and Crossref (an abstract, when asked for) and the visitor counter.
"""

from __future__ import annotations

import datetime as dt
import re
from html import escape
from typing import Optional
from urllib.parse import quote

from ..models import Paper

NAV_ITEMS = (
    ("index.html", "Latest"),
    ("search.html", "Search"),
    ("journals.html", "Journals"),
    ("authors.html", "Authors"),
    ("categories/index.html", "Categories"),
    ("archive/index.html", "Archive"),
    ("about.html", "About"),
)

AUTHORS_SHOWN = 12
AUTHOR_LINK = "Guruprakash M P"
AUTHOR_HOME = "https://guruprakashmp.github.io/"

# The site's mark: a benzene ring with three data points, white on navy.
LOGO_SVG = (
    '<svg viewBox="0 0 32 32" width="34" height="34" aria-hidden="true" focusable="false">'
    '<rect width="32" height="32" rx="8" fill="#1e3a6e"/>'
    '<path d="M16 6.6l8.1 4.7v9.4L16 25.4l-8.1-4.7v-9.4z" fill="none" stroke="#fff" '
    'stroke-width="1.7" stroke-linejoin="round"/>'
    '<circle cx="16" cy="6.6" r="2.2" fill="#8cc8ff"/>'
    '<circle cx="24.1" cy="20.7" r="2.2" fill="#8cc8ff"/>'
    '<circle cx="7.9" cy="20.7" r="2.2" fill="#8cc8ff"/></svg>')

FONT_PRELOADS = ("fonts/inter-latin-wght-normal.woff2",
                 "fonts/source-serif-4-latin-wght-normal.woff2")


def esc(value: object) -> str:
    return escape(str(value or ""), quote=True)


_EM_DASH = re.compile(r"\s*—\s*")


def no_dash(value: object) -> str:
    """Display form of text from the data: an em dash becomes a spaced hyphen.

    Only what the page shows changes; the stored record (and every link, search and
    match built from it) keeps the publisher's text exactly.
    """
    return _EM_DASH.sub(" - ", str(value or "")).strip()


def txt(value: object) -> str:
    """Escaped display text from the data (see :func:`no_dash`)."""
    return esc(no_dash(value))


def _q(value: str) -> str:
    """Query-string encoding for a link built in Python (as encodeURIComponent)."""
    return quote(str(value or ""), safe="")


def page(
    *,
    title: str,
    site_title: str,
    tagline: str,
    content: str,
    depth: int = 0,
    active: str = "",
    head_extra: str = "",
    index_key: str = "",
    contact_email: str = "",
    base_url: str = "",
    path: str = "",
    body_page: str = "",
    description: str = "",
) -> str:
    """Full HTML document. ``depth`` is the directory depth below the site root and
    ``path`` the page's own path from it (for the canonical link). ``body_page`` names the
    app.js behaviour of a page without an #app element ("static": the archive's cards)."""
    prefix = "../" * depth
    nav = "\n      ".join(
        f'<a href="{prefix}{href}"{" aria-current=\"page\"" if href == active else ""}>'
        f"{esc(label)}</a>" for href, label in NAV_ITEMS)
    year = dt.date.today().year
    desc = description or tagline
    canonical = (f'<link rel="canonical" href="{esc(base_url + path)}">\n'
                 f'<meta property="og:url" content="{esc(base_url + path)}">\n'
                 if base_url and path is not None else "")
    preload = "".join(
        f'<link rel="preload" href="{prefix}assets/{f}" as="font" type="font/woff2" crossorigin>\n'
        for f in FONT_PRELOADS)
    attrs = (f' data-index-key="{esc(index_key)}" data-site-title="{esc(site_title)}"'
             f' data-root="{prefix}"')
    if body_page:
        attrs += f' data-page="{esc(body_page)}"'
    contact = (f'<a href="mailto:{esc(contact_email)}">Report a correction</a>'
               if contact_email else "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta name="theme-color" content="#1e3a6e">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{esc(site_title)}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
{canonical}<link rel="icon" href="{prefix}assets/icon.svg" type="image/svg+xml">
<link rel="alternate" type="application/atom+xml" title="{esc(site_title)}: latest papers" href="{prefix}feed.xml">
{preload}<link rel="stylesheet" href="{prefix}assets/style.css">
<script defer src="{prefix}assets/app.js"></script>
{head_extra}
</head>
<body{attrs}>
<a class="skip" href="#main">Skip to the content</a>
<header class="top">
  <div class="top-in">
    <a class="brand" href="{prefix}index.html">{LOGO_SVG}<span><span class="brand-name">{esc(site_title)}</span><span class="brand-sub">{esc(tagline)}</span></span></a>
    <nav class="nav" aria-label="Site">
      {nav}
    </nav>
  </div>
</header>
<main class="wrap" id="main">
{content}
</main>
<footer class="foot">
  <div class="foot-in">
    <span>&copy; {year} <a href="{AUTHOR_HOME}">{AUTHOR_LINK}</a></span>
    <a href="{prefix}about.html">About</a>
    <a href="{prefix}feed.xml">RSS feed</a>
    {contact}
    <span class="grow"></span>
    <span class="visitors" id="visitors" hidden></span>
  </div>
</footer>
</body>
</html>
"""


def page_head(heading: str, lede: str = "", crumb: str = "") -> str:
    """The heading block at the top of a page (not the front page's)."""
    return (f'<div class="page-head">{f"<p class={chr(34)}crumb{chr(34)}>{crumb}</p>" if crumb else ""}'
            f"<h1>{heading}</h1>{f'<p>{lede}</p>' if lede else ''}</div>")


def paper_link(paper: Paper) -> str:
    """The "Full text" target: the DOI when there is one, else the source's URL."""
    if paper.doi:
        return f"https://doi.org/{paper.doi}"
    return paper.url or ""


def toc_large(url: str) -> str:
    """The larger version of a TOC graphic, for the zoom view (app.js tocLarge)."""
    if re.search(r"onlinelibrary\.wiley\.com/", url):
        return re.sub(r"-m\.(png|jpe?g|gif)$", r".\1", url, flags=re.I)
    if url.startswith("https://ars.els-cdn.com/") and url.endswith("-ga1.jpg"):
        return url[: -len(".jpg")] + "_lrg.jpg"
    return url


def toc_publisher(url: str) -> str:
    if "wiley.com/" in url:
        return "Wiley"
    if "els-cdn.com/" in url:
        return "Elsevier"
    return "the publisher"


def toc_figure(img: str, title: str = "") -> str:
    """The publisher's table-of-contents graphic. Without JavaScript the link opens the
    large image itself; app.js opens it in the zoom view instead."""
    if not img or not img.startswith("https://"):
        return ""
    big = toc_large(img)
    return (f'<figure class="toc"><a class="toc-btn" href="{esc(big)}" data-zoom="{esc(big)}" '
            f'target="_blank" rel="noopener" aria-label="Enlarge the graphical abstract">'
            f'<img src="{esc(img)}" alt="Graphical abstract ({esc(toc_publisher(img))})" '
            f'loading="lazy" decoding="async" referrerpolicy="no-referrer"></a></figure>')


def authors_text(authors, more: int = 0) -> str:
    shown = list(authors[:AUTHORS_SHOWN])
    extra = more + max(0, len(authors) - AUTHORS_SHOWN)
    s = txt(", ".join(shown))
    if extra:
        s += f" and {extra} more"
    return s


def paper_card(paper: Paper, root: str = "", toc: str = "") -> str:
    """Server-side card markup, kept in sync with renderCard() in app.js, which adds the
    Show abstract / Save / Mark read buttons. ``root`` is the relative path to the site
    root ("../../../" on a month page) and ``toc`` the paper's TOC graphic, if any."""
    link = paper_link(paper)
    title = (f'<a href="{esc(link)}" target="_blank" rel="noopener">{txt(paper.title)}</a>'
             if link else txt(paper.title))
    journal = (f'<a class="jbadge" href="{root}journals.html?j={esc(_q(paper.journal))}">'
               f"{txt(paper.journal)}</a>" if paper.journal else "")
    full = (f'<a class="act act-full" href="{esc(link)}" target="_blank" rel="noopener">'
            f"Full text</a>" if link else "")
    doi = f'<span class="doi">{esc(paper.doi)}</span>' if paper.doi else ""
    figure = toc_figure(toc, paper.title)
    return (f'<article class="card{" has-toc" if figure else ""}" data-id="{esc(paper.id)}" '
            f'data-doi="{esc(paper.doi)}">{figure}<div class="body">'
            f'<p class="meta">{journal}<time datetime="{esc(paper.published)}">'
            f"{esc(short_date(paper.published))}</time></p>"
            f'<h3 class="title">{title}</h3>'
            f'<p class="authors">{authors_text(paper.authors)}</p>'
            f'<div class="actions">{full}{doi}</div></div></article>')


_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


def pretty_date(iso: Optional[str]) -> str:
    """2026-10-22 -> 22 October 2026 (2026-10 -> October 2026)."""
    if not iso:
        return ""
    parts = iso.split("-")
    try:
        if len(parts) >= 3:
            return f"{int(parts[2])} {_MONTHS[int(parts[1]) - 1]} {parts[0]}"
        if len(parts) == 2:
            return f"{_MONTHS[int(parts[1]) - 1]} {parts[0]}"
    except (ValueError, IndexError):
        pass
    return iso


def short_date(iso: Optional[str]) -> str:
    """2026-10-22 -> 22 Oct 2026."""
    full = pretty_date(iso).split(" ")
    if len(full) == 3:
        return f"{full[0]} {full[1][:3]} {full[2]}"
    if len(full) == 2:
        return f"{full[0][:3]} {full[1]}"
    return pretty_date(iso)


def month_name(month: int) -> str:
    return _MONTHS[month - 1]
