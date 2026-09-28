"""Device pages: add, edit, remove, restore."""

import pytest
from devices import create_device, end_device_access, remove_device
from django.urls import reverse

from games.models import Device, LibraryEvent
from games.writes.answers import CONFLICT_STATUS, CommandFailed
from timetracker.temporal import temporal_input_name

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def _device_events(device: Device) -> list[str]:
    return list(
        LibraryEvent.objects.filter(aggregate_id=device.pk)
        .order_by("sequence")
        .values_list("event_type", flat=True)
    )


def test_adding_states_a_creation(logged_in, owned_library):
    response = logged_in.post(
        reverse("games:add_device"),
        {"name": " Steam Deck ", "type": Device.HANDHELD, "submission": "0" * 32},
    )

    assert response.status_code == 302
    device = Device.objects.get()
    assert (device.library, device.name, device.type) == (
        owned_library,
        "Steam Deck",
        Device.HANDHELD,
    )
    assert _device_events(device) == ["library.device.created"]


def test_a_submit_posted_twice_creates_one_device(logged_in):
    posted = {"name": "Deck", "type": Device.PC, "submission": "1" * 32}

    logged_in.post(reverse("games:add_device"), posted)
    logged_in.post(reverse("games:add_device"), posted)

    assert Device.objects.count() == 1


def test_the_add_page_renders_a_fresh_submission(logged_in):
    first = logged_in.get(reverse("games:add_device")).content.decode()
    second = logged_in.get(reverse("games:add_device")).content.decode()

    marker = 'name="submission" value="'
    assert marker in first
    assert first.split(marker)[1][:36] != second.split(marker)[1][:36]


def test_editing_states_each_differing_fact(logged_in, owned_library):
    device = create_device(owned_library, "Deck", Device.UNKNOWN)

    edit = logged_in.get(reverse("games:edit_device", args=[device.pk]))
    assert 'value="Deck"' in edit.content.decode()
    assert 'name="submission"' not in edit.content.decode()

    response = logged_in.post(
        reverse("games:edit_device", args=[device.pk]),
        {"name": "Steam Deck", "type": Device.UNKNOWN},
    )

    assert response.status_code == 302
    device.refresh_from_db()
    assert device.name == "Steam Deck"
    assert _device_events(device) == [
        "library.device.created",
        "library.device.name_changed",
    ]


def test_a_refused_edit_is_a_sentence_on_the_form(
    logged_in, owned_library, monkeypatch
):
    device = create_device(owned_library, "Deck")

    def refuse(*args, **kwargs):
        raise CommandFailed("That device cannot be named so.", CONFLICT_STATUS)

    monkeypatch.setattr("games.views.device.restate_device", refuse)

    response = logged_in.post(
        reverse("games:edit_device", args=[device.pk]),
        {"name": "Steam Deck", "type": Device.PC},
    )

    assert response.status_code == CONFLICT_STATUS
    assert "That device cannot be named so." in response.content.decode()
    device.refresh_from_db()
    assert device.name == "Deck"


def test_removing_and_restoring_state_their_events(logged_in, owned_library):
    device = create_device(owned_library, "Deck")

    logged_in.post(reverse("games:remove_device", args=[device.pk]))
    device.refresh_from_db()
    assert device.removed_at is not None

    logged_in.post(reverse("games:restore_device", args=[device.pk]))
    device.refresh_from_db()
    assert device.removed_at is None
    assert _device_events(device) == [
        "library.device.created",
        "library.device.removed",
        "library.device.restored",
    ]


def test_a_removed_device_cannot_be_edited(logged_in, owned_library):
    device = remove_device(create_device(owned_library, "Deck"))

    response = logged_in.get(reverse("games:edit_device", args=[device.pk]))

    assert response.status_code == 404


def _access(way: str, *, year: str = "", month: str = "", note: str = "") -> dict:
    posted = {"access": way, "access_note": note}
    if year:
        posted[temporal_input_name("access_day", "kind")] = "date"
        posted[temporal_input_name("access_day", "start_year")] = year
        posted[temporal_input_name("access_day", "start_month")] = month
    return posted


def _edit(client, device: Device, **access):
    return client.post(
        reverse("games:edit_device", args=[device.pk]),
        {"name": device.name, "type": device.type, **_access(**access)},
    )


def test_editing_to_sold_states_the_end(logged_in, owned_library):
    device = create_device(owned_library, "Deck", Device.HANDHELD)

    response = _edit(logged_in, device, way="sold", year="2021", month="5", note="x")

    assert response.status_code == 302
    device.refresh_from_db()
    assert (
        device.access_end_way,
        device.access_ended.canonical,
        device.access_end_note,
    ) == (
        "sold",
        "2021-05",
        "x",
    )
    assert _device_events(device)[-1] == "library.device.access_ended"


def test_the_edit_page_shows_the_stated_end(logged_in, owned_library):
    device = create_device(owned_library, "Deck", Device.HANDHELD)
    _edit(logged_in, device, way="lost", note="on a train")

    page = logged_in.get(reverse("games:edit_device", args=[device.pk]))

    body = page.content.decode()
    assert '<option value="lost" selected>' in body
    assert "on a train" in body


def test_another_way_corrects_and_held_voids(logged_in, owned_library):
    device = create_device(owned_library, "Deck", Device.HANDHELD)
    _edit(logged_in, device, way="sold")
    device.refresh_from_db()
    marker = device.access_end_recorded_at

    _edit(logged_in, device, way="lost")
    device.refresh_from_db()
    assert (device.access_end_way, device.access_end_recorded_at) == ("lost", marker)

    _edit(logged_in, device, way="")
    device.refresh_from_db()
    assert device.access_end_recorded_at is None
    assert _device_events(device)[-2:] == [
        "library.device.access_end_corrected",
        "library.device.access_end_voided",
    ]


def test_a_rename_and_an_end_share_one_correlation(logged_in, owned_library):
    device = create_device(owned_library, "Deck", Device.HANDHELD)

    logged_in.post(
        reverse("games:edit_device", args=[device.pk]),
        {"name": "Steam Deck", "type": device.type, **_access("stolen")},
    )

    events = list(
        LibraryEvent.objects.filter(aggregate_id=device.pk).order_by("sequence")
    )
    #: The end first: a refusal of it leaves no rename.
    assert [event.event_type for event in events] == [
        "library.device.created",
        "library.device.access_ended",
        "library.device.name_changed",
    ]
    assert events[1].correlation_id == events[2].correlation_id


def test_a_refused_end_sends_no_rename(logged_in, owned_library, monkeypatch):
    device = create_device(owned_library, "Deck", Device.HANDHELD)
    #: A racer ends access between the page's read and the save.
    monkeypatch.setattr(
        "games.writes.device.stated", lambda row, endpoint: None, raising=True
    )
    end_device_access(device)

    response = logged_in.post(
        reverse("games:edit_device", args=[device.pk]),
        {"name": "Steam Deck", "type": device.type, **_access("lost")},
    )

    assert response.status_code == CONFLICT_STATUS
    assert "already has an end recorded" in response.content.decode()
    device.refresh_from_db()
    assert device.name == "Deck"


def test_saving_an_ended_device_unchanged_appends_nothing(logged_in, owned_library):
    device = create_device(owned_library, "Deck", Device.HANDHELD)
    _edit(logged_in, device, way="sold", year="2021", month="5", note="one\r\ntwo")
    before = _device_events(device)

    _edit(logged_in, device, way="sold", year="2021", month="5", note="one\r\ntwo")

    assert _device_events(device) == before


def test_a_day_on_a_held_device_asks_for_a_way(logged_in, owned_library):
    device = create_device(owned_library, "Deck", Device.HANDHELD)

    response = _edit(logged_in, device, way="", note="sold it")

    assert response.status_code == 200
    assert "Choose how the device left" in response.content.decode()
    assert _device_events(device) == ["library.device.created"]


def test_held_takes_the_day_and_note_it_shows_with_it(logged_in, owned_library):
    device = create_device(owned_library, "Deck", Device.HANDHELD)
    _edit(logged_in, device, way="sold", year="2021", month="5", note="x")

    response = _edit(logged_in, device, way="", year="2021", month="5", note="x")

    assert response.status_code == 302
    assert _device_events(device)[-1] == "library.device.access_end_voided"


def test_adding_a_device_that_already_left(logged_in):
    logged_in.post(
        reverse("games:add_device"),
        {
            "name": "Wii",
            "type": Device.CONSOLE,
            "submission": "2" * 32,
            **_access("given_away", year="2015"),
        },
    )

    device = Device.objects.get()
    assert _device_events(device) == [
        "library.device.created",
        "library.device.access_ended",
    ]
    assert device.access_ended.canonical == "2015"
