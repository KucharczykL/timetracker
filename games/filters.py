"""
Entity-specific filter types for the timetracker app.

Each filter class mirrors a Django model, with fields expressed as typed
criteria from common.criteria.  The to_q() method produces a Django Q object
ready for queryset.filter().

Inspired by Stash's filter architecture: each entity has an OperatorFilter
with AND/OR/NOT composition and typed criterion fields.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields, replace
from functools import cache
from typing import TYPE_CHECKING, Any, ClassVar, Final, Literal, NamedTuple

if TYPE_CHECKING:
    from games.models import (
        Device,
        Game,
        HistoricalPlaytime,
        LibraryEntry,
        LibraryEvent,
        Platform,
        PlayerSession,
        Playthrough,
        Purchase,
        UserLibrary,
    )

import builtins

from django.db.models import Exists, Model, OuterRef, Q, QuerySet, TextChoices
from django.urls import reverse
from django.utils.http import urlencode

from common.criteria import (
    AggregateCriterion,
    AggregateSpec,
    AttrName,
    BoolCriterion,
    ChoiceCriterion,
    ChoiceMeta,
    DateCriterion,
    FieldHandler,
    FilterError,
    FilterField,
    FilterQueryContext,
    FilterQueryContextRequired,
    FloatCriterion,
    IntCriterion,
    ModelFieldBundle,
    ModelKey,
    Modifier,
    OperatorFilter,
    StringCriterion,
    UUIDMultiCriterion,
    _Criterion,
    beyond_bound_handler,
    bool_isnull_handler,
    bool_running_handler,
    calendar_day_handler,
    comparable_columns,
    days_touched_handler,
    duration_hours_handler,
    field_metadata,
    filter_from_json,
    filter_to_json,
    relation_to_q,
    search_q,
    temporal_interval_handler,
)
from games.conversion_review import ORIGIN, Category
from games.endpoint_fields import EndpointColumnsBase
from games.endpoints import (
    DEVICE_ACCESS_END,
    ENTRY_ACCESS_END,
    ENTRY_ACQUISITION,
    PLAYTHROUGH_COMPLETION,
    PLAYTHROUGH_START,
    PURCHASE_DAY,
    PURCHASE_REFUND,
)
from games.models import (
    EntryAccess,
    EntryFormat,
    PlayerSessionTimingMode,
    PriceState,
    SessionInstantColumn,
    session_day_of,
)
from games.reads.playthrough_activity import RunActivity
from games.reads.prerelease_play import PRERELEASE_PLAY
from timetracker.settings_registry import DEFAULT_PAGE_SIZE

# ── FindFilter (sort / pagination) ─────────────────────────────────────────


@dataclass
class FindFilter:
    """Sorting and pagination, separate from filtering criteria (Stash-style).

    Free-text search is not here — it is a ``search`` criterion on each
    ``OperatorFilter`` (rendered by the filter bar's search box, carried in the
    ``?filter=`` JSON).
    """

    page: int = 1
    per_page: int = DEFAULT_PAGE_SIZE
    sort: str | None = None  # e.g. "-created_at" (a signed SortString)
    per_page_explicit: bool = field(default=False, kw_only=True)

    @property
    def per_page_override(self) -> int | None:
        """Explicit URL override, if any."""
        return self.per_page if self.per_page_explicit else None


def session_day_handler(column: SessionInstantColumn) -> FieldHandler:
    """A session instant's day, in its zone."""

    def handler(criterion: _Criterion, context: FilterQueryContext | None) -> Q:
        if not isinstance(criterion, DateCriterion):
            raise FilterError(f"{column} compares a day; state a date")
        return criterion.to_q_on(session_day_of(column))

    return handler


#: The held copy's column a facet reads.
type HeldEntryColumn = Literal["access", "format"]


def held_entry_word_handler(column: HeldEntryColumn) -> FieldHandler:
    """A game by its held copies' words."""

    def handler(criterion: _Criterion, context: FilterQueryContext | None) -> Q:
        if not isinstance(criterion, ChoiceCriterion):
            raise FilterError(f"{column} picks words; state a list")
        if context is None:
            raise FilterQueryContextRequired(f"{column} reads the library's copies")
        from games.models import LibraryEntry

        held = context.queryset_for(LibraryEntry).filter(
            access_end_recorded_at__isnull=True
        )

        def holding(copies: QuerySet[LibraryEntry]) -> Q:
            return Q(pk__in=copies.values("player_game__game"))

        def holding_any(words: list[str]) -> Q:
            return holding(held.filter(**{f"{column}__in": words}))

        modifier = criterion.modifier
        if modifier == Modifier.IS_NULL:
            return ~holding(held)
        if modifier == Modifier.NOT_NULL:
            return holding(held)
        words = criterion.value
        if not words:
            q = Q()
        elif modifier in (Modifier.INCLUDES, Modifier.EQUALS):
            q = holding_any(words)
        elif modifier in (Modifier.EXCLUDES, Modifier.NOT_EQUALS):
            q = ~holding_any(words)
        elif modifier == Modifier.INCLUDES_ONLY:
            q = holding(held) & ~holding(held.exclude(**{f"{column}__in": words}))
        elif modifier == Modifier.INCLUDES_ALL:
            q = Q()
            for word in words:
                q &= holding(held.filter(**{column: word}))
        else:
            raise FilterError(f"Unsupported modifier {modifier} for {column}")
        if criterion.excludes:
            q &= ~holding_any(criterion.excludes)
        return q

    return handler


#: The rows tagged events reach.
type TaggedRows = Callable[[QuerySet[LibraryEvent, LibraryEvent]], Q]

_REVIEW_CHOICES: Final[tuple[ChoiceMeta, ...]] = tuple(
    ChoiceMeta(value=word.value, label=word.label) for word in Category
)
_REVIEW_VALUES: Final[frozenset[str]] = frozenset(Category.values)


def own_events(events: QuerySet[LibraryEvent, LibraryEvent]) -> Exists:
    """Events of the outer row itself."""
    return Exists(
        events.filter(library=OuterRef("library"), aggregate_id=OuterRef("pk"))
    )


def conversion_review_field(tagged: TaggedRows) -> FilterField:
    """A row by the conversion's review words."""

    def handler(criterion: _Criterion, context: FilterQueryContext | None) -> Q:
        if not isinstance(criterion, ChoiceCriterion):
            raise FilterError("conversion_review picks words; state a list")
        unknown = sorted({*criterion.value, *criterion.excludes} - _REVIEW_VALUES)
        if unknown:
            raise FilterError(f"conversion_review knows no word {unknown}")
        from games.models import LibraryEvent

        events = LibraryEvent.objects.filter(source_metadata__origin=ORIGIN)

        def any_of(words: list[str]) -> Q:
            return tagged(events.filter(source_metadata__review__has_any_keys=words))

        modifier = criterion.modifier
        if modifier == Modifier.IS_NULL:
            return ~any_of(sorted(_REVIEW_VALUES))
        if modifier == Modifier.NOT_NULL:
            return any_of(sorted(_REVIEW_VALUES))
        words = criterion.value
        if not words:
            matched = Q()
        elif modifier in (Modifier.INCLUDES, Modifier.EQUALS):
            matched = any_of(words)
        elif modifier in (Modifier.EXCLUDES, Modifier.NOT_EQUALS):
            matched = ~any_of(words)
        elif modifier == Modifier.INCLUDES_ALL:
            matched = Q()
            for word in words:
                matched &= any_of([word])
        elif modifier == Modifier.INCLUDES_ONLY:
            others = sorted(_REVIEW_VALUES - set(words))
            matched = any_of(words) & (~any_of(others) if others else Q())
        else:
            raise FilterError(f"Unsupported modifier {modifier} for conversion_review")
        if criterion.excludes:
            matched &= ~any_of(criterion.excludes)
        return matched

    return FilterField(
        handler=handler,
        label="Conversion review",
        choices=_REVIEW_CHOICES,
        nullable=True,
    )


def _purchase_tagged(events: QuerySet[LibraryEvent, LibraryEvent]) -> Q:
    return Q(own_events(events))


def _entry_tagged(events: QuerySet[LibraryEvent, LibraryEvent]) -> Q:
    """The copy's events, or its purchases'."""
    from games.models import Purchase

    #: A removed purchase still tags its copy.
    purchases = Purchase.objects.filter(entry=OuterRef("pk"))
    return Q(own_events(events)) | Q(Exists(purchases.filter(own_events(events))))


#: Columns that widen the Games list.
ADDON_FIELDS: Final[tuple[AttrName, ...]] = ("kind", "parent")


def _names_addon_column(column: str) -> bool:
    return column.split("__", 1)[0] in ADDON_FIELDS


def _word_choices(words: type[TextChoices]) -> tuple[ChoiceMeta, ...]:
    return tuple(
        ChoiceMeta(value=str(value), label=str(label)) for value, label in words.choices
    )


# ── GameFilter ─────────────────────────────────────────────────────────────


class NarrowingClauses(NamedTuple):
    """What the Playtime column narrows by; None counts all."""

    sessions: PlayerSessionFilter | None
    records: HistoricalPlaytimeFilter | None


@dataclass
class GameFilter(OperatorFilter):
    """Filter for the Game model."""

    AND: list[GameFilter] = field(default_factory=list)
    OR: list[GameFilter] = field(default_factory=list)
    NOT: list[GameFilter] = field(default_factory=list)

    name: StringCriterion | None = None
    sort_name: StringCriterion | None = None
    year_released: IntCriterion | None = None
    original_year_released: IntCriterion | None = None
    wikidata: StringCriterion | None = None
    platform: UUIDMultiCriterion | None = None  # Platform ids
    platform_group: ChoiceCriterion | None = None  # platform__group (str)
    status: ChoiceCriterion | None = None  # selectable filter widget
    mastered: BoolCriterion | None = None
    excluded_from_unfinished: BoolCriterion | None = None
    excluded_from_dropped: BoolCriterion | None = None
    playtime_hours: IntCriterion | None = None  # converted to timedelta on to_q()
    created_at: DateCriterion | None = None  # compared by calendar day
    updated_at: DateCriterion | None = None  # compared by calendar day
    #: The held copies' words.
    access: ChoiceCriterion | None = None
    format: ChoiceCriterion | None = None
    #: Naming either lists add-ons too.
    kind: ChoiceCriterion | None = None
    parent: UUIDMultiCriterion | None = None  # Game ids

    # Aggregates over the game's relations (count / sum / avg). The reducer +
    # relation accessor + source + unit live in ``GameFilter.aggregates`` (the
    # AggregateSpec table assigned below all filter classes); the criterion
    # carries only the numeric comparison and an optional scope sub-filter.
    session_count: AggregateCriterion | None = None
    session_average: AggregateCriterion | None = None  # average in hours
    purchase_count: AggregateCriterion | None = None  # distinct purchases per game
    playthrough_count: AggregateCriterion | None = None  # finished runs per game
    entry_count: AggregateCriterion | None = None  # live copies, ended included

    # The game's sessions' `effective_duration`, summed, in hours; a scope
    # on `timing_mode` narrows it to one mode's share.
    session_playtime_hours: AggregateCriterion | None = None

    # Cross-entity: sum of the game's purchase valuations
    purchase_price_total: AggregateCriterion | None = None  # sum of valuations

    # Free-text search (combines name + sort_name + platform name)
    search: StringCriterion | None = None

    # Cross-entity filters
    session_filter: PlayerSessionFilter | None = None
    purchase_filter: PurchaseFilter | None = None
    playthrough_filter: PlaythroughFilter | None = None
    historical_playtime_filter: HistoricalPlaytimeFilter | None = None
    platform_filter: PlatformFilter | None = None
    entry_filter: LibraryEntryFilter | None = None

    # Declarative attr→ORM-lookup table, kept in the old to_q emission order for a
    # reviewable diff (AND-composition makes the order semantically irrelevant).
    # TODO(py3.15, ~Oct 2026): these read-only ClassVar dict tables (here and in
    # forms.py Meta) exist to satisfy RUF012; once the project moves to 3.15,
    # consider the builtin ``frozendict`` (PEP 814) instead — but verify first
    # that RUF012 treats it as immutable and that each consumer accepts a
    # non-dict Mapping (frozendict does not subclass dict).
    fields: ClassVar[dict[str, FilterField]] = {
        "name": FilterField(),
        "sort_name": FilterField(),
        "year_released": FilterField(),
        "original_year_released": FilterField(),
        "wikidata": FilterField(),
        "platform": FilterField("platform__id", search_url="/api/platforms/search"),
        "status": FilterField(
            "tracked__status", metadata_lookup="player_games__status"
        ),
        "mastered": FilterField(
            "tracked__mastered", metadata_lookup="player_games__mastered"
        ),
        "excluded_from_unfinished": FilterField(
            "tracked__excluded_from_unfinished",
            metadata_lookup="player_games__excluded_from_unfinished",
        ),
        "excluded_from_dropped": FilterField(
            "tracked__excluded_from_dropped",
            metadata_lookup="player_games__excluded_from_dropped",
        ),
        "playtime_hours": FilterField(handler=duration_hours_handler("playtime")),
        "created_at": FilterField(
            handler=calendar_day_handler("created_at"), metadata_lookup="created_at"
        ),
        "updated_at": FilterField(
            handler=calendar_day_handler("updated_at"), metadata_lookup="updated_at"
        ),
        "platform_group": FilterField(
            "platform__group", search_url="/api/platforms/groups"
        ),
        "access": FilterField(
            handler=held_entry_word_handler("access"),
            label="Access",
            choices=_word_choices(EntryAccess),
            #: The picker asks for no held copy.
            nullable=True,
        ),
        "format": FilterField(
            handler=held_entry_word_handler("format"),
            label="Format",
            choices=_word_choices(EntryFormat),
            nullable=True,
        ),
        "kind": FilterField(label="Kind"),
        "parent": FilterField(
            "parent__id", search_url="/api/games/search", label="Add-on of"
        ),
    }
    #: A person reads "copy", never "entry".
    labels: ClassVar[dict[str, str]] = {"entry_count": "Copies"}

    # Overrides with a ``type`` field write ``builtins.type``.
    @classmethod
    def _comparison_model(cls) -> type[Game]:
        from games.models import Game

        return Game

    def names_addon_fields(self) -> bool:
        """Any boolean level names kind or parent."""
        if self.kind is not None or self.parent is not None:
            return True
        if any(
            _names_addon_column(comparison.left)
            or _names_addon_column(comparison.right)
            for comparison in self.field_comparisons
        ):
            return True
        return any(
            member.names_addon_fields() for member in (*self.AND, *self.OR, *self.NOT)
        )

    def of_every_kind(self) -> GameFilter:
        """This filter, over every kind.

        Under an `OR`, state it on each member:
        a node ORs its members with its own
        leaves, so a top-level one matches all.
        """
        from games.models import GameKind

        return replace(self, kind=GameFilter.where(kind=list(GameKind.values)).kind)

    def narrowing(self) -> NarrowingClauses:
        """The clauses the Playtime column narrows by.

        The top level's own, or -- for a filter that is one `OR` of
        members each stating one relation and nothing else, the shape
        the stats links state -- the members'. Anything else narrows
        nothing.
        """
        own = NarrowingClauses(self.session_filter, self.historical_playtime_filter)
        if own.sessions is not None or own.records is not None:
            return own
        if not self.OR or self.AND or self.NOT or self._states_a_leaf():
            return NarrowingClauses(None, None)
        sessions = records = None
        for member in self.OR:
            if member._states_a_leaf() or member.AND or member.OR or member.NOT:
                return NarrowingClauses(None, None)
            sessions = member.session_filter or sessions
            records = member.historical_playtime_filter or records
        return NarrowingClauses(sessions, records)

    def _states_a_leaf(self) -> bool:
        """Any criterion here, bar kind and parent."""
        return any(
            getattr(self, f.name) is not None
            for f in fields(self)
            if f.name
            not in ("AND", "OR", "NOT", "match", "field_comparisons", *ADDON_FIELDS)
            and not f.name.endswith("_filter")
        ) or bool(self.field_comparisons)

    def _extra_q(self, context: FilterQueryContext | None = None) -> Q:
        q = Q()

        # ── free-text search (OR across multiple fields) ──
        if self.search is not None:
            q &= search_q(self.search, "name", "sort_name", "platform__name")

        # Cross-entity sub-filters (ANY/NONE via each sub-filter's match mode)
        if self.session_filter is not None:
            from games.models import PlayerSession

            q &= relation_to_q(
                self.session_filter,
                context=context,
                related_model=PlayerSession,
                related_lookup=f"{SESSION_GAME}__id",
            )

        if self.purchase_filter is not None:
            from games.models import Purchase

            q &= relation_to_q(
                self.purchase_filter,
                context=context,
                related_model=Purchase,
                related_lookup="entry__player_game__game__id",
            )

        if self.playthrough_filter is not None:
            from games.models import Playthrough

            q &= relation_to_q(
                self.playthrough_filter,
                context=context,
                related_model=Playthrough,
                related_lookup="player_game__game__id",
            )

        if self.historical_playtime_filter is not None:
            from games.models import HistoricalPlaytime

            q &= relation_to_q(
                self.historical_playtime_filter,
                context=context,
                related_model=HistoricalPlaytime,
                related_lookup="player_game__game__id",
            )

        if self.platform_filter is not None:
            from games.models import Platform

            q &= relation_to_q(
                self.platform_filter,
                context=context,
                related_model=Platform,
                related_lookup="id",
                parent_field="platform__id",
            )

        if self.entry_filter is not None:
            from games.models import LibraryEntry

            q &= relation_to_q(
                self.entry_filter,
                context=context,
                related_model=LibraryEntry,
                related_lookup="player_game__game__id",
            )

        return q


#: A session reaches its game through the run; a game reaches its
#: sessions the other way round.
SESSION_GAME: Final = "playthrough__player_game__game"
#: The Releases a live session or record names.
PLAYED_RELEASE_SEARCH_URL: Final = "/api/releases/played"
GAME_SESSIONS: Final = "player_games__playthroughs__sessions"
GAME_PURCHASES: Final = "player_games__entries__purchases"


# ── PlayerSessionFilter ────────────────────────────────────────────────────


@dataclass
class PlayerSessionFilter(OperatorFilter):
    """Filter for the PlayerSession projection, in its own words."""

    AND: list[PlayerSessionFilter] = field(default_factory=list)
    OR: list[PlayerSessionFilter] = field(default_factory=list)
    NOT: list[PlayerSessionFilter] = field(default_factory=list)

    game: UUIDMultiCriterion | None = None  # through the run
    device: UUIDMultiCriterion | None = None  # filters on device_id
    emulated: BoolCriterion | None = None
    note: StringCriterion | None = None
    timing_mode: ChoiceCriterion | None = None
    is_running: BoolCriterion | None = None  # Timed, and no end yet
    playthrough_kind: ChoiceCriterion | None = None  # the run's kind
    #: Day before the start, or after completion.
    before_playthrough_start: BoolCriterion | None = None
    after_playthrough_completion: BoolCriterion | None = None
    release: UUIDMultiCriterion | None = None  # filters on release_id
    edition_kind: ChoiceCriterion | None = None  # the Release's Edition
    day: DateCriterion | None = None  # effective_day, the library's calendar
    started: DateCriterion | None = (
        None  # started_at's day in day_zone; null Duration-only
    )
    ended: DateCriterion | None = (
        None  # ended_at's day in day_zone; null running, Duration-only
    )
    duration_hours: IntCriterion | None = None  # effective_duration
    created_at: DateCriterion | None = None  # compared by calendar day

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity: sessions for games matching these criteria
    game_filter: GameFilter | None = None

    # Cross-entity: sessions for devices matching these criteria
    device_filter: DeviceFilter | None = None

    fields: ClassVar[dict[str, FilterField]] = {
        "game": FilterField(f"{SESSION_GAME}__id", search_url="/api/games/search"),
        "device": FilterField("device_id", search_url="/api/devices/search"),
        "emulated": FilterField(),
        "note": FilterField(),
        "timing_mode": FilterField(label="Timing"),
        "is_running": FilterField(
            handler=bool_running_handler(PlayerSessionTimingMode.TIMED),
            label="Running",
        ),
        "playthrough_kind": FilterField("playthrough__kind", label="Playthrough"),
        "before_playthrough_start": FilterField(
            handler=beyond_bound_handler(
                "effective_day",
                "playthrough__started_lower",
                "below",
                #: Demo play is not the run's.
                unless=PRERELEASE_PLAY,
            ),
            label="Before start",
        ),
        "after_playthrough_completion": FilterField(
            handler=beyond_bound_handler(
                "effective_day",
                "playthrough__completed_upper",
                "above",
                unless=PRERELEASE_PLAY,
            ),
            label="After completion",
        ),
        "release": FilterField("release_id", search_url=PLAYED_RELEASE_SEARCH_URL),
        "edition_kind": FilterField("release__edition__kind", label="Edition kind"),
        "day": FilterField("effective_day", label="Day"),
        "started": FilterField(
            handler=session_day_handler("started_at"),
            metadata_lookup="started_at",
            label="Started",
        ),
        "ended": FilterField(
            handler=session_day_handler("ended_at"),
            metadata_lookup="ended_at",
            label="Ended",
        ),
        "duration_hours": FilterField(
            handler=duration_hours_handler("effective_duration"),
            label="Duration (hours)",
        ),
        "created_at": FilterField(
            handler=calendar_day_handler("created_at"), metadata_lookup="created_at"
        ),
    }

    @classmethod
    def _comparison_model(cls) -> type[PlayerSession]:
        from games.models import PlayerSession

        return PlayerSession

    def _extra_q(self, context: FilterQueryContext | None = None) -> Q:
        q = Q()

        # Free-text search
        if self.search is not None:
            q &= search_q(
                self.search,
                f"{SESSION_GAME}__name",
                f"{SESSION_GAME}__platform__name",
                "device__name",
                "device__type",
            )

        # Cross-entity sub-filters: sessions for matching games / devices
        if self.game_filter is not None:
            from games.models import Game

            q &= relation_to_q(
                self.game_filter,
                context=context,
                related_model=Game,
                related_lookup="id",
                parent_field=f"{SESSION_GAME}__id",
            )

        if self.device_filter is not None:
            from games.models import Device

            q &= relation_to_q(
                self.device_filter,
                context=context,
                related_model=Device,
                related_lookup="id",
                parent_field="device_id",
            )

        return q


# ── DeviceFilter ───────────────────────────────────────────────────────────


class EndpointFilterFields(NamedTuple):
    """The leaves one stated endpoint offers a filter."""

    #: The stated day, as an interval.
    interval: FilterField
    #: Whether the act happened at all.
    stated: FilterField


def endpoint_filter_fields(
    endpoint: EndpointColumnsBase,
    *,
    stated_label: str,
    interval_label: str | None = None,
    stated_when_absent: bool = False,
) -> EndpointFilterFields:
    """An endpoint's leaves, placed by each filter.

    `stated_when_absent` asks the other way round: true
    where no act is stated.
    """
    return EndpointFilterFields(
        interval=FilterField(
            handler=temporal_interval_handler(
                endpoint.when, endpoint.lower, endpoint.upper
            ),
            metadata_lookup=endpoint.lower,
            label=interval_label,
        ),
        stated=FilterField(
            handler=bool_isnull_handler(endpoint.marker, invert=not stated_when_absent),
            label=stated_label,
        ),
    )


def way_filter_field(endpoint: EndpointColumnsBase, *, label: str) -> FilterField:
    """A way endpoint's way, as a choice."""
    if endpoint.way is None:
        raise TypeError(f"Endpoint {endpoint.name!r} states no way.")
    return FilterField(endpoint.way.column, label=label)


_START_FIELDS = endpoint_filter_fields(PLAYTHROUGH_START, stated_label="Has a start")
_COMPLETION_FIELDS = endpoint_filter_fields(
    PLAYTHROUGH_COMPLETION, stated_label="Has a completion"
)
_ACCESS_END_FIELDS = endpoint_filter_fields(
    DEVICE_ACCESS_END,
    interval_label="Day access ended",
    stated_label="Owned",
    stated_when_absent=True,
)


@dataclass
class DeviceFilter(OperatorFilter):
    """Filter for the Device model."""

    AND: list[DeviceFilter] = field(default_factory=list)
    OR: list[DeviceFilter] = field(default_factory=list)
    NOT: list[DeviceFilter] = field(default_factory=list)

    name: StringCriterion | None = None
    type: ChoiceCriterion | None = None
    created_at: DateCriterion | None = None  # compared by calendar day
    access_ended: DateCriterion | None = None  # the interval the end states
    is_owned: BoolCriterion | None = None  # no end of access stated
    access_end_way: ChoiceCriterion | None = None

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity: Devices that have sessions matching these criteria
    session_filter: PlayerSessionFilter | None = None

    # Declarative attr→ORM-lookup table, kept in the old to_q emission order for a
    # reviewable diff (AND-composition makes the order semantically irrelevant).
    fields: ClassVar[dict[str, FilterField]] = {
        "name": FilterField(),
        "type": FilterField(),
        "created_at": FilterField(
            handler=calendar_day_handler("created_at"), metadata_lookup="created_at"
        ),
        "access_ended": _ACCESS_END_FIELDS.interval,
        "is_owned": _ACCESS_END_FIELDS.stated,
        "access_end_way": way_filter_field(DEVICE_ACCESS_END, label="Status"),
    }

    @classmethod
    def _comparison_model(cls) -> builtins.type[Device]:
        from games.models import Device

        return Device

    def _extra_q(self, context: FilterQueryContext | None = None) -> Q:
        q = Q()

        # Free-text search
        if self.search is not None:
            q &= search_q(self.search, "name", "type")

        # Cross-entity sub-filter: devices that have matching sessions
        if self.session_filter is not None:
            from games.models import PlayerSession

            q &= relation_to_q(
                self.session_filter,
                context=context,
                related_model=PlayerSession,
                related_lookup="device_id",
            )

        return q


# ── PlatformFilter ─────────────────────────────────────────────────────────


@dataclass
class PlatformFilter(OperatorFilter):
    """Filter for the Platform model."""

    AND: list[PlatformFilter] = field(default_factory=list)
    OR: list[PlatformFilter] = field(default_factory=list)
    NOT: list[PlatformFilter] = field(default_factory=list)

    name: StringCriterion | None = None
    group: StringCriterion | None = None
    icon: StringCriterion | None = None
    created_at: DateCriterion | None = None  # compared by calendar day

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity
    game_filter: GameFilter | None = None
    purchase_filter: PurchaseFilter | None = None

    # Declarative attr→ORM-lookup table, kept in the old to_q emission order for a
    # reviewable diff (AND-composition makes the order semantically irrelevant).
    fields: ClassVar[dict[str, FilterField]] = {
        "name": FilterField(),
        "group": FilterField(),
        "icon": FilterField(),
        "created_at": FilterField(
            handler=calendar_day_handler("created_at"), metadata_lookup="created_at"
        ),
    }

    @classmethod
    def _comparison_model(cls) -> type[Platform]:
        from games.models import Platform

        return Platform

    def _extra_q(self, context: FilterQueryContext | None = None) -> Q:
        q = Q()

        # Free-text search
        if self.search is not None:
            q &= search_q(self.search, "name", "group")

        # Cross-entity sub-filters: platforms with matching games / purchases
        if self.game_filter is not None:
            from games.models import Game

            q &= relation_to_q(
                self.game_filter,
                context=context,
                related_model=Game,
                related_lookup="platform__id",
            )

        if self.purchase_filter is not None:
            from games.models import Purchase

            q &= relation_to_q(
                self.purchase_filter,
                context=context,
                related_model=Purchase,
                related_lookup="entry__release__platform__id",
            )

        return q


# ── PlaythroughFilter ──────────────────────────────────────────────────────

#: Built from RunActivity, so nothing drifts.
ACTIVITY_CHOICES: Final[tuple[ChoiceMeta, ...]] = tuple(
    ChoiceMeta(value=str(value), label=str(label))
    for value, label in RunActivity.choices
)


@dataclass
class PlaythroughFilter(OperatorFilter):
    """Filter for the Playthrough projection."""

    AND: list[PlaythroughFilter] = field(default_factory=list)
    OR: list[PlaythroughFilter] = field(default_factory=list)
    NOT: list[PlaythroughFilter] = field(default_factory=list)

    game: UUIDMultiCriterion | None = None  # player_game__game__id
    name: StringCriterion | None = None
    started: DateCriterion | None = None  # the interval the endpoint states
    completed: DateCriterion | None = None
    is_started: BoolCriterion | None = None  # the act, day or no day
    is_completed: BoolCriterion | None = None
    days_to_finish: IntCriterion | None = None  # date arithmetic, no column
    note: StringCriterion | None = None
    start_note: StringCriterion | None = None
    completion_note: StringCriterion | None = None
    created_at: DateCriterion | None = None  # compared by calendar day
    #: The clock's word: an alias, not column.
    activity: ChoiceCriterion | None = None

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity: runs at games matching these criteria
    game_filter: GameFilter | None = None

    #: Old presets still spell `completed` as `ended`.
    renamed_fields: ClassVar[Mapping[str, str]] = {"ended": "completed"}

    fields: ClassVar[dict[str, FilterField]] = {
        "game": FilterField("player_game__game__id", search_url="/api/games/search"),
        "name": FilterField(),
        "started": _START_FIELDS.interval,
        "completed": _COMPLETION_FIELDS.interval,
        "is_started": _START_FIELDS.stated,
        "is_completed": _COMPLETION_FIELDS.stated,
        "days_to_finish": FilterField(
            handler=days_touched_handler("started_lower", "completed_upper"),
            label="Days to finish",
        ),
        "note": FilterField(),
        "start_note": FilterField(),
        "completion_note": FilterField(),
        "created_at": FilterField(
            handler=calendar_day_handler("created_at"), metadata_lookup="created_at"
        ),
        "activity": FilterField(
            #: Delegate: a hand-built Q drops the modifier.
            handler=lambda criterion, context: criterion.to_q("activity"),
            label="Activity",
            choices=ACTIVITY_CHOICES,
            #: Null for completed runs; the picker asks.
            nullable=True,
        ),
    }

    @classmethod
    def _comparison_model(cls) -> type[Playthrough]:
        from games.models import Playthrough

        return Playthrough

    def _extra_q(self, context: FilterQueryContext | None = None) -> Q:
        q = Q()

        #: A blank name is stored nowhere.
        if self.search is not None:
            q &= search_q(
                self.search,
                "player_game__game__name",
                "name",
                "note",
                "start_note",
                "completion_note",
            )

        if self.game_filter is not None:
            from games.models import Game

            q &= relation_to_q(
                self.game_filter,
                context=context,
                related_model=Game,
                related_lookup="id",
                parent_field="player_game__game__id",
            )

        return q


# ── HistoricalPlaytimeFilter ───────────────────────────────────────────────


@dataclass
class HistoricalPlaytimeFilter(OperatorFilter):
    """Filter for the HistoricalPlaytime projection."""

    AND: list[HistoricalPlaytimeFilter] = field(default_factory=list)
    OR: list[HistoricalPlaytimeFilter] = field(default_factory=list)
    NOT: list[HistoricalPlaytimeFilter] = field(default_factory=list)

    game: UUIDMultiCriterion | None = None  # player_game__game__id
    provenance: ChoiceCriterion | None = None
    device: UUIDMultiCriterion | None = None  # filters on device_id
    release: UUIDMultiCriterion | None = None  # filters on release_id
    edition_kind: ChoiceCriterion | None = None  # the Release's Edition
    emulated: BoolCriterion | None = None
    duration_hours: IntCriterion | None = None
    when: DateCriterion | None = None  # the interval the record states
    note: StringCriterion | None = None
    created_at: DateCriterion | None = None  # compared by calendar day

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity: matching games and devices
    game_filter: GameFilter | None = None
    device_filter: DeviceFilter | None = None

    fields: ClassVar[dict[str, FilterField]] = {
        "game": FilterField("player_game__game__id", search_url="/api/games/search"),
        "provenance": FilterField(),
        "device": FilterField("device_id", search_url="/api/devices/search"),
        "release": FilterField("release_id", search_url=PLAYED_RELEASE_SEARCH_URL),
        "edition_kind": FilterField("release__edition__kind", label="Edition kind"),
        "emulated": FilterField(),
        "duration_hours": FilterField(
            handler=duration_hours_handler("duration"),
            label="Duration (hours)",
        ),
        "when": FilterField(
            handler=temporal_interval_handler("when", "when_lower", "when_upper"),
            metadata_lookup="when_lower",
            label="When",
        ),
        "note": FilterField(),
        "created_at": FilterField(
            handler=calendar_day_handler("created_at"), metadata_lookup="created_at"
        ),
    }

    @classmethod
    def _comparison_model(cls) -> type[HistoricalPlaytime]:
        from games.models import HistoricalPlaytime

        return HistoricalPlaytime

    def _extra_q(self, context: FilterQueryContext | None = None) -> Q:
        q = Q()

        if self.search is not None:
            q &= search_q(
                self.search,
                "player_game__game__name",
                "player_game__game__platform__name",
                "device__name",
                "note",
            )

        if self.game_filter is not None:
            from games.models import Game

            q &= relation_to_q(
                self.game_filter,
                context=context,
                related_model=Game,
                related_lookup="id",
                parent_field="player_game__game__id",
            )

        if self.device_filter is not None:
            from games.models import Device

            q &= relation_to_q(
                self.device_filter,
                context=context,
                related_model=Device,
                related_lookup="id",
                parent_field="device_id",
            )

        return q


# ── LibraryEntryFilter ─────────────────────────────────────────────────────


_ACQUISITION_FIELDS = endpoint_filter_fields(
    ENTRY_ACQUISITION, interval_label="Acquired", stated_label="Acquired"
)
_ENTRY_END_FIELDS = endpoint_filter_fields(
    ENTRY_ACCESS_END, interval_label="Day access ended", stated_label="Ended"
)


@dataclass
class LibraryEntryFilter(OperatorFilter):
    """Filter for the LibraryEntry projection."""

    AND: list[LibraryEntryFilter] = field(default_factory=list)
    OR: list[LibraryEntryFilter] = field(default_factory=list)
    NOT: list[LibraryEntryFilter] = field(default_factory=list)

    access: ChoiceCriterion | None = None
    format: ChoiceCriterion | None = None
    acquired: DateCriterion | None = None  # the interval the day states
    is_ended: BoolCriterion | None = None  # an end of access is stated
    access_ended: DateCriterion | None = None  # the interval the end states
    access_end_way: ChoiceCriterion | None = None
    platform: UUIDMultiCriterion | None = None  # the Release's platform
    game: UUIDMultiCriterion | None = None  # player_game__game__id
    edition_kind: ChoiceCriterion | None = None
    note: StringCriterion | None = None
    created_at: DateCriterion | None = None  # compared by calendar day
    conversion_review: ChoiceCriterion | None = None

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity: copies of games matching these criteria
    game_filter: GameFilter | None = None
    purchase_filter: PurchaseFilter | None = None

    fields: ClassVar[dict[str, FilterField]] = {
        "access": FilterField(),
        "format": FilterField(),
        "acquired": _ACQUISITION_FIELDS.interval,
        "is_ended": _ENTRY_END_FIELDS.stated,
        "access_ended": _ENTRY_END_FIELDS.interval,
        "access_end_way": way_filter_field(ENTRY_ACCESS_END, label="Way"),
        "platform": FilterField(
            "release__platform__id", search_url="/api/platforms/search"
        ),
        "game": FilterField("player_game__game__id", search_url="/api/games/search"),
        "edition_kind": FilterField("release__edition__kind", label="Edition"),
        "note": FilterField(),
        "created_at": FilterField(
            handler=calendar_day_handler("created_at"), metadata_lookup="created_at"
        ),
        "conversion_review": conversion_review_field(_entry_tagged),
    }

    @classmethod
    def _comparison_model(cls) -> type[LibraryEntry]:
        from games.models import LibraryEntry

        return LibraryEntry

    def _extra_q(self, context: FilterQueryContext | None = None) -> Q:
        q = Q()

        if self.search is not None:
            q &= search_q(
                self.search,
                "player_game__game__name",
                "release__platform__name",
                "note",
            )

        if self.game_filter is not None:
            from games.models import Game

            q &= relation_to_q(
                self.game_filter,
                context=context,
                related_model=Game,
                related_lookup="id",
                parent_field="player_game__game__id",
            )

        if self.purchase_filter is not None:
            from games.models import Purchase

            q &= relation_to_q(
                self.purchase_filter,
                context=context,
                related_model=Purchase,
                related_lookup="entry__id",
            )

        return q


# ── PurchaseFilter ─────────────────────────────────────────────────────────

_PURCHASE_DAY_FIELDS = endpoint_filter_fields(
    PURCHASE_DAY, interval_label="Purchased", stated_label="Purchased"
)
_REFUND_FIELDS = endpoint_filter_fields(
    PURCHASE_REFUND, interval_label="Day refunded", stated_label="Refunded"
)


@dataclass
class PurchaseFilter(OperatorFilter):
    """Filter for the Purchase projection."""

    AND: list[PurchaseFilter] = field(default_factory=list)
    OR: list[PurchaseFilter] = field(default_factory=list)
    NOT: list[PurchaseFilter] = field(default_factory=list)

    kind: ChoiceCriterion | None = None
    name: StringCriterion | None = None
    note: StringCriterion | None = None
    amount: FloatCriterion | None = None  # null is unknown
    currency: StringCriterion | None = None
    price_state: ChoiceCriterion | None = None
    #: The current valuation; an alias.
    valuation: FloatCriterion | None = None
    purchased: DateCriterion | None = None  # the interval the day states
    refunded: DateCriterion | None = None  # the interval the refund states
    is_refunded: BoolCriterion | None = None
    access: ChoiceCriterion | None = None  # the copy's
    format: ChoiceCriterion | None = None
    platform: UUIDMultiCriterion | None = None  # the copy's Release's
    game: UUIDMultiCriterion | None = None
    created_at: DateCriterion | None = None  # compared by calendar day
    conversion_review: ChoiceCriterion | None = None

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity: the copy, and its game
    entry_filter: LibraryEntryFilter | None = None
    game_filter: GameFilter | None = None

    fields: ClassVar[dict[str, FilterField]] = {
        "kind": FilterField(),
        "name": FilterField(),
        "note": FilterField(),
        "amount": FilterField(),
        "currency": FilterField(),
        "price_state": FilterField(
            #: Delegate: a hand-built Q drops the modifier.
            handler=lambda criterion, context: criterion.to_q("price_state"),
            label="Price",
            choices=_word_choices(PriceState),
            nullable=False,
        ),
        "valuation": FilterField(
            handler=lambda criterion, context: criterion.to_q("valuation_amount"),
            label="Valuation",
            nullable=True,
        ),
        "purchased": _PURCHASE_DAY_FIELDS.interval,
        "refunded": _REFUND_FIELDS.interval,
        "is_refunded": _REFUND_FIELDS.stated,
        "access": FilterField("entry__access"),
        "format": FilterField("entry__format"),
        "platform": FilterField(
            "entry__release__platform__id", search_url="/api/platforms/search"
        ),
        "game": FilterField(
            "entry__player_game__game__id", search_url="/api/games/search"
        ),
        "created_at": FilterField(
            handler=calendar_day_handler("created_at"), metadata_lookup="created_at"
        ),
        "conversion_review": conversion_review_field(_purchase_tagged),
    }

    @classmethod
    def _comparison_model(cls) -> type[Purchase]:
        from games.models import Purchase

        return Purchase

    def _extra_q(self, context: FilterQueryContext | None = None) -> Q:
        q = Q()

        if self.search is not None:
            q &= search_q(
                self.search,
                "name",
                "entry__player_game__game__name",
                "entry__release__platform__name",
            )

        if self.entry_filter is not None:
            from games.models import LibraryEntry

            q &= relation_to_q(
                self.entry_filter,
                context=context,
                related_model=LibraryEntry,
                related_lookup="id",
                parent_field="entry__id",
            )

        if self.game_filter is not None:
            from games.models import Game

            q &= relation_to_q(
                self.game_filter,
                context=context,
                related_model=Game,
                related_lookup="id",
                parent_field="entry__player_game__game__id",
            )

        return q


if _unknown := set(ADDON_FIELDS) - {field.name for field in fields(GameFilter)}:
    raise RuntimeError(f"ADDON_FIELDS names no GameFilter field: {_unknown}")


# ── Aggregate wiring ───────────────────────────────────────────────────────

# Assigned after the class definitions (not in GameFilter's body) because the
# specs reference filter classes defined below GameFilter — a class-body dict
# would NameError on PlayerSessionFilter/PurchaseFilter/PlaythroughFilter. The generic
# ``OperatorFilter.to_q`` walks this table; ``from_json`` reads each spec's
# ``scope_filter`` to deserialize an aggregate's scope. The drift guard in
# tests/test_filters.py asserts the table covers exactly the
# AggregateCriterion-annotated fields.
GameFilter.aggregates = {
    "session_count": AggregateSpec("count", GAME_SESSIONS, PlayerSessionFilter),
    "session_average": AggregateSpec(
        "avg",
        GAME_SESSIONS,
        PlayerSessionFilter,
        source="effective_duration",
        unit="duration_hours",
    ),
    "purchase_count": AggregateSpec("count", GAME_PURCHASES, PurchaseFilter),
    "entry_count": AggregateSpec("count", "player_games__entries", LibraryEntryFilter),
    "playthrough_count": AggregateSpec(
        "count",
        "player_games__playthroughs",
        PlaythroughFilter,
        #: Counts the runs whose completion is stated.
        base_scope=PlaythroughFilter(is_completed=BoolCriterion(value=True)),
    ),
    #: Scope it by `timing_mode` for one mode's share.
    "session_playtime_hours": AggregateSpec(
        "sum",
        GAME_SESSIONS,
        PlayerSessionFilter,
        source="effective_duration",
        unit="duration_hours",
    ),
    "purchase_price_total": AggregateSpec(
        "sum",
        GAME_PURCHASES,
        PurchaseFilter,
        source="valuation_amount",
        correlated="entry__player_game__game",
    ),
}


# ── Convenience helpers ────────────────────────────────────────────────────


def parse_game_filter(json_str: str) -> GameFilter | None:
    return filter_from_json(GameFilter, json_str)


def parse_session_filter(json_str: str) -> PlayerSessionFilter | None:
    return filter_from_json(PlayerSessionFilter, json_str)


def parse_purchase_filter(json_str: str) -> PurchaseFilter | None:
    return filter_from_json(PurchaseFilter, json_str)


def parse_device_filter(json_str: str) -> DeviceFilter | None:
    return filter_from_json(DeviceFilter, json_str)


def parse_platform_filter(json_str: str) -> PlatformFilter | None:
    return filter_from_json(PlatformFilter, json_str)


def parse_playthrough_filter(json_str: str) -> PlaythroughFilter | None:
    return filter_from_json(PlaythroughFilter, json_str)


def parse_historical_playtime_filter(
    json_str: str,
) -> HistoricalPlaytimeFilter | None:
    return filter_from_json(HistoricalPlaytimeFilter, json_str)


def parse_entry_filter(json_str: str) -> LibraryEntryFilter | None:
    return filter_from_json(LibraryEntryFilter, json_str)


# Validates a mode's ``?filter=`` JSON, raising FilterError or returning None.
type FilterParser = Callable[[str], OperatorFilter | None]
#: One scope, built when a filter first names its model.
type ScopeThunk = Callable[[], QuerySet[Any]]

# Maps a FilterPreset.mode to the parser that validates that mode's filter JSON.
# Keyset is contract-tested against FilterPreset.MODE_CHOICES (games/models.py)
# in tests/test_filter_presets.py::test_mode_parsers_cover_every_mode_choice.
MODE_PARSERS: dict[str, FilterParser] = {
    "games": parse_game_filter,
    "sessions": parse_session_filter,
    "purchases": parse_purchase_filter,
    "playthroughs": parse_playthrough_filter,
    "historical_playtime": parse_historical_playtime_filter,
    "devices": parse_device_filter,
    "platforms": parse_platform_filter,
    "entries": parse_entry_filter,
}


# ── Model-key → filter-class resolution ────────────────────────────────────

#: Model keys no screen filters any more.
RETIRED_FILTER_MODELS: Final[frozenset[ModelKey]] = frozenset({"legacypurchase"})


def filter_for_model(model_name: ModelKey) -> type[OperatorFilter]:
    """Resolve a model key (e.g. ``"game"``) to its ``OperatorFilter`` subclass by
    naming convention — no registry to maintain.

    The nested filter builder element carries ``model = Model._meta.model_name``;
    every filter in this module is named ``{Model.__name__}Filter``. So
    ``"game" → Game → GameFilter``. Raises ``LookupError`` for an unknown or retired model and
    ``KeyError`` if a model has no matching filter class.
    """
    from django.apps import apps

    if model_name in RETIRED_FILTER_MODELS:
        raise LookupError(f"{model_name!r} no longer has a filter")
    model = apps.get_model("games", model_name)
    return globals()[f"{model.__name__}Filter"]


def filter_queryset_for_library(
    model_name: ModelKey, library: UserLibrary, game_filter: GameFilter | None = None
) -> QuerySet:
    """Return the explicit ownership base for a generic filter model.

    Most models reachable from the filter builder implement ``for_library``;
    notably, Platform uses the private-management scope here rather than
    ``visible_to`` because the destination list manages private Platforms only.

    Game is one exception: its list counts the games this library tracks,
    through `games_list_base`, which only `game_filter` naming `kind` or
    `parent` widens; other models ignore it. Counting anything else here
    would answer the builder's live count with a number the destination
    list cannot show. Playthrough is the other: its
    condition alias needs the viewer's clock. PlayerSession,
    HistoricalPlaytime and LibraryEntry state no `for_library`: their read
    modules state the scope.
    """
    from django.apps import apps

    from games.models import (
        Game,
        HistoricalPlaytime,
        LibraryEntry,
        PlayerSession,
        Playthrough,
        Purchase,
    )
    from games.reads.entries import library_entries
    from games.reads.games_list import games_list_base
    from games.reads.historical_playtime_records import shown_records
    from games.reads.player_sessions import shown_sessions
    from games.reads.playthrough_runs import runs_with_condition
    from games.reads.purchases import library_purchases

    model = apps.get_model("games", model_name)
    if model is Game:
        return games_list_base(library, game_filter)
    if model is Playthrough:
        return runs_with_condition(library)
    if model is PlayerSession:
        return shown_sessions(library)
    if model is HistoricalPlaytime:
        return shown_records(library)
    if model is LibraryEntry:
        return library_entries(library)
    if model is Purchase:
        return library_purchases(library).annotated_for_filtering(library)
    return model.objects.for_library(library)


def filter_query_context_for_library(library: UserLibrary) -> FilterQueryContext:
    """Resolve every compiler subquery from the current library's visibility.

    Scopes build once, when named: the runs' scope reads the clock.
    """
    from games.models import (
        Device,
        Game,
        HistoricalPlaytime,
        LibraryEntry,
        Platform,
        PlayerSession,
        Playthrough,
        Purchase,
    )
    from games.reads.calendar import calendar_day_zone
    from games.reads.entries import library_entries
    from games.reads.historical_playtime_records import shown_records
    from games.reads.player_sessions import shown_sessions
    from games.reads.playthrough_runs import runs_with_condition
    from games.reads.purchases import library_purchases

    scopes: dict[builtins.type[Model], ScopeThunk] = {
        #: tracked_by, not for_library: a nested game filter resolves
        #: from the games this library tracks, and its criteria read
        #: the projection through the `tracked` alias.
        Game: cache(lambda: Game.objects.tracked_by(library)),
        PlayerSession: cache(lambda: shown_sessions(library)),
        HistoricalPlaytime: cache(lambda: shown_records(library)),
        LibraryEntry: cache(lambda: library_entries(library)),
        Purchase: cache(
            lambda: library_purchases(library).annotated_for_filtering(library)
        ),
        Playthrough: cache(lambda: runs_with_condition(library)),
        Device: cache(lambda: Device.objects.for_library(library)),
        # Related Platform selection supports the shared catalogue plus this
        # library's private rows. Top-level Platform management remains the
        # private-only base returned by filter_queryset_for_library().
        Platform: cache(lambda: Platform.objects.visible_to(library)),
    }
    return FilterQueryContext(
        lambda model: scopes[model](),
        day_zone=lambda: calendar_day_zone(library),
    )


def reachable_models(root_model: ModelKey) -> dict[ModelKey, type[OperatorFilter]]:
    """The closed set of models reachable from ``root_model`` via relation descents
    or aggregate-scope descents, each mapped to its ``OperatorFilter`` subclass (BFS
    over ``field_metadata``'s relation entries and ``scope_model``s). Relation fields
    cycle (game↔session, game↔purchase, …), so the result covers every model the
    nested builder can descend into from the root — the metadata the client needs to
    render any child group offline (#193). Aggregate scope targets (#151) are
    enqueued too so a scope group's field bundle always ships, even for a model
    reachable only through a scope."""
    from collections import deque

    result: dict[ModelKey, type[OperatorFilter]] = {}
    queue: deque[ModelKey] = deque([root_model])
    while queue:
        key = queue.popleft()
        if key in result:
            continue
        filter_cls = filter_for_model(key)
        result[key] = filter_cls
        for meta in field_metadata(filter_cls):
            for relation in meta["relations"]:
                target_key = relation["model"].lower()
                if target_key not in result:
                    queue.append(target_key)
            if meta["scope_model"] and meta["scope_model"] not in result:
                queue.append(meta["scope_model"])
    return result


def model_field_registry(root_model: ModelKey) -> dict[ModelKey, ModelFieldBundle]:
    """Per-model ``{fields, columns}`` bundles for every model reachable from
    ``root_model`` (#193). Serialized as ``<filter-group>``'s ``models`` prop; the
    client keys off it to render each relation's child group from the target model's
    own field metadata and comparison columns."""
    from django.apps import apps

    return {
        key: ModelFieldBundle(
            fields=field_metadata(filter_cls),
            columns=comparable_columns(apps.get_model("games", key)),
        )
        for key, filter_cls in reachable_models(root_model).items()
    }


# ── URL building (the "reverse() for filters") ─────────────────────────────


_FILTER_LIST_URL: dict[type[OperatorFilter], str] = {
    GameFilter: "games:list_games",
    PlayerSessionFilter: "games:list_sessions",
    PurchaseFilter: "games:list_purchases",
    PlaythroughFilter: "games:list_playthroughs",
    HistoricalPlaytimeFilter: "games:list_historical_playtime",
    DeviceFilter: "games:list_devices",
    PlatformFilter: "games:list_platforms",
    LibraryEntryFilter: "games:list_library",
}


def filter_url(filter_obj: OperatorFilter, **extra_params: str) -> str:
    """Build a URL to the filtered list view for ``filter_obj``.

    The target view is inferred from the filter's type, so a filter can never be
    paired with a mismatched list URL.  ``extra_params`` are merged into the
    query string (e.g. ``sort``, ``page``).

    Usage:
        filter_url(GameFilter.where(purchase_count__gt=1))
    """
    try:
        url_name = _FILTER_LIST_URL[type(filter_obj)]
    except KeyError:
        raise TypeError(
            f"No list view registered for {type(filter_obj).__name__}"
        ) from None
    params = {"filter": filter_to_json(filter_obj), **extra_params}
    return f"{reverse(url_name)}?{urlencode(params)}"
