"""The purchase conversion pass over legacy rows."""

import dataclasses
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction
from entries import record_entry
from purchases import _state, record_purchase

from games.backfill import purchase as conversion
from games.backfill.purchase import (
    PurchaseConversion,
    PurchaseConversionDrift,
    PurchaseConversionRefused,
    RefusalKind,
    convert_purchases,
    legacy_rows,
)
from games.backfill.purchase_reconciliation import (
    legacy_statistics,
    reconcile,
    review_lists,
    snapshot_value,
)
from games.commands.playergame import RemovePlayerGame, TrackGame
from games.commands.purchase import VoidPurchaseRefund
from games.conversion_review import Category
from games.events.purchase import PURCHASE_CREATED
from games.models import (
    Edition,
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
from games.reads.sums import PlaytimeBreakdown
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


def convert(library=None) -> PurchaseConversion:
    rows = legacy_rows(LegacyPurchase, None if library is None else library.pk)
    return convert_purchases(rows, recorded_at=INSTANT)


def in_key_order(*games: Game) -> list[Game]:
    return sorted(games, key=lambda game: game.pk)


def entries_of(game) -> list[LibraryEntry]:
    return list(LibraryEntry.objects.filter(player_game__game=game).order_by("pk"))


def test_the_reader_names_games_in_key_order_and_the_platform(
    owned_library, game_on, steam
):
    first, second = in_key_order(game_on("Tunic"), game_on("Hades"))
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
    purchase = Purchase.objects.get(pk=row.pk)
    assert (entry.access, entry.access_end_way) == ("rented", "refunded")
    assert purchase.refunded.serialize() == "2021-05-04"
    assert not refund_owns_the_end(owned_library, purchase)


def test_a_borrowed_copy_at_no_price_has_no_purchase(owned_library, game_on):
    game = game_on("Tunic")
    legacy(owned_library, game, ownership_type=LegacyPurchase.BORROWED, price=0.0)

    convert()

    [entry] = entries_of(game)
    assert entry.access == "borrowed"
    assert not Purchase.objects.exists()


def test_a_bundle_splits_into_one_purchase_per_game(owned_library, game_on):
    games = in_key_order(*(game_on(name) for name in ("A", "B", "C")))
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
    own = PlayerGame.objects.get(game=dlc)
    assert own.excluded_from_unfinished and own.excluded_from_dropped
    assert not PlayerGame.objects.get(game=base).excluded_from_unfinished


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
    finite = legacy(owned_library, game, date_purchased=date(2022, 1, 1))

    convert()

    tracked = PlayerGame.objects.get(game=game)
    assert tracked.excluded_from_unfinished and tracked.excluded_from_dropped
    for row in (infinite, finite):
        review = LibraryEvent.objects.get(aggregate_id=row.pk).source_metadata
        assert Category.MIXED_INFINITE in review["review"]


def test_a_removed_legacy_row_removes_its_purchase_and_copy(owned_library, game_on):
    game = game_on("Tunic")
    row = legacy(owned_library, game)
    remove(row)

    convert()

    assert Purchase.objects.get(pk=row.pk).removed_at is not None
    [entry] = entries_of(game)
    assert entry.removed_at is not None
    #: The copy's removal took no purchase.
    assert list(
        LibraryEvent.objects.filter(
            idempotency_key__startswith="conversion:723:removed_copy:"
        ).values_list("event_type", flat=True)
    ) == ["library.libraryentry.removed"]


def test_a_removed_game_is_skipped(owned_library, game_on):
    game = game_on("Tunic")
    row = legacy(owned_library, game)
    legacy(owned_library, game_on("Hades"))
    remove(game)

    done = convert()

    [library] = done.libraries
    assert [(skip.legacy_id, skip.game_id) for skip in library.skipped] == [
        (row.pk, game.pk)
    ]
    assert not entries_of(game)
    lists = review_lists(owned_library, library)
    assert lists[Category.SKIPPED_REMOVED_GAME] == [str(row.pk)]


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

    with pytest.raises(PurchaseConversionDrift, match="games_purchase.amount"):
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
        converted_price=250.0,
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

    [done] = convert().libraries

    valued = {row.purchase_id: row for row in PurchaseValuation.objects.all()}
    assert (valued[own.pk].amount, valued[own.pk].rate) == (Decimal("100.00"), None)
    assert (valued[foreign.pk].amount, valued[foreign.pk].rate) == (
        Decimal("250.00"),
        Decimal("25.5"),
    )
    assert unrated.pk not in valued
    assert {(row.version, row.calculated_at) for row in valued.values()} == {
        (3, INSTANT)
    }
    assert not stale_purchases(owned_library).filter(pk=foreign.pk).exists()
    assert _requested(owned_library) == requested + 1
    assert [(item.legacy_id, item.reason) for item in done.unvalued] == [
        (unrated.pk, "no stored USD->CZK rate for 2021")
    ]


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

    [done] = convert().libraries

    assert not PurchaseValuation.objects.exists()
    assert {item.reason for item in done.unvalued} == {
        "the library has published no target currency"
    }
    assert _requested(owned_library) == requested + 1


def test_a_library_without_a_target_requests_nothing(owned_library, game_on):
    legacy(owned_library, game_on("Tunic"))
    PurchaseConversionState.objects.filter(library=owned_library).update(
        requested_currency=""
    )
    requested = _requested(owned_library)

    convert()

    assert _requested(owned_library) == requested


def test_an_appending_rerun_keeps_standing_valuations(owned_library, game_on):
    _publish(owned_library)
    first = legacy(owned_library, game_on("Tunic"), price=100.0, price_currency="CZK")
    convert()
    seeded_at = datetime(2020, 1, 1, tzinfo=UTC)
    PurchaseValuation.objects.update(calculated_at=seeded_at)
    later = legacy(owned_library, game_on("Hades"), price=50.0, price_currency="CZK")
    requested = _requested(owned_library)

    convert()

    stamps = dict(PurchaseValuation.objects.values_list("purchase_id", "calculated_at"))
    assert stamps == {first.pk: seeded_at, later.pk: INSTANT}
    assert _requested(owned_library) == requested + 1


def test_a_rerun_with_nothing_new_seeds_and_requests_nothing(owned_library, game_on):
    _publish(owned_library)
    legacy(owned_library, game_on("Tunic"), price=100.0, price_currency="CZK")
    convert()
    requested = _requested(owned_library)

    again = convert()

    assert again.nothing_awaited
    assert _requested(owned_library) == requested


def test_a_differing_replay_refuses(owned_library, game_on, monkeypatch):
    legacy(owned_library, game_on("Tunic"))
    real = conversion.rebuild_projections

    def drifted(library, **options):
        report = real(library, **options)
        table = dataclasses.replace(report.tables[0], differing=1)
        return dataclasses.replace(report, tables=(table,))

    monkeypatch.setattr(conversion, "rebuild_projections", drifted)

    with pytest.raises(PurchaseConversionDrift, match="does not replay"):
        convert()
    assert not Purchase.objects.exists()


def test_the_pass_nests_in_a_caller_transaction(owned_library, game_on):
    row = legacy(owned_library, game_on("Tunic"))
    with transaction.atomic():
        convert()
    assert Purchase.objects.filter(pk=row.pk).exists()


def test_the_reconciliation_explains_quantization_and_refunds(owned_library, game_on):
    legacy(owned_library, game_on("Tunic"), price=2.9925)
    legacy(
        owned_library,
        game_on("Hades"),
        game_on("Celeste"),
        price=10.0,
        date_refunded=date(2021, 5, 4),
    )
    legacy(
        owned_library,
        game_on("Inside"),
        ownership_type=LegacyPurchase.RENTED,
        price=3.0,
        date_refunded=date(2021, 5, 4),
    )
    rows = legacy_rows(LegacyPurchase)

    [done] = convert_purchases(rows, recorded_at=INSTANT).libraries
    checked = reconcile(rows, done)

    [eur] = checked.totals
    assert (eur.legacy, eur.converted, eur.quantization) == (
        Decimal("15.9925"),
        Decimal("15.99"),
        Decimal("-0.0025"),
    )
    assert (checked.refunded_purchases, checked.refund_ended_copies) == (
        (3, 3),
        (3, 3),
    )
    assert checked.copies_by_access == {
        ("owned", "digital"): 3,
        ("rented", "digital"): 1,
    }
    assert checked.failures() == []
    lists = review_lists(owned_library, done)
    assert len(lists[Category.BUNDLE_SPLIT]) == 1
    assert len(lists[Category.QUANTIZED]) == 1


def test_a_missing_refund_is_a_failure(owned_library, game_on):
    legacy(owned_library, game_on("Tunic"), date_refunded=date(2021, 5, 4))
    rows = legacy_rows(LegacyPurchase)
    [done] = convert_purchases(rows, recorded_at=INSTANT).libraries
    Purchase.objects.update(refund_recorded_at=None)

    assert reconcile(rows, done).failures() == ["0 refunded purchases, expected 1"]


def test_a_snapshot_spells_every_value(owned_library, game_on, steam):
    game = game_on("Tunic")
    breakdown = PlaytimeBreakdown(timedelta(hours=1), timedelta(0))

    encoded = snapshot_value(
        {
            "games": Game.objects.filter(pk=game.pk),
            "game": game,
            "spent": Decimal("1.50"),
            "day": date(2024, 1, 2),
            "hours": breakdown,
            "pair": ("a", 1),
            "none": None,
        }
    )

    assert encoded == {
        "games": [str(game.pk)],
        "game": str(game.pk),
        "spent": "1.50",
        "day": "2024-01-02",
        "hours": {"tracked": 3600, "historical": 0},
        "pair": ["a", 1],
        "none": None,
    }


def test_the_legacy_statistics_cover_every_purchase_year(owned_library, game_on):
    legacy(owned_library, game_on("Tunic"), date_purchased=date(2019, 3, 1))
    rows = legacy_rows(LegacyPurchase)

    snapshot = legacy_statistics(LegacyPurchase, owned_library, rows)

    assert snapshot["format"] == 2
    assert snapshot["library"] == str(owned_library.pk)
    assert set(snapshot["scopes"]) == {"all-time", "2019"}
    assert snapshot["scopes"]["2019"]["rows"]["purchases"] == [str(rows[0].id)]
    assert snapshot["scopes"]["2019"]["figures"]["all_purchased_this_year_count"] == 1
    json.dumps(snapshot)


def _review_of(row) -> list[str]:
    return LibraryEvent.objects.get(
        aggregate_id=row.pk, event_type=PURCHASE_CREATED.event_type
    ).source_metadata["review"]


def _events_by_key() -> dict[str, list[str]]:
    keyed: dict[str, list[str]] = {}
    for key, event_type in LibraryEvent.objects.order_by("sequence").values_list(
        "idempotency_key", "event_type"
    ):
        keyed.setdefault(key, []).append(event_type)
    return keyed


def test_a_full_rerun_replays_every_key(owned_library, game_on):
    rental = game_on("Inside")
    legacy(
        owned_library,
        rental,
        ownership_type=LegacyPurchase.RENTED,
        price=3.0,
        date_refunded=date(2021, 5, 4),
    )
    gone = game_on("Limbo")
    remove(legacy(owned_library, gone))
    bundle = in_key_order(*(game_on(name) for name in ("A", "B", "C")))
    legacy(owned_library, *bundle, price=10.0)
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
    before = _events_by_key()
    copies = {game.pk: entries_of(game) for game in (rental, gone, *bundle, base)}
    keys = {
        game.pk: Purchase.objects.get(entry__player_game__game=game).pk
        for game in bundle
    }
    later = legacy(owned_library, game_on("Celeste"))

    convert()

    after = _events_by_key()
    added = {key: types for key, types in after.items() if key not in before}
    assert set(added) == {key for key in after if str(later.pk) in key}
    assert {key: after[key] for key in before} == before
    assert {
        game.pk: entries_of(game) for game in (rental, gone, *bundle, base)
    } == copies
    assert {
        game.pk: Purchase.objects.get(entry__player_game__game=game).pk
        for game in bundle
    } == keys
    assert Game.objects.filter(parent=base, kind=GameKind.DLC).count() == 1


def test_a_legacy_row_changed_after_its_conversion_is_a_defect(owned_library, game_on):
    game = game_on("Tunic")
    row = legacy(owned_library, game)
    convert()
    LegacyPurchase.objects.filter(pk=row.pk).update(price=12.0)

    with pytest.raises(PurchaseConversionRefused) as refused:
        convert()

    [refusal] = refused.value.refusals
    assert (refusal.legacy_id, refusal.kind) == (row.pk, RefusalKind.DEFECT)
    assert "changed after its conversion" in refusal.reason


def test_a_refund_stated_after_the_conversion_converts_on_a_rerun(
    owned_library, game_on
):
    game = game_on("Tunic")
    row = legacy(owned_library, game)
    convert()
    LegacyPurchase.objects.filter(pk=row.pk).update(date_refunded=date(2021, 5, 4))

    convert()

    assert Purchase.objects.get(pk=row.pk).refunded.serialize() == "2021-05-04"
    [entry] = entries_of(game)
    assert entry.access_end_way == "refunded"


def test_a_refunded_or_removed_pass_leaves_the_base_copy(owned_library, game_on):
    game = game_on("Destiny")
    base = legacy(owned_library, game)
    season = legacy(
        owned_library,
        game,
        type=LegacyPurchase.SEASONPASS,
        name="Year 1",
        related_game=game,
        date_refunded=date(2021, 5, 4),
    )
    upgrade = legacy(owned_library, game, ownership_type=LegacyPurchase.DIGITALUPGRADE)
    remove(upgrade)
    LegacyPurchase.objects.filter(pk=upgrade.pk).update(removed_at=INSTANT)

    convert()

    [entry] = entries_of(game)
    assert (entry.access_end_recorded_at, entry.removed_at) == (None, None)
    assert Purchase.objects.get(pk=base.pk).entry == entry
    assert Purchase.objects.get(pk=season.pk).refund_recorded_at is not None
    assert Purchase.objects.get(pk=upgrade.pk).removed_at is not None


def test_a_refunded_upgrade_on_its_own_copy_ends_it(owned_library, game_on):
    game = game_on("Cyberpunk")
    row = legacy(
        owned_library,
        game,
        ownership_type=LegacyPurchase.DIGITALUPGRADE,
        date_refunded=date(2021, 5, 4),
    )

    convert()

    [entry] = entries_of(game)
    assert entry.access_end_way == "refunded"
    assert Category.OWN_COPY_FALLBACK in _review_of(row)


def test_a_pass_never_rides_a_removed_rows_copy(owned_library, game_on):
    game = game_on("Destiny")
    remove(legacy(owned_library, game))
    season = legacy(
        owned_library,
        game,
        type=LegacyPurchase.SEASONPASS,
        name="Year 1",
        related_game=game,
    )

    convert()

    copy = Purchase.objects.get(pk=season.pk).entry
    assert copy.removed_at is None
    assert len(entries_of(game)) == 2


def test_a_free_pass_beside_an_owned_base_gets_its_own_copy(owned_library, game_on):
    game = game_on("Destiny")
    legacy(owned_library, game)
    legacy(
        owned_library,
        game,
        type=LegacyPurchase.SEASONPASS,
        name="Trial pass",
        related_game=game,
        ownership_type=LegacyPurchase.BORROWED,
        price=0.0,
    )

    convert()

    assert sorted(entry.access for entry in entries_of(game)) == [
        "borrowed",
        "owned",
    ]


def test_a_pass_prefers_the_base_copy_on_its_platform(owned_library, game_on, steam):
    game = game_on("Destiny")
    switch = Platform.objects.create(name="Switch", group="Nintendo")
    on_switch = legacy(
        owned_library, game, platform=switch, date_purchased=date(2020, 1, 1)
    )
    on_steam = legacy(owned_library, game, platform=steam)
    season = legacy(
        owned_library,
        game,
        type=LegacyPurchase.SEASONPASS,
        name="Year 1",
        related_game=game,
        platform=steam,
    )

    convert()

    assert Purchase.objects.get(pk=season.pk).entry_id == (
        Purchase.objects.get(pk=on_steam.pk).entry_id
    )
    assert Purchase.objects.get(pk=on_switch.pk).entry_id != (
        Purchase.objects.get(pk=season.pk).entry_id
    )


def test_owned_free_rows_pass_the_price_rules(owned_library, game_on):
    epic = Platform.objects.create(name="Epic Games Store", group="PC")
    free = legacy(
        owned_library, game_on("Control", platform=epic), price=0.0, platform=epic
    )
    unknown = legacy(owned_library, game_on("Tunic"), price=0.0)

    [done] = convert().libraries

    prices = Purchase.objects.values_list("amount", "currency")
    assert prices.get(pk=free.pk) == (Decimal("0.00"), "EUR")
    assert prices.get(pk=unknown.pk) == (None, "")
    lists = review_lists(owned_library, done)
    assert lists[Category.EPIC_FREE] == [str(free.pk)]
    assert lists[Category.UNKNOWN_PRICE] == [str(unknown.pk)]


def test_a_refusal_in_one_library_rolls_back_the_other(
    owned_library, game_on, django_user_model
):
    other = django_user_model.objects.create_user(username="other").library
    legacy(owned_library, game_on("Tunic"))
    legacy(other, game_on("Hades", library=other), price=1e12)

    with pytest.raises(PurchaseConversionRefused):
        convert()

    assert not Purchase.objects.exists()
    assert not LibraryEvent.objects.filter(library=owned_library).exists()


def test_a_defect_is_listed_beside_a_refusal(owned_library, game_on, monkeypatch):
    broken = legacy(owned_library, game_on("Tunic"))
    refused = legacy(owned_library, game_on("Hades"), price=1e12)
    real = conversion._LibraryPass._create

    def create(self, copy, *args, **kwargs):
        if copy.row.id == broken.pk:
            raise IntegrityError("a constraint")
        return real(self, copy, *args, **kwargs)

    monkeypatch.setattr(conversion._LibraryPass, "_create", create)

    with pytest.raises(PurchaseConversionRefused) as raised:
        convert()

    kinds = {refusal.legacy_id: refusal for refusal in raised.value.refusals}
    assert kinds[broken.pk].kind == RefusalKind.DEFECT
    assert "IntegrityError" in kinds[broken.pk].reason
    assert kinds[refused.pk].kind == RefusalKind.REFUSED
    assert not Purchase.objects.exists()


def test_demos_share_one_edition_across_platforms(owned_library, game_on, steam):
    game = game_on("Tunic")
    switch = Platform.objects.create(name="Switch", group="Nintendo")
    for platform in (steam, steam, switch):
        legacy(
            owned_library,
            game,
            ownership_type=LegacyPurchase.DEMO,
            price=0.0,
            platform=platform,
        )

    convert()

    [edition] = Edition.objects.filter(game=game, name="Demo")
    releases = Release.objects.filter(edition=edition).alive()
    assert {release.platform for release in releases} == {steam, switch}
    assert len(entries_of(game)) == 3


def test_an_untracked_game_is_skipped(owned_library, game_on):
    game = game_on("Tunic")
    row = legacy(owned_library, game)
    legacy(owned_library, game_on("Hades"))
    _state(owned_library, TrackGame(game_id=game.pk))
    _state(owned_library, RemovePlayerGame(game_id=game.pk))

    [done] = convert().libraries

    assert [skip.legacy_id for skip in done.skipped] == [row.pk]


def test_a_game_without_a_live_release_is_refused(owned_library, game_on):
    game = game_on("Tunic")
    remove(Release.objects.get(edition__game=game))
    switch = Platform.objects.create(name="Switch", group="Nintendo")
    row = legacy(owned_library, game, platform=switch)

    with pytest.raises(PurchaseConversionRefused) as refused:
        convert()

    assert [refusal.legacy_id for refusal in refused.value.refusals] == [row.pk]


def test_the_reconciliation_subtracts_a_skipped_copy(owned_library, game_on):
    games = in_key_order(*(game_on(name) for name in ("A", "B", "C")))
    legacy(owned_library, *games, price=10.0)
    remove(games[2])
    rows = legacy_rows(LegacyPurchase)

    [done] = convert_purchases(rows, recorded_at=INSTANT).libraries
    checked = reconcile(rows, done)

    [eur] = checked.totals
    assert (eur.converted, eur.skipped) == (Decimal("6.67"), Decimal("3.33"))
    assert checked.failures() == []


def test_a_changed_amount_and_a_missing_end_are_failures(owned_library, game_on):
    legacy(owned_library, game_on("Tunic"), date_refunded=date(2021, 5, 4))
    rows = legacy_rows(LegacyPurchase)
    [done] = convert_purchases(rows, recorded_at=INSTANT).libraries
    Purchase.objects.update(amount=Decimal("9.00"))
    LibraryEntry.objects.update(access_end_way="sold")

    failures = reconcile(rows, done).failures()

    assert failures == [
        "EUR: legacy 10.0 + quantization 0.00 - skipped 0 is not the converted 9.00",
        "0 copies ended as refunded, expected 1",
    ]


def test_valuations_keep_standing_rows_and_list_the_unvalued(owned_library, game_on):
    _publish(owned_library)
    hand = record_purchase(
        record_entry(
            owned_library, Release.objects.get(edition__game=game_on("Inside"))
        ),
        amount=Decimal("100.00"),
        currency="CZK",
    )
    PurchaseValuation.objects.create(
        library=owned_library,
        purchase_id=hand.pk,
        target_currency="CZK",
        amount=Decimal("100.00"),
        source_amount=Decimal("100.00"),
        source_currency="CZK",
        rate_year=2021,
        rate=None,
        version=3,
        calculated_at=INSTANT,
    )
    ExchangeRate.objects.create(
        currency_from="EUR", currency_to="CZK", year=2021, rate=Decimal("25.5")
    )
    ExchangeRate.objects.create(
        currency_from="USD", currency_to="CZK", year=2021, rate=Decimal(23)
    )
    elsewhere = legacy(
        owned_library,
        game_on("Hades"),
        price=10.0,
        price_currency="USD",
        converted_price=9.0,
        converted_currency="EUR",
    )
    bundle = in_key_order(game_on("A"), game_on("B"))
    legacy(
        owned_library,
        *bundle,
        price=10.0,
        converted_price=240.0,
        converted_currency="CZK",
    )

    [done] = convert().libraries

    valued = {row.purchase_id: row.amount for row in PurchaseValuation.objects.all()}
    assert valued[hand.pk] == Decimal("100.00")
    assert elsewhere.pk not in valued
    assert [
        valued[Purchase.objects.get(entry__player_game__game=game).pk]
        for game in bundle
    ] == [Decimal("120.00"), Decimal("120.00")]
    [unvalued] = done.unvalued
    assert (unvalued.legacy_id, unvalued.reason) == (
        elsewhere.pk,
        "the legacy converted currency EUR is not CZK",
    )


def _defect_after(row, change):
    LegacyPurchase.objects.filter(pk=row.pk).update(**change)
    with pytest.raises(PurchaseConversionRefused) as refused:
        convert()
    [refusal] = refused.value.refusals
    assert refusal.kind == RefusalKind.DEFECT
    return refusal


@pytest.mark.parametrize(
    ("facts", "change", "reason"),
    [
        ({"date_refunded": date(2021, 5, 4)}, {"date_refunded": None}, "its refund"),
        ({"removed_at": INSTANT}, {"removed_at": None}, "its removal"),
        (
            {"ownership_type": LegacyPurchase.BORROWED, "price": 0.0},
            {"price": 4.0},
            "its price changed",
        ),
    ],
    ids=["refund cleared", "removal cleared", "free row priced"],
)
def test_a_withdrawn_act_is_a_defect(owned_library, game_on, facts, change, reason):
    row = legacy(owned_library, game_on("Tunic"))
    LegacyPurchase.objects.filter(pk=row.pk).update(**facts)
    convert()

    refusal = _defect_after(row, change)

    assert refusal.legacy_id == row.pk
    assert reason in refusal.reason


def test_a_platform_changed_after_its_conversion_is_a_defect(owned_library, game_on):
    row = legacy(owned_library, game_on("Tunic"))
    convert()
    switch = Platform.objects.create(name="Switch", group="Nintendo")

    refusal = _defect_after(row, {"platform": switch})

    assert "changed after its conversion" in refusal.reason


def test_an_infinite_flag_cleared_after_its_conversion_is_a_defect(
    owned_library, game_on
):
    row = legacy(owned_library, game_on("Tunic"), infinite=True)
    convert()

    refusal = _defect_after(row, {"infinite": False})

    assert "no live infinite row" in refusal.reason


def test_a_free_row_removed_after_its_conversion_removes_its_copy(
    owned_library, game_on
):
    game = game_on("Tunic")
    row = legacy(owned_library, game, ownership_type=LegacyPurchase.BORROWED, price=0.0)
    convert()
    LegacyPurchase.objects.filter(pk=row.pk).update(removed_at=INSTANT)

    convert()

    [entry] = entries_of(game)
    assert entry.removed_at is not None


def test_a_priced_row_removed_after_its_conversion_removes_on_a_rerun(
    owned_library, game_on
):
    game = game_on("Tunic")
    row = legacy(owned_library, game)
    convert()
    LegacyPurchase.objects.filter(pk=row.pk).update(removed_at=INSTANT)

    convert()

    assert Purchase.objects.get(pk=row.pk).removed_at is not None
    [entry] = entries_of(game)
    assert entry.removed_at is not None


def test_an_infinite_flag_set_after_its_conversion_excludes(owned_library, game_on):
    game = game_on("Tunic")
    row = legacy(owned_library, game)
    convert()
    LegacyPurchase.objects.filter(pk=row.pk).update(infinite=True)

    convert()

    assert PlayerGame.objects.get(game=game).excluded_from_unfinished


def test_a_rerun_after_a_skipped_copy_awaits_nothing(owned_library, game_on):
    game = game_on("Tunic")
    legacy(owned_library, game)
    legacy(owned_library, game_on("Hades"))
    remove(game)
    convert()

    assert convert().nothing_awaited


def test_a_converted_copy_is_not_hand_recorded_on_a_rerun(owned_library, game_on):
    game = game_on("Tunic")
    legacy(owned_library, game)
    convert()
    second = legacy(owned_library, game, date_purchased=date(2022, 1, 1))

    convert()

    assert Category.HAND_RECORDED_COPY not in _review_of(second)


def test_a_pass_riding_a_hand_recorded_copy_is_not_tagged(owned_library, game_on):
    game = game_on("Destiny")
    record_entry(owned_library, Release.objects.get(edition__game=game))
    season = legacy(
        owned_library,
        game,
        type=LegacyPurchase.SEASONPASS,
        name="Year 1",
        related_game=game,
    )

    convert()

    assert len(entries_of(game)) == 1
    assert Category.HAND_RECORDED_COPY not in _review_of(season)


def test_a_dlc_on_another_platform_has_one_release(owned_library, game_on):
    base = game_on("Hitman")
    switch = Platform.objects.create(name="Switch", group="Nintendo")
    row = legacy(
        owned_library,
        base,
        type=LegacyPurchase.DLC,
        name="Blood Money",
        related_game=base,
        platform=switch,
    )

    convert()

    dlc = Game.objects.get(parent=base)
    assert [
        release.platform for release in Release.objects.filter(edition__game=dlc)
    ] == [switch]
    assert Category.CREATED_RELEASE not in _review_of(row)


def test_same_named_dlcs_under_two_bases_both_convert(owned_library, game_on):
    first, second = game_on("Hitman"), game_on("Hitman 2")
    for base in (first, second):
        legacy(
            owned_library,
            base,
            type=LegacyPurchase.DLC,
            name="Soundtrack",
            related_game=base,
        )

    [done] = convert().libraries

    names = sorted(
        Game.objects.filter(parent__in=[first, second]).values_list("name", flat=True)
    )
    assert names in (
        ["Hitman 2: Soundtrack", "Soundtrack"],
        ["Hitman: Soundtrack", "Soundtrack"],
    )
    lists = review_lists(owned_library, done)
    assert len(lists[Category.RENAMED_ADDON]) == 1


def test_a_missing_conversion_state_is_a_defect(owned_library, game_on):
    legacy(owned_library, game_on("Tunic"))
    PurchaseConversionState.objects.filter(library=owned_library).delete()

    with pytest.raises(PurchaseConversionRefused) as refused:
        convert()

    [refusal] = refused.value.refusals
    assert (refusal.legacy_id, refusal.kind) == (None, RefusalKind.DEFECT)


def test_a_seeded_valuation_that_drifts_is_a_failure(owned_library, game_on):
    _publish(owned_library)
    ExchangeRate.objects.create(
        currency_from="EUR", currency_to="CZK", year=2021, rate=Decimal("25.5")
    )
    legacy(
        owned_library,
        game_on("Tunic"),
        price=10.0,
        converted_price=250.0,
        converted_currency="CZK",
    )
    rows = legacy_rows(LegacyPurchase)
    [done] = convert_purchases(rows, recorded_at=INSTANT).libraries
    PurchaseValuation.objects.update(amount=Decimal("255.00"))

    assert reconcile(rows, done).failures() == [
        "CZK: seeded 255.00, legacy shares 250.00"
    ]
