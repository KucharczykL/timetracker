# Remove one Edition or one Release

An Edition and a Release read the parent Game today: `EditionQuerySet` and
`ReleaseQuerySet` both filter on `game__removed_at__isnull=True`, and neither
model holds a mark. That is right while a Game holds exactly one of each, because
there is then nothing to remove short of the Game.

[The one removal act](2026-08-29-issue-944-one-removal-act-design.md) states that
rule. This specification amends it, before #967 makes many of both.

The act is remove. [Vocabulary](../../vocabulary.md) refuses `archive` in the
domain sense and names `remove` in its place, and `make vale` holds it.

## The columns

Edition and Release each get a nullable `removed_at`, and each extends
`ReferencedRow`. Each joins `REMOVABLE_MODELS` in `games/removal.py` with a
builder in `tests/test_removable_models.py`, which fails until it has one.

Neither needs an `_AFTER_STAMP` entry. No signal recounts or recalculates
anything from an Edition or a Release.

One migration adds the two columns and one index for each, and reverses.

## A row is visible when no ancestor is removed

`alive()` on a Release reads three marks: its own, its Edition's, and its Game's.
`alive()` on an Edition reads two.

A child keeps its own mark, thus restoring a Game does not show a Release that a
writer removed separately.

A default Edition or Release is removed only when no live sibling can take the
mark. With a live sibling, the writer names the next default first. #967 owns
that rule and the verbs that state it; this specification owns only the mark.

## The reference kind

`catalog.release` joins the registry in `games/events/references.py` at
`Resolution.REQUIRED`. The retention guard of #653 then refuses to destroy a
referenced Release from the first day one can exist, rather than from the day
#690 first records one. A removed Release still resolves for replay, because a
removal is a mark and not a destruction.

`catalog.edition` stays out. No event names an Edition, and a reference kind with
no event states a convention rather than a rule.

A whole-library purge still completes, through `purging_library()`.

## This changes no current behaviour

Every Game still holds one default Edition and one default Release, and nothing
yet removes either. The columns are null on every row, and every existing query
answers what it answered.

## Boundary

No write service; #967 owns the verbs. No screen; #969 owns the confirmation and
the routes. No recovery screen; #795 owns restoring.
