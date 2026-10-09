# Log a game in one modal

Issue #1517, part of #1521. One "Log a game" form states what today's
add pages state, in one press. No new model, rule, event or read. Every
page it combines stays as it is.

## Approved design (2026-10-09)

The design session's mockup (2026-10-05) is the base. The person
approved these changes to it:

- Existing components only. Status is the fixed-choice picker
  (`ChoiceSearchSelectWidget`), not six segments. Format, price and the
  playtime kind stay radio lists. A segmented control and side-by-side
  rows are #1595.
- The Dates section holds Started and Finished. It has no run name.
- The session option states a Day (the calendar's today by default),
  a Duration and a Device.
- Opened with a held game, each held fact is one muted summary line.
  Ticking a section hides its line and opens its dialog.
- Each section opens as a nested dialog, not a panel that grows the
  Log modal (redirect of 2026-10-09).
- A refusal after earlier sections saved shows as below
  ("Partial refusal"). #1596 replaces this with a check before any
  write.

Layout, top to bottom:

1. Game: `SearchSelect` with #1501's + (`NEW_GAME`). A game the opener
   states is a fixed row (#1516 `OpenerFactsMixin`).
2. Status: picker, opened on its none row, which reads "Leave as is"
   (with a held game, "Leave as is: Completed"). A word picked is a
   statement; the none row states nothing. The none row is the field's
   `("", label)` choice, built per request; `ChoiceSearchSelectWidget`
   offers it because the field is optional.
3. Playthrough: the run picker (`PlaythroughSelectWidget`), shown only
   while Dates, Playtime or More is ticked.
4. Summary lines, opened with a held game only.
5. "Add" ticks: Copy and price (reads "Another copy" where the game
   holds one), Dates, Playtime, Mastered and note. The ticks are a
   placeholder until #1595.
6. Under the ticks, one line per ticked section: "<section> added"
   and Edit.
7. Log game, Cancel.

Each section's fieldsets render inside a nested `ModalDialog` in the
same form (`FormFieldGroup.container`: adjacent groups sharing one
container render inside one call). The dialog moves no field, so its
fields post with Log game. `<log-sections>`
(`ts/elements/log-sections.ts`) wires them:

- Ticking a section opens its dialog.
- Done closes it and keeps the tick.
- ×, Escape and the backdrop close it and untick the section. The
  values stay in the DOM; the server ignores an unticked section.
- Edit reopens it.
- The `open-section` prop opens one on connect, once its own dialog
  is open: the first ticked section with a field error.

The run picker and the summary lines still show through CSS: the
wrapper is `group/log`, and a literal class such as
`hidden group-has-[[value=dates]:checked]/log:flex` reads the tick.

No panel field is `required`. `LogGameForm` sets every copy, price and
playtime field `required=False` after construction. `clean()` drops an
unticked panel's fields with `ignore_fields` (`games/price_fields.py`),
and checks a ticked panel's fields itself: a Release, an access and a
format under Copy and price; a non-zero duration under Playtime.
`PriceFields.clean()` already checks the price on every press, so
`LogGameForm.clean()` never calls `_clean_price` again (a second pass
reads a `Decimal` as text); it pops the price errors of an unticked
panel instead, since `price=paid` posts from a hidden panel too.
Hidden fields still post, so the server, not the browser, decides.

## Entry points

- The navbar's green "Log game" primary opens the modal
  (`form_dialog_link()` on its `ControlButton`). Add session stays
  reachable from the Sessions list and its own URL.
- Game detail's Played split button menu
  (`games/views/game.py`, `_played_row`) gets "Log…" with
  `facts={"game": str(game.pk)}` stated directly, not through
  `_game_fact`, because the modal takes shared catalog games too.

## Route

`games:log_game` at `log/`, classified `ORIGIN_AWARE` in
`games/views/returns.py`. GET renders, POST writes. Success queues
"Logged <game>." and redirects to `return_url(fallback=Game detail)`,
which the form dialog answers `done`.

## Form

`LogGameForm` in `games/log_forms.py`:
`OpenerFactsMixin, PrimitiveWidgetsMixin, Submission, CopyFields`.

- `CopyFields` is extracted from `EntryAddForm`: release, format,
  access, acquired, price, amount, currency,
  `price_choices = (PAID, FREE, NONE)`, with `copy_statement(note)` and
  `copy_purchase_draft(note)`; `EntryAddForm.draft()` and
  `purchase_draft()` call them with its note. `EntryAddForm` keeps its game field, its
  note and its `draft()`/`purchase_draft()` signatures, so Add to
  library renders and writes as today. The release picker's `params`
  name the host form's game field.
- No prefix, so the opener fact is `game`
  (`state_opener_facts` reads `add_prefix(name)`).
- `game`: `SingleGameChoiceField` over `Game.objects.visible_to(library)`,
  as `EntryAddForm`, so a shared catalog game is loggable.
- `submission`: `Submission` with a new `SubmissionKind` word `"log"`.
- `status`: optional choice, none row first.
- `sections` (`CheckboxListWidget`), `saved` (hidden, the sections a
  previous press wrote).
- `playthrough` (optional), `started`, `completed` (`TemporalFormField`,
  cleaned to `TemporalValue | None`), `started_seen`,
  `completed_seen` (hidden, the seeded values).
- `playtime_kind` (`session`/`historical`), `day`, `duration`
  (`HoursMinutesField`), `device` (default device seeded).
- `mastered`, `mastered_seen`, `note`.

`clean()` refuses on the field, before any write:

- A Release of another game (the rule `EntryAddForm` holds).
- A price `check_price` refuses (`PriceFields` already does).
- Dates certainly reversed (`certainly_reversed`).
- A zero duration in a ticked Playtime.
- A run of another game, or no run where the game holds several live
  ordinary runs and a run section is ticked.

## Writes

`games/writes/log_game.py` holds `log_game(actor, statement, *,
correlation_id, token)`. It answers the sections it wrote, or raises a
`LogRefused` carrying the refused section, its `CommandFailed` and the
sections written before it. One correlation id covers every dispatch.
No dispatch runs inside a transaction (`run_in_transaction` refuses to
nest).

Order, each skipped where its section is not ticked or is in `saved`:

| Step | Write | Key |
|---|---|---|
| Track | `track_game` where untracked (`TrackGame` answers `Unchanged` for a tracked game, and refuses one the library removed: "Restore it instead") | minted |
| Copy | `record_purchase` with a price, else `record_entry` | `log-copy-<token>` |
| Run | where Dates or More is ticked: `restate_run` on the picked run, else on the sole live ordinary run, else `record_run` (adopts or creates) | none; each dispatch compares state |
| Playtime | `record_session` with `DurationOnlyTiming`, or `record_historical_playtime` with `when=None`, provenance `manually_entered` | `log-session-<token>`, `log-historical-<token>` |
| Mastered | `record_facts(mastered=)` where it differs from `mastered_seen` | `log-mastered-<token>` |
| Status | `record_facts(status=)` where a word is picked | `log-status-<token>` |

- The Run step states Dates and the note together in one `RunDraft`.
  An endpoint is `ActStatement(value)` only where its value differs
  from its seen value; a blank or unchanged one is `None`, which
  states nothing. So the modal never voids an endpoint (no screen
  does; only batch Undo voids), and seeded days never land on another run
  the picker names.
- The Playtime step uses the run the Run step answered, else the
  picked run, else the sole live ordinary run, else `record_run` with
  an empty draft (adopts or creates), because a session and a record
  each name a run. With Dates unticked the
  draft states no act; with More unticked it carries the run's own
  note, which `restate_run` leaves alone.
- Acts state the status they imply: `implies_played=True`,
  `implies_completed=True` on the run, `implies_played=True` on the
  session. The command decides (`status_implied_over`).
- Status runs last. A word the person picked stands over an implied
  one. The none row writes nothing, so an implied status stands.
- A new run comes from the picker's create row
  (`RecordPlaythroughByName`), as on Add session. That create tracks an
  untracked game at pick time, before the press; Add session does the
  same.
- The view reads `tracked_game` before the press. Where the game was
  untracked and is tracked after it, an info toast says so, as
  `record_run_for_request` does.

## Partial refusal

The view catches `LogRefused`. It rebuilds the form from
`request.POST.copy()` with the written sections added to `saved` and
the game fixed, puts the sentence on the refused section's first field
(the Track step's on `game`), and renders it.
A saved section shows one success line ("Saved: your copy") and no
tick, so it is not sent again. The sections after the refused one keep
their values. A second press finishes them. A double press writes
once: each create is keyed, and each other dispatch answers
`Unchanged` for a state the row already holds.

A `CommandNotPermitted` still answers 404 through `answered()`.

## Held facts

With a fixed game the view reads, once:

- the copies had now (`game_entries` less those whose access ended,
  as Game detail's Library section lists them), first one summarised
  with `release_words`, and a count of the rest. "Another copy" reads
  where one is had; an ended copy shows nowhere here;
- the sole live ordinary run's days, seeding Started and Finished, so
  a change is a correction;
- `game_playtime(...).total` and `mastered`.

## Tests

- `tests/test_log_game.py`: each section alone; all together on an
  untracked game (tracks once, one correlation id); status chosen over
  an implied one; status left as seen keeps the implied one; a refused
  run step after a saved copy (saved line, no second copy on resubmit);
  a double press writes once; each `clean()` refusal; an unticked
  Copy with `price=paid` and no amount passes; a removed game refused
  on `game`; the held-fact summaries.
- `tests/test_entry_forms.py` (extend): Add to library unchanged after
  the `CopyFields` extraction.
- `e2e/test_log_game_e2e.py`: navbar opens the modal; a tick opens its
  section, Done keeps it, Escape unticks it; a refusal reopens its section; New game hands the game back; logging from Game detail fixes
  the game and reloads Game detail.
- Route lists: `tests/test_returns_classification.py`,
  `tests/test_form_dialog.py` (`test_each_route_states_its_width`),
  `tests/test_dialog_create_pages.py` (game pickers with New game),
  `tests/test_form_dialog_results.py` (`_FORM_ROUTES`);
  `tests/test_view_authentication.py` reaches it on its own.
- `tests/test_navbar_log_button.py` (extend): the primary carries
  `data-form-dialog` and the log URL.

## Deliberate deviations from the mockup

- The run has no name here. #1519's tab is where a run gets its name.
- A held copy is a summary line with an "Another copy" tick, not a
  card with a link.
- The session states a Day, not "I played today" alone.
- Status opens on "Leave as is".

## Follow-up issues

All four sit in #1521's order, after #1517.

- #1595: segmented radios, toggle pills (the "Add" ticks) and
  side-by-side field rows.
- #1596: report every refusal before anything is written.
- #1597: an icon and a caption on `FormFieldGroup`; the footer with
  Cancel first and the primary right-aligned.
- #1598: the game picker's subtitle and a "+ New game" text; a device
  picker +.
