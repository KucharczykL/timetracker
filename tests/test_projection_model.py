"""The projection base and its purity check."""

import datetime
import itertools
import uuid

from django.apps import apps as global_apps
from django.core.checks import CheckMessage
from django.db import models
from django.test.utils import isolate_apps
from django.utils import timezone

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
def test_a_clock_default_is_refused():
    class Stamped(ProjectionModel):
        id = models.UUIDField(primary_key=True)
        seen_at = models.DateTimeField(default=timezone.now)

        class Meta:
            app_label = "games"

    #: A rebuild evaluates it again, at rebuild time.
    assert check(Stamped) == ["games.E006"]


@isolate_apps("games")
def test_a_constant_default_is_allowed():
    class Fixed(ProjectionModel):
        id = models.UUIDField(primary_key=True)
        origin = models.UUIDField(default=uuid.UUID(int=1))
        status = models.CharField(max_length=9, default="unplayed")
        mastered = models.BooleanField(default=False)
        archived_at = models.DateTimeField(null=True, default=None)

        class Meta:
            app_label = "games"

    #: A constant reproduces itself, whatever its module.
    assert check(Fixed) == []


@isolate_apps("games")
def test_an_empty_container_default_is_allowed():
    """The idiom Django asks for."""

    class Collected(ProjectionModel):
        id = models.UUIDField(primary_key=True)
        tags = models.JSONField(default=dict)
        history = models.JSONField(default=list)

        class Meta:
            app_label = "games"

    assert check(Collected) == []


@isolate_apps("games")
def test_a_callable_default_of_another_kind_is_refused():
    """The rest, beyond E005 and E006."""

    ranks = itertools.count()

    def next_rank() -> int:
        return next(ranks)

    class Ranked(ProjectionModel):
        id = models.UUIDField(primary_key=True)
        rank = models.IntegerField(default=next_rank)

        class Meta:
            app_label = "games"

    assert check(Ranked) == ["games.E007"]


@isolate_apps("games")
def test_a_wrapped_clock_default_is_refused():
    """The hole E006's own hint admitted to."""

    def when() -> datetime.datetime:
        return timezone.now()

    class Wrapped(ProjectionModel):
        id = models.UUIDField(primary_key=True)
        seen_at = models.DateTimeField(default=when)

        class Meta:
            app_label = "games"

    assert check(Wrapped) == ["games.E007"]


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


#: Every constant a projection column starts at.
PINNED_DEFAULTS: dict[str, dict[str, object]] = {
    "games.PlayerGame": {
        "status": "unplayed",
        "mastered": False,
        "excluded_from_unfinished": False,
        "archived_at": None,
    },
}


def test_every_projection_default_is_pinned():
    """A change to a default is reviewed."""
    found = {
        model._meta.label: {
            field.name: field.default
            for field in model._meta.concrete_fields
            if field.has_default()
        }
        for model in global_apps.get_models()
        if issubclass(model, ProjectionModel) and model._meta.managed
    }

    assert {label: columns for label, columns in found.items() if columns} == (
        PINNED_DEFAULTS
    )


@isolate_apps("games")
def test_a_conventional_model_is_not_checked():
    class Conventional(models.Model):
        updated_at = models.DateTimeField(auto_now=True)

        class Meta:
            app_label = "games"

    assert check(Conventional) == []
