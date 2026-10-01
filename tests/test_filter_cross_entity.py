"""Repointed cross-entity filter widgets (#123 Phase 2d).

Nine GameFilter widgets (and one PurchaseFilter widget) stopped emitting a flat
top-level convenience key and now emit the canonical NESTED cross-entity
sub-filter form, composed as INDEPENDENT EXISTS — each its own element of the
parent's n-ary ``AND`` list. This module asserts:

- the JSON each repointed widget emits parses + ``to_q()``-selects the right rows
  (equivalent to the flat oracle where one exists);
- two widgets over the SAME relation compose as independent EXISTS, not a single
  merged relation node;
- prefill reads those AND elements back and re-renders the widget populated.
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from devices import create_device
from django.contrib.auth import get_user_model
from django.utils import timezone
from entries import record_entry
from filter_contexts import unrestricted_filter_context
from graphs import default_graph
from purchases import record_purchase, refund_purchase
from session_rows import session_row

from games.filters import (
    parse_game_filter,
    parse_purchase_filter,
    parse_session_filter,
)
from games.models import (
    Device,
    Game,
    Platform,
    PlayerSession,
    Playthrough,
    Purchase,
)
from timetracker.temporal import TemporalValue

UNRESTRICTED_FILTER_CONTEXT = unrestricted_filter_context(ZoneInfo("UTC"))


@pytest.fixture(autouse=True)
def _single_library_filter_world(db, monkeypatch):
    """These algebra tests use one explicit owner; isolation is tested elsewhere."""
    user = get_user_model().objects.create_user(username="cross-entity-owner")

    def owned_create(original):
        def create(**kwargs):
            kwargs.setdefault("library", user.library)
            return original(**kwargs)

        return create

    for model in (Game,):
        manager = model.objects
        monkeypatch.setattr(manager, "create", owned_create(manager.create))
    return user.library


def _session_ids(filter_json: str) -> set[UUID]:
    parsed = parse_session_filter(filter_json)
    assert parsed is not None
    return set(
        PlayerSession.objects.filter(parsed.to_q(UNRESTRICTED_FILTER_CONTEXT))
        .distinct()
        .values_list("id", flat=True)
    )


def _dt(year=2024, month=6, day=1):
    return datetime(year, month, day, 12, 0, tzinfo=UTC)


def _game_ids(filter_json: str) -> set[UUID]:
    parsed = parse_game_filter(filter_json)
    assert parsed is not None
    return set(
        Game.objects.filter(parsed.to_q(UNRESTRICTED_FILTER_CONTEXT))
        .distinct()
        .values_list("id", flat=True)
    )


def _bought(game, *, format: str = "digital", refunded: bool = False, **purchase):
    """One copy of the game, bought."""
    entry = record_entry(
        game.library, default_graph(game, game.library).release, format=format
    )
    bought = record_purchase(
        entry, purchased=TemporalValue.parse("2024-01-01"), **purchase
    )
    if refunded:
        refund_purchase(bought, TemporalValue.parse("2024-02-01"))
    return bought


def _set_criterion(value: str, label: str) -> dict:
    return {
        "value": [{"id": value, "label": label}],
        "excludes": [],
        "modifier": "INCLUDES",
    }


# ── round-trip: the emitted JSON selects the right games ─────────────────────


@pytest.fixture
def device_world(_single_library_filter_world):
    pc = Platform.objects.create(name="PC")
    deck = create_device(
        _single_library_filter_world, name="SteamDeck", type=Device.HANDHELD
    )
    desktop = create_device(
        _single_library_filter_world, name="Desktop", type=Device.PC
    )
    on_deck = Game.objects.create(name="OnDeck", platform=pc)
    on_desktop = Game.objects.create(name="OnDesktop", platform=pc)
    Game.objects.create(name="NoSessions", platform=pc)
    session_row(on_deck, started_at=_dt(), device=deck)
    session_row(on_desktop, started_at=_dt(), device=desktop)
    return {"deck": deck, "on_deck": on_deck.id, "on_desktop": on_desktop.id}


def test_device_widget_json_selects_games(device_world):
    """Repointed device widget emits AND→session_filter→device."""
    filter_json = json.dumps(
        {
            "AND": [
                {
                    "session_filter": {
                        "device": _set_criterion(
                            str(device_world["deck"].id), "SteamDeck"
                        )
                    }
                }
            ]
        }
    )
    assert _game_ids(filter_json) == {device_world["on_deck"]}


@pytest.fixture
def purchase_world(db):
    pc = Platform.objects.create(name="PC")
    game_buyer = Game.objects.create(name="GameBuyer", platform=pc)
    pass_buyer = Game.objects.create(name="PassBuyer", platform=pc)
    Game.objects.create(name="NoPurchase", platform=pc)

    _bought(game_buyer, amount=Decimal(10))
    _bought(pass_buyer, kind="season_pass", name="Pass", amount=Decimal(50))
    return {"game_buyer": game_buyer.id, "pass_buyer": pass_buyer.id}


def test_purchase_kind_widget_json_selects_games(purchase_world):
    filter_json = json.dumps(
        {"AND": [{"purchase_filter": {"kind": _set_criterion("game", "Game")}}]}
    )
    assert _game_ids(filter_json) == {purchase_world["game_buyer"]}


def test_purchase_format_widget_json_selects_games(db):
    """AND→purchase_filter→format reads the copy."""
    pc = Platform.objects.create(name="PC")
    physical = Game.objects.create(name="Physical", platform=pc)
    digital = Game.objects.create(name="Digital", platform=pc)
    Game.objects.create(name="NoPurchase", platform=pc)
    _bought(physical, format="physical")
    _bought(digital)

    filter_json = json.dumps(
        {
            "AND": [
                {"purchase_filter": {"format": _set_criterion("physical", "Physical")}}
            ]
        }
    )
    assert _game_ids(filter_json) == {physical.id}


def test_purchase_price_any_widget_json_selects_games(purchase_world):
    filter_json = json.dumps(
        {
            "AND": [
                {
                    "purchase_filter": {
                        "amount": {
                            "value": 20,
                            "modifier": "GREATER_THAN",
                        }
                    }
                }
            ]
        }
    )
    assert _game_ids(filter_json) == {purchase_world["pass_buyer"]}  # 50 > 20


def _state_run(game: Game, **stated: object) -> None:
    """State a fact on the game's run."""
    Playthrough.objects.filter(player_game__game=game).update(**stated)


def _finished(game: Game, day: date) -> None:
    """The run finished on that day."""
    _state_run(
        game,
        completion_recorded_at=timezone.now(),
        completed=TemporalValue.from_day(day),
    )


def test_playthrough_note_widget_json_selects_games(db):
    pc = Platform.objects.create(name="PC")
    finished = Game.objects.create(name="Finished", platform=pc)
    started = Game.objects.create(name="Started", platform=pc)
    _state_run(finished, note="Completed the game")
    _state_run(started, note="Just started")

    filter_json = json.dumps(
        {
            "AND": [
                {
                    "playthrough_filter": {
                        "note": {"value": "Completed", "modifier": "INCLUDES"}
                    }
                }
            ]
        }
    )
    assert _game_ids(filter_json) == {finished.id}


def test_game_finished_widget_json_selects_games(db):
    pc = Platform.objects.create(name="PC")
    in_range = Game.objects.create(name="InRange", platform=pc)
    out_range = Game.objects.create(name="OutRange", platform=pc)
    _finished(in_range, date(2024, 6, 15))
    _finished(out_range, date(2023, 1, 1))

    filter_json = json.dumps(
        {
            "AND": [
                {
                    "playthrough_filter": {
                        "completed": {
                            "value": "2024-01-01",
                            "value2": "2024-12-31",
                            "modifier": "BETWEEN",
                        }
                    }
                }
            ]
        }
    )
    assert _game_ids(filter_json) == {in_range.id}


def test_game_finished_widget_json_min_only_and_max_only(db):
    """One bound emits GREATER_THAN or LESS_THAN."""
    pc = Platform.objects.create(name="PC")
    early = Game.objects.create(name="Early", platform=pc)
    middle = Game.objects.create(name="Middle", platform=pc)
    late = Game.objects.create(name="Late", platform=pc)
    _finished(early, date(2023, 1, 1))
    _finished(middle, date(2024, 6, 15))
    _finished(late, date(2025, 12, 31))

    min_only = json.dumps(
        {
            "AND": [
                {
                    "playthrough_filter": {
                        "completed": {"value": "2024-01-01", "modifier": "GREATER_THAN"}
                    }
                }
            ]
        }
    )
    assert _game_ids(min_only) == {middle.id, late.id}

    max_only = json.dumps(
        {
            "AND": [
                {
                    "playthrough_filter": {
                        "completed": {"value": "2024-12-31", "modifier": "LESS_THAN"}
                    }
                }
            ]
        }
    )
    assert _game_ids(max_only) == {early.id, middle.id}


# ── relation match: ANY (default) vs NONE ────────────────────────────────────


@pytest.fixture
def emulated_world(db):
    pc = Platform.objects.create(name="PC")
    emulated = Game.objects.create(name="Emulated", platform=pc)
    native = Game.objects.create(name="Native", platform=pc)
    no_sessions = Game.objects.create(name="NoSessions", platform=pc)
    session_row(emulated, started_at=_dt(), emulated=True)
    session_row(native, started_at=_dt(), emulated=False)
    return {
        "emulated": emulated.id,
        "native": native.id,
        "no_sessions": no_sessions.id,
    }


def _relation_bool_json(relation_field: str, child: dict, *, value: bool) -> str:
    relation: dict = dict(child)
    if not value:
        relation = {"match": "NONE", **child}
    return json.dumps({"AND": [{relation_field: relation}]})


def test_session_emulated_true_matches_any(emulated_world):
    filter_json = _relation_bool_json(
        "session_filter",
        {"emulated": {"value": True, "modifier": "EQUALS"}},
        value=True,
    )
    assert _game_ids(filter_json) == {emulated_world["emulated"]}


def test_session_emulated_false_matches_none(emulated_world):
    """False → NONE: games with no emulated session, including zero-session games."""
    filter_json = _relation_bool_json(
        "session_filter",
        {"emulated": {"value": True, "modifier": "EQUALS"}},
        value=False,
    )
    assert _game_ids(filter_json) == {
        emulated_world["native"],
        emulated_world["no_sessions"],
    }


def test_purchase_refunded_false_matches_none(db):
    pc = Platform.objects.create(name="PC")
    refunded = Game.objects.create(name="Refunded", platform=pc)
    kept = Game.objects.create(name="Kept", platform=pc)
    none = Game.objects.create(name="NoPurchase", platform=pc)
    _bought(refunded, refunded=True)
    _bought(kept)

    filter_json = _relation_bool_json(
        "purchase_filter",
        {"is_refunded": {"value": True, "modifier": "EQUALS"}},
        value=False,
    )
    assert _game_ids(filter_json) == {kept.id, none.id}


def test_purchase_refunded_true_matches_any(db):
    """True → ANY: games with at least one refunded purchase."""
    pc = Platform.objects.create(name="PC")
    refunded = Game.objects.create(name="Refunded", platform=pc)
    kept = Game.objects.create(name="Kept", platform=pc)
    Game.objects.create(name="NoPurchase", platform=pc)
    _bought(refunded, refunded=True)
    _bought(kept)

    filter_json = _relation_bool_json(
        "purchase_filter",
        {"is_refunded": {"value": True, "modifier": "EQUALS"}},
        value=True,
    )
    assert _game_ids(filter_json) == {refunded.id}


# ── two widgets over one relation = independent EXISTS ────────────────────────


@pytest.fixture
def two_purchase_world(db):
    """A game whose two qualifying purchases are *distinct* rows: a game
    purchase on a digital copy and a pass on a separate physical copy. Only
    independent EXISTS matches it; a merged single-node filter (one purchase
    must be BOTH) does not."""
    pc = Platform.objects.create(name="PC")
    split = Game.objects.create(name="Split", platform=pc)
    combined = Game.objects.create(name="Combined", platform=pc)

    _bought(split)
    _bought(split, format="physical", kind="season_pass", name="Pass")
    # combined: one purchase that is BOTH kind=game AND on a physical copy.
    _bought(combined, format="physical")
    return {"split": split.id, "combined": combined.id}


def test_two_widgets_same_relation_are_independent_exists(two_purchase_world):
    """kind=game AND format=physical as two AND elements: independent
    EXISTS, so a game with a game purchase AND a SEPARATE purchase on a
    physical copy matches."""
    independent = json.dumps(
        {
            "AND": [
                {"purchase_filter": {"kind": _set_criterion("game", "Game")}},
                {"purchase_filter": {"format": _set_criterion("physical", "Physical")}},
            ]
        }
    )
    assert _game_ids(independent) == {
        two_purchase_world["split"],
        two_purchase_world["combined"],
    }


def test_merged_single_node_requires_one_matching_row(two_purchase_world):
    """Contrast: the WRONG single merged relation node requires ONE purchase to
    match BOTH kind=game and format=physical, so the split game is excluded."""
    merged = json.dumps(
        {
            "AND": [
                {
                    "purchase_filter": {
                        "kind": _set_criterion("game", "Game"),
                        "format": _set_criterion("physical", "Physical"),
                    }
                }
            ]
        }
    )
    assert _game_ids(merged) == {two_purchase_world["combined"]}


# ── purchase bar: finished → game_filter → playthrough_filter → completed ────


def test_purchase_finished_widget_json_selects_purchases(db):

    pc = Platform.objects.create(name="PC")
    finished_game = Game.objects.create(name="Finished", platform=pc)
    other_game = Game.objects.create(name="Other", platform=pc)
    _finished(finished_game, date(2024, 6, 15))

    bought_finished = _bought(finished_game)
    _bought(other_game)

    filter_json = json.dumps(
        {
            "AND": [
                {
                    "game_filter": {
                        "playthrough_filter": {
                            "completed": {
                                "value": "2024-01-01",
                                "value2": "2024-12-31",
                                "modifier": "BETWEEN",
                            }
                        }
                    }
                }
            ]
        }
    )
    parsed = parse_purchase_filter(filter_json)
    assert parsed is not None
    purchase_ids = set(
        Purchase.objects.filter(parsed.to_q(UNRESTRICTED_FILTER_CONTEXT))
        .distinct()
        .values_list("id", flat=True)
    )
    assert purchase_ids == {bought_finished.id}


def test_historical_playtime_widget_json_selects_games(owned_library):
    from historical_playtime_rows import record_row
    from session_rows import tracked_run

    from games.models import HistoricalPlaytimeProvenance

    estimated = Game.objects.create(library=owned_library, name="Estimated")
    measured = Game.objects.create(library=owned_library, name="Measured")
    record_row(
        [tracked_run(owned_library, estimated)],
        provenance=HistoricalPlaytimeProvenance.ESTIMATED,
    )
    record_row(
        [tracked_run(owned_library, measured)],
        provenance=HistoricalPlaytimeProvenance.EXTERNALLY_MEASURED,
    )

    filter_json = json.dumps(
        {
            "historical_playtime_filter": {
                "provenance": {"value": ["estimated"], "modifier": "INCLUDES"}
            }
        }
    )
    assert _game_ids(filter_json) == {estimated.id}

    none_json = json.dumps(
        {
            "historical_playtime_filter": {
                "match": "NONE",
                "provenance": {"value": ["estimated"], "modifier": "INCLUDES"},
            }
        }
    )
    unrecorded = Game.objects.create(library=owned_library, name="Unrecorded")
    assert _game_ids(none_json) >= {measured.id, unrecorded.id}
    assert estimated.id not in _game_ids(none_json)


def test_a_record_within_the_year_selects_the_game(owned_library):
    from historical_playtime_rows import record_row
    from session_rows import tracked_run

    inside = Game.objects.create(library=owned_library, name="Inside")
    straddling = Game.objects.create(library=owned_library, name="Straddling")
    record_row([tracked_run(owned_library, inside)], when="2024-03")
    record_row([tracked_run(owned_library, straddling)], when="2023-12/2024-01")

    filter_json = json.dumps(
        {
            "historical_playtime_filter": {
                "when": {
                    "value": "2024-01-01",
                    "value2": "2024-12-31",
                    "modifier": "WITHIN",
                }
            }
        }
    )
    assert _game_ids(filter_json) == {inside.id}
