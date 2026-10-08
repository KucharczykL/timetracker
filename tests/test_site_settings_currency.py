"""Purchase entry and display currencies have separate live consumers."""

from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from entries import record_entry
from graphs import default_graph
from purchases import record_purchase

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.models import Game, UserPreferences
from games.purchase_forms import PurchaseAddForm
from timetracker import config as config_module
from timetracker import settings_resolver
from timetracker.settings_commands import change_site_setting
from timetracker.temporal import TemporalValue

_PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


@pytest.fixture
def clean_currency_env(monkeypatch):
    for key in ("DEFAULT_PURCHASE_CURRENCY", "DEFAULT_DISPLAY_CURRENCY"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(f"{key}__FILE", raising=False)
    config_module.reset_caches()
    settings_resolver.clear_cache()
    yield


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="currency-user")


def _set_currency(callbacks, key, value):
    with callbacks(execute=True):
        change_site_setting(key, value)


def _purchase_form(user) -> PurchaseAddForm:
    return PurchaseAddForm(
        library=user.library, presentation=_PRESENTATION, today=date(2025, 1, 1)
    )


def test_purchase_form_preselection_tracks_live_entry_currency(
    user, clean_currency_env, django_capture_on_commit_callbacks
):
    _set_currency(
        django_capture_on_commit_callbacks,
        "DEFAULT_PURCHASE_CURRENCY",
        "EUR",
    )
    form = _purchase_form(user)
    assert form.initial["currency"] == "EUR"
    assert form.fields["currency"].widget.attrs["placeholder"] == "EUR"


def test_purchase_form_uses_personal_entry_currency(user, clean_currency_env):
    UserPreferences.objects.filter(user=user).update(default_purchase_currency="GBP")
    settings_resolver.clear_cache()

    assert _purchase_form(user).initial["currency"] == "GBP"


def test_purchase_form_requires_explicit_library_context(db):
    with pytest.raises(TypeError):
        PurchaseAddForm(presentation=_PRESENTATION, today=date(2025, 1, 1))


def test_convert_prices_targets_display_currency(
    user,
    clean_currency_env,
    django_capture_on_commit_callbacks,
):
    from games.models import PurchaseConversionState, PurchaseValuation
    from games.tasks import convert_library_prices

    _set_currency(
        django_capture_on_commit_callbacks,
        "DEFAULT_DISPLAY_CURRENCY",
        "EUR",
    )
    graph = default_graph(Game(library=user.library, name="Tunic"), user.library)
    purchase = record_purchase(
        record_entry(user.library, graph.release),
        amount=Decimal("50.00"),
        currency="EUR",
        purchased=TemporalValue.parse("2025-01-01"),
    )

    state = PurchaseConversionState.objects.get(library=user.library)
    convert_library_prices(str(user.library.pk), state.requested_version)

    valuation = PurchaseValuation.objects.get(purchase_id=purchase.pk)
    assert valuation.target_currency == "EUR"
    assert valuation.amount == Decimal("50.00")
