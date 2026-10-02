"""One legacy purchase row as planned copies."""

# conversion-tooling

import math
import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Literal, NamedTuple, get_args

from games.commands.purchase import UNKNOWN_PRICE, StatedPrice, refund_ends
from games.conversion_review import Category
from games.events.libraryentry import EntryAccessValue, EntryFormatValue
from games.events.purchase import PurchaseKindValue
from timetracker.temporal import TemporalValue

CENT = Decimal("0.01")
GAMEPASS = "Xbox Gamepass"
EPIC = "Epic Games Store"

type LegacyOwnership = Literal["ph", "di", "du", "re", "bo", "tr", "de", "pi"]
type LegacyType = Literal["game", "dlc", "season_pass", "battle_pass"]
type LegacyId = uuid.UUID
type LibraryId = uuid.UUID
type GameId = uuid.UUID
type PurchaseId = uuid.UUID
type CurrencyCode = str  # "EUR"
type AccessAndFormat = tuple[EntryAccessValue, EntryFormatValue]

LEGACY_OWNERSHIPS: frozenset[str] = frozenset(get_args(LegacyOwnership.__value__))
LEGACY_TYPES: frozenset[str] = frozenset(get_args(LegacyType.__value__))
OWNED: frozenset[str] = frozenset({"ph", "di", "du"})
PASSES: frozenset[str] = frozenset({"season_pass", "battle_pass"})


class CopyShape(StrEnum):
    """Where a planned copy lives."""

    #: Its own copy of the row's game.
    OWN = "own"
    #: Its own copy of the DLC's Game.
    ADDON_GAME = "addon_game"
    #: The base's copy; else its own.
    ATTACHED = "attached"


class LegacyRow(NamedTuple):
    """Read by name; a historical model fits."""

    id: LegacyId
    library_id: LibraryId
    #: Sorted by game key.
    game_ids: tuple[GameId, ...]
    platform_id: uuid.UUID | None
    platform_name: str
    date_purchased: date
    date_refunded: date | None
    infinite: bool
    price: float
    price_currency: CurrencyCode
    converted_price: float | None
    converted_currency: CurrencyCode
    ownership_type: LegacyOwnership
    type: LegacyType
    name: str
    related_game_id: GameId | None
    removed_at: datetime | None


class ConvertedShare(NamedTuple):
    """A legacy converted amount, split alike."""

    amount: Decimal
    currency: CurrencyCode


class PlannedPurchase(NamedTuple):
    """The purchase a planned copy carries."""

    kind: PurchaseKindValue
    name: str
    price: StatedPrice
    converted: ConvertedShare | None
    #: Legacy key on a bundle's first game.
    key: PurchaseId | None


class PlannedCopy(NamedTuple):
    """One legacy row's copy of one game."""

    row: LegacyRow
    game_id: GameId
    access: EntryAccessValue
    format: EntryFormatValue
    #: None: a copy and no purchase.
    purchase: PlannedPurchase | None
    purchased: TemporalValue
    refunded: TemporalValue | None
    shape: CopyShape
    categories: tuple[Category, ...]

    @property
    def refund_ends_it(self) -> bool:
        """RefundPurchase ends this new copy itself."""
        return self.purchase is not None and refund_ends(
            self.purchase.kind, self.access, ended=False
        )


class RowNotConvertible(ValueError):
    """A row no conversion rule states."""


def exact_amount(price: float) -> Decimal:
    """The float's shortest spelling."""
    return Decimal(repr(price))


def quantized_amount(price: float) -> Decimal:
    """Shortest float spelling, half up to cents."""
    return exact_amount(price).quantize(CENT, rounding=ROUND_HALF_UP)


def split_cents(total: Decimal, count: int) -> list[Decimal]:
    """Equal cents; first ones get one more."""
    quotient, remainder = divmod(int(total / CENT), count)
    return [
        (quotient + (1 if index < remainder else 0)) * CENT for index in range(count)
    ]


def access_and_format(
    ownership: LegacyOwnership, platform_name: str
) -> AccessAndFormat:
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


def legacy_refusals(row: LegacyRow) -> list[str]:
    """What no conversion rule can state."""
    refusals: list[str] = []
    if not row.game_ids:
        refusals.append("it names no game")
    if list(row.game_ids) != sorted(row.game_ids):
        refusals.append("its games are not in key order")
    if row.type != "game" and set(row.game_ids) != {row.related_game_id}:
        refusals.append(f"a {row.type} names games other than exactly its base game")
    if row.type == "dlc" and not row.name.strip():
        refusals.append("a DLC states no name for its own game")
    if row.type == "dlc" and row.ownership_type == "du":
        refusals.append("a DLC cannot also be a digital upgrade")
    if not math.isfinite(row.price):
        refusals.append(f"its price {row.price!r} is not a number")
    if row.converted_price is not None and not math.isfinite(row.converted_price):
        refusals.append(f"its converted price {row.converted_price!r} is not a number")
    if row.ownership_type not in LEGACY_OWNERSHIPS:
        refusals.append(f"its ownership {row.ownership_type!r} is unknown")
    if row.type not in LEGACY_TYPES:
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


def _shape(row: LegacyRow) -> CopyShape:
    if row.type == "dlc":
        return CopyShape.ADDON_GAME
    if row.ownership_type == "du" or row.type in PASSES:
        return CopyShape.ATTACHED
    return CopyShape.OWN


def _prices(row: LegacyRow, quantized: Decimal, owned: bool) -> list[StatedPrice]:
    count = len(row.game_ids)
    currency = row.price_currency.strip().upper()
    if quantized == 0 and owned and row.platform_name == EPIC:
        return [StatedPrice(Decimal("0.00"), currency)] * count
    if quantized == 0:
        return [UNKNOWN_PRICE] * count
    return [StatedPrice(amount, currency) for amount in split_cents(quantized, count)]


def plan(row: LegacyRow) -> list[PlannedCopy]:
    """One copy per game; refuses unconvertible rows."""
    refusals = legacy_refusals(row)
    if refusals:
        raise RowNotConvertible(f"Legacy purchase {row.id}: {'; '.join(refusals)}.")
    count = len(row.game_ids)
    access, format = access_and_format(row.ownership_type, row.platform_name)
    owned = row.ownership_type in OWNED
    quantized = quantized_amount(row.price)
    shared: list[Category] = []
    if quantized == 0 and owned:
        shared.append(
            Category.EPIC_FREE if row.platform_name == EPIC else Category.UNKNOWN_PRICE
        )
    if exact_amount(row.price) != quantized:
        shared.append(Category.QUANTIZED)
    if row.ownership_type == "re":
        shared.append(Category.RENTAL)
    if row.ownership_type == "de":
        shared.append(Category.DEMO_EDITION)
    if row.type == "dlc":
        shared.append(Category.ADDON_GAME)
    if count > 1:
        shared.append(Category.BUNDLE_SPLIT)
    converted: list[ConvertedShare | None] = (
        [None] * count
        if row.converted_price is None
        else [
            ConvertedShare(share, row.converted_currency.strip().upper())
            for share in split_cents(quantized_amount(row.converted_price), count)
        ]
    )
    has_purchase = owned or quantized != 0
    kind = _kind(row)
    shape = _shape(row)
    #: Attached exactly when not a game purchase.
    assert (shape == CopyShape.ATTACHED) == (kind != "game")
    return [
        PlannedCopy(
            row=row,
            game_id=game_id,
            access=access,
            format=format,
            purchase=(
                PlannedPurchase(
                    kind=kind,
                    name="" if row.type == "dlc" else row.name.strip(),
                    price=price,
                    converted=share,
                    key=row.id if index == 0 else None,
                )
                if has_purchase
                else None
            ),
            purchased=TemporalValue.from_day(row.date_purchased),
            refunded=(
                None
                if row.date_refunded is None
                else TemporalValue.from_day(row.date_refunded)
            ),
            shape=shape,
            categories=tuple(shared),
        )
        for index, (game_id, price, share) in enumerate(
            zip(row.game_ids, _prices(row, quantized, owned), converted, strict=True)
        )
    ]
