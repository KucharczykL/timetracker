import logging
from datetime import timedelta

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q, Sum
from django.db.models.expressions import RawSQL
from django.db.models.fields.generated import GeneratedField
from django.db.models.functions import Coalesce
from django.template.defaultfilters import floatformat, pluralize, slugify
from django.utils import timezone

from common.time import format_duration
from common.utils import label_with_details

logger = logging.getLogger("games")


class Game(models.Model):
    class Meta:
        unique_together = [["name", "platform", "year_released"]]
        constraints = [
            # unique_together never bites for platformless games (SQLite treats
            # NULLs as pairwise distinct), so this keeps the dedup guarantee the
            # sentinel platform used to provide.
            models.UniqueConstraint(
                fields=["name", "year_released"],
                condition=Q(platform__isnull=True),
                name="unique_platformless_game_name_year",
            )
        ]

    name = models.CharField(max_length=255)
    sort_name = models.CharField(max_length=255, blank=True, default="")
    year_released = models.IntegerField(null=True, blank=True, default=None)
    original_year_released = models.IntegerField(null=True, blank=True, default=None)
    wikidata = models.CharField(max_length=50, blank=True, default="")
    platform = models.ForeignKey(
        "Platform", on_delete=models.SET_NULL, null=True, blank=True, default=None
    )

    playtime = models.DurationField(blank=True, editable=False, default=timedelta(0))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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

    def __str__(self):
        return self.name

    @property
    def search_label(self) -> str:
        # label_with_details drops falsy details, so coalesce NULL platform to
        # the display label — otherwise the segment silently vanishes.
        return label_with_details(
            self.name, self.platform or "Unspecified", self.year_released
        )

    def finished(self):
        return (
            self.status == self.Status.FINISHED
            or self.playevents.filter(ended__isnull=False).exists()
        )

    def abandoned(self):
        return self.status == self.Status.ABANDONED

    def retired(self):
        return self.status == self.Status.RETIRED

    def played(self):
        return self.status == self.Status.PLAYED

    def unplayed(self):
        return self.status == self.Status.UNPLAYED

    def playtime_formatted(self):
        return format_duration(self.playtime, "%2.1H")


class Platform(models.Model):
    name = models.CharField(max_length=255)
    group = models.CharField(max_length=255, blank=True, default="")
    icon = models.SlugField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.icon:
            self.icon = slugify(self.name)
        super().save(*args, **kwargs)


class PurchaseQueryset(models.QuerySet):
    def refunded(self):
        return self.filter(date_refunded__isnull=False)

    def not_refunded(self):
        return self.filter(date_refunded__isnull=True)

    def games_only(self):
        return self.filter(type=Purchase.GAME)

    def finished(self):
        return self.filter(
            Q(games__status="f") | Q(games__playevents__ended__isnull=False)
        ).distinct()

    def abandoned(self):
        return self.filter(games__status="a").distinct()

    def dropped(self):
        return self.filter(
            Q(games__status="a") | Q(date_refunded__isnull=False)
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
    OWNERSHIP_TYPES = [
        (PHYSICAL, "Physical"),
        (DIGITAL, "Digital"),
        (DIGITALUPGRADE, "Digital Upgrade"),
        (RENTED, "Rented"),
        (BORROWED, "Borrowed"),
        (TRIAL, "Trial"),
        (DEMO, "Demo"),
        (PIRATED, "Pirated"),
    ]
    GAME = "game"
    DLC = "dlc"
    SEASONPASS = "season_pass"
    BATTLEPASS = "battle_pass"
    TYPES = [
        (GAME, "Game"),
        (DLC, "DLC"),
        (SEASONPASS, "Season Pass"),
        (BATTLEPASS, "Battle Pass"),
    ]

    objects = PurchaseQueryset().as_manager()

    games = models.ManyToManyField(Game, related_name="purchases")

    platform = models.ForeignKey(
        Platform, on_delete=models.SET_NULL, default=None, null=True, blank=True
    )
    date_purchased = models.DateField(verbose_name="Purchased")
    date_refunded = models.DateField(blank=True, null=True, verbose_name="Refunded")
    infinite = models.BooleanField(default=False)
    price = models.FloatField(default=0)
    price_currency = models.CharField(max_length=3, default="USD")
    converted_price = models.FloatField(null=True)
    converted_currency = models.CharField(max_length=3, blank=True, default="")
    needs_price_update = models.BooleanField(default=True, db_index=True)
    price_per_game = GeneratedField(
        expression=Coalesce(F("converted_price"), F("price"), 0) / F("num_purchases"),
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

    def save(self, *args, **kwargs):
        if not self.price_currency:
            self.price_currency = settings.DEFAULT_CURRENCY
        if self.type != Purchase.GAME and not self.related_game:
            raise ValidationError(
                f"{self.get_type_display()} must have a related game."
            )
        super().save(*args, **kwargs)


class SessionQuerySet(models.QuerySet):
    def total_duration_formatted(self):
        return format_duration(self.total_duration_unformatted())

    def total_duration_unformatted(self):
        result = self.aggregate(
            duration=Sum(F("duration_calculated") + F("duration_manual"))
        )
        return result["duration"]

    def calculated_duration_formatted(self):
        return format_duration(self.calculated_duration_unformatted())

    def calculated_duration_unformatted(self):
        result = self.aggregate(duration=Sum(F("duration_calculated")))
        return result["duration"]

    def without_manual(self):
        return self.exclude(duration_calculated__iexact=0)

    def only_manual(self):
        return self.filter(duration_calculated__iexact=0)


class Session(models.Model):
    class Meta:
        get_latest_by = "timestamp_start"

    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        null=True,
        default=None,
        related_name="sessions",
    )
    timestamp_start = models.DateTimeField(verbose_name="Start", db_index=True)
    timestamp_end = models.DateTimeField(blank=True, null=True, verbose_name="End")
    duration_manual = models.DurationField(
        blank=True, null=True, default=timedelta(0), verbose_name="Manual duration"
    )
    duration_calculated = GeneratedField(
        expression=Coalesce(F("timestamp_end") - F("timestamp_start"), 0),
        output_field=models.DurationField(),
        db_persist=True,
        editable=False,
    )
    duration_total = GeneratedField(
        expression=F("duration_calculated") + F("duration_manual"),
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

    objects = SessionQuerySet.as_manager()

    def __str__(self):
        mark = "*" if self.is_manual() else ""
        return f"{str(self.game)} {str(self.timestamp_start.date())} ({self.duration_formatted()}{mark})"

    def finish_now(self):
        self.timestamp_end = timezone.now()

    def duration_formatted(self) -> str:
        result = format_duration(self.duration_total, "%02.1H")
        return result

    def duration_formatted_with_mark(self) -> str:
        mark = "*" if self.is_manual() else ""
        return f"{self.duration_formatted()}{mark}"

    def is_manual(self) -> bool:
        return not self.duration_manual == timedelta(0)

    def save(self, *args, **kwargs) -> None:
        if not isinstance(self.duration_manual, timedelta):
            self.duration_manual = timedelta(0)
        super(Session, self).save(*args, **kwargs)


class Device(models.Model):
    PC = "PC"
    CONSOLE = "Console"
    HANDHELD = "Handheld"
    MOBILE = "Mobile"
    SBC = "Single-board computer"
    UNKNOWN = "Unknown"
    DEVICE_TYPES = [
        (PC, "PC"),
        (CONSOLE, "Console"),
        (HANDHELD, "Handheld"),
        (MOBILE, "Mobile"),
        (SBC, "Single-board computer"),
        (UNKNOWN, "Unknown"),
    ]
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=255, choices=DEVICE_TYPES, default=UNKNOWN)
    created_at = models.DateTimeField(auto_now_add=True)

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


class PlayEvent(models.Model):
    game = models.ForeignKey(Game, related_name="playevents", on_delete=models.CASCADE)
    started = models.DateField(null=True, blank=True)
    ended = models.DateField(null=True, blank=True)
    days_to_finish = GeneratedField(
        # special cases:
        # missing ended, started, or both = 0
        # same day = 1 day to finish
        expression=RawSQL(
            """
            COALESCE(
                CASE 
                    WHEN date(ended) = date(started) THEN 1
                    ELSE julianday(ended) - julianday(started)
                END, 0
            )
            """,
            [],
        ),
        output_field=models.IntegerField(),
        db_persist=True,
        editable=False,
        blank=True,
    )
    note = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


# class PlayMarker(models.Model):
#     game = models.ForeignKey(Game, related_name="markers", on_delete=models.CASCADE)
#     played_since = models.DurationField()
#     played_total = models.DurationField()
#     note = models.CharField(max_length=255)


class GameStatusChange(models.Model):
    """
    Tracks changes to the status of a Game.
    """

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
        ordering = ["-timestamp"]


class FilterPreset(models.Model):
    """Saved filter configuration, following Stash's SavedFilter pattern.

    Separates find_filter (sort/pagination), object_filter (criteria JSON),
    and ui_options (presentation state) so they can evolve independently.
    """

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "mode", "name"],
                name="unique_user_mode_name_preset",
            )
        ]

    MODE_CHOICES = [
        ("games", "Games"),
        ("sessions", "Sessions"),
        ("purchases", "Purchases"),
        ("playevents", "Play Events"),
        ("devices", "Devices"),
        ("platforms", "Platforms"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="filter_presets",
    )
    name = models.CharField(max_length=255)
    mode = models.CharField(max_length=50, choices=MODE_CHOICES, default="games")
    find_filter = models.JSONField(default=dict, blank=True)
    object_filter = models.JSONField(default=dict, blank=True)
    ui_options = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.get_mode_display()})"
