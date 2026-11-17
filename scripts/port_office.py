"""Port the office-incident investigation cases into groundcheck scenarios.

The source is a set of simulator scenario YAML files (badge swipes and camera
track observations, all synthetic). Each case's event log is the incident
scenario, plus a block of facility configuration facts, plus a background
"normal workday" sequence two hours earlier. Questions were adapted so every
answer is machine-checkable; cases whose original expectation was "the model
must hedge" became no-evidence scenarios.

Usage: python scripts/port_office.py --src <path to repo root of the source project>
Writes scenarios/office.jsonl. Requires PyYAML.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from groundcheck.schema import Answer, Event, Scenario, dump_jsonl

ZONE = {"cam_reception_01": "zone_reception", "cam_workspace_01": "zone_open_workspace",
        "cam_server_01": "zone_server_room"}

# key, text, entity tags (used only to label distractors)
CONFIG = [
    ("cap_rec", "zone_reception max_occupancy=15", {"cfg:capacity", "zone_reception"}),
    ("cap_srv", "zone_server_room max_occupancy=3", {"cfg:capacity", "zone_server_room"}),
    ("tr_rw", "min_transit zone_reception->zone_open_workspace=4s (adjacent)", {"cfg:transit"}),
    ("tr_ws", "min_transit zone_open_workspace->zone_server_room=5s (adjacent)", {"cfg:transit"}),
    ("tr_rs", "min_transit zone_reception->zone_server_room=9s (not adjacent, via zone_open_workspace)", {"cfg:transit"}),
    ("hours", "business_hours=08:00-19:00 UTC", {"cfg:hours"}),
    ("b1", "badge_0001 assigned_to=person_it_admin_01", {"badge_0001", "person_it_admin_01"}),
    ("b2", "badge_0002 assigned_to=person_it_admin_02", {"badge_0002", "person_it_admin_02"}),
]

A = Answer
ABSTAIN = A("abstain", "insufficient evidence")
# id, scenario, question, answer, gold keys ("s<i>" = incident step i, "c:<key>" = config), extra
CASES = [
    ("tg_real", "tailgating", "Did a second, unlabelled track enter the server room within 5 seconds of badge_0001 being granted at door_server_01?",
     A("yesno", "yes"), ["s0", "s1", "s2"], {}),
    ("tg_who", "tailgating", "What is the identity of the second person, track sim_trk_tail?", ABSTAIN, [], {}),
    ("tg_intent", "tailgating", "Did the person on track sim_trk_tail intend to break in?", ABSTAIN, [], {}),
    ("tg_unauth_why", "tailgating", "Which track entered the server room without a badge swipe of its own?",
     A("entity", "sim_trk_tail", ["sim_trk_tail"]), ["s0", "s1", "s2"], {}),
    ("tg_missing_badge", "tailgating", "At what time was the badge used by track sim_trk_admin granted at door_server_01 on the incident morning (around 10:00 UTC)?",
     ABSTAIN, [], {"drop": ["s0"]}),
    ("sr_path", "server_room_unauthorized_entry", "Which zones did track sim_trk_001 pass through before it reached the server room?",
     A("entity", "zone_reception, zone_open_workspace", ["reception", "workspace"]), ["s0", "s1"], {}),
    ("sr_dwell_len", "server_room_unauthorized_entry", "How many seconds passed between the first and the last observation of track sim_trk_001 in the server room?",
     A("number", "330", ["330"]), ["s2", "s13"], {}),
    ("sr_dwell_doing", "server_room_unauthorized_entry", "What was the person on track sim_trk_001 doing in the server room?", ABSTAIN, [], {}),
    ("sr_nobadge", "server_room_unauthorized_entry", "Was a badge swipe recorded at door_server_01 in the minute before track sim_trk_001 entered the server room?",
     A("yesno", "no"), ["s1", "s2"], {}),
    ("it_real", "impossible_transit", "Did track sim_trk_jump move from the reception camera to the workspace camera faster than the minimum transit time between those zones?",
     A("yesno", "yes"), ["s0", "s1", "c:tr_rw"], {}),
    ("it_label", "impossible_transit", "What is the real name of the person labelled person_staff_01?", ABSTAIN, [], {}),
    ("ah_breach", "after_hours_presence", "Was track sim_trk_night_01 present in the open workspace outside business hours?",
     A("yesno", "yes"), ["s0", "s1", "s2", "c:hours"], {}),
    ("oc_count", "reception_over_capacity", "How many distinct tracks were observed in reception during the incident, and what is the reception occupancy limit?",
     A("number", "16 tracks, limit 15", ["16", "15"]), [f"s{i}" for i in range(16)] + ["c:cap_rec"], {}),
    ("bwe_entered", "badge_without_entry", "After badge_0002 was granted at door_server_01 on the incident morning, did any track appear on the server room camera?",
     A("yesno", "no"), ["s0"], {}),
    ("bwe_stolen", "badge_without_entry", "Was badge_0002 stolen?", ABSTAIN, [], {}),
    ("e1_letin", "eval_badge_denied_then_entry", "Did the badge reader at door_server_01 grant access to badge_0100?",
     A("yesno", "no"), ["s0"], {}),
    ("e1_whose", "eval_badge_denied_then_entry", "Is the person on track sim_e1 the owner of badge_0100?", ABSTAIN, [], {}),
    ("e2_holder", "eval_two_unknown_after_badge", "Which of the two tracks, sim_e2_a or sim_e2_b, is the holder of badge_0002?", ABSTAIN, [], {}),
    ("e2_first", "eval_two_unknown_after_badge", "Is track sim_e2_b the person person_it_admin_02?", ABSTAIN, [], {}),
    ("e3_allowed", "eval_admin_after_hours", "Is person_it_admin_01 permitted by policy to work in the office at night?", ABSTAIN, [], {}),
    ("e3_who", "eval_admin_after_hours", "Which person label is attached to track sim_e3?",
     A("entity", "person_it_admin_01", ["person_it_admin_01"]), ["s0", "s1", "s2"], {}),
    ("e4_peak", "eval_server_over_capacity", "How many tracks were in the server room at the peak of the incident, and what is the server room capacity?",
     A("number", "4 tracks, capacity 3", ["4", "3"]), ["s0", "s1", "s2", "s3", "c:cap_srv"], {}),
    ("e4_group", "eval_server_over_capacity", "Did tracks sim_e4_1 to sim_e4_4 arrive together as one organised group?", ABSTAIN, [], {}),
    ("e5_hop", "eval_multi_hop_transit", "What is the minimum transit time in seconds from reception to the server room, which track sim_e5 appears to beat?",
     A("number", "9", ["9"]), ["s0", "s1", "c:tr_rs"], {}),
    ("e6_escalate", "eval_authorized_admin_dwell", "Which badge was granted at door_server_01 immediately before track sim_e6 appeared in the server room?",
     A("entity", "badge_0001", ["badge_0001"]), ["s0", "s1"], {}),
    ("e6_authorized", "eval_authorized_admin_dwell", "Is track sim_e6 labelled as the person to whom the badge granted just before its entry is assigned?",
     A("yesno", "yes"), ["s0", "s1", "c:b1"], {}),
    ("e6_doing", "eval_authorized_admin_dwell", "Was the person on track sim_e6 doing maintenance work?", ABSTAIN, [], {}),
]


def _ts(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _render(step: dict) -> tuple[str, str, set]:
    if step.get("kind") == "access" or "door_id" in step:
        text = f"ACCESS {step['result']} door={step['door_id']} badge={step['badge_id']}"
        return "access", text, {step["badge_id"]}
    pid = step.get("person_id")
    zone = ZONE.get(step["camera_id"], "unknown")
    text = (f"OBSERVATION camera={step['camera_id']} zone={zone} track={step['track_id']} "
            f"person_label={pid or 'none'} confidence={step.get('confidence', 0.9)}")
    tags = {step["track_id"]} | ({pid} if pid else set())
    return "camera", text, tags


def build(src: Path) -> list[Scenario]:
    dirs = [src / "data" / "scenarios", src / "backend" / "evals" / "investigation" / "scenarios"]

    def load(name):
        for d in dirs:
            p = d / f"{name}.yaml"
            if p.exists():
                return yaml.safe_load(p.read_text(encoding="utf-8"))
        raise FileNotFoundError(name)

    background = load("normal_workday")["steps"]
    out = []
    for cid, scen, question, answer, gold_keys, extra in CASES:
        d = load(scen)
        base = datetime.strptime(d["base_time_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        rows = []  # (time, key, source, text, tags)
        midnight = base.replace(hour=0, minute=0, second=0)
        for i, (k, text, tags) in enumerate(CONFIG):
            rows.append((midnight + timedelta(seconds=i), f"c:{k}", "config", text, tags))
        for i, st in enumerate(background):
            src_, text, tags = _render(st)
            rows.append((base - timedelta(hours=2) + timedelta(seconds=st["t"]), f"b{i}", src_, text, tags))
        for i, st in enumerate(d["steps"]):
            if f"s{i}" in extra.get("drop", []):
                continue
            src_, text, tags = _render(st)
            rows.append((base + timedelta(seconds=st["t"]), f"s{i}", src_, text, tags))
        rows.sort(key=lambda r: (r[0], r[1]))
        key2id = {r[1]: f"E{n + 1:03d}" for n, r in enumerate(rows)}
        events = [Event(key2id[k], _ts(t), s, txt) for t, k, s, txt, _ in rows]
        gold = [key2id[k] for k in gold_keys]
        gold_tags = set().union(*[r[4] for r in rows if r[1] in gold_keys]) if gold_keys else set()
        if not gold_keys:  # no-evidence: label events about the entities named in the question
            gold_tags = {t for r in rows for t in r[4] if t in question}
        distractors = [key2id[r[1]] for r in rows if r[1] not in gold_keys and r[4] & gold_tags]
        out.append(Scenario(
            id=f"office-{cid}", domain="office", question=question, events=events, answer=answer,
            gold_evidence=sorted(gold), distractors=sorted(distractors),
            no_evidence=answer.type == "abstain",
            meta={"source_case": cid, "source_scenario": scen},
        ))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="root of the source project")
    ap.add_argument("--out", default="scenarios/office.jsonl")
    a = ap.parse_args()
    sc = build(Path(a.src))
    dump_jsonl(sc, a.out)
    print(f"wrote {len(sc)} scenarios to {a.out}")


if __name__ == "__main__":
    main()
