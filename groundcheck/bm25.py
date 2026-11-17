"""Small Okapi BM25 used by the retrieval baseline and the mock model."""
from __future__ import annotations

import math
import re
from collections import Counter

_TOK = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    toks = []
    for t in _TOK.findall(text.lower()):
        toks.append(t)
        parts = re.split(r"[._=-]", t)
        if len(parts) > 1:
            toks.extend(p for p in parts if p)
    return toks


def bm25_scores(query: str, docs: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    toks = [tokenize(d) for d in docs]
    n = len(docs)
    avgdl = sum(len(t) for t in toks) / max(n, 1)
    df = Counter(w for t in toks for w in set(t))
    q = tokenize(query)
    out = []
    for t in toks:
        tf = Counter(t)
        s = 0.0
        for w in q:
            if w not in tf:
                continue
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(t) / avgdl))
        out.append(s)
    return out


def top_k(query: str, docs: list[str], k: int) -> list[int]:
    sc = bm25_scores(query, docs)
    return sorted(range(len(docs)), key=lambda i: (-sc[i], i))[:k]
