"""One key, and the three readers that must agree with the database."""

import pytest
from django.core.exceptions import ValidationError
from django.db.models.functions import Lower, Trim

from common.naming import name_key
from games.models import Platform

pytestmark = pytest.mark.django_db

#: The database reads this pair as two keys and `casefold()` as one.
DIVERGING = ("Straße", "STRASSE")


@pytest.mark.parametrize(
    "value",
    [
        *DIVERGING,
        " Deluxe ",
        #: SQL lowercases this to one character and Python to two.
        #: Not a bug to close: the builtin provider states the simple
        #: case mapping and `str.lower()` the full one, and nothing in
        #: Python states the provider's. Strict, so the day a Python
        #: release or a provider change closes the gap says so here.
        pytest.param(
            "İ",
            marks=pytest.mark.xfail(
                reason="the provider states the simple case mapping and "
                "Python the full one",
                strict=True,
            ),
        ),
    ],
)
def test_the_key_is_what_the_database_compares(value):
    stored = Platform.objects.create(name=value)
    read = (
        Platform.objects.filter(pk=stored.pk)
        .annotate(key=Lower(Trim("name")))
        .values_list("key", flat=True)
        .first()
    )

    assert name_key(value) == read


def test_two_names_the_constraint_separates_are_two_names():
    assert name_key(DIVERGING[0]) != name_key(DIVERGING[1])


def test_a_private_platform_may_not_shadow_a_shared_one_in_another_case(
    owned_library,
):
    Platform.objects.create(name="STRASSE")

    with pytest.raises(ValidationError):
        Platform(name="strasse", library=owned_library).full_clean()
