"""One legacy row to its copies."""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from games.backfill.purchase_plan import (
    Category,
    LegacyRow,
    legacy_refusals,
    plan,
    quantized_amount,
    split_cents,
)

GAMES = tuple(sorted(uuid.uuid7() for _ in range(3)))


def _row(**facts: object) -> LegacyRow:
    stated: dict[str, object] = {
        "id": uuid.uuid7(),
        "library_id": uuid.uuid7(),
        "game_ids": GAMES[:1],
        "platform_id": None,
        "platform_name": "",
        "date_purchased": date(2021, 5, 3),
        "date_refunded": None,
        "infinite": False,
        "price": 10.0,
        "price_currency": "EUR",
        "converted_price": None,
        "converted_currency": "",
        "ownership_type": "di",
        "type": "game",
        "name": "",
        "related_game_id": None,
        "removed_at": None,
    }
    stated.update(facts)
    return LegacyRow(**stated)  # type: ignore[arg-type]


def _minted():
    return uuid.uuid7()


@pytest.mark.parametrize(
    ("ownership", "platform", "access", "format"),
    [
        ("ph", "", "owned", "physical"),
        ("di", "", "owned", "digital"),
        ("du", "", "owned", "digital"),
        ("re", "Xbox Gamepass", "subscription", "digital"),
        ("re", "Xbox", "rented", "digital"),
        ("bo", "", "borrowed", "physical"),
        ("tr", "", "trial", "digital"),
        ("de", "", "demo", "digital"),
        ("pi", "", "pirated", "unknown"),
    ],
)
def test_access_and_format_follow_the_table(ownership, platform, access, format):
    [copy] = plan(
        _row(ownership_type=ownership, platform_name=platform), minted=_minted
    )
    assert (copy.access, copy.format) == (access, format)


def test_an_owned_free_row_is_free_on_epic_and_unknown_elsewhere():
    [epic] = plan(_row(price=0.0, platform_name="Epic Games Store"), minted=_minted)
    [steam] = plan(_row(price=0.0, platform_name="Steam"), minted=_minted)

    assert (epic.amount, epic.currency, epic.categories) == (
        Decimal("0.00"),
        "EUR",
        (Category.EPIC_FREE,),
    )
    assert (steam.amount, steam.currency, steam.categories) == (
        None,
        "",
        (Category.UNKNOWN_PRICE,),
    )
    assert epic.purchase_id is not None and steam.purchase_id is not None


def test_a_non_owned_row_has_a_purchase_only_with_an_amount():
    [free] = plan(_row(ownership_type="bo", price=0.0), minted=_minted)
    [paid] = plan(_row(ownership_type="re", price=4.0), minted=_minted)

    assert free.purchase_id is None
    assert paid.purchase_id is not None
    assert paid.categories == (Category.RENTAL,)


def test_a_bundle_splits_the_cents_in_key_order():
    row = _row(
        game_ids=GAMES,
        price=10.0,
        converted_price=250.0,
        converted_currency="CZK",
    )
    minted = [uuid.uuid7(), uuid.uuid7()]

    copies = plan(row, minted=iter(minted).__next__)

    assert [copy.game_id for copy in copies] == list(GAMES)
    assert [copy.amount for copy in copies] == [
        Decimal("3.34"),
        Decimal("3.33"),
        Decimal("3.33"),
    ]
    assert [copy.converted_share for copy in copies] == [
        Decimal("83.34"),
        Decimal("83.33"),
        Decimal("83.33"),
    ]
    assert [copy.purchase_id for copy in copies] == [row.id, *minted]
    assert all(Category.BUNDLE_SPLIT in copy.categories for copy in copies)


def test_a_digital_upgrade_is_an_attached_upgrade():
    [copy] = plan(_row(ownership_type="du"), minted=_minted)
    assert (copy.kind, copy.is_attached) == ("upgrade", True)


def test_a_dlc_row_buys_its_own_game_under_no_name():
    [copy] = plan(
        _row(type="dlc", name="Blood Money", related_game_id=GAMES[0]),
        minted=_minted,
    )
    assert (copy.kind, copy.name, copy.is_addon_game, copy.is_attached) == (
        "game",
        "",
        True,
        False,
    )
    assert Category.ADDON_GAME in copy.categories


def test_a_pass_keeps_its_kind_and_name_and_attaches():
    [copy] = plan(
        _row(type="season_pass", name="Year 1", related_game_id=GAMES[0]),
        minted=_minted,
    )
    assert (copy.kind, copy.name, copy.is_attached) == ("season_pass", "Year 1", True)


def test_an_amount_is_quantized_once_and_the_currency_upper_cased():
    [copy] = plan(_row(price=2.9925, price_currency="eur"), minted=_minted)
    assert (copy.amount, copy.currency) == (Decimal("2.99"), "EUR")
    assert Category.QUANTIZED in copy.categories


def test_quantizing_rounds_half_up_from_the_float_s_shortest_spelling():
    assert quantized_amount(1.005) == Decimal("1.01")
    assert quantized_amount(1.0725) == Decimal("1.07")


def test_split_gives_the_remainder_to_the_first():
    assert split_cents(Decimal("0.05"), 3) == [
        Decimal("0.02"),
        Decimal("0.02"),
        Decimal("0.01"),
    ]


def test_days_and_demos_carry_over():
    [copy] = plan(
        _row(ownership_type="de", date_refunded=date(2021, 5, 4)), minted=_minted
    )
    assert copy.purchased.serialize() == "2021-05-03"
    assert copy.refunded is not None and copy.refunded.serialize() == "2021-05-04"
    assert Category.DEMO_EDITION in copy.categories


@pytest.mark.parametrize(
    "facts",
    [
        {"game_ids": ()},
        {"type": "dlc", "name": "Blood Money", "related_game_id": None},
        {"type": "season_pass", "game_ids": GAMES[:2], "related_game_id": GAMES[0]},
        {"type": "dlc", "name": "  ", "related_game_id": GAMES[0]},
        {"price": float("nan")},
        {"price": float("inf")},
        {"converted_price": float("nan")},
    ],
    ids=[
        "no game",
        "add-on without base",
        "add-on with two games",
        "blank add-on name",
        "NaN price",
        "infinite price",
        "NaN converted",
    ],
)
def test_rows_no_rule_converts_are_refused(facts):
    assert legacy_refusals(_row(**facts))


def test_an_upgrade_without_a_base_is_no_refusal():
    assert legacy_refusals(_row(ownership_type="du")) == []
