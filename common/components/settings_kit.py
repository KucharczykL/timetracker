"""Reusable settings-page components (issue #384).

This module owns layout and settings-specific composition only. Native controls
still come from Django forms through ``PrimitiveWidgetsMixin`` and
``FormFields``; the kit adds grouping metadata, origin/lock context, responsive
navigation, secret masking, and the live-save host around that existing path.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from common.components.core import Child, Element, Node, randomid
from common.components.custom_elements import Dropdown, DropdownMenuPanel
from common.components.primitives import (
    A,
    Badge,
    ContentContainer,
    ControlButton,
    Div,
    FormFieldGroup,
    FormFields,
    Input,
    Label,
    Li,
    P,
    Span,
    Ul,
    custom_element_builder,
)

_SettingsSectionNav = custom_element_builder("settings-section-nav")
_LiveSettingFields = custom_element_builder("live-setting-fields")

_SECTION_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_SOURCE_LABELS = {
    "user": "Personal",
    "database": "Database",
    "env": "Environment",
    "env_file": "Environment file",
    "dotenv": ".env",
    "ini": "settings.ini",
    "default": "Default",
}

_NAV_LINK_CLASS = (
    "inline-flex min-h-control items-center whitespace-nowrap rounded px-3 "
    "text-type-body font-medium bg-brand-soft text-heading no-underline "
    "hover:bg-neutral-tertiary-medium focus:outline-hidden focus:ring-4 "
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
    return _SettingsSectionNav(class_="block min-w-0")[
        Element(
            "nav",
            [
                ("aria-label", "Settings sections"),
                (
                    "class",
                    "mb-4 @4xl:sticky @4xl:top-4 @4xl:mb-0 "
                    "@4xl:max-h-[calc(100vh-2rem)] @4xl:overflow-y-auto",
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
    children: list[Node] = [
        Element(
            "h2",
            [("id", heading_id), ("class", "text-type-section text-heading")],
        )[section.label]
    ]
    if section.description:
        children.append(P(class_="text-type-body text-body")[section.description])
    children.append(Div(class_="flex flex-col gap-4")[section.content])
    return Element(
        "section",
        [
            ("id", section.id),
            ("aria-labelledby", heading_id),
            ("data-settings-section", ""),
            (
                "class",
                "scroll-mt-4 flex flex-col gap-3 rounded-base border "
                "border-default bg-neutral-primary-medium p-4 @container",
            ),
        ],
    )[*children]


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
                "@4xl:grid-cols-[12rem_minmax(0,1fr)] @4xl:items-start @4xl:gap-8"
            ),
        )[
            SettingsSectionNav(sections),
            Div(class_="flex min-w-0 flex-col gap-6")[
                *[_section_panel(section) for section in sections]
            ],
        ]
    ]


def SettingSourceBadge(source: str, *, locked: bool = False) -> Node:
    """Static setting-origin + optional lock badges, built only on ``Badge``."""
    source_value = str(source)
    label = _SOURCE_LABELS.get(source_value, source_value.replace("_", " ").title())
    badges: list[Node] = [Badge(label, size="sm", tone="neutral")]
    if locked:
        badges.append(Badge("Locked", size="sm", tone="warning"))
    return Span(
        class_="inline-flex flex-wrap items-center gap-2",
        data_setting_origin=source_value,
    )[*badges]


def _field_metadata(field_name: str, state: SettingFieldState) -> Node:
    reason = state.reason
    if state.locked and not reason:
        source_label = _SOURCE_LABELS.get(
            str(state.source), str(state.source).replace("_", " ").title()
        )
        reason = f"Managed by {source_label}; it cannot be changed here."
    details = [text for text in (state.help_text, reason) if text]
    return Div(
        id=f"id_{field_name}_setting_metadata",
        class_="flex flex-col gap-1",
        data_setting_metadata="",
    )[
        SettingSourceBadge(state.source, locked=state.locked),
        *[P(class_="text-type-micro text-body")[text] for text in details],
    ]


def prepare_setting_fields(
    form,
    states: Mapping[str, SettingFieldState],
) -> dict[str, Node]:
    """Stamp live-save/lock semantics and return ``FormFields.extras``.

    This is intentionally preparation for the existing renderer, not a second
    field renderer. The mapping key is a Django form field name; ``state.key``
    is the registry key sent to the API.
    """
    extras: dict[str, Node] = {}
    for field_name, state in states.items():
        if field_name not in form.fields:
            raise ValueError(f"Unknown setting form field {field_name!r}.")
        field = form.fields[field_name]
        field.widget.attrs["data-setting-key"] = state.key
        metadata_id = f"id_{field_name}_setting_metadata"
        describedby = str(field.widget.attrs.get("aria-describedby", "")).strip()
        field.widget.attrs["aria-describedby"] = " ".join(
            part for part in (describedby, metadata_id) if part
        )
        if state.locked:
            field.disabled = True
        extras[field_name] = _field_metadata(field_name, state)
    return extras


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
    extras = prepare_setting_fields(form, states)
    return _LiveSettingFields(
        patch_url_template=patch_url_template,
        csrf=csrf,
        event=event,
        class_="flex flex-col gap-6 @container",
    )[FormFields(form, extras=extras, groups=groups)]


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
    "SettingsScaffold",
    "SettingsSection",
    "SettingsSectionNav",
    "prepare_setting_fields",
]
