from django.contrib import admin

from games.models import Game, Platform, Purchase, Session, Edition, Device

# Register your models here.
admin.site.register(Game)
admin.site.register(Purchase)
admin.site.register(Platform)
admin.site.register(Session)
admin.site.register(Edition)
admin.site.register(Device)
