from django import template
import time
import os

register = template.Library()


@register.simple_tag
def version_date():
    return time.strftime(
        "%d-%b-%Y %H:%m",
        time.gmtime(os.path.getmtime(os.path.abspath(os.path.join(".git")))),
    )


@register.simple_tag
def version():
    return os.environ.get("VERSION_NUMBER", "UNKNOWN VERSION")
