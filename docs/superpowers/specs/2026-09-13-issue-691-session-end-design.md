# SES-03 — End a running Timed session

**Issue:** [#691](https://github.com/KucharczykL/timetracker/issues/691)
**Parent phase:** #601 · **Wave review:**
[Session delivery wave](2026-09-12-session-wave-design.md)
**Depends on:** [#689](2026-09-13-issue-689-playersession-aggregate-design.md)

One command, one event, one handler: state the end instant of a Timed session
that has none. Nothing else — no screen, no route, no read. #702 owns the
surfaces that call this.

The issue records that production holds zero live running sessions, the only
two rows in the running shape being removed. The preflight's own `running`
counter does not separate removed rows, so the repo cannot confirm the figure;
either way every path below is exercised by tests rather than by conversion.

## The verb is `end`

`EndSession`, `library.playersession.ended`, `playersession_ended()` — and the
columns the handler writes are `ended_at` and `ended_at_zone`. One word, three
places, which is the shape of every other act in this codebase.

The wave's prose and the legacy view both say *finish*. The naming rule in
[event retention](../../event-retention.md#naming) does not settle it either
way: it reaches an act record, and `ended_at` holds when a session was played,
not when anything was recorded — the doc names this very column as the example.
So the tiebreak is the column, and the column says `end`. The issue title keeps
its word; the code does not.

## The event

```
library.playersession.ended   aggregate_type: playersession
payload {"ended_at": InstantText, "ended_at_zone": str | None}
effective_time: the end instant read in the row's day_zone
```

**A payload of its own, not `TimingPayload`.** That union states a whole mode
and serves whole statements — the creation, #692's `CorrectSessionTiming`,
#700's conversion. An end is a partial act: it states two columns and leaves
the other six as the creation left them. #689 committed this shape and this is
where it lands.

**`day_zone` is not in the payload.** The row already holds it, the act does
not restate it, and a key admitted under `extra="forbid"` is a fact somebody
may state — a second spelling of a zone the row already carries. The builder
takes it as an argument and uses it for one thing.

The reference fields are empty: an end names no device and no release.

### The event's day is not the row's day

`playersession_ended(session_id, *, ended_at, ended_at_zone, day_zone)` reads
`ended_at` in `day_zone` and states that day.

This is **not** the rule `stated_day_of` applies. That one reads the *start* in
`day_zone`, and so does the `effective_day` column generated from it. Reading
the end is a different rule producing a different day, and for a session that
crosses midnight the two disagree permanently: the event trail says day N+1 and
the row says day N.

That disagreement is the point. The event dates the act — a rename states no
day because a rename happens on no day, and an end happens on the day it
happened. The row dates the session, which is what every day-grained read keys
on, and the wave fixed that to the start deliberately. Neither answers the
other's question.

Nothing reads either field in a way this breaks today. The Journal's day
projector reads `stated_day` and `started_at` off the row, not `effective_time`
off the trail, so the two days never meet. #740–#743 and #748 inherit the
divergence and must not assume a session's events all carry one day; a test
pins it so the assumption cannot be made silently.

## The command

```python
@dataclass(frozen=True, slots=True)
class EndSession(Command):
    #: CommandName.PLAYERSESSION_END = "library.playersession.end".
    #: The value is in every fingerprint, so it is never renamed.
    command_name: ClassVar[CommandName] = CommandName.PLAYERSESSION_END
    session_id: uuid.UUID
    ended_at: datetime
    #: No default. Null is a zone nobody stated; a caller says so.
    ended_at_zone: str | None
```

**The zone has no default.** Null is admitted — it is what a session recorded
by a browser reporting no zone will carry — but it is stated rather than fallen
into. A caller that forgets the argument is a `TypeError` at the call site, not
a session silently recorded as stating no zone. `TimedTiming.started_at_zone`
defaults because it is a construction convenience for a five-field tuple; a
three-field command has no such excuse.

### `__post_init__`, before the fingerprint

Two normalizations and one refusal, all of them ahead of dispatch's hash for
the reason `CreateSession` states: dispatch fingerprints the input first, so a
build-time rule about the input's *shape* would never run.

- **A blank zone is `None`.** `ended_at_zone` is stripped, and an empty result
  becomes `None`. Without this the codebase holds two spellings of one fact
  that hash differently, and the legacy finish path produces the wrong one:
  `_posted_browser_zone` in `games/views/session.py` returns `""` for a browser
  that reports no zone. `""` would then be refused by `known_zone` rather than
  recorded as "nobody stated a zone" — a save the legacy path accepted — and an
  honest retry of the same statement spelled the other way would answer 409.
  Every sibling command normalizes its unstated spelling here and says so.
  The `playersession_zone_not_blank` CHECK becomes a backstop this command
  cannot reach, which is the right direction.
- **The instant must be aware.** `_check_aware` today is a `@staticmethod` on
  `CreateSession`; this issue lifts it to a module-level helper in
  `games/commands/playersession.py` and both commands call it. A naive datetime
  has no canonical form in the fingerprint, so a build-time refusal would never
  run and the person would meet a `TypeError`.

### Resolving the row

`_live_session(context, session_id)`:

1. `library_row(context, PlayerSession.objects.all(), Refusal(...), pk=…)` —
   this library's row, or "That session is not available."
2. `_live_run(context, session.playthrough_id)` — the existing helper, reused
   whole, as `CreateSession` already imports and reuses it. It resolves the run
   through `library_playthrough`, so it also proves the run on the
   `PlayerSession → Playthrough` edge is **this library's** — the registered
   reference `audit_library_ownership` walks, which a bare `library=` on the
   session alone would miss. It proves that one edge and no other: it reads
   `run.player_game.removed_at` without re-checking that `PlayerGame`'s
   library. It produces both ancestor refusals with the sentences #681 wrote.
3. `session.removed_at is not None` → refused.

Step 3 is inert on arrival: nothing states a session's mark until #694. It
belongs here anyway, because it is a fact about *resolving a session*, and this
issue is where the resolution helper is written — #694 adds an event, and a
helper that is already complete is one less thing for that issue to remember.
The precedent is #1011, which shipped `BLOCKING_REFERRERS` empty. Its test
arranges the mark with a direct `UPDATE`, exactly as
`tests/test_playersession_projection.py` already does: that is a test arranging
state, not production code writing a projection, and `PlayerSession` is absent
from `REMOVABLE_MODELS`, so `remove()` is not available to it.

### What it refuses, and when

Each refusal carries the two sentences the rule requires: a message naming the
id for a log, a sentence for the person.

| Phase | Condition | Sentence |
|---|---|---|
| `__post_init__` | The instant is naive | *(ValueError — no sentence; a shape the caller got wrong)* |
| `build` | No such session in this library | That session is not available. |
| `build` | The tracked game is removed | That game was removed from your library. Restore it before recording this. |
| `build` | The run is removed | That playthrough was removed from your library. Restore it before recording this. |
| `build` | The session is removed | That session was removed from your library. Restore it before recording this. |
| `build` | `timing_mode` is Duration-only | This session records how long it lasted on a day, so it has no end to state. |
| `build` | `timing_mode` is Corrected | This session's time was already corrected, so it already has an end. Correct it again to change it. |
| `build` | Timed, an end already stated, and either the instant or the zone differs | This session already has an end. Correct the one it has instead of stating another. |
| `build` | `ended_at < started_at` | This session would end before it started. Check the time. |
| `build` | `ended_at_zone` names no zone both tzdata sets read | *name* is not a time zone we know. |

The table enumerates this command's refusals, not every mark in the ancestry: a
removed **catalog** `Game` under a live `PlayerGame` is not refused here, which
#689 settled as a read-layer rule and `CreateSession` already inherits.

Mode is checked before the end, so a Corrected row is told what it is rather
than told it "already has an end" — the remedy differs.

The zone check is in `build`, because `known_zone` reads `pg_timezone_names`,
and `build` runs under the stream-head lock. That sits against dispatch's rule
that everything able to refuse refuses before any database work. It is
inherited rather than introduced: `CreateSession` already validates zones from
`build`, the read is `lru_cache`d for the process, and only a miss costs two
queries under the lock. This issue does not move it; a wave-level change would
have to move both.

### Unchanged, and what it does not cover

A Timed row that already ends at exactly the stated instant, in exactly the
stated zone, answers `Unchanged("This session already ends then.")` and records
nothing. That is `CompletePlaythrough`'s shape: a genuine restatement of a
recorded value is quiet rather than an error.

**It does not make a double-submitted finish button quiet.** The legacy control
sets the end from the server clock — `timezone.now()` in `finish_session` — so
two submits state two different instants and the second is a refusal, not an
`Unchanged`. This branch fires only where the instant is supplied by the caller
and stable across a resubmit. #702 decides whether its control works that way;
the command is indifferent, and this spec claims nothing about it.

A retry under the same idempotency key never reaches either branch — it answers
from the idempotency record, before `build` runs.

### The end equal to the start

Admitted. Started by mistake and ended at once is a thing that happens, and
removal is the remedy for a session that should not exist. The
`playersession_end_after_start` CHECK admits it with `gte`, and the wave's rule
holds: the command admits a subset of what the schema does, never a superset.
The row's `effective_duration` is then zero — the same number a still-running
row sums to, which #689 already named and every read distinguishes by
`ended_at IS NULL`.

### The zone is the only guard there is

`ended_at_zone` feeds no generated column and carries exactly one constraint,
`playersession_zone_not_blank`. An unknown but non-blank name — a typo, a zone
this installation lost — violates nothing, is stored silently, and renders as
unlabelled at read time through `zone_or_none`. So `known_zone` here is not a
guard ahead of a backstop, the way the `day_zone` check is ahead of a
`DataError`: it is the only thing standing between a typo and a permanent
silent record. Nobody relaxes it on the reasoning that the schema would catch
it.

## The handler

```python
def _ended(self, event: RecordedEvent) -> None:
    payload = event.payload
    self.amend(
        PlayerSession,
        event.aggregate_id,
        ended_at=instant_from_text(payload["ended_at"]),
        ended_at_zone=payload["ended_at_zone"],
    )
```

`amend`, not `project`: an event that changes two columns knows nothing of the
six the creation wrote, and `amend` refuses a row that does not exist, which is
what keeps a rebuild honest.

The handler re-reads no mode. It cannot: `amend` is a bare `UPDATE` over the
columns it is handed. The mode was checked by the command, under dispatch's
lock, and the CHECK constraints are what hold thereafter —
`playersession_timed_columns` constrains `started_at`, `stated_day`,
`stated_duration` and `day_zone` and says nothing of the end, so an ended Timed
row is admitted; `playersession_end_after_start` admits only an end at or after
the start; and `playersession_zone_needs_its_instant` admits the zone because
the instant is now there.

## Replay and rebuild

One stream per library, replayed in contiguous sequence order, so `created`
always precedes `ended` and `amend`'s missing-row refusal cannot fire. The
shadow twin carries a default manager, so the same `UPDATE` runs against it and
the stored generated columns recompute there too.

Created, then ended, reproduces the row exactly: `effective_duration` becomes
the elapsed interval, `sort_instant` does not move because it reads the start,
and **`effective_day` does not move either** — for the same reason, which is
the divergence named above.

## Tests

**`tests/test_playersession_events.py`** — the ended payload round-trips; an
extra key is refused; a non-canonical instant is refused; a null zone is
admitted; the event type enumerates no references; the builder states the end's
day read in `day_zone`, including a Prague end just past midnight UTC, and that
day differs from the one the creation stated for the same session.

**One test pins the encoding coupling.** `ended_at` is safe to fingerprint only
because `instant_text` and the fingerprint's `_canonical_datetime` are
independently written expressions that happen to produce identical text. That
is the hazard class `DURATION_RESOLUTION` exists for on the duration side, and
nothing currently holds the two functions together: truncate either one and
every honest retry answers 409 with no test failing. The test asserts they
agree for a microsecond-bearing instant in a non-UTC `tzinfo`.

**`tests/test_playersession_command.py`** — one section beside `CreateSession`,
reusing its `game` and `run` fixtures: the happy path writes both columns and
appends one event; every row of the refusal table; a blank and a whitespace
zone both normalize to `None` and record, rather than being refused; the same
statement spelled `""` and `None` fingerprints alike; the identical restatement
answers `Unchanged` and appends nothing; a same-instant-different-zone
restatement is refused; an end equal to the start is recorded; a naive instant
is refused at construction; another library's session is not found. Its
`record` helper ends in `PlayerSession.objects.get()`, so any test needing two
sessions states its own.

**`tests/test_playersession_projection.py`** — the handler amends exactly two
columns and leaves the other six; `effective_duration` becomes the elapsed
time; `sort_instant` and `effective_day` do not move; replay reproduces the
row; a rebuild diffs clean. The zero-length and running-row duration cases are
already there and are not duplicated.

## Boundary

Out: every screen and route, the session form's "end plus manual duration"
reading, the three correction commands, removal and restoration, the
conversion, and any read of `ended_at`. No registry work: both `PlayerSession`
references are already registered, the event adds no foreign key, and
`answers.py` needs no new classification.

Nothing calls `EndSession` when this merges — which makes it incomplete rather
than inconsistent, the same way #689 merged.

## What later issues inherit

- **#692** restates a whole mode through `TimingPayload`. A Timed row that
  `EndSession` ended is one of its inputs, and `CorrectSessionTiming` is the
  command every refusal above points at.
- **#694** makes step 3 of the resolution live, and must keep it: a removed
  session states no further facts.
- **#700** holds a converted row's whole timing in hand, so it states it in the
  creation rather than appending an end after it. This event is for the live
  path.
- **#702** calls this from the session form's finish control and renders the
  range the ended row now holds. It decides whether the end instant is set by
  the server clock at submit — in which case a resubmit is a refusal — or
  carried by the control, in which case it is `Unchanged`.
- **#740–#743, #748** inherit an event trail whose `effective_time` may name a
  later day than the row's `effective_day` for one session.
