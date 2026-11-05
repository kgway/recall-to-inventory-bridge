# SPDX-License-Identifier: MPL-2.0
"""Safety tests for the date-pair format observed in a real native agent run."""
import copy
import unittest

from recall_guard.assessment_input import canonicalize_assessment
from recall_guard.engine import Engine, digest
from recall_guard.storage import MemoryStore
from test_engine import assessment, lot, notice


class AssessmentInputTest(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.engine = Engine(self.store)
        self.note = notice()
        self.item = lot()
        self.engine.seed([self.note], [self.item])
        self.key = digest([self.note['notice_id'], self.item['lot_id']])

    def evaluate(self, value, model='unit-test'):
        run = self.engine.prepare_run(self.note['notice_id'], model=model, limit=20)
        self.engine.tool(run['run_id'], 'ReadContext')
        self.engine.submit(run['run_id'], [value])
        self.engine.finish_run(run['run_id'])
        return run['run_id']

    def string_pair(self, text='[2025-04, 2026-01]', decision='MATCH_RECALL'):
        value = assessment(self.item, self.note, decision)
        value['checks'][1]['value'] = text
        return value

    def legacy_record(self, run_id):
        # Fixture matching the earlier strict parser's rejection of the captured
        # model's unquoted month-pair string. No inference is simulated here.
        previous = self.store.get('assessment', self.key)
        previous.pop('input_format_version', None)
        previous.pop('input_normalizations', None)
        previous.update(decision='INSUFFICIENT_EVIDENCE', reason='Manufacturing month requires an inclusive range.',
                        checks=[], missing_fields=['validated_evidence'])
        self.store.put('assessment', self.key, previous)
        return previous

    def test_observed_month_pair_string_is_canonicalized_without_changing_raw_output(self):
        value = self.string_pair()
        original = copy.deepcopy(value)
        self.evaluate(value)
        saved = self.store.get('assessment', self.key)
        self.assertEqual(saved['decision'], 'MATCH_RECALL')
        self.assertEqual(saved['checks'][1]['value'], ['2025-04', '2026-01'])
        self.assertEqual(saved['proposed_assessment'], original)
        self.assertEqual(value, original)
        self.assertEqual(len(saved['input_normalizations']), 1)

    def test_json_encoded_pair_is_also_unambiguous(self):
        self.evaluate(self.string_pair('["2025-04", "2026-01"]'))
        self.assertEqual(self.store.get('assessment', self.key)['decision'], 'MATCH_RECALL')

    def test_other_strings_extra_values_and_invalid_months_cannot_clear_inventory(self):
        for text in ('2025-04 through 2026-01', '[2025-04, 2026-01, 2027-01]',
                     '[2025-13, 2026-01]', '[2026-01, 2025-04]',
                     '[2025-03, 2026-02]', '[2025-04, 2026-01]; extra'):
            with self.subTest(text=text):
                self.evaluate(self.string_pair(text, 'NO_MATCH_FOR_NOTICE'), model=text)
                self.assertEqual(self.store.get('assessment', self.key)['decision'], 'INSUFFICIENT_EVIDENCE')

    def test_canonical_pair_cannot_make_a_missing_lot_date_a_mismatch(self):
        self.engine.import_lots([{**self.item, 'manufactured_month': None}])
        self.evaluate(self.string_pair(decision='NO_MATCH_FOR_NOTICE'))
        self.assertEqual(self.store.get('assessment', self.key)['decision'], 'INSUFFICIENT_EVIDENCE')

    def test_canonical_pair_does_not_repair_a_fabricated_quote(self):
        value = self.string_pair()
        value['checks'][1]['evidence'] = {'snapshot_id': self.note['snapshots'][0]['id'], 'quote': 'Fabricated source dates.'}
        self.evaluate(value)
        self.assertEqual(self.store.get('assessment', self.key)['decision'], 'INSUFFICIENT_EVIDENCE')

    def test_unrelated_fields_are_never_coerced(self):
        value = self.string_pair()
        value['checks'][0]['value'] = '[2025-04, 2026-01]'
        canonical, changes = canonicalize_assessment(value)
        self.assertEqual(canonical['checks'][0]['value'], value['checks'][0]['value'])
        self.assertEqual([c['check_index'] for c in changes], [1])

    def test_revalidation_preserves_inference_and_archives_previous_validation(self):
        run_id = self.evaluate(self.string_pair())
        previous = self.legacy_record(run_id)
        run_before = self.store.get('run', run_id)
        report = self.engine.revalidate_run(run_id)
        saved = self.store.get('assessment', self.key)
        run_after = self.store.get('run', run_id)
        self.assertTrue(report['without_inference'])
        self.assertEqual(saved['decision'], 'MATCH_RECALL')
        self.assertEqual(saved['proposed_assessment'], previous['proposed_assessment'])
        self.assertEqual(self.store.scan('assessment_revision'), [previous])
        for field in ('run_id', 'created_at', 'finished_at', 'usage', 'tool_calls', 'prompt_version'):
            self.assertEqual(run_before[field], run_after[field])
        self.assertEqual(len(self.store.scan('run')), 1)
        self.assertTrue(self.engine.revalidate_run(run_id)['reused'])
        self.assertEqual(len(self.store.scan('assessment_revision')), 1)

    def test_revalidation_refuses_changed_source_or_inventory(self):
        for changed in ('source', 'inventory'):
            with self.subTest(changed=changed):
                self.setUp()
                run_id = self.evaluate(self.string_pair())
                self.legacy_record(run_id)
                if changed == 'source':
                    self.engine.import_notices([notice(text='Source evidence changed.')])
                else:
                    self.engine.import_lots([{**self.item, 'model': 'CHANGED-MODEL'}])
                before = self.store.get('assessment', self.key)
                with self.assertRaises(ValueError):
                    self.engine.revalidate_run(run_id)
                self.assertEqual(before, self.store.get('assessment', self.key))
                self.assertFalse(self.store.scan('assessment_revision'))

    def test_revalidation_refuses_unfinished_or_failed_runs(self):
        run_id = self.evaluate(self.string_pair())
        self.legacy_record(run_id)
        for status in ('RUNNING', 'SUBMITTED', 'FAILED'):
            with self.subTest(status=status):
                run = self.store.get('run', run_id)
                run['status'] = status
                self.store.put('run', run_id, run)
                with self.assertRaises(ValueError):
                    self.engine.revalidate_run(run_id)

    def test_revalidation_cannot_replace_a_newer_run(self):
        old = self.evaluate(self.string_pair())
        self.legacy_record(old)
        newer = self.evaluate(assessment(self.item, self.note), model='another-unit-test-model')
        with self.assertRaises(ValueError):
            self.engine.revalidate_run(old)
        self.assertEqual(self.store.get('assessment', self.key)['run_id'], newer)

    def test_revalidation_refuses_a_retired_evidence_policy(self):
        run_id = self.evaluate(self.string_pair())
        self.legacy_record(run_id)
        run = self.store.get('run', run_id)
        run['policy_version'] = 'retired-policy'
        self.store.put('run', run_id, run)
        with self.assertRaises(ValueError):
            self.engine.revalidate_run(run_id)
        self.assertFalse(self.store.scan('assessment_revision'))

    def test_revalidation_cannot_overwrite_an_operator_review(self):
        value = {'lot_id': self.item['lot_id'], 'decision': 'INSUFFICIENT_EVIDENCE',
                 'reason': 'Need to inspect the label.', 'checks': [], 'missing_fields': ['label']}
        run_id = self.evaluate(value)
        current = self.store.get('assessment', self.key)
        request = {k: current[k] for k in ('notice_id', 'lot_id', 'notice_version', 'inventory_version', 'run_id')}
        request.update(decision='CONFIRM_RECALL', reason='Synthetic operator test: keep the precautionary hold until label inspection.')
        self.engine.review(request, 'unit-test-operator')
        before = self.store.get('assessment', self.key)
        with self.assertRaises(ValueError):
            self.engine.revalidate_run(run_id)
        self.assertEqual(before, self.store.get('assessment', self.key))
