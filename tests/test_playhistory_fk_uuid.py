import uuid
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from common.criteria import FilterQueryContext, Modifier, RelationMatch, StringCriterion
from common.date_time_presentation import (
    DEFAULT_DATE_TIME_FORMAT_PROFILE,
    DateTimePresentation,
)
from games.filters import GameFilter, PlayEventFilter
from games.forms import PlayEventForm
from games.models import Game, GameStatusChange, PlayEvent

PRESENTATION = DateTimePresentation(
    DEFAULT_DATE_TIME_FORMAT_PROFILE, "en-us", ZoneInfo("UTC")
)

UNRESTRICTED_FILTER_CONTEXT = FilterQueryContext(
    lambda model: model._default_manager.all()
)

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE_FK_UUID = ("games", "0008_library_config_uuid_identity")
WITH_FK_UUID = ("games", "0009_playhistory_game_uuid_fk")


# --- Migration harness -------------------------------------------------------


@pytest.fixture
def fk_uuid_harness():
    # Migrating down to BEFORE_FK_UUID unapplies every later migration too, so
    # the restore target is the graph's leaf nodes rather than WITH_FK_UUID,
    # which would strand this worker's shared database behind head for every
    # later test that reuses it.
    leaf_nodes = MigrationExecutor(connection).loader.graph.leaf_nodes()
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_FK_UUID])
    call_command("flush", interactive=False, verbosity=0)
    old_apps = executor.loader.project_state([BEFORE_FK_UUID]).apps
    yield old_apps
    MigrationExecutor(connection).migrate(leaf_nodes)


def migrate_to_fk_uuid():
    executor = MigrationExecutor(connection)
    executor.migrate([WITH_FK_UUID])
    return executor.loader.project_state([WITH_FK_UUID]).apps


def seed_owned_games(apps, *, username: str, count: int):
    User = apps.get_model("auth", "User")
    UserLibrary = apps.get_model("games", "UserLibrary")
    Game = apps.get_model("games", "Game")
    user = User.objects.create(username=username)
    library = UserLibrary.objects.create(user_id=user.pk, created_at=timezone.now())
    return [
        Game.objects.create(library_id=library.pk, name=f"Historic Game {index}")
        for index in range(count)
    ]


def column_type(table_name: str, column_name: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT domain_name FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            """,
            [table_name, column_name],
        )
        row = cursor.fetchone()
    assert row is not None, f"{table_name}.{column_name} does not exist"
    return row[0]


def foreign_key_target(table_name: str, column_name: str) -> tuple[str, str] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ccu.table_name, ccu.column_name
            FROM information_schema.table_constraints AS constraint_row
            JOIN information_schema.key_column_usage AS key_usage
                ON key_usage.constraint_name = constraint_row.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = constraint_row.constraint_name
            WHERE constraint_row.table_name = %s
                AND constraint_row.constraint_type = 'FOREIGN KEY'
                AND key_usage.column_name = %s
            """,
            [table_name, column_name],
        )
        row = cursor.fetchone()
    return tuple(row) if row is not None else None


# --- Migration: forward -------------------------------------------------------


def test_forward_migration_repoints_playevent_and_gamestatuschange_to_game_uuid(
    fk_uuid_harness, capsys
):
    apps = fk_uuid_harness
    first_game, second_game = seed_owned_games(apps, username="fk-uuid-owner", count=2)
    PlayEvent = apps.get_model("games", "PlayEvent")
    GameStatusChange = apps.get_model("games", "GameStatusChange")

    playevent_on_first = PlayEvent.objects.create(game_id=first_game.pk)
    playevent_on_second = PlayEvent.objects.create(game_id=second_game.pk)
    status_change = GameStatusChange.objects.create(
        game_id=first_game.pk, new_status="p", timestamp=timezone.now()
    )

    new_apps = migrate_to_fk_uuid()
    NewGame = new_apps.get_model("games", "Game")
    NewPlayEvent = new_apps.get_model("games", "PlayEvent")
    NewGameStatusChange = new_apps.get_model("games", "GameStatusChange")

    assert (
        NewPlayEvent.objects.get(pk=playevent_on_first.pk).game.name
        == "Historic Game 0"
    )
    assert (
        NewPlayEvent.objects.get(pk=playevent_on_second.pk).game.name
        == "Historic Game 1"
    )
    assert (
        NewGameStatusChange.objects.get(pk=status_change.pk).game.name
        == "Historic Game 0"
    )
    assert (
        NewPlayEvent.objects.get(pk=playevent_on_first.pk).game_id
        == NewGame.objects.get(pk=first_game.pk).uuid
    )

    assert column_type("games_playevent", "game_id") == "uuid_v7"
    assert column_type("games_gamestatuschange", "game_id") == "uuid_v7"
    assert foreign_key_target("games_playevent", "game_id") == ("games_game", "uuid")
    assert foreign_key_target("games_gamestatuschange", "game_id") == (
        "games_game",
        "uuid",
    )

    output = capsys.readouterr().out
    assert "FK identity rewritten" in output
    assert "playevent_rows=2 playevent_games=2" in output
    assert "gamestatuschange_rows=1 gamestatuschange_games=1" in output
    assert "unmatched=0" in output


# --- Migration: reverse -------------------------------------------------------


def test_reverse_migration_restores_the_original_integer_game_id(fk_uuid_harness):
    apps = fk_uuid_harness
    (game,) = seed_owned_games(apps, username="fk-uuid-reverse-owner", count=1)
    PlayEvent = apps.get_model("games", "PlayEvent")
    GameStatusChange = apps.get_model("games", "GameStatusChange")

    playevent = PlayEvent.objects.create(game_id=game.pk)
    status_change = GameStatusChange.objects.create(
        game_id=game.pk, new_status="p", timestamp=timezone.now()
    )

    migrate_to_fk_uuid()

    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE_FK_UUID])
    reverted_apps = executor.loader.project_state([BEFORE_FK_UUID]).apps

    RevertedPlayEvent = reverted_apps.get_model("games", "PlayEvent")
    RevertedGameStatusChange = reverted_apps.get_model("games", "GameStatusChange")

    assert RevertedPlayEvent.objects.get(pk=playevent.pk).game_id == game.pk
    assert RevertedGameStatusChange.objects.get(pk=status_change.pk).game_id == game.pk
    assert "game_uuid" not in [
        field.name for field in RevertedPlayEvent._meta.get_fields()
    ]
    assert "game_uuid" not in [
        field.name for field in RevertedGameStatusChange._meta.get_fields()
    ]


# --- ORM behavior (current schema) -------------------------------------------


@pytest.fixture
def game(owned_library):
    return Game.objects.create(library=owned_library, name="FK Identity Subject")


def test_playevent_game_id_reads_back_as_the_games_uuid(game):
    playevent = PlayEvent.objects.create(game=game)
    assert playevent.game_id == game.uuid


def test_gamestatuschange_game_id_reads_back_as_the_games_uuid(game):
    change = GameStatusChange.objects.create(
        game=game, new_status="p", timestamp=timezone.now()
    )
    assert change.game_id == game.uuid


def test_playevent_filters_by_game_instance(game, owned_library):
    other_game = Game.objects.create(library=owned_library, name="Other")
    matching = PlayEvent.objects.create(game=game)
    PlayEvent.objects.create(game=other_game)
    assert list(PlayEvent.objects.filter(game=game)) == [matching]


def test_playevent_filters_by_game_integer_id(game, owned_library):
    other_game = Game.objects.create(library=owned_library, name="Other")
    matching = PlayEvent.objects.create(game=game)
    PlayEvent.objects.create(game=other_game)
    assert list(PlayEvent.objects.filter(game__id=game.id)) == [matching]


def test_game_reverse_accessors_expose_playevents_and_status_changes(game):
    playevent = PlayEvent.objects.create(game=game)
    change = GameStatusChange.objects.create(
        game=game, new_status="p", timestamp=timezone.now()
    )
    assert list(game.playevents.all()) == [playevent]
    assert list(game.status_changes.all()) == [change]


def test_deleting_a_game_cascades_to_playevents_and_status_changes(game):
    playevent = PlayEvent.objects.create(game=game)
    change = GameStatusChange.objects.create(
        game=game, new_status="p", timestamp=timezone.now()
    )
    game.delete()
    assert not PlayEvent.objects.filter(pk=playevent.pk).exists()
    assert not GameStatusChange.objects.filter(pk=change.pk).exists()


def test_database_rejects_a_playevent_referencing_a_uuid_no_game_owns():
    with pytest.raises(IntegrityError), transaction.atomic():
        PlayEvent.objects.create(game_id=uuid.uuid7())


def test_database_rejects_a_gamestatuschange_referencing_a_uuid_no_game_owns():
    with pytest.raises(IntegrityError), transaction.atomic():
        GameStatusChange.objects.create(
            game_id=uuid.uuid7(), new_status="p", timestamp=timezone.now()
        )


# --- Filters (integer criterion values, one join deeper) --------------------


def test_playeventfilter_game_criterion_selects_the_right_rows(game, owned_library):
    other_game = Game.objects.create(library=owned_library, name="Other")
    matching = PlayEvent.objects.create(game=game)
    PlayEvent.objects.create(game=other_game)

    filter_ = PlayEventFilter.where(game=[game.id])
    results = PlayEvent.objects.filter(filter_.to_q(UNRESTRICTED_FILTER_CONTEXT))
    assert list(results) == [matching]


def test_gamefilter_playevent_filter_any_selects_games_with_a_matching_playevent(
    game, owned_library
):
    other_game = Game.objects.create(library=owned_library, name="Other")
    PlayEvent.objects.create(game=game, note="Marathon session")
    PlayEvent.objects.create(game=other_game, note="Something else")

    filter_ = GameFilter(
        playevent_filter=PlayEventFilter(
            note=StringCriterion(value="Marathon", modifier=Modifier.INCLUDES),
        )
    )
    results = Game.objects.filter(library=owned_library).filter(
        filter_.to_q(UNRESTRICTED_FILTER_CONTEXT)
    )
    assert list(results) == [game]


def test_gamefilter_playevent_filter_none_excludes_games_with_a_matching_playevent(
    game, owned_library
):
    other_game = Game.objects.create(library=owned_library, name="Other")
    PlayEvent.objects.create(game=game, note="Marathon session")

    filter_ = GameFilter(
        playevent_filter=PlayEventFilter(
            note=StringCriterion(value="Marathon", modifier=Modifier.INCLUDES),
            match=RelationMatch.NONE,
        )
    )
    results = Game.objects.filter(library=owned_library).filter(
        filter_.to_q(UNRESTRICTED_FILTER_CONTEXT)
    )
    assert list(results) == [other_game]


def test_gamefilter_playevent_filter_all_requires_every_playevent_to_match(
    game, owned_library
):
    other_game = Game.objects.create(library=owned_library, name="Other")
    PlayEvent.objects.create(game=game, note="Marathon session")
    PlayEvent.objects.create(game=other_game, note="Marathon session")
    PlayEvent.objects.create(game=other_game, note="Something else")

    filter_ = GameFilter(
        playevent_filter=PlayEventFilter(
            note=StringCriterion(value="Marathon", modifier=Modifier.INCLUDES),
            match=RelationMatch.ALL,
        )
    )
    results = Game.objects.filter(library=owned_library).filter(
        filter_.to_q(UNRESTRICTED_FILTER_CONTEXT)
    )
    assert list(results) == [game]


def test_playeventfilter_game_filter_selects_playevents_for_matching_games(
    game, owned_library
):
    other_game = Game.objects.create(library=owned_library, name="Other")
    matching = PlayEvent.objects.create(game=game)
    PlayEvent.objects.create(game=other_game)

    filter_ = PlayEventFilter(
        game_filter=GameFilter(name=StringCriterion(value=game.name)),
    )
    results = PlayEvent.objects.filter(filter_.to_q(UNRESTRICTED_FILTER_CONTEXT))
    assert list(results) == [matching]


# --- Form initial-value shim -------------------------------------------------


def test_playeventform_preselects_the_games_integer_id_when_editing(
    game, owned_library
):
    playevent = PlayEvent.objects.create(game=game)

    form = PlayEventForm(
        instance=playevent, library=owned_library, presentation=PRESENTATION
    )

    assert form.initial["game"] == game
    assert form.fields["game"].prepare_value(form.initial["game"]) == game.pk


def test_playeventform_posting_an_integer_game_id_saves_the_right_game(
    game, owned_library
):
    playevent = PlayEvent.objects.create(game=game)
    other_game = Game.objects.create(library=owned_library, name="Retarget")

    form = PlayEventForm(
        data={
            "game": str(other_game.pk),
            "started": "",
            "ended": "",
            "note": "",
        },
        instance=playevent,
        library=owned_library,
        presentation=PRESENTATION,
    )

    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.game_id == other_game.uuid
