import pytest
from django.utils import timezone

from games.models import Device, Game, Platform, Session
from games.views.session import session_row, session_row_data


@pytest.fixture
def running_session(db):
    platform = Platform.objects.create(name="PC")
    game = Game.objects.create(name="Celeste", platform=platform)
    device = Device.objects.create(name="Desktop")
    return Session.objects.create(
        game=game, device=device, timestamp_start=timezone.now()
    )


def test_session_row_data_shape(running_session):
    device_list = Device.objects.order_by("name")
    data = session_row_data(running_session, device_list, "tok")
    assert len(data["cell_data"]) == 6
    assert ("id", f"session-row-{running_session.pk}") in data["attributes"]
    assert ("hx-select", f"#session-row-{running_session.pk}") in data["attributes"]


def test_session_row_renders_id_and_six_cells(running_session):
    device_list = Device.objects.order_by("name")
    html = str(session_row(running_session, device_list, "tok"))
    assert f'id="session-row-{running_session.pk}"' in html
    assert html.count("<td") + html.count("<th") == 6


def test_running_session_finish_button_targets_row(running_session):
    device_list = Device.objects.order_by("name")
    html = str(session_row(running_session, device_list, "tok"))
    assert f'hx-target="#session-row-{running_session.pk}"' in html
    assert 'hx-swap="outerHTML"' in html
