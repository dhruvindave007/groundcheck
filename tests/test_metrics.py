import pytest

from groundcheck.metrics import Prediction, bootstrap_ci, grade_answer, score
from groundcheck.prompts import parse_response
from groundcheck.schema import Answer, Event, Scenario


def scen(answer=Answer("yesno", "yes"), gold=("A", "B"), dis=("C",), no_ev=False):
    ev = [Event(i, "t", "s", i) for i in "ABCDE"]
    return Scenario("s", "test", "q?", ev, answer, list(gold), list(dis), no_ev)


def test_hand_checked_citation_scores():
    # cites A (gold), C (distractor), Z (fabricated): P = 1/3, R = 1/2, F1 = 0.4
    r = score(scen(), Prediction(answer="Yes.", citations=["A", "C", "Z"]))
    assert r["precision"] == pytest.approx(1 / 3)
    assert r["recall"] == pytest.approx(1 / 2)
    assert r["f1"] == pytest.approx(0.4)
    assert r["fabricated"] == 1.0
    assert r["distractor_rate"] == pytest.approx(1 / 3)
    assert r["correct"] == 1.0
    assert r["grounded"] == 0.0  # right answer, F1 0.4 < 0.5


def test_perfect_and_duplicate_citations():
    r = score(scen(), Prediction(answer="yes", citations=["A", "B", "A"]))
    assert (r["precision"], r["recall"], r["f1"], r["fabricated"], r["grounded"]) == (1, 1, 1, 0, 1)


def test_no_citations_and_abstain_on_answerable():
    r = score(scen(), Prediction(answer="insufficient evidence", abstain=True))
    assert r["f1"] == 0 and r["correct"] == 0 and r["false_abstain"] == 1
    assert r["distractor_rate"] is None


def test_no_evidence_scenario():
    s = scen(answer=Answer("abstain", "insufficient evidence"), gold=(), no_ev=True)
    r = score(s, Prediction(answer="x", abstain=True))
    assert r["abstained_noev"] == 1 and r["f1"] is None and r["correct"] is None
    r = score(s, Prediction(answer="yes", citations=["Q"]))
    assert r["abstained_noev"] == 0 and r["fabricated"] == 1


def test_citation_only_baseline_has_no_accuracy():
    r = score(scen(), Prediction(citations=["A"], answers=False))
    assert r["correct"] is None and r["f1"] == pytest.approx(2 / 3)


def test_grading():
    assert grade_answer(scen(Answer("number", "16, limit 15", ["16", "15"])), "16 tracks; limit is 15")
    assert not grade_answer(scen(Answer("number", "16", ["16"])), "15")
    assert grade_answer(scen(Answer("entity", "web-03", ["web-03"])), "Host WEB-03")
    assert not grade_answer(scen(Answer("yesno", "no")), "Yes, it did not")


def test_bootstrap():
    mean, lo, hi, n = bootstrap_ci([1.0, 0.0, 1.0, 1.0, None])
    assert mean == 0.75 and n == 4 and 0 <= lo <= mean <= hi <= 1
    assert bootstrap_ci([0.5] * 10)[1:3] == (0.5, 0.5)
    assert bootstrap_ci([None]) == (None, None, None, 0)


def test_parse_response():
    p = parse_response('Sure: {"answer": "web-03", "citations": ["L1", "L2"], "insufficient_evidence": false}')
    assert p.answer == "web-03" and p.citations == ["L1", "L2"] and not p.abstain
    p = parse_response('{"answer": "Insufficient evidence", "citations": [], "insufficient_evidence": false}')
    assert p.abstain
    p = parse_response('answer: web-03 "citations": ["L9"] (broken json')
    assert p.citations == ["L9"]
