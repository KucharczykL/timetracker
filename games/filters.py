"""
Entity-specific filter types for the timetracker app.

Each filter class mirrors a Django model, with fields expressed as typed
criteria from common.criteria.  The to_q() method produces a Django Q object
ready for queryset.filter().

Inspired by Stash's filter architecture: each entity has an OperatorFilter
with AND/OR/NOT composition and typed criterion fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db.models import Q, QuerySet
from django.urls import reverse
from django.utils.http import urlencode

from common.criteria import (
    BoolCriterion,
    ChoiceCriterion,
    DateCriterion,
    FloatCriterion,
    IntCriterion,
    Modifier,
    MultiCriterion,
    OperatorFilter,
    StringCriterion,
    filter_from_json,
    filter_to_json,
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

    AND: GameFilter | None = None
    OR: GameFilter | None = None
    NOT: GameFilter | None = None

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

    session_count: IntCriterion | None = None
    session_average: IntCriterion | None = None  # average in hours
    purchase_count: IntCriterion | None = None  # distinct purchases per game
    playevent_count: IntCriterion | None = None  # playevents per game

    # Aggregate session durations (hours), summed across the game's sessions
    manual_playtime_hours: IntCriterion | None = None
    calculated_playtime_hours: IntCriterion | None = None

    # Cross-entity: any session played on these devices / matching these flags
    device: MultiCriterion | None = None  # game has session on any of these devices
    session_emulated: BoolCriterion | None = None  # game has emulated session

    # Cross-entity: matches against the game's purchases
    purchase_refunded: BoolCriterion | None = None  # game has refunded purchase
    purchase_infinite: BoolCriterion | None = None  # game has infinite purchase
    purchase_price_total: FloatCriterion | None = None  # sum of converted prices
    purchase_price_any: FloatCriterion | None = None  # any single purchase in range
    purchase_type: ChoiceCriterion | None = None  # game has purchase of type
    purchase_ownership_type: ChoiceCriterion | None = None  # by ownership

    # Cross-entity: substring match against the game's playevent notes
    playevent_note: StringCriterion | None = None

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
            from django.db.models import Count

            from games.models import Game

            matching_ids: QuerySet[Any, Any] = (
                Game.objects.annotate(s_count=Count("sessions", distinct=True))
                .filter(self.session_count.to_q("s_count"))
                .values_list("id", flat=True)
            )
            q &= Q(id__in=matching_ids)

        if self.session_average is not None:
            from django.db.models import Avg

            from games.models import Game

            matching_ids = (
                Game.objects.annotate(s_avg=Avg("sessions__duration_total"))
                .filter(self._playtime_to_q_for_field(self.session_average, "s_avg"))
                .values_list("id", flat=True)
            )
            q &= Q(id__in=matching_ids)

        if self.purchase_count is not None:
            from django.db.models import Count

            from games.models import Game

            matching_ids = (
                Game.objects.annotate(p_count=Count("purchases", distinct=True))
                .filter(self.purchase_count.to_q("p_count"))
                .values_list("id", flat=True)
            )
            q &= Q(id__in=matching_ids)

        if self.playevent_count is not None:
            from django.db.models import Count

            from games.models import Game

            matching_ids = (
                Game.objects.annotate(pe_count=Count("playevents", distinct=True))
                .filter(self.playevent_count.to_q("pe_count"))
                .values_list("id", flat=True)
            )
            q &= Q(id__in=matching_ids)

        if self.manual_playtime_hours is not None:
            from django.db.models import Sum

            from games.models import Game

            matching_ids = (
                Game.objects.annotate(s_manual=Sum("sessions__duration_manual"))
                .filter(
                    self._playtime_to_q_for_field(
                        self.manual_playtime_hours, "s_manual"
                    )
                )
                .values_list("id", flat=True)
            )
            q &= Q(id__in=matching_ids)

        if self.calculated_playtime_hours is not None:
            from django.db.models import Sum

            from games.models import Game

            matching_ids = (
                Game.objects.annotate(s_calc=Sum("sessions__duration_calculated"))
                .filter(
                    self._playtime_to_q_for_field(
                        self.calculated_playtime_hours, "s_calc"
                    )
                )
                .values_list("id", flat=True)
            )
            q &= Q(id__in=matching_ids)

        if self.device is not None:
            from games.models import Session

            session_q = self.device.to_q("device_id")
            matching_ids = Session.objects.filter(session_q).values_list(
                "game_id", flat=True
            )
            q &= Q(id__in=matching_ids)

        if self.session_emulated is not None:
            from games.models import Session

            emulated_ids = Session.objects.filter(
                emulated=self.session_emulated.value
            ).values_list("game_id", flat=True)
            if self.session_emulated.value:
                q &= Q(id__in=emulated_ids)
            else:
                emulated_true_ids = Session.objects.filter(emulated=True).values_list(
                    "game_id", flat=True
                )
                q &= ~Q(id__in=emulated_true_ids)

        if self.purchase_refunded is not None:
            from games.models import Purchase

            refunded_ids = Purchase.objects.filter(
                date_refunded__isnull=False
            ).values_list("games__id", flat=True)
            if self.purchase_refunded.value:
                q &= Q(id__in=refunded_ids)
            else:
                q &= ~Q(id__in=refunded_ids)

        if self.purchase_infinite is not None:
            from games.models import Purchase

            infinite_ids = Purchase.objects.filter(infinite=True).values_list(
                "games__id", flat=True
            )
            if self.purchase_infinite.value:
                q &= Q(id__in=infinite_ids)
            else:
                q &= ~Q(id__in=infinite_ids)

        if self.purchase_price_total is not None:
            from django.db.models import Sum

            from games.models import Game

            matching_ids = (
                Game.objects.annotate(p_total=Sum("purchases__converted_price"))
                .filter(self.purchase_price_total.to_q("p_total"))
                .values_list("id", flat=True)
            )
            q &= Q(id__in=matching_ids)

        if self.purchase_price_any is not None:
            from games.models import Purchase

            price_q = self.purchase_price_any.to_q("converted_price")
            matching_ids = Purchase.objects.filter(price_q).values_list(
                "games__id", flat=True
            )
            q &= Q(id__in=matching_ids)

        if self.purchase_type is not None:
            from games.models import Purchase

            type_q = self.purchase_type.to_q("type")
            matching_ids = Purchase.objects.filter(type_q).values_list(
                "games__id", flat=True
            )
            q &= Q(id__in=matching_ids)

        if self.purchase_ownership_type is not None:
            from games.models import Purchase

            ownership_q = self.purchase_ownership_type.to_q("ownership_type")
            matching_ids = Purchase.objects.filter(ownership_q).values_list(
                "games__id", flat=True
            )
            q &= Q(id__in=matching_ids)

        if self.playevent_note is not None:
            q &= self._playevent_note_to_q(self.playevent_note)

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

        # Cross-entity filters
        if self.session_filter is not None:
            from games.models import Session

            session_q = self.session_filter.to_q()
            matching_ids = Session.objects.filter(session_q).values_list(
                "game_id", flat=True
            )
            q &= Q(id__in=matching_ids)

        if self.purchase_filter is not None:
            from games.models import Purchase

            purchase_q = self.purchase_filter.to_q()
            matching_ids = Purchase.objects.filter(purchase_q).values_list(
                "games__id", flat=True
            )
            q &= Q(id__in=matching_ids)

        if self.playevent_filter is not None:
            from games.models import PlayEvent

            playevent_q = self.playevent_filter.to_q()
            matching_ids = PlayEvent.objects.filter(playevent_q).values_list(
                "game_id", flat=True
            )
            q &= Q(id__in=matching_ids)

        if self.platform_filter is not None:
            from games.models import Platform

            platform_q = self.platform_filter.to_q()
            matching_ids = Platform.objects.filter(platform_q).values_list(
                "id", flat=True
            )
            q &= Q(platform_id__in=matching_ids)

        # ── AND / OR / NOT sub-filters ──
        sub = self.sub_filter()
        if sub is not None:
            if self.AND is not None:
                q &= sub.to_q()
            elif self.OR is not None:
                q |= sub.to_q()
            elif self.NOT is not None:
                q &= ~sub.to_q()

        return q

    @staticmethod
    def _playtime_to_q(c: IntCriterion) -> Q:
        return GameFilter._playtime_to_q_for_field(c, "playtime")

    @staticmethod
    def _playtime_to_q_for_field(c: IntCriterion, field: str) -> Q:
        """Convert hours-based criterion to a DurationField Q object.

        Django stores DurationField as microseconds in SQLite, so we convert
        hours → timedelta(microseconds=X) and use the appropriate lookups.
        """
        from datetime import timedelta

        from common.criteria import Modifier

        m = c.modifier
        td_val = timedelta(hours=c.value)

        if m == Modifier.EQUALS:
            return Q(
                **{
                    f"{field}__gte": td_val,
                    f"{field}__lt": timedelta(hours=c.value + 1),
                }
            )
        if m == Modifier.NOT_EQUALS:
            return ~Q(
                **{
                    f"{field}__gte": td_val,
                    f"{field}__lt": timedelta(hours=c.value + 1),
                }
            )
        if m == Modifier.GREATER_THAN:
            return Q(**{f"{field}__gt": td_val})
        if m == Modifier.LESS_THAN:
            return Q(**{f"{field}__lt": td_val})
        if m == Modifier.BETWEEN and c.value2 is not None:
            lo = timedelta(hours=min(c.value, c.value2))
            hi = timedelta(hours=max(c.value, c.value2))
            return Q(**{f"{field}__gte": lo, f"{field}__lte": hi})
        if m == Modifier.NOT_BETWEEN and c.value2 is not None:
            lo = timedelta(hours=min(c.value, c.value2))
            hi = timedelta(hours=max(c.value, c.value2))
            return Q(**{f"{field}__lt": lo}) | Q(**{f"{field}__gt": hi})
        if m == Modifier.IS_NULL:
            return Q(**{f"{field}": timedelta(0)})
        if m == Modifier.NOT_NULL:
            return ~Q(**{f"{field}": timedelta(0)})
        return Q()

    @staticmethod
    def _playevent_note_to_q(criterion: StringCriterion) -> Q:
        """Match games by substring / regex / null against their playevents' notes."""
        from games.models import PlayEvent

        event_q = criterion.to_q("note")
        matching_ids = PlayEvent.objects.filter(event_q).values_list(
            "game_id", flat=True
        )
        return Q(id__in=matching_ids)


# ── SessionFilter ──────────────────────────────────────────────────────────


@dataclass
class SessionFilter(OperatorFilter):
    """Filter for the Session model."""

    AND: SessionFilter | None = None
    OR: SessionFilter | None = None
    NOT: SessionFilter | None = None

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
        from datetime import timedelta

        q = Q()
        td_val = timedelta(hours=c.value)
        m = c.modifier
        if m == Modifier.EQUALS:
            q &= Q(
                **{
                    f"{field}__gte": td_val,
                    f"{field}__lt": timedelta(hours=c.value + 1),
                }
            )
        elif m == Modifier.NOT_EQUALS:
            q &= ~Q(
                **{
                    f"{field}__gte": td_val,
                    f"{field}__lt": timedelta(hours=c.value + 1),
                }
            )
        elif m == Modifier.GREATER_THAN:
            q &= Q(**{f"{field}__gt": td_val})
        elif m == Modifier.LESS_THAN:
            q &= Q(**{f"{field}__lt": td_val})
        elif m == Modifier.BETWEEN and c.value2 is not None:
            lo = timedelta(hours=min(c.value, c.value2))
            hi = timedelta(hours=max(c.value, c.value2))
            q &= Q(**{f"{field}__gte": lo, f"{field}__lte": hi})
        elif m == Modifier.NOT_BETWEEN and c.value2 is not None:
            lo = timedelta(hours=min(c.value, c.value2))
            hi = timedelta(hours=max(c.value, c.value2))
            q &= Q(**{f"{field}__lt": lo}) | Q(**{f"{field}__gt": hi})
        elif m == Modifier.IS_NULL:
            q &= Q(**{f"{field}": timedelta(0)})
        elif m == Modifier.NOT_NULL:
            q &= ~Q(**{f"{field}": timedelta(0)})
        return q

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

        # Cross-entity filter: sessions for games matching GameFilter
        if self.game_filter is not None:
            from games.models import Game

            game_q = self.game_filter.to_q()
            matching_ids: QuerySet[Any, Any] = Game.objects.filter(game_q).values_list(
                "id", flat=True
            )
            q &= Q(game_id__in=matching_ids)

        # Cross-entity filter: sessions for devices matching DeviceFilter
        if self.device_filter is not None:
            from games.models import Device

            device_q = self.device_filter.to_q()
            matching_ids = Device.objects.filter(device_q).values_list("id", flat=True)
            q &= Q(device_id__in=matching_ids)

        # AND / OR / NOT
        sub = self.sub_filter()
        if sub is not None:
            if self.AND is not None:
                q &= sub.to_q()
            elif self.OR is not None:
                q |= sub.to_q()
            elif self.NOT is not None:
                q &= ~sub.to_q()

        return q


# ── PurchaseFilter ─────────────────────────────────────────────────────────


@dataclass
class PurchaseFilter(OperatorFilter):
    """Filter for the Purchase model."""

    AND: PurchaseFilter | None = None
    OR: PurchaseFilter | None = None
    NOT: PurchaseFilter | None = None

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

        # Cross-entity filter
        if self.game_filter is not None:
            from games.models import Game

            game_q = self.game_filter.to_q()
            matching_ids: QuerySet[Any, Any] = Game.objects.filter(game_q).values_list(
                "id", flat=True
            )
            q &= Q(games__id__in=matching_ids)

        # Cross-entity platform filter
        if self.platform_filter is not None:
            from games.models import Platform

            platform_q = self.platform_filter.to_q()
            matching_ids = Platform.objects.filter(platform_q).values_list(
                "id", flat=True
            )
            q &= Q(platform_id__in=matching_ids)

        sub = self.sub_filter()
        if sub is not None:
            if self.AND is not None:
                q &= sub.to_q()
            elif self.OR is not None:
                q |= sub.to_q()
            elif self.NOT is not None:
                q &= ~sub.to_q()

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
        game_ids = [int(game_id) for game_id in criterion.value]
        exclude_ids = [int(game_id) for game_id in criterion.excludes]

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

    AND: DeviceFilter | None = None
    OR: DeviceFilter | None = None
    NOT: DeviceFilter | None = None

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

        # Cross-entity filter: session_filter
        if self.session_filter is not None:
            from games.models import Session

            session_q = self.session_filter.to_q()
            matching_ids = Session.objects.filter(session_q).values_list(
                "device_id", flat=True
            )
            q &= Q(id__in=matching_ids)

        sub = self.sub_filter()
        if sub is not None:
            if self.AND is not None:
                q &= sub.to_q()
            elif self.OR is not None:
                q |= sub.to_q()
            elif self.NOT is not None:
                q &= ~sub.to_q()

        return q


# ── PlatformFilter ─────────────────────────────────────────────────────────


@dataclass
class PlatformFilter(OperatorFilter):
    """Filter for the Platform model."""

    AND: PlatformFilter | None = None
    OR: PlatformFilter | None = None
    NOT: PlatformFilter | None = None

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

        # Cross-entity filter: game_filter
        if self.game_filter is not None:
            from games.models import Game

            game_q = self.game_filter.to_q()
            matching_ids: QuerySet[Any, Any] = Game.objects.filter(game_q).values_list(
                "platform_id", flat=True
            )
            q &= Q(id__in=matching_ids)

        # Cross-entity filter: purchase_filter
        if self.purchase_filter is not None:
            from games.models import Purchase

            purchase_q = self.purchase_filter.to_q()
            matching_ids = Purchase.objects.filter(purchase_q).values_list(
                "platform_id", flat=True
            )
            q &= Q(id__in=matching_ids)

        sub = self.sub_filter()
        if sub is not None:
            if self.AND is not None:
                q &= sub.to_q()
            elif self.OR is not None:
                q |= sub.to_q()
            elif self.NOT is not None:
                q &= ~sub.to_q()

        return q


# ── PlayEventFilter ────────────────────────────────────────────────────────


@dataclass
class PlayEventFilter(OperatorFilter):
    """Filter for the PlayEvent model."""

    AND: PlayEventFilter | None = None
    OR: PlayEventFilter | None = None
    NOT: PlayEventFilter | None = None

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

        # Cross-entity filter: game_filter
        if self.game_filter is not None:
            from games.models import Game

            game_q = self.game_filter.to_q()
            matching_ids: QuerySet[Any, Any] = Game.objects.filter(game_q).values_list(
                "id", flat=True
            )
            q &= Q(game_id__in=matching_ids)

        sub = self.sub_filter()
        if sub is not None:
            if self.AND is not None:
                q &= sub.to_q()
            elif self.OR is not None:
                q |= sub.to_q()
            elif self.NOT is not None:
                q &= ~sub.to_q()

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
