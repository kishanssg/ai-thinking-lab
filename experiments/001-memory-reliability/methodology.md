# Methodology

Every task asks to credit `customer-42` to `credit-42`. The invented business rule is that the customer must exist and have `approved=1`. One credit per credit is allowed. Memory contains a Boolean from an earlier observation. Authoritative state is the SQLite customers table. Each of the 24 runs starts with an independent empty credit table.

## Policies and enforcement

- A trusts memory and uses an unguarded credit operation.
- B voluntarily checks on every task under this predetermined policy; it refuses on lookup error or when the credit is not approved. Its write operation does not require proof of a check.
- C has the same policy, but the application commit wrapper rejects calls without a positive precheck. That precheck result can become stale.
- D uses the C precheck and a conditional `INSERT ... SELECT ... WHERE approved=1` inside `BEGIN IMMEDIATE`. The write transaction prevents an interleaved SQLite writer between validation and insertion. Missing and unapproved customers produce no row. Exceptions roll back; duplicate credits are rejected.

The C/D wrapper is an internal simulation boundary, not an unforgeable authorization token or a production access-control system. D's database condition enforces approval even when called directly. The unguarded operation intentionally lacks a customer foreign key, making missing-customer baseline failures observable.

The race fixture injects a committed approval cancellation after the decision and before the credit transaction, with no sleeps. It runs for every approach. No threaded concurrency is claimed. Lookup failure is a synthetic failure of the precheck interface while underlying ground truth remains available to the evaluator. D fails closed at that interface and does not attempt a direct write in that case.

## Event-derived metrics

Each trace records initial memory and authoritative state, verification calls and reasons, the recommendation and decision-time ground truth, any injected change, commit-time ground truth, commit attempt and reason, and final stored row count. Evaluator state reads and injected updates are instrumentation, not policy tool calls.

The summary reads these events, not the convenience outcome fields or expected labels:

- Incorrect affirmative recommendations: affirmative recommendations when decision-time state is not true, divided by all six tasks. This is not an all-decision error rate. The JSON key is `incorrect_affirmative_recommendations`. A refusal is measured separately.
- Invalid commits: successful writes when commit-time state is not true, divided by all six tasks. These are task incidence rates, not conditional error rates among writes.
- Valid-task completion: successful writes on approved commit-time tasks divided by the three approved commit-time tasks (unchanged, stale false, lookup failure).
- Unnecessary refusals: negative recommendations on those approved tasks divided by three. The JSON key remains `unnecessary_refusals`. This measures lost opportunity against commit-time approval even when failing closed is justified operationally; it is not a decision-time false-negative rate. The two metrics have different denominators and must not be added.
- Verification rate: tasks with a precheck attempt, including failed lookups, divided by six. The atomic predicate is part of the commit call, not an additional precheck call.
- Tool calls: precheck attempts plus commit attempts. Internal SQL statements are not separate tool calls. Total recommendations, commit attempts, and successful writes are also supplied.
- Latency: `perf_counter_ns` elapsed per task including database setup, instrumentation, and teardown; minimum, maximum, and arithmetic mean. No speedup or performance conclusion is inferred.

The race recommendation is correct when made, even though an unguarded later write is invalid. This temporal distinction explains why recommendation and commit errors differ. Logical results are repeatable; machine metadata, timestamps, and timings are not byte-for-byte deterministic. There is no sampling, statistical significance test, or model-generated ground truth.
