import json

from groundcheck.generators.syslog import TEMPLATES, default_suite, generate
from groundcheck.schema import validate


def test_same_seed_same_scenario():
    a = generate(7, "disk", 50, 0.5, "end")
    b = generate(7, "disk", 50, 0.5, "end")
    assert a == b
    assert generate(8, "disk", 50, 0.5, "end") != a


def test_shipped_file_matches_generator():
    shipped = open("scenarios/syslog.jsonl", encoding="utf-8").read().splitlines()
    regen = [json.dumps(s.to_dict(), sort_keys=True) for s in default_suite(0)]
    assert shipped == regen


def test_controls_respected():
    for t in TEMPLATES:
        for n in (20, 100):
            for d in (0.0, 0.5):
                for pos in ("start", "middle", "end"):
                    s = generate(1, t, n, d, pos)
                    validate(s)
                    assert len(s.events) == n
                    third = n / 3
                    lo, hi = {"start": (0, third), "middle": (third, 2 * third), "end": (2 * third, n)}[pos]
                    idx = [s.event_ids.index(g) for g in s.gold_evidence]
                    assert all(lo - 1 <= i < hi + 1 for i in idx)
                    n_rest = n - len(s.gold_evidence)
                    assert len(s.distractors) == round(d * n_rest)


def test_uuid_ids_and_no_evidence():
    s = generate(3, "trace", 30, 0.25, "middle", id_format="uuid", no_evidence=True)
    validate(s)
    assert s.no_evidence and not s.gold_evidence and len(s.event_ids[0]) == 36
