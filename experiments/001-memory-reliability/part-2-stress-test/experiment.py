"""Concurrent approval-cancellation harness for Experiment 001, part 2; standard library only.

Each iteration resets a file-backed SQLite database, then an agent connection (main
thread) runs one approach while a canceller connection (its own thread) sets the customer's
approval to 0. An AFTER INSERT trigger records the approval the inserting write
transaction saw, so an invalid row is one whose customer was unapproved when it committed.
"""
import argparse
import json
import os
import platform
import random
import sqlite3
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APPROACHES = ('C', 'E', 'F', 'D')
MODES = ('forced', 'free')
OUTCOMES = ('refused_precheck', 'refused_reread', 'refused_guard',
            'credited_valid', 'credited_invalid', 'busy_gave_up')

SCHEMA = '''
    CREATE TABLE IF NOT EXISTS customers (id TEXT PRIMARY KEY, approved INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS credits (
        credit_id TEXT PRIMARY KEY, customer TEXT NOT NULL, approved_at_insert INTEGER);
    CREATE TRIGGER IF NOT EXISTS audit_credit AFTER INSERT ON credits BEGIN
        UPDATE credits SET approved_at_insert =
            (SELECT approved FROM customers WHERE id = NEW.customer)
        WHERE credit_id = NEW.credit_id;
    END;
'''


class BusyGaveUp(Exception):
    pass


def is_busy(error):
    code = getattr(error, 'sqlite_errorcode', None)
    return code is not None and code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)


def retry(fn, stats, key, max_attempts, backoff_s):
    """Run fn, retrying on SQLITE_BUSY/LOCKED; count each busy response in stats[key]."""
    for _ in range(max_attempts):
        try:
            return fn()
        except sqlite3.OperationalError as error:
            if not is_busy(error):
                raise
            stats[key] += 1
            time.sleep(backoff_s)
    raise BusyGaveUp(key)


def connect(path):
    # timeout=0 disables SQLite's internal busy handler so every SQLITE_BUSY is visible
    # to retry() and counted. Autocommit mode: transactions are explicit.
    conn = sqlite3.connect(path, timeout=0, isolation_level=None, check_same_thread=False)
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


def create_database(path):
    conn = connect(path)
    journal = conn.execute('PRAGMA journal_mode=WAL').fetchone()[0]
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR REPLACE INTO customers VALUES ('customer-42', 1)")
    conn.close()
    return journal


def reset(conn):
    conn.execute('BEGIN IMMEDIATE')
    conn.execute('DELETE FROM credits')
    conn.execute("UPDATE customers SET approved=1 WHERE id='customer-42'")
    conn.execute('COMMIT')


def read_approved(conn):
    row = conn.execute("SELECT approved FROM customers WHERE id='customer-42'").fetchone()
    return bool(row and row[0])


def audit(conn):
    """Return (row_count, approved_at_insert) for the single credit_id."""
    rows = conn.execute('SELECT approved_at_insert FROM credits').fetchall()
    return len(rows), (rows[0][0] if rows else None)


def give_credit(conn, approach, hook, think_s, stats, max_attempts, backoff_s):
    """Run one approach. hook() marks the approach's vulnerable point (see methodology)."""
    def attempt(fn):
        return retry(fn, stats, 'agent_busy', max_attempts, backoff_s)

    def unguarded_insert():
        attempt(lambda: conn.execute(
            "INSERT INTO credits (credit_id, customer) VALUES ('credit-42', 'customer-42')"))

    def rollback():
        if conn.in_transaction:
            conn.execute('ROLLBACK')

    if not read_approved(conn):                 # decision-time precheck (C, E, F, D)
        return 'refused_precheck'
    time.sleep(think_s)                         # simulated work between decision and action
    if approach == 'C':                         # act on the precheck alone
        hook()
        unguarded_insert()
        return 'credited'
    if approach == 'E':                         # late re-read, no transaction around it
        if not read_approved(conn):
            return 'refused_reread'
        hook()
        unguarded_insert()
        return 'credited'
    if approach == 'F':                         # re-read and plain insert in one write txn
        attempt(lambda: conn.execute('BEGIN IMMEDIATE'))
        try:
            if not read_approved(conn):
                conn.execute('ROLLBACK')
                return 'refused_reread'
            hook()
            conn.execute("INSERT INTO credits (credit_id, customer) VALUES ('credit-42', 'customer-42')")
            conn.execute('COMMIT')
            return 'credited'
        except BaseException:
            rollback()
            raise
    if approach == 'D':                         # part 1's guard: conditional insert in a write txn
        attempt(lambda: conn.execute('BEGIN IMMEDIATE'))
        try:
            hook()
            cursor = conn.execute('''
                INSERT INTO credits (credit_id, customer)
                SELECT 'credit-42', id FROM customers WHERE id='customer-42' AND approved=1
            ''')
            conn.execute('COMMIT')
            return 'credited' if cursor.rowcount == 1 else 'refused_guard'
        except BaseException:
            rollback()
            raise
    raise ValueError(f'unknown approach {approach!r}')


class Canceller(threading.Thread):
    """Sets approved=0 on its own connection, after a delay (free) or at the hook (forced)."""

    def __init__(self, conn, stats, max_attempts, backoff_s, delay_s=None, wait_s=5.0):
        super().__init__(daemon=True)
        self.conn, self.stats = conn, stats
        self.max_attempts, self.backoff_s = max_attempts, backoff_s
        self.delay_s, self.wait_s = delay_s, wait_s
        self.gap_open = threading.Event()       # forced mode: agent reached its hook
        self.attempted = threading.Event()      # first UPDATE attempt returned (ok or busy)
        self.committed = threading.Event()
        self.error = None

    def run(self):
        try:
            if self.delay_s is None:
                self.gap_open.wait(self.wait_s)
            else:
                time.sleep(self.delay_s)
            first = [True]

            def update():
                try:
                    self.conn.execute("UPDATE customers SET approved=0 WHERE id='customer-42'")
                finally:
                    if first[0]:
                        first[0] = False
                        self.attempted.set()

            retry(update, self.stats, 'canceller_busy', self.max_attempts, self.backoff_s)
            self.committed.set()
        except BusyGaveUp:
            self.stats['canceller_gave_up'] += 1
        except BaseException as error:  # surfaced by run_iteration
            self.error = error
        finally:
            self.attempted.set()


def new_stats():
    stats = {k: 0 for k in OUTCOMES}
    stats.update(agent_busy=0, canceller_busy=0, canceller_gave_up=0,
                 cancellation_committed_at_hook=0, hook_reached=0, iterations=0,
                 iterations_with_agent_busy=0, invalid_after_agent_busy=0)
    return stats


def run_iteration(agent, canceller_conn, approach, mode, stats, rng, config):
    reset(agent)
    max_attempts, backoff_s = config['max_attempts'], config['busy_backoff_s']
    delay = rng.uniform(0, config['cancel_window_s']) if mode == 'free' else None
    canceller = Canceller(canceller_conn, stats, max_attempts, backoff_s, delay_s=delay)

    def hook():
        stats['hook_reached'] += 1
        if mode == 'forced':
            canceller.gap_open.set()
            canceller.attempted.wait(config['hook_wait_s'])
            stats['cancellation_committed_at_hook'] += canceller.committed.is_set()

    busy_before = stats['agent_busy']
    canceller.start()
    try:
        outcome = give_credit(agent, approach, hook, config['think_s'], stats,
                         max_attempts, backoff_s)
    except BusyGaveUp:
        outcome = 'busy_gave_up'
    finally:
        canceller.gap_open.set()
        canceller.join(30)
    if canceller.is_alive():
        raise RuntimeError('canceller thread did not finish')
    if canceller.error:
        raise canceller.error
    rows, approved_at_insert = audit(agent)
    if outcome == 'credited':
        if rows != 1:
            raise AssertionError('credited without exactly one row')
        outcome = 'credited_valid' if approved_at_insert == 1 else 'credited_invalid'
    elif rows:
        raise AssertionError(f'{outcome} left a row behind')
    stats[outcome] += 1
    stats['iterations'] += 1
    if stats['agent_busy'] > busy_before:
        stats['iterations_with_agent_busy'] += 1
        stats['invalid_after_agent_busy'] += outcome == 'credited_invalid'
    return outcome


def ratio(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'rate': numerator / denominator if denominator else None}


def summarize(stats):
    out = dict(stats)
    out['invalid_commits'] = ratio(stats['credited_invalid'], stats['iterations'])
    committed = stats['credited_valid'] + stats['credited_invalid']
    out['invalid_among_commits'] = ratio(stats['credited_invalid'], committed)
    return out


def run_mode(db_path, mode, iterations, seed, config, approaches=APPROACHES):
    """Interleave approaches round-robin so drift in machine load affects all equally."""
    rng = random.Random(seed)
    stats = {a: new_stats() for a in approaches}
    agent, canceller_conn = connect(db_path), connect(db_path)
    started = time.perf_counter()
    try:
        for _ in range(iterations):
            for approach in approaches:
                run_iteration(agent, canceller_conn, approach, mode, stats[approach], rng, config)
    finally:
        agent.close()
        canceller_conn.close()
    return {'mode': mode, 'seed': seed, 'iterations_per_approach': iterations,
            'elapsed_s': round(time.perf_counter() - started, 3),
            'approaches': {a: summarize(s) for a, s in stats.items()}}


DEFAULT_CONFIG = {'think_s': 0.001, 'cancel_window_s': 0.003, 'hook_wait_s': 2.0,
                  'busy_backoff_s': 0.0002, 'max_attempts': 500}


def environment(journal_mode):
    gil = getattr(sys, '_is_gil_enabled', None)
    return {'python': platform.python_version(), 'implementation': platform.python_implementation(),
            'platform': platform.system(), 'release': platform.release(),
            'version': platform.version(), 'machine': platform.machine(),
            'processor': platform.processor(), 'cpu_count': os.cpu_count(),
            'sqlite': sqlite3.sqlite_version, 'journal_mode': journal_mode,
            'synchronous': 'NORMAL', 'gil_enabled': gil() if gil else True,
            'switch_interval_s': sys.getswitchinterval()}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--iterations', type=int, default=3000, help='per approach per run')
    parser.add_argument('--free-runs', type=int, default=3,
                        help='independent free-running repeats (each with its own seed)')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--output', type=Path, default=ROOT / 'results' / 'results.json')
    args = parser.parse_args()
    config = dict(DEFAULT_CONFIG)
    with tempfile.TemporaryDirectory(prefix='exp001-part2-') as tmp:
        db_path = str(Path(tmp) / 'credits.db')
        journal = create_database(db_path)
        runs = [run_mode(db_path, 'forced', args.iterations, args.seed, config)]
        for i in range(args.free_runs):
            runs.append(run_mode(db_path, 'free', args.iterations, args.seed + i, config))
    report = {'experiment': '001-part-2', 'simulation': True, 'environment': environment(journal),
              'command': 'python ' + ' '.join(sys.argv),
              'generated_at_utc': datetime.now(timezone.utc).isoformat(),
              'config': config, 'approaches': {
                  'C': 'precheck, think, unguarded insert',
                  'E': 'precheck, think, re-read, unguarded autocommit insert',
                  'F': 'precheck, think, BEGIN IMMEDIATE, re-read, plain insert, COMMIT',
                  'D': 'precheck, think, BEGIN IMMEDIATE, INSERT...SELECT WHERE approved=1, COMMIT'},
              'runs': runs}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    for run in runs:
        cells = ', '.join(f"{a} {s['credited_invalid']}/{s['iterations']}"
                          for a, s in run['approaches'].items())
        print(f"{run['mode']:6} seed={run['seed']} invalid commits: {cells} ({run['elapsed_s']}s)")
    print(f'Saved to {args.output}')


if __name__ == '__main__':
    main()
