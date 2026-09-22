# Sessions outside their playthrough's dates

`PlayerSessionFilter` states two facts about the run a session names.

## The run's kind

`playthrough_kind` is a `ChoiceCriterion` over `playthrough__kind`, labelled
`Playthrough`. It is a plain lookup, not a handler: `kind` is a column one hop
away, so the widget reads the model's own choices and the field states no
`search_url`. The criterion is never null, because a session always names a
run.

The field makes the review link agree with the review. `reviewable_sessions`
refuses a row in the imported-history bucket, and the session list keeps such
rows, so `review_filter()` states the kind too.

A new filter field widens no act. An act is its own base, narrowed by the
filter in the statement.

## The days a run's dates do not cover

`outside_playthrough_dates` is a `BoolCriterion` with a handler and no column
of its own, the shape `is_running` has. True selects a session whose
`effective_day` is below `playthrough__started_lower` or above
`playthrough__completed_upper`. False is that expression negated.

The two generated bound columns give the widest interval an endpoint permits,
so a run dated `2022` flags no day in 2022. An endpoint a run does not state is
unbounded on its side: a run stating a start alone answers on that start, and a
run stating neither is never flagged.

Django adds an `IS NOT NULL` guard to a negated lookup whose right side is a
column. The False answer therefore keeps every session of a run that states no
date. A test pins that answer, because the rule lives in the ORM.

The handler is `outside_interval_handler` in `common/criteria.py`: a day column
against two bound columns, which any projection with a stated interval reuses.

## The counts, and why both fields are facets

`games/reads/session_organization.py` states each filter one time.
`organization_counts` counts `library_sessions(library)` through each, under
`filter_query_context_for_library`. The Library page gives those same objects
to `filter_url`, so a count and its link compile one predicate.

Both fields are in `QUICK_FACETS["sessions"]`. The quick bar degrades to a
read-only pill when a filter names a key no facet holds, and these links carry
both keys.

## The cards

The Library page's Playtime section shows a `StatisticGrid` of three cards: To
review, Imported history, Outside dates. Each links to the session list. A card
counting zero is not shown. The review's paragraphs stay below the grid; where
the review counts zero, the `Nothing to review` state replaces them; where all
three count zero, the grid is absent.

## The same question, stated by hand

`effective_day` and both bound columns are comparable, so an `OR` of two field
comparisons answers the same rows, which a test pins. The field is a shorthand,
as `is_running` is.

A field comparison states no offset, so the builder cannot say "thirty days
after the completion". No issue asks for one.

## Follow-ups

- #1249 — the quick bar merges its facets into a filter it cannot state whole,
  instead of hiding them.
- #1250 — a catalogue of named filters, which the statistics links would name
  instead of carrying their JSON.
