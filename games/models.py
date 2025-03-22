import logging
from datetime import timedelta

import requests
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Sum
from django.db.models.expressions import RawSQL
from django.db.models.fields.generated import GeneratedField
from django.db.models.functions import Coalesce
from django.template.defaultfilters import floatformat, pluralize, slugify
from django.utils import timezone

from common.time import format_duration

logger = logging.getLogger("games")


class Game(models.Model):
    class Meta:
        unique_together = [["name", "platform", "year_released"]]

    name = models.CharField(max_length=255)
    sort_name = models.CharField(max_length=255, blank=True, default="")
    year_released = models.IntegerField(null=True, blank=True, default=None)
    original_year_released = models.IntegerField(null=True, blank=True, default=None)
    wikidata = models.CharField(max_length=50, blank=True, default="")
    platform = models.ForeignKey(
        "Platform", on_delete=models.SET_DEFAULT, null=True, blank=True, default=None
    )

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

    session_average: float | int | timedelta | None
    session_count: int | None

    def __str__(self):
        return self.name

    def finished(self):
        return self.status == self.Status.FINISHED

    def abandoned(self):
        return self.status == self.Status.ABANDONED

    def retired(self):
        return self.status == self.Status.RETIRED

    def played(self):
        return self.status == self.Status.PLAYED

    def unplayed(self):
        return self.status == self.Status.UNPLAYED

    def save(self, *args, **kwargs):
        if self.platform is None:
            self.platform = get_sentinel_platform()
        super().save(*args, **kwargs)


def get_sentinel_platform():
    return Platform.objects.get_or_create(
        name="Unspecified", icon="unspecified", group="Unspecified"
    )[0]


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
        Platform, on_delete=models.CASCADE, default=None, null=True, blank=True
    )
    date_purchased = models.DateField()
    date_refunded = models.DateField(blank=True, null=True)
    # move date_finished to PlayEvent model's Finished field
    # also set Game's model Status field to Finished
    # date_finished = models.DateField(blank=True, null=True)
    # move date_dropped to Game model's field Status (Abandoned)
    # date_dropped = models.DateField(blank=True, null=True)
    infinite = models.BooleanField(default=False)
    price = models.FloatField(default=0)
    price_currency = models.CharField(max_length=3, default="USD")
    converted_price = models.FloatField(null=True)
    converted_currency = models.CharField(max_length=3, blank=True, default="")
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
    related_purchase = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        default=None,
        null=True,
        related_name="related_purchases",
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
        additional_info = [
            str(item)
            for item in [
                f"{self.num_purchases} game{pluralize(self.num_purchases)}",
                self.date_purchased,
                self.standardized_price,
            ]
            if item
        ]
        return f"{self.standardized_name} ({', '.join(additional_info)})"

    def is_game(self):
        return self.type == self.GAME

    def price_or_currency_differ_from(self, purchase_to_compare):
        return (
            self.price != purchase_to_compare.price
            or self.price_currency != purchase_to_compare.price_currency
        )

    def save(self, *args, **kwargs):
        if self.type != Purchase.GAME and not self.related_purchase:
            raise ValidationError(
                f"{self.get_type_display()} must have a related purchase."
            )
        if self.pk is not None:
            # Retrieve the existing instance from the database
            existing_purchase = Purchase.objects.get(pk=self.pk)
            # If price has changed, reset converted fields
            if existing_purchase.price_or_currency_differ_from(self):
                from games.tasks import currency_to

                exchange_rate = get_or_create_rate(
                    self.price_currency, currency_to, self.date_purchased.year
                )
                if exchange_rate:
                    self.converted_price = floatformat(self.price * exchange_rate, 0)
                    self.converted_currency = currency_to
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
    timestamp_start = models.DateTimeField()
    timestamp_end = models.DateTimeField(blank=True, null=True)
    duration_manual = models.DurationField(blank=True, null=True, default=timedelta(0))
    duration_calculated = models.DurationField(blank=True, null=True)
    device = models.ForeignKey(
        "Device",
        on_delete=models.SET_DEFAULT,
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
        mark = ", manual" if self.is_manual() else ""
        return f"{str(self.game)} {str(self.timestamp_start.date())} ({self.duration_formatted()}{mark})"

    def finish_now(self):
        self.timestamp_end = timezone.now()

    def start_now():
        self.timestamp_start = timezone.now()

    def duration_seconds(self) -> timedelta:
        manual = timedelta(0)
        calculated = timedelta(0)
        if self.is_manual() and isinstance(self.duration_manual, timedelta):
            manual = self.duration_manual
        if self.timestamp_end is not None and self.timestamp_start is not None:
            calculated = self.timestamp_end - self.timestamp_start
        return timedelta(seconds=(manual + calculated).total_seconds())

    def duration_formatted(self) -> str:
        result = format_duration(self.duration_seconds(), "%02.0H:%02.0m")
        return result

    def is_manual(self) -> bool:
        return not self.duration_manual == timedelta(0)

    @property
    def duration_sum(self) -> str:
        return Session.objects.all().total_duration_formatted()

    def save(self, *args, **kwargs) -> None:
        if self.timestamp_start is not None and self.timestamp_end is not None:
            self.duration_calculated = self.timestamp_end - self.timestamp_start
        else:
            self.duration_calculated = timedelta(0)

        if not isinstance(self.duration_manual, timedelta):
            self.duration_manual = timedelta(0)

        if not self.device:
            default_device, _ = Device.objects.get_or_create(
                type=Device.UNKNOWN, defaults={"name": "Unknown"}
            )
            self.device = default_device
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
                exchange_rate = ExchangeRate.objects.create(
                    currency_from=currency_from,
                    currency_to=currency_to,
                    year=year,
                    rate=floatformat(rate, 2),
                )
                exchange_rate = exchange_rate.rate
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
