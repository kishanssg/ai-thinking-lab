# Methodology

Part 2 keeps Part 1's invented rule: credit `customer-42` to `credit-42` only if the customer has `approved=1`. It changes only how the approval cancellation arrives. In 001 the cancellation was a sequential statement on the same in-memory connection, injected before D's transaction, so `BEGIN IMMEDIATE` was never contended. Here it comes from a second connection in a second thread, against a file on disk.

## Database and connections

- A fresh temporary directory per run holds one SQLite file in WAL journal mode (`synchronous=NORMAL`, chosen for speed; it does not change isolation). Each iteration resets that file to one approved customer and no credits.
- The **agent** connection runs in the main thread. The **canceller** connection runs `UPDATE customers SET approved=0` in a new thread each iteration.
- Both connections use `timeout=0`, which turns off SQLite's built-in busy handler, so every `SQLITE_BUSY`/`SQLITE_LOCKED` reaches the harness. `retry()` counts each one, sleeps 0.2 ms, and tries again, up to 500 attempts. Giving up is recorded as `busy_gave_up`; it did not happen in the saved run.
- An `AFTER INSERT` trigger copies the customer's `approved` value into the new credit row. The trigger runs inside the inserting write transaction, and SQLite allows one writer at a time. So the recorded value is the committed approval when the row committed. **Invalid commit = a row whose recorded approval is 0.** This is instrumentation; no approach reads it.

## Approaches

Every approach first runs a decision-time precheck (a plain `SELECT`) and refuses if the customer is unapproved. Then it sleeps `think_s` = 1 ms to stand in for work between deciding and acting. Then:

| Approach | After the think time | Vulnerable point (`hook`) |
|---|---|---|
| C | unguarded `INSERT` (same as Part 1's C: act on the precheck) | before the insert |
| E | re-read approval, refuse if 0, else unguarded autocommit `INSERT`; no transaction around the pair | between re-read and insert |
| F | `BEGIN IMMEDIATE`, re-read, refuse if 0, else plain `INSERT`, `COMMIT` | inside the transaction, between re-read and insert |
| D | `BEGIN IMMEDIATE`, `INSERT ... SELECT ... WHERE approved=1`, `COMMIT` (Part 1's guard) | inside the transaction, before the insert |

E is the question from Part 1's open-questions section. F was added to separate two things D combines: the write transaction and the conditional insert. Part 1's code is not imported or changed; D is re-implemented here with the same SQL.

## Modes

**Forced.** The canceller thread waits for the agent to reach its `hook`. Then it tries the update once. The agent waits until that first try has returned, whether it committed or got `SQLITE_BUSY`, and records which. This places the cancellation at each approach's worst point every time. It shows what each approach does when the race lands there. It does not show how often that happens.

**Free-running.** The canceller sleeps for a delay drawn uniformly from 0–3 ms (seeded `random.Random`) and then updates. Nothing coordinates it with the agent. Where the cancellation lands depends on the OS scheduler, the GIL, and lock timing. These runs measure how often each approach commits an invalid row under this specific timing setup. Three free-running runs use seeds 1, 2 and 3. The seed fixes the delays but not the thread scheduling, so the counts differ between runs and between machines.

Approaches run round-robin (C, E, F, D, C, E, …) so changes in machine load fall on all four alike. Each run uses 3,000 iterations per approach.

## Counters

Each iteration ends in exactly one outcome: `refused_precheck`, `refused_reread` (E, F), `refused_guard` (D), `credited_valid`, `credited_invalid`, or `busy_gave_up`. Also recorded: total `agent_busy` and `canceller_busy` responses, `iterations_with_agent_busy`, `invalid_after_agent_busy` (invalid commits in iterations where the agent was told busy at least once), `hook_reached`, and, in forced mode, `cancellation_committed_at_hook`.

`invalid_commits` divides invalid rows by iterations. `invalid_among_commits` divides by committed rows. The iteration count, seed, configuration, machine, Python/SQLite versions, journal mode and GIL status are saved with the results.

## What this does not test

- **Only SQLite.** In SQLite there is one writer at a time, so a write transaction is a full serialization point. Both F and D depend on that. PostgreSQL's default READ COMMITTED isolation behaves differently. From its documentation (not tested here), a plain `SELECT` takes no row lock. The `SELECT` inside `INSERT ... SELECT` takes none either. So neither F's pattern nor D's conditional insert would stop a concurrent cancellation that commits after the read and before the insert commits. That would need `FOR SHARE`/`FOR UPDATE` on the customer row, SERIALIZABLE isolation, or a database constraint. PostgreSQL and other databases were not tested; they would need a server, and this experiment uses the standard library only.
- One customer, one credit, one canceller, one agent. No multi-row constraints, no deletes, no network.
- Not a benchmark. Elapsed times are recorded only so readers can see how long a run took.
- CPython with the GIL enabled. Thread handoffs depend on the 5 ms switch interval and on `sqlite3` releasing the GIL during statements. A free-threaded build, another OS, or another disk could change the free-running rates.
