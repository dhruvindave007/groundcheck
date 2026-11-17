"""Scenario schema and validator.

A scenario is an event log, a question about it, a gold answer, and the set of
event IDs that support that answer. Distractor IDs label events that look
relevant (they share entities, times or wording with the gold events) but do not
support the answer. A scenario with ``no_evidence=True`` cannot be answered from
its log; the correct behaviour is to abstain.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

ANSWER_TYPES = ("yesno", "number", "entity", "abstain")


@dataclass
class Event:
    id: str
    ts: str
    source: str
    text: str


@dataclass
class Answer:
    type: str  # one of ANSWER_TYPES
    value: str  # canonical answer, human readable
    required: list[str] = field(default_factory=list)  # tokens/numbers a correct answer must contain


@dataclass
class Scenario:
    id: str
    domain: str
    question: str
    events: list[Event]
    answer: Answer
    gold_evidence: list[str]
    distractors: list[str] = field(default_factory=list)
    no_evidence: bool = False
    meta: dict = field(default_factory=dict)

    @property
    def event_ids(self) -> list[str]:
        return [e.id for e in self.events]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Scenario":
        return cls(
            id=d["id"],
            domain=d["domain"],
            question=d["question"],
            events=[Event(**e) for e in d["events"]],
            answer=Answer(**d["answer"]),
            gold_evidence=list(d["gold_evidence"]),
            distractors=list(d.get("distractors", [])),
            no_evidence=bool(d.get("no_evidence", False)),
            meta=dict(d.get("meta", {})),
        )


class ScenarioError(ValueError):
    pass


def validate(s: Scenario) -> None:
    """Raise ScenarioError if the scenario is internally inconsistent."""
    errs = []
    if not s.id:
        errs.append("empty id")
    if not s.question.strip():
        errs.append("empty question")
    if not s.events:
        errs.append("no events")
    ids = s.event_ids
    if len(set(ids)) != len(ids):
        errs.append("duplicate event ids")
    idset = set(ids)
    if s.answer.type not in ANSWER_TYPES:
        errs.append(f"bad answer type {s.answer.type!r}")
    missing = [g for g in s.gold_evidence if g not in idset]
    if missing:
        errs.append(f"gold evidence not in log: {missing}")
    missing = [d for d in s.distractors if d not in idset]
    if missing:
        errs.append(f"distractors not in log: {missing}")
    if set(s.gold_evidence) & set(s.distractors):
        errs.append("an event is both gold and distractor")
    if s.no_evidence:
        if s.gold_evidence:
            errs.append("no_evidence scenario has gold evidence")
        if s.answer.type != "abstain":
            errs.append("no_evidence scenario must have answer type 'abstain'")
    else:
        if not s.gold_evidence:
            errs.append("answerable scenario has no gold evidence")
        if s.answer.type == "abstain":
            errs.append("answerable scenario has answer type 'abstain'")
        if s.answer.type in ("number", "entity") and not s.answer.required:
            errs.append("number/entity answer needs 'required' tokens")
        if s.answer.type == "yesno" and s.answer.value not in ("yes", "no"):
            errs.append("yesno answer value must be 'yes' or 'no'")
    if errs:
        raise ScenarioError(f"{s.id}: " + "; ".join(errs))


def load_jsonl(path: str | Path) -> list[Scenario]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                s = Scenario.from_dict(json.loads(line))
                validate(s)
                out.append(s)
    return out


def dump_jsonl(scenarios: Iterable[Scenario], path: str | Path) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for s in scenarios:
            validate(s)
            f.write(json.dumps(s.to_dict(), sort_keys=True) + "\n")
