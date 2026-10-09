"""A flag's box over the rows' held state."""

from typing import Literal, NamedTuple

from common.components.core import Node
from common.components.custom_elements import _TriStateCheckbox
from common.components.primitives import CHECKBOX_LOOK_CLASS, Input, Span

type TriState = Literal["checked", "unchecked", "mixed"]


class TriStateWords(NamedTuple):
    """What each definite state posts."""

    checked: str
    unchecked: str


class TriStateHints(NamedTuple):
    """The muted hint beside the box."""

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
    """Shows ``stated``; posts it against ``held``."""
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
        # Restored form state would contradict held.
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
