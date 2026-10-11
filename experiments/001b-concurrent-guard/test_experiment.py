import random
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock
from pathlib import Path

from experiment import (APPROACHES, DEFAULT_CONFIG, BusyGaveUp, assign, audit, connect,
                        create_database, new_stats, read_eligible, reset, retry, run_iteration,
                        run_mode, summarize)

FAST = dict(DEFAULT_CONFIG, think_s=0.0005, revoke_window_s=0.0015)


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'test.db')
        self.journal = create_database(self.path)
        self.conn = connect(self.path)
        self.other = connect(self.path)

    def tearDown(self):
        self.conn.close()
        self.other.close()
        self.tmp.cleanup()

    def run_approach(self, approach, hook=lambda: None):
        stats = new_stats()
        outcome = assign(self.conn, approach, hook, 0, stats, 10, 0.0001)
        return outcome, stats

    def revoke_from_other_connection(self):
        self.other.execute("UPDATE workers SET eligible=0 WHERE id='toy-worker'")

    def test_database_is_file_backed_wal(self):
        self.assertEqual(self.journal, 'wal')
        self.assertTrue(Path(self.path).exists())

    def test_audit_trigger_records_eligibility_seen_by_insert(self):
        self.revoke_from_other_connection()
        self.conn.execute("INSERT INTO assignments (shift, worker) VALUES ('toy-shift', 'toy-worker')")
        self.assertEqual(audit(self.conn), (1, 0))
        reset(self.conn)
        self.assertEqual(audit(self.conn), (0, None))
        self.assertTrue(read_eligible(self.conn))

    def test_all_approaches_assign_when_nothing_changes(self):
        for approach in APPROACHES:
            with self.subTest(approach=approach):
                reset(self.conn)
                self.assertEqual(self.run_approach(approach)[0], 'assigned')
                self.assertEqual(audit(self.conn), (1, 1))

    def test_all_approaches_refuse_when_already_revoked(self):
        for approach in APPROACHES:
            with self.subTest(approach=approach):
                reset(self.conn)
                self.revoke_from_other_connection()
                self.assertEqual(self.run_approach(approach)[0], 'refused_precheck')
                self.assertEqual(audit(self.conn), (0, None))

    def test_revocation_at_hook_sequentially(self):
        # Sequential version of the vulnerable point: C and E write an invalid row; F and D
        # cannot be revoked at their hook because they already hold the write lock.
        expected = {'C': ('assigned', 0), 'E': ('assigned', 0)}
        for approach in ('C', 'E'):
            with self.subTest(approach=approach):
                reset(self.conn)
                outcome, _ = self.run_approach(approach, self.revoke_from_other_connection)
                self.assertEqual((outcome, audit(self.conn)[1]), expected[approach])
        for approach in ('F', 'D'):
            with self.subTest(approach=approach):
                reset(self.conn)
                busy = []

                def hook():
                    try:
                        self.revoke_from_other_connection()
                    except sqlite3.OperationalError as error:
                        busy.append(error)

                outcome, _ = self.run_approach(approach, hook)
                self.assertEqual(outcome, 'assigned')
                self.assertEqual(len(busy), 1)
                self.assertEqual(audit(self.conn), (1, 1))

    def test_guard_and_reread_refuse_revocation_before_their_check(self):
        for approach, refusal in (('E', 'refused_reread'), ('F', 'refused_reread'),
                                  ('D', 'refused_guard')):
            with self.subTest(approach=approach):
                reset(self.conn)
                # Revoke during the think time: after the precheck, before the approach acts.
                with mock.patch('experiment.time.sleep',
                                side_effect=lambda _: self.revoke_from_other_connection()):
                    outcome = assign(self.conn, approach, lambda: None, 0, new_stats(), 10, 0.0001)
                self.assertEqual(outcome, refusal)
                self.assertEqual(audit(self.conn), (0, None))

    def test_in_flight_revocation_is_invisible_to_a_late_reread(self):
        # The revoker opens its write transaction during the think time and commits while
        # the assigner backs off from SQLITE_BUSY. Under WAL, E's re-read sees the last
        # committed value (eligible), so its retried insert lands after the revocation.
        expected = {'C': 'assigned_invalid', 'E': 'assigned_invalid',
                    'F': 'refused_reread', 'D': 'refused_guard'}
        for approach, want in expected.items():
            with self.subTest(approach=approach):
                reset(self.conn)
                steps = iter([
                    lambda: (self.other.execute('BEGIN IMMEDIATE'),
                             self.other.execute("UPDATE workers SET eligible=0")),
                    lambda: self.other.execute('COMMIT')])
                stats = new_stats()
                with mock.patch('experiment.time.sleep',
                                side_effect=lambda _: next(steps, lambda: None)()):
                    outcome = assign(self.conn, approach, lambda: None, 0, stats, 10, 0)
                if outcome == 'assigned':
                    outcome = 'assigned_valid' if audit(self.conn)[1] == 1 else 'assigned_invalid'
                self.assertEqual(outcome, want)
                self.assertEqual(stats['assigner_busy'], 1)

    def test_retry_counts_busy_and_gives_up(self):
        self.other.execute('BEGIN IMMEDIATE')
        stats = {'busy': 0}
        with self.assertRaises(BusyGaveUp):
            retry(lambda: self.conn.execute('BEGIN IMMEDIATE'), stats, 'busy', 3, 0)
        self.assertEqual(stats['busy'], 3)
        self.other.execute('ROLLBACK')

    def test_retry_succeeds_after_lock_released(self):
        self.other.execute('BEGIN IMMEDIATE')
        stats = {'busy': 0}
        timer = threading.Timer(0.02, lambda: self.other.execute('ROLLBACK'))
        timer.start()
        retry(lambda: self.conn.execute('BEGIN IMMEDIATE'), stats, 'busy', 10_000, 0.001)
        self.conn.execute('ROLLBACK')
        timer.join()
        self.assertGreater(stats['busy'], 0)

    def test_retry_does_not_swallow_other_errors(self):
        with self.assertRaises(sqlite3.OperationalError):
            retry(lambda: self.conn.execute('SELECT * FROM missing_table'), {'b': 0}, 'b', 5, 0)

    def test_forced_mode_threads_revoke_in_the_gap(self):
        stats = {a: new_stats() for a in APPROACHES}
        rng = random.Random(0)
        for _ in range(20):
            for approach in APPROACHES:
                run_iteration(self.conn, self.other, approach, 'forced', stats[approach], rng, FAST)
        for approach in ('C', 'E'):
            self.assertEqual(stats[approach]['assigned_invalid'], 20)
            self.assertEqual(stats[approach]['revocation_committed_at_hook'], 20)
        for approach in ('F', 'D'):
            self.assertEqual(stats[approach]['assigned_invalid'], 0)
            self.assertEqual(stats[approach]['assigned_valid'], 20)
            self.assertGreaterEqual(stats[approach]['revoker_busy'], 20)
        self.assertFalse(read_eligible(self.conn))  # every revoker thread committed

    def test_free_mode_accounting_and_guarded_invariant(self):
        run = run_mode(self.path, 'free', 50, 7, FAST)
        for approach, s in run['approaches'].items():
            with self.subTest(approach=approach):
                outcomes = sum(s[k] for k in ('refused_precheck', 'refused_reread', 'refused_guard',
                                              'assigned_valid', 'assigned_invalid', 'busy_gave_up'))
                self.assertEqual(outcomes, 50)
                self.assertEqual(s['invalid_commits']['denominator'], 50)
        # Assertion of the property under test, not of a timing-dependent rate.
        self.assertEqual(run['approaches']['F']['assigned_invalid'], 0)
        self.assertEqual(run['approaches']['D']['assigned_invalid'], 0)

    def test_summarize_ratios(self):
        stats = new_stats()
        stats.update(iterations=4, assigned_invalid=1, assigned_valid=1)
        s = summarize(stats)
        self.assertEqual(s['invalid_commits'], {'numerator': 1, 'denominator': 4, 'rate': 0.25})
        self.assertEqual(s['invalid_among_commits']['rate'], 0.5)


if __name__ == '__main__':
    unittest.main()
