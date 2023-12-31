from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from common.time import format_duration
from django.conf import settings
from django.db import models
from django.db.models import F, Manager, Sum


class Game(models.Model):
    name = models.CharField(max_length=255)
    sort_name = models.CharField(max_length=255, null=True, blank=True, default=None)
    year_released = models.IntegerField(null=True, blank=True, default=None)
    wikidata = models.CharField(max_length=50, null=True, blank=True, default=None)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        def get_sort_name(name):
            articles = ["a", "an", "the"]
            name_parts = name.split()
            first_word = name_parts[0].lower()
            if first_word in articles:
                return f"{' '.join(name_parts[1:])}, {name_parts[0]}"
            else:
                return name

        self.sort_name = get_sort_name(self.name)
        super().save(*args, **kwargs)


class Edition(models.Model):
    class Meta:
        unique_together = [["name", "platform"]]

    game = models.ForeignKey("Game", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    sort_name = models.CharField(max_length=255, null=True, blank=True, default=None)
    platform = models.ForeignKey(
        "Platform", on_delete=models.CASCADE, null=True, blank=True, default=None
    )
    year_released = models.IntegerField(null=True, blank=True, default=None)
    wikidata = models.CharField(max_length=50, null=True, blank=True, default=None)

    def __str__(self):
        return self.sort_name

    def save(self, *args, **kwargs):
        def get_sort_name(name):
            articles = ["a", "an", "the"]
            name_parts = name.split()
            first_word = name_parts[0].lower()
            if first_word in articles:
                return f"{' '.join(name_parts[1:])}, {name_parts[0]}"
            else:
                return name

        self.sort_name = get_sort_name(self.name)
        super().save(*args, **kwargs)


class PurchaseQueryset(models.QuerySet):
    def refunded(self):
        return self.filter(date_refunded__isnull=False)

    def not_refunded(self):
        return self.filter(date_refunded__isnull=True)

    def finished(self):
        return self.filter(date_finished__isnull=False)


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

    objects = PurchaseQueryset().as_manager()

    edition = models.ForeignKey("Edition", on_delete=models.CASCADE)
    platform = models.ForeignKey(
        "Platform", on_delete=models.CASCADE, default=None, null=True, blank=True
    )
    date_purchased = models.DateField()
    date_refunded = models.DateField(blank=True, null=True)
    date_finished = models.DateField(blank=True, null=True)
    price = models.IntegerField(default=0)
    price_currency = models.CharField(max_length=3, default="USD")
    ownership_type = models.CharField(
        max_length=2, choices=OWNERSHIP_TYPES, default=DIGITAL
    )

    def __str__(self):
        platform_info = self.platform
        if self.platform != self.edition.platform:
            platform_info = f"{self.edition.platform} version on {self.platform}"
        return f"{self.edition} ({platform_info}, {self.edition.year_released}, {self.get_ownership_type_display()})"


class Platform(models.Model):
    name = models.CharField(max_length=255)
    group = models.CharField(max_length=255, null=True, blank=True, default=None)

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


class Session(models.Model):
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

    objects = SessionQuerySet.as_manager()

    def __str__(self):
        mark = ", manual" if self.duration_manual != None else ""
        return f"{str(self.purchase)} {str(self.timestamp_start.date())} ({self.duration_formatted()}{mark})"

    def finish_now(self):
        self.timestamp_end = datetime.now(ZoneInfo(settings.TIME_ZONE))

    def start_now():
        self.timestamp_start = datetime.now(ZoneInfo(settings.TIME_ZONE))

    def duration_seconds(self) -> timedelta:
        manual = timedelta(0)
        calculated = timedelta(0)
        if not self.duration_manual in (None, 0, timedelta(0)):
            manual = self.duration_manual
        if self.timestamp_end != None and self.timestamp_start != None:
            calculated = self.timestamp_end - self.timestamp_start
        return timedelta(seconds=(manual + calculated).total_seconds())

    def duration_formatted(self) -> str:
        result = format_duration(self.duration_seconds(), "%02.0H:%02.0m")
        return result

    @property
    def duration_sum(self) -> str:
        return Session.objects.all().total_duration_formatted()

    def save(self, *args, **kwargs):
        if self.timestamp_start != None and self.timestamp_end != None:
            self.duration_calculated = self.timestamp_end - self.timestamp_start
        else:
            self.duration_calculated = timedelta(0)

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

    def __str__(self):
        return f"{self.name} ({self.get_type_display()})"
