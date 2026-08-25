"""A shadow twin of a projection model."""

from django.core.checks import run_checks
from django.db import models
from django.db.models.fields.generated import GeneratedField
from django.test.utils import isolate_apps

from games.events.targets import LIVE_TARGET, SHADOW_SUFFIX, ShadowTarget
from games.models import ProjectionModel

SHELF_TABLE = "test_projection_shelf"
ENTRY_TABLE = "test_projection_entry"


def declare_projection_models() -> tuple[type[ProjectionModel], type[ProjectionModel]]:
    """Parent and child tables; `UserLibrary` prevents `fields.E300`."""

    class UserLibrary(models.Model):
        id = models.UUIDField(primary_key=True)

        class Meta:
            app_label = "games"
            db_table = "games_userlibrary"

    class Shelf(ProjectionModel):
        id = models.UUIDField(primary_key=True)
        title = models.CharField(max_length=64)
        note = models.TextField(null=True)
        played_seconds = models.IntegerField(default=0)
        played_minutes = GeneratedField(
            expression=models.F("played_seconds") / 60,
            output_field=models.IntegerField(),
            db_persist=True,
        )

        class Meta:
            app_label = "games"
            db_table = SHELF_TABLE

    class Entry(ProjectionModel):
        id = models.UUIDField(primary_key=True)
        shelf = models.ForeignKey(
            Shelf, on_delete=models.CASCADE, related_name="entries"
        )
        position = models.IntegerField()

        class Meta:
            app_label = "games"
            db_table = ENTRY_TABLE

    return Shelf, Entry


def field_names(model: type[models.Model]) -> list[str]:
    return [field.name for field in model._meta.concrete_fields]


@isolate_apps("games")
def test_a_twin_carries_the_live_fields_under_a_shadow_table():
    shelf, _ = declare_projection_models()

    twin = ShadowTarget().model(shelf)

    assert twin is not shelf
    assert twin._meta.db_table == f"{SHELF_TABLE}{SHADOW_SUFFIX}"
    assert twin._meta.managed is False
    assert field_names(twin) == field_names(shelf)
    assert twin._meta.pk is not None
    assert twin._meta.pk.name == "id"


@isolate_apps("games")
def test_a_twin_lands_in_the_registry_its_live_model_came_from():
    shelf, _ = declare_projection_models()

    twin = ShadowTarget().model(shelf)

    #: A twin must not outlive its test.
    assert twin._meta.apps is shelf._meta.apps


@isolate_apps("games")
def test_one_twin_is_manufactured_per_live_model():
    shelf, entry = declare_projection_models()
    target = ShadowTarget()

    assert target.model(shelf) is target.model(shelf)
    #: A redefined twin would displace the first.
    assert ShadowTarget().model(shelf) is target.model(shelf)
    assert target.model(entry) is not target.model(shelf)


@isolate_apps("games")
def test_the_live_target_hands_back_the_live_model():
    shelf, _ = declare_projection_models()

    assert LIVE_TARGET.model(shelf) is shelf


@isolate_apps("games")
def test_manufacturing_a_twin_leaves_every_check_clean():
    """The `fields.E304` regression, pinned."""
    shelf, entry = declare_projection_models()
    target = ShadowTarget()

    shelf_twin = target.model(shelf)
    entry_twin = target.model(entry)

    assert shelf.check() == []
    assert entry.check() == []
    assert shelf_twin.check() == []
    assert entry_twin.check() == []
    assert run_checks() == []


@isolate_apps("games")
def test_a_twins_relations_hide_their_reverse_accessors():
    _, entry = declare_projection_models()

    twin = ShadowTarget().model(entry)

    #: A deep copy would cache `hidden` False.
    assert twin._meta.get_field("shelf").remote_field.hidden is True
    assert twin._meta.get_field("library").remote_field.hidden is True


@isolate_apps("games")
def test_a_generated_column_survives_onto_the_twin():
    shelf, _ = declare_projection_models()

    twin = ShadowTarget().model(shelf)

    generated = twin._meta.get_field("played_minutes")
    assert isinstance(generated, GeneratedField)
    assert generated.db_persist is True
