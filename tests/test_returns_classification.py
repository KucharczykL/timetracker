"""Every routed name is classified exactly once.

Guarding on a name prefix (add_/edit_/delete_/…) does not hold: the session
clone route is named for where it is launched from, and a future clone_/reset_/
archive_ route would pass silently. Completeness against the real route table
has no such hole, and READ_ONLY doubles as the origin allow-list.
"""

from games import urls as games_urls
from games.views.returns import (
    CONFIRMATION,
    DEBUG_ONLY,
    IN_PLACE,
    ORIGIN_AWARE,
    READ_ONLY,
)

BUCKETS = {
    "READ_ONLY": READ_ONLY,
    "ORIGIN_AWARE": ORIGIN_AWARE,
    "CONFIRMATION": CONFIRMATION,
    "IN_PLACE": IN_PLACE,
}


def _routed_names() -> set[str]:
    return {
        f"games:{pattern.name}"
        for pattern in games_urls.urlpatterns
        if pattern.name is not None
    }


def test_every_routed_name_is_classified():
    classified = set().union(*BUCKETS.values())
    assert _routed_names() - classified == set()


def test_classifications_name_only_real_routes():
    classified = set().union(*BUCKETS.values())
    # The component-kit preview routes exist only when DEBUG was true at import.
    assert classified - _routed_names() <= DEBUG_ONLY


def test_no_name_is_in_two_buckets():
    seen: dict[str, str] = {}
    for bucket_name, names in BUCKETS.items():
        for name in names:
            assert name not in seen, f"{name} in {seen.get(name)} and {bucket_name}"
            seen[name] = bucket_name
