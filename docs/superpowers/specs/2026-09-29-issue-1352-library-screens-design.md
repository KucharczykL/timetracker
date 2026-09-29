# The Library screens

Issue: [#1352](https://github.com/KucharczykL/timetracker/issues/1352),
member M3 of the
[Access and Purchases wave](2026-09-28-access-and-purchases-wave-design.md).
It needs [the LibraryEntry aggregate](2026-09-29-issue-719-libraryentry-aggregate-design.md)
and [a copy's end and resume](2026-09-29-issue-721-entry-access-end-design.md).
Precedents: [the Games list](2026-09-22-issue-1134-games-list-selectable-design.md),
[bulk game Edit](2026-09-28-issue-1270-bulk-game-edit-design.md),
[the Devices list](2026-09-24-issue-1135-devices-list-selectable-design.md).

## Result

A person sees and changes the copies they hold where they already look:

- The Games page has two tabs, **Games** and **Library**. The Library tab
  lists every copy, with filters, presets, bulk Edit and bulk Remove.
- Game detail has a **Library** section: one card per copy of the game.
  Every act on one copy opens inside its card.
- The Games tab has an **Access** column, off by default, and two facets,
  access and format.
- **Add to library** is a page, reached from the Library tab and from the
  Library page beside Add purchase.

No page states an entry alone. No purchase shows here; P5 adds them.

## Words

"Library" is the person's word for the tab, the section and the form.
"Copy" is the word for one row, so `SUBJECT` in
`games/writes/libraryentry.py` becomes `"copy"` and every answered
sentence says it. "Entry" is the word in code, events and the API. The
navbar's Library page keeps its name.

## Delivery

One spec, one plan, three PRs against `main`, each merged alone after the
full gate, in this order. Nothing in a PR links to a route a later PR adds.

1. **Game detail and the forms**: the Library section, the entry routes,
   the Release picker, the Add to library page.
2. **The Library tab**: the list, `LibraryEntryFilter`, mode `entries`,
   presets, the builder page, the tray acts, the row menu, and the
   section's View all.
3. **The Games tab**: the Access column, `AccessBadge`, the cloud glyph,
   `GameFilter` additions.

## 1. Game detail and the forms

### The section

`_library_section` in `games/views/game.py` sits above Purchases and is
one `_game_section`: heading "Library" with a count of live copies, an
Add button, and "Nothing in your library yet." when empty. Its body is a
`SummaryList` of one `SummaryRow` per copy (`copy_rows` in
`games/views/library_cards.py`), the library kit's shape; the section
invents no markup. A row's label is the Release (platform, "Unspecified"
where it names none, then the edition where it has a name); its
subtitle is access, format, "since <acquired>", and for an ended copy
"<Way> <day>"; its detail is the copy's note. Its actions are links:
Edit, End access and Remove on a held copy; Edit, Edit end, Resume and
Remove on an ended one. The row has room below for P5's purchases.

The section reads `game_entries(...)` with `select_related` of the
Release, its Edition and its Platform; a test pins the query count over
several copies.

### One page per act

Every act is its own page, as every other add and edit in the app is:
`AddForm` over `FormFields`, titled "<Act> - <game> (<release>)". A GET
renders the page; a valid POST writes and returns through `return_url`,
falling back to Game detail; an invalid form renders again at 200; a
refused command renders again at the refusal's `status_code`, its
sentence in a toast; a row the library does not hold is 404. Every link
to a page carries `action_url(..., origin=...)`. #1385 later opens these
pages in a dialog (#1384); the pages stay the source of truth.

| Act | Route | Write |
|---|---|---|
| Add | `game/<game>/library/add` | `record_entry` |
| Edit | `library/<entry>/edit` | `restate_entry` |
| End access | `library/<entry>/end` | `end_entry_access`, new |
| Edit end | `library/<entry>/end/edit` | `restate_entry(access_end=...)` |
| Resume | `library/<entry>/resume` | `resume_entry_access` |
| Remove | `library/<entry>/remove` | `confirm_and_remove(action=partial(remove_entry, …))` |
| Restore | `library/<entry>/restore` | `restore_and_return`, `restore_entry` |

Add and Edit state the copy's own facts, grouped by space alone into
what the copy is (Release, format), how it is had (access, acquired),
and its note. Each group is a `FormFieldGroup` whose legend is hidden
(`legend_hidden`), so a screen reader still names it. Format is a radio
list. Add defaults access to Owned, format to Digital, acquired to
`request_calendar_today(request, library)`, and the Release to the
game's default one, first in `game_releases`' order.

The end lives on its own pages, which the rarer act earns. End access
states way, day and note on a held copy. Edit end restates a standing
end's way, day and note, and its "It didn't end" button voids it, for an
end stated by mistake; a copy that came back is Resume's act, a dated
fact the history keeps. End access on an ended copy redirects to Edit
end, and Edit end on a held copy to End access.

Add, End access and Resume carry a submission key
(`form.submission_key()`), as the device form does, so a double press
is absorbed, not refused. End access, Edit end and Resume post the end
marker the page rendered, as `DeviceForm` posts `access_end_seen`, and
refuse with `CHANGED_SINCE_OPENED` where the row moved since. A press
whose submission key already ran skips that check, so its repeat
replays rather than reading its own write as another tab's.

`end_entry_access` in `games/writes/libraryentry.py` dispatches
`EndEntryAccess` alone under an idempotency key, so a second tab is
refused rather than correcting the end, which `restate_entry`'s
`endpoint_move` would do. Restore resolves a removed entry through a
library-scoped plain-manager lookup, since `library_entries` excludes it.
Every route is classified in `games/views/returns.py`. Remove keeps the
one confirmation page every removal has, and offers Undo.

### The Release picker

A `SearchSelect` over `GET /api/releases/search` with `game_id` and `q`,
answering `{value, label, data}` for the game's visible live Releases.
A label is platform, then the edition where it has a name, then the year:
"PS5 · Deluxe · 2021". Add preselects the game's default Release.

Where the page knows the Game is the library's own (Game detail), the
picker offers a create row with the verb "Create release", which renders
`Create release “<text>”`. On the Add to library page the Game is picked
on the client, so the create row is always offered, and the route
answers for a shared Game.

The row posts `{name, game_id}` to `POST /api/releases/`, which:

1. answers 404 for a Game the library cannot see, and 422 with the
   sentence "Record this game as your own game to add a release to it"
   for a shared Game;
2. resolves one visible live Platform whose trimmed name equals the text,
   ignoring case; none answers 422 naming the Platforms page; several answer
   422 naming each, as shared or yours, with its group;
3. answers the live Release on that Platform under the default Edition
   where one exists, as `POST /api/devices/` answers a name it holds;
4. else states a Release on that Platform under the default Edition (the
   lone Edition otherwise), date unset, through `state_catalog_graph`
   inside `write_and_mirror`, restating the Edition's own name;
   `write_and_mirror` is atomic already, and the route dispatches no
   command. A `ValidationError` from it (`GraphRefused`, or
   `LEGACY_IDENTITY_TAKEN` from `games/catalog_compat.py`) is raised
   again as `RowRefused` with its messages, so it answers 422 with a
   toast, never 500.

A shared Game with no Release shows the same sentence in the section in
place of Add, and the section offers no Add button. #1375 owns a library's Release under a shared Edition.

### Add to library

Route `library/add`, name `add_to_library`. It is the Add page
with a Game picker in front; the Release picker's `params` name the Game
field by its posted name (`self.add_prefix("game")`, set after
`super().__init__`), so it searches again when the Game changes. An untracked game is
tracked in the same dispatch, as `RecordEntry` does. The Library page's
"Temporary home" row offers it beside Add purchase. P5 adds the purchase
segment and retires Add purchase.

## 2. The Library tab

`PageTabs("Games", …)` with Games (`list_games`) and Library
(`list_library`, route `game/library`) renders on both pages, as
`PlaytimeTabs` does. On the Library tab, the tab row ends with an
"Add to library" `ControlButton`. PR 2 judges the stack of tabs, button
and quick bar by screenshot; if it reads crowded, a quick bar collapsed by
default is a change to every list and gets its own issue.

**Columns**: Game (not hideable), Platform, Access, Format, Acquired,
Access ended (way · day), Created (off by default). Sorts on each.

**`LibraryEntryFilter`** in `games/filters.py`, named after its model
because `filter_for_model` builds the name: `access`, `format`,
`acquired` (the opening endpoint's interval), `is_ended` and
`access_ended` from `endpoint_filter_fields`, `access_end_way` from
`way_filter_field`, `platform` through the Release, `game`, `created_at`
through `calendar_day_handler`, `search` over the game's name, and
`game_filter`. Quick facets in order: access, format, ended, way,
platform, acquired, game.

**Mode `entries`** reaches every registry that names a mode:
`MODE_CHOICES` (with a migration altering `FilterPreset.mode` and
`ListColumnChoice.mode`), `FILTER_MODE_MODELS`, `FILTER_MODE_LIST_URLS`,
`MODE_SORTS`, `BUILDER_MODES`, the parse table, `QUICK_FACETS`,
`LIST_COLUMNS` (without it, the column picker's Apply is 404), and
`LIST_ROUTES` in `render_pages`. `filter_queryset_for_library` answers
`library_entries(library)` for `LibraryEntry`, and
`filter_query_context_for_library` scopes `LibraryEntry` the same way.

**Tray**: `entry.edit` and `entry.remove`, declared in
`games/bulk_actions.py`, Undo through `EventRows(LibraryEntry)`. Edit
sets access, format and note; an empty field keeps, and note is an
`UnsetWidget(…, none_label="No note")` so it can be cleared. Remove runs
`RemoveEntry`; its Undo runs `RestoreEntry`.

**The fact-change reader**: `_Fact` and `_change` move from
`games/reads/playergame_facts.py` into `games/reads/fact_change.py`
beside `FactChange`, parameterised by the creation event and the facts.
A fact's value before a batch is the latest earlier event's value; where
that event is the creation, a fact with a constant takes the constant (a
game's status) and a fact without one reads the creation's payload (a
copy's access, format and note). `batch_fact_changes` for a game and a
new reader for a copy call it; P5's purchase edit is the third caller.

**Row menu** (`games/views/entry_menu.py`): Edit, End access or Resume
(whichever applies), Remove. Edit, End access and Resume link to the
game's page with that form open; Remove links to the confirmation. The
trigger reads "<game> (<platform>) actions", "Unspecified" where the
Release names no platform.

**Game detail** gains View all, to the tab filtered to the game.

## 3. The Games tab

**`AccessBadge`** in `common/components/domain.py`, a builder of its
own, not a `Pill` kind. Filled is `solid-brand`, the on-color utility;
outlined is a border with body text. One pill, three signals. A copy is *held* where it is live and no end stands.

- **Fill**: filled where the game has a held copy with access `owned`;
  outlined otherwise.
- **Glyph**: the formats of the held copies: cloud (digital), disc
  (physical), both, or the `unspecified` glyph (unknown). With no held
  copy, the glyph of the copy whose end is latest, by upper bound, then
  `access_end_recorded_at`.
- **Number**: the count of held copies, where above one.

Each glyph renders `aria-hidden` without its `<title>`. A `title` and a
visually hidden text carry the rest: each held copy's access and format,
or "Not owned · formerly <access> · <format>, <way> <day>". A game with
no live copy has no badge.

The cloud glyph is a new filled snippet, `games/templates/icons/cloud.html`,
drawn to match `physical.html` in weight and size, then `make gen-icons`.
It is judged by screenshot on the real page, not by measurement.

**`access_summaries(library, game_ids)`** in `games/reads/entries.py`
reads the page's rows in one query over `library_entries`.

**Column**: "Access", key `access`, `hidden_by_default=True`, no sort.

**`GameFilter`** gains four keys. Each subquery reads
`context.queryset_for(LibraryEntry)`, so a shared Game counts one
library's copies.

- `access` and `format`, each a `FilterField` stating its own `choices`
  and `nullable=True`, as `activity` does, with a handler over the held
  copies' words. It honours the set criterion's modifier and its
  `excludes` list, which the ✗ pill emits: INCLUDES, a held copy with one
  of the words; EXCLUDES, no held copy with any of them; INCLUDES_ONLY,
  at least one held copy and every held copy's word in the set; IS_NULL,
  no held copy; NOT_NULL, a held copy; and beside any of these but the
  presence pair, no held copy with an excluded word. INCLUDES_ALL, which
  the widget never offers for a handler field, means a held copy with
  each word.
- `entry_count`, an aggregate over live copies, ended included, scoped by
  a `LibraryEntryFilter`.
- `entry_filter`, a relation.

Quick facets access and format join the Games list's facets.

## Not in this issue

- Purchases in the section, the tab and `LibraryEntryFilter` (P5).
- Bulk End access (#1355).
- A library's own Release under a shared Edition (#1375).
- A Release on a session or a record (#1354).

## Tests that name every member

Each PR changes the exact lists its additions join:

- PR 1: `tests/test_rendered_pages.py` (`test_view_game`,
  `test_view_game_empty_sections`), `tests/test_returns_classification.py`.
- PR 2: `_ALL_FILTERS` and `ALL_FILTERS` in `tests/test_filters.py`,
  `_BAR_CASES` in `tests/test_filter_paths.py`,
  `tests/test_filter_widgets.py`, `tests/test_list_columns_view.py`,
  `tests/test_column_choice_lists.py`,
  `tests/test_action_origin_parity.py`, `tests/test_paths_return_200.py`,
  `tests/test_filter_presets.py`, `tests/test_render_pages.py`.
- PR 3: `tests/test_quick_filter_bar.py`, the icon tests.

## Proof

- `make render-pages` before and after each PR on one database. The
  deployment holds no copy before P4, so each PR also runs it on a scratch
  restore after recording a few copies through the API, and attributes
  every difference.
- Two-library tests: another library's copies never render, count, or
  match a facet; its private Release and its Game answer 404 from the
  picker and the create route.
- One test per route: success, an invalid form at 200 with that form open,
  a refusal at its status, 404 for another library's entry, a GET
  redirecting to the open form, a repeated submission recording once.
- Bulk tests for both acts and their Undo; a test that the shared reader
  answers a game's facts as before and a copy's from its creation.
- An e2e test per PR: open a disclosure and use the Release picker and the
  temporal field inside it; add, end, resume and remove a copy; select two
  copies and edit them; filter the Games tab by access.
- Orca checks added to #1335, each with a recipe: the badge's spoken
  text, a card's buttons and disclosure, the Library tab's row menu.
- Full `make check`.
