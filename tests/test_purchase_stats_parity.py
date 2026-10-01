"""The legacy purchase figures, and their parity gate."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from graphs import default_graph
from purchases import record_purchase, remove_purchase
from session_rows import session_row
from tracked_games import create_tracked_game

from games.backfill import purchase as conversion
from games.backfill.purchase import convert_purchases, legacy_rows
from games.backfill.purchase_reconciliation import (
    ALL_TIME,
    legacy_figures,
    legacy_statistics,
)
from games.models import (
    Game,
    LegacyPurchase,
    LibraryEntry,
    PlayerGame,
    PlayerGameStatus,
    Playthrough,
    Purchase,
    PurchaseConversionState,
    PurchaseValuation,
)
from games.purchase_parity import (
    ConversionMap,
    PurchaseScope,
    Reason,
    judge_purchase_scope,
    read_snapshot,
)
from games.stats_parity import unattributed
from games.views.stats_data import compute_stats
from timetracker.temporal import TemporalValue

pytestmark = pytest.mark.django_db

YEAR = 2021
INSTANT = datetime(2026, 10, 1, 12, tzinfo=UTC)


def _legacy(library, game, day: date, **columns) -> LegacyPurchase:
    """A row the old task converted, as a priced row was."""
    currency = columns.pop("price_currency", "EUR")
    if columns.get("price"):
        columns.setdefault("converted_price", columns["price"])
        columns.setdefault("converted_currency", currency)
    purchase = LegacyPurchase.objects.create(
        library=library, date_purchased=day, price_currency=currency, **columns
    )
    purchase.games.add(game)
    return purchase


@pytest.fixture
def legacy_library(owned_library):
    """One row for each rule the old figures read."""
    library = owned_library
    done = create_tracked_game(library, "Done", status=PlayerGameStatus.COMPLETED)
    playing = create_tracked_game(
        library, "Playing", status=PlayerGameStatus.PLAYED, year_released=YEAR
    )
    abandoned = create_tracked_game(
        library, "Dropped", status=PlayerGameStatus.ABANDONED
    )
    refunded = create_tracked_game(library, "Refunded", status=PlayerGameStatus.PLAYED)
    endless = create_tracked_game(library, "Endless", status=PlayerGameStatus.PLAYED)
    finished = create_tracked_game(
        library, "Finished", status=PlayerGameStatus.COMPLETED, year_released=YEAR
    )
    Playthrough.objects.filter(player_game__game=finished).update(
        completed=TemporalValue.parse(f"{YEAR}-06-01"),
        completion_recorded_at=timezone.now(),
    )
    session_row(playing, started_at=datetime(YEAR, 6, 1, 12, tzinfo=UTC))
    for game in (done, playing, abandoned, refunded, endless, finished):
        default_graph(game, library)
    rows = {
        "done": _legacy(
            library,
            done,
            date(YEAR, 2, 1),
            price=10,
            converted_price=10,
            converted_currency="EUR",
        ),
        "playing": _legacy(
            library,
            playing,
            date(YEAR, 3, 1),
            price=20,
            converted_price=20,
            converted_currency="EUR",
        ),
        "dropped": _legacy(library, abandoned, date(YEAR, 4, 1)),
        "refunded": _legacy(
            library, refunded, date(YEAR, 5, 1), date_refunded=date(YEAR, 5, 10)
        ),
        "endless": _legacy(library, endless, date(YEAR, 5, 2), infinite=True),
        "pass": _legacy(
            library,
            playing,
            date(YEAR, 5, 3),
            type=LegacyPurchase.SEASONPASS,
            name="Pass",
            related_game=playing,
        ),
        "finished": _legacy(library, finished, date(YEAR - 1, 1, 1)),
    }
    return library, {name: str(row.pk) for name, row in rows.items()}


def test_the_year_rows_follow_the_old_rules(legacy_library):
    library, key = legacy_library

    rows = legacy_figures(LegacyPurchase, library, YEAR).rows

    assert rows["purchases"] == {
        key[name]
        for name in ("done", "playing", "dropped", "refunded", "endless", "pass")
    }
    assert rows["refunded"] == {key["refunded"]}
    assert rows["unfinished"] == {key["playing"]}
    assert rows["dropped"] == {key["dropped"], key["refunded"]}
    assert rows["finished"] == {key["finished"]}
    assert rows["finished_released"] == {key["finished"]}
    assert rows["backlog_decrease"] == {key["finished"]}
    assert rows["bought_and_finished"] == set()
    assert rows["played"] == {key["playing"], key["pass"]}
    assert rows["valued"] == {key["done"], key["playing"]}


def test_the_year_values_follow_the_old_rules(legacy_library):
    library, key = legacy_library

    figures = legacy_figures(LegacyPurchase, library, YEAR)

    assert figures.values == {
        "all_purchased_this_year_count": 6,
        "all_purchased_refunded_this_year_count": 1,
        "refunded_percent": 16,
        "total_spent": 30.0,
        "total_spent_currency": "EUR",
        "spent_per_game": 6,
        "dropped_count": 2,
        "dropped_percentage": 33,
        "purchased_unfinished_count": 1,
        "unfinished_purchases_percent": 20,
        "backlog_decrease_count": 1,
        "this_year_finished_this_year_count": 1,
        "total_year_games": 2,
        "all_finished_this_year_count": 1,
    }
    assert figures.amounts == {
        key["done"]: Decimal("10.00"),
        key["playing"]: Decimal("20.00"),
    }


def test_all_time_finishes_by_a_done_status_too(legacy_library):
    library, key = legacy_library

    rows = legacy_figures(LegacyPurchase, library, None).rows

    assert rows["finished"] == {key["done"], key["finished"]}
    assert rows["backlog_decrease"] == rows["finished"]
    assert len(rows["purchases"]) == 7


def test_a_removed_game_hides_its_purchase(legacy_library):
    from games.removal import remove

    library, key = legacy_library
    remove(LegacyPurchase.objects.get(pk=key["dropped"]).games.get())

    assert (
        key["dropped"]
        not in legacy_figures(LegacyPurchase, library, None).rows["purchases"]
    )


@pytest.mark.django_db(transaction=True)
def test_the_historical_model_answers_alike(legacy_library):
    library, _ = legacy_library
    state = MigrationExecutor(connection).loader.project_state(
        ("games", "0031_purchase_conversion")
    )
    historical = state.apps.get_model("games", "LegacyPurchase")

    assert legacy_figures(historical, library, YEAR) == legacy_figures(
        LegacyPurchase, library, YEAR
    )
    assert legacy_figures(historical, library, None) == legacy_figures(
        LegacyPurchase, library, None
    )


# ── The gate ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def no_replay_check(monkeypatch):
    """Seeded rows hold no events; replay is not this file's."""
    monkeypatch.setattr(conversion, "require_replay_parity", lambda libraries: None)


def _snapshot(library) -> dict:
    rows = legacy_rows(LegacyPurchase, library.pk)
    return json.loads(json.dumps(legacy_statistics(LegacyPurchase, library, rows)))


def _convert(library) -> None:
    convert_purchases(legacy_rows(LegacyPurchase, library.pk), recorded_at=INSTANT)


def _judged(library, snapshot) -> dict[str, PurchaseScope]:
    mapping = ConversionMap.read(library)
    return {
        label: judge_purchase_scope(
            scope,
            compute_stats(library, None if label == ALL_TIME else int(label)),
            library,
            None if label == ALL_TIME else int(label),
            mapping,
        )
        for label, scope in read_snapshot(snapshot, library).items()
    }


def _reasons_for(judged, legacy_key: str) -> set[Reason]:
    return {
        reason
        for scope in judged.values()
        for judgement in scope.judgements
        for reason in judgement.explained.get(legacy_key, ())
    }


def _unattributed(judged) -> list:
    return [
        change for scope in judged.values() for change in unattributed(scope.changes)
    ]


def _gate(owned_user, path) -> str:
    out = StringIO()
    call_command(
        "verify_purchase_statistics",
        "--user",
        owned_user.username,
        "--snapshot",
        str(path),
        stdout=out,
    )
    return out.getvalue()


@pytest.fixture
def euro(owned_library):
    """The library publishes euros."""
    PurchaseConversionState.objects.filter(library=owned_library).update(
        requested_version=1, published_version=1, published_currency="EUR"
    )
    return owned_library


def test_a_clean_conversion_passes_the_gate(legacy_library, owned_user, euro, tmp_path):
    library, _ = legacy_library
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(_snapshot(library)))
    _convert(library)

    assert "Every figure is attributed." in _gate(owned_user, path)


def test_format_one_is_refused(owned_user, owned_library, tmp_path):
    path = tmp_path / "old.json"
    path.write_text(
        json.dumps({"format": 1, "library": str(owned_library.pk), "scopes": {}})
    )

    with pytest.raises(CommandError, match="format 1"):
        _gate(owned_user, path)


def test_an_unexplained_row_fails_the_gate(legacy_library, owned_user, euro, tmp_path):
    library, key = legacy_library
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(_snapshot(library)))
    _convert(library)
    remove_purchase(Purchase.objects.get(pk=key["dropped"]))

    with pytest.raises(CommandError, match="unattributed"):
        _gate(owned_user, path)


def test_a_cent_off_the_total_fails(legacy_library, euro):
    library, key = legacy_library
    snapshot = _snapshot(library)
    _convert(library)
    assert not _unattributed(_judged(library, snapshot))
    assert PurchaseValuation.objects.filter(purchase_id=key["playing"]).exists()
    for scope in snapshot["scopes"].values():
        if key["playing"] in scope["amounts"]:
            scope["amounts"][key["playing"]] = str(
                Decimal(scope["amounts"][key["playing"]]) + Decimal("0.01")
            )

    failed = {change.key for change in _unattributed(_judged(library, snapshot))}

    assert "total_spent" in failed


# ── One reason each ─────────────────────────────────────────────────────────


@pytest.fixture
def game_on(owned_library, stated_graph):
    def make(name: str, **facts) -> Game:
        game = stated_graph(Game(name=name, library=owned_library), owned_library).game
        PlayerGame.objects.filter(game=game).update(**facts)
        return game

    return make


def _reason_of(library, row, reason: Reason) -> None:
    """Snapshot, convert, judge; the row's key names it."""
    snapshot = _snapshot(library)
    _convert(library)
    judged = _judged(library, snapshot)

    assert reason in _reasons_for(judged, str(row.pk))
    assert not _unattributed(judged)


def test_a_free_rental_is_a_copy_and_no_purchase(owned_library, euro, game_on):
    row = _legacy(
        owned_library,
        game_on("Inside"),
        date(YEAR, 3, 1),
        ownership_type=LegacyPurchase.RENTED,
        price=0,
    )

    _reason_of(owned_library, row, Reason.NO_PURCHASE)


def test_a_bundle_splits(owned_library, euro, game_on):
    row = _legacy(owned_library, game_on("One"), date(YEAR, 3, 1), price=10)
    row.games.add(game_on("Two"))

    _reason_of(owned_library, row, Reason.BUNDLE_SPLIT)


def test_a_rental_is_not_owned(owned_library, euro, game_on):
    row = _legacy(
        owned_library,
        game_on("Rented"),
        date(YEAR, 3, 1),
        ownership_type=LegacyPurchase.RENTED,
        price=5,
    )

    _reason_of(owned_library, row, Reason.NOT_OWNED)


def test_a_demo_is_a_prerelease_copy(owned_library, euro, game_on):
    row = _legacy(
        owned_library,
        game_on("Demo"),
        date(YEAR, 3, 1),
        ownership_type=LegacyPurchase.DEMO,
        price=0,
    )

    _reason_of(owned_library, row, Reason.PRERELEASE)


def test_a_dlc_counts_through_its_own_game(owned_library, euro, game_on):
    base = game_on("Base", status=PlayerGameStatus.COMPLETED)
    row = _legacy(
        owned_library,
        base,
        date(YEAR, 3, 1),
        type=LegacyPurchase.DLC,
        name="Expansion",
        related_game=base,
        price=5,
    )

    _reason_of(owned_library, row, Reason.ADDON_GAME)


def test_a_mixed_infinite_game_moves_its_exclusion(owned_library, euro, game_on):
    game = game_on("Endless")
    _legacy(owned_library, game, date(YEAR, 3, 1), infinite=True, price=5)
    finite = _legacy(owned_library, game, date(YEAR, 4, 1), price=5)

    _reason_of(owned_library, finite, Reason.EXCLUSION_MOVED)


def test_a_pass_rides_the_base_copy(owned_library, euro, game_on):
    game = game_on("Destiny")
    _legacy(owned_library, game, date(YEAR, 3, 1), price=10)
    season = _legacy(
        owned_library,
        game,
        date(YEAR, 4, 1),
        type=LegacyPurchase.SEASONPASS,
        name="Year 1",
        related_game=game,
        price=5,
    )

    _reason_of(owned_library, season, Reason.RIDES_BASE)


def test_a_pass_without_a_base_records_its_own_copy(owned_library, euro, game_on):
    game = game_on("Lonely")
    season = _legacy(
        owned_library,
        game,
        date(YEAR, 4, 1),
        type=LegacyPurchase.SEASONPASS,
        name="Year 1",
        related_game=game,
        price=5,
    )

    _reason_of(owned_library, season, Reason.OWN_COPY)


def test_a_price_nobody_knows(owned_library, euro, game_on):
    row = _legacy(
        owned_library,
        game_on("Unpriced"),
        date(YEAR, 3, 1),
        price=0,
        converted_price=0,
        converted_currency="EUR",
    )

    _reason_of(owned_library, row, Reason.UNKNOWN_PRICE)


def test_a_price_without_a_valuation(owned_library, game_on):
    row = _legacy(
        owned_library,
        game_on("Unvalued"),
        date(YEAR, 3, 1),
        price=10,
        price_currency="USD",
        converted_price=9,
        converted_currency="EUR",
    )

    _reason_of(owned_library, row, Reason.NO_VALUATION)


def test_a_purchase_recorded_since(owned_library, euro, game_on):
    game = game_on("Later")
    _legacy(owned_library, game, date(YEAR, 3, 1), price=10)
    snapshot = _snapshot(owned_library)
    _convert(owned_library)
    record_purchase(
        LibraryEntry.objects.get(player_game__game=game),
        purchased=TemporalValue.parse(f"{YEAR}-05-01"),
    )

    judged = _judged(owned_library, snapshot)
    [purchases] = [
        judgement
        for judgement in judged[str(YEAR)].judgements
        if judgement.rows_key == "purchases"
    ]

    assert purchases.recorded_since == 1
    assert not _unattributed(judged)
