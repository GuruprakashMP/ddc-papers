"""Tests for the core filtering rule: ML applied to chemistry."""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from ddc.classify import classify  # noqa: E402
from ddc.models import RawRecord  # noqa: E402


def record(title: str, abstract: str = "", journal: str = "") -> RawRecord:
    return RawRecord(title=title, abstract=abstract, journal=journal, source="test")


class TestClassify(unittest.TestCase):
    def test_accepts_ml_for_chemistry(self):
        r = record(
            "Machine learning prediction of reaction yields in Pd-catalyzed "
            "cross-coupling",
            "We train a random forest on high-throughput experimentation data "
            "to predict the yield of catalytic reactions.")
        verdict = classify(r)
        self.assertTrue(verdict.accepted)
        self.assertGreaterEqual(verdict.score, 70)
        self.assertIn("Catalysis", verdict.categories)
        self.assertTrue(any("Random Forest" == t for t in verdict.tags))

    def test_accepts_gnn_property_prediction(self):
        r = record(
            "Graph neural networks for molecular property prediction",
            "A message passing neural network predicts HOMO-LUMO gaps and "
            "atomization energies of organic molecules.")
        verdict = classify(r)
        self.assertTrue(verdict.accepted)
        self.assertGreaterEqual(verdict.score, 80)
        self.assertIn("Graph Neural Networks", verdict.categories)

    def test_rejects_pure_ml_paper(self):
        r = record(
            "Attention is all you need",
            "We propose the transformer, a network architecture for sequence "
            "transduction based solely on attention mechanisms.")
        self.assertFalse(classify(r).accepted)

    def test_rejects_pure_chemistry_paper(self):
        r = record(
            "Total synthesis of a complex natural product",
            "A 24-step enantioselective total synthesis using classical "
            "organic chemistry methods and careful ligand choice.")
        self.assertFalse(classify(r).accepted)

    def test_rejects_medical_ai(self):
        r = record(
            "Deep learning for cancer diagnosis from medical imaging",
            "A convolutional neural network analyses radiology scans of "
            "patients in a clinical trial to support disease diagnosis.")
        verdict = classify(r)
        # either rejected outright or heavily penalised below threshold
        self.assertTrue(not verdict.accepted or verdict.score < 40)

    def test_rejects_finance_ai(self):
        r = record(
            "Machine learning for stock market prediction",
            "We apply LSTM networks to financial market time series and "
            "portfolio optimization.")
        verdict = classify(r)
        self.assertTrue(not verdict.accepted or verdict.score < 40)

    def test_chemistry_venue_boosts_score(self):
        base = record("Machine learning models for catalyst screening",
                      "Data-driven screening of transition metal catalysts.")
        boosted = record("Machine learning models for catalyst screening",
                         "Data-driven screening of transition metal catalysts.",
                         journal="ACS Catalysis")
        self.assertGreater(classify(boosted).score, classify(base).score)

    def test_empty_title_rejected(self):
        self.assertFalse(classify(record("")).accepted)

    def test_score_bounds(self):
        r = record(
            "Machine learning and deep learning with graph neural networks for "
            "retrosynthesis, catalysis, DFT and property prediction in organic "
            "chemistry",
            "machine learning catalysis retrosynthesis dft nmr polymer "
            "electrochemistry molecular property prediction")
        verdict = classify(r)
        self.assertLessEqual(verdict.score, 100)
        self.assertGreaterEqual(verdict.score, 90)


if __name__ == "__main__":
    unittest.main()
