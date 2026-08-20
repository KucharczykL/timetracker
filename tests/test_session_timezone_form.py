"""SessionForm zone binding and the FormFields embedded-row mechanism."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from django import forms

from common.components import FormFields
from common.components.core import render
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.forms import SESSION_TIMEZONE_EMBEDS, SessionForm
from games.models import Game, Session

pytestmark = pytest.mark.django_db

_PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("Europe/Prague")
)


@pytest.fixture
def library(django_user_model):
    return django_user_model.objects.create_user(username="session-zone-form").library


def _form_data(game: Game, **overrides) -> dict[str, str]:
    data = {
        "game": str(game.pk),
        "timestamp_start": "2026-07-01T21:00:00+09:00",
        "timestamp_start_timezone": "Asia/Tokyo",
        "timestamp_end": "",
        "timestamp_end_timezone": "",
        "duration_manual": "",
        "device": "",
        "note": "",
    }
    data.update(overrides)
    return data


def test_zone_binds_to_the_model_and_empty_cleans_to_null(library):
    game = Game.objects.create(library=library, name="Hades")
    form = SessionForm(
        data=_form_data(game), library=library, presentation=_PRESENTATION
    )
    assert form.is_valid(), form.errors
    session = form.save()
    session.refresh_from_db()
    assert session.timestamp_start_timezone == "Asia/Tokyo"
    assert session.timestamp_end_timezone is None


def test_invalid_zone_is_a_form_error(library):
    game = Game.objects.create(library=library, name="Hades")
    form = SessionForm(
        library=library,
        data=_form_data(game, timestamp_start_timezone="Not/AZone"),
        presentation=_PRESENTATION,
    )
    assert not form.is_valid()
    assert "timestamp_start_timezone" in form.errors


def test_unbound_add_form_captures_the_start_zone_only(library):
    """Both rows render, but only the start captures: an open session's end
    timestamp is committed later, in a zone this page cannot know."""
    form = SessionForm(library=library, presentation=_PRESENTATION)
    assert form.instance.pk is not None
    assert form.instance._state.adding
    html = render(FormFields(form, embedded=SESSION_TIMEZONE_EMBEDS))
    assert html.count("<time-zone-row") == 2
    assert html.count('capture-default="true"') == 1
    assert html.count('capture-default="false"') == 1
    assert 'display-zone="Europe/Prague"' in html


def test_an_end_timestamp_on_the_add_form_captures_its_zone_too(library):
    """A retroactive add (or a duration shortcut that pre-fills the end)
    commits both timestamps now, so both capture."""
    form = SessionForm(
        library=library,
        presentation=_PRESENTATION,
        initial={"timestamp_end": datetime(2026, 7, 1, 14, 0, tzinfo=UTC)},
    )
    html = render(FormFields(form, embedded=SESSION_TIMEZONE_EMBEDS))
    assert html.count('capture-default="true"') == 2


def test_edit_form_carries_the_stored_zone_without_recapture(library):
    game = Game.objects.create(library=library, name="Hades")
    session = Session.objects.create(
        game=game,
        timestamp_start=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        timestamp_start_timezone="Asia/Tokyo",
    )
    form = SessionForm(instance=session, library=library, presentation=_PRESENTATION)
    html = render(FormFields(form, embedded=SESSION_TIMEZONE_EMBEDS))
    assert 'stored-zone="Asia/Tokyo"' in html
    assert html.count('capture-default="false"') == 2


def test_embedded_field_renders_in_its_host_row_not_its_own(library):
    form = SessionForm(library=library, presentation=_PRESENTATION)
    html = render(FormFields(form, embedded=SESSION_TIMEZONE_EMBEDS))
    # No standalone label row for the zone fields; the widget's own trigger
    # carries the accessible label.
    assert "Timestamp start timezone" not in html
    # The row markup appears exactly once per field (no double render). A
    # leading space disambiguates the hidden input's `name=` from the
    # element's own `field-name=` attribute, which contains the same substring.
    assert html.count(' name="timestamp_start_timezone"') == 1


def test_form_fields_embedded_rejects_unknown_names():
    class TinyForm(forms.Form):
        name = forms.CharField()

    with pytest.raises(ValueError):
        FormFields(TinyForm(), embedded={"missing": "name"})
    with pytest.raises(ValueError):
        FormFields(TinyForm(), embedded={"name": "missing"})
