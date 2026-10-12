# Experiment 001, Part 2: Concurrent Guard

[Part 1](../README.md) found that D, a precheck plus a conditional `INSERT ... SELECT ... WHERE approved=1` inside `BEGIN IMMEDIATE`, blocked the invalid write in its race scenario. But that cancellation was a sequential statement on the same in-memory connection, run before D's transaction began. So Part 1 could not tell D apart from simply re-reading approval late, and `BEGIN IMMEDIATE` was never contended. This part asks the question Part 1 left open: **does the guarded write matter, or does any late re-read work just as well?**

Claude Code (Anthropic) assisted with this follow-up's design, implementation, tests, and documentation, as part of this AI-assisted portfolio. The results below come from an actual saved run; the generated code and prose are not claimed to be error-free. Part 1's code, fixtures, and logical results are unchanged by this part.

## Method

A file-backed SQLite database (WAL) in a temporary directory. Two connections: an **agent** in the main thread and a **canceller** in its own thread, which sets the customer's approval to 0. Every approach does a decision-time precheck, then 1 ms of simulated work, then:

- **C**: unguarded insert (Part 1's C)
- **E**: re-read approval, then an unguarded insert, with no transaction around the pair (new)
- **F**: `BEGIN IMMEDIATE`, re-read, plain insert, `COMMIT` (new; separates "transaction" from "conditional insert")
- **D**: `BEGIN IMMEDIATE`, `INSERT ... SELECT ... WHERE approved=1`, `COMMIT` (Part 1's guard, re-implemented)

A trigger records the approval each inserted row saw at commit time; a row that saw 0 is an invalid commit. **Forced** mode makes the canceller thread fire at each approach's vulnerable point. **Free-running** mode fires it after a random 0–3 ms delay with no coordination. `SQLITE_BUSY` is retried with a 0.2 ms backoff and every occurrence is counted. See [methodology](methodology.md).

## Result

3,000 iterations per approach per run; invalid commits / iterations:

| Mode | C | E | F | D |
|---|---:|---:|---:|---:|
| Forced (cancellation at the vulnerable point) | 3000/3000 | 3000/3000 | 0/3000 | 0/3000 |
| Free-running, 3 runs combined | 2617/9000 (29.1%) | 1611/9000 (17.9%) | 0/9000 | 0/9000 |
| Free-running, per run (seeds 1, 2, 3) | 892 · 868 · 857 | 523 · 537 · 551 | 0 · 0 · 0 | 0 · 0 · 0 |

**E did not match D.** A late re-read cut invalid commits compared with C but left about one in six in this setup. D had none, and so did F. F is the same check as E, but done inside a write transaction. In SQLite, what prevents the invalid write is putting the check and the write in one write transaction. The conditional-insert syntax is not what matters.

98% of E's invalid commits (1,581/1,611) came from one pattern. The cancellation's write had started but not committed when E re-read. Under WAL, E saw the old committed value. Its insert hit `SQLITE_BUSY`, waited for the cancellation to commit, and then went in. The remaining 30 were cancellations that committed in the instant between E's re-read and insert. In forced mode, F's and D's transactions made the canceller's update wait (3,073 and 3,121 `SQLITE_BUSY` responses), which Part 1 never exercised. Details and every counter: [findings](findings.md).

## Limits

- **Timing-dependent.** The free-running rates came from one machine: Windows 11, Intel Core i7-10510U, Optane + SSD, CPython 3.13.3 with the GIL, SQLite 3.49.1. They varied between runs with identical settings (E: 523–551 per 3,000), and will differ on other hardware, operating systems, Python builds, think times, or delay windows. Read them as "this happens, often, under contention", not as a rate to quote.
- **Zero is not proof.** 0 invalid commits in 12,000 iterations each for F and D is what SQLite's single-writer locking should guarantee, and the forced mode shows the mechanism directly. It is still an observation, not a proof.
- **SQLite only.** PostgreSQL and other databases were not tested; they would need a server. Under PostgreSQL's default READ COMMITTED isolation, neither a read inside a transaction (F) nor `INSERT ... SELECT` (D) takes a row lock. Without `FOR SHARE`/`FOR UPDATE`, SERIALIZABLE isolation, or a constraint, neither would be expected to stop a concurrent cancellation. That is expected from the documentation and was not measured here.
- One customer, one credit, one agent and one canceller; synthetic data; no LLM or model API involved. Elapsed times are not a benchmark.

## Reproduce

From the repository root with Python 3.13 (standard library only):

```sh
python -m unittest discover -s experiments/001-memory-reliability/part-2-stress-test -p 'test_*.py' -v
python experiments/001-memory-reliability/part-2-stress-test/experiment.py
```

The run takes about three minutes on the machine above. Options: `--iterations`, `--free-runs`, `--seed`, and `--output` (use another path to keep the saved run). The seed fixes the canceller delays but not thread scheduling, so free-running counts will not repeat exactly. [Test output](results/tests.txt) (13 tests) and [results](results/results.json) are actual saved runs.
