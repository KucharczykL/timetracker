"""Saved presets are rewritten into the projection's words."""

import importlib

import pytest

from games.filters import parse_game_filter, parse_purchase_filter, parse_session_filter
from games.models import FilterPreset

rewrite = importlib.import_module("games.migrations.0032_purchase_presets")


def _choice(*words, modifier="INCLUDES"):
    return {"value": list(words), "modifier": modifier}


def _purchase(node):
    walked = rewrite.rewrite_purchase_node(node)
    assert walked.unexpressible == []
    #: The new filter reads what was written.
    assert parse_purchase_filter(_json(walked.node)) is not None
    return walked.node


def _json(node) -> str:
    import json

    return json.dumps(node)


def _refused(node) -> list[str]:
    return rewrite.rewrite_purchase_node(node).unexpressible


# ── One row of the table each ───────────────────────────────────────────────


def test_type_game_and_dlc_are_or_members():
    rewritten = _purchase({"type": _choice("game", "dlc")})

    assert rewritten == {
        "AND": [
            {
                "OR": [
                    {
                        "kind": _choice("game", "upgrade"),
                        "game_filter": {"kind": _choice("dlc", modifier="EXCLUDES")},
                    },
                    {"kind": _choice("game"), "game_filter": {"kind": _choice("dlc")}},
                ]
            }
        ]
    }


@pytest.mark.parametrize("word", ["season_pass", "battle_pass"])
def test_a_pass_type_is_its_kind(word):
    assert _purchase({"type": _choice(word)}) == {
        "AND": [{"OR": [{"kind": _choice(word)}]}]
    }


def test_a_labelled_word_reads_its_id():
    labelled = {"value": [{"id": "season_pass", "label": "Season pass"}]}

    assert _purchase({"type": labelled}) == {
        "AND": [{"OR": [{"kind": _choice("season_pass")}]}]
    }


NOT_UPGRADE = _choice("upgrade", modifier="EXCLUDES")


@pytest.mark.parametrize(
    ("word", "access", "entry_format", "kind"),
    [
        ("ph", ["owned"], "physical", NOT_UPGRADE),
        ("di", ["owned"], "digital", NOT_UPGRADE),
        ("du", ["owned"], None, _choice("upgrade")),
        ("re", ["rented", "subscription"], "digital", NOT_UPGRADE),
        ("bo", ["borrowed"], "physical", NOT_UPGRADE),
        ("tr", ["trial"], "digital", NOT_UPGRADE),
        ("de", ["demo"], "digital", NOT_UPGRADE),
        ("pi", ["pirated"], "unknown", NOT_UPGRADE),
    ],
)
def test_ownership_reads_the_conversion_table(word, access, entry_format, kind):
    (group,) = _purchase({"ownership_type": _choice(word)})["AND"]
    (member,) = group["OR"]

    expected = {"access": _choice(*access)}
    if entry_format is not None:
        expected["format"] = _choice(entry_format)
    assert member["entry_filter"] == expected
    assert member["kind"] == kind


def test_infinite_is_the_game_s_unfinished_flag():
    flag = {"value": True}

    assert _purchase({"infinite": flag}) == {
        "AND": [{"game_filter": {"excluded_from_unfinished": flag}}]
    }


@pytest.mark.parametrize(
    ("old", "new"), [("price", "amount"), ("converted_price", "valuation")]
)
def test_prices_are_renamed(old, new):
    criterion = {"value": 5, "modifier": "GREATER_THAN"}

    assert _purchase({old: criterion}) == {new: criterion}


@pytest.mark.parametrize(
    "criterion",
    [
        {"value": 0},
        {"value": 1, "modifier": "LESS_THAN"},
        {"value": 0, "modifier": "GREATER_THAN_OR_EQUAL"},
        {"value": 0, "value2": 5, "modifier": "BETWEEN"},
        {"value": 5, "value2": 9, "modifier": "NOT_BETWEEN"},
        {"value": 5, "modifier": "NOT_EQUALS"},
        {"modifier": "NOT_NULL"},
        {"modifier": "IS_NULL"},
    ],
)
@pytest.mark.parametrize("old", ["price", "converted_price"])
def test_a_price_criterion_matching_0_is_refused(old, criterion):
    assert _refused({old: criterion}) == [f"{old}: matches 0, now an unknown price"]


def test_a_price_currency_is_refused():
    assert _refused({"price_currency": {"value": "EUR"}}) == [
        "price_currency: no field states it"
    ]


@pytest.mark.parametrize(
    ("modifier", "refunded"), [("NOT_NULL", True), ("IS_NULL", False)]
)
def test_a_refund_day_s_presence_is_the_act(modifier, refunded):
    assert _purchase({"date_refunded": {"modifier": modifier}}) == {
        "is_refunded": {"value": refunded}
    }


def test_a_purchase_day_s_presence_is_refused():
    assert _refused({"date_purchased": {"modifier": "NOT_NULL"}}) == [
        "date_purchased: a day may now be unknown"
    ]


@pytest.mark.parametrize(
    ("old", "new"), [("date_purchased", "purchased"), ("date_refunded", "refunded")]
)
def test_dates_are_renamed(old, new):
    criterion = {"value": "2024-01-01", "value2": "2024-12-31", "modifier": "BETWEEN"}

    assert _purchase({old: criterion}) == {new: criterion}


def test_is_refunded_stays():
    assert _purchase({"is_refunded": {"value": True}}) == {
        "is_refunded": {"value": True}
    }


def test_games_includes_is_game():
    criterion = _choice("018f5e66-e800-7000-8000-000000000001")

    assert _purchase({"games": criterion}) == {"game": criterion}


@pytest.mark.parametrize("key", ["platform", "name", "created_at", "search"])
def test_unchanged_keys_stay(key):
    criterion = {"value": "x", "modifier": "INCLUDES"}
    if key == "platform":
        criterion = _choice("018f5e66-e800-7000-8000-000000000001")
    if key == "created_at":
        criterion = {"value": "2024-01-01", "modifier": "EQUALS"}

    assert _purchase({key: criterion}) == {key: criterion}


# ── What no field states ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "node",
    [
        {"type": _choice("game", modifier="EXCLUDES")},
        {"ownership_type": _choice("ph", modifier="INCLUDES_ONLY")},
        {"games": _choice("x", modifier="INCLUDES_ALL")},
        {"num_purchases": {"value": 2}},
        {"needs_price_update": {"value": True}},
        {"converted_currency": {"value": "EUR"}},
        {"updated_at": {"value": "2024-01-01"}},
        {"platform_filter": {"name": {"value": "PC"}}},
        {"date_purchased": {"value": None, "modifier": "EQUALS"}},
        {"type": _choice("bundle")},
    ],
    ids=lambda node: next(iter(node)),
)
def test_an_unexpressible_criterion_is_reported(node):
    assert _refused(node)


def test_a_legacy_comparison_operand_is_reported():
    games = {
        "field_comparisons": [
            {
                "left": "purchases__date_purchased",
                "right": "created_at",
                "modifier": "LESS_THAN",
            }
        ]
    }

    assert rewrite.rewrite_filter_tree(games).unexpressible


# ── Nested ──────────────────────────────────────────────────────────────────


def test_a_games_preset_s_purchase_filter():
    games = {"purchase_filter": {"price": {"value": 5, "modifier": "GREATER_THAN"}}}

    walked = rewrite.rewrite_filter_tree(games)

    assert walked.node == {
        "purchase_filter": {"amount": {"value": 5, "modifier": "GREATER_THAN"}}
    }
    assert parse_game_filter(_json(walked.node)) is not None


def test_a_sessions_preset_s_game_filter_purchase_filter():
    sessions = {"game_filter": {"purchase_filter": {"type": _choice("battle_pass")}}}

    walked = rewrite.rewrite_filter_tree(sessions)

    assert walked.node == {
        "game_filter": {
            "purchase_filter": {"AND": [{"OR": [{"kind": _choice("battle_pass")}]}]}
        }
    }
    assert parse_session_filter(_json(walked.node)) is not None


def test_an_aggregate_scope():
    games = {
        "purchase_count": {
            "value": 1,
            "modifier": "GREATER_THAN",
            "scope": {"date_refunded": {"modifier": "NOT_NULL"}},
        }
    }

    walked = rewrite.rewrite_filter_tree(games)

    assert walked.node["purchase_count"]["scope"] == {"is_refunded": {"value": True}}
    assert parse_game_filter(_json(walked.node)) is not None


def test_operator_members():
    node = {
        "OR": [{"price": {"value": 1, "modifier": "GREATER_THAN"}}],
        "NOT": [{"is_refunded": {"value": True}}],
    }

    assert _purchase(node) == {
        "OR": [{"amount": {"value": 1, "modifier": "GREATER_THAN"}}],
        "NOT": [{"is_refunded": {"value": True}}],
    }


def test_a_purchase_filter_inside_a_purchase_s_game_filter():
    node = {"game_filter": {"purchase_filter": {"price": {"value": 1}}}}

    assert _purchase(node) == {
        "game_filter": {"purchase_filter": {"amount": {"value": 1}}}
    }


# ── Sorts ───────────────────────────────────────────────────────────────────


def test_sort_tokens_keep_their_sign():
    assert rewrite.rewrite_sort({"sort": "-type,price,-purchased"}) == (
        {"sort": "-kind,amount,-purchased"},
        [],
    )


def test_infinite_leaves_the_sort_and_says_so():
    assert rewrite.rewrite_sort({"sort": "-infinite,name"}) == (
        {"sort": "name"},
        ["sort 'infinite' dropped: no new key"],
    )


# ── The pass ────────────────────────────────────────────────────────────────


def _preset(library, mode, object_filter, find_filter=None) -> FilterPreset:
    return FilterPreset.objects.create(
        library=library,
        name=f"{mode} {len(FilterPreset.objects.all())}",
        mode=mode,
        object_filter=object_filter,
        find_filter=find_filter or {},
        ui_options={},
    )


@pytest.mark.django_db
def test_the_pass_rewrites_and_keeps(owned_library, capsys):
    from django.apps import apps

    converts = _preset(
        owned_library, "purchases", {"price": {"value": 5}}, {"sort": "-price"}
    )
    stays = _preset(owned_library, "purchases", {"num_purchases": {"value": 2}})
    untouched = _preset(owned_library, "games", {"name": {"value": "x"}})

    rewrite.rewrite_forward(apps, None)
    for preset in (converts, stays, untouched):
        preset.refresh_from_db()

    assert converts.object_filter == {"amount": {"value": 5}}
    assert converts.find_filter == {"sort": "-amount"}
    assert stays.object_filter == {"num_purchases": {"value": 2}}
    assert untouched.object_filter == {"name": {"value": "x"}}
    printed = capsys.readouterr().out
    assert "presets rewritten: 1/3" in printed
    assert "num_purchases" in printed


@pytest.mark.django_db
def test_a_second_pass_changes_nothing(owned_library, capsys):
    from django.apps import apps

    preset = _preset(owned_library, "purchases", {"type": _choice("game")})
    rewrite.rewrite_forward(apps, None)
    preset.refresh_from_db()
    once = preset.object_filter

    rewrite.rewrite_forward(apps, None)
    preset.refresh_from_db()

    assert preset.object_filter == once
    printed = capsys.readouterr().out
    assert "presets rewritten: 0/1" in printed
    assert "kept" not in printed


# ── Across the conversion: the same rows ────────────────────────────────────


@pytest.fixture
def converted(owned_library, stated_graph, monkeypatch):
    """Legacy rows of each type and ownership, converted."""
    from datetime import UTC, date, datetime

    from games.backfill import purchase as conversion
    from games.backfill.purchase import convert_purchases, legacy_rows
    from games.models import Game, LegacyPurchase, PurchaseConversionState

    monkeypatch.setattr(conversion, "require_replay_parity", lambda libraries: None)
    PurchaseConversionState.objects.filter(library=owned_library).update(
        requested_version=1, published_version=1, published_currency="EUR"
    )

    def game(name: str) -> Game:
        return stated_graph(Game(name=name, library=owned_library), owned_library).game

    def legacy(target, day, **columns) -> LegacyPurchase:
        row = LegacyPurchase.objects.create(
            library=owned_library,
            date_purchased=day,
            price=columns.pop("price", 10),
            price_currency="EUR",
            converted_price=10,
            converted_currency="EUR",
            **columns,
        )
        row.games.add(target)
        return row

    base = game("Base")
    legacy(base, date(2021, 1, 1), ownership_type=LegacyPurchase.PHYSICAL)
    legacy(base, date(2021, 2, 1), ownership_type=LegacyPurchase.DIGITALUPGRADE)
    legacy(
        base,
        date(2021, 3, 1),
        type=LegacyPurchase.DLC,
        name="More",
        related_game=base,
        date_refunded=date(2021, 3, 4),
    )
    legacy(
        base,
        date(2021, 4, 1),
        type=LegacyPurchase.SEASONPASS,
        name="Year 1",
        related_game=base,
        #: A pass now takes its base copy's.
        ownership_type=LegacyPurchase.PHYSICAL,
    )
    legacy(game("Rental"), date(2021, 5, 1), ownership_type=LegacyPurchase.RENTED)
    legacy(game("Digital"), date(2021, 6, 1))
    convert_purchases(
        legacy_rows(LegacyPurchase, owned_library.pk),
        recorded_at=datetime(2026, 10, 1, 12, tzinfo=UTC),
    )
    return owned_library


@pytest.mark.django_db
@pytest.mark.parametrize(
    "legacy_filter",
    [
        {"type": _choice("game")},
        {"type": _choice("dlc")},
        {"type": _choice("season_pass")},
        {"ownership_type": _choice("ph")},
        {"ownership_type": _choice("di")},
        {"ownership_type": _choice("du")},
        {"ownership_type": _choice("re")},
        {"date_purchased": {"value": "2021-03-01", "modifier": "GREATER_THAN"}},
        {"date_purchased": {"value": "2021-03-01", "modifier": "LESS_THAN"}},
        {"date_refunded": {"modifier": "NOT_NULL"}},
        {"date_refunded": {"modifier": "IS_NULL"}},
        {"price": {"value": 5, "modifier": "GREATER_THAN"}},
    ],
)
def test_a_rewritten_preset_matches_the_same_rows(converted, legacy_filter):
    from games.models import LegacyPurchase
    from games.purchase_parity import ConversionMap
    from games.reads.purchase_figures import purchases_matching

    [(key, criterion)] = legacy_filter.items()
    lookups = {
        "type": lambda: {"type__in": criterion["value"]},
        "ownership_type": lambda: {"ownership_type__in": criterion["value"]},
        "price": lambda: {"price__gt": criterion["value"]},
        "date_purchased": lambda: {
            "date_purchased__gt"
            if criterion["modifier"] == "GREATER_THAN"
            else "date_purchased__lt": criterion["value"]
        },
        "date_refunded": lambda: {
            "date_refunded__isnull": criterion["modifier"] == "IS_NULL"
        },
    }
    before = {
        str(pk)
        for pk in LegacyPurchase.objects.filter(
            library=converted, **lookups[key]()
        ).values_list("pk", flat=True)
    }
    rewritten = _purchase(legacy_filter)
    legacy_of = ConversionMap.read(converted).legacy_of

    after = {
        legacy_of[str(pk)]
        for pk in purchases_matching(
            converted, parse_purchase_filter(_json(rewritten))
        ).values_list("pk", flat=True)
    }

    assert before
    assert after == before
