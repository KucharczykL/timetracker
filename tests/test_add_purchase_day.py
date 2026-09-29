"""Add Purchase offers the library's day."""

import pytest
from calendar_days import displace_calendar, process_day
from django.urls import reverse

from games.reads.calendar import calendar_today

#: Transactional: displacing the calendar dispatches.
pytestmark = pytest.mark.django_db(transaction=True)


def test_the_offered_day_is_the_calendars(client, owned_user, owned_library):
    client.force_login(owned_user)
    displace_calendar(owned_library)

    body = client.get(reverse("games:add_purchase")).content.decode()

    assert f'value="{calendar_today(owned_library).isoformat()}"' in body
    assert f'value="{process_day().isoformat()}"' not in body
