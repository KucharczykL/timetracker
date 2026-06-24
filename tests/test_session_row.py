import pytest
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


def test_running_session_actions_drive_the_api(running_session):
    html = render_row(running_session)
    # Finish/reset are now JS-driven via the <session-actions> custom element
    # hitting PATCH /api/session/<id>, not no-JS POST forms / confirm-page links.
    assert "<session-actions" in html
    assert f'api-url="/api/session/{running_session.pk}"' in html
    assert "data-finish" in html
    assert "data-reset" in html
    assert "data-reset-modal" in html
    assert 'title="Finish session now"' in html
    assert 'method="post"' not in html
    assert "hx-target" not in html
    assert "hx-swap" not in html


def test_finished_session_has_no_finish_or_reset(running_session):
    running_session.timestamp_end = timezone.now()
    running_session.save()
    html = render_row(running_session)
    assert "data-finish" not in html
    assert "data-reset" not in html
    assert "data-reset-modal" not in html
