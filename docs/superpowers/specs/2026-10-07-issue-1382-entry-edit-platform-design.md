# Bulk Edit states a platform on many copies (#1382)

Part of the [Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).

## The field

The `entry.edit` act (`games/bulk_entry_edit.py`) states a platform,
an access, a format and a note. The platform field is first. Its
order matches the preview columns.

The field is a platform picker inside an `UnsetWidget`. An empty field
keeps the platform. The ⊘ toggle states Unspecified: a Release with no
platform. The picker has no create row and no +. A new platform has no
Release, so every row would refuse.

`EntryEditStatement.platform` holds a `StatedPlatform` or `None`.
`StatedPlatform(None)` is Unspecified. `None` keeps. The wire key is
`platform`. A statement without the key decodes.

## The Release of each row

A statement names a platform. A copy names a Release. Each game has
its own Releases, so each row finds its Release when it runs.
`release_on_platform` (`games/reads/releases.py`) gives the answer:

1. The copy's Release is on the platform. The answer is that Release.
2. Else the candidates are the game's live Releases on the platform,
   on a live platform, in Editions of the copy's Edition kind.
3. The copy's own Edition holds candidates: those are the set. Else
   all candidates are the set.
4. One Release in the set is the answer. None or several refuse.

The kind rule keeps a copy on a prerelease Edition off a full
Edition, and the reverse. The copy's `access` has no effect.

The row states its Release in one `DescribeEntry` dispatch with the
other facts. Step 1 also states the Release. A row that runs again
under its key must give the same fingerprint, or the dispatcher
answers `IdempotencyKeyMismatch`.

## Refusals

A refusal is a `CommandRejected` in `answered`. The runner logs the
row and continues. The tally keeps each sentence once, so a sentence
names no game:

- `PLATFORM_REMOVED`: the platform has a removal mark. The batch runs
  after the press, so each row reads the mark again.
- `NO_RELEASE_ON_PLATFORM`: no candidate. The sentence gives no
  remedy, because a shared game takes no Release.
- `SEVERAL_RELEASES_ON_PLATFORM`: several candidates. The copy's own
  edit form picks one.

The act never makes a Release.

## Undo

`entry_fact_changes` (`games/reads/entry_facts.py`) reads the release
fact from `libraryentry.created` and `.release_changed`. It parses the
`id` of the recorded Reference. The Undo states the earlier Release
with the other facts in one dispatch. A Release with a removal mark
refuses the row.

## Limits

A session or a record keeps the Release it names. After a move, no
live copy can hold that Release. The per-copy edit form does the same.
