from django.contrib import admin

from games.models import (
    Device,
    ExchangeRate,
    Game,
    Platform,
    Purchase,
    Session,
)

# Register your models here.
admin.site.register(Game)
admin.site.register(Purchase)
admin.site.register(Platform)
admin.site.register(Session)
admin.site.register(Device)
admin.site.register(ExchangeRate)
