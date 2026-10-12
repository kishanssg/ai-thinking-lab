import random
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock
from pathlib import Path

from experiment import (APPROACHES, DEFAULT_CONFIG, BusyGaveUp, give_credit, audit, connect,
                        create_database, new_stats, read_approved, reset, retry, run_iteration,
                        run_mode, summarize)

FAST = dict(DEFAULT_CONFIG, think_s=0.0005, cancel_window_s=0.0015)


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
        outcome = give_credit(self.conn, approach, hook, 0, stats, 10, 0.0001)
        return outcome, stats

    def cancel_from_other_connection(self):
        self.other.execute("UPDATE customers SET approved=0 WHERE id='customer-42'")

    def test_database_is_file_backed_wal(self):
        self.assertEqual(self.journal, 'wal')
        self.assertTrue(Path(self.path).exists())

    def test_audit_trigger_records_approval_seen_by_insert(self):
        self.cancel_from_other_connection()
        self.conn.execute("INSERT INTO credits (credit_id, customer) VALUES ('credit-42', 'customer-42')")
        self.assertEqual(audit(self.conn), (1, 0))
        reset(self.conn)
        self.assertEqual(audit(self.conn), (0, None))
        self.assertTrue(read_approved(self.conn))

    def test_all_approaches_credit_when_nothing_changes(self):
        for approach in APPROACHES:
            with self.subTest(approach=approach):
                reset(self.conn)
                self.assertEqual(self.run_approach(approach)[0], 'credited')
                self.assertEqual(audit(self.conn), (1, 1))

    def test_all_approaches_refuse_when_already_cancelled(self):
        for approach in APPROACHES:
            with self.subTest(approach=approach):
                reset(self.conn)
                self.cancel_from_other_connection()
                self.assertEqual(self.run_approach(approach)[0], 'refused_precheck')
                self.assertEqual(audit(self.conn), (0, None))

    def test_cancellation_at_hook_sequentially(self):
        # Sequential version of the vulnerable point: C and E write an invalid row; F and D
        # cannot be cancelled at their hook because they already hold the write lock.
        expected = {'C': ('credited', 0), 'E': ('credited', 0)}
        for approach in ('C', 'E'):
            with self.subTest(approach=approach):
                reset(self.conn)
                outcome, _ = self.run_approach(approach, self.cancel_from_other_connection)
                self.assertEqual((outcome, audit(self.conn)[1]), expected[approach])
        for approach in ('F', 'D'):
            with self.subTest(approach=approach):
                reset(self.conn)
                busy = []

                def hook():
                    try:
                        self.cancel_from_other_connection()
                    except sqlite3.OperationalError as error:
                        busy.append(error)

                outcome, _ = self.run_approach(approach, hook)
                self.assertEqual(outcome, 'credited')
                self.assertEqual(len(busy), 1)
                self.assertEqual(audit(self.conn), (1, 1))

    def test_guard_and_reread_refuse_cancellation_before_their_check(self):
        for approach, refusal in (('E', 'refused_reread'), ('F', 'refused_reread'),
                                  ('D', 'refused_guard')):
            with self.subTest(approach=approach):
                reset(self.conn)
                # Cancel during the think time: after the precheck, before the approach acts.
                with mock.patch('experiment.time.sleep',
                                side_effect=lambda _: self.cancel_from_other_connection()):
                    outcome = give_credit(self.conn, approach, lambda: None, 0, new_stats(), 10, 0.0001)
                self.assertEqual(outcome, refusal)
                self.assertEqual(audit(self.conn), (0, None))

    def test_in_flight_cancellation_is_invisible_to_a_late_reread(self):
        # The canceller opens its write transaction during the think time and commits while
        # the agent backs off from SQLITE_BUSY. Under WAL, E's re-read sees the last
        # committed value (approved), so its retried insert lands after the cancellation.
        expected = {'C': 'credited_invalid', 'E': 'credited_invalid',
                    'F': 'refused_reread', 'D': 'refused_guard'}
        for approach, want in expected.items():
            with self.subTest(approach=approach):
                reset(self.conn)
                steps = iter([
                    lambda: (self.other.execute('BEGIN IMMEDIATE'),
                             self.other.execute("UPDATE customers SET approved=0")),
                    lambda: self.other.execute('COMMIT')])
                stats = new_stats()
                with mock.patch('experiment.time.sleep',
                                side_effect=lambda _: next(steps, lambda: None)()):
                    outcome = give_credit(self.conn, approach, lambda: None, 0, stats, 10, 0)
                if outcome == 'credited':
                    outcome = 'credited_valid' if audit(self.conn)[1] == 1 else 'credited_invalid'
                self.assertEqual(outcome, want)
                self.assertEqual(stats['agent_busy'], 1)

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

    def test_forced_mode_threads_cancel_in_the_gap(self):
        stats = {a: new_stats() for a in APPROACHES}
        rng = random.Random(0)
        for _ in range(20):
            for approach in APPROACHES:
                run_iteration(self.conn, self.other, approach, 'forced', stats[approach], rng, FAST)
        for approach in ('C', 'E'):
            self.assertEqual(stats[approach]['credited_invalid'], 20)
            self.assertEqual(stats[approach]['cancellation_committed_at_hook'], 20)
        for approach in ('F', 'D'):
            self.assertEqual(stats[approach]['credited_invalid'], 0)
            self.assertEqual(stats[approach]['credited_valid'], 20)
            self.assertGreaterEqual(stats[approach]['canceller_busy'], 20)
        self.assertFalse(read_approved(self.conn))  # every canceller thread committed

    def test_free_mode_accounting_and_guarded_invariant(self):
        run = run_mode(self.path, 'free', 50, 7, FAST)
        for approach, s in run['approaches'].items():
            with self.subTest(approach=approach):
                outcomes = sum(s[k] for k in ('refused_precheck', 'refused_reread', 'refused_guard',
                                              'credited_valid', 'credited_invalid', 'busy_gave_up'))
                self.assertEqual(outcomes, 50)
                self.assertEqual(s['invalid_commits']['denominator'], 50)
        # Assertion of the property under test, not of a timing-dependent rate.
        self.assertEqual(run['approaches']['F']['credited_invalid'], 0)
        self.assertEqual(run['approaches']['D']['credited_invalid'], 0)

    def test_summarize_ratios(self):
        stats = new_stats()
        stats.update(iterations=4, credited_invalid=1, credited_valid=1)
        s = summarize(stats)
        self.assertEqual(s['invalid_commits'], {'numerator': 1, 'denominator': 4, 'rate': 0.25})
        self.assertEqual(s['invalid_among_commits']['rate'], 0.5)


if __name__ == '__main__':
    unittest.main()
