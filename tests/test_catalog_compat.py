from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.catalog_compat import (
    LEGACY_IDENTITY_TAKEN,
    InitialRelease,
    mirror_legacy_columns,
    save_legacy_game_form,
    write_and_mirror,
)
from games.catalog_writes import add_release, save_private_game
from games.external_references import save_external_reference
from games.forms import GameForm
from games.models import (
    Edition,
    ExternalReference,
    Game,
    Platform,
    PlayerGameStatus,
    Release,
)
from timetracker.temporal import TemporalValue, temporal_input_name

pytestmark = pytest.mark.django_db

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)


def game_form(*, library, instance=None, original="2001", **overrides) -> GameForm:
    data = {
        "name": "Legacy adapter game",
        "sort_name": "Adapter game, Legacy",
        "status": PlayerGameStatus.PLAYED,
        "mastered": "on",
        "wikidata": "Q123",
        temporal_input_name("original_release_date", "kind"): "date"
        if original
        else "",
        temporal_input_name("original_release_date", "start_year"): original,
    }
    data.update(overrides)
    return GameForm(
        data=data, instance=instance, library=library, presentation=PRESENTATION
    )


def new_release(*, platform=None, year: int | None = 2002) -> InitialRelease:
    """The inline row the Add Game form states beside the Game."""
    return InitialRelease(
        platform=platform,
        release_date=None if year is None else TemporalValue.from_year(year),
    )


def test_legacy_wikidata_create_canonicalizes_and_synchronizes(owned_library):
    form = game_form(library=owned_library, wikidata=" q123 ")

    assert form.is_valid()
    game = save_legacy_game_form(form)

    game.refresh_from_db()
    reference = ExternalReference.objects.get(
        provider="wikidata", entity_kind="game", provider_key="Q123"
    )
    assert game.wikidata == "Q123"
    assert reference.game_id == game.pk


def test_legacy_wikidata_unchanged_edit_retains_reference_identity(owned_library):
    create_form = game_form(library=owned_library)
    assert create_form.is_valid()
    game = save_legacy_game_form(create_form)
    reference_id = ExternalReference.objects.get(game=game).pk

    edit_form = game_form(library=owned_library, instance=game)
    assert edit_form.is_valid()
    save_legacy_game_form(edit_form)

    assert ExternalReference.objects.get(game=game).pk == reference_id


def test_legacy_wikidata_changed_edit_replaces_the_mapping(owned_library):
    create_form = game_form(library=owned_library)
    assert create_form.is_valid()
    game = save_legacy_game_form(create_form)
    old_reference = ExternalReference.objects.get(game=game)

    edit_form = game_form(library=owned_library, instance=game, wikidata="Q456")
    assert edit_form.is_valid()
    save_legacy_game_form(edit_form)

    assert not ExternalReference.objects.filter(pk=old_reference.pk).exists()
    assert (
        ExternalReference.objects.get(
            provider="wikidata", entity_kind="game", provider_key="Q456"
        ).game_id
        == game.pk
    )


def test_legacy_wikidata_clearing_removes_the_mapping(owned_library):
    create_form = game_form(library=owned_library)
    assert create_form.is_valid()
    game = save_legacy_game_form(create_form)

    edit_form = game_form(library=owned_library, instance=game, wikidata="   ")
    assert edit_form.is_valid()
    save_legacy_game_form(edit_form)

    game.refresh_from_db()
    assert game.wikidata == ""
    assert not ExternalReference.objects.filter(game=game).exists()


def test_legacy_wikidata_conflict_rolls_back_the_game_graph_and_old_reference(
    owned_library,
):
    create_form = game_form(library=owned_library, name="Before conflict")
    assert create_form.is_valid()
    game = save_legacy_game_form(create_form)
    old_reference = ExternalReference.objects.get(game=game)
    edition_id = game.editions.get(is_default=True).pk
    release_id = game.editions.get(is_default=True).releases.get(is_default=True).pk

    edit_form = game_form(
        library=owned_library,
        instance=game,
        name="After conflict",
        wikidata="Q456",
    )
    assert edit_form.is_valid()
    owner = Game.objects.create(library=owned_library, name="Conflict owner")
    save_external_reference(provider="wikidata", provider_key="Q456", target=owner)

    with pytest.raises(ValidationError, match="already maps to another catalog target"):
        save_legacy_game_form(edit_form)

    stored_game = Game.objects.get(pk=game.pk)
    assert (stored_game.name, stored_game.wikidata) == ("Before conflict", "Q123")
    assert stored_game.editions.get(is_default=True).pk == edition_id
    assert Release.objects.get(pk=release_id).edition_id == edition_id
    assert ExternalReference.objects.get(pk=old_reference.pk).game_id == game.pk


def test_legacy_wikidata_reference_failure_rolls_back_new_and_existing_graphs(
    owned_library, monkeypatch
):
    existing_form = game_form(library=owned_library, name="Before reference failure")
    assert existing_form.is_valid()
    existing_game = save_legacy_game_form(existing_form)
    old_reference = ExternalReference.objects.get(game=existing_game)
    edition_id = existing_game.editions.get(is_default=True).pk
    release_id = (
        existing_game.editions.get(is_default=True).releases.get(is_default=True).pk
    )

    def fail_reference_save(*args, **kwargs):
        raise RuntimeError("forced reference save failure")

    monkeypatch.setattr(ExternalReference, "save", fail_reference_save)
    new_form = game_form(
        library=owned_library,
        name="New reference failure",
        wikidata="Q789",
    )
    assert new_form.is_valid()
    with pytest.raises(RuntimeError, match="forced reference save failure"):
        save_legacy_game_form(new_form)

    edit_form = game_form(
        library=owned_library,
        instance=existing_game,
        name="After reference failure",
        wikidata="Q456",
    )
    assert edit_form.is_valid()
    with pytest.raises(RuntimeError, match="forced reference save failure"):
        save_legacy_game_form(edit_form)

    stored_game = Game.objects.get(pk=existing_game.pk)
    assert not Game.objects.filter(name="New reference failure").exists()
    assert (stored_game.name, stored_game.wikidata) == (
        "Before reference failure",
        "Q123",
    )
    assert stored_game.editions.get(is_default=True).pk == edition_id
    assert Release.objects.get(pk=release_id).edition_id == edition_id
    assert (
        ExternalReference.objects.get(pk=old_reference.pk).game_id == existing_game.pk
    )


def test_save_private_game_does_not_create_a_legacy_wikidata_reference(owned_library):
    graph = save_private_game(
        game=Game(
            library=owned_library,
            name="Durable writer only",
            wikidata="Q123",
        ),
        original_release_date=None,
        release_date=TemporalValue.from_year(2001),
        platform=None,
    )

    assert graph.game.wikidata == "Q123"
    assert not ExternalReference.objects.filter(game=graph.game).exists()


# --- the flat columns shadow the graph ---------------------------------------


def test_the_mirror_copies_the_default_release_onto_the_flat_columns(owned_library):
    platform = Platform.objects.create(library=owned_library, name="Amiga")
    game = Game.objects.create(library=owned_library, name="Elite")
    edition = Edition.objects.create(game=game, is_default=True)
    Release.objects.create(
        edition=edition,
        platform=platform,
        release_date=TemporalValue.from_month(1984, 6),
        is_default=True,
    )

    mirror_legacy_columns(game)

    game.refresh_from_db()
    assert game.platform_id == platform.pk
    assert game.year_released == 1984


def test_the_mirror_keeps_the_precision_of_the_original_date(owned_library):
    game = Game.objects.create(
        library=owned_library,
        name="Elite",
        original_release_date=TemporalValue.from_month(1983, 9),
    )

    mirror_legacy_columns(game)

    game.refresh_from_db()
    assert game.original_year_released == 1983
    assert game.original_release_date == TemporalValue.from_month(1983, 9)


def test_the_mirror_clears_the_columns_when_the_release_states_nothing(owned_library):
    game = Game.objects.create(library=owned_library, name="Elite", year_released=1999)
    edition = Edition.objects.create(game=game, is_default=True)
    Release.objects.create(edition=edition, is_default=True)

    mirror_legacy_columns(game)

    game.refresh_from_db()
    assert game.platform_id is None
    assert game.year_released is None


def test_the_mirror_refuses_to_collide_with_another_live_game(owned_library):
    platform = Platform.objects.create(library=owned_library, name="Amiga")
    Game.objects.create(
        library=owned_library, name="Elite", platform=platform, year_released=1984
    )
    second = Game.objects.create(library=owned_library, name="Elite")
    edition = Edition.objects.create(game=second, is_default=True)
    Release.objects.create(
        edition=edition,
        platform=platform,
        release_date=TemporalValue.from_year(1984),
        is_default=True,
    )

    with pytest.raises(ValidationError) as refusal:
        mirror_legacy_columns(second)

    assert LEGACY_IDENTITY_TAKEN in refusal.value.messages


def test_a_refused_mirror_leaves_the_write_undone(owned_library):
    """One transaction: the mirror's refusal takes the write with it."""
    platform = Platform.objects.create(library=owned_library, name="Amiga")
    Game.objects.create(
        library=owned_library, name="Elite", platform=platform, year_released=1984
    )
    second = Game.objects.create(library=owned_library, name="Elite")
    edition = Edition.objects.create(game=second, is_default=True)

    with pytest.raises(ValidationError):
        write_and_mirror(
            second,
            lambda: add_release(
                edition=edition,
                library=owned_library,
                platform=platform,
                release_date=TemporalValue.from_year(1984),
            ),
        )

    assert not Release.objects.filter(edition=edition).exists()


# --- the form states a graph, and only what it states ------------------------


def stored_release(game) -> Release:
    return Release.objects.get(
        edition__game=game, edition__is_default=True, is_default=True
    )


def test_the_inline_row_states_the_first_release(owned_library):
    platform = Platform.objects.create(library=owned_library, name="Amiga")
    form = game_form(library=owned_library, name="Elite")
    assert form.is_valid()

    game = save_legacy_game_form(
        form, initial_release=new_release(platform=platform, year=1984)
    )

    release = stored_release(game)
    assert release.platform_id == platform.pk
    assert release.release_date == TemporalValue.from_year(1984)
    assert (game.platform_id, game.year_released) == (platform.pk, 1984)


def test_an_edit_passes_the_stored_release_straight_back(owned_library):
    platform = Platform.objects.create(library=owned_library, name="Amiga")
    create_form = game_form(library=owned_library, name="Elite")
    assert create_form.is_valid()
    game = save_legacy_game_form(
        create_form, initial_release=new_release(platform=platform, year=1984)
    )
    span = TemporalValue.parse("1984-05/1984-06")
    Release.objects.filter(pk=stored_release(game).pk).update(release_date=span)

    edit_form = game_form(
        library=owned_library, instance=Game.objects.get(pk=game.pk), name="Elite II"
    )
    assert edit_form.is_valid()
    save_legacy_game_form(edit_form)

    release = stored_release(game)
    assert release.release_date == span
    assert release.platform_id == platform.pk


def test_the_form_states_the_original_date_at_its_own_precision(owned_library):
    form = game_form(
        library=owned_library,
        name="Elite",
        **{
            temporal_input_name("original_release_date", "start_month"): "9",
        },
        original="1983",
    )
    assert form.is_valid()

    game = save_legacy_game_form(form)

    stored = Game.objects.get(pk=game.pk)
    assert stored.original_release_date == TemporalValue.from_month(1983, 9)
    assert stored.original_year_released == 1983


def test_the_form_clears_the_original_date(owned_library):
    create_form = game_form(library=owned_library, name="Elite")
    assert create_form.is_valid()
    game = save_legacy_game_form(create_form)

    edit_form = game_form(
        library=owned_library, instance=Game.objects.get(pk=game.pk), original=""
    )
    assert edit_form.is_valid()
    save_legacy_game_form(edit_form)

    stored = Game.objects.get(pk=game.pk)
    assert stored.original_release_date is None
    assert stored.original_year_released is None
