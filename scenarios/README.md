# Scenario data card

Format: one JSON object per line, schema in `groundcheck/schema.py`. Both files pass `groundcheck validate`.

## office.jsonl (27 scenarios, 12 no-evidence)

Adapted from the investigation eval set of an office security digital-twin prototype by the same author.
All people, badges, tracks and times are synthetic simulator output; no real data is included.
Each log has three parts, sorted by time and numbered `E001`, `E002`, ...:

- eight facility configuration facts (zone capacities, minimum transit times, business hours, badge assignments);
- a background "normal workday" sequence two hours before the incident;
- the incident's badge-swipe and camera-observation events.

Questions were rewritten so the answer is checkable (yes/no, number or entity). Cases whose original
expectation was that the model must hedge (identity, intent, policy, or evidence removed from the log) are
no-evidence scenarios. Distractors are non-gold events that share a track, badge or person label with the
gold events (for no-evidence scenarios: with the entities named in the question).
Regenerate with `python scripts/port_office.py --src <source project root>`.

## syslog.jsonl (96 scenarios, 19 no-evidence)

Produced by `groundcheck generate --seed 0` (`groundcheck/generators/syslog.py`); a test checks the file
matches the generator byte for byte. Grid: log length {20, 50, 100, 200} x distractor share
{0, 0.25, 0.5, 0.75} x gold position {start, middle, end} x 2 seeds. Templates rotate over:

| Template | Question | Answer | Near-miss distractors |
|---|---|---|---|
| disk | Which host's full disk caused service S to crash? | host | full disks on other hosts, other services' ENOSPC crashes, warnings on the same host |
| lockout | How many failed logins for user U before lockout? | number | other users' failures and lockouts, same user's MFA and reset events |
| deploy | Which version of S was in production when its alert fired? | version | staging deploys and alerts, other services' deploys and alerts |
| trace | Which backend host served failing request T? | host | near-identical trace IDs on other hosts |

Every fifth scenario is a no-evidence variant in which the supporting lines are withheld (for example the
crash reason is OOMKilled and no disk filled up). Lines that remain from the withheld chain are labelled
distractors. IDs are sequential (`L0123`) by default; `id_format="uuid"` is available for the ID-format ablation.
