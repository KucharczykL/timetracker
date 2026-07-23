from datetime import UTC, datetime

from django.test import Client
from django.urls import reverse
from django.utils import timezone

import common.layout
from games.templatetags.version import version_modified_at


def test_version_modified_at_is_an_aware_utc_datetime() -> None:
    value = version_modified_at()

    assert isinstance(value, datetime)
    assert timezone.is_aware(value)
    assert value.tzinfo is UTC


def test_footer_formats_build_timestamp_through_request_presentation(
    db, monkeypatch
) -> None:
    monkeypatch.setattr(
        common.layout,
        "version_modified_at",
        lambda: datetime(2026, 7, 22, 12, 5, tzinfo=UTC),
    )

    html = Client().get(reverse("login")).content.decode()

    assert "git-main (2026-07-22 12:05)" in html
