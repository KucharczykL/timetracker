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
`beyond_bound_handler(day_field, bound_field, side)`, where `side` is a
`BoundSide = Literal["below", "above"]` alias. It answers `day < bound` or
`day > bound`, and False is the negation. The two fields call it; nothing else
did.

The old key is removed, not aliased. `from_json` refuses a key it does not
know. The session list reads its filter through `apply_structured_filter`,
which fails open: a stale link shows the whole list and the toast "Ignored
invalid filter". The bulk runner and the preset save refuse it outright. That
is the list's rule for every unknown key, and this change adds no exception.
The dump holds no preset naming the old key.

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

The card reads **Before start**. Its link also states `sort=playthrough`, so
the session list groups the rows by game, then by run: the rows a person moves
together sit together. No builder for "after completion" exists in this module,
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
work. Today's panel has that clash with the Outside dates card; this change
ends it.

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
a different version of the game. The Access and Purchases wave owns the answer.
The charter lists `Demo` among `LibraryEntry` access kinds (#719–#722), and a
session keeps the Release it used. Until then such a session counts under
Before start, and a person may move it to a run of its own.

## Tests

- `tests/test_filters.py`: the `dated_population` fixture stays.
  `OUTSIDE_CASES` splits into `BEFORE_START_CASES` and
  `AFTER_COMPLETION_CASES`. The two-sided class becomes one class per field,
  each with its true cases, its False answer, and the no-bound-keeps-the-row
  case for its own side. `TestTheDatesQuestionStatedTheLongWay` becomes one
  single field-comparison equivalence per field.
- `tests/test_session_organization.py`: the population's before-start row
  counts and its after-completion row does not (`before_start=1`); the
  link-parity test names `before_start_filter` and reads `sort=playthrough`.
- `tests/test_session_reclassification_views.py`: the cards read `Before
  start`; the paragraph renders exactly when that card does; `Nothing to
  review` renders only where no card does.
- `tests/test_quick_filter_bar.py`, `e2e/test_quick_filter_e2e.py`: the facet
  lists and the applied-facet test name the two new keys.
- A stored filter naming `outside_playthrough_dates` is refused with
  `FilterError`.

## Documents

`CLAUDE.md`'s `PlayerSessionFilter` paragraph names the old field and handler
and is rewritten. The #717 and selectable-tables wave specs stay as records
of what those issues decided, each with one line pointing here.

## Out of scope

- Demo play (above), handed to the Access and Purchases wave.
- A per-run statement that post-game play was reviewed. The after-completion
  sweep is one pass over legacy data, and a facet is enough for it.
