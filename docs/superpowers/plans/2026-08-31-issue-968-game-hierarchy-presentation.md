# Game hierarchy presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a Game's live Editions and their live Releases on Game detail, and
retire the two flattened legacy rows that stood in for them.

**Architecture:** One read module answers the whole visible graph in two
queries; `games/views/game.py` renders it two ways. The ordinary Game — one
unnamed Edition, at most one Release — keeps its two facts as header meta rows
where the Platform row is today. Anything richer gets a `Releases` section below
the header, one table per Edition. Nothing writes, and no route changes.

**Tech Stack:** Django 6, Python 3.14, the `common.components` node tree,
`common/temporal_presentation.py` (#963), pytest.

**Spec:** `docs/superpowers/specs/2026-08-30-issue-968-game-hierarchy-presentation-design.md`

## Global Constraints

- **A read only.** No write, route, form, action or link that mutates. #969
  owns every control; this issue adds none, not even for a private Game.
- **No legacy column is dropped.** `Game.platform`, `Game.year_released` and
  `Game.original_year_released` stay as columns and stay written by the legacy
  form. #889 removes them. This issue stops *reading two of them on this page*.
- **`Original release` stays.** It reads `Game.original_release_date`, a fact of
  the work, through `TemporalText`. The spec says so twice, and the #963 spec's
  **Callers** section names it. (Comment 5477… on #968 says this row goes; it
  conflicts with both specs and is treated as an error about which legacy field
  is which — `year_released` is the flattened Release year, and that one goes.)
- **A shared Game gets no mark.** The spec's "marked as not editable here" is
  **deferred, deliberately.** A shared row exists in the schema and in nothing a
  person can reach: no route makes one, and the IGDB wave (#782, #783, #784) is
  where the first ones arrive and where the words for them get designed. A mark
  here would name a mechanism before its behaviour is decided. The *reads* stay
  library-correct and stay tested; only the badge is left out. #969 revisits it
  when the absence of a control first needs explaining.
- **Every read is library-scoped.** `Edition.objects.visible_to(library)` and
  `Release.objects.visible_to(library)`, never `game.editions` — a shared Game's
  reverse accessors reach every library that ever wrote under it.
- **A removed row does not appear.** `visible_to()` calls `alive()`, which reads
  ancestor marks too (#966), so a removed Game, Edition or Release drops out.
- **Game URLs are unchanged.**
- Component rules from `CLAUDE.md`: build with `common.components` builders in
  htpy form, `Fragment` to group siblings, unabbreviated identifiers, named
  compound types, `#:` notes at roughly seven words.
- Verification gate: full `make check`, default parallel workers.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `games/reads/catalog_hierarchy.py` (create) | The visible Editions of one Game, each with its visible Releases, ordered, in two queries. |
| `tests/test_catalog_hierarchy_read.py` (create) | Grouping, ordering, removal, isolation, query count. |
| `games/views/game.py` (modify) | Renders the two shapes; loses the Platform meta row and the title year popover. |
| `tests/test_game_hierarchy_section.py` (create) | Page-level: ordinary shape, rich shape, unspecified Platform, isolation. |
| `tests/test_rendered_pages.py` (modify) | The legacy-row assertions this page no longer owes. |
| `docs/catalog.md` (modify) | What Game detail shows, and when it collapses. |
| `docs/superpowers/specs/2026-08-30-issue-963-temporal-presentation-design.md` (modify) | Record this page in **Callers**, as the hand-off asks. |

---

### Task 1: The read

**Files:**
- Create: `games/reads/catalog_hierarchy.py`
- Test: `tests/test_catalog_hierarchy_read.py`

**Interfaces:**
- Consumes: `Edition`, `Release`, `Game`, `UserLibrary` from `games/models.py`;
  `EditionQuerySet.visible_to` / `ReleaseQuerySet.visible_to`, which already
  call `alive()`.
- Produces:
  - `class EditionEntry(NamedTuple)` with `edition: Edition` and
    `releases: tuple[Release, ...]`
  - `def game_hierarchy(game: Game, library: UserLibrary) -> tuple[EditionEntry, ...]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_catalog_hierarchy_read.py`:

```python
"""What one library sees under one Game."""

import pytest
from django.contrib.auth import get_user_model

from games.models import Edition, Game, Platform, Release
from games.reads.catalog_hierarchy import game_hierarchy
from games.removal import remove
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db


@pytest.fixture
def library():
    return get_user_model().objects.create_user(username="hierarchy-reader").library


@pytest.fixture
def stranger():
    return get_user_model().objects.create_user(username="hierarchy-stranger").library


def test_game_hierarchy_groups_releases_under_their_editions(library):
    game = Game.objects.create(library=library, name="Elite")
    gold = Edition.objects.create(game=game, name="Gold")
    plus = Edition.objects.create(game=game, name="Plus")
    gold_release = Release.objects.create(edition=gold)
    plus_release = Release.objects.create(edition=plus)

    entries = game_hierarchy(game, library)

    assert [(entry.edition, entry.releases) for entry in entries] == [
        (gold, (gold_release,)),
        (plus, (plus_release,)),
    ]


def test_game_hierarchy_puts_the_default_first(library):
    game = Game.objects.create(library=library, name="Elite")
    Edition.objects.create(game=game, name="Alpha")
    standard = Edition.objects.create(game=game, name="Zulu", is_default=True)

    entries = game_hierarchy(game, library)

    assert entries[0].edition == standard


def test_game_hierarchy_orders_releases_by_their_earliest_day(library):
    game = Game.objects.create(library=library, name="Elite")
    edition = Edition.objects.create(game=game)
    later = Release.objects.create(
        edition=edition, release_date=TemporalValue.from_year(1985)
    )
    earlier = Release.objects.create(
        edition=edition, release_date=TemporalValue.from_year(1984)
    )
    undated = Release.objects.create(edition=edition)

    entries = game_hierarchy(game, library)

    assert entries[0].releases == (earlier, later, undated)


def test_game_hierarchy_leaves_out_a_removed_edition_and_a_removed_release(library):
    game = Game.objects.create(library=library, name="Elite")
    kept = Edition.objects.create(game=game, name="Kept")
    gone = Edition.objects.create(game=game, name="Gone")
    kept_release = Release.objects.create(edition=kept)
    gone_release = Release.objects.create(edition=kept)
    Release.objects.create(edition=gone)
    remove(gone)
    remove(gone_release)

    entries = game_hierarchy(game, library)

    assert entries == ((kept, (kept_release,)),)


def test_game_hierarchy_gives_another_library_nothing(library, stranger):
    game = Game.objects.create(library=library, name="Private")
    edition = Edition.objects.create(game=game)
    Release.objects.create(edition=edition)

    assert game_hierarchy(game, stranger) == ()


def test_game_hierarchy_shows_a_shared_game_to_every_library(library, stranger):
    shared = Game.objects.create(name="Shared")
    edition = Edition.objects.create(game=shared)
    release = Release.objects.create(edition=edition)

    for reader in (library, stranger):
        assert game_hierarchy(shared, reader) == ((edition, (release,)),)


def test_game_hierarchy_carries_the_platform_and_the_name_with_it(
    library, django_assert_num_queries
):
    """Two queries, whatever the graph holds.

    `display_name` reads the Game and a row reads its Platform,
    thus both are selected: a per-row read would grow with the list.
    """
    platform = Platform.objects.create(library=library, name="Amiga")
    game = Game.objects.create(library=library, name="Elite")
    first = Edition.objects.create(game=game, name="Gold")
    second = Edition.objects.create(game=game, name="Plus")
    Release.objects.create(edition=first, platform=platform)
    Release.objects.create(edition=second)

    with django_assert_num_queries(2):
        entries = game_hierarchy(game, library)
        read = [
            (entry.edition.display_name, entry.releases[0].platform)
            for entry in entries
        ]

    assert read == [("Gold", platform), ("Plus", None)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_catalog_hierarchy_read.py"`
Expected: FAIL, `ModuleNotFoundError: No module named 'games.reads.catalog_hierarchy'`

- [ ] **Step 3: Write the read**

Create `games/reads/catalog_hierarchy.py`:

```python
"""The Editions and Releases one library sees under one Game."""

from typing import NamedTuple
from uuid import UUID

from django.db.models import F
from django.db.models.functions import Lower

from games.models import Edition, Game, Release, UserLibrary


class EditionEntry(NamedTuple):
    """One Edition and the Releases under it."""

    edition: Edition
    releases: tuple[Release, ...]


def game_hierarchy(game: Game, library: UserLibrary) -> tuple[EditionEntry, ...]:
    """This Game's visible Editions, each with its Releases.

    Two queries, and no reverse accessor: a shared Game's
    accessors reach every library that ever wrote under it.
    `visible_to()` calls `alive()`, thus a removed row and the
    children of one both drop out.
    """
    editions = list(
        Edition.objects.visible_to(library)
        .filter(game=game)
        .select_related("game")
        .order_by("-is_default", Lower("name"), "pk")
    )
    releases = (
        Release.objects.visible_to(library)
        .filter(edition__in=editions)
        .select_related("platform")
        #: The default first, then the earliest day anyone knows.
        .order_by(
            "-is_default",
            F("release_date_lower").asc(nulls_last=True),
            "pk",
        )
    )
    grouped: dict[UUID, list[Release]] = {edition.pk: [] for edition in editions}
    for release in releases:
        grouped[release.edition_id].append(release)
    return tuple(
        EditionEntry(edition, tuple(grouped[edition.pk])) for edition in editions
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_catalog_hierarchy_read.py"`
Expected: 7 passed.

If `test_game_hierarchy_orders_releases_by_their_earliest_day` fails on the
undated row, check the `nulls_last=True`: PostgreSQL sorts NULL first ascending
by default, which would put the undated Release ahead of both dated ones.

- [ ] **Step 5: Type-check and commit**

Run: `make typecheck`

```bash
git add games/reads/catalog_hierarchy.py tests/test_catalog_hierarchy_read.py
git commit -m "Read a Game's visible Editions and their Releases"
```

---

### Task 2: The ordinary Game reads its own Release

**Files:**
- Modify: `games/views/game.py` — module constants near line 101,
  `_game_header` (562-660), `view_game` (815-851)
- Create: `tests/test_game_hierarchy_section.py`
- Modify: `tests/test_rendered_pages.py:350-372` (`test_view_game`)

**Interfaces:**
- Consumes: `EditionEntry`, `game_hierarchy` from Task 1.
- Produces, all module-level in `games/views/game.py`:
  - `GREY_VALUE_CLASS: str`, `UNSPECIFIED_PLATFORM: str`
  - `def _platform_words(release: Release | None) -> str`
  - `def _reads_plainly(entries: Sequence[EditionEntry]) -> bool`
  - `def _plain_release_rows(entries, presentation) -> list[Node]`
  - `_game_header(...)` gains a final parameter `entries: Sequence[EditionEntry]`

This task leaves the rich shape unrendered on purpose: every Game in the
database today holds one Edition, so the plain shape is the whole page. Task 3
adds the section for the graphs #969 will let a person build.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_game_hierarchy_section.py`:

```python
"""What Game detail says about Editions and Releases."""

import pytest
from django.contrib.auth import get_user_model

from games.models import Edition, Game, Platform, Release
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return get_user_model().objects.create_user(username="hierarchy-page", password="p")


@pytest.fixture
def library(user):
    return user.library


@pytest.fixture
def reader(client, user):
    client.force_login(user)

    def read(game):
        return client.get(game.get_absolute_url()).content.decode()

    return read


def one_release(library, *, platform=None, release_date=None, name=""):
    """A Game shaped the way the legacy form leaves one."""
    game = Game.objects.create(library=library, name="Elite")
    edition = Edition.objects.create(game=game, name=name, is_default=True)
    Release.objects.create(
        edition=edition,
        platform=platform,
        release_date=release_date,
        is_default=True,
    )
    return game


def test_game_detail_reads_the_one_release_platform_and_date(library, reader):
    platform = Platform.objects.create(library=library, name="Amiga")
    game = one_release(
        library, platform=platform, release_date=TemporalValue.from_month(1984, 6)
    )

    html = reader(game)

    assert "Platform" in html
    assert "Amiga" in html
    assert "Released" in html
    assert "June 1984" in html
    assert "1984-06" not in html


def test_game_detail_says_unspecified_for_a_release_with_no_platform(library, reader):
    game = one_release(library, release_date=TemporalValue.from_year(1984))

    html = reader(game)

    assert "Unspecified" in html


def test_game_detail_says_unknown_for_a_release_with_no_date(library, reader):
    platform = Platform.objects.create(library=library, name="Amiga")
    game = one_release(library, platform=platform)

    html = reader(game)

    assert "Unknown" in html


def test_game_detail_reads_no_release_at_all_without_falling_over(library, reader):
    """A Game the service never touched still renders.

    Nothing but a test makes one, and a 500 here would hide
    every other assertion on the page.
    """
    game = Game.objects.create(library=library, name="Bare")

    html = reader(game)

    assert "Unspecified" in html
    assert "Unknown" in html


def test_game_detail_no_longer_reads_the_legacy_platform_column(library, reader):
    """The column stays; this page stops believing it.

    #889 drops it. Until then a Game may carry a column the
    graph disagrees with, and the graph is what a Release states.
    """
    stale = Platform.objects.create(library=library, name="Stale Column")
    game = one_release(library)
    Game.objects.filter(pk=game.pk).update(platform=stale)

    html = reader(game)

    assert "Stale Column" not in html


def test_game_detail_no_longer_shows_the_legacy_release_year(library, reader):
    game = one_release(library)
    Game.objects.filter(pk=game.pk).update(year_released=1999)

    html = reader(game)

    assert "Release year" not in html
    assert 'id="popover-year"' not in html


def test_game_detail_keeps_the_original_release_of_the_work(library, reader):
    game = one_release(library)
    Game.objects.filter(pk=game.pk).update(
        original_release_date=TemporalValue.from_year(1983)
    )

    html = reader(game)

    assert "Original release" in html
    assert "1983" in html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_game_hierarchy_section.py"`
Expected: FAIL. `test_game_detail_reads_the_one_release_platform_and_date` fails
on `"Released" in html`; the two legacy tests fail because the page still shows
`Stale Column` and `Release year`.

- [ ] **Step 3: Add the module constants and the two helpers**

In `games/views/game.py`, add to the imports:

```python
from games.models import (
    Game,
    PlayerGameStatus,
    PlayEvent,
    Purchase,
    Release,
    Session,
    SessionQuerySet,
    UserLibrary,
)
from games.reads.catalog_hierarchy import EditionEntry, game_hierarchy
```

Beneath `WIKIDATA_CONFLICT_MESSAGE` (line 101), add:

```python
#: The value half of a meta row, against the label's grey.
GREY_VALUE_CLASS = "text-black dark:text-slate-300"
#: No Platform is a stated fact, not a blank.
UNSPECIFIED_PLATFORM = "Unspecified"
```

Add, just above `_game_header`:

```python
def _platform_words(release: Release | None) -> str:
    """A Release says which Platform, or says nobody said."""
    if release is None or release.platform is None:
        return UNSPECIFIED_PLATFORM
    return release.platform.name


def _reads_plainly(entries: Sequence[EditionEntry]) -> bool:
    """One unnamed Edition holding at most one Release.

    That shape says everything in two rows, thus a section of
    headings above them would be scaffolding around one fact.
    """
    if len(entries) > 1:
        return False
    if not entries:
        return True
    entry = entries[0]
    return not entry.edition.name and len(entry.releases) <= 1


def _plain_release_rows(
    entries: Sequence[EditionEntry], presentation: DateTimePresentation
) -> list[Node]:
    """The ordinary Game states its one Release in the header.

    A richer graph states nothing here: the section below carries
    every Edition and every Release instead.
    """
    if not _reads_plainly(entries):
        return []
    releases = entries[0].releases if entries else ()
    release = releases[0] if releases else None
    return [
        _meta_row(
            "Platform",
            Span(class_=GREY_VALUE_CLASS)[_platform_words(release)],
        ),
        _meta_row(
            "Released",
            TemporalText(
                None if release is None else release.release_date,
                presentation,
                class_=GREY_VALUE_CLASS,
            ),
        ),
    ]
```

- [ ] **Step 4: Rewrite `_game_header`**

Change the signature (line 562) to take the graph:

```python
def _game_header(
    game: Game,
    request: HttpRequest,
    metrics: dict[str, Any],
    presentation: DateTimePresentation,
    durations: DurationPresentation,
    origin: OriginUrl | None,
    entries: Sequence[EditionEntry],
) -> Node:
```

Delete the `grey_value_class = "text-black dark:text-slate-300"` line (578) — the
module constant replaces it — and replace the whole `title_span` assignment
(579-598) with:

```text
    #: The year beside a name was one Release's, flattened.
    title_span = Span(class_="text-balance max-w-120")[
        Span(class_="text-type-title font-serif")[game.name],
    ]
```

`Safe` stays imported — `_stat_popover` (line 446) still uses it. `Popover`
stays too, for the same reason.

In the `metadata` block (626-654), point the `Original release` row at the
module constant, and replace the trailing `Platform` meta row with the graph's
rows:

```text
    metadata = Div(
        class_="flex flex-col mb-6 text-gray-600 dark:text-slate-400 gap-y-4 text-type-body",
    )[
        _meta_row(
            "Original release",
            TemporalText(
                game.original_release_date, presentation, class_=GREY_VALUE_CLASS
            ),
        ),
        _meta_row(
            "Status",
            Span()[
                GameStatusSelector(
                    game,
                    PlayerGameStatus.choices,
                    get_token(request),
                    current=game.tracked_status,
                )
            ],
            "👑" if game.tracked_mastered else "",
        ),
        _played_row(game, request, origin),
        *_plain_release_rows(entries, presentation),
    ]
```

- [ ] **Step 5: Read the graph in `view_game`**

In `view_game`, after the `playevents` assignment, add the read and thread it
into the header:

```text
    hierarchy = game_hierarchy(game, library)
    content = ContentContainer(class_="dark:text-white")[
        _game_header(
            game,
            request,
            _game_overview_metrics(sessions),
            presentation,
            durations,
            origin,
            hierarchy,
        ),
        _purchases_section(game, purchases, presentation, origin),
        _sessions_section(game, sessions, presentation, durations),
        _playevents_section(game, playevents, presentation, origin),
        _history_section(game, library, presentation),
    ]
```

- [ ] **Step 6: Run the new tests**

Run: `make test ARGS="tests/test_game_hierarchy_section.py"`
Expected: 7 passed.

- [ ] **Step 7: Run the pages the change touches**

Run: `make test ARGS="tests/test_rendered_pages.py tests/test_game_detail_links.py tests/test_html_validity.py tests/test_paths_return_200.py tests/test_date_time_rendering_paths.py"`

`test_view_game` still passes: its `"Platform"` marker is the label of the new
row, and its seeded Game holds no Release, so the value beside it reads
`Unspecified`. If anything else fails, read the failure before changing it —
these are the assertions the removal is allowed to break, and no others.

- [ ] **Step 8: Pin the removal in `test_view_game`**

In `tests/test_rendered_pages.py`, append two markers to the `test_view_game`
marker list, after `"Platform"`:

```text
            "Platform",
            "Released",
```

and add, directly beneath the method:

```text
    def test_view_game_drops_the_flattened_release_year(self):
        """The title said a year no Release had to agree with."""
        Game.objects.filter(pk=self.game.pk).update(year_released=1999)

        html = self.client.get(self.game.get_absolute_url()).content.decode()

        self.assertNotIn('id="popover-year"', html)
        self.assertNotIn("Release year", html)
```

- [ ] **Step 9: Run them, then commit**

Run: `make test ARGS="tests/test_rendered_pages.py tests/test_game_hierarchy_section.py"`
Expected: all pass.

Run: `make lint && make typecheck`

```bash
git add games/views/game.py tests/test_game_hierarchy_section.py tests/test_rendered_pages.py
git commit -m "Read a Game's own Release where the legacy row stood"
```

---

### Task 3: A richer graph gets a section

**Files:**
- Modify: `games/views/game.py` — new builders beside `_game_section`, one line
  in `view_game`
- Modify: `tests/test_game_hierarchy_section.py`

**Interfaces:**
- Consumes: `_reads_plainly`, `_platform_words`, `GREY_VALUE_CLASS`,
  `EditionEntry` from Task 2; `StyledTable`, `Column`, `make_row`,
  `PageHeading`, `Fragment`, already imported in `games/views/game.py`.
- Produces:
  - `def _release_table(releases: Sequence[Release], presentation) -> Node`
  - `def _edition_block(entry: EditionEntry, presentation, *, named: bool) -> Node`
  - `def _releases_section(entries: Sequence[EditionEntry], presentation) -> Node`
    — returns an empty `Fragment()` when `_reads_plainly(entries)`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_game_hierarchy_section.py`:

```python
def two_releases(library):
    """One unnamed Edition, two Releases: the shape needs a table."""
    amiga = Platform.objects.create(library=library, name="Amiga")
    dos = Platform.objects.create(library=library, name="DOS")
    game = Game.objects.create(library=library, name="Elite")
    edition = Edition.objects.create(game=game, is_default=True)
    Release.objects.create(
        edition=edition,
        platform=amiga,
        release_date=TemporalValue.from_year(1984),
        is_default=True,
    )
    Release.objects.create(
        edition=edition, platform=dos, release_date=TemporalValue.from_year(1988)
    )
    return game


def test_game_detail_tables_a_second_release(library, reader):
    game = two_releases(library)

    html = reader(game)

    assert "Releases" in html
    assert "Amiga" in html
    assert "DOS" in html
    assert "1988" in html


def test_game_detail_gives_one_unnamed_edition_no_heading(library, reader):
    """The Game's own name above its only Edition says nothing."""
    game = two_releases(library)

    html = reader(game)

    assert html.count("Releases of this edition") == 1
    assert 'text-type-subheading text-heading">Elite</span>' not in html


def test_game_detail_heads_each_of_two_editions(library, reader):
    game = Game.objects.create(library=library, name="Elite")
    gold = Edition.objects.create(game=game, name="Gold", is_default=True)
    Edition.objects.create(game=game, name="Plus")
    Release.objects.create(edition=gold, is_default=True)

    html = reader(game)

    assert "Gold" in html
    assert "Plus" in html
    assert "No releases yet." in html


def test_game_detail_heads_an_unnamed_sibling_with_the_work(library, reader):
    """An unnamed Edition presents as the Game, per `display_name`."""
    game = Game.objects.create(library=library, name="Elite")
    Edition.objects.create(game=game, is_default=True)
    Edition.objects.create(game=game, name="Plus")

    html = reader(game)

    assert 'text-type-subheading text-heading">Plus</span>' in html
    assert 'text-type-subheading text-heading">Elite</span>' in html


def test_game_detail_leaves_out_a_removed_edition(library, reader):
    game = Game.objects.create(library=library, name="Elite")
    Edition.objects.create(game=game, is_default=True)
    gone = Edition.objects.create(game=game, name="Withdrawn")
    remove(gone)

    html = reader(game)

    assert "Withdrawn" not in html
```

Extend the file's imports for these:

```python
from games.models import Edition, Game, Platform, Release
from games.removal import remove
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_game_hierarchy_section.py"`
Expected: the five new tests fail; the second Release and the second Edition
appear nowhere, because nothing renders the rich shape yet.

- [ ] **Step 3: Write the three builders**

In `games/views/game.py`, directly after `_game_section` (which ends at line
537 before this task's edits), add:

```python
def _release_table(
    releases: Sequence[Release], presentation: DateTimePresentation
) -> Node:
    """Two facts per Release, as the sibling sections do."""
    rows = [
        make_row(
            _platform_words(release),
            TemporalText(release.release_date, presentation),
        )
        for release in releases
    ]
    return StyledTable(
        columns=[Column("Platform"), Column("Released")],
        rows=rows,
        data_table=True,
        caption="Releases of this edition",
    )


def _edition_block(
    entry: EditionEntry, presentation: DateTimePresentation, *, named: bool
) -> Node:
    """One Edition's Releases, named where a name tells them apart.

    A lone Edition takes no heading: `display_name` would print
    the Game's own name above the Game's own page.
    """
    return Div(class_="flex flex-col gap-2")[
        Span(class_="text-type-subheading text-heading")[entry.edition.display_name]
        if named
        else "",
        _release_table(entry.releases, presentation)
        if entry.releases
        else "No releases yet.",
    ]


def _releases_section(
    entries: Sequence[EditionEntry], presentation: DateTimePresentation
) -> Node:
    """Every Edition and every Release, where two rows cannot say it."""
    if _reads_plainly(entries):
        return Fragment()
    count = sum(len(entry.releases) for entry in entries)
    named = len(entries) > 1
    return Div(class_="mb-6 flex flex-col gap-4")[
        PageHeading(children=["Releases"], badge=str(count) if count else ""),
        *(_edition_block(entry, presentation, named=named) for entry in entries),
    ]
```

- [ ] **Step 4: Place the section**

In `view_game`, add the section between the header and the purchases:

```text
        _game_header(
            game,
            request,
            _game_overview_metrics(sessions),
            presentation,
            durations,
            origin,
            hierarchy,
        ),
        _releases_section(hierarchy, presentation),
        _purchases_section(game, purchases, presentation, origin),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `make test ARGS="tests/test_game_hierarchy_section.py"`
Expected: 14 passed.

- [ ] **Step 6: Check the whole page still holds together**

Run: `make test ARGS="tests/test_rendered_pages.py tests/test_html_validity.py tests/test_column_priority_contract.py"`

The priority contract only governs a table that has an `Actions` column, and the
Releases table has none — #969 is what adds one, and that is where the contract
starts applying. The run is here to prove that, not to change anything.

- [ ] **Step 7: Lint, type-check, commit**

Run: `make lint && make typecheck`

```bash
git add games/views/game.py tests/test_game_hierarchy_section.py
git commit -m "Show every Edition and every Release a Game holds"
```

---

### Task 4: Say what the page shows, and pass the gate

**Files:**
- Modify: `docs/catalog.md`
- Modify: `docs/superpowers/specs/2026-08-30-issue-963-temporal-presentation-design.md`

**Interfaces:**
- Consumes: the behaviour Tasks 1-3 shipped. Produces no code.

- [ ] **Step 1: Write what Game detail shows**

In `docs/catalog.md`, insert a section between `## Permission` and
`## Repeating a write`:

```markdown
## What Game detail shows

Game detail reads the graph through `game_hierarchy()` in
`games/reads/catalog_hierarchy.py`: the Editions one library may see under one
Game, each with its Releases, in two queries. Nothing on the page reads a
reverse accessor, because a shared Game's accessors reach every library that
ever wrote under it.

Most Games hold one unnamed Edition and one Release. That shape says everything
in two header rows — the Platform, and the date through the presenter — and the
page adds no heading above them. A second Edition or a second Release brings the
`Releases` section: one table per Edition, headed by `display_name` where two
Editions make a name worth printing.

A Release with no Platform reads as `Unspecified`. Nothing is inferred from the
Game, from a sibling Release, or from a display default.

A shared Game's graph is shown, and the page says nothing about who may change
it. The page offers no control either way, thus there is nothing yet for such a
word to explain. #969 adds controls, and only for a private Game.

The Game's own `original_release_date` stays on the Game, because it is a fact
of the work rather than of one Release. The flattened Platform row and the
flattened release year left with this reading; #889 takes the columns.
```

- [ ] **Step 2: Record the second caller of the presenter**

In `docs/superpowers/specs/2026-08-30-issue-963-temporal-presentation-design.md`,
replace the body of `## Callers` with:

```markdown
The Game detail page reads `Game.original_release_date` through the presenter,
in the meta row labelled `Original release`. The value accepts a month, a decade
and a range, thus a label that says "year" is a wrong label.

The same page reads every Release date through it too, since #968: the one
`Released` row an ordinary Game shows, and every cell of the `Releases` table a
richer graph shows.
```

- [ ] **Step 3: Lint the prose**

Run: `make vale`
Expected: no errors. Warnings on files this branch did not touch are
pre-existing; warnings on `docs/catalog.md` are not — read each one.

- [ ] **Step 4: Run the gate**

Run: `make check`
Expected: green, default parallel workers, `e2e/` included.

- [ ] **Step 5: Commit**

```bash
git add docs/catalog.md docs/superpowers/specs/2026-08-30-issue-963-temporal-presentation-design.md
git commit -m "Say what a Game detail page shows of the graph"
```

---

## Before the PR

The docs sweep drops this plan document; the spec stays. The commit that removes
it is the last one on the branch.

## Self-Review

**Spec coverage.**

| Spec / acceptance line | Task |
| --- | --- |
| Hierarchy section, each live Edition, each live Release | 1, 3 |
| Release date through `present_temporal_value()` | 2 (`TemporalText`), 3 |
| A Release with no Platform reads as explicitly unspecified | 2 (`_platform_words`) |
| The ordinary Game reads plainly, no empty scaffolding | 2 (`_reads_plainly`) |
| The Platform row and the release year row leave | 2 |
| The original release date stays, through the presenter | 2 (kept, constant-ised) |
| A shared Game is visible | 1 (read test); the mark is deferred, see Global Constraints |
| Another library's rows never appear | 1 (`visible_to`, isolation test) |
| A removed Edition or Release does not appear | 1, 3 |
| Game URLs unchanged | no URL is touched in any task |
| Focused rendering, hierarchy, isolation tests | 1, 2, 3 |
| Full `make check` | 4 |
| No write, route, form or action | no task adds one |
| No legacy column removal | no migration in any task |

**Type consistency.** `EditionEntry` and `game_hierarchy` are named identically
in Tasks 1, 2 and 3. `_platform_words`, `_reads_plainly` and `GREY_VALUE_CLASS`
are defined in Task 2 and consumed unchanged in Task 3. `_game_header` gains
`entries` in Task 2 and keeps that name.

**Open risk, called out rather than resolved.** A Game created by
`Game.objects.create()` in a test holds no Edition, so its page reads
`Unspecified` / `Unknown` even where the legacy `Game.platform` column is set.
That is the intended contract — the graph is the truth and the column is on its
way out — and migration `0020_catalog_hierarchy_backfill` gave every production
Game a default Edition and Release carrying its Platform, so no real page
regresses. Task 2 pins this deliberately in
`test_game_detail_no_longer_reads_the_legacy_platform_column`.
