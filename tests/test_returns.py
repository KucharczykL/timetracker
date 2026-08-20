"""The origin mechanism: what may travel in ?origin=, and what must not."""

import pytest
from django.urls import reverse

from common.returns import ORIGIN_PARAM, action_url, parse_origin

RETURNABLE = frozenset({"games:list_games", "games:view_game"})
LIST_URL = "/tracker/game/list?page=3"


# Any catalog route takes a UUIDv7; the value never reaches the database.
GAME_ID = "018f5e66-e800-7000-8000-000000000001"


def _request(request_factory, origin_value=None):
    query = {ORIGIN_PARAM: origin_value} if origin_value is not None else {}
    return request_factory.get("/tracker/game/1/edit", query)


def test_action_url_appends_the_encoded_origin(db):
    assert action_url("games:edit_game", GAME_ID, origin=LIST_URL) == (
        reverse("games:edit_game", args=[GAME_ID])
        + "?origin=%2Ftracker%2Fgame%2Flist%3Fpage%3D3"
    )


def test_action_url_without_an_origin_is_the_bare_url(db):
    assert action_url("games:edit_game", GAME_ID, origin=None) == reverse(
        "games:edit_game", args=[GAME_ID]
    )


def test_valid_origin_survives(rf, db):
    assert parse_origin(_request(rf, LIST_URL), returnable=RETURNABLE) == LIST_URL


def test_absent_origin_is_none(rf, db):
    assert parse_origin(_request(rf), returnable=RETURNABLE) is None


@pytest.mark.parametrize(
    "candidate",
    [
        "https://evil.example/steal",
        "//evil.example/steal",
        "javascript:alert(1)",
        "/tracker/no-such-route",
        "",
    ],
)
def test_unsafe_or_unroutable_origins_are_rejected(rf, db, candidate):
    assert parse_origin(_request(rf, candidate), returnable=RETURNABLE) is None


def test_external_host_with_valid_returnable_path_is_rejected(rf, db):
    """A crafted origin can pair an external host with a path that legitimately
    resolves to a url name in RETURNABLE. Without the host check, this becomes
    an open redirect. This test pins that the host/scheme validation runs *before*
    the route resolver, not after."""
    # /tracker/game/list resolves to games:list_games, which IS in RETURNABLE.
    # But the host is external.
    candidate = "https://evil.example/tracker/game/list"
    assert parse_origin(_request(rf, candidate), returnable=RETURNABLE) is None


@pytest.mark.parametrize(
    "candidate",
    ["/tracker/game/1/delete", "/api/games/search", "/logout/"],
)
def test_origins_outside_the_returnable_set_are_rejected(rf, db, candidate):
    """A resolving path is not enough: a mutating target would let a crafted
    link launder the user's confirming POST into a second mutation."""
    assert parse_origin(_request(rf, candidate), returnable=RETURNABLE) is None


def test_an_embedded_newline_is_stripped_not_passed_through(rf, db):
    """Django validates the stripped URL; returning the raw one would raise
    BadHeaderError in redirect() after the mutation had already committed."""
    parsed = parse_origin(_request(rf, "\n" + LIST_URL), returnable=RETURNABLE)
    assert parsed == LIST_URL


def test_rejected_path_is_dropped(rf, db):
    detail = reverse("games:view_game", args=[GAME_ID, "test-game"])
    assert (
        parse_origin(_request(rf, detail), returnable=RETURNABLE, reject=detail) is None
    )
    assert parse_origin(_request(rf, detail), returnable=RETURNABLE) == detail
