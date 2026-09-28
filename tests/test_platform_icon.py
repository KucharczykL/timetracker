"""A platform states an icon the picker lists."""

import pytest
from django.core.exceptions import ValidationError

from common.platform_icons import ICON_UNLISTED
from games.forms import PlatformForm
from games.models import Platform

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


def test_the_group_picker_offers_the_librarys_groups_and_holds_the_platforms(
    owned_library,
):
    Platform.objects.create(library=owned_library, name="Amiga", group="Commodore")
    platform = Platform.objects.create(library=owned_library, name="DOS", group="PC")

    html = str(PlatformForm(instance=platform, library=owned_library)["group"])

    assert 'data-value="Commodore"' in html
    assert 'create="select"' in html
    assert 'create-verb="Use"' in html
    assert '<input name="group" value="PC" type="hidden">' in html


@pytest.mark.parametrize("group", ["Commodore", "Retro"])
def test_the_form_saves_a_suggested_or_typed_group(owned_library, group):
    Platform.objects.create(library=owned_library, name="Amiga", group="Commodore")
    form = PlatformForm({"name": "C64", "group": group}, library=owned_library)

    assert form.is_valid(), form.errors
    assert form.save().group == group


def test_a_cleared_group_box_states_no_group(owned_library):
    platform = Platform.objects.create(library=owned_library, name="DOS", group="PC")
    form = PlatformForm(
        {"name": "DOS", "icon": "unspecified"}, instance=platform, library=owned_library
    )

    assert form.is_valid(), form.errors
    assert form.save().group == ""


def test_the_group_box_takes_no_more_than_a_group_holds(owned_library):
    html = str(PlatformForm(library=owned_library)["group"])

    assert 'maxlength="255"' in html


def test_a_posting_create_row_names_its_endpoint():
    from common.components import PostCreate

    with pytest.raises(ValueError):
        PostCreate("")


def test_a_listed_icon_no_snippet_draws_fails_the_check():
    from games.checks import unsnipped_platform_icons

    refusals = unsnipped_platform_icons(["steam", "gone"], ["steam"])

    assert [refusal.id for refusal in refusals] == ["games.E013"]
    assert "gone" in refusals[0].msg
    assert unsnipped_platform_icons(["steam"], ["steam", "edit"]) == []
