"""TriStateCheckbox: a flag's box over the rows' held state.

The box posts nothing; one hidden input carries the field's name and posts
the word the shown state states over the held one, or nothing where the two
agree. ``ts/elements/tri-state-checkbox.ts`` drives the cycle.
"""

from typing import Literal, NamedTuple

from common.components.core import Node
from common.components.custom_elements import _TriStateCheckbox
from common.components.primitives import CHECKBOX_LOOK_CLASS, Input, Span

type TriState = Literal["checked", "unchecked", "mixed"]


class TriStateWords(NamedTuple):
    """What the hidden input posts for each definite state."""

    checked: str
    unchecked: str


class TriStateHints(NamedTuple):
    """The muted line beside the box."""

    mixed: str
    kept: str
    changed: str


def _hint(stated: TriState, held: TriState, hints: TriStateHints) -> str:
    if stated == "mixed":
        return hints.mixed
    if stated == held:
        return hints.kept
    return hints.changed


def _posted(stated: TriState, held: TriState, words: TriStateWords) -> str:
    if stated == held:
        return ""
    if stated == "mixed":
        raise ValueError("mixed is only held, never stated over a definite state")
    return words.checked if stated == "checked" else words.unchecked


def TriStateCheckbox(
    *,
    name: str,
    box_id: str,
    held: TriState,
    stated: TriState,
    words: TriStateWords,
    hints: TriStateHints,
) -> Node:
    """The box shows ``stated``; the hidden input posts it against ``held``."""
    hint_id = f"{box_id}-hint"
    return _TriStateCheckbox(
        name=name,
        held=held,
        checked_word=words.checked,
        unchecked_word=words.unchecked,
        hint_mixed=hints.mixed,
        hint_kept=hints.kept,
        hint_changed=hints.changed,
        class_="inline-flex items-center gap-2",
    )[
        Span(id=hint_id, data_tri_state_hint="", class_="text-body-subtle")[
            _hint(stated, held, hints)
        ],
        # A restored form state would stand beside a held that disagrees.
        Input(
            type="checkbox",
            id=box_id,
            data_tri_state_box="",
            aria_describedby=hint_id,
            autocomplete="off",
            checked=stated == "checked",
            class_=CHECKBOX_LOOK_CLASS,
        ),
        Input(
            type="hidden",
            name=name,
            value=_posted(stated, held, words),
            data_tri_state_value="",
            autocomplete="off",
        ),
    ]
