import re
from html import unescape
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


def test_navbar_playtime_renders_the_totals_it_is_given():
    # Each total arrives as a node that owns its own link and popover — the
    # linking cannot happen here, since a popover trigger may not sit inside
    # an <a>.
    html = str(NavbarPlaytime("1 h 00 m", "5 h 00 m"))
    assert "1 h 00 m" in html
    assert "5 h 00 m" in html


@pytest.mark.django_db
def test_model_counts_exposes_session_filter_urls():
    from games.views.general import model_counts

    request = RequestFactory().get("/")
    counts = model_counts(request)

    # The urls now live inside the rendered Duration nodes rather than as
    # separate context keys; what matters is that the filter JSON they carry
    # still parses.
    for key in ("today_played", "last_7_played"):
        href = re.search(r'href="([^"]+)"', str(counts[key]))
        assert href is not None
        filter_json = parse_qs(urlparse(unescape(href.group(1))).query)["filter"][0]
        assert parse_session_filter(filter_json).timestamp_start is not None
