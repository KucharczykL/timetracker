"""One row, made from the name a person typed.

The device and platform create rows state a name and
nothing else. Every other rule belongs to the form the add
page runs, so both routes run that form rather than a rule
of their own. A run states a command instead.
"""

from typing import Any, Protocol

from django import forms

from games.models import UserLibrary


class NamedRow(Protocol):
    """What a create route answers about the row it made."""

    pk: Any
    name: str


class NameForm(Protocol):
    """What a create route asks of the form it runs.

    The add pages' forms take the library themselves, which
    is what scopes the row they save, and answer that row.
    """

    def __call__(
        self, *, data: dict[str, object], library: UserLibrary
    ) -> forms.BaseForm: ...


def refusal_sentence(form: forms.BaseForm) -> str:
    """One sentence for everything the form refused.

    Non-field errors are read beside field errors: a
    Platform that shadows a shared row states its refusal
    under `__all__`, and a sentence built from the fields
    alone would say nothing at all.

    A field error names its field, because a create row
    renders one field and the refused one may be another.
    """
    sentences: list[str] = []
    for field_name, messages in form.errors.items():
        field = form.fields.get(field_name)
        label = "" if field is None else str(field.label or field_name)
        sentences += [
            str(message) if not label else f"{label}: {message}" for message in messages
        ]
    return " ".join(sentences).strip() or "That name was refused."


def created_by_form(
    form_class: NameForm, *, library: UserLibrary, name: str, **fields: object
) -> NamedRow:
    """The form the add page runs, over one typed name.

    Answers the saved row, or raises `RowRefused` carrying
    the sentence the form stated.
    """
    form = form_class(data={"name": name.strip(), **fields}, library=library)
    if not form.is_valid():
        raise RowRefused(refusal_sentence(form))
    #: Every form this runs is a ModelForm, which the protocol
    #: cannot state: a form that only validates states no save.
    saved: NamedRow = form.save()  # type: ignore[attr-defined]
    return saved


class RowRefused(Exception):
    """The form refused the name, and says why."""

    def __init__(self, sentence: str) -> None:
        super().__init__(sentence)
        self.sentence = sentence
