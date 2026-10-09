"""The tri-state box, hint and hidden input."""

import re

import pytest

from common.components import collect_media
from common.components.primitives import CHECKBOX_LOOK_CLASS, DISABLED_CONTROL_CLASS
from common.components.tri_state_checkbox import (
    TriStateCheckbox,
    TriStateHints,
    TriStateWords,
)

TRI_STATE_SCRIPT = "dist/elements/tri-state-checkbox.js"
WORDS = TriStateWords(checked="True", unchecked="False")
HINTS = TriStateHints(mixed="Keep: mixed", kept="Keep", changed="Will change")


def render(held, stated) -> str:
    """``stated`` None keeps ``held``."""
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
    value = re.search(r'value="([^"]*)"', tag(markup, "data-tri-state-value"))
    assert value
    return value.group(1)


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
    markup = render(held, None)

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


def test_unstated_mixed_posts_nothing():
    markup = render("mixed", None)

    assert hidden_value(markup) == ""
    assert hint_text(markup) == "Keep: mixed"


def test_unstated_checked_held_keeps_the_box_checked():
    markup = render("checked", None)

    assert is_checked(markup)
    assert hidden_value(markup) == ""
    assert hint_text(markup) == "Keep"


@pytest.mark.parametrize(
    ("checked", "unchecked"),
    [("", "False"), ("True", ""), ("True", "True")],
)
def test_words_refuse_an_empty_or_repeated_word(checked, unchecked):
    with pytest.raises(ValueError):
        TriStateWords(checked=checked, unchecked=unchecked)


def test_the_box_is_a_nameless_check_all_look_checkbox():
    box = tag(render("mixed", None), "data-tri-state-box")

    assert 'type="checkbox"' in box
    assert CHECKBOX_LOOK_CLASS in box
    assert DISABLED_CONTROL_CLASS in box
    assert re.search(r"\sdisabled(=|\s|>)", box)
    assert 'autocomplete="off"' in box
    assert 'id="id_choice-mastered"' in box
    assert 'aria-describedby="id_choice-mastered-hint"' in box
    assert "name=" not in box


def test_the_hidden_input_carries_the_field_name_and_no_autofill():
    hidden = tag(render("checked", None), "data-tri-state-value")

    assert 'type="hidden"' in hidden
    assert 'name="mastered"' in hidden
    assert 'autocomplete="off"' in hidden


def test_the_host_states_its_props_for_the_element():
    host = tag(render("mixed", None), "tri-state-checkbox")

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
                stated=None,
                words=WORDS,
                hints=HINTS,
            )
        ).js
    )
