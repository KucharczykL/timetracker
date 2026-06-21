from urllib.parse import parse_qs, urlparse

import pytest
from django.test import RequestFactory

from common.layout import NavbarPlaytime
from games.filters import parse_session_filter


def test_navbar_playtime_has_stable_id_and_values():
    html = str(NavbarPlaytime("1 h 00 m", "7 h 00 m"))
    assert 'id="navbar-playtime"' in html
    assert "1 h 00 m" in html
    assert "7 h 00 m" in html
    assert "hx-swap-oob" not in html


def test_navbar_playtime_oob_flag():
    html = str(NavbarPlaytime("1 h 00 m", "7 h 00 m", oob=True))
    assert 'id="navbar-playtime"' in html
    assert 'hx-swap-oob="true"' in html


def test_navbar_playtime_wraps_totals_in_links():
    html = str(
        NavbarPlaytime(
            "1 h 00 m",
            "5 h 00 m",
            today_url="/sessions/?filter=today",
            last_7_url="/sessions/?filter=week",
        )
    )
    assert 'href="/sessions/?filter=today"' in html
    assert 'href="/sessions/?filter=week"' in html
    assert "1 h 00 m" in html
    assert "5 h 00 m" in html


@pytest.mark.django_db
def test_model_counts_exposes_session_filter_urls():
    from games.views.general import model_counts

    request = RequestFactory().get("/")
    counts = model_counts(request)

    today_filter_json = parse_qs(urlparse(counts["today_url"]).query)["filter"][0]
    last_7_filter_json = parse_qs(urlparse(counts["last_7_url"]).query)["filter"][0]

    assert parse_session_filter(today_filter_json).timestamp_start is not None
    assert parse_session_filter(last_7_filter_json).timestamp_start is not None
