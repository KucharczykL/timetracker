"""The Devices list states each device's access."""

import json

import pytest
from devices import create_device, end_device_access
from django.urls import reverse

from games.end_ways import EndWay
from games.filters import DeviceFilter, filter_query_context_for_library
from games.models import Device
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def devices(owned_library):
    create_device(owned_library, "Deck")
    end_device_access(
        create_device(owned_library, "Switch"),
        way=EndWay.SOLD,
        when=TemporalValue.parse("2021-05"),
    )
    end_device_access(create_device(owned_library, "Phone"), way=EndWay.LOST)
    end_device_access(
        create_device(owned_library, "Wii"),
        way=EndWay.GIVEN_AWAY,
        when=TemporalValue.parse("2019"),
    )


@pytest.fixture
def logged_in(client, owned_user):
    client.force_login(owned_user)
    return client


def matched(library, filter_object) -> set[str]:
    return set(
        Device.objects.for_library(library)
        .filter(filter_object.to_q(filter_query_context_for_library(library)))
        .values_list("name", flat=True)
    )


def _row(body: str, name: str) -> str:
    """The table row naming one device."""
    start = body.rindex("<tr", 0, body.index(f">{name}<"))
    return body[start : body.index("</tr>", start)]


def _list(client, **query) -> str:
    return client.get(reverse("games:list_devices"), query).content.decode()


def test_the_access_column_reads_held_or_the_way_and_its_day(logged_in, devices):
    body = _list(logged_in)

    assert ">Access<" in body
    assert _row(body, "Deck").count(">Held<") == 1
    assert "Sold · May 2021" in _row(body, "Switch")
    assert ">Lost<" in _row(body, "Phone")


def test_the_facets_narrow_by_the_act_and_by_the_way(owned_library, devices):
    ended = matched(owned_library, DeviceFilter.where(is_owned=False))
    held = matched(owned_library, DeviceFilter.where(is_owned=True))
    sold = matched(owned_library, DeviceFilter.where(access_end_way=["sold"]))

    assert (ended, held, sold) == ({"Switch", "Phone", "Wii"}, {"Deck"}, {"Switch"})


def test_the_end_filters_as_the_interval_its_day_states(owned_library, devices):
    in_2021 = DeviceFilter.where(access_ended__between=("2021-01-01", "2021-12-31"))

    assert matched(owned_library, in_2021) == {"Switch"}


def test_the_facets_keep_the_bar_editable(logged_in, devices):
    applied = json.dumps(
        {
            "is_owned": {"value": False, "modifier": "EQUALS"},
            "access_end_way": {"value": ["sold"], "modifier": "INCLUDES"},
        }
    )

    body = _list(logged_in, filter=applied)

    assert "Advanced filter active" not in body
    assert "Switch" in body
    assert "Phone" not in body


@pytest.mark.parametrize("direction", ["access", "-access"])
def test_devices_with_no_day_sort_last_both_ways(
    logged_in, owned_library, devices, direction
):
    body = _list(logged_in, sort=direction)

    at = {
        device.name: body.index(f'"{device.pk}"')
        for device in Device.objects.filter(library=owned_library)
    }
    earlier, later = ("Wii", "Switch") if direction == "access" else ("Switch", "Wii")
    assert at[earlier] < at[later]
    #: No day: held, or left undated.
    assert min(at["Deck"], at["Phone"]) > max(at["Wii"], at["Switch"])


def test_the_builder_offers_the_access_leaves(logged_in):
    body = logged_in.get(
        reverse("games:filter_builder", args=["device"])
    ).content.decode()

    assert "access_end_way" in body
    assert "is_owned" in body
