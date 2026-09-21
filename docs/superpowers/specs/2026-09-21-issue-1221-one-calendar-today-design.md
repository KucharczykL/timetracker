# The day a request is on

Issue #1221. The last readers #1217 left on the viewer's clock, and the
query that pays for moving them.

## The problem

#1047 settled that a library counts days in one zone, and #1217 moved every
day-grained reader and act onto it. Four readers stayed behind, all of them
in `games/views/general.py` and `common/time.py`:

- `model_counts` builds the navbar's today and last-7-days windows from
  `localdate()`, then sums `effective_day`, which is counted on the
  calendar. For the hours the viewer's display zone and the calendar name
  different dates, both figures are a day out.
- `index` redirects to `localdate().year`, `global_current_year` publishes
  the same year to every page, and `available_stats_year_range` offers the
  years the stats picker lists. Year granularity, so they disagree with the
  calendar only across New Year's Eve, but they disagree for the same reason.

What kept `model_counts` on the viewer's clock is where it sits. It is a
context processor, so a `LibraryCalendar` read there happens on every page.
Measured on the Library page, the read costs one query and the page costs 23.

## The decision

A request loads its library once, in the query that loads its user, and the
freed query buys the calendar read. The navbar's budget does not move.

`ModelBackend.get_user` loads the user by primary key. `library` is a reverse
one-to-one, so `select_related("library")` fetches both rows in one query.
Measured: user and library in a single statement, against two today. Every
authenticated request pays one query fewer, whether or not it renders a
navbar, so the calendar read the navbar adds is already paid for.

A session stores the path of the backend that made it, and Django refuses a
session naming a backend it no longer lists. The deploy that lands this one
therefore ends every session made before it, and each person signs in again
once. Listing the former backend beside it would avoid that, at the price of
carrying a second way to load a user for as long as the oldest session lives.

## What each reader asks

| Reader | Asks |
|---|---|
| `model_counts` | `calendar_today(library)`, and nothing when no library |
| `index` | `calendar_today(library).year` |
| `global_current_year` | the library's year; `localdate().year` for a viewer with no library |
| `available_stats_year_range` | its caller, which states the day |

`common/time.py` holds no `games` import and gains none. The year range takes
the day as an argument, and `compute_stats`, which already holds the library,
states it.

The anonymous branches are the only clocks left. A viewer with no library has
no calendar to read, and the navbar figures such a viewer sees are zero, so
`model_counts` computes no day at all there.

## The guard

`annotated_for_filtering` refuses a second clock on one queryset, and every
reader this issue moves lives where that guard cannot look. A syntax-tree
walk, shaped like `tests/test_iterator_guard.py`, refuses a call to
`localdate`, `date.today` or `datetime.today` under `games/`, `common/`,
`timetracker/`, `contrib/` and `scripts/`. Two entries stand in its
allowlist: `games/reads/calendar.py`, the one place that states what today
means for a library, and `global_current_year`'s anonymous branch.

Tests are out of scope for the walk. A test states a day to compare against,
and pinning them would turn the guard into a rewrite of the suite.

## One read for one request

`calendar_day_zone` reads its row on every call, and two context processors
ask: the navbar for its window, the year publisher for its year. The answer
is cached on the request, by `request_calendar_today`, so a page reads the
calendar once.

The cache sits on the request rather than on the library instance because a
change of `DISPLAY_TIME_ZONE` restates the calendar, and it does so in the
view, which runs before a context processor asks. A library instance outlives
that write inside the same request; the request does not outlive it.

`compute_stats` keeps its own read. It takes a library, not a request, and a
reader that states its own scope is worth one statement on the one page that
calls it.

## Acceptance

- The navbar's today and last-7-days windows are the library's days, at every
  hour, not only outside the window where the defaults disagree.
- The Library page still costs 23 queries, and a request loads its user and
  its library together.
- No production module derives a day or a year from the process clock, except
  where no library exists to ask.
