"""Deterministic fictional assignment workflows; no model or network calls."""
import argparse
import json
import platform
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parent


def load_fixtures():
    return json.loads((ROOT / 'fixtures.json').read_text())


class Store:
    def __init__(self, state):
        self.db = sqlite3.connect(':memory:', isolation_level=None)
        self.db.executescript('''
            CREATE TABLE workers (id TEXT PRIMARY KEY, eligible INTEGER NOT NULL);
            CREATE TABLE assignments (shift TEXT PRIMARY KEY, worker TEXT NOT NULL);
        ''')
        if state is not None:
            self.db.execute('INSERT INTO workers VALUES (?, ?)', ('toy-worker', int(state)))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def state(self):
        row = self.db.execute('SELECT eligible FROM workers WHERE id=?', ('toy-worker',)).fetchone()
        return bool(row[0]) if row else None

    def verify(self, fails):
        if fails:
            raise OSError('synthetic lookup failure')
        return self.state() is True

    def change(self, state):
        if state is None:
            self.db.execute('DELETE FROM workers')
        else:
            self.db.execute('INSERT OR REPLACE INTO workers VALUES (?, ?)',
                            ('toy-worker', int(state)))

    def assignment_count(self):
        return self.db.execute('SELECT COUNT(*) FROM assignments').fetchone()[0]

    def commit(self, guarded):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.assignment_count():
                outcome = (False, 'already_assigned')
            elif guarded:
                cursor = self.db.execute('''
                    INSERT INTO assignments (shift, worker)
                    SELECT 'toy-shift', id FROM workers
                    WHERE id='toy-worker' AND eligible=1
                ''')
                outcome = (True, 'assigned') if cursor.rowcount == 1 else (
                    False, 'ineligible_or_missing')
            else:
                self.db.execute('INSERT INTO assignments VALUES (?, ?)',
                                ('toy-shift', 'toy-worker'))
                outcome = (True, 'assigned')
            self.db.execute('COMMIT')
            return outcome
        except Exception:
            self.db.execute('ROLLBACK')
            raise


def required_commit(store, verified_eligible, guarded):
    if not verified_eligible:
        return False, 'required_precheck_missing'
    return store.commit(guarded)


def run_case(fixture, approach):
    if approach not in 'ABCD' or len(approach) != 1:
        raise ValueError('unknown approach')
    start = perf_counter_ns()
    events = []
    with Store(fixture['initial']) as store:
        events.append({'kind': 'ground_truth', 'phase': 'initial', 'state': store.state(),
                       'memory': fixture['memory']})
        verified = False
        if approach == 'A':
            recommended = fixture['memory']
            reason = 'memory_only'
        else:
            # B voluntarily checks on every task; C/D require a successful precheck.
            try:
                verified = store.verify(fixture['lookup_fails'])
                reason = 'eligible' if verified else 'ineligible_or_missing'
            except OSError:
                reason = 'lookup_error'
            events.append({'kind': 'verification', 'eligible': verified, 'reason': reason})
            recommended = verified
        events.append({'kind': 'decision', 'recommended': recommended, 'reason': reason,
                       'ground_truth': store.state()})
        if fixture['initial'] != fixture['commit_state']:
            store.change(fixture['commit_state'])
            events.append({'kind': 'state_change', 'reason': 'injected_before_commit',
                           'state': store.state()})
        events.append({'kind': 'ground_truth', 'phase': 'commit', 'state': store.state()})
        committed = False
        if recommended:
            state = store.state()
            if approach in 'CD':
                committed, reason = required_commit(store, verified, approach == 'D')
            else:
                committed, reason = store.commit(False)
            events.append({'kind': 'commit_attempt', 'committed': committed,
                           'guarded': approach == 'D', 'reason': reason, 'ground_truth': state})
        else:
            events.append({'kind': 'refusal', 'reason': reason})
        events.append({'kind': 'final', 'assignment_count': store.assignment_count()})
    return {'scenario': fixture['id'], 'approach': approach, 'recommended': recommended,
            'committed': committed, 'latency_ns': perf_counter_ns() - start, 'events': events}


def ratio(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'rate': numerator / denominator if denominator else None}


def summarize(results):
    summary = {}
    for approach in 'ABCD':
        runs = [r for r in results if r['approach'] == approach]
        if not runs:
            continue
        wrong = invalid = valid = refused = verified = eligible_tasks = calls = attempts = 0
        recommendations = committed_total = 0
        for run in runs:
            events = run['events']
            decision = next(e for e in events if e['kind'] == 'decision')
            eligible = next(e['state'] is True for e in events
                            if e['kind'] == 'ground_truth' and e['phase'] == 'commit')
            checks = [e for e in events if e['kind'] == 'verification']
            writes = [e for e in events if e['kind'] == 'commit_attempt']
            committed = any(e['committed'] for e in writes)
            wrong += decision['recommended'] and decision['ground_truth'] is not True
            invalid += sum(e['committed'] and e['ground_truth'] is not True for e in writes)
            valid += committed and eligible
            refused += not decision['recommended'] and eligible
            eligible_tasks += eligible
            verified += bool(checks)
            calls += len(checks) + len(writes)
            attempts += len(writes)
            recommendations += decision['recommended']
            committed_total += committed
        summary[approach] = {
            'tasks': len(runs), 'recommendations': recommendations,
            'committed_assignments': committed_total, 'commit_attempts': attempts,
            'incorrect_affirmative_recommendations': ratio(wrong, len(runs)),
            'invalid_commits': ratio(invalid, len(runs)),
            'valid_task_completion': ratio(valid, eligible_tasks),
            'unnecessary_refusals': ratio(refused, eligible_tasks),
            'verification_rate': ratio(verified, len(runs)), 'tool_calls': calls,
            'latency_ns': {'min': min(r['latency_ns'] for r in runs),
                           'max': max(r['latency_ns'] for r in runs),
                           'mean': sum(r['latency_ns'] for r in runs) / len(runs)}}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'results' / 'results.json')
    args = parser.parse_args()
    runs = [run_case(f, a) for f in load_fixtures() for a in 'ABCD']
    report = {'experiment': '001', 'simulation': True,
              'environment': {'python': platform.python_version(), 'platform': platform.system(),
                              'machine': platform.machine(), 'sqlite': sqlite3.sqlite_version},
              'command': 'python3 ' + ' '.join(sys.argv),
              'generated_at_utc': datetime.now(timezone.utc).isoformat(),
              'runs': runs, 'summary': summarize(runs)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Saved {len(runs)} task traces to {args.output.relative_to(Path.cwd()) if args.output.is_relative_to(Path.cwd()) else args.output}')


if __name__ == '__main__':
    main()
