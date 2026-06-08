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

from django.db.models import Q

from common.criteria import (
    BoolCriterion,
    ChoiceCriterion,
    FloatCriterion,
    IntCriterion,
    Modifier,
    MultiCriterion,
    OperatorFilter,
    StringCriterion,
    filter_from_json,
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
    status: ChoiceCriterion | None = None  # selectable filter widget
    mastered: BoolCriterion | None = None
    playtime_minutes: IntCriterion | None = None  # converted to timedelta on to_q()
    created_at: StringCriterion | None = None  # date string
    updated_at: StringCriterion | None = None  # date string

    # Free-text search (combines name + sort_name + platform name)
    search: StringCriterion | None = None

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
        if self.playtime_minutes is not None:
            q &= self._playtime_to_q(self.playtime_minutes)
        if self.created_at is not None:
            q &= self.created_at.to_q("created_at")
        if self.updated_at is not None:
            q &= self.updated_at.to_q("updated_at")

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
        """Convert minutes-based criterion to a DurationField Q object.

        Django stores DurationField as microseconds in SQLite, so we convert
        minutes → timedelta(microseconds=X) and use the appropriate lookups.
        """
        from datetime import timedelta

        from common.criteria import Modifier

        m = c.modifier
        field = "playtime"
        td_val = timedelta(minutes=c.value)

        if m == Modifier.EQUALS:
            return Q(
                **{
                    f"{field}__gte": td_val,
                    f"{field}__lt": timedelta(minutes=c.value + 1),
                }
            )
        if m == Modifier.NOT_EQUALS:
            return ~Q(
                **{
                    f"{field}__gte": td_val,
                    f"{field}__lt": timedelta(minutes=c.value + 1),
                }
            )
        if m == Modifier.GREATER_THAN:
            return Q(**{f"{field}__gt": td_val})
        if m == Modifier.LESS_THAN:
            return Q(**{f"{field}__lt": td_val})
        if m == Modifier.BETWEEN and c.value2 is not None:
            lo = timedelta(minutes=min(c.value, c.value2))
            hi = timedelta(minutes=max(c.value, c.value2))
            return Q(**{f"{field}__gte": lo, f"{field}__lte": hi})
        if m == Modifier.NOT_BETWEEN and c.value2 is not None:
            lo = timedelta(minutes=min(c.value, c.value2))
            hi = timedelta(minutes=max(c.value, c.value2))
            return Q(**{f"{field}__lt": lo}) | Q(**{f"{field}__gt": hi})
        if m == Modifier.IS_NULL:
            return Q(**{f"{field}": timedelta(0)})
        if m == Modifier.NOT_NULL:
            return ~Q(**{f"{field}": timedelta(0)})
        return Q()


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
    duration_minutes: IntCriterion | None = None  # on duration_total
    is_active: BoolCriterion | None = None  # timestamp_end IS NULL
    timestamp_start: StringCriterion | None = None  # date string
    timestamp_end: StringCriterion | None = None  # date string
    is_manual: BoolCriterion | None = None  # duration_manual > 0
    created_at: StringCriterion | None = None

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity: sessions for games matching these criteria
    game_filter: GameFilter | None = None

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
        if self.duration_minutes is not None:
            c = self.duration_minutes
            td_val = timedelta(minutes=c.value)
            field = "duration_total"
            m = c.modifier
            if m == Modifier.EQUALS:
                q &= Q(
                    **{
                        f"{field}__gte": td_val,
                        f"{field}__lt": timedelta(minutes=c.value + 1),
                    }
                )
            elif m == Modifier.NOT_EQUALS:
                q &= ~Q(
                    **{
                        f"{field}__gte": td_val,
                        f"{field}__lt": timedelta(minutes=c.value + 1),
                    }
                )
            elif m == Modifier.GREATER_THAN:
                q &= Q(**{f"{field}__gt": td_val})
            elif m == Modifier.LESS_THAN:
                q &= Q(**{f"{field}__lt": td_val})
            elif m == Modifier.BETWEEN and c.value2 is not None:
                lo = timedelta(minutes=min(c.value, c.value2))
                hi = timedelta(minutes=max(c.value, c.value2))
                q &= Q(**{f"{field}__gte": lo, f"{field}__lte": hi})
            elif m == Modifier.NOT_BETWEEN and c.value2 is not None:
                lo = timedelta(minutes=min(c.value, c.value2))
                hi = timedelta(minutes=max(c.value, c.value2))
                q &= Q(**{f"{field}__lt": lo}) | Q(**{f"{field}__gt": hi})
            elif m == Modifier.IS_NULL:
                q &= Q(**{f"{field}": timedelta(0)})
            elif m == Modifier.NOT_NULL:
                q &= ~Q(**{f"{field}": timedelta(0)})
        if self.is_active is not None:
            if self.is_active.value:
                q &= Q(timestamp_end__isnull=True)
            else:
                q &= Q(timestamp_end__isnull=False)
        if self.timestamp_start is not None:
            q &= self.timestamp_start.to_q("timestamp_start")
        if self.timestamp_end is not None:
            q &= self.timestamp_end.to_q("timestamp_end")
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
            matching_ids = Game.objects.filter(game_q).values_list("id", flat=True)
            q &= Q(game_id__in=matching_ids)

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
    date_purchased: StringCriterion | None = None  # date string
    date_refunded: StringCriterion | None = None  # date string
    is_refunded: BoolCriterion | None = None  # date_refunded IS NOT NULL
    price: FloatCriterion | None = None  # on price field
    converted_price: FloatCriterion | None = None
    price_currency: StringCriterion | None = None
    num_purchases: IntCriterion | None = None
    ownership_type: ChoiceCriterion | None = None  # ph/di/du/re/bo/tr/de/pi
    type: ChoiceCriterion | None = None  # game/dlc/season_pass/battle_pass
    created_at: StringCriterion | None = None
    updated_at: StringCriterion | None = None

    # Free-text search
    search: StringCriterion | None = None

    # Cross-entity: purchases for games matching these criteria
    game_filter: GameFilter | None = None

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
            matching_ids = Game.objects.filter(game_q).values_list("id", flat=True)
            q &= Q(games__id__in=matching_ids)

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
        # Empty value means no constraint; still apply excludes if any
        if not criterion.value:
            if criterion.excludes:
                return ~Q(games__in=criterion.excludes)
            return Q()

        from games.models import Game, Purchase

        if criterion.modifier in (Modifier.INCLUDES_ALL, Modifier.INCLUDES_ONLY):
            subquery = Purchase.objects.all()
            for game_id in criterion.value:
                subquery = subquery.filter(games=game_id)

            if criterion.modifier == Modifier.INCLUDES_ONLY:
                extra_ids = Game.objects.exclude(
                    id__in=criterion.value
                ).values_list("id", flat=True)
                if extra_ids:
                    subquery = subquery.exclude(games__in=extra_ids)

            q = Q(pk__in=subquery.values("pk"))
            if criterion.excludes:
                q &= ~Q(games__in=criterion.excludes)
            return q

        if criterion.modifier == Modifier.INCLUDES:
            # Use subquery to avoid duplicate rows from M2M join
            subquery = Purchase.objects.filter(games__in=criterion.value)
            q = Q(pk__in=subquery.values("pk"))
            if criterion.excludes:
                q &= ~Q(games__in=criterion.excludes)
            return q

        return criterion.to_q("games")


# ── Convenience helpers ────────────────────────────────────────────────────


def parse_game_filter(json_str: str) -> GameFilter | None:
    return filter_from_json(GameFilter, json_str)


def parse_session_filter(json_str: str) -> SessionFilter | None:
    return filter_from_json(SessionFilter, json_str)


def parse_purchase_filter(json_str: str) -> PurchaseFilter | None:
    return filter_from_json(PurchaseFilter, json_str)
