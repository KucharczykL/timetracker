from datetime import timedelta

from django import template

from common.time import durationformat, format_duration

register = template.Library()


@register.filter(name="format_duration")
def filter_format_duration(duration: timedelta, argument: str = durationformat):
    return format_duration(duration, format_string=argument)
