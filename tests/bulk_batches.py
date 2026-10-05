"""Bulk batch chunks, run inline in tests."""

import uuid
from collections import deque
from dataclasses import dataclass, field

import pytest
from django.db import transaction

from games import bulk_jobs
from games.models import BulkBatch

type QueuedChunk = tuple[uuid.UUID, int]

#: The queue the cluster would use.
REAL_ENQUEUE = bulk_jobs.enqueue


@dataclass
class ChunkQueue:
    """Chunks queued, drained on commit unless held."""

    held: bool = False
    #: A test expecting a defect opts in.
    failures_expected: bool = False
    queued: deque[QueuedChunk] = field(default_factory=deque)
    _draining: bool = field(default=False, init=False)

    def enqueue(self, batch_id: uuid.UUID, chunk: int) -> None:
        self.queued.append((batch_id, chunk))
        if not self.held:
            transaction.on_commit(self.drain)

    def drain(self) -> None:
        """Run every queued chunk; loops, never recurses."""
        if self._draining:
            return
        self._draining = True
        try:
            while self.queued:
                self.run_one()
        finally:
            self._draining = False

    def run_one(self) -> None:
        assert self.queued, "no chunk is queued"
        batch_id, chunk = self.queued.popleft()
        bulk_jobs.run_chunk(batch_id, chunk)
        state = BulkBatch.objects.filter(pk=batch_id).values_list("state", flat=True)
        if not self.failures_expected and state.first() == BulkBatch.State.FAILED:
            raise AssertionError(f"batch {batch_id} failed; see the games log")

    def run_all(self) -> None:
        while self.queued:
            self.run_one()


@pytest.fixture(autouse=True)
def chunk_queue(monkeypatch) -> ChunkQueue:
    """Every press acts before its redirect."""
    queue = ChunkQueue()
    monkeypatch.setattr(bulk_jobs, "enqueue", queue.enqueue)
    return queue


@pytest.fixture
def held_batches(chunk_queue) -> ChunkQueue:
    """Chunks wait for the test to run them."""
    chunk_queue.held = True
    return chunk_queue


@pytest.fixture
def failing_batches(chunk_queue) -> ChunkQueue:
    """A batch may end failed."""
    chunk_queue.failures_expected = True
    return chunk_queue
