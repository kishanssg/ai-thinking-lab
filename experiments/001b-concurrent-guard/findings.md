# Observed findings

Source: the saved [`results/results.json`](results/results.json) run, generated 2026-10-11 23:27 UTC with `python experiments/001b-concurrent-guard/experiment.py`. Machine: Windows 11 (10.0.26200), Intel Core i7-10510U (4 cores / 8 threads, 1.8 GHz), 16 GB RAM, Intel Optane + 477 GB SSD; CPython 3.13.3 with the GIL, SQLite 3.49.1, WAL, `synchronous=NORMAL`. 3,000 iterations per approach per run, one forced run and three free-running runs: 48,000 iterations in total.

## Forced: revocation placed at each approach's vulnerable point

| Approach | Invalid commits | Valid commits | Revoker `SQLITE_BUSY` responses | Revocation already committed when the assigner resumed |
|---|---:|---:|---:|---:|
| C | 3000/3000 | 0 | 0 | 3000/3000 |
| E | 3000/3000 | 0 | 0 | 3000/3000 |
| F | 0/3000 | 3000 | 3040 | 0/3000 |
| D | 0/3000 | 3000 | 3041 | 0/3000 |

When the revocation commits between E's re-read and its insert, E writes an invalid row every time, just like C. For F and D the revoker cannot get in at that point. Its update gets `SQLITE_BUSY` because the assigner holds the write lock, so it waits and commits afterward. The assignment was valid when it committed. This is the contention that 001 never exercised.

## Free-running: revocation after a random 0–3 ms delay, no coordination

Invalid commits / iterations:

| Run (seed) | C | E | F | D |
|---|---:|---:|---:|---:|
| 1 | 816/3000 (27.2%) | 527/3000 (17.6%) | 0/3000 | 0/3000 |
| 2 | 808/3000 (26.9%) | 451/3000 (15.0%) | 0/3000 | 0/3000 |
| 3 | 836/3000 (27.9%) | 494/3000 (16.5%) | 0/3000 | 0/3000 |
| Total | 2460/9000 (27.3%) | 1472/9000 (16.4%) | 0/9000 | 0/9000 |

Other outcomes over the three runs: E refused at its re-read 2,077 times; F refused at its re-read 2,482 times; D's guard refused 2,363 times; precheck refusals were 1 in total (F, run 2). No iteration gave up on `SQLITE_BUSY`. E's count changed by up to 76 between runs with otherwise identical settings. These rates depend on timing and will differ on another machine or run.

### Why E failed far more often than its "gap" suggests

| Run | E invalid | …in iterations where E's insert first got `SQLITE_BUSY` | …with no busy response |
|---|---:|---:|---:|
| 1 | 527 | 483 | 44 |
| 2 | 451 | 413 | 38 |
| 3 | 494 | 445 | 49 |

91% of E's invalid commits (1,341 of 1,472) happened in iterations where its insert was first told `SQLITE_BUSY`. Every E iteration that hit busy ended invalid (483/483, 413/413, 445/445 iterations). The mechanism, reproduced step by step in `test_in_flight_revocation_is_invisible_to_a_late_reread`:

1. The revoker's `UPDATE` has started and holds SQLite's write lock but has not committed.
2. E re-reads. Under WAL, readers see the last committed value, so E still sees `eligible=1`.
3. E's insert gets `SQLITE_BUSY` and backs off. The revocation commits. E's retried insert succeeds, and the new row records `eligible=0`.

So E's real exposure window is not two adjacent statements. It also covers any write already in progress when it reads, plus the time spent waiting for that write's lock. The other ~10% (131 of 1,472) were classic interleavings with no busy response. The revocation committed in the instant between E's re-read returning and its insert taking the lock.

For C, every iteration with an assigner busy response also ended invalid (137/137, 122/122, 134/134), by the same mechanism. Most of C's invalid commits, though, came from the 1 ms think time with no contention. F and D also got busy responses (102�151 iterations per run). None of those iterations ended invalid. Because their check runs only after `BEGIN IMMEDIATE` gets the lock, a revocation that was in flight has already committed by the time they check. The harness does not record whether each of those iterations then refused or committed validly.

## Answer to 001's open question

Under real two-connection contention in SQLite, **a late re-read (E) did not work as well as the guarded write (D)**. E cut invalid commits from about 27% (C) to about 16% in this setup, but did not remove them. D had zero in 12,000 iterations. F, a plain re-read inside `BEGIN IMMEDIATE`, also had zero in 12,000 iterations. **In SQLite, the protection comes from doing the check and the write inside one write transaction. The `INSERT ... SELECT` form is not what matters.** D's conditional insert is one convenient way to get that; F is another.

Zero observed invalid commits for F and D in 12,000 iterations each is consistent with what SQLite's single-writer locking should guarantee. It is not a proof. In this harness, the forced mode is the stronger evidence for F and D: there, every revocation aimed at their vulnerable point was blocked. The observation applies to SQLite only. Under PostgreSQL's default isolation, neither F's nor D's SQL would be expected to give the same protection without row locks or SERIALIZABLE isolation (see [methodology](methodology.md#what-this-does-not-test)). That was not tested.

All 13 unit tests passed ([output](results/tests.txt)).
