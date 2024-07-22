from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Manager, Sum
from django.utils import timezone

from common.time import format_duration


class Game(models.Model):
    name = models.CharField(max_length=255)
    sort_name = models.CharField(max_length=255, null=True, blank=True, default=None)
    year_released = models.IntegerField(null=True, blank=True, default=None)
    wikidata = models.CharField(max_length=50, null=True, blank=True, default=None)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Edition(models.Model):
    class Meta:
        unique_together = [["name", "platform", "year_released"]]

    game = models.ForeignKey("Game", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    sort_name = models.CharField(max_length=255, null=True, blank=True, default=None)
    platform = models.ForeignKey(
        "Platform", on_delete=models.CASCADE, null=True, blank=True, default=None
    )
    year_released = models.IntegerField(null=True, blank=True, default=None)
    wikidata = models.CharField(max_length=50, null=True, blank=True, default=None)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.sort_name


class PurchaseQueryset(models.QuerySet):
    def refunded(self):
        return self.filter(date_refunded__isnull=False)

    def not_refunded(self):
        return self.filter(date_refunded__isnull=True)

    def finished(self):
        return self.filter(date_finished__isnull=False)

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

    edition = models.ForeignKey("Edition", on_delete=models.CASCADE)
    platform = models.ForeignKey(
        "Platform", on_delete=models.CASCADE, default=None, null=True, blank=True
    )
    date_purchased = models.DateField()
    date_refunded = models.DateField(blank=True, null=True)
    date_finished = models.DateField(blank=True, null=True)
    date_dropped = models.DateField(blank=True, null=True)
    infinite = models.BooleanField(default=False)
    price = models.IntegerField(default=0)
    price_currency = models.CharField(max_length=3, default="USD")
    ownership_type = models.CharField(
        max_length=2, choices=OWNERSHIP_TYPES, default=DIGITAL
    )
    type = models.CharField(max_length=255, choices=TYPES, default=GAME)
    name = models.CharField(max_length=255, default="", null=True, blank=True)
    related_purchase = models.ForeignKey(
        "Purchase",
        on_delete=models.SET_NULL,
        default=None,
        null=True,
        blank=True,
        related_name="related_purchases",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        additional_info = [
            self.get_type_display() if self.type != Purchase.GAME else "",
            (
                f"{self.edition.platform} version on {self.platform}"
                if self.platform != self.edition.platform
                else self.platform
            ),
            self.edition.year_released,
            self.get_ownership_type_display(),
        ]
        return f"{self.edition} ({', '.join(filter(None, map(str, additional_info)))})"

    def is_game(self):
        return self.type == self.GAME

    def save(self, *args, **kwargs):
        if self.type == Purchase.GAME:
            self.name = ""
        elif self.type != Purchase.GAME and not self.related_purchase:
            raise ValidationError(
                f"{self.get_type_display()} must have a related purchase."
            )
        super().save(*args, **kwargs)


class Platform(models.Model):
    name = models.CharField(max_length=255)
    group = models.CharField(max_length=255, null=True, blank=True, default=None)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


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

    purchase = models.ForeignKey("Purchase", on_delete=models.CASCADE)
    timestamp_start = models.DateTimeField()
    timestamp_end = models.DateTimeField(blank=True, null=True)
    duration_manual = models.DurationField(blank=True, null=True, default=timedelta(0))
    duration_calculated = models.DurationField(blank=True, null=True)
    device = models.ForeignKey(
        "Device",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        default=None,
    )
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    objects = SessionQuerySet.as_manager()

    def __str__(self):
        mark = ", manual" if self.is_manual() else ""
        return f"{str(self.purchase)} {str(self.timestamp_start.date())} ({self.duration_formatted()}{mark})"

    def finish_now(self):
        self.timestamp_end = timezone.now()

    def start_now():
        self.timestamp_start = timezone.now()

    def duration_seconds(self) -> timedelta:
        manual = timedelta(0)
        calculated = timedelta(0)
        if self.is_manual() and isinstance(self.duration_manual, timedelta):
            manual = self.duration_manual
        if self.timestamp_end != None and self.timestamp_start != None:
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

    def save(self, *args, **kwargs):
        if self.timestamp_start != None and self.timestamp_end != None:
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
    PC = "pc"
    CONSOLE = "co"
    HANDHELD = "ha"
    MOBILE = "mo"
    SBC = "sbc"
    UNKNOWN = "un"
    DEVICE_TYPES = [
        (PC, "PC"),
        (CONSOLE, "Console"),
        (HANDHELD, "Handheld"),
        (MOBILE, "Mobile"),
        (SBC, "Single-board computer"),
        (UNKNOWN, "Unknown"),
    ]
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=3, choices=DEVICE_TYPES, default=UNKNOWN)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"
