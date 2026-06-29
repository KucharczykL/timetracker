"""Cross-language contract for the filter-tree serializer (issue #188).

The TS vitest suite emits fixtures.canonical.json = serialize(deserialize(x)) for every
shared fixture. This test asserts the TS serializer's ACTUAL output parses via the
backend and is to_q()-equivalent to the original source filter — locking the TS
canonical form to backend semantics (the OR / NOT / relation / presence cases most
likely to diverge). Skipped if the artifact is missing (run `make test-ts` first);
`make check` orders test-ts before this so the gate always sees fresh output.
"""

import json
import os
from pathlib import Path

import pytest

from common.criteria import filter_from_json
from games.filters import GameFilter, SessionFilter

FILTER_TREE_DIR = (
    Path(__file__).resolve().parent.parent / "ts" / "elements" / "filter-tree"
)
FIXTURES = json.loads((FILTER_TREE_DIR / "fixtures.json").read_text())
CANONICAL_PATH = FILTER_TREE_DIR / "fixtures.canonical.json"

FILTER_FOR_MODEL = {"game": GameFilter, "session": SessionFilter}

# Map each original fixture to its TS-emitted canonical form, by description.
if CANONICAL_PATH.exists():
    _canonical_by_description = {
        case["description"]: case
        for case in json.loads(CANONICAL_PATH.read_text())["cases"]
    }
else:
    _canonical_by_description = {}


def test_canonical_artifact_present_under_ci():
    """In CI the artifact MUST exist (`make test-ts` runs before pytest), so a
    pipeline that forgets to generate it fails loudly here instead of letting the
    contract test below silently skip. Locally the artifact may be absent (#227)."""
    if os.environ.get("CI"):
        assert CANONICAL_PATH.exists(), (
            "fixtures.canonical.json missing under CI — `make test-ts` must run "
            "before pytest (see #227)"
        )


def _q_str(filter_object) -> str:
    # str(Q) is a stable structural rendering; equal structures compare equal.
    return str(filter_object.to_q())


@pytest.mark.django_db
@pytest.mark.skipif(
    not CANONICAL_PATH.exists(),
    reason="fixtures.canonical.json missing — run `make test-ts` first",
)
@pytest.mark.parametrize(
    "case", FIXTURES["cases"], ids=[c["description"] for c in FIXTURES["cases"]]
)
def test_ts_canonical_output_is_to_q_equivalent(case):
    filter_cls = FILTER_FOR_MODEL[case["model"]]

    original = filter_from_json(filter_cls, json.dumps(case["filter"]))
    assert original is not None, f"fixture did not parse: {case['description']}"

    if case["description"] not in _canonical_by_description:
        pytest.fail(
            f"TS canonical missing case {case['description']!r} — run `make test-ts` first"
        )
    ts_canonical = _canonical_by_description[case["description"]]
    reparsed = filter_from_json(filter_cls, json.dumps(ts_canonical["filter"]))
    assert reparsed is not None, f"TS canonical did not parse: {case['description']}"

    assert _q_str(reparsed) == _q_str(original), case["description"]
