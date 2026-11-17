"""Per-scenario scoring and bootstrap aggregation.

Definitions (C = cited IDs, deduplicated; G = gold IDs; L = IDs in the log;
D = labelled distractor IDs):

- precision = |C & G| / |C|, recall = |C & G| / |G|, F1 their harmonic mean.
  Computed on answerable scenarios only. Citing nothing scores 0 on all three.
- fabricated = 1 if any cited ID is not in L (any scenario).
- distractor_rate = |C & D| / |C| (scenarios with at least one citation).
- correct = answer matches gold and the model did not abstain (answerable only).
- grounded = correct and F1 >= 0.5 (answerable only).
- abstained_noev = model abstained (no-evidence scenarios only).
- false_abstain = model abstained (answerable scenarios only).

Undefined values are None and are skipped when averaging.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from groundcheck.schema import Scenario

METRICS = ["precision", "recall", "f1", "fabricated", "distractor_rate", "correct", "grounded",
           "abstained_noev", "false_abstain"]
GROUNDED_F1 = 0.5

_NUM = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass
class Prediction:
    answer: str = ""
    citations: list[str] = field(default_factory=list)
    abstain: bool = False
    raw: str = ""
    answers: bool = True  # False for citation-only baselines (no answer is attempted)


def grade_answer(s: Scenario, answer: str) -> bool:
    a = answer.strip().lower()
    t = s.answer.type
    if t == "yesno":
        m = re.search(r"\b(yes|no)\b", a)
        return bool(m) and m.group(1) == s.answer.value
    if t == "number":
        nums = {float(x) for x in _NUM.findall(a.replace(",", ""))}
        return all(float(r) in nums for r in s.answer.required)
    if t == "entity":
        return all(r.lower() in a for r in s.answer.required)
    return False


def score(s: Scenario, p: Prediction) -> dict:
    cited = list(dict.fromkeys(c.strip() for c in p.citations if c and c.strip()))
    C, G, L, D = set(cited), set(s.gold_evidence), set(s.event_ids), set(s.distractors)
    r = {m: None for m in METRICS}
    r["fabricated"] = float(bool(C - L))
    if C:
        r["distractor_rate"] = len(C & D) / len(C)
    if s.no_evidence:
        r["abstained_noev"] = float(p.abstain)
        return r
    hit = len(C & G)
    prec = hit / len(C) if C else 0.0
    rec = hit / len(G)
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    r.update(precision=prec, recall=rec, f1=f1, false_abstain=float(p.abstain))
    if p.answers:
        ok = (not p.abstain) and grade_answer(s, p.answer)
        r["correct"] = float(ok)
        r["grounded"] = float(ok and f1 >= GROUNDED_F1)
    return r


def bootstrap_ci(values: list[float], n_boot: int = 1000, seed: int = 0, alpha: float = 0.05):
    """Mean and percentile bootstrap CI over scenarios. Returns (mean, lo, hi, n)."""
    v = [x for x in values if x is not None]
    if not v:
        return None, None, None, 0
    mean = sum(v) / len(v)
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(v, k=len(v))) / len(v) for _ in range(n_boot))
    lo = means[int((alpha / 2) * n_boot)]
    hi = means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return mean, lo, hi, len(v)


def aggregate(rows: list[dict], n_boot: int = 1000, seed: int = 0) -> dict:
    return {m: bootstrap_ci([r[m] for r in rows], n_boot, seed) for m in METRICS}
