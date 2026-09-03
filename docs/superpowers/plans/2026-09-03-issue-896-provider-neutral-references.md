# Provider-neutral external references Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One section on the Game and Platform forms states every external
reference a record holds, every surface shows those references as safe links,
and a removed row lets go of the provider key it claimed (#976).

**Architecture:** `PROVIDER_POLICIES` in `games/external_references.py` becomes
the single registry that drives storage, validation, links and form fields, so
a new provider is one entry and no UI change. `ExternalReference` gains a
`removed_at` that `games/removal.py` stamps alongside its target's, which makes
every uniqueness constraint on the table conditional. A new
`state_external_references()` states one target's whole desired set in one
transaction, the way `state_catalog_graph()` states a graph, and
`Game.wikidata` inverts from source to mirror.

**Tech Stack:** Django 6, PostgreSQL 18, Python 3.14, pytest + pytest-xdist,
Playwright for e2e, the project's Python component system
(`common/components/`). No new dependency, no new custom element, no new route.

**Spec:** `docs/superpowers/specs/2026-09-03-issue-896-provider-neutral-references-design.md`

## Global Constraints

- **Every command goes through `make`.** `make test ARGS="tests/test_x.py -k y"`
  for a focused run, `make check-fast` while iterating, the full `make check`
  before declaring done. Never `uv run pytest` directly, never `direnv exec .`.
- **Python 3.14.** If `except A, B:` raises a `SyntaxError`, the interpreter is
  wrong, not the code.
- **Nothing destroys a record.** Call `remove()`/`restore()` from
  `games/removal.py`. Never `instance.delete()` on a catalog row. The one
  exception this plan removes is `sync_game_wikidata()`, which calls
  `reference.delete()` today and is deleted itself in Task 5.
- **Nothing opens a server-side cursor.** Never `QuerySet.iterator()`. Page with
  `keyset_pages()` from `common/keyset.py`, keyed on fields in one index, last
  field unique. `tests/test_iterator_guard.py` walks the syntax tree and fails
  on a new call.
- **No dispatch inside a transaction.** `run_in_transaction` refuses to nest. A
  view that dispatches a command carries no `@transaction.atomic`. A test that
  POSTs through such a view needs `@pytest.mark.django_db(transaction=True)`.
- **Refused words.** `make vale` fails on `delete`/`archive`/`tombstone`/`fold`
  next to a record noun, in prose and in comments. Write `remove` for the act,
  `removed row` for the result. Code identifiers are out of scope.
- **Name variables with complete words** — `reference` not `ref`, `element` not
  `el`, `provider_key` not `key` where both exist in scope.
- **Build UI with Python components** from `common.components`. Never raw HTML
  strings. Builders take htpy form: `Div(class_="x")[child]`.
- **A widget renders to text, so its `Media` never bubbles** — a view hosting one
  threads `scripts=ModuleScript(...)`. This plan adds no widget with JS, so no
  view gains a script.
- **Provider-neutral means the registry decides.** After this plan, no form, no
  renderer and no view may contain the literal `wikidata`. Only
  `games/external_references.py`, `games/models.py` (two check constraints), the
  migrations, the mirror, and the filter/sort entries that #889 owns may.
- **The exact Wikidata link is** `https://www.wikidata.org/wiki/{provider_key}`,
  so `Q123` resolves to `https://www.wikidata.org/wiki/Q123`.

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `games/migrations/0041_external_reference_marks.py` | The `removed_at` column, its backfill, the one-per-provider resolution, and the five constraints. |
| `games/reference_form.py` | `ReferenceSetForm` — one key field per registered provider, plus the shared two-form submit helper both hosting views use. |
| `games/views/reference_section.py` | Renders the External references area for a hosting form. |
| `games/reads/external_references.py` | `references_for()` — the live references of a batch of rows, in one query per kind. |
| `tests/test_reference_form.py` | The form's fields, sentences and both hosting submits. |
| `tests/test_reference_removal.py` | #976 end to end, plus the restore rule and the race. |
| `tests/test_reference_presentation.py` | The link component and the three read-only surfaces. |
| `e2e/test_external_references_e2e.py` | Add, change and clear a key through a real browser. |

**Modified:**

| Path | Change |
|---|---|
| `games/models.py:694-800` | `removed_at`, the conditional tuple constraint, four per-provider constraints. |
| `games/external_references.py` | `label`/`hint` on the policy, live-only lookup, `state_external_references()`, `mirror_game_wikidata()` replacing `sync_game_wikidata()`. |
| `games/removal.py:56-77` | `_AFTER_STAMP` values become tuples; four reference hooks; the mirror hook on Game. |
| `games/forms.py:986-1027` | `GameForm` loses `wikidata`, `clean_wikidata()` and the `Meta.fields` entry. |
| `games/catalog_submit.py` | Writes the reference set in the same transaction; answers its refusals through the set form. |
| `games/views/game.py` | Hosts the area on Add and Edit Game; a References metadata row and an Editions column on detail. |
| `games/views/platform.py` | Hosts the area on Add and Edit Platform; a References column on the list. |
| `common/components/domain.py` | `ExternalReferenceLinks()`. |
| `docs/catalog.md` | An External references section. |
| `docs/event-retention.md` | The cross-reference for the new conditional constraints. |
| `tests/test_external_references.py` | The mark, the constraints, the set writer, the mirror. |
| `tests/test_catalog_submit.py` | The guard entries and the moved Wikidata cases. |

---

### Task 1: The mark on a reference, and the constraints that read it

**Files:**
- Modify: `games/models.py:694-800`
- Create: `games/migrations/0041_external_reference_marks.py`
- Modify: `games/catalog_submit.py:54-60`
- Test: `tests/test_external_references.py`, `tests/test_catalog_submit.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ExternalReference.removed_at` (`DateTimeField`, `null=True`,
  `default=None`, `editable=False`); the constraint names
  `unique_external_reference_provider_kind_key` (now conditional),
  `unique_live_game_reference_per_provider`,
  `unique_live_edition_reference_per_provider`,
  `unique_live_release_reference_per_provider`,
  `unique_live_platform_reference_per_provider`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_external_references.py`:

```python
def test_a_marked_reference_lets_go_of_its_provider_key(owned_library):
    """#976: a removed row does not hold a key against a later entry."""
    first = Game.objects.create(name="Elite", library=owned_library)
    second = Game.objects.create(name="Elite II", library=owned_library)
    reference = ExternalReference.objects.create(
        provider="wikidata", entity_kind="game", provider_key="Q123", game=first
    )
    ExternalReference.objects.filter(pk=reference.pk).update(removed_at=now())

    taken = ExternalReference.objects.create(
        provider="wikidata", entity_kind="game", provider_key="Q123", game=second
    )

    assert taken.pk != reference.pk


def test_two_live_references_of_one_tuple_are_refused(owned_library):
    first = Game.objects.create(name="Elite", library=owned_library)
    second = Game.objects.create(name="Elite II", library=owned_library)
    ExternalReference.objects.create(
        provider="wikidata", entity_kind="game", provider_key="Q123", game=first
    )

    with pytest.raises(IntegrityError):
        ExternalReference.objects.create(
            provider="wikidata", entity_kind="game", provider_key="Q123", game=second
        )


def test_one_live_key_per_record_per_provider(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    ExternalReference.objects.create(
        provider="wikidata", entity_kind="game", provider_key="Q123", game=game
    )

    with pytest.raises(IntegrityError):
        ExternalReference.objects.create(
            provider="wikidata", entity_kind="game", provider_key="Q124", game=game
        )


def test_a_marked_key_frees_the_record_for_another(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    first = ExternalReference.objects.create(
        provider="wikidata", entity_kind="game", provider_key="Q123", game=game
    )
    ExternalReference.objects.filter(pk=first.pk).update(removed_at=now())

    second = ExternalReference.objects.create(
        provider="wikidata", entity_kind="game", provider_key="Q124", game=game
    )

    assert second.pk != first.pk
```

Each new test needs `from django.utils.timezone import now` and
`from django.db import IntegrityError` at the top of the module if absent, and
runs under the module's existing `pytestmark`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_external_references.py -k 'marked or one_live or two_live' -x"`

Expected: FAIL. The first with `django.db.utils.IntegrityError: duplicate key
value violates unique constraint
"unique_external_reference_provider_kind_key"`; the two `one_live` cases with
`Failed: DID NOT RAISE`.

- [ ] **Step 3: Add the column and the constraints to the model**

In `games/models.py`, inside `class ExternalReference`, replace the `Meta.constraints`
tuple's first element and append four more. The finished `Meta` reads:

```text
class Meta:
    constraints = (
        #: A removed row holds no slot, as every other
        #: conditional constraint here states (#976).
        UniqueConstraint(
            fields=("provider", "entity_kind", "provider_key"),
            condition=Q(removed_at__isnull=True),
            name="unique_external_reference_provider_kind_key",
        ),
        ... the two existing CheckConstraints and the kind/target one, unchanged ...
        #: A provider issues one identity per record. Four rather
        #: than one constraint over five columns: the kind/target
        #: check above enumerates the same four, and a reader who
        #: has met that one needs no note about null handling.
        UniqueConstraint(
            fields=("provider", "game"),
            condition=Q(game__isnull=False) & Q(removed_at__isnull=True),
            name="unique_live_game_reference_per_provider",
        ),
        UniqueConstraint(
            fields=("provider", "edition"),
            condition=Q(edition__isnull=False) & Q(removed_at__isnull=True),
            name="unique_live_edition_reference_per_provider",
        ),
        UniqueConstraint(
            fields=("provider", "release"),
            condition=Q(release__isnull=False) & Q(removed_at__isnull=True),
            name="unique_live_release_reference_per_provider",
        ),
        UniqueConstraint(
            fields=("provider", "platform"),
            condition=Q(platform__isnull=False) & Q(removed_at__isnull=True),
            name="unique_live_platform_reference_per_provider",
        ),
    )
```

and beside the four target foreign keys add the column, worded exactly as the
nine removable models word theirs:

```text
#: Set instead of destroying the row. Derived: it follows
#: the row this reference names, and `games/removal.py`
#: writes it. ExternalReference is not in REMOVABLE_MODELS.
removed_at = models.DateTimeField(
    null=True, blank=True, default=None, editable=False
)
```

- [ ] **Step 4: Generate the migration and write its data step**

Run: `make makemigrations ARGS="games --name external_reference_marks"`

Then open the generated `games/migrations/0041_external_reference_marks.py` and
insert a `RunPython` between the `AddField` and the `AddConstraint`/
`RemoveConstraint` operations. Reorder the operations so they run: `AddField`,
`RunPython`, `RemoveConstraint` (the old tuple constraint), `AddConstraint`
(the conditional tuple constraint), then the four new `AddConstraint`s.

The data step, in the same file, above `class Migration`:

```text
BATCH_SIZE = 500


def _mark_references_of_removed_rows(apps, schema_editor):
    """A removed row lets go of the key it claimed (#976)."""
    from django.utils.timezone import now

    ExternalReference = apps.get_model("games", "ExternalReference")
    stamped = now()
    for kind, path in (
        ("game", "game__removed_at__isnull"),
        ("edition", "edition__removed_at__isnull"),
        ("release", "release__removed_at__isnull"),
        ("platform", "platform__removed_at__isnull"),
    ):
        ExternalReference.objects.filter(
            entity_kind=kind, removed_at__isnull=True, **{path: False}
        ).update(removed_at=stamped)


def _keep_one_key_per_record(apps, schema_editor):
    """Resolve a record that already holds two keys of one provider.

    Nothing should be found: `sync_game_wikidata` has been removing
    the extras and only a direct service call could make one. It
    runs because a migration that assumes a shape it can check is a
    migration that fails on the one database that broke it.
    """
    from django.utils.timezone import now

    ExternalReference = apps.get_model("games", "ExternalReference")
    Game = apps.get_model("games", "Game")
    stamped = now()
    columns = {
        "game": "game_id",
        "edition": "edition_id",
        "release": "release_id",
        "platform": "platform_id",
    }
    mirrored = dict(
        Game.objects.exclude(wikidata="").values_list("id", "wikidata")
    )
    for kind, column in columns.items():
        held: dict[tuple[str, object], object] = {}
        rows = ExternalReference.objects.filter(
            entity_kind=kind, removed_at__isnull=True
        ).order_by("provider", column, "id")
        for reference in _paged(rows):
            target = getattr(reference, column)
            slot = (reference.provider, target)
            incumbent = held.get(slot)
            if incumbent is None:
                held[slot] = reference
                continue
            keeper = _keeper(kind, incumbent, reference, mirrored)
            loser = reference if keeper is incumbent else incumbent
            held[slot] = keeper
            ExternalReference.objects.filter(pk=loser.pk).update(
                removed_at=stamped
            )


def _keeper(kind, incumbent, candidate, mirrored):
    """The row that stays: the mirrored key, else the earliest id."""
    if kind == "game":
        wanted = mirrored.get(incumbent.game_id)
        if wanted is not None:
            if candidate.provider_key == wanted:
                return candidate
            if incumbent.provider_key == wanted:
                return incumbent
    return incumbent if incumbent.id <= candidate.id else candidate


def _paged(queryset):
    """Page a historical queryset; never `iterator()`."""
    last = None
    while True:
        page = queryset if last is None else queryset.filter(id__gt=last)
        rows = list(page[:BATCH_SIZE])
        if not rows:
            return
        yield from rows
        if len(rows) < BATCH_SIZE:
            return
        last = rows[-1].id
```

`_paged` is local rather than `keyset_pages()` because a migration reads a
historical model and `common/keyset.py` types against the live one. It is the
same shape and opens no cursor. Both `RunPython` calls take
`migrations.RunPython.noop` as their reverse: reversing drops the constraints
and the column, so a mark has nowhere to live and nothing to undo.

- [ ] **Step 5: Add the four guard entries**

In `games/catalog_submit.py`, extend `UNREACHABLE_FROM_THE_GAME_FORM`:

```text
"unique_live_game_reference_per_provider": (
    "`ReferenceSetForm` holds one field per provider, thus a post "
    "cannot state two keys for one. `state_external_references` "
    "refuses a second live row before the database sees it."
),
```

and the same sentence, with the kind changed, for
`unique_live_edition_reference_per_provider`,
`unique_live_release_reference_per_provider` and
`unique_live_platform_reference_per_provider`.

- [ ] **Step 6: Run the tests**

Run: `make test ARGS="tests/test_external_references.py tests/test_catalog_submit.py tests/test_external_reference_migration.py"`

Expected: PASS, including
`test_every_unique_constraint_the_form_can_reach_is_mapped`.

- [ ] **Step 7: Prove the migration is reversible**

Run: `make migrate ARGS="games 0040_edition_name"` then
`make migrate ARGS="games 0041_external_reference_marks"`

Expected: both directions apply with no error.

- [ ] **Step 8: Commit**

```bash
git add games/models.py games/migrations/0041_external_reference_marks.py \
        games/catalog_submit.py tests/test_external_references.py
git commit -m "Let a removed row let go of its provider key"
```

---

### Task 2: A stamp reaches the references of the row it takes out

**Files:**
- Modify: `games/removal.py:42-87`
- Test: `tests/test_reference_removal.py` (create)

**Interfaces:**
- Consumes: `ExternalReference.removed_at` from Task 1.
- Produces: `_AFTER_STAMP: dict[type[Model], tuple[Callable[[Any], None], ...]]`
  — the values are now tuples run in order. `games/removal.py` exports no new
  public name; `remove()` and `restore()` keep their signatures.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reference_removal.py`:

```python
"""What a removal does to the keys a row claimed (#976)."""

import pytest
from django.db import IntegrityError

from games.models import ExternalReference, Game, Platform
from games.removal import remove, restore

pytestmark = pytest.mark.django_db


def _reference(game, provider_key):
    return ExternalReference.objects.create(
        provider="wikidata",
        entity_kind="game",
        provider_key=provider_key,
        game=game,
    )


def test_removing_a_game_marks_the_references_it_holds(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    reference = _reference(game, "Q123")

    remove(game)

    reference.refresh_from_db()
    assert reference.removed_at is not None


def test_a_second_game_may_take_the_key_a_removed_game_held(owned_library):
    first = Game.objects.create(name="Elite", library=owned_library)
    _reference(first, "Q123")
    remove(first)

    second = Game.objects.create(name="Elite II", library=owned_library)
    taken = _reference(second, "Q123")

    assert taken.game_id == second.pk


def test_restoring_a_game_takes_back_a_key_that_is_free(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    reference = _reference(game, "Q123")
    remove(game)

    restore(game)

    reference.refresh_from_db()
    assert reference.removed_at is None


def test_restoring_leaves_a_key_another_record_has_taken(owned_library):
    first = Game.objects.create(name="Elite", library=owned_library)
    reference = _reference(first, "Q123")
    remove(first)
    second = Game.objects.create(name="Elite II", library=owned_library)
    _reference(second, "Q123")

    restore(first)

    reference.refresh_from_db()
    first.refresh_from_db()
    assert first.removed_at is None
    assert reference.removed_at is not None


def test_a_removed_platform_lets_go_of_its_key(owned_library):
    platform = Platform.objects.create(name="Amiga", library=owned_library)
    reference = ExternalReference.objects.create(
        provider="wikidata",
        entity_kind="platform",
        provider_key="Q100047",
        platform=platform,
    )

    remove(platform)

    reference.refresh_from_db()
    assert reference.removed_at is not None


def test_a_live_release_under_a_removed_game_keeps_its_key(owned_library, stated_graph):
    """Only the row a person removed lets go.

    A Game's mark hides its children without stamping them, thus
    their references are not stamped either, and a restore brings
    the whole subtree back unchanged.
    """
    game, edition, release = stated_graph(
        Game(name="Elite", library=owned_library), owned_library
    )
    reference = ExternalReference.objects.create(
        provider="wikidata",
        entity_kind="release",
        provider_key="Q999",
        release=release,
    )

    remove(game)

    reference.refresh_from_db()
    assert reference.removed_at is None

    with pytest.raises(IntegrityError):
        second = Game.objects.create(name="Other", library=owned_library)
        ExternalReference.objects.create(
            provider="wikidata",
            entity_kind="game",
            provider_key="Q999",
            game=second,
        )
```

`stated_graph` is the fixture in `tests/conftest.py`: it takes an unsaved Game
and its library, and returns a `DefaultGraph(game, edition, release)`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_reference_removal.py -x"`

Expected: FAIL on the first test with `assert None is not None`.

- [ ] **Step 3: Write the hooks**

In `games/removal.py`, add above `_AFTER_STAMP`:

```text
def _mark_the_references_of(instance: Model) -> None:
    """A reference follows the row it names.

    A removal stamps every reference of the row. A restore takes
    back only the keys no live row holds: re-claiming one would
    repeat the theft in the other direction, and raising would
    surface as a traceback, because restore() has no error channel
    until #695 and #795 give it one.
    """
    from games.models import ExternalReference

    column = ExternalReference.TARGET_FIELDS_BY_MODEL[type(instance)]
    held = ExternalReference.objects.filter(**{column: instance.pk})
    stamp = instance.removed_at  # type: ignore[attr-defined]
    if stamp is not None:
        held.filter(removed_at__isnull=True).update(removed_at=stamp)
        return
    free = ~Exists(
        ExternalReference.objects.filter(
            provider=OuterRef("provider"),
            entity_kind=OuterRef("entity_kind"),
            provider_key=OuterRef("provider_key"),
            removed_at__isnull=True,
        )
    )
    held.filter(removed_at__isnull=False).filter(free).update(removed_at=None)
```

`TARGET_FIELDS_BY_MODEL` is a new `ClassVar` on `ExternalReference`, beside the
existing `TARGET_FIELDS`, mapping the four model classes to `"game_id"`,
`"edition_id"`, `"release_id"`, `"platform_id"`. All four classes are defined
above `ExternalReference` in `games/models.py`, so a plain `ClassVar` dict
works.

**Two mappings, two conventions.** `TARGET_FIELDS_BY_MODEL` is keyed on the
model class and yields the `_id` attribute, because its callers hold a row and
want its primary key. `_target_metadata()` in `games/external_references.py`
yields the relation name (`"game"`), because its callers assign the object.
Keep them apart, and read which one a snippet uses before copying a lookup
between tasks.

Import `Exists` and `OuterRef` from `django.db.models` at the top of
`games/removal.py`.

Then change `_AFTER_STAMP` and `_stamp`:

```text
#: What a stamp does not do. Values run in order.
_AFTER_STAMP: dict[type[Model], tuple[Callable[[Any], None], ...]] = {
    Game: (_mark_the_references_of, _recount_purchases),
    Edition: (_mark_the_references_of,),
    Release: (_mark_the_references_of,),
    Platform: (_mark_the_references_of,),
    Session: (_recalculate_the_games_playtime,),
}
```

and in `_stamp`, replace the two closing lines with:

```text
for after in _AFTER_STAMP.get(model, ()):
    after(instance)
```

- [ ] **Step 4: Run the tests**

Run: `make test ARGS="tests/test_reference_removal.py tests/test_removable_models.py"`

Expected: PASS. `test_removable_models.py` must stay green — `ExternalReference`
is deliberately not in `REMOVABLE_MODELS` and that file's builder guard should
not ask for one.

- [ ] **Step 5: Commit**

```bash
git add games/removal.py games/models.py tests/test_reference_removal.py
git commit -m "Let a reference follow the row it names"
```

---

### Task 3: The policy grows a face

**Files:**
- Modify: `games/external_references.py:23-55`
- Modify: `games/models.py` (the `Provider` choices comment)
- Test: `tests/test_external_references.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ProviderPolicy(normalize_key, url_template, label, hint)` —
  `label: str` and `hint: str` are new required fields;
  `provider_labels() -> dict[str, str]` mapping provider slug to label, in
  registry order.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_external_references.py`:

```python
def test_every_registered_policy_states_a_label_and_a_hint():
    """A provider is one registry entry, UI included."""
    for provider, policy in PROVIDER_POLICIES.items():
        assert policy.label, provider
        assert policy.hint, provider


def test_the_wikidata_policy_reads_as_a_person_would_say_it():
    assert PROVIDER_POLICIES["wikidata"].label == "Wikidata"
    assert "Q123" in PROVIDER_POLICIES["wikidata"].hint


def test_provider_labels_are_the_registry_in_order():
    assert provider_labels() == {"wikidata": "Wikidata"}
```

Add `PROVIDER_POLICIES` and `provider_labels` to the module's import list in
the test file.

- [ ] **Step 2: Run the test to verify it fails**

Run: `make test ARGS="tests/test_external_references.py -k policy_states or labels -x"`

Expected: FAIL with `AttributeError: 'ProviderPolicy' object has no attribute
'label'` and `ImportError: cannot import name 'provider_labels'`.

- [ ] **Step 3: Extend the policy**

In `games/external_references.py`:

```text
@dataclass(frozen=True, slots=True)
class ProviderPolicy:
    """What a provider states, and how it reads.

    The one entry a provider needs. A form field, its label, its
    help text and its link all come from here, thus registering a
    policy is the whole UI cost of a provider.
    """

    normalize_key: Callable[[str], str]
    url_template: str
    label: str
    hint: str


PROVIDER_POLICIES = {
    "wikidata": ProviderPolicy(
        normalize_key=_normalize_wikidata_key,
        url_template="https://www.wikidata.org/wiki/{provider_key}",
        label="Wikidata",
        hint="An entity ID such as Q123.",
    ),
}


def provider_labels() -> dict[str, str]:
    """Every registered provider, under the words a person reads."""
    return {
        provider: policy.label for provider, policy in PROVIDER_POLICIES.items()
    }
```

In `games/models.py`, add a comment above `class Provider(models.TextChoices)`:

```text
#: The database's own words. The human label a screen reads
#: comes from PROVIDER_POLICIES, because a provider that
#: names itself twice can name itself two ways.
```

- [ ] **Step 4: Run the tests**

Run: `make test ARGS="tests/test_external_references.py"`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/external_references.py games/models.py \
        tests/test_external_references.py
git commit -m "Let a provider policy say how it reads"
```

---

### Task 4: One call states a record's whole set of references

**Files:**
- Modify: `games/external_references.py`
- Test: `tests/test_external_references.py`

**Interfaces:**
- Consumes: the mark (Task 1), `provider_labels()` (Task 3).
- Produces:
  - `class ReferencesRefused(ValidationError)` with `.provider: str | None`;
  - `SHARED_TARGET`, `OTHER_LIBRARY_TARGET`, `REMOVED_TARGET`, `KEY_TAKEN` —
    module-level sentence constants;
  - `state_external_references(*, target: CatalogTarget, library: UserLibrary,
    keys: Mapping[str, str]) -> None` — states the whole desired set for the
    providers `keys` names, in one transaction.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_external_references.py`:

```python
def test_stating_a_key_creates_the_reference(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)

    state_external_references(
        target=game, library=owned_library, keys={"wikidata": " q123 "}
    )

    reference = ExternalReference.objects.get(game=game, removed_at=None)
    assert reference.provider_key == "Q123"


def test_stating_a_blank_key_marks_the_reference(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )

    state_external_references(target=game, library=owned_library, keys={"wikidata": ""})

    assert not ExternalReference.objects.filter(game=game, removed_at=None).exists()
    assert ExternalReference.objects.filter(game=game).exists()


def test_stating_a_new_key_replaces_the_old_one(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )

    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q124"}
    )

    live = ExternalReference.objects.get(game=game, removed_at=None)
    assert live.provider_key == "Q124"


def test_a_provider_the_caller_does_not_name_is_left_alone(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )

    state_external_references(target=game, library=owned_library, keys={})

    assert ExternalReference.objects.filter(game=game, removed_at=None).exists()


def test_a_key_another_record_holds_is_refused(owned_library):
    first = Game.objects.create(name="Elite", library=owned_library)
    second = Game.objects.create(name="Elite II", library=owned_library)
    state_external_references(
        target=first, library=owned_library, keys={"wikidata": "Q123"}
    )

    with pytest.raises(ReferencesRefused) as refusal:
        state_external_references(
            target=second, library=owned_library, keys={"wikidata": "Q123"}
        )

    assert refusal.value.provider == "wikidata"
    assert refusal.value.messages[0] == KEY_TAKEN
    assert (
        ExternalReference.objects.get(provider_key="Q123", removed_at=None).game_id
        == first.pk
    )


def test_a_shared_target_is_refused(owned_library):
    shared = Game.objects.create(name="Elite", library=None)

    with pytest.raises(ReferencesRefused) as refusal:
        state_external_references(
            target=shared, library=owned_library, keys={"wikidata": "Q123"}
        )

    assert refusal.value.messages[0] == SHARED_TARGET


def test_another_librarys_target_is_refused(owned_library, django_user_model):
    other = django_user_model.objects.create_user(
        username="other", password="p"
    ).library
    theirs = Game.objects.create(name="Elite", library=other)

    with pytest.raises(ReferencesRefused) as refusal:
        state_external_references(
            target=theirs, library=owned_library, keys={"wikidata": "Q123"}
        )

    assert refusal.value.messages[0] == OTHER_LIBRARY_TARGET


def test_a_removed_target_is_refused(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    remove(game)

    with pytest.raises(ReferencesRefused) as refusal:
        state_external_references(
            target=game, library=owned_library, keys={"wikidata": "Q123"}
        )

    assert refusal.value.messages[0] == REMOVED_TARGET


def test_a_malformed_key_is_refused_under_its_provider(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)

    with pytest.raises(ReferencesRefused) as refusal:
        state_external_references(
            target=game, library=owned_library, keys={"wikidata": "banana"}
        )

    assert refusal.value.provider == "wikidata"
    assert "Q123" in refusal.value.messages[0]


def test_nothing_is_written_when_one_provider_is_refused(owned_library):
    """Every refusal is read before anything is written."""
    game = Game.objects.create(name="Elite", library=owned_library)

    with pytest.raises(ReferencesRefused):
        state_external_references(
            target=game, library=owned_library, keys={"wikidata": "banana"}
        )

    assert not ExternalReference.objects.filter(game=game).exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_external_references.py -k state_ or stating_ -x"`

Expected: FAIL with `ImportError: cannot import name
'state_external_references'`.

- [ ] **Step 3: Write the writer**

In `games/external_references.py`, add the sentences and the refusal:

```text
#: A shared row is read-only for everyone, and what sharing means
#: is unsettled until the IGDB wave (#783, #784, #785) lands.
SHARED_TARGET = "A shared record's references cannot be changed here."
OTHER_LIBRARY_TARGET = "This record belongs to another library."
REMOVED_TARGET = "This record was removed. Put it back before you change it."
KEY_TAKEN = "Another record already states this identifier."


class ReferencesRefused(ValidationError):
    """A refusal, and the provider whose box caused it."""

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider
```

Then the verb. It resolves the target under a lock, reads every refusal against
the desired end state, and writes:

```text
def state_external_references(
    *,
    target: CatalogTarget,
    library: UserLibrary,
    keys: Mapping[str, str],
) -> None:
    """One record's whole desired set, for the providers named.

    A provider the caller does not name is left alone: a writer
    that knows one provider must not take another's row. Removal
    is a mark. Every refusal is read before anything is written,
    and each carries the provider whose box caused it.
    """
    from games.models import ExternalReference

    entity_kind, column = _target_metadata(target)
    wanted = {
        normalize_provider(provider): _normalized_or_refused(provider, raw)
        for provider, raw in keys.items()
    }
    with transaction.atomic():
        _refuse_an_unwritable_target(target, library)
        held = {
            reference.provider: reference
            for reference in ExternalReference.objects.select_for_update()
            .filter(removed_at__isnull=True, **{f"{column}_id": target.pk})
            .filter(provider__in=wanted)
        }
        _refuse_a_taken_key(wanted, held, entity_kind)
        for provider, provider_key in wanted.items():
            _state_one(
                provider, provider_key, held.get(provider), target, column
            )
```

with four helpers in the same module:

```text
def _normalized_or_refused(provider: str, raw: str) -> str:
    """A blank box states no reference; anything else normalizes."""
    if not raw.strip():
        return ""
    try:
        _, provider_key = normalize_provider_key(
            provider=provider, provider_key=raw
        )
    except ValidationError as refusal:
        raise ReferencesRefused(
            refusal.messages[0], provider=normalize_provider(provider)
        ) from refusal
    return provider_key


def _refuse_an_unwritable_target(
    target: CatalogTarget, library: UserLibrary
) -> None:
    """A shared, foreign or removed record states nothing here."""
    owner, removed = _owner_and_mark(target)
    if owner is None:
        raise ReferencesRefused(SHARED_TARGET)
    if owner != library.pk:
        raise ReferencesRefused(OTHER_LIBRARY_TARGET)
    if removed:
        raise ReferencesRefused(REMOVED_TARGET)


def _refuse_a_taken_key(
    wanted: Mapping[str, str],
    held: Mapping[str, object],
    entity_kind: str,
) -> None:
    """A key a live row of this kind already holds.

    No pre-check wins a race; the conditional constraint answers
    the one this loses, and `games/catalog_submit.py` reads the
    name the database gave.
    """
    from games.models import ExternalReference

    for provider, provider_key in wanted.items():
        if not provider_key:
            continue
        incumbent = held.get(provider)
        clash = ExternalReference.objects.filter(
            provider=provider,
            entity_kind=entity_kind,
            provider_key=provider_key,
            removed_at__isnull=True,
        )
        if incumbent is not None:
            clash = clash.exclude(pk=incumbent.pk)
        if clash.exists():
            raise ReferencesRefused(KEY_TAKEN, provider=provider)


def _state_one(
    provider: str,
    provider_key: str,
    incumbent: object | None,
    target: CatalogTarget,
    column: str,
) -> None:
    """One provider's box, as one write."""
    from games.models import ExternalReference

    if incumbent is not None:
        if incumbent.provider_key == provider_key:
            return
        ExternalReference.objects.filter(pk=incumbent.pk).update(
            removed_at=now()
        )
    if not provider_key:
        return
    entity_kind, _ = _target_metadata(target)
    ExternalReference.objects.create(
        provider=provider,
        entity_kind=entity_kind,
        provider_key=provider_key,
        **{column: target},
    )
```

`_owner_and_mark(target)` is a small dispatcher beside `_target_metadata`: for a
Game it reads `library_id` and `removed_at`; for a Platform the same; for an
Edition it reads the Game's `library_id` and refuses if the Edition or the Game
carries a mark; for a Release it walks `edition.game`. Import `now` from
`django.utils.timezone` and `Mapping` from `collections.abc`.

Change `save_external_reference()`'s two lookups to add
`removed_at__isnull=True`, so a marked row's key reads as free and the writer
makes a new live row beside it.

- [ ] **Step 4: Run the tests**

Run: `make test ARGS="tests/test_external_references.py"`

Expected: PASS, the pre-existing cases included.

- [ ] **Step 5: Commit**

```bash
git add games/external_references.py tests/test_external_references.py
git commit -m "State a record's references as one set"
```

---

### Task 5: The column becomes the mirror

**Files:**
- Modify: `games/external_references.py:165-197`
- Modify: `games/catalog_submit.py:75-100`
- Modify: `games/removal.py`
- Test: `tests/test_external_references.py`, `tests/test_catalog_submit.py`

**Interfaces:**
- Consumes: `state_external_references()` (Task 4), the `_AFTER_STAMP` tuples
  (Task 2).
- Produces: `mirror_game_wikidata(game: Game) -> None`. `sync_game_wikidata()`
  is gone; every caller and every test that names it moves.

- [ ] **Step 1: Write the failing tests**

Replace the five `sync_game_wikidata` tests at the end of
`tests/test_external_references.py` with:

```python
def test_the_mirror_writes_the_column_from_the_live_reference(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )

    mirror_game_wikidata(game)

    game.refresh_from_db()
    assert game.wikidata == "Q123"


def test_the_mirror_empties_the_column_when_no_reference_is_live(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library, wikidata="Q1")

    mirror_game_wikidata(game)

    game.refresh_from_db()
    assert game.wikidata == ""


def test_the_mirror_ignores_a_marked_reference(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )
    state_external_references(target=game, library=owned_library, keys={"wikidata": ""})

    mirror_game_wikidata(game)

    game.refresh_from_db()
    assert game.wikidata == ""


def test_a_removed_game_keeps_the_column_a_restore_wants(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )
    mirror_game_wikidata(game)

    remove(game)

    game.refresh_from_db()
    assert game.wikidata == "Q123"


def test_a_restore_that_loses_the_key_empties_the_column(owned_library):
    first = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=first, library=owned_library, keys={"wikidata": "Q123"}
    )
    mirror_game_wikidata(first)
    remove(first)
    second = Game.objects.create(name="Elite II", library=owned_library)
    state_external_references(
        target=second, library=owned_library, keys={"wikidata": "Q123"}
    )

    restore(first)

    first.refresh_from_db()
    assert first.wikidata == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_external_references.py -k mirror or restore_that -x"`

Expected: FAIL with `ImportError: cannot import name 'mirror_game_wikidata'`.

- [ ] **Step 3: Replace the adapter**

Delete `sync_game_wikidata()` from `games/external_references.py` and write:

```text
def mirror_game_wikidata(game: Game) -> None:
    """Write `Game.wikidata` from the reference that states it.

    The reference is what a person states; the column is what
    filters, sorting, the games list, the API and the sample
    fixture still read. An UPDATE rather than a save(), like
    `mirror_legacy_columns()`, so the mirror revalidates nothing
    and fires no signal. #889 takes the column.
    """
    from games.models import ExternalReference, Game

    live = (
        ExternalReference.objects.filter(
            provider="wikidata",
            entity_kind="game",
            game_id=game.pk,
            removed_at__isnull=True,
        )
        .values_list("provider_key", flat=True)
        .first()
    ) or ""
    if game.wikidata == live:
        return
    Game.objects.filter(pk=game.pk).update(wikidata=live)
    game.wikidata = live
```

In `games/catalog_submit.py`, `save_game_columns()` loses its
`sync_game_wikidata(game=game)` line and the import. The reference set is
written in Task 7, after the graph.

In `games/removal.py`, add a Game-only hook and put it in the tuple:

```text
def _mirror_the_wikidata_column(game: Game) -> None:
    """A restore that lost the key must not leave the column naming it."""
    from games.external_references import mirror_game_wikidata

    if game.removed_at is None:
        mirror_game_wikidata(game)
```

`_AFTER_STAMP[Game]` becomes `(_mark_the_references_of,
_mirror_the_wikidata_column, _recount_purchases)`. The mirror runs after the
mark, so it reads the marks the same stamp wrote. A removal skips it, so the
column keeps the value a restore wants.

- [ ] **Step 4: Move the Wikidata cases in the submit tests**

In `tests/test_catalog_submit.py`, the three tests
`test_the_wikidata_id_is_canonicalized_and_synchronized`,
`test_an_unchanged_wikidata_id_keeps_the_reference_it_had` and
`test_a_changed_wikidata_id_replaces_the_mapping` post
`wikidata=` through `game_post()`. Leave them failing for now with a
`pytest.mark.xfail(reason="Task 7 moves the field into the references area")`,
and remove the marker in Task 7 when the posted field name changes.

- [ ] **Step 5: Run the tests**

Run: `make test ARGS="tests/test_external_references.py tests/test_reference_removal.py tests/test_catalog_submit.py"`

Expected: PASS, with three xfails.

- [ ] **Step 6: Commit**

```bash
git add games/external_references.py games/catalog_submit.py \
        games/removal.py tests/test_external_references.py \
        tests/test_catalog_submit.py
git commit -m "Let the reference state the key and the column mirror it"
```

---

### Task 6: One field per registered provider

**Files:**
- Create: `games/reference_form.py`
- Create: `tests/test_reference_form.py`

**Interfaces:**
- Consumes: `provider_labels()`, `PROVIDER_POLICIES`,
  `state_external_references()`, `ReferencesRefused`.
- Produces:
  - `reference_field_name(provider: str) -> str` — `f"reference_{provider}"`;
  - `class ReferenceSetForm(PrimitiveWidgetsMixin, forms.Form)` with
    `__init__(self, data, *, target, library)`, `stated_keys() -> dict[str, str]`,
    `write()`, `answer(refusal: ValidationError) -> bool`, and `bind(target)`
    for Add, where the record does not exist yet;
  - `submitted_or_form_error(form, references) -> Model | None` — the shared
    two-form submit for Platform. Game keeps `submitted_game_or_form_error()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reference_form.py`:

```python
"""The External references area, as one bound thing."""

import pytest

from games.external_references import KEY_TAKEN, state_external_references
from games.models import ExternalReference, Game
from games.reference_form import ReferenceSetForm, reference_field_name

pytestmark = pytest.mark.django_db


def test_the_registry_states_the_fields(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)

    form = ReferenceSetForm(None, target=game, library=owned_library)

    assert list(form.fields) == ["reference_wikidata"]
    assert form.fields["reference_wikidata"].label == "Wikidata"
    assert "Q123" in form.fields["reference_wikidata"].help_text


def test_an_unbound_form_reads_the_live_reference(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )

    form = ReferenceSetForm(None, target=game, library=owned_library)

    assert form.initial["reference_wikidata"] == "Q123"


def test_a_malformed_key_lands_on_its_own_box(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)

    form = ReferenceSetForm(
        {"reference_wikidata": "banana"}, target=game, library=owned_library
    )

    assert not form.is_valid()
    assert "Q123" in form.errors["reference_wikidata"][0]


def test_a_valid_key_is_written(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    form = ReferenceSetForm(
        {"reference_wikidata": " q123 "}, target=game, library=owned_library
    )
    assert form.is_valid(), form.errors

    form.write()

    assert (
        ExternalReference.objects.get(game=game, removed_at=None).provider_key == "Q123"
    )


def test_a_blank_box_removes_the_reference(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )
    form = ReferenceSetForm(
        {"reference_wikidata": ""}, target=game, library=owned_library
    )
    assert form.is_valid(), form.errors

    form.write()

    assert not ExternalReference.objects.filter(game=game, removed_at=None).exists()


def test_a_service_refusal_answers_onto_its_box(owned_library):
    first = Game.objects.create(name="Elite", library=owned_library)
    second = Game.objects.create(name="Elite II", library=owned_library)
    state_external_references(
        target=first, library=owned_library, keys={"wikidata": "Q123"}
    )
    form = ReferenceSetForm(
        {"reference_wikidata": "Q123"}, target=second, library=owned_library
    )
    assert form.is_valid(), form.errors

    with pytest.raises(Exception) as refusal:
        form.write()

    assert form.answer(refusal.value)
    assert form.errors["reference_wikidata"] == [KEY_TAKEN]


def test_a_refusal_naming_no_provider_is_a_non_field_error(owned_library):
    shared = Game.objects.create(name="Elite", library=None)
    form = ReferenceSetForm(
        {"reference_wikidata": "Q123"}, target=shared, library=owned_library
    )
    assert form.is_valid(), form.errors

    with pytest.raises(Exception) as refusal:
        form.write()

    assert form.answer(refusal.value)
    assert form.errors["__all__"]


def test_the_field_name_is_the_provider(owned_library):
    assert reference_field_name("wikidata") == "reference_wikidata"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_reference_form.py -x"`

Expected: FAIL with `ModuleNotFoundError: No module named 'games.reference_form'`.

- [ ] **Step 3: Write the form**

Create `games/reference_form.py`:

```text
"""The External references area of a record's form.

One field per registered provider, because a provider issues one
identity per record. Registering a policy in
`games/external_references.py` adds a field and nothing else, thus
no form, renderer or view names a provider.
"""

from collections.abc import Mapping
from typing import cast

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Model

from games.external_references import (
    PROVIDER_POLICIES,
    ReferencesRefused,
    state_external_references,
)
from games.forms import PrimitiveWidgetsMixin
from games.models import ExternalReference, UserLibrary


def reference_field_name(provider: str) -> str:
    """``reference_field_name("wikidata")`` is ``"reference_wikidata"``."""
    return f"reference_{provider}"


class ReferenceSetForm(PrimitiveWidgetsMixin, forms.Form):
    """Every external reference of one record, as one bound thing.

    `target` is None on an Add page, where the record does not
    exist yet; `bind()` names it once the submit has made it.
    """

    def __init__(
        self,
        data: Mapping[str, str] | None,
        *,
        target: Model | None,
        library: UserLibrary,
    ) -> None:
        self.target = target
        self.library = library
        initial = {} if target is None else self._stored(target)
        super().__init__(data, initial=initial)
        for provider, policy in PROVIDER_POLICIES.items():
            self.fields[reference_field_name(provider)] = forms.CharField(
                required=False,
                max_length=255,
                label=policy.label,
                help_text=policy.hint,
            )

    def _stored(self, target: Model) -> dict[str, str]:
        """The keys this record holds, under their field names."""
        column = ExternalReference.TARGET_FIELDS_BY_MODEL[type(target)]
        held = ExternalReference.objects.filter(
            removed_at__isnull=True, **{column: target.pk}
        ).values_list("provider", "provider_key")
        return {
            reference_field_name(provider): provider_key
            for provider, provider_key in held
        }

    def clean(self) -> dict[str, object]:
        """Each policy's own sentence, on its own box."""
        cleaned = cast(dict[str, object], super().clean())
        for provider, policy in PROVIDER_POLICIES.items():
            name = reference_field_name(provider)
            raw = cast(str, cleaned.get(name, "")).strip()
            if not raw:
                cleaned[name] = ""
                continue
            try:
                cleaned[name] = policy.normalize_key(raw)
            except ValidationError as refusal:
                self.add_error(name, refusal.messages[0])
        return cleaned

    def stated_keys(self) -> dict[str, str]:
        """What every box says, under its provider."""
        return {
            provider: cast(
                str, self.cleaned_data.get(reference_field_name(provider), "")
            )
            for provider in PROVIDER_POLICIES
        }

    def bind(self, target: Model) -> None:
        """Name the record a submit just made."""
        self.target = target

    def write(self) -> None:
        """One statement of the whole set."""
        assert self.target is not None, "bind() names a new record first."
        state_external_references(
            target=self.target, library=self.library, keys=self.stated_keys()
        )

    def answer(self, refusal: ValidationError) -> bool:
        """Put the sentence on the box that stated it."""
        if not isinstance(refusal, ReferencesRefused):
            return False
        name = (
            None
            if refusal.provider is None
            else reference_field_name(refusal.provider)
        )
        self.add_error(name, refusal.messages[0])
        return True
```

Then the shared submit, in the same module, which Task 8 uses:

```text
def submitted_or_form_error(
    form: forms.ModelForm, references: ReferenceSetForm
) -> Model | None:
    """Write a record and its references, or answer the refusal.

    One transaction. `IntegrityError` is not caught here: no
    constraint on this table is reachable, because the form holds
    one box per provider and the service reads every refusal
    before it writes.
    """
    from django.db import transaction

    try:
        with transaction.atomic():
            record = form.save()
            references.bind(record)
            references.write()
    except ValidationError as refusal:
        if references.answer(refusal):
            return None
        raise
    return record
```

- [ ] **Step 4: Run the tests**

Run: `make test ARGS="tests/test_reference_form.py"`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/reference_form.py tests/test_reference_form.py
git commit -m "Give a record's references one field per provider"
```

---

### Task 7: Add and Edit Game host the area

**Files:**
- Create: `games/views/reference_section.py`
- Modify: `games/forms.py:986-1027`
- Modify: `games/catalog_submit.py`
- Modify: `games/views/game.py:254-410`
- Test: `tests/test_reference_form.py`, `tests/test_catalog_submit.py`,
  `tests/test_game_form_page.py`

**Interfaces:**
- Consumes: `ReferenceSetForm`, `reference_field_name`.
- Produces: `references_area(form: ReferenceSetForm) -> Node`;
  `save_game_and_graph(form, graph, references)` and
  `submitted_game_or_form_error(form, graph, references)` gain a third
  parameter; `GameForm` no longer has a `wikidata` field.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_reference_form.py`:

```python
def test_add_game_writes_the_key_the_area_states(client, owned_user):
    client.force_login(owned_user)

    client.post(
        reverse("games:add_game"),
        game_post("Elite", reference_wikidata="q123"),
    )

    game = Game.objects.get(name="Elite")
    assert game.wikidata == "Q123"
    assert (
        ExternalReference.objects.get(game=game, removed_at=None).provider_key == "Q123"
    )


def test_a_taken_key_answers_on_the_game_form(client, owned_user):
    client.force_login(owned_user)
    held = Game.objects.create(name="Held", library=owned_user.library)
    state_external_references(
        target=held, library=owned_user.library, keys={"wikidata": "Q123"}
    )

    response = client.post(
        reverse("games:add_game"),
        game_post("Elite", reference_wikidata="Q123"),
    )

    assert response.status_code == 200
    assert KEY_TAKEN in response.content.decode()
    assert not Game.objects.filter(name="Elite").exists()


def test_clearing_the_box_removes_the_reference(client, owned_user):
    client.force_login(owned_user)
    game = Game.objects.create(name="Elite", library=owned_user.library)
    state_external_references(
        target=game, library=owned_user.library, keys={"wikidata": "Q123"}
    )

    client.post(
        reverse("games:edit_game", args=[game.pk]),
        game_post("Elite", reference_wikidata=""),
    )

    game.refresh_from_db()
    assert game.wikidata == ""
    assert not ExternalReference.objects.filter(game=game, removed_at=None).exists()
```

These reuse `game_post()`; import it from `tests.test_catalog_submit` or move
that helper into `tests/conftest.py` and import it from both. Moving it is
better: two modules now post the Game form. Drop `"wikidata": ""` from its
default body and add `"reference_wikidata": ""`. These three tests need
`pytest.mark.django_db(transaction=True)`, because the view dispatches a
PlayerGame command.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_reference_form.py -k add_game or taken_key or clearing -x"`

Expected: FAIL — the posted `reference_wikidata` is ignored and `game.wikidata`
is `""`.

- [ ] **Step 3: Write the renderer**

Create `games/views/reference_section.py`:

```text
"""The External references area of a record's form.

One labelled row per registered provider. No add button, no count
field and no clone template: the rows are the registry, and the
registry does not change while a page is open.
"""

from common.components import Div, FormFields, Node, PageHeading
from games.reference_form import ReferenceSetForm

_BLOCK_CLASS = "rounded-base border border-default-medium p-3 sm:p-4 @container"


def references_area(form: ReferenceSetForm) -> Node:
    """Every provider's box, under one heading."""
    return Div(class_="mb-6 flex flex-col gap-4")[
        PageHeading(children=["External references"]),
        Div(class_=_BLOCK_CLASS)[FormFields(form)],
    ]
```

- [ ] **Step 4: Take the field off the Game form**

In `games/forms.py`, `GameForm` loses `clean_wikidata()`, the `"wikidata"` entry
in `field_order`, and the `"wikidata"` entry in `Meta.fields`. Drop the now
unused imports of `normalize_provider_key` and `ExternalReference` if nothing
else in the module uses them.

- [ ] **Step 5: Write the set inside the submit**

In `games/catalog_submit.py`:

- `save_game_and_graph(form, graph, references)` calls `references.bind(game)`
  and `references.write()` after `graph.write()`, then `mirror_game_wikidata(game)`,
  all inside the existing `@transaction.atomic`;
- `submitted_game_or_form_error(form, graph, references)` adds
  `if references.answer(refusal): return None` to its `ValidationError` branch,
  before the graph's;
- `_game_form_refusal()` loses its `provider_key` branch, and
  `WIKIDATA_CONFLICT_MESSAGE` is deleted — `KEY_TAKEN` in
  `games/external_references.py` is the sentence now, for every provider.

Update `UNREACHABLE_FROM_THE_GAME_FORM`'s entry for
`unique_external_reference_provider_kind_key` to name
`state_external_references` rather than `save_external_reference`.

- [ ] **Step 6: Host it on both views**

In `games/views/game.py`, `add_game()` and `edit_game()` each build a third form
and thread it through:

```text
references = ReferenceSetForm(
    request.POST or None, target=game, library=library
)
```

(`target=None` in `add_game()`). Both read before either writes, matching the
existing comment about why the order is not `and`:

```text
game_reads = form.is_valid()
references_read = references.is_valid()
if graph.is_valid() and game_reads and references_read:
    written = submitted_game_or_form_error(form, graph, references)
```

and the field markup grows one node:

```text
fields=Fragment(FormFields(form), editions_area(graph), references_area(references))
```

After a successful write in `edit_game()`, rebuild `references` unbound from the
written Game, exactly as the graph is rebuilt, so a resubmit lands on the rows
storage returned.

- [ ] **Step 7: Fix the moved tests**

Remove the three `xfail` markers added in Task 5 and rewrite those tests to post
`reference_wikidata` instead of `wikidata`. Search the suite for the posted
field name and fix every caller:

Run: `grep -rn '"wikidata"' tests/ e2e/`

- [ ] **Step 8: Run the tests**

Run: `make test ARGS="tests/test_reference_form.py tests/test_catalog_submit.py tests/test_game_form_page.py tests/test_rendered_pages.py"`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add games/views/reference_section.py games/forms.py \
        games/catalog_submit.py games/views/game.py tests/
git commit -m "Let the Game form state every reference it holds"
```

---

### Task 8: Add and Edit Platform host the same area

**Files:**
- Modify: `games/views/platform.py:162-190`
- Test: `tests/test_reference_form.py`

**Interfaces:**
- Consumes: `references_area()`, `ReferenceSetForm`, `submitted_or_form_error()`.
- Produces: nothing new.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_reference_form.py`:

```python
def test_add_platform_writes_the_key_the_area_states(client, owned_user):
    client.force_login(owned_user)

    client.post(
        reverse("games:add_platform"),
        {
            "name": "Amiga",
            "group": "",
            "icon": "",
            "reference_wikidata": "Q100047",
        },
    )

    platform = Platform.objects.get(name="Amiga")
    assert (
        ExternalReference.objects.get(platform=platform, removed_at=None).provider_key
        == "Q100047"
    )


def test_a_shared_platform_offers_no_edit(client, owned_user):
    shared = Platform.objects.create(name="Amiga", library=None)
    client.force_login(owned_user)

    response = client.get(reverse("games:edit_platform", args=[shared.pk]))

    assert response.status_code == 404


def test_a_taken_key_answers_on_the_platform_form(client, owned_user):
    client.force_login(owned_user)
    held = Platform.objects.create(name="Held", library=owned_user.library)
    state_external_references(
        target=held, library=owned_user.library, keys={"wikidata": "Q100047"}
    )

    response = client.post(
        reverse("games:add_platform"),
        {
            "name": "Amiga",
            "group": "",
            "icon": "",
            "reference_wikidata": "Q100047",
        },
    )

    assert response.status_code == 200
    assert KEY_TAKEN in response.content.decode()
    assert not Platform.objects.filter(name="Amiga").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_reference_form.py -k platform -x"`

Expected: FAIL — `ExternalReference.DoesNotExist`. The shared-platform case
should already pass; it is the regression guard for the read-only rule.

- [ ] **Step 3: Host it**

`add_platform()` and `edit_platform()` each build the second form and hand both
to the shared submit:

```text
form = PlatformForm(request.POST or None, instance=platform, library=library)
references = ReferenceSetForm(
    request.POST or None, target=platform, library=library
)
form_reads = form.is_valid()
if references.is_valid() and form_reads:
    if submitted_or_form_error(form, references) is not None:
        return redirect(return_url(request, fallback="games:list_platforms"))
return render_page(
    request,
    AddForm(
        form,
        request=request,
        fields=Fragment(FormFields(form), references_area(references)),
    ),
    title="Edit Platform",
)
```

`add_platform()` is the same with `instance` and `target` absent, its own
fallback title, and `PlatformForm(request.POST or None, library=library)`.

- [ ] **Step 4: Run the tests**

Run: `make test ARGS="tests/test_reference_form.py tests/test_paths_return_200.py"`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/views/platform.py tests/test_reference_form.py
git commit -m "Let the Platform form state every reference it holds"
```

---

### Task 9: What a reader sees

**Files:**
- Modify: `common/components/domain.py`
- Modify: `common/components/__init__.py`
- Create: `games/reads/external_references.py`
- Modify: `games/views/game.py` (the metadata row and the Editions column)
- Modify: `games/views/platform.py` (the list column)
- Create: `tests/test_reference_presentation.py`

**Interfaces:**
- Consumes: `external_reference_url()`, `PROVIDER_POLICIES`.
- Produces:
  - `ExternalReferenceLinks(references: Sequence[ExternalReference]) -> Node`;
  - `references_for(rows: Sequence[Model]) -> dict[UUID, list[ExternalReference]]`
    — keyed by the target row's primary key, one query per kind present.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reference_presentation.py`:

```python
"""What a reference looks like on a page."""

import pytest
from django.urls import reverse

from common.components import ExternalReferenceLinks
from games.external_references import state_external_references
from games.models import ExternalReference, Game, Platform
from games.reads.external_references import references_for

pytestmark = pytest.mark.django_db


def test_a_link_states_its_provider_and_its_key(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )
    references = list(ExternalReference.objects.filter(game=game))

    markup = str(ExternalReferenceLinks(references))

    assert 'href="https://www.wikidata.org/wiki/Q123"' in markup
    assert "Wikidata" in markup
    assert "Q123" in markup


def test_no_reference_renders_nothing_a_reader_reads_as_one(owned_library):
    assert str(ExternalReferenceLinks([])).strip() in ("", "—")


def test_the_batch_read_takes_one_query_per_kind(
    owned_library, django_assert_num_queries
):
    games = [
        Game.objects.create(name=f"Game {index}", library=owned_library)
        for index in range(5)
    ]
    for index, game in enumerate(games):
        state_external_references(
            target=game,
            library=owned_library,
            keys={"wikidata": f"Q{index + 1}"},
        )

    with django_assert_num_queries(1):
        found = references_for(games)

    assert len(found) == 5


def test_a_marked_reference_is_not_read(owned_library):
    game = Game.objects.create(name="Elite", library=owned_library)
    state_external_references(
        target=game, library=owned_library, keys={"wikidata": "Q123"}
    )
    state_external_references(target=game, library=owned_library, keys={"wikidata": ""})

    assert references_for([game]) == {}


def test_game_detail_shows_the_reference(client, owned_user):
    client.force_login(owned_user)
    game = Game.objects.create(name="Elite", library=owned_user.library)
    state_external_references(
        target=game, library=owned_user.library, keys={"wikidata": "Q123"}
    )

    response = client.get(game.get_absolute_url())

    assert "https://www.wikidata.org/wiki/Q123" in response.content.decode()


def test_the_platform_list_shows_the_reference(client, owned_user):
    client.force_login(owned_user)
    platform = Platform.objects.create(name="Amiga", library=owned_user.library)
    state_external_references(
        target=platform,
        library=owned_user.library,
        keys={"wikidata": "Q100047"},
    )

    response = client.get(reverse("games:list_platforms"))

    assert "https://www.wikidata.org/wiki/Q100047" in response.content.decode()
```

The Game-detail test needs the `_track_created_games` autouse fixture to have
given the Game its projection row; it does, so no extra setup.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `make test ARGS="tests/test_reference_presentation.py -x"`

Expected: FAIL with `ImportError: cannot import name 'ExternalReferenceLinks'`.

- [ ] **Step 3: Write the component**

In `common/components/domain.py`:

```text
def ExternalReferenceLinks(references) -> Node:
    """One link per reference, safe by three layers.

    The database refuses a key its canonical pattern does not
    match, the policy template is the only source of a URL and
    quotes the key it interpolates, and the node layer escapes
    every attribute value it writes.
    """
    from games.external_references import PROVIDER_POLICIES

    if not references:
        return Fragment()
    return Span(class_="flex flex-wrap gap-2")[
        *(
            Link(
                href=external_reference_url(
                    provider=reference.provider,
                    entity_kind=reference.entity_kind,
                    provider_key=reference.provider_key,
                ),
                class_="whitespace-nowrap",
                rel="noopener noreferrer",
                target="_blank",
            )[
                f"{PROVIDER_POLICIES[reference.provider].label} "
                f"{reference.provider_key}"
            ]
            for reference in references
        )
    ]
```

`Link` is the primitive `GameLink()` in the same module already uses, so a
reference link reads like every other link on the page. Export
`ExternalReferenceLinks` from `common/components/__init__.py`.

- [ ] **Step 4: Write the batch read**

Create `games/reads/external_references.py`:

```text
"""The live references of a batch of rows.

One query per kind present, so no list pays per row.
"""

from collections import defaultdict
from collections.abc import Sequence
from uuid import UUID

from django.db.models import Model

from games.models import ExternalReference


def references_for(
    rows: Sequence[Model],
) -> dict[UUID, list[ExternalReference]]:
    """Every live reference of these rows, under the row's own id."""
    by_column: dict[str, list[UUID]] = defaultdict(list)
    for row in rows:
        by_column[ExternalReference.TARGET_FIELDS_BY_MODEL[type(row)]].append(
            row.pk
        )
    found: dict[UUID, list[ExternalReference]] = defaultdict(list)
    for column, ids in by_column.items():
        held = ExternalReference.objects.filter(
            removed_at__isnull=True, **{f"{column}__in": ids}
        ).order_by("provider")
        for reference in held:
            found[getattr(reference, column)].append(reference)
    return dict(found)
```

- [ ] **Step 5: Add the three surfaces**

In `games/views/game.py`:

- `_game_header()` gains one row, after `Original release`:
  `_meta_row("References", ExternalReferenceLinks(references_for([game]).get(game.pk, [])))`.
  Pass the map in from `view_game()` rather than reading inside the header, so
  the page reads once.
- `_releases_section()` gains a `Column("References", priority=3)` and a cell
  per Edition row holding that Edition's references followed by its Releases'.
  Build the map once in `view_game()` over every Edition and Release in
  `hierarchy` and thread it in.

In `games/views/platform.py`, `list_platforms()` builds
`references = references_for(list(platforms))` after pagination and adds
`Column("References", priority=3)` with
`ExternalReferenceLinks(references.get(platform.pk, []))` as its cell.

The games list is untouched.

- [ ] **Step 6: Run the tests**

Run: `make test ARGS="tests/test_reference_presentation.py tests/test_rendered_pages.py tests/test_paths_return_200.py"`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add common/components/ games/reads/external_references.py \
        games/views/game.py games/views/platform.py \
        tests/test_reference_presentation.py
git commit -m "Show a record's references where a reader looks"
```

---

### Task 10: The evidence the acceptance list asks for, and the docs

**Files:**
- Modify: `tests/test_external_references.py`
- Create: `e2e/test_external_references_e2e.py`
- Modify: `docs/catalog.md`, `docs/event-retention.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing the code imports.

- [ ] **Step 1: Write the parity, isolation, safety and accessibility tests**

Append to `tests/test_external_references.py`:

```python
def test_every_mirrored_column_equals_its_live_reference(django_db_setup):
    """Parity over the anonymized production snapshot."""
    from django.core.management import call_command

    call_command("loaddata", "sample.yaml.gz", verbosity=0)
    for game in Game.objects.all():
        live = (
            ExternalReference.objects.filter(
                provider="wikidata",
                entity_kind="game",
                game_id=game.pk,
                removed_at__isnull=True,
            )
            .values_list("provider_key", flat=True)
            .first()
        )
        assert game.wikidata == (live or "")


def test_a_second_library_cannot_state_the_first_librarys_key(
    owned_library, django_user_model
):
    other = django_user_model.objects.create_user(
        username="second", password="p"
    ).library
    mine = Game.objects.create(name="Elite", library=owned_library)
    theirs = Game.objects.create(name="Elite", library=other)
    state_external_references(
        target=mine, library=owned_library, keys={"wikidata": "Q123"}
    )

    with pytest.raises(ReferencesRefused) as refusal:
        state_external_references(
            target=theirs, library=other, keys={"wikidata": "Q123"}
        )

    assert refusal.value.messages[0] == KEY_TAKEN


def test_a_key_cannot_select_a_url_of_its_own(owned_library):
    """Three layers, each refusing on its own."""
    game = Game.objects.create(name="Elite", library=owned_library)

    with pytest.raises(ReferencesRefused):
        state_external_references(
            target=game,
            library=owned_library,
            keys={"wikidata": 'Q1" onmouseover="x'},
        )

    with pytest.raises(IntegrityError):
        ExternalReference.objects.create(
            provider="wikidata",
            entity_kind="game",
            provider_key='Q1" onmouseover="x',
            game=game,
        )


def test_every_key_box_states_a_label(client, owned_user):
    """The accessibility tree names each box."""
    client.force_login(owned_user)

    body = client.get(reverse("games:add_game")).content.decode()

    assert 'for="id_reference_wikidata"' in body
    assert ">Wikidata<" in body
```

The parity test's `loaddata` call must run in its own database state; if the
suite's fixtures make that awkward, mark it
`@pytest.mark.django_db(transaction=True)` and load into the empty test
database, which is what the fixture's prod primary keys need.

- [ ] **Step 2: Write the e2e case**

Create `e2e/test_external_references_e2e.py`. The `signed_in` fixture and the
`SUBMIT` selector are private to `e2e/test_game_form_catalog_e2e.py`, so this
file states its own, the way that file states its own copy of `stated_graph`:

```python
"""An external reference, stated and followed in a real browser.

The area holds one plain text box per provider and no scripting of
its own, thus this file proves the round trip rather than a widget:
what a person types is written, shown as a link, changed, and let
go of.

A UI assertion is not a database assertion. Every ORM read below
waits for the page the redirect lands on first.
"""

import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from games.external_references import state_external_references
from games.models import ExternalReference, Game

pytestmark = pytest.mark.django_db(transaction=True)

SUBMIT = 'button[type="submit"]:has-text("Submit")'


@pytest.fixture
def signed_in(live_server, page: Page, e2e_user) -> Page:
    page.goto(f"{live_server.url}{reverse('login')}")
    page.fill('input[name="username"]', "tester")
    page.fill('input[name="password"]', "secret123")
    page.click('button:has-text("Login")')
    page.wait_for_url(f"{live_server.url}/tracker**")
    return page


def saved(page: Page, live_server) -> None:
    """Press Submit and wait for the page the write redirects to."""
    page.click(SUBMIT)
    page.wait_for_url(f"{live_server.url}{reverse('games:list_games')}**")


def live_key(game: Game) -> str | None:
    return (
        ExternalReference.objects.filter(
            provider="wikidata",
            entity_kind="game",
            game_id=game.pk,
            removed_at__isnull=True,
        )
        .values_list("provider_key", flat=True)
        .first()
    )


def test_add_game_states_a_reference_and_detail_follows_it(
    signed_in, live_server, e2e_library
):
    page = signed_in
    page.goto(f"{live_server.url}{reverse('games:add_game')}")

    page.fill("input[name='name']", "Elite")
    page.fill("input[name='reference_wikidata']", "q123")
    saved(page, live_server)

    written = Game.objects.get(library=e2e_library, name="Elite")
    assert live_key(written) == "Q123"

    page.goto(f"{live_server.url}{written.get_absolute_url()}")
    link = page.get_by_role("link", name="Wikidata Q123")
    expect(link).to_have_attribute("href", "https://www.wikidata.org/wiki/Q123")


def test_editing_the_box_changes_the_key_then_lets_go_of_it(
    signed_in, live_server, e2e_library
):
    page = signed_in
    game = Game.objects.create(library=e2e_library, name="Elite")
    state_external_references(
        target=game, library=e2e_library, keys={"wikidata": "Q123"}
    )
    edit = f"{live_server.url}{reverse('games:edit_game', args=[game.pk])}"

    page.goto(edit)
    box = page.locator("input[name='reference_wikidata']")
    expect(box).to_have_value("Q123")
    box.fill("Q124")
    saved(page, live_server)

    assert live_key(game) == "Q124"

    page.goto(edit)
    page.locator("input[name='reference_wikidata']").fill("")
    saved(page, live_server)

    assert live_key(game) is None
    page.goto(f"{live_server.url}{game.get_absolute_url()}")
    expect(page.get_by_role("link", name="Wikidata Q124")).to_have_count(0)


def test_a_taken_key_answers_beside_the_box_a_person_typed_into(
    signed_in, live_server, e2e_library
):
    """The refusal comes back on the page, with the value still in it."""
    page = signed_in
    held = Game.objects.create(library=e2e_library, name="Held")
    state_external_references(
        target=held, library=e2e_library, keys={"wikidata": "Q123"}
    )
    page.goto(f"{live_server.url}{reverse('games:add_game')}")

    page.fill("input[name='name']", "Elite")
    page.fill("input[name='reference_wikidata']", "Q123")
    page.click(SUBMIT)

    expect(page.get_by_text(KEY_TAKEN)).to_be_visible()
    expect(page.locator("input[name='reference_wikidata']")).to_have_value("Q123")
    assert not Game.objects.filter(library=e2e_library, name="Elite").exists()
```

Import `KEY_TAKEN` beside `state_external_references`. Confirm the Submit
button's text against `e2e/test_game_form_catalog_e2e.py`'s own `SUBMIT`
constant before running, and copy it if it differs.

- [ ] **Step 3: Run them**

Run: `make test ARGS="tests/test_external_references.py"` then
`make test-e2e ARGS="-k external_references"`

Expected: PASS.

- [ ] **Step 4: Write the docs**

In `docs/catalog.md`, add a section after **What a constraint says**:

> ## External references
>
> A record may name itself in a provider's catalog. `ExternalReference` holds
> one `(provider, entity_kind, provider_key)` tuple against one row, and
> `PROVIDER_POLICIES` in `games/external_references.py` is the one registry:
> a policy states how a key normalizes, the trusted HTTPS template its link
> comes from, the words a person reads, and therefore the field a form draws.
> Registering a policy is the whole cost of a provider, except for the two
> check constraints that pin the column and the key pattern, which a second
> provider migrates.
>
> A provider issues one identity per record, so a form holds one box per
> provider and four conditional constraints hold the rule. Blank means the
> record names none.
>
> `state_external_references()` states one record's whole desired set, under
> the contract [Stating a graph](#stating-a-graph) sets out: a provider the
> caller does not name is left alone, removal is a mark, every refusal is read
> before anything is written, and each names the box that caused it. It
> refuses a shared record, another library's record and a removed one.
>
> A reference carries a `removed_at` of its own, which `games/removal.py`
> writes when it stamps the row the reference names. That is what lets a
> removed record let go of its key (#976). A restore takes back only the keys
> no live row holds.
>
> Game and Platform host the editor. An Edition's and a Release's references
> are shown and are not editable: neither row has a route, and only #782's
> importer writes one.
>
> `Game.wikidata` is a mirror now, written from the live Wikidata reference by
> `mirror_game_wikidata()`. Filters, sorting, the games list and the sample
> fixture read the column; #889 takes it.

In `docs/event-retention.md`, add the new constraints to whatever list of
conditional constraints that page keeps, with #976 named as the reason.

- [ ] **Step 5: Run the full gate**

Run: `make check`

Expected: green, including `make vale`, `mypy`, `format-check` and the whole
pytest suite with `e2e/`. This is the gate; a hand-picked subset is not.

- [ ] **Step 6: Commit**

```bash
git add tests/ e2e/ docs/
git commit -m "Prove the references hold, and write down the contract"
```

---

## After the plan

Record the two deferral verdicts from the spec in the tracker, not only here:

- **#896** and **#601** get the note that Edition and Release references are
  read-only in this issue, with #782 owning the producer and #690 the section.
- **#896** and **#601** get the note that a provider key is unique across every
  library, with #654/#785 owning reconciliation.
- **#976** closes with this branch.
