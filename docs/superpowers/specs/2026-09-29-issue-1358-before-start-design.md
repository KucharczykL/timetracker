# Sessions before their playthrough's start

Issue #1358. The Library page's Playtime section counts "Outside dates" and
says nothing about what the count means or how to fix it. This design splits
that one question into two, keeps a count only for the one that is a
contradiction, and says what to do about it.

## Two questions, not one

`outside_playthrough_dates` (#717) selects a session whose `effective_day` is
below its run's `started_lower` or above its `completed_upper`. The two sides
mean different things.

**Before the start is a contradiction.** A session proves its run had started
(overhaul charter, "Mandatory, quiet playthroughs"). A session dated before
the run's stated start means one of these is so:

- the session belongs to an earlier run nobody recorded;
- the session's day is wrong;
- the run's start is wrong.

**After the completion is not.** A run's completion states that the main
objective was completed, not that the run ended. Play after it on the same run
is post-game play, and the row is right as it stands: same run, completion
date intact. Legacy data holds a few replays among these rows, because a
`PlayEvent` could only mark a completion and a later replay had no run of its
own. Those are found once and moved; no count needs to keep asking.

The 2026-09-28 dump states the split: 113 sessions over 29 runs are
outside. 102 are after the completion and 11 before the start. Every one of
the 29 games holds exactly one run, so no existing run covers any of the 113.

## The fields

`PlayerSessionFilter` loses `outside_playthrough_dates` and gains two
`BoolCriterion` fields with handlers:

| Field | Label | True selects |
|---|---|---|
| `before_playthrough_start` | Before start | `effective_day < playthrough__started_lower` |
| `after_playthrough_completion` | After completion | `effective_day > playthrough__completed_upper` |

Each is one side of the old handler. False is the plain negation, and Django's
`IS NOT NULL` guard on a negated column comparison keeps a session whose run
states no bound on that side in the False answer. That is the property #717
pinned for the two-sided field, and each field keeps it for its own side. A
bound column is the widest the endpoint permits, so a start stated as `2022`
flags no day in 2022.

`outside_interval_handler` in `common/criteria.py` has one caller. It becomes
`beyond_bound_handler(day_field, bound_field, side, *, unless=None)`, where
`side` is a `BoundSide = Literal["below", "above"]` alias. True answers
`day < bound` or `day > bound`, less the `unless` rows; False is the plain
negation, so an `unless` row answers False. That is the shape the two-sided
handler has today, cut to one side. The two fields call it; nothing else did.

Both fields pass `unless=PRERELEASE_PLAY` (`games/reads/prerelease_play.py`),
as `outside_playthrough_dates` does. Play on a prerelease Edition is not the
run's play, so it is never before the run's start or after its completion. A
session that names no Release still counts. `PRERELEASE_PLAY` is a constant,
not the owner's `SHOW_PRERELEASE_PLAY` setting, so neither field reads that
setting.

The old key is removed, not aliased. `from_json` refuses a key it does not
know. The session list reads its filter through `apply_structured_filter`,
which fails open: a stale link shows the whole list and the toast "Ignored
invalid filter". The bulk runner and the preset save refuse it outright. That
is the list's rule for every unknown key, and this change adds no exception.
`OperatorFilter.renamed_fields` renames a key that maps onto one new key, as
`ended` became `completed`. The old key here maps onto two keys with a
different meaning, so a rename would widen a stored filter in silence, and the
key is refused instead. The 2026-09-28 dump holds no preset naming it. A fresh
dump is checked again before deploy, because the facet has offered Presets
since it shipped.

Both fields replace the old one in `QUICK_FACETS["sessions"]`, in its place:
Before start, then After completion. The quick bar degrades a filter to a
read-only pill when a key has no facet, and the card's link carries
`before_playthrough_start`.

## The count and the card

`games/reads/session_organization.py` renames `outside_dates_filter` to
`before_start_filter`, which states `before_playthrough_start=True`.
`OrganizationCounts.outside` becomes `before_start`. The Library page gives the
same object to `filter_url`, so the count and its link still compile one
predicate. A session after its run's completion is not counted.

`organization_counts` counts over `shown_sessions(library)`, which drops
prerelease play when the owner hides it. Before start excludes that play
through `unless` in every case, so its count is the same under both settings.
The count and its list therefore agree whatever the setting says.

The card reads **Before start**. Its link also states `sort=playthrough`, so
the session list groups the rows by game, then by run: the rows a person moves
together sit together. The sort lives where the panel builds the href,
`filter_url(before_start_filter(), sort="playthrough")`, not in the builder:
the builder is the predicate the count shares. No builder for "after completion" exists in this module,
because the Library page counts no such thing.

A card counting zero is not shown, as today.

## What the section says

When the Before start card shows, one paragraph follows the review's
paragraphs, in card order:

> Before start counts sessions dated before the start of their playthrough.
> A session can only happen once its playthrough has started, so either the
> session or the playthrough has the wrong date. If the sessions were an
> earlier attempt, select one game's sessions, choose Edit, and create a new
> playthrough for them. If a session's day is wrong, correct the session. If
> the playthrough started earlier than it says, correct its start.

The wording is final in review, not here; the three remedies and their order
are the design. The order puts the move first, because it is the remedy the
bulk runner already carries: bulk Edit's Playthrough picker creates a run
(#1080) and moves the selection to it (#1310). The picker searches and creates
under one game, and `refuse_another_game` refuses a move across games, so the
move is one game at a time. The link's `sort=playthrough` puts each game's rows
together.

The `Nothing to review` state speaks only about long typed-in totals. It shows
only where no card shows. Where the review counts zero and another card shows,
the review states nothing, so no "nothing" sits beside a count asking for
work. Today's panel has that clash with every card, Imported history included,
and a test pins it; this change inverts that test. A panel showing only the
Imported history card then carries the card and no prose.

## No new act

The three remedies need three different writes, and the cause is the person's
to judge: nothing in a row says which one applies. A bulk "start the run on its
earliest session's day" act is right for one cause only, and wrong for an
aborted earlier attempt, whose sessions would drag the run's start years back.
The counts are single digits. The move is already a bulk act; a start or day
correction stays one row at a time.

## Demo play

A session of a game's demo is often dated before the full game's run starts,
sometimes by a year. Correcting the run's start to cover it is wrong: a demo is
a different version of the game. A demo is an Edition of kind `prerelease`
(#1353), with a Release per platform, and a session is demo play through the
Release it names (#1354). Both fields exclude such a session through `unless`,
above.

A demo session that names no Release yet still counts under Before start. The
remedy is bulk Edit's Release field, which places it on the demo Release; never
a start correction. The field offers only Releases the library holds a copy
of, so the person adds a copy of the demo first.

## Tests

- `tests/test_filters.py`: the `dated_population` fixture stays.
  `OUTSIDE_CASES` splits into `BEFORE_START_CASES` and
  `AFTER_COMPLETION_CASES`. The two-sided class becomes one class per field,
  each with its true cases, its False answer, and the no-bound-keeps-the-row
  case for its own side. `TestTheDatesQuestionStatedTheLongWay` becomes one
  single field-comparison equivalence per field.
- `tests/test_session_organization.py`: the population's before-start row
  counts and its after-completion row does not (`before_start=1`); the
  link-parity test names `before_start_filter`. A new test counts the same
  population with `SHOW_PRERELEASE_PLAY` set to show and to hide, and the two
  counts are equal.
- `tests/test_session_reclassification_views.py`: the cards read `Before
  start`, and its rendered href carries `sort=playthrough`; the paragraph
  renders exactly when that card does; `Nothing to review` renders only where
  no card does, so `test_the_paragraphs_give_way_when_nothing_waits_for_review`
  is inverted.
- `tests/test_quick_filter_bar.py`: `RunFacetsTest`, the editable test and
  `FacetOrderTest` name the two new keys.
- `e2e/test_quick_filter_e2e.py`: the applied-facet test names
  `before_playthrough_start`. The sessions bar goes from seven facets to
  eight, so the width-dependent priority test's row count and overflow list
  are measured again, not loosened.
- `tests/test_session_release.py`: the demo test states both fields. A
  session on the demo Release answers False for each, a session on the game's
  Release and one naming none answer True for Before start, and
  `organization_counts(...).before_start == 2`.
- A stored filter naming `outside_playthrough_dates` is refused with
  `FilterError`.

## Documents

`CLAUDE.md`'s `PlayerSessionFilter` paragraph names the old field and handler
and is rewritten. Every older spec naming the old key (#717, the
selectable-tables wave, #1254, #1354, #1361, the Access and Purchases wave)
stays as a record of what it decided. Only the two that define the field, #717
and the selectable-tables wave, get one line pointing here.

## Out of scope

- A per-run statement that post-game play was reviewed. The after-completion
  sweep is one pass over legacy data, and a facet is enough for it.
