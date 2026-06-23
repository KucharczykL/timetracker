"""HTTP typing helpers shared across the app."""

from django.http import HttpRequest
from django_htmx.middleware import HtmxDetails


class HtmxHttpRequest(HttpRequest):
    """An ``HttpRequest`` carrying the ``htmx`` attribute that django-htmx's
    middleware adds to every request. Use as the request annotation in any view
    that branches on ``request.htmx``."""

    htmx: HtmxDetails
