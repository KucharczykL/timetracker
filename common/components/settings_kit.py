"""Reusable settings-page components (issue #384).

This module owns layout and settings-specific composition only. Native controls
still come from Django forms through ``PrimitiveWidgetsMixin`` and
``FormFields``; the kit adds grouping metadata, origin/lock context, secret
masking, and the live-save host around that existing path.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from common.components.core import (
    Element,
    Fragment,
    Node,
    randomid,
)
from common.components.primitives import (
    FORM_MAX_WIDTH_CLASS,
    Badge,
    Div,
    FormFieldGroup,
    FormFieldPresentation,
    FormFields,
    Icon,
    Input,
    Label,
    P,
    Popover,
    Span,
    TooltipDefinition,
    TooltipDefinitionList,
    custom_element_builder,
)

_LiveSettingFields = custom_element_builder("live-setting-fields")
_SettingSourceBadge = custom_element_builder("setting-source-badge")

type SettingsFieldColumns = Literal[1, 2, 3]
_SETTINGS_FIELD_LAYOUT_CLASSES: dict[SettingsFieldColumns, str] = {
    1: f"flex w-full {FORM_MAX_WIDTH_CLASS} flex-col gap-6",
    2: "grid w-full grid-cols-1 gap-6 @md:grid-cols-2",
    3: "grid w-full grid-cols-1 gap-6 @md:grid-cols-2 @4xl:grid-cols-3",
}
_SOURCE_LABELS = {
    "user": "Personal",
    "database": "Database",
    "env": "Environment",
    "env_file": "Environment file",
    "dotenv": ".env",
    "ini": "settings.ini",
    "default": "Default",
}
_SOURCE_DESCRIPTIONS = {
    "user": "Saved for your account and overrides the site default.",
    "database": "Saved in the application database as the current site-wide value.",
    "env": "Loaded from an environment variable.",
    "env_file": "Loaded from a file referenced by an environment variable.",
    "dotenv": "Loaded from the application's .env file.",
    "ini": "Loaded from the application's settings.ini file.",
    "default": "The built-in default, used because no higher-priority value is set.",
}
_NON_DEFAULT_SOURCE_STATUS = "Non-default source (default source: “Default”)"


@dataclass(frozen=True, slots=True)
class SettingFieldState:
    """Settings metadata applied to one Django form field.

    ``key`` is the registry/event identity stamped on the control and source
    badge. ``live_save`` grants generic PATCH ownership to
    ``LiveSettingFieldsElement``; a custom owner retains the key and sets
    ``live_save=False``.
    A locked state sets Django's real ``Field.disabled`` flag before rendering,
    so native semantics and the shared disabled utility classes do the work.

    ``show_source`` renders the origin badge. Set it only where the control
    cannot express origin itself: a locked field (the badge carries the reason
    it is disabled) or a site default, whose control shows the resolved value
    identically whether it is stored or inherited. A personal control that
    already reads "Use site default (25)" says it better, so the page turns this
    off rather than repeating it (#381).
    """

    key: str
    source: str
    locked: bool = False
    reason: str = ""
    help_text: str = ""
    live_save: bool = True
    show_source: bool = True


def SettingsFieldLayout(columns: SettingsFieldColumns = 1) -> Element:
    """A supported settings-field flow; one column is always width-capped."""
    if columns not in _SETTINGS_FIELD_LAYOUT_CLASSES:
        raise ValueError("SettingsFieldLayout columns must be 1, 2, or 3.")
    return Div(
        class_=_SETTINGS_FIELD_LAYOUT_CLASSES[columns],
        data_settings_field_layout=str(columns),
    )


# Placement rule (#381): a source badge appears only where the control cannot state
# its own origin. That is every site default — those controls seed from the resolved
# value, so a stored 25 and an inherited 25 render identically, and only the badge
# says which — plus locked and read-only rows, where it carries the reason the field
# is disabled. Personal controls name the value they inherit ("Use site default
# (25)"), so that page suppresses the badge via SettingFieldState.show_source rather
# than repeat it. A badge is never the field's identity: it sits beside a real
# <label>, never instead of one.
def SettingSourceBadge(
    source: str,
    *,
    locked: bool = False,
    reason: str = "",
    id: str = "",
    setting_key: str = "",
    namespace: str,
) -> Node:
    """One setting-origin badge with an accessible explanatory tooltip."""
    source_value = str(source)
    label = _SOURCE_LABELS.get(source_value, source_value.replace("_", " ").title())
    attributes: list[tuple[str, str]] = [("data-setting-origin", source_value)]
    content: Node | str = Span(data_setting_source_label="")[label]
    if locked:
        attributes.extend(
            [
                ("data-setting-locked", ""),
            ]
        )
        content = Fragment(
            Icon(
                "lock",
                [("aria-hidden", "true"), ("class", "shrink-0")],
                size="size-3",
            ),
            Span(data_setting_source_label="")[label],
        )
    badge = Badge(
        content,
        size="sm",
        tone=(
            "warning"
            if locked
            else ("neutral" if source_value == "default" else "brand")
        ),
        extra_class="gap-1",
        attributes=attributes,
    )
    source_description = _SOURCE_DESCRIPTIONS.get(
        source_value,
        f"Provided by {label}.",
    )
    tooltip_definitions = [
        TooltipDefinition(
            "Source",
            source_description,
            [("data-setting-source-description", "")],
        )
    ]
    if not locked:
        status_attributes: list[tuple[str, str]] = [("data-setting-source-status", "")]
        if source_value == "default":
            status_attributes.append(("hidden", ""))
        tooltip_definitions.append(
            TooltipDefinition(
                "Status",
                _NON_DEFAULT_SOURCE_STATUS,
                status_attributes,
            )
        )
    if locked:
        lock_reason = reason or (
            f"{label} values take priority over settings saved in the application, "
            "so this field cannot be edited here."
        )
        tooltip_definitions.append(TooltipDefinition("Locked", lock_reason))
    popover = Popover(
        popover_content=TooltipDefinitionList(
            tooltip_definitions,
            class_="max-w-sm",
        ),
        children=[badge],
        id=id,
        trigger_label=f"{label} source" + (", locked" if locked else ""),
        wrapped_classes=(
            "cursor-help rounded leading-none focus:outline-hidden "
            "focus:ring-2 focus:ring-fg-brand"
        ),
    )
    return _SettingSourceBadge(key=setting_key, namespace=namespace)[popover]


def _lock_reason(state: SettingFieldState) -> str:
    if state.reason:
        return state.reason
    source_label = _SOURCE_LABELS.get(
        str(state.source),
        str(state.source).replace("_", " ").title(),
    )
    return f"Managed by {source_label}; it cannot be changed here."


def _field_metadata(metadata_id: str, state: SettingFieldState) -> Node | None:
    reason = _lock_reason(state) if state.locked else state.reason
    details = [text for text in (state.help_text, reason) if text]
    if not details:
        return None
    return Div(
        id=metadata_id,
        class_="mt-2 flex flex-col gap-1",
        data_setting_metadata="",
    )[*[P(class_="text-type-micro text-body")[text] for text in details]]


def prepare_setting_fields(
    form,
    states: Mapping[str, SettingFieldState],
    presentations: Mapping[str, FormFieldPresentation] | None = None,
    *,
    namespace: str,
) -> dict[str, FormFieldPresentation]:
    """Stamp semantics and return one presentation per setting field.

    This is intentionally preparation for the existing renderer, not a second
    field renderer. The mapping key is a Django form field name; ``state.key``
    is the registry/event identity, while ``state.live_save`` controls whether
    ``data-live-setting-control`` grants PATCH ownership to
    ``LiveSettingFieldsElement``.
    """
    supplied = dict(presentations or {})
    unknown = set(supplied) - set(form.fields)
    if unknown:
        raise ValueError(f"Unknown setting presentations: {sorted(unknown)!r}.")
    prepared: dict[str, FormFieldPresentation] = {}
    for field_name, state in states.items():
        if field_name not in form.fields:
            raise ValueError(f"Unknown setting form field {field_name!r}.")
        field = form.fields[field_name]
        bound_field = form[field_name]
        # Django prefixes the bound control ID when multiple forms share a page.
        # Derive every related ID from that real control identity rather than
        # from the unprefixed field name, or separate forms containing e.g.
        # `enabled` would emit duplicate tooltip/metadata IDs.
        control_id = (
            bound_field.id_for_label
            or bound_field.auto_id
            or f"id_{form.add_prefix(field_name)}"
        )
        tooltip_id = f"{control_id}_setting_source_tooltip"
        metadata_id = f"{control_id}_setting_metadata"
        field.widget.attrs["data-setting-key"] = state.key
        if state.live_save:
            field.widget.attrs["data-live-setting-control"] = ""
        else:
            field.widget.attrs.pop("data-live-setting-control", None)
        label_extra = (
            SettingSourceBadge(
                state.source,
                locked=state.locked,
                reason=_lock_reason(state) if state.locked else "",
                id=tooltip_id,
                setting_key=state.key,
                namespace=namespace,
            )
            if state.show_source
            else None
        )
        metadata = _field_metadata(metadata_id, state)
        if metadata is not None:
            describedby = str(field.widget.attrs.get("aria-describedby", "")).strip()
            field.widget.attrs["aria-describedby"] = " ".join(
                part for part in (describedby, metadata_id) if part
            )
        if state.locked:
            field.disabled = True
        presentation = supplied.get(field_name, FormFieldPresentation())
        prepared[field_name] = FormFieldPresentation(
            label_extra=(
                Fragment(presentation.label_extra, label_extra)
                if presentation.label_extra is not None and label_extra is not None
                else presentation.label_extra or label_extra
            ),
            after_control=(
                Fragment(presentation.after_control, metadata)
                if presentation.after_control is not None and metadata is not None
                else presentation.after_control or metadata
            ),
            decorate_control=presentation.decorate_control,
        )
    prepared.update(
        {key: value for key, value in supplied.items() if key not in states}
    )
    return prepared


def LiveSettingFields(
    form,
    *,
    states: Mapping[str, SettingFieldState],
    patch_url_template: str,
    csrf: str,
    namespace: str,
    groups: Sequence[FormFieldGroup] | None = None,
    presentations: Mapping[str, FormFieldPresentation] | None = None,
) -> Node:
    """Render existing ``FormFields`` inside the optimistic live-save host."""
    if "__key__" not in patch_url_template:
        raise ValueError("patch_url_template must contain the literal __key__ token.")
    prepared = prepare_setting_fields(form, states, presentations, namespace=namespace)
    return _LiveSettingFields(
        patch_url_template=patch_url_template,
        csrf=csrf,
        namespace=namespace,
        class_="block w-full @container",
    )[
        SettingsFieldLayout(1)[
            FormFields(
                form,
                presentations=prepared,
                groups=groups,
            )
        ]
    ]


def ReadonlySettingField(
    *,
    name: str,
    value: str,
    source: str,
    namespace: str,
    setting_key: str,
    locked: bool = False,
    reason: str = "",
    help_text: str = "",
    note: str = "",
    secret_present: bool | None = None,
) -> Node:
    """Read-only settings row that mirrors the ``FormFields`` row shell.

    Renders through the same label-line / control / metadata skeleton as
    ``_form_field_row`` (label_extra present path) so infra rows sit in the
    same visual family as editable site-default rows — same type scale, same
    label-line layout — without routing through a Django form or emitting any
    ``<input>`` element.

    ``secret_present`` controls the value slot: ``None`` renders ``value``
    verbatim; ``True`` emits the fixed mask ``••••••••``; ``False`` leaves the
    slot blank. When set, ``value`` is ignored — the real secret is never a
    parameter and can never reach the DOM.
    """
    # A per-setting id: without it the badge's Popover derives its DOM id from
    # its content, so two rows with the same source/locked/reason (e.g. several
    # env-locked settings) would collide and fail assert_unique_element_ids.
    badge = SettingSourceBadge(
        source,
        locked=locked,
        reason=reason,
        id=f"readonly-{namespace}-{setting_key}-setting-source-tooltip",
        setting_key=setting_key,
        namespace=namespace,
    )
    # Identifier line: mirrors _form_field_label with label_extra present.
    # Name rendered in monospace; badge in the label_extra slot.
    label_line = Div(
        class_="flex min-w-0 flex-wrap items-center gap-2",
        data_form_field_label_line="",
    )[
        Span(class_="text-type-label text-heading font-mono")[name],
        badge,
    ]
    # Value slot: plain monospace static text (no input, no disabled widget).
    if secret_present is None:
        displayed_value = value
    elif secret_present:
        displayed_value = "••••••••"
    else:
        displayed_value = ""
    value_node = Span(class_="font-mono text-type-body text-heading")[displayed_value]
    # Metadata: help_text then note, as muted micro-text.
    metadata_texts = [text for text in (help_text, note) if text]
    metadata: Node | None = None
    if metadata_texts:
        metadata = Div(
            class_="mt-2 flex flex-col gap-1",
            data_setting_metadata="",
        )[*[P(class_="text-type-micro text-body")[text] for text in metadata_texts]]

    # Row shell: mirrors the label_extra-present, non-checkbox branch of
    # _form_field_row — Div(class_="mb-2.5")[label_line] then control then
    # optional after_control — using the exact same class strings.
    row_children: list[Node] = [
        Div(class_="mb-2.5")[label_line],
        value_node,
    ]
    if metadata is not None:
        row_children.append(metadata)
    return Div()[*row_children]


def MaskedSecretField(
    *,
    label: str,
    present: bool,
    id: str = "",
    help_text: str = "The stored value is hidden.",
) -> Node:
    """Read-only secret display that cannot leak the secret into page source.

    The API deliberately accepts only ``present``; callers cannot accidentally
    pass a real secret. A fixed mask is rendered when a value exists.
    """
    # Local import avoids a component-package import cycle: games.forms imports
    # common.components while defining PrimitiveWidgetsMixin. The canonical
    # input class remains single-sourced there for every Django native control.
    from games.forms import INPUT_CLASS

    field_id = id or randomid(seed="masked-", content=label, length=18)
    return Div(class_="flex flex-col gap-2", data_masked_secret="")[
        Label(for_=field_id, class_="text-type-label text-heading")[label],
        Input(
            id_=field_id,
            type="password",
            value="••••••••" if present else "",
            placeholder="Not set" if not present else "",
            readonly=True,
            aria_readonly="true",
            autocomplete="off",
            class_=INPUT_CLASS,
        ),
        P(class_="text-type-micro text-body")[help_text],
    ]


__all__ = [
    "LiveSettingFields",
    "MaskedSecretField",
    "ReadonlySettingField",
    "SettingFieldState",
    "SettingSourceBadge",
    "SettingsFieldColumns",
    "SettingsFieldLayout",
    "prepare_setting_fields",
]
