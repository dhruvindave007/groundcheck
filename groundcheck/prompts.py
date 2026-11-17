"""Versioned prompt template and response parser."""
from __future__ import annotations

import json
import re

from groundcheck.metrics import Prediction
from groundcheck.schema import Scenario

PROMPT_VERSION = "cite-ids-v1"

SYSTEM = (
    "You answer questions about an event log. Use only the log. "
    "Cite the IDs of every log event that supports your answer, and only those. "
    "If the log does not contain enough evidence to answer, say so and set insufficient_evidence to true. "
    'Reply with one JSON object and nothing else: {"answer": string, "citations": [event IDs], '
    '"insufficient_evidence": boolean}.'
)


def render_user(s: Scenario, events=None) -> str:
    lines = [f"[{e.id}] {e.ts} {e.source}: {e.text}" for e in (events if events is not None else s.events)]
    return "EVENT LOG\n" + "\n".join(lines) + f"\n\nQUESTION\n{s.question}"


HEDGES = ("insufficient evidence", "not enough evidence", "cannot be determined", "cannot determine",
          "unknown", "does not contain enough")
_ID_LIST = re.compile(r'"citations"\s*:\s*\[(.*?)\]', re.S)


def parse_response(text: str) -> Prediction:
    """Parse a model reply. JSON first; regex fallback for malformed output."""
    obj = None
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            obj = None
    if isinstance(obj, dict):
        ans = str(obj.get("answer", ""))
        cites = obj.get("citations") or []
        cites = [str(c) for c in cites] if isinstance(cites, list) else [str(cites)]
        abstain = bool(obj.get("insufficient_evidence", False))
    else:
        ans = text
        lm = _ID_LIST.search(text)
        cites = re.findall(r'"([^"]+)"', lm.group(1)) if lm else []
        abstain = False
    abstain = abstain or any(h in ans.lower() for h in HEDGES)
    return Prediction(answer=ans, citations=cites, abstain=abstain, raw=text)
