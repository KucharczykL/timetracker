# The Library screens: implementation plan

> **For agentic workers:** execute inline by default (ask the user before
> subagent-driven execution). Steps use checkbox (`- [ ]`) syntax.

**Goal:** M3 of the Access and Purchases wave: the Library section on Game
detail, the entry forms and routes, the Library tab on the Games page, and
the Games tab's Access column and facets.

**Architecture:** Three PRs against `main`, each merged alone after the
full gate: (1) Game detail and the forms, (2) the Library tab, (3) the
Games tab. Every write goes through `games/writes/libraryentry.py`; every
read through `games/reads/entries.py`.

**Spec:** [The Library screens](../specs/2026-09-29-issue-1352-library-screens-design.md).
The spec holds the rules; this plan names where they land and what proves
them.

## Global constraints

- Person-facing words: "Library", "copy"; "entry" only in code, events, API.
- Every day a form defaults is `request_calendar_today(request, library)`;
  tests seed days through `tests/calendar_days.py`.
- No dispatch inside a transaction; POSTing tests use
  `@pytest.mark.django_db(transaction=True)`.
- Buttons are `ControlButton`; UI is Python components (htpy form); no
  inline JS; custom elements declare `Media`.
- Every new route is classified in `games/views/returns.py`; every link to
  a mutating route is `action_url(..., origin=...)`.
- `make vale` over docs and comments passes before each commit.
- Rebase onto `origin/main` before each PR's first edit. Before each
  commit: `make format`, `make lint-fix`, `make format-check`.
- Iterate with `make check-fast` or `make test ARGS=...`; the gate is the
  full `make check` once per PR, wrapped in
  `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`.
- `make ts` after any `.ts` edit, before e2e.

---

## PR 1: Game detail and the forms

> Superseded in review: the section is summary rows and every act is its
> own page. The spec's "One page per act" holds the rules; the disclosure
> tasks below record what was first built.

This branch (`claude/issue-1352-planning-2c9581`), whose first commits
are the spec and this plan; PR 1 carries them.

### Task 1.1: Writes and words

**Files:** modify `games/writes/libraryentry.py`; test
`tests/test_libraryentry_writes.py`.

- `SUBJECT = "copy"`.
- New `end_entry_access(actor, entry, statement: WayActStatement, *,
  correlation_id, idempotency_key=None) -> None`: dispatches
  `EndEntryAccess` alone under `answered(SUBJECT)`.

Tests: ends a held copy; a repeat under one key is absorbed; a second
statement under another key answers 409 with the command's sentence; a
refused sentence reads "copy".

### Task 1.2: The Release routes

**Files:** modify `games/api.py` (new `release_router` at `/releases`);
create `games/reads/releases.py` (`game_releases(library, game)` visible
live Releases with Edition and Platform selected; `release_label(release,
presentation) -> str`); test `tests/test_release_api.py`.

- `GET /api/releases/search?game_id=&q=` answers `list[PickerOption]`;
  label "PS5 · Deluxe · 2021" (edition only where named; "Unspecified"
  platform).
- `POST /api/releases/` `{name, game_id}`, `extra="forbid"`: the four
  steps of the spec, in order. `ValidationError` from `write_and_mirror`
  re-raised as `RowRefused(" ".join(error.messages))`. The statement is
  `EditionState(key, edition=stored, name=stored.name, releases=(existing
  ReleaseStates…, ReleaseState(new, platform=platform)))`; read
  `state_catalog_graph`'s docstring for how untouched rows are left alone
  before building it.

Tests: search scoped to the game and library, sole Release, label forms;
create on an owned Game; answers an existing Release on that Platform;
unknown platform 422; two platforms 422 naming both; shared Game 422 with
its sentence; foreign Game 404; another library's private Release never
listed; `LEGACY_IDENTITY_TAKEN` 422 not 500; the Edition keeps its name.

Gotcha: `Release.platform` is nullable; `Platform` uniqueness is
`Lower(Trim(name))` with group, shared and private separately.

### Task 1.3: The entry forms

**Files:** create `games/entry_forms.py` (`EntryAddForm`, `EntryEditForm`,
`EntryEndForm`, `EntryResumeForm`); test `tests/test_entry_forms.py`.

- Each takes `prefix`; Add, End and Resume have `submission` and
  `submission_key()`; Edit, End and Resume carry `access_end_seen` and
  refuse with `CHANGED_SINCE_OPENED` (reuse from `games/forms.py`, move it
  if the import would cycle).
- Release field: `SearchSelectWidget` over `/api/releases/search`;
  `params` a literal `game_id` on Game detail, the prefixed Game field
  (`self.add_prefix("game")`) on the Add page, set after
  `super().__init__`; `create=PostCreate(...)` with verb "Create release"
  where the caller says the Game is owned or unknown.
- Acquired, end and resume days: `TemporalFormField`, initial
  `request_calendar_today`.
- Edit's end: a two-choice field Held | Ended with way, day, note; clean
  to `KEEP`, `None` (void) or a `WayActStatement`.
- Access and format choices from `EntryAccess`/`EntryFormat`.

Tests: prefixes give distinct ids; each clean shape; the seen marker
refusal; Held on a held copy is `KEEP`.

### Task 1.4: `details`/`summary` builders and the section

**Files:** modify `common/components/elements.py`,
`common/components/__init__.py`; modify `games/views/game.py`
(`game_detail_page(request, game, open_form: OpenForm | None)`,
`_library_section`); create `games/views/library_cards.py` (card, chip,
disclosures); test `tests/test_rendered_pages.py`,
`tests/test_library_section.py`.

- `OpenForm = NamedTuple(act: LibraryAct, entry_id: UUID | None, form:
  Form | None)`; `type LibraryAct = Literal["add", "edit", "end",
  "resume"]`. GET reads `?library=`/`?copy=`; a bad value opens nothing.
- Origin for every link is `game.get_absolute_url()`.
- Section: heading + count, Add disclosure (or the shared-Game sentence
  where the Game has no Release and is shared), cards. Card: line, ended
  chip, Edit + End access | Resume disclosures, ⋯ menu with Remove.
- Reads `game_entries(...).select_related("release__edition",
  "release__platform")`.
- Widget media inside the disclosures: forms render through `FormFields`,
  so `component_media` attaches; check `collect_media` on the page picks
  up search-select and temporal-field.

Tests: section markers and empty state in `test_view_game` and
`test_view_game_empty_sections`; query count flat over 1 vs 4 copies;
`?library=end&copy=<id>` renders that disclosure `open`; another library's
copies absent.

### Task 1.5: The entry routes

**Files:** create `games/views/library_entry.py`; modify `games/urls.py`,
`games/views/returns.py`; test `tests/test_library_entry_views.py`.

Routes from the spec's table. POST: bind with the prefix, call the write
under `answered`, redirect to `return_url(request,
fallback=game.get_absolute_url())`; invalid form → `game_detail_page` at
200 with that form; `CommandFailed` → same at its `status_code`; GET →
redirect to Game detail with the form open. Remove:
`confirm_and_remove(action=partial(remove_entry, ...))` with an
`UndoOffer` to `restore_entry`, no `detail_url`. Restore:
`restore_and_return`, resolving the removed row with
`LibraryEntry.objects.filter(library=library, pk=...)`.

Tests per route: success; invalid at 200 with the form open; refusal at
its status; foreign entry 404; GET redirect; repeated submission records
once; Held on an ended copy voids; a stale seen marker refuses.
`test_action_origin_parity` passes on Game detail.

### Task 1.6: Add to library page

**Files:** modify `games/views/library_entry.py` (`add_to_library`),
`games/urls.py`, `games/views/returns.py`, `games/views/library.py`
(Temporary home action); test `tests/test_library_entry_views.py`, e2e
`e2e/test_library_section_e2e.py`.

Game picker (`/api/games/search`), then the Add form with the prefixed
Game param. Tracks an untracked game in the same dispatch.

E2e: open Add on Game detail, pick a Release, create one, submit; End
access, Resume, Remove + Undo; on the Add page, change the Game and see the
Release picker search again.

### PR 1 close

- [ ] `make render-pages` before/after on the dump and on a scratch
  restore with copies recorded through `POST /api/entries/`; attribute
  every difference.
- [ ] Screenshot Game detail with two copies, one ended, in light and dark.
- [ ] Orca checks for a card's buttons and disclosures added to #1335.
- [ ] Full `make check` under the lock; PR body lists the render-pages
  attribution.

---

## PR 2: The Library tab

Branch `claude/issue-1352-library-tab`, after PR 1 merges.

### Task 2.1: Mode `entries`

**Files:** modify `games/models.py` (`MODE_CHOICES`), new migration
(`make makemigrations ARGS="games --name entries_mode"`),
`games/filters.py` (`LibraryEntryFilter`, `FILTER_MODE_MODELS`, parse
table, `filter_queryset_for_library`, `filter_query_context_for_library`),
`common/components/custom_elements.py` (`FILTER_MODE_LIST_URLS`),
`games/sorting.py` (`ENTRY_SORTS`, `MODE_SORTS`), `games/views/filtering`
(`BUILDER_MODES`), `common/components/quick_filter.py` (`QUICK_FACETS`),
`games/views/list_columns.py` (`LIST_COLUMNS`),
`games/management/commands/render_pages.py` (`LIST_ROUTES`); tests: the
exact lists named in the spec.

`LibraryEntryFilter` fields per the spec; `acquired` and access end from
`endpoint_filter_fields(ENTRY_ACQUISITION / ENTRY_ACCESS_END, ...)`,
`access_end_way` from `way_filter_field`, `platform` at
`release__platform__id` with `/api/platforms/search`, `game` at
`player_game__game__id` with `/api/games/search`, `created_at` through
`calendar_day_handler`, `search` over `player_game__game__name`,
`game_filter` relation.

Tests: each criterion's `to_q` over two libraries; `from_json` refuses an
unknown key; every exact list updated; builder page renders mode
`entries`.

### Task 2.2: The shared fact-change reader

**Files:** modify `games/reads/fact_change.py` (gains `Fact[T]` with
optional `initial`, `fact_change(...)`), `games/reads/playergame_facts.py`
(calls it); create `games/reads/entry_facts.py`
(`EntryFactChanges`, `entry_fact_changes(library, entry_id, batch_id)`);
test `tests/test_fact_change.py`.

Where the latest earlier event is the creation: constant if the fact has
one, else the creation payload's key through `fact.read`.

Tests: game facts answer as before (existing `test_bulk_game_edit.py`
stays green); a copy's access before a batch reads the creation payload;
after a later change reads that change.

### Task 2.3: The bulk acts

**Files:** create `games/bulk_entry_edit.py` (`BulkEntryEditForm`,
`ENTRY_EDIT = BulkAction(name="entry.edit", ...)`); modify
`games/bulk_removal.py` (`REMOVE_ENTRY`, `entry_scope`,
`entry_resolution`, `remove_one_entry`, `restore_one_entry`),
`games/bulk_actions.py` (foot imports); test
`tests/test_bulk_entry_edit.py`, `tests/test_bulk_entry_removal.py`.

Scope `library_entries(library)` narrowed by the statement's filter;
`undo_rows=EventRows(LibraryEntry)`; note through `UnsetWidget(...,
none_label="No note")`; titles "Edit this copy" / "Edit {count} copies",
"Remove this copy" / "Remove {count} copies". Edit's Undo restates each
changed fact from `entry_fact_changes`, logging overwrites through
`games/bulk_edit.py`.

Tests: edit two, keep empty fields, clear a note, Undo; remove two, Undo;
another library's key is lost; an unreadable filter refuses.

### Task 2.4: The list, the tabs and the row menu

**Files:** create `games/views/library_list.py` (`list_library`),
`games/views/entry_menu.py` (`entry_row_menu`); modify
`common/components/domain.py` (`GamesTabs(current)` beside
`PlaytimeTabs`, with an optional trailing node for the Add button),
`games/views/game.py` (`list_games` renders `GamesTabs("games")`; the
section gains View all), `games/urls.py`, `games/views/returns.py`; tests
`tests/test_library_list.py`, `tests/test_paths_return_200.py`, e2e
`e2e/test_library_tab_e2e.py`.

Columns and sorts per the spec; rows keyed on the entry; `menu_slot`;
selection with both acts; quick bar mode `entries`. Menu items link to
`game.get_absolute_url()` + `?library=<act>&copy=<id>#copy-<id>`; Remove
to the confirmation; trigger label "<game> (<platform>) actions".

E2e: tabs switch; filter by access; select two, Edit, Undo; ⋯ End access
lands on Game detail with the disclosure open.

### PR 2 close

- [ ] Screenshot the Library tab (tabs + Add button + quick bar); if the
  stack reads crowded, file the "quick bar collapsed by default" issue.
- [ ] Orca checks for the row menu added to #1335.
- [ ] render-pages as in PR 1; full `make check`.

---

## PR 3: The Games tab

Branch `claude/issue-1352-games-access`, after PR 2 merges.

### Task 3.1: The cloud glyph

**Files:** create `games/templates/icons/cloud.html`; `make gen-icons`
(regenerates `common/components/icons_generated.py`).

Filled path, viewBox chosen so its ink box matches `physical.html`'s disc.
Judge by screenshot beside the disc at badge size, light and dark;
iterate the path, not CSS offsets.

### Task 3.2: `access_summaries` and `AccessBadge`

**Files:** modify `games/reads/entries.py` (`AccessSummary` NamedTuple:
`owned_now: bool`, `formats: frozenset[str]`, `held: int`,
`former: LibraryEntry | None`; `access_summaries(library, game_ids) ->
dict[UUID, AccessSummary]`), `common/components/domain.py`
(`AccessBadge(summary)`); test `tests/test_access_summaries.py`,
`tests/test_access_badge.py`.

One query over `library_entries`. Glyphs render `aria-hidden` without
`<title>`; filled `solid-brand`, outlined border + body text; `title` and
visually hidden text per the spec.

Tests: each row of the approved variants table; latest-ended tie order;
removed copies ignored; two libraries.

### Task 3.3: Column and `GameFilter`

**Files:** modify `games/views/game.py` (`game_list_columns`: "Access",
key `access`, `hidden_by_default=True`; cells from `access_summaries` for
the page's games), `games/filters.py` (`GameFilter.access`, `.format`,
`entry_count` in `GameFilter.aggregates`, `entry_filter` in `_extra_q`;
handler `held_entry_word_handler(column)`),
`common/components/quick_filter.py` (games facets); tests
`tests/test_filters.py`, `tests/test_quick_filter_bar.py`,
`tests/test_rendered_pages.py`, e2e in `e2e/test_library_tab_e2e.py`.

Handler: Exists over `context.queryset_for(LibraryEntry)` filtered to
held copies, `.values("player_game__game")`; each modifier and the
`excludes` list as the spec states. `LibraryEntry` joins
`filter_query_context_for_library`'s scopes in Task 2.1 already.

Tests: every modifier and `excludes` on a game with mixed and ended
copies; a shared Game counts one library; `is_quick_editable` accepts the
bar's output; column hidden by default, shown through the picker.

### PR 3 close

- [ ] Screenshot the Access column with every badge variant, light and
  dark; cloud and disc read the same size.
- [ ] Orca check for the badge's spoken text added to #1335.
- [ ] render-pages; full `make check`.

---

## After the last merge

- Docs sweep: delete this plan, trim the spec, amend CLAUDE.md's
  LibraryEntry paragraph (screens), comment on #1352's siblings and the
  wave doc, as the wave's verification contract asks.
