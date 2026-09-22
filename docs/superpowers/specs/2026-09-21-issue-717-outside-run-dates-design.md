# Sessions outside their playthrough's dates

The conversion (#700) placed every legacy session on its game's sole run by
rule, and nobody was asked. On the reviewed dump 113 sessions on 39 runs are
dated outside the interval their sole run states, and one session sits in the
imported-history bucket. Neither population is findable: `PlayerSessionFilter`
states no word about the run a session names.

This issue states both questions in the filter grammar and counts both answers
on the Library page. No stored state. The facet is the suggestion; a row a
person leaves is right where it is.

## The kind field

`playthrough_kind` is a `ChoiceCriterion` over `FilterField("playthrough__kind")`,
labelled `Playthrough`. It is a plain lookup, not a handler: `kind` is a real
column one to-one hop away, so the widget reads the model's own choices, as
`timing_mode` does. It states no `search_url`, which belongs to a column whose
values are not an enum. The criterion is never null, because a session's run is
never absent.

`games/bulk_reclassification.py` states that the bucket "is told apart by its
run's kind, which `PlayerSessionFilter` does not carry". It carries it now, and
that sentence and the `#:` comment beside it are restated. The act's scope does
not move: an act is its own base narrowed by the statement's filter, so a field
the grammar gains widens nothing.

What it does close is the review link. `review_filter()` states the timing and
the length; `reviewable_sessions` states those and the kind, and the list's own
base keeps bucket rows, so the link names rows the review does not offer. The
link states the kind as well, and the two agree.

The label is `Playthrough`, not `Kind`: the same bar carries `Timing`, which is
the session's own word, and two one-word labels beside each other would both
read as the session's.

## The dates field

`outside_playthrough_dates` is a `BoolCriterion` with a handler and no column of
its own, the shape `is_running` already has. True where the session's
`effective_day` lies before `playthrough__started_lower` or after
`playthrough__completed_upper`; false is that Q negated, as `is_running`
negates its own.

The two generated bound columns are the widest interval the endpoint admits, so
a run dated only `2022` flags no day inside 2022. An endpoint the run does not
state is unbounded on its side: a run that states a start and no completion
answers the question its start can answer, and a run that states neither is
never flagged.

The negation is safe, and not obviously so. A comparison against a nullable
column is NULL where the column is, and `NOT NULL` is NULL, which would drop
every undated run's sessions out of both answers. Django does not leave it
there: a negated lookup whose right side is a column carries an `IS NOT NULL`
guard the ORM adds itself, so the No answer holds every session of every
undated run. The handler therefore states one Q and negates it, and a test
pins the No answer over a run that states no endpoint — the rule lives in the
ORM, so this codebase states what it depends on.

The handler is a factory beside `temporal_interval_handler` in
`common/criteria.py`: a day column against two bound columns, which any
projection with a stated interval can reuse.

A bucket states no endpoint today, so no bucket row is flagged, and the kind
field is how those rows are found. Nothing in the domain holds that: the
endpoint commands resolve through `_live_run`, which reads removal marks and no
kind, and only the API's `_writable_runs` and the read layer's `library_runs`
keep a bucket out of reach. A dated bucket would join the Yes answer, correctly.

## The long way round

The grammar already asks this question without the field. `effective_day` is a
comparable generated column, `playthrough__started_lower` is one to-one FK hop,
and `_comparison_relations` offers every concrete foreign key, so a field
comparison states one clause and an `OR` of two states both. Its NULL rule is
strict and two-valued, which is the same rule stated above.
`PlayerSession.comparison_through` needs nothing: it names multi-segment paths,
and this is one hop.

So the field is a shorthand, not a new power — as `is_running` is shorthand for
a timed row with no end, both of which the grammar states on their own. The
shorthand earns its place at the top of the list, where the question is one
press. A test pins the long way, so the capability is stated rather than
accidental.

The long way is not wider in every direction. A field comparison states a
column against a column under `raw`, `date` or `year`, and no offset: the
builder states a day after a run's completion, never a day thirty days after
it. An interval offset is nobody's issue yet.

## Both are facets

Both fields join `QUICK_FACETS["sessions"]`. This is not decoration:
`is_quick_editable` degrades the whole bar to the read-only pill when a filter
names a key no facet holds, so a link carrying either field would land on a bar
the person cannot edit, one press from the organizer's own next step, which is
to narrow to one game. Both kinds pass the bar's own check without a modifier
test, which it makes for string and number fields alone.

## The counts

`games/reads/session_organization.py` states each filter once and counts
`library_sessions(library)` through its `to_q()`, under
`filter_query_context_for_library(library)`, as
`games/reads/playthrough_completions.py` does. Neither filter names a relation
today; the context is what keeps that true if one ever does. The Library page
links the same object through `filter_url`, so the number and the link compile
one predicate.

## The cards

The Library page's Playtime section leads with a `StatisticGrid` of three:

| card | counts | links to |
|---|---|---|
| To review | the review population | the session list, review filter |
| Imported history | sessions whose run is the bucket | the session list, kind filter |
| Outside dates | sessions outside their run's dates | the session list, dates filter |

A card counting zero is not rendered. The review's two paragraphs stay below
the grid as the first card's explanation, and its "See these sessions" button
goes, because the card is now the link. Where the review counts zero, its
paragraphs give way to today's `Nothing to review` empty state, which is what
the section shows now and what a test pins. Where all three count zero, the
grid is absent and that empty state is the whole section.

Each card's link lands on a list that spans games, and #715's Playthrough
column shows only while the filtered rows name one game. So a person sees the
flagged rows first and the run each names after narrowing. The card answers
"how many, and which rows"; the organizer answers "on which run", one facet
later.

## Verification

Built cases, on the filter:

- a day before a stated start, and after a stated completion;
- a day inside the interval;
- a run stating a start alone, and a completion alone;
- a run stating neither, in both answers, which is the ORM guard this design
  depends on;
- a bucket row, in both answers;
- an imprecise endpoint, where the day lies inside the widest bounds;
- the same rule stated the long way, as an `OR` of two field comparisons;
- the filter's JSON round trip, and the quick bar's editability with each
  field present.

On the Library page: three cards with their links, a zero card absent, the
empty state where the review counts zero, and the review link naming the same
rows the review card counts.

Measured on the 2026-09-22 production dump, over 2,821 live sessions:

| rule | sessions |
|---|---|
| this one, any endpoint the run states | 113 |
| the wave review's, both endpoints stated | 113 |
| of those, on a game's sole live ordinary run | 113 |
| the imported-history bucket | 1 |

The flagged rows name 29 runs, not the 39 the wave record wrote.

The two rules answer one number here because of how the runs are dated. Of
870 live ordinary runs, 207 state both endpoints, 540 state a start alone,
none states a completion alone, and 123 state neither. Not one session falls
outside a start-alone run, because #1038 dated such a run from the earliest
day the library already held, so no session can precede it. The wider rule
therefore costs nothing today and answers the runs a later completion-alone
statement would create.

Full `make check`.

## What this moves

Three tests and one browser test name the button the grid replaces:
`test_the_library_offers_the_review` and
`test_the_session_list_carries_no_review_row` in
`tests/test_session_reclassification_views.py`, and the first press of
`e2e/test_session_reclassification_e2e.py`, whose link becomes the card, whose
accessible name is the count beside the label.
`test_the_review_filter_parses_and_stays_quick_editable` pins the review
filter's two keys and answers for three.

The docs sweep restates `games/bulk_reclassification.py`'s docstring and its
`#:` comment, and CLAUDE.md's `PlayerSessionFilter` paragraph, which lists the
filter's words.

## Follow-ups

- #1250 — a catalogue of named filters the preset picker offers, which the
  statistics links would name instead of carrying their JSON in a URL. A
  shipped filter takes a parameter, such as the year, which a saved preset row
  cannot, so the catalogue is not the preset table.
- #1249 — the quick bar merging its facets into a filter it cannot state whole,
  rather than refusing to show them. The bar replaces the filter today, which
  is why showing a facet over an advanced filter would drop the rest at the
  next Apply. Merging keeps every key no facet names and states beside the
  facets that a condition it does not show is active. Both of this issue's
  fields are facets, so neither waits on it.

## What the wave review said, and what changed

The wave review names one new field; there are two, because the bucket count
needs a link and no field stated a run's kind.

It names the rule as a run "that states both" endpoints; the rule here judges
each endpoint the run states, so a session a year before a stated start is
asked about. Its figure of 113 belongs to a third rule, the sole run's stated
interval, and is measured again under this one.

It names two counts in the Playtime section; there are three cards, because the
section already counts the review in prose and three numbers in two voices read
worse than three cards.
