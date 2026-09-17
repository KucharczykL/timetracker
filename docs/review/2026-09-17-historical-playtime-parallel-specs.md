# Review: the three parallel Historical Playtime specs

Date: 2026-09-17. Reviewer: the coordinating session.
Wave: [Historical Playtime](../superpowers/specs/2026-09-17-historical-playtime-wave-design.md).
Base: `main` at 670b5fe3, with #705 merged.

Inputs, one per worktree:

| issue | branch | spec |
|---|---|---|
| #706 | `claude/issue-706-planning-6e406e` (ccc8c576) | `docs/superpowers/specs/2026-09-17-issue-706-historical-playtime-entry-design.md` |
| #709 | `claude/issue-709-planning-8f15e9` (cfa438b2) | `docs/superpowers/specs/2026-09-17-issue-709-historical-playtime-reads-design.md` |
| #1097 | `claude/issue-1097-planning-23e520` (440b5f37) | `docs/superpowers/specs/2026-09-17-issue-1097-playtime-page-design.md` |

Every claim below was checked against the code on `main`, not against the
specs alone. Each branch reads this document, amends its spec, and only then
writes its plan.

## Verdict

The three boundaries are right: #706 writes, #709 sums, #1097 lists. Nothing
is built twice. But the one shared module is described three different ways,
one scope text misses a mark, two specs rely on a function that raises, and
every cross-issue comment the specs say was posted does not exist. Six
decisions below settle the shared surface; each spec then has its own list.

## Decisions on the shared surface

### D1. Two read modules, one fixed text

The specs disagree on where the record scope lives:

- #706: `games/reads/historical_playtime_records.py` with `game_records`,
  `library_record`, `any_library_record`; claims "neither sibling uses these
  names".
- #709: `games/reads/historical_playtime.py` with `library_records` and
  `game_records`, plus every sum.
- #1097: `games/reads/historical_playtime_records.py` with `library_records`
  and `readable_records`.

`game_records` is named by #706 and #709 in two files with two meanings.
Decision: mirror the session split, `player_sessions.py` for scope and
`playtime.py` for sums.

| module | owner | contents |
|---|---|---|
| `games/reads/historical_playtime_records.py` | shared; first to merge owns it, the others take `main`'s copy on rebase | `library_records`, `readable_records`, `game_records`, `RECORD_ORDER` |
| `games/reads/historical_playtime.py` | #709 alone | `contained_in`, `historical_total`, `historical_summed_by_game`, `historical_by_platform`, `historical_by_month`, `historical_years`, `game_historical_playtime` |

The shared module is this text, and no branch adds to it:

```python
"""The records a library counts, and the row path a page reads."""

from django.db.models import F

from games.models import (
    Game,
    HistoricalPlaytime,
    HistoricalPlaytimeQuerySet,
    UserLibrary,
)

#: Newest first; an unknown `when` last; then newest recorded.
RECORD_ORDER = (F("when_lower").desc(nulls_last=True), "-created_at", "id")


def library_records(library: UserLibrary) -> HistoricalPlaytimeQuerySet:
    """Every live record this library counts.

    A copy of this breaks quietly. The record's and its tracked
    game's libraries are both stated: either can name another
    library's row. `alive()` alone keeps the records of a removed
    catalog game.
    """
    return HistoricalPlaytime.objects.filter(
        library=library,
        player_game__library=library,
        removed_at__isnull=True,
        player_game__removed_at__isnull=True,
        player_game__game__removed_at__isnull=True,
    )


def readable_records(library: UserLibrary) -> HistoricalPlaytimeQuerySet:
    """The row path the list, the section and the API share."""
    return library_records(library).select_related(
        "player_game__game__platform", "device"
    )


def game_records(library: UserLibrary, game: Game) -> HistoricalPlaytimeQuerySet:
    """The counted records at one catalog game."""
    return library_records(library).filter(player_game__game=game)
```

Run names are not in the module: a page numbers runs with
`numbered_for(library, player_game_ids)` over the page's rows and joins in
Python, as #1097 already states. #706's section does the same over one game.

#706's `library_record` and `any_library_record` are view resolvers, as
`_library_session` is in `games/views/session.py`. They move into #706's view
module as private functions. The shared module then holds nothing only one
issue wants.

### D2. The scope states five conditions

#709's text is right. #706 states `library` and `alive()` only; #1097 states
both libraries but only two marks. `HistoricalPlaytimeQuerySet.alive()` reads
the record's mark and the `PlayerGame`'s (`ancestor_marks = ("player_game",)`),
never the catalog game's, and CLAUDE.md says the read layer states that mark
itself. `library_sessions` is the precedent: library on every hop, every mark.
D1's text is the one to carry.

### D3. One order for records

#706 orders the section `when_lower` desc nulls last, `created_at` desc, id.
#1097 defaults the list to `-when,created`. Decision: `RECORD_ORDER` in D1,
newest recorded first on a tie, in both places. #1097's `-when` sort key
orders `when_lower` and lets `apply_sort` put nulls last, as today.

### D4. Row actions and "View all" belong to the second merge

#1097 says the second of #706 and #1097 to merge adds the list's Actions
column. #706 says nothing about it and files "View all" as a follow-up.
Decision: whichever of the two merges second adds both, in its own PR:

- the Actions column on the Historical list (Edit, Remove, through
  `action_url` with the origin);
- the "View all" link from the Game detail section to the list, narrowed to
  the game (`_game_section`'s existing `view_all_url`).

Both specs state this. Neither files a follow-up for it.

### D5. `CLAUDE.md` is edited three times

All three replace the sentence "Nothing reads or writes it from a page yet."
in the HistoricalPlaytime entry (line 397). Rule: each branch replaces that
sentence with one sentence of its own; the second and third to merge keep
`main`'s sentence and append theirs. Nothing else in that entry is touched.

### D6. No cross-issue comment exists

#709 says its scope functions "are posted on both issues"; #1097 says its
sharing "is stated on #709" and the Actions column "on #706"; #706 says #710
"is told" of the header deviation. None of #706, #709, #1097 or #710 has a
comment. This document is the one place the agreement lives. Each branch
links it from its own issue in one comment, and #709 comments on #710 once
with D4 and the header deviation (P706-4).

## #706: findings

Blocking:

1. **`display_name` raises on the form's choices.** The spec labels
   `live_ordinary_runs(library, tracked)` with `display_name`. That function
   is `games.reads.playthrough_numbering.display_name`, and it raises
   `UnnumberedPlaythrough` for a blank-named run unless the queryset carries
   `display_number`, which `live_ordinary_runs` does not annotate. Use
   `numbered_for(library, [tracked.pk])` for the choices and for the section.
2. **"Removed playthrough" is unreachable for a live record.**
   `BLOCKING_REFERRERS` already holds `HistoricalPlaytimeRun.playthrough`
   (`games/commands/playthrough.py:534`), so `RemovePlaythrough` refuses a run
   a live record names, as #709 states. Drop the fallback and the test for it;
   a live record's runs are always numbered.
3. **Edit of a record naming a removed device.** `Restate` keeps a held
   device only when the posted `device_id` equals the row's
   (`games/commands/historical_playtime.py:283`). The session form's device
   resolver offers live devices, so an Edit form cannot repost a removed one
   and would state `None`, which is a change. State how the form keeps it:
   the initial device rides as the selected option even when the resolver
   would not offer it, and the test "restate keeps a removed device" is added.
4. **Scope.** Take D1 and D2; the section's queryset is
   `readable_records(library).filter(player_game__game=game).order_by(*RECORD_ORDER)`.

Amend:

5. State D4 (the second merge adds the list's Actions column and the
   section's "View all") and drop the "View all" follow-up.
6. The header deviation (count badge, not the plain total) stands: the total
   is #709's read and #710's presentation. Comment on #710 goes through #709
   (D6).
7. The view module name `games/views/historical_playtime_entry.py` stands;
   #1097 takes `games/views/historical_playtime.py` (P1097-5).

Verified as stated: `owned_or_404`, `Game.objects.tracked_by`,
`latest_ordinary_run`, `TemporalFormField`, `when_sentence`,
`confirm_and_apply` with `fallback_args` and `undo`, `restore_and_return`
with `restored=`, `_game_section` (gains `add_url`), `AT_LEAST_ONE_RUN`,
`AT_LEAST_A_SECOND`, `answered("historical playtime")` beside the four
subjects in use, `Duration(..., id_scope=...)`, `TemporalText`.

## #709: findings

Blocking: none. The rule, the breakdown, the expressions, the classification
and the callers all check out against `games/reads/playtime.py`,
`games/views/game.py:168` and `games/views/general.py:53`.

Amend:

1. Split the module per D1: scope in `historical_playtime_records.py`, sums
   in `historical_playtime.py`. The sums import `library_records`.
2. `tests/test_playtime_sources.py` exists (23 tests over the session
   sums). The spec lists it as new; it is extended.
3. The "Parallel work" section claims the scope functions are posted on both
   issues. They are not (D6). Replace the claim with a link to this document.
4. The `StatsData` classification table names `total_hours` and
   `total_playtime` in the issue; the model has `total_hours` only. The spec
   is right; the issue body is stale. Say so in the issue comment.
5. The follow-up "GameFilter relation to records" is shared with #1097's
   note that its `when` filter reads overlap, not containment. One issue, filed
   by #709, states both: the relation, and a containment modifier or a second
   field, so the stats link and the stat compile one predicate. #1097 files
   nothing for it.

## #1097: findings

Blocking:

1. **Scope.** Take D1 and D2. The spec's `library_records` reads two marks;
   the catalog game's is missing.
2. **Name the tests the mode inherits.** "The existing keyset tests then cover
   the new mode without change" names `tests/test_keyset.py`, which tests
   `keyset_pages()` and knows no mode. The tests that walk the mode registries
   are `tests/test_filter_presets.py`, `tests/test_quick_filter_bar.py`,
   `tests/test_filter_widgets.py` and `tests/test_render_pages.py`. Name the
   ones the plan relies on.

Amend:

3. **The Library card.** "Playtime" over a count of sessions plus records is
   a row count under a duration's name. Keep the relabel and the link; the
   value stays the count for now and #710, which owns presentation and
   follows #709, replaces it with the `PlaytimeSplit` total. Say so in the
   spec and in #709's comment on #710 (D6). If a count is kept, the card's
   `title` says what is counted.
4. **Order.** Take D3: the default sort is `-when` then `-created`.
5. **Name the view module** `games/views/historical_playtime.py`; #706
   reserved it. Name the test files so they cannot collide with #706's
   (`test_historical_playtime_form.py`, `_views.py`,
   `test_game_detail_historical_playtime.py`) or #705's (`_command.py`,
   `_events.py`, `_projection.py`): `tests/test_historical_playtime_filter.py`,
   `tests/test_historical_playtime_api.py`, `tests/test_playtime_page.py`,
   `e2e/test_playtime_page_e2e.py`.
6. `SessionListOut` is the session list's envelope; the new list gets its
   own `HistoricalPlaytimeListOut` of the same five fields, or the spec says
   the two routers share one generic envelope. Pick one.
7. The nav deviation (no "Sessions" entry exists; the Library card, the
   landing-page choice and the `index` redirect are the three entries) is
   verified. The wave document says "nav entry"; #1097's PR amends the wave's
   Screens section in one sentence.
8. `PageTabs` is new. The only `aria-current="page"` today is the
   pagination nav in `primitives.py`; no tabs primitive exists to reuse.

Verified as stated: migration `0010` is next; `filter_queryset_for_library`
falls back to `for_library()`; `temporal_interval_handler(value, lower,
upper)` and `metadata_lookup`; `duration_hours_handler` over a
`DurationField`; `comparison_through` declared; `numbered_for` takes many
games; `render_pages.LIST_ROUTES`; the e2e table-width and responsive-table
route lists.

## Agreements that hold without change

- **Containment for sums, overlap for the filter.** #709 counts a record in
  a period only when both bounds lie inside; #1097's `when` facet matches a
  record whose interval touches the range, as Playthrough's endpoints do. Both
  specs say so. The gap is one follow-up (#709 item 5).
- **Per-platform through the game's platform column** until #889. Recorded
  in #709 and the wave.
- **`playtime_matching` stays sessions-only**, and the game list's column
  header says so under a session filter.
- **No `run` field on the filter**; a run's records are read from Game
  detail.
- **`game_historical_playtime` is #709's**; #706 avoids it.
- **`games/views/game.py`**: #709 changes the header call at line 1069, #706
  adds a section between lines 941 and 1003. Adjacent, not overlapping.
- **`games/urls.py`, `games/views/returns.py`, `games/api.py`,
  `games/filters.py`**: one block each; conflicts are adjacent lines.

## Merge order

None is required. The first to merge owns the shared module (D1); each later
branch rebases, takes `main`'s copy, and resolves `CLAUDE.md` by D5. The
second of #706 and #1097 carries D4. #710 waits on #709, as the wave says.

## Follow-ups to file

1. #709 files: `GameFilter` relation to historical playtime records with a
   containment modifier, so a stats link finds a game only records reach.
   After #1097.
2. #709 files: a stated session count on a record (its follow-up 2),
   after the wave.
3. #709 comments on #710: `PlaytimeSplit` in the Game detail section header
   and as the Library card's value.
4. #1097 amends the wave document's Screens section: no nav entry; the three
   entries named above.

## What each branch does next

- Amend the spec per its list above and per D1 to D6.
- Comment once on its own issue with a link to this document.
- Write the plan. The plan names the shared module's text as D1's, verbatim.
