"""One legacy purchase row as planned copies."""

import math
import uuid
from collections.abc import Callable
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import NamedTuple

from games.events.libraryentry import EntryAccessValue, EntryFormatValue
from games.events.purchase import PurchaseKindValue
from timetracker.temporal import TemporalValue

CENT = Decimal("0.01")
GAMEPASS = "Xbox Gamepass"
EPIC = "Epic Games Store"
OWNED_TYPES = frozenset({"ph", "di", "du"})
ATTACHED_TYPES = frozenset({"season_pass", "battle_pass"})

type LegacyOwnership = str  # "di"
type LegacyType = str  # "season_pass"
type MintKey = Callable[[], uuid.UUID]


class Category(StrEnum):
    """A review list a planned copy joins."""

    UNKNOWN_PRICE = "unknown_price"
    EPIC_FREE = "epic_free"
    RENTAL = "rental"
    CREATED_RELEASE = "created_release"
    DEMO_EDITION = "demo_edition"
    MIXED_INFINITE = "mixed_infinite"
    ADDON_GAME = "addon_game"
    QUANTIZED = "quantized"
    BUNDLE_SPLIT = "bundle_split"
    HAND_RECORDED_COPY = "hand_recorded_copy"
    SKIPPED_REMOVED_GAME = "skipped_removed_game"


class LegacyRow(NamedTuple):
    """Named columns only; later columns cannot break."""

    id: uuid.UUID
    library_id: uuid.UUID
    #: Key order.
    game_ids: tuple[uuid.UUID, ...]
    platform_id: uuid.UUID | None
    platform_name: str
    date_purchased: date
    date_refunded: date | None
    infinite: bool
    price: float
    price_currency: str
    converted_price: float | None
    converted_currency: str
    ownership_type: LegacyOwnership
    type: LegacyType
    name: str
    related_game_id: uuid.UUID | None
    removed_at: datetime | None


class PlannedCopy(NamedTuple):
    """One (legacy row, game): a copy, maybe a purchase."""

    row: LegacyRow
    game_id: uuid.UUID
    #: None: a copy and no purchase.
    purchase_id: uuid.UUID | None
    access: EntryAccessValue
    format: EntryFormatValue
    kind: PurchaseKindValue
    name: str
    amount: Decimal | None
    currency: str
    converted_share: Decimal | None
    purchased: TemporalValue
    refunded: TemporalValue | None
    #: The copy is the DLC Game's, not game_id's.
    is_addon_game: bool
    #: A pass or upgrade, on the base's copy.
    is_attached: bool
    categories: tuple[Category, ...]


def quantized_amount(price: float) -> Decimal:
    """The float's shortest spelling, half up to cents."""
    return Decimal(repr(price)).quantize(CENT, rounding=ROUND_HALF_UP)


def split_cents(total: Decimal, count: int) -> list[Decimal]:
    """Equal cents; the remainder to the first."""
    quotient, remainder = divmod(int(total / CENT), count)
    return [
        (quotient + (1 if index < remainder else 0)) * CENT for index in range(count)
    ]


def access_and_format(
    ownership: LegacyOwnership, platform_name: str
) -> tuple[EntryAccessValue, EntryFormatValue]:
    match ownership:
        case "ph":
            return "owned", "physical"
        case "di" | "du":
            return "owned", "digital"
        case "re" if platform_name == GAMEPASS:
            return "subscription", "digital"
        case "re":
            return "rented", "digital"
        case "bo":
            return "borrowed", "physical"
        case "tr":
            return "trial", "digital"
        case "de":
            return "demo", "digital"
        case "pi":
            return "pirated", "unknown"
    raise ValueError(f"No access for ownership {ownership!r}.")


def legacy_refusals(row: LegacyRow) -> list[str]:
    """What no conversion rule can state."""
    refusals: list[str] = []
    if not row.game_ids:
        refusals.append("it names no game")
    if row.type != "game" and set(row.game_ids) != {row.related_game_id}:
        refusals.append(f"a {row.type} names games other than exactly its base game")
    if row.type == "dlc" and not row.name.strip():
        refusals.append("a DLC states no name for its own game")
    if not math.isfinite(row.price):
        refusals.append(f"its price {row.price!r} is not a number")
    if row.converted_price is not None and not math.isfinite(row.converted_price):
        refusals.append(f"its converted price {row.converted_price!r} is not a number")
    if row.ownership_type not in {"ph", "di", "du", "re", "bo", "tr", "de", "pi"}:
        refusals.append(f"its ownership {row.ownership_type!r} is unknown")
    if row.type not in {"game", "dlc", *ATTACHED_TYPES}:
        refusals.append(f"its type {row.type!r} is unknown")
    return refusals


def _kind(row: LegacyRow) -> PurchaseKindValue:
    if row.ownership_type == "du":
        return "upgrade"
    if row.type == "season_pass":
        return "season_pass"
    if row.type == "battle_pass":
        return "battle_pass"
    return "game"


def plan(row: LegacyRow, *, minted: MintKey) -> list[PlannedCopy]:
    """One copy per game; refusals checked first."""
    count = len(row.game_ids)
    access, format = access_and_format(row.ownership_type, row.platform_name)
    owned = row.ownership_type in OWNED_TYPES
    exact = quantized_amount(row.price)
    currency = row.price_currency.strip().upper()
    shared: list[Category] = []
    amounts: list[Decimal | None]
    if exact == 0 and owned and row.platform_name == EPIC:
        amounts = [Decimal("0.00")] * count
        shared.append(Category.EPIC_FREE)
    elif exact == 0 and owned:
        amounts, currency = [None] * count, ""
        shared.append(Category.UNKNOWN_PRICE)
    elif exact == 0:
        amounts, currency = [None] * count, ""
    else:
        amounts = list(split_cents(exact, count))
    has_purchase = owned or exact != 0
    if Decimal(repr(row.price)) != exact:
        shared.append(Category.QUANTIZED)
    if row.ownership_type == "re":
        shared.append(Category.RENTAL)
    if row.ownership_type == "de":
        shared.append(Category.DEMO_EDITION)
    if row.type == "dlc":
        shared.append(Category.ADDON_GAME)
    if count > 1:
        shared.append(Category.BUNDLE_SPLIT)
    shares: list[Decimal | None] = (
        [None] * count
        if row.converted_price is None
        else list(split_cents(quantized_amount(row.converted_price), count))
    )
    keys = [row.id, *(minted() for _ in range(count - 1))]
    return [
        PlannedCopy(
            row=row,
            game_id=game_id,
            purchase_id=key if has_purchase else None,
            access=access,
            format=format,
            kind=_kind(row),
            name="" if row.type == "dlc" else row.name.strip(),
            amount=amount,
            currency=currency,
            converted_share=share,
            purchased=TemporalValue.from_day(row.date_purchased),
            refunded=(
                None
                if row.date_refunded is None
                else TemporalValue.from_day(row.date_refunded)
            ),
            is_addon_game=row.type == "dlc",
            is_attached=_kind(row) == "upgrade" or row.type in ATTACHED_TYPES,
            categories=tuple(shared),
        )
        for game_id, key, amount, share in zip(
            row.game_ids, keys, amounts, shares, strict=True
        )
    ]
