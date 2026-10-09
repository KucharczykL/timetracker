"""TriStateCheckbox: the box, its hint and the one hidden input."""

import re

import pytest

from common.components import collect_media
from common.components.primitives import CHECKBOX_LOOK_CLASS
from common.components.tri_state_checkbox import (
    TriStateCheckbox,
    TriStateHints,
    TriStateWords,
)

TRI_STATE_SCRIPT = "dist/elements/tri-state-checkbox.js"
WORDS = TriStateWords(checked="True", unchecked="False")
HINTS = TriStateHints(mixed="Keep: mixed", kept="Keep", changed="Will change")


def render(held, stated) -> str:
    return str(
        TriStateCheckbox(
            name="mastered",
            box_id="id_choice-mastered",
            held=held,
            stated=stated,
            words=WORDS,
            hints=HINTS,
        )
    )


def tag(markup: str, marker: str) -> str:
    match = re.search(rf"<[^>]*{marker}[^>]*>", markup)
    assert match, f"no {marker} in {markup}"
    return match.group(0)


def hint_text(markup: str) -> str:
    match = re.search(r"data-tri-state-hint[^>]*>([^<]*)<", markup)
    assert match
    return match.group(1)


def hidden_value(markup: str) -> str:
    return re.search(r'value="([^"]*)"', tag(markup, "data-tri-state-value")).group(1)


def is_checked(markup: str) -> bool:
    return (
        re.search(r"\schecked(=|\s|>)", tag(markup, "data-tri-state-box")) is not None
    )


@pytest.mark.parametrize(
    ("held", "checked", "hint"),
    [
        ("checked", True, "Keep"),
        ("unchecked", False, "Keep"),
        ("mixed", False, "Keep: mixed"),
    ],
)
def test_held_state_renders_the_box_and_its_keep_hint(held, checked, hint):
    markup = render(held, held)

    assert is_checked(markup) is checked
    assert hint_text(markup) == hint
    assert hidden_value(markup) == ""


def test_stated_checked_over_mixed_posts_its_word_and_says_will_change():
    markup = render("mixed", "checked")

    assert is_checked(markup)
    assert hidden_value(markup) == "True"
    assert hint_text(markup) == "Will change"


def test_stated_unchecked_over_checked_posts_its_word():
    markup = render("checked", "unchecked")

    assert not is_checked(markup)
    assert hidden_value(markup) == "False"
    assert hint_text(markup) == "Will change"


def test_stated_equal_to_agreeing_held_posts_nothing():
    markup = render("unchecked", "unchecked")

    assert hidden_value(markup) == ""
    assert hint_text(markup) == "Keep"


def test_stated_mixed_over_mixed_posts_nothing():
    markup = render("mixed", "mixed")

    assert hidden_value(markup) == ""
    assert hint_text(markup) == "Keep: mixed"


def test_mixed_cannot_be_stated_over_a_held_state():
    with pytest.raises(ValueError):
        render("checked", "mixed")


def test_the_box_is_a_nameless_check_all_look_checkbox():
    box = tag(render("mixed", "mixed"), "data-tri-state-box")

    assert 'type="checkbox"' in box
    assert CHECKBOX_LOOK_CLASS in box
    assert 'autocomplete="off"' in box
    assert 'id="id_choice-mastered"' in box
    assert 'aria-describedby="id_choice-mastered-hint"' in box
    assert "name=" not in box


def test_the_hidden_input_carries_the_field_name_and_no_autofill():
    hidden = tag(render("checked", "checked"), "data-tri-state-value")

    assert 'type="hidden"' in hidden
    assert 'name="mastered"' in hidden
    assert 'autocomplete="off"' in hidden


def test_the_host_states_its_props_for_the_element():
    host = tag(render("mixed", "mixed"), "tri-state-checkbox")

    assert 'name="mastered"' in host
    assert 'held="mixed"' in host
    assert 'checked-word="True"' in host
    assert 'unchecked-word="False"' in host
    assert 'hint-mixed="Keep: mixed"' in host
    assert 'hint-kept="Keep"' in host
    assert 'hint-changed="Will change"' in host


def test_the_element_script_is_collected():
    assert (
        TRI_STATE_SCRIPT
        in collect_media(
            TriStateCheckbox(
                name="mastered",
                box_id="box",
                held="mixed",
                stated="mixed",
                words=WORDS,
                hints=HINTS,
            )
        ).js
    )
