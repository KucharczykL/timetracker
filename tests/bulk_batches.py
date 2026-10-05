"""Bulk batch chunks, run inline in tests."""

import uuid
from dataclasses import dataclass, field

import pytest
from django.db import transaction

from games import bulk_jobs

type QueuedChunk = tuple[uuid.UUID, int]


@dataclass
class ChunkQueue:
    """Chunks queued, drained on commit unless held."""

    held: bool = False
    queued: list[QueuedChunk] = field(default_factory=list)
    draining: bool = False

    def enqueue(self, batch_id: uuid.UUID, chunk: int) -> None:
        self.queued.append((batch_id, chunk))
        if not self.held:
            transaction.on_commit(self.drain)

    def drain(self) -> None:
        """Run every queued chunk; loops, never recurses."""
        if self.draining:
            return
        self.draining = True
        try:
            while self.queued:
                batch_id, chunk = self.queued.pop(0)
                bulk_jobs.run_chunk(batch_id, chunk)
        finally:
            self.draining = False

    def run_one(self) -> None:
        batch_id, chunk = self.queued.pop(0)
        bulk_jobs.run_chunk(batch_id, chunk)

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
