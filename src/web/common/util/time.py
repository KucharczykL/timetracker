from datetime import datetime
from django.conf import settings
from zoneinfo import ZoneInfo


def now():
    return datetime.now(ZoneInfo(settings.TIME_ZONE))
