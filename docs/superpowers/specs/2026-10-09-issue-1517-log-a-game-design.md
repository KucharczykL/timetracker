# Log a game in one modal

Issue #1517, part of #1521. One "Log a game" modal adds a game to the
library and edits what the library already states about it. It shows
the basic facts inline. Detail sits in nested modals, and later in
#1519's per-playthrough and library tabs.

## Approved design (2026-10-09)

The person approved this design in an interview on 2026-10-09. It
replaces the tick-and-panel design of the same day.

- The modal is an add form and an edit form. A game the library
  tracks loads its data into the fields. A game it does not track
  starts empty.
- Inline fields only: Game, Status, Platform, Started on, Finished on.
- Two links open nested modals: "Add playtime…" and "Mastered and
  note…". The links show no summary of held facts. After a modal
  holds a value, its link reads "Playtime added" or "Mastered and
  note set".
- × and Escape on a nested modal act as Done: they keep what the
  person typed. "× reverts" is a follow-up issue.
- The main button reads "Create log" for a game the library does not
  track and "Save" for one it tracks. Cancel drops everything.
- Copy details (format, access, acquisition day, price, purchase) are
  not in this modal. #1519's library tab states them.
- No run picker and no run name. The dates edit the newest run, a
  placeholder rule. #1519's playthrough tabs pick a run.
- Nothing deploys before the whole dialog (#1521) is done.

## Layout

1. **Game.** From the navbar: a `SearchSelect` with `NEW_GAME`. A pick
   reloads the modal with that game's data (see "Reload on pick").
   From Game detail: a fixed row (#1516 `OpenerFactsMixin`).
   Game detail's facts lock; the navbar's prefill does not.
2. **Status.** The fixed-choice picker, prefilled with the tracked
   word, or "Unplayed" for an untracked game (the word tracking
   gives). A word that differs from the prefilled one is a statement.
   An unchanged word states nothing, so a status an act implies
   stands.
3. **Platform.** A platform picker over every live platform the
   library sees, with a create row and +. It is optional.
   TODO(#1604): restrict it to the game's platforms.
4. **Started on** and **Finished on**, side by side, each a
   `TemporalFormField`.
5. Links: "Add playtime…", "Mastered and note…".
6. "Create log" or "Save", Cancel.

The page title is "Log a game", or "Log <game>" with a game.

## Prefill

`held_facts(library, game)` (`games/reads/log_game.py`, replacing
today's `HeldFacts`) reads once:

- `removed`: the library tracked the game and removed it, read on
  the plain manager, since `tracked_game` hides it. `clean()`
  then refuses on `game`: "Restore it instead", before any write.
- `status`: the tracked status, else none.
- `run`: the newest live ordinary run by `created_at`, else none.
  This rule is a placeholder. #1519's playthrough tabs pick the run.
- `started`, `completed`: that run's stated days. An act stated with
  no day reads as an empty field.
- `platform`: the platform of the Release that the newest live
  session (`sort_instant`) on any run of the game names; else that of
  the newest live record (`when_upper`, nulls last) naming one; else
  that of the newest live copy (`created_at`). Only a live Release on
  a live Platform counts. Rows read through `library_sessions` and
  `library_records`: every ordinary-run row, prerelease included.
- `mastered`, and the run's note.

Each prefilled value travels in the post as a hidden `<name>_seen`
field. A field equal to its seen value states nothing. The seen
values are what the person saw, so they never refresh between two
presses (see "Refusal").

## Writes

`log_game(actor, statement, *, correlation_id, token)` in
`games/writes/log_game.py`. One correlation id covers every dispatch.
No dispatch runs inside a transaction. `token` is the form's
`submission` key and survives a refusal re-render.

| Step | When | Write | Key |
|---|---|---|---|
| Track | the game is untracked | `track_game` | minted |
| Copy | Platform differs from its seen value and no live copy is on it | see "Copy" | `log-copy-<token>` |
| Run | a day or the note differs from its seen value | see "Dates" | `log-run-<token>` on a creation; per command otherwise |
| Playtime | the Playtime modal states a non-zero duration | `record_session` (`DurationOnlyTiming`) or `record_historical_playtime` (`when=None`, `manually_entered`) | `log-session-<token>-<attempt>`, `log-historical-<token>-<attempt>` |
| Mastered | it differs from its seen value | `record_facts(mastered=)` | `log-mastered-<token>` |
| Status | the word differs from its seen value | `record_facts(status=)`, last | `log-status-<token>` |

`attempt` is a hidden field, 0 at first. A re-render after a written
playtime drops that playtime and raises `attempt`, so a new playtime
posts under a new key. `record_run` gains an `idempotency_key`
parameter, so a double press on a game with no live run creates one
run. The Run step's other commands compare state: a repeated day
answers `Unchanged`.

An act implies its status (`implies_played`, `implies_completed`, and
a session's `implies_played`) unless the person changed Status. A
historical record implies nothing in its command; where one is stated,
Status is unchanged and the seen word is Unplayed, the Status step
states Played (`status_implied_over`).

### Copy

The posted platform resolves a Release on every press, read-only
first:

1. A live copy on that platform (ended or not, as `held_releases`
   reads): that copy's Release. With several, the one whose Release
   the newest live session names, else the newest by `created_at`.
   No write.
2. Else, where Platform differs from its seen value: the default
   Edition's live Release on that platform. An owned game reaches it
   through `release_on(library, game, platform)`
   (`games/catalog_release.py`), which creates it where absent under
   the Game's lock. A shared game reads it and never creates one:
   `release_on` refuses every shared game. Then `record_entry` with
   access `unknown`, format `unknown`, acquisition day unknown, no
   note.
3. Else (the platform is the seen one and no live copy is on it, such
   as one prefilled from an old session's Release): no Release.

Playtime names the Release step 1 or 2 resolved, else none.

`clean()` checks, before any write, the cases where step 2 cannot
land, and refuses on `platform`:

- a shared game with no live Release on that platform under its
  default Edition (`SHARED_GAME_RELEASE`);
- a game with several Editions and none default
  (`NO_DEFAULT_EDITION`);
- a default Edition of kind `prerelease`: "Its default edition is a
  prerelease.";
- a platform `Platform.objects.visible_to` does not show live.

`release_on` refuses with `RowRefused`, not `CommandFailed`. `log_game`
answers one that still reaches it, after Track wrote, as a
`LogRefused` on `platform`.

### Access Unknown

`EntryAccess` gains `UNKNOWN` ("Unknown"). The person chose a word over
a nullable column, which matches `EntryFormat.UNKNOWN`. It is not
owned:

- Copy figures count `OWNED` alone (`games/reads/copy_figures.py`).
- `AccessSummary.owned_now` stays false, so the badge is hollow.
- A game purchase's refund ends no Unknown copy.
- `_NATURAL_ENDS` (`common/components/domain.py`) gains no entry.

Every access picker offers the word: Add to library, bulk Edit, the
filter, the API. The event's `Literal` (`games/events/libraryentry.py`)
and the column's CHECK gain it, with a migration.

### Dates

Each endpoint is a `Restated[ActStatement]`
(`games/writes/endpoint.py`): `KEEP` where the day equals its seen
value, `None` where a seen day was cleared, else the act or its
correction. `RunDraft` keeps its meaning (`None` states nothing): the
Run step passes `restate_run` (or `record_run`) the acts and
corrections with `None` for each `KEEP` and void, then dispatches each
void itself, `VoidPlaythroughStart`/`VoidPlaythroughCompletion`
through a new `void_run_endpoint` beside `restate_run`
(`games/writes/playthrough.py`). A void answers `Unchanged` where the
endpoint is unstated.

- A cleared day voids the act and its note. The status it implied
  stays. Status is the field that changes it.
- An act stated with no day shows an empty field. It stays unless a
  day is typed, which corrects it.
- A game with no live ordinary run gets one from `record_run`.

Playtime names the prefilled run, else the run the Run step recorded,
else the run Track minted (read again after Track), else one
`record_run` with an empty draft creates.

## Reload on pick

A navbar pick of a game reloads the modal for that game. The Log page
reads `prefill_game=<id>`, the editable-prefill carrier #1526
names as a candidate (this issue settles `prefill_<field>`, recorded
in #1526): the picker holds the game as its initial value, never
`disabled`. `<log-sections>` builds the URL from its own route, the
page's `origin` and the picked id, and dispatches `form-dialog:reload`.
`<form-dialog>` gains that event: it fetches the URL in dialog mode,
replaces the body, and takes a new baseline, so no unsaved-changes
prompt fires. A full page navigates to the same URL. Anything typed
below Game is dropped, because Game comes first.

## Nested modals

Each nested modal is a `ModalDialog` inside the form
(`FormFieldGroup.container`), so its fields post with Save.
`<log-sections>` opens one from its opener, a `ControlButton` (never
an `<a href>`, which `<form-dialog>` reads as leaving). Done, ×,
Escape and the backdrop all close it and keep its fields. It opens the
first one holding a field error on load (`open-section`). On
disconnect it drops its modal handles, since a reload replaces the
body.

- **Playtime:** Session or Historical playtime, Day (the calendar's
  today), Duration, Device (the default device).
- **Mastered and note:** Mastered, Note (the run's note).

## Refusal

`clean()` refuses on the field before any write: a removed game, a
platform step 2 cannot land on, a reversed pair of days
(`certainly_reversed`; each side is the posted day, else the parsed
seen day), a zero duration in a stated playtime.

A `LogRefused` re-renders the form from the post with the sentence on
the step's field and its modal opened. The seen values come from the
post, not a new read, so a word the person left unchanged stays
unchanged and an implied status is never written back. A written
playtime is dropped from the re-render. A second press finishes the
rest.

## Entry points

- Navbar: the green "Log game" primary (`form_dialog_link()`).
- Game detail's Played menu: "Log…", `facts={"game": id}`.

Route `games:log_game` at `log/`, `ORIGIN_AWARE`. Success queues
"Logged <game>." and returns to the origin, else Game detail
(`game_page`).

## Tests

- `tests/test_log_game.py`: each step alone; an untracked game with
  every field (one correlation id); an unchanged status keeps an
  implied one; a changed day corrects; a cleared day voids and keeps
  the status; a no-day act survives an untouched press; a note alone
  restates; an unchanged platform records no copy; a held platform
  records no copy and the session names its Release; an unheld
  platform records an Unknown copy, on a standing Release and on a
  created one; playtime on an untracked game names Track's run; a
  double press writes once; a refusal's second press writes no
  status back.
- `tests/test_log_forms.py`: `clean()` refusals (removed game, shared
  game without a Release, reversed days, zero duration).
- `tests/test_log_game_view.py`: prefill for a tracked game (status
  word, platform, days, mastered, note); "Create log" and "Save";
  `prefill_game` renders an editable held game; a refusal opens its
  modal.
- Access Unknown: copy figures, badge and refund leave it out; the
  event `Literal` stays equal to the enum.
- `e2e/test_log_game_e2e.py`: a navbar pick reloads with the game's
  data and no unsaved prompt; Add playtime opens, Done keeps; a
  refusal reopens its modal; Game detail locks the game.
- `ts/elements/form-dialog.test.ts`: `form-dialog:reload` replaces the
  body and rebaselines.
- Route lists as before.

## Follow-up issues

- #1603: × reverts a nested modal's fields.
- #1604: Platform lists only the game's platforms.
- #1519: copy details and purchases in the library tab; a run picker,
  run names and which run the dates edit, in the playthrough tabs.
- #1596, #1595, #1597, #1598 as before.
