# The day a request is on

A library counts days in one zone, its calendar's `day_zone`. Every
day-grained reader asks that calendar. A day from `timezone.localdate()` is
the viewer's display zone. The two zones name different dates for some hours
of each day.

## The readers

`calendar_today(library)` states the day. The navbar's windows, the landing
redirect and the published year all ask it. `available_stats_year_range`
takes the day as an argument, so `common/` holds no `games` import. A viewer
with no library has no calendar to ask. The navbar computes no day for such a
viewer, because both of its figures are zero.

## One statement for the user and the library

`LibraryModelBackend` loads the user with `select_related("library")`. The
library is a reverse one-to-one, so one statement gets both rows. This
removes the statement that read the library alone.

The calendar read replaces that statement. The Library page costs 23 queries.

A session stores the path of the backend that made it. Django refuses a
session that names a backend it does not list. Thus this backend ends the
sessions that are older than itself. Each person signs in one more time.

## One read for one request

Two context processors ask for the day. `request_calendar_today` reads the
calendar one time and keeps the answer on the request.

The cache is on the request, not on the library. A change of
`DISPLAY_TIME_ZONE` restates the calendar in the view. The view runs before a
context processor. A library object stays the same across that write, but a
request does not.

`compute_stats` does its own read. It takes a library, not a request.

## The guard

`annotated_for_filtering` refuses a second clock on one queryset. It sees
only that queryset. A render, an act or a helper is out of its reach.

`tests/test_calendar_clock_guard.py` reads the syntax tree of `games/`,
`common/`, `timetracker/`, `contrib/`, `scripts/`, `tests/` and `e2e/`. It
refuses a day that comes from the process clock or the active zone:

- `localdate` or `localtime` with no zone argument.
- `date.today`, `datetime.today` and `date.fromtimestamp`.
- A day field (`.date()`, `.year`, `.strftime` and others) of a `now()` that
  has no zone. The guard follows the instant through arithmetic,
  `.replace()`, `.astimezone()` with no zone, and a name in the same scope.
- One of these clock functions named but not called.

`None`, `get_current_timezone()`, `get_default_timezone()` and
`settings.TIME_ZONE` do not state a zone. The report names the file, the line
and the qualified function.

An exception is an `ALLOWED_FUNCTIONS` entry. The key is an
`AllowedFunction(path, function)`. The value is an `Exemption(reason, reads)`.
A count that does not agree with the walk is an error.

A test states a fixed day or seeds at `library_noon(library)`. The suite sets
the process zone to a date that is not the default calendar's date. A test
that reads the process clock thus fails at every hour.

The guard cannot see an ORM `__date` lookup. Such a lookup reads the active
zone.
