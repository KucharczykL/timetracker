# Session removal implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `RemoveSession` and `RestoreSession`, the two events they record, the two projector handlers, the first `BLOCKING_REFERRERS` entry, and the swapped refusal order in `RemovePlaythrough`.

**Architecture:** Mirrors the Playthrough pair. No schema change: `PlayerSession.removed_at` exists and `alive()` already reads it.

**Spec:** `docs/superpowers/specs/2026-09-14-issue-694-session-removal-design.md` — read it first; every "why" lives there.

## Global Constraints

- Run everything through `make`. Iterate with `make check-fast`; the gate is the full `make check`.
- Focused runs: `make test ARGS="tests/test_playersession_command.py -x"`.
- Every `CommandRejected` carries `sentence=`.
- No bare manager `.get()` inside a `build` — `library_row` only.
- Comments explain intent, never history; no issue references in code comments.
- `make vale`: `remove`/`restore` are the sanctioned words.

---

### Task 1: Events and handlers

**Files:**
- Modify: `games/events/playersession.py` (after `playersession_moved`)
- Modify: `games/projectors/playersession.py`
- Test: `tests/test_playersession_events.py`, `tests/test_playersession_projection.py`

**Interfaces produced:**
- `PlayerSessionRemovedPayload`, `PlayerSessionRestoredPayload` — bodyless `TypedDict` under `STRICT_SCHEMA`
- `PLAYERSESSION_REMOVED` (`library.playersession.removed`), `PLAYERSESSION_RESTORED` (`library.playersession.restored`), aggregate type `playersession`, registered in `DEFAULT_EVENT_TYPES`
- `playersession_removed(session_id)`, `playersession_restored(session_id)` — empty payload, no `effective_time`
- `PlayerSessions._removed` amends `removed_at=event.recorded_at`; `_restored` amends `None`; both in `handles`

**Tests:**
- events: both types spelled once and forever; both in the default vocabulary; payload refuses an extra key (`{"removed": True}`, `{"at": …}`); builders name the session, empty payload, no `effective_time`
- projection: `test_the_lifecycle_events_have_a_current_state_handler`; removal writes the event's own time; restore states the way back; a re-applied creation keeps a later removal (mirror `test_re_applying_the_creation_event_leaves_an_amendment_alone` — needs a `reapply_creation` helper reading `RecordedEvent` by `aggregate_id`, as `tests/test_playthrough_projection.py` has); replay of created/removed/restored/removed reaches one state; `rebuild_projections` in `CHECK` mode reproduces a removed row with an empty diff

**Gotcha:** the creation handler names its columns explicitly and `removed_at` is not among them. Do not add it.

- [ ] Task 1 done

### Task 2: Commands

**Files:**
- Modify: `games/events/dispatch.py` (`CommandName`: `PLAYERSESSION_REMOVE = "library.playersession.remove"`, `PLAYERSESSION_RESTORE = "library.playersession.restore"`)
- Modify: `games/commands/playersession.py`
- Test: `tests/test_playersession_command.py`

**Interfaces produced:**
- `library_session(context, session_id) -> PlayerSession` — the `library_row` call lifted out of `_live_session`, with `select_related("playthrough__player_game")` so both marks read without a second query; refusal sentence "That session is not available." unchanged
- `_live_session` = `library_session` + `_live_run` + the removed-session check, unchanged behaviour
- `_refuse_under_a_removed_parent(session)` — two sentences: "That game was removed from your library. Restore it before changing its sessions." and "That playthrough was removed from your library. Restore it before changing its sessions."
- `RemoveSession(session_id)`, `RestoreSession(session_id)` — frozen slots dataclasses; order in `build`: no-op first (`Unchanged`), then game, then run

**Tests (the `# --- Removing and restoring a session ---` section):**
- a removal leaves the reads (`alive()` misses it, plain manager finds it), `removed_at == recorded_at` of the event
- a restore clears the mark
- a repeat of each answers `Unchanged` (`CommandOutcome.UNCHANGED`)
- an unknown id and another library's session both say "That session is not available." (use `a_session_another_library_holds`)
- removal and restore under a removed run, and under a removed game, refused with each sentence; the removed-run case builds a second run at the game with `CreatePlaythrough` (the last-run rule protects the fixture's) or stamps the run with `UPDATE` as sibling tests do — an `UPDATE` is enough, the command reads the mark
- one idempotency key covers a repeat (one event)
- a removed session refuses end, correction, description and move — rewrite `test_a_removed_session_is_refused` to dispatch `RemoveSession`, and parametrize the four
- a restored session records a fact again

- [ ] Task 2 done

### Task 3: The registry and the swapped order

**Files:**
- Modify: `games/commands/playthrough.py`
- Test: `tests/test_playthrough_command.py`

**Changes:**
- `BLOCKING_REFERRERS` holds `BlockingReferrer.on(PlayerSession, "playthrough", sentence="Sessions are recorded on this playthrough. Move them to another playthrough before removing it.")`. `PlayerSession` is imported from `games.models` there already? — no: add it to the existing import.
- `RemovePlaythrough.build`: last-ordinary-run check before `blocking_referrer`.
- Comments naming #700/#701 go: the `BlockingReferrer.model` comment, the registry comment.

**Gotcha:** `games/commands/playersession.py` imports `_live_run` from `games/commands/playthrough.py`; the registry imports `PlayerSession` from `games.models`, not from the session command module, so no cycle.

**Tests:**
- `test_the_delivered_registry_refuses_nothing` → `test_the_delivered_registry_names_sessions`: one entry, `model is PlayerSession`, `field_name == "playthrough"`
- a live session keeps its run in place (second run, one `CreateSession`, `RemovePlaythrough` refused with the sentence)
- a removed session does not (dispatch `RemoveSession` then `RemovePlaythrough` succeeds)
- a sole run with a live session is refused by the last-run sentence
- docstrings naming #700 and #701 on `referring_models` and `test_a_registered_referrer_keeps_a_run_in_place` rewritten

- [ ] Task 3 done

### Task 4: Prose

**Files:**
- `games/commands/playersession.py` — the "nothing states one yet" comment in `_live_session`
- `games/removal.py` — the projection note names three models
- `CLAUDE.md` — Playthrough bullet (registry no longer empty; order of refusals) and PlayerSession bullet (the pair exists)
- `docs/superpowers/specs/2026-09-12-session-wave-design.md` — the #694 section records what was delivered: the order swap and the #1048 decision
- Close-out comment for #1048 is the PR body's job, not this repo's

- [ ] Task 4 done

### Task 5: Gate

- [ ] `make check` green, e2e included
