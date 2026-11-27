"""The index's classification: one chemistry area per paper, and the data-driven methods it uses.

A paper's ``categories`` list holds its area first, then its methods, each a name below.
The descriptions are shown on the categories page; the same definitions guide labelling.
"""

from __future__ import annotations

from typing import List, Tuple

AREAS: Tuple[Tuple[str, str], ...] = (
    ("Catalysis", "Heterogeneous, homogeneous, electro-, photo- and biocatalysis: "
                  "catalyst design, discovery and mechanisms."),
    ("Synthesis & Reactions", "Reaction outcome and yield prediction, selectivity, conditions, "
                              "retrosynthesis, mechanisms and kinetics."),
    ("Drug Discovery", "Medicinal chemistry of small molecules: bioactivity, QSAR, ADMET, "
                       "binding affinity and molecule generation for drugs."),
    ("Molecular Properties & Design", "Property prediction and design of functional molecules, "
                                      "molecular representations and chemical space."),
    ("Materials", "Inorganic, hybrid and solid-state materials: MOFs, COFs, zeolites, "
                  "perovskites, alloys, glasses, 2D materials and crystals."),
    ("Energy & Electrochemistry", "Batteries, electrolytes, fuel cells, supercapacitors and "
                                  "electrochemical processes."),
    ("Polymers & Soft Matter", "Polymers, soft materials, formulations and self-assembly."),
    ("Computational Chemistry", "Machine-learned potentials, electronic structure, quantum "
                                "chemistry and molecular simulation with machine learning."),
    ("Spectroscopy & Analysis", "NMR, mass spectrometry, IR, Raman, UV-vis, X-ray methods, "
                                "chromatography, chemometrics and chemical sensors."),
    ("Environmental Chemistry", "Pollutants, water treatment, CO2 capture, atmospheric "
                                "chemistry and green chemistry."),
    ("Chemical Engineering", "Reactors, separations, process optimization, flow chemistry "
                             "and scale-up."),
    ("AI Methods & Tools", "General methods, benchmarks, datasets, language models and agents, "
                           "text mining and self-driving-lab platforms."),
)

METHODS: Tuple[Tuple[str, str], ...] = (
    ("Classical ML", "Random forests, gradient boosting, support vector machines, kernel "
                     "methods and regularized regression."),
    ("Deep Learning", "Neural networks, including CNNs, RNNs and transformers other than "
                      "language models."),
    ("Graph Neural Networks", "Message-passing and other graph networks on molecules and "
                              "crystals."),
    ("Generative Models", "VAEs, GANs, diffusion and flow models: generative design of "
                          "molecules and materials."),
    ("Language Models", "Large and chemical language models, LLM agents and LLM-based text "
                        "mining."),
    ("ML Potentials", "Machine-learned interatomic potentials and force fields."),
    ("Bayesian Optimization & Active Learning", "Choosing the next experiment or calculation "
                                                "from a model and its uncertainty."),
    ("Automation & High-Throughput", "Self-driving labs, robotic platforms, high-throughput "
                                     "experimentation and closed-loop workflows."),
    ("Chemometrics", "PLS, PCA and other multivariate calibration and classification of "
                     "chemical data."),
    ("Reinforcement Learning", "Agents that learn from reward, for synthesis planning, design "
                               "or control."),
    ("Data Mining", "Mining databases and the literature, curating chemical data, analysing "
                    "screening data."),
)

AREA_NAMES: List[str] = [name for name, _ in AREAS]
METHOD_NAMES: List[str] = [name for name, _ in METHODS]
# The order of every category code in the site's data files (see site/generator.py).
ALL_NAMES: List[str] = AREA_NAMES + METHOD_NAMES


def area_of(categories: List[str]) -> str:
    """The paper's area (the first category that is an area), or ''."""
    for name in categories or []:
        if name in AREA_NAMES:
            return name
    return ""


def methods_of(categories: List[str]) -> List[str]:
    return [name for name in categories or [] if name in METHOD_NAMES]
