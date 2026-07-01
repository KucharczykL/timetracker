"""Cross-language contract for the NL filter summary's modifier phrasing (#194).

The vitest suite emits summary-modifiers.canonical.json = the keys of the
``MODIFIER_PHRASES`` map in ts/elements/filter-tree/summary.ts. This test asserts
every key is a real ``common.criteria.Modifier`` value, so a renamed/removed Python
modifier fails CI instead of orphaning a phrase (the #141 failure mode). Mirrors
tests/test_filter_tokens_contract.py.

Skipped if the artifact is missing (run ``make test-ts`` first); ``make check``
orders test-ts before pytest so the gate always sees fresh output.
"""

import json
import os
from pathlib import Path

import pytest

from common.criteria import Modifier

CANONICAL_PATH = (
    Path(__file__).resolve().parent.parent
    / "ts"
    / "elements"
    / "filter-tree"
    / "summary-modifiers.canonical.json"
)

MODIFIER_VALUES = {modifier.value for modifier in Modifier}


def test_canonical_artifact_present_under_ci():
    if os.environ.get("CI"):
        assert CANONICAL_PATH.exists(), (
            "summary-modifiers.canonical.json missing under CI — `make test-ts` "
            "must run before pytest"
        )


@pytest.mark.skipif(
    not CANONICAL_PATH.exists(),
    reason="summary-modifiers.canonical.json missing — run `make test-ts` first",
)
def test_summary_modifier_keys_are_real_modifiers():
    keys = json.loads(CANONICAL_PATH.read_text())
    assert keys, "no modifier keys emitted — the TS artifact is empty"
    for key in keys:
        assert key in MODIFIER_VALUES, (
            f"MODIFIER_PHRASES key {key!r} is not a common.criteria.Modifier value "
            "— the summary phrase map drifted from the Python enum (#194)"
        )


@pytest.mark.skipif(
    not CANONICAL_PATH.exists(),
    reason="summary-modifiers.canonical.json missing — run `make test-ts` first",
)
def test_every_modifier_has_a_summary_phrase():
    """The contract is bidirectional: besides every phrase key being a real
    Modifier, every Modifier must have a phrase — otherwise a newly-added Modifier
    would reach the summary and silently print its raw token instead of English."""
    keys = set(json.loads(CANONICAL_PATH.read_text()))
    missing = MODIFIER_VALUES - keys
    assert not missing, (
        f"Modifier(s) {sorted(missing)} have no MODIFIER_PHRASES entry — the summary "
        "would print the raw token. Add a phrase in ts/elements/filter-tree/summary.ts (#194)"
    )
