"""The abstract base a projection table inherits, and the check that keeps a
projected row a pure function of the events.

Every model here is declared under `isolate_apps("games")`: an un-isolated
`app_label = "games"` model would join the global registry for the rest of the
process, where `games/identity_audit.py` would find it and
`tests/test_uuid_identity_audit.py` would fail on a set it never expected.
"""

import uuid

from django.core.checks import CheckMessage
from django.db import models
from django.test.utils import isolate_apps

from games.checks import check_projection_models
from games.models import ProjectionModel


def error_ids(messages: list[CheckMessage]) -> list[str]:
    return sorted(str(message.id) for message in messages)


def check(model: type[models.Model]) -> list[str]:
    """The check, run over the registry the model was declared in.

    `isolate_apps` patches `Options.default_apps` and leaves the global
    registry alone, so a check hard-wired to `django.apps.apps` would look at
    none of these models and pass vacuously.
    """
    return error_ids(check_projection_models(apps=model._meta.apps))


@isolate_apps("games")
def test_an_event_derived_projection_passes():
    class Conforming(ProjectionModel):
        id = models.UUIDField(primary_key=True)
        title = models.CharField(max_length=64)
        recorded_at = models.DateTimeField()
        finished_at = models.DateTimeField(null=True)

        class Meta:
            app_label = "games"

    assert check(Conforming) == []


@isolate_apps("games")
def test_auto_now_is_refused():
    class Touched(ProjectionModel):
        id = models.UUIDField(primary_key=True)
        updated_at = models.DateTimeField(auto_now=True)

        class Meta:
            app_label = "games"

    assert check(Touched) == ["games.E001"]


@isolate_apps("games")
def test_auto_now_add_is_refused():
    class Stamped(ProjectionModel):
        id = models.UUIDField(primary_key=True)
        created_at = models.DateTimeField(auto_now_add=True)

        class Meta:
            app_label = "games"

    assert check(Stamped) == ["games.E002"]


@isolate_apps("games")
def test_an_implicit_auto_field_primary_key_is_refused():
    class Counted(ProjectionModel):
        title = models.CharField(max_length=64)

        class Meta:
            app_label = "games"

    #: The shadow table's LIKE copy gets its own identity sequence starting at
    #: 1, so an auto-increment key diffs every unchanged row as a deletion and
    #: an insertion, forever.
    assert check(Counted) == ["games.E003"]


@isolate_apps("games")
def test_an_explicit_auto_field_primary_key_is_refused():
    class Numbered(ProjectionModel):
        id = models.BigAutoField(primary_key=True)

        class Meta:
            app_label = "games"

    assert check(Numbered) == ["games.E003"]


@isolate_apps("games")
def test_a_database_default_is_refused():
    class Defaulted(ProjectionModel):
        id = models.UUIDField(primary_key=True)
        rank = models.IntegerField(db_default=0)

        class Meta:
            app_label = "games"

    #: PostgreSQL copies the default onto the shadow and evaluates it there
    #: independently.
    assert check(Defaulted) == ["games.E004"]


@isolate_apps("games")
def test_a_uuid_module_default_is_refused():
    class Minted(ProjectionModel):
        id = models.UUIDField(primary_key=True, default=uuid.uuid4)

        class Meta:
            app_label = "games"

    assert check(Minted) == ["games.E005"]


@isolate_apps("games")
def test_the_repos_uuidv7_field_is_refused_on_both_counts():
    """`UUIDv7Field` carries a `uuid.uuid7` default and a `uuidv7()` database
    default, so the trap is one field declaration away."""
    from timetracker.uuidv7 import UUIDv7Field

    class Identified(ProjectionModel):
        id = UUIDv7Field(primary_key=True)

        class Meta:
            app_label = "games"

    assert check(Identified) == ["games.E004", "games.E005"]


@isolate_apps("games")
def test_a_rule_broken_by_an_intermediate_abstract_base_is_still_caught():
    class TimestampedProjection(ProjectionModel):
        id = models.UUIDField(primary_key=True)
        updated_at = models.DateTimeField(auto_now=True)

        class Meta:
            abstract = True

    class Inheriting(TimestampedProjection):
        class Meta:
            app_label = "games"

    #: Abstract inheritance copies the field into the concrete model, so
    #: `local_fields` sees it. That is the property being pinned.
    assert check(Inheriting) == ["games.E001"]


@isolate_apps("games")
def test_an_unmanaged_twin_is_not_checked():
    class Live(ProjectionModel):
        id = models.UUIDField(primary_key=True)

        class Meta:
            app_label = "games"

    class Shadow(ProjectionModel):
        id = models.UUIDField(primary_key=True)
        updated_at = models.DateTimeField(auto_now=True)

        class Meta:
            app_label = "games"
            managed = False
            db_table = "games_live__shadow"

    #: The manufactured twins are `managed = False` and carry the live model's
    #: fields; checking them would report every live offence twice.
    assert check(Live) == []


@isolate_apps("games")
def test_a_conventional_model_is_not_checked():
    class Conventional(models.Model):
        updated_at = models.DateTimeField(auto_now=True)

        class Meta:
            app_label = "games"

    assert check(Conventional) == []
