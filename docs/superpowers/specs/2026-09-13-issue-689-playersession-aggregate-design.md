# The PlayerSession aggregate and its three timing modes

Issue [#689](https://github.com/KucharczykL/timetracker/issues/689). Parent
phase [#601](https://github.com/KucharczykL/timetracker/issues/601). Wave
review: [Session delivery wave](2026-09-12-session-wave-design.md). Census:
[#699](2026-09-12-issue-699-session-preflight-design.md).

`PlayerSession` is the third projection table and the third command family. It
follows `PlayerGame` and `Playthrough`: the primary key is the creation event's
`aggregate_id`, both `UUIDv7Field` defaults are opted out, the projector is the
only writer, and `removed_at` is the projector's mark, so the model is absent
from `REMOVABLE_MODELS`.

Every figure below was measured against the restored production dump of
2026-09-12 and against a throwaway table in the same PostgreSQL 18 cluster.

## What the probes settled

| probe | result |
|---|---|
| `GeneratedField` over `timezone(day_zone, started_at)::date` | Django compiles it; PostgreSQL accepts it, which is itself the proof the bound overload is IMMUTABLE |
| `UPDATE day_zone` on such a row | regenerates `effective_day` across a day boundary |
| NULL `day_zone` beside a stated instant | `effective_day` is NULL, so a constraint has to forbid the pair |
| CHECK reading a generated column | accepted, and refuses the offending row at write time |
| `(stated_day::timestamp) AT TIME ZONE 'UTC'` in a generated column | accepted; **without** the explicit cast PostgreSQL refuses the column, because `date → timestamptz` is STABLE |
| a discriminated union inside a strict payload | refuses a bad tag, an extra key, a missing key and a lax int; nested TypedDicts inherit `extra="forbid"` and `strict` from the parent config |
| the rebuild's diff | `(live.*) IS DISTINCT FROM (shadow.*)` — the whole row, generated columns included |
| zone columns, production | 2,736 of 2,807 rows state neither zone; the only zone ever stated is `Europe/Prague`; no row states two different ones; **56 rows state an end zone and no start zone** |
| day-zone delta, production | 124 sessions on another day, 10 in another month, 5 in another year |
| durations, production | no `duration_manual` carries sub-second precision; 1,024 start instants and 1,671 end instants do |
| timing verdicts, production | timed 2,663, duration_only 142, running 2, **corrected 0** |
| removed `PlayerGame` over a live `Game` holding live sessions | 0 rows |

## The three modes

`timing_mode` is a stated word, never a shape read off the row:

- **Timed** — an exact start, an optional end while running, no override. The
  duration is elapsed time.
- **Duration-only** — a written calendar day and a stated duration. No instants.
- **Corrected** — an exact start and end, plus an override that **replaces**
  elapsed time.

`PlayerSessionTimingMode` spells them `timed`, `duration_only` and `corrected`,
which is how `TimingVerdict` in `games/preflight/session.py` spells the three
verdicts `MODE_VERDICTS` names. A test asserts the two sets agree — against
`MODE_VERDICTS`, not against `TimingVerdict`, which holds three further verdicts
no mode admits.

### Corrected replaces; the legacy column added

This is the one place the new vocabulary reuses a legacy word for different
arithmetic, and the difference is unrecoverable if the conversion misreads it.
Legacy `Session.duration_total` is `COALESCE(end - start, 0) + duration_manual`
— the manual value **adds**. A Corrected `PlayerSession` states the whole
duration and its `effective_duration` **ignores** the elapsed interval.

So a converted Corrected row's `stated_duration` is the legacy row's
`duration_total`, never its `duration_manual`. #700 owns the conversion, but
#689 owns the sentence, because the mode's meaning is defined here.

Production holds no such row, so #704's strict-equality gate on restored
production data cannot catch a mistake here — the wave says the branch converts
nothing. But `SessionForm` exposes `timestamp_start`, `timestamp_end` and
`duration_manual` together, so the combination is reachable in the live product
today. Two consequences this issue states and later issues carry out:

- #700's conversion test asserts **arithmetic**, not spelling: for a synthetic
  legacy row of each verdict, `Session.duration_total == PlayerSession.effective_duration`.
- #702 either removes the form's "end plus manual" combination or renders it as
  a Corrected statement whose override is the total. It cannot keep meaning
  "add".

## The columns

```
id                 UUIDv7Field primary key, both defaults opted out
library            from ProjectionModel
playthrough        FK(Playthrough, RESTRICT, related_name="sessions")
device             FK(Device, RESTRICT, null=True)
timing_mode        CharField(choices=PlayerSessionTimingMode)
started_at         DateTimeField(null=True)
started_at_zone    CharField(64, null=True)
ended_at           DateTimeField(null=True)
ended_at_zone      CharField(64, null=True)
stated_day         DateField(null=True)
stated_duration    DurationField(null=True)
day_zone           CharField(64, null=True)
effective_day      GeneratedField, stored
effective_duration GeneratedField, stored
sort_instant       GeneratedField, stored
note               TextField
emulated           BooleanField
created_at         DateTimeField          -- the creation event's recorded_at
removed_at         DateTimeField(null=True, default=None)  -- #694 states it
```

**No column the creation event states carries a default.** `_required_columns`
exempts a defaulted column from the check that holds a handler to naming every
column it writes, and a timing column left unnamed is a null a rebuild would
insert. `removed_at` is the one exception, because #694 amends it.

`device` is `RESTRICT`, not the legacy `SET_NULL`: `SET_NULL` would change a
projection row from outside the projector.

`Meta.get_latest_by = "sort_instant"`, replacing legacy
`get_latest_by = "timestamp_start"`.

### Every column is derived from events, including the zone

The rebuild's diff compares whole rows, so a column changed outside the
projector is drift forever: `rebuild_projections --check` reports it, and
`swap_in` reverts it.

This binds the follow-up the wave files — restating a library's days when its
display zone changes. That restatement **is an act and needs an event**; it is
not a bulk `UPDATE`. Whether the event is one per session or one library-scoped
event the projector fans out over the library's rows is the follow-up's
decision; that it is an event is this issue's, because a `day_zone` written by
2,807 frozen events cannot be moved any other way.

### The three zones are three facts

`started_at_zone` and `ended_at_zone` say where the clock stood when each
endpoint was committed. They are stamped per endpoint — `finish_session` stamps
the end zone at the moment of finishing, which is why 56 production rows carry
an end zone and no start zone — they may legitimately differ (a session started
in Prague and ended in Tokyo, which `session_time_range` renders under the "own"
display preference and `tests/test_session_time_range_timezones.py` covers), and
NULL means not stated.

`day_zone` is a different fact: the zone the **library** counts days in.
Collapsing it into the endpoint zones would make "sessions this week" move with
the player's travel and make the navbar's midnight window depend on a row.

`day_zone` is NULL on a Duration-only row, and that row's day never moves again.
A written calendar day is zone-free by definition — the Journal already
specifies it that way — so a later restatement moves the Timed and Corrected
rows and leaves these alone, deliberately. The 142 legacy rows #700 converts
this way do have an instant; that instant is evidence, recorded in the event's
`source_metadata` as #1038 did, not a column the mode admits.

### The effective day

```sql
effective_day date GENERATED ALWAYS AS
  (COALESCE(stated_day, (timezone((day_zone)::text, started_at))::date)) STORED
```

In Django: `Coalesce(F("stated_day"), Cast(Func(F("day_zone"), F("started_at"),
function="timezone"), DateField()))`. That is the SQL Django emits, cast
included.

**`day_zone` is seeded from the viewer's display zone, and the caller states
it.** `TimezoneActivationMiddleware` wraps every request outside
`/api/settings/` in `timezone.override(DISPLAY_TIME_ZONE)`, so every day-grained
read already groups in the viewer's zone; production's one user holds
`Europe/Prague` while `TIME_ZONE` resolves to UTC. Seeding from
`settings.TIME_ZONE` would move 124 sessions to another day, 10 to another month
and 5 to another year, and #704's strict-equality gate would fail by exactly
that. The command takes the zone inside the timing statement rather than
resolving a preference itself, for the same reason it takes a run rather than
inferring one.

That costs the write path nothing: inside a request the zone is
`timezone.get_current_timezone_name()`, already activated by the middleware. It
is not a new control on a form, and #702 adds no zone picker for it.

One limit, stated because it cannot be fixed here: `timezone(text, timestamptz)`
is immutable but reads the interpreter's tzdata, so a tzdata update that changes
a historical rule does not regenerate stored values. Determinism holds within a
tzdata generation.

### The effective duration

```sql
effective_duration interval GENERATED ALWAYS AS
  (COALESCE(stated_duration, (ended_at - started_at), INTERVAL '0')) STORED
```

Duration-only and Corrected answer their stated duration; a finished Timed row
answers elapsed time; a running Timed row falls through to zero, which is what
legacy `duration_calculated` already coalesces to — and which makes a running
session indistinguishable from a finished zero-length one in any playtime sum.
`timing_mode` and a null `ended_at` are what tell them apart, and every read
that cares must say so.

This is not the `PlaytimeTotal` projection the wave dropped. That was an
aggregate over many rows, unable to serve sub-filtered reads; this is one row's
own fact, the twin of a column legacy already had, and without it #697, #702 and
#704 each repeat a three-branch CASE over a table whose CHECKs make the branches
total.

No generated column for elapsed time alone: a reader subtracts two instants, and
`timing_mode` says when they exist.

### The sort instant

```sql
sort_instant timestamptz GENERATED ALWAYS AS
  (COALESCE(started_at, (stated_day::timestamp) AT TIME ZONE 'UTC')) STORED
```

The explicit `::timestamp` is load-bearing: `date AT TIME ZONE 'UTC'` resolves
through the STABLE `date → timestamptz` cast and PostgreSQL refuses the column.
Django's `Cast(..., DateTimeField())` asks for `timestamptz` and hits exactly
that, so the expression states the naive cast itself, through a one-line `Func`
subclass beside the model.

It exists because ordering is not day-grained. `recent_session_resumes` keys on
`(timestamp_start, id)` and the session list sorts on the instant; keying on
`effective_day` instead would make the intra-day order the `id` order, which for
2,807 converted rows is the order the conversion happened to iterate. A
Duration-only row has no instant, so this column invents one — midnight UTC of
its written day — for ordering alone. It is never rendered and never compared to
a real instant; it is the total, non-null key `keyset_pages` requires.

### The constraints

Nine, each named for what it refuses. They exist because the migration is the
code most likely to write an impossible row, and it runs once over years of
data.

1. `playersession_timing_mode_known` — the word is one of the three. `choices`
   is not a database constraint, and the conversion writes this column.
2. `playersession_timed_columns` — Timed states `started_at` and `day_zone`, and
   states no `stated_day` and no `stated_duration`. `ended_at` is free: null is
   a running session.
3. `playersession_duration_only_columns` — Duration-only states `stated_day` and
   `stated_duration`, and states no instant, no endpoint zone and no `day_zone`.
4. `playersession_corrected_columns` — Corrected states `started_at`, `ended_at`,
   `day_zone` and `stated_duration`, and states no `stated_day`.
5. `playersession_end_after_start` — `ended_at` is null or not before
   `started_at`. Equal is admitted: a zero-length session is a correction
   somebody may legitimately state.
6. `playersession_duration_not_negative` — `stated_duration` is null or at least
   zero.
7. `playersession_zone_needs_its_instant` — `started_at_zone` is null unless
   `started_at` is stated, and `ended_at_zone` is null unless `ended_at` is. The
   review found the design without this one admits a Timed row carrying an end
   zone and no end.
8. `playersession_zone_not_blank` — neither endpoint zone is the empty string.
   An empty string is not a zone, and NULL already means unset.
9. `playersession_effective_day_stated` — `effective_day` is not null. It reads
   a generated column, which PostgreSQL permits and refuses on write. It is the
   backstop: any hole the others leave arrives here as a row with no day, and
   every day-grained read keys on this column.

**`day_zone` is deliberately absent from 8, because no constraint can reach it.**
A generated column is computed before any constraint runs, so a blank or unknown
`day_zone` answers `DataError: time zone "" not recognized` while `effective_day`
is being generated — measured, not assumed. `answered()` now catches that error
as a defect and says only that nothing was saved, so the command refusing an
unknown zone is still the only thing that can tell a person *which* zone was
wrong.

**The database admits a superset of what the command admits, never the
reverse.** A CHECK stricter than the command turns a forgotten refusal into an
`IntegrityError`, raised after the stream head is locked, which
`games/writes/answers.py` can only answer with "nothing was saved". That is why
constraint 6
stops at "not negative" while the command refuses a sub-second duration and a
zero-duration Duration-only row: those rules can tighten and relax without a
migration, and their failure mode is a sentence rather than a traceback.

### The indexes

- `(library, effective_day, id)` — the day-grained reads: the navbar's today and
  last-seven-days figures, the stats page's day and month grouping, and the year
  scope.
- `(library, sort_instant, id)` — the list order, `get_latest_by`, and the
  keyset key `recent_session_resumes` needs. `keyset_pages` requires fields
  lying in one index with a unique last field; `id` is the UUIDv7 primary key.
- `(playthrough, effective_day)` — the dormancy clock asks when one run was last
  played, which #702 narrows from the game to the run.

All three ship with the table, while it is empty.

## The event

One event type, `library.playersession.created`, aggregate type `playersession`.

The namespace follows `library.playergame.*` and `library.playthrough.*`: the
event namespace is the aggregate's model name, lowercased. The wave review names
no event type at all, and the `library.session.created` in
`games/events/vocabulary.py:31` is an illustrative comment in a type alias, not
a commitment — the comment is corrected to match. A mechanical rule is worth
more than a nicer-reading name in a vocabulary that can never be renamed:
`VersionNotUpcastable` refuses a version bump, and nothing rewrites a recorded
event type.

```python
class PlayerSessionCreatedPayload(TypedDict):
    playthrough: ReferenceId  # bare id, as PlaythroughCreatedPayload does
    device: Reference | None
    release: Reference | None  # reserved; always None until #719-#724
    timing: TimingPayload
    note: str
    emulated: bool
```

`playthrough` is a bare `ReferenceId` for the reason
`PlaythroughCreatedPayload.player_game` is: a REQUIRED `ReferenceKind` for a
projection would make replay read the live table before the first row, so a
rebuild of a library that lost rows would refuse to run. `device` is a captured
`Reference` of the registered kind **`device`** — the registry holds `device`,
`catalog.game`, `catalog.platform` and `catalog.release`, and no
`library.`-prefixed kind exists.

`release` is reserved from day one so ACCESS adds a consumer rather than a
field. It is a required key holding `None` because it exists from the first
recorded payload; a key added to an existing member *later* must be
`NotRequired`, since a version bump is refused. Those are two different
situations, not two rules.

`effective_time` on the creation event carries the session's day. It is the
envelope's field for what the player says happened, `TemporalValue` bottoms out
at day precision so the instant cannot go there, and #740–#743 and #748 would
otherwise open JSONB and branch on the mode to learn a date the envelope was
built to hold. It is derived from `day_zone` at statement time and, like every
recorded value, does not move when a later event restates the zone; the
projection's `effective_day` is the live answer.

`timing` is a discriminated union tagged on `mode`:

```python
TimingPayload = Annotated[
    TimedTimingPayload | DurationOnlyTimingPayload | CorrectedTimingPayload,
    Field(discriminator="mode"),
]
```

- `TimedTimingPayload` — `mode`, `started_at`, `started_at_zone`, `ended_at`,
  `ended_at_zone`, `day_zone`
- `DurationOnlyTimingPayload` — `mode`, `stated_day`, `duration_seconds`
- `CorrectedTimingPayload` — `mode`, `started_at`, `started_at_zone`, `ended_at`,
  `ended_at_zone`, `day_zone`, `duration_seconds`

**The union states a whole mode, so it serves whole statements only** — this
creation and #692's `CorrectSessionTiming`, which restates a mode entirely, and
#700's conversion, which is the code the guard is for. A partial act carries its
own payload: #691's finish states `ended_at` and `ended_at_zone`, and its
command re-reads the mode, because `amend()` is a bare `UPDATE` over the columns
it is handed and re-reads nothing.

The guard is an append-time one. `replay()` compares a version integer and does
not re-validate payloads, so the CHECK constraints are the durable enforcement
and the union is what stops a bad payload being recorded in the first place. It
is worth its weight for the conversion alone; it does not replace the
constraints, and this spec does not pretend it does.

Each member carries its own `@with_config(STRICT_SCHEMA)`. A nested TypedDict
does inherit the parent's config, but `_check_schema_config` only inspects the
top-level payload, so nothing would catch a member that lost it.

References stay at the top level. `reference_fields` raises
`ReferenceFieldUnsupported` for a `Reference` nested where nothing enumerates
it, so a later Release inside a timing member is refused at import — the guard
working, not a limitation to route around.

Instants and days cross as validated text, not bare `str`:

```python
type InstantText = Annotated[str, AfterValidator(canonical_instant_text)]
type DayText = Annotated[str, AfterValidator(canonical_day_text)]
```

mirroring `ReferenceId`, whose whole point is that a payload carries the form it
is read back in. Each validator parses and reformats and refuses anything that
differs, so `"2024-06-01T21:30:00Z"`, `"2024-06-01T21:30:00+00:00"` and
`"not a date"` cannot all be recorded as one field's value. The canonical
instant is UTC ISO-8601 from `datetime.isoformat()` — production instants carry
microseconds, and the trail is read by people during a migration audit. Without
this, a malformed string surfaces as a `ValueError` inside the projector during
a rebuild, which is the worst moment to find it.

Durations cross as `duration_seconds: int`: no production duration carries
sub-second precision, every duration in a payload is human-entered, and the
command refuses anything finer, so the payload and the fingerprint agree by
construction (see below). A sub-second duration later would be a `NotRequired`
key, not a rewrite.

`playersession_created(...)` accepts an explicit identity, as
`playthrough_created` does, because #700 appends this same type while recording
a past instant. **#700 reuses the legacy `Session.id` as the aggregate id**:
every bookmarked session URL and `/api/session/{id}` keeps working, and #704's
row-to-row parity needs no mapping table. `make audit-uuid-identity` holds
identity order against `(created_at, pk)`, and with every converted row sharing
one `created_at` the tiebreak is the key itself, so reuse passes.

## The command

`CreateSession`, `CommandName.PLAYERSESSION_CREATE =
"library.playersession.create"`.

```python
CreateSession(
    playthrough_id: uuid.UUID,
    timing: TimingStatement,
    device_id: uuid.UUID | None = None,
    note: str = "",
    emulated: bool = False,
)
```

`TimingStatement` is the Python-side union of three `NamedTuple`s mirroring the
payload members — `NamedTuple` because `canonical_command_input` builds a shallow
dict of dataclass fields and `json.dumps` encodes a NamedTuple as an array,
where a dataclass reaches `default` and raises. `timedelta` has no canonical
encoding today, so this issue adds one branch to `_encode_command_value` —
`("duration", total microseconds as text)` — which #692, #700 and HIST inherit.
The encoding is positional, so reordering a member's fields invalidates every
issued idempotency key and needs a `FINGERPRINT_VERSION` bump; the fields are
named here once and left alone.

It takes the run explicitly and never infers one from the game, the day or
another session. It resolves the run through `_live_run` in
`games/commands/playthrough.py`, so the refusals for a removed run and a removed
tracked game are stated once for the whole wave, and the device through
`library_row`, so neither read is a bare manager `.get()` that
`tests/test_command_scope_guard.py` would fail.

Refusals, each with both sentences:

- a run this library does not hold, a removed run, a removed tracked game
  (`_live_run`)
- a device this library does not hold, or one it removed
- an end before its start, in Timed and Corrected alike
- a negative duration
- a duration that is not a whole number of seconds. Not merely "below one
  second": the payload carries seconds while the fingerprint carries
  microseconds, so truncating would make an honest retry of
  `timedelta(seconds=90, microseconds=1)` fingerprint differently from the
  recorded event and answer 409
- a Duration-only statement of zero duration: the census classifies a legacy row
  with no end and a zero manual duration as `running`, which no mode holds, so a
  zero-duration Duration-only row would let the command and the classifier name
  one row two ways
- an endpoint zone stated without its instant
- a naive datetime. This one is refused in `__post_init__`, before the
  fingerprint: dispatch fingerprints a command's input before building it, and a
  naive datetime has no canonical form there, so a refusal inside `build` would
  never run and the person would meet a `TypeError` instead
- a zone name that either tzdata does not know

That last one needs both checks. `zone_or_none` reads Python's `zoneinfo` and
answers `None` rather than raising, while `effective_day` is generated by
PostgreSQL's `timezone()`, which **errors** on an unknown name — and in this
deployment the two tzdata sets come from different images. A name Python knows
and PostgreSQL does not would pass the command, reach `project()`, and raise
`DataError` inside the append transaction: a 500 for the person, and a hard stop
mid-rebuild that cannot be repaired without editing recorded events. The
validator therefore tests `zone_or_none(...) is not None` **and** membership in
`pg_timezone_names`, read once and cached.

It never answers `Unchanged`: a creation mints an identity, so there is no state
it can find already held.

## The projector

`PlayerSessions`, family `ProjectorFamily.CURRENT_STATE`, beside `PlayerGames`
and `Playthroughs`. One handler, `_created`, writing the whole row through
`project()`.

One function maps a timing statement to the eight columns it decides —
`timing_mode` and the seven it admits or forbids — and **always returns all
eight, naming `None` for every column its mode forbids**. #692's correction
handler shares it, which is what lets a Timed→Duration-only correction clear the
five columns the new mode forbids through `amend()`.

A replay reaches the creation of a run before the creation of a session naming
it, because replay follows stream sequence, so the `RESTRICT` key holds without
the family needing an order.

## The queryset

```python
class PlayerSessionQuerySet(RemovableMixin, models.QuerySet["PlayerSession"]):
    ancestor_marks = ("playthrough", "playthrough__player_game")
```

`PlaythroughQuerySet` is the obvious precedent and the wrong one: it deliberately
states neither `alive()` nor `for_library()`, and `BlockingReferrer.on` refuses a
model whose manager lacks `alive()` — `_skips_removed_rows` is literally
`hasattr(manager, "alive")`, and `BLOCKING_REFERRERS` is built at module scope,
so following that precedent is a `TypeError` at import the moment #694 registers
one.

**The catalog `Game`'s mark is deliberately absent.** `blocking_referrer` asks
`alive().filter(playthrough=run, …).exists()` to refuse removing a run that
sessions name. If `alive()` also hid sessions whose catalog game is removed, then
removing a catalog game would make its sessions invisible to that check, the run
would become removable, and restoring the game would leave live sessions naming
a removed run — the state #1011's refusal exists to prevent. The `PlayerGame`
mark carries no such hazard, because `RemovePlaythrough` already refuses a run
under a removed tracked game.

The catalog mark is a read-layer rule instead, stated where `library_runs()`
states its own: explicitly, in the read module. Legacy `SessionQuerySet` hid a
session for its own mark and the catalog game's; the two marks here add the run's
and the tracked game's, and production holds **0** rows where that difference
shows (one removed `PlayerGame`, over no live game with live sessions), so #704's
strict-equality gate is unaffected.

No `for_library()`. #702 states library scoping with its readers in hand, and
must state `playthrough__library` beside `library` as `library_runs()` does,
because a projection row may name another library's row — the drift
`audit_library_ownership` reports.

## What each mode renders

Storage that no renderer can express is storage chosen too early, so the shape
above is committed to a contract #702 implements:

- **Timed, running** — the start instant alone.
- **Timed or Corrected, finished** — the range, each endpoint in its own zone
  under the "own" display preference, exactly as `session_time_range` does now.
- **Duration-only** — the written day and the duration. No time of day, and no
  zone label: there is no instant to label.

`session_time_range` dereferences `timestamp_start` unconditionally today, so it
does not port by renaming fields; the 142 Duration-only rows are the branch it
has never had.

## The registry

Both references are registered in `AUDITED_PROJECTION_REFERENCES`:
`ProjectionReference.on(PlayerSession, "playthrough")` — the second
projection-to-projection key, after the one #1017 registered — and
`ProjectionReference.on(PlayerSession, "device")`. Registration is not optional:
`projection_references()` walks every foreign key out of a projection into a
library-scoped model, and `games.E009` fails `manage.py check` for either one
left out.

## Boundary

Out: every other event type (finish, correct, describe, move, remove, restore),
every screen and form, the conversion and the bucket run, `for_library()`, and
any read of the new table. Nothing writes it and nothing reads it when this issue
merges; that is what makes it incomplete rather than inconsistent, so it merges
on its own like any other issue.

## What later issues inherit

- **#691** states an end on a Timed row through a payload of its own, and its
  command re-reads the mode, because `amend()` does not.
- **#692** restates a whole mode through `TimingPayload` and the shared mapper;
  `reset_session` is a restated start, not a command of its own.
- **#700** converts a Corrected row's override from `duration_total`, reuses the
  legacy id, derives a Duration-only row's `stated_day` in the seeded zone,
  keeps the legacy instants and both duration components as `source_metadata`,
  and decides what `started_at_zone` the 56 end-zone-only rows take.
- **#702** carries the render contract above, reinterprets the form's "end plus
  manual" combination, and repoints `recent_session_resumes` at
  `(library, sort_instant, id)`. It also inherits an exemption that stops being
  true under it: the three zone columns sit in `KNOWN_NULLABLE_EXCEPTIONS` in
  `tests/test_filters.py` because no `StringCriterion` reads them, and nothing
  re-checks that precondition when a session filter arrives.
- **#702 and the dormancy clock**: `effective_day` is frozen in the seeded zone,
  so `ActivityClock.zone` no longer changes the day a session lands on. The
  clock's comparison has to be stated against the same zone, and
  `default_activity_clock()`'s UTC is the thing that moves.
- **The deferred zone-restatement issue** ships an event, not an `UPDATE`.
- **`answers.py` classifies no database error.** Closed after this wave:
  `answered()` catches every `django.db.Error` as a defect, logging the
  constraint name and answering `REFUSED_BY_DATABASE` with status 500, and
  the completeness guard now walks `vocabulary`, `references`, `envelope` and
  `projection` as well. The backstop writes no sentence a person can act on,
  so the rule above is unchanged: every refusal a person can do something
  about belongs in the command.

## Verification

- Every CHECK refuses the rows it should, proven by writing the row and reading
  the `IntegrityError`: `stated_day` on a Timed row and on a Corrected row, an
  instant on a Duration-only row, an endpoint zone without its instant, a blank
  zone, an end before its start, a negative duration, and a `timing_mode` no
  enum member spells.
- Every command refusal is answered with its sentence, and each one the database
  also refuses is refused by the command first.
- `effective_day`, `effective_duration` and `sort_instant` answer correctly for
  all three modes, and `effective_day` follows an `UPDATE` of `day_zone` across
  a day boundary.
- Replay from an empty stream reproduces the projection exactly, through
  `rebuild_projections --check`.
- `PlayerSessionTimingMode` and `MODE_VERDICTS` agree, member for member.
- The event type spelling is pinned; the payload refuses a bad tag, an extra key,
  a missing key, a wrong scalar type, and a non-canonical instant or day.
- A `timedelta` fingerprints, and a duration with microseconds is refused before
  it can be truncated.
- `AUDITED_PROJECTION_REFERENCES` holds both entries and `manage.py check` is
  clean.
- The full `make check` gate passes.
