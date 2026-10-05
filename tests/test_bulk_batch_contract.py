"""Every `batch_out` shape the coordinator reads."""

import json
import uuid
from pathlib import Path

from django.utils import timezone

from games.bulk_jobs import batch_out
from games.models import BulkBatch

#: vitest reads it; this test keeps it current.
FIXTURE = Path(__file__).resolve().parents[1] / "ts" / "bulk-batch-status.fixtures.json"

TOKEN = uuid.UUID("01900000-0000-7000-8000-000000000001")
UNDONE = uuid.UUID("01900000-0000-7000-8000-000000000002")


def _batch(state: BulkBatch.State, **columns) -> BulkBatch:
    now = timezone.now()
    ended = now if state in BulkBatch.TERMINAL else None
    return BulkBatch(
        token=TOKEN,
        action="session.reclassify",
        origin="/tracker/session/list",
        rows=["a", "b"],
        total=2,
        state=state,
        updated_at=now,
        ended_at=ended,
        **columns,
    )


def shapes() -> list[dict]:
    states = BulkBatch.State
    return [
        dict(batch_out(batch))
        for batch in (
            _batch(states.QUEUED),
            _batch(states.RUNNING, done=1, position=1),
            _batch(states.RUNNING, stop_requested_at=timezone.now()),
            _batch(states.FINISHED, done=2, position=2),
            _batch(states.FINISHED, refused=2, position=2, reasons=["Why."]),
            _batch(states.FINISHED, done=2, position=2, undoes=UNDONE),
            _batch(states.STOPPED, done=1, position=1),
            _batch(states.FAILED, done=1, position=1),
        )
    ]


def test_the_coordinators_fixture_is_current():
    written = json.dumps(shapes(), indent=2) + "\n"
    if FIXTURE.read_text() != written:
        FIXTURE.write_text(written)
        raise AssertionError(f"{FIXTURE.name} was stale; rewritten, commit it")
