"""What the line is told to offer."""

import pytest

from games.bulk_tray import tray_actions
from games.views.bulk import STATEMENT_FIELD

ORIGIN = "/session/list"


def test_an_act_is_offered_with_its_label_and_its_route():
    offered = tray_actions("session.remove", origin=ORIGIN)

    assert len(offered) == 1
    assert offered[0]["label"] == "Remove"
    assert offered[0]["cardinality"] == "many"
    assert "/bulk/session.remove/" in offered[0]["url"]


def test_the_url_carries_the_page_the_person_stands_on():
    offered = tray_actions("session.reclassify", origin=ORIGIN)

    assert "origin=%2Fsession%2Flist" in offered[0]["url"]


def test_every_named_act_is_offered_in_the_order_it_was_named():
    offered = tray_actions("session.reclassify", "session.remove", origin=ORIGIN)

    assert [action["label"] for action in offered] == [
        "Record as historical playtime",
        "Remove",
    ]


def test_a_name_no_act_declares_is_refused():
    """The view stated it, so a quiet omission would hide the typo."""
    with pytest.raises(ValueError, match="no declared act"):
        tray_actions("session.remoove", origin=ORIGIN)


def test_the_line_and_the_route_spell_the_statement_one_way():
    from common.components import SELECTION_STATEMENT_FIELD

    assert STATEMENT_FIELD == SELECTION_STATEMENT_FIELD
