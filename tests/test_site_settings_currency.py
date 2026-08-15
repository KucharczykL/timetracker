"""Purchase entry and display currencies have separate live consumers."""

from datetime import date
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.models import Game, Platform, Purchase, UserPreferences
from timetracker import config as config_module
from timetracker import settings_resolver
from timetracker.settings_commands import change_site_setting

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


@pytest.fixture
def game(user):
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    return Game.objects.create(
        library=user.library,
        name="Test Game",
        platform=platform,
    )


def _set_currency(callbacks, key, value):
    with callbacks(execute=True):
        change_site_setting(key, value)


def test_purchase_form_preselection_tracks_live_entry_currency(
    user, clean_currency_env, django_capture_on_commit_callbacks
):
    from games.forms import PurchaseForm

    _set_currency(
        django_capture_on_commit_callbacks,
        "DEFAULT_PURCHASE_CURRENCY",
        "EUR",
    )
    form = PurchaseForm(
        library=user.library,
        user=user,
        presentation=_PRESENTATION,
    )
    assert form.initial["price_currency"] == "EUR"
    assert form.fields["price_currency"].widget.attrs["placeholder"] == "EUR"


def test_purchase_form_uses_personal_entry_currency(user, clean_currency_env):
    from games.forms import PurchaseForm

    UserPreferences.objects.filter(user=user).update(default_purchase_currency="GBP")
    settings_resolver.clear_cache()

    form = PurchaseForm(
        library=user.library,
        user=user,
        presentation=_PRESENTATION,
    )

    assert form.initial["price_currency"] == "GBP"


def test_purchase_form_requires_explicit_library_and_user_context(db):
    from games.forms import PurchaseForm

    with pytest.raises(TypeError):
        PurchaseForm(presentation=_PRESENTATION)


def test_purchase_model_never_resolves_a_hidden_currency(user):
    purchase = Purchase(
        library=user.library,
        price=10,
        date_purchased=date(2025, 1, 1),
        price_currency="",
    )

    with pytest.raises(ValidationError):
        purchase.save()


def test_convert_prices_targets_display_currency(
    user,
    game,
    clean_currency_env,
    django_capture_on_commit_callbacks,
):
    from games.models import PurchaseConversionState
    from games.tasks import convert_library_prices

    _set_currency(
        django_capture_on_commit_callbacks,
        "DEFAULT_DISPLAY_CURRENCY",
        "EUR",
    )
    purchase = Purchase.objects.create(
        library=user.library,
        price=50,
        price_currency="EUR",
        date_purchased=date(2025, 1, 1),
    )
    purchase.games.add(game)

    state = PurchaseConversionState.objects.get(library=user.library)
    convert_library_prices(str(user.library.pk), state.requested_version)

    purchase.refresh_from_db()
    assert purchase.converted_currency == "EUR"
    assert purchase.converted_price == 50
