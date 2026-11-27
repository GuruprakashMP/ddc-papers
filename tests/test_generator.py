"""Tests for the static site generator (renders into a temp directory)."""

from __future__ import annotations

import datetime
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from ddc.models import Paper  # noqa: E402
from ddc.settings import Settings  # noqa: E402
from ddc.site import generator  # noqa: E402
from ddc.taxonomy import ALL_NAMES  # noqa: E402

ADDED = "2026-07-20"
GRA = "https://onlinelibrary.wiley.com/cms/asset/a1/adfm1-gra-0001-m.png"


def mk(**kw):
    base = dict(id="p", title="t", authors=["Jane Doe"], journal="Analytical Chemistry", publisher="",
                published="2026-07-18", year=2026, doi="", url="", source="crossref",
                categories=["Catalysis", "Classical ML"], tags=[], relevance_score=90, added=ADDED)
    base.update(kw)
    return Paper(**base)


SAMPLE = [
    mk(id="p1", title="ML for catalysis <test> — a study.", doi="10.1002/adfm.1",
       journal="Analytical chemistry", oa_abstract="yes"),
    mk(id="p2", title="GNNs for property prediction", doi="10.1039/y", journal="Analytical Chemistry",
       categories=["Molecular Properties & Design", "Graph Neural Networks"], published="2026-06-02"),
    mk(id="p3", title="An arXiv preprint", url="https://arxiv.org/abs/2601.00001",
       journal="arXiv (Cornell University)", published="2027-01-05"),
]


class TestGenerator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = pathlib.Path(self.tmp.name)
        store = mock.Mock()
        store.load_all.return_value = [Paper.from_dict(p.to_dict()) for p in SAMPLE]
        for target, value in (("PaperStore", store), ("_load_tocs", None)):
            p = (mock.patch.object(generator, target, return_value=value) if target == "PaperStore"
                 else mock.patch.object(generator, target, return_value={"10.1002/adfm.1": GRA}))
            p.start()
            self.addCleanup(p.stop)
        generator.generate_site(Settings(site_title="TestSite", site_tagline="Tag",
                                         site_base_url="https://example.org/ddc/"), out_dir=self.out)

    def read(self, rel):
        return (self.out / rel).read_text(encoding="utf-8")

    def test_pages_and_assets_exist(self):
        for rel in ("index.html", "search.html", "authors.html", "journals.html", "about.html",
                    "categories/index.html", "archive/index.html", "archive/2026/07/index.html",
                    "assets/style.css", "assets/app.js", "assets/worker.js", "assets/icon.svg",
                    "assets/fonts/inter-latin-wght-normal.woff2", "assets/data/manifest.json",
                    "assets/data/feed.json", "assets/data/papers-2026.json", "feed.xml", "sitemap.xml"):
            self.assertTrue((self.out / rel).exists(), rel)

    def test_manifest_and_compact_rows(self):
        man = json.loads(self.read("assets/data/manifest.json"))
        self.assertEqual(man["format"], 2)
        self.assertEqual(man["categories"], ALL_NAMES)
        y = next(e for e in man["years"] if e["year"] == 2026)
        self.assertEqual(len(y["v"]), 12)
        d = json.loads(self.read("assets/data/papers-2026.json"))
        rows = {r[0]: r for r in d["p"]}
        self.assertEqual(d["j"][rows["p1"][3]], "Analytical Chemistry")   # spellings merged
        self.assertEqual(rows["p1"][6], [ALL_NAMES.index("Catalysis"), ALL_NAMES.index("Classical ML")])
        self.assertEqual(rows["p1"][8], GRA)
        self.assertEqual(rows["p1"][9], "o")
        self.assertEqual(rows["p3"][7], "https://arxiv.org/abs/2601.00001")
        self.assertEqual(rows["p3"][10], ADDED)          # dated ahead: sorted by the day added

    def test_front_page_cards(self):
        html = self.read("index.html")
        self.assertIn("ML for catalysis &lt;test&gt; - a study", html)   # escaped, dash shown, no full stop
        self.assertNotIn("—", html)
        self.assertIn('class="toc-btn" href="https://onlinelibrary.wiley.com/cms/asset/a1/adfm1-gra-0001.png"', html)
        for gone in ("score", "chip-cat", "meta-source", "gp-tools", "starfield"):
            self.assertNotIn(gone, html)
        self.assertEqual(html.count("TestSite</span>"), 1)              # the name, once
        self.assertIn('"@type": "Dataset"', html)

    def test_archive_relative_links(self):
        html = self.read("archive/2026/07/index.html")
        self.assertIn('href="../../../assets/style.css"', html)
        self.assertIn('data-page="static"', html)

    def test_journal_names_and_display_title(self):
        names = generator.journal_names([mk(journal="arXiv (Cornell University)"), mk(journal="arXiv"),
                                         mk(journal="Analytical chemistry"), mk(journal="Analytical Chemistry")])
        self.assertEqual(names["arXiv (Cornell University)"], "arXiv")
        self.assertEqual(names["Analytical chemistry"], "Analytical Chemistry")
        self.assertEqual(generator.display_title("A title."), "A title")
        self.assertEqual(generator.display_title("Smith et al."), "Smith et al.")

    def test_feed_window_and_minimum(self):
        today = datetime.date(2026, 11, 27)
        old = [mk(id=f"o{i}", added="2026-01-01", published="2025-12-20") for i in range(300)]
        new = [mk(id=f"n{i}", added="2026-11-26", published="2026-11-20") for i in range(5)]
        late = [mk(id=f"l{i}", added="2026-11-26", published="2019-05-01") for i in range(3)]
        got = generator.feed_papers(old + new + late, today)
        self.assertEqual(len(got), 305)          # fewer than FEED_MIN recent: the whole oldest day too
        self.assertEqual(got[0].added, "2026-11-26")
        self.assertFalse(any(p.id.startswith("l") for p in got))   # old papers found late: not news

    def test_atom_and_sitemap(self):
        atom = self.read("feed.xml")
        self.assertIn('<link rel="self" href="https://example.org/ddc/feed.xml"/>', atom)
        self.assertIn("https://doi.org/10.1002/adfm.1", atom)
        self.assertIn("<loc>https://example.org/ddc/archive/2026/07/index.html</loc>", self.read("sitemap.xml"))


if __name__ == "__main__":
    unittest.main()
