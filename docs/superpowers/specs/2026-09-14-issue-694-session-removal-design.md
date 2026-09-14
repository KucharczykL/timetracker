# Remove and restore a session

Issue [#694](https://github.com/KucharczykL/timetracker/issues/694). Parent
phase [#601](https://github.com/KucharczykL/timetracker/issues/601). Wave
review: [Session delivery wave](2026-09-12-session-wave-design.md).
Predecessors: [the PlayerSession aggregate](2026-09-13-issue-689-playersession-aggregate-design.md),
[an end](2026-09-13-issue-691-session-end-design.md) and
[corrections](2026-09-14-issue-692-session-corrections-design.md). The model
for the pair is [remove and restore a Playthrough](2026-09-06-issue-1011-playthrough-removal-design.md),
itself modelled on [archive and restore a tracked game](2026-08-27-issue-675-playergame-archive-restore-design.md)
read with the rename [#944](2026-08-29-issue-944-one-removal-act-design.md).

A library takes a session out of its lists, and later puts it back. Both acts
are stated as commands, because `PlayerSession.removed_at` is the projector's
column and no other writer may touch it.

This issue also registers the first `BlockingReferrer`, which is what makes
#1011's refusal live: a run cannot be removed while a live session names it.
That refusal has a cost the wave review priced and
[#1048](https://github.com/KucharczykL/timetracker/issues/1048) asked this
specification to decide. The decision is below, and it changes the order of
`RemovePlaythrough`'s refusals.

## No schema change

`PlayerSession.removed_at` exists. #689 added it with the row: nullable, not
editable, starting at `None`, and the one column the creation event does not
state, exempted from `_required_columns` for exactly this issue. `PINNED_DEFAULTS`
in `tests/test_projection_model.py` already holds it.

Three places read the column today. `PlayerSessionQuerySet.alive()` skips a
removed row, and the removed run's and removed tracked game's rows with it;
`_live_session` refuses every statement about a removed session, a branch that
was unreachable until now; and `blocking_referrer` reads `alive()`, so a removed
session keeps no run in place.

No migration, no field, no index. The reversal is the projection rebuild
[#667](2026-08-25-issue-667-shadow-rebuild-design.md) already provides.

## Two events

The types are `library.playersession.removed` and
`library.playersession.restored`. The aggregate id is the session's own
identity, and both payloads are empty.

Removing and restoring are two facts, so the type is the fact and no payload
holds a direction that could disagree with it. Each payload is a bodyless
`TypedDict` under `STRICT_SCHEMA`, so a later fact takes a later type rather
than a key nobody declared. Neither states the time: `recorded_at` carries it,
as the creation event's carries `created_at`, and a replay writes what was
recorded.

Neither carries an `effective_time`. Of the family's events only
`.timing_corrected` does, because only it restates the day the session sits
on; a removal is an act about the row, dated by the act.

Each spec has a builder beside it, `playersession_removed()` and
`playersession_restored()`, and the commands and the projector import the
builders, as every `playersession` event since #689 does.

#700 appends `.removed` as well: the two removed legacy rows convert with their
removal stated as a fact, which is why this issue precedes the conversion in the
wave order.

## Two commands

`RemoveSession(session_id)` and `RestoreSession(session_id)`, with
`CommandName.PLAYERSESSION_REMOVE` as `library.playersession.remove` and
`CommandName.PLAYERSESSION_RESTORE` as `library.playersession.restore`.

### The resolver

Both resolve the row with `library_session()`, a library-scoped resolver over
the plain manager, which this issue lifts out of `_live_session` so that the
two helpers stand in the same relation as `library_playthrough()` and
`_live_run()`. `_live_session` becomes `library_session()` followed by the
mark checks it already makes; the refusal and its sentence for an unknown or
another library's session do not move.

Neither command uses `_live_session()`. That helper refuses a removed session,
which is right for a statement about a live session and wrong for both of
these: a repeated removal must answer `Unchanged`, and a restore can only ever
name a removed row.

### The order the refusals run in

`RemoveSession.build`, under the lock:

1. the session is already removed, so answer `Unchanged`;
2. the run's `PlayerGame` is removed, so refuse;
3. the run is removed, so refuse.

`RestoreSession.build`, under the lock:

1. the session is not removed, so answer `Unchanged`;
2. the run's `PlayerGame` is removed, so refuse;
3. the run is removed, so refuse.

The no-op comes first, the rule
[#906](2026-08-28-issue-906-no-op-command-semantics-design.md) settled: a
command asking for state that already holds succeeds recording no event, and
is never refused for a reason that could not apply to it. A second removal of
a session whose run was removed in between still answers success.

This is a different order from `_live_session`, which reads the run's marks
first and the session's second. Both are correct for what they guard, and each
build carries a comment naming #906 as the reason it differs, as the Playthrough
pair does.

The way back is always open. `RestorePlayerGame` refuses under nothing,
`RestorePlaythrough` refuses only under a removed game, and `RestoreSession`
refuses under either, so the order to follow is game, then run, then session,
and each refusal states the next step rather than hiding a restored row behind
a removed parent.

Each refusal carries a `sentence`, and the pair writes its own rather than
borrowing `_live_run`'s: "Restore it before recording this" names an act the
person is not performing. A module helper, `_refuse_under_a_removed_parent()`,
holds both sentences for both commands:

- "That game was removed from your library. Restore it before changing its
  sessions."
- "That playthrough was removed from your library. Restore it before changing
  its sessions."

`MoveSessionToPlaythrough` is unchanged. It resolves through `_live_session`,
so a removed session cannot be moved, and the remedy is to restore it first.

## The handlers

The `PlayerSessions` projector gains `_removed`, which amends
`removed_at=event.recorded_at`, and `_restored`, which amends it to `None`.
Each is one `UPDATE` on the primary key of the created row, and an absent row
raises `ProjectionRowMissing`. `handles` maps the two new specs.

The creation handler names its columns and not this one, so re-applying a
creation event cannot take a later removal back out.
`tests/test_playersession_projection.py` gains the test
`tests/test_playthrough_projection.py` already runs for its family: stamp,
re-apply the creation, and read the stamp still there.

`amend()` goes through the default manager, and `PlayerSessionQuerySet` filters
nothing by itself, so a removed row is still reachable, which is what makes a
restore possible at all.

## The registry entry

`BLOCKING_REFERRERS` in `games/commands/playthrough.py` gains its first and
only entry:

    BLOCKING_REFERRERS: tuple[BlockingReferrer, ...] = (
        BlockingReferrer.on(
            PlayerSession,
            "playthrough",
            sentence=(
                "Sessions are recorded on this playthrough. Move them to "
                "another playthrough before removing it."
            ),
        ),
    )

`BlockingReferrer.on` refuses a field that is not a key to a run and a model
whose manager states no `alive()`. `PlayerSession.playthrough` is a
`ForeignKey` to `Playthrough`, and `PlayerSessionQuerySet` states `alive()`, so
the entry constructs at import. `games/models.py` is already imported there,
so the import adds no cycle.

`alive()` reads the run's mark and the tracked game's, not the catalog game's,
which #689 chose for this lookup: a catalog mark would hide sessions from the
check, leave the run removable, and restoring the game would leave live
sessions naming a removed run.

The sentence names the remedy that exists at the moment it is shown:
`MoveSessionToPlaythrough`, one session at a time, to a run at the same game
or any other. It does not name a bulk move, because #714 has not shipped, and
it does not name a screen, because #702 owns them.

The lookup is scoped on the library, as `blocking_referrer` already is. The
patched-model tests #1011 wrote keep proving the machinery; the test that
pinned the registry empty, `test_the_delivered_registry_refuses_nothing`, is
replaced by one that pins the entry.

The code comments that name #700 and #701 as the issues that fill the registry
are wrong twice over: #701 no longer exists, and this is the issue. Both go.

## The order of refusals in `RemovePlaythrough`, and the #1048 decision

#1011 runs the referrer check before the last-ordinary-run check. This issue
swaps them:

1. the run is already removed, so answer `Unchanged`;
2. the run's `PlayerGame` is removed, so refuse;
3. the run is ordinary and no other live ordinary run remains on its
   `PlayerGame`, so refuse;
4. a registered referrer names the run, so refuse.

The reason is the acceptance line: the refusal's sentence must name a remedy
that exists. For a sole run the move is not one. A sole run with sessions is
refused either way, and the two sentences disagree about what to do next:
"move the sessions" sends a person moving every session to a run at some other
game, and even then the run stays refused as the last one; "remove the game
itself instead" is a remedy that works. `RemovePlayerGame` refuses nothing about
runs or sessions, and `alive()` reads the tracked game's mark, so removing the
game takes every session out of the reads at once.

With the swap, the referrer bites only a run with a live ordinary sibling.
#700's measured assignment says how many sessions that is: 2,743 of 2,807
legacy sessions sit at a game with exactly one live ordinary run, where the
last-run rule answers first, and the remaining 62 sit at games with more than
one. The busiest run in production, 47 sessions, is a sole run, so it was never
this refusal's to answer. What #1048 measured as "a well-played game is
effectively unremovable" is, after the swap, "a run with a sibling and at most
a few dozen sessions needs them moved one at a time".

The decision is therefore #1048's option 2: accept the gap, stated here.

- Option 1, pulling #714 forward, buys a bulk form for a case that touches at
  most 62 rows across every multi-run game in production, at the price of
  reviewing an ORG-wave issue inside this one.
- Option 3, offering the move at the confirmation, is a screen. The command
  layer refuses with a sentence, and a screen may add an affordance over
  `MoveSessionToPlaythrough` later without changing the command. #702 owns
  the screens and the organizer (#715 to #717) owns the affordance.

The gap opens later than #694's merge. No screen calls `RemovePlaythrough`
with a live entry until the wave ships as one release after #704, and no
`PlayerSession` row exists in production until #700 converts the legacy rows.

No existing test pins the old order: every referrer test builds a sibling with
`_second_run`, so the referrer stays what refuses there. One test is added to
pin the new order, a sole run with a live session refused by the last-run
sentence. #1048 closes with this issue: its acceptance asks for the decision
stated here, a sentence naming a remedy that exists, and the gate.

## What reads change

Nothing today. No view, filter, statistic or API route reads `PlayerSession`
yet; legacy `Session` still serves every surface, and #702 moves them. The
first acceptance line is met by the read scope those surfaces must use:
`alive()`, which `tests/test_playersession_projection.py` already pins for a
removed session with a raw `UPDATE`. That test keeps its direct write, because
what it proves is the read.

`_live_session`'s removed branch becomes reachable, so the one command test
that arranged a removed session with an `UPDATE`,
`test_a_removed_session_is_refused`, dispatches `RemoveSession` instead, and
the comment saying nothing states the mark yet goes with it. Every other
`UPDATE` of `removed_at` in the family's tests stamps a run, a game or a device,
and each stays.

The Playthrough `DELETE` route in `games/api.py` reaches `RemovePlaythrough`
through `answered()`. Once #700 populates the projection, that route can answer
the referrer's sentence; nothing changes there.

## What this issue does not change

Verified inert: `REMOVABLE_MODELS` (a projection stays out, and the comment in
`games/removal.py` now names three), `AUDITED_PROJECTION_REFERENCES` and its
two checks, `CONFLICT_ANSWERS` / `ANSWERED_DIRECTLY` / `NOT_ANSWERED` (the
commands raise no new exception type), the benchmark workload, the UUID
identity audit, and the route return-classification table. The suite holds no
completeness test over event types or command names, so the coverage is the
tests this issue writes.

`remove` and `restore` are the words `docs/vocabulary.md` sanctions, and
`removed_at` satisfies the one-act-one-verb rule in `docs/event-retention.md`.
Neither document changes.

Prose that does: the `BLOCKING_REFERRERS` comment and the `BlockingReferrer.model`
comment in `games/commands/playthrough.py`; the "nothing states one yet" comment
in `_live_session`; the projection note in `games/removal.py`; the `Playthrough`
and `PlayerSession` bullets in `CLAUDE.md`, which say the registry is empty and
name the old order; the docstrings in `tests/test_playthrough_command.py` that
name #700 and #701; and the wave review's #694 section, which records what was
delivered against what it committed to.

#695, undo for a removed session, is a toast over `RestoreSession` and lands
any time after the cutover. It is out of this issue and out of the wave.

## Verification and reversibility

The gate is the full `make check`, green on delivery. The focused tests, in the
files the family already uses:

- **`tests/test_playersession_events.py`** — both types are spelled once and
  forever, both are in the default vocabulary, and both payloads refuse an
  extra key.
- **`tests/test_playersession_projection.py`** — a removal writes the event's
  own time; a restore states the way back; a re-applied creation keeps a later
  removal; a replay of created, removed, restored and removed again reaches one
  state; `rebuild_projections --check` reproduces a removed row without drift.
- **`tests/test_playersession_command.py`** — a repeat of each command answers
  `Unchanged`; an unknown id and another library's session answer alike; a
  removal and a restore under a removed run and under a removed game are
  refused, each with its sentence; one idempotency key covers a repeat; a
  removed session refuses an end, a correction, a description and a move, each
  arranged by dispatching `RemoveSession`; a restored session records a fact
  again.
- **`tests/test_playthrough_command.py`** — the delivered registry holds one
  entry naming `PlayerSession.playthrough`; a live session keeps its run in
  place, with the sentence above; a removed session does not; a session under
  a run with a sibling is what the referrer refuses, and a sole run with a
  session is refused by the last-run sentence instead.

A revert is the commits alone. There is no migration, and no caller appends
either event until #700 converts and #702 switches the writes, so no recorded
event is lost.
