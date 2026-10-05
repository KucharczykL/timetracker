import logging
from collections.abc import Callable, Mapping
from datetime import timedelta
from operator import attrgetter
from typing import TYPE_CHECKING, Any, ClassVar, Final, Literal
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import (
    Exists,
    F,
    FilteredRelation,
    Func,
    OuterRef,
    Q,
    Value,
)
from django.db.models.functions import Cast, Coalesce, Lower, Trim
from django.template.defaultfilters import slugify
from django.urls import reverse
from django.utils import timezone

from common.keyset import FieldName, RelationPath, lookup
from common.naming import name_key
from common.platform_icons import UNSPECIFIED_ICON, require_platform_icon
from common.utils import label_with_details
from games.end_ways import EndWay, EndWays
from games.endpoint_fields import (
    EndpointColumns,
    OpeningEndpointColumns,
    WayColumn,
    endpoint_bound,
    endpoint_constraints,
    endpoint_marker,
    endpoint_note,
    endpoint_way,
    endpoint_when,
    opening_marker,
)
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

if TYPE_CHECKING:
    from games.reads.playthrough_activity import ActivityClock

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
    #: The library `playtime` reads, cloned along.
    _playtime_library: UserLibrary | None = None

    def _clone(self) -> GameQuerySet:
        #: Django's hook; django-stubs declares no `_clone`.
        clone: GameQuerySet = super()._clone()  # type: ignore[misc]
        clone._playtime_library = self._playtime_library
        return clone

    def visible_to(self, library):
        return self.filter(Q(library__isnull=True) | Q(library=library)).alive()

    def in_display_order(self) -> GameQuerySet:
        """Order by DISPLAY_ORDER_FIELDS."""
        return self.order_by(*Game.DISPLAY_ORDER_FIELDS)

    def annotated_for_filtering(self, library=None):
        """Register the aliases only; drop no row.

        A filter names `tracked__status`, which needs the alias and
        nothing else. The facts are selected by `tracked_by()`
        after it filters, because an F() before the filter opens a
        second join Django cannot merge.

        No library leaves the join unconditional, so a game two
        libraries track comes back once per library. Unscoped is for
        compiling a lookup, not for executing one.

        Only a filter naming `playtime` compiles it. A second call
        without a library keeps the scope; one naming another library
        is refused, because `add_annotation` would swap it in silence.
        """
        #: Imported here: the package imports models.
        from games.reads.playtime import playtime_by_game

        if "playtime" in self.query.annotations:
            if library is not None and library != self._playtime_library:
                raise ValueError(
                    "this queryset already reads playtime for library "
                    f"{getattr(self._playtime_library, 'pk', None)}; "
                    "annotate once, at the read that states the scope"
                )
            return self
        condition = Q() if library is None else Q(player_games__library=library)
        queryset = self.annotate(
            tracked=FilteredRelation("player_games", condition=condition)
        ).alias(playtime=playtime_by_game(library))
        queryset._playtime_library = library
        return queryset

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
                tracked_excluded_from_unfinished=F("tracked__excluded_from_unfinished"),
                tracked_excluded_from_dropped=F("tracked__excluded_from_dropped"),
            )
        )

    def removable_by(self, library):
        """What the library's per-row Remove finds.

        A live game it owns, tracked or not, so a removal a defect
        stopped halfway is still reachable; or a shared game it tracks.
        """
        return self.alive().filter(
            Q(library=library)
            | Q(
                Exists(
                    PlayerGame.objects.filter(
                        game=OuterRef("pk"), library=library, removed_at__isnull=True
                    )
                ),
                library__isnull=True,
            )
        )

    def restorable_by(self, library):
        """What the library's per-row restore finds, removed or not.

        A game it owns, or a shared game it holds a PlayerGame for.
        """
        return self.filter(
            Q(library=library)
            | Q(
                Exists(PlayerGame.objects.filter(game=OuterRef("pk"), library=library)),
                library__isnull=True,
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


class GameKind(models.TextChoices):
    """What work a Game is; IGDB's words."""

    MAIN = "main", "Main game"
    DLC = "dlc", "DLC"
    EXPANSION = "expansion", "Expansion"
    STANDALONE_EXPANSION = "standalone_expansion", "Standalone expansion"


#: Kinds that name a parent.
ADDON_KINDS: Final[frozenset[GameKind]] = frozenset(GameKind) - {GameKind.MAIN}


class EditionKind(models.TextChoices):
    """The whole game, or a prerelease."""

    FULL = "full", "Full"
    PRERELEASE = "prerelease", "Prerelease"


class Game(ReferencedRow):
    if TYPE_CHECKING:
        #: Annotations, not columns: GameQuerySet.tracked_by() puts the
        #: library's four projection facts here, and only a queryset from
        #: it carries them.
        tracked_status: str
        tracked_mastered: bool
        tracked_excluded_from_unfinished: bool
        tracked_excluded_from_dropped: bool

    #: Every game order; blank sort_name leads.
    #: Local non-null columns only: Python sorts on them too.
    DISPLAY_ORDER_FIELDS: ClassVar[tuple[FieldName, ...]] = ("sort_name", "name", "id")

    #: Columns gone, refused by name in comparisons.
    RETIRED_COMPARISON_COLUMNS: ClassVar[dict[str, str]] = {
        "playtime": (
            "Playtime is read from sessions now and cannot be compared "
            "with another column; filter on playtime hours instead."
        ),
    }

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
            models.CheckConstraint(
                condition=Q(kind__in=GameKind.values),
                name="game_kind_word",
            ),
            #: An add-on names a parent; main, none.
            models.CheckConstraint(
                condition=(
                    Q(kind=GameKind.MAIN, parent__isnull=True)
                    | (~Q(kind=GameKind.MAIN) & Q(parent__isnull=False))
                ),
                name="game_parent_exactly_for_addons",
            ),
            models.CheckConstraint(
                condition=~Q(parent=F("id")),
                name="game_not_its_own_parent",
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
    kind = models.CharField(max_length=20, choices=GameKind, default=GameKind.MAIN)
    #: No reverse accessor: it crosses libraries.
    parent = models.ForeignKey(
        "self",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        default=None,
        related_name="+",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    #: Set instead of destroying the row.
    removed_at = models.DateTimeField(
        null=True, blank=True, default=None, editable=False
    )

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


#: Sorts loaded games as `order_by(*DISPLAY_ORDER_FIELDS)` does.
game_display_key: Callable[[Game], tuple[Any, ...]] = attrgetter(
    *Game.DISPLAY_ORDER_FIELDS
)


def game_display_order_through(path: RelationPath) -> tuple[FieldName, ...]:
    """DISPLAY_ORDER_FIELDS, reached through a relation."""
    return tuple(lookup(path, name) for name in Game.DISPLAY_ORDER_FIELDS)


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
    icon = models.SlugField(default=UNSPECIFIED_ICON)
    created_at = models.DateTimeField(auto_now_add=True)
    #: Set instead of destroying the row.
    removed_at = models.DateTimeField(
        null=True, blank=True, default=None, editable=False
    )

    def __str__(self):
        return self.name

    @property
    def named_with_group(self) -> str:
        """Its name, and its group where stated."""
        return f"{self.name} ({self.group})" if self.group else self.name

    def clean(self):
        super().clean()
        try:
            require_platform_icon(self.icon)
        except ValueError as refusal:
            raise ValidationError({"icon": str(refusal)}) from refusal
        duplicates = (
            #: A removed Platform shadows nothing.
            Platform.objects.alive()
            .exclude(pk=self.pk)
            .annotate(
                normalized_name=Lower(Trim("name")),
                normalized_group=Lower(Trim("group")),
            )
            .filter(
                normalized_name=name_key(self.name),
                normalized_group=name_key(self.group),
            )
        )
        if self.library_id is None:
            collision = duplicates.filter(library__isnull=False).exists()
        else:
            collision = duplicates.filter(library__isnull=True).exists()
        if collision:
            raise ValidationError("A private Platform cannot shadow a shared Platform.")

    def save(self, *args, **kwargs):
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
            models.CheckConstraint(
                condition=Q(kind__in=EditionKind.values),
                name="edition_kind_word",
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
    kind = models.CharField(
        max_length=20, choices=EditionKind, default=EditionKind.FULL
    )
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
    #: The database's words; screens read PROVIDER_POLICIES.
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

    #: The `_id` attribute, keyed on the model.
    TARGET_FIELDS_BY_MODEL: ClassVar[dict[type[models.Model], str]] = {
        Game: "game_id",
        Edition: "edition_id",
        Release: "release_id",
        Platform: "platform_id",
    }

    class Meta:
        constraints = (
            #: A removed row holds no slot (#976).
            models.UniqueConstraint(
                fields=("provider", "entity_kind", "provider_key"),
                condition=Q(removed_at__isnull=True),
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
            #: A provider issues one identity per record.
            models.UniqueConstraint(
                fields=("provider", "game"),
                condition=Q(game__isnull=False) & Q(removed_at__isnull=True),
                name="unique_live_game_reference_per_provider",
            ),
            models.UniqueConstraint(
                fields=("provider", "edition"),
                condition=Q(edition__isnull=False) & Q(removed_at__isnull=True),
                name="unique_live_edition_reference_per_provider",
            ),
            models.UniqueConstraint(
                fields=("provider", "release"),
                condition=Q(release__isnull=False) & Q(removed_at__isnull=True),
                name="unique_live_release_reference_per_provider",
            ),
            models.UniqueConstraint(
                fields=("provider", "platform"),
                condition=Q(platform__isnull=False) & Q(removed_at__isnull=True),
                name="unique_live_platform_reference_per_provider",
            ),
        )

    id = UUIDv7Field(primary_key=True, editable=False)
    provider = models.CharField(max_length=50, choices=Provider)
    entity_kind = models.CharField(max_length=20, choices=EntityKind)
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
    #: A mark; ExternalReference is not in REMOVABLE_MODELS.
    removed_at = models.DateTimeField(
        null=True, blank=True, default=None, editable=False
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


#: Places of a stored rate.
RATE_PLACES: Final = 12


class ExchangeRate(models.Model):
    currency_from = models.CharField(max_length=255)
    currency_to = models.CharField(max_length=255)
    year = models.PositiveIntegerField()
    rate = models.DecimalField(max_digits=24, decimal_places=RATE_PLACES)

    class Meta:
        unique_together = ("currency_from", "currency_to", "year")
        constraints = (
            models.CheckConstraint(
                condition=Q(rate__gt=0), name="games_exchangerate_rate_positive"
            ),
        )

    def __str__(self):
        return f"{self.currency_from}/{self.currency_to} - {self.rate} ({self.year})"


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
        ("playthroughs", "Playthroughs"),
        ("historical_playtime", "Historical playtime"),
        ("devices", "Devices"),
        ("platforms", "Platforms"),
        ("entries", "Library"),
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


class ListColumnChoice(models.Model):
    """The statement of one person about one list.

    Keyed on the person, not the library. A saved filter selects rows; the
    columns that show them are the property of the person.
    """

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("user", "mode"),
                name="unique_list_column_choice_per_mode",
            ),
        )

    id = UUIDv7Field(primary_key=True, editable=False)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="list_column_choices",
    )
    mode = models.CharField(max_length=50, choices=FilterPreset.MODE_CHOICES)
    #: Column key to shown, for the keys that differ from the default.
    shown = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} ({self.get_mode_display()})"


class BatchChange(models.Model):
    """One field a batch changed on a conventional row.

    A conventional row writes no event, so its batch Undo reads the
    value before here. An event-backed act never writes one.
    """

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("library", "batch", "model_label", "row_id", "field"),
                name="unique_batch_change_per_field",
            ),
        )
        indexes = (models.Index(fields=("library", "batch")),)

    id = UUIDv7Field(primary_key=True, editable=False)
    library = models.ForeignKey(
        "UserLibrary", on_delete=models.CASCADE, related_name="+"
    )
    #: The batch's correlation id.
    batch = models.UUIDField()
    #: An act's declared name, or its Undo's.
    act = models.CharField(max_length=100)
    #: `app_label.model_name` of the row.
    model_label = models.CharField(max_length=100)
    row_id = models.UUIDField()
    field = models.CharField(max_length=100)
    earlier = models.JSONField(null=True)
    stated = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.model_label} {self.row_id}.{self.field} in {self.batch}"


#: Named so a caught violation names which.
BULK_BATCH_TOKEN_CONSTRAINT = "unique_bulk_batch_token"
BULK_BATCH_LIVE_UNDO_CONSTRAINT = "one_live_undo_per_bulk_batch"


class BulkBatch(models.Model):
    """One bulk act, run in the background."""

    class State(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        FINISHED = "finished"
        STOPPED = "stopped"
        FAILED = "failed"

    #: The states nothing moves on from.
    TERMINAL: ClassVar[frozenset[State]] = frozenset(
        {State.FINISHED, State.STOPPED, State.FAILED}
    )
    #: The states a runner still owns.
    LIVE: ClassVar[frozenset[State]] = frozenset({State.QUEUED, State.RUNNING})

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("library", "token"), name=BULK_BATCH_TOKEN_CONSTRAINT
            ),
            models.UniqueConstraint(
                fields=("library", "undoes"),
                condition=Q(undoes__isnull=False, state__in=("queued", "running")),
                name=BULK_BATCH_LIVE_UNDO_CONSTRAINT,
            ),
            models.CheckConstraint(
                condition=Q(
                    state__in=("queued", "running", "finished", "stopped", "failed")
                ),
                name="bulk_batch_state_known",
            ),
            models.CheckConstraint(
                condition=Q(state__in=("queued", "running"), ended_at__isnull=True)
                | Q(
                    state__in=("finished", "stopped", "failed"),
                    ended_at__isnull=False,
                ),
                name="bulk_batch_ended_exactly_when_terminal",
            ),
            models.CheckConstraint(
                condition=Q(announced_at__isnull=True) | Q(ended_at__isnull=False),
                name="bulk_batch_announced_after_its_end",
            ),
            models.CheckConstraint(
                condition=Q(position__lte=F("total")),
                name="bulk_batch_position_within_rows",
            ),
            models.CheckConstraint(
                condition=Q(undoes__isnull=True) | Q(choice=""),
                name="bulk_batch_undo_states_no_choice",
            ),
        )
        indexes = (models.Index(fields=("library", "state")),)

    id = UUIDv7Field(primary_key=True, editable=False)
    #: The batch's correlation id.
    token = models.UUIDField()
    library = models.ForeignKey(
        "UserLibrary", on_delete=models.CASCADE, related_name="+"
    )
    action = models.CharField(max_length=100)
    #: The batch an Undo takes back.
    undoes = models.UUIDField(null=True)
    #: The settled answer; empty for none.
    choice = models.TextField(blank=True, default="")
    origin = models.TextField()
    #: Row keys as text; read through `keys`.
    rows = models.JSONField()
    #: Index into `rows` of the next key.
    position = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    done = models.PositiveIntegerField(default=0)
    unchanged = models.PositiveIntegerField(default=0)
    refused = models.PositiveIntegerField(default=0)
    lost = models.PositiveIntegerField(default=0)
    reasons = models.JSONField(default=list)
    #: The chunk due next.
    chunk = models.PositiveIntegerField(default=0)
    #: How often the due chunk started.
    attempts = models.PositiveIntegerField(default=0)
    state = models.CharField(max_length=16, choices=State, default=State.QUEUED)
    stop_requested_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    ended_at = models.DateTimeField(null=True)
    #: Set once the end was acknowledged.
    announced_at = models.DateTimeField(null=True)

    def __str__(self):
        return f"{self.action} {self.token} ({self.state})"

    @property
    def is_terminal(self) -> bool:
        return self.state in self.TERMINAL

    @property
    def keys(self) -> tuple[str, ...]:
        """The row keys, in order."""
        return tuple(str(key) for key in self.rows)


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
    enforces that last rule. A conventional row naming a projection row
    stores its key alone, as `UserLibraryPreferences.default_device_id` does.

    A projection row and every projection row it names belong to one
    library. A row across the boundary is restricted at purge, so the
    library holding the row it names can never be purged. The swap
    survives it -- it restores the same keys inside one transaction --
    but the two libraries no longer rebuild independently: a replay of
    the named library that reproduces one key fewer is refused by a
    foreign key from a library nobody asked to rebuild. Nothing in the
    schema refuses it. `audit_library_ownership` reports it, over the
    references `games/projections.py` registers, and `games.E009`
    refuses a reference that registry omits.

    Every table is unique on `(id, library)`, the projector's upsert target,
    through `library_identity_constraint()` in its own `Meta`: a concrete
    `Meta` inherits none of an abstract one. `games.E012` refuses a table
    without it.
    """

    library = models.ForeignKey(
        UserLibrary,
        on_delete=models.CASCADE,
        related_name="+",
    )

    #: Relations the comparison-operand walk never follows.
    comparison_scoping_relations: ClassVar[tuple[str, ...]] = ("library",)
    #: `(path, label)` pairs the walk treats as one hop: a to-one path
    #: at every segment, which `games.E011` checks, offered under the
    #: label. A projection reaches the catalog through its parents.
    comparison_through: ClassVar[tuple[tuple[str, str], ...]] = ()

    class Meta:
        abstract = True


def library_identity_constraint() -> models.UniqueConstraint:
    """The upsert's conflict target; one per Meta."""
    return models.UniqueConstraint(
        fields=("id", "library"),
        name="unique_%(app_label)s_%(class)s_library_identity",
    )


#: How a device leaves the library's hands.
DEVICE_WAYS: EndWays = (
    EndWay.SOLD,
    EndWay.LOST,
    EndWay.GIVEN_AWAY,
    EndWay.BROKEN,
    EndWay.STOLEN,
)

DEVICE_ACCESS_END_COLUMNS = EndpointColumns(
    name="access_end",
    model_label="games.Device",
    when="access_ended",
    lower="access_ended_lower",
    upper="access_ended_upper",
    marker="access_end_recorded_at",
    note="access_end_note",
    way=WayColumn("access_end_way", DEVICE_WAYS),
)


class Device(ProjectionModel, ReferencedRow):
    """Owned device; only the Devices projector writes."""

    objects = RemovableLibraryQuerySet.as_manager()

    #: The creation event's aggregate id.
    id = UUIDv7Field(
        primary_key=True,
        editable=False,
        default=models.NOT_PROVIDED,
        db_default=models.NOT_PROVIDED,
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
    #: The creation event's recorded_at.
    created_at = models.DateTimeField(editable=False)
    #: The remove event's recorded_at; null live.
    removed_at = models.DateTimeField(
        null=True, blank=True, default=None, editable=False
    )
    #: The day access ended; null unknown or unstated.
    access_ended = endpoint_when()
    access_ended_lower = endpoint_bound("access_ended", "lower")
    access_ended_upper = endpoint_bound("access_ended", "upper")
    #: Null is a device the library still holds.
    access_end_recorded_at = endpoint_marker()
    access_end_note = endpoint_note()
    #: One of DEVICE_WAYS; empty while held.
    access_end_way = endpoint_way(DEVICE_WAYS)

    class Meta:
        constraints = (
            library_identity_constraint(),
            *endpoint_constraints(DEVICE_ACCESS_END_COLUMNS),
        )

    def __str__(self):
        return f"{self.name} ({self.type})"


class PlayerGameStatus(models.TextChoices):
    """The status a library gives a game.

    Full words: a recorded payload is never upcast.
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


#: A PlayerGame flag leaving it out.
type VisibilityField = Literal["excluded_from_unfinished", "excluded_from_dropped"]

#: What a game may be left out of.
VISIBILITY_FIELDS: tuple[VisibilityField, ...] = (
    "excluded_from_unfinished",
    "excluded_from_dropped",
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
        #: No cascade may destroy a projection row.
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
    mastered = models.BooleanField(default=False)
    #: Explicit preferences, never inferred from status.
    excluded_from_unfinished = models.BooleanField(default=False)
    excluded_from_dropped = models.BooleanField(default=False)
    #: The remove event's recorded_at; null means live.
    #: The player's act, not the catalog's.
    removed_at = models.DateTimeField(null=True, default=None, editable=False)

    class Meta:
        constraints = (
            library_identity_constraint(),
            models.UniqueConstraint(
                fields=("library", "game"),
                name="unique_library_player_game",
            ),
        )

    def __str__(self) -> str:
        return f"{self.game} tracked by library {self.library_id}"


class PlaythroughKind(models.TextChoices):
    """A person's run, or the importer's."""

    ORDINARY = "ordinary", "Ordinary"
    IMPORTED_HISTORY = "imported_history", "Imported history"


class PlaythroughQuerySet(models.QuerySet["Playthrough"]):
    """The alias method, and its clock."""

    #: The clock these aliases read, cloned along.
    _activity_clock: ActivityClock | None = None

    def _clone(self) -> PlaythroughQuerySet:
        #: Django's hook; django-stubs declares no `_clone`.
        clone: PlaythroughQuerySet = super()._clone()  # type: ignore[misc]
        clone._activity_clock = self._activity_clock
        return clone

    def annotated_for_filtering(
        self, clock: ActivityClock | None = None
    ) -> PlaythroughQuerySet:
        """Register the two condition aliases.

        `add_annotation` replaces an alias without a word, so
        annotating twice would swap one clock for another in
        silence. A second call naming the same clock is the
        no-op `with_filter_aliases` needs; one naming another
        clock is a read that cannot state which threshold it
        answered, and is refused.

        Without a clock both names resolve and refuse to compile:
        a query naming either raises when compiled, one naming
        neither executes.
        """
        from games.reads.playthrough_activity import (
            UnscopedActivityAlias,
            activity_day_expression,
            activity_expression,
        )

        annotated = self.query.annotations.keys() & {"activity", "activity_day"}
        if annotated:
            if clock is not None and clock != self._activity_clock:
                raise ValueError(
                    "this queryset already carries a condition alias from "
                    f"{self._activity_clock}; annotate once, at the read "
                    "that states the scope"
                )
            return self
        if clock is None:
            return self.alias(
                activity_day=UnscopedActivityAlias(output_field=models.DateField()),
                activity=UnscopedActivityAlias(
                    output_field=models.CharField(null=True)
                ),
            )
        queryset = self.annotate(activity_day=activity_day_expression()).annotate(
            activity=activity_expression(clock)
        )
        queryset._activity_clock = clock
        return queryset


class Playthrough(ProjectionModel):
    """One run at a tracked game."""

    objects = PlaythroughQuerySet.as_manager()

    id = UUIDv7Field(
        primary_key=True,
        editable=False,
        #: The creation event's aggregate_id, evaluated once.
        default=models.NOT_PROVIDED,
        db_default=models.NOT_PROVIDED,
    )
    player_game = models.ForeignKey(
        PlayerGame,
        #: No cascade may destroy a projection row.
        on_delete=models.RESTRICT,
        related_name="playthroughs",
    )
    #: Stated by the creation event, never restated. No default, so
    #: `_required_columns` holds the handler to naming it.
    kind = models.CharField(max_length=16, choices=PlaythroughKind)
    #: Stated by `DescribePlaythrough`; blank reads as `Playthrough N`,
    #: derived at read time by `games/reads/playthrough_numbering.py`.
    name = models.CharField(max_length=255, blank=True, default="")
    #: Stated by `DescribePlaythrough`, beside the name.
    note = models.TextField(blank=True, default="")
    #: The day the run began. Null is a day nobody knows, which is
    #: why `start_recorded_at` beside it carries the act itself.
    started = endpoint_when()
    started_lower = endpoint_bound("started", "lower")
    started_upper = endpoint_bound("started", "upper")
    #: Null is the act that never happened. An unknown day is null too,
    #: which is why the date cannot say it.
    start_recorded_at = endpoint_marker()
    #: The note of the act. The row's `note` has no day.
    start_note = endpoint_note()
    #: The day the run met its main objective. Null is a day nobody
    #: knows, as on the start.
    completed = endpoint_when()
    completed_lower = endpoint_bound("completed", "lower")
    completed_upper = endpoint_bound("completed", "upper")
    #: Null is the act that never happened, as on the start.
    completion_recorded_at = endpoint_marker()
    #: The note of the act. The row's `note` has no day.
    completion_note = endpoint_note()
    #: The creation event's recorded_at.
    created_at = models.DateTimeField(editable=False)
    #: The remove event's recorded_at; null means live.
    #: RemovePlaythrough states it, RestorePlaythrough clears it.
    removed_at = models.DateTimeField(null=True, default=None, editable=False)

    #: The bound columns a comparison may name.
    comparable_temporal_bounds: ClassVar[Mapping[str, str]] = {
        "started_lower": "Started (earliest)",
        "started_upper": "Started (latest)",
        "completed_lower": "Completed (earliest)",
        "completed_upper": "Completed (latest)",
    }

    class Meta:
        constraints = (library_identity_constraint(),)
        indexes = (
            #: The display-number order, ending on the key.
            models.Index(
                fields=(
                    "player_game",
                    "started_lower",
                    "completed_lower",
                    "created_at",
                    "id",
                ),
                name="playthrough_display_order",
            ),
        )

    def __str__(self) -> str:
        return f"Playthrough {self.pk} of tracked game {self.player_game_id}"


class NaiveTimestamp(models.Func):
    """A date read as a wall-clock timestamp, in no zone at all.

    `Cast(..., DateTimeField())` asks for `timestamptz`, and the cast
    from a date to one is STABLE -- it reads the session's TimeZone --
    so PostgreSQL refuses any generated column built on it.
    """

    template = "(%(expressions)s)::timestamp"
    output_field = models.DateTimeField()


class PlayerSessionTimingMode(models.TextChoices):
    """What one session states about its time.

    The three words the timing payload's discriminator spells.
    """

    TIMED = "timed", "Timed"
    DURATION_ONLY = "duration_only", "Duration only"
    CORRECTED = "corrected", "Corrected"


class PlayerSessionQuerySet(RemovableMixin, models.QuerySet["PlayerSession"]):
    """The marks that hide a session.

    Not the catalog game's, deliberately. `blocking_referrer` reads
    `alive()` to refuse removing a run that sessions name; a catalog
    mark here would hide them from that check, leave the run
    removable, and restoring the game would leave live sessions
    naming a removed run. `library_sessions()` states that mark itself.
    """

    ancestor_marks = ("playthrough", "playthrough__player_game")


type SessionInstantColumn = Literal["started_at", "ended_at"]


def session_day_of(column: SessionInstantColumn) -> Cast:
    """The instant's day in the row's zone."""
    return Cast(Func(F("day_zone"), F(column), function="timezone"), models.DateField())


class PlayerSession(ProjectionModel):
    """One session a library recorded, projected from its events."""

    objects = PlayerSessionQuerySet.as_manager()

    #: The game is two parents away; the filter compares against it.
    comparison_through = (("playthrough__player_game__game", "Game"),)

    id = UUIDv7Field(
        primary_key=True,
        editable=False,
        #: The creation event's aggregate_id, evaluated once.
        default=models.NOT_PROVIDED,
        db_default=models.NOT_PROVIDED,
    )
    playthrough = models.ForeignKey(
        Playthrough,
        #: No cascade may destroy a projection row.
        on_delete=models.RESTRICT,
        related_name="sessions",
    )
    #: RESTRICT: only the projector changes rows.
    device = models.ForeignKey(
        "Device",
        on_delete=models.RESTRICT,
        null=True,
        related_name="player_sessions",
    )
    #: A Release of the run's game; null unstated.
    release = models.ForeignKey(
        Release, on_delete=models.RESTRICT, null=True, related_name="+"
    )
    #: Every column below is stated by the creation event and carries no
    #: default, so `_required_columns` holds the handler to naming it.
    timing_mode = models.CharField(max_length=13, choices=PlayerSessionTimingMode)
    started_at = models.DateTimeField(null=True)
    #: The zone the clock stood in when the endpoint was committed.
    #: Null is a zone nobody stated.
    started_at_zone = models.CharField(max_length=64, null=True)
    ended_at = models.DateTimeField(null=True)
    ended_at_zone = models.CharField(max_length=64, null=True)
    #: The written calendar day of a Duration-only session, which no
    #: zone converts and no restatement moves.
    stated_day = models.DateField(null=True)
    #: Duration-only states its whole duration here; Corrected states
    #: the override that replaces elapsed time.
    stated_duration = models.DurationField(null=True)
    #: The zone this library counts days in, not where the player sat.
    day_zone = models.CharField(max_length=64, null=True)
    effective_day = models.GeneratedField(
        expression=Coalesce(F("stated_day"), session_day_of("started_at")),
        output_field=models.DateField(),
        db_persist=True,
        editable=False,
    )
    effective_duration = models.GeneratedField(
        expression=Coalesce(
            F("stated_duration"),
            F("ended_at") - F("started_at"),
            Value(timedelta(0)),
        ),
        output_field=models.DurationField(),
        db_persist=True,
        editable=False,
    )
    #: Ordering alone, and never rendered: a Duration-only row has no
    #: instant, so this invents midnight UTC of its written day to keep
    #: one total key across all three modes. The cast to a naive
    #: timestamp is load-bearing -- `date` to `timestamptz` is STABLE,
    #: and PostgreSQL refuses a generated column built on it.
    sort_instant = models.GeneratedField(
        expression=Coalesce(
            F("started_at"),
            Func(
                Value("UTC"),
                NaiveTimestamp(F("stated_day")),
                function="timezone",
            ),
        ),
        output_field=models.DateTimeField(),
        db_persist=True,
        editable=False,
    )
    note = models.TextField()
    emulated = models.BooleanField()
    #: The creation event's recorded_at.
    created_at = models.DateTimeField(editable=False)
    #: The remove event's recorded_at; null means live.
    removed_at = models.DateTimeField(null=True, default=None, editable=False)

    class Meta:
        get_latest_by = "sort_instant"
        indexes = (
            #: The day-grained reads: today, the last seven days, the
            #: stats page's grouping and its year scope.
            models.Index(
                fields=("library", "effective_day", "id"),
                name="playersession_day_order",
            ),
            #: The list order, `get_latest_by`, and the navbar's keyset.
            models.Index(
                fields=("library", "sort_instant", "id"),
                name="playersession_sort_order",
            ),
            #: When one run was last played.
            models.Index(
                fields=("playthrough", "effective_day"),
                name="playersession_run_day",
            ),
        )
        constraints = (
            library_identity_constraint(),
            models.CheckConstraint(
                condition=Q(timing_mode__in=tuple(PlayerSessionTimingMode.values)),
                name="playersession_timing_mode_known",
            ),
            models.CheckConstraint(
                condition=~Q(timing_mode=PlayerSessionTimingMode.TIMED)
                | Q(
                    started_at__isnull=False,
                    stated_day__isnull=True,
                    stated_duration__isnull=True,
                    day_zone__isnull=False,
                ),
                name="playersession_timed_columns",
            ),
            models.CheckConstraint(
                condition=~Q(timing_mode=PlayerSessionTimingMode.DURATION_ONLY)
                | Q(
                    started_at__isnull=True,
                    started_at_zone__isnull=True,
                    ended_at__isnull=True,
                    ended_at_zone__isnull=True,
                    day_zone__isnull=True,
                    stated_day__isnull=False,
                    stated_duration__isnull=False,
                ),
                name="playersession_duration_only_columns",
            ),
            models.CheckConstraint(
                condition=~Q(timing_mode=PlayerSessionTimingMode.CORRECTED)
                | Q(
                    started_at__isnull=False,
                    ended_at__isnull=False,
                    stated_day__isnull=True,
                    stated_duration__isnull=False,
                    day_zone__isnull=False,
                ),
                name="playersession_corrected_columns",
            ),
            #: Equal is admitted: a zero-length session is a correction
            #: somebody may state.
            models.CheckConstraint(
                condition=Q(ended_at__isnull=True) | Q(ended_at__gte=F("started_at")),
                name="playersession_end_after_start",
            ),
            #: Not negative, rather than the command's stricter rule.
            #: The database admits a superset of what the command
            #: admits: a CHECK the command does not know would answer
            #: an IntegrityError nothing maps, after the lock is taken.
            models.CheckConstraint(
                condition=Q(stated_duration__isnull=True)
                | Q(stated_duration__gte=timedelta(0)),
                name="playersession_duration_not_negative",
            ),
            models.CheckConstraint(
                condition=(
                    Q(started_at_zone__isnull=True) | Q(started_at__isnull=False)
                )
                & (Q(ended_at_zone__isnull=True) | Q(ended_at__isnull=False)),
                name="playersession_zone_needs_its_instant",
            ),
            #: An empty string is not a zone; null already means unset.
            #:
            #: `day_zone` is absent on purpose. `effective_day` is
            #: generated before any constraint runs, so a blank or
            #: unknown zone there is already a DataError -- one nothing
            #: maps to an answer, which is why the command refuses a
            #: zone neither tzdata knows before the append begins.
            models.CheckConstraint(
                condition=~Q(started_at_zone="") & ~Q(ended_at_zone=""),
                name="playersession_zone_not_blank",
            ),
            #: The backstop. Every day-grained read keys on this column,
            #: and any hole the rules above leave arrives here.
            models.CheckConstraint(
                condition=Q(effective_day__isnull=False),
                name="playersession_effective_day_stated",
            ),
        )

    def __str__(self) -> str:
        return f"Session {self.pk} of run {self.playthrough_id}"


class LibraryCalendar(ProjectionModel):
    """The zone a library counts days in, projected from its events."""

    id = UUIDv7Field(
        primary_key=True,
        editable=False,
        #: The library's id: one calendar per library.
        default=models.NOT_PROVIDED,
        db_default=models.NOT_PROVIDED,
    )
    day_zone = models.CharField(max_length=64)

    class Meta:
        constraints = (
            library_identity_constraint(),
            #: The pk is the library's id; uniqueness per library follows.
            models.CheckConstraint(
                condition=Q(id=F("library")),
                name="games_librarycalendar_id_is_library",
            ),
        )


class HistoricalPlaytimeProvenance(models.TextChoices):
    """Where a stated duration came from."""

    ESTIMATED = "estimated", "Estimated"
    MANUALLY_ENTERED = "manually_entered", "Manually entered"
    EXTERNALLY_MEASURED = "externally_measured", "Externally measured"


class HistoricalPlaytimeQuerySet(RemovableMixin, models.QuerySet["HistoricalPlaytime"]):
    """The marks that hide a record."""

    ancestor_marks = ("player_game",)


class HistoricalPlaytime(ProjectionModel):
    """Playtime stated without sittings, from events."""

    objects = HistoricalPlaytimeQuerySet.as_manager()

    #: The game is one parent away.
    comparison_through = (("player_game__game", "Game"),)

    id = UUIDv7Field(
        primary_key=True,
        editable=False,
        #: The creation event's aggregate_id.
        default=models.NOT_PROVIDED,
        db_default=models.NOT_PROVIDED,
    )
    player_game = models.ForeignKey(
        PlayerGame,
        #: No cascade destroys a projection row.
        on_delete=models.RESTRICT,
        related_name="historical_playtime",
    )
    #: Stated by the event; the projector names each.
    duration = models.DurationField()
    #: Null is a when nobody knows; no default.
    when = TemporalValueField(default=models.NOT_PROVIDED)
    when_lower = models.GeneratedField(
        expression=TemporalLowerBound("when"),
        output_field=models.DateField(null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    when_upper = models.GeneratedField(
        expression=TemporalUpperBound("when"),
        output_field=models.DateField(null=True),
        null=True,
        serialize=False,
        db_persist=True,
        editable=False,
    )
    provenance = models.CharField(max_length=19, choices=HistoricalPlaytimeProvenance)
    #: No cascade destroys a projection row.
    device = models.ForeignKey(
        "Device",
        on_delete=models.RESTRICT,
        null=True,
        related_name="historical_playtime",
    )
    #: A Release of the record's game; null unstated.
    release = models.ForeignKey(
        Release, on_delete=models.RESTRICT, null=True, related_name="+"
    )
    emulated = models.BooleanField()
    note = models.TextField()
    #: The creation event's recorded_at.
    created_at = models.DateTimeField(editable=False)
    #: The remove event's recorded_at; null live.
    removed_at = models.DateTimeField(null=True, default=None, editable=False)
    #: Latest restate's recorded_at; null, never restated.
    restated_at = models.DateTimeField(null=True, default=None, editable=False)
    #: The session this record came from.
    reclassified_from = models.ForeignKey(
        "PlayerSession",
        #: No cascade destroys a projection row.
        on_delete=models.RESTRICT,
        null=True,
        default=None,
        related_name="reclassified_records",
    )

    class Meta:
        indexes = (
            #: Containment reads: period, then key.
            models.Index(
                fields=("library", "when_lower", "id"),
                name="historicalplaytime_when_order",
            ),
        )
        constraints = (
            library_identity_constraint(),
            models.CheckConstraint(
                condition=Q(duration__gt=timedelta(0)),
                name="historicalplaytime_duration_positive",
            ),
            models.CheckConstraint(
                condition=Q(provenance__in=HistoricalPlaytimeProvenance.values),
                name="historicalplaytime_provenance_known",
            ),
            #: Backstop for the commands' guard.
            models.UniqueConstraint(
                fields=("reclassified_from",),
                condition=Q(reclassified_from__isnull=False, removed_at__isnull=True),
                name="historicalplaytime_one_live_per_session",
            ),
        )


class HistoricalPlaytimeRunQuerySet(models.QuerySet["HistoricalPlaytimeRun"]):
    """A join row lives while its record."""

    def alive(self):
        return self.filter(
            record__removed_at__isnull=True,
            record__player_game__removed_at__isnull=True,
        )


class HistoricalPlaytimeRun(ProjectionModel):
    """One run a record names."""

    objects = HistoricalPlaytimeRunQuerySet.as_manager()

    id = UUIDv7Field(
        primary_key=True,
        editable=False,
        #: The statement's id for this pair.
        default=models.NOT_PROVIDED,
        db_default=models.NOT_PROVIDED,
    )
    record = models.ForeignKey(
        HistoricalPlaytime, on_delete=models.RESTRICT, related_name="runs"
    )
    playthrough = models.ForeignKey(
        Playthrough,
        on_delete=models.RESTRICT,
        related_name="historical_playtime_runs",
    )

    class Meta:
        constraints = (
            library_identity_constraint(),
            models.UniqueConstraint(
                fields=("record", "playthrough"),
                name="historicalplaytimerun_once_per_record",
            ),
        )


class EntryAccess(models.TextChoices):
    """How a library reaches a Release."""

    OWNED = "owned", "Owned"
    BORROWED = "borrowed", "Borrowed"
    RENTED = "rented", "Rented"
    SUBSCRIPTION = "subscription", "Subscription"
    TRIAL = "trial", "Trial"
    DEMO = "demo", "Demo"
    PIRATED = "pirated", "Pirated"


class EntryFormat(models.TextChoices):
    """The shape a copy takes."""

    PHYSICAL = "physical", "Physical"
    DIGITAL = "digital", "Digital"
    UNKNOWN = "unknown", "Unknown"


ENTRY_ACQUISITION_COLUMNS = OpeningEndpointColumns(
    name="acquisition",
    model_label="games.LibraryEntry",
    when="acquired",
    lower="acquired_lower",
    upper="acquired_upper",
    marker="acquisition_recorded_at",
    note="acquisition_note",
)

#: How a copy leaves the library's hands.
ENTRY_WAYS: EndWays = (
    EndWay.UNSTATED,
    EndWay.RETURNED,
    EndWay.EXPIRED,
    EndWay.REVOKED,
    EndWay.REFUNDED,
    EndWay.SOLD,
    EndWay.LOST,
    EndWay.GIVEN_AWAY,
    EndWay.BROKEN,
    EndWay.STOLEN,
)

ENTRY_ACCESS_END_COLUMNS = EndpointColumns(
    name="access_end",
    model_label="games.LibraryEntry",
    when="access_ended",
    lower="access_ended_lower",
    upper="access_ended_upper",
    marker="access_end_recorded_at",
    note="access_end_note",
    way=WayColumn("access_end_way", ENTRY_WAYS),
)


class LibraryEntryQuerySet(RemovableMixin, models.QuerySet["LibraryEntry"]):
    """Entry marks; catalog marks are the reads'."""

    ancestor_marks = ("player_game",)


class LibraryEntry(ProjectionModel, ReferencedRow):
    """One copy of a Release; Entries writes."""

    objects = LibraryEntryQuerySet.as_manager()

    #: The game is one parent away.
    comparison_through = (("player_game__game", "Game"),)

    #: The creation event's aggregate id.
    id = UUIDv7Field(
        primary_key=True,
        editable=False,
        default=models.NOT_PROVIDED,
        db_default=models.NOT_PROVIDED,
    )
    player_game = models.ForeignKey(
        "PlayerGame", on_delete=models.RESTRICT, related_name="entries"
    )
    #: A Release of the tracked game; commands keep it.
    release = models.ForeignKey(Release, on_delete=models.RESTRICT, related_name="+")
    access = models.CharField(max_length=16, choices=EntryAccess)
    format = models.CharField(max_length=16, choices=EntryFormat)
    note = models.TextField(blank=True, default="")
    #: The day acquired; null unknown.
    acquired = endpoint_when()
    acquired_lower = endpoint_bound("acquired", "lower")
    acquired_upper = endpoint_bound("acquired", "upper")
    #: The creation's instant; every row holds one.
    acquisition_recorded_at = opening_marker()
    acquisition_note = endpoint_note()
    #: The day access ended; null unknown or unstated.
    access_ended = endpoint_when()
    access_ended_lower = endpoint_bound("access_ended", "lower")
    access_ended_upper = endpoint_bound("access_ended", "upper")
    #: Null is a copy the library holds.
    access_end_recorded_at = endpoint_marker()
    access_end_note = endpoint_note()
    #: One of ENTRY_WAYS; empty while held.
    access_end_way = endpoint_way(ENTRY_WAYS)
    #: The creation event's recorded_at.
    created_at = models.DateTimeField(editable=False)
    #: The remove event's recorded_at; null live.
    removed_at = models.DateTimeField(null=True, default=None, editable=False)

    class Meta:
        #: The person's word.
        verbose_name = "copy"
        verbose_name_plural = "copies"
        constraints = (
            library_identity_constraint(),
            *endpoint_constraints(ENTRY_ACCESS_END_COLUMNS),
            models.CheckConstraint(
                condition=Q(access__in=[word.value for word in EntryAccess]),
                name="games_libraryentry_access_known",
            ),
            models.CheckConstraint(
                condition=Q(format__in=[word.value for word in EntryFormat]),
                name="games_libraryentry_format_known",
            ),
        )
        indexes = (
            models.Index(
                fields=("library", "release"),
                condition=Q(removed_at__isnull=True),
                name="live_entry_per_release_idx",
            ),
        )

    def __str__(self) -> str:
        return f"{self.access}, {self.format}"


#: An ISO 4217 code, e.g. "EUR".
CURRENCY_CODE = "[A-Z]{3}"


class PurchaseKind(models.TextChoices):
    """What one purchase paid for."""

    GAME = "game", "Game"
    SEASON_PASS = "season_pass", "Season pass"
    BATTLE_PASS = "battle_pass", "Battle pass"
    UPGRADE = "upgrade", "Upgrade"


class PriceState(models.TextChoices):
    """What a stated price says."""

    PAID = "paid", "Paid"
    FREE = "free", "Free"
    UNKNOWN = "unknown", "Unknown"


def price_state_expression() -> models.Case:
    """The amount, read as a PriceState word."""
    return models.Case(
        models.When(amount__isnull=True, then=models.Value(PriceState.UNKNOWN)),
        models.When(amount=0, then=models.Value(PriceState.FREE)),
        default=models.Value(PriceState.PAID),
        output_field=models.CharField(),
    )


PURCHASE_DAY_COLUMNS = OpeningEndpointColumns(
    name="purchase",
    model_label="games.Purchase",
    when="purchased",
    lower="purchased_lower",
    upper="purchased_upper",
    marker="purchase_recorded_at",
    note="purchase_note",
)

PURCHASE_REFUND_COLUMNS = EndpointColumns(
    name="refund",
    model_label="games.Purchase",
    when="refunded",
    lower="refunded_lower",
    upper="refunded_upper",
    marker="refund_recorded_at",
    note="refund_note",
)


class PurchaseQuerySet(RemovableMixin, models.QuerySet["Purchase"]):
    """Purchase, entry and tracked-game marks."""

    ancestor_marks = ("entry", "entry__player_game")

    #: The library the valuation alias reads.
    _valuation_library: UserLibrary | None = None

    def _clone(self) -> PurchaseQuerySet:
        #: Django's hook; django-stubs declares no `_clone`.
        clone: PurchaseQuerySet = super()._clone()  # type: ignore[misc]
        clone._valuation_library = self._valuation_library
        return clone

    def annotated_for_filtering(
        self, library: UserLibrary | None = None
    ) -> PurchaseQuerySet:
        """Register the price and valuation aliases.

        As the run's condition aliases: a second call naming the
        same library is a no-op, one naming another is refused,
        and without a library the names resolve and refuse to
        compile. A library named after an unscoped call is
        refused too: filters may already hold the unscoped alias.
        """
        from games.reads.purchases import valuation_annotations

        if "valuation_amount" in self.query.annotations:
            if library is None or library == self._valuation_library:
                return self
            if self._valuation_library is None:
                raise ValueError(
                    "this queryset carries the unscoped valuation alias; "
                    "name the library at the first call"
                )
            raise ValueError(
                "this queryset already carries a valuation alias from "
                f"{self._valuation_library}; annotate once, at the read "
                "that states the scope"
            )
        rate_year, valuation = valuation_annotations(library)
        if library is None:
            return self.alias(price_state=price_state_expression(), **rate_year).alias(
                **valuation
            )
        queryset = self.annotate(
            price_state=price_state_expression(), **rate_year
        ).annotate(**valuation)
        queryset._valuation_library = library
        return queryset


class Purchase(ProjectionModel):
    """One transaction for one copy; Purchases writes."""

    objects = PurchaseQuerySet.as_manager()

    #: The game is two parents away.
    comparison_through = (("entry__player_game__game", "Game"),)

    #: The creation event's aggregate id.
    id = UUIDv7Field(
        primary_key=True,
        editable=False,
        default=models.NOT_PROVIDED,
        db_default=models.NOT_PROVIDED,
    )
    entry = models.ForeignKey(
        LibraryEntry, on_delete=models.RESTRICT, related_name="purchases"
    )
    kind = models.CharField(
        max_length=max(len(word) for word in PurchaseKind.values),
        choices=PurchaseKind,
    )
    name = models.CharField(max_length=255, blank=True, default="")
    #: Null unknown; zero free.
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, default=None
    )
    #: Blank exactly where amount is null.
    currency = models.CharField(max_length=3, blank=True, default="")
    note = models.TextField(blank=True, default="")
    #: The day bought; null unknown.
    purchased = endpoint_when()
    purchased_lower = endpoint_bound("purchased", "lower")
    purchased_upper = endpoint_bound("purchased", "upper")
    #: The creation's instant; every row holds one.
    purchase_recorded_at = opening_marker()
    purchase_note = endpoint_note()
    #: The day refunded; null unknown or unstated.
    refunded = endpoint_when()
    refunded_lower = endpoint_bound("refunded", "lower")
    refunded_upper = endpoint_bound("refunded", "upper")
    #: Null is a purchase not refunded.
    refund_recorded_at = endpoint_marker()
    refund_note = endpoint_note()
    #: The creation event's recorded_at.
    created_at = models.DateTimeField(editable=False)
    #: The remove event's recorded_at; null live.
    removed_at = models.DateTimeField(null=True, default=None, editable=False)

    #: The bound columns a comparison may name.
    comparable_temporal_bounds: ClassVar[Mapping[str, str]] = {
        "purchased_lower": "Purchased (earliest)",
        "purchased_upper": "Purchased (latest)",
        "refunded_lower": "Refunded (earliest)",
        "refunded_upper": "Refunded (latest)",
    }

    class Meta:
        verbose_name = "purchase"
        verbose_name_plural = "purchases"
        constraints = (
            library_identity_constraint(),
            models.CheckConstraint(
                condition=Q(kind__in=[word.value for word in PurchaseKind]),
                name="games_purchase_kind_known",
            ),
            models.CheckConstraint(
                condition=Q(amount__isnull=True) | Q(amount__gte=0),
                name="games_purchase_amount_not_negative",
            ),
            models.CheckConstraint(
                condition=Q(amount__isnull=True, currency="")
                | Q(amount__isnull=False, currency__regex=f"^{CURRENCY_CODE}$"),
                name="games_purchase_currency_where_amount",
            ),
        )
        indexes = (
            #: Not unique: one copy, many purchases.
            models.Index(
                fields=("library", "entry"),
                condition=Q(removed_at__isnull=True),
                name="live_purchase_per_entry_idx",
            ),
        )

    def __str__(self) -> str:
        return self.name or self.kind


class UserLibraryPreferences(models.Model):
    library = models.OneToOneField(
        UserLibrary,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    #: A device key, never a foreign key.
    default_device_id = models.UUIDField(null=True, blank=True, default=None)
    updated_at = models.DateTimeField(default=timezone.now)

    @property
    def default_device(self) -> Device | None:
        """The held default; an ended one keeps its key."""
        stored = self.stored_default_device
        if stored is None or stored.access_end_recorded_at is not None:
            return None
        return stored

    @property
    def stored_default_device(self) -> Device | None:
        """The live device the preference names, held or not."""
        if self.default_device_id is None:
            return None
        return (
            Device.objects.for_library(self.library)
            .filter(pk=self.default_device_id)
            .first()
        )

    def clean(self):
        super().clean()
        if (
            self.default_device_id is not None
            and not Device.objects.filter(
                library_id=self.library_id, pk=self.default_device_id
            ).exists()
        ):
            raise ValidationError(
                {"default_device": "Default device must belong to the same library."}
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def set_default_device(self, device: Device | None) -> bool:
        device_id = None if device is None else device.pk
        if self.default_device_id == device_id:
            return False
        self.default_device_id = device_id
        self.updated_at = timezone.now()
        self.save(update_fields=["default_device_id", "updated_at"])
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


class PurchaseValuation(models.Model):
    """A purchase's amount in the reporting currency."""

    id = UUIDv7Field(primary_key=True, editable=False)
    library = models.ForeignKey(UserLibrary, on_delete=models.CASCADE, related_name="+")
    #: Nothing keys into a projection row.
    purchase_id = models.UUIDField()
    target_currency = models.CharField(max_length=3)
    amount = models.DecimalField(max_digits=26, decimal_places=2)
    source_amount = models.DecimalField(max_digits=12, decimal_places=2)
    source_currency = models.CharField(max_length=3)
    rate_year = models.PositiveSmallIntegerField()
    rate = models.DecimalField(
        max_digits=24, decimal_places=RATE_PLACES, null=True, default=None
    )
    #: Provenance; currency is judged on inputs.
    version = models.PositiveBigIntegerField()
    calculated_at = models.DateTimeField()

    class Meta:
        constraints = (
            #: Publication keeps one target per library.
            models.UniqueConstraint(
                fields=("library", "purchase_id"),
                name="games_purchasevaluation_one_per_purchase",
            ),
            models.CheckConstraint(
                condition=Q(amount__gte=0) & Q(source_amount__gte=0),
                name="games_purchasevaluation_amounts_not_negative",
            ),
            models.CheckConstraint(
                condition=Q(
                    rate__isnull=True,
                    amount=F("source_amount"),
                )
                & (Q(source_currency=F("target_currency")) | Q(source_amount=0))
                | Q(rate__isnull=False, rate__gt=0)
                & ~Q(source_currency=F("target_currency"))
                & ~Q(source_amount=0),
                name="games_purchasevaluation_rate_where_needed",
            ),
            models.CheckConstraint(
                condition=Q(
                    source_currency__regex=f"^{CURRENCY_CODE}$",
                    target_currency__regex=f"^{CURRENCY_CODE}$",
                ),
                name="games_purchasevaluation_currency_codes",
            ),
        )


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
        #: Two reads the sequence does not serve.
        indexes = (
            models.Index(
                fields=("library", "correlation_id"),
                name="library_event_batch",
            ),
            models.Index(
                fields=("library", "aggregate_id"),
                name="library_event_aggregate",
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
