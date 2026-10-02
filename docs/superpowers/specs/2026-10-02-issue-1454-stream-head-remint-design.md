# The anonymizer re-mints the stream head

Issue [#1454](https://github.com/KucharczykL/timetracker/issues/1454).

## The gap

`make anonymize-sample` mints new ids for events, references and
aggregates from the rewritten dates. It keeps the id of
`LibraryEventStreamHead`. That UUIDv7 holds the real millisecond at which
the library got its stream.

## The change

After `_reassign_event_identities` returns, `_reassign_stream_head` gives
the stream head of the library a new id. A library that never appended
has no head, and the step does nothing:

- The id is minted with `_mint` at the earliest rewritten `recorded_at`
  of the library's events, so the head comes no later than its first
  event in id order. A dated event takes the midnight of its jittered
  day, and that day can be before `FIXED_EPOCH`: the 2026-10-01 fixture
  holds 622 such events. A library whose stream holds no event mints at
  `FIXED_EPOCH`.
- The entropy comes from the seeded random generator. The call comes
  after every other draw, so the ids before it do not move.
- A queryset `update` writes the primary key, because `bulk_update`
  refuses one.
- `_remap_referrers(LibraryEventStreamHead, {old: new})` points each
  foreign key at the new id. `LibraryEvent.stream` is the only one;
  no payload, metadata or other table holds a stream id. One `UPDATE` of
  the events would be cheaper, but the walk also finds a referrer that a
  later model adds.

Both keys from an event to its head are deferred: Django creates the
`stream` key `DEFERRABLE INITIALLY DEFERRED`, and migration 0036 (#1450)
makes `library_event_stream_matches_library` the same. Thus the head
can change before its events. The remap is complete before
`connection.check_constraints()`, which runs ahead of `dumpdata`.

The step runs after the event pass. That pass groups idempotency keys by
`(stream_id, key)` on the rows that it read, so the stream id must not
change while it runs.

## Tests

`tests/test_anonymize_sample.py`:

- The head id in the output is a UUIDv7 whose moment is the earliest
  `recorded_at` of the output events. The test seeds a session in 2005,
  so that moment is before `FIXED_EPOCH` and differs from the fallback.
- Each output event names that head as its `stream`.
- The head id differs from the source head id.
- The prune test asserts one head in the output. Its old assertion, that
  no outsider stream id is in the output, passes whatever the prune does
  once the head is re-minted.

The `TODO(#1454)` in `anonymize_sample.py` goes.

## The fixture

`games/fixtures/sample.yaml.gz` is generated again from the 2026-10-02
post-deploy dump, which is at migration 0036, with
`make anonymize-sample USER=<owner>`. That is seed 42, no
`--scrub-devices`, and no name overrides, as for the 2026-10-01 fixture.
The tests that read the fixture are the gate:
`tests/test_library_commands.py`, `tests/test_uuid_identity_audit.py`
and `tests/test_external_references.py`.
