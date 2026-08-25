"""The projection base and its purity check."""

import uuid

from django.core.checks import CheckMessage
from django.db import models
from django.test.utils import isolate_apps

from games.checks import check_projection_models
from games.models import ProjectionModel


def error_ids(messages: list[CheckMessage]) -> list[str]:
    return sorted(str(message.id) for message in messages)


def check(model: type[models.Model]) -> list[str]:
    """The check over the model's own registry."""
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

    #: The shadow gets its own identity sequence.
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

    #: The shadow evaluates the copied default itself.
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
    """The trap is one field declaration away."""
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

    #: The copied field lands in `local_fields`.
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

    #: A twin would report each offence twice.
    assert check(Live) == []


@isolate_apps("games")
def test_a_conventional_model_is_not_checked():
    class Conventional(models.Model):
        updated_at = models.DateTimeField(auto_now=True)

        class Meta:
            app_label = "games"

    assert check(Conventional) == []
