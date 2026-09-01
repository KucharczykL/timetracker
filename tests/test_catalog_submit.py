"""One submit of the Game form: one transaction, one creator."""

from unittest.mock import patch

import pytest
from django.db import IntegrityError
from django.urls import reverse

from games.catalog_compat import LEGACY_IDENTITY_TAKEN, mirror_legacy_columns
from games.catalog_submit import (
    CONSTRAINT_ANSWERS,
    RACED,
    UNREACHABLE_FROM_THE_GAME_FORM,
    WIKIDATA_CONFLICT_MESSAGE,
    answered_constraint,
)
from games.models import Edition, ExternalReference, Game, Release
from timetracker.temporal import TemporalValue, temporal_input_name

pytestmark = pytest.mark.django_db(transaction=True)


def game_post(name: str, **extra: str) -> dict[str, str]:
    """The Game form's own fields, beside the Editions area."""
    posted = {
        "name": name,
        "sort_name": "",
        "wikidata": "",
        "status": "unplayed",
        "editions-count": "1",
        "edition-0-name": "",
        "edition-0-releases-count": "1",
        "edition-0-release-0-platform": "",
        "in_library": "edition-0-release-0",
    }
    posted.update(extra)
    return posted


def test_a_refused_graph_takes_the_renamed_game_back(client, owned_user, stated_graph):
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
    client, owned_user, stated_graph
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


def test_add_game_leaves_exactly_one_edition_and_one_release(client, owned_user):
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


def test_a_game_with_no_graph_can_be_edited(client, owned_user):
    """What the backfill leaves: a Game nothing ever wrote a graph for."""
    client.force_login(owned_user)
    game = Game.objects.create(library=owned_user.library, name="Stranded")

    response = client.post(
        reverse("games:edit_game", args=[game.pk]), data=game_post("Stranded")
    )

    assert response.status_code == 302
    assert Edition.objects.alive().filter(game=game).count() == 1


def test_a_taken_legacy_identity_lands_on_the_game_form(
    client, owned_user, stated_graph
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


def test_a_taken_wikidata_id_lands_on_the_wikidata_field(
    client, owned_user, stated_graph
):
    client.force_login(owned_user)
    twin = stated_graph(
        Game(library=owned_user.library, name="Twin"), owned_user.library
    )
    ExternalReference.objects.create(
        provider="wikidata",
        entity_kind="game",
        provider_key="Q42",
        game=twin.game,
    )
    graph = stated_graph(
        Game(library=owned_user.library, name="Elite"), owned_user.library
    )
    posted = game_post("Elite", wikidata="Q42")
    posted["edition-0-edition_id"] = str(graph.edition.pk)
    posted["edition-0-release-0-release_id"] = str(graph.release.pk)

    response = client.post(
        reverse("games:edit_game", args=[graph.game.pk]), data=posted
    )

    assert response.status_code == 200
    assert WIKIDATA_CONFLICT_MESSAGE in response.content.decode()


def test_a_race_the_pre_check_missed_answers_in_words(client, owned_user, stated_graph):
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


def test_the_wikidata_constraint_names_its_own_field():
    answer = answered_constraint(
        collision("unique_external_reference_provider_kind_key")
    )

    assert answer == (WIKIDATA_CONFLICT_MESSAGE, "wikidata")


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
