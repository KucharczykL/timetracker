"""The Game form's nested Edition and Release rows.

A row is named by Django's own form prefix. `BoundField.html_name` is
``f"{prefix}-{name}"``, and Django hands the widget that prefixed name, so
`TemporalWidget` builds ``edition-0-release-1-release_date-year`` without a
line changing in `timetracker/temporal.py`.
"""

from typing import Final, cast

from django import forms

from common.date_time_presentation import DateTimePresentation
from games.forms import PrimitiveWidgetsMixin, TemporalFormField
from games.models import Edition, Platform, Release, UserLibrary

#: One radio group over the whole Game; its value is a release prefix.
MARK_FIELD: Final[str] = "in_library"
#: How many Edition blocks were posted, the way a formset states it.
EDITION_COUNT_FIELD: Final[str] = "editions-count"

#: The service allows it for #782's importer; a person typing does not,
#: because two unnamed siblings both read as the Game's name.
UNNAMED_SIBLING_EDITION = (
    "Name this edition. Another edition already presents as the game's own name."
)


def edition_prefix(index: int) -> str:
    """``edition_prefix(0)`` is ``"edition-0"``."""
    return f"edition-{index}"


def release_prefix(edition: int, release: int) -> str:
    """``release_prefix(0, 1)`` is ``"edition-0-release-1"``."""
    return f"{edition_prefix(edition)}-release-{release}"


def release_count_field(edition_index: int) -> str:
    """``release_count_field(0)`` is ``"edition-0-releases-count"``."""
    return f"{edition_prefix(edition_index)}-releases-count"


class EditionRowForm(PrimitiveWidgetsMixin, forms.Form):
    """One Edition block's own fields."""

    edition_id = forms.UUIDField(required=False, widget=forms.HiddenInput)
    name = forms.CharField(max_length=255, required=False, label="Edition name")
    removed = forms.BooleanField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        #: `CatalogGraphForm` sets this from the stored graph, never
        #: from the posted id: a row naming a row storage did not
        #: return is a new row, not a write to somebody else's.
        self.instance: Edition | None = None

    def clean_name(self) -> str:
        return cast(str, self.cleaned_data["name"]).strip()


class ReleaseRowForm(PrimitiveWidgetsMixin, forms.Form):
    """One Release row inside an Edition block."""

    release_id = forms.UUIDField(required=False, widget=forms.HiddenInput)
    removed = forms.BooleanField(required=False, widget=forms.HiddenInput)

    #: A plain select, not `SearchSelectWidget`. A composite widget carries
    #: its id on a wrapper div, and a cloned row would have to rewrite that
    #: id and re-run the element's wiring.
    platform = forms.ModelChoiceField(
        queryset=Platform.objects.none(),
        required=False,
        empty_label="Unspecified",
    )

    def __init__(
        self,
        *args: object,
        library: UserLibrary,
        presentation: DateTimePresentation,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.library = library
        self.instance: Release | None = None
        cast(
            forms.ModelChoiceField, self.fields["platform"]
        ).queryset = Platform.objects.visible_to(library).order_by("name")
        self.fields["release_date"] = TemporalFormField(
            presentation=presentation, label="Released"
        )
        #: `release_date` joins the form last, thus it sorts last too.
        self.order_fields(("release_id", "platform", "release_date", "removed"))
