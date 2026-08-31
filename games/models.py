import logging
from datetime import timedelta
from typing import TYPE_CHECKING, ClassVar, Final
from uuid import UUID

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import (
    Case,
    Exists,
    ExpressionWrapper,
    F,
    FilteredRelation,
    Func,
    OuterRef,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.fields.generated import GeneratedField
from django.db.models.functions import Coalesce, Lower, NullIf, Trim
from django.template.defaultfilters import floatformat, pluralize, slugify
from django.urls import reverse
from django.utils import timezone

from common.duration_presentation import format_decimal_hours
from common.utils import label_with_details
from games.external_references import external_reference_url, normalize_provider_key
from timetracker.settings_registry import THEME_CHOICES, SettingKey
from timetracker.temporal import (
    TemporalEndKind,
    TemporalEndPrecision,
    TemporalEndQualifier,
    TemporalKind,
    TemporalLowerBound,
    TemporalPrecisionValue,
    TemporalQualifierValue,
    TemporalStartKind,
    TemporalStartPrecision,
    TemporalStartQualifier,
    TemporalUpperBound,
    TemporalValueField,
)
from timetracker.uuidv7 import UUIDv7Field

logger = logging.getLogger("games")


class LibraryOwnedQuerySet(models.QuerySet):
    def for_library(self, library):
        return self.filter(library=library)


class RemovableMixin:
    """The row stays; the reads skip it.

    `alive()` asks about this row and about every row named in
    `ancestor_marks`, because a catalog child sits under rows that
    hold a mark of their own. A queryset states the path once, thus
    a new level between two models is one edit.

    A mixin rather than a queryset: two queryset bases give
    django-stubs two `as_manager` return types to disagree over.
    """

    #: Paths to the rows whose removal also hides this one.
    ancestor_marks: tuple[str, ...] = ()

    def alive(self):
        conditions = {"removed_at__isnull": True} | {
            f"{path}__removed_at__isnull": True for path in self.ancestor_marks
        }
        return self.filter(**conditions)


class RemovableLibraryQuerySet(RemovableMixin, LibraryOwnedQuerySet):
    """A library-owned row a user can remove.

    `for_library` and `visible_to` are how the application asks for
    rows. A caller that must see removed rows uses the plain manager.
    """

    def for_library(self, library):
        return super().for_library(library).alive()


class ReferencedRow(models.Model):
    """A row an event may name."""

    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        #: The policy runs before the collector.
        #:
        #: `Model.delete()` collects before it sends `pre_delete`, so a
        #: RESTRICT relation would refuse first and say only which foreign key
        #: held the row. The receiver stays the backstop for the paths that
        #: never reach here: a queryset delete and a cascade.
        from games.retention import refuse_to_delete_a_referenced_row

        refuse_to_delete_a_referenced_row(self)
        return super().delete(*args, **kwargs)


class GameQuerySet(RemovableLibraryQuerySet):
    def visible_to(self, library):
        return self.filter(Q(library__isnull=True) | Q(library=library)).alive()

    def annotated_for_filtering(self, library=None):
        """Register the alias only; drop no row.

        A filter names `tracked__status`, which needs the alias and
        nothing else. The two facts are selected by `tracked_by()`
        after it filters, because an F() before the filter opens a
        second join Django cannot merge.

        No library leaves the join unconditional, so a game two
        libraries track comes back once per library. Unscoped is for
        compiling a lookup, not for executing one.
        """
        condition = Q() if library is None else Q(player_games__library=library)
        return self.annotate(
            tracked=FilteredRelation("player_games", condition=condition)
        )

    def tracked_by(self, library, **conditions):
        """Every live game this library tracks, facts read.

        No `library=library`: a shared catalog game this library
        tracks belongs on the list.

        Extra conditions ride in that same filter() call.

        A FilteredRelation, not a plain path. Django opens a join per
        filter() call on a multi-valued relation, and a list applies
        its scope and its criteria in separate calls; on a plain path
        the second join carries no library condition. The alias
        copies its condition into every join, and
        `unique_library_player_game` allows one row per pair, so the
        joins cannot disagree.

        `alive()` comes first: since #676 a game delete leaves the
        catalog row removed and the projection row beside it.

        A removed row is not tracked. TrackGame refuses to track a
        removed game again, so a game the list still showed could not
        be got rid of.
        """
        return (
            self.alive()
            .annotated_for_filtering(library)
            .filter(
                tracked__isnull=False,
                tracked__removed_at__isnull=True,
                **conditions,
            )
            .annotate(
                tracked_status=F("tracked__status"),
                tracked_mastered=F("tracked__mastered"),
            )
        )


def _validate_related_library(
    owner_library_id, related, field_name: str, *, allow_shared: bool = False
):
    if related is None:
        return
    related_library_id = related.library_id
    if allow_shared and related_library_id is None:
        return
    if related_library_id != owner_library_id:
        raise ValidationError(
            {
                field_name: (
                    f"{related._meta.verbose_name.title()} belongs to another library."
                )
            }
        )


class Game(ReferencedRow):
    if TYPE_CHECKING:
        #: Annotations, not columns: GameQuerySet.tracked_by() puts the
        #: library's two projection facts here, and only a queryset from
        #: it carries them.
        tracked_status: str
        tracked_mastered: bool

    class Meta:
        #: Both partial on `removed_at`.
        #: A removed name is free again.
        #: `unique_together` cannot carry a condition.
        constraints = (
            models.UniqueConstraint(
                fields=("library", "name", "platform", "year_released"),
                condition=Q(removed_at__isnull=True),
                name="unique_library_game_name_platform_year",
            ),
            models.UniqueConstraint(
                fields=("library", "name", "year_released"),
                condition=Q(platform__isnull=True) & Q(removed_at__isnull=True),
                name="unique_library_platformless_game_name_year",
            ),
        )

    objects = GameQuerySet.as_manager()

    library = models.ForeignKey(
        "UserLibrary",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        default=None,
        related_name="games",
    )
    id = UUIDv7Field(primary_key=True, editable=False)
    name = models.CharField(max_length=255)
    sort_name = models.CharField(max_length=255, blank=True, default="")
    year_released = models.IntegerField(null=True, blank=True, default=None)
    original_year_released = models.IntegerField(null=True, blank=True, default=None)
    original_release_date = TemporalValueField()
    original_release_date_lower = models.GeneratedField(
        expression=TemporalLowerBound("original_release_date"),
        output_field=models.DateField(null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    original_release_date_upper = models.GeneratedField(
        expression=TemporalUpperBound("original_release_date"),
        output_field=models.DateField(null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    original_release_date_kind = models.GeneratedField(
        expression=TemporalKind("original_release_date"),
        output_field=models.CharField(max_length=7),
        serialize=False,
        db_persist=True,
        editable=False,
    )
    original_release_date_precision = models.GeneratedField(
        expression=TemporalPrecisionValue("original_release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    original_release_date_start_kind = models.GeneratedField(
        expression=TemporalStartKind("original_release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    original_release_date_end_kind = models.GeneratedField(
        expression=TemporalEndKind("original_release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    original_release_date_start_precision = models.GeneratedField(
        expression=TemporalStartPrecision("original_release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    original_release_date_end_precision = models.GeneratedField(
        expression=TemporalEndPrecision("original_release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    original_release_date_qualifier = models.GeneratedField(
        expression=TemporalQualifierValue("original_release_date"),
        output_field=models.CharField(max_length=11, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    original_release_date_start_qualifier = models.GeneratedField(
        expression=TemporalStartQualifier("original_release_date"),
        output_field=models.CharField(max_length=11, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    original_release_date_end_qualifier = models.GeneratedField(
        expression=TemporalEndQualifier("original_release_date"),
        output_field=models.CharField(max_length=11, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    wikidata = models.CharField(max_length=50, blank=True, default="")
    platform = models.ForeignKey(
        "Platform",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
    )

    playtime = models.DurationField(blank=True, editable=False, default=timedelta(0))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    #: Set instead of destroying the row.
    removed_at = models.DateTimeField(
        null=True, blank=True, default=None, editable=False
    )

    class Status(models.TextChoices):
        UNPLAYED = (
            "u",
            "Unplayed",
        )
        PLAYED = (
            "p",
            "Played",
        )
        FINISHED = (
            "f",
            "Finished",
        )
        RETIRED = (
            "r",
            "Retired",
        )
        ABANDONED = (
            "a",
            "Abandoned",
        )

    status = models.CharField(max_length=1, choices=Status, default=Status.UNPLAYED)
    mastered = models.BooleanField(default=False)

    def clean(self):
        super().clean()
        if self.platform_id is not None:
            _validate_related_library(
                self.library_id,
                self.platform,
                "platform",
                allow_shared=True,
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @property
    def url_slug(self) -> str:
        return slugify(self.name) or "game"

    def get_absolute_url(self) -> str:
        return reverse(
            "games:view_game",
            kwargs={"game_id": self.pk, "slug": self.url_slug},
        )

    @property
    def search_label(self) -> str:
        # label_with_details drops falsy details, so coalesce NULL platform to
        # the display label — otherwise the segment silently vanishes.
        return label_with_details(
            self.name, self.platform or "Unspecified", self.year_released
        )


class PlatformQuerySet(RemovableLibraryQuerySet):
    def visible_to(self, library):
        return self.filter(Q(library__isnull=True) | Q(library=library)).alive()


class Platform(ReferencedRow):
    class Meta:
        #: Both partial, as on Game.Meta.
        constraints = (
            models.UniqueConstraint(
                Lower(Trim("name")),
                Lower(Trim("group")),
                condition=Q(library__isnull=True) & Q(removed_at__isnull=True),
                name="unique_shared_platform_normalized_name_group",
            ),
            models.UniqueConstraint(
                F("library"),
                Lower(Trim("name")),
                Lower(Trim("group")),
                condition=Q(library__isnull=False) & Q(removed_at__isnull=True),
                name="unique_private_platform_normalized_name_group",
            ),
        )

    objects = PlatformQuerySet.as_manager()

    library = models.ForeignKey(
        "UserLibrary",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        default=None,
        related_name="platforms",
    )
    id = UUIDv7Field(primary_key=True, editable=False)
    name = models.CharField(max_length=255)
    group = models.CharField(max_length=255, blank=True, default="")
    icon = models.SlugField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    #: Set instead of destroying the row.
    removed_at = models.DateTimeField(
        null=True, blank=True, default=None, editable=False
    )

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        duplicates = (
            #: A removed Platform shadows nothing.
            Platform.objects.alive()
            .exclude(pk=self.pk)
            .annotate(
                normalized_name=Lower(Trim("name")),
                normalized_group=Lower(Trim("group")),
            )
            .filter(
                normalized_name=self.name.strip().casefold(),
                normalized_group=self.group.strip().casefold(),
            )
        )
        if self.library_id is None:
            collision = duplicates.filter(library__isnull=False).exists()
        else:
            collision = duplicates.filter(library__isnull=True).exists()
        if collision:
            raise ValidationError("A private Platform cannot shadow a shared Platform.")

    def save(self, *args, **kwargs):
        if not self.icon:
            self.icon = slugify(self.name)
        self.clean()
        super().save(*args, **kwargs)


class EditionQuerySet(RemovableMixin, models.QuerySet):
    """An Edition holds a mark, under a Game that holds one.

    A removed Game hides its Editions. An Edition keeps its own
    mark through that, thus restoring the Game shows back only the
    Editions nobody removed.
    """

    ancestor_marks = ("game",)

    def for_library(self, library):
        return self.filter(game__library=library).alive()

    def visible_to(self, library):
        return self.filter(
            Q(game__library__isnull=True) | Q(game__library=library)
        ).alive()


class Edition(ReferencedRow):
    class Meta:
        constraints = (
            #: A removed row holds no slot.
            models.UniqueConstraint(
                fields=("game",),
                condition=Q(is_default=True) & Q(removed_at__isnull=True),
                name="unique_default_edition_per_game",
            ),
            #: A name is unique among one Game's live Editions.
            #: No name is not a name, thus it claims no slot.
            models.UniqueConstraint(
                F("game"),
                Lower(Trim("name")),
                condition=Q(removed_at__isnull=True) & ~Q(name=""),
                name="unique_live_edition_name_per_game",
            ),
        )
        indexes = (
            #: The live Editions of one Game.
            models.Index(
                fields=("game",),
                condition=Q(removed_at__isnull=True),
                name="live_edition_per_game_idx",
            ),
        )

    id = UUIDv7Field(primary_key=True, editable=False)
    objects = EditionQuerySet.as_manager()
    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        related_name="editions",
    )
    #: The words this Edition presents under.
    name = models.CharField(max_length=255, blank=True, default="")
    is_default = models.BooleanField(default=False, editable=False)
    #: Set instead of destroying the row.
    removed_at = models.DateTimeField(
        null=True, blank=True, default=None, editable=False
    )

    @property
    def display_name(self) -> str:
        """An unnamed Edition presents as the work."""
        return self.name or self.game.name


class ReleaseQuerySet(RemovableMixin, models.QuerySet):
    """A Release holds a mark, under two rows that hold one."""

    ancestor_marks = ("edition", "edition__game")

    def for_library(self, library):
        return self.filter(edition__game__library=library).alive()

    def visible_to(self, library):
        return self.filter(
            Q(edition__game__library__isnull=True) | Q(edition__game__library=library)
        ).alive()


class Release(ReferencedRow):
    class Meta:
        constraints = (
            #: A removed row holds no slot.
            models.UniqueConstraint(
                fields=("edition",),
                condition=Q(is_default=True) & Q(removed_at__isnull=True),
                name="unique_default_release_per_edition",
            ),
        )
        indexes = (
            #: The live Releases of one Edition.
            models.Index(
                fields=("edition",),
                condition=Q(removed_at__isnull=True),
                name="live_release_per_edition_idx",
            ),
        )

    id = UUIDv7Field(primary_key=True, editable=False)
    objects = ReleaseQuerySet.as_manager()
    edition = models.ForeignKey(
        Edition,
        on_delete=models.CASCADE,
        related_name="releases",
    )
    is_default = models.BooleanField(default=False, editable=False)
    platform = models.ForeignKey(
        Platform,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="+",
    )
    release_date = TemporalValueField()
    release_date_lower = models.GeneratedField(
        expression=TemporalLowerBound("release_date"),
        output_field=models.DateField(null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    release_date_upper = models.GeneratedField(
        expression=TemporalUpperBound("release_date"),
        output_field=models.DateField(null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    release_date_kind = models.GeneratedField(
        expression=TemporalKind("release_date"),
        output_field=models.CharField(max_length=7),
        serialize=False,
        db_persist=True,
        editable=False,
    )
    release_date_precision = models.GeneratedField(
        expression=TemporalPrecisionValue("release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    release_date_start_kind = models.GeneratedField(
        expression=TemporalStartKind("release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    release_date_end_kind = models.GeneratedField(
        expression=TemporalEndKind("release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    release_date_start_precision = models.GeneratedField(
        expression=TemporalStartPrecision("release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    release_date_end_precision = models.GeneratedField(
        expression=TemporalEndPrecision("release_date"),
        output_field=models.CharField(max_length=7, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    release_date_qualifier = models.GeneratedField(
        expression=TemporalQualifierValue("release_date"),
        output_field=models.CharField(max_length=11, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    release_date_start_qualifier = models.GeneratedField(
        expression=TemporalStartQualifier("release_date"),
        output_field=models.CharField(max_length=11, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    release_date_end_qualifier = models.GeneratedField(
        expression=TemporalEndQualifier("release_date"),
        output_field=models.CharField(max_length=11, null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    #: Set instead of destroying the row.
    removed_at = models.DateTimeField(
        null=True, blank=True, default=None, editable=False
    )

    def clean(self):
        super().clean()
        if self.platform_id is not None:
            _validate_related_library(
                self.edition.game.library_id,
                self.platform,
                "platform",
                allow_shared=True,
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class ExternalReference(models.Model):
    class Provider(models.TextChoices):
        WIKIDATA = "wikidata", "Wikidata"

    class EntityKind(models.TextChoices):
        GAME = "game", "Game"
        EDITION = "edition", "Edition"
        RELEASE = "release", "Release"
        PLATFORM = "platform", "Platform"

    TARGET_FIELDS: ClassVar[dict[str, str]] = {
        EntityKind.GAME: "game",
        EntityKind.EDITION: "edition",
        EntityKind.RELEASE: "release",
        EntityKind.PLATFORM: "platform",
    }

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("provider", "entity_kind", "provider_key"),
                name="unique_external_reference_provider_kind_key",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        entity_kind="game",
                        game__isnull=False,
                        edition__isnull=True,
                        release__isnull=True,
                        platform__isnull=True,
                    )
                    | Q(
                        entity_kind="edition",
                        game__isnull=True,
                        edition__isnull=False,
                        release__isnull=True,
                        platform__isnull=True,
                    )
                    | Q(
                        entity_kind="release",
                        game__isnull=True,
                        edition__isnull=True,
                        release__isnull=False,
                        platform__isnull=True,
                    )
                    | Q(
                        entity_kind="platform",
                        game__isnull=True,
                        edition__isnull=True,
                        release__isnull=True,
                        platform__isnull=False,
                    )
                ),
                name="external_reference_kind_matches_target",
            ),
            models.CheckConstraint(
                condition=Q(provider="wikidata"),
                name="external_reference_supported_provider",
            ),
            models.CheckConstraint(
                condition=Q(provider_key__regex=r"^Q[1-9][0-9]*$"),
                name="external_reference_canonical_provider_key",
            ),
        )

    id = UUIDv7Field(primary_key=True, editable=False)
    provider = models.CharField(max_length=50)
    entity_kind = models.CharField(max_length=20)
    provider_key = models.CharField(max_length=255)
    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="external_references",
    )
    edition = models.ForeignKey(
        Edition,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="external_references",
    )
    release = models.ForeignKey(
        Release,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="external_references",
    )
    platform = models.ForeignKey(
        Platform,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="external_references",
    )

    def clean(self):
        super().clean()
        self.provider, self.provider_key = normalize_provider_key(
            provider=self.provider,
            provider_key=self.provider_key,
        )

        target_ids = {
            target_kind: getattr(self, f"{target_field}_id")
            for target_kind, target_field in self.TARGET_FIELDS.items()
        }
        errors = {}
        expected_target_field = self.TARGET_FIELDS.get(self.entity_kind)
        if expected_target_field is None:
            errors["entity_kind"] = "Unsupported catalog entity kind."
        elif target_ids[self.entity_kind] is None:
            errors[expected_target_field] = (
                f"A {self.entity_kind} reference requires a {self.entity_kind} target."
            )
        for target_kind, target_id in target_ids.items():
            if target_id is not None and target_kind != self.entity_kind:
                errors[target_kind] = (
                    f"A {self.entity_kind} reference cannot target a {target_kind}."
                )
        if errors:
            raise ValidationError(errors)

        if self.pk is not None:
            persisted_target_ids = (
                type(self)
                .objects.filter(pk=self.pk)
                .values("game_id", "edition_id", "release_id", "platform_id")
                .first()
            )
            if persisted_target_ids is not None:
                current_target_ids = {
                    f"{target_field}_id": target_ids[target_kind]
                    for target_kind, target_field in self.TARGET_FIELDS.items()
                }
                if persisted_target_ids != current_target_ids:
                    raise ValidationError(
                        {
                            "target_uuid": (
                                "An existing external reference is already mapped "
                                "to a target and cannot be reassigned."
                            )
                        }
                    )

    @property
    def target_uuid(self) -> UUID:
        target_ids = {
            target_kind: getattr(self, f"{target_field}_id")
            for target_kind, target_field in self.TARGET_FIELDS.items()
        }
        target_id = target_ids.get(self.entity_kind)
        if (
            target_id is None
            or sum(value is not None for value in target_ids.values()) != 1
        ):
            raise ValidationError(
                {"entity_kind": "External reference target is invalid."}
            )
        return target_id

    @property
    def external_url(self) -> str:
        return external_reference_url(
            provider=self.provider,
            entity_kind=self.entity_kind,
            provider_key=self.provider_key,
        )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class PurchaseQueryset(RemovableLibraryQuerySet):
    def for_library(self, library):
        #: One live game keeps a bundle.
        #: A purchase that names no game
        #: is untouched by removal, so it stays.
        linked = Game.objects.filter(purchases=OuterRef("pk"))
        return (
            super()
            .for_library(library)
            .filter(~Exists(linked) | Exists(linked.alive()))
        )

    def refunded(self):
        return self.filter(date_refunded__isnull=False)

    def not_refunded(self):
        return self.filter(date_refunded__isnull=True)

    def games_only(self):
        return self.filter(type=Purchase.GAME)

    def finished(self, library):
        #: The status lives on the library's row.
        return self.filter(
            Q(
                games__in=Game.objects.tracked_by(
                    library, tracked__status__in=DONE_STATUSES
                )
            )
            | Q(games__playevents__ended__isnull=False)
        ).distinct()


class Purchase(models.Model):
    PHYSICAL = "ph"
    DIGITAL = "di"
    DIGITALUPGRADE = "du"
    RENTED = "re"
    BORROWED = "bo"
    TRIAL = "tr"
    DEMO = "de"
    PIRATED = "pi"
    OWNERSHIP_TYPES = (
        (PHYSICAL, "Physical"),
        (DIGITAL, "Digital"),
        (DIGITALUPGRADE, "Digital Upgrade"),
        (RENTED, "Rented"),
        (BORROWED, "Borrowed"),
        (TRIAL, "Trial"),
        (DEMO, "Demo"),
        (PIRATED, "Pirated"),
    )
    GAME = "game"
    DLC = "dlc"
    SEASONPASS = "season_pass"
    BATTLEPASS = "battle_pass"
    TYPES = (
        (GAME, "Game"),
        (DLC, "DLC"),
        (SEASONPASS, "Season Pass"),
        (BATTLEPASS, "Battle Pass"),
    )

    objects = PurchaseQueryset().as_manager()

    id = UUIDv7Field(primary_key=True, editable=False, serialize=False)
    library = models.ForeignKey(
        "UserLibrary", on_delete=models.CASCADE, related_name="purchases"
    )
    games = models.ManyToManyField(Game, related_name="purchases")

    platform = models.ForeignKey(
        Platform,
        on_delete=models.SET_NULL,
        default=None,
        null=True,
        blank=True,
    )
    date_purchased = models.DateField(verbose_name="Purchased")
    date_refunded = models.DateField(blank=True, null=True, verbose_name="Refunded")
    infinite = models.BooleanField(default=False)
    price = models.FloatField(default=0)
    # Entry forms preselect a resolved default, but every persisted Purchase
    # carries its original currency explicitly.
    price_currency = models.CharField(max_length=3, blank=True, default="")
    converted_price = models.FloatField(null=True)
    converted_currency = models.CharField(max_length=3, blank=True, default="")
    needs_price_update = models.BooleanField(default=True, db_index=True)
    price_per_game = GeneratedField(
        expression=Coalesce(F("converted_price"), F("price"), 0)
        / NullIf(F("num_purchases"), 0),
        output_field=models.FloatField(),
        db_persist=True,
        editable=False,
    )
    num_purchases = models.IntegerField(default=0)
    ownership_type = models.CharField(
        max_length=2, choices=OWNERSHIP_TYPES, default=DIGITAL
    )
    type = models.CharField(max_length=255, choices=TYPES, default=GAME)
    name = models.CharField(max_length=255, blank=True, default="")
    related_game = models.ForeignKey(
        Game,
        on_delete=models.SET_NULL,
        default=None,
        null=True,
        blank=True,
        related_name="addon_purchases",
        verbose_name="Base game",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    #: Set instead of destroying the row.
    removed_at = models.DateTimeField(
        null=True, blank=True, default=None, editable=False
    )

    @property
    def standardized_price(self):
        return (
            f"{floatformat(self.converted_price, 0)} {self.converted_currency}"
            if self.converted_price
            else None
        )

    @property
    def has_one_item(self):
        return self.games.count() == 1

    @property
    def standardized_name(self):
        return self.name or self.first_game.name

    @property
    def first_game(self):
        return self.games.first()

    def __str__(self):
        return self.standardized_name

    @property
    def full_name(self):
        return label_with_details(
            self.standardized_name,
            f"{self.num_purchases} game{pluralize(self.num_purchases)}",
            self.date_purchased,
            self.standardized_price,
        )

    def is_game(self):
        return self.type == self.GAME

    def refund(self):
        self.date_refunded = timezone.now()
        self.save()

    def clean(self):
        super().clean()
        if self.platform_id is not None:
            _validate_related_library(
                self.library_id,
                self.platform,
                "platform",
                allow_shared=True,
            )
        if self.related_game_id is not None:
            _validate_related_library(
                self.library_id,
                self.related_game,
                "related_game",
            )

    def save(self, *args, **kwargs):
        if not self.price_currency:
            raise ValidationError({"price_currency": "Purchase currency is required."})
        self.clean()
        if self.type != Purchase.GAME and not self.related_game:
            raise ValidationError(
                f"{self.get_type_display()} must have a related game."
            )

        update_fields = kwargs.get("update_fields")
        conversion_fields = {"date_purchased", "price", "price_currency"}
        may_need_conversion = (
            self._state.adding
            or update_fields is None
            or not conversion_fields.isdisjoint(update_fields)
        )
        if not may_need_conversion:
            super().save(*args, **kwargs)
            return

        from games.conversion import _request_conversion_for_locked_state

        is_new = self._state.adding
        with transaction.atomic():
            conversion_state = PurchaseConversionState.objects.select_for_update().get(
                library_id=self.library_id
            )
            price_changed = is_new
            if not is_new:
                previous = (
                    Purchase.objects.only("date_purchased", "price", "price_currency")
                    .filter(pk=self.pk)
                    .first()
                )
                price_changed = previous is None or (
                    previous.date_purchased != self.date_purchased
                    or previous.price != self.price
                    or previous.price_currency != self.price_currency
                )

            if price_changed:
                self.needs_price_update = True
                if update_fields is not None:
                    kwargs["update_fields"] = set(update_fields) | {
                        "needs_price_update"
                    }

            super().save(*args, **kwargs)
            if price_changed:
                _request_conversion_for_locked_state(
                    conversion_state,
                    conversion_state.requested_currency,
                )


class SessionQuerySet(RemovableMixin, models.QuerySet):
    def for_library(self, library):
        """A live session of a live game."""
        return self.filter(game__library=library, game__removed_at__isnull=True).alive()

    def total_duration_unformatted(self):
        result = self.aggregate(
            duration=Sum(F("duration_calculated") + F("duration_manual"))
        )
        return result["duration"]

    def calculated_duration_unformatted(self):
        result = self.aggregate(duration=Sum(F("duration_calculated")))
        return result["duration"]

    def without_manual(self):
        return self.exclude(duration_calculated=timedelta(0))

    def only_manual(self):
        return self.filter(duration_calculated=timedelta(0))


class Session(models.Model):
    class Meta:
        get_latest_by = "timestamp_start"
        indexes = (
            #: The navbar's resume read keys on both.
            models.Index(fields=("timestamp_start", "id"), name="session_start_id_idx"),
        )

    id = UUIDv7Field(primary_key=True, editable=False)
    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        related_name="sessions",
    )
    timestamp_start = models.DateTimeField(verbose_name="Session start", db_index=True)
    timestamp_end = models.DateTimeField(
        blank=True, null=True, verbose_name="Session end"
    )
    # IANA zone id the timestamp was committed in. NULL means "assume the
    # account's display zone" — exactly the pre-existing behaviour, so old
    # rows need no backfill. No `choices`: the valid set is the running
    # interpreter's tzdata, validated at the form/API edge, so tzdata
    # updates never churn migrations.
    timestamp_start_timezone = models.CharField(
        max_length=64, null=True, blank=True, default=None
    )
    timestamp_end_timezone = models.CharField(
        max_length=64, null=True, blank=True, default=None
    )
    duration_manual = models.DurationField(
        blank=True, null=True, default=timedelta(0), verbose_name="Manual duration"
    )
    duration_calculated = GeneratedField(
        expression=Coalesce(F("timestamp_end") - F("timestamp_start"), timedelta(0)),
        output_field=models.DurationField(),
        db_persist=True,
        editable=False,
    )
    duration_total = GeneratedField(
        expression=ExpressionWrapper(
            Coalesce(F("timestamp_end") - F("timestamp_start"), timedelta(0))
            + F("duration_manual"),
            output_field=models.DurationField(),
        ),
        output_field=models.DurationField(),
        db_persist=True,
        editable=False,
    )
    device = models.ForeignKey(
        "Device",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
    )
    note = models.TextField(blank=True, default="")
    emulated = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    #: Set instead of destroying the row.
    removed_at = models.DateTimeField(
        null=True, blank=True, default=None, editable=False
    )

    objects = SessionQuerySet.as_manager()

    def __str__(self):
        mark = "*" if self.is_manual() else ""
        return (
            f"{self.game!s} {self.timestamp_start.date()!s} "
            f"({format_decimal_hours(self.duration_total)}{mark})"
        )

    def finish_now(self):
        self.timestamp_end = timezone.now()

    def is_manual(self) -> bool:
        return self.duration_manual != timedelta(0)

    def save(self, *args, **kwargs) -> None:
        if self.game_id is not None and self.device_id is not None:
            _validate_related_library(
                self.game.library_id,
                self.device,
                "device",
            )
        if not isinstance(self.duration_manual, timedelta):
            self.duration_manual = timedelta(0)
        super().save(*args, **kwargs)


class Device(ReferencedRow):
    #: Removable: `device` is a REQUIRED reference kind.
    objects = RemovableLibraryQuerySet.as_manager()

    id = UUIDv7Field(primary_key=True, editable=False)
    library = models.ForeignKey(
        "UserLibrary", on_delete=models.CASCADE, related_name="devices"
    )

    PC = "PC"
    CONSOLE = "Console"
    HANDHELD = "Handheld"
    MOBILE = "Mobile"
    SBC = "Single-board computer"
    UNKNOWN = "Unknown"
    DEVICE_TYPES = (
        (PC, "PC"),
        (CONSOLE, "Console"),
        (HANDHELD, "Handheld"),
        (MOBILE, "Mobile"),
        (SBC, "Single-board computer"),
        (UNKNOWN, "Unknown"),
    )
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=255, choices=DEVICE_TYPES, default=UNKNOWN)
    created_at = models.DateTimeField(auto_now_add=True)
    #: Set instead of destroying the row.
    removed_at = models.DateTimeField(
        null=True, blank=True, default=None, editable=False
    )

    def __str__(self):
        return f"{self.name} ({self.type})"


class ExchangeRate(models.Model):
    currency_from = models.CharField(max_length=255)
    currency_to = models.CharField(max_length=255)
    year = models.PositiveIntegerField()
    rate = models.FloatField()

    class Meta:
        unique_together = ("currency_from", "currency_to", "year")

    def __str__(self):
        return f"{self.currency_from}/{self.currency_to} - {self.rate} ({self.year})"


def get_or_create_rate(currency_from: str, currency_to: str, year: int) -> float | None:
    # Currently unused. If ever wired up, its currency_to must come from
    # settings_resolver.resolve_str("DEFAULT_DISPLAY_CURRENCY"), not a boot-frozen value.
    exchange_rate = None
    result = ExchangeRate.objects.filter(
        currency_from=currency_from, currency_to=currency_to, year=year
    )
    if result:
        exchange_rate = result[0].rate
    else:
        try:
            # this API endpoint only accepts lowercase currency string
            response = requests.get(
                f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{year}-01-01/v1/currencies/{currency_from.lower()}.json"
            )
            response.raise_for_status()
            data = response.json()
            currency_from_data = data.get(currency_from.lower())
            rate = currency_from_data.get(currency_to.lower())

            if rate:
                logger.info(f"[convert_prices]: Got {rate}, saving...")
                created_rate = ExchangeRate.objects.create(
                    currency_from=currency_from,
                    currency_to=currency_to,
                    year=year,
                    rate=floatformat(rate, 2),
                )
                exchange_rate = created_rate.rate
            else:
                logger.info("[convert_prices]: Could not get an exchange rate.")
        except requests.RequestException as e:
            logger.info(
                f"[convert_prices]: Failed to fetch exchange rate for {currency_from}->{currency_to} in {year}: {e}"
            )
    return exchange_rate


class PlayEventQuerySet(RemovableMixin, models.QuerySet):
    def for_library(self, library):
        """A live event of a live game."""
        return self.filter(game__library=library, game__removed_at__isnull=True).alive()


class PlayEvent(models.Model):
    objects = PlayEventQuerySet.as_manager()

    id = UUIDv7Field(primary_key=True, editable=False)
    game = models.ForeignKey(Game, related_name="playevents", on_delete=models.CASCADE)
    started = models.DateField(null=True, blank=True)
    ended = models.DateField(null=True, blank=True)
    days_to_finish = GeneratedField(
        expression=Coalesce(
            Case(
                When(ended=F("started"), then=Value(1)),
                default=Func(
                    F("ended"),
                    F("started"),
                    function="",
                    template="(%(expressions)s)",
                    arg_joiner=" - ",
                    output_field=models.IntegerField(),
                ),
                output_field=models.IntegerField(),
            ),
            Value(0),
        ),
        output_field=models.IntegerField(),
        db_persist=True,
        editable=False,
        blank=True,
    )
    note = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    #: Set instead of destroying the row.
    removed_at = models.DateTimeField(
        null=True, blank=True, default=None, editable=False
    )


# class PlayMarker(models.Model):
#     game = models.ForeignKey(Game, related_name="markers", on_delete=models.CASCADE)
#     played_since = models.DurationField()
#     played_total = models.DurationField()
#     note = models.CharField(max_length=255)


class GameStatusChangeQuerySet(models.QuerySet):
    def for_library(self, library):
        """No screen removes one. #771 takes it."""
        return self.filter(game__library=library, game__removed_at__isnull=True)


class GameStatusChange(models.Model):
    """
    Tracks changes to the status of a Game.
    """

    objects = GameStatusChangeQuerySet.as_manager()

    id = UUIDv7Field(primary_key=True, editable=False)
    game = models.ForeignKey(
        Game, on_delete=models.CASCADE, related_name="status_changes"
    )
    old_status = models.CharField(
        max_length=1, choices=Game.Status.choices, blank=True, null=True
    )
    new_status = models.CharField(max_length=1, choices=Game.Status.choices)
    timestamp = models.DateTimeField(null=True)

    def __str__(self):
        return f"{self.game.name}: {self.old_status or 'None'} -> {self.new_status} at {self.timestamp}"

    class Meta:
        ordering: ClassVar[list[str]] = ["-timestamp"]


class FilterPreset(models.Model):
    """Saved filter configuration, following Stash's SavedFilter pattern.

    Separates find_filter (sort/pagination), object_filter (criteria JSON),
    and ui_options (presentation state) so they can evolve independently.
    """

    class Meta:
        ordering: ClassVar[list[str]] = ["name"]
        constraints = (
            #: Partial: a removed preset frees its name.
            models.UniqueConstraint(
                fields=("library", "mode", "name"),
                condition=Q(removed_at__isnull=True),
                name="unique_library_mode_name_preset",
            ),
        )

    objects = RemovableLibraryQuerySet.as_manager()

    id = UUIDv7Field(primary_key=True, editable=False)

    MODE_CHOICES = (
        ("games", "Games"),
        ("sessions", "Sessions"),
        ("purchases", "Purchases"),
        ("playevents", "Play Events"),
        ("devices", "Devices"),
        ("platforms", "Platforms"),
    )

    library = models.ForeignKey(
        "UserLibrary", on_delete=models.CASCADE, related_name="filter_presets"
    )
    name = models.CharField(max_length=255)
    mode = models.CharField(max_length=50, choices=MODE_CHOICES, default="games")
    find_filter = models.JSONField(default=dict, blank=True)
    object_filter = models.JSONField(default=dict, blank=True)
    ui_options = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    #: Set instead of destroying the row.
    removed_at = models.DateTimeField(
        null=True, blank=True, default=None, editable=False
    )

    def __str__(self):
        return f"{self.name} ({self.get_mode_display()})"


class SiteSetting(models.Model):
    """DB layer of the settings resolver: a global runtime override for a
    site-scoped setting. Deliberately no user FK — per-user prefs live on
    UserPreferences."""

    key = models.CharField(max_length=100, unique=True)
    value = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["key"]

    def __str__(self):
        return f"{self.key} = {self.value!r}"


#: USER-scoped key → the nullable UserPreferences column storing it. Keys absent
#: here live in the ``extra_preferences`` bag.
USER_PREFERENCE_FIELD_BY_KEY: Final[dict[SettingKey, str]] = {
    "DEFAULT_PURCHASE_CURRENCY": "default_purchase_currency",
    "DEFAULT_DISPLAY_CURRENCY": "default_display_currency",
    "DEFAULT_LANDING_PAGE": "default_landing_page",
    "THEME": "theme",
    "DISPLAY_TIME_ZONE": "display_time_zone",
    "DATE_FORMAT_LOCALE": "date_format_locale",
    "DATETIME_FORMAT": "datetime_format",
}


class UserLibrary(models.Model):
    id = UUIDv7Field(primary_key=True, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="library",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def __str__(self) -> str:
        return str(self.id)


class ProjectionModel(models.Model):
    """A projection table, rebuilt from events.

    Three rules apply. This class gives each table a `library` column, so the
    swap is one statement per table. The primary key must be explicit, because
    the shadow copy starts a new identity sequence; `games.checks` refuses an
    auto-increment key. No model outside the projections may point to a
    projection row, because the swap deletes and inserts each row. No check
    enforces that last rule.
    """

    library = models.ForeignKey(
        UserLibrary,
        on_delete=models.CASCADE,
        related_name="+",
    )

    class Meta:
        abstract = True


class PlayerGameStatus(models.TextChoices):
    """The status a library gives a game.

    Full words, not the letters of `Game.Status`: a recorded payload cannot be
    upcast, so an event recording `f` would mean Completed forever.
    """

    UNPLAYED = "unplayed", "Unplayed"
    PLAYED = "played", "Played"
    COMPLETED = "completed", "Completed"
    RETIRED = "retired", "Retired"
    SHELVED = "shelved", "Shelved"
    ABANDONED = "abandoned", "Abandoned"


#: Done with the game: completed or retired.
DONE_STATUSES: tuple[PlayerGameStatus, ...] = (
    PlayerGameStatus.COMPLETED,
    PlayerGameStatus.RETIRED,
)


class PlayerGame(ProjectionModel):
    """One catalog game a library tracks, projected from its events."""

    id = UUIDv7Field(
        primary_key=True,
        editable=False,
        #: The creation event's aggregate_id, evaluated once.
        default=models.NOT_PROVIDED,
        db_default=models.NOT_PROVIDED,
    )
    game = models.ForeignKey(
        Game,
        #: No cascade may delete a projection row.
        on_delete=models.RESTRICT,
        related_name="player_games",
    )
    #: The creation event's recorded_at.
    tracked_at = models.DateTimeField(editable=False)
    #: No event states it: a constant default.
    #: A default is also absent from the creation handler's DO UPDATE list, so
    #: re-running that event keeps a status a later event set.
    status = models.CharField(
        max_length=9,
        choices=PlayerGameStatus,
        default=PlayerGameStatus.UNPLAYED,
    )
    #: No event states it: a constant default.
    mastered = models.BooleanField(default=False)
    #: An explicit preference, never inferred from status.
    excluded_from_unfinished = models.BooleanField(default=False)
    #: The remove event's recorded_at; null means live.
    #: The player's act, not the catalog's.
    removed_at = models.DateTimeField(null=True, default=None, editable=False)

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("library", "game"),
                name="unique_library_player_game",
            ),
        )

    def __str__(self) -> str:
        return f"{self.game} tracked by library {self.library_id}"


class UserLibraryPreferences(models.Model):
    library = models.OneToOneField(
        UserLibrary,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    default_device = models.ForeignKey(
        Device,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    updated_at = models.DateTimeField(default=timezone.now)

    def clean(self):
        super().clean()
        if self.default_device_id is not None:
            _validate_related_library(
                self.library_id,
                self.default_device,
                "default_device",
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def set_default_device(self, device):
        if self.default_device_id == getattr(device, "pk", None):
            return False
        self.default_device = device
        self.updated_at = timezone.now()
        self.save(update_fields=["default_device", "updated_at"])
        return True


class PurchaseConversionState(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        FAILED = "failed", "Failed"
        COMPLETE = "complete", "Complete"

    library = models.OneToOneField(
        UserLibrary,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="purchase_conversion_state",
    )
    requested_version = models.PositiveBigIntegerField(default=0)
    requested_currency = models.CharField(max_length=3, blank=True, default="")
    published_version = models.PositiveBigIntegerField(default=0)
    published_currency = models.CharField(max_length=3, blank=True, default="")
    status = models.CharField(max_length=10, choices=Status, default=Status.COMPLETE)
    retry_at = models.DateTimeField(null=True, blank=True, default=None)
    last_error = models.TextField(blank=True, default="")


class UserPreferences(models.Model):
    """Per-user layer of the settings resolver: a personal override for a
    user-scoped setting, sitting above the site default. Unset is a NULL column
    (or an absent ``extra_preferences`` key), which falls through to the site and
    code-default layers — never an empty-string sentinel."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    default_purchase_currency = models.CharField(
        max_length=3, null=True, blank=True, default=None
    )
    default_display_currency = models.CharField(
        max_length=3, null=True, blank=True, default=None
    )
    default_landing_page = models.CharField(
        max_length=100, null=True, blank=True, default=None
    )
    theme = models.CharField(
        max_length=6,
        choices=THEME_CHOICES,
        null=True,
        blank=True,
        default=None,
    )
    display_time_zone = models.CharField(
        max_length=100, null=True, blank=True, default=None
    )
    date_format_locale = models.CharField(
        max_length=20, null=True, blank=True, default=None
    )
    datetime_format = models.CharField(
        max_length=20, null=True, blank=True, default=None
    )
    #: Extension bag for USER keys without a typed column. Absent key == unset.
    extra_preferences = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "user preferences"
        verbose_name_plural = "user preferences"

    def __str__(self):
        return f"Preferences for {self.user}"

    @classmethod
    def get_for_user(cls, user) -> UserPreferences:
        """The user's row, created on first access. Write path only — the resolver
        reads a snapshot, never this."""
        preferences, _ = cls.objects.get_or_create(user=user)
        return preferences

    def set_preference_value(self, key: SettingKey, value: object) -> None:
        """Store ``value`` for ``key``; ``None`` clears it back to unset. The
        value must already be normalized — the command (``change_user_setting``)
        is the one write path and validates before calling this."""
        field = USER_PREFERENCE_FIELD_BY_KEY.get(key)
        if field is not None:
            setattr(self, field, value)
            self.save(update_fields=[field, "updated_at"])
            return
        if value is None:
            self.extra_preferences.pop(key, None)
        else:
            self.extra_preferences[key] = value
        self.save(update_fields=["extra_preferences", "updated_at"])


class LibraryEventQuerySet(LibraryOwnedQuerySet):
    pass


class LibraryEventStreamHead(models.Model):
    """The single append point of one library's event stream: its stable stream
    identity and the sequence a command locks before appending."""

    class Meta:
        constraints = (
            #: Redundant against the primary key, and present only so an event
            #: can point a composite foreign key at (stream, library).
            models.UniqueConstraint(
                fields=("id", "library"),
                name="unique_library_event_stream_head_library_identity",
            ),
        )

    id = UUIDv7Field(primary_key=True, editable=False)
    library = models.OneToOneField(
        UserLibrary,
        on_delete=models.CASCADE,
        related_name="event_stream_head",
    )
    #: Zero means the stream exists but nothing has been appended yet.
    current_sequence = models.PositiveBigIntegerField(default=0)

    def __str__(self) -> str:
        return f"Event stream {self.id}"


#: Named here rather than inline so the retry classifier, which must recognise
#: this collision by name, cannot drift from the constraint it matches.
LIBRARY_EVENT_SEQUENCE_CONSTRAINT = "unique_library_event_stream_sequence"


class LibraryEvent(models.Model):
    """One recorded change to a private library, carrying enough envelope to
    replay and explain itself without reading any projection table."""

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("stream", "sequence"),
                name=LIBRARY_EVENT_SEQUENCE_CONSTRAINT,
            ),
            models.CheckConstraint(
                condition=Q(sequence__gte=1),
                name="library_event_sequence_positive",
            ),
            models.CheckConstraint(
                condition=Q(payload_schema_version__gte=1),
                name="library_event_payload_schema_version_positive",
            ),
            models.CheckConstraint(
                condition=~Q(event_type=""),
                name="library_event_type_not_empty",
            ),
            models.CheckConstraint(
                condition=~Q(idempotency_key=""),
                name="library_event_idempotency_key_not_empty",
            ),
        )

    id = UUIDv7Field(primary_key=True, editable=False)
    library = models.ForeignKey(
        UserLibrary,
        on_delete=models.CASCADE,
        related_name="events",
    )
    stream = models.ForeignKey(
        LibraryEventStreamHead,
        on_delete=models.RESTRICT,
        related_name="events",
    )
    sequence = models.PositiveBigIntegerField()
    event_type = models.CharField(max_length=255)
    #: The private aggregate being changed, never a shared catalog identity.
    #: Both defaults are cleared so a writer cannot forget to name it.
    aggregate_id = UUIDv7Field(default=None, db_default=models.NOT_PROVIDED)
    payload_schema_version = models.PositiveIntegerField(default=1)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    effective_time = TemporalValueField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    #: Shared by every event of one human action, so the two are never confused
    #: with a generated-per-row identity.
    correlation_id = UUIDv7Field(default=None, db_default=models.NOT_PROVIDED)
    causation_id = UUIDv7Field(
        null=True, blank=True, default=None, db_default=models.NOT_PROVIDED
    )
    source_metadata = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(max_length=255)
    payload = models.JSONField()

    objects = LibraryEventQuerySet.as_manager()

    def __str__(self) -> str:
        return f"{self.event_type} #{self.sequence}"


class LibraryIdempotencyRecordQuerySet(LibraryOwnedQuerySet):
    pass


class LibraryIdempotencyRecord(models.Model):
    """What one command key already produced, so repeating the key answers from
    that instead of appending a second time. A key claimed by a command that
    changed nothing produced no events, and so carries no range.

    The events table cannot carry this: one append writes many rows sharing a
    key, so the pair could never be unique there.
    """

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("library", "idempotency_key"),
                name="unique_library_idempotency_key",
            ),
            #: Both columns, or neither. #740 removes this with the model.
            #: The second branch tests nullness rather than leaving it to the
            #: comparisons: one column absent makes those NULL, and a check
            #: constraint admits a NULL as satisfied.
            models.CheckConstraint(
                condition=(
                    Q(first_sequence__isnull=True, last_sequence__isnull=True)
                    | Q(
                        first_sequence__isnull=False,
                        last_sequence__isnull=False,
                        first_sequence__gte=1,
                        last_sequence__gte=F("first_sequence"),
                    )
                ),
                name="library_idempotency_range_whole",
            ),
            models.CheckConstraint(
                condition=~Q(idempotency_key=""),
                name="library_idempotency_key_not_empty",
            ),
            models.CheckConstraint(
                condition=~Q(request_fingerprint=""),
                name="library_idempotency_request_fingerprint_not_empty",
            ),
            models.CheckConstraint(
                condition=Q(fingerprint_version__gte=1),
                name="library_idempotency_fingerprint_version_positive",
            ),
        )

    id = UUIDv7Field(primary_key=True, editable=False)
    library = models.ForeignKey(
        UserLibrary,
        on_delete=models.CASCADE,
        related_name="idempotency_records",
    )
    idempotency_key = models.CharField(max_length=255)
    request_fingerprint = models.CharField(max_length=64)
    #: No default: a row must never claim a version it was not hashed under.
    fingerprint_version = models.PositiveSmallIntegerField()
    #: Absent when the command changed nothing: nothing was appended, so there
    #: is no range to replay. #740 removes the nullability along with this
    #: whole model, which it replaces with a record of the request itself.
    first_sequence = models.PositiveBigIntegerField(null=True)
    last_sequence = models.PositiveBigIntegerField(null=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    objects = LibraryIdempotencyRecordQuerySet.as_manager()

    def __str__(self) -> str:
        return self.idempotency_key


class LibraryEventReferenceQuerySet(LibraryOwnedQuerySet):
    def to_row(self, kind: str, referenced_id):
        """Every recorded reference naming that row.

        Not library-scoped. One library keeps a shared row for all.
        """
        return self.filter(kind=kind, referenced_id=referenced_id)


class LibraryEventReference(models.Model):
    """One reference one event recorded.

    The payloads hold this too. The index makes the retention
    question a lookup, not a scan of every event.
    """

    class Meta:
        indexes = (
            #: The retention question, asked once per delete.
            models.Index(fields=("kind", "referenced_id")),
            models.Index(fields=("library", "kind")),
        )
        constraints = (
            models.CheckConstraint(
                condition=~Q(kind=""),
                name="library_event_reference_kind_not_empty",
            ),
            models.CheckConstraint(
                condition=~Q(payload_key=""),
                name="library_event_reference_payload_key_not_empty",
            ),
        )

    id = UUIDv7Field(primary_key=True, editable=False)
    library = models.ForeignKey(
        UserLibrary,
        on_delete=models.CASCADE,
        related_name="event_references",
    )
    event = models.ForeignKey(
        LibraryEvent,
        on_delete=models.CASCADE,
        related_name="references",
    )
    #: A registered ReferenceKind name, such as "catalog.game".
    kind = models.CharField(max_length=255)
    #: Both defaults cleared.
    #: A generated id would name nothing.
    referenced_id = UUIDv7Field(default=None, db_default=models.NOT_PROVIDED)
    #: The field holding it, for a report.
    payload_key = models.CharField(max_length=255)

    objects = LibraryEventReferenceQuerySet.as_manager()

    def __str__(self) -> str:
        return f"{self.kind} {self.referenced_id}"
