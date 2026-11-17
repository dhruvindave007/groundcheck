# groundcheck

A benchmark for whether LLM agents cite real evidence or fabricate it.

## Abstract

Agents that investigate logs, tickets or documents are often asked to justify a conclusion by citing
the IDs of the records it rests on. A cited ID is only useful if it exists, if it supports the claim,
and if the set of citations is complete. groundcheck measures this directly. Each scenario gives a model
an event log with stable IDs and a question; the model must answer and cite the supporting event IDs, or
say the log does not contain enough evidence. Every scenario carries a gold answer, a gold evidence set,
and labelled near-miss distractor events, so citation errors can be split into three kinds: citing an ID
that is not in the log (fabrication), citing a plausible but wrong event (distractor capture), and
missing required evidence (low recall). Version 0.1 ships 123 scenarios in two domains: 27 office
security incidents (badge swipes and camera tracks) adapted from an earlier investigation agent's eval
set, and 96 synthetic server-log scenarios from a seeded generator with controllable log length,
distractor share and evidence position. This release reports non-LLM baselines only; model runs are next.

## What is measured

All metrics are computed per scenario, averaged, and reported with a percentile bootstrap 95% CI over
scenarios (1000 resamples, fixed seed).

| Metric | Definition | Scenarios |
|---|---|---|
| Citation precision / recall / F1 | Overlap of cited IDs with the gold evidence set. Citing nothing scores 0. | answerable |
| Fabricated-ID rate | Share of responses that cite at least one ID not present in the log. | all |
| Distractor-citation rate | Share of cited IDs that are labelled distractors. | with ≥1 citation |
| Accuracy | Answer matches gold (yes/no, all required numbers, or all required entities) and the model did not abstain. | answerable |
| Grounded accuracy | Correct and citation F1 ≥ 0.5: right for the right reasons. | answerable |
| Abstention (no-ev) | Model says the evidence is insufficient. | no-evidence |
| False abstention | Model abstains although the log answers the question. | answerable |

Of the 123 scenarios, 92 are answerable and 31 are no-evidence (12 office, 19 syslog).

## Baseline results

Full suite (123 scenarios, 92 answerable). Mean with bootstrap 95% CI.

| Baseline | Cite P | Cite R | Cite F1 | Fabricated-ID | Distractor | Accuracy | Grounded acc | Abstain (no-ev) |
|---|---|---|---|---|---|---|---|---|
| Random-k | 0.07 [0.04, 0.10] | 0.07 [0.04, 0.10] | 0.07 [0.04, 0.10] | 0.00 | 0.34 [0.28, 0.42] | n/a | n/a | 0.00 |
| BM25 top-k | 0.74 [0.68, 0.80] | 0.74 [0.68, 0.80] | 0.74 [0.68, 0.80] | 0.00 | 0.40 [0.33, 0.47] | n/a | n/a | 0.00 |
| Oracle | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 | 1.00 | 1.00 | 1.00 |

Citation F1 on answerable syslog scenarios by distractor share:

| Baseline | 0% | 25% | 50% | 75% |
|---|---|---|---|---|
| Random-k | 0.04 | 0.07 | 0.03 | 0.07 |
| BM25 top-k | 1.00 | 0.70 | 0.65 | 0.69 |

Per-domain tables with CIs are in [results/RESULTS.md](results/RESULTS.md); per-scenario outputs are in
`results/runs/`.

How to read these numbers:

- Random-k and BM25 cite k events where k is the size of the gold set (2 on no-evidence scenarios), so
  precision equals recall by construction. Matching k uses gold information; it makes BM25 a strong,
  slightly optimistic retrieval reference rather than a deployable system.
- Neither citation-only baseline answers or abstains, so accuracy is n/a and no-evidence abstention is 0.
- Baselines only cite IDs from the log, so their fabricated-ID rate is 0 by construction. Any nonzero
  fabrication in a model run is therefore attributable to the model.
- BM25 is perfect when there are no distractors and drops to about 0.65 to 0.70 once near-miss lines share
  wording with the gold lines. A model that only matches keywords should show the same drop.
- Oracle cites the gold set and returns the gold answer. It checks that the scoring pipeline reaches 1.0;
  it is not a model result. For LLMs, `--condition oracle-evidence` shows the model only the gold events,
  which gives the answer-accuracy ceiling.

## Quickstart

```bash
git clone <repo-url> groundcheck && cd groundcheck
pip install -e ".[dev]"            # or: uv pip install -e ".[dev]"
pytest                              # 24 tests
groundcheck validate
groundcheck run --model baseline:bm25 --suite all
groundcheck run --model mock --suite office          # deterministic fake LLM, no network
groundcheck report                                   # writes results/RESULTS.md
```

Running a real model (keys are read from the environment and never logged):

```bash
# OpenAI or any OpenAI-compatible server (vLLM, Ollama, OpenRouter)
export OPENAI_API_KEY=...                            # optional for local servers
export OPENAI_BASE_URL=http://localhost:11434/v1     # default https://api.openai.com/v1
groundcheck run --model openai:<model-name> --suite all

pip install -e ".[anthropic]"; export ANTHROPIC_API_KEY=...
groundcheck run --model anthropic:<model-name> --suite all

pip install -e ".[bedrock]"    # standard AWS credential chain, AWS_REGION
groundcheck run --model bedrock:<model-id> --suite all
```

Model replies are cached in `.cache/` by a hash of model, prompt version and prompt, so reruns are free.

## Layout

```
groundcheck/schema.py             Scenario, Event, Answer + validator, JSONL I/O
groundcheck/generators/syslog.py  seeded server-log generator (length, distractor share, position, ID format)
groundcheck/prompts.py            versioned prompt (cite-ids-v1) and JSON/regex response parser
groundcheck/models.py             mock, OpenAI-compatible, Anthropic, Bedrock adapters; baselines
groundcheck/metrics.py            per-scenario scores, bootstrap CIs
groundcheck/cli.py                generate | validate | run | report
scripts/port_office.py            one-off port of the office-incident cases
scenarios/                        office.jsonl, syslog.jsonl, data card
results/                          per-scenario runs and RESULTS.md
```

## Limitations

- No LLM has been run yet. The table above contains baselines only.
- 123 scenarios is small; CIs on the 27-scenario office suite are wide (about ±0.15 on F1).
- Gold evidence sets were written by one author and not checked by a second annotator. In office
  scenarios, repeated observations of the same track beyond the ones listed as gold are labelled
  distractors, which penalises a model that cites them although they are consistent with the answer.
- Office questions were rewritten from the original eval so that answers are machine-checkable; cases
  whose original check was "the model must hedge" became no-evidence scenarios.
- Answer grading is exact-match on yes/no, numbers and entity strings. It does not judge free-text
  reasoning, and it does not check that each citation supports the specific claim it is attached to.
- Syslog scenarios come from four templates. Models may learn the templates; they are a controlled probe,
  not a sample of real logs.
- Abstention is detected from the `insufficient_evidence` flag or a short list of hedge phrases.

## Roadmap

1. Model runs: two API models and two or three open models via vLLM or Ollama, on the full suite and the
   distractor-share ablation (0/25/50/75%), with temperature 0 and 0.7 (3 samples).
2. Ablations already supported by the generator but not yet reported: log length (20 to 200), evidence
   position (start, middle, end), and ID format (sequential vs. UUID).
3. Prompt variants: IDs only vs. IDs plus quoted event text, and a self-check pass.
4. A third domain (short document QA with passage IDs) and a second annotator for gold sets.
5. An Inspect task wrapper so the suite runs inside existing eval harnesses.
6. A short technical report with failure analysis of hand-inspected cases.

## License

Apache-2.0. See [LICENSE](LICENSE).
