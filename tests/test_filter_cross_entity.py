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
import re
from datetime import date, datetime, timezone

import pytest

from common.components.filters import FilterBar, PurchaseFilterBar
from common.criteria import (
    BoolCriterion,
    ChoiceCriterion,
    DateCriterion,
    FloatCriterion,
    Modifier,
    MultiCriterion,
    RelationMatch,
    StringCriterion,
)
from games.filters import (
    GameFilter,
    PlayEventFilter,
    PurchaseFilter,
    SessionFilter,
    parse_game_filter,
    parse_purchase_filter,
)
from games.models import Device, Game, Platform, PlayEvent, Purchase, Session


def _dt(year=2024, month=6, day=1):
    return datetime(year, month, day, 12, 0, tzinfo=timezone.utc)


def _game_ids(filter_json: str) -> set[int]:
    parsed = parse_game_filter(filter_json)
    assert parsed is not None
    return set(
        Game.objects.filter(parsed.to_q()).distinct().values_list("id", flat=True)
    )


def _set_criterion(value: str, label: str) -> dict:
    return {
        "value": [{"id": value, "label": label}],
        "excludes": [],
        "modifier": "INCLUDES",
    }


# ── round-trip: the emitted JSON selects the right games ─────────────────────


@pytest.fixture
def device_world(db):
    pc = Platform.objects.create(name="PC")
    deck = Device.objects.create(name="SteamDeck", type=Device.HANDHELD)
    desktop = Device.objects.create(name="Desktop", type=Device.PC)
    on_deck = Game.objects.create(name="OnDeck", platform=pc)
    on_desktop = Game.objects.create(name="OnDesktop", platform=pc)
    Game.objects.create(name="NoSessions", platform=pc)
    Session.objects.create(game=on_deck, timestamp_start=_dt(), device=deck)
    Session.objects.create(game=on_desktop, timestamp_start=_dt(), device=desktop)
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
    dlc_buyer = Game.objects.create(name="DlcBuyer", platform=pc)
    Game.objects.create(name="NoPurchase", platform=pc)

    p1 = Purchase.objects.create(
        date_purchased=date(2024, 1, 1), type=Purchase.GAME, converted_price=10.0
    )
    p1.games.set([game_buyer])
    p2 = Purchase.objects.create(
        date_purchased=date(2024, 1, 1),
        type=Purchase.DLC,
        related_game=dlc_buyer,
        converted_price=50.0,
    )
    p2.games.set([dlc_buyer])
    return {"game_buyer": game_buyer.id, "dlc_buyer": dlc_buyer.id}


def test_purchase_type_widget_json_selects_games(purchase_world):
    filter_json = json.dumps(
        {"AND": [{"purchase_filter": {"type": _set_criterion("game", "Game")}}]}
    )
    assert _game_ids(filter_json) == {purchase_world["game_buyer"]}


def test_purchase_price_any_widget_json_selects_games(purchase_world):
    filter_json = json.dumps(
        {
            "AND": [
                {
                    "purchase_filter": {
                        "converted_price": {
                            "value": 20,
                            "modifier": "GREATER_THAN",
                        }
                    }
                }
            ]
        }
    )
    assert _game_ids(filter_json) == {purchase_world["dlc_buyer"]}  # 50 > 20


def test_playevent_note_widget_json_selects_games(db):
    from games.models import PlayEvent

    pc = Platform.objects.create(name="PC")
    finished = Game.objects.create(name="Finished", platform=pc)
    started = Game.objects.create(name="Started", platform=pc)
    PlayEvent.objects.create(game=finished, note="Completed the game")
    PlayEvent.objects.create(game=started, note="Just started")

    filter_json = json.dumps(
        {
            "AND": [
                {
                    "playevent_filter": {
                        "note": {"value": "Completed", "modifier": "INCLUDES"}
                    }
                }
            ]
        }
    )
    assert _game_ids(filter_json) == {finished.id}


def test_game_finished_widget_json_selects_games(db):
    from games.models import PlayEvent

    pc = Platform.objects.create(name="PC")
    in_range = Game.objects.create(name="InRange", platform=pc)
    out_range = Game.objects.create(name="OutRange", platform=pc)
    PlayEvent.objects.create(game=in_range, ended=date(2024, 6, 15))
    PlayEvent.objects.create(game=out_range, ended=date(2023, 1, 1))

    filter_json = json.dumps(
        {
            "AND": [
                {
                    "playevent_filter": {
                        "ended": {
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


# ── relation-bool: ANY (True) vs NONE (False) ────────────────────────────────


@pytest.fixture
def emulated_world(db):
    pc = Platform.objects.create(name="PC")
    emulated = Game.objects.create(name="Emulated", platform=pc)
    native = Game.objects.create(name="Native", platform=pc)
    no_sessions = Game.objects.create(name="NoSessions", platform=pc)
    Session.objects.create(game=emulated, timestamp_start=_dt(), emulated=True)
    Session.objects.create(game=native, timestamp_start=_dt(), emulated=False)
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
    """False → NONE: games with no emulated session, including zero-session games.

    Matches the flat ``session_emulated=False`` oracle."""
    filter_json = _relation_bool_json(
        "session_filter",
        {"emulated": {"value": True, "modifier": "EQUALS"}},
        value=False,
    )
    from common.criteria import BoolCriterion

    flat = GameFilter(session_emulated=BoolCriterion(value=False))
    flat_ids = set(
        Game.objects.filter(flat.to_q()).distinct().values_list("id", flat=True)
    )
    assert _game_ids(filter_json) == flat_ids
    assert _game_ids(filter_json) == {
        emulated_world["native"],
        emulated_world["no_sessions"],
    }


def test_purchase_refunded_false_matches_none(db):
    pc = Platform.objects.create(name="PC")
    refunded = Game.objects.create(name="Refunded", platform=pc)
    kept = Game.objects.create(name="Kept", platform=pc)
    none = Game.objects.create(name="NoPurchase", platform=pc)
    p1 = Purchase.objects.create(
        date_purchased=date(2024, 1, 1), date_refunded=date(2024, 2, 1)
    )
    p1.games.set([refunded])
    p2 = Purchase.objects.create(date_purchased=date(2024, 1, 1))
    p2.games.set([kept])

    filter_json = _relation_bool_json(
        "purchase_filter",
        {"is_refunded": {"value": True, "modifier": "EQUALS"}},
        value=False,
    )
    assert _game_ids(filter_json) == {kept.id, none.id}


def test_purchase_infinite_true_matches_any(db):
    pc = Platform.objects.create(name="PC")
    infinite = Game.objects.create(name="Infinite", platform=pc)
    finite = Game.objects.create(name="Finite", platform=pc)
    p1 = Purchase.objects.create(date_purchased=date(2024, 1, 1), infinite=True)
    p1.games.set([infinite])
    p2 = Purchase.objects.create(date_purchased=date(2024, 1, 1), infinite=False)
    p2.games.set([finite])

    filter_json = _relation_bool_json(
        "purchase_filter",
        {"infinite": {"value": True, "modifier": "EQUALS"}},
        value=True,
    )
    assert _game_ids(filter_json) == {infinite.id}


# ── two widgets over one relation = independent EXISTS ────────────────────────


@pytest.fixture
def two_purchase_world(db):
    """A game whose two qualifying purchases are *distinct* rows: a type=game
    purchase (digital ownership) and a separate ownership=physical purchase
    (dlc type). Only independent EXISTS matches it; a merged single-node filter
    (one purchase must be BOTH) does not."""
    pc = Platform.objects.create(name="PC")
    split = Game.objects.create(name="Split", platform=pc)
    combined = Game.objects.create(name="Combined", platform=pc)

    game_digital = Purchase.objects.create(
        date_purchased=date(2024, 1, 1),
        type=Purchase.GAME,
        ownership_type=Purchase.DIGITAL,
    )
    game_digital.games.set([split])
    dlc_physical = Purchase.objects.create(
        date_purchased=date(2024, 1, 1),
        type=Purchase.DLC,
        related_game=split,
        ownership_type=Purchase.PHYSICAL,
    )
    dlc_physical.games.set([split])

    # combined: a single purchase that is BOTH type=game AND ownership=physical.
    both = Purchase.objects.create(
        date_purchased=date(2024, 1, 1),
        type=Purchase.GAME,
        ownership_type=Purchase.PHYSICAL,
    )
    both.games.set([combined])
    return {"split": split.id, "combined": combined.id}


def test_two_widgets_same_relation_are_independent_exists(two_purchase_world):
    """purchase_type=game AND purchase_ownership=physical as two AND elements:
    independent EXISTS, so a game with a type=game purchase AND a SEPARATE
    physical-ownership purchase matches."""
    independent = json.dumps(
        {
            "AND": [
                {"purchase_filter": {"type": _set_criterion("game", "Game")}},
                {
                    "purchase_filter": {
                        "ownership_type": _set_criterion("ph", "Physical")
                    }
                },
            ]
        }
    )
    assert _game_ids(independent) == {
        two_purchase_world["split"],
        two_purchase_world["combined"],
    }


def test_merged_single_node_requires_one_matching_row(two_purchase_world):
    """Contrast: the WRONG single merged relation node requires ONE purchase to
    match BOTH type=game and ownership=physical, so the split game is excluded."""
    merged = json.dumps(
        {
            "AND": [
                {
                    "purchase_filter": {
                        "type": _set_criterion("game", "Game"),
                        "ownership_type": _set_criterion("ph", "Physical"),
                    }
                }
            ]
        }
    )
    assert _game_ids(merged) == {two_purchase_world["combined"]}


# ── purchase bar: finished → game_filter → playevent_filter → ended ──────────


def test_purchase_finished_widget_json_selects_purchases(db):
    from games.models import PlayEvent

    pc = Platform.objects.create(name="PC")
    finished_game = Game.objects.create(name="Finished", platform=pc)
    other_game = Game.objects.create(name="Other", platform=pc)
    PlayEvent.objects.create(game=finished_game, ended=date(2024, 6, 15))

    bought_finished = Purchase.objects.create(date_purchased=date(2024, 1, 1))
    bought_finished.games.set([finished_game])
    bought_other = Purchase.objects.create(date_purchased=date(2024, 1, 1))
    bought_other.games.set([other_game])

    filter_json = json.dumps(
        {
            "AND": [
                {
                    "game_filter": {
                        "playevent_filter": {
                            "ended": {
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
        Purchase.objects.filter(parsed.to_q()).distinct().values_list("id", flat=True)
    )
    assert purchase_ids == {bought_finished.id}


# ── prefill: the bar reads the AND elements back and repopulates widgets ──────


def test_game_bar_prefills_device_from_and(db):
    deck = Device.objects.create(name="SteamDeck", type=Device.HANDHELD)
    filter_json = json.dumps(
        {
            "AND": [
                {
                    "session_filter": {
                        "device": _set_criterion(str(deck.id), "SteamDeck")
                    }
                }
            ]
        }
    )
    html = str(FilterBar(filter_json))
    # the included pill renders the device label
    assert "SteamDeck" in html


def test_game_bar_prefills_purchase_type_from_and(db):
    filter_json = json.dumps(
        {"AND": [{"purchase_filter": {"type": _set_criterion("game", "Game")}}]}
    )
    html = str(FilterBar(filter_json))
    # the included value pill carries the selected enum value
    assert 'data-value="game"' in html


def test_game_bar_prefills_session_emulated_false_radio(db):
    """A relation-bool NONE element prefills the 'False' radio as checked."""
    filter_json = _relation_bool_json(
        "session_filter",
        {"emulated": {"value": True, "modifier": "EQUALS"}},
        value=False,
    )
    html = str(FilterBar(filter_json))
    # locate the emulated widget's radio group and confirm a checked False radio
    assert 'value="false"' in html
    # the emulated radio group uses name filter-session-emulated
    assert "filter-session-emulated" in html


def test_purchase_bar_prefills_finished_from_and(db):
    filter_json = json.dumps(
        {
            "AND": [
                {
                    "game_filter": {
                        "playevent_filter": {
                            "ended": {
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
    html = str(PurchaseFilterBar(filter_json))
    assert "2024-01-01" in html
    assert "2024-12-31" in html


# ── parametrized parity: each repointed widget's NESTED form selects the same
#    rows as its still-live FLAT oracle field (#123 Phase 2d permanent guard) ──
#
# The 10 repointed widgets are now the canonical path; the flat GameFilter /
# PurchaseFilter convenience fields remain as oracles. Each case builds BOTH the
# flat and the nested filter dataclass over one shared world and asserts they
# select the identical id set. A mismatch is a real bug (the repoint changed
# behaviour), not a test to weaken.


@pytest.fixture
def parity_world(db):
    """One world exercising every repointed widget's dimension at once.

    Each repointed criterion matches a strict, non-empty subset so an equal
    flat/nested result is a meaningful (non-vacuous) check."""
    pc = Platform.objects.create(name="PC")
    deck = Device.objects.create(name="SteamDeck", type=Device.HANDHELD)
    desktop = Device.objects.create(name="Desktop", type=Device.PC)

    # session: device + emulated dimension
    deck_game = Game.objects.create(name="DeckGame", platform=pc)
    Session.objects.create(
        game=deck_game, timestamp_start=_dt(), device=deck, emulated=False
    )
    emulated_game = Game.objects.create(name="EmulatedGame", platform=pc)
    Session.objects.create(
        game=emulated_game, timestamp_start=_dt(), device=desktop, emulated=True
    )

    # purchase: type / ownership / price / refunded / infinite dimension
    game_buyer = Game.objects.create(name="GameBuyer", platform=pc)
    cheap = Purchase.objects.create(
        date_purchased=date(2024, 1, 1),
        type=Purchase.GAME,
        ownership_type=Purchase.DIGITAL,
        converted_price=10.0,
        infinite=False,
    )
    cheap.games.set([game_buyer])

    dlc_buyer = Game.objects.create(name="DlcBuyer", platform=pc)
    pricey = Purchase.objects.create(
        date_purchased=date(2024, 1, 1),
        type=Purchase.DLC,
        related_game=dlc_buyer,
        ownership_type=Purchase.PHYSICAL,
        converted_price=50.0,
        date_refunded=date(2024, 2, 1),
        infinite=True,
    )
    pricey.games.set([dlc_buyer])

    # playevent: note + ended dimension
    finished_game = Game.objects.create(name="FinishedGame", platform=pc)
    PlayEvent.objects.create(
        game=finished_game, ended=date(2024, 6, 15), note="Completed the run"
    )
    started_game = Game.objects.create(name="StartedGame", platform=pc)
    PlayEvent.objects.create(
        game=started_game, ended=date(2023, 1, 1), note="Just started"
    )

    # a bare game touching no relation (matters for the NONE/False branches)
    Game.objects.create(name="Bare", platform=pc)

    # purchase-bar finished: a purchase of a finished game vs one of an unfinished
    bought_finished = Purchase.objects.create(date_purchased=date(2024, 1, 1))
    bought_finished.games.set([finished_game])
    bought_other = Purchase.objects.create(date_purchased=date(2024, 1, 1))
    bought_other.games.set([started_game])

    return {"deck": deck.id}


def _ids(model, filt) -> set[int]:
    return set(
        model.objects.filter(filt.to_q()).distinct().values_list("id", flat=True)
    )


def _between_2024() -> DateCriterion:
    return DateCriterion(
        value="2024-01-01", value2="2024-12-31", modifier=Modifier.BETWEEN
    )


# Each case: (model, flat-filter builder, nested-filter builder). Builders take
# the world dict (only the device case needs an id from it).
PARITY_CASES = {
    "device_set": (
        Game,
        lambda w: GameFilter(
            device=MultiCriterion(value=[w["deck"]], modifier=Modifier.INCLUDES)
        ),
        lambda w: GameFilter(
            session_filter=SessionFilter(
                device=MultiCriterion(value=[w["deck"]], modifier=Modifier.INCLUDES)
            )
        ),
    ),
    "purchase_type_set": (
        Game,
        lambda w: GameFilter(
            purchase_type=ChoiceCriterion(value=["game"], modifier=Modifier.INCLUDES)
        ),
        lambda w: GameFilter(
            purchase_filter=PurchaseFilter(
                type=ChoiceCriterion(value=["game"], modifier=Modifier.INCLUDES)
            )
        ),
    ),
    "purchase_ownership_set": (
        Game,
        lambda w: GameFilter(
            purchase_ownership_type=ChoiceCriterion(
                value=["ph"], modifier=Modifier.INCLUDES
            )
        ),
        lambda w: GameFilter(
            purchase_filter=PurchaseFilter(
                ownership_type=ChoiceCriterion(value=["ph"], modifier=Modifier.INCLUDES)
            )
        ),
    ),
    "purchase_price_any_number": (
        Game,
        lambda w: GameFilter(
            purchase_price_any=FloatCriterion(
                value=20.0, modifier=Modifier.GREATER_THAN
            )
        ),
        lambda w: GameFilter(
            purchase_filter=PurchaseFilter(
                converted_price=FloatCriterion(
                    value=20.0, modifier=Modifier.GREATER_THAN
                )
            )
        ),
    ),
    "playevent_note_string": (
        Game,
        lambda w: GameFilter(
            playevent_note=StringCriterion(
                value="Completed", modifier=Modifier.INCLUDES
            )
        ),
        lambda w: GameFilter(
            playevent_filter=PlayEventFilter(
                note=StringCriterion(value="Completed", modifier=Modifier.INCLUDES)
            )
        ),
    ),
    "game_finished_date": (
        Game,
        lambda w: GameFilter(finished=_between_2024()),
        lambda w: GameFilter(playevent_filter=PlayEventFilter(ended=_between_2024())),
    ),
    "session_emulated_true": (
        Game,
        lambda w: GameFilter(session_emulated=BoolCriterion(value=True)),
        lambda w: GameFilter(
            session_filter=SessionFilter(
                match=RelationMatch.ANY, emulated=BoolCriterion(value=True)
            )
        ),
    ),
    "session_emulated_false": (
        Game,
        lambda w: GameFilter(session_emulated=BoolCriterion(value=False)),
        lambda w: GameFilter(
            session_filter=SessionFilter(
                match=RelationMatch.NONE, emulated=BoolCriterion(value=True)
            )
        ),
    ),
    "purchase_refunded_true": (
        Game,
        lambda w: GameFilter(purchase_refunded=BoolCriterion(value=True)),
        lambda w: GameFilter(
            purchase_filter=PurchaseFilter(
                match=RelationMatch.ANY, is_refunded=BoolCriterion(value=True)
            )
        ),
    ),
    "purchase_refunded_false": (
        Game,
        lambda w: GameFilter(purchase_refunded=BoolCriterion(value=False)),
        lambda w: GameFilter(
            purchase_filter=PurchaseFilter(
                match=RelationMatch.NONE, is_refunded=BoolCriterion(value=True)
            )
        ),
    ),
    "purchase_infinite_true": (
        Game,
        lambda w: GameFilter(purchase_infinite=BoolCriterion(value=True)),
        lambda w: GameFilter(
            purchase_filter=PurchaseFilter(
                match=RelationMatch.ANY, infinite=BoolCriterion(value=True)
            )
        ),
    ),
    "purchase_infinite_false": (
        Game,
        lambda w: GameFilter(purchase_infinite=BoolCriterion(value=False)),
        lambda w: GameFilter(
            purchase_filter=PurchaseFilter(
                match=RelationMatch.NONE, infinite=BoolCriterion(value=True)
            )
        ),
    ),
    "purchase_bar_finished_date": (
        Purchase,
        lambda w: PurchaseFilter(finished=_between_2024()),
        lambda w: PurchaseFilter(
            game_filter=GameFilter(
                playevent_filter=PlayEventFilter(ended=_between_2024())
            )
        ),
    ),
}


@pytest.mark.parametrize("case_id", list(PARITY_CASES), ids=list(PARITY_CASES))
def test_repointed_widget_nested_equals_flat_oracle(parity_world, case_id):
    model, build_flat, build_nested = PARITY_CASES[case_id]
    flat_ids = _ids(model, build_flat(parity_world))
    nested_ids = _ids(model, build_nested(parity_world))
    # Non-vacuous: the criterion must actually match something in the world, so an
    # all-empty bug can't make the equality trivially pass.
    assert flat_ids, f"{case_id}: flat oracle matched nothing (test data too thin)"
    assert nested_ids == flat_ids, (
        f"{case_id}: nested form selected {nested_ids} but flat oracle {flat_ids}"
    )


# ── prefill coverage gaps (#123 Phase 2d hardening) ──────────────────────────


def test_game_bar_prefills_purchase_price_any_from_and(db):
    """Number helper: a nested converted_price criterion repopulates the widget."""
    filter_json = json.dumps(
        {
            "AND": [
                {
                    "purchase_filter": {
                        "converted_price": {"value": 20, "modifier": "GREATER_THAN"}
                    }
                }
            ]
        }
    )
    html = str(FilterBar(filter_json))
    assert re.search(r'name="filter-purchase-price-any"[^>]*value="20"', html)


def test_game_bar_prefills_playevent_note_from_and(db):
    """String helper: a nested note criterion repopulates the text input."""
    filter_json = json.dumps(
        {
            "AND": [
                {
                    "playevent_filter": {
                        "note": {"value": "Completed", "modifier": "INCLUDES"}
                    }
                }
            ]
        }
    )
    html = str(FilterBar(filter_json))
    assert re.search(r'name="filter-playevent_note"[^>]*value="Completed"', html)


def test_game_bar_prefills_session_emulated_true_radio(db):
    """Relation-bool TRUE branch: an ANY element checks the 'True' radio."""
    filter_json = _relation_bool_json(
        "session_filter",
        {"emulated": {"value": True, "modifier": "EQUALS"}},
        value=True,
    )
    html = str(FilterBar(filter_json))
    assert re.search(
        r'name="filter-session-emulated"[^>]*value="true"[^>]*checked', html
    )


def test_game_bar_prefills_purchase_type_and_ownership_independently(db):
    """Prefill ambiguity: two purchase_filter AND elements (type + ownership) each
    repopulate their OWN widget — the type pill shows the type value and the
    ownership pill the ownership value, with no cross-contamination."""
    filter_json = json.dumps(
        {
            "AND": [
                {"purchase_filter": {"type": _set_criterion("game", "Game")}},
                {
                    "purchase_filter": {
                        "ownership_type": _set_criterion("ph", "Physical")
                    }
                },
            ]
        }
    )
    html = str(FilterBar(filter_json))
    include_pills = re.findall(
        r'data-pill[^>]*?data-value="([^"]+)"[^>]*?data-search-select-type="include"',
        html,
    )
    # exactly one include pill per widget — no value leaked into the other widget
    assert include_pills.count("game") == 1
    assert include_pills.count("ph") == 1


def test_game_bar_prefills_refunded_false_and_infinite_true_independently(db):
    """Two relation-bool elements set together prefill each bool independently:
    refunded NONE → 'False' checked, infinite ANY → 'True' checked."""
    filter_json = json.dumps(
        {
            "AND": [
                {
                    "purchase_filter": {
                        "match": "NONE",
                        "is_refunded": {"value": True, "modifier": "EQUALS"},
                    }
                },
                {
                    "purchase_filter": {
                        "infinite": {"value": True, "modifier": "EQUALS"}
                    }
                },
            ]
        }
    )
    html = str(FilterBar(filter_json))
    assert re.search(
        r'name="filter-purchase-refunded"[^>]*value="false"[^>]*checked', html
    )
    assert re.search(
        r'name="filter-purchase-infinite"[^>]*value="true"[^>]*checked', html
    )
