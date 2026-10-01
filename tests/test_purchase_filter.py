"""The Purchase filter and its valuation alias."""

from datetime import timedelta
from decimal import Decimal

import pytest
from calendar_days import library_noon
from entries import end_entry_access, record_entry
from purchases import record_purchase, refund_purchase, remove_purchase, request_run

from common.criteria import FilterError, FilterQueryContext
from games import tasks
from games.filters import (
    GameFilter,
    LibraryEntryFilter,
    PurchaseFilter,
    filter_query_context_for_library,
    filter_queryset_for_library,
    parse_purchase_filter,
)
from games.models import ExchangeRate, Game, Platform, Purchase
from games.reads.calendar import calendar_today
from games.reads.purchases import UnscopedValuationRead
from timetracker.temporal import TemporalValue

pytestmark = [pytest.mark.django_db, pytest.mark.untracked_games]

MARCH_2021 = TemporalValue.parse("2021-03-01")


@pytest.fixture(autouse=True)
def no_stored_rates():
    ExchangeRate.objects.all().delete()


@pytest.fixture
def entry(owned_library, stated_graph):
    graph = stated_graph(Game(name="Tunic", library=owned_library), owned_library)
    return record_entry(owned_library, graph.release)


def _value(library, currency: str = "EUR") -> None:
    tasks.convert_library_prices(str(library.pk), request_run(library, currency))


# The valuation alias


def test_a_second_call_with_the_same_library_is_a_no_op(entry, owned_library):
    rows = Purchase.objects.annotated_for_filtering(owned_library)

    assert rows.annotated_for_filtering(owned_library).query.annotations.keys() == (
        rows.query.annotations.keys()
    )
    assert rows.annotated_for_filtering() is not None


def test_a_call_naming_another_library_is_refused(owned_library, django_user_model):
    stranger = django_user_model.objects.create_user(username="stranger").library
    rows = Purchase.objects.annotated_for_filtering(owned_library)

    with pytest.raises(ValueError, match="valuation alias"):
        rows.annotated_for_filtering(stranger)


def test_an_unscoped_alias_resolves_and_refuses_to_execute():
    rows = Purchase.objects.none().annotated_for_filtering()
    narrowed = Purchase.objects.annotated_for_filtering().filter(valuation_amount__gt=1)

    assert list(rows.filter(valuation_amount__gt=1)) == []
    with pytest.raises(UnscopedValuationRead):
        list(narrowed)


def test_an_unscoped_queryset_naming_no_alias_executes(entry):
    record_purchase(entry, purchased=MARCH_2021)

    assert Purchase.objects.annotated_for_filtering().count() == 1


def test_the_scoped_alias_reads_the_current_valuation(entry, owned_library):
    purchase = record_purchase(
        entry, amount=Decimal("12.50"), currency="EUR", purchased=MARCH_2021
    )
    unvalued = record_purchase(entry, amount=None, purchased=MARCH_2021)
    _value(owned_library)

    rows = {
        row.pk: (row.valuation_amount, row.valuation_currency)
        for row in Purchase.objects.annotated_for_filtering(owned_library)
    }

    assert rows[purchase.pk] == (Decimal("12.50"), "EUR")
    assert rows[unvalued.pk] == (None, "EUR")


def test_the_validation_context_accepts_a_valuation_filter():
    rows = FilterQueryContext.for_validation().queryset_for(Purchase)

    assert list(rows.filter(valuation_amount__gt=1)) == []


def test_both_library_scopes_carry_the_alias(entry, owned_library):
    purchase = record_purchase(entry, amount=Decimal(5), purchased=MARCH_2021)
    _value(owned_library)
    context = filter_query_context_for_library(owned_library)

    for rows in (
        context.queryset_for(Purchase),
        filter_queryset_for_library("purchase", owned_library),
    ):
        assert list(rows.filter(valuation_amount=5).values_list("pk", flat=True)) == [
            purchase.pk
        ]


# The filter, one field at a time


def _matching(library, purchase_filter: PurchaseFilter) -> set[Purchase]:
    context = filter_query_context_for_library(library)
    return set(
        filter_queryset_for_library("purchase", library).filter(
            purchase_filter.to_q(context)
        )
    )


@pytest.fixture
def tunic(owned_library, stated_graph):
    platform = Platform.objects.create(name="Switch", group="Nintendo")
    return stated_graph(
        Game(name="Tunic", library=owned_library), owned_library, platform=platform
    )


@pytest.fixture
def hades(owned_library, stated_graph):
    return stated_graph(Game(name="Hades", library=owned_library), owned_library)


def test_kind(entry, owned_library):
    game = record_purchase(entry, purchased=MARCH_2021)
    record_purchase(entry, kind="season_pass", name="Pass", purchased=MARCH_2021)

    assert _matching(owned_library, PurchaseFilter.where(kind=["game"])) == {game}


def test_name_and_note(entry, owned_library):
    named = record_purchase(entry, name="Deluxe", note="gift", purchased=MARCH_2021)
    record_purchase(entry, purchased=MARCH_2021)

    assert _matching(owned_library, PurchaseFilter.where(name="Deluxe")) == {named}
    assert _matching(owned_library, PurchaseFilter.where(note="gift")) == {named}


def test_amount_and_an_unknown_one(entry, owned_library):
    paid = record_purchase(entry, amount=Decimal("12.50"), purchased=MARCH_2021)
    unknown = record_purchase(entry, amount=None, purchased=MARCH_2021)

    assert _matching(owned_library, PurchaseFilter.where(amount__gt=10)) == {paid}
    assert _matching(owned_library, PurchaseFilter.where(amount__isnull=True)) == {
        unknown
    }


def test_currency(entry, owned_library):
    euro = record_purchase(entry, currency="EUR", purchased=MARCH_2021)
    record_purchase(entry, currency="USD", purchased=MARCH_2021)

    assert _matching(owned_library, PurchaseFilter.where(currency="EUR")) == {euro}


@pytest.mark.parametrize("word", ["paid", "free", "unknown"])
def test_price_state(entry, owned_library, word):
    rows = {
        "paid": record_purchase(entry, amount=Decimal(3), purchased=MARCH_2021),
        "free": record_purchase(entry, amount=Decimal(0), purchased=MARCH_2021),
        "unknown": record_purchase(entry, amount=None, purchased=MARCH_2021),
    }

    assert _matching(owned_library, PurchaseFilter.where(price_state=[word])) == {
        rows[word]
    }


def test_price_state_excludes(entry, owned_library):
    paid = record_purchase(entry, amount=Decimal(3), purchased=MARCH_2021)
    record_purchase(entry, amount=None, purchased=MARCH_2021)

    assert _matching(
        owned_library, PurchaseFilter.where(price_state__exclude=["unknown"])
    ) == {paid}


def test_valuation_reads_the_current_one_only(entry, owned_library):
    current = record_purchase(entry, amount=Decimal(20), purchased=MARCH_2021)
    stale = record_purchase(entry, amount=Decimal(30), purchased=MARCH_2021)
    _value(owned_library)
    Purchase.objects.filter(pk=stale.pk).update(amount=Decimal(31))

    assert _matching(owned_library, PurchaseFilter.where(valuation__gt=10)) == {current}
    assert _matching(owned_library, PurchaseFilter.where(valuation__isnull=True)) == {
        stale
    }


def test_purchased_within_a_year(entry, owned_library):
    inside = record_purchase(entry, purchased=MARCH_2021)
    record_purchase(entry, purchased=TemporalValue.parse("2021-12/2022-01"))

    assert _matching(
        owned_library,
        PurchaseFilter.where(purchased__within=("2021-01-01", "2021-12-31")),
    ) == {inside}


def test_refunded_and_is_refunded(entry, owned_library):
    refunded = refund_purchase(
        record_purchase(entry, kind="season_pass", name="P", purchased=MARCH_2021),
        TemporalValue.parse("2021-04-01"),
    )
    kept = record_purchase(entry, purchased=MARCH_2021)

    assert _matching(owned_library, PurchaseFilter.where(is_refunded=True)) == {
        refunded
    }
    assert _matching(owned_library, PurchaseFilter.where(is_refunded=False)) == {kept}
    assert _matching(
        owned_library,
        PurchaseFilter.where(refunded__between=("2021-04-01", "2021-04-30")),
    ) == {refunded}


def test_access_format_and_platform_read_the_copy(owned_library, tunic, hades):
    borrowed = record_purchase(
        record_entry(
            owned_library, tunic.release, access="borrowed", format="physical"
        ),
        purchased=MARCH_2021,
    )
    owned = record_purchase(
        record_entry(owned_library, hades.release), purchased=MARCH_2021
    )

    assert _matching(owned_library, PurchaseFilter.where(access=["borrowed"])) == {
        borrowed
    }
    assert _matching(owned_library, PurchaseFilter.where(format=["digital"])) == {owned}
    assert _matching(
        owned_library, PurchaseFilter.where(platform=[tunic.release.platform_id])
    ) == {borrowed}


def test_game(owned_library, tunic, hades):
    record_purchase(record_entry(owned_library, tunic.release), purchased=MARCH_2021)
    of_hades = record_purchase(
        record_entry(owned_library, hades.release), purchased=MARCH_2021
    )

    assert _matching(owned_library, PurchaseFilter.where(game=[hades.game.pk])) == {
        of_hades
    }


def test_created_at_by_calendar_day(entry, owned_library):
    today = record_purchase(entry, purchased=MARCH_2021)
    earlier = record_purchase(entry, purchased=MARCH_2021)
    Purchase.objects.filter(pk=earlier.pk).update(
        created_at=library_noon(owned_library, days_ago=3)
    )
    day = calendar_today(owned_library)

    assert _matching(owned_library, PurchaseFilter.where(created_at=day)) == {today}
    assert _matching(
        owned_library,
        PurchaseFilter.where(created_at__lt=day - timedelta(days=1)),
    ) == {earlier}


@pytest.mark.parametrize("text", ["Deluxe", "Tunic", "Switch"])
def test_search_reads_name_game_and_platform(owned_library, tunic, hades, text):
    found = record_purchase(
        record_entry(owned_library, tunic.release), name="Deluxe", purchased=MARCH_2021
    )
    record_purchase(record_entry(owned_library, hades.release), purchased=MARCH_2021)

    assert _matching(owned_library, PurchaseFilter.where(search=text)) == {found}


def test_entry_filter(owned_library, tunic):
    held = record_purchase(
        record_entry(owned_library, tunic.release), purchased=MARCH_2021
    )
    ended = record_purchase(
        end_entry_access(record_entry(owned_library, tunic.release)),
        purchased=MARCH_2021,
    )

    assert _matching(
        owned_library,
        PurchaseFilter(entry_filter=LibraryEntryFilter.where(is_ended=True)),
    ) == {ended}
    assert held not in _matching(
        owned_library,
        PurchaseFilter(entry_filter=LibraryEntryFilter.where(is_ended=True)),
    )


def test_game_filter(owned_library, tunic, hades):
    of_tunic = record_purchase(
        record_entry(owned_library, tunic.release), purchased=MARCH_2021
    )
    record_purchase(record_entry(owned_library, hades.release), purchased=MARCH_2021)

    assert _matching(
        owned_library, PurchaseFilter(game_filter=GameFilter.where(name="Tunic"))
    ) == {of_tunic}


def test_a_removed_purchase_is_not_listed(entry, owned_library):
    remove_purchase(record_purchase(entry, purchased=MARCH_2021))

    assert _matching(owned_library, PurchaseFilter()) == set()


def test_another_library_s_purchase_never_matches(
    entry, owned_library, django_user_model, stated_graph
):
    stranger = django_user_model.objects.create_user(username="stranger").library
    graph = stated_graph(Game(name="Tunic", library=stranger), stranger)
    theirs = record_purchase(
        record_entry(stranger, graph.release), purchased=MARCH_2021
    )
    ours = record_purchase(entry, purchased=MARCH_2021)

    assert _matching(owned_library, PurchaseFilter.where(search="Tunic")) == {ours}
    assert theirs not in _matching(owned_library, PurchaseFilter())


def test_a_legacy_key_is_refused():
    with pytest.raises(FilterError):
        parse_purchase_filter(
            '{"ownership_type": {"value": ["di"], "modifier": "INCLUDES"}}'
        )


# Relations and aggregates that reach a purchase


def _games(library, game_filter: GameFilter) -> set[Game]:
    context = filter_query_context_for_library(library)
    return set(
        filter_queryset_for_library("game", library).filter(game_filter.to_q(context))
    )


def test_purchase_count_counts_across_copies(owned_library, tunic, hades):
    record_purchase(record_entry(owned_library, tunic.release), purchased=MARCH_2021)
    record_purchase(record_entry(owned_library, tunic.release), purchased=MARCH_2021)
    record_purchase(record_entry(owned_library, hades.release), purchased=MARCH_2021)

    assert _games(owned_library, GameFilter.where(purchase_count__gt=1)) == {tunic.game}


def test_a_removed_purchase_is_not_counted(owned_library, tunic):
    copy = record_entry(owned_library, tunic.release)
    record_purchase(copy, purchased=MARCH_2021)
    remove_purchase(record_purchase(copy, purchased=MARCH_2021))

    assert _games(owned_library, GameFilter.where(purchase_count__gt=1)) == set()


def test_price_total_sums_valuations_only(owned_library, tunic, hades):
    copy = record_entry(owned_library, tunic.release)
    record_purchase(copy, amount=Decimal(20), purchased=MARCH_2021)
    record_purchase(copy, amount=Decimal(15), purchased=MARCH_2021)
    record_purchase(copy, amount=None, purchased=MARCH_2021)
    record_purchase(
        record_entry(owned_library, hades.release),
        amount=Decimal(40),
        purchased=MARCH_2021,
    )
    _value(owned_library)

    assert _games(owned_library, GameFilter.where(purchase_price_total=35)) == {
        tunic.game
    }
    assert _games(owned_library, GameFilter.where(purchase_price_total__gt=36)) == {
        hades.game
    }


def test_price_total_honours_its_scope(owned_library, tunic):
    copy = record_entry(owned_library, tunic.release)
    record_purchase(copy, amount=Decimal(20), purchased=MARCH_2021)
    record_purchase(
        copy, kind="season_pass", name="P", amount=Decimal(15), purchased=MARCH_2021
    )
    _value(owned_library)
    scoped = GameFilter.from_json(
        {
            "purchase_price_total": {
                "value": 20,
                "modifier": "EQUALS",
                "scope": {"kind": {"value": ["game"], "modifier": "INCLUDES"}},
            }
        }
    )

    assert _games(owned_library, scoped) == {tunic.game}


def test_a_count_refuses_a_correlated_path():
    from common.criteria import AggregateSpec

    with pytest.raises(TypeError, match="correlated"):
        AggregateSpec("count", "x", PurchaseFilter, correlated="entry")


def test_game_purchase_filter(owned_library, tunic, hades):
    record_purchase(
        record_entry(owned_library, tunic.release), name="Deluxe", purchased=MARCH_2021
    )
    record_purchase(record_entry(owned_library, hades.release), purchased=MARCH_2021)

    assert _games(
        owned_library, GameFilter(purchase_filter=PurchaseFilter.where(name="Deluxe"))
    ) == {tunic.game}


def test_platform_purchase_filter_reads_the_copy_s_release(owned_library, tunic):
    from games.filters import PlatformFilter

    record_purchase(record_entry(owned_library, tunic.release), purchased=MARCH_2021)
    context = filter_query_context_for_library(owned_library)
    matching = PlatformFilter(purchase_filter=PurchaseFilter()).to_q(context)

    assert set(Platform.objects.filter(matching)) == {tunic.release.platform}


def test_entry_purchase_filter_and_edition_kind(owned_library, tunic, hades):
    bought = record_entry(owned_library, tunic.release)
    record_purchase(bought, name="Deluxe", purchased=MARCH_2021)
    record_entry(owned_library, hades.release)
    context = filter_query_context_for_library(owned_library)
    entries = filter_queryset_for_library("libraryentry", owned_library)

    assert set(
        entries.filter(
            LibraryEntryFilter(
                purchase_filter=PurchaseFilter.where(name="Deluxe")
            ).to_q(context)
        )
    ) == {bought}
    assert (
        entries.filter(
            LibraryEntryFilter.where(edition_kind=["full"]).to_q(context)
        ).count()
        == 2
    )
    assert not entries.filter(
        LibraryEntryFilter.where(edition_kind=["prerelease"]).to_q(context)
    ).exists()


def test_a_valuation_matches_to_the_cent(entry, owned_library):
    cents = record_purchase(entry, amount=Decimal("19.99"), purchased=MARCH_2021)
    _value(owned_library)

    assert _matching(owned_library, PurchaseFilter.where(valuation=19.99)) == {cents}
    assert _matching(owned_library, PurchaseFilter.where(valuation__gt=19.99)) == set()
    assert _matching(owned_library, PurchaseFilter.where(valuation__lt=19.99)) == set()


def test_price_total_matches_to_the_cent(owned_library, tunic):
    record_purchase(
        record_entry(owned_library, tunic.release),
        amount=Decimal("59.99"),
        purchased=MARCH_2021,
    )
    _value(owned_library)

    assert _games(owned_library, GameFilter.where(purchase_price_total=59.99)) == {
        tunic.game
    }


def test_price_total_sums_every_copy_and_skips_a_removed_one(owned_library, tunic):
    record_purchase(
        record_entry(owned_library, tunic.release),
        amount=Decimal(20),
        purchased=MARCH_2021,
    )
    second = record_entry(owned_library, tunic.release)
    record_purchase(second, amount=Decimal(15), purchased=MARCH_2021)
    remove_purchase(record_purchase(second, amount=Decimal(99), purchased=MARCH_2021))
    _value(owned_library)

    assert _games(owned_library, GameFilter.where(purchase_price_total=35)) == {
        tunic.game
    }


def test_price_total_is_null_where_no_purchase_is_valued(owned_library, tunic, hades):
    record_purchase(
        record_entry(owned_library, tunic.release), amount=None, purchased=MARCH_2021
    )

    assert _games(owned_library, GameFilter.where(purchase_price_total__lt=10)) == set()
    assert _games(
        owned_library, GameFilter.where(purchase_price_total__isnull=True)
    ) == {tunic.game}


def test_price_total_sums_one_library_at_a_shared_game(
    owned_library, tunic, django_user_model
):
    Game.objects.filter(pk=tunic.game.pk).update(library=None)
    second = django_user_model.objects.create_user("second").library
    record_purchase(
        record_entry(owned_library, tunic.release),
        amount=Decimal(20),
        purchased=MARCH_2021,
    )
    record_purchase(
        record_entry(second, tunic.release), amount=Decimal(7), purchased=MARCH_2021
    )
    _value(owned_library)
    _value(second)

    assert _games(owned_library, GameFilter.where(purchase_price_total=20)) == {
        tunic.game
    }
    assert _games(second, GameFilter.where(purchase_price_total=7)) == {tunic.game}
