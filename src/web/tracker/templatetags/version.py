import os
import time

from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def version_date():
    return time.strftime(
        "%d-%b-%Y %H:%m",
        time.gmtime(
            os.path.getmtime(
                os.path.abspath(
                    os.path.join(settings.BASE_DIR, "..", "..", "pyproject.toml")
                )
            )
        ),
    )


@register.simple_tag
def version():
    return os.environ.get("VERSION_NUMBER", "git-main")
