# Name retention's tombstone column for what it is

Issue [#937](https://github.com/KucharczykL/timetracker/issues/937). #653 and
#669 give the tombstone. #675 waits for the name this issue frees.

## The rename

Retention's whole vocabulary takes the word tombstone.

| Now | After |
| --- | --- |
| `Game.archived_at`, `Platform.archived_at`, `Device.archived_at` | `tombstoned_at` |
| `Retirement.ARCHIVED = "archived"` | `Retirement.TOMBSTONED = "tombstoned"` |
| `archive_or_delete()` | `tombstone_or_delete()` |
| `ArchivableQuerySet` | `TombstonableQuerySet` |

The docstrings, the comments and the prose take the same word.
`Retirement.DELETED` keeps its name.

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

The rename stops at the column in no place. `archive_or_delete()` is the act
itself. If it kept the word, it would become the one thing named "archive" that
does not archive, which is the defect this issue removes.

`Retirement.DELETED` stays because the row really was deleted. "Purge" is
already the whole-library delete, thus it is not a substitute.

## The migration

There is no new migration. `0027_archive_catalog_rows.py` is edited in place:
three `AddField` names and four `AddConstraint` conditions take the new word.
The file becomes `0027_tombstone_catalog_rows.py`, and the dependency string in
`0028_playergame.py` follows it.

**The column has never existed.** The only durable database stops at
`0022_external_references`, and `information_schema` shows no column of either
name. Migrations `0023` to `0031` are the event work, and no deployment has run
them. Thus `archived_at` holds no data anywhere, and a `RenameField` would
rename a column that no live schema has.

This is the one condition under which a migration is rewritten. A migration is
otherwise a record of what occurred, and `0027` has occurred nowhere.

**A developer database that already applied `0023` or later is now wrong.** It
holds a column named `archived_at` while the migration state claims
`tombstoned_at`, and no command detects the difference. Drop that database and
migrate again.

**Do not reach for `make makemigrations` to produce a rename instead.** That
target passes `--noinput`, the non-interactive questioner answers no to every
rename question, and the autodetector emits `RemoveField` and `AddField`
in place of `RenameField`.

## Verification

The gate is the full `make check`. The drift guard proves that the models and
the edited `0027` agree, and a fresh `make migrate` proves that the edited file
applies.

**Grep for `archived_at`, and for `Archiv`.** One hit is correct:
`tests/test_projection_model.py`. Any second hit is a missed reference.

## Scope

String lookups carry most of the risk. mypy and ruff cannot see a field name
inside `filter()` or inside an exclusion set.

- `games/models.py` — the three field declarations; `TombstonableQuerySet` and
  its `alive()`; `PlatformQuerySet`; `Device.objects`; the four partial unique
  constraints and their comments. Also `EditionQuerySet` and `ReleaseQuerySet`,
  which subclass `models.QuerySet` and spell the lookup across a relation:
  `game__archived_at__isnull` and `edition__game__archived_at__isnull`. A rename
  of the field alone does not reach those four methods.
- `games/retention.py` — the enum member and its value, the function name, the
  stamping update and the docstrings
- `games/forms.py` — `exclusions.discard("archived_at")`. The line does not hide
  the column; `editable=False` does. The line puts the column back into
  constraint validation, because Django skips a conditional constraint whose
  condition names an excluded field.
- `games/views/retirement.py`, `games/signals.py`, `common/import_data.py`,
  `games/commands/playergame.py` — the import, the call, and three comments
- `docs/event-retention.md` — the prose, the `ARCHIVED` table row, and the
  headings "What archiving does" and "Where an archived row is not visible"
- `CLAUDE.md` — one line in the Architecture section that points at the Naming
  section below
- `tests/test_retention.py`, `tests/test_reference_reconciliation.py`,
  `tests/test_playergame_command.py`, `e2e/test_retention_confirmation_e2e.py`
- `tests/test_archived_rows.py` — also becomes `tests/test_tombstoned_rows.py`

`tests/test_library_form_isolation.py` needs no edit and is the guard for the
`games/forms.py` string. It makes a live duplicate and asserts that the form
refuses it. A forgotten rename there makes that test fail.

`tests/test_projection_model.py` declares its own `archived_at` on a synthetic
model. That column is not this one and does not change.

Every specification older than this one keeps its wording. A record of what the
project decided is not rewritten.

## The naming rule

`docs/event-retention.md` gains a Naming section. `CLAUDE.md` gains one line
that points at it.

One act takes one verb. The event type, the command and the projection column
all use that verb. The charter states the rule: deletion is domain-specific and
not one generic switch.

The column names the act in the past participle: `<act>_at`, and a name for what
the act touches can come first. It is a nullable `DateTimeField`, and null is
the live state. Thus `tombstoned_at`, `archived_at`, `voided_at`,
`access_ended_at`.

A fact about the world and a retraction of a record are two acts, thus they take
two verbs. #721 records an end of access and #727 records a refund. Both are
facts. #727 also records a void and #694 records a deletion. Both are
retractions.

`Retirement` is outside the rule. The rule governs an event, a command and a
column, and retention has none of the three: the enum reports which of two
outcomes a delete had. A hard delete leaves no row and thus no column, so
`deleted_at` on a projection always means the reversible act.

`Purchase.date_refunded` is older than the rule. #727 owns the decision to align
it.

## What does not change

The behaviour does not change. The same rows stay, and the same rows stay
hidden. No person reads the word "archive": `retention_message()` says that the
record "is kept out of sight rather than deleted".

## Order and reversibility

This issue merges before #675. It adds no migration, thus it does not collide
with the `0032` that #675 adds. It does edit `games/models.py` and
`games/commands/playergame.py`, thus #675 rebases.

#675 renames its own column by the same route. Its `0032` is also unapplied, so
`hidden_at` becomes `archived_at` in that file rather than in a second
migration.

A revert is the commit. No database has to move.

## Out of scope

`PlayerGame` keeps `hidden_at` here. #675 renames its own column to
`archived_at` after this issue.
