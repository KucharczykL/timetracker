"""The External references area of a record's form.

One labelled row per registered provider. No add button, no count
field and no clone template: the rows are the registry, and the
registry does not change while a page is open.
"""

from typing import Final

from common.components import Div, FormFields, Node, Span
from games.reference_form import ReferenceSetForm

#: The Editions area's block, so the two read as one page.
_BLOCK_CLASS: Final[str] = "rounded-base border border-default-medium p-3 sm:p-4"


def references_area(form: ReferenceSetForm) -> Node:
    """Every provider's box, under one heading."""
    return Div(class_="flex flex-col gap-4")[
        Span(class_="text-type-subheading text-heading")["External references"],
        Div(class_=_BLOCK_CLASS)[FormFields(form)],
    ]
