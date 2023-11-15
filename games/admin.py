from django.contrib import admin

from games.models import Device, Edition, Game, Platform, Purchase, Session

# Register your models here.
admin.site.register(Game)
admin.site.register(Purchase)
admin.site.register(Platform)
admin.site.register(Session)
admin.site.register(Edition)
admin.site.register(Device)
