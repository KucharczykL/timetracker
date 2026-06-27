"""Tests for the relation algebra added in #123 Phase 1:

- relation match-mode (ANY/NONE) on nested cross-entity sub-filters, and its
  JSON round-trip;
- equivalence of the new nested NONE form with the old flat NOT-EXISTS
  convenience fields (the mapping Phase 2's widgets will rely on);
- the first-class AggregateCriterion (count / sum) replacing the bespoke
  annotate subqueries.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from common.criteria import (
    AggregateCriterion,
    BoolCriterion,
    Modifier,
    MultiCriterion,
    RelationMatch,
    StringCriterion,
)
from games.filters import GameFilter, PurchaseFilter, SessionFilter
from games.models import Device, Game, Platform, Purchase, Session


def _dt(year=2024, month=6, day=1):
    return datetime(year, month, day, 12, 0, tzinfo=timezone.utc)


def _ids(filter_obj):
    return set(
        Game.objects.filter(filter_obj.to_q()).distinct().values_list("id", flat=True)
    )


@pytest.fixture
def emulated_world(db):
    """Four games spanning every emulated-session combination, including the
    zero-session edge case that separates ANY/NONE semantics."""
    pc = Platform.objects.create(name="PC")
    emu_only = Game.objects.create(name="EmuOnly", platform=pc)
    both = Game.objects.create(name="Both", platform=pc)
    non_emu = Game.objects.create(name="NonEmu", platform=pc)
    no_sessions = Game.objects.create(name="NoSessions", platform=pc)

    Session.objects.create(game=emu_only, timestamp_start=_dt(), emulated=True)
    Session.objects.create(game=both, timestamp_start=_dt(2024, 6, 2), emulated=True)
    Session.objects.create(game=both, timestamp_start=_dt(2024, 6, 3), emulated=False)
    Session.objects.create(
        game=non_emu, timestamp_start=_dt(2024, 6, 4), emulated=False
    )

    return {
        "emu_only": emu_only.id,
        "both": both.id,
        "non_emu": non_emu.id,
        "no_sessions": no_sessions.id,
    }


# ── match-mode semantics ─────────────────────────────────────────────────────


def test_relation_any_matches_existence(emulated_world):
    """ANY (default) = has at least one session matching the sub-filter."""
    any_emulated = GameFilter(
        session_filter=SessionFilter(emulated=BoolCriterion(value=True))
    )
    assert _ids(any_emulated) == {emulated_world["emu_only"], emulated_world["both"]}


def test_relation_none_is_not_exists(emulated_world):
    """NONE = has no session matching the sub-filter, including games with zero
    sessions (the case a positive ANY(emulated=False) would miss)."""
    no_emulated = GameFilter(
        session_filter=SessionFilter(
            emulated=BoolCriterion(value=True), match=RelationMatch.NONE
        )
    )
    assert _ids(no_emulated) == {
        emulated_world["non_emu"],
        emulated_world["no_sessions"],
    }


def test_empty_none_subfilter_means_no_related_rows(emulated_world):
    """A match-only NONE node (no child criteria) = "has no sessions at all"."""
    no_sessions = GameFilter(session_filter=SessionFilter(match=RelationMatch.NONE))
    assert _ids(no_sessions) == {emulated_world["no_sessions"]}


# ── equivalence with the flat convenience fields (Phase 2 mapping) ───────────


def test_nested_matches_flat_session_emulated(emulated_world):
    """The flat session_emulated bool and the nested match-mode form must select
    identical games for both True (ANY) and False (NONE)."""
    for value, match in [(True, RelationMatch.ANY), (False, RelationMatch.NONE)]:
        flat = GameFilter(session_emulated=BoolCriterion(value=value))
        nested = GameFilter(
            session_filter=SessionFilter(
                emulated=BoolCriterion(value=True), match=match
            )
        )
        assert _ids(flat) == _ids(nested), f"mismatch for value={value}"


def test_nested_matches_flat_purchase_refunded(db):
    pc = Platform.objects.create(name="PC")
    refunded = Game.objects.create(name="Refunded", platform=pc)
    kept = Game.objects.create(name="Kept", platform=pc)
    none = Game.objects.create(name="NoPurchase", platform=pc)
    Purchase.objects.create(
        date_purchased=_dt(), date_refunded=_dt(2024, 7, 1)
    ).games.set([refunded])
    Purchase.objects.create(date_purchased=_dt()).games.set([kept])

    flat_false = GameFilter(purchase_refunded=BoolCriterion(value=False))
    nested_none = GameFilter(
        purchase_filter=PurchaseFilter(
            is_refunded=BoolCriterion(value=True), match=RelationMatch.NONE
        )
    )
    assert _ids(flat_false) == _ids(nested_none)
    assert _ids(flat_false) == {kept.id, none.id}


# ── match round-trip ─────────────────────────────────────────────────────────


def test_match_json_round_trip():
    f = GameFilter(
        session_filter=SessionFilter(
            emulated=BoolCriterion(value=True), match=RelationMatch.NONE
        )
    )
    payload = f.to_json()
    assert payload["session_filter"]["match"] == RelationMatch.NONE

    restored = GameFilter.from_json(json.loads(json.dumps(payload)))
    assert restored is not None and restored.session_filter is not None
    assert restored.session_filter.match == RelationMatch.NONE


def test_default_any_match_is_not_serialized():
    """The default ANY quantifier stays implicit, so existing filters serialize
    byte-identically (no spurious "match" key)."""
    f = GameFilter(session_filter=SessionFilter(emulated=BoolCriterion(value=True)))
    assert "match" not in f.to_json()["session_filter"]


# ── AggregateCriterion ───────────────────────────────────────────────────────


@pytest.fixture
def aggregate_world(db):
    pc = Platform.objects.create(name="PC")
    busy = Game.objects.create(name="Busy", platform=pc)
    quiet = Game.objects.create(name="Quiet", platform=pc)
    Game.objects.create(name="Idle", platform=pc)  # zero sessions

    for day in (1, 2, 3):
        Session.objects.create(
            game=busy,
            timestamp_start=_dt(2024, 6, day),
            duration_manual=timedelta(hours=2),
        )
    Session.objects.create(
        game=quiet, timestamp_start=_dt(), duration_manual=timedelta(hours=1)
    )
    return {"busy": busy.id, "quiet": quiet.id}


def test_aggregate_count(aggregate_world):
    over_two = GameFilter(
        session_count=AggregateCriterion(value=2, modifier=Modifier.GREATER_THAN)
    )
    assert _ids(over_two) == {aggregate_world["busy"]}


def test_aggregate_duration_sum(aggregate_world):
    """manual_playtime_hours sums duration_manual across the game's sessions."""
    over_three_hours = GameFilter(
        manual_playtime_hours=AggregateCriterion(
            value=3, modifier=Modifier.GREATER_THAN
        )
    )
    assert _ids(over_three_hours) == {aggregate_world["busy"]}  # 6h vs 1h


def test_aggregate_round_trip(aggregate_world):
    f = GameFilter(
        session_count=AggregateCriterion(value=2, modifier=Modifier.GREATER_THAN)
    )
    restored = GameFilter.from_json(json.loads(json.dumps(f.to_json())))
    assert restored is not None
    assert _ids(restored) == _ids(f)


def test_aggregate_average_duration(db):
    """session_average uses Avg over the DurationField + duration-hours compare."""
    pc = Platform.objects.create(name="PC")
    high = Game.objects.create(name="High", platform=pc)
    low = Game.objects.create(name="Low", platform=pc)
    for day in (1, 2):
        Session.objects.create(
            game=high,
            timestamp_start=_dt(2024, 6, day),
            duration_manual=timedelta(hours=2),
        )
    Session.objects.create(
        game=low, timestamp_start=_dt(), duration_manual=timedelta(hours=1)
    )
    over_one_hour = GameFilter(
        session_average=AggregateCriterion(value=1, modifier=Modifier.GREATER_THAN)
    )
    assert _ids(over_one_hour) == {high.id}  # avg 2h vs 1h


def test_aggregate_price_sum(db):
    """purchase_price_total uses float Sum + numeric compare (not duration)."""
    from decimal import Decimal

    pc = Platform.objects.create(name="PC")
    pricey = Game.objects.create(name="Pricey", platform=pc)
    cheap = Game.objects.create(name="Cheap", platform=pc)
    for amount in (10, 15):
        purchase = Purchase.objects.create(
            date_purchased=_dt(), converted_price=Decimal(amount)
        )
        purchase.games.set([pricey])
    purchase = Purchase.objects.create(date_purchased=_dt(), converted_price=Decimal(5))
    purchase.games.set([cheap])

    over_twenty = GameFilter(
        purchase_price_total=AggregateCriterion(
            value=20, modifier=Modifier.GREATER_THAN
        )
    )
    assert _ids(over_twenty) == {pricey.id}  # 25 vs 5


# ── NONE on the M2M parent_field + non-Game parents ──────────────────────────


def test_m2m_relation_none_excludes_partial_bundle(db):
    """PurchaseFilter.game_filter NONE negates over the M2M parent_field
    (`games__id`): a bundle containing the matching game must be excluded."""
    pc = Platform.objects.create(name="PC")
    hit = Game.objects.create(name="Hit", platform=pc)
    miss = Game.objects.create(name="Miss", platform=pc)
    bundle = Purchase.objects.create(date_purchased=_dt())
    bundle.games.set([hit, miss])
    solo = Purchase.objects.create(date_purchased=_dt())
    solo.games.set([miss])
    empty = Purchase.objects.create(date_purchased=_dt())

    no_hit = PurchaseFilter(
        game_filter=GameFilter(
            name=StringCriterion(value="Hit"), match=RelationMatch.NONE
        )
    )
    purchase_ids = set(
        Purchase.objects.filter(no_hit.to_q()).distinct().values_list("id", flat=True)
    )
    assert purchase_ids == {solo.id, empty.id}  # bundle (contains Hit) excluded


def test_relation_none_on_non_game_parent(db):
    """The shared relation_to_q NONE path works for a non-Game parent
    (SessionFilter.game_filter)."""
    pc = Platform.objects.create(name="PC")
    hit = Game.objects.create(name="Hit", platform=pc)
    miss = Game.objects.create(name="Miss", platform=pc)
    Session.objects.create(game=hit, timestamp_start=_dt())
    keep = Session.objects.create(game=miss, timestamp_start=_dt(2024, 6, 2))

    not_hit = SessionFilter(
        game_filter=GameFilter(
            name=StringCriterion(value="Hit"), match=RelationMatch.NONE
        )
    )
    session_ids = set(
        Session.objects.filter(not_hit.to_q()).values_list("id", flat=True)
    )
    assert session_ids == {keep.id}


# ── ALL relation match (every related row matches; vacuous truth INCLUDED) ────


def test_relation_all_every_row_matches_included(emulated_world):
    """ALL = every related row matches the sub-filter.

    EmuOnly (one emulated session) qualifies; Both (one emulated + one not) has a
    violating row and is excluded; NonEmu (one non-emulated) is excluded; and
    NoSessions has no related rows, so it matches vacuously (∀ over an empty set).
    """
    all_emulated = GameFilter(
        session_filter=SessionFilter(
            emulated=BoolCriterion(value=True), match=RelationMatch.ALL
        )
    )
    assert _ids(all_emulated) == {
        emulated_world["emu_only"],
        emulated_world["no_sessions"],
    }


def test_relation_all_excludes_mixed_rows(emulated_world):
    """A parent with a mix of matching and violating rows is excluded from ALL."""
    all_emulated = GameFilter(
        session_filter=SessionFilter(
            emulated=BoolCriterion(value=True), match=RelationMatch.ALL
        )
    )
    assert emulated_world["both"] not in _ids(all_emulated)


def test_relation_all_vacuous_truth_includes_zero_row_parent(emulated_world):
    """A parent with ZERO related rows matches ALL (vacuous truth)."""
    all_emulated = GameFilter(
        session_filter=SessionFilter(
            emulated=BoolCriterion(value=True), match=RelationMatch.ALL
        )
    )
    assert emulated_world["no_sessions"] in _ids(all_emulated)


def test_all_match_json_round_trip():
    """match=ALL serializes as {"match": "ALL"} and rebuilds identically."""
    f = GameFilter(
        session_filter=SessionFilter(
            emulated=BoolCriterion(value=True), match=RelationMatch.ALL
        )
    )
    payload = f.to_json()
    assert payload["session_filter"]["match"] == RelationMatch.ALL

    restored = GameFilter.from_json(json.loads(json.dumps(payload)))
    assert restored is not None and restored.session_filter is not None
    assert restored.session_filter.match == RelationMatch.ALL


# ── reserved/invalid quantifiers fail loud ───────────────────────────────────


def test_aggregate_to_q_not_callable_directly():
    """AggregateCriterion is evaluated via aggregate_to_q, not the base to_q."""
    with pytest.raises(NotImplementedError):
        AggregateCriterion(value=1).to_q("session_count")


def test_two_level_match_round_trip():
    """match survives a round-trip at a nested-deeper-than-one level."""
    from games.filters import DeviceFilter

    f = GameFilter(
        session_filter=SessionFilter(
            device_filter=DeviceFilter(match=RelationMatch.NONE)
        )
    )
    restored = GameFilter.from_json(json.loads(json.dumps(f.to_json())))
    assert restored is not None and restored.session_filter is not None
    assert restored.session_filter.device_filter is not None
    assert restored.session_filter.device_filter.match == RelationMatch.NONE


# ── n-ary boolean composition (#127): AND/OR/NOT as lists ─────────────────────


@pytest.fixture
def boolean_world(db):
    """Games spanning combinations of an emulated session and a refunded purchase,
    plus a game (``split``) whose two qualifying sessions are *distinct* rows — the
    case only n-ary AND over one relation can express (the flat single-session
    conjunction misses it)."""
    pc = Platform.objects.create(name="PC")
    deck = Device.objects.create(name="SteamDeck", type=Device.HANDHELD)
    desktop = Device.objects.create(name="Desktop", type=Device.PC)

    both = Game.objects.create(name="Both", platform=pc)
    emu_only = Game.objects.create(name="EmuOnly", platform=pc)
    refund_only = Game.objects.create(name="RefundOnly", platform=pc)
    neither = Game.objects.create(name="Neither", platform=pc)

    Session.objects.create(game=both, timestamp_start=_dt(), emulated=True)
    Session.objects.create(game=emu_only, timestamp_start=_dt(), emulated=True)
    Session.objects.create(game=refund_only, timestamp_start=_dt(), emulated=False)
    Session.objects.create(game=neither, timestamp_start=_dt(), emulated=False)

    Purchase.objects.create(
        date_purchased=_dt(), date_refunded=_dt(2024, 7, 1)
    ).games.set([both])
    Purchase.objects.create(date_purchased=_dt()).games.set([emu_only])
    Purchase.objects.create(
        date_purchased=_dt(), date_refunded=_dt(2024, 7, 1)
    ).games.set([refund_only])
    Purchase.objects.create(date_purchased=_dt()).games.set([neither])

    # split: emulated session and deck session are two different rows.
    split = Game.objects.create(name="Split", platform=pc)
    Session.objects.create(
        game=split, timestamp_start=_dt(), emulated=True, device=desktop
    )
    Session.objects.create(
        game=split, timestamp_start=_dt(2024, 6, 2), emulated=False, device=deck
    )
    # combined: a single session that is both emulated and on the deck.
    combined = Game.objects.create(name="Combined", platform=pc)
    Session.objects.create(
        game=combined, timestamp_start=_dt(), emulated=True, device=deck
    )

    return {
        "both": both.id,
        "emu_only": emu_only.id,
        "refund_only": refund_only.id,
        "neither": neither.id,
        "split": split.id,
        "combined": combined.id,
        "deck": deck.id,
    }


def test_and_list_two_independent_subfilters_both_required(boolean_world):
    """Two AND sub-filters over *different* relations: a game must have BOTH an
    emulated session AND a refunded purchase."""
    both_required = GameFilter(
        AND=[
            GameFilter(
                session_filter=SessionFilter(emulated=BoolCriterion(value=True))
            ),
            GameFilter(
                purchase_filter=PurchaseFilter(is_refunded=BoolCriterion(value=True))
            ),
        ]
    )
    assert _ids(both_required) == {boolean_world["both"]}


def test_and_list_two_subfilters_same_relation(boolean_world):
    """Two AND sub-filters over the SAME relation are two independent EXISTS, so a
    game qualifies when *different* sessions satisfy each — the unary form could
    not express this. The flat single-session conjunction misses ``split``."""
    deck = boolean_world["deck"]
    nary = GameFilter(
        AND=[
            GameFilter(
                session_filter=SessionFilter(emulated=BoolCriterion(value=True))
            ),
            GameFilter(
                session_filter=SessionFilter(device=MultiCriterion(value=[deck]))
            ),
        ]
    )
    nary_ids = _ids(nary)
    assert boolean_world["split"] in nary_ids
    assert boolean_world["combined"] in nary_ids

    # One session required to be BOTH emulated AND on the deck: split is excluded.
    single_session = GameFilter(
        session_filter=SessionFilter(
            emulated=BoolCriterion(value=True), device=MultiCriterion(value=[deck])
        )
    )
    single_ids = _ids(single_session)
    assert boolean_world["combined"] in single_ids
    assert boolean_world["split"] not in single_ids


def test_or_list_two_subfilters_union(boolean_world):
    """Two OR sub-filters on a criteria-free node = the union of the two EXISTS
    (Django drops the empty base ``Q()`` from the OR)."""
    either = GameFilter(
        OR=[
            GameFilter(
                session_filter=SessionFilter(emulated=BoolCriterion(value=True))
            ),
            GameFilter(
                purchase_filter=PurchaseFilter(is_refunded=BoolCriterion(value=True))
            ),
        ]
    )
    assert _ids(either) == {
        boolean_world["both"],
        boolean_world["emu_only"],
        boolean_world["refund_only"],
        boolean_world["split"],
        boolean_world["combined"],
    }


def test_legacy_single_object_and_is_wrapped_to_list(boolean_world):
    """A legacy single-object AND payload (pre-#127) parses as a one-element list
    and evaluates identically to the explicit list form."""
    legacy = GameFilter.from_json(
        {"AND": {"session_filter": {"emulated": {"value": True, "modifier": "EQUALS"}}}}
    )
    assert legacy is not None
    assert isinstance(legacy.AND, list) and len(legacy.AND) == 1
    explicit = GameFilter(
        AND=[
            GameFilter(session_filter=SessionFilter(emulated=BoolCriterion(value=True)))
        ]
    )
    assert _ids(legacy) == _ids(explicit)


def test_multi_element_and_list_round_trip(boolean_world):
    """A two-element AND list survives the JSON round-trip and selects the same
    games."""
    original = GameFilter(
        AND=[
            GameFilter(
                session_filter=SessionFilter(emulated=BoolCriterion(value=True))
            ),
            GameFilter(
                purchase_filter=PurchaseFilter(is_refunded=BoolCriterion(value=True))
            ),
        ]
    )
    payload = original.to_json()
    assert isinstance(payload["AND"], list) and len(payload["AND"]) == 2

    restored = GameFilter.from_json(json.loads(json.dumps(payload)))
    assert restored is not None
    assert isinstance(restored.AND, list) and len(restored.AND) == 2
    assert _ids(restored) == _ids(original)


def test_unused_operator_list_is_not_serialized():
    """An empty operator list stays out of the serialized form."""
    f = GameFilter(name=StringCriterion(value="x"))
    payload = f.to_json()
    assert "AND" not in payload and "OR" not in payload and "NOT" not in payload
