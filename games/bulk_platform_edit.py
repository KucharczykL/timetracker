"""Edit many platforms: their group, their icon, or both."""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypedDict, cast

from django import forms
from django.contrib.auth.models import User
from django.http import QueryDict

from common.components import Icon
from common.components.platform_icons import PLATFORM_ICONS
from common.components.primitives import FormFields
from games.bulk_actions import (
    ActTitle,
    AsksNothing,
    BulkAction,
    BulkChoice,
    ChoiceValue,
    Control,
    FieldName,
    LedgerRows,
    Offered,
    PreviewColumn,
    RowOutcome,
)
from games.bulk_edit import (
    form_refusal,
    keeping,
    settled,
    stated_object,
    statement_unreadable,
)
from games.bulk_platforms import outcome, platform_resolution, platform_scope, undoing
from games.events.idempotency import IdempotencyKey
from games.forms import (
    KEEP,
    DatalistTextInput,
    IconPickerWidget,
    PrimitiveWidgetsMixin,
    UnsetFieldsForm,
    UnsetWidget,
)
from games.models import Platform, UserLibrary
from games.writes.answers import answered
from games.writes.platform import edit_platform_in_batch


class PlatformEditJson(TypedDict, total=False):
    """A statement on the wire; absent is unstated."""

    group: str
    icon: str


#: What a statement's JSON may name.
_KEYS = frozenset(PlatformEditJson.__annotations__)

NOTHING_STATED = "Choose a group, no group, or an icon."
NO_GROUP = "No group"
GROUP_LENGTH = Platform._meta.get_field("group").max_length or 255


@dataclass(frozen=True, slots=True)
class PlatformEditStatement:
    """What one batch states; None leaves alone.

    An empty group states no group.
    """

    group: str | None
    icon: str | None

    def __post_init__(self) -> None:
        if self.group is not None:
            #: One rule for form and carried statement.
            object.__setattr__(self, "group", self.group.strip())
            if len(self.group) > GROUP_LENGTH:
                raise ValueError(f"A group is {GROUP_LENGTH} characters at most.")
        if self.group is None and self.icon is None:
            raise ValueError("An edit states a group or an icon.")
        if self.icon is not None and self.icon not in PLATFORM_ICONS:
            raise ValueError(f"{self.icon!r} is no platform icon.")

    def encode(self) -> ChoiceValue:
        stated: PlatformEditJson = {}
        if self.group is not None:
            stated["group"] = self.group
        if self.icon is not None:
            stated["icon"] = self.icon
        return json.dumps(stated, sort_keys=True)

    @classmethod
    def decode(cls, raw: ChoiceValue) -> PlatformEditStatement:
        """An earlier settle's answer, or a refusal."""
        stated = stated_object(raw, _KEYS)
        for key, value in stated.items():
            if not isinstance(value, str):
                raise statement_unreadable(f"{raw!r} states a {key} that is no text")
        try:
            return cls(stated.get("group"), stated.get("icon"))
        except ValueError as refused:
            raise statement_unreadable(f"{raw!r}: {refused}") from refused


def _groups(library: UserLibrary) -> list[str]:
    """Every group a live platform the library sees holds."""
    return sorted(
        set(
            Platform.objects.visible_to(library)
            .exclude(group="")
            .values_list("group", flat=True)
        ),
        key=str.casefold,
    )


def _group_shown(group: str) -> str:
    return group or NO_GROUP


def _icon_shown(icon: str) -> str:
    return PLATFORM_ICONS.get(icon, icon)


class BulkPlatformEditForm(PrimitiveWidgetsMixin, UnsetFieldsForm):
    """An empty field keeps; ⊘ states no group."""

    group = forms.CharField(
        label="Group",
        required=False,
        max_length=GROUP_LENGTH,
        widget=UnsetWidget(DatalistTextInput(), none_label=NO_GROUP),
    )
    icon = forms.ChoiceField(
        label="Icon",
        required=False,
        choices=[("", "Keep"), *PLATFORM_ICONS.items()],
        widget=IconPickerWidget(label="Icon"),
    )

    def __init__(
        self,
        data: QueryDict | None = None,
        *,
        library: UserLibrary,
        prefix: FieldName,
        rows: Sequence[Platform] = (),
    ) -> None:
        super().__init__(data, prefix=prefix)
        group = cast(UnsetWidget, self.fields["group"].widget).widget
        cast(DatalistTextInput, group).suggestions = tuple(_groups(library))
        if rows:
            group.attrs["placeholder"] = keeping(
                rows, lambda row: row.group, _group_shown
            )
            cast(IconPickerWidget, self.fields["icon"].widget).keep_label = keeping(
                rows, lambda row: row.icon, _icon_shown
            )

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if cleaned.get("group") is KEEP and not cleaned.get("icon"):
            raise forms.ValidationError(NOTHING_STATED)
        return cleaned

    def statement(self) -> PlatformEditStatement:
        """The valid form, as one statement."""
        group = self.cleaned_data["group"]
        return PlatformEditStatement(
            None if group is KEEP else group,
            self.cleaned_data["icon"] or None,
        )


def offer_edit(
    library: UserLibrary, rows: Sequence[Platform], field_name: FieldName
) -> Offered:
    """Every field is prefixed `field_name`."""
    if not rows:
        #: The confirmation states there are no rows.
        return AsksNothing()
    return Control(
        FormFields(BulkPlatformEditForm(library=library, prefix=field_name, rows=rows))
    )


def settle_edit(library: UserLibrary, post: QueryDict) -> ChoiceValue:
    """Carried statement, else the form's."""
    #: Local: the act table imports this module.
    from games.views.bulk import CHOICE_FIELD

    carried = post.get(CHOICE_FIELD, "")
    if carried:
        return PlatformEditStatement.decode(carried).encode()
    form = BulkPlatformEditForm(post, library=library, prefix=CHOICE_FIELD)
    if not form.is_valid():
        raise form_refusal(form, labelled=True)
    return form.statement().encode()


def edit_one(
    actor: User,
    platform: Platform,
    *,
    choice: ChoiceValue | None,
    idempotency_key: IdempotencyKey,
    correlation_id: uuid.UUID,
) -> RowOutcome:
    """The ledger, not the key, makes a repeat harmless."""
    with answered("platform"):
        statement = settled(
            choice,
            PlatformEditStatement.decode,
            act_name=EDIT_PLATFORMS.name,
            row_description=f"Platform {platform.pk} of library {actor.library.pk}",
        )
    return outcome(
        edit_platform_in_batch(
            platform,
            group=statement.group,
            icon=statement.icon,
            batch=correlation_id,
            act=EDIT_PLATFORMS.name,
        )
    )


#: One name for the act and its Undo.
EDIT_NAME = "platform.edit"

EDIT_PREVIEW: tuple[PreviewColumn[Platform], ...] = (
    PreviewColumn("Platform", lambda row, _: row.name),
    PreviewColumn("Group", lambda row, _: _group_shown(row.group)),
    PreviewColumn("Icon", lambda row, _: Icon(row.icon, [("title", row.icon)])),
)

EDIT_PLATFORMS = BulkAction(
    name=EDIT_NAME,
    label="Edit…",
    title=ActTitle(one="Edit this platform", many="Edit {count} platforms"),
    confirm_label="Save",
    subject="platform",
    color="blue",
    undo_rows=LedgerRows(Platform),
    fallback="games:list_platforms",
    scope=platform_scope,
    resolve=platform_resolution,
    run=edit_one,
    inverse=undoing(EDIT_NAME),
    preview=EDIT_PREVIEW,
    choice=BulkChoice(offer=offer_edit, settle=settle_edit),
)
