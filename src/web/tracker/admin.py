from django.contrib import admin

from .models import Game, Platform, Purchase, Session

# Register your models here.
admin.site.register(Game)
admin.site.register(Purchase)
admin.site.register(Platform)
admin.site.register(Session)
