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

from django.db.models import Q
from django.urls import reverse
from django.utils.http import urlencode

from common.criteria import (
    AggregateCriterion,
    BoolCriterion,
    ChoiceCriterion,
    DateCriterion,
    FilterError,
    FloatCriterion,
    IntCriterion,
    Modifier,
    MultiCriterion,
    OperatorFilter,
    StringCriterion,
    aggregate_to_q,
    duration_hours_to_q,
    filter_from_json,
    filter_to_json,
    relation_to_q,
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
    platform: ChoiceCriterion | None = None  # selectable filter widget
    platform_group: MultiCriterion | None = None  # platform__group__in
    status: ChoiceCriterion | None = None  # selectable filter widget
    mastered: BoolCriterion | None = None
    playtime_hours: IntCriterion | None = None  # converted to timedelta on to_q()
    created_at: StringCriterion | None = None  # date string
    updated_at: StringCriterion | None = None  # date string

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

    def to_q(self) -> Q:
        q = Q()

        # ── individual criteria ──
        if self.name is not None:
            q &= self.name.to_q("name")
        if self.sort_name is not None:
            q &= self.sort_name.to_q("sort_name")
        if self.year_released is not None:
            q &= self.year_released.to_q("year_released")
        if self.original_year_released is not None:
            q &= self.original_year_released.to_q("original_year_released")
        if self.wikidata is not None:
            q &= self.wikidata.to_q("wikidata")
        if self.platform is not None:
            q &= self.platform.to_q("platform_id")
        if self.status is not None:
            q &= self.status.to_q("status")
        if self.mastered is not None:
            q &= self.mastered.to_q("mastered")
        if self.playtime_hours is not None:
            q &= self._playtime_to_q(self.playtime_hours)
        if self.created_at is not None:
            q &= self.created_at.to_q("created_at")
        if self.updated_at is not None:
            q &= self.updated_at.to_q("updated_at")

        if self.platform_group is not None:
            q &= self.platform_group.to_q("platform__group")

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
        if self.search is not None and self.search.value:
            search_q = (
                Q(name__icontains=self.search.value)
                | Q(sort_name__icontains=self.search.value)
                | Q(platform__name__icontains=self.search.value)
            )
            if self.search.modifier == Modifier.EXCLUDES:
                search_q = ~search_q
            q &= search_q

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

        # ── AND / OR / NOT sub-filters (n-ary; see OperatorFilter) ──
        return self._apply_operators(q)

    @staticmethod
    def _playtime_to_q(c: IntCriterion) -> Q:
        return GameFilter._playtime_to_q_for_field(c, "playtime")

    @staticmethod
    def _playtime_to_q_for_field(c: IntCriterion, field: str) -> Q:
        """Convert an hours-based criterion to a DurationField Q object."""
        return duration_hours_to_q(c.value, c.value2, c.modifier, field)


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
    duration_hours: IntCriterion | None = None  # on duration_total (legacy alias)
    duration_total_hours: IntCriterion | None = None
    duration_manual_hours: IntCriterion | None = None
    duration_calculated_hours: IntCriterion | None = None
    is_active: BoolCriterion | None = None  # timestamp_end IS NULL
    timestamp_start: DateCriterion | None = None  # date, compared via __date
    timestamp_end: DateCriterion | None = None  # date, compared via __date
    is_manual: BoolCriterion | None = None  # duration_manual > 0
    created_at: StringCriterion | None = None

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity: sessions for games matching these criteria
    game_filter: GameFilter | None = None

    # Cross-entity: sessions for devices matching these criteria
    device_filter: DeviceFilter | None = None

    def _duration_to_q(self, c: IntCriterion, field: str) -> Q:
        """Convert an hours-based criterion to a DurationField Q object."""
        return duration_hours_to_q(c.value, c.value2, c.modifier, field)

    def to_q(self) -> Q:
        from datetime import timedelta

        q = Q()

        if self.game is not None:
            q &= self.game.to_q("game_id")
        if self.device is not None:
            q &= self.device.to_q("device_id")
        if self.emulated is not None:
            q &= self.emulated.to_q("emulated")
        if self.note is not None:
            q &= self.note.to_q("note")
        if self.duration_hours is not None:
            q &= self._duration_to_q(self.duration_hours, "duration_total")
        if self.duration_total_hours is not None:
            q &= self._duration_to_q(self.duration_total_hours, "duration_total")
        if self.duration_manual_hours is not None:
            q &= self._duration_to_q(self.duration_manual_hours, "duration_manual")
        if self.duration_calculated_hours is not None:
            q &= self._duration_to_q(
                self.duration_calculated_hours, "duration_calculated"
            )
        if self.is_active is not None:
            if self.is_active.value:
                q &= Q(timestamp_end__isnull=True)
            else:
                q &= Q(timestamp_end__isnull=False)
        if self.timestamp_start is not None:
            # Compare the date portion so a date matches the datetime column.
            q &= self.timestamp_start.to_q("timestamp_start__date")
        if self.timestamp_end is not None:
            q &= self.timestamp_end.to_q("timestamp_end__date")
        if self.is_manual is not None:
            if self.is_manual.value:
                q &= ~Q(duration_manual=timedelta(0))
            else:
                q &= Q(duration_manual=timedelta(0))
        if self.created_at is not None:
            q &= self.created_at.to_q("created_at")

        # Free-text search
        if self.search is not None and self.search.value:
            search_q = (
                Q(game__name__icontains=self.search.value)
                | Q(game__platform__name__icontains=self.search.value)
                | Q(device__name__icontains=self.search.value)
                | Q(device__type__icontains=self.search.value)
            )
            if self.search.modifier == Modifier.EXCLUDES:
                search_q = ~search_q
            q &= search_q

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

        # AND / OR / NOT (n-ary; see OperatorFilter)
        return self._apply_operators(q)


# ── PurchaseFilter ─────────────────────────────────────────────────────────


@dataclass
class PurchaseFilter(OperatorFilter):
    """Filter for the Purchase model."""

    AND: list[PurchaseFilter] = field(default_factory=list)
    OR: list[PurchaseFilter] = field(default_factory=list)
    NOT: list[PurchaseFilter] = field(default_factory=list)

    name: StringCriterion | None = None
    platform: ChoiceCriterion | None = None  # platform_id
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
    created_at: StringCriterion | None = None
    updated_at: StringCriterion | None = None

    infinite: BoolCriterion | None = None
    needs_price_update: BoolCriterion | None = None
    converted_currency: StringCriterion | None = None

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity: purchases for games matching these criteria
    game_filter: GameFilter | None = None

    # Cross-entity: purchases for platforms matching these criteria
    platform_filter: PlatformFilter | None = None

    def to_q(self) -> Q:
        q = Q()

        if self.name is not None:
            q &= self.name.to_q("name")
        if self.platform is not None:
            q &= self.platform.to_q("platform_id")
        if self.games is not None:
            q &= self._games_to_q(self.games)
        if self.date_purchased is not None:
            q &= self.date_purchased.to_q("date_purchased")
        if self.date_refunded is not None:
            q &= self.date_refunded.to_q("date_refunded")
        if self.is_refunded is not None:
            q &= Q(date_refunded__isnull=not self.is_refunded.value)
        if self.price is not None:
            q &= self.price.to_q("price")
        if self.converted_price is not None:
            q &= self.converted_price.to_q("converted_price")
        if self.price_currency is not None:
            q &= self.price_currency.to_q("price_currency")
        if self.num_purchases is not None:
            q &= self.num_purchases.to_q("num_purchases")
        if self.ownership_type is not None:
            q &= self.ownership_type.to_q("ownership_type")
        if self.type is not None:
            q &= self.type.to_q("type")
        if self.created_at is not None:
            q &= self.created_at.to_q("created_at")
        if self.updated_at is not None:
            q &= self.updated_at.to_q("updated_at")
        if self.infinite is not None:
            q &= self.infinite.to_q("infinite")
        if self.needs_price_update is not None:
            q &= self.needs_price_update.to_q("needs_price_update")
        if self.converted_currency is not None:
            q &= self.converted_currency.to_q("converted_currency")

        # Free-text search
        if self.search is not None and self.search.value:
            search_q = (
                Q(name__icontains=self.search.value)
                | Q(games__name__icontains=self.search.value)
                | Q(platform__name__icontains=self.search.value)
            )
            if self.search.modifier == Modifier.EXCLUDES:
                search_q = ~search_q
            q &= search_q

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

        # AND / OR / NOT (n-ary; see OperatorFilter)
        return self._apply_operators(q)

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
    created_at: StringCriterion | None = None

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity: Devices that have sessions matching these criteria
    session_filter: SessionFilter | None = None

    def to_q(self) -> Q:
        q = Q()

        if self.name is not None:
            q &= self.name.to_q("name")
        if self.type is not None:
            q &= self.type.to_q("type")
        if self.created_at is not None:
            q &= self.created_at.to_q("created_at")

        # Free-text search
        if self.search is not None and self.search.value:
            search_q = Q(name__icontains=self.search.value) | Q(
                type__icontains=self.search.value
            )
            if self.search.modifier == Modifier.EXCLUDES:
                search_q = ~search_q
            q &= search_q

        # Cross-entity sub-filter: devices that have matching sessions
        if self.session_filter is not None:
            from games.models import Session

            q &= relation_to_q(
                self.session_filter,
                related_model=Session,
                related_lookup="device_id",
            )

        # AND / OR / NOT (n-ary; see OperatorFilter)
        return self._apply_operators(q)


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
    created_at: StringCriterion | None = None

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity
    game_filter: GameFilter | None = None
    purchase_filter: PurchaseFilter | None = None

    def to_q(self) -> Q:
        q = Q()

        if self.name is not None:
            q &= self.name.to_q("name")
        if self.group is not None:
            q &= self.group.to_q("group")
        if self.icon is not None:
            q &= self.icon.to_q("icon")
        if self.created_at is not None:
            q &= self.created_at.to_q("created_at")

        # Free-text search
        if self.search is not None and self.search.value:
            search_q = Q(name__icontains=self.search.value) | Q(
                group__icontains=self.search.value
            )
            if self.search.modifier == Modifier.EXCLUDES:
                search_q = ~search_q
            q &= search_q

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

        # AND / OR / NOT (n-ary; see OperatorFilter)
        return self._apply_operators(q)


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
    created_at: StringCriterion | None = None

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity: PlayEvents for games matching these criteria
    game_filter: GameFilter | None = None

    def to_q(self) -> Q:
        q = Q()

        if self.game is not None:
            q &= self.game.to_q("game_id")
        if self.started is not None:
            q &= self.started.to_q("started")
        if self.ended is not None:
            q &= self.ended.to_q("ended")
        if self.days_to_finish is not None:
            q &= self.days_to_finish.to_q("days_to_finish")
        if self.note is not None:
            q &= self.note.to_q("note")
        if self.created_at is not None:
            q &= self.created_at.to_q("created_at")

        # Free-text search
        if self.search is not None and self.search.value:
            search_q = Q(game__name__icontains=self.search.value) | Q(
                note__icontains=self.search.value
            )
            if self.search.modifier == Modifier.EXCLUDES:
                search_q = ~search_q
            q &= search_q

        # Cross-entity sub-filter: playevents for matching games
        if self.game_filter is not None:
            from games.models import Game

            q &= relation_to_q(
                self.game_filter,
                related_model=Game,
                related_lookup="id",
                parent_field="game_id",
            )

        # AND / OR / NOT (n-ary; see OperatorFilter)
        return self._apply_operators(q)


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
