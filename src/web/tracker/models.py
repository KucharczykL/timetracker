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
        return f"{str(self.purchase)} {str(self.timestamp_start.date())} ({self.total_duration()}{mark})"

    def calculated_duration(self):
        if self.timestamp_end == None or self.timestamp_start == None:
            return 0
        else:
            return self.timestamp_end - self.timestamp_start

    def total_duration(self):
        return (
            self.calculated_duration()
            if self.duration_manual == None
            else self.duration_manual + self.calculated_duration()
        )

    def save(self, *args, **kwargs):
        if self.timestamp_start != None and self.timestamp_end != None:
            self.duration_calculated = self.timestamp_end - self.timestamp_start
        super(Session, self).save(*args, **kwargs)
