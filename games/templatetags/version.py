import os
from datetime import UTC, datetime
from pathlib import Path

from django import template
from django.conf import settings

register = template.Library()


def version_modified_at() -> datetime:
    """Return the version source's modification instant as aware UTC."""

    return datetime.fromtimestamp(
        (Path(settings.BASE_DIR) / "pyproject.toml").stat().st_mtime,
        tz=UTC,
    )


@register.simple_tag
def version():
    return os.environ.get("VERSION_NUMBER", "git-main")
