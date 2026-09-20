import unittest

from experiment import Store, load_fixtures, run_case, summarize


class ExperimentTests(unittest.TestCase):
    def test_predetermined_outcomes(self):
        for fixture in load_fixtures():
            for approach, expected in fixture['expected'].items():
                with self.subTest(scenario=fixture['id'], approach=approach):
                    result = run_case(fixture, approach)
                    self.assertEqual([result['recommended'], result['committed']], expected)

    def test_ground_truth_and_metrics(self):
        results = [run_case(f, a) for f in load_fixtures() for a in 'ABCD']
        self.assertEqual(len(results), 24)
        summary = summarize(results)
        expected = {'A': (2, 3, 2, 1, 0), 'B': (0, 1, 2, 1, 6),
                    'C': (0, 1, 2, 1, 6), 'D': (0, 0, 2, 1, 6)}
        for approach, counts in expected.items():
            s = summary[approach]
            self.assertEqual(tuple(s[k]['numerator'] for k in (
                'incorrect_affirmative_recommendations', 'invalid_commits', 'valid_task_completion',
                'unnecessary_refusals', 'verification_rate')), counts)
            self.assertEqual(s['valid_task_completion']['denominator'], 3)
            self.assertEqual(s['incorrect_affirmative_recommendations']['denominator'], 6)
            self.assertEqual(s['unnecessary_refusals']['denominator'], 3)
            self.assertNotIn('incorrect_recommendations', s)

    def test_atomic_guard_reads_current_state(self):
        with Store(True) as store:
            self.assertTrue(store.verify(False))
            store.change(False)
            self.assertEqual(store.commit(True), (False, 'ineligible_or_missing'))
            self.assertEqual(store.assignment_count(), 0)

    def test_guard_allows_eligible_and_is_idempotent(self):
        with Store(True) as store:
            self.assertEqual(store.commit(True), (True, 'assigned'))
            self.assertEqual(store.commit(True), (False, 'already_assigned'))
            self.assertEqual(store.assignment_count(), 1)

    def test_guard_rejects_missing_and_ineligible(self):
        for state in (None, False):
            with self.subTest(state=state), Store(state) as store:
                self.assertEqual(store.commit(True), (False, 'ineligible_or_missing'))
                self.assertEqual(store.assignment_count(), 0)

    def test_required_precheck_cannot_be_bypassed(self):
        from experiment import required_commit
        with Store(True) as store:
            self.assertEqual(required_commit(store, False, False),
                             (False, 'required_precheck_missing'))
            self.assertEqual(store.assignment_count(), 0)

    def test_lookup_failure_fails_closed(self):
        fixture = next(f for f in load_fixtures() if f['id'] == 'lookup_fails')
        for approach in 'BCD':
            result = run_case(fixture, approach)
            self.assertFalse(result['committed'])
            self.assertTrue(any(e['kind'] == 'verification' and e['reason'] == 'lookup_error'
                                for e in result['events']))

    def test_metrics_derive_from_events(self):
        result = run_case(load_fixtures()[0], 'D')
        result['recommended'] = False
        result['committed'] = False
        self.assertEqual(summarize([result])['D']['valid_task_completion']['numerator'], 1)


if __name__ == '__main__':
    unittest.main()
