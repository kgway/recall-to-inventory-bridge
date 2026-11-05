# SPDX-License-Identifier: MPL-2.0
"""Verify completed live assessments and execute a bounded set of synthetic orders.

Run once after all three live investigations, before human review or other orders.
This script makes NO LLM requests. Successful orders consume synthetic stock.
"""
import argparse
import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from iris_client import IrisClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    record = {'at_utc': datetime.now(timezone.utc).isoformat(), 'success': False,
              'llm_called_by_this_check': False, 'orders_are_synthetic': True,
              'limitation': 'The configured Retailer operation has pool size 1; this checks concurrent HTTP requests through that Production, not direct database writers.',
              'assessment_checks': [], 'transactions': []}
    with args.output.open('x', encoding='utf-8') as output:
        try:
            client = IrisClient()
            state = client.state()
            record['iris_version'] = state['iris_version']
            expected = json.loads((Path(__file__).resolve().parents[1]/'fixtures/expected_decisions.json').read_text())
            runs = {r['run_id']: r for r in state['runs']}
            actual = {(a['notice_id'], a['lot_id']): a for a in state['assessments']}
            for case in expected['cases']:
                for notice, decision in zip(expected['notice_order'], case['decisions'], strict=True):
                    assessment = actual.get((notice, case['lot_id']), {})
                    run = runs.get(assessment.get('run_id'), {})
                    backed = (run.get('status') == 'COMPLETED' and run.get('mode') == 'live'
                              and any(t['name'] == 'ReadContext' for t in run.get('tool_calls', [])))
                    record['assessment_checks'].append({'notice_id': notice, 'lot_id': case['lot_id'],
                        'expected': decision, 'actual': assessment.get('decision'),
                        'run_id': assessment.get('run_id'),
                        'passed': backed and assessment.get('decision') == decision})
            if not all(c['passed'] for c in record['assessment_checks']):
                raise RuntimeError('Live assessment expectations did not all match.')
            if state['reviews'] or any(l['quantity'] != 5 for l in state['lots']):
                raise RuntimeError('Run this check before human review or successful stock-consuming orders.')
            lots = {l['lot_id']: l for l in state['lots']}
            expected_status = {'DREO-start': 'HOLD_RECALL', 'ANKER-unverified': 'HOLD_REVIEW',
                               'CONTROL-unrelated': 'ELIGIBLE_IN_DEMO_SCOPE', 'DREO-after': 'ELIGIBLE_IN_DEMO_SCOPE'}
            if any(lots[k]['status'] != v for k, v in expected_status.items()):
                raise RuntimeError('Required hold/eligible states are missing.')

            def order(kind, lines, key=None):
                request = {'idempotency_key': key or 'live-check-'+uuid.uuid4().hex,
                           'kind': kind, 'lines': lines}
                return IrisClient().request('transact', request)

            for kind in ('sale', 'shipment'):
                result = order(kind, [{'lot_id': 'DREO-start', 'quantity': 1}])
                record['transactions'].append(result)
                if result['allowed'] or not any(b.get('status') == 'HOLD_RECALL' for b in result['blocked']):
                    raise RuntimeError('A confirmed recall did not block '+kind+'.')
            result = order('shipment', [{'lot_id': 'ANKER-unverified', 'quantity': 1}])
            record['transactions'].append(result)
            if result['allowed'] or not any(b.get('status') == 'HOLD_REVIEW' for b in result['blocked']):
                raise RuntimeError('An unresolved serial-qualified case did not block shipment.')
            result = order('sale', [{'lot_id': 'CONTROL-unrelated', 'quantity': 1}])
            record['transactions'].append(result)
            if not result['allowed']:
                raise RuntimeError('The eligible control lot did not allow a synthetic sale.')
            replay = order('sale', result['lines'], result['idempotency_key'])
            record['transactions'].append(replay)
            if not replay['allowed'] or not replay['replayed']:
                raise RuntimeError('An identical retry did not reuse its stored result.')
            mixed = order('shipment', [{'lot_id': 'DREO-before', 'quantity': 1},
                                       {'lot_id': 'DREO-end', 'quantity': 1}])
            record['transactions'].append(mixed)
            if mixed['allowed']:
                raise RuntimeError('A mixed order containing a recalled lot was allowed.')
            with ThreadPoolExecutor(max_workers=2) as pool:
                pending = [pool.submit(order, 'shipment', [{'lot_id': 'DREO-after', 'quantity': 3}]) for _ in range(2)]
                concurrent = [future.result() for future in pending]
            record['transactions'].extend(concurrent)
            if sum(r['allowed'] for r in concurrent) != 1:
                raise RuntimeError('Concurrent shipments did not allow exactly one request.')
            after = client.state()
            quantities = {l['lot_id']: l['quantity'] for l in after['lots']}
            wanted = {l['lot_id']: 5 for l in state['lots']}
            wanted.update({'CONTROL-unrelated': 4, 'DREO-after': 2})
            if quantities != wanted:
                raise RuntimeError('Stock changes differed from the two successful synthetic orders.')
            record.update(success=True, matched_assessments=len(record['assessment_checks']),
                          quantities_after=quantities, agent_run_count_before=len(state['runs']),
                          agent_run_count_after=len(after['runs']))
            if record['agent_run_count_before'] != record['agent_run_count_after']:
                raise RuntimeError('Unexpected investigation during the no-LLM gate check.')
        except Exception as exc:
            record.update(success=False, error_type=type(exc).__name__, error=str(exc)[:800])
        record['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        json.dump(record, output, indent=2)
        output.write('\n')
    print(json.dumps({k: v for k, v in record.items() if k not in {'assessment_checks', 'transactions'}}, indent=2))
    return 0 if record['success'] else 1


if __name__ == '__main__':
    sys.exit(main())
