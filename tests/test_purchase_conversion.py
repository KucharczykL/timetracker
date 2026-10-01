"""The purchase conversion pass over legacy rows."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.db import connection, transaction
from entries import record_entry
from purchases import _state

from games.backfill import purchase as conversion
from games.backfill.purchase import (
    PurchaseConversionRefused,
    convert_purchases,
    legacy_rows,
)
from games.backfill.purchase_plan import Category
from games.commands.purchase import VoidPurchaseRefund
from games.models import (
    EditionKind,
    ExchangeRate,
    Game,
    GameKind,
    LegacyPurchase,
    LibraryEntry,
    LibraryEvent,
    Platform,
    PlayerGame,
    Purchase,
    PurchaseConversionState,
    PurchaseValuation,
    Release,
)
from games.reads.purchases import refund_owns_the_end, stale_purchases
from games.removal import remove

pytestmark = [pytest.mark.django_db, pytest.mark.untracked_games]

INSTANT = datetime(2026, 10, 1, 12, tzinfo=UTC)
DAY = date(2021, 5, 3)


@pytest.fixture(autouse=True)
def no_stored_rates():
    ExchangeRate.objects.all().delete()


@pytest.fixture
def steam():
    return Platform.objects.create(name="Steam", group="PC")


@pytest.fixture
def game_on(owned_library, stated_graph, steam):
    def make(name: str, library=owned_library, platform=steam) -> Game:
        return stated_graph(
            Game(name=name, library=library), library, platform=platform
        ).game

    return make


def legacy(library, *games, **facts) -> LegacyPurchase:
    stated = {
        "library": library,
        "date_purchased": DAY,
        "price": 10.0,
        "price_currency": "EUR",
        "ownership_type": LegacyPurchase.DIGITAL,
    }
    stated.update(facts)
    row = LegacyPurchase.objects.create(**stated)
    row.games.add(*games)
    return row


def convert(library=None):
    rows = legacy_rows(LegacyPurchase, None if library is None else library.pk)
    return convert_purchases(rows, recorded_at=INSTANT)


def entries_of(game) -> list[LibraryEntry]:
    return list(LibraryEntry.objects.filter(player_game__game=game).order_by("pk"))


def test_the_reader_names_games_in_key_order_and_the_platform(
    owned_library, game_on, steam
):
    first, second = sorted([game_on("Tunic"), game_on("Hades")], key=lambda g: g.pk)
    row = legacy(owned_library, second, first, platform=steam)

    [read] = legacy_rows(LegacyPurchase)

    assert (read.id, read.game_ids, read.platform_name) == (
        row.pk,
        (first.pk, second.pk),
        "Steam",
    )


def test_a_game_row_states_one_copy_and_one_purchase(owned_library, game_on):
    game = game_on("Tunic")
    row = legacy(owned_library, game, price=19.99)

    done = convert()

    [entry] = entries_of(game)
    purchase = Purchase.objects.get(pk=row.pk)
    assert (entry.access, entry.format, entry.acquired.serialize()) == (
        "owned",
        "digital",
        "2021-05-03",
    )
    assert (purchase.entry_id, purchase.amount, purchase.currency) == (
        entry.pk,
        Decimal("19.99"),
        "EUR",
    )
    created = LibraryEvent.objects.get(aggregate_id=row.pk)
    assert created.recorded_at == INSTANT
    assert created.source_metadata["origin"] == "conversion"
    assert created.source_metadata["legacy_purchases"] == [str(row.pk)]
    assert done.appended > 0


def test_a_second_run_appends_nothing(owned_library, game_on):
    legacy(owned_library, game_on("Tunic"), date_refunded=date(2021, 5, 4))
    convert()
    events = LibraryEvent.objects.count()

    again = convert()

    assert again.appended == 0
    assert LibraryEvent.objects.count() == events


def test_a_rerun_after_a_new_legacy_row_converts_only_it(owned_library, game_on):
    legacy(owned_library, game_on("Tunic"))
    convert()
    later = legacy(owned_library, game_on("Hades"))

    convert()

    assert Purchase.objects.filter(pk=later.pk).exists()
    assert Purchase.objects.count() == 2


def test_a_refunded_game_row_owns_its_copy_end(owned_library, game_on):
    game = game_on("Tunic")
    row = legacy(owned_library, game, date_refunded=date(2021, 5, 4))

    convert()

    purchase = Purchase.objects.get(pk=row.pk)
    [entry] = entries_of(game)
    assert purchase.refunded.serialize() == "2021-05-04"
    assert entry.access_end_way == "refunded"
    assert refund_owns_the_end(owned_library, purchase)
    _state(owned_library, VoidPurchaseRefund(purchase_id=purchase.pk))
    entry.refresh_from_db()
    assert entry.access_end_recorded_at is None


def test_a_refunded_rental_ends_its_copy_by_hand(owned_library, game_on):
    game = game_on("Tunic")
    row = legacy(
        owned_library,
        game,
        ownership_type=LegacyPurchase.RENTED,
        price=4.0,
        date_refunded=date(2021, 5, 4),
    )

    convert()

    [entry] = entries_of(game)
    assert (entry.access, entry.access_end_way) == ("rented", "refunded")
    assert not refund_owns_the_end(owned_library, Purchase.objects.get(pk=row.pk))


def test_a_borrowed_copy_at_no_price_has_no_purchase(owned_library, game_on):
    game = game_on("Tunic")
    legacy(owned_library, game, ownership_type=LegacyPurchase.BORROWED, price=0.0)

    convert()

    [entry] = entries_of(game)
    assert entry.access == "borrowed"
    assert not Purchase.objects.exists()


def test_a_bundle_splits_into_one_purchase_per_game(owned_library, game_on):
    games = sorted([game_on(name) for name in ("A", "B", "C")], key=lambda g: g.pk)
    row = legacy(owned_library, *games, price=10.0)

    convert()

    purchases = [Purchase.objects.get(entry__player_game__game=game) for game in games]
    assert [purchase.amount for purchase in purchases] == [
        Decimal("3.34"),
        Decimal("3.33"),
        Decimal("3.33"),
    ]
    assert purchases[0].pk == row.pk
    review = LibraryEvent.objects.get(aggregate_id=purchases[1].pk).source_metadata
    assert Category.BUNDLE_SPLIT in review["review"]


def test_a_dlc_row_states_its_own_game_under_the_base(owned_library, game_on, steam):
    base = game_on("Hitman")
    legacy(owned_library, base)
    legacy(
        owned_library,
        base,
        type=LegacyPurchase.DLC,
        name="Blood Money",
        related_game=base,
        infinite=True,
    )

    convert()

    dlc = Game.objects.get(parent=base)
    assert (dlc.kind, dlc.name, dlc.sort_name, dlc.library) == (
        GameKind.DLC,
        "Blood Money",
        "Blood Money",
        owned_library,
    )
    [entry] = entries_of(dlc)
    assert entry.release.platform == steam
    purchase = Purchase.objects.get(entry=entry)
    assert (purchase.kind, purchase.name) == ("game", "")
    for game in (base, dlc):
        tracked = PlayerGame.objects.get(game=game)
        assert tracked.excluded_from_unfinished and tracked.excluded_from_dropped
    convert()
    assert Game.objects.filter(parent=base).count() == 1


def test_a_demo_states_a_prerelease_edition(owned_library, game_on):
    game = game_on("Tunic")
    legacy(owned_library, game, ownership_type=LegacyPurchase.DEMO, price=0.0)

    convert()

    [entry] = entries_of(game)
    edition = entry.release.edition
    assert (edition.name, edition.kind, entry.access) == (
        "Demo",
        EditionKind.PRERELEASE,
        "demo",
    )


def test_another_platform_states_one_release_reused(owned_library, game_on):
    game = game_on("Tunic")
    switch = Platform.objects.create(name="Switch", group="Nintendo")
    first = legacy(owned_library, game, platform=switch)
    legacy(owned_library, game, platform=switch, date_purchased=date(2022, 1, 1))

    convert()

    copies = entries_of(game)
    assert len(copies) == 2
    assert {copy.release.platform for copy in copies} == {switch}
    assert len({copy.release_id for copy in copies}) == 1
    review = LibraryEvent.objects.get(aggregate_id=first.pk).source_metadata
    assert Category.CREATED_RELEASE in review["review"]


def test_a_pass_takes_the_live_base_copy(owned_library, game_on):
    game = game_on("Destiny")
    legacy(owned_library, game, date_refunded=date(2021, 5, 4))
    kept = legacy(owned_library, game, date_purchased=date(2021, 6, 1))
    season = legacy(
        owned_library,
        game,
        type=LegacyPurchase.SEASONPASS,
        name="Year 1",
        related_game=game,
        date_purchased=date(2021, 4, 1),
    )

    convert()

    kept_copy = Purchase.objects.get(pk=kept.pk).entry_id
    pass_purchase = Purchase.objects.get(pk=season.pk)
    assert pass_purchase.entry_id == kept_copy
    assert (pass_purchase.kind, pass_purchase.name) == ("season_pass", "Year 1")


def test_a_pass_without_a_base_copy_and_the_upgrade_get_their_own(
    owned_library, game_on
):
    destiny, cyberpunk = game_on("Destiny"), game_on("Cyberpunk")
    season = legacy(
        owned_library,
        destiny,
        type=LegacyPurchase.SEASONPASS,
        name="Year 1",
        related_game=destiny,
    )
    upgrade = legacy(
        owned_library, cyberpunk, ownership_type=LegacyPurchase.DIGITALUPGRADE
    )

    convert()

    assert Purchase.objects.get(pk=season.pk).entry.player_game.game == destiny
    upgraded = Purchase.objects.get(pk=upgrade.pk)
    assert (upgraded.kind, upgraded.entry.access) == ("upgrade", "owned")


def test_a_mixed_infinite_game_is_tagged_and_excluded(owned_library, game_on):
    game = game_on("Tunic")
    infinite = legacy(owned_library, game, infinite=True)
    legacy(owned_library, game, date_purchased=date(2022, 1, 1))

    convert()

    tracked = PlayerGame.objects.get(game=game)
    assert tracked.excluded_from_unfinished and tracked.excluded_from_dropped
    review = LibraryEvent.objects.get(aggregate_id=infinite.pk).source_metadata
    assert Category.MIXED_INFINITE in review["review"]


def test_a_removed_legacy_row_removes_its_purchase_and_copy(owned_library, game_on):
    game = game_on("Tunic")
    row = legacy(owned_library, game)
    remove(row)

    convert()

    assert Purchase.objects.get(pk=row.pk).removed_at is not None
    [entry] = entries_of(game)
    assert entry.removed_at is not None


def test_a_removed_game_is_skipped(owned_library, game_on):
    game = game_on("Tunic")
    row = legacy(owned_library, game)
    legacy(owned_library, game_on("Hades"))
    remove(game)

    done = convert()

    assert [(skip.legacy_id, skip.game_id) for skip in done.libraries[0].skipped] == [
        (row.pk, game.pk)
    ]
    assert not entries_of(game)


def test_a_hand_recorded_copy_gets_a_second_copy(owned_library, game_on):
    game = game_on("Tunic")
    release = Release.objects.get(edition__game=game)
    record_entry(owned_library, release)
    row = legacy(owned_library, game)

    convert()

    assert len(entries_of(game)) == 2
    review = LibraryEvent.objects.get(aggregate_id=row.pk).source_metadata
    assert Category.HAND_RECORDED_COPY in review["review"]


def test_only_the_named_library_converts(owned_library, game_on, django_user_model):
    other = django_user_model.objects.create_user(username="other").library
    mine = legacy(owned_library, game_on("Tunic"))
    theirs = legacy(other, game_on("Hades", library=other))

    convert(owned_library)

    assert Purchase.objects.filter(pk=mine.pk).exists()
    assert not Purchase.objects.filter(pk=theirs.pk).exists()


def test_every_refusal_is_listed_and_nothing_written(owned_library, game_on):
    too_large = legacy(owned_library, game_on("Tunic"), price=1e12)
    dlc_base = game_on("Hitman")
    addon = game_on("Already DLC")
    Game.objects.filter(pk=addon.pk).update(kind=GameKind.DLC, parent=dlc_base)
    under_addon = legacy(
        owned_library,
        addon,
        type=LegacyPurchase.DLC,
        name="Nested",
        related_game=addon,
    )
    events = LibraryEvent.objects.count()

    with pytest.raises(PurchaseConversionRefused) as refused:
        convert()

    assert {refusal.legacy_id for refusal in refused.value.refusals} == {
        too_large.pk,
        under_addon.pk,
    }
    assert LibraryEvent.objects.count() == events
    assert not Game.objects.filter(name="Nested").exists()


def test_a_row_no_rule_converts_is_refused_first(owned_library):
    row = legacy(owned_library)

    with pytest.raises(PurchaseConversionRefused) as refused:
        convert()

    assert [refusal.legacy_id for refusal in refused.value.refusals] == [row.pk]


def test_the_schema_guard_refuses_a_missing_column(owned_library, game_on, monkeypatch):
    legacy(owned_library, game_on("Tunic"))
    describe = connection.introspection.get_table_description

    def without_amount(cursor, table):
        columns = describe(cursor, table)
        if table == Purchase._meta.db_table:
            return [column for column in columns if column.name != "amount"]
        return columns

    monkeypatch.setattr(
        connection.introspection, "get_table_description", without_amount
    )

    with pytest.raises(PurchaseConversionRefused, match="games_purchase.amount"):
        convert()


def _publish(library, version=3, currency="CZK"):
    PurchaseConversionState.objects.filter(library=library).update(
        published_version=version,
        published_currency=currency,
        requested_version=version,
        requested_currency=currency,
    )


def test_valuations_seed_from_the_legacy_conversion(owned_library, game_on):
    _publish(owned_library)
    ExchangeRate.objects.create(
        currency_from="EUR", currency_to="CZK", year=2021, rate=Decimal("25.5")
    )
    own = legacy(owned_library, game_on("Tunic"), price=100.0, price_currency="CZK")
    foreign = legacy(
        owned_library,
        game_on("Hades"),
        price=10.0,
        converted_price=255.0,
        converted_currency="CZK",
    )
    unrated = legacy(
        owned_library,
        game_on("Celeste"),
        price=10.0,
        price_currency="USD",
        converted_price=230.0,
        converted_currency="CZK",
    )

    requested = _requested(owned_library)

    convert()

    valued = {row.purchase_id: row for row in PurchaseValuation.objects.all()}
    assert (valued[own.pk].amount, valued[own.pk].rate) == (Decimal("100.00"), None)
    assert (valued[foreign.pk].amount, valued[foreign.pk].rate) == (
        Decimal("255.00"),
        Decimal("25.5"),
    )
    assert unrated.pk not in valued
    assert not stale_purchases(owned_library).filter(pk=foreign.pk).exists()
    assert _requested(owned_library) == requested + 1


def _requested(library) -> int:
    return PurchaseConversionState.objects.get(library=library).requested_version


def test_an_unpublished_library_seeds_nothing_and_requests_a_run(
    owned_library, game_on
):
    legacy(owned_library, game_on("Tunic"))
    PurchaseConversionState.objects.filter(library=owned_library).update(
        requested_currency="CZK"
    )
    requested = _requested(owned_library)

    convert()

    assert not PurchaseValuation.objects.exists()
    assert _requested(owned_library) == requested + 1


def test_a_library_without_a_target_requests_nothing(owned_library, game_on):
    legacy(owned_library, game_on("Tunic"))
    PurchaseConversionState.objects.filter(library=owned_library).update(
        requested_currency=""
    )
    requested = _requested(owned_library)

    convert()

    assert _requested(owned_library) == requested


def test_a_second_run_seeds_and_requests_nothing(owned_library, game_on):
    _publish(owned_library)
    legacy(owned_library, game_on("Tunic"), price=100.0, price_currency="CZK")
    convert()
    seeded_at = datetime(2020, 1, 1, tzinfo=UTC)
    PurchaseValuation.objects.update(calculated_at=seeded_at)
    requested = _requested(owned_library)

    again = convert()

    assert again.appended == 0
    assert PurchaseValuation.objects.get().calculated_at == seeded_at
    assert _requested(owned_library) == requested


def test_a_differing_replay_refuses(owned_library, game_on, monkeypatch):
    legacy(owned_library, game_on("Tunic"))
    real = conversion.rebuild_projections

    def drifted(library, **options):
        report = real(library, **options)
        table = report.tables[0]
        return report.__class__(
            **{
                **{name: getattr(report, name) for name in report.__slots__},
                "tables": (
                    table.__class__(
                        **{
                            **{name: getattr(table, name) for name in table.__slots__},
                            "differing": 1,
                        }
                    ),
                ),
            }
        )

    monkeypatch.setattr(conversion, "rebuild_projections", drifted)

    with pytest.raises(PurchaseConversionRefused, match="does not replay"):
        convert()
    assert not Purchase.objects.exists()


def test_the_pass_nests_in_a_caller_transaction(owned_library, game_on):
    row = legacy(owned_library, game_on("Tunic"))
    with transaction.atomic():
        convert()
    assert Purchase.objects.filter(pk=row.pk).exists()
