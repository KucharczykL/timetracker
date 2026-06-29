"""
Entity-specific filter types for the timetracker app.

Each filter class mirrors a Django model, with fields expressed as typed
criteria from common.criteria.  The to_q() method produces a Django Q object
ready for queryset.filter().

Inspired by Stash's filter architecture: each entity has an OperatorFilter
with AND/OR/NOT composition and typed criterion fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Type  # noqa: UP035 — see _comparison_model below

if TYPE_CHECKING:
    from games.models import (
        Device,
        Game,
        PlayEvent,
        Platform,
        Purchase,
        Session,
    )

from django.db.models import Q
from django.urls import reverse
from django.utils.http import urlencode

from common.criteria import (
    AggregateCriterion,
    BoolCriterion,
    ChoiceCriterion,
    DateCriterion,
    FilterError,
    FilterField,
    FloatCriterion,
    IntCriterion,
    Modifier,
    MultiCriterion,
    OperatorFilter,
    StringCriterion,
    aggregate_to_q,
    bool_isnull_handler,
    bool_nonzero_duration_handler,
    duration_hours_handler,
    filter_from_json,
    filter_to_json,
    relation_to_q,
    search_q,
)

# ── FindFilter (sort / pagination) ─────────────────────────────────────────


@dataclass
class FindFilter:
    """Sorting and pagination, separate from filtering criteria (Stash-style)."""

    q: str | None = None  # free-text search
    page: int = 1
    per_page: int = 25
    sort: str | None = None  # e.g. "-created_at"
    direction: str = "desc"  # asc / desc


# ── GameFilter ─────────────────────────────────────────────────────────────


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
    platform: MultiCriterion | None = None  # platform_id (int FK)
    platform_group: ChoiceCriterion | None = None  # platform__group (str)
    status: ChoiceCriterion | None = None  # selectable filter widget
    mastered: BoolCriterion | None = None
    playtime_hours: IntCriterion | None = None  # converted to timedelta on to_q()
    created_at: DateCriterion | None = None  # compared via __date
    updated_at: DateCriterion | None = None  # compared via __date

    # Aggregates over the game's relations (count / sum / avg). The reducer +
    # relation accessor + source + unit are supplied at query time via
    # aggregate_to_q; the criterion carries only the numeric comparison.
    session_count: AggregateCriterion | None = None
    session_average: AggregateCriterion | None = None  # average in hours
    purchase_count: AggregateCriterion | None = None  # distinct purchases per game
    playevent_count: AggregateCriterion | None = None  # playevents per game

    # Aggregate session durations (hours), summed across the game's sessions
    manual_playtime_hours: AggregateCriterion | None = None
    calculated_playtime_hours: AggregateCriterion | None = None

    # Cross-entity: sum of the game's purchase prices (converted)
    purchase_price_total: AggregateCriterion | None = None  # sum of converted prices

    # Free-text search (combines name + sort_name + platform name)
    search: StringCriterion | None = None

    # Cross-entity filters
    session_filter: SessionFilter | None = None
    purchase_filter: PurchaseFilter | None = None
    playevent_filter: PlayEventFilter | None = None
    platform_filter: PlatformFilter | None = None

    # Declarative attr→ORM-lookup table, kept in the old to_q emission order for a
    # reviewable diff (AND-composition makes the order semantically irrelevant).
    fields = {
        "name": FilterField(),
        "sort_name": FilterField(),
        "year_released": FilterField(),
        "original_year_released": FilterField(),
        "wikidata": FilterField(),
        "platform": FilterField("platform_id"),
        "status": FilterField(),
        "mastered": FilterField(),
        "playtime_hours": FilterField(handler=duration_hours_handler("playtime")),
        "created_at": FilterField("created_at__date"),
        "updated_at": FilterField("updated_at__date"),
        "platform_group": FilterField("platform__group"),
    }

    # Uppercase ``Type[...]`` (not the modern ``type[...]``) is deliberate: two
    # filters below (PurchaseFilter, DeviceFilter) declare a field named ``type``
    # that shadows the builtin in annotation scope, so ``type[Purchase]`` fails
    # mypy ("Variable ... .type is not valid as a type"). Uniform ``Type`` keeps
    # all six overrides consistent.
    @classmethod
    def _comparison_model(cls) -> Type[Game]:
        from games.models import Game

        return Game

    def _extra_q(self) -> Q:
        q = Q()

        # ── aggregates over the game's relations ──
        if self.session_count is not None:
            from games.models import Game

            q &= aggregate_to_q(
                self.session_count, model=Game, reducer="count", accessor="sessions"
            )

        if self.session_average is not None:
            from games.models import Game

            q &= aggregate_to_q(
                self.session_average,
                model=Game,
                reducer="avg",
                accessor="sessions",
                source="duration_total",
                unit="duration_hours",
            )

        if self.purchase_count is not None:
            from games.models import Game

            q &= aggregate_to_q(
                self.purchase_count, model=Game, reducer="count", accessor="purchases"
            )

        if self.playevent_count is not None:
            from games.models import Game

            q &= aggregate_to_q(
                self.playevent_count, model=Game, reducer="count", accessor="playevents"
            )

        if self.manual_playtime_hours is not None:
            from games.models import Game

            q &= aggregate_to_q(
                self.manual_playtime_hours,
                model=Game,
                reducer="sum",
                accessor="sessions",
                source="duration_manual",
                unit="duration_hours",
            )

        if self.calculated_playtime_hours is not None:
            from games.models import Game

            q &= aggregate_to_q(
                self.calculated_playtime_hours,
                model=Game,
                reducer="sum",
                accessor="sessions",
                source="duration_calculated",
                unit="duration_hours",
            )

        if self.purchase_price_total is not None:
            from games.models import Game

            q &= aggregate_to_q(
                self.purchase_price_total,
                model=Game,
                reducer="sum",
                accessor="purchases",
                source="converted_price",
            )

        # ── free-text search (OR across multiple fields) ──
        if self.search is not None:
            q &= search_q(self.search, "name", "sort_name", "platform__name")

        # Cross-entity sub-filters (ANY/NONE via each sub-filter's match mode)
        if self.session_filter is not None:
            from games.models import Session

            q &= relation_to_q(
                self.session_filter, related_model=Session, related_lookup="game_id"
            )

        if self.purchase_filter is not None:
            from games.models import Purchase

            q &= relation_to_q(
                self.purchase_filter, related_model=Purchase, related_lookup="games__id"
            )

        if self.playevent_filter is not None:
            from games.models import PlayEvent

            q &= relation_to_q(
                self.playevent_filter, related_model=PlayEvent, related_lookup="game_id"
            )

        if self.platform_filter is not None:
            from games.models import Platform

            q &= relation_to_q(
                self.platform_filter,
                related_model=Platform,
                related_lookup="id",
                parent_field="platform_id",
            )

        return q


# ── SessionFilter ──────────────────────────────────────────────────────────


@dataclass
class SessionFilter(OperatorFilter):
    """Filter for the Session model."""

    AND: list[SessionFilter] = field(default_factory=list)
    OR: list[SessionFilter] = field(default_factory=list)
    NOT: list[SessionFilter] = field(default_factory=list)

    game: MultiCriterion | None = None  # filters on game_id
    device: MultiCriterion | None = None  # filters on device_id
    emulated: BoolCriterion | None = None
    note: StringCriterion | None = None
    duration_total_hours: IntCriterion | None = None
    duration_manual_hours: IntCriterion | None = None
    duration_calculated_hours: IntCriterion | None = None
    is_active: BoolCriterion | None = None  # timestamp_end IS NULL
    timestamp_start: DateCriterion | None = None  # date, compared via __date
    timestamp_end: DateCriterion | None = None  # date, compared via __date
    is_manual: BoolCriterion | None = None  # duration_manual > 0
    created_at: DateCriterion | None = None  # compared via __date

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity: sessions for games matching these criteria
    game_filter: GameFilter | None = None

    # Cross-entity: sessions for devices matching these criteria
    device_filter: DeviceFilter | None = None

    # Declarative attr→ORM-lookup table, kept in the old to_q emission order for a
    # reviewable diff (AND-composition makes the order semantically irrelevant).
    fields = {
        "game": FilterField("game_id"),
        "device": FilterField("device_id"),
        "emulated": FilterField(),
        "note": FilterField(),
        "duration_total_hours": FilterField(
            handler=duration_hours_handler("duration_total")
        ),
        "duration_manual_hours": FilterField(
            handler=duration_hours_handler("duration_manual")
        ),
        "duration_calculated_hours": FilterField(
            handler=duration_hours_handler("duration_calculated")
        ),
        "is_active": FilterField(handler=bool_isnull_handler("timestamp_end")),
        # Compare the date portion so a date matches the datetime column.
        "timestamp_start": FilterField("timestamp_start__date"),
        "timestamp_end": FilterField("timestamp_end__date"),
        "is_manual": FilterField(
            handler=bool_nonzero_duration_handler("duration_manual")
        ),
        "created_at": FilterField("created_at__date"),
    }

    @classmethod
    def _comparison_model(cls) -> Type[Session]:
        from games.models import Session

        return Session

    def _extra_q(self) -> Q:
        q = Q()

        # Free-text search
        if self.search is not None:
            q &= search_q(
                self.search,
                "game__name",
                "game__platform__name",
                "device__name",
                "device__type",
            )

        # Cross-entity sub-filters: sessions for matching games / devices
        if self.game_filter is not None:
            from games.models import Game

            q &= relation_to_q(
                self.game_filter,
                related_model=Game,
                related_lookup="id",
                parent_field="game_id",
            )

        if self.device_filter is not None:
            from games.models import Device

            q &= relation_to_q(
                self.device_filter,
                related_model=Device,
                related_lookup="id",
                parent_field="device_id",
            )

        return q


# ── PurchaseFilter ─────────────────────────────────────────────────────────


@dataclass
class PurchaseFilter(OperatorFilter):
    """Filter for the Purchase model."""

    AND: list[PurchaseFilter] = field(default_factory=list)
    OR: list[PurchaseFilter] = field(default_factory=list)
    NOT: list[PurchaseFilter] = field(default_factory=list)

    name: StringCriterion | None = None
    platform: MultiCriterion | None = None  # platform_id (int FK)
    games: ChoiceCriterion | None = None  # games (M2M IDs)
    date_purchased: DateCriterion | None = None
    date_refunded: DateCriterion | None = None
    is_refunded: BoolCriterion | None = None  # date_refunded IS NOT NULL
    price: FloatCriterion | None = None  # on price field
    converted_price: FloatCriterion | None = None
    price_currency: StringCriterion | None = None
    num_purchases: IntCriterion | None = None
    ownership_type: ChoiceCriterion | None = None  # ph/di/du/re/bo/tr/de/pi
    type: ChoiceCriterion | None = None  # game/dlc/season_pass/battle_pass
    created_at: DateCriterion | None = None  # compared via __date
    updated_at: DateCriterion | None = None  # compared via __date

    infinite: BoolCriterion | None = None
    needs_price_update: BoolCriterion | None = None
    converted_currency: StringCriterion | None = None

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity: purchases for games matching these criteria
    game_filter: GameFilter | None = None

    # Cross-entity: purchases for platforms matching these criteria
    platform_filter: PlatformFilter | None = None

    # Declarative attr→ORM-lookup table, kept in the old to_q emission order for a
    # reviewable diff (AND-composition makes the order semantically irrelevant).
    # ``games`` (M2M) and ``search`` stay imperative — see ``_IMPERATIVE_CRITERIA``
    # and ``_extra_q``.
    fields = {
        "name": FilterField(),
        "platform": FilterField("platform_id"),
        "date_purchased": FilterField(),
        "date_refunded": FilterField(),
        "is_refunded": FilterField(
            handler=bool_isnull_handler("date_refunded", invert=True)
        ),
        "price": FilterField(),
        "converted_price": FilterField(),
        "price_currency": FilterField(),
        "num_purchases": FilterField(),
        "ownership_type": FilterField(),
        "type": FilterField(),
        "created_at": FilterField("created_at__date"),
        "updated_at": FilterField("updated_at__date"),
        "infinite": FilterField(),
        "needs_price_update": FilterField(),
        "converted_currency": FilterField(),
    }

    # ``games`` is a many-to-many handled by ``_games_to_q`` (INCLUDES_ALL/_ONLY
    # need chained subqueries), so it stays out of ``fields``.
    _IMPERATIVE_CRITERIA = {"search", "games"}

    @classmethod
    def _comparison_model(cls) -> Type[Purchase]:
        from games.models import Purchase

        return Purchase

    def _extra_q(self) -> Q:
        q = Q()

        # M2M games: chained subqueries for INCLUDES_ALL/_ONLY keep it out of the
        # declarative fields table. AND-composed into the same Q, so its position
        # relative to the simple fields does not affect results.
        if self.games is not None:
            q &= self._games_to_q(self.games)

        # Free-text search
        if self.search is not None:
            q &= search_q(self.search, "name", "games__name", "platform__name")

        # Cross-entity sub-filters: purchases for matching games / platforms
        if self.game_filter is not None:
            from games.models import Game

            q &= relation_to_q(
                self.game_filter,
                related_model=Game,
                related_lookup="id",
                parent_field="games__id",
            )

        if self.platform_filter is not None:
            from games.models import Platform

            q &= relation_to_q(
                self.platform_filter,
                related_model=Platform,
                related_lookup="id",
                parent_field="platform_id",
            )

        return q

    @staticmethod
    def _games_to_q(criterion: ChoiceCriterion) -> Q:
        """Build the Q for the many-to-many ``games`` field.

        ``INCLUDES_ALL`` ("related to every selected game") and
        ``INCLUDES_ONLY`` ("related to exactly these, nothing else") cannot be
        a single ``.filter(Q(games=a) & Q(games=b))`` — that collapses to one
        join and would require a single link row to be both games. Instead
        chain a filter per game so each gets its own join, then match by
        ``pk``.  ``INCLUDES_ONLY`` additionally excludes purchases that have
        any game outside the specified set.

        ``INCLUDES`` (plain "any") also uses a subquery instead of a raw
        ``games__in`` join because a single purchase linked to *n* of the
        given games would appear *n* times in the result set (M2M join
        duplicates).

        The orthogonal ``excludes`` channel is applied as a negative,
        consistent with every other modifier. All other modifiers delegate
        to the criterion.
        """
        # Criterion values arrive as strings; the M2M lookups want game PKs.
        # A hand-edited filter can carry a non-integer id — raise FilterError so
        # the boundary catches it instead of a bare ValueError escaping.
        try:
            game_ids = [int(game_id) for game_id in criterion.value]
            exclude_ids = [int(game_id) for game_id in criterion.excludes]
        except (ValueError, TypeError) as exc:
            raise FilterError(f"games filter values must be integers: {exc}") from exc

        # Empty value means no constraint; still apply excludes if any
        if not game_ids:
            if exclude_ids:
                return ~Q(games__in=exclude_ids)
            return Q()

        from games.models import Game, Purchase

        if criterion.modifier in (Modifier.INCLUDES_ALL, Modifier.INCLUDES_ONLY):
            subquery = Purchase.objects.all()
            for game_id in game_ids:
                subquery = subquery.filter(games=game_id)

            if criterion.modifier == Modifier.INCLUDES_ONLY:
                extra_ids = Game.objects.exclude(id__in=game_ids).values_list(
                    "id", flat=True
                )
                if extra_ids:
                    subquery = subquery.exclude(games__in=extra_ids)

            q = Q(pk__in=subquery.values("pk"))
            if exclude_ids:
                q &= ~Q(games__in=exclude_ids)
            return q

        if criterion.modifier == Modifier.INCLUDES:
            # Use subquery to avoid duplicate rows from M2M join
            subquery = Purchase.objects.filter(games__in=game_ids)
            q = Q(pk__in=subquery.values("pk"))
            if exclude_ids:
                q &= ~Q(games__in=exclude_ids)
            return q

        return criterion.to_q("games")


# ── DeviceFilter ───────────────────────────────────────────────────────────


@dataclass
class DeviceFilter(OperatorFilter):
    """Filter for the Device model."""

    AND: list[DeviceFilter] = field(default_factory=list)
    OR: list[DeviceFilter] = field(default_factory=list)
    NOT: list[DeviceFilter] = field(default_factory=list)

    name: StringCriterion | None = None
    type: ChoiceCriterion | None = None
    created_at: DateCriterion | None = None  # compared via __date

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity: Devices that have sessions matching these criteria
    session_filter: SessionFilter | None = None

    # Declarative attr→ORM-lookup table, kept in the old to_q emission order for a
    # reviewable diff (AND-composition makes the order semantically irrelevant).
    fields = {
        "name": FilterField(),
        "type": FilterField(),
        "created_at": FilterField("created_at__date"),
    }

    @classmethod
    def _comparison_model(cls) -> Type[Device]:
        from games.models import Device

        return Device

    def _extra_q(self) -> Q:
        q = Q()

        # Free-text search
        if self.search is not None:
            q &= search_q(self.search, "name", "type")

        # Cross-entity sub-filter: devices that have matching sessions
        if self.session_filter is not None:
            from games.models import Session

            q &= relation_to_q(
                self.session_filter,
                related_model=Session,
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
    created_at: DateCriterion | None = None  # compared via __date

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity
    game_filter: GameFilter | None = None
    purchase_filter: PurchaseFilter | None = None

    # Declarative attr→ORM-lookup table, kept in the old to_q emission order for a
    # reviewable diff (AND-composition makes the order semantically irrelevant).
    fields = {
        "name": FilterField(),
        "group": FilterField(),
        "icon": FilterField(),
        "created_at": FilterField("created_at__date"),
    }

    @classmethod
    def _comparison_model(cls) -> Type[Platform]:
        from games.models import Platform

        return Platform

    def _extra_q(self) -> Q:
        q = Q()

        # Free-text search
        if self.search is not None:
            q &= search_q(self.search, "name", "group")

        # Cross-entity sub-filters: platforms with matching games / purchases
        if self.game_filter is not None:
            from games.models import Game

            q &= relation_to_q(
                self.game_filter, related_model=Game, related_lookup="platform_id"
            )

        if self.purchase_filter is not None:
            from games.models import Purchase

            q &= relation_to_q(
                self.purchase_filter,
                related_model=Purchase,
                related_lookup="platform_id",
            )

        return q


# ── PlayEventFilter ────────────────────────────────────────────────────────


@dataclass
class PlayEventFilter(OperatorFilter):
    """Filter for the PlayEvent model."""

    AND: list[PlayEventFilter] = field(default_factory=list)
    OR: list[PlayEventFilter] = field(default_factory=list)
    NOT: list[PlayEventFilter] = field(default_factory=list)

    game: MultiCriterion | None = None  # filters on game_id
    started: DateCriterion | None = None  # DateField, bare lookup
    ended: DateCriterion | None = None  # DateField, bare lookup
    days_to_finish: IntCriterion | None = None
    note: StringCriterion | None = None
    created_at: DateCriterion | None = None  # compared via __date

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity: PlayEvents for games matching these criteria
    game_filter: GameFilter | None = None

    # Declarative attr→ORM-lookup table, kept in the old to_q emission order for a
    # reviewable diff (AND-composition makes the order semantically irrelevant).
    fields = {
        "game": FilterField("game_id"),
        "started": FilterField(),
        "ended": FilterField(),
        "days_to_finish": FilterField(),
        "note": FilterField(),
        "created_at": FilterField("created_at__date"),
    }

    @classmethod
    def _comparison_model(cls) -> Type[PlayEvent]:
        from games.models import PlayEvent

        return PlayEvent

    def _extra_q(self) -> Q:
        q = Q()

        # Free-text search
        if self.search is not None:
            q &= search_q(self.search, "game__name", "note")

        # Cross-entity sub-filter: playevents for matching games
        if self.game_filter is not None:
            from games.models import Game

            q &= relation_to_q(
                self.game_filter,
                related_model=Game,
                related_lookup="id",
                parent_field="game_id",
            )

        return q


# ── Convenience helpers ────────────────────────────────────────────────────


def parse_game_filter(json_str: str) -> GameFilter | None:
    return filter_from_json(GameFilter, json_str)


def parse_session_filter(json_str: str) -> SessionFilter | None:
    return filter_from_json(SessionFilter, json_str)


def parse_purchase_filter(json_str: str) -> PurchaseFilter | None:
    return filter_from_json(PurchaseFilter, json_str)


def parse_device_filter(json_str: str) -> DeviceFilter | None:
    return filter_from_json(DeviceFilter, json_str)


def parse_platform_filter(json_str: str) -> PlatformFilter | None:
    return filter_from_json(PlatformFilter, json_str)


def parse_playevent_filter(json_str: str) -> PlayEventFilter | None:
    return filter_from_json(PlayEventFilter, json_str)


# ── URL building (the "reverse() for filters") ─────────────────────────────


_FILTER_LIST_URL: dict[type[OperatorFilter], str] = {
    GameFilter: "games:list_games",
    SessionFilter: "games:list_sessions",
    PurchaseFilter: "games:list_purchases",
    PlayEventFilter: "games:list_playevents",
    DeviceFilter: "games:list_devices",
    PlatformFilter: "games:list_platforms",
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
