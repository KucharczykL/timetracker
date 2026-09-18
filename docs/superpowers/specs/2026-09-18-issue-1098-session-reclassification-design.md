# Reclassify a session as historical playtime

Issue: [#1098](https://github.com/KucharczykL/timetracker/issues/1098).
Wave: [Historical Playtime](2026-09-17-historical-playtime-wave-design.md).
Follows [#706](2026-09-17-issue-706-historical-playtime-entry-design.md), whose
form it prefills, and
[#1097](2026-09-17-issue-1097-playtime-page-design.md), whose tab it lives on.

## Purpose

Half of the library's recorded playtime is an estimate stored as a session. A
person tells one from the other; this specification gives them the act, one row
at a time and over everything a review shows.

The wave's census of the production copy taken on 2026-09-16 counts 142 live
Duration-only sessions carrying about 4,700 of 9,300 hours. 93 of them are 8
hours or longer, 61 are the sole session of their game, 91 carry a device, and
the longest states 46 days 8 hours against a note that reads "561 hours". Those
figures are the wave's, and the rehearsal below is what re-measures them. No
rule separates a 9-hour sitting from a 4-hour estimate. Duration suggests; a
person decides.

## The act

`ReclassifySessionAsHistoricalPlaytime` in `games/commands/playersession.py`
states two facts: a record exists, and a session became it.

```python
@dataclass(frozen=True, slots=True)
class ReclassifySessionAsHistoricalPlaytime(Command):
    command_name: ClassVar[CommandName] = CommandName.PLAYERSESSION_RECLASSIFY
    session_id: uuid.UUID
    statement: HistoricalPlaytimeStatement
```

`build` answers two events in one sequence:
`library.historicalplaytime.created`, then
`library.playersession.reclassified`.

### One command, not two dispatches

The wave named two dispatches under one correlation id and cited #683. #683's
pairing is `tracking_events` in `games/commands/playergame.py`: one command
answering two events of two aggregates. That is the shape taken here, and the
wave's sentence is amended.

A dispatch is a transaction, and `run_in_transaction` refuses to nest, so two
dispatches cannot be made one. Two of them admit a state between: the record
live, the session live, every playtime total counting the same hours twice
until a person notices. `append` writes a whole sequence under one stream
lock and replays it into the projections in order, so the record row exists
before the session names it, and no reader meets a half-stated act. One
command also carries one idempotency key, so a repeated submit replays the
pair rather than recording a second record beside the first.

Nothing in the append path is per-aggregate: the idempotency record spans the
whole sequence, the rebuild diffs each table on its own, and no constraint
asks that one command's events share an aggregate.

### The shared creation

`RecordHistoricalPlaytime.build` gives up its body to
`created_event(runs, device, statement)` in
`games/commands/historical_playtime.py`. The caller resolves the runs and the
device and hands them over, so both commands build one event from one mapping,
and each keeps the device rule its own act needs.

### What the record states

`statement_from_session(session, provenance)` in
`games/commands/playersession.py` derives the default statement:

| record | session |
|---|---|
| `duration` | `effective_duration` |
| `when` | `effective_day`, at day precision |
| `playthrough_ids` | the session's run |
| `device_id`, `emulated`, `note` | the same columns |
| `provenance` | `Manually entered`, unless the caller states `Estimated` |

`effective_day` is the written day of a Duration-only row and the start read in
the library's day zone for the other two modes, which is the `stated_day` the
wave asks for, already generated.

The command takes the whole statement rather than deriving it, so one screen
states the conversion and the correction together. The 46-day row whose note
reads "561 hours" is converted to 561 hours in one act. The form is honest:
every field it draws is a field the command reads.

### The device the session holds

The session's own device is resolved with `library_device_row`, not
`library_device`, exactly as `RestateHistoricalPlaytime` resolves a device a
record already holds. A device the person named anew is resolved with
`library_device` and refused while removed.

This is not a detail. `library_device` refuses a removed device, the session
already holds it, and 91 of the 93 rows carry one; a person who retired a
console cannot otherwise convert any of its sessions, and the refusal would
name a device they have no reason to restore.

### Refusals

| Refused | Sentence names |
|---|---|
| A running Timed row | Finish or correct the session first |
| A run outside the session's own `PlayerGame` | The game the session belongs to |
| A device named anew and removed | `library_device` |
| Everything the record statement refuses | `normalized_statement` and `_live_runs` |
| A removed session, a removed run, a removed game | `_live_session` |

The run rule is what keeps hours in place. Without it a statement moves a
session's playtime to another game while marking the session converted, and
two per-game totals move at once. Within the game the runs are the person's:
a record names a set, and an estimate that spans two runs is one record.

The command admits a finished Timed row. Nothing on screen offers one; the
bulk act refuses one (below). The wave's reasoning holds — a person may decide
a recorded sitting was a figure they typed — and the command is where that
decision is admitted, not where it is offered.

## The undo

`UndoSessionReclassification(session_id)`, beside it, answers
`library.historicalplaytime.removed` and `library.playersession.restored`.
One dispatch, for the reason the act is one: the reverse of a pair that cannot
half-happen must not half-happen either.

The no-op comes first, as in `RemoveSession` and `RestoreSession`: a live
session whose record is already removed answers `Unchanged`, so a second press
of Undo appends nothing rather than restoring a row that was never removed.
Then the refusals: a session that states no `reclassified_into`. A removed
record beneath a removed session states only the restore, so an Undo pressed
after the record was removed by hand still returns the session.

The composite is also what lets `RestoreSession` keep its own refusal. A
person restoring the session alone is refused while the record stands; the undo
states both halves, so it is not refused by the rule it satisfies.

## Storage

`PlayerSession` gains one column:

```python
reclassified_into = models.ForeignKey(
    "HistoricalPlaytime", on_delete=models.RESTRICT, null=True, default=None
)
```

`default=None` keeps it out of `_required_columns`, so the creation handler
does not name it, as `removed_at` is not named. `RESTRICT`, because no cascade
may destroy a projection row. The pair joins
`AUDITED_PROJECTION_REFERENCES` in `games/projections.py`, or `games.E009`
refuses it at `manage.py check`. A projection naming a projection is
precedented: `HistoricalPlaytimeRun.record` is already audited.

### One act, one verb, and one mark

The `reclassified` handler writes `removed_at`, which is the `remove` act's
column. [Naming](../../event-retention.md#naming) gains the case rather than
being broken quietly: **an act that includes a removal states the removal's
mark and adds its own reference, never a second mark.** Reclassification is a
removal with a stated reason, and `reclassified_into` is the reason.

The alternative is a `reclassified_at` mark of its own, and its cost is the
reason it is refused: `PlayerSessionQuerySet.alive()`, `library_sessions`,
`readable_sessions`, the session figures, `blocking_referrer` and the game
list's aggregates would each have to learn a second condition, and the one
that forgot would count the hours twice — the exact failure this act exists to
prevent. One mark, and every reader already states it.

### The projector

`PlayerSessions` gains one handler. `_reclassified` amends `removed_at` with
the event's instant and `reclassified_into` with the record the payload names.
`_restored` keeps clearing `removed_at` alone.

The column persists through a restore. It is the durable fact that this
session became that record, and it is what makes the two guards symmetric:

- `RestoreSession` refuses a session whose `reclassified_into` names a live
  record, and names the record in its sentence. The guard lands after the
  `Unchanged` answer, which reads `removed_at`, so a live session is still
  answered as unchanged rather than refused.
- `RestoreHistoricalPlaytime` refuses a record a live session names, after its
  own `Unchanged`.

Neither order of the two restores counts the hours twice. Clearing the column
on restore, which the wave describes, leaves the record with no way back to the
session, and restoring that record later counts its hours beside the session's.

### The event

```python
@with_config(STRICT_SCHEMA)
class PlayerSessionReclassifiedPayload(TypedDict):
    """A bare key, as the move's run."""

    record: ReferenceId
```

`library.playersession.reclassified`, aggregate `playersession`, registered in
`DEFAULT_EVENT_TYPES`. A bare key rather than a captured reference, because the
record row does not exist when the event is built — the creation beside it
writes it. Nothing indexes a bare key: `references_in` writes
`LibraryEventReference` rows for captured references alone. The anonymizer
re-mints it through `aggregate_id_keys`, as it does the run of `moved`.

Two command names join `CommandName`: `library.playersession.reclassify` and
`library.playersession.undo_reclassification`.

## Screens

### Greater-or-equal, first

The review is "8 hours or longer", and the leaf number path cannot say it.
`Modifier.GREATER_THAN_OR_EQUAL` and `LESS_THAN_OR_EQUAL` exist and are already
offered for field comparisons; they are missing from `Modifier.for_numbers()`,
from the three leaf `to_q` bodies and `_numeric_to_q`, and from `NumberFilter`'s
option list. All four gain them.

Two options into one select is the whole change on screen, and none in
TypeScript: `readNumberWidget` reads the select's value verbatim, so the
criterion round-trips through the quick bar untouched. `buildRangeCriterion`,
which serialises a min and a max, is a different widget and is not touched —
its bounds keep the meaning they have.

An open bound without its closed form is an absence, not a decision. Every
number facet in every mode gains the pair.

### The review

A row between `PlaytimeTabs` and the quick bar on the Sessions tab — the page
has no toolbar today — carries a "Review estimates" link and, beside it,
"Convert all shown". Replacing the wave's bespoke review facet with a link is
the third amendment to the wave.

The link carries `?filter=`:

```json
{
  "timing_mode": {"value": ["duration_only"], "modifier": "INCLUDES"},
  "duration_hours": {"value": 8, "modifier": "GREATER_THAN_OR_EQUAL"}
}
```

`timing_mode` is a set criterion, so its value is a list and its modifier is
`INCLUDES`. Both fields are already quick facets of the `sessions` mode, and a
filter of two flat facet criteria passes `is_quick_editable`, so the bar draws
both as editable dropdowns. N is edited in the Duration facet that is already
there, the review narrows or widens through every control the bar offers, and
the filter round-trips through presets and the nested builder unchanged. No
facet kind is added, and the bar's round-trip guarantee is untouched.

`REVIEW_THRESHOLD_HOURS` is 8, in one place, read by the link and by the
confirm page's sentence.

There is no stored "suggested" state. The threshold is the suggestion, and a
row a person does not convert stays a session.

### One row

Every live Duration-only row gains a "Was an estimate" action in
`SessionActions`, which is already conditional — Finish and Reset draw only
while a row runs.

`games:reclassify_session` renders `HistoricalPlaytimeForm`, which gains a
`session=` parameter beside its `record=`. The parameter is what the prefill
needs: `_record_initial` seeds a fresh form with the game's latest run and
`Estimated`, and it runs after the caller's `initial`, so a caller-supplied
run and provenance are overwritten today. `session=` also widens the device
queryset to hold the session's own device, removed or not, as `record=`
already does — otherwise the prefilled device is not among the choices.

The run checkboxes show the game's live ordinary runs with the session's own
run selected; the command refuses the rest. The form's `submission` key is the
idempotency key, because the act has no `Unchanged`.

Success queues an Undo toast over `games:undo_reclassify_session`, a POST-only
route holding the session key alone: the record is read from
`reclassified_into`.

### Everything shown

"Convert all shown" opens `games:reclassify_shown_sessions` through
`confirm_and_apply`.

The GET lists every row the current filter matches, not the page, and writes
each session key into a hidden input inside the confirm form, which `details`
renders. The POST converts exactly those keys, and re-renders its list from the
posted keys rather than from `?filter=`, so a refusal redraws the list that was
acted on. A confirmation that lists one set and acts on another is not a
confirmation; re-running the filter on the POST would convert a row recorded in
another tab between the two requests, which no person ever read.

The POST refuses any key whose row is not Duration-only, whatever the command
admits. The list a person read is a list of estimates; a crafted body over an
unfiltered list would otherwise convert 2,668 recorded sittings.

Each row is one dispatch of the derived statement at day precision, provenance
`Manually entered`. Rows are independent decisions a person has already made,
so one unreadable row does not deny the other 92 an act they are entitled to.
The action closure therefore catches each `CommandFailed` itself and raises
none: `confirm_and_apply` discards its return and turns one raised refusal into
a re-rendered page. It queues its own answer through `common/notices.py` — how
many converted, and once per distinct sentence why the rest did not.

Each row's idempotency key is the submit token and the session key. A second
press after the cause is repaired replays what converted and retries only the
remainder, so a refusal is a resumable remainder rather than a dead end.

One correlation id covers the whole request. `new_correlation_id` states the
rule — one per request, however many dispatches — and the bulk conversion is
one act a person performed. The issue's "one correlation id per row" is
amended to it.

The population is bounded at 142 rows. Django's `DATA_UPLOAD_MAX_NUMBER_FIELDS`
bounds the form at 1,000; chunking past that is TABLE-03's, as the issue says.

Three route names join `games/views/returns.py` as origin-aware, or the
completeness guard fails: `reclassify_session`, `reclassify_shown_sessions`
and `undo_reclassify_session`. Every link to them is built with `action_url`,
because `tests/test_action_origin_parity.py` renders the session list and
refuses an origin-aware link that carries no `?origin=`.

## What moves

No read in `games/reads` changes shape. A converted session leaves every read
through `removed_at`, and the record enters every read through the scopes #709
and #1097 already state. What moves is every session-only figure:

- the wave's classification table — `total_sessions`, `unique_days`, the
  longest session, the highest average, and the first and last play;
- the run's condition, `games/reads/playthrough_activity.py`: a run whose only
  session is converted reads `Never played`. This is the one a person sees,
  on Game detail and in the `activity` facet;
- Game detail's session count, its averages and its play range;
- `GameFilter`'s `session_count` and `session_playtime_hours`;
- `playtime_matching`, which is sessions-only by the wave's own text, so the
  game list's narrowed-sum column falls by the converted hours.

Every playtime total is equal before and after, because a record and a session
contribute alike.

## Verification

- `tests/test_session_reclassification.py`: the pair under one key, every new
  refusal, the run rule, the held device, the derived statement, the undo's
  `Unchanged`, and the two symmetric restore refusals.
- `tests/test_playersession_projection.py`: `reclassified` writes both
  columns; `restored` clears one. Its `unaudited_projection_references()`
  assertion trips before `games.E009` does.
- `tests/test_projection_replay_gate.py`: a conversion and an undo in
  `build_stream`; `len(missing)` rises from 26 to 27. `empty_projections`
  deletes `PlayerSession` before `HistoricalPlaytime` — the present order is
  records first, which a session naming a record refuses with
  `RestrictedError`.
- `tests/test_restore_routes.py`: the undo route joins the parametrization, so
  its 405, its 404 and its second post are covered as every other restore is.
- `tests/test_session_reclassification_views.py`, beside
  `tests/test_session_list.py` for the review link and the row action: the
  confirm page's list, the count, a refused key, a key that is not
  Duration-only, and a repeated submit.
- `tests/test_filters.py` and the cross-language contract fixture: both new
  modifiers compile and round-trip.
- `e2e/`: the review link, one conversion, and its Undo in a browser.
- The rehearsal, on a copy of the deployment restored 2026-09-18 and migrated.
  Ninety-three rows matched "written down, eight hours or longer" -- the
  census figure exactly -- and all ninety-three converted, none refused, which
  is the held-device rule answering on real rows rather than in a test.

  What did not move: every playtime total, in every scope. All-time stayed
  33,504,255 seconds and each of the twenty years kept its own total to the
  second. The two halves now sum to it: 16,157,055 tracked and 17,347,200
  historical. A record's `when` is one day, so it lies inside every period the
  session lay inside, and containment counts it there.

  What moved, and why: `total_sessions` 2,815 to 2,722, which is the
  ninety-three; distinct days 1,308 to 1,233, so seventy-five of the converted
  rows were the only play recorded on their day; the longest session, the
  highest average and the first play, each because the row that held the
  record was a converted one. On the 2022 page the longest session falls from
  216.4 hours to 11.4 -- a 216-hour sitting is the mis-recording this act
  exists for.

  `make render-pages` over 1,706 pages differs on 111: ninety game pages, the
  eighteen statistics pages, the session list, the historical playtime list
  and the library page. Each statistics page keeps its total as one line and
  gains the tracked-and-historical split beneath it.
- Full `make check` green.

## Not in this specification

- **A record restored after its session was converted a second time.** Convert,
  undo, convert again, and the first record is orphaned: no live session names
  it, so its restore is admitted beside the second record and the hours count
  twice. Reaching it needs a screen that restores an already-removed record,
  and none exists — the Undo toast is the only path, and it is spent. The
  Trash (#795) is where such a screen arrives, and it owns the rule. Recorded
  on that issue.
- **Undo of a whole bulk conversion.** Each row keeps its own act; nothing
  reverses 93 at once.
- **A record naming the session it came from.** The reference runs one way.
  Nothing reads the other direction.
- **The bulk act on the Historical tab.** Records do not become sessions.
