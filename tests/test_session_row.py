import pytest
from django.urls import reverse
from django.utils import timezone

from common.components import TableRow
from games.models import Device, Game, Platform, Session
from games.views.session import session_row_data


@pytest.fixture
def running_session(db):
    platform = Platform.objects.create(name="PC")
    game = Game.objects.create(name="Celeste", platform=platform)
    device = Device.objects.create(name="Desktop")
    return Session.objects.create(
        game=game, device=device, timestamp_start=timezone.now()
    )


def render_row(session) -> str:
    device_list = Device.objects.order_by("name")
    return str(TableRow(session_row_data(session, device_list, "tok")))


def test_session_row_data_shape(running_session):
    device_list = Device.objects.order_by("name")
    data = session_row_data(running_session, device_list, "tok")
    assert len(data["cell_data"]) == 6
    assert ("id", f"session-row-{running_session.pk}") in data["attributes"]
    # No htmx row-swap wiring remains on the row.
    assert all(name != "hx-select" for name, _ in data["attributes"])


def test_session_row_renders_id_and_six_cells(running_session):
    html = render_row(running_session)
    assert f'id="session-row-{running_session.pk}"' in html
    assert html.count("<td") + html.count("<th") == 6


def test_running_session_finish_is_a_post_form(running_session):
    html = render_row(running_session)
    end_url = reverse("games:list_sessions_end_session", args=[running_session.pk])
    assert f'action="{end_url}"' in html
    assert 'method="post"' in html
    assert 'title="Finish session now"' in html
    assert "hx-target" not in html
    assert "hx-swap" not in html
