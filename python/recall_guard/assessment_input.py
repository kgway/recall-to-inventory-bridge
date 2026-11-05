# SPDX-License-Identifier: MPL-2.0
"""Decode unambiguous transport formats before strict evidence validation."""
import copy
import json
import re

FORMAT_VERSION = 'assessment-input-v1'
MONTH = r'[0-9]{4}-(?:0[1-9]|1[0-2])'
PAIR = re.compile(r'\[\s*('+MONTH+r')\s*,\s*('+MONTH+r')\s*\]')


def canonicalize_assessment(proposal):
    value = copy.deepcopy(proposal)
    changes = []
    if not isinstance(value, dict) or not isinstance(value.get('checks'), list):
        return value, changes
    for index, check in enumerate(value['checks']):
        if not isinstance(check, dict) or check.get('field') != 'manufactured_month' or check.get('operator') != 'between_inclusive':
            continue
        original = check.get('value')
        if not isinstance(original, str):
            continue
        try:
            parsed = json.loads(original)
        except (ValueError, TypeError):
            match = PAIR.fullmatch(original.strip())
            parsed = list(match.groups()) if match else None
        if (not isinstance(parsed, list) or len(parsed) != 2
                or any(not isinstance(v, str) or not re.fullmatch(MONTH, v) for v in parsed)):
            continue
        check['value'] = parsed
        changes.append({'check_index': index, 'kind': 'month-pair-string', 'original': original, 'canonical': parsed})
    return value, changes
