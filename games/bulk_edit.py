"""What every bulk Edit act shares.

Imports no act and not the act table: the table's foot imports the
acts, and an act importing this module first would find the table
half built.
"""

import json
import logging
from collections.abc import Callable, Sequence
from typing import Any, cast

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS

from common.components.custom_elements import TriState
from common.components.tri_state_checkbox import PostedWord, TriStateWords
from games.events.dispatch import CommandRejected, RowUnreadable
from games.forms import TriStateCheckboxWidget
from games.reads.fact_change import FactChange

logger = logging.getLogger("games")

#: A placeholder: what "leave as it is" keeps.
type Keeping = str  # "Keep: Played"

#: A statement as the runner carries it.
type CarriedStatement = str  # '{"status": "played"}'

#: One statement key.
type StatementKey = str  # "status"

STATEMENT_UNREADABLE = "What to change could not be read. Choose it again."


def keeping[RowT, ValueT](
    rows: Sequence[RowT],
    value: Callable[[RowT], ValueT],
    shown: Callable[[ValueT], str],
) -> Keeping:
    """What the rows hold; differing, "mixed"."""
    held = {value(row) for row in rows}
    if len(held) != 1:
        return "Keep: mixed"
    return f"Keep: {shown(held.pop())}"


#: A flag's two posted words.
FLAG_CHECKED: PostedWord = "True"
FLAG_UNCHECKED: PostedWord = "False"
_FLAG_WORDS = TriStateWords(checked=FLAG_CHECKED, unchecked=FLAG_UNCHECKED)


def flag_field(label: str) -> forms.TypedChoiceField:
    """A flag: a word states, nothing keeps."""
    return forms.TypedChoiceField(
        label=label,
        choices=((FLAG_CHECKED, "Yes"), (FLAG_UNCHECKED, "No")),
        coerce=lambda value: value == FLAG_CHECKED,
        empty_value=None,
        required=False,
        widget=TriStateCheckboxWidget(words=_FLAG_WORDS),
    )


def held_flag[RowT](rows: Sequence[RowT], value: Callable[[RowT], bool]) -> TriState:
    """What the rows hold; mixed where they differ."""
    if not rows:
        raise ValueError("a flag holds nothing across no rows")
    held = {value(row) for row in rows}
    if held == {True}:
        return "checked"
    if held == {False}:
        return "unchecked"
    return "mixed"


def hold_flag[RowT](
    form: forms.BaseForm,
    name: str,
    rows: Sequence[RowT],
    value: Callable[[RowT], bool],
) -> None:
    """Holds the rows' flag on the box ``name`` names."""
    cast(TriStateCheckboxWidget, form.fields[name].widget).held = held_flag(rows, value)


def statement_unreadable(message: str) -> CommandRejected:
    return CommandRejected(message, sentence=STATEMENT_UNREADABLE)


def stated_object(
    raw: CarriedStatement, keys: frozenset[StatementKey]
) -> dict[StatementKey, Any]:
    """A carried statement's JSON object, every key known."""
    try:
        stated = json.loads(raw)
    except ValueError as unreadable:
        raise statement_unreadable(f"{raw!r} is no JSON: {unreadable}") from unreadable
    if not isinstance(stated, dict):
        raise statement_unreadable(f"{raw!r} is no object")
    unknown = set(stated) - keys
    if unknown:
        raise statement_unreadable(f"{raw!r} names {sorted(unknown)}")
    return stated


def settled[StatementT](
    choice: CarriedStatement | None,
    decode: Callable[[CarriedStatement], StatementT],
    *,
    act_name: str,
    row_description: str,
) -> StatementT:
    """The statement this request settled; its absence is ours.

    The act declares a choice, so the runner settles one before any
    row: a missing or unreadable one is a defect, not a refusal.
    """
    if choice is None:
        raise RowUnreadable(
            f"{act_name} ran with no statement for {row_description}. The act "
            "declares a choice, so the runner settles one before a row."
        )
    try:
        return decode(choice)
    except CommandRejected as drift:
        raise RowUnreadable(
            f"{act_name} settled {choice!r} and cannot read it back: {drift}"
        ) from drift


def form_refusal(form: forms.Form, *, labelled: bool) -> CommandRejected:
    """A refused form's first error, as the confirmation shows it."""
    sentences = [
        _named(form, name, str(message)) if labelled else str(message)
        for name, messages in form.errors.items()
        for message in messages
    ]
    return CommandRejected(f"the edit form refuses: {sentences}", sentence=sentences[0])


def _named(form: forms.Form, name: str, message: str) -> str:
    """A field's message, led by its label."""
    if name == NON_FIELD_ERRORS:
        return message
    return f"{form.fields[name].label}: {message}"


def restated[T](change: FactChange[T] | None, held: T) -> T | None:
    """The earlier value, where the row differs."""
    if change is None or held == change.before:
        return None
    return change.before


def log_overwrite(
    change: FactChange[Any] | None,
    held: object,
    *,
    act_name: str,
    fact: str,
    row_description: str,
) -> None:
    """A later value the Undo writes over."""
    if change is None or held in (change.before, change.stated):
        return
    logger.info(
        "[bulk]: %s Undo states %s %s over %s on %s",
        act_name,
        fact,
        change.before,
        held,
        row_description,
    )
