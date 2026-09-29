"""The routes that add, edit, end, resume, remove and restore a copy."""

import datetime
from urllib.parse import urlencode

import pytest
from django.urls import reverse
from entries import end_entry_access, record_entry, remove_entry

from games.entry_forms import CHANGED_SINCE_OPENED
from games.models import Game, LibraryEntry, LibraryEvent, Platform
from games.removal import remove
from games.views.library_cards import ADD_PREFIX, act_prefix
from timetracker.temporal import TemporalValue, temporal_input_name

pytestmark = pytest.mark.django_db(transaction=True)

SUBMISSION = "01928e5e-4f6b-7c3a-8e9d-000000000001"


def _day(name: str, day: datetime.date) -> dict[str, str]:
    return {
        temporal_input_name(name, "kind"): "date",
        temporal_input_name(name, "start_year"): str(day.year),
        temporal_input_name(name, "start_month"): str(day.month),
        temporal_input_name(name, "start_day"): str(day.day),
    }


@pytest.fixture
def graph(owned_library, stated_graph):
    ps5 = Platform.objects.create(name="PS5", group="Sony")
    return stated_graph(
        Game(name="Tunic", library=owned_library), owned_library, platform=ps5
    )


@pytest.fixture
def entry(owned_library, graph):
    return record_entry(
        owned_library, graph.release, acquired=TemporalValue.parse("2021-05")
    )


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def _types(entry_id) -> list[str]:
    return list(
        LibraryEvent.objects.filter(aggregate_id=entry_id)
        .order_by("sequence")
        .values_list("event_type", flat=True)
    )


# --- add ------------------------------------------------------------------


def _add_post(graph, **changes) -> dict[str, str]:
    posted = {
        f"{ADD_PREFIX}-release": str(graph.release.pk),
        f"{ADD_PREFIX}-access": "owned",
        f"{ADD_PREFIX}-format": "digital",
        f"{ADD_PREFIX}-note": "",
        f"{ADD_PREFIX}-submission": SUBMISSION,
        **_day(f"{ADD_PREFIX}-acquired", datetime.date(2026, 9, 1)),
    }
    return posted | {f"{ADD_PREFIX}-{key}": value for key, value in changes.items()}


def _add_url(game) -> str:
    return reverse("games:add_library_entry", args=[game.pk])


def test_add_records_a_copy_and_returns(logged_in, graph):
    response = logged_in.post(
        _add_url(graph.game) + f"?origin={graph.game.get_absolute_url()}",
        _add_post(graph),
    )

    assert response.status_code == 302
    assert response["Location"] == graph.game.get_absolute_url()
    entry = LibraryEntry.objects.get(release=graph.release)
    assert entry.acquired == TemporalValue.parse("2026-09-01")


def test_a_repeated_add_records_once(logged_in, graph):
    for _ in range(2):
        logged_in.post(_add_url(graph.game), _add_post(graph))

    assert LibraryEntry.objects.filter(release=graph.release).count() == 1


def test_an_invalid_add_renders_game_detail_with_the_form_open(logged_in, graph):
    response = logged_in.post(_add_url(graph.game), _add_post(graph, access="lent"))

    assert response.status_code == 200
    html = response.content.decode()
    assert 'id="library"' in html
    assert "<details open" in html
    assert not LibraryEntry.objects.exists()


def test_a_removed_release_is_refused_on_the_form(logged_in, graph):
    remove(graph.release)
    response = logged_in.post(_add_url(graph.game), _add_post(graph))

    assert response.status_code == 200
    assert not LibraryEntry.objects.exists()


def test_a_get_on_add_opens_the_form(logged_in, graph):
    response = logged_in.get(_add_url(graph.game))

    assert response.status_code == 302
    assert "?library=add" in response["Location"]


def test_add_on_another_librarys_game_is_absent(client, graph, django_user_model):
    stranger = django_user_model.objects.create_user(username="stranger")
    client.force_login(stranger)

    response = client.post(_add_url(graph.game), _add_post(graph))

    assert response.status_code == 404


# --- edit -----------------------------------------------------------------


def _edit_post(entry, **changes) -> dict[str, str]:
    prefix = act_prefix(entry.pk, "edit")
    posted = {
        f"{prefix}-release": str(entry.release_id),
        f"{prefix}-access": entry.access,
        f"{prefix}-format": entry.format,
        f"{prefix}-note": entry.note,
        f"{prefix}-end_state": "held"
        if entry.access_end_recorded_at is None
        else "ended",
        f"{prefix}-way": entry.access_end_way,
        f"{prefix}-access_end_seen": (
            ""
            if entry.access_end_recorded_at is None
            else entry.access_end_recorded_at.isoformat()
        ),
        temporal_input_name(f"{prefix}-acquired", "kind"): "date",
        temporal_input_name(f"{prefix}-acquired", "start_year"): "2021",
        temporal_input_name(f"{prefix}-acquired", "start_month"): "5",
    }
    return posted | {f"{prefix}-{key}": value for key, value in changes.items()}


def _edit_url(entry) -> str:
    return reverse("games:edit_library_entry", args=[entry.pk])


def test_edit_restates_the_copy(logged_in, entry):
    response = logged_in.post(_edit_url(entry), _edit_post(entry, note="shelf"))

    assert response.status_code == 302
    entry.refresh_from_db()
    assert entry.note == "shelf"


def test_held_on_an_ended_copy_voids_the_end(logged_in, entry):
    entry = end_entry_access(entry)

    logged_in.post(_edit_url(entry), _edit_post(entry, end_state="held"))

    entry.refresh_from_db()
    assert entry.access_end_recorded_at is None
    assert _types(entry.pk)[-1] == "library.libraryentry.access_end_voided"


def test_a_stale_end_marker_is_refused(logged_in, entry):
    posted = _edit_post(entry)
    end_entry_access(entry)

    response = logged_in.post(_edit_url(entry), posted)

    assert response.status_code == 200
    assert CHANGED_SINCE_OPENED in response.content.decode()
    entry.refresh_from_db()
    assert entry.access_end_recorded_at is not None


def test_a_refused_edit_renders_at_its_status(logged_in, entry):
    posted = _edit_post(entry, end_state="ended", way="sold")
    posted |= _day(f"{act_prefix(entry.pk, 'edit')}-ended", datetime.date(2020, 1, 1))

    response = logged_in.post(_edit_url(entry), posted)

    assert response.status_code == 409
    assert "<details open" in response.content.decode()


def test_edit_of_another_librarys_copy_is_absent(client, entry, django_user_model):
    stranger = django_user_model.objects.create_user(username="stranger")
    client.force_login(stranger)

    assert client.post(_edit_url(entry), _edit_post(entry)).status_code == 404


def test_a_get_on_edit_opens_the_form(logged_in, entry):
    response = logged_in.get(_edit_url(entry))

    assert response.status_code == 302
    assert f"?library=edit&copy={entry.pk}#copy-{entry.pk}" in response["Location"]


# --- end and resume ---------------------------------------------------------


def _end_post(entry, **changes) -> dict[str, str]:
    prefix = act_prefix(entry.pk, "end")
    posted = {
        f"{prefix}-way": "sold",
        f"{prefix}-note": "",
        f"{prefix}-access_end_seen": "",
        f"{prefix}-submission": SUBMISSION,
        **_day(f"{prefix}-ended", datetime.date(2026, 9, 2)),
    }
    return posted | {f"{prefix}-{key}": value for key, value in changes.items()}


def test_end_access_states_the_end_once(logged_in, entry):
    url = reverse("games:end_library_entry", args=[entry.pk])
    for _ in range(2):
        response = logged_in.post(url, _end_post(entry))

    assert response.status_code == 302
    assert _types(entry.pk).count("library.libraryentry.access_ended") == 1


def test_resume_states_the_resume(logged_in, entry):
    entry = end_entry_access(entry, ended=TemporalValue.parse("2022"))
    prefix = act_prefix(entry.pk, "resume")

    response = logged_in.post(
        reverse("games:resume_library_entry", args=[entry.pk]),
        {
            f"{prefix}-note": "",
            f"{prefix}-access_end_seen": entry.access_end_recorded_at.isoformat(),
            f"{prefix}-submission": SUBMISSION,
            **_day(f"{prefix}-resumed", datetime.date(2026, 9, 2)),
        },
    )

    assert response.status_code == 302
    entry.refresh_from_db()
    assert entry.access_end_recorded_at is None


# --- remove and restore -----------------------------------------------------


def test_remove_confirms_then_removes(logged_in, entry, graph):
    url = reverse("games:remove_library_entry", args=[entry.pk])

    assert logged_in.get(url).status_code == 200
    response = logged_in.post(url + f"?origin={graph.game.get_absolute_url()}")

    assert response.status_code == 302
    entry.refresh_from_db()
    assert entry.removed_at is not None


def test_restore_puts_a_removed_copy_back(logged_in, entry):
    entry = remove_entry(entry)

    response = logged_in.post(reverse("games:restore_library_entry", args=[entry.pk]))

    assert response.status_code == 302
    entry.refresh_from_db()
    assert entry.removed_at is None


def test_the_page_a_post_renders_links_to_game_detail(logged_in, entry, graph):
    response = logged_in.post(_edit_url(entry), _edit_post(entry, access="lent"))

    html = response.content.decode()
    assert urlencode({"origin": graph.game.get_absolute_url()}) in html
    assert urlencode({"origin": _edit_url(entry)}) not in html
