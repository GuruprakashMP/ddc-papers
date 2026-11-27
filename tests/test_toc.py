"""Tests for the TOC-graphics module (no network: feeds and lookups are mocked)."""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from ddc import toc  # noqa: E402
from ddc.models import Paper  # noqa: E402

GRA = "https://onlinelibrary.wiley.com/cms/asset/a3e6/anie75683-gra-0001-m.png"
COVER = "https://onlinelibrary.wiley.com/cms/asset/b1/anie202600001-blkfxd-0001-m.jpg"
WILEY = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/"><channel>
<item><title>A paper</title><prism:doi>10.1002/anie.8646657</prism:doi>
<content:encoded><![CDATA[<img src="{GRA}" alt="x"/> text]]></content:encoded></item>
<item><title>A cover</title><prism:doi>10.1002/anie.202600001</prism:doi>
<content:encoded><![CDATA[<img src="{COVER}"/>]]></content:encoded></item>
</channel></rss>""".encode()


def paper(doi, journal="Angewandte Chemie", added="2026-11-20"):
    return Paper(id=doi, title="t", authors=[], journal=journal, publisher="", published=added,
                 year=2026, doi=doi, url="", source="crossref", categories=[], tags=[],
                 relevance_score=90, added=added)


class TestRules(unittest.TestCase):
    def test_wiley_graphical_abstract_kept_cover_pictures_refused(self):
        self.assertEqual(toc.parse_feed("Wiley", WILEY), {"10.1002/anie.8646657": GRA})
        self.assertIsNone(toc.image_ok("Wiley", COVER))

    def test_only_the_publishers_own_https_hosts(self):
        self.assertIsNone(toc.image_ok("Wiley", "https://evil.example.com/x-gra-0001-m.png"))
        self.assertEqual(toc.image_ok("Wiley", GRA.replace("https:", "http:")), GRA)
        ga = "https://ars.els-cdn.com/content/image/1-s2.0-S0378517326010719-ga1.jpg"
        self.assertEqual(toc.image_ok("Elsevier", ga), ga)
        self.assertIsNone(toc.image_ok("Elsevier", ga.replace("-ga1", "-gr1")))

    def test_publisher_from_doi_prefix(self):
        self.assertEqual(toc.publisher_of("10.1002/x"), "Wiley")
        self.assertEqual(toc.publisher_of("10.1016/j.x"), "Elsevier")
        self.assertIsNone(toc.publisher_of("10.1021/x"))

    def test_elsevier_candidates_skip_recent_checks_and_known(self):
        today = dt.date(2026, 11, 27)
        papers = [paper("10.1016/a"), paper("10.1016/b"), paper("10.1016/c"), paper("10.1021/d")]
        checked = {"10.1016/b": ["2026-11-20", 1], "10.1016/c": ["2026-10-01", 2]}
        got = toc.elsevier_candidates(papers, {}, checked, today)
        self.assertIn("10.1016/a", got)
        self.assertNotIn("10.1016/b", got)      # checked a week ago
        self.assertNotIn("10.1016/c", got)      # missed twice already
        self.assertNotIn("10.1021/d", got)


class TestUpdate(unittest.TestCase):
    def test_update_keeps_graphics_of_indexed_papers_only(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            (d / "toc.json").write_text(json.dumps({
                "10.1002/old": {"img": COVER, "pub": "Wiley"},            # a cover: dropped
                "10.1002/gone": {"img": GRA, "pub": "Wiley"}}))           # not indexed: dropped
            papers = [paper("10.1002/anie.8646657"), paper("10.1002/old"), paper("10.1016/e")]
            ga = "https://ars.els-cdn.com/content/image/1-s2.0-S0000000000000001-ga1.jpg"
            with mock.patch.multiple(toc, TOC_FILE=d / "toc.json", SOURCES_FILE=d / "s.json",
                                     CHECKED_FILE=d / "c.json", PAUSE_SECONDS=0), \
                 mock.patch.object(toc, "choose_feeds", return_value=["https://onlinelibrary.wiley.com/feed/1/most-recent"]), \
                 mock.patch.object(toc, "_fetch_feed", return_value=WILEY), \
                 mock.patch.object(toc, "elsevier_pii", return_value="S0000000000000001"), \
                 mock.patch.object(toc, "image_exists", return_value=True):
                toc.update(papers, today=dt.date(2026, 11, 27))
            saved = json.loads((d / "toc.json").read_text())
        self.assertEqual(saved["10.1002/anie.8646657"]["img"], GRA)
        self.assertEqual(saved["10.1016/e"]["img"], ga)
        self.assertNotIn("10.1002/old", saved)
        self.assertNotIn("10.1002/gone", saved)

    def test_feed_failures_do_not_stop_the_update(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            with mock.patch.multiple(toc, TOC_FILE=d / "toc.json", SOURCES_FILE=d / "s.json",
                                     CHECKED_FILE=d / "c.json", PAUSE_SECONDS=0), \
                 mock.patch.object(toc, "choose_feeds", return_value=["u1", "u2"]), \
                 mock.patch.object(toc, "_fetch_feed", side_effect=toc.http.FetchError("down")), \
                 mock.patch.object(toc, "elsevier_candidates", return_value=[]):
                stats = toc.update([paper("10.1002/x")], today=dt.date(2026, 11, 27))
        self.assertEqual(stats["Wiley feeds failed"], 2)


if __name__ == "__main__":
    unittest.main()
