"""Remove platforms in bulk; undo the batch."""

import json
import uuid
from datetime import date

import pytest
from bulk_posts import act_url, posted, selection
from django.http import Http404
from django.urls import reverse

from games.bulk_actions import BULK_ACTIONS
from games.bulk_parts import LedgerRows
from games.bulk_platforms import PLATFORM_GONE
from games.bulk_removal import REMOVE_PLATFORM
from games.models import Game, Platform, Purchase, UserLibrary
from games.reads.platform_departures import platform_departures_of
from games.removal import remove, restore
from games.views.bulk import STATEMENT_FIELD, TOKEN_FIELD, _act_of
from games.views.platform_menu import platform_row_menu

pytestmark = [pytest.mark.untracked_games, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def amiga(owned_library):
    return Platform.objects.create(
        library=owned_library, name="Amiga", group="Commodore"
    )


@pytest.fixture
def dos(owned_library):
    return Platform.objects.create(library=owned_library, name="DOS")


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def _live(library: UserLibrary) -> set[uuid.UUID]:
    return set(Platform.objects.for_library(library).values_list("pk", flat=True))


def _press(client, *rows) -> uuid.UUID:
    """Confirm and run; the batch's id."""
    url = act_url(REMOVE_PLATFORM)
    submitted = posted(client.post(url, {STATEMENT_FIELD: selection(*rows)}))
    client.post(url, submitted)
    return uuid.UUID(submitted[TOKEN_FIELD])


def _undo(client, batch: uuid.UUID):
    return client.post(reverse("games:undo_bulk_action", args=[batch]))


def test_the_act_is_declared():
    assert BULK_ACTIONS["platform.remove"] is REMOVE_PLATFORM
    assert REMOVE_PLATFORM.undo_rows == LedgerRows(Platform)


# ── The rows ─────────────────────────────────────────────────────────────────


def test_the_scope_is_private_and_live(owned_library, amiga, dos):
    Platform.objects.create(name="Switch", group="Nintendo")
    remove(dos)

    assert list(REMOVE_PLATFORM.scope(owned_library, "")) == [amiga]


def test_the_scope_narrows_by_the_statements_filter(owned_library, amiga, dos):
    narrowed = REMOVE_PLATFORM.scope(
        owned_library, json.dumps({"name": {"value": "DOS", "modifier": "EQUALS"}})
    )

    assert list(narrowed) == [dos]


def test_a_key_the_library_does_not_hold_comes_out_lost(owned_library, amiga):
    shared = Platform.objects.create(name="Switch", group="Nintendo")

    resolution = REMOVE_PLATFORM.resolve(owned_library, [amiga.pk, shared.pk])

    assert [row.pk for row in resolution.rows] == [amiga.pk]
    assert [
        (entry.key, entry.lost, entry.sentence) for entry in resolution.refused
    ] == [(str(shared.pk), True, PLATFORM_GONE)]


def test_the_counts_are_the_live_rows_naming_each(
    owned_library, stated_graph, amiga, dos
):
    stated_graph(
        Game(library=owned_library, name="Lemmings", platform=amiga),
        owned_library,
        platform=amiga,
    )
    gone = stated_graph(
        Game(library=owned_library, name="Turrican", platform=amiga),
        owned_library,
        platform=amiga,
    )
    remove(gone.game)
    Purchase.objects.create(
        library=owned_library,
        name="Lemmings",
        platform=amiga,
        date_purchased=date(2026, 1, 1),
        price=5,
        price_currency="USD",
    )

    rows = REMOVE_PLATFORM.resolve(owned_library, [amiga.pk, dos.pk]).rows

    #: Name order.
    assert [(row.name, platform_departures_of(row)) for row in rows] == [
        ("Amiga", (1, 1, 1)),
        ("DOS", (0, 0, 0)),
    ]


# ── A batch and its Undo ─────────────────────────────────────────────────────


def test_a_batch_removes_and_its_undo_puts_every_row_back(
    logged_in, owned_library, amiga, dos
):
    url = act_url(REMOVE_PLATFORM)
    confirmation = logged_in.post(url, {STATEMENT_FIELD: selection(amiga, dos)})
    html = confirmation.content.decode()
    for heading in ("Platform", "Group", "Games", "Releases", "Purchases"):
        assert heading in html
    assert "Remove 2 platforms" in html
    submitted = posted(confirmation)

    logged_in.post(url, submitted)
    #: The same token again removes nothing twice.
    logged_in.post(url, submitted)

    assert _live(owned_library) == set()
    batch = uuid.UUID(submitted[TOKEN_FIELD])
    assert set(LedgerRows(Platform).rows(owned_library, batch)) == {amiga.pk, dos.pk}

    _undo(logged_in, batch)

    assert _live(owned_library) == {amiga.pk, dos.pk}


def test_a_chunk_posted_after_a_restore_by_hand_leaves_the_row(
    logged_in, owned_library, amiga
):
    url = act_url(REMOVE_PLATFORM)
    submitted = posted(logged_in.post(url, {STATEMENT_FIELD: selection(amiga)}))
    logged_in.post(url, submitted)
    restore(amiga)

    logged_in.post(url, submitted)

    assert _live(owned_library) == {amiga.pk}


def test_the_undo_after_a_restore_by_hand_changes_nothing(
    logged_in, owned_library, amiga, dos
):
    batch = _press(logged_in, amiga, dos)
    restore(amiga)

    response = _undo(logged_in, batch)

    assert response.status_code in (200, 302)
    assert _live(owned_library) == {amiga.pk, dos.pk}


def test_the_undo_restores_over_a_later_removal(logged_in, owned_library, amiga, dos):
    batch = _press(logged_in, amiga, dos)
    restore(amiga)
    remove(amiga)

    _undo(logged_in, batch)

    assert _live(owned_library) == {amiga.pk, dos.pk}


def test_the_undo_answers_a_taken_name_for_that_row_only(
    logged_in, owned_library, amiga, dos
):
    batch = _press(logged_in, amiga, dos)
    Platform.objects.create(library=owned_library, name="Amiga", group="Commodore")

    _undo(logged_in, batch)

    live = _live(owned_library)
    assert dos.pk in live
    assert amiga.pk not in live


# ── Which act wrote a batch ──────────────────────────────────────────────────


def test_a_ledger_batch_names_its_act(logged_in, owned_library, amiga):
    batch = _press(logged_in, amiga)

    assert _act_of(owned_library, batch) is REMOVE_PLATFORM


def test_another_librarys_ledger_batch_is_not_found(
    logged_in, client, owned_library, django_user_model, amiga
):
    batch = _press(logged_in, amiga)
    stranger = django_user_model.objects.create_user("stranger", password="p")

    with pytest.raises(Http404):
        _act_of(stranger.library, batch)
    client.force_login(stranger)
    response = client.post(reverse("games:undo_bulk_action", args=[batch]))

    assert response.status_code == 404
    assert Platform.objects.get(pk=amiga.pk).removed_at is not None


def test_an_unknown_batch_is_not_found(owned_library):
    with pytest.raises(Http404):
        _act_of(owned_library, uuid.uuid7())


# ── The row menu and the list ────────────────────────────────────────────────


def test_a_row_offers_edit_and_remove(amiga, dos):
    html = str(platform_row_menu(amiga, origin=None))

    assert reverse("games:edit_platform", args=[amiga.pk]) in html
    assert reverse("games:remove_platform", args=[amiga.pk]) in html
    assert "Amiga (Commodore) actions" in html
    assert "DOS actions" in str(platform_row_menu(dos, origin=None))


def test_the_list_carries_the_selection_and_no_actions_column(logged_in, amiga):
    html = logged_in.get(reverse("games:list_platforms")).content.decode()

    assert ">Actions<" not in html
    assert "selectable-table" in html
    assert f"platform-menu-{amiga.pk}" in html
    assert act_url(REMOVE_PLATFORM) in html


def test_the_one_row_confirmation_counts_as_the_batch_does(
    logged_in, owned_library, amiga
):
    Game.objects.create(library=owned_library, name="Lemmings", platform=amiga)

    html = logged_in.get(
        reverse("games:remove_platform", args=[amiga.pk])
    ).content.decode()

    assert "1 game(s), 0 release(s) and 0 purchase(s) still name it" in html
