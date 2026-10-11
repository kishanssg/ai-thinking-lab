"""Concurrent eligibility-revocation harness for Experiment 001b; standard library only.

Each iteration resets a file-backed SQLite database, then an assigner connection (main
thread) runs one approach while a revoker connection (its own thread) sets the worker's
eligibility to 0. An AFTER INSERT trigger records the eligibility the inserting write
transaction saw, so an invalid row is one whose worker was ineligible when it committed.
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
            'assigned_valid', 'assigned_invalid', 'busy_gave_up')

SCHEMA = '''
    CREATE TABLE IF NOT EXISTS workers (id TEXT PRIMARY KEY, eligible INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS assignments (
        shift TEXT PRIMARY KEY, worker TEXT NOT NULL, eligible_at_insert INTEGER);
    CREATE TRIGGER IF NOT EXISTS audit_assignment AFTER INSERT ON assignments BEGIN
        UPDATE assignments SET eligible_at_insert =
            (SELECT eligible FROM workers WHERE id = NEW.worker)
        WHERE shift = NEW.shift;
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
    conn.execute("INSERT OR REPLACE INTO workers VALUES ('toy-worker', 1)")
    conn.close()
    return journal


def reset(conn):
    conn.execute('BEGIN IMMEDIATE')
    conn.execute('DELETE FROM assignments')
    conn.execute("UPDATE workers SET eligible=1 WHERE id='toy-worker'")
    conn.execute('COMMIT')


def read_eligible(conn):
    row = conn.execute("SELECT eligible FROM workers WHERE id='toy-worker'").fetchone()
    return bool(row and row[0])


def audit(conn):
    """Return (row_count, eligible_at_insert) for the single shift."""
    rows = conn.execute('SELECT eligible_at_insert FROM assignments').fetchall()
    return len(rows), (rows[0][0] if rows else None)


def assign(conn, approach, hook, think_s, stats, max_attempts, backoff_s):
    """Run one approach. hook() marks the approach's vulnerable point (see methodology)."""
    def attempt(fn):
        return retry(fn, stats, 'assigner_busy', max_attempts, backoff_s)

    def unguarded_insert():
        attempt(lambda: conn.execute(
            "INSERT INTO assignments (shift, worker) VALUES ('toy-shift', 'toy-worker')"))

    def rollback():
        if conn.in_transaction:
            conn.execute('ROLLBACK')

    if not read_eligible(conn):                 # decision-time precheck (C, E, F, D)
        return 'refused_precheck'
    time.sleep(think_s)                         # simulated work between decision and action
    if approach == 'C':                         # act on the precheck alone
        hook()
        unguarded_insert()
        return 'assigned'
    if approach == 'E':                         # late re-read, no transaction around it
        if not read_eligible(conn):
            return 'refused_reread'
        hook()
        unguarded_insert()
        return 'assigned'
    if approach == 'F':                         # re-read and plain insert in one write txn
        attempt(lambda: conn.execute('BEGIN IMMEDIATE'))
        try:
            if not read_eligible(conn):
                conn.execute('ROLLBACK')
                return 'refused_reread'
            hook()
            conn.execute("INSERT INTO assignments (shift, worker) VALUES ('toy-shift', 'toy-worker')")
            conn.execute('COMMIT')
            return 'assigned'
        except BaseException:
            rollback()
            raise
    if approach == 'D':                         # 001's guard: conditional insert in a write txn
        attempt(lambda: conn.execute('BEGIN IMMEDIATE'))
        try:
            hook()
            cursor = conn.execute('''
                INSERT INTO assignments (shift, worker)
                SELECT 'toy-shift', id FROM workers WHERE id='toy-worker' AND eligible=1
            ''')
            conn.execute('COMMIT')
            return 'assigned' if cursor.rowcount == 1 else 'refused_guard'
        except BaseException:
            rollback()
            raise
    raise ValueError(f'unknown approach {approach!r}')


class Revoker(threading.Thread):
    """Sets eligible=0 on its own connection, after a delay (free) or at the hook (forced)."""

    def __init__(self, conn, stats, max_attempts, backoff_s, delay_s=None, wait_s=5.0):
        super().__init__(daemon=True)
        self.conn, self.stats = conn, stats
        self.max_attempts, self.backoff_s = max_attempts, backoff_s
        self.delay_s, self.wait_s = delay_s, wait_s
        self.gap_open = threading.Event()       # forced mode: assigner reached its hook
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
                    self.conn.execute("UPDATE workers SET eligible=0 WHERE id='toy-worker'")
                finally:
                    if first[0]:
                        first[0] = False
                        self.attempted.set()

            retry(update, self.stats, 'revoker_busy', self.max_attempts, self.backoff_s)
            self.committed.set()
        except BusyGaveUp:
            self.stats['revoker_gave_up'] += 1
        except BaseException as error:  # surfaced by run_iteration
            self.error = error
        finally:
            self.attempted.set()


def new_stats():
    stats = {k: 0 for k in OUTCOMES}
    stats.update(assigner_busy=0, revoker_busy=0, revoker_gave_up=0,
                 revocation_committed_at_hook=0, hook_reached=0, iterations=0,
                 iterations_with_assigner_busy=0, invalid_after_assigner_busy=0)
    return stats


def run_iteration(assigner, revoker_conn, approach, mode, stats, rng, config):
    reset(assigner)
    max_attempts, backoff_s = config['max_attempts'], config['busy_backoff_s']
    delay = rng.uniform(0, config['revoke_window_s']) if mode == 'free' else None
    revoker = Revoker(revoker_conn, stats, max_attempts, backoff_s, delay_s=delay)

    def hook():
        stats['hook_reached'] += 1
        if mode == 'forced':
            revoker.gap_open.set()
            revoker.attempted.wait(config['hook_wait_s'])
            stats['revocation_committed_at_hook'] += revoker.committed.is_set()

    busy_before = stats['assigner_busy']
    revoker.start()
    try:
        outcome = assign(assigner, approach, hook, config['think_s'], stats,
                         max_attempts, backoff_s)
    except BusyGaveUp:
        outcome = 'busy_gave_up'
    finally:
        revoker.gap_open.set()
        revoker.join(30)
    if revoker.is_alive():
        raise RuntimeError('revoker thread did not finish')
    if revoker.error:
        raise revoker.error
    rows, eligible_at_insert = audit(assigner)
    if outcome == 'assigned':
        if rows != 1:
            raise AssertionError('assigned without exactly one row')
        outcome = 'assigned_valid' if eligible_at_insert == 1 else 'assigned_invalid'
    elif rows:
        raise AssertionError(f'{outcome} left a row behind')
    stats[outcome] += 1
    stats['iterations'] += 1
    if stats['assigner_busy'] > busy_before:
        stats['iterations_with_assigner_busy'] += 1
        stats['invalid_after_assigner_busy'] += outcome == 'assigned_invalid'
    return outcome


def ratio(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'rate': numerator / denominator if denominator else None}


def summarize(stats):
    out = dict(stats)
    out['invalid_commits'] = ratio(stats['assigned_invalid'], stats['iterations'])
    committed = stats['assigned_valid'] + stats['assigned_invalid']
    out['invalid_among_commits'] = ratio(stats['assigned_invalid'], committed)
    return out


def run_mode(db_path, mode, iterations, seed, config, approaches=APPROACHES):
    """Interleave approaches round-robin so drift in machine load affects all equally."""
    rng = random.Random(seed)
    stats = {a: new_stats() for a in approaches}
    assigner, revoker_conn = connect(db_path), connect(db_path)
    started = time.perf_counter()
    try:
        for _ in range(iterations):
            for approach in approaches:
                run_iteration(assigner, revoker_conn, approach, mode, stats[approach], rng, config)
    finally:
        assigner.close()
        revoker_conn.close()
    return {'mode': mode, 'seed': seed, 'iterations_per_approach': iterations,
            'elapsed_s': round(time.perf_counter() - started, 3),
            'approaches': {a: summarize(s) for a, s in stats.items()}}


DEFAULT_CONFIG = {'think_s': 0.001, 'revoke_window_s': 0.003, 'hook_wait_s': 2.0,
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
    with tempfile.TemporaryDirectory(prefix='exp001b-') as tmp:
        db_path = str(Path(tmp) / 'assignments.db')
        journal = create_database(db_path)
        runs = [run_mode(db_path, 'forced', args.iterations, args.seed, config)]
        for i in range(args.free_runs):
            runs.append(run_mode(db_path, 'free', args.iterations, args.seed + i, config))
    report = {'experiment': '001b', 'simulation': True, 'environment': environment(journal),
              'command': 'python ' + ' '.join(sys.argv),
              'generated_at_utc': datetime.now(timezone.utc).isoformat(),
              'config': config, 'approaches': {
                  'C': 'precheck, think, unguarded insert',
                  'E': 'precheck, think, re-read, unguarded autocommit insert',
                  'F': 'precheck, think, BEGIN IMMEDIATE, re-read, plain insert, COMMIT',
                  'D': 'precheck, think, BEGIN IMMEDIATE, INSERT...SELECT WHERE eligible=1, COMMIT'},
              'runs': runs}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    for run in runs:
        cells = ', '.join(f"{a} {s['assigned_invalid']}/{s['iterations']}"
                          for a, s in run['approaches'].items())
        print(f"{run['mode']:6} seed={run['seed']} invalid commits: {cells} ({run['elapsed_s']}s)")
    print(f'Saved to {args.output}')


if __name__ == '__main__':
    main()
