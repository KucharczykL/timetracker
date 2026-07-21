"""Reusable settings-page components (issue #384).

This module owns layout and settings-specific composition only. Native controls
still come from Django forms through ``PrimitiveWidgetsMixin`` and
``FormFields``; the kit adds grouping metadata, origin/lock context, responsive
navigation, secret masking, and the live-save host around that existing path.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from common.components.core import Child, Element, Fragment, Node, randomid
from common.components.custom_elements import Dropdown, DropdownMenuPanel
from common.components.primitives import (
    A,
    Badge,
    ContentContainer,
    ControlButton,
    Div,
    FORM_MAX_WIDTH_CLASS,
    FormFieldGroup,
    FormFields,
    Icon,
    Input,
    Label,
    Li,
    P,
    Popover,
    Span,
    TooltipDefinition,
    TooltipDefinitionList,
    Ul,
    custom_element_builder,
)

_SettingsSectionNav = custom_element_builder("settings-section-nav")
_LiveSettingFields = custom_element_builder("live-setting-fields")

_SECTION_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
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

_NAV_LINK_CLASS = (
    "inline-flex min-h-control items-center whitespace-nowrap rounded px-3 "
    "text-type-body font-medium bg-brand-soft text-heading no-underline "
    "hover:bg-neutral-tertiary-medium focus:outline-hidden focus:ring-4 focus:ring-inset "
    "focus:ring-brand-medium @4xl:w-full @4xl:justify-start @4xl:rounded-base "
    "@4xl:bg-transparent"
)


@dataclass(frozen=True, slots=True)
class SettingsSection:
    """One labeled, anchorable section in :func:`SettingsScaffold`."""

    id: str
    label: str
    content: Child
    description: str = ""


@dataclass(frozen=True, slots=True)
class SettingFieldState:
    """Settings metadata applied to one Django form field.

    ``key`` is the registry/API key (kept separate from the form field name).
    A locked state sets Django's real ``Field.disabled`` flag before rendering,
    so native semantics and the shared disabled utility classes do the work.
    """

    key: str
    source: str
    locked: bool = False
    reason: str = ""
    help_text: str = ""


def SettingsFieldLayout(columns: SettingsFieldColumns = 1) -> Element:
    """A supported settings-field flow; one column is always width-capped."""
    if columns not in _SETTINGS_FIELD_LAYOUT_CLASSES:
        raise ValueError("SettingsFieldLayout columns must be 1, 2, or 3.")
    return Div(
        class_=_SETTINGS_FIELD_LAYOUT_CLASSES[columns],
        data_settings_field_layout=str(columns),
    )


def _validate_sections(sections: Sequence[SettingsSection]) -> None:
    if not sections:
        raise ValueError("SettingsScaffold requires at least one section.")
    seen: set[str] = set()
    for section in sections:
        if not _SECTION_ID.fullmatch(section.id):
            raise ValueError(
                f"Invalid settings section id {section.id!r}; use an HTML-safe id."
            )
        if section.id in seen:
            raise ValueError(f"Duplicate settings section id {section.id!r}.")
        seen.add(section.id)


def _section_link(section: SettingsSection) -> Node:
    return Li(
        data_section_nav_item="",
        class_="shrink-0 @4xl:w-full",
    )[A(href=f"#{section.id}", class_=_NAV_LINK_CLASS)[section.label]]


def SettingsSectionNav(sections: Sequence[SettingsSection]) -> Node:
    """Same-DOM mobile anchor chips and desktop sticky section rail.

    At narrow container widths the custom element applies a priority-plus
    layout and moves rightmost ``li`` nodes into the shared dropdown panel. At
    ``@4xl`` the sentinel becomes visible, the element restores every node to
    the primary list, and the same nav becomes a vertical sticky rail.
    """
    _validate_sections(sections)
    overflow_id = randomid(
        seed="settings-nav-",
        content=":".join(section.id for section in sections),
        length=20,
    )
    overflow_trigger = ControlButton(
        variant="ghost",
        aria_haspopup="menu",
        aria_label="More settings sections",
    )["More"].as_element()
    overflow = Div(
        data_section_nav_overflow="",
        class_="hidden shrink-0 @4xl:hidden",
    )[
        Dropdown(
            trigger_element=overflow_trigger,
            target_element=DropdownMenuPanel(
                items=[], aria_label="More settings sections"
            ),
            id=overflow_id,
            placement="bottom-end",
        )
    ]
    return _SettingsSectionNav(
        class_="block min-w-0 @4xl:sticky @4xl:top-4 @4xl:self-start"
    )[
        Element(
            "nav",
            [
                ("aria-label", "Settings sections"),
                (
                    "class",
                    "mb-4 @4xl:mb-0 @4xl:max-h-[calc(100vh-2rem)] @4xl:overflow-y-auto",
                ),
            ],
        )[
            Div(
                data_section_nav_row="",
                class_="flex min-w-0 items-center gap-2 @4xl:block",
            )[
                Ul(
                    data_section_nav_primary="",
                    class_=(
                        "flex min-w-0 flex-1 gap-2 overflow-hidden "
                        "@4xl:flex-col @4xl:overflow-visible"
                    ),
                )[*[_section_link(section) for section in sections]],
                overflow,
            ],
            # CSS/container-query truth exposed to the layout behavior without
            # duplicating the @4xl threshold in matchMedia JavaScript.
            Span(
                data_section_nav_wide="",
                class_="hidden @4xl:block",
                aria_hidden="true",
            ),
        ]
    ]


def _section_panel(section: SettingsSection) -> Node:
    heading_id = f"{section.id}-heading"
    header_children: list[Node] = [
        Element(
            "h2",
            [("id", heading_id), ("class", "text-type-subheading text-heading")],
        )[section.label]
    ]
    if section.description:
        header_children.append(
            P(class_="text-type-body text-body")[section.description]
        )
    return Element(
        "section",
        [
            ("id", section.id),
            ("aria-labelledby", heading_id),
            ("data-settings-section", ""),
            (
                "class",
                "scroll-mt-4 flex flex-col gap-6 rounded-base border "
                "border-default bg-neutral-primary-medium p-4 @container",
            ),
        ],
    )[
        Div(
            data_settings_section_header="",
            class_="flex flex-col gap-2",
        )[*header_children],
        Div(
            data_settings_section_content="",
            class_="flex flex-col gap-4",
        )[section.content],
    ]


def SettingsScaffold(sections: Sequence[SettingsSection]) -> Node:
    """Responsive settings section-nav + content scaffold.

    The split is container-query driven: a narrow embedding stacks nav/content;
    a wide embedding promotes the nav to a rail without changing or cloning DOM.
    """
    _validate_sections(sections)
    return ContentContainer(class_="@container")[
        Div(
            data_settings_scaffold="",
            class_=(
                "grid grid-cols-1 gap-6 "
                "@4xl:grid-cols-[14rem_minmax(0,1fr)] @4xl:items-start @4xl:gap-8"
            ),
        )[
            SettingsSectionNav(sections),
            Div(class_="flex min-w-0 flex-col gap-6")[
                *[_section_panel(section) for section in sections]
            ],
        ]
    ]


# EPIC-FINAL DELETION GATE (#381)
# Inline source badges on ordinary unlocked/editable fields are provisional. Before
# closing the settings-panel epic, identify at least one concrete shipped field where
# visible origin materially helps the user. A source badge must never replace a
# visible field label. If no such unlocked use case exists, remove the unlocked badge
# integration from prepare_setting_fields together with its preview, tests, and docs;
# retain provenance only for concrete locked/read-only settings that require it.
def SettingSourceBadge(
    source: str,
    *,
    locked: bool = False,
    reason: str = "",
    id: str = "",
) -> Node:
    """One setting-origin badge with an accessible explanatory tooltip."""
    source_value = str(source)
    label = _SOURCE_LABELS.get(source_value, source_value.replace("_", " ").title())
    attributes: list[tuple[str, str]] = [("data-setting-origin", source_value)]
    content: Node | str = label
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
            label,
        )
    badge = Badge(
        content,
        size="sm",
        tone="warning" if locked else "neutral",
        extra_class="gap-1",
        attributes=attributes,
    )
    source_description = _SOURCE_DESCRIPTIONS.get(
        source_value,
        f"Provided by {label}.",
    )
    tooltip_definitions = [TooltipDefinition("Source", source_description)]
    if locked:
        lock_reason = reason or (
            f"{label} values take priority over settings saved in the application, "
            "so this field cannot be edited here."
        )
        tooltip_definitions.append(TooltipDefinition("Locked", lock_reason))
    return Popover(
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


def _lock_reason(state: SettingFieldState) -> str:
    if state.reason:
        return state.reason
    source_label = _SOURCE_LABELS.get(
        str(state.source),
        str(state.source).replace("_", " ").title(),
    )
    return f"Managed by {source_label}; it cannot be changed here."


def _field_metadata(field_name: str, state: SettingFieldState) -> Node | None:
    reason = _lock_reason(state) if state.locked else state.reason
    details = [text for text in (state.help_text, reason) if text]
    if not details:
        return None
    return Div(
        id=f"id_{field_name}_setting_metadata",
        class_="mt-2 flex flex-col gap-1",
        data_setting_metadata="",
    )[*[P(class_="text-type-micro text-body")[text] for text in details]]


def prepare_setting_fields(
    form,
    states: Mapping[str, SettingFieldState],
) -> tuple[dict[str, Node], dict[str, Node]]:
    """Stamp semantics and return control-below + label-line metadata.

    This is intentionally preparation for the existing renderer, not a second
    field renderer. The mapping key is a Django form field name; ``state.key``
    is the registry key sent to the API.
    """
    extras: dict[str, Node] = {}
    label_extras: dict[str, Node] = {}
    for field_name, state in states.items():
        if field_name not in form.fields:
            raise ValueError(f"Unknown setting form field {field_name!r}.")
        field = form.fields[field_name]
        field.widget.attrs["data-setting-key"] = state.key
        # Provisional for unlocked fields; see the epic-final deletion gate above
        # SettingSourceBadge before extending this pattern to more settings.
        label_extras[field_name] = SettingSourceBadge(
            state.source,
            locked=state.locked,
            reason=_lock_reason(state) if state.locked else "",
            id=f"id_{field_name}_setting_source_tooltip",
        )
        metadata = _field_metadata(field_name, state)
        if metadata is not None:
            metadata_id = f"id_{field_name}_setting_metadata"
            describedby = str(field.widget.attrs.get("aria-describedby", "")).strip()
            field.widget.attrs["aria-describedby"] = " ".join(
                part for part in (describedby, metadata_id) if part
            )
            extras[field_name] = metadata
        if state.locked:
            field.disabled = True
    return extras, label_extras


def LiveSettingFields(
    form,
    *,
    states: Mapping[str, SettingFieldState],
    patch_url_template: str,
    csrf: str,
    groups: Sequence[FormFieldGroup] | None = None,
    event: str = "setting-saved",
) -> Node:
    """Render existing ``FormFields`` inside the optimistic live-save host."""
    if "__key__" not in patch_url_template:
        raise ValueError("patch_url_template must contain the literal __key__ token.")
    extras, label_extras = prepare_setting_fields(form, states)
    return _LiveSettingFields(
        patch_url_template=patch_url_template,
        csrf=csrf,
        event=event,
        class_="block w-full @container",
    )[
        SettingsFieldLayout(1)[
            FormFields(
                form,
                extras=extras,
                label_extras=label_extras,
                groups=groups,
            )
        ]
    ]


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
    "SettingFieldState",
    "SettingSourceBadge",
    "SettingsFieldColumns",
    "SettingsFieldLayout",
    "SettingsScaffold",
    "SettingsSection",
    "SettingsSectionNav",
    "prepare_setting_fields",
]
