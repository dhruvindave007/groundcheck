import pytest

from groundcheck.schema import Answer, Event, Scenario, ScenarioError, load_jsonl, validate


def make(**kw):
    base = dict(id="t1", domain="test", question="q?", events=[Event("A", "t", "s", "x"), Event("B", "t", "s", "y")],
                answer=Answer("yesno", "yes"), gold_evidence=["A"], distractors=["B"])
    base.update(kw)
    return Scenario(**base)


def test_valid_scenario_passes():
    validate(make())


@pytest.mark.parametrize("kw", [
    dict(gold_evidence=["Z"]),                      # gold not in log
    dict(distractors=["A"]),                         # gold and distractor overlap
    dict(events=[Event("A", "t", "s", "x")] * 2),    # duplicate ids
    dict(gold_evidence=[]),                          # answerable without evidence
    dict(no_evidence=True),                          # no-evidence with gold + non-abstain answer
    dict(answer=Answer("number", "3")),              # number without required tokens
    dict(answer=Answer("yesno", "maybe")),
])
def test_invalid_scenarios_rejected(kw):
    with pytest.raises(ScenarioError):
        validate(make(**kw))


def test_roundtrip():
    s = make()
    assert Scenario.from_dict(s.to_dict()) == s


def test_shipped_suites_valid():
    office = load_jsonl("scenarios/office.jsonl")
    syslog = load_jsonl("scenarios/syslog.jsonl")
    assert len(office) == 27 and len(syslog) == 96
    assert any(s.no_evidence for s in office) and any(s.no_evidence for s in syslog)
