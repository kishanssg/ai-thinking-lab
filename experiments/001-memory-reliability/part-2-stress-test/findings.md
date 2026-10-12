# Observed findings

Source: the saved [`results/results.json`](results/results.json) run, generated 2026-10-12 00:46 UTC with `python experiments/001-memory-reliability/part-2-stress-test/experiment.py`. Machine: Windows 11 (10.0.26200), Intel64 Family 6 Model 142 Stepping 12, GenuineIntel, 8 logical CPUs; CPython 3.13.3 with the GIL, SQLite 3.49.1, WAL, `synchronous=NORMAL`. 3,000 iterations per approach per run, one forced run and 3 free-running runs: 48,000 iterations in total.

These numbers come from a re-run after the code was renamed to the store-credit wording. An earlier run of the same logic (before renaming) gave the same pattern with slightly different counts (E: 1,472 of 9,000), as expected for a timing-dependent test.

## Forced: cancellation placed at each approach's vulnerable point

| Approach | Invalid commits | Valid commits | Canceller `SQLITE_BUSY` responses | Cancellation already committed when the agent resumed |
|---|---:|---:|---:|---:|
| C | 3000/3000 | 0 | 0 | 3000/3000 |
| E | 3000/3000 | 0 | 0 | 3000/3000 |
| F | 0/3000 | 3000 | 3073 | 0/3000 |
| D | 0/3000 | 3000 | 3121 | 0/3000 |

When the cancellation commits between E's re-read and its insert, E writes an invalid row every time, just like C. For F and D the canceller cannot get in at that point. Its update gets `SQLITE_BUSY` because the agent holds the write lock, so it waits and commits afterward. The credit was valid when it committed. This is the contention that Part 1 never exercised.

## Free-running: cancellation after a random 0–3 ms delay, no coordination

Invalid commits / iterations:

| Run (seed) | C | E | F | D |
|---|---:|---:|---:|---:|
| 1 | 892/3000 (29.7%) | 523/3000 (17.4%) | 0/3000 | 0/3000 |
| 2 | 868/3000 (28.9%) | 537/3000 (17.9%) | 0/3000 | 0/3000 |
| 3 | 857/3000 (28.6%) | 551/3000 (18.4%) | 0/3000 | 0/3000 |
| Total | 2617/9000 (29.1%) | 1611/9000 (17.9%) | 0/9000 | 0/9000 |

Other outcomes over the 3 runs: E refused at its re-read 2,391 times; F refused at its re-read 2,560 times; D's guard refused 2,549 times; precheck refusals were 5 in total (C 3, F 1, D 1). No iteration gave up on `SQLITE_BUSY`. E's count changed by up to 28 between runs with otherwise identical settings. These rates depend on timing and will differ on another machine or run.

### Why E failed far more often than its "gap" suggests

| Run | E invalid | …in iterations where E's insert first got `SQLITE_BUSY` | …with no busy response |
|---|---:|---:|---:|
| 1 | 523 | 514 | 9 |
| 2 | 537 | 530 | 7 |
| 3 | 551 | 537 | 14 |

98% of E's invalid commits (1,581 of 1,611) happened in iterations where its insert was first told `SQLITE_BUSY`. Every E iteration that hit busy ended invalid (514/514, 530/530, 537/537 iterations). The mechanism, reproduced step by step in `test_in_flight_cancellation_is_invisible_to_a_late_reread`:

1. The canceller's `UPDATE` has started and holds SQLite's write lock but has not committed.
2. E re-reads. Under WAL, readers see the last committed value, so E still sees `approved=1`.
3. E's insert gets `SQLITE_BUSY` and backs off. The cancellation commits. E's retried insert succeeds, and the new row records `approved=0`.

So E's real exposure window is not two adjacent statements. It also covers any write already in progress when it reads, plus the time spent waiting for that write's lock. The rest (30 of 1,611) were classic interleavings with no busy response: the cancellation committed in the instant between E's re-read returning and its insert taking the lock.

For C, every iteration with an agent busy response also ended invalid (92/92, 83/83, 73/73), by the same mechanism. Most of C's invalid commits, though, came from the 1 ms think time with no contention. F and D also got busy responses (57–82 iterations per run). None of those iterations ended invalid. Because their check runs only after `BEGIN IMMEDIATE` gets the lock, a cancellation that was in flight has already committed by the time they check.

## Answer to Part 1's open question

Under real two-connection contention in SQLite, **a late re-read (E) did not work as well as the guarded write (D)**. E cut invalid commits from about 29% (C) to about 18% in this setup, but did not remove them. D had zero in 12,000 iterations. F, a plain re-read inside `BEGIN IMMEDIATE`, also had zero in 12,000 iterations. **In SQLite, the protection comes from doing the check and the write inside one write transaction. The `INSERT ... SELECT` form is not what matters.** D's conditional insert is one convenient way to get that; F is another.

Zero observed invalid commits for F and D in 12,000 iterations each is consistent with what SQLite's single-writer locking should guarantee. It is not a proof. In this harness, the forced mode is the stronger evidence for F and D: there, every cancellation aimed at their vulnerable point was blocked. The observation applies to SQLite only. Under PostgreSQL's default isolation, neither F's nor D's SQL would be expected to give the same protection without row locks or SERIALIZABLE isolation (see [methodology](methodology.md#what-this-does-not-test)). That was not tested.

All 13 unit tests passed ([output](results/tests.txt)).
