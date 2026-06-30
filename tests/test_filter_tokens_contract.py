"""Cross-language contract for the behavioral filter tokens (#152).

The TS vitest suite emits filter-tokens.canonical.json = the actual token arrays
ts/elements/filter-tokens.ts exports. This test asserts every token is a real
``common.criteria.Modifier`` value, so a renamed/removed Python modifier fails CI
instead of silently orphaning a TS literal (the #141 failure mode). Membership —
not set-identity — is the contract: *which* tokens are presence/range is a TS UI
decision; that each names a live Modifier is the cross-language invariant.

Skipped if the artifact is missing (run ``make test-ts`` first); ``make check``
orders test-ts before this so the gate always sees fresh output. Mirrors
tests/test_filter_tree_contract.py.
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
    / "filter-tokens.canonical.json"
)

MODIFIER_VALUES = {modifier.value for modifier in Modifier}


def test_canonical_artifact_present_under_ci():
    """In CI the artifact MUST exist (``make test-ts`` runs before pytest), so a
    pipeline that forgets to generate it fails loudly here instead of letting the
    contract test below silently skip."""
    if os.environ.get("CI"):
        assert CANONICAL_PATH.exists(), (
            "filter-tokens.canonical.json missing under CI — `make test-ts` must "
            "run before pytest"
        )


@pytest.mark.skipif(
    not CANONICAL_PATH.exists(),
    reason="filter-tokens.canonical.json missing — run `make test-ts` first",
)
def test_behavioral_tokens_are_real_modifiers():
    tokens = json.loads(CANONICAL_PATH.read_text())
    flattened = [(group, value) for group, values in tokens.items() for value in values]
    assert flattened, "no tokens emitted — the TS artifact is empty"
    for group, value in flattened:
        assert value in MODIFIER_VALUES, (
            f"{group} token {value!r} is not a common.criteria.Modifier value — "
            "the TS token drifted from the Python enum (#152)"
        )
