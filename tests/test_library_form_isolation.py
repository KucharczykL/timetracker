from functools import partial
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django import forms
from django.urls import reverse

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.catalog_form import ReleaseRowForm
from games.forms import (
    DeviceForm,
    GameForm,
    LibraryPreferencesForm,
    PlatformForm,
    PlayEventForm,
    PurchaseForm,
    SessionForm,
)
from games.models import (
    Device,
    Game,
    Platform,
    PlayerGameStatus,
    PlayEvent,
    Purchase,
    Session,
)

pytestmark = pytest.mark.django_db

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


@pytest.fixture
def world(client, django_user_model):
    owner = django_user_model.objects.create_user(username="owner-form", password="p")
    foreign_user = django_user_model.objects.create_user(
        username="foreign-form", password="p"
    )
    owner_library = owner.library
    foreign_library = foreign_user.library
    client.force_login(owner)
    client.raise_request_exception = False

    shared_platform = Platform.objects.create(name="Shared form platform")
    own_platform = Platform.objects.create(
        library=owner_library, name="Owner form platform"
    )
    foreign_platform = Platform.objects.create(
        library=foreign_library, name="Foreign form platform"
    )
    own_game = Game.objects.create(
        library=owner_library, name="Owner form game", platform=own_platform
    )
    foreign_game = Game.objects.create(
        library=foreign_library, name="Foreign form game", platform=foreign_platform
    )
    own_device = Device.objects.create(library=owner_library, name="Owner form device")
    foreign_device = Device.objects.create(
        library=foreign_library, name="Foreign form device"
    )
    return SimpleNamespace(**locals())


def _ids(queryset):
    return set(queryset.values_list("pk", flat=True))


def test_form_relationship_querysets_are_explicitly_library_bound(world):
    session = SessionForm(library=world.owner_library, presentation=PRESENTATION)
    purchase = PurchaseForm(
        library=world.owner_library,
        user=world.owner,
        presentation=PRESENTATION,
    )
    release = ReleaseRowForm(library=world.owner_library, presentation=PRESENTATION)
    playevent = PlayEventForm(library=world.owner_library, presentation=PRESENTATION)

    assert _ids(session.fields["game"].queryset) == {world.own_game.pk}
    assert _ids(session.fields["device"].queryset) == {world.own_device.pk}
    assert _ids(purchase.fields["games"].queryset) == {world.own_game.pk}
    assert _ids(purchase.fields["related_game"].queryset) == {world.own_game.pk}
    assert _ids(playevent.fields["game"].queryset) == {world.own_game.pk}
    visible_platforms = {world.shared_platform.pk, world.own_platform.pk}
    #: The Game names no Platform now; its first Release does.
    assert _ids(release.fields["platform"].queryset) == visible_platforms
    assert _ids(purchase.fields["platform"].queryset) == visible_platforms


def test_library_preferences_default_device_is_a_scoped_model_choice(world):
    form = LibraryPreferencesForm(
        devices=Device.objects.for_library(world.owner_library).order_by("name"),
        default_device=world.own_device,
    )
    field = form.fields["default_device"]

    assert isinstance(field, forms.ModelChoiceField)
    assert _ids(field.queryset) == {world.own_device.pk}
    assert form.initial["default_device"] == world.own_device


@pytest.mark.parametrize(
    ("form_class", "data", "model"),
    [
        (
            PlatformForm,
            {"name": "New private platform", "icon": "", "group": ""},
            Platform,
        ),
        (DeviceForm, {"name": "New private device", "type": Device.UNKNOWN}, Device),
        (
            partial(GameForm, presentation=PRESENTATION),
            {
                "name": "New private game",
                "status": PlayerGameStatus.UNPLAYED,
            },
            Game,
        ),
    ],
)
def test_directly_owned_forms_save_new_rows_in_the_explicit_library(
    world, form_class, data, model
):
    form = form_class(data=data, library=world.owner_library)

    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.library == world.owner_library
    assert (
        model.objects.for_library(world.foreign_library).filter(pk=saved.pk).count()
        == 0
    )


def test_shared_platform_is_selectable_but_foreign_private_platform_is_rejected(world):
    shared_form = ReleaseRowForm(
        data={"platform": world.shared_platform.pk},
        library=world.owner_library,
        presentation=PRESENTATION,
    )
    foreign_form = ReleaseRowForm(
        data={"platform": world.foreign_platform.pk},
        library=world.owner_library,
        presentation=PRESENTATION,
    )

    assert shared_form.is_valid(), shared_form.errors
    assert shared_form.cleaned_data["platform"] == world.shared_platform
    assert not foreign_form.is_valid()
    assert "platform" in foreign_form.errors
    assert world.foreign_platform.name not in str(foreign_form)


def test_library_bound_forms_validate_constraints_with_implicit_owner(world):
    #: The Game pair (name, platform, year) left the form with #969.
    #: `mirror_legacy_columns` guards it, over `tests/test_catalog_compat.py`.
    platform_form = PlatformForm(
        data={
            "name": world.own_platform.name,
            "icon": "",
            "group": world.own_platform.group,
        },
        library=world.owner_library,
    )

    assert not platform_form.is_valid()
    assert "__all__" in platform_form.errors


def test_session_form_rejects_foreign_game_and_device_without_saving(world):
    before = Session.objects.count()
    form = SessionForm(
        data={
            "game": world.foreign_game.pk,
            "timestamp_start": "2026-08-14T12:00:00+00:00",
            "timestamp_start_timezone": "UTC",
            "timestamp_end": "",
            "timestamp_end_timezone": "",
            "duration_manual": "",
            "device": world.foreign_device.pk,
            "note": "",
        },
        library=world.owner_library,
        presentation=PRESENTATION,
    )

    assert not form.is_valid()
    assert {"game", "device"} <= set(form.errors)
    assert Session.objects.count() == before
    html = str(form)
    assert world.foreign_game.name not in html
    assert world.foreign_device.name not in html


def test_purchase_form_rejects_foreign_relationships_without_saving(world):
    before = Purchase.objects.count()
    form = PurchaseForm(
        data={
            "games": [world.foreign_game.pk],
            "platform": world.foreign_platform.pk,
            "date_purchased": "2026-08-14",
            "date_refunded": "",
            "price": "10",
            "price_currency": "USD",
            "ownership_type": Purchase.DIGITAL,
            "type": Purchase.DLC,
            "related_game": world.foreign_game.pk,
            "name": "Foreign add-on",
        },
        library=world.owner_library,
        user=world.owner,
        presentation=PRESENTATION,
    )

    assert not form.is_valid()
    assert {"games", "platform", "related_game"} <= set(form.errors)
    assert Purchase.objects.count() == before
    html = str(form)
    assert world.foreign_game.name not in html
    assert world.foreign_platform.name not in html


def test_the_play_event_form_rejects_a_foreign_game(world):
    before = PlayEvent.objects.count()
    form = PlayEventForm(
        data={
            "game": world.foreign_game.pk,
            "started": "2026-08-14",
            "ended": "",
            "note": "",
        },
        library=world.owner_library,
        presentation=PRESENTATION,
    )

    assert not form.is_valid()
    assert "game" in form.errors
    assert PlayEvent.objects.count() == before
    assert world.foreign_game.name not in str(form)


def test_add_game_post_with_foreign_platform_is_rejected_without_mutation(world):
    response = world.client.post(
        reverse("games:add_game"),
        {
            "name": "Rejected game",
            "platform": world.foreign_platform.pk,
            "status": PlayerGameStatus.UNPLAYED,
        },
    )

    assert response.status_code == 200
    assert not Game.objects.filter(name="Rejected game").exists()
    assert world.foreign_platform.name not in response.content.decode()


def test_add_session_post_with_foreign_device_is_rejected_without_mutation(world):
    before = Session.objects.count()
    response = world.client.post(
        reverse("games:add_session"),
        {
            "game": world.own_game.pk,
            "timestamp_start": "2026-08-14T12:00:00+00:00",
            "timestamp_start_timezone": "UTC",
            "timestamp_end": "",
            "timestamp_end_timezone": "",
            "duration_manual": "",
            "device": world.foreign_device.pk,
            "note": "",
        },
    )
    assert response.status_code == 200
    assert Session.objects.count() == before
    body = response.content.decode()
    assert world.foreign_device.name not in body


def test_bound_forms_preselect_platform_by_integer_id(world):
    """A bound instance must hand the platform combobox the identity its
    options carry — an integer Platform pk — not the foreign key's attname."""
    import datetime

    purchase = Purchase.objects.create(
        library=world.owner_library,
        platform=world.own_platform,
        date_purchased=datetime.date(2026, 1, 1),
        price=10,
        price_currency="USD",
    )

    purchase_form = PurchaseForm(
        library=world.owner_library,
        user=world.owner,
        presentation=PRESENTATION,
        instance=purchase,
    )

    rendered = str(purchase_form["platform"])
    assert world.own_platform.name in rendered
    assert f'value="{world.own_platform.pk}"' in rendered


def test_bound_forms_leave_an_unset_platform_unselected(world):
    import datetime

    platformless_purchase = Purchase.objects.create(
        library=world.owner_library,
        platform=None,
        date_purchased=datetime.date(2026, 1, 1),
        price=10,
        price_currency="USD",
    )

    purchase_form = PurchaseForm(
        library=world.owner_library,
        user=world.owner,
        presentation=PRESENTATION,
        instance=platformless_purchase,
    )

    rendered = str(purchase_form["platform"])
    assert world.own_platform.name not in rendered
    assert "None" not in rendered


def test_a_release_row_offers_unspecified_for_no_platform(world):
    """The row's platform is a plain select, thus every option is drawn.

    An unset Platform is a fact rather than a blank, and the empty
    option says so in words.
    """
    rendered = str(
        ReleaseRowForm(library=world.owner_library, presentation=PRESENTATION)[
            "platform"
        ]
    )

    assert "Unspecified" in rendered
    assert world.own_platform.name in rendered
    assert world.foreign_platform.name not in rendered


def test_game_option_data_carries_the_integer_platform_id(world):
    from games.forms import game_option_data

    platformless = Game.objects.create(
        library=world.owner_library, name="Optionless", platform=None
    )

    assert game_option_data(world.own_game) == {
        "platform": str(world.own_platform.pk),
        "platform_name": world.own_platform.name,
    }
    assert game_option_data(platformless) == {"platform": "", "platform_name": ""}
