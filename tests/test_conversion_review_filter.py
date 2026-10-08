"""The conversion_review field reads the conversion's tags."""

import json

import pytest
from entries import record_entry
from graphs import default_graph
from purchases import record_purchase, remove_purchase

from common.criteria import ChoiceCriterion, FilterError, Modifier
from games.conversion_review import ORIGIN, Category
from games.filters import (
    LibraryEntryFilter,
    PurchaseFilter,
    parse_entry_filter,
    parse_purchase_filter,
)
from games.models import Game, LibraryEntry, Purchase

pytestmark = [pytest.mark.django_db, pytest.mark.untracked_games]


def tagged(*words: Category) -> dict[str, object]:
    return {"origin": ORIGIN, "issue": 723, "review": [str(word) for word in words]}


@pytest.fixture
def copies(owned_library):
    def copy(name: str) -> LibraryEntry:
        graph = default_graph(Game(name=name, library=owned_library), owned_library)
        return record_entry(owned_library, graph.release)

    return copy


def _review(modifier: Modifier, *words: Category, excludes=()) -> ChoiceCriterion:
    return ChoiceCriterion(
        value=[str(word) for word in words],
        modifier=modifier,
        excludes=[str(word) for word in excludes],
    )


def _purchases(library, criterion: ChoiceCriterion) -> set[Purchase]:
    q = PurchaseFilter(conversion_review=criterion).to_q()
    return set(Purchase.objects.filter(library=library).filter(q))


@pytest.fixture
def three(copies):
    unknown = record_purchase(
        copies("Tunic"), source_metadata=tagged(Category.UNKNOWN_PRICE)
    )
    both = record_purchase(
        copies("Hades"),
        source_metadata=tagged(Category.UNKNOWN_PRICE, Category.BUNDLE_SPLIT),
    )
    plain = record_purchase(copies("Celeste"))
    return unknown, both, plain


@pytest.mark.parametrize("modifier", [Modifier.INCLUDES, Modifier.EQUALS])
def test_includes_selects_any_tagged_purchase(owned_library, three, modifier):
    unknown, both, _ = three

    assert _purchases(owned_library, _review(modifier, Category.UNKNOWN_PRICE)) == {
        unknown,
        both,
    }


def test_includes_all_needs_every_word(owned_library, three):
    _, both, _ = three

    assert _purchases(
        owned_library,
        _review(Modifier.INCLUDES_ALL, Category.UNKNOWN_PRICE, Category.BUNDLE_SPLIT),
    ) == {both}


@pytest.mark.parametrize("modifier", [Modifier.EXCLUDES, Modifier.NOT_EQUALS])
def test_excludes_leaves_the_tagged_out(owned_library, three, modifier):
    unknown, _, plain = three

    assert _purchases(owned_library, _review(modifier, Category.BUNDLE_SPLIT)) == {
        unknown,
        plain,
    }


def test_no_word_with_an_exclusion_leaves_only_that_out(owned_library, three):
    unknown, _, plain = three

    assert _purchases(
        owned_library,
        _review(Modifier.INCLUDES, excludes=[Category.BUNDLE_SPLIT]),
    ) == {unknown, plain}


def test_the_excludes_list_is_a_conjunct(owned_library, three):
    unknown, _, _ = three

    assert _purchases(
        owned_library,
        _review(
            Modifier.INCLUDES,
            Category.UNKNOWN_PRICE,
            excludes=[Category.BUNDLE_SPLIT],
        ),
    ) == {unknown}


def test_presence_reads_any_category(owned_library, three):
    unknown, both, plain = three

    assert _purchases(owned_library, _review(Modifier.NOT_NULL)) == {unknown, both}
    assert _purchases(owned_library, _review(Modifier.IS_NULL)) == {plain}


def test_another_origin_is_no_tag(owned_library, copies):
    record_purchase(
        copies("Tunic"),
        source_metadata={"origin": "import", "review": [str(Category.RENTAL)]},
    )

    assert _purchases(owned_library, _review(Modifier.NOT_NULL)) == set()


def test_includes_only_needs_no_other_word(owned_library, three):
    unknown, _, _ = three

    assert _purchases(
        owned_library, _review(Modifier.INCLUDES_ONLY, Category.UNKNOWN_PRICE)
    ) == {unknown}


@pytest.mark.parametrize(
    "criterion",
    [
        ChoiceCriterion(value=["no_such_word"], modifier=Modifier.INCLUDES),
        ChoiceCriterion(value=["skipped_removed_game"], modifier=Modifier.INCLUDES),
        ChoiceCriterion(
            value=[], excludes=["no_such_word"], modifier=Modifier.INCLUDES
        ),
    ],
)
def test_an_unknown_word_is_refused(owned_library, three, criterion):
    with pytest.raises(FilterError):
        _purchases(owned_library, criterion)


def test_a_removed_purchase_still_tags_its_copy(owned_library, copies):
    base = copies("Tunic")
    remove_purchase(
        record_purchase(
            base, kind="season_pass", source_metadata=tagged(Category.OWN_COPY_FALLBACK)
        )
    )

    assert _entries(
        owned_library, _review(Modifier.INCLUDES, Category.OWN_COPY_FALLBACK)
    ) == {base}


def test_the_choices_carry_the_labels():
    choices = PurchaseFilter.fields["conversion_review"].choices
    assert choices is not None
    assert [(choice["value"], choice["label"]) for choice in choices] == [
        (word.value, word.label) for word in Category
    ]


def _entries(library, criterion: ChoiceCriterion) -> set[LibraryEntry]:
    q = LibraryEntryFilter(conversion_review=criterion).to_q()
    return set(LibraryEntry.objects.filter(library=library).filter(q))


def test_an_entry_reads_its_own_tags(owned_library):
    graph = default_graph(Game(name="Tunic", library=owned_library), owned_library)
    rental = record_entry(
        owned_library, graph.release, source_metadata=tagged(Category.RENTAL)
    )
    record_entry(owned_library, graph.release)

    assert _entries(owned_library, _review(Modifier.INCLUDES, Category.RENTAL)) == {
        rental
    }


def test_an_entry_reads_its_purchases_tags(owned_library, copies):
    base = copies("Tunic")
    record_purchase(base)
    record_purchase(
        base, kind="season_pass", source_metadata=tagged(Category.OWN_COPY_FALLBACK)
    )
    copies("Hades")

    assert _entries(
        owned_library, _review(Modifier.INCLUDES, Category.OWN_COPY_FALLBACK)
    ) == {base}
    assert base not in _entries(
        owned_library, _review(Modifier.EXCLUDES, Category.OWN_COPY_FALLBACK)
    )


def test_the_field_round_trips_through_json():
    criterion = _review(Modifier.INCLUDES, Category.RENTAL)

    assert parse_purchase_filter(
        json.dumps(PurchaseFilter(conversion_review=criterion).to_json())
    ) == PurchaseFilter(conversion_review=criterion)
    assert parse_entry_filter(
        json.dumps(LibraryEntryFilter(conversion_review=criterion).to_json())
    ) == LibraryEntryFilter(conversion_review=criterion)
