from django.db import models
from datetime import timedelta


class Game(models.Model):
    name = models.CharField(max_length=255)
    wikidata = models.CharField(max_length=50)

    def __str__(self):
        return self.name


class Purchase(models.Model):
    game = models.ForeignKey("Game", on_delete=models.CASCADE)
    platform = models.ForeignKey("Platform", on_delete=models.CASCADE)
    date_purchased = models.DateField()
    date_refunded = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"{self.game} ({self.platform})"


class Platform(models.Model):
    name = models.CharField(max_length=255)
    group = models.CharField(max_length=255)

    def __str__(self):
        return self.name


class Session(models.Model):
    purchase = models.ForeignKey("Purchase", on_delete=models.CASCADE)
    timestamp_start = models.DateTimeField()
    timestamp_end = models.DateTimeField(blank=True, null=True)
    duration_manual = models.DurationField(blank=True, null=True)
    duration_calculated = models.DurationField(blank=True, null=True)
    note = models.TextField(blank=True, null=True)

    def __str__(self):
        mark = ", manual" if self.duration_manual != None else ""
        return f"{str(self.purchase)} {str(self.timestamp_start.date())} ({self.duration_any()}{mark})"

    def duration_seconds(self):
        if self.timestamp_end == None or self.timestamp_start == None:
            if self.duration_manual == None:
                return 0
            else:
                value = self.duration_manual
        else:
            value = self.timestamp_end - self.timestamp_start
        return value.total_seconds()

    def duration_formatted(self):
        seconds = self.duration_seconds()
        if seconds == 0:
            return seconds
        hours, remainder = divmod(seconds, 3600)
        minutes = remainder % 60
        hour_string = f"{int(hours)}h" if hours != 0 else ""
        minute_string = f"{int(minutes)}m" if minutes != 0 else ""
        return f"{hour_string}{minute_string}"

    def duration_any(self):
        return (
            self.duration_formatted()
            if self.duration_manual == None
            else self.duration_manual
        )

    def save(self, *args, **kwargs):
        if self.timestamp_start != None and self.timestamp_end != None:
            self.duration_calculated = self.timestamp_end - self.timestamp_start
        super(Session, self).save(*args, **kwargs)
