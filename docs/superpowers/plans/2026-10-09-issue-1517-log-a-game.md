# Plan: Log a game in one modal (#1517)

Spec: `docs/superpowers/specs/2026-10-09-issue-1517-log-a-game-design.md`.
Inline, TDD, one task at a time. Iterate with
`flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test ARGS=…`.

## Task 1: extract `CopyFields`

- `games/entry_forms.py`: new `CopyFields(PriceFields)` holding
  `price_choices = (PAID, FREE, NONE)`, the `access`/`format` fields,
  and an `install_copy_fields(library, presentation, today, game_field,
  game)` helper building `release` and `acquired` (release `params` name
  `game_field`). Methods `copy_statement(note)`,
  `copy_purchase_draft(note)`, `refuse_release_of_other_game(game)`.
- `EntryAddForm(OpenerFactsMixin, PrimitiveWidgetsMixin, Submission,
  CopyFields)`: keeps game, note, `draft()`, `purchase_draft()`, field
  order, `clean()` behaviour.
- `SubmissionKind` gains `"log"`.
- Tests: existing `tests/test_entry_forms.py`,
  `tests/test_library_entry_views.py` (or the Add to library tests found
  by `grep -l add_to_library tests`) stay green unchanged. Add none.
- Gotcha: `PriceFields.__init__` takes `user=`; MRO must keep
  `PriceFields.clean()` reachable through `super().clean()`.

## Task 2: `LogGameForm`

- New `games/log_forms.py`. Fields per spec "Form". No prefix.
- `SECTIONS: Final = ("copy", "dates", "playtime", "more")` and a
  `LogSection = Literal[...]` alias; `SECTION_LABELS`.
- Literal Tailwind classes per section in a dict (`PANEL_SHOWN`,
  `SUMMARY_HIDDEN`, `RUN_ROW_SHOWN`), never f-strings.
- `__init__(*args, library, presentation, today, facts, held: HeldFacts
  | None)`: build fields, `apply_primitive_widget_classes`, set
  copy/price/playtime fields `required=False`, `state_opener_facts`,
  seed status none-row label, seeds from `held`, default device.
- `clean()`: `super().clean()`; `ignore_fields` for every unticked
  panel (copy group + price group, playtime group); ticked copy needs
  release/access/format and release of the game; ticked dates refuses
  `certainly_reversed`; ticked playtime refuses zero duration; run
  rules (another game's run; several runs, none picked).
- `statement() -> LogStatement` (see Task 3).
- Tests `tests/test_log_forms.py`: each refusal; unticked copy with
  `price=paid` and empty amount is valid; ticked copy without amount
  refused on `amount`; status none row label with/without held game;
  opener fact fixes `game`.

## Task 3: `log_game` write

- New `games/writes/log_game.py`:
  - `LogStatement` frozen dataclass: `game`, `sections` (frozenset of
    `LogSection`), `copy: EntryStatement | None`,
    `purchase: PurchaseDraft | None`, `run_id: PlaythroughId | None`,
    `started/completed: ActStatement | None`, `note: str | None`,
    `playtime: SessionTiming | HistoricalHours | None` (two small named
    tuples: day+duration+device, duration+device), `mastered: bool |
    None`, `status: PlayerGameStatus | None`.
  - `LogRefused(CommandFailed)` sibling? No: plain `Exception`
    subclass carrying `section: LogSection | Literal["game"]`,
    `failure: CommandFailed`, `written: frozenset[LogSection]`.
  - `log_game(actor, statement, *, correlation_id, token) ->
    LoggedGame(written, tracked_the_game)`.
  - Steps and keys exactly as the spec table. Run resolution helper
    `_run_for(actor, statement)` returns picked, sole
    (`sole_ordinary_run`), else `record_run(...).playthrough_id`.
  - Each step wrapped: `except CommandFailed as failure: raise
    LogRefused(section, failure, written)`.
- Tests `tests/test_log_game.py` (`transaction=True`): every case in
  the spec's Tests list; assert one `correlation_id` over the events
  (`LibraryEvent`), counts of entries/sessions/records after a resubmit.
- Gotcha: `record_entry` vs `record_purchase` return types differ;
  only success matters. `record_facts(mastered=)` only where it differs
  from `mastered_seen`.

## Task 4: view and route

- New `games/views/log_game.py`: `log_game_page(request)`.
  Reads `held_facts(library, game)` (helper in `games/reads/log_game.py`:
  held copies less ended ones, sole run, `game_playtime(...).total`,
  mastered, status), builds the form, renders through `render_page`
  with `AddForm(..., fields=Div(class_="group/log")[FormFields(...),
  summaries], submit_label="Log game", cancel_url=...)`,
  `width="form"`, title "Log a game" or "Log <game>".
- POST valid: `log_game(...)`; success toast "Logged <game>.", info
  toast when tracked, `redirect(return_url(fallback=view_game))`. On
  `LogRefused`: rebuild form from `request.POST.copy()` with `saved`
  extended and `fix_field("game", game)`, `add_error` on the section's
  first field (`game` for track), status `failure.status_code`.
- Saved lines: one `P` per saved section, success colour, before the
  ticks; a saved section's tick is omitted from the choices.
- `games/urls.py`: `path("log/", log_game.log_game_page, name="log_game")`.
- `games/views/returns.py`: `ORIGIN_AWARE`.
- Tests: route lists named in the spec; `tests/test_log_game_view.py`
  GET renders (no native select passes the autouse guard), POST
  success redirect, partial refusal re-render with saved line and
  sentence on the field, held summaries text.

## Task 5: entry points

- `common/layout.py` `NavbarLogButton`: primary `href=action_url(
  "games:log_game", origin=origin)` with `form_dialog_link()` as the
  positional attribute slot.
- `games/views/game.py` `_played_row`: item `DropdownLinkItem(
  action_url("games:log_game", origin=origin, facts={"game":
  str(game.pk)}), "Log…", attributes=form_dialog_link())`.
- Tests: extend `tests/test_navbar_log_button.py`; game detail menu
  test (find with `grep -rn "Set times played" tests`).

## Task 6: e2e

- `e2e/test_log_game_e2e.py`: navbar opens the modal; tick shows its
  panel, untick hides it (computed display); log copy+dates on a new
  game through New game (`picker_opened` helper); from Game detail the
  game is fixed and the page reloads with the new copy summary
  (wait on server-rendered content before ORM reads).

## Task 7: docs sweep, gate, PR

Per the implement-issue skill: delete this plan, spec timeless,
CLAUDE.md line under Key patterns or the views list, comment #1519,
#1520, #1596 where the log modal changes their work, full `make check`, draft PR, five
reviewers.

## Status (2026-10-09)

Tasks 1–6 done, then the nested-dialog redirect: `FormFieldGroup.container`,
`<log-sections>`, section dialogs with Done and Edit, × unticks, a
refusal reopens its section. Focused tests, vitest and the log e2e
green; no full `make check` yet. Next: the user's spot check, then Task 7.
