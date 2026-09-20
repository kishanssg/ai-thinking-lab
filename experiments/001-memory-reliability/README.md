# Experiment 001: Memory Reliability

A stale eligibility flag can cause a fictional worker to be assigned incorrectly. A fresh check helps, but eligibility may change before execution. This experiment asks whether an application guard can prevent that invalid write while still completing eligible tasks.

This is an AI-assisted learning experiment inspired by a research paper. ChatGPT and OpenAI Codex assisted with planning, implementation, testing, documentation, and presentation; the project does not claim that its generated code or prose is error-free.

## Method

Six predetermined fixtures cover unchanged eligibility, stale true, stale false, a missing worker, a failed lookup, and an injected eligibility revocation. All records and rules are synthetic. Each of four approaches runs each fixture against a fresh SQLite database:

- A uses memory and an unguarded write.
- B voluntarily checks on every task under a fixed simulated policy, then uses an unguarded write.
- C uses the same policy, but an internal application wrapper requires a positive precheck before writing.
- D adds a current-eligibility conditional insert inside `BEGIN IMMEDIATE`, enforcing eligibility at assignment time.

C's positive check can become stale. D's write predicate remains authoritative. The wrapper is not an unforgeable authorization system, and the unsafe operations exist only as experimental baselines. See [methodology](methodology.md).

## Reproduce

From the repository root with Python 3.13:

```sh
python3 -m unittest discover -s experiments/001-memory-reliability -p 'test_*.py' -v
python3 experiments/001-memory-reliability/experiment.py
```

No packages, network access, model calls, or credentials are needed. The eight tests check all 24 fixture/approach outcomes, the race, eligibility enforcement, idempotency, lookup failure, and event-derived metrics. [Test output](results/tests.txt) and [results](results/results.json) are actual saved runs. Rerunning overwrites the JSON; use `--output` with another path to preserve an additional run. Preserve any failed test logs rather than replacing them.

## Findings

| Approach | Incorrect affirmative recommendations / tasks | Invalid commits / tasks | Completed / eligible tasks | Unnecessary refusals / eligible tasks | Verified / tasks | Tool calls |
|---|---:|---:|---:|---:|---:|---:|
| A | 2/6 | 3/6 | 2/3 | 1/3 | 0/6 | 5 |
| B | 0/6 | 1/6 | 2/3 | 1/3 | 6/6 | 9 |
| C | 0/6 | 1/6 | 2/3 | 1/3 | 6/6 | 9 |
| D | 0/6 | 0/6 | 2/3 | 1/3 | 6/6 | 9 |

All four approaches completed only 2/3 legitimate tasks. D prevented invalid commits in these cases, but refused an eligible worker when lookup failed. A missed a different eligible task because stale memory said false. B and C behaved identically by construction. [Per-scenario findings](findings.md) retain unsafe baseline outcomes.

## Interpretation and limits

The observations illustrate stale-state and time-of-check/time-of-use failures in our own deterministic Python/SQLite system. Standard-library tools and synthetic traces make this application-level mechanism inexpensive to inspect and test. No cost benchmark or real LLM reliability claim is made.

No real LLM or model API was evaluated. Simulated voluntary checking cannot establish prompt compliance. We cannot generalize from six hand-selected cases, a single binary rule, and sequential race injection. Performance measurements are descriptive, not benchmarks. A production system would need broader constraints, authorization, failure recovery, and concurrency testing.

This is not a reproduction of MemRiskBench, its benchmark, or model scores. The measured results above are ours, not the researchers'. See [research attribution](attribution.md).
