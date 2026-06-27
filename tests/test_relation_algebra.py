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

from common.criteria import AggregateCriterion, BoolCriterion, Modifier
from games.filters import GameFilter, SessionFilter
from games.models import Game, Platform, Purchase, Session


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
            emulated=BoolCriterion(value=True), match=Modifier.EXCLUDES
        )
    )
    assert _ids(no_emulated) == {
        emulated_world["non_emu"],
        emulated_world["no_sessions"],
    }


def test_empty_none_subfilter_means_no_related_rows(emulated_world):
    """A match-only NONE node (no child criteria) = "has no sessions at all"."""
    no_sessions = GameFilter(session_filter=SessionFilter(match=Modifier.EXCLUDES))
    assert _ids(no_sessions) == {emulated_world["no_sessions"]}


# ── equivalence with the flat convenience fields (Phase 2 mapping) ───────────


def test_nested_matches_flat_session_emulated(emulated_world):
    """The flat session_emulated bool and the nested match-mode form must select
    identical games for both True (ANY) and False (NONE)."""
    for value, match in [(True, Modifier.INCLUDES), (False, Modifier.EXCLUDES)]:
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

    from games.filters import PurchaseFilter

    def purchase_ids(f):
        return set(
            Game.objects.filter(f.to_q()).distinct().values_list("id", flat=True)
        )

    flat_false = GameFilter(purchase_refunded=BoolCriterion(value=False))
    nested_none = GameFilter(
        purchase_filter=PurchaseFilter(
            is_refunded=BoolCriterion(value=True), match=Modifier.EXCLUDES
        )
    )
    assert purchase_ids(flat_false) == purchase_ids(nested_none)
    assert purchase_ids(flat_false) == {kept.id, none.id}


# ── match round-trip ─────────────────────────────────────────────────────────


def test_match_json_round_trip():
    f = GameFilter(
        session_filter=SessionFilter(
            emulated=BoolCriterion(value=True), match=Modifier.EXCLUDES
        )
    )
    payload = f.to_json()
    assert payload["session_filter"]["match"] == Modifier.EXCLUDES

    restored = GameFilter.from_json(json.loads(json.dumps(payload)))
    assert restored is not None and restored.session_filter is not None
    assert restored.session_filter.match == Modifier.EXCLUDES


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
    assert _ids(restored) == _ids(f)
