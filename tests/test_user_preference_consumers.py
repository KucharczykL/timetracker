import re
from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from games.models import Device, Game, Platform, Purchase, Session, UserPreferences


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="tester", password="pw")


@pytest.fixture
def auth_client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def game(db):
    platform = Platform.objects.create(name="PC", icon="pc", group="PC")
    return Game.objects.create(name="Hades", platform=platform)


def _tag_with(html: str, **attributes: object) -> str:
    for tag in re.findall(r"<[^>]+>", html):
        if all(f'{name}="{value}"' in tag for name, value in attributes.items()):
            return tag
    raise AssertionError(f"No tag contains {attributes!r}")


@pytest.mark.parametrize(
    "url_name", ["games:add_purchase", "games:add_purchase_for_game"]
)
def test_purchase_add_forms_use_user_currency(auth_client, user, game, url_name):
    UserPreferences.objects.create(user=user, default_currency="EUR")
    args = [game.pk] if url_name.endswith("for_game") else []

    html = auth_client.get(reverse(url_name, args=args)).content.decode()

    currency_input = _tag_with(html, id="id_price_currency")
    assert 'value="EUR"' in currency_input
    assert 'placeholder="EUR"' in currency_input


def test_purchase_edit_uses_user_currency_only_when_existing_value_is_empty(
    auth_client, user, game
):
    UserPreferences.objects.create(user=user, default_currency="EUR")
    empty = Purchase.objects.create(
        date_purchased=date(2026, 1, 1), price_currency="USD"
    )
    empty.games.add(game)
    Purchase.objects.filter(pk=empty.pk).update(price_currency="")
    existing = Purchase.objects.create(
        date_purchased=date(2026, 1, 2),
        price_currency="GBP",
    )
    existing.games.add(game)

    empty_html = auth_client.get(
        reverse("games:edit_purchase", args=[empty.pk])
    ).content.decode()
    existing_html = auth_client.get(
        reverse("games:edit_purchase", args=[existing.pk])
    ).content.decode()

    assert 'value="EUR"' in _tag_with(empty_html, id="id_price_currency")
    assert 'value="GBP"' in _tag_with(existing_html, id="id_price_currency")


def test_purchase_edit_blank_currency_falls_back_to_user_currency(
    auth_client, user, game
):
    UserPreferences.objects.create(user=user, default_currency="EUR")
    purchase = Purchase.objects.create(
        date_purchased=date(2026, 1, 1), price_currency="USD"
    )
    purchase.games.add(game)

    response = auth_client.post(
        reverse("games:edit_purchase", args=[purchase.pk]),
        _purchase_post_data([game.pk], price_currency=""),
    )

    assert response.status_code == 302
    purchase.refresh_from_db()
    assert purchase.price_currency == "EUR"


def _purchase_post_data(game_ids: list[int], **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "games": game_ids,
        "platform": "",
        "date_purchased": "2026-01-01",
        "price": "10",
        "price_currency": "",
        "ownership_type": Purchase.DIGITAL,
        "type": Purchase.GAME,
        "name": "",
    }
    data.update(overrides)
    return data


def test_combined_purchase_save_falls_back_to_user_currency(auth_client, user, game):
    UserPreferences.objects.create(user=user, default_currency="EUR")

    response = auth_client.post(
        reverse("games:add_purchase"),
        _purchase_post_data([game.pk], pricing_mode="combined"),
    )

    assert response.status_code == 302
    assert Purchase.objects.get().price_currency == "EUR"


def test_separate_purchase_save_falls_back_to_user_currency(auth_client, user, game):
    second = Game.objects.create(name="Celeste", platform=game.platform)
    UserPreferences.objects.create(user=user, default_currency="EUR")

    response = auth_client.post(
        reverse("games:add_purchase"),
        _purchase_post_data(
            [game.pk, second.pk],
            pricing_mode="per_game",
            **{
                f"price_for_game_{game.pk}": "10",
                f"price_for_game_{second.pk}": "20",
            },
        ),
    )

    assert response.status_code == 302
    assert set(Purchase.objects.values_list("price_currency", flat=True)) == {"EUR"}


@pytest.mark.parametrize(
    "url_name", ["games:add_session", "games:add_session_for_game"]
)
def test_session_add_forms_use_user_device(auth_client, user, game, url_name):
    preferred = Device.objects.create(name="Steam Deck", type=Device.HANDHELD)
    UserPreferences.objects.create(user=user, default_device=preferred)
    args = [game.pk] if url_name.endswith("for_game") else []

    html = auth_client.get(reverse(url_name, args=args)).content.decode()

    _tag_with(html, name="device", value=preferred.pk)


def test_session_edit_uses_user_device_only_when_existing_value_is_empty(
    auth_client, user, game
):
    preferred = Device.objects.create(name="Steam Deck", type=Device.HANDHELD)
    existing_device = Device.objects.create(name="Desktop", type=Device.PC)
    UserPreferences.objects.create(user=user, default_device=preferred)
    empty = Session.objects.create(game=game, timestamp_start=timezone.now())
    existing = Session.objects.create(
        game=game,
        timestamp_start=timezone.now(),
        device=existing_device,
    )

    empty_html = auth_client.get(
        reverse("games:edit_session", args=[empty.pk])
    ).content.decode()
    existing_html = auth_client.get(
        reverse("games:edit_session", args=[existing.pk])
    ).content.decode()

    _tag_with(empty_html, name="device", value=preferred.pk)
    _tag_with(existing_html, name="device", value=existing_device.pk)
