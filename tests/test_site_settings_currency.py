"""The three DEFAULT_CURRENCY consumption sites read the live resolved value."""

from datetime import date

import pytest

from timetracker import config as config_module
from timetracker import settings_resolver
from timetracker.settings_resolver import set_site_setting


@pytest.fixture
def clean_currency_env(monkeypatch):
    monkeypatch.delenv("DEFAULT_CURRENCY", raising=False)
    monkeypatch.delenv("DEFAULT_CURRENCY__FILE", raising=False)
    config_module.reset_caches()
    settings_resolver.clear_cache()
    yield


@pytest.fixture
def game(db):
    from games.models import Game, Platform

    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    return Game.objects.create(name="Test Game", platform=platform)


def _set_currency(django_capture_on_commit_callbacks, value):
    with django_capture_on_commit_callbacks(execute=True):
        set_site_setting("DEFAULT_CURRENCY", value)


def test_purchase_save_uses_live_db_currency(
    game, clean_currency_env, django_capture_on_commit_callbacks
):
    from games.models import Purchase

    _set_currency(django_capture_on_commit_callbacks, "EUR")
    purchase = Purchase.objects.create(price=10, date_purchased=date(2025, 1, 1))
    purchase.games.add(game)
    assert purchase.price_currency == "EUR"

    _set_currency(django_capture_on_commit_callbacks, "GBP")
    later = Purchase.objects.create(price=10, date_purchased=date(2025, 1, 2))
    later.games.add(game)
    assert later.price_currency == "GBP"


def test_orm_default_no_longer_usd(game, clean_currency_env):
    from django.conf import settings

    from games.models import Purchase

    # No env, empty SiteSetting table → the config default (CZK), not "USD".
    purchase = Purchase.objects.create(price=10, date_purchased=date(2025, 1, 1))
    purchase.games.add(game)
    assert purchase.price_currency == settings.DEFAULT_CURRENCY
    assert purchase.price_currency != "USD"


def test_form_placeholder_tracks_live_currency(
    db, clean_currency_env, django_capture_on_commit_callbacks
):
    from games.forms import PurchaseForm

    _set_currency(django_capture_on_commit_callbacks, "EUR")
    placeholder = PurchaseForm().fields["price_currency"].widget.attrs["placeholder"]
    assert placeholder == "EUR"

    _set_currency(django_capture_on_commit_callbacks, "GBP")
    placeholder = PurchaseForm().fields["price_currency"].widget.attrs["placeholder"]
    assert placeholder == "GBP"


def test_convert_prices_targets_resolved_currency_identity(
    game, clean_currency_env, django_capture_on_commit_callbacks
):
    from games.models import Purchase
    from games.tasks import convert_prices

    _set_currency(django_capture_on_commit_callbacks, "EUR")
    purchase = Purchase.objects.create(
        price=50, price_currency="EUR", date_purchased=date(2025, 1, 1)
    )
    purchase.games.add(game)

    convert_prices()  # EUR == target → identity, no network

    purchase.refresh_from_db()
    assert purchase.converted_currency == "EUR"
    assert purchase.converted_price == 50


def test_convert_prices_targets_resolved_currency_with_rate(
    game, clean_currency_env, monkeypatch, django_capture_on_commit_callbacks
):
    from games.models import Purchase
    from games.tasks import convert_prices

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"usd": {"eur": 0.9}}

    monkeypatch.setattr(
        "games.tasks.requests.get", lambda *args, **kwargs: FakeResponse()
    )

    _set_currency(django_capture_on_commit_callbacks, "EUR")
    purchase = Purchase.objects.create(
        price=100, price_currency="USD", date_purchased=date(2025, 1, 1)
    )
    purchase.games.add(game)

    convert_prices()

    purchase.refresh_from_db()
    assert purchase.converted_currency == "EUR"
    assert purchase.converted_price == 90
