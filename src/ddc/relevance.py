"""Relevance model: does a record belong in the index (data-driven chemistry)?

A logistic regression over TF-IDF features of the title, abstract, journal and, when known,
the OpenAlex type and topic of a work. It was trained on papers labelled by hand-written
rules (the About page's "What is included"); the weights are in ``relevance_model.json``
next to this module. This file only turns a record into features and a probability, with
the standard library, exactly as the training script did.

Hard rules come first (:func:`gate`): a record without a DOI or an arXiv identifier, and
OpenAlex types that are not research (datasets, software, editorials, errata, peer reviews,
paratext...) are never included, whatever the text says.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

MODEL_FILE = Path(__file__).with_name("relevance_model.json")

# OpenAlex work types that can be research papers; anything else is excluded.
RESEARCH_TYPES = {"article", "review", "preprint", "conference-paper", "book-chapter",
                  "dissertation", "letter", "report", "data-paper", "software-paper", ""}
# Title prefixes of records that are not papers about the topic.
_NOT_PAPER = re.compile(
    r"^\s*(?:retracted(?: article)?|retraction(?: notice)?|withdrawn|erratum|errata|"
    r"corrigendum|correction(?: to)?|expression of concern|editorial(?: board| masthead)?|"
    r"issue (?:information|publication information)|masthead|cover(?: picture| image| feature)?|"
    r"front cover|back cover|inside (?:front|back) cover|table of contents|"
    r"peer review|reviewer report|author response|decision letter|reply to|response to)\b[:\s.-]",
    re.I)

_WORD = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
STOP = frozenset("""a an and are as at be by for from has have in into is it its of on or that
the their these this to was were which with we our using use used based via between than can
also both such not but been may more most other these those through within without over under
about after before during per each all any some new novel study""".split())


def _tokens(text: str):
    words = [w for w in _WORD.findall((text or "").lower()) if w not in STOP and not w.isdigit()]
    return words + [a + " " + b for a, b in zip(words, words[1:])]


def features(title: str, abstract: str = "", journal: str = "", oa_type: str = "",
             oa_field: str = "", oa_topic: str = "") -> Dict[str, int]:
    """Term counts in separate namespaces: title words ("t:"), title and abstract words
    (no prefix), journal words ("j:"), and the OpenAlex type ("type:"), field and subfield
    ("f:") and topic ("topic:")."""
    counts: Counter = Counter()
    for t in _tokens(title):
        counts["t:" + t] += 1
    for t in _tokens(f"{title} {abstract}"):
        counts[t] += 1
    for t in _tokens(journal):
        counts["j:" + t] += 1
    if oa_type:
        counts["type:" + oa_type.lower()] += 1
    for part in (oa_field or "").split(" / "):
        if part.strip():
            counts["f:" + part.strip().lower()] += 1
    if oa_topic:
        counts["topic:" + oa_topic.strip().lower()] += 1
    if not (abstract or "").strip():
        counts["no-abstract"] += 1
    return dict(counts)


class Model:
    def __init__(self, data: dict) -> None:
        self.terms: Dict[str, int] = {t: i for i, t in enumerate(data["terms"])}
        self.idf = data["idf"]
        self.w = data["w"]
        self.b = float(data["b"])
        self.threshold = float(data["threshold"])
        self.version = data.get("version", "")

    def probability(self, counts: Dict[str, int]) -> float:
        vec = {}
        for term, c in counts.items():
            i = self.terms.get(term)
            if i is not None and c > 0:
                vec[i] = (1.0 + math.log(c)) * self.idf[i]
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        z = self.b + sum(self.w[i] * v / norm for i, v in vec.items())
        return 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, z))))


@lru_cache(maxsize=1)
def model() -> Optional[Model]:
    try:
        return Model(json.loads(MODEL_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError):
        return None


def gate(title: str, doi: str, url: str = "", oa_type: str = "") -> str:
    """The reason a record is excluded whatever its text says, or ''."""
    if not doi and not re.search(r"arxiv\.org/abs/", url or ""):
        return "no DOI or arXiv identifier"
    if (oa_type or "").lower() not in RESEARCH_TYPES:
        return f"not a research paper ({oa_type})"
    if _NOT_PAPER.match(title or ""):
        return "not a research paper (title)"
    return ""


# A paper belongs only when a data-driven method is central to it, so its title or abstract
# must name one. Words that name a learned or statistical model are strong evidence; words
# that also occur in work without one ("automated", "dataset", "high-throughput", "PCA") are
# weak, and a paper that has only those needs a higher probability (WEAK_THRESHOLD).
# Acronyms are matched case-sensitively ("ML" is not "mL", "GAN" is not "GaN").
_STRONG = [
    r"machine[- ]?learn", r"deep[- ]?learn", r"\blearn(?:ed|ing|t|s)?\b", r"neural",
    r"artificial[- ]intelligence", r"data[- ]driven", r"data science", r"informatic",
    r"\bQS[APR]R", r"quantitative structure", r"chemometric", r"random forest",
    r"gradient[- ]boost", r"xgboost", r"adaboost", r"catboost", r"lightgbm", r"support vector",
    r"gaussian process", r"bayesian", r"generative", r"language model", r"transformer",
    r"graph (?:convolution|attention|network)", r"message[- ]passing", r"auto-?encoder",
    r"diffusion model", r"flow matching", r"autoregressive", r"equivariant", r"foundation model",
    r"attention mechanism", r"self-attention", r"slot-attention", r"pre-?train", r"fine-?tun",
    r"self-supervised", r"contrastive", r"test-time", r"self-driving", r"data[- ]?mining",
    r"text[- ]mining", r"literature mining", r"big data", r"surrogate model", r"classifier",
    r"partial least", r"kernel (?:ridge|method)", r"explainab", r"decision tree",
    r"atomic cluster expansion", r"statistical learning", r"conformal prediction",
    r"(?:llm|ai)[- ]agent", r"multi-agent", r"agentic", r"chatgpt", r"\bselfies\b",
    r"natural language processing", r"molecul(?:e|ar) generation", r"explainer",
    r"state space model", r"applicability domain", r"deep potential", r"\bdeepmd",
    r"\bnequip", r"\bschnet", r"\bchgnet", r"\bm3gnet"]
_WEAK = [
    r"kriging", r"high[- ]throughput", r"autonomous", r"robot", r"automated",
    r"clustering (?:analysis|algorithm)", r"k-means", r"hierarchical clustering",
    r"principal component", r"multivariate", r"interpretab", r"genetic algorithm",
    r"nearest neighbo", r"statistical model", r"regression model",
    r"predictive model", r"data analytics", r"\bdatasets?\b", r"data set", r"fingerprint",
    r"de novo (?:molecul\w+ )?(?:design|generation)", r"permutation[- ]invariant polynomial"]
_STRONG_RE = re.compile("|".join(_STRONG), re.I)
_STRONG_ACRONYMS = re.compile(
    r"\b(?:AI|ML|LLMs?|GPT|GNNs?|CNNs?|RNNs?|ANNs?|DNNs?|MLPs?|MLIPs?|MLFFs?|NNPs?|SVMs?|SVR|"
    r"PLSR|PLS-DA|OPLS-DA|SHAP|kNN|k-NN|LSTM|VAEs?|GANs?|BERT|NLP|MACE|ANI-\w+)\b")
_WEAK_RE = re.compile("|".join(_WEAK), re.I)
_WEAK_ACRONYMS = re.compile(r"\b(?:PLS|PCA|SMILES)\b")
WEAK_THRESHOLD = 0.8


def method_evidence(title: str, abstract: str = "") -> int:
    """2 when the title or abstract names a data-driven method, 1 when it has only weak
    signs of one, 0 when it has none."""
    text = f"{title} {abstract}"
    if _STRONG_RE.search(text) or _STRONG_ACRONYMS.search(text):
        return 2
    if _WEAK_RE.search(text) or _WEAK_ACRONYMS.search(text):
        return 1
    return 0


def probability(title: str, abstract: str = "", journal: str = "", oa_type: str = "",
                oa_field: str = "", oa_topic: str = "") -> Optional[float]:
    m = model()
    if m is None:
        return None
    return m.probability(features(title, abstract, journal, oa_type, oa_field, oa_topic))


# ---------------------------------------------------------------------------
# categories: the chemistry area (one) and the data-driven methods (one or more)
# ---------------------------------------------------------------------------

CATEGORY_FILE = Path(__file__).with_name("category_model.json")

# Methods are named in the text far more reliably than a model learns them from a few
# hundred examples, so explicit names decide first; the learned model adds the rest.
# (Acronyms are matched case-sensitively: "GAN" is not gallium nitride, "GaN".)
_I = re.I
METHOD_RULES = {
    "Graph Neural Networks": [(r"graph (?:neural|convolution|attention|transformer|network)|message[- ]passing|"
                               r"equivariant (?:graph|neural|message)", _I),
                              (r"\b(?:GNN|GCN|MPNN)s?\b|SchNet|DimeNet|MEGNet|CGCNN|ALIGNN|PaiNN", 0)],
    "Generative Models": [(r"generative|variational auto-?encoder|adversarial network|diffusion model|"
                           r"denoising diffusion|normalizing flow|flow matching|de novo (?:molecular |molecule |drug )?design|"
                           r"inverse design|molecul(?:e|ar) generation", _I),
                          (r"\b(?:VAE|GAN)s?\b", 0)],
    "Language Models": [(r"language model|chatgpt|chemical language|natural language processing|"
                         r"(?:llm|ai|autonomous|multi-agent) agents?\b|agentic", _I),
                        (r"\b(?:LLM|GPT|BERT|NLP)s?\b|\bGPT-\d|ChemBERTa|ChemCrow", 0)],
    "ML Potentials": [(r"(?:machine[- ]learn\w*|neural[- ]network|deep[- ]learn\w*|learned|machine-learned)"
                       r"[- ](?:based )?(?:interatomic )?(?:potential|force[- ]?field)|interatomic potential|"
                       r"deep potential|universal (?:machine[- ]learning |interatomic )?potential", _I),
                      (r"\b(?:MLIP|MLFF|NNP|MLP)s?\b(?=.{0,80}(?:potential|force|molecular dynamics|MD\b))|"
                       r"DeePMD|\bMACE\b|NequIP|Allegro|CHGNet|M3GNet|\bANI-\w+|\bGAP\b", 0)],
    "Bayesian Optimization & Active Learning": [(r"bayesian optimi[sz]|active[- ]learning|acquisition function|"
                                                 r"closed-loop optimi[sz]", _I)],
    "Automation & High-Throughput": [(r"self-driving|autonomous (?:lab|laborator|experiment|platform|synthesis|robot|chemist)|"
                                      r"robotic|high-throughput (?:experiment|synthesis)|closed-loop (?:experiment|platform|synthesis|discovery)|"
                                      r"(?:lab|laboratory) automation|automated (?:synthesis|laborator|experiment|platform)", _I),
                                     (r"\bHTE\b", 0)],
    "Reinforcement Learning": [(r"reinforcement learning|q-learning|policy gradient|monte carlo tree search", _I),
                               (r"\b(?:RL|MCTS)\b", 0)],
    "Chemometrics": [(r"chemometric|partial least[- ]squares|principal component (?:analysis|regression)|"
                      r"multivariate (?:calibration|analysis|curve resolution|data analysis)|comfa|comsia|3d-qsar", _I),
                     (r"\b(?:PLS|PLSR|PLS-DA|OPLS-DA|PCA|SIMCA|MCR-ALS|PCR)\b", 0)],
    "Data Mining": [(r"data[- ]mining|text[- ]mining|literature[- ]mining|mined from|mining (?:of )?(?:the )?"
                     r"(?:literature|databases?|patents?|publications)|knowledge graph|data curation|"
                     r"natural language processing of (?:the )?literature", _I)],
    "Deep Learning": [(r"deep[- ]learning|neural network|convolutional|recurrent neural|transformer|autoencoder|"
                       r"multilayer perceptron|attention mechanism|long short-term memory", _I),
                      (r"\b(?:CNN|RNN|LSTM|ANN|DNN|MLP)s?\b", 0)],
    "Classical ML": [(r"random forest|gradient[- ]boost|xgboost|lightgbm|catboost|support vector|kernel ridge|"
                      r"nearest neighbo|decision tree|gaussian process|lasso\b|ridge regression|elastic net|"
                      r"extra trees|multiple linear regression|logistic regression|naive bayes|"
                      r"quantitative structure", _I),
                     (r"\b(?:SVM|SVR|KRR|kNN|k-NN|QSAR|QSPR|GPR|RF)\b", 0)],
}
_METHOD_RES = {m: [re.compile(p, f) for p, f in rules] for m, rules in METHOD_RULES.items()}


def named_methods(title: str, abstract: str = "") -> list:
    text = f"{title} {abstract}"
    return [m for m, res in _METHOD_RES.items() if any(r.search(text) for r in res)]


class Categorizer:
    def __init__(self, data: dict) -> None:
        self.terms = {t: i for i, t in enumerate(data["terms"])}
        self.idf = data["idf"]
        self.areas, self.area_w, self.area_b = data["areas"], data["area_w"], data["area_b"]
        self.methods, self.method_w, self.method_b = data["methods"], data["method_w"], data["method_b"]
        self.method_threshold = float(data.get("method_threshold", 0.5))

    def _vec(self, counts: Dict[str, int]) -> Dict[int, float]:
        vec = {}
        for term, c in counts.items():
            i = self.terms.get(term)
            if i is not None and c > 0:
                vec[i] = (1.0 + math.log(c)) * self.idf[i]
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {i: v / norm for i, v in vec.items()}

    def categories(self, counts: Dict[str, int], title: str, abstract: str = "") -> list:
        """[area, method, ...]: the most likely area, then the methods (named in the text, or
        likely by the model; at least one)."""
        v = self._vec(counts)
        scores = [b + sum(w[i] * x for i, x in v.items()) for w, b in zip(self.area_w, self.area_b)]
        area = self.areas[max(range(len(scores)), key=scores.__getitem__)]
        probs = []
        for w, b in zip(self.method_w, self.method_b):
            z = b + sum(w[i] * x for i, x in v.items())
            probs.append(1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, z)))))
        named = set(named_methods(title, abstract))
        chosen = [m for m, p in zip(self.methods, probs) if m in named or p >= self.method_threshold]
        if not chosen:
            chosen = [self.methods[max(range(len(probs)), key=probs.__getitem__)]]
        return [area] + chosen


@lru_cache(maxsize=1)
def categorizer() -> Optional[Categorizer]:
    try:
        return Categorizer(json.loads(CATEGORY_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError):
        return None
