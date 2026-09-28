"""A platform states an icon the picker lists."""

import pytest
from django.core.exceptions import ValidationError

from games.forms import PlatformForm
from games.models import ICON_UNLISTED, Platform

pytestmark = pytest.mark.django_db


def test_a_platform_stating_no_icon_holds_unspecified(owned_library):
    platform = Platform.objects.create(library=owned_library, name="Playstation 5")

    assert platform.icon == "unspecified"


def test_an_unlisted_icon_is_refused_on_its_field(owned_library):
    with pytest.raises(ValidationError) as refusal:
        Platform.objects.create(library=owned_library, name="PC", icon="pc")

    assert refusal.value.message_dict == {"icon": [ICON_UNLISTED]}


@pytest.mark.parametrize("stated", [{}, {"icon": ""}])
def test_the_form_states_unspecified_for_no_icon(owned_library, stated):
    form = PlatformForm({"name": "Amiga", "group": "", **stated}, library=owned_library)

    assert form.is_valid(), form.errors
    assert form.save().icon == "unspecified"


def test_the_form_refuses_an_unlisted_icon(owned_library):
    form = PlatformForm(
        {"name": "Amiga", "group": "", "icon": "pc"}, library=owned_library
    )

    assert not form.is_valid()
    assert "icon" in form.errors
