# SPDX-License-Identifier: MPL-2.0
"""Validate agent evidence and independently evaluate supported lot constraints."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from typing import Any

DECISIONS = {"MATCH_RECALL", "NO_MATCH_FOR_NOTICE", "INSUFFICIENT_EVIDENCE"}
FIELDS = {"brand", "model", "adapter_model", "manufactured_month", "generation"}
MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
POLICY_VERSION = "evidence-v2"
GENERATIONS = {1: ("1", "1st", "first"), 2: ("2", "2nd", "second"),
               3: ("3", "3rd", "third"), 4: ("4", "4th", "fourth")}


class InvalidAssessment(ValueError):
    pass


def identifier(value: Any) -> str:
    """Ignore cosmetic separators without dropping letters or leading zeroes."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\s\-]", "", value).casefold()


def month(value: Any) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        return value
    return None


def generation(value: Any) -> int | None:
    normalized = identifier(value)
    for number, aliases in GENERATIONS.items():
        if any(normalized in {alias, "gen" + alias, "generation" + alias,
                              alias + "gen", alias + "generation"} for alias in aliases):
            return number
    return None


def cited_generations(quote: str) -> set[int]:
    result = set()
    for number, aliases in GENERATIONS.items():
        ordinal = "(?:" + "|".join(aliases) + ")"
        if re.search(rf"\b(?:{ordinal}[\s-]+(?:generation|gen)|(?:generation|gen)[\s-]+{ordinal})\b", quote, re.I):
            result.add(number)
    return result


def source_month_range(text: str) -> tuple[str, str] | None:
    names = "|".join(MONTHS)
    pattern = rf"(?:from\s+)?({names})\s+(\d{{4}})\s+(?:through|to)\s+({names})\s+(\d{{4}})"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    start = f"{match[2]}-{MONTHS[match[1].lower()]:02}"
    end = f"{match[4]}-{MONTHS[match[3].lower()]:02}"
    return (start, end) if start <= end else None


@dataclass(frozen=True)
class ValidatedAssessment:
    decision: str
    reason: str
    checks: list[dict]
    missing_fields: list[str]


def _evidence(check: dict, snapshots: list[dict]) -> str:
    evidence = check.get("evidence")
    if not isinstance(evidence, dict):
        raise InvalidAssessment("Every check needs a source reference.")
    quote = evidence.get("quote")
    if not isinstance(quote, str) or not 3 <= len(quote) <= 2500:
        raise InvalidAssessment("Evidence quote has an invalid length.")
    source = next((s for s in snapshots if s["id"] == evidence.get("snapshot_id")), None)
    if source is None or quote not in source["text"]:
        raise InvalidAssessment("Evidence quote does not occur in the specified snapshot.")
    return quote


def _check(check: dict, lot: dict, snapshots: list[dict]) -> bool | None:
    if not isinstance(check, dict) or check.get("field") not in FIELDS:
        raise InvalidAssessment("Unsupported inventory field.")
    quote = _evidence(check, snapshots)
    field, op, expected = check["field"], check.get("operator"), check.get("value")
    actual = lot.get(field)
    if field == "manufactured_month":
        bounds = source_month_range(quote)
        if op != "between_inclusive" or not isinstance(expected, list) or len(expected) != 2:
            raise InvalidAssessment("Manufacturing month requires an inclusive range.")
        if bounds is None or tuple(expected) != bounds:
            raise InvalidAssessment("Month range is not supported by the cited source.")
        parsed = month(actual)
        return None if parsed is None else bounds[0] <= parsed <= bounds[1]
    if op != "equals" or not isinstance(expected, str) or not expected.strip():
        raise InvalidAssessment("Identifier checks require a nonempty string equality.")
    if field == "generation":
        expected_generation = generation(expected)
        if expected_generation is None or cited_generations(quote) != {expected_generation}:
            raise InvalidAssessment("Generation needs one explicit, unambiguous source generation.")
        actual_generation = generation(actual)
        return None if actual_generation is None else actual_generation == expected_generation
    if identifier(expected) not in identifier(quote):
        raise InvalidAssessment("Identifier is absent from the cited evidence.")
    # A substring within a different model is not a source for a model identifier.
    tokens = re.findall(r"[A-Za-z0-9]+(?:[- ][A-Za-z0-9]+)*", quote)
    if field in {"model", "adapter_model"}:
        bounded = re.search(r"(?<![A-Za-z0-9])" + re.escape(expected) + r"(?![A-Za-z0-9])", quote, re.I)
        if not bounded and not any(identifier(t) == identifier(expected) for t in tokens):
            raise InvalidAssessment("Model is only a substring of source text.")
    if actual is None or actual == "":
        return None
    if not isinstance(actual, str):
        raise InvalidAssessment("Inventory attribute must be a string or unknown.")
    actual_id, expected_id = identifier(actual), identifier(expected)
    if actual_id == expected_id:
        return True
    if actual_id.startswith(expected_id) or expected_id.startswith(actual_id):
        # A shortened brand or a model-family/suffix relationship is ambiguous.
        return None
    return False


def validate_assessment(value: dict, lot: dict, notice: dict) -> ValidatedAssessment:
    if not isinstance(value, dict) or value.get("decision") not in DECISIONS:
        raise InvalidAssessment("Unknown assessment decision.")
    if value.get("lot_id") != lot["lot_id"]:
        raise InvalidAssessment("Lot is outside the assessment scope.")
    reason = value.get("reason")
    if not isinstance(reason, str) or not 1 <= len(reason) <= 1200:
        raise InvalidAssessment("A concise reason is required.")
    checks = value.get("checks", [])
    missing = value.get("missing_fields", [])
    if not isinstance(checks, list) or len(checks) > 10:
        raise InvalidAssessment("Too many checks or invalid check format.")
    if not isinstance(missing, list) or any(not isinstance(x, str) or len(x) > 100 for x in missing):
        raise InvalidAssessment("Invalid missing-fields list.")
    if notice.get("target_component") == "power_adapter" and any(c.get("field") == "model" for c in checks if isinstance(c, dict)):
        raise InvalidAssessment("This is a component recall; compare adapter_model rather than the host product model.")
    results = [_check(check, lot, notice["snapshots"]) for check in checks]
    decision = value["decision"]
    if decision == "INSUFFICIENT_EVIDENCE":
        return ValidatedAssessment(decision, reason, checks, missing)
    if decision == "NO_MATCH_FOR_NOTICE":
        if not any(result is False for result in results):
            raise InvalidAssessment("A no-match needs an independently verified mismatch.")
        if notice.get("source_conflict") and not any(check["field"] == "brand" and result is False for check, result in zip(checks, results)):
            return ValidatedAssessment("INSUFFICIENT_EVIDENCE", "Source versions differ; human review is required.", checks, ["source_reconciliation"])
        return ValidatedAssessment(decision, reason, checks, missing)
    # A source mismatch or incomplete scope must never become an automatic clearance
    # or a confident recalled determination based only on a model's confidence.
    if not results or any(result is not True for result in results) or missing:
        raise InvalidAssessment("Recall match has missing or unsatisfied constraints.")
    fields = {check["field"] for check in checks}
    if not fields.intersection({"model", "adapter_model"}):
        raise InvalidAssessment("Recall match requires an explicit model check.")
    source = "\n".join(s["text"] for s in notice["snapshots"])
    if source_month_range(source) and "manufactured_month" not in fields:
        raise InvalidAssessment("Manufacturing range was not evaluated.")
    if notice.get("source_conflict"):
        return ValidatedAssessment("INSUFFICIENT_EVIDENCE", "Source versions differ; human review is required.", checks, ["source_reconciliation"])
    if re.search(r"qualifying serial|check their serial|some units", source, re.I):
        return ValidatedAssessment("INSUFFICIENT_EVIDENCE", "The notice has scope qualifiers requiring independent confirmation.", checks, ["scope_confirmation"])
    return ValidatedAssessment(decision, reason, checks, missing)
