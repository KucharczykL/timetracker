# One submit, one statement — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one submit of the Game form one transaction and one service
call that states the whole catalog graph, so a removal cannot eat a re-add and
nothing but the form creates a graph.

**Architecture:** `games/catalog_writes.py` loses its six row verbs and gains
one verb, `state_catalog_graph`, that takes the whole desired graph of one
Game, refuses it against the desired end state, and writes it in an order it
owns. `CatalogGraphForm` stops sequencing verbs and states its rows. A new
module, `games/catalog_submit.py`, owns one submit: the Game's columns, its
wikidata reference, the graph and the flat mirror, in one `transaction.atomic`,
with the PlayerGame command still outside it.

**Tech Stack:** Django 6, Python 3.14, PostgreSQL 18, pytest + pytest-django,
Playwright for e2e.

**Spec:** `docs/superpowers/specs/2026-09-01-issue-986-one-submit-one-transaction-design.md`

## Global Constraints

- **Drive everything through `make`.** Never `direnv exec .`, never a raw
  `uv run` / `pytest` / `pnpm`. Focused runs: `make test ARGS="tests/x.py -k y"`,
  `make test-e2e ARGS="-k z"`.
- **The verification gate is the full `make check`**, including `e2e/`. Use
  `make check-fast` while iterating only.
- **Nothing destroys a record.** Call `remove()` / `restore()` from
  `games/removal.py`, never `instance.delete()`. The one exception already in
  the tree is `add_game`'s undo of a Game no event names; it stays as it is.
- **No dispatch inside a transaction.** `run_in_transaction` refuses to nest,
  so `record_facts_for_request` and `track_game_for_request` stay outside every
  `transaction.atomic` block. A test that POSTs through these views needs
  `@pytest.mark.django_db(transaction=True)`.
- **Never write to a `GeneratedField`.**
- **Name variables with complete words** in Python and TypeScript. Name
  compound types explicitly (`NamedTuple`, `TypedDict`, `type` alias).
- **`make vale` grades prose**, including code comments. A projector *replays*
  events; the row it leaves is the *projection*; a record is *removed*, never
  the other word. See `docs/vocabulary.md`.
- **Comments are `#:` doc-comments** in this codebase where they explain a
  decision, and they say why rather than what.
- Every refusal sentence is a module constant, so a screen and a test name the
  same words.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `games/catalog_writes.py` | The one verb: `state_catalog_graph`, its state and result types, its sentences, and the write order it owns. Nothing else writes an Edition or a Release. |
| `games/catalog_submit.py` | **New.** One submit of the Game form: `save_game_columns`, `save_game_and_graph`, `submitted_game_or_form_error`, the refusal answering and the constraint→sentence mapping. |
| `games/catalog_form.py` | The posted rows, their validation, and `write_rows()` — the one place the form states a graph. |
| `games/catalog_compat.py` | The flat mirror only. `save_legacy_game_form` and `InitialRelease` leave for the coordinator; #889 takes what stays. |
| `games/views/game.py` | Two views that call the coordinator. No write logic of its own. |
| `tests/test_state_catalog_graph.py` | **New.** The verb, end to end: what it refuses, what it writes, and in what order. Replaces `tests/test_catalog_graph_writes.py` and `tests/test_catalog_writes.py`. |
| `tests/test_catalog_submit.py` | **New.** One transaction, one creator, the refusal landings, the constraint mapping and its guard test. |
| `tests/conftest.py` | Gains `stated_graph`, the fixture every test uses to make a Game with a default graph. |

---

## Task 1: The one verb

Add `state_catalog_graph` beside the six row verbs. Nothing calls it yet, so
the suite stays green while the verb earns its own tests.

**Files:**
- Modify: `games/catalog_writes.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_state_catalog_graph.py` (create)

**Interfaces:**
- Consumes: `games.models` (`Edition`, `Game`, `Platform`, `Release`,
  `UserLibrary`), `games.removal.remove`, `timetracker.temporal.TemporalValue`.
- Produces:
  - `type RowKey = str`
  - `class GraphRefused(ValidationError)` with `.key: RowKey | None`
  - `EditionState(key, edition=None, name="", removed=False, is_default=False, releases=())`
  - `ReleaseState(key, release=None, platform=None, release_date=None, removed=False, is_default=False)`
  - `WrittenEdition(key, edition, releases: tuple[tuple[RowKey, Release], ...])`
  - `WrittenGraph(game, editions: tuple[WrittenEdition, ...])`
  - `state_catalog_graph(*, game: Game, library: UserLibrary, editions: Sequence[EditionState]) -> WrittenGraph`
  - new sentences `TWO_DEFAULT_EDITIONS`, `TWO_DEFAULT_RELEASES`, `FOREIGN_ROW`
  - fixture `stated_graph(game, library, *, platform=None, release_date=None) -> DefaultGraph`

- [ ] **Step 1: Add the shared test fixture**

`tests/conftest.py` gains the fixture every ported test uses in place of
`save_private_game`. `DefaultGraph` carries the same three names
`PrivateGameGraph` did, so a ported call site keeps reading `graph.release`.

```python
class DefaultGraph(NamedTuple):
    """One Game and the single default graph a test starts from."""

    game: Game
    edition: Edition
    release: Release


@pytest.fixture
def stated_graph():
    """A Game with one default Edition holding one default Release."""

    def state(
        game: Game,
        library: UserLibrary,
        *,
        platform: Platform | None = None,
        release_date: TemporalValue | None = None,
    ) -> DefaultGraph:
        game.save()
        written = state_catalog_graph(
            game=game,
            library=library,
            editions=[
                EditionState(
                    key="edition-0",
                    is_default=True,
                    releases=(
                        ReleaseState(
                            key="edition-0-release-0",
                            platform=platform,
                            release_date=release_date,
                            is_default=True,
                        ),
                    ),
                )
            ],
        )
        entry = written.editions[0]
        return DefaultGraph(written.game, entry.edition, entry.releases[0][1])

    return state
```

The imports it needs at the top of `tests/conftest.py`:

```python
from typing import NamedTuple

from games.catalog_writes import (
    EditionState,
    ReleaseState,
    state_catalog_graph,
)
from games.models import Edition, Game, Platform, Release, UserLibrary
from timetracker.temporal import TemporalValue
```

- [ ] **Step 2: Write the failing tests for what the statement refuses**

Create `tests/test_state_catalog_graph.py`. These are the refusals the verb
keeps, each carrying the key of the row that caused it.

```python
"""One call states a whole Game's graph.

Every refusal is checked against the desired end state, before
anything is written, and carries the caller's own name for the row.
"""

import pytest
from django.core.exceptions import ValidationError

from games.catalog_writes import (
    DUPLICATE_EDITION_NAME,
    FOREIGN_GAME,
    FOREIGN_PLATFORM,
    FOREIGN_ROW,
    LAST_EDITION,
    REMOVED_EDITION,
    REMOVED_GAME,
    REMOVED_RELEASE,
    SHARED_GAME,
    TWO_DEFAULT_EDITIONS,
    TWO_DEFAULT_RELEASES,
    EditionState,
    GraphRefused,
    ReleaseState,
    state_catalog_graph,
)
from games.models import Edition, Game, Platform, Release
from games.removal import remove
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db


@pytest.fixture
def other_library(django_user_model):
    return django_user_model.objects.create_user(username="second-owner").library


@pytest.fixture
def game(owned_library, stated_graph):
    return stated_graph(Game(library=owned_library, name="Deus Ex"), owned_library)


def one(key="edition-0", **fields) -> EditionState:
    """One Edition state, defaulting to a lone marked row."""
    fields.setdefault("is_default", True)
    fields.setdefault(
        "releases", (ReleaseState(key=f"{key}-release-0", is_default=True),)
    )
    return EditionState(key=key, **fields)


def state(game, library, *editions):
    return state_catalog_graph(game=game, library=library, editions=list(editions))


def test_a_shared_game_is_read_only(owned_library):
    shared = Game.objects.create(library=None, name="Shared")

    with pytest.raises(ValidationError) as refused:
        state(shared, owned_library, one())

    assert SHARED_GAME in refused.value.messages


def test_another_library_s_game_is_refused(other_library, game):
    with pytest.raises(ValidationError) as refused:
        state(game.game, other_library, one())

    assert FOREIGN_GAME in refused.value.messages


def test_a_removed_game_goes_back_first(owned_library, game):
    remove(game.game)

    with pytest.raises(ValidationError) as refused:
        state(game.game, owned_library, one())

    assert REMOVED_GAME in refused.value.messages


def test_a_named_edition_that_is_removed_is_refused(owned_library, game):
    """The caller read the row before the lock; storage decides."""
    remove(game.edition)

    with pytest.raises(GraphRefused) as refused:
        state(game.game, owned_library, one(edition=game.edition))

    assert REMOVED_EDITION in refused.value.messages
    assert refused.value.key == "edition-0"


def test_a_named_release_that_is_removed_is_refused(owned_library, game):
    remove(game.release)

    with pytest.raises(GraphRefused) as refused:
        state(
            game.game,
            owned_library,
            one(
                edition=game.edition,
                releases=(
                    ReleaseState(
                        key="edition-0-release-0",
                        release=game.release,
                        is_default=True,
                    ),
                ),
            ),
        )

    assert REMOVED_RELEASE in refused.value.messages
    assert refused.value.key == "edition-0-release-0"


def test_another_game_s_edition_is_refused(owned_library, game, stated_graph):
    theirs = stated_graph(Game(library=owned_library, name="Theirs"), owned_library)

    with pytest.raises(GraphRefused) as refused:
        state(game.game, owned_library, one(edition=theirs.edition))

    assert FOREIGN_ROW in refused.value.messages
    assert refused.value.key == "edition-0"


def test_another_edition_s_release_is_refused(owned_library, game, stated_graph):
    theirs = stated_graph(Game(library=owned_library, name="Theirs"), owned_library)

    with pytest.raises(GraphRefused) as refused:
        state(
            game.game,
            owned_library,
            one(
                edition=game.edition,
                releases=(
                    ReleaseState(
                        key="edition-0-release-0",
                        release=theirs.release,
                        is_default=True,
                    ),
                ),
            ),
        )

    assert FOREIGN_ROW in refused.value.messages
    assert refused.value.key == "edition-0-release-0"


def test_another_library_s_platform_is_refused(owned_library, other_library, game):
    theirs = Platform.objects.create(library=other_library, name="Theirs")

    with pytest.raises(GraphRefused) as refused:
        state(
            game.game,
            owned_library,
            one(
                releases=(
                    ReleaseState(
                        key="edition-0-release-0", platform=theirs, is_default=True
                    ),
                )
            ),
        )

    assert FOREIGN_PLATFORM in refused.value.messages
    assert refused.value.key == "edition-0-release-0"


def test_two_surviving_editions_may_not_state_one_name(owned_library, game):
    with pytest.raises(GraphRefused) as refused:
        state(
            game.game,
            owned_library,
            one(name="Original"),
            one(key="edition-1", name="original", is_default=False),
        )

    assert DUPLICATE_EDITION_NAME in refused.value.messages
    assert refused.value.key == "edition-1"


def test_a_name_an_unmentioned_edition_holds_is_refused(owned_library, game):
    """A row nobody states still holds its own name."""
    Edition.objects.create(game=game.game, name="Original")

    with pytest.raises(GraphRefused) as refused:
        state(game.game, owned_library, one(edition=game.edition, name="Original"))

    assert DUPLICATE_EDITION_NAME in refused.value.messages
    assert refused.value.key == "edition-0"


def test_a_game_keeps_an_edition(owned_library, game):
    with pytest.raises(GraphRefused) as refused:
        state(game.game, owned_library, one(edition=game.edition, removed=True))

    assert LAST_EDITION in refused.value.messages
    assert refused.value.key == "edition-0"


def test_a_game_keeps_an_edition_nobody_stated(owned_library, game):
    """An unmentioned live Edition is an Edition the Game keeps."""
    Edition.objects.create(game=game.game, name="Original")

    state(game.game, owned_library, one(edition=game.edition, removed=True))

    assert Edition.objects.alive().filter(game=game.game).count() == 1


def test_two_stated_default_editions_are_refused(owned_library, game):
    with pytest.raises(GraphRefused) as refused:
        state(
            game.game,
            owned_library,
            one(name="First"),
            one(key="edition-1", name="Second"),
        )

    assert TWO_DEFAULT_EDITIONS in refused.value.messages
    assert refused.value.key == "edition-1"


def test_two_stated_default_releases_are_refused(owned_library, game):
    with pytest.raises(GraphRefused) as refused:
        state(
            game.game,
            owned_library,
            one(
                releases=(
                    ReleaseState(key="edition-0-release-0", is_default=True),
                    ReleaseState(key="edition-0-release-1", is_default=True),
                )
            ),
        )

    assert TWO_DEFAULT_RELEASES in refused.value.messages
    assert refused.value.key == "edition-0-release-1"


def test_nothing_is_written_when_the_set_is_refused(owned_library, game):
    """The refusal comes before the first write."""
    with pytest.raises(ValidationError):
        state(
            game.game,
            owned_library,
            one(edition=game.edition, name="Renamed"),
            one(key="edition-1", name="Renamed", is_default=False),
        )

    game.edition.refresh_from_db()
    assert game.edition.name == ""
    assert Edition.objects.filter(game=game.game).count() == 1
```

- [ ] **Step 3: Run them to see them fail**

Run: `make test ARGS="tests/test_state_catalog_graph.py -x"`
Expected: FAIL — `ImportError: cannot import name 'FOREIGN_ROW'`.

- [ ] **Step 4: Write the failing tests for what the statement writes**

Append to the same file. These are the cases the row verbs could not express.

```python
# --- what a statement writes -------------------------------------------------


def live_releases(edition: Edition) -> list[Release]:
    return list(Release.objects.alive().filter(edition=edition).order_by("pk"))


def test_a_binned_release_does_not_eat_its_re_add(owned_library, stated_graph):
    """The case that started this: one submit, two rows, one pair."""
    amiga = Platform.objects.create(library=owned_library, name="Amiga")
    graph = stated_graph(
        Game(library=owned_library, name="Elite"),
        owned_library,
        platform=amiga,
        release_date=TemporalValue.from_year(1984),
    )

    state(
        graph.game,
        owned_library,
        one(
            edition=graph.edition,
            releases=(
                ReleaseState(
                    key="edition-0-release-0", release=graph.release, removed=True
                ),
                ReleaseState(
                    key="edition-0-release-1",
                    platform=amiga,
                    release_date=TemporalValue.from_year(1984),
                    is_default=True,
                ),
            ),
        ),
    )

    graph.release.refresh_from_db()
    live = live_releases(graph.edition)
    assert graph.release.removed_at is not None
    assert [row.pk for row in live] != [graph.release.pk]
    assert len(live) == 1
    assert live[0].is_default is True


def test_a_binned_edition_does_not_eat_a_re_add_of_its_name(owned_library, game):
    original = Edition.objects.create(game=game.game, name="Original")

    state(
        game.game,
        owned_library,
        EditionState(key="edition-0", edition=original, name="Original", removed=True),
        one(key="edition-1", name="Original"),
    )

    original.refresh_from_db()
    live = Edition.objects.alive().filter(game=game.game, name="Original")
    assert original.removed_at is not None
    assert live.count() == 1
    assert live.get().pk != original.pk


def test_two_editions_exchange_names_in_one_statement(owned_library, game):
    """A name being given up is freed before it is taken."""
    beta = Edition.objects.create(game=game.game, name="Beta")
    Edition.objects.filter(pk=game.edition.pk).update(name="Alpha")

    state(
        game.game,
        owned_library,
        EditionState(key="edition-0", edition=game.edition, name="Beta"),
        EditionState(key="edition-1", edition=beta, name="Alpha", is_default=True),
    )

    game.edition.refresh_from_db()
    beta.refresh_from_db()
    assert (game.edition.name, beta.name) == ("Beta", "Alpha")


def test_the_default_edition_leaves_when_a_sibling_takes_the_mark(owned_library, game):
    """Today `DEFAULT_EDITION_HELD`; the statement carries the answer."""
    sibling = Edition.objects.create(game=game.game, name="Sibling")

    state(
        game.game,
        owned_library,
        EditionState(key="edition-0", edition=game.edition, removed=True),
        EditionState(key="edition-1", edition=sibling, name="Sibling", is_default=True),
    )

    game.edition.refresh_from_db()
    sibling.refresh_from_db()
    assert game.edition.removed_at is not None
    assert sibling.is_default is True


def test_the_default_release_leaves_when_a_sibling_takes_the_mark(owned_library, game):
    sibling = Release.objects.create(edition=game.edition, is_default=False)

    state(
        game.game,
        owned_library,
        one(
            edition=game.edition,
            releases=(
                ReleaseState(
                    key="edition-0-release-0", release=game.release, removed=True
                ),
                ReleaseState(
                    key="edition-0-release-1", release=sibling, is_default=True
                ),
            ),
        ),
    )

    game.release.refresh_from_db()
    sibling.refresh_from_db()
    assert game.release.removed_at is not None
    assert sibling.is_default is True


def test_a_removed_edition_keeps_its_releases(owned_library, game):
    """Each read tests its ancestors' marks, so restoring brings them back."""
    sibling = Edition.objects.create(game=game.game, name="Sibling")
    Release.objects.create(edition=sibling)

    state(
        game.game,
        owned_library,
        EditionState(key="edition-0", edition=game.edition, is_default=True),
        EditionState(key="edition-1", edition=sibling, name="Sibling", removed=True),
    )

    assert Release.objects.filter(edition=sibling, removed_at__isnull=True).count() == 1


def test_a_row_nobody_mentions_is_left_alone(owned_library, game):
    """Absence is not removal: #782's importer states what it knows."""
    untouched = Edition.objects.create(game=game.game, name="Untouched")

    state(game.game, owned_library, one(edition=game.edition, name="Stated"))

    untouched.refresh_from_db()
    assert untouched.removed_at is None
    assert untouched.name == "Untouched"


def test_the_first_surviving_row_takes_an_unstated_mark(owned_library, game):
    written = state(
        game.game,
        owned_library,
        EditionState(
            key="edition-0",
            releases=(ReleaseState(key="edition-0-release-0"),),
        ),
        EditionState(key="edition-1", name="Second"),
    )

    first = written.editions[0]
    assert first.edition.is_default is True
    assert first.releases[0][1].is_default is True
    assert written.editions[1].edition.is_default is False


def test_an_unstated_mark_leaves_the_standing_default_where_it_is(owned_library, game):
    """A partial statement does not move a mark it says nothing about."""
    sibling = Edition.objects.create(game=game.game, name="Sibling")

    state(
        game.game,
        owned_library,
        EditionState(key="edition-0", edition=sibling, name="Sibling"),
    )

    game.edition.refresh_from_db()
    sibling.refresh_from_db()
    assert (game.edition.is_default, sibling.is_default) == (True, False)


def test_the_written_graph_hands_every_row_back_under_its_key(owned_library, game):
    written = state(
        game.game,
        owned_library,
        one(
            edition=game.edition,
            releases=(
                ReleaseState(
                    key="edition-0-release-0", release=game.release, is_default=True
                ),
                ReleaseState(key="edition-0-release-1"),
            ),
        ),
    )

    entry = written.editions[0]
    assert written.game.pk == game.game.pk
    assert entry.key == "edition-0"
    assert entry.edition.pk == game.edition.pk
    assert [key for key, _ in entry.releases] == [
        "edition-0-release-0",
        "edition-0-release-1",
    ]


def test_a_removed_row_is_not_handed_back(owned_library, game):
    sibling = Release.objects.create(edition=game.edition)

    written = state(
        game.game,
        owned_library,
        one(
            edition=game.edition,
            releases=(
                ReleaseState(
                    key="edition-0-release-0", release=game.release, is_default=True
                ),
                ReleaseState(key="edition-0-release-1", release=sibling, removed=True),
            ),
        ),
    )

    assert [key for key, _ in written.editions[0].releases] == ["edition-0-release-0"]
```

- [ ] **Step 5: Run them to see them fail**

Run: `make test ARGS="tests/test_state_catalog_graph.py -x"`
Expected: FAIL — the import still names things that do not exist.

- [ ] **Step 6: Write the verb**

Add to `games/catalog_writes.py`, above the six row verbs, keeping every
existing helper (`_writable_game`, `_live_editions`, `_clear_default_edition`,
`_live_releases`, `_clear_default_release`). Widen the one platform helper to
carry a key, and leave its old call sites passing none:

```python
def _refuse_foreign_platform(
    library_id, platform: Platform | None, key: RowKey | None = None
) -> None:
    """A Platform is shared, or it is this library's."""
    if platform is not None and platform.library_id not in (None, library_id):
        raise GraphRefused(FOREIGN_PLATFORM, key=key)
```

The new sentences, beside the ones already there:

```python
TWO_DEFAULT_EDITIONS = "A game keeps one default edition, and this states two."
TWO_DEFAULT_RELEASES = "An edition keeps one default release, and this states two."
FOREIGN_ROW = "This row belongs to another game."
```

The refusal that names a row, and the four state types:

```python
#: The caller's own name for one row, handed back on a refusal.
type RowKey = str


class GraphRefused(ValidationError):
    """A refusal that names the row that caused it.

    `key` is opaque here. The form passes the prefix it already
    has, thus a sentence reaches the row a person typed into
    without the service knowing what a form is.
    """

    def __init__(self, sentence: str, *, key: RowKey | None = None) -> None:
        super().__init__(sentence)
        self.key = key


@dataclass(frozen=True, slots=True)
class ReleaseState:
    """One Release the caller wants under one Edition.

    `release` is identity only: the verb resolves it under the
    Game lock. None states a row that does not exist yet.
    """

    key: RowKey
    release: Release | None = None
    platform: Platform | None = None
    release_date: TemporalValue | None = None
    removed: bool = False
    is_default: bool = False


@dataclass(frozen=True, slots=True)
class EditionState:
    """One Edition the caller wants under one Game."""

    key: RowKey
    edition: Edition | None = None
    name: EditionName = ""
    removed: bool = False
    is_default: bool = False
    releases: tuple[ReleaseState, ...] = ()


@dataclass(frozen=True, slots=True)
class WrittenEdition:
    """One written Edition and the Releases that survived under it."""

    key: RowKey
    edition: Edition
    releases: tuple[tuple[RowKey, Release], ...]


@dataclass(frozen=True, slots=True)
class WrittenGraph:
    """What one statement left, parallel to the surviving input."""

    game: Game
    editions: tuple[WrittenEdition, ...]
```

Resolution under the lock:

```python
def _resolved_edition(owner: Game, state: EditionState) -> Edition | None:
    """The stored row a state names, read after the Game is locked."""
    if state.edition is None:
        return None
    stored = Edition.objects.filter(pk=state.edition.pk).first()
    if stored is None or stored.game_id != owner.pk:
        raise GraphRefused(FOREIGN_ROW, key=state.key)
    if stored.removed_at is not None:
        raise GraphRefused(REMOVED_EDITION, key=state.key)
    return stored


def _resolved_release(parent: Edition | None, state: ReleaseState) -> Release | None:
    """The stored Release a state names, under the parent it names."""
    if state.release is None:
        return None
    stored = Release.objects.filter(pk=state.release.pk).first()
    if stored is None or parent is None or stored.edition_id != parent.pk:
        raise GraphRefused(FOREIGN_ROW, key=state.key)
    if stored.removed_at is not None:
        raise GraphRefused(REMOVED_RELEASE, key=state.key)
    return stored
```

What the desired end state has to say:

```python
def _refuse_taken_names(
    surviving: list[EditionState], untouched: list[Edition]
) -> None:
    """One live name per Game, whoever holds it."""
    taken = {edition.name.strip().casefold() for edition in untouched} - {""}
    for state in surviving:
        wanted = state.name.strip().casefold()
        if not wanted:
            continue
        if wanted in taken:
            raise GraphRefused(DUPLICATE_EDITION_NAME, key=state.key)
        taken.add(wanted)


def _refuse_the_set(
    owner: Game,
    library: UserLibrary,
    editions: Sequence[EditionState],
    stored_editions: dict[RowKey, Edition | None],
) -> None:
    """Everything the statement itself can be wrong about."""
    surviving = [state for state in editions if not state.removed]
    named = [stored.pk for stored in stored_editions.values() if stored is not None]
    untouched = list(_live_editions(owner.pk).exclude(pk__in=named))
    if not surviving and not untouched:
        raise GraphRefused(LAST_EDITION, key=editions[0].key if editions else None)
    marked = [state for state in surviving if state.is_default]
    if len(marked) > 1:
        raise GraphRefused(TWO_DEFAULT_EDITIONS, key=marked[1].key)
    _refuse_taken_names(surviving, untouched)
    for state in surviving:
        rows = [row for row in state.releases if not row.removed]
        marked_rows = [row for row in rows if row.is_default]
        if len(marked_rows) > 1:
            raise GraphRefused(TWO_DEFAULT_RELEASES, key=marked_rows[1].key)
        for row in rows:
            _refuse_foreign_platform(library.pk, row.platform, row.key)
```

The write, in the order the verb owns:

```python
def _written_release(
    edition: Edition, state: ReleaseState, stored: Release | None
) -> Release:
    """One Release's whole Platform and date. The mark comes last."""
    if stored is None:
        return Release.objects.create(
            edition=edition,
            platform=state.platform,
            release_date=state.release_date,
            is_default=False,
        )
    stored.platform = state.platform
    stored.release_date = state.release_date
    stored.is_default = False
    stored.save(update_fields=("platform", "release_date", "is_default"))
    return stored


def _written_edition(
    owner: Game,
    state: EditionState,
    stored: Edition | None,
    stored_releases: dict[RowKey, Release | None],
) -> WrittenEdition:
    """One Edition's whole name, and every Release that survives it."""
    name = state.name.strip()
    if stored is None:
        edition = Edition.objects.create(game=owner, name=name, is_default=False)
    else:
        edition = stored
        edition.name = name
        edition.is_default = False
        edition.save(update_fields=("name", "is_default"))
    rows = tuple(
        (row.key, _written_release(edition, row, stored_releases[row.key]))
        for row in state.releases
        if not row.removed
    )
    return WrittenEdition(key=state.key, edition=edition, releases=rows)


def _default_edition(
    owner: Game,
    surviving: Sequence[EditionState],
    written: Sequence[WrittenEdition],
    standing: Edition | None,
) -> Edition | None:
    """The stated mark, else the one standing, else the first row."""
    for state, entry in zip(surviving, written, strict=True):
        if state.is_default:
            return entry.edition
    if standing is not None:
        kept = _live_editions(owner.pk).filter(pk=standing.pk).first()
        if kept is not None:
            return kept
    if written:
        return written[0].edition
    return _live_editions(owner.pk).order_by("pk").first()


def _default_release(
    state: EditionState, entry: WrittenEdition, standing: Release | None
) -> Release | None:
    """The same rule, one level down. An Edition may hold no Release."""
    stated = [row for row in state.releases if not row.removed]
    for row, (_, release) in zip(stated, entry.releases, strict=True):
        if row.is_default:
            return release
    if standing is not None:
        kept = _live_releases(entry.edition.pk).filter(pk=standing.pk).first()
        if kept is not None:
            return kept
    if entry.releases:
        return entry.releases[0][1]
    return _live_releases(entry.edition.pk).order_by("pk").first()


@transaction.atomic
def state_catalog_graph(
    *,
    game: Game,
    library: UserLibrary,
    editions: Sequence[EditionState],
) -> WrittenGraph:
    """State one Game's whole graph, in one transaction.

    A row the caller does not mention is left alone: removal is
    stated by `removed`, so one partial writer cannot take a
    catalog somebody built by hand.
    """
    owner = _writable_game(game.pk, library)
    stored_editions = {state.key: _resolved_edition(owner, state) for state in editions}
    stored_releases = {
        row.key: _resolved_release(stored_editions[state.key], row)
        for state in editions
        for row in state.releases
    }
    _refuse_the_set(owner, library, editions, stored_editions)

    surviving = [state for state in editions if not state.removed]
    standing_edition = _live_editions(owner.pk).filter(is_default=True).first()
    standing_releases = {
        state.key: _live_releases(stored_editions[state.key].pk)
        .filter(is_default=True)
        .first()
        for state in surviving
        if stored_editions[state.key] is not None
    }

    #: 1. Every live default steps down first. Both constraints
    #: permit at most one, thus none is a legal intermediate state
    #: and every order below is free.
    _clear_default_edition(owner.pk)
    for state in surviving:
        stored = stored_editions[state.key]
        if stored is not None:
            _clear_default_release(stored.pk)

    #: 2. A removal is a stamp. A removed Edition keeps its
    #: Releases: each read tests its ancestors' marks as well as
    #: its own, thus putting the Edition back brings back exactly
    #: the rows nobody removed.
    for state in surviving:
        for row in state.releases:
            stored_release = stored_releases[row.key]
            if row.removed and stored_release is not None:
                remove(stored_release)
    for state in editions:
        stored = stored_editions[state.key]
        if state.removed and stored is not None:
            remove(stored)

    #: 3. A name being given up is freed before it is taken. The
    #: empty name claims no slot, thus two Editions can exchange.
    for state in surviving:
        stored = stored_editions[state.key]
        if stored is not None and stored.name.strip() != state.name.strip():
            Edition.objects.filter(pk=stored.pk).update(name="")

    #: 4 and 5. The stored rows, then the new ones.
    written = [
        _written_edition(owner, state, stored_editions[state.key], stored_releases)
        for state in surviving
    ]

    #: 6. One mark at each level, once everything else stands.
    winner = _default_edition(owner, surviving, written, standing_edition)
    if winner is not None:
        winner.is_default = True
        winner.save(update_fields=("is_default",))
    for state, entry in zip(surviving, written, strict=True):
        row = _default_release(state, entry, standing_releases.get(state.key))
        if row is not None:
            row.is_default = True
            row.save(update_fields=("is_default",))

    return WrittenGraph(game=owner, editions=tuple(written))
```

The module gains one import: `from collections.abc import Sequence`.

- [ ] **Step 7: Run the new tests**

Run: `make test ARGS="tests/test_state_catalog_graph.py"`
Expected: PASS, all of them.

- [ ] **Step 8: Run everything the verb could have disturbed**

Run: `make check-fast`
Expected: PASS. Nothing calls the new verb yet, so only `tests/conftest.py`
and `games/catalog_writes.py` changed.

- [ ] **Step 9: Commit**

```bash
git add games/catalog_writes.py tests/conftest.py tests/test_state_catalog_graph.py
git commit -m "State a whole catalog graph in one call"
```

---

## Task 2: The form states the graph

`CatalogGraphForm` stops sequencing verbs. It keeps `adopt()` and
`initial_release` for one more task, so the views still work and the suite
stays green.

**Files:**
- Modify: `games/catalog_form.py`
- Modify: `tests/test_catalog_graph_form.py`

**Interfaces:**
- Consumes: `state_catalog_graph`, `EditionState`, `ReleaseState`,
  `GraphRefused`, `RowKey`, `WrittenGraph` from `games.catalog_writes`;
  `write_and_mirror` from `games.catalog_compat`.
- Produces:
  - `CatalogGraphForm.write_rows() -> None` — states the whole posted graph in
    one call and adopts what came back.
  - `CatalogGraphForm.write() -> None` — `write_and_mirror(game, write_rows)`.
  - `CatalogGraphForm.answer(refusal: ValidationError) -> bool` — True when the
    refusal named a row of this form.
  - `CatalogGraphForm.bind(game: Game) -> None`
  - `DUPLICATE_RELEASE_IN_FORM` sentence.
- Gone: `_promote_marked_edition`, `_write_other_editions`, `_winner`,
  `_write_releases`, `_write_release`, `_write_edition`, `_remove_releases`,
  `_remove_editions`, `_blame`, `_write`, `blamed`, `save()`, `_stated`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_catalog_graph_form.py`. The first two replace
`test_save_rollback_leaves_the_whole_graph_as_it_was` and
`test_a_refused_release_edit_lands_on_the_row_that_stated_it`, whose subject
(`DUPLICATE_RELEASE` from the service) is now a validation rule.

```python
def test_two_surviving_rows_may_not_state_one_platform_and_date(
    owned_library, two_release_game
):
    """Two rows a person cannot tell apart, refused before any write."""
    blocks = stored_blocks(two_release_game.game, owned_library)
    blocks[0]["releases"][1] = release(
        release_id=blocks[0]["releases"][1]["release_id"],
        platform=None,
        date=TemporalValue.from_year(2007),
    )

    form = graph_form(
        posted(*blocks), game=two_release_game.game, library=owned_library
    )

    assert not form.is_valid()
    assert DUPLICATE_RELEASE_IN_FORM in form.blocks[0].rows[1].non_field_errors()


def test_binning_a_row_frees_its_platform_and_date_for_a_new_one(
    owned_library, two_release_game
):
    """The rule is about the surviving set, thus this passes and writes."""
    game = two_release_game.game
    blocks = stored_blocks(game, owned_library)
    stated = blocks[0]["releases"][0]
    blocks[0]["releases"][0] = release(release_id=stated["release_id"], removed=True)
    blocks[0]["releases"].append(
        release(platform=stated["platform"], date=stated["date"])
    )

    saved(game, owned_library, *blocks, mark="edition-0-release-2")

    live = Release.objects.alive().filter(edition=two_release_game.edition)
    assert live.count() == 2
    assert not live.filter(pk=two_release_game.release.pk).exists()


def test_renaming_two_editions_past_each_other_is_written(owned_library, plain_game):
    """The intermediate state the row verbs could not reach."""
    beta = Edition.objects.create(game=plain_game.game, name="Beta")
    Release.objects.create(edition=beta)
    Edition.objects.filter(pk=plain_game.edition.pk).update(name="Alpha")
    blocks = stored_blocks(plain_game.game, owned_library)
    blocks[0]["name"] = "Beta"
    blocks[1]["name"] = "Alpha"

    saved(plain_game.game, owned_library, *blocks)

    plain_game.edition.refresh_from_db()
    beta.refresh_from_db()
    assert (plain_game.edition.name, beta.name) == ("Beta", "Alpha")


def test_a_refusal_lands_on_the_row_whose_key_it_carries(owned_library, plain_game):
    """A row removed behind the request is the service's word, not the form's."""
    blocks = stored_blocks(plain_game.game, owned_library)
    form = graph_form(posted(*blocks), game=plain_game.game, library=owned_library)
    assert form.is_valid(), form.form_errors
    remove(plain_game.edition)

    with pytest.raises(ValidationError) as refused:
        form.write()

    assert form.answer(refused.value) is True
    assert REMOVED_EDITION in form.blocks[0].form.non_field_errors()


def test_a_refusal_naming_no_row_is_not_this_form_s_to_answer(
    owned_library, plain_game
):
    """`mirror_legacy_columns` refuses the whole Game; the coordinator has it."""
    form = graph_form(
        posted(*stored_blocks(plain_game.game, owned_library)),
        game=plain_game.game,
        library=owned_library,
    )
    assert form.is_valid(), form.form_errors

    assert form.answer(ValidationError(LEGACY_IDENTITY_TAKEN)) is False
```

Update the `saved()` helper in the same file, and the two remaining
`form.save() is False` call sites, which become the pattern above:

```python
def saved(game, library, *blocks, mark="edition-0-release-0"):
    """Bind the posted graph, check it, write it."""
    form = graph_form(posted(*blocks), game=game, library=library)
    assert form.is_valid(), (form.form_errors, [one.form.errors for one in form.blocks])
    form.write()
    game.refresh_from_db()
    return form
```

Remove `test_save_refuses_renaming_two_editions_past_each_other` (its
successor is `test_renaming_two_editions_past_each_other_is_written`),
`test_save_rollback_leaves_the_whole_graph_as_it_was` and
`test_a_refused_release_edit_lands_on_the_row_that_stated_it` (both replaced
by the two duplicate-pair tests above), and
`test_a_refusal_belonging_to_no_row_lands_on_the_form` (it moves to
`tests/test_catalog_submit.py` in Task 3). Point the file's imports at
`DUPLICATE_RELEASE_IN_FORM` instead of `DUPLICATE_RELEASE`, and at the
`stated_graph` fixture instead of `save_private_game`.

- [ ] **Step 2: Run them to see them fail**

Run: `make test ARGS="tests/test_catalog_graph_form.py -x"`
Expected: FAIL — `ImportError: cannot import name 'DUPLICATE_RELEASE_IN_FORM'`.

- [ ] **Step 3: Add the form's own duplicate rule**

In `games/catalog_form.py`, beside the other form sentences:

```python
#: The service allows two: #782 needs two regions on one date to be
#: two rows. A person typing does not, because the page would show
#: two rows nothing tells apart.
DUPLICATE_RELEASE_IN_FORM = (
    "Another release of this edition already states this platform and date."
)
```

And the check, called from `_validate_set`:

```python
class CatalogGraphForm:
    def _validate_releases(self, surviving: list[EditionBlock]) -> bool:
        """Two surviving rows of one Edition that read the same."""
        valid = True
        for block in surviving:
            seen: set[tuple[object, object]] = set()
            for row in block.surviving:
                #: A row with its own errors states no pair yet.
                if row.errors:
                    continue
                pair = (
                    row.cleaned_data.get("platform"),
                    row.cleaned_data.get("release_date"),
                )
                if pair in seen:
                    row.add_error(None, DUPLICATE_RELEASE_IN_FORM)
                    valid = False
                seen.add(pair)
        return valid
```

`_validate_set` gains one line, after the names:

```text
        valid = self._validate_names(surviving) and valid
        valid = self._validate_releases(surviving) and valid
```

- [ ] **Step 4: Replace the write path**

Remove `_promote_marked_edition`, `_write_other_editions`, `_winner`,
`_write_releases`, `_write_release`, `_write_edition`, `_remove_releases`,
`_remove_editions`, `_write`, `_blame`, the `blamed` property, `save()`, the
`_blamed` attribute in `__init__`, and the module-level `_stated`. In their
place:

```python
class CatalogGraphForm:
    def _states(self) -> list[EditionState]:
        """Every posted row, as the graph the service is to write."""
        marked = self.marked()
        assert marked is not None, "is_valid() states the mark names a surviving row."
        marked_block, marked_row = marked
        return [
            EditionState(
                key=block.form.prefix,
                edition=block.edition,
                name=cast(str, block.form.cleaned_data.get("name", "")),
                removed=block.removed,
                is_default=block is marked_block,
                releases=tuple(
                    ReleaseState(
                        key=row.prefix,
                        release=row.instance,
                        platform=cast(
                            Platform | None, row.cleaned_data.get("platform")
                        ),
                        release_date=cast(
                            TemporalValue | None, row.cleaned_data.get("release_date")
                        ),
                        removed=_removed(row),
                        is_default=row is marked_row,
                    )
                    for row in block.rows
                ),
            )
            for block in self.blocks
        ]

    def _rows_by_key(self) -> dict[RowKey, forms.Form]:
        """Every row of this form, under the key the service was given."""
        rows: dict[RowKey, forms.Form] = {}
        for block in self.blocks:
            rows[block.form.prefix] = block.form
            for row in block.rows:
                rows[row.prefix] = row
        return rows

    def _adopt(self, written: WrittenGraph) -> None:
        """Each row now names the stored row it wrote.

        A re-render after a refused command shows what storage
        holds, rather than posting the same rows back as new ones.
        """
        blocks = {block.form.prefix: block for block in self.blocks}
        for entry in written.editions:
            block = blocks[entry.key]
            block.form.instance = entry.edition
            rows = {row.prefix: row for row in block.rows}
            for key, release in entry.releases:
                rows[key].instance = release

    def write_rows(self) -> None:
        """One statement of the whole posted graph."""
        self._adopt(
            state_catalog_graph(
                game=self.written_game,
                library=self.library,
                editions=self._states(),
            )
        )

    def answer(self, refusal: ValidationError) -> bool:
        """Put the sentence on the row that stated it, if it names one."""
        key = refusal.key if isinstance(refusal, GraphRefused) else None
        form = None if key is None else self._rows_by_key().get(key)
        if form is None:
            return False
        form.add_error(None, refusal.messages[0])
        return True

    def bind(self, game: Game) -> None:
        """Name the Game a submit just made, so the graph has a parent."""
        self.game = game

    def write(self) -> None:
        """One transaction over the graph and the columns that shadow it."""
        write_and_mirror(self.written_game, self.write_rows)
```

`adopt()` and `initial_release` stay for now; Task 3 takes them. The imports
at the top of the module become:

```python
from games.catalog_writes import (
    EditionState,
    GraphRefused,
    ReleaseState,
    RowKey,
    WrittenGraph,
    state_catalog_graph,
)
```

`adopt()` still uses `InitialRelease` through `initial_release`, so
`games.catalog_compat` keeps that import for one more task.

- [ ] **Step 5: Run the form tests**

Run: `make test ARGS="tests/test_catalog_graph_form.py"`
Expected: PASS.

- [ ] **Step 6: Run the suite that renders and posts these pages**

Run: `make check-fast`
Expected: PASS. `tests/test_game_form_page.py` and `tests/test_catalog_compat.py`
still exercise the old creator through the views, which is untouched here.

- [ ] **Step 7: Commit**

```bash
git add games/catalog_form.py tests/test_catalog_graph_form.py
git commit -m "Let the Game form state its graph in one call"
```

---

## Task 3: The coordinator, and one submit per view

**Files:**
- Create: `games/catalog_submit.py`
- Create: `tests/test_catalog_submit.py`
- Modify: `games/views/game.py`
- Modify: `games/catalog_form.py` (remove `adopt()` and `initial_release`)

**Interfaces:**
- Consumes: `CatalogGraphForm.bind`, `.write`, `.answer` (Task 2);
  `write_and_mirror`, `LEGACY_IDENTITY_TAKEN` from `games.catalog_compat`;
  `sync_game_wikidata` from `games.external_references`.
- Produces:
  - `save_game_columns(form: GameForm) -> Game`
  - `save_game_and_graph(form: GameForm, graph: CatalogGraphForm) -> Game`
  - `submitted_game_or_form_error(form, graph) -> Game | None`
  - `WIKIDATA_CONFLICT_MESSAGE`, `RACED`, `ConstraintAnswer`,
    `CONSTRAINT_ANSWERS`, `UNREACHABLE_FROM_THE_GAME_FORM`
- Gone from `games/views/game.py`: `WIKIDATA_CONFLICT_MESSAGE`,
  `_game_form_refusal`, `_saved_game_or_form_error`,
  `_added_game_or_form_error`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_catalog_submit.py`.

```python
"""One submit of the Game form: one transaction, one creator."""

from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse

from games.catalog_compat import LEGACY_IDENTITY_TAKEN
from games.catalog_submit import (
    CONSTRAINT_ANSWERS,
    RACED,
    UNREACHABLE_FROM_THE_GAME_FORM,
    WIKIDATA_CONFLICT_MESSAGE,
    answered_constraint,
)
from games.models import Edition, ExternalReference, Game, Release
from timetracker.temporal import temporal_input_name

pytestmark = pytest.mark.django_db(transaction=True)


def game_post(name: str, **extra: str) -> dict[str, str]:
    """The Game form's own fields, beside the Editions area."""
    posted = {
        "name": name,
        "sort_name": "",
        "wikidata": "",
        "status": "unplayed",
        "editions-count": "1",
        "edition-0-name": "",
        "edition-0-releases-count": "1",
        "edition-0-release-0-platform": "",
        "in_library": "edition-0-release-0",
    }
    posted.update(extra)
    return posted


def test_a_refused_graph_takes_the_renamed_game_back(client, owned_user, stated_graph):
    """One transaction: the name and the graph go together or not at all."""
    client.force_login(owned_user)
    graph = stated_graph(
        Game(library=owned_user.library, name="Elite"), owned_user.library
    )
    posted = game_post("Elite Renamed")
    posted["edition-0-edition_id"] = str(graph.edition.pk)
    posted["edition-0-release-0-release_id"] = str(graph.release.pk)
    Edition.objects.filter(pk=graph.edition.pk).update(game=None)

    response = client.post(
        reverse("games:edit_game", args=[graph.game.pk]), data=posted
    )

    assert response.status_code == 200
    graph.game.refresh_from_db()
    assert graph.game.name == "Elite"


def test_a_graph_that_is_fine_saves_the_rename_with_it(
    client, owned_user, stated_graph
):
    """The inverse, so the rollback above is not passing on nothing."""
    client.force_login(owned_user)
    graph = stated_graph(
        Game(library=owned_user.library, name="Elite"), owned_user.library
    )
    posted = game_post("Elite Renamed")
    posted["edition-0-edition_id"] = str(graph.edition.pk)
    posted["edition-0-release-0-release_id"] = str(graph.release.pk)
    posted["edition-0-name"] = "Director's Cut"

    response = client.post(
        reverse("games:edit_game", args=[graph.game.pk]), data=posted
    )

    assert response.status_code == 302
    graph.game.refresh_from_db()
    graph.edition.refresh_from_db()
    assert (graph.game.name, graph.edition.name) == (
        "Elite Renamed",
        "Director's Cut",
    )


def test_add_game_leaves_exactly_one_edition_and_one_release(client, owned_user):
    """One creator: nothing claims a row it did not ask for."""
    client.force_login(owned_user)
    posted = game_post("Elite")
    posted["edition-0-name"] = "Director's Cut"
    row = "edition-0-release-0-release_date"
    posted[temporal_input_name(row, "kind")] = "date"
    posted[temporal_input_name(row, "start_year")] = "1984"

    response = client.post(reverse("games:add_game"), data=posted)

    assert response.status_code == 302
    game = Game.objects.get(name="Elite")
    editions = Edition.objects.alive().filter(game=game)
    assert editions.count() == 1
    assert editions.get().name == "Director's Cut"
    releases = Release.objects.alive().filter(edition=editions.get())
    assert releases.count() == 1
    assert releases.get().is_default is True


def test_a_game_with_no_graph_can_be_edited(client, owned_user):
    """What the backfill leaves: a Game nothing ever wrote a graph for."""
    client.force_login(owned_user)
    game = Game.objects.create(library=owned_user.library, name="Stranded")

    response = client.post(
        reverse("games:edit_game", args=[game.pk]), data=game_post("Stranded")
    )

    assert response.status_code == 302
    assert Edition.objects.alive().filter(game=game).count() == 1


def test_a_taken_legacy_identity_lands_on_the_game_form(
    client, owned_user, stated_graph
):
    """The mirror refuses the whole Game, not one row."""
    client.force_login(owned_user)
    stated_graph(Game(library=owned_user.library, name="Twin"), owned_user.library)
    graph = stated_graph(
        Game(library=owned_user.library, name="Elite"), owned_user.library
    )
    posted = game_post("Twin")
    posted["edition-0-edition_id"] = str(graph.edition.pk)
    posted["edition-0-release-0-release_id"] = str(graph.release.pk)

    response = client.post(
        reverse("games:edit_game", args=[graph.game.pk]), data=posted
    )

    assert response.status_code == 200
    assert LEGACY_IDENTITY_TAKEN in response.content.decode()


def test_a_taken_wikidata_id_lands_on_the_wikidata_field(
    client, owned_user, stated_graph
):
    client.force_login(owned_user)
    twin = stated_graph(
        Game(library=owned_user.library, name="Twin"), owned_user.library
    )
    ExternalReference.objects.create(
        provider="wikidata",
        entity_kind="game",
        provider_key="Q42",
        game=twin.game,
    )
    graph = stated_graph(
        Game(library=owned_user.library, name="Elite"), owned_user.library
    )
    posted = game_post("Elite", wikidata="Q42")
    posted["edition-0-edition_id"] = str(graph.edition.pk)
    posted["edition-0-release-0-release_id"] = str(graph.release.pk)

    response = client.post(
        reverse("games:edit_game", args=[graph.game.pk]), data=posted
    )

    assert response.status_code == 200
    assert WIKIDATA_CONFLICT_MESSAGE in response.content.decode()


def test_a_race_the_pre_check_missed_answers_in_words(client, owned_user, stated_graph):
    """The database is the only thing that decides, so read what it did."""
    client.force_login(owned_user)
    stated_graph(Game(library=owned_user.library, name="Twin"), owned_user.library)
    graph = stated_graph(
        Game(library=owned_user.library, name="Elite"), owned_user.library
    )
    posted = game_post("Twin")
    posted["edition-0-edition_id"] = str(graph.edition.pk)
    posted["edition-0-release-0-release_id"] = str(graph.release.pk)

    with patch("games.catalog_compat._collides", return_value=False):
        response = client.post(
            reverse("games:edit_game", args=[graph.game.pk]), data=posted
        )

    assert response.status_code == 200
    assert LEGACY_IDENTITY_TAKEN in response.content.decode()


# --- the mapping itself ------------------------------------------------------


class _Diagnostic:
    def __init__(self, name: str) -> None:
        self.constraint_name = name


class _Cause(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.diag = _Diagnostic(name)


def collision(name: str) -> IntegrityError:
    error = IntegrityError(name)
    error.__cause__ = _Cause(name)
    return error


def test_a_mapped_constraint_becomes_a_sentence():
    answer = answered_constraint(collision("unique_default_edition_per_game"))

    assert answer is not None
    assert answer.sentence == RACED
    assert answer.field is None


def test_the_wikidata_constraint_names_its_own_field():
    answer = answered_constraint(
        collision("unique_external_reference_provider_kind_key")
    )

    assert answer == (WIKIDATA_CONFLICT_MESSAGE, "wikidata")


def test_an_unmapped_constraint_gets_no_sentence():
    """A wrong sentence is worse than none."""
    assert answered_constraint(collision("unique_library_mode_name_preset")) is None


def test_a_collision_with_no_diagnostic_gets_no_sentence():
    assert answered_constraint(IntegrityError("no cause")) is None


def test_every_unique_constraint_the_form_can_reach_is_mapped():
    """A migration that adds one fails here, not in front of a person."""
    from django.db.models import UniqueConstraint

    reachable = [Game, Edition, Release, ExternalReference]
    declared = {
        constraint.name
        for model in reachable
        for constraint in model._meta.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    accounted = set(CONSTRAINT_ANSWERS) | set(UNREACHABLE_FROM_THE_GAME_FORM)

    assert declared <= accounted, declared - accounted
```

- [ ] **Step 2: Run them to see them fail**

Run: `make test ARGS="tests/test_catalog_submit.py -x"`
Expected: FAIL — `ModuleNotFoundError: No module named 'games.catalog_submit'`.

- [ ] **Step 3: Give the mirror a seam its race test can open**

`test_a_race_the_pre_check_missed_answers_in_words` patches the mirror's
pre-check away so a real `IntegrityError` rises. Pull that check out of
`mirror_legacy_columns` in `games/catalog_compat.py` into a function with a
name, changing nothing about what it does:

```python
def _collides(game: Game, platform: Platform | None, year: int | None) -> bool:
    """Another live Game of this library already reads the same."""
    return (
        Game.objects.filter(
            library_id=game.library_id,
            name=game.name,
            platform=platform,
            year_released=year,
            removed_at__isnull=True,
        )
        .exclude(pk=game.pk)
        .exists()
    )
```

and in `mirror_legacy_columns`:

```text
    if _collides(game, platform, year):
        raise ValidationError(LEGACY_IDENTITY_TAKEN)
```

- [ ] **Step 4: Write the coordinator**

Create `games/catalog_submit.py`:

```python
"""One submit of the Game form.

The Game's own columns, its wikidata reference, its whole catalog
graph and the flat columns that shadow it, in one transaction. The
PlayerGame command stays outside: `run_in_transaction` opens the
transaction it retries and refuses to nest.
"""

from typing import TYPE_CHECKING, Final, NamedTuple

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from games.catalog_compat import LEGACY_IDENTITY_TAKEN
from games.catalog_form import CatalogGraphForm
from games.catalog_writes import DUPLICATE_EDITION_NAME
from games.external_references import sync_game_wikidata
from games.models import Game

if TYPE_CHECKING:
    from games.forms import GameForm

WIKIDATA_CONFLICT_MESSAGE = "This Wikidata entity ID already belongs to another game."
#: No pre-check wins a race. The database decided; this says so.
RACED = "Another change reached this game first. Nothing was saved; try again."


class ConstraintAnswer(NamedTuple):
    """What a constraint says, and where a person reads it."""

    sentence: str
    field: str | None


#: A refusal only the database can state, in words a person reads.
CONSTRAINT_ANSWERS: Final[dict[str, ConstraintAnswer]] = {
    "unique_library_game_name_platform_year": ConstraintAnswer(
        LEGACY_IDENTITY_TAKEN, None
    ),
    "unique_library_platformless_game_name_year": ConstraintAnswer(
        LEGACY_IDENTITY_TAKEN, None
    ),
    "unique_live_edition_name_per_game": ConstraintAnswer(DUPLICATE_EDITION_NAME, None),
    "unique_default_edition_per_game": ConstraintAnswer(RACED, None),
    "unique_default_release_per_edition": ConstraintAnswer(RACED, None),
    "unique_external_reference_provider_kind_key": ConstraintAnswer(
        WIKIDATA_CONFLICT_MESSAGE, "wikidata"
    ),
}

#: Declared on a model this form writes, and still out of its reach.
#: A constraint named here states why, and the guard test reads it.
UNREACHABLE_FROM_THE_GAME_FORM: Final[dict[str, str]] = {}


def answered_constraint(collision: IntegrityError) -> ConstraintAnswer | None:
    """What the database refused, if this form has words for it.

    An unmapped constraint gets none and rises as itself, the way
    `games/writes/answers.py` treats an unmapped conflict: a wrong
    sentence is worse than no sentence.
    """
    diagnostic = getattr(collision.__cause__, "diag", None)
    name = None if diagnostic is None else diagnostic.constraint_name
    return None if name is None else CONSTRAINT_ANSWERS.get(name)


@transaction.atomic
def save_game_columns(form: "GameForm") -> Game:
    """The Game's own columns and its wikidata reference.

    No graph and no mirror: the graph is stated after this, and the
    mirror reads what the graph left.
    """
    game = form.save(commit=False)
    if not game._state.adding:
        persisted = Game.objects.select_for_update().get(pk=game.pk)
        if persisted.library_id != game.library_id:
            raise ValidationError("A persisted Game cannot change library owner.")
    if game.library_id is None:
        raise ValidationError("A private Game requires a library owner.")
    game.original_release_date = form.cleaned_data["original_release_date"]
    game.save()
    sync_game_wikidata(game=game)
    return game


@transaction.atomic
def save_game_and_graph(form: "GameForm", graph: CatalogGraphForm) -> Game:
    """The Game and its whole graph, or neither of them.

    The mirror runs last, once, so a rename can no longer collide
    with the platform and year of a Release the same submit is
    replacing.
    """
    game = save_game_columns(form)
    graph.bind(game)
    graph.write()
    return game


def _game_form_refusal(form: "GameForm", error: ValidationError) -> bool:
    """Put a refusal the Game's own fields caused back on them."""
    if hasattr(error, "message_dict") and set(error.message_dict) == {"provider_key"}:
        form.add_error("wikidata", WIKIDATA_CONFLICT_MESSAGE)
        return True
    if LEGACY_IDENTITY_TAKEN in error.messages:
        #: (name, platform, year) is unique per library, and the
        #: platform and the year come from the marked Release row.
        form.add_error(None, LEGACY_IDENTITY_TAKEN)
        return True
    return False


def submitted_game_or_form_error(
    form: "GameForm", graph: CatalogGraphForm
) -> Game | None:
    """Write one submit, or put every refusal where it is read.

    `IntegrityError` is caught out here: inside the transaction the
    connection is unusable, thus the answer has to come after the
    rollback.
    """
    try:
        return save_game_and_graph(form, graph)
    except IntegrityError as collision:
        answer = answered_constraint(collision)
        if answer is None:
            raise
        form.add_error(answer.field, answer.sentence)
        return None
    except ValidationError as refusal:
        if _game_form_refusal(form, refusal):
            return None
        if graph.answer(refusal):
            return None
        #: `save_game_columns`'s two guards are programming errors,
        #: not things a person typed.
        raise
```

- [ ] **Step 5: Point both views at it**

In `games/views/game.py`, remove `WIKIDATA_CONFLICT_MESSAGE`,
`_game_form_refusal`, `_saved_game_or_form_error` and
`_added_game_or_form_error`, drop the now-unused imports of
`save_legacy_game_form` and `LEGACY_IDENTITY_TAKEN`, and add:

```python
from games.catalog_submit import submitted_game_or_form_error
```

`add_game` calls it in place of `_added_game_or_form_error`:

```text
    if form.is_valid() and graph.is_valid():
        game = submitted_game_or_form_error(form, graph)
        if game is not None:
```

`edit_game`'s `and`-chain, where each `and` used to be a commit, becomes:

```text
    if form.is_valid() and graph.is_valid():
        game = submitted_game_or_form_error(form, graph)
        if game is not None and record_facts_for_request(
            request,
            game,
            status=form.cleaned_data["status"],
            mastered=form.cleaned_data["mastered"],
            correlation_id=new_correlation_id(),
        ):
            return redirect(return_url(request, fallback="games:list_games"))
```

- [ ] **Step 6: Take `adopt()` and `initial_release` out of the form**

There is one creator now, so there is nothing to claim. Remove `adopt()`,
`initial_release`, and the `InitialRelease` import from
`games/catalog_form.py`. Update `written_game`'s assertion message, which
names the method that is gone:

```python
class CatalogGraphForm:
    @property
    def written_game(self) -> Game:
        """The Game the graph hangs from, once there is one."""
        assert self.game is not None, "A new Game is named by bind() before the write."
        return self.game
```

- [ ] **Step 7: Run the new tests**

Run: `make test ARGS="tests/test_catalog_submit.py"`
Expected: PASS.

- [ ] **Step 8: Run the pages that post through these views**

Run: `make test ARGS="tests/test_game_form_page.py tests/test_catalog_graph_form.py tests/test_catalog_compat.py"`
Expected: PASS. `tests/test_catalog_compat.py` still calls
`save_legacy_game_form`, which is still there and still works; Task 4 takes it.

- [ ] **Step 9: Commit**

```bash
git add games/catalog_submit.py games/catalog_form.py games/catalog_compat.py \
    games/views/game.py tests/test_catalog_submit.py
git commit -m "Make one submit of the Game form one transaction"
```

---

## Task 4: Retire the row verbs

Nothing in the app calls them now. Take them out, and take the tests whose
subject they were with them.

**Files:**
- Modify: `games/catalog_writes.py`
- Modify: `games/catalog_compat.py`
- Modify: `tests/test_catalog_compat.py`, `tests/test_catalog_graph_form.py`,
  `tests/test_game_form_page.py`, `tests/test_removed_rows.py`
- Remove: `tests/test_catalog_writes.py`, `tests/test_catalog_graph_writes.py`

- [ ] **Step 1: Check that nothing but a test names them**

Run:

```bash
grep -rn "add_edition\|update_edition\|remove_edition\|add_release\|update_release\|remove_release\|save_private_game\|PrivateGameGraph\|save_legacy_game_form\|InitialRelease" --include=*.py .
```

Expected: hits in `games/catalog_writes.py`, `games/catalog_compat.py`, the
four test files above, the two files being removed, and
`e2e/test_game_form_catalog_e2e.py` (Task 5). No other app module.

- [ ] **Step 2: Take them out of `games/catalog_writes.py`**

Remove `save_private_game`, `PrivateGameGraph`, `add_edition`,
`update_edition`, `remove_edition`, `add_release`, `update_release`,
`remove_release`, `_validate_platform`, `_writable_edition`,
`_writable_release`, and the five sentences the statement answers:
`DUPLICATE_RELEASE`, `DEFAULT_EDITION_HELD`, `DEFAULT_RELEASE_HELD`,
`DEMOTED_EDITION`, `DEMOTED_RELEASE`. `_refuse_foreign_platform` keeps its
`key` parameter and loses the default, since the one caller states a key.

The module docstring says what the module is now:

```python
"""Write a private Game's Editions and Releases.

One call states the whole graph of one Game, checks it against the
desired end state, and writes it in one transaction. Nothing here
destroys a row: a removal is a stamp.
"""
```

- [ ] **Step 3: Take the legacy save out of `games/catalog_compat.py`**

Remove `save_legacy_game_form`, `InitialRelease`, and the imports they needed
(`save_private_game`, `Platform`, `TemporalValue`, `Callable` stays for
`write_and_mirror`, the `TYPE_CHECKING` block for `GameForm` goes). What
stays is the mirror: `LEGACY_IDENTITY_TAKEN`, `_default_release`, `_collides`,
`mirror_legacy_columns`, `write_and_mirror`.

- [ ] **Step 4: Remove the two test files whose subject is gone**

```bash
git rm tests/test_catalog_writes.py tests/test_catalog_graph_writes.py
```

Every case worth keeping from them is already in
`tests/test_state_catalog_graph.py` (the permission refusals, the removal
rules, the name rules) or `tests/test_catalog_submit.py` (the owner-transfer
and shared-Game guards, the rollback). Before removing them, read both files
once and confirm each surviving rule has a home; add the case to the new file
if it does not.

- [ ] **Step 5: Move `tests/test_catalog_compat.py` onto the coordinator**

Its 16 tests split in two. The ones about the mirror — what the flat columns
follow, when the year goes null, the identity check — stay, calling
`save_game_and_graph` or `mirror_legacy_columns` directly. The ones about
`save_legacy_game_form`'s own guards move into `tests/test_catalog_submit.py`
as `save_game_columns` tests:

```python
def test_a_persisted_game_may_not_change_library_owner(owned_library, other_library):
    game = Game.objects.create(library=owned_library, name="Elite")
    form = game_form(instance=game, library=other_library, name="Elite")
    assert form.is_valid(), form.errors
    form.instance.library = other_library

    with pytest.raises(ValidationError):
        save_game_columns(form)


def test_a_private_game_needs_a_library_owner(owned_library):
    form = game_form(library=owned_library, name="Elite")
    assert form.is_valid(), form.errors
    form.instance.library = None

    with pytest.raises(ValidationError):
        save_game_columns(form)
```

Replace `new_release(...)` and the `save_private_game` fixtures in that file
with the `stated_graph` fixture.

- [ ] **Step 6: Update the three remaining test modules**

- `tests/test_catalog_graph_form.py` and `tests/test_game_form_page.py`:
  replace every `save_private_game(...)` call with the `stated_graph` fixture,
  and every `add_edition` / `add_release` setup call with a direct
  `Edition.objects.create(...)` / `Release.objects.create(...)`, which is what
  the setup was reaching for.
- `tests/test_removed_rows.py`: it built a `PrivateGameGraph` by hand. Give it
  its own container, since the type was never about that file:

```python
class Graph(NamedTuple):
    """One Game and the two rows a removal test hangs from."""

    game: Game
    edition: Edition
    release: Release
```

- [ ] **Step 7: Run everything but the browser**

Run: `make check-fast`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add -A games/ tests/
git commit -m "Retire the six row verbs and the legacy save"
```

---

## Task 5: The browser sees it too

**Files:**
- Modify: `e2e/test_game_form_catalog_e2e.py`

- [ ] **Step 1: Point the file at what is left**

Its imports name `DUPLICATE_RELEASE`, `add_release` and `save_private_game`.
The first becomes `DUPLICATE_RELEASE_IN_FORM` from `games.catalog_form`; the
`game` fixture states the graph itself, since `tests/conftest.py` is not on
this package's path:

```python
from games.catalog_compat import mirror_legacy_columns
from games.catalog_form import DUPLICATE_RELEASE_IN_FORM
from games.catalog_writes import EditionState, ReleaseState, state_catalog_graph


def state_default_graph(game: Game, library, *, platform=None, release_date=None):
    """One Game as the app leaves it: one default Edition and Release."""
    game.save()
    return state_catalog_graph(
        game=game,
        library=library,
        editions=[
            EditionState(
                key="edition-0",
                is_default=True,
                releases=(
                    ReleaseState(
                        key="edition-0-release-0",
                        platform=platform,
                        release_date=release_date,
                        is_default=True,
                    ),
                ),
            )
        ],
    )


@pytest.fixture
def game(e2e_library, amiga) -> Game:
    """One Game as the app leaves it: a default graph, columns mirrored."""
    written = state_default_graph(
        Game(library=e2e_library, name="Elite"),
        e2e_library,
        platform=amiga,
        release_date=TemporalValue.from_year(1984),
    )
    mirror_legacy_columns(written.game)
    return written.game
```

The `add_release(...)` setup calls become `Release.objects.create(...)` on the
default Edition.

- [ ] **Step 2: Add the case the whole spec is about**

```python
def test_binning_a_release_and_re_adding_its_pair_keeps_the_new_row(
    signed_in, live_server, game, amiga
):
    """One submit, one statement: the re-add is not eaten by the removal."""
    page = signed_in
    open_form(page, live_server, game)
    old = live_releases(default_edition(game))[0]

    remove_release_row(page, edition=0, release=0)
    add_release_row(page, edition=0)
    fill_release_row(page, edition=0, release=1, platform="Amiga", year="1984")
    mark_release_row(page, edition=0, release=1)
    submit(page)

    page.wait_for_url(f"{live_server.url}/tracker/game/**")
    live = live_releases(default_edition(game))
    assert len(live) == 1
    assert live[0].pk != old.pk
    assert live[0].platform == amiga
```

Reuse the row helpers already in that file for removing, adding, filling,
marking and submitting; do not write new ones. Read the existing tests first
and call the same helpers by their own names.

- [ ] **Step 3: Run the browser suite for this file**

Run: `make test-e2e ARGS="e2e/test_game_form_catalog_e2e.py"`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add e2e/test_game_form_catalog_e2e.py
git commit -m "Bin a release and re-add its pair, in a real browser"
```

---

## Task 6: The contract says what the code does

**Files:**
- Modify: `docs/catalog.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Rewrite the sections of `docs/catalog.md` that changed shape**

Four edits, each named in the spec:

1. **"Repeating a write" goes.** In its place, a section on stating a graph:

```markdown
## Stating a graph

`state_catalog_graph()` takes one Game's whole desired graph and writes it in
one transaction. Identity is the row the caller names and nothing else: a state
naming an Edition or a Release is that row, and a state naming none is a new
row. A name is a name, not an identity.

A row the caller does not mention is left alone. Removal is stated by a mark on
the row, so a writer that knows about two Editions can state those two without
taking the three somebody added by hand. Absence meaning removal would let one
importer defect take a whole catalog.

Every refusal is checked against the desired end state, before anything is
written, and each carries the caller's own name for the row that caused it, so
a sentence reaches the row a person typed into.

A named row is read again under the Game's lock. The Edition or Release a
caller passes is identity only: the verb resolves each after
`select_for_update()` and refuses one that is removed, or that hangs from
another Game or Edition. Every caller reads its rows before the lock, so no
caller can act on a stale one.
```

2. **"What a removal refuses" shrinks to one rule.** Its four bullets become:

```markdown
A removal is a stamp. `state_catalog_graph` calls `remove()` from
`games/removal.py`; nothing in the service destroys a row.

- **The last Edition of a Game stays.** A Game with no Edition has nowhere to
  hold a Release. An Edition nobody mentioned counts: the rule is about what
  the Game is left holding.
- **The last Release of an Edition goes**, and the default mark goes with it.
  An Edition holding no Release is an ordinary state.

The three rules that used to guard the default mark are gone. A statement says
which row is default and which row leaves at the same time, so a mark a
removal would have stranded is a question the caller already answered.
```

3. **"The graph is written in one place"** becomes true and names its place.
   The paragraph about `save_private_game` and `adopt()` on Add Game goes; in
   its stead:

```markdown
On Add Game there is no Game to hang the graph from yet, and the area starts as
one blank Edition holding one blank marked row. `games/catalog_submit.py` saves
the Game's own columns first and hands the graph form the Game it made, so one
statement writes the whole graph. There is no second creator and nothing to
claim. The Game, its wikidata reference, its graph and the flat columns are one
transaction, so a refused row leaves no Game behind for a second submit to
collide with.
```

4. **"What a form refuses that the service does not"** gains the second rule:

```markdown
Two surviving Releases of one Edition may not state the same platform and date.
The page would show a person two rows nothing tells apart. `CatalogGraphForm`
refuses it; the service does not, because #782 needs two regions on one date to
be two rows. The rule is about the surviving set, so binning a row and adding
another that states its platform and date is fine, and is written.
```

And a short section for the backstop:

```markdown
## What a constraint says

No pre-check wins a race. The mirror reads with a SELECT and writes with an
UPDATE, the wikidata reference has the same shape, and the two default marks
are set with no pre-check at all. So `games/catalog_submit.py` catches the
`IntegrityError` outside the transaction, reads the constraint the database
named, and looks it up in `CONSTRAINT_ANSWERS`. A constraint that is not in
that mapping rises as itself: a wrong sentence is worse than none. A guard test
fails unless every unique constraint on Game, Edition, Release and
ExternalReference is either mapped or named as out of reach, with a reason.
```

Also update the opening: `save_private_game()` no longer writes anything, and
"The six verbs below write the rest of it" is one verb now.

- [ ] **Step 2: Update the `CLAUDE.md` catalog bullet**

Replace the "A private catalog graph is written through the service" bullet:

```markdown
- **A private catalog graph is stated, not patched row by row** — call
  `state_catalog_graph` from `games/catalog_writes.py`, never
  `Edition.objects.create()` and never a per-row verb. It takes one Game's
  whole desired graph, refuses it against the desired end state, and writes it
  in one transaction; a row the caller does not mention is left alone, and
  removal is stated by a mark on the row. Each refusal carries the caller's own
  key for the row that caused it. One submit of the Game form goes through
  `games/catalog_submit.py`, which writes the Game's columns, its wikidata
  reference, the graph and the flat mirror in one transaction and answers every
  refusal onto the field or the row that stated it; the PlayerGame command
  stays outside, because `run_in_transaction` refuses to nest. The one thing
  that states a graph from a person is `CatalogGraphForm` in
  `games/catalog_form.py`, hosted by Add Game and Edit Game alike. There are no
  standalone Edition or Release routes. The contract is
  [Catalog](docs/catalog.md).
```

- [ ] **Step 3: Lint the prose**

Run: `make vale`
Expected: no error. A warning about a word in a non-domain sense is fine;
an error names one replacement and has to be taken.

- [ ] **Step 4: Run the gate**

Run: `make check`
Expected: PASS — lint, format check, mypy, vale, ts-check, vitest, and the
whole pytest suite including `e2e/`.

- [ ] **Step 5: Commit**

```bash
git add docs/catalog.md CLAUDE.md
git commit -m "Say that one call states the whole graph"
```

- [ ] **Step 6: Record the finding on #782**

The importer's identity is `ExternalReference`, and that issue's own words are
the argument for removing name matching. Post it:

```bash
gh issue comment 782 --body "$(cat <<'EOF'
#986 removed `add_edition`'s name matching and `add_release`'s
(platform, release_date) matching. `docs/catalog.md` justified both as
idempotency for this importer, and this issue had already retired that
justification:

> It is not a prerequisite of idempotency either, because `ExternalReference`
> already accepts `entity_kind="release"` and each Release keys on IGDB's own
> `release_dates.id`.

So the importer's identity is `ExternalReference`, and nothing else. The
service now takes one Game's whole desired graph through
`state_catalog_graph`, where a row the caller names is that row and a row it
names none is new. A partial statement leaves unmentioned rows alone, so
stating the two Editions IGDB knows about cannot remove three a person added.

One consequence for this issue: the pair identity that would have had to
become a triple when region lands no longer exists, so the region column is
purely additive.
EOF
)"
```

---

## Self-Review

**Spec coverage.**

| Spec section | Task |
| --- | --- |
| Why the row verbs are the wrong grain | 1 (the verb), 4 (they go) |
| The upsert has no consumer | 4, 6 (the #782 comment) |
| The verb, its types, its refusals | 1 |
| The write order is now private | 1, step 6 |
| What the other verbs become | 4 |
| The coordinator, its transaction order | 3 |
| Where a refusal lands (three steps) | 3 |
| What the form becomes | 2, 3 (`adopt`/`initial_release`) |
| One refusal the form keeps making | 2 |
| What a constraint says | 3 (mapping, guard test, the `_collides` seam) |
| Tests: service cases | 1 |
| Tests: form and view cases | 2, 3 |
| Tests: the e2e case | 5 |
| Documentation | 6 |

**Placeholders.** None: every step carries the code or the command it needs.
Two steps are judgement rather than transcription — Task 4 step 4 asks the
implementer to read the two files being removed and confirm each surviving
rule has a home, and Task 5 step 2 asks them to reuse the row helpers that
file already has rather than invent new ones. Both are named as such.

**Type consistency.** `RowKey`, `EditionState`, `ReleaseState`,
`WrittenEdition`, `WrittenGraph` and `GraphRefused` are defined in Task 1 and
used under those names in Tasks 2, 3 and 5. `write_rows` (Task 2) is what
`write()` passes to `write_and_mirror`, and `write()` is what
`save_game_and_graph` calls in Task 3. `answer()` returns `bool` in Task 2 and
is read as a bool in Task 3. `ConstraintAnswer(sentence, field)` is defined
and read as a two-field `NamedTuple` in Task 3, including in the test that
compares it to a plain tuple.

**What is deliberately left.** `record_facts_for_request` still commits after
the graph, so a refused command leaves a saved catalog edit. The spec says so,
and the reason is that `run_in_transaction` refuses to nest.
