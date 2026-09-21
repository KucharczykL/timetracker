"""One row, made from the name a person typed.

The picker's create row states a name and nothing else.
Every other rule belongs to the form the add page runs, so
both routes run that form rather than a rule of their own.
"""

from django import forms

from games.models import UserLibrary

#: What a created row answers: a key, and what a picker shows.
type RowKey = str  # a UUIDv7, as text
type RowLabel = str  # e.g. "Steam Deck"


def refusal_sentence(form: forms.BaseForm) -> str:
    """One sentence for everything the form refused.

    Non-field errors are read beside field errors: a
    Platform that shadows a shared row states its refusal
    under `__all__`, and a sentence built from the fields
    alone would say nothing at all.
    """
    sentences = [
        str(message) for messages in form.errors.values() for message in messages
    ]
    return " ".join(sentences) or "That name was refused."


def created_by_form(form_class, *, library: UserLibrary, name: str, **fields):
    """The form the add page runs, over one typed name.

    Answers the saved row, or raises `RowRefused` carrying
    the sentence the form stated.
    """
    form = form_class(data={"name": name.strip(), **fields}, library=library)
    if not form.is_valid():
        raise RowRefused(refusal_sentence(form))
    return form.save()


class RowRefused(Exception):
    """The form refused the name, and says why."""

    def __init__(self, sentence: str) -> None:
        super().__init__(sentence)
        self.sentence = sentence
