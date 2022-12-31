from django.db import models


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
    timestamp_end = models.DateTimeField()
    duration_manual = models.DurationField(blank=True, null=True)
    duration_calculated = models.DurationField(blank=True, null=True)
    note = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.purchase

    def calculated_duration(self):
        return self.timestamp_end - self.timestamp_start
