"""A flag's box over the rows' held state."""

from dataclasses import dataclass
from typing import Literal, NamedTuple

from common.components.core import Node
from common.components.custom_elements import TriState, _TriStateCheckbox
from common.components.primitives import (
    CHECKBOX_LOOK_CLASS,
    DISABLED_CONTROL_CLASS,
    Input,
    Span,
)

type DefiniteState = Literal["checked", "unchecked"]
type PostedWord = str  # what a definite state posts


@dataclass(frozen=True, slots=True)
class TriStateWords:
    """What each definite state posts."""

    checked: PostedWord
    unchecked: PostedWord

    def __post_init__(self) -> None:
        if not self.checked or not self.unchecked:
            raise ValueError("a definite state needs a non-empty posted word")
        if self.checked == self.unchecked:
            raise ValueError("the two definite states need two posted words")


class TriStateHints(NamedTuple):
    """The hint per state."""

    mixed: str
    kept: str
    changed: str


def _hint(stated: DefiniteState | None, held: TriState, hints: TriStateHints) -> str:
    if stated is None:
        return hints.mixed if held == "mixed" else hints.kept
    return hints.kept if stated == held else hints.changed


def _posted(
    stated: DefiniteState | None, held: TriState, words: TriStateWords
) -> PostedWord:
    if stated is None or stated == held:
        return ""
    return words.checked if stated == "checked" else words.unchecked


def TriStateCheckbox(
    *,
    name: str,
    box_id: str,
    held: TriState,
    stated: DefiniteState | None,
    words: TriStateWords,
    hints: TriStateHints,
) -> Node:
    """Shows ``stated`` or ``held``; posts the difference."""
    hint_id = f"{box_id}-hint"
    shown = held if stated is None else stated
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
        # Both inputs: restored state would contradict held.
        Input(
            type="checkbox",
            id=box_id,
            data_tri_state_box="",
            aria_describedby=hint_id,
            autocomplete="off",
            disabled=True,
            checked=shown == "checked",
            class_=f"{CHECKBOX_LOOK_CLASS} {DISABLED_CONTROL_CLASS}",
        ),
        Input(
            type="hidden",
            name=name,
            value=_posted(stated, held, words),
            data_tri_state_value="",
            autocomplete="off",
        ),
    ]
