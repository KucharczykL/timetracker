"""The Editions area of the Game form.

A Release row is not a table row with a radio at the end: the whole row
is the radio's label, and the mark is one group over the whole Game, so
exactly one row across every Edition carries it.

The block is a container query of its own. Narrow, a row stacks and each
control keeps a visible label; wide, the labels go `sr-only` and one
header row stands over the columns. The header and the cards are
separate grids, thus both declare `EDITION_COLUMNS`.
"""

from typing import Final

from django.forms import BoundField
from django.forms.forms import BaseForm

from common.components import (
    FORM_LABEL_CLASS,
    ICON_BUTTON_SIZE_CLASS,
    ChoiceCard,
    ChoiceCardGroup,
    ControlButton,
    Div,
    FieldErrors,
    Icon,
    Input,
    Label,
    Node,
    Safe,
    Span,
)
from common.components.primitives import field_label_id
from games.catalog_form import (
    EDITION_COUNT_FIELD,
    MARK_FIELD,
    CatalogGraphForm,
    EditionBlock,
    ReleaseRowForm,
    release_count_field,
    release_prefix,
)

#: Radio, platform, date, removal — once the block is wide enough.
#: A fixed first column so the header labels sit over their own controls.
EDITION_COLUMNS: Final[str] = (
    "@2xl/edition:grid-cols-[5.5rem_minmax(0,13rem)_minmax(0,1fr)_auto]"
)

#: Visible on a narrow card, named-but-unseen once the headers appear.
NARROW_LABEL_CLASS: Final[str] = f"{FORM_LABEL_CLASS} @2xl/edition:sr-only"

_BLOCK_CLASS: Final[str] = "rounded-base border border-default-medium p-3 sm:p-4"

_HEADINGS_CLASS: Final[str] = (
    "hidden border-b border-default pb-1 px-3 gap-3 "
    f"@2xl/edition:grid {EDITION_COLUMNS}"
)

_PLATFORM_PLACEMENT: Final[str] = "@2xl/edition:col-start-2 @2xl/edition:row-start-1"
_DATE_PLACEMENT: Final[str] = "@2xl/edition:col-start-3 @2xl/edition:row-start-1"

#: The bin sits top-right on a narrow card and last in the wide row.
_BIN_CELL_CLASS: Final[str] = (
    "col-start-2 row-start-1 flex min-h-control items-center justify-end "
    "@2xl/edition:col-start-4"
)


def _count_input(field: str, count: int) -> Node:
    """How many rows the page holds, the way a formset states it."""
    return Input(type="hidden", name=field, value=str(count))


def _remove_button(title: str) -> Node:
    """Inert until `<catalog-editor>` picks it up."""
    return ControlButton(
        color="red",
        variant="ghost",
        type="button",
        title=title,
        aria_label=title,
        data_catalog_remove="",
    )[Icon("delete", size=ICON_BUTTON_SIZE_CLASS)]


def _hidden_fields(form: BaseForm) -> list[Node]:
    return [Safe(str(field)) for field in form if field.is_hidden]


def _non_field_errors(form: BaseForm) -> list[Node]:
    errors = FieldErrors(form.non_field_errors())
    return [] if errors is None else [errors]


def _labelled(
    field: BoundField, class_: str, label_class: str = NARROW_LABEL_CLASS
) -> Node:
    """One control, the label that names it, and its own refusals.

    A composite control names itself through the label's id, which is
    why the label carries both: see `field_label_id`.
    """
    children: list[Node] = [
        Label(
            class_=label_class,
            for_=field.id_for_label,
            id_=field_label_id(field.id_for_label) or None,
        )[str(field.label)],
        Safe(str(field)),
    ]
    errors = FieldErrors(field.errors)
    if errors is not None:
        children.append(errors)
    return Div(class_=class_)[*children]


def _field_cell(field: BoundField, placement: str) -> Node:
    return _labelled(
        field, f"flex flex-col col-span-2 @2xl/edition:col-span-1 {placement}"
    )


def _platform_name(row: ReleaseRowForm) -> str:
    """What the card's mark calls this row, for whoever cannot see it."""
    release = row.instance
    if release is None or release.platform is None:
        return "unspecified platform"
    return release.platform.name


def _release_card(row: ReleaseRowForm, *, value: str, chosen: bool) -> Node:
    platform = _platform_name(row)
    return ChoiceCard(
        name=MARK_FIELD,
        value=value,
        label=f"Show the {platform} release in the library",
        checked=chosen,
        columns=EDITION_COLUMNS,
    )[
        [
            *_hidden_fields(row),
            Div(class_=_BIN_CELL_CLASS)[
                _remove_button(f"Remove the {platform} release")
            ],
            _field_cell(row["platform"], _PLATFORM_PLACEMENT),
            _field_cell(row["release_date"], _DATE_PLACEMENT),
            *_non_field_errors(row),
        ]
    ]


def _headings() -> Node:
    return Div(aria_hidden="true", class_=_HEADINGS_CLASS)[
        Span(class_=FORM_LABEL_CLASS)["In library"],
        Span(class_=FORM_LABEL_CLASS)["Platform"],
        Span(class_=FORM_LABEL_CLASS)["Released"],
        #: The bin column: a heading over it would name nothing.
        Span(),
    ]


def _name_row(block: EditionBlock) -> Node:
    """The Edition's own name, which no header row stands over."""
    name = block.form["name"]
    title = f"Remove the {name.value() or 'unnamed'} edition"
    return Div(class_="flex items-end gap-3")[
        _labelled(name, "grow flex flex-col", FORM_LABEL_CLASS),
        Div(class_="flex min-h-control items-center")[_remove_button(title)],
    ]


def _edition_block(block: EditionBlock, index: int, mark: str) -> Node:
    rows = [
        _release_card(
            row,
            value=release_prefix(index, row_index),
            chosen=release_prefix(index, row_index) == mark,
        )
        for row_index, row in enumerate(block.rows)
    ]
    add_release = ControlButton(
        variant="ghost", type="button", data_catalog_add_release=""
    )["Add release"]
    return ChoiceCardGroup(
        name=MARK_FIELD,
        legend=block.form["name"].value() or "Unnamed edition",
        class_=_BLOCK_CLASS,
    )[
        [
            *_hidden_fields(block.form),
            _count_input(release_count_field(index), len(block.rows)),
            _name_row(block),
            *_non_field_errors(block.form),
            _headings(),
            *rows,
            Div()[add_release],
        ]
    ]


def editions_area(graph: CatalogGraphForm) -> Node:
    """Every Edition of one Game, and every Release under each."""
    errors = [
        Div(class_="text-type-body text-danger")[sentence]
        for sentence in graph.form_errors
    ]
    add_edition = ControlButton(
        variant="ghost", type="button", data_catalog_add_edition=""
    )["Add edition"]
    return Div(class_="flex flex-col gap-4")[
        Span(class_="text-type-subheading text-heading")["Editions"],
        *errors,
        _count_input(EDITION_COUNT_FIELD, len(graph.blocks)),
        *(
            _edition_block(block, index, graph.mark)
            for index, block in enumerate(graph.blocks)
        ),
        Div()[add_edition],
    ]
