"""Command line: generate, validate, run, report."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from groundcheck.generators.syslog import default_suite
from groundcheck.metrics import METRICS, aggregate, score
from groundcheck.models import get_solver, safe_name
from groundcheck.schema import dump_jsonl, load_jsonl

SUITES = {"office": ["office.jsonl"], "syslog": ["syslog.jsonl"], "all": ["office.jsonl", "syslog.jsonl"]}


def load_suite(suite: str, scen_dir: str):
    out = []
    for f in SUITES[suite]:
        out.extend(load_jsonl(Path(scen_dir) / f))
    return out


def cmd_generate(a):
    sc = default_suite(a.seed)
    out = Path(a.scenarios_dir) / "syslog.jsonl"
    dump_jsonl(sc, out)
    print(f"wrote {len(sc)} scenarios to {out}")


def cmd_validate(a):
    for suite in ("office", "syslog"):
        sc = load_suite(suite, a.scenarios_dir)
        noev = sum(s.no_evidence for s in sc)
        print(f"{suite}: {len(sc)} scenarios valid ({noev} no-evidence)")


def cmd_run(a):
    scen = load_suite(a.suite, a.scenarios_dir)
    if a.limit:
        scen = scen[: a.limit]
    solver = get_solver(a.model, a.condition, a.cache_dir)
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = f"{a.suite}__{safe_name(solver.name)}"
    rows = []
    with open(outdir / f"{stem}.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for s in scen:
            p = solver.solve(s)
            r = score(s, p)
            rows.append(r)
            f.write(json.dumps({"scenario": s.id, "domain": s.domain, "meta": s.meta, "answer": p.answer,
                                "citations": p.citations, "abstain": p.abstain, "scores": r}) + "\n")
    agg = aggregate(rows, a.n_boot, a.seed)
    summary = {"model": solver.name, "suite": a.suite, "n": len(rows), "metrics": agg}
    (outdir / f"{stem}.summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"{solver.name} on {a.suite} ({len(rows)} scenarios)")
    for m in METRICS:
        mean, lo, hi, n = agg[m]
        if mean is not None:
            print(f"  {m:16s} {mean:.3f}  [{lo:.3f}, {hi:.3f}]  n={n}")


LABELS = [("precision", "Cite P"), ("recall", "Cite R"), ("f1", "Cite F1"), ("fabricated", "Fabricated-ID"),
          ("distractor_rate", "Distractor"), ("correct", "Accuracy"), ("grounded", "Grounded acc"),
          ("abstained_noev", "Abstain (no-ev)"), ("false_abstain", "False abstain")]


def _fmt(t):
    mean, lo, hi, n = t
    return "n/a" if mean is None else f"{mean:.2f} [{lo:.2f}, {hi:.2f}]"


def build_report(runs_dir: Path) -> str:
    summaries = sorted(runs_dir.glob("*.summary.json"))
    by_suite = defaultdict(list)
    for p in summaries:
        d = json.loads(p.read_text(encoding="utf-8"))
        by_suite[d["suite"]].append((p, d))
    lines = []
    for suite in sorted(by_suite):
        lines += [f"### Suite: {suite}", "",
                  "| Model | N | " + " | ".join(lab for _, lab in LABELS) + " |",
                  "|---|---|" + "---|" * len(LABELS)]
        for _, d in by_suite[suite]:
            lines.append(f"| {d['model']} | {d['n']} | " + " | ".join(_fmt(d["metrics"][m]) for m, _ in LABELS) + " |")
        lines.append("")
        # syslog ablation slice: citation F1 by distractor share
        shares, table = set(), {}
        for p, d in by_suite[suite]:
            per = defaultdict(list)
            for line in open(p.with_name(p.name.replace(".summary.json", ".jsonl")), encoding="utf-8"):
                r = json.loads(line)
                if r["domain"] == "syslog" and r["scores"]["f1"] is not None:
                    per[r["meta"]["distractor_share"]].append(r["scores"]["f1"])
            shares |= set(per)
            table[d["model"]] = per
        if shares:
            sh = sorted(shares)
            lines += ["Citation F1 on syslog scenarios by distractor share (mean, answerable scenarios):", "",
                      "| Model | " + " | ".join(f"{int(x * 100)}%" for x in sh) + " |", "|---|" + "---|" * len(sh)]
            for model, per in table.items():
                lines.append(f"| {model} | " + " | ".join(
                    f"{sum(per[x]) / len(per[x]):.2f}" if per[x] else "n/a" for x in sh) + " |")
            lines.append("")
    return "\n".join(lines)


def cmd_report(a):
    md = "## Results\n\nMean over scenarios with bootstrap 95% CI (1000 resamples).\n\n" + build_report(Path(a.runs))
    Path(a.out).write_text(md, encoding="utf-8", newline="\n")
    print(md)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="groundcheck")
    ap.add_argument("--scenarios-dir", default="scenarios")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="regenerate scenarios/syslog.jsonl")
    g.add_argument("--seed", type=int, default=0)
    g.set_defaults(fn=cmd_generate)
    sub.add_parser("validate", help="validate all scenario files").set_defaults(fn=cmd_validate)
    r = sub.add_parser("run", help="run one model on one suite")
    r.add_argument("--model", required=True)
    r.add_argument("--suite", default="all", choices=sorted(SUITES))
    r.add_argument("--condition", default="full", choices=["full", "oracle-evidence"])
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--out", default="results/runs")
    r.add_argument("--cache-dir", default=".cache")
    r.add_argument("--n-boot", type=int, default=1000)
    r.add_argument("--seed", type=int, default=0)
    r.set_defaults(fn=cmd_run)
    p = sub.add_parser("report", help="write a markdown table from run summaries")
    p.add_argument("--runs", default="results/runs")
    p.add_argument("--out", default="results/RESULTS.md")
    p.set_defaults(fn=cmd_report)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
