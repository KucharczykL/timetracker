"""One submit of the Game form: one transaction, one creator."""

from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse

from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.catalog_compat import (
    LEGACY_IDENTITY_TAKEN,
    MirroredIdentity,
    mirror_legacy_columns,
)
from games.catalog_form import CatalogGraphForm
from games.catalog_submit import (
    CONSTRAINT_ANSWERS,
    RACED,
    REMOVED_SINCE_READ,
    UNREACHABLE_FROM_THE_GAME_FORM,
    answered_constraint,
    save_game_columns,
    submitted_game_or_form_error,
)
from games.forms import GameForm
from games.models import (
    Edition,
    ExternalReference,
    Game,
    Platform,
    PlayerGameStatus,
    Release,
)
from games.reference_form import ReferenceSetForm
from games.removal import remove
from timetracker.temporal import TemporalValue, temporal_input_name

pytestmark = pytest.mark.django_db(transaction=True)

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)
#: These cases state the columns alone; no graph names a pair.
NO_MIRROR = MirroredIdentity(None, None)


def test_a_binned_row_with_a_bad_value_refuses_nothing(
    client, owned_user, stated_graph, game_post
):
    """A row that is going states only which row it is.

    Its date never reaches storage, and the page draws the row out of
    sight, thus a sentence about that date would refuse a submit for a
    reason nobody can read.
    """
    library = owned_user.library
    client.force_login(owned_user)
    graph = stated_graph(Game(library=library, name="Elite"), library)
    staying = Release.objects.create(
        edition=graph.edition,
        platform=Platform.objects.create(library=library, name="DOS"),
        release_date=TemporalValue.from_year(1988),
    )
    posted = game_post("Elite")
    posted["edition-0-edition_id"] = str(graph.edition.pk)
    posted["edition-0-releases-count"] = "2"
    posted["edition-0-release-0-release_id"] = str(graph.release.pk)
    posted["edition-0-release-0-removed"] = "on"
    #: A month with no year beside it: the field alone refuses this.
    row = "edition-0-release-0-release_date"
    posted[temporal_input_name(row, "kind")] = "date"
    posted[temporal_input_name(row, "start_month")] = "5"
    posted["edition-0-release-1-release_id"] = str(staying.pk)
    posted["edition-0-release-1-platform"] = str(staying.platform_id)
    staying_row = "edition-0-release-1-release_date"
    posted[temporal_input_name(staying_row, "kind")] = "date"
    posted[temporal_input_name(staying_row, "start_year")] = "1988"
    posted["in_library"] = "edition-0-release-1"

    response = client.post(
        reverse("games:edit_game", args=[graph.game.pk]), data=posted
    )

    assert response.status_code == 302
    graph.release.refresh_from_db()
    assert graph.release.removed_at is not None
    assert [row.pk for row in graph.edition.releases.alive()] == [staying.pk]


def test_a_refused_graph_takes_the_renamed_game_back(
    client, owned_user, stated_graph, game_post
):
    """One transaction: the name and the graph go together or not at all."""
    client.force_login(owned_user)
    graph = stated_graph(
        Game(library=owned_user.library, name="Elite"), owned_user.library
    )
    #: A live Edition this submit never mentions still holds its name,
    #: and only the service knows that. The form sees one clean block.
    Edition.objects.create(game=graph.game, name="Director's Cut")
    posted = game_post("Elite Renamed")
    posted["edition-0-edition_id"] = str(graph.edition.pk)
    posted["edition-0-release-0-release_id"] = str(graph.release.pk)
    posted["edition-0-name"] = "Director's Cut"

    response = client.post(
        reverse("games:edit_game", args=[graph.game.pk]), data=posted
    )

    assert response.status_code == 200
    graph.game.refresh_from_db()
    assert graph.game.name == "Elite"


def test_a_graph_that_is_fine_saves_the_rename_with_it(
    client, owned_user, stated_graph, game_post
):
    """The inverse, so the rollback above is not passing on nothing."""
    client.force_login(owned_user)
    graph = stated_graph(
        Game(library=owned_user.library, name="Elite"), owned_user.library
    )
    posted = game_post("Elite Renamed")
    posted["edition-0-edition_id"] = str(graph.edition.pk)
    posted["edition-0-release-0-release_id"] = str(graph.release.pk)
    posted["edition-0-name"] = "Director's Cut"

    response = client.post(
        reverse("games:edit_game", args=[graph.game.pk]), data=posted
    )

    assert response.status_code == 302
    graph.game.refresh_from_db()
    graph.edition.refresh_from_db()
    assert (graph.game.name, graph.edition.name) == (
        "Elite Renamed",
        "Director's Cut",
    )


def test_add_game_leaves_exactly_one_edition_and_one_release(
    client, owned_user, game_post
):
    """One creator: nothing claims a row it did not ask for."""
    client.force_login(owned_user)
    posted = game_post("Elite")
    posted["edition-0-name"] = "Director's Cut"
    row = "edition-0-release-0-release_date"
    posted[temporal_input_name(row, "kind")] = "date"
    posted[temporal_input_name(row, "start_year")] = "1984"

    response = client.post(reverse("games:add_game"), data=posted)

    assert response.status_code == 302
    game = Game.objects.get(name="Elite")
    editions = Edition.objects.alive().filter(game=game)
    assert editions.count() == 1
    assert editions.get().name == "Director's Cut"
    releases = Release.objects.alive().filter(edition=editions.get())
    assert releases.count() == 1
    assert releases.get().is_default is True


def test_a_game_with_no_graph_can_be_edited(client, owned_user, game_post):
    """What the backfill leaves: a Game nothing ever wrote a graph for."""
    client.force_login(owned_user)
    game = Game.objects.create(library=owned_user.library, name="Stranded")

    response = client.post(
        reverse("games:edit_game", args=[game.pk]), data=game_post("Stranded")
    )

    assert response.status_code == 302
    assert Edition.objects.alive().filter(game=game).count() == 1


def test_a_taken_legacy_identity_lands_on_the_game_form(
    client, owned_user, stated_graph, game_post
):
    """The mirror refuses the whole Game, not one row."""
    client.force_login(owned_user)
    stated_graph(Game(library=owned_user.library, name="Twin"), owned_user.library)
    graph = stated_graph(
        Game(library=owned_user.library, name="Elite"), owned_user.library
    )
    posted = game_post("Twin")
    posted["edition-0-edition_id"] = str(graph.edition.pk)
    posted["edition-0-release-0-release_id"] = str(graph.release.pk)

    response = client.post(
        reverse("games:edit_game", args=[graph.game.pk]), data=posted
    )

    assert response.status_code == 200
    assert LEGACY_IDENTITY_TAKEN in response.content.decode()


def test_a_rename_that_moves_its_own_platform_is_not_refused(
    client, owned_user, stated_graph, game_post
):
    """The name and the pair it stands beside go in one write.

    The end state is free, and only the pair the submit replaces
    was ever taken, thus nothing here collides.
    """
    library = owned_user.library
    client.force_login(owned_user)
    amiga = Platform.objects.create(library=library, name="Amiga")
    dos = Platform.objects.create(library=library, name="DOS")
    Game.objects.create(
        library=library, name="Elite", platform=amiga, year_released=1984
    )
    graph = stated_graph(
        Game(library=library, name="Frontier"),
        library,
        platform=amiga,
        release_date=TemporalValue.from_year(1984),
    )
    mirror_legacy_columns(graph.game)
    posted = game_post("Elite")
    posted["edition-0-edition_id"] = str(graph.edition.pk)
    posted["edition-0-release-0-release_id"] = str(graph.release.pk)
    posted["edition-0-release-0-platform"] = str(dos.pk)
    row = "edition-0-release-0-release_date"
    posted[temporal_input_name(row, "kind")] = "date"
    posted[temporal_input_name(row, "start_year")] = "1984"

    response = client.post(
        reverse("games:edit_game", args=[graph.game.pk]), data=posted
    )

    assert response.status_code == 302
    graph.game.refresh_from_db()
    assert (graph.game.name, graph.game.platform_id) == ("Elite", dos.pk)


def test_a_written_graph_is_redrawn_from_storage(
    client, owned_user, stated_graph, game_post
):
    """A refused command re-renders the page, and a resubmit is not a copy."""
    library = owned_user.library
    client.force_login(owned_user)
    graph = stated_graph(Game(library=library, name="Elite"), library)
    posted = game_post("Elite")
    posted["editions-count"] = "2"
    posted["edition-0-edition_id"] = str(graph.edition.pk)
    posted["edition-0-release-0-release_id"] = str(graph.release.pk)
    posted["edition-1-name"] = "Gold"
    posted["edition-1-releases-count"] = "1"
    posted["edition-1-release-0-platform"] = ""

    with patch(
        "games.views.game.record_facts_for_request", return_value=False
    ) as refused:
        response = client.post(
            reverse("games:edit_game", args=[graph.game.pk]), data=posted
        )

    assert refused.called
    assert response.status_code == 200
    written = Edition.objects.alive().get(game=graph.game, name="Gold")
    assert str(written.pk) in response.content.decode()


def test_a_race_the_pre_check_missed_answers_in_words(
    client, owned_user, stated_graph, game_post
):
    """The database is the only thing that decides, so read what it did.

    The two games differ by year until this submit, thus the Game's
    own save is fine and only the mirror walks it onto the twin.
    """
    client.force_login(owned_user)
    twin = stated_graph(
        Game(library=owned_user.library, name="Twin"),
        owned_user.library,
        release_date=TemporalValue.from_year(1984),
    )
    mirror_legacy_columns(twin.game)
    graph = stated_graph(
        Game(library=owned_user.library, name="Elite"),
        owned_user.library,
        release_date=TemporalValue.from_year(1990),
    )
    mirror_legacy_columns(graph.game)
    posted = game_post("Twin")
    posted["edition-0-edition_id"] = str(graph.edition.pk)
    posted["edition-0-release-0-release_id"] = str(graph.release.pk)
    row = "edition-0-release-0-release_date"
    posted[temporal_input_name(row, "kind")] = "date"
    posted[temporal_input_name(row, "start_year")] = "1984"

    with patch("games.catalog_compat._collides", return_value=False):
        response = client.post(
            reverse("games:edit_game", args=[graph.game.pk]), data=posted
        )

    assert response.status_code == 200
    assert LEGACY_IDENTITY_TAKEN in response.content.decode()


# --- the mapping itself ------------------------------------------------------


class _Diagnostic:
    def __init__(self, name: str) -> None:
        self.constraint_name = name


class _Cause(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.diag = _Diagnostic(name)


def collision(name: str) -> IntegrityError:
    error = IntegrityError(name)
    error.__cause__ = _Cause(name)
    return error


def test_a_mapped_constraint_becomes_a_sentence():
    answer = answered_constraint(collision("unique_default_edition_per_game"))

    assert answer is not None
    assert answer.sentence == RACED
    assert answer.field is None


def test_the_wikidata_constraint_never_reaches_the_mapping():
    """`state_external_references` answers it first, on its own box."""
    assert (
        answered_constraint(collision("unique_external_reference_provider_kind_key"))
        is None
    )
    assert "unique_external_reference_provider_kind_key" in (
        UNREACHABLE_FROM_THE_GAME_FORM
    )


def test_an_unmapped_constraint_gets_no_sentence():
    """A wrong sentence is worse than none."""
    assert answered_constraint(collision("unique_library_mode_name_preset")) is None


def test_a_collision_with_no_diagnostic_gets_no_sentence():
    assert answered_constraint(IntegrityError("no cause")) is None


def test_every_unique_constraint_the_form_can_reach_is_mapped():
    """A migration that adds one fails here, not in front of a person."""
    from django.db.models import UniqueConstraint

    reachable = [Game, Edition, Release, ExternalReference]
    declared = {
        constraint.name
        for model in reachable
        for constraint in model._meta.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    accounted = set(CONSTRAINT_ANSWERS) | set(UNREACHABLE_FROM_THE_GAME_FORM)

    assert declared <= accounted, declared - accounted


# --- the Game's own columns --------------------------------------------------


def game_form(*, library, instance=None, original="2001", **overrides) -> GameForm:
    data = {
        "name": "Legacy adapter game",
        "sort_name": "Adapter game, Legacy",
        "status": PlayerGameStatus.PLAYED,
        "mastered": "on",
        temporal_input_name("original_release_date", "kind"): "date"
        if original
        else "",
        temporal_input_name("original_release_date", "start_year"): original,
    }
    data.update(overrides)
    return GameForm(
        data=data, instance=instance, library=library, presentation=PRESENTATION
    )


def saved_columns(form: GameForm) -> Game:
    assert form.is_valid(), form.errors
    return save_game_columns(form, NO_MIRROR)


def test_a_persisted_game_may_not_change_library_owner(
    owned_library, django_user_model
):
    other = django_user_model.objects.create_user(username="new-catalog-owner")
    game = Game.objects.create(library=owned_library, name="Elite")
    form = game_form(library=owned_library, instance=game, name="Elite")
    assert form.is_valid(), form.errors
    form.instance.library = other.library

    with pytest.raises(ValidationError, match="library owner"):
        save_game_columns(form, NO_MIRROR)

    assert Game.objects.get(pk=game.pk).library_id == owned_library.pk


def test_a_game_removed_while_it_was_being_edited_stays_removed(owned_library):
    """A save writes every column, `removed_at` among them.

    The form read this Game while it was live, so a plain save would
    put it back with no event saying so. Edit Game answers a removed
    Game with a 404, thus the window is inside one request; the guard
    is here because the write is here.
    """
    game = Game.objects.create(library=owned_library, name="Elite")
    form = game_form(library=owned_library, instance=game, name="Elite II")
    assert form.is_valid(), form.errors
    remove(game)

    with pytest.raises(ValidationError, match="removed while you were editing"):
        save_game_columns(form, NO_MIRROR)

    stored = Game.objects.get(pk=game.pk)
    assert stored.removed_at is not None
    assert stored.name == "Elite"


def test_a_game_removed_while_it_was_being_edited_answers_the_form(
    owned_library, game_post
):
    """The guard is a sentence on the form, not a 500."""
    game = Game.objects.create(library=owned_library, name="Elite")
    form = game_form(library=owned_library, instance=game, name="Elite II")
    graph = CatalogGraphForm(
        game_post("Elite II"),
        game=game,
        library=owned_library,
        presentation=PRESENTATION,
    )
    references = ReferenceSetForm(
        {"reference_wikidata": ""}, target=game, library=owned_library
    )
    assert form.is_valid(), form.errors
    assert graph.is_valid(), graph.form_errors
    assert references.is_valid(), references.errors
    remove(game)

    assert submitted_game_or_form_error(form, graph, references) is None
    assert REMOVED_SINCE_READ in form.non_field_errors()


def test_a_private_game_needs_a_library_owner(owned_library):
    form = game_form(library=owned_library, name="Elite")
    assert form.is_valid(), form.errors
    form.instance.library = None

    with pytest.raises(ValidationError, match="requires a library owner"):
        save_game_columns(form, NO_MIRROR)

    assert not Game.objects.filter(name="Elite").exists()


def test_a_graph_statement_writes_no_wikidata_reference(owned_library, stated_graph):
    """The column travels with the graph; only a submit maps it."""
    graph = stated_graph(
        Game(library=owned_library, name="Durable writer only", wikidata="Q123"),
        owned_library,
    )

    assert graph.game.wikidata == "Q123"
    assert not ExternalReference.objects.filter(game=graph.game).exists()


def test_the_original_date_is_stored_at_the_precision_it_was_typed(owned_library):
    """The column is not editable, thus the form states it by hand."""
    game = saved_columns(
        game_form(
            library=owned_library,
            name="Elite",
            **{temporal_input_name("original_release_date", "start_month"): "9"},
            original="1983",
        )
    )

    assert Game.objects.get(pk=game.pk).original_release_date == (
        TemporalValue.from_month(1983, 9)
    )


def test_the_original_date_can_be_cleared(owned_library):
    game = saved_columns(game_form(library=owned_library, name="Elite"))

    saved_columns(
        game_form(
            library=owned_library, instance=Game.objects.get(pk=game.pk), original=""
        )
    )

    assert Game.objects.get(pk=game.pk).original_release_date is None
