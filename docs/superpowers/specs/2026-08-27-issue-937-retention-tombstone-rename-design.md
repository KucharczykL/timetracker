# Name retention's tombstone column for what it is

Issue [#937](https://github.com/KucharczykL/timetracker/issues/937). #653 and
#669 give the tombstone. #675 waits for the name this issue frees.

## The rename

`Game`, `Platform` and `Device` each hold `archived_at`. The column becomes
`tombstoned_at`. `Retirement.ARCHIVED` becomes `Retirement.TOMBSTONED`.

Three `RenameField` operations do the work. A rename keeps the column and its
values, thus no data step occurs.

The word also changes in prose. `docs/event-retention.md` says "archived row"
throughout and becomes "tombstoned row".

## Why the name changes

The word names two different acts.

A player archives a game. The charter gives that act the events
`PlayerGameArchived` and `PlayerGameRestored`. The player chooses it, and the
player can undo it.

Retention does something else. `archive_or_delete()` runs on a delete. A
`REQUIRED` reference makes the delete impossible. The function then removes
every other row and stamps the column. The row that stays is a husk that the
event log needs. Nobody archived it, and no screen offers it back.

The charter calls that husk "an archived record or merge tombstone" and thus
gives both words. The catalog wave specification, #653 and #669 all say
tombstone. Retention takes the word that only fits it, and the player act keeps
the word that describes a choice.

`Retirement.DELETED` keeps its name. The row really was deleted. "Purge" is
already the whole-library delete, thus it is not a substitute.

## The naming rule

`docs/event-retention.md` gains a Naming section. `CLAUDE.md` gains one line
that points at it.

One act takes one verb. The event type, the command and the projection column
all use that verb. The charter states the rule: deletion is domain-specific and
not one generic switch.

The column is `<verb>_at` and is a nullable `DateTimeField`. A null column is
the live state. `Purchase.date_refunded` is older than the rule and keeps its
name.

A fact about the world and a retraction of a record are two acts, thus they take
two verbs. #721 records an end of access and #727 records a refund. Both are
facts. #727 also records a void and #694 records a deletion. Both are
retractions.

## What does not change

The behaviour does not change. The same rows stay, and the same rows stay
hidden. No person reads the word "archive": `retention_message()` says that the
record "is kept out of sight rather than deleted".

## Scope

- `games/models.py` — three field declarations, `alive()`, `for_library()`,
  `visible_to()`, and four partial unique constraints
- `games/retention.py` — the enum member and the stamping update
- `games/forms.py` — the exclusion that keeps the column off every form
- `games/commands/playergame.py` — the catalog lookup filter
- `docs/event-retention.md` — the references and the new Naming section
- `CLAUDE.md` — one pointer line
- `tests/test_retention.py`, `tests/test_playergame_command.py`,
  `e2e/test_retention_confirmation_e2e.py`
- `tests/test_archived_rows.py` — also becomes `tests/test_tombstoned_rows.py`

`tests/test_projection_model.py` declares its own `archived_at` on a synthetic
model. That column is not this one and does not change.

`games/migrations/0027_archive_catalog_rows.py` keeps its name. A migration is
a record of what occurred, thus it is not rewritten.

## Verification and reversibility

The gate is the full `make check`. The migration drift guard proves that the
models and the migration agree. The retention tests prove that the same rows
stay. A grep for the old name proves that no reference remains.

A revert is the commit and a migration back.

## Out of scope

`PlayerGame` keeps `hidden_at` here. #675 renames its own column to
`archived_at` after this issue. `Purchase.date_refunded` waits for #727 or a
later purchase slice.
