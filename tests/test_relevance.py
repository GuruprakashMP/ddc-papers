"""Tests for the relevance rules, model and categorizer (the shipped JSON weights)."""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from ddc import relevance  # noqa: E402
from ddc.models import RawRecord  # noqa: E402
from ddc.pipeline import judge  # noqa: E402
from ddc.taxonomy import AREA_NAMES, METHOD_NAMES  # noqa: E402

IN = RawRecord(
    title="Graph neural networks predict the activity of single-atom catalysts for CO2 electroreduction",
    source="test", doi="10.1021/acscatal.6b00001", journal="ACS Catalysis", oa_type="article",
    abstract="We train a graph neural network on DFT adsorption energies of 2,000 single-atom "
             "catalysts and use it to screen candidates for CO2 reduction; the best predicted "
             "catalysts were synthesized and showed high Faradaic efficiency.")
OUT = RawRecord(
    title="Deep learning detects pneumonia in chest radiographs of hospital patients",
    source="test", doi="10.1000/rad.1", journal="Radiology", oa_type="article",
    abstract="A convolutional neural network classifies chest X-ray images of 12,000 patients "
             "into pneumonia and normal with an area under the curve of 0.94.")


class TestRelevance(unittest.TestCase):
    def test_gate(self):
        self.assertTrue(relevance.gate("A title", "", "https://example.org/x"))
        self.assertEqual(relevance.gate("A title", "", "https://arxiv.org/abs/2601.1"), "")
        self.assertTrue(relevance.gate("A title", "10.1/x", oa_type="dataset"))
        self.assertTrue(relevance.gate("Correction to: Machine learning of X", "10.1/x"))
        self.assertEqual(relevance.gate("Machine learning of X", "10.1/x", oa_type="conference-paper"), "")

    def test_model_separates_clear_cases(self):
        m = relevance.model()
        self.assertIsNotNone(m)
        f = lambda r: m.probability(relevance.features(r.title, r.abstract, r.journal, r.oa_type))
        self.assertGreater(f(IN), m.threshold)
        self.assertLess(f(OUT), m.threshold)

    def test_judge_and_categories(self):
        ok, p, cats, _ = judge(IN)
        self.assertTrue(ok)
        self.assertEqual(cats[0], "Catalysis")
        self.assertIn("Graph Neural Networks", cats[1:])
        self.assertTrue(all(c in METHOD_NAMES for c in cats[1:]) and cats[0] in AREA_NAMES)
        self.assertFalse(judge(OUT)[0])

    def test_method_names_case_sensitive_acronyms(self):
        self.assertIn("Generative Models", relevance.named_methods("A GAN designs molecules"))
        self.assertNotIn("Generative Models", relevance.named_methods("GaN nanowires for LEDs"))
        self.assertIn("ML Potentials", relevance.named_methods("A machine-learned interatomic potential for water"))


    def test_method_evidence(self):
        self.assertEqual(relevance.method_evidence("Lithiated carbocations: CLi5+", "5 mL of THF"), 0)
        self.assertEqual(relevance.method_evidence("GaN nanowires", "Grown by MOCVD"), 0)
        self.assertEqual(relevance.method_evidence("An automated docking protocol"), 1)
        self.assertEqual(relevance.method_evidence("AI-assisted colorimetric sensor array"), 2)
        self.assertEqual(relevance.method_evidence("A GAN for molecules"), 2)
        rec = RawRecord(source="crossref", title="Chiral flipping in Viedma deracemization",
                        doi="10.1/x", abstract="Grinding experiments and a kinetic model.")
        self.assertFalse(judge(rec)[0])

    def test_enrich_budget_keeps_late_records(self):
        from ddc.enrich import enrich
        recs = [RawRecord(source="crossref", title=f"Paper {i} about catalysts", doi=f"10.1/x{i}")
                for i in range(3)]
        late = enrich(recs, budget=1e-9)
        self.assertEqual(late, {id(r) for r in recs})
        self.assertTrue(all(r.oa_type == "" for r in recs))


if __name__ == "__main__":
    unittest.main()
