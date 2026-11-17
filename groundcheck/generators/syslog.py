"""Seeded generator for synthetic server-log scenarios.

Each scenario is built from a question template that emits (a) the gold lines in
causal order, (b) an unbounded supply of near-miss distractor lines that share
hosts, users, services or wording with the gold lines but do not answer the
question, and (c) a no-evidence variant in which the supporting lines are
withheld. Background noise fills the rest of the log.

Controls: log length, distractor share (fraction of non-gold lines that are
distractors), gold evidence position (start, middle or end third of the log),
and ID format (sequential or UUID). The same seed always produces the same
scenario.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone

from groundcheck.schema import Answer, Event, Scenario

HOSTS = [f"web-{i:02d}" for i in range(1, 13)] + [f"db-{i:02d}" for i in range(1, 5)]
SERVICES = ["payments", "search", "checkout", "auth", "inventory", "notifications", "billing", "catalog"]
USERS = ["alice", "bob", "carol", "dmitri", "erin", "farah", "gopal", "hana", "ivan", "jun"]
ABSTAIN = Answer("abstain", "insufficient evidence")


def _others(rng, pool, exclude, k=1):
    cand = [x for x in pool if x not in exclude]
    return rng.sample(cand, k) if k > 1 else rng.choice(cand)


def t_disk(rng, no_ev):
    h, s = rng.choice(HOSTS), rng.choice(SERVICES)
    q = f"Service {s} crashed. Which host's full disk caused the crash?"
    if no_ev:
        gold = []
        extra = [("app", f"service={s} host={h} CRASH exit_code=137 reason=OOMKilled")]
    else:
        gold = [("sys", f"host={h} disk=/var usage=100% ENOSPC write failed"),
                ("app", f"service={s} host={h} CRASH exit_code=1 reason=ENOSPC: no space left on device")]
        extra = []

    def distractor(r):
        h2, s2 = _others(r, HOSTS, {h}), _others(r, SERVICES, {s})
        return r.choice([
            ("sys", f"host={h} disk=/data usage={r.randint(70, 94)}% WARN"),
            ("sys", f"host={h2} disk=/var usage=100% ENOSPC write failed"),
            ("app", f"service={s2} host={h2} CRASH exit_code=1 reason=ENOSPC: no space left on device"),
            ("app", f"service={s} host={h} health_check latency={r.randint(300, 900)}ms SLOW"),
        ])
    ans = ABSTAIN if no_ev else Answer("entity", h, [h])
    return q, ans, gold, extra, distractor, {h, s}


def t_lockout(rng, no_ev):
    u, k = rng.choice(USERS), rng.randint(2, 4)
    q = f"How many failed login attempts for user {u} were logged before the account was locked?"
    fails = [("auth", f"user={u} login FAILED src=10.0.{rng.randint(0, 255)}.{rng.randint(1, 254)} reason=bad_password")
             for _ in range(k)]
    if no_ev:
        gold, extra = [], fails  # failures exist, but no lockout event
    else:
        gold, extra = fails + [("auth", f"user={u} account LOCKED after repeated failures")], []

    def distractor(r):
        u2 = _others(r, USERS, {u})
        return r.choice([
            ("auth", f"user={u2} login FAILED src=10.0.{r.randint(0, 255)}.{r.randint(1, 254)} reason=bad_password"),
            ("auth", f"user={u2} account LOCKED after repeated failures"),
            ("auth", f"user={u} password_reset_requested via=email"),
            ("auth", f"user={u} mfa_challenge sent"),
        ])
    ans = ABSTAIN if no_ev else Answer("number", str(k), [str(k)])
    return q, ans, gold, extra, distractor, {u}


def t_deploy(rng, no_ev):
    s = rng.choice(SERVICES)
    v = f"v{rng.randint(1, 4)}.{rng.randint(0, 20)}.{rng.randint(0, 9)}"
    q = f"Which version of {s} was deployed to production when its error-rate alert fired?"
    deploy = ("deploy", f"deploy service={s} env=production version={v} status=success")
    if no_ev:
        gold, extra = [], [deploy]  # deploy exists, but no alert for this service
    else:
        gold, extra = [deploy, ("alert", f"ALERT service={s} env=production error_rate={rng.randint(12, 60)}% threshold=5%")], []

    def distractor(r):
        s2 = _others(r, SERVICES, {s})
        v2 = f"v{r.randint(1, 4)}.{r.randint(0, 20)}.{r.randint(0, 9)}"
        return r.choice([
            ("deploy", f"deploy service={s} env=staging version={v2} status=success"),
            ("deploy", f"deploy service={s2} env=production version={v2} status=success"),
            ("alert", f"ALERT service={s2} env=production error_rate={r.randint(12, 60)}% threshold=5%"),
            ("alert", f"ALERT service={s} env=staging error_rate={r.randint(12, 60)}% threshold=5%"),
        ])
    ans = ABSTAIN if no_ev else Answer("entity", v, [v])
    return q, ans, gold, extra, distractor, {s}


def t_trace(rng, no_ev):
    tid = f"{rng.getrandbits(32):08x}"
    h = rng.choice(HOSTS[:12])
    q = f"Request trace_id={tid} returned an HTTP 500. Which backend host served it?"
    if no_ev:
        gold, extra = [], []
    else:
        gold = [("gateway", f"gateway trace_id={tid} route=/api/checkout upstream={h}"),
                ("app", f"host={h} trace_id={tid} status=500 error=upstream_timeout")]
        extra = []

    def distractor(r):
        t2 = tid[:5] + f"{r.getrandbits(12):03x}"  # near-identical trace id
        h2 = _others(r, HOSTS[:12], {h})
        return r.choice([
            ("gateway", f"gateway trace_id={t2} route=/api/checkout upstream={h2}"),
            ("app", f"host={h2} trace_id={t2} status=500 error=upstream_timeout"),
            ("app", f"host={h} trace_id={t2} status=200 latency={r.randint(5, 80)}ms"),
        ])
    ans = ABSTAIN if no_ev else Answer("entity", h, [h])
    return q, ans, gold, extra, distractor, {h}


TEMPLATES = {"disk": t_disk, "lockout": t_lockout, "deploy": t_deploy, "trace": t_trace}


def _background(rng, avoid):
    h = _others(rng, HOSTS, avoid)
    s = _others(rng, SERVICES, avoid)
    u = _others(rng, USERS, avoid)
    return rng.choice([
        ("app", f"service={s} host={h} GET /health 200 {rng.randint(1, 9)}ms"),
        ("cron", f"cron job=logrotate host={h} status=ok duration={rng.randint(1, 40)}s"),
        ("auth", f"user={u} login SUCCESS src=10.1.{rng.randint(0, 255)}.{rng.randint(1, 254)}"),
        ("sys", f"host={h} cpu={rng.randint(3, 60)}% mem={rng.randint(20, 70)}%"),
        ("app", f"service={s} host={h} cache_hit_ratio=0.{rng.randint(70, 99)}"),
        ("sys", f"host={h} ntp offset={rng.randint(0, 9)}ms"),
    ])


def generate(seed: int, template: str, n_events: int = 50, distractor_share: float = 0.25,
             position: str = "middle", id_format: str = "seq", no_evidence: bool = False) -> Scenario:
    rng = random.Random(f"{seed}|{template}|{n_events}|{distractor_share}|{position}|{id_format}|{no_evidence}")
    q, ans, gold, extra, distractor, avoid = TEMPLATES[template](rng, no_evidence)
    fixed = [("G", *g) for g in gold] + [("X", *x) for x in extra]  # placed in order
    n_rest = n_events - len(fixed)
    if n_rest < 0:
        raise ValueError("log too short for template")
    n_dis = round(distractor_share * n_rest)
    rest = [("D", *distractor(rng)) for _ in range(n_dis)] + [("B", *_background(rng, avoid)) for _ in range(n_rest - n_dis)]
    rng.shuffle(rest)
    # pick slots for the fixed block inside the requested third
    third = n_events / 3
    lo, hi = {"start": (0, third), "middle": (third, 2 * third), "end": (2 * third, n_events)}[position]
    slots = sorted(rng.sample(range(int(lo), max(int(hi), int(lo) + len(fixed))), len(fixed)))
    lines, it_rest, it_fixed = [], iter(rest), iter(fixed)
    for i in range(n_events):
        if slots and i == slots[0]:
            slots.pop(0)
            lines.append(next(it_fixed))
        else:
            lines.append(next(it_rest))
    t = datetime(2026, 3, 1, tzinfo=timezone.utc) + timedelta(hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
    events, gold_ids, dis_ids = [], [], []
    start = rng.randint(1, 500)
    for i, (kind, src, text) in enumerate(lines):
        t += timedelta(seconds=rng.randint(1, 30))
        eid = f"L{start + i:04d}" if id_format == "seq" else str(uuid.UUID(int=rng.getrandbits(128), version=4))
        events.append(Event(eid, t.strftime("%Y-%m-%dT%H:%M:%SZ"), src, text))
        if kind == "G":
            gold_ids.append(eid)
        elif kind in ("D", "X"):  # withheld-context lines in no-evidence variants count as distractors
            dis_ids.append(eid)
    sid = f"syslog-{template}-n{n_events}-d{int(distractor_share * 100)}-{position}-{id_format}-s{seed}" + ("-noev" if no_evidence else "")
    return Scenario(
        id=sid, domain="syslog", question=q, events=events, answer=ans,
        gold_evidence=sorted(gold_ids), distractors=sorted(dis_ids), no_evidence=no_evidence,
        meta={"template": template, "n_events": n_events, "distractor_share": distractor_share,
              "position": position, "id_format": id_format, "seed": seed},
    )


def default_suite(seed: int = 0) -> list[Scenario]:
    """The v0 syslog suite: 4 lengths x 4 distractor shares x 3 positions x 2 reps = 96 scenarios.

    Templates rotate; every fifth scenario is a no-evidence variant.
    """
    out, i = [], 0
    names = list(TEMPLATES)
    for rep in range(2):
        for n in (20, 50, 100, 200):
            for d in (0.0, 0.25, 0.5, 0.75):
                for pos in ("start", "middle", "end"):
                    out.append(generate(seed * 1000 + rep, names[i % len(names)], n, d, pos,
                                        no_evidence=(i % 5 == 4)))
                    i += 1
    return out
