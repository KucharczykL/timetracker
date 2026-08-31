# Manage private Editions and Releases — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a private Game's detail page the controls to add, edit and remove
its own Editions and Releases, and move the Platform and the release date off the
Game form onto the graph that now owns them.

**Architecture:** Six new `ORIGIN_AWARE` routes in a new `games/views/catalog.py`
render two thin forms (`EditionForm`, `ReleaseForm`) that call the #967 verbs in
`games/catalog_writes.py` and turn a refusal into a form error. Game detail grows
per-Edition and per-Release control rows, and only for a private Game. The Game
form gives up `platform` and `year_released`, states `original_release_date`
through #964's `TemporalFormField`, and keeps one inline Release row on Add Game.
The three legacy integer/FK columns stop being written by a form and become a
*mirror* of the default Edition's default Release, maintained in
`games/catalog_compat.py` until #889 drops them.

**Tech Stack:** Django 6 · PostgreSQL 18 · Python 3.14 · the Python component
system in `common/components/` · `<temporal-field>` (`ts/elements/temporal-field.ts`,
Node ≥ 26) · pytest + pytest-playwright.

**Spec:** `docs/superpowers/specs/2026-08-30-issue-969-private-catalog-management-design.md`

**Issue:** https://github.com/KucharczykL/timetracker/issues/969 (depends on #964,
#965, #967, #968; blocks #896)

---

## Two calls this plan makes that the spec did not

Read these before Task 1. Both are answers to comments on the issue, and both go
beyond the spec's literal words. If either is wrong, stop and say so rather than
building around it.

**1. The Game form drops `year_released` *and* `original_year_released`.**
The spec says only that "Platform and release year leave" the Game form, and that
"the original release date stays on the Game form, because it is a fact of the
work." But issue comment 1 records the trap: `original_year_released` is an
integer, and `catalog_compat._reconcile_year()` silently downgrades a stored
`1984-06` to `1984` the moment somebody edits an unrelated field. Comment 1's
option 2 is taken here: `original_year_released` leaves the form too, replaced by
`original_release_date` rendered through `TemporalFormField`. That deletes
`_LegacyYear`, `_StoredDates`, `_stored_dates()` and `_reconcile_year()` outright,
and with them the whole reconciliation problem. This is what makes #969 the first
page that hosts a `<temporal-field>`, which the widget's own docstring already
anticipates.

**2. The three legacy columns become a mirror, with a pre-check.**
`Game.platform`, `Game.year_released` and `Game.original_year_released` still have
readers outside this issue's blast radius (filters, the API, the sample fixture,
`unique_library_game_name_platform_year`). #889's body sanctions "temporary
dual-write/read compatibility", so this plan writes it: after every catalog write,
`mirror_legacy_columns(game)` copies the default Edition's default Release down
onto the flat columns. Because those columns carry a conditional unique
constraint, a Release edit can push one Game onto another's `(name, platform,
year)`. The mirror pre-checks with a query and refuses with a readable sentence,
rather than letting an `IntegrityError` become a 500.

## Global Constraints

- **Everything runs through `make`.** Never `uv run pytest`, never `direnv exec .`.
  Iterate with `make check-fast`; the gate before done/push/PR is the full
  `make check`, and it must be green.
- **Nothing destroys a row.** `remove_edition`/`remove_release` in the service
  already call `remove()`. No view calls `.delete()`.
- **No dispatch inside a transaction.** `run_in_transaction` refuses to nest. The
  new catalog views dispatch no command, so they may use `transaction.atomic` via
  `write_and_mirror`; a view that also calls `record_facts_for_request` must not.
- **The service owns the write.** A form calls a verb from
  `games/catalog_writes.py`. No form calls `Edition.objects.create()`,
  `Release.objects.create()` or `instance.save()` on either model.
- **Every mutating link carries `?origin=`** via `action_url(name, *args,
  origin=request.get_full_path())`, and every mutating view ends with
  `redirect(return_url(request, fallback=...))`. Every new route is classified in
  `games/views/returns.py` or `tests/test_returns_classification.py` fails.
- **No route mutates on GET.** A removal is one `confirm_and_remove()` call.
- **UI is Python components** from `common.components`, htpy form only:
  `Builder(class_="x")[child]`. Never HTML strings, never `str(a) + str(b)`.
- **Complete words in identifiers** — `element` not `el`, `release` not `rel`.
- **Refused words** — a projector *replays*; the row is the *projection*; nothing
  is *deleted*. `make vale` grades docs and comments. See `docs/vocabulary.md`.
- **A widget renders to text, so `Media` never bubbles.** Any view rendering a
  `TemporalFormField` must thread
  `scripts=ModuleScript("dist/elements/temporal-field.js")` itself.
- **A refusal sentence is a module constant**, so a screen and a test name the
  same words.
- **Controls appear only for a private Game** (`game.library_id is not None`).
- Work on branch `claude/issue-969-private-catalog-management`.

---

## File structure

| File | Responsibility | Task |
|---|---|---|
| `games/views/removal.py` | `confirm_and_apply` re-renders on a refused action | 1 |
| `tests/test_confirmation_refusals.py` | *(create)* the refused-confirmation contract | 1 |
| `games/catalog_compat.py` | the legacy mirror; `_reconcile_year` and friends go | 2 |
| `tests/test_catalog_compat.py` | rewritten around the mirror | 2 |
| `games/forms.py` | `GameForm` loses two fields, gains a temporal one; `InitialReleaseForm` | 3 |
| `games/views/game.py` | `add_game`/`edit_game` host the temporal element and the inline row | 3 |
| `ts/add_game.ts` | drops the year→original-year sync pair | 3 |
| `games/forms.py` | `EditionForm`, `ReleaseForm` — the service-backed forms | 4 |
| `tests/test_catalog_forms.py` | *(create)* form-level rules and refusal surfacing | 4 |
| `games/views/catalog.py` | *(create)* the six views | 5 |
| `games/urls.py` | the six routes | 5 |
| `games/views/returns.py` | the six routes classified `ORIGIN_AWARE` | 5 |
| `tests/test_catalog_write_views.py` | the six routes end to end | 5 |
| `games/views/game.py` | Game detail grows the control rows | 6 |
| `tests/test_game_hierarchy_section.py` | what the controls say, and when they are absent | 6 |
| `e2e/test_catalog_management_e2e.py` | *(create)* add an Edition and a Release in a browser | 7 |
| `docs/temporal.md` | *(create)* the temporal layer, written once | 8 |
| `docs/catalog.md`, `CLAUDE.md` | the controls, the mirror, the deferrals | 8 |

---

### Task 1: A refused confirmation re-renders instead of falling over

`confirm_and_apply` calls `action()` bare, so a `ValidationError` from a catalog
verb would become a 500. Every Edition and Release removal in Task 5 goes through
it, and three of the service's refusals (`LAST_EDITION`, `DEFAULT_EDITION_HELD`,
`DEFAULT_RELEASE_HELD`) are reachable by a person clicking Remove on a page that
raced with another tab. Fix the flow before building on it.

**Files:**
- Modify: `games/views/removal.py:27-69`
- Test: `tests/test_confirmation_refusals.py` *(create)*

**Interfaces:**
- Consumes: nothing.
- Produces: `confirm_and_apply(request, *, action, title, message, confirm_label,
  fallback, fallback_args=(), details=None, reject=None) -> HttpResponse` — the
  signature is unchanged; the behaviour on a `ValidationError` from `action()` is
  new. It re-renders the same `ConfirmPage` with the error's first message shown
  above the message, at HTTP 409.

- [ ] **Step 1: Write the failing test**

```python
"""A refused confirmation says why, on the same page."""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from games.views.removal import confirm_and_apply

pytestmark = pytest.mark.django_db

REFUSAL = "This edition is the last one."


@pytest.fixture
def request_factory_post(rf):
    user = get_user_model().objects.create_user(username="refused", password="p")

    def post():
        request = rf.post("/anything/")
        request.user = user
        return request

    return post


def test_a_refused_action_re_renders_the_confirmation(request_factory_post):
    def refuse():
        raise ValidationError(REFUSAL)

    response = confirm_and_apply(
        request_factory_post(),
        action=refuse,
        title="Remove edition",
        message="Remove it?",
        confirm_label="Remove",
        fallback="games:list_games",
    )

    assert response.status_code == 409
    assert REFUSAL in response.content.decode()


def test_an_accepted_action_still_redirects(request_factory_post):
    response = confirm_and_apply(
        request_factory_post(),
        action=lambda: None,
        title="Remove edition",
        message="Remove it?",
        confirm_label="Remove",
        fallback="games:list_games",
    )

    assert response.status_code == 302
```

- [ ] **Step 2: Run it and watch it fail**

Run: `make test ARGS="tests/test_confirmation_refusals.py -x"`
Expected: FAIL — the `ValidationError` propagates out of `confirm_and_apply`.

- [ ] **Step 3: Make the confirmation absorb the refusal**

In `games/views/removal.py`, add the import and split the confirmation render out
so both paths use it:

```python
from django.core.exceptions import ValidationError
```

Replace the body of `confirm_and_apply` from `if request.method != "POST":` down:

```python
def confirmation(refusal: str = "", status: int = 200) -> HttpResponse:
    return render_page(
        request,
        ConfirmPage(
            title=title,
            message=f"{refusal} {message}" if refusal else message,
            details=details,
            post_url=request.get_full_path(),
            csrf_token=get_token(request),
            cancel_url=return_url(
                request, fallback=fallback, fallback_args=fallback_args
            ),
            confirm_label=confirm_label,
        ),
        title=title,
        status=status,
    )


if request.method != "POST":
    return confirmation()
try:
    action()
except ValidationError as refusal:
    #: The service refuses on state, and state moves: another tab
    #: may have taken the sibling this removal was counting on.
    #: A 500 would read as our fault rather than a stale page.
    return confirmation(refusal.messages[0], status=409)
return redirect(
    return_url(
        request,
        fallback=fallback,
        fallback_args=fallback_args,
        reject=reject,
    )
)
```

- [ ] **Step 4: Give `render_page` a status, if it has none**

Run: `grep -n "def render_page" -A 20 common/layout.py`

If `render_page` takes no `status`, add a keyword-only `status: int = 200` and
pass it to the `HttpResponse` it builds. Do not add a second render helper.

- [ ] **Step 5: Run the tests**

Run: `make test ARGS="tests/test_confirmation_refusals.py tests/test_removable_models.py -x"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add games/views/removal.py common/layout.py tests/test_confirmation_refusals.py
git commit -m "Say why a confirmation was refused, on the same page"
```

---

### Task 2: The legacy columns mirror the graph

`Game.platform`, `Game.year_released` and `Game.original_year_released` stop being
form fields and become a shadow of the graph. Delete the reconciliation machinery
in one go; there is nothing left for it to reconcile once the form states a
`TemporalValue` directly.

**Files:**
- Modify: `games/catalog_compat.py` (whole file)
- Modify: `tests/test_catalog_compat.py`

**Interfaces:**
- Consumes: `save_private_game(*, game, original_release_date, release_date,
  platform) -> PrivateGameGraph` from `games/catalog_writes.py`.
- Produces:
  - `LEGACY_IDENTITY_TAKEN: str` — the refusal sentence.
  - `mirror_legacy_columns(game: Game) -> None` — writes the three columns from
    the default Edition's default Release, raising `ValidationError` first if the
    result would collide with another live Game.
  - `write_and_mirror[T](game: Game, write: Callable[[], T]) -> T` — one
    transaction: the write, then the mirror.
  - `InitialRelease(platform: Platform | None, release_date: TemporalValue | None)`
    — a `NamedTuple`.
  - `save_legacy_game_form(form: GameForm, *, initial_release: InitialRelease |
    None = None) -> Game`.
- Gone: `_LegacyYear`, `_StoredDates`, `_stored_dates`, `_reconcile_year`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_catalog_compat.py` (keep the existing `library`/`user` fixtures;
the `game_form()` helper is rewritten in Task 3, so write these against the
functions, not the form):

```python
def test_the_mirror_copies_the_default_release_onto_the_flat_columns(library):
    platform = Platform.objects.create(library=library, name="Amiga")
    game = Game.objects.create(library=library, name="Elite")
    edition = Edition.objects.create(game=game, is_default=True)
    Release.objects.create(
        edition=edition,
        platform=platform,
        release_date=TemporalValue.from_month(1984, 6),
        is_default=True,
    )

    mirror_legacy_columns(game)

    game.refresh_from_db()
    assert game.platform_id == platform.pk
    assert game.year_released == 1984


def test_the_mirror_keeps_the_precision_of_the_original_date(library):
    game = Game.objects.create(
        library=library,
        name="Elite",
        original_release_date=TemporalValue.from_month(1983, 9),
    )

    mirror_legacy_columns(game)

    game.refresh_from_db()
    assert game.original_year_released == 1983
    assert game.original_release_date == TemporalValue.from_month(1983, 9)


def test_the_mirror_clears_the_columns_when_the_release_states_nothing(library):
    game = Game.objects.create(library=library, name="Elite", year_released=1999)
    edition = Edition.objects.create(game=game, is_default=True)
    Release.objects.create(edition=edition, is_default=True)

    mirror_legacy_columns(game)

    game.refresh_from_db()
    assert game.platform_id is None
    assert game.year_released is None


def test_the_mirror_refuses_to_collide_with_another_live_game(library):
    platform = Platform.objects.create(library=library, name="Amiga")
    Game.objects.create(
        library=library, name="Elite", platform=platform, year_released=1984
    )
    second = Game.objects.create(library=library, name="Elite")
    edition = Edition.objects.create(game=second, is_default=True)
    Release.objects.create(
        edition=edition,
        platform=platform,
        release_date=TemporalValue.from_year(1984),
        is_default=True,
    )

    with pytest.raises(ValidationError) as refusal:
        mirror_legacy_columns(second)

    assert LEGACY_IDENTITY_TAKEN in refusal.value.messages


def test_a_refused_mirror_leaves_the_write_undone(library):
    """One transaction: the mirror's refusal takes the write with it."""
    platform = Platform.objects.create(library=library, name="Amiga")
    Game.objects.create(
        library=library, name="Elite", platform=platform, year_released=1984
    )
    second = Game.objects.create(library=library, name="Elite")
    edition = Edition.objects.create(game=second, is_default=True)

    with pytest.raises(ValidationError):
        write_and_mirror(
            second,
            lambda: add_release(
                edition=edition,
                library=library,
                platform=platform,
                release_date=TemporalValue.from_year(1984),
            ),
        )

    assert not Release.objects.filter(edition=edition).exists()
```

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_catalog_compat.py -x"`
Expected: FAIL with `ImportError` / `NameError` on `mirror_legacy_columns`.

- [ ] **Step 3: Rewrite `games/catalog_compat.py`**

Replace `_LegacyYear`, `_StoredDates`, `_stored_dates`, `_reconcile_year` and
`save_legacy_game_form` with:

```python
#: A flat column pair still holds a unique constraint over the
#: library, thus a Release edit can walk one Game onto another's.
LEGACY_IDENTITY_TAKEN = (
    "Another game in your library already has this name, platform and year."
)


class InitialRelease(NamedTuple):
    """The one Release the Add Game form states inline."""

    platform: Platform | None
    release_date: TemporalValue | None


def _default_release(game: Game) -> Release | None:
    """The Release the flat columns shadow."""
    return Release.objects.filter(
        edition__game_id=game.pk,
        edition__is_default=True,
        edition__removed_at__isnull=True,
        is_default=True,
        removed_at__isnull=True,
    ).first()


def mirror_legacy_columns(game: Game) -> None:
    """The flat Game columns follow the graph that now owns them.

    Nothing reads these to render a Game any more, but filters, the
    API and the fixture still do. #889 takes them, and this with
    them.
    """
    release = _default_release(game)
    platform_id = None if release is None else release.platform_id
    date = None if release is None else release.release_date
    year = None if date is None else date.year
    original = game.original_release_date
    collides = (
        Game.objects.filter(
            library_id=game.library_id,
            name=game.name,
            platform_id=platform_id,
            year_released=year,
            removed_at__isnull=True,
        )
        .exclude(pk=game.pk)
        .exists()
    )
    if collides:
        raise ValidationError(LEGACY_IDENTITY_TAKEN)
    Game.objects.filter(pk=game.pk).update(
        platform_id=platform_id,
        year_released=year,
        original_year_released=None if original is None else original.year,
    )
    game.refresh_from_db(fields=("platform", "year_released", "original_year_released"))


@transaction.atomic
def write_and_mirror[T](game: Game, write: Callable[[], T]) -> T:
    """One write to the graph, then the columns that shadow it."""
    result = write()
    mirror_legacy_columns(game)
    return result


#: No dispatch here: run_in_transaction refuses to nest.
@transaction.atomic
def save_legacy_game_form(
    form: GameForm, *, initial_release: InitialRelease | None = None
) -> Game:
    """Write the Game and the one default graph its form states.

    `initial_release` is the Add Game form's inline row. An edit
    states none and passes the stored Release straight back, so the
    save guarantees the graph without touching it.
    """
    game = form.save(commit=False)
    stored = _default_release(game) if game.pk else None
    release = initial_release or InitialRelease(
        platform=None if stored is None else stored.platform,
        release_date=None if stored is None else stored.release_date,
    )
    graph = save_private_game(
        game=game,
        original_release_date=form.cleaned_data["original_release_date"],
        release_date=release.release_date,
        platform=release.platform,
    )
    sync_game_wikidata(game=graph.game)
    mirror_legacy_columns(graph.game)
    return graph.game
```

Fix the imports at the top: drop anything only the removed helpers used; add
`Callable` from `collections.abc`, `NamedTuple` from `typing`, `ValidationError`
from `django.core.exceptions`, `Release` and `Platform` from `games.models`, and
`TemporalValue` from `timetracker.temporal`.

- [ ] **Step 4: Rewrite the tests the reconciliation owned**

These six tests in `tests/test_catalog_compat.py` describe a rule that no longer
exists. Remove them:

- `test_legacy_save_keeps_a_qualifier_on_the_release_date`
- `test_legacy_save_still_writes_a_year_the_form_owns`
- `test_legacy_save_leaves_an_unknown_year_unset`
- `test_legacy_save_writes_both_years_for_a_new_game`
- `test_legacy_save_keeps_the_year_of_a_stored_decade`
- `test_legacy_save_keeps_the_year_of_a_stored_range`

Their concern — a rich stored value surviving an edit — is now covered by
`test_the_mirror_keeps_the_precision_of_the_original_date` above and by
`test_edit_game_keeps_a_month_on_the_original_release` in Task 3.

- [ ] **Step 5: Run the tests**

Run: `make test ARGS="tests/test_catalog_compat.py -x"`
Expected: PASS. `tests/test_catalog_write_views.py` is expected to be red until
Task 3; leave it.

- [ ] **Step 6: Commit**

```bash
git add games/catalog_compat.py tests/test_catalog_compat.py
git commit -m "Let the flat columns follow the graph that owns them"
```

---

### Task 3: The Game form gives up two fields and states a date at any precision

**Files:**
- Modify: `games/forms.py` (`GameForm` ~934-1026; add `InitialReleaseForm`)
- Modify: `games/views/game.py:117-127` (`_save_game_form_or_add_wikidata_error`),
  `:261-323` (`add_game`), `:355-380` (`edit_game`)
- Modify: `ts/add_game.ts`
- Modify: `tests/test_catalog_write_views.py`, `tests/test_sentinel_removal.py`,
  `tests/test_library_form_isolation.py`, `tests/test_removed_rows.py`,
  `tests/test_catalog_hierarchy.py`

**Interfaces:**
- Consumes: `InitialRelease`, `save_legacy_game_form(form, *, initial_release=None)`
  from Task 2; `TemporalFormField(*, presentation, label="Date", **kwargs)` and
  `date_time_presentation_for_request(request) -> DateTimePresentation`.
- Produces:
  - `GameForm(data=None, *, library: UserLibrary, presentation:
    DateTimePresentation, instance=None)` — `Meta.fields` is now
    `("name", "sort_name", "wikidata")`; `original_release_date` is a
    form-level `TemporalFormField`; `platform`, `year_released` and
    `original_year_released` are gone.
  - `InitialReleaseForm(data=None, *, library: UserLibrary, presentation:
    DateTimePresentation)` with fields `platform` and `release_date`, and
    `def initial_release(self) -> InitialRelease`.
  - `_saved_game_or_form_error(form, *, initial_release=None) -> Game | None` in
    `games/views/game.py`, replacing `_save_game_form_or_add_wikidata_error`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_catalog_write_views.py`, replace the `game_payload()` helper's
`platform` / `year_released` / `original_year_released` keys with the temporal and
inline-release names, and add:

```python
def temporal_payload(prefix: str, **parts: str) -> dict[str, str]:
    """The inputs one temporal control posts."""
    return {temporal_input_name(prefix, key): value for key, value in parts.items()}


def test_add_game_states_the_platform_through_the_inline_release(client, library):
    platform = Platform.objects.create(library=library, name="Amiga")
    payload = game_payload() | {"platform": str(platform.pk)}
    payload |= temporal_payload("release_date", lower_year="1984", lower_month="6")

    client.post(reverse("games:add_game"), payload)

    game = Game.objects.get(name=payload["name"])
    release = Release.objects.get(edition__game=game)
    assert release.platform_id == platform.pk
    assert release.release_date == TemporalValue.from_month(1984, 6)
    #: The flat columns shadow it until #889.
    assert game.platform_id == platform.pk
    assert game.year_released == 1984


def test_add_game_states_the_original_release_at_its_own_precision(client, library):
    payload = game_payload() | temporal_payload(
        "original_release_date", lower_year="1983", lower_month="9"
    )

    client.post(reverse("games:add_game"), payload)

    game = Game.objects.get(name=payload["name"])
    assert game.original_release_date == TemporalValue.from_month(1983, 9)
    assert game.original_year_released == 1983


def test_edit_game_keeps_a_month_on_the_original_release(client, library):
    """The trap issue comment 1 named: an unrelated edit downgraded it."""
    game = Game.objects.create(
        library=library,
        name="Elite",
        original_release_date=TemporalValue.from_month(1983, 9),
    )
    payload = game_payload(name="Elite II") | temporal_payload(
        "original_release_date", lower_year="1983", lower_month="9"
    )

    client.post(reverse("games:edit_game", args=[game.pk]), payload)

    game.refresh_from_db()
    assert game.original_release_date == TemporalValue.from_month(1983, 9)


def test_edit_game_leaves_the_default_release_alone(client, library):
    platform = Platform.objects.create(library=library, name="Amiga")
    game = Game.objects.create(library=library, name="Elite")
    edition = Edition.objects.create(game=game, is_default=True)
    Release.objects.create(
        edition=edition,
        platform=platform,
        release_date=TemporalValue.from_year(1984),
        is_default=True,
    )

    client.post(reverse("games:edit_game", args=[game.pk]), game_payload(name="Elite"))

    release = Release.objects.get(edition=edition)
    assert release.platform_id == platform.pk
    assert release.release_date == TemporalValue.from_year(1984)


def test_add_game_hosts_the_temporal_element(client):
    html = client.get(reverse("games:add_game")).content.decode()

    assert "<temporal-field" in html
    assert "dist/elements/temporal-field.js" in html
```

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_catalog_write_views.py -x"`
Expected: FAIL — `GameForm` still declares `platform`, and no temporal input is
rendered.

- [ ] **Step 3: Rewrite `GameForm` and add `InitialReleaseForm`**

In `games/forms.py`, replace `GameForm.__init__`, its declared `platform` field,
`field_order` and `Meta.fields`:

```python
class GameForm(
    _LibraryBoundConstraintValidationMixin, PrimitiveWidgetsMixin, forms.ModelForm
):
    def __init__(
        self,
        *args,
        library: UserLibrary,
        presentation: DateTimePresentation,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.library = library
        self.instance.library = library
        #: The column is not editable, thus no model field reaches
        #: the form and the initial is stated by hand.
        self.fields["original_release_date"] = TemporalFormField(
            presentation=presentation, label="Original release"
        )
        if self.instance.pk is not None:
            self.initial.setdefault(
                "original_release_date", self.instance.original_release_date
            )
        #: A declared field added here otherwise sinks to the bottom.
        self.order_fields(self.field_order)
        #: They left Meta.fields, so model_to_dict misses them.
        if self.instance.pk is not None:
            tracked = PlayerGame.objects.filter(
                library=library, game=self.instance
            ).first()
            if tracked is not None:
                self.initial.setdefault("status", tracked.status)
                self.initial.setdefault("mastered", tracked.mastered)

    #: Plain fields: this form writes no column.
    #: The initial is what tracking would create.
    status = forms.ChoiceField(
        choices=PlayerGameStatus.choices,
        required=True,
        initial=PlayerGameStatus.UNPLAYED,
    )
    mastered = forms.BooleanField(required=False)

    #: Declared fields otherwise sink below model fields.
    field_order = (
        "name",
        "sort_name",
        "original_release_date",
        "status",
        "mastered",
        "wikidata",
    )
```

and its `Meta`:

```python
    class Meta:
        model = Game
        fields = ("name", "sort_name", "wikidata")
        widgets: ClassVar[dict[str, forms.Widget]] = {"name": autofocus_input_widget}
```

Leave `save()` and `clean_wikidata()` as they are. Then add, directly below:

```python
class InitialReleaseForm(PrimitiveWidgetsMixin, forms.Form):
    """The one Release the Add Game form states inline.

    A Game gets a default Edition and a default Release either way;
    this only says what they hold. Editing them afterwards is the
    Release form's job.
    """

    def __init__(
        self,
        *args,
        library: UserLibrary,
        presentation: DateTimePresentation,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.library = library
        cast(
            forms.ModelChoiceField, self.fields["platform"]
        ).queryset = Platform.objects.visible_to(library).order_by("name")
        self.fields["platform"].widget.options_resolver = partial(
            _platform_options, library=library
        )
        self.fields["release_date"] = TemporalFormField(
            presentation=presentation, label="Released"
        )

    platform = forms.ModelChoiceField(
        queryset=Platform.objects.order_by("name"),
        required=False,
        widget=SearchSelectWidget(
            search_url="/api/platforms/search", options_resolver=_platform_options
        ),
    )

    def initial_release(self) -> InitialRelease:
        return InitialRelease(
            platform=self.cleaned_data["platform"],
            release_date=self.cleaned_data["release_date"],
        )
```

Import `InitialRelease` from `games.catalog_compat` inside the method or at the
bottom of the module if a circular import bites; `games/forms.py` is imported by
`catalog_compat` only for a type annotation, so prefer
`from games.catalog_compat import InitialRelease` under `TYPE_CHECKING` plus a
local import in `initial_release()` if `make check` complains.

- [ ] **Step 4: Rewrite the two views**

In `games/views/game.py`, replace `_save_game_form_or_add_wikidata_error`:

```python
def _saved_game_or_form_error(
    form: GameForm, *, initial_release: InitialRelease | None = None
) -> Game | None:
    """Save, or put the refusal where the person typing can read it."""
    try:
        return save_legacy_game_form(form, initial_release=initial_release)
    except ValidationError as error:
        if getattr(error, "message_dict", None) and set(error.message_dict) == {
            "provider_key"
        }:
            form.add_error("wikidata", WIKIDATA_CONFLICT_MESSAGE)
            return None
        if LEGACY_IDENTITY_TAKEN in error.messages:
            #: (name, platform, year) is unique per library, and the
            #: platform and the year now come from the inline row.
            form.add_error(None, LEGACY_IDENTITY_TAKEN)
            return None
        raise
```

In `add_game`, build both forms and thread the element's script:

```python
@login_required
def add_game(request: HttpRequest) -> HttpResponse:
    library = cast(User, request.user).library
    presentation = date_time_presentation_for_request(request)
    form = GameForm(request.POST or None, library=library, presentation=presentation)
    release_form = InitialReleaseForm(
        request.POST or None, library=library, presentation=presentation
    )
    if form.is_valid() and release_form.is_valid():
        game = _saved_game_or_form_error(
            form, initial_release=release_form.initial_release()
        )
        if game is not None:
            ...  # the existing tracking / record_facts / redirect block, unchanged
```

and its render:

```python
    return render_page(
        request,
        AddForm(
            form,
            request=request,
            fields=Fragment(FormFields(form), FormFields(release_form)),
            additional_row=Fragment(
                ControlButton(
                    color="gray",
                    type="submit",
                    name="submit_and_redirect",
                )["Submit & Create Purchase"],
                ControlButton(
                    color="gray",
                    type="submit",
                    name="submit_and_create_session",
                )["Submit & Create Session"],
            ),
        ),
        title="Add New Game",
        scripts=Fragment(
            ModuleScript("dist/elements/search-select.js"),
            ModuleScript("dist/elements/temporal-field.js"),
            ModuleScript("dist/add_game.js"),
        ),
    )
```

In `edit_game`, pass the presentation, call the renamed helper with no
`initial_release`, and add the element's script:

```python
    presentation = date_time_presentation_for_request(request)
    form = GameForm(
        request.POST or None,
        instance=game,
        library=library,
        presentation=presentation,
    )
    if (
        form.is_valid()
        and _saved_game_or_form_error(form) is not None
        and record_facts_for_request(...)  # unchanged
    ):
        ...
    return render_page(
        request,
        AddForm(form, request=request),
        title="Edit Game",
        scripts=Fragment(
            ModuleScript("dist/elements/search-select.js"),
            ModuleScript("dist/elements/temporal-field.js"),
        ),
    )
```

Add `LEGACY_IDENTITY_TAKEN`, `InitialRelease` and `InitialReleaseForm` to the
imports, and `FormFields` to the `common.components` import.

- [ ] **Step 5: Drop the dead sync pair in `ts/add_game.ts`**

The `#id_year_released` → `#id_original_year_released` pair has no source field
any more. Remove that pair and keep the name → sort_name one. Do **not** try to
sync the two temporal controls: they are multi-input composites, and copying a
whole draft across is a feature nobody asked for. Note the lost convenience in the
commit message.

- [ ] **Step 6: Repair every `GameForm(` construction site**

Six places pass no `presentation`. Give each one
`date_time_presentation_for_request(request)` in a view, or the test's own
presentation fixture:

- `games/views/game.py` — `add_game`, `edit_game` (done in Step 4)
- `tests/test_catalog_compat.py:26`
- `tests/test_removed_rows.py:262`
- `tests/test_catalog_hierarchy.py:288`
- `tests/test_library_form_isolation.py` lines 80, 140, 148, 170, 315, 343

In `tests/test_library_form_isolation.py:89`, the assertion on
`game.fields["platform"].queryset` moves to `InitialReleaseForm` — `GameForm` no
longer has a platform field. Keep the assertion; change the form it names.

- [ ] **Step 7: Repair `tests/test_sentinel_removal.py:95-120`**

`test_platformless_duplicate_via_add_game_form_shows_error` posts
`year_released: "1984"`. Post the inline release's temporal inputs instead, and
expect `LEGACY_IDENTITY_TAKEN` in the re-rendered page rather than the model
constraint's message. The behaviour under test — a duplicate re-renders the form,
it does not 500 — is unchanged; the sentence that says so has moved.

- [ ] **Step 8: Run the tests**

Run: `make ts && make check-fast`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add games/forms.py games/views/game.py ts/add_game.ts tests/
git commit -m "Let the Game form state a date the graph can hold"
```

---

### Task 4: The two forms that call the service

**Files:**
- Modify: `games/forms.py` (add `EditionForm` and `ReleaseForm` below
  `InitialReleaseForm`)
- Test: `tests/test_catalog_forms.py` *(create)*

**Interfaces:**
- Consumes: `add_edition`, `update_edition`, `add_release`, `update_release` from
  `games/catalog_writes.py`; `write_and_mirror` from `games/catalog_compat.py`.
- Produces:
  - `UNNAMED_SIBLING_EDITION: str` in `games/forms.py`.
  - `EditionForm(data=None, *, library: UserLibrary, game: Game, instance:
    Edition | None = None)` with fields `name`, `is_default`, and
    `def write(self) -> Edition | None`.
  - `ReleaseForm(data=None, *, library: UserLibrary, presentation:
    DateTimePresentation, edition: Edition, instance: Release | None = None)`
    with fields `platform`, `release_date`, `is_default`, and
    `def write(self) -> Release | None`.
  - Both `write()` methods return `None` after adding the service's sentence as a
    non-field error.

- [ ] **Step 1: Write the failing tests**

`tests/test_catalog_forms.py`:

```python
"""What the Edition and Release forms refuse, and how they say it."""

import pytest
from django.contrib.auth import get_user_model

from games.catalog_writes import DUPLICATE_EDITION_NAME
from games.forms import UNNAMED_SIBLING_EDITION, EditionForm, ReleaseForm
from games.models import Edition, Game, Platform, Release
from timetracker.temporal import TemporalValue, temporal_input_name

pytestmark = pytest.mark.django_db


@pytest.fixture
def library():
    return (
        get_user_model()
        .objects.create_user(username="catalog-forms", password="p")
        .library
    )


@pytest.fixture
def game(library):
    game = Game.objects.create(library=library, name="Elite")
    Edition.objects.create(game=game, is_default=True)
    return game


def test_a_second_edition_must_state_a_name(library, game):
    form = EditionForm({"name": ""}, library=library, game=game)

    assert not form.is_valid()
    assert UNNAMED_SIBLING_EDITION in form.errors["name"]


def test_a_lone_edition_may_stay_unnamed(library):
    bare = Game.objects.create(library=library, name="Bare")
    form = EditionForm({"name": ""}, library=library, game=bare)

    assert form.is_valid()


def test_an_edition_may_state_its_own_empty_name_again(library):
    lone = Game.objects.create(library=library, name="Lone")
    edition = Edition.objects.create(game=lone, is_default=True)
    form = EditionForm({"name": ""}, library=library, game=lone, instance=edition)

    assert form.is_valid()


def test_the_form_says_what_the_service_refused(library, game):
    Edition.objects.create(game=game, name="Gold")
    form = EditionForm({"name": "Gold"}, library=library, game=game)

    assert form.is_valid()
    assert form.write() is None
    assert DUPLICATE_EDITION_NAME in form.errors["__all__"]


def test_the_current_default_edition_cannot_be_demoted_in_the_form(library, game):
    default = Edition.objects.get(game=game, is_default=True)
    form = EditionForm(library=library, game=game, instance=default)

    assert form.fields["is_default"].disabled
    assert form.fields["is_default"].initial is True


def test_a_release_form_writes_through_the_service(library, game, presentation):
    platform = Platform.objects.create(library=library, name="Amiga")
    edition = Edition.objects.get(game=game, is_default=True)
    posted = {"platform": str(platform.pk)} | {
        temporal_input_name("release_date", "lower_year"): "1984"
    }
    form = ReleaseForm(
        posted, library=library, presentation=presentation, edition=edition
    )

    assert form.is_valid()
    release = form.write()

    assert release is not None
    assert release.platform_id == platform.pk
    assert release.release_date == TemporalValue.from_year(1984)
    #: The flat columns followed it.
    game.refresh_from_db()
    assert game.year_released == 1984
```

Add a `presentation` fixture to the file, or reuse the project's existing one if
`tests/conftest.py` already provides one — check with
`grep -rn "def presentation" tests/conftest.py`.

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_catalog_forms.py -x"`
Expected: FAIL with `ImportError` on `EditionForm`.

- [ ] **Step 3: Write the two forms**

In `games/forms.py`:

```python
#: The service allows it for #782's importer; a person typing does
#: not, because two unnamed siblings both read as the Game's name.
UNNAMED_SIBLING_EDITION = (
    "Name this edition. Another edition already presents as the game's own name."
)


class EditionForm(PrimitiveWidgetsMixin, forms.Form):
    """One Edition, written through `games/catalog_writes.py`."""

    name = forms.CharField(
        max_length=255, required=False, widget=autofocus_input_widget
    )
    is_default = forms.BooleanField(required=False, label="Default edition")

    def __init__(
        self,
        *args,
        library: UserLibrary,
        game: Game,
        instance: Edition | None = None,
        **kwargs,
    ):
        self.library = library
        self.game = game
        self.instance = instance
        if instance is not None:
            kwargs.setdefault(
                "initial", {"name": instance.name, "is_default": instance.is_default}
            )
        super().__init__(*args, **kwargs)
        if instance is not None and instance.is_default:
            #: The service refuses a demotion, thus the control does.
            #: Promoting a sibling is how the mark moves.
            self.fields["is_default"].disabled = True
            self.fields["is_default"].initial = True

    def clean_name(self) -> str:
        wanted = self.cleaned_data["name"].strip()
        if wanted:
            return wanted
        siblings = Edition.objects.for_library(self.library).filter(game=self.game)
        if self.instance is not None:
            siblings = siblings.exclude(pk=self.instance.pk)
        if siblings.exists():
            raise forms.ValidationError(UNNAMED_SIBLING_EDITION)
        return wanted

    def write(self) -> Edition | None:
        """Call the verb, or say what it refused."""
        try:
            return write_and_mirror(self.game, self._verb)
        except ValidationError as refusal:
            self.add_error(None, refusal.messages[0])
            return None

    def _verb(self) -> Edition:
        if self.instance is None:
            return add_edition(
                game=self.game,
                library=self.library,
                name=self.cleaned_data["name"],
                is_default=self.cleaned_data["is_default"],
            )
        return update_edition(
            edition=self.instance,
            library=self.library,
            name=self.cleaned_data["name"],
            is_default=self.cleaned_data["is_default"],
        )


class ReleaseForm(InitialReleaseForm):
    """One Release, written through `games/catalog_writes.py`."""

    is_default = forms.BooleanField(required=False, label="Default release")

    def __init__(
        self,
        *args,
        library: UserLibrary,
        presentation: DateTimePresentation,
        edition: Edition,
        instance: Release | None = None,
        **kwargs,
    ):
        self.edition = edition
        self.instance = instance
        if instance is not None:
            kwargs.setdefault(
                "initial",
                {
                    "platform": instance.platform_id,
                    "release_date": instance.release_date,
                    "is_default": instance.is_default,
                },
            )
        super().__init__(*args, library=library, presentation=presentation, **kwargs)
        if instance is not None and instance.is_default:
            self.fields["is_default"].disabled = True
            self.fields["is_default"].initial = True

    def write(self) -> Release | None:
        try:
            return write_and_mirror(self.edition.game, self._verb)
        except ValidationError as refusal:
            self.add_error(None, refusal.messages[0])
            return None

    def _verb(self) -> Release:
        if self.instance is None:
            return add_release(
                edition=self.edition,
                library=self.library,
                platform=self.cleaned_data["platform"],
                release_date=self.cleaned_data["release_date"],
                is_default=self.cleaned_data["is_default"],
            )
        return update_release(
            release=self.instance,
            library=self.library,
            platform=self.cleaned_data["platform"],
            release_date=self.cleaned_data["release_date"],
            is_default=self.cleaned_data["is_default"],
        )
```

`ReleaseForm` inherits `InitialReleaseForm`'s `platform` field and its
`release_date` wiring, so the two stay identical by construction rather than by
discipline. `self.edition.game` needs the Game loaded — the views select it
related.

Add the imports: `add_edition`, `update_edition`, `add_release`, `update_release`
from `games.catalog_writes`, `write_and_mirror` from `games.catalog_compat`,
`Edition` and `Release` from `games.models`, `ValidationError` from
`django.core.exceptions`.

- [ ] **Step 4: Run the tests**

Run: `make test ARGS="tests/test_catalog_forms.py -x"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/forms.py tests/test_catalog_forms.py
git commit -m "Give an edition and a release a form that calls the service"
```

---

### Task 5: The six routes

**Files:**
- Create: `games/views/catalog.py`
- Modify: `games/urls.py`, `games/views/returns.py`
- Test: `tests/test_catalog_write_views.py`

**Interfaces:**
- Consumes: `EditionForm`, `ReleaseForm` (Task 4); `confirm_and_remove` with the
  refusal handling from Task 1; `remove_edition`, `remove_release`,
  `SHARED_GAME` from `games/catalog_writes.py`; `write_and_mirror`.
- Produces six views and six url names:
  - `games:add_edition` — `game/<uuidv7:game_id>/edition/add`
  - `games:edit_edition` — `edition/<uuidv7:edition_id>/edit`
  - `games:remove_edition` — `edition/<uuidv7:edition_id>/remove`
  - `games:add_release` — `edition/<uuidv7:edition_id>/release/add`
  - `games:edit_release` — `release/<uuidv7:release_id>/edit`
  - `games:remove_release` — `release/<uuidv7:release_id>/remove`
  All six are `ORIGIN_AWARE`. All six fall back to the Game's own detail page.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_catalog_write_views.py`:

```python
def test_add_edition_writes_one_and_returns_to_the_game(client, library):
    game = Game.objects.create(library=library, name="Elite")
    Edition.objects.create(game=game, is_default=True)

    response = client.post(
        reverse("games:add_edition", args=[game.pk]), {"name": "Gold"}
    )

    assert response.status_code == 302
    assert Edition.objects.filter(game=game, name="Gold").exists()


def test_edit_edition_states_the_whole_row(client, library):
    game = Game.objects.create(library=library, name="Elite")
    Edition.objects.create(game=game, is_default=True)
    edition = Edition.objects.create(game=game, name="Gold")

    client.post(reverse("games:edit_edition", args=[edition.pk]), {"name": "Plus"})

    edition.refresh_from_db()
    assert edition.name == "Plus"


def test_remove_edition_stamps_rather_than_destroys(client, library):
    game = Game.objects.create(library=library, name="Elite")
    Edition.objects.create(game=game, is_default=True)
    edition = Edition.objects.create(game=game, name="Gold")

    client.post(reverse("games:remove_edition", args=[edition.pk]))

    edition.refresh_from_db()
    assert edition.removed_at is not None


def test_removing_the_last_edition_says_why_on_the_page(client, library):
    game = Game.objects.create(library=library, name="Elite")
    edition = Edition.objects.create(game=game, is_default=True)

    response = client.post(reverse("games:remove_edition", args=[edition.pk]))

    assert response.status_code == 409
    assert LAST_EDITION in response.content.decode()
    edition.refresh_from_db()
    assert edition.removed_at is None


def test_add_release_writes_one_under_its_edition(client, library):
    platform = Platform.objects.create(library=library, name="Amiga")
    game = Game.objects.create(library=library, name="Elite")
    edition = Edition.objects.create(game=game, is_default=True)
    posted = {"platform": str(platform.pk)} | {
        temporal_input_name("release_date", "lower_year"): "1984"
    }

    client.post(reverse("games:add_release", args=[edition.pk]), posted)

    release = Release.objects.get(edition=edition)
    assert release.release_date == TemporalValue.from_year(1984)


def test_edit_release_states_the_whole_row(client, library):
    game = Game.objects.create(library=library, name="Elite")
    edition = Edition.objects.create(game=game, is_default=True)
    release = Release.objects.create(
        edition=edition, release_date=TemporalValue.from_year(1984), is_default=True
    )

    client.post(
        reverse("games:edit_release", args=[release.pk]),
        {temporal_input_name("release_date", "lower_year"): "1985"},
    )

    release.refresh_from_db()
    assert release.release_date == TemporalValue.from_year(1985)
    assert release.platform_id is None


def test_remove_release_stamps_rather_than_destroys(client, library):
    game = Game.objects.create(library=library, name="Elite")
    edition = Edition.objects.create(game=game, is_default=True)
    Release.objects.create(edition=edition, is_default=True)
    second = Release.objects.create(edition=edition)

    client.post(reverse("games:remove_release", args=[second.pk]))

    second.refresh_from_db()
    assert second.removed_at is not None


def test_a_shared_game_answers_404_to_every_catalog_route(client):
    shared = Game.objects.create(library=None, name="Shared")
    edition = Edition.objects.create(game=shared, is_default=True)
    release = Release.objects.create(edition=edition, is_default=True)

    assert client.get(reverse("games:add_edition", args=[shared.pk])).status_code == 404
    assert (
        client.get(reverse("games:edit_edition", args=[edition.pk])).status_code == 404
    )
    assert (
        client.get(reverse("games:add_release", args=[edition.pk])).status_code == 404
    )
    assert (
        client.get(reverse("games:edit_release", args=[release.pk])).status_code == 404
    )


def test_another_library_cannot_reach_an_edition(client, other_library):
    game = Game.objects.create(library=other_library, name="Theirs")
    edition = Edition.objects.create(game=game, is_default=True)

    assert (
        client.get(reverse("games:edit_edition", args=[edition.pk])).status_code == 404
    )
```

Add an `other_library` fixture if the file has none: a second user's library.

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_catalog_write_views.py -k edition or release -x"`
Expected: FAIL — `NoReverseMatch`.

- [ ] **Step 3: Write `games/views/catalog.py`**

```python
"""Add, state and remove a private Game's Editions and Releases.

Every write goes through `games/catalog_writes.py`; nothing here
touches a model. A shared Game is not reachable: it has no owning
library, so `owned_or_404` refuses it before a form is built.
"""

from functools import partial
from typing import cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from common.components import AddForm, Fragment, ModuleScript
from common.layout import render_page
from common.returns import OriginUrl
from games.catalog_compat import write_and_mirror
from games.catalog_writes import remove_edition, remove_release
from games.forms import EditionForm, ReleaseForm
from games.models import Edition, Game, Release, User
from games.views.game import owned_or_404
from games.views.removal import confirm_and_remove
from games.views.returns import return_url
from timetracker.date_presentation import date_time_presentation_for_request


def _owned_game(request: HttpRequest, game_id: UUID) -> Game:
    library = cast(User, request.user).library
    return owned_or_404(Game.objects.for_library(library), library, id=game_id)


def _owned_edition(request: HttpRequest, edition_id: UUID) -> Edition:
    library = cast(User, request.user).library
    return owned_or_404(
        Edition.objects.for_library(library).select_related("game"),
        library,
        id=edition_id,
    )


def _owned_release(request: HttpRequest, release_id: UUID) -> Release:
    library = cast(User, request.user).library
    return owned_or_404(
        Release.objects.for_library(library).select_related("edition__game"),
        library,
        id=release_id,
    )


def _edition_page(
    request: HttpRequest, form: EditionForm, game: Game, title: str
) -> HttpResponse:
    if request.method == "POST" and form.is_valid() and form.write() is not None:
        return redirect(_back_to(request, game))
    return render_page(request, AddForm(form, request=request), title=title)


def _release_page(
    request: HttpRequest, form: ReleaseForm, game: Game, title: str
) -> HttpResponse:
    if request.method == "POST" and form.is_valid() and form.write() is not None:
        return redirect(_back_to(request, game))
    return render_page(
        request,
        AddForm(form, request=request),
        title=title,
        #: A widget renders to text, thus its Media never bubbles.
        scripts=Fragment(
            ModuleScript("dist/elements/search-select.js"),
            ModuleScript("dist/elements/temporal-field.js"),
        ),
    )


def _back_to(request: HttpRequest, game: Game) -> str:
    return return_url(
        request,
        fallback="games:view_game",
        fallback_args=(game.pk, game.url_slug),
    )


@login_required
def add_edition(request: HttpRequest, game_id: UUID) -> HttpResponse:
    game = _owned_game(request, game_id)
    library = cast(User, request.user).library
    form = EditionForm(request.POST or None, library=library, game=game)
    return _edition_page(request, form, game, "Add edition")


@login_required
def edit_edition(request: HttpRequest, edition_id: UUID) -> HttpResponse:
    edition = _owned_edition(request, edition_id)
    library = cast(User, request.user).library
    form = EditionForm(
        request.POST or None,
        library=library,
        game=edition.game,
        instance=edition,
    )
    return _edition_page(request, form, edition.game, "Edit edition")


@login_required
def remove_edition_view(request: HttpRequest, edition_id: UUID) -> HttpResponse:
    edition = _owned_edition(request, edition_id)
    library = cast(User, request.user).library
    game = edition.game
    return confirm_and_remove(
        request,
        edition,
        title="Remove edition",
        message=f"Remove the {edition.display_name} edition of {game.name}?",
        fallback="games:view_game",
        fallback_args=(game.pk, game.url_slug),
        action=partial(
            write_and_mirror,
            game,
            partial(remove_edition, edition=edition, library=library),
        ),
    )


@login_required
def add_release(request: HttpRequest, edition_id: UUID) -> HttpResponse:
    edition = _owned_edition(request, edition_id)
    library = cast(User, request.user).library
    form = ReleaseForm(
        request.POST or None,
        library=library,
        presentation=date_time_presentation_for_request(request),
        edition=edition,
    )
    return _release_page(request, form, edition.game, "Add release")


@login_required
def edit_release(request: HttpRequest, release_id: UUID) -> HttpResponse:
    release = _owned_release(request, release_id)
    library = cast(User, request.user).library
    form = ReleaseForm(
        request.POST or None,
        library=library,
        presentation=date_time_presentation_for_request(request),
        edition=release.edition,
        instance=release,
    )
    return _release_page(request, form, release.edition.game, "Edit release")


@login_required
def remove_release_view(request: HttpRequest, release_id: UUID) -> HttpResponse:
    release = _owned_release(request, release_id)
    library = cast(User, request.user).library
    game = release.edition.game
    return confirm_and_remove(
        request,
        release,
        title="Remove release",
        message=f"Remove this release of {release.edition.display_name}?",
        fallback="games:view_game",
        fallback_args=(game.pk, game.url_slug),
        action=partial(
            write_and_mirror,
            game,
            partial(remove_release, release=release, library=library),
        ),
    )
```

Check `owned_or_404`'s real home with `grep -rn "def owned_or_404" games/` and
import it from there rather than from `games/views/game.py` if it lives in a
shared module. `Release.objects.for_library` reads its ancestors' marks (#966), so
a removed Game hides its Releases here too.

- [ ] **Step 4: Add the six routes**

In `games/urls.py`, beside the existing game routes:

```python
(
    path(
        "game/<uuidv7:game_id>/edition/add",
        catalog.add_edition,
        name="add_edition",
    ),
)
(path("edition/<uuidv7:edition_id>/edit", catalog.edit_edition, name="edit_edition"),)
(
    path(
        "edition/<uuidv7:edition_id>/remove",
        catalog.remove_edition_view,
        name="remove_edition",
    ),
)
(
    path(
        "edition/<uuidv7:edition_id>/release/add",
        catalog.add_release,
        name="add_release",
    ),
)
(path("release/<uuidv7:release_id>/edit", catalog.edit_release, name="edit_release"),)
(
    path(
        "release/<uuidv7:release_id>/remove",
        catalog.remove_release_view,
        name="remove_release",
    ),
)
```

with `from games.views import catalog` at the top.

- [ ] **Step 5: Classify them**

In `games/views/returns.py`, add all six names to `ORIGIN_AWARE`:

```python
("games:add_edition",)
("games:edit_edition",)
("games:remove_edition",)
("games:add_release",)
("games:edit_release",)
("games:remove_release",)
```

- [ ] **Step 6: Run the tests**

Run: `make test ARGS="tests/test_catalog_write_views.py tests/test_returns_classification.py tests/test_paths_return_200.py -x"`
Expected: PASS. If `tests/test_paths_return_200.py` needs a URL sample for a new
route, add one following the file's existing pattern.

- [ ] **Step 7: Commit**

```bash
git add games/views/catalog.py games/urls.py games/views/returns.py tests/
git commit -m "Route an edition and a release to the service that writes them"
```

---

### Task 6: Game detail carries the controls

The spec's boundary: controls, and only for a private Game. #968 left two page
shapes, and each grows differently.

- **Plain shape** (one unnamed Edition, ≤ 1 Release) keeps its two header rows and
  gains one control row below them: *Edit release* (or *Add release*, when the
  Edition holds none) and *Add edition*.
- **The `Releases` section** gains a per-Release Actions column (Edit, Remove), a
  per-Edition control row (Edit edition, Remove edition, Add release), and a
  section-level *Add edition*.
- **A shared Game** gets none of it, and the page still says nothing about why —
  the spec's rule, unchanged from #968.

Hide the affordances the service would refuse, so a person is not offered a button
that answers 409: no *Remove* on the only live Edition, none on a default Edition
that has a live sibling, none on a default Release that has a live sibling.

**Files:**
- Modify: `games/views/game.py` (`_plain_release_rows`, `_release_table`,
  `_edition_block`, `_releases_section`, `_game_header`, `view_game`)
- Test: `tests/test_game_hierarchy_section.py`

**Interfaces:**
- Consumes: the six url names from Task 5; `action_url` and `EditionEntry`.
- Produces: `_catalog_controls_visible(game: Game) -> bool` and the private
  builders `_edition_controls(entry, entries, origin)`,
  `_release_actions(release, entry, origin)` and
  `_add_edition_button(game, origin)`. `_plain_release_rows` takes new
  keyword-only `game: Game` and `origin: OriginUrl | None` and asks
  `_catalog_controls_visible` itself; `_release_table`, `_edition_block` and
  `_releases_section` each take a new `origin: OriginUrl | None` and a
  keyword-only `controls: bool`, and `_releases_section` also takes `game: Game`
  for the section-level Add edition button.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_game_hierarchy_section.py`:

```python
def test_a_plain_game_offers_one_control_row(library, reader):
    game = one_release(library, release_date=TemporalValue.from_year(1984))

    html = reader(game)

    assert "Edit release" in html
    assert "Add edition" in html


def test_a_release_row_offers_edit_and_remove(library, reader):
    game = two_releases(library)
    second = Release.objects.filter(edition__game=game, is_default=False).get()

    html = reader(game)

    assert reverse("games:edit_release", args=[second.pk]) in html
    assert reverse("games:remove_release", args=[second.pk]) in html


def test_the_last_release_of_an_edition_may_go(library, reader):
    """An Edition holding no Release is an ordinary state."""
    game = one_release(library, name="Gold")
    only = Release.objects.get(edition__game=game)

    html = reader(game)

    assert reverse("games:remove_release", args=[only.pk]) in html


def test_a_default_release_with_a_live_sibling_offers_no_removal(library, reader):
    game = two_releases(library)
    default = Release.objects.filter(edition__game=game, is_default=True).get()

    html = reader(game)

    assert reverse("games:remove_release", args=[default.pk]) not in html


def test_the_only_edition_offers_no_removal(library, reader):
    game = one_release(library, name="Gold")
    edition = Edition.objects.get(game=game)

    html = reader(game)

    assert reverse("games:edit_edition", args=[edition.pk]) in html
    assert reverse("games:remove_edition", args=[edition.pk]) not in html


def test_a_non_default_sibling_edition_offers_removal(library, reader):
    game = Game.objects.create(library=library, name="Elite")
    Edition.objects.create(game=game, is_default=True)
    sibling = Edition.objects.create(game=game, name="Gold")

    html = reader(game)

    assert reverse("games:remove_edition", args=[sibling.pk]) in html


def test_a_shared_game_offers_no_control_at_all(client, user, reader):
    shared = Game.objects.create(library=None, name="Shared")
    edition = Edition.objects.create(game=shared, is_default=True)
    Release.objects.create(edition=edition, is_default=True)
    PlayerGame.objects.create(library=user.library, game=shared)

    html = reader(shared)

    assert "Add edition" not in html
    assert reverse("games:add_release", args=[edition.pk]) not in html
```

The last test needs the shared Game tracked, because `view_game` reads through
`Game.objects.tracked_by(library)`. Follow whatever `tests/test_catalog_hierarchy.py`
already does to track one, rather than inventing a second way.

- [ ] **Step 2: Run them and watch them fail**

Run: `make test ARGS="tests/test_game_hierarchy_section.py -x"`
Expected: FAIL — no control markup on the page.

- [ ] **Step 3: Build the controls**

In `games/views/game.py`, beside the existing hierarchy builders:

```python
def _catalog_controls_visible(game: Game) -> bool:
    """A shared Game is read-only for everyone."""
    return game.library_id is not None


def _release_actions(
    release: Release, entry: EditionEntry, origin: OriginUrl | None
) -> Node:
    """Edit always; Remove where the service would allow it."""
    buttons: list[dict[str, object]] = [
        {
            "href": action_url("games:edit_release", release.pk, origin=origin),
            "slot": Icon("edit", size=ICON_BUTTON_SIZE_CLASS),
            "color": "gray",
        }
    ]
    #: A default Release stays while a live sibling could take the
    #: mark. Offering the button would only answer 409.
    holds_the_mark = release.is_default and len(entry.releases) > 1
    if not holds_the_mark:
        buttons.append(
            {
                "href": action_url("games:remove_release", release.pk, origin=origin),
                "slot": Icon("delete", size=ICON_BUTTON_SIZE_CLASS),
                "color": "red",
            }
        )
    return ButtonGroup(buttons)


def _edition_controls(
    entry: EditionEntry, entries: Sequence[EditionEntry], origin: OriginUrl | None
) -> Node:
    edition = entry.edition
    buttons: list[dict[str, object]] = [
        {
            "href": action_url("games:add_release", edition.pk, origin=origin),
            "slot": "Add release",
            "color": "gray",
        },
        {
            "href": action_url("games:edit_edition", edition.pk, origin=origin),
            "slot": "Edit edition",
            "color": "gray",
        },
    ]
    #: The last Edition stays, and so does a default one while a
    #: sibling could take its mark. Together: promote first.
    holds_the_game = len(entries) == 1 or edition.is_default
    if not holds_the_game:
        buttons.append(
            {
                "href": action_url("games:remove_edition", edition.pk, origin=origin),
                "slot": "Remove edition",
                "color": "red",
            }
        )
    return ButtonGroup(buttons)


def _add_edition_button(game: Game, origin: OriginUrl | None) -> Node:
    return ControlButton(
        href=action_url("games:add_edition", game.pk, origin=origin),
        color="gray",
    )["Add edition"]
```

Thread `origin` and `controls` through `_plain_release_rows`, `_release_table`,
`_edition_block` and `_releases_section`, and through `_game_header` into
`view_game`. In the plain shape, append a control row after the two meta rows:

```python
def _plain_release_rows(
    entries: Sequence[EditionEntry],
    presentation: DateTimePresentation,
    *,
    game: Game,
    origin: OriginUrl | None,
) -> list[Node]:
    if not _reads_plainly(entries):
        return []
    release = entries[0].releases[0] if entries and entries[0].releases else None
    rows: list[Node] = [
        _meta_row("Platform", Span(class_=META_VALUE_CLASS)[_platform_words(release)]),
        _meta_row(
            "Released",
            TemporalText(
                None if release is None else release.release_date,
                presentation,
                class_=META_VALUE_CLASS,
            ),
        ),
    ]
    if not _catalog_controls_visible(game):
        return rows
    edition = entries[0].edition if entries else None
    if edition is None:
        return rows
    release_button = (
        {
            "href": action_url("games:edit_release", release.pk, origin=origin),
            "slot": "Edit release",
            "color": "gray",
        }
        if release is not None
        else {
            "href": action_url("games:add_release", edition.pk, origin=origin),
            "slot": "Add release",
            "color": "gray",
        }
    )
    rows.append(
        Div(class_="flex gap-2")[
            ButtonGroup(
                [
                    release_button,
                    {
                        "href": action_url("games:add_edition", game.pk, origin=origin),
                        "slot": "Add edition",
                        "color": "gray",
                    },
                ]
            )
        ]
    )
    return rows
```

Keep the existing early-return guard `_plain_release_rows` already has for the
non-plain shape; the code above states it explicitly so the two shapes never both
render controls.

In `_release_table`, add a third `Column("")` and an actions cell per row, only
when `controls` is true. In `_edition_block`, append `_edition_controls(...)`
below the table, again only when `controls` is true. In `_releases_section`,
append `_add_edition_button(game, origin)` after the Edition blocks. The section
already receives no `game`; pass it.

- [ ] **Step 4: Run the tests**

Run: `make test ARGS="tests/test_game_hierarchy_section.py tests/test_action_origin_parity.py -x"`
Expected: PASS. `tests/test_action_origin_parity.py` is the one that catches a
`reverse()` where an `action_url()` belonged.

- [ ] **Step 5: Commit**

```bash
git add games/views/game.py tests/test_game_hierarchy_section.py
git commit -m "Let a private game's page reach its own editions and releases"
```

---

### Task 7: A browser adds an Edition and a Release

The synthetic harness in `e2e/test_temporal_field_e2e.py` says "No page hosts one
until #969." Now one does, so prove the element works where a person meets it.

**Files:**
- Create: `e2e/test_catalog_management_e2e.py`
- Modify: `e2e/test_temporal_field_e2e.py` (the "no page hosts one" comment)

**Interfaces:**
- Consumes: the routes from Task 5 and the controls from Task 6.
- Produces: nothing other tasks read.

- [ ] **Step 1: Write the test**

Follow `e2e/test_temporal_field_e2e.py` for the fixtures and the login helper.

```python
"""Adding an edition and a release, in a browser."""

import pytest

from games.models import Edition, Game, Release

pytestmark = pytest.mark.django_db(transaction=True)


def test_a_person_adds_an_edition_from_the_game_page(page, live_server, signed_in):
    game = Game.objects.create(library=signed_in.library, name="Elite")
    Edition.objects.create(game=game, is_default=True)

    page.goto(f"{live_server.url}{game.get_absolute_url()}")
    page.get_by_role("link", name="Add edition").click()
    page.fill("#id_name", "Gold")
    page.get_by_role("button", name="Submit").click()

    #: Server-rendered, thus the write has committed.
    page.wait_for_selector("text=Gold")
    assert Edition.objects.filter(game=game, name="Gold").exists()


def test_the_release_form_hosts_a_working_temporal_field(page, live_server, signed_in):
    game = Game.objects.create(library=signed_in.library, name="Elite")
    edition = Edition.objects.create(game=game, is_default=True)

    page.goto(f"{live_server.url}/edition/{edition.pk}/release/add")
    #: The element enhances the native controls; if the module never
    #: loaded, the number inputs stay visible and this fails.
    page.wait_for_selector("temporal-field")
    page.fill("#id_release_date-lower-year", "1984")
    page.get_by_role("button", name="Submit").click()

    page.wait_for_selector("text=1984")
    release = Release.objects.get(edition=edition)
    assert release.release_date.year == 1984
```

Confirm the real input ids with
`grep -n "temporal_input_name\|input_id" common/components/temporal_field.py`
before writing the selectors; the suffixes come from `TEMPORAL_INPUT_SUFFIXES`.

- [ ] **Step 2: Run it**

Run: `make ts && make test-e2e ARGS="-k catalog_management"`
Expected: PASS. If Chrome is not found, set `E2E_CHROME`.

- [ ] **Step 3: Update the harness comment**

In `e2e/test_temporal_field_e2e.py`, replace "No page hosts one until #969" with a
pointer to the real page, and keep the synthetic harness — it covers the grammar's
edges that the release form does not exercise.

- [ ] **Step 4: Commit**

```bash
git add e2e/
git commit -m "Add an edition and a release in a real browser"
```

---

### Task 8: Documentation, and the deferrals on the record

Issue comment 2 asks for `docs/temporal.md` to be written **here, once** — the
whole temporal wave (#962–#965, #969) has left notes scattered across specs, and
this is the issue that finishes it.

**Files:**
- Create: `docs/temporal.md`
- Modify: `docs/catalog.md`, `CLAUDE.md`, the #969 spec
- Modify (via `gh`): issue #969 and the catalog epic

**Interfaces:** none.

- [ ] **Step 1: Write `docs/temporal.md`**

One page, ASD-STE100 plain, covering exactly these six things and nothing else:

1. **The grammar.** What a stored value may say: a year, a month, a day, a decade,
   a range with a precision per endpoint, an open start, and a qualifier per
   endpoint. The words come from `timetracker/temporal.py`.
2. **Where a value is refused.** `TemporalValueParseError` and its codes; a
   refused draft re-renders the characters a person typed, because
   `TemporalWidget.value_from_datadict` returns raw text rather than a parsed
   draft.
3. **The one-way precision rule.** A stored value is never widened by a form that
   cannot say what it holds. This is why #969 deleted `_reconcile_year`: the
   reliable answer is to give the form the same grammar as the column, not to
   guess when the integer disagrees.
4. **The wire.** `temporal_input_name(name, key)` and the draft keys; one field
   name yields several inputs; two temporal fields on one page must have distinct
   field names (Add Game has `original_release_date` and `release_date`).
5. **The no-script contract.** The whole value round-trips with scripting off.
   `<temporal-field>` only enhances: it hides number inputs for a segmented date,
   folds the disclosure, and offers the whole-decade and open-start boxes. Nothing
   it does is required to save a value. Node ≥ 26, because it uses `Temporal`.
6. **Hosting one.** A widget renders to text, so `Media` never bubbles: the view
   threads `scripts=ModuleScript("dist/elements/temporal-field.js")`. Name
   `games/views/game.py` and `games/views/catalog.py` as the pages that do.

Cross-link the `search_path` note in `docs/deployment.md` where the storage
representation is discussed, as comment 2 asks.

- [ ] **Step 2: Update `docs/catalog.md`**

Three edits:

- Under **What Game detail shows**, replace "#969 adds controls, and only for a
  private Game" with what the page now offers, and state the two rules that hide a
  button: the last Edition and a default with a live sibling.
- Add a **What a form refuses that the service does not** section: the
  unnamed-sibling rule, and why the service stays permissive (#782's importer
  writes unnamed Editions in bulk).
- Replace **The legacy Game form** entirely. The reconciliation is gone. Describe
  the mirror instead: the three columns follow the default Edition's default
  Release, `mirror_legacy_columns` writes them, `write_and_mirror` wraps every
  catalog write, and the pre-check exists because those columns still carry a
  unique constraint. End with "#889 retires this path", as it does now.

- [ ] **Step 3: Update `CLAUDE.md`**

Two lines in **Conventions for AI assistants**:

- Extend the existing catalog-service bullet: a form that writes an Edition or a
  Release calls `EditionForm`/`ReleaseForm`, which call the verbs; a view calls
  `write_and_mirror` so the legacy columns follow.
- In the `temporal_field.py` paragraph, replace "#969 is the first page that hosts
  one" with the two pages that do, and point at `docs/temporal.md`.

- [ ] **Step 4: Amend the spec with the two calls this plan made**

Add a short **Amendments** section at the end of
`docs/superpowers/specs/2026-08-30-issue-969-private-catalog-management-design.md`
recording both departures from the spec's literal words — the
`original_year_released` replacement (comment 1's option 2) and the legacy mirror
with its pre-check — and why each was taken. A spec that quietly disagrees with
its implementation is worse than one that says where it changed.

- [ ] **Step 5: Record the two deferral verdicts**

Comment 3 (a mark on a shared Game saying who may change it) and comment 4's
service-level variant both end in "not yet". Write each verdict into issue #969
**and** the catalog epic, not only into this plan:

```bash
gh issue comment 969 --repo KucharczykL/timetracker --body "..."
```

- **Shared-Game mark: nothing, for now.** Controls are simply absent for a shared
  Game, with no mark and no sentence. What sharing means is unsettled until the
  IGDB wave (#783/#784/#785) lands; a mark written now would describe a rule that
  does not exist yet.
- **The unnamed-sibling rule lives in the form, not the service.** #782's importer
  writes unnamed Editions in bulk and must keep being able to. If a second writer
  ever needs the rule, it moves down then.

- [ ] **Step 6: Lint the prose and commit**

Run: `make vale`
Expected: no errors. A warning is allowed; an error is not.

```bash
git add docs/ CLAUDE.md
git commit -m "Write down the temporal layer, once"
```

---

### Task 9: The gate

- [ ] **Step 1: Run the full check**

Run: `make check`
Expected: green — lint, format-check, mypy, vale, ts-check, vitest, and the entire
pytest suite **including `e2e/`**. Never verify with a hand-picked subset.

- [ ] **Step 2: Look for readers of the flat columns that the mirror missed**

Run: `grep -rn "year_released\|original_year_released" games/ common/ tests/ e2e/ --include=*.py | grep -v migrations`

Every remaining reader should be either a filter, the API, the fixture, or a test
of the mirror itself. A reader that renders a Game page is a bug — #968 took those
out. Fix anything that surfaced.

- [ ] **Step 3: Regenerate nothing**

`make loadsample` still works: the fixture carries the flat columns and the graph
alike, and the mirror writes columns rather than reading them. Confirm with
`make loadsample` against a scratch database if one is handy; do not regenerate
`sample.yaml.gz`.

- [ ] **Step 4: Commit and open the PR**

```bash
git add -A
git commit -m "Manage private editions and releases"
gh pr create --repo KucharczykL/timetracker --fill
```

---

## Self-review notes

**Spec coverage.** Every section of the spec maps to a task: the route table →
Task 5; "The forms" → Tasks 3 and 4; "The Game form gives up two fields" → Task 3
(with the amendment above); "Add Game keeps one inline Release row" → Task 3;
"The original release date stays on the Game form" → Task 3; Isolation → Task 5's
shared-Game and other-library tests; Tests → Tasks 1–7; Boundary → nothing here
adds a Release selector, a Catalogue page, IGDB, product relationships, or drops a
legacy column.

**Issue comments.** Comment 1 → Task 3 plus the amendment. Comment 2 → Task 8
Step 1. Comment 3 → Task 8 Step 5, as a recorded deferral. Comment 4 → Task 4's
`UNNAMED_SIBLING_EDITION` plus Task 8 Step 5.

**Known risk.** The mirror's pre-check races: two concurrent writes can both pass
it and the second gets an `IntegrityError`. This is acceptable for a
single-writer-per-library app and disappears with #889. If it turns out to bite,
the fix is a `select_for_update` on the sibling row, not a broader lock.
