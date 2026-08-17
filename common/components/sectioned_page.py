"""Reusable sectioned-page structure with responsive same-DOM navigation."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from common.components.core import Child, Children, Node, as_children, randomid
from common.components.custom_elements import BottomSheet
from common.components.primitives import (
    ContentContainer,
    ControlButton,
    ControlLink,
    Div,
    Icon,
    Li,
    Nav,
    P,
    PageHeading,
    PlainH2,
    Section,
    Span,
    Ul,
    custom_element_builder,
)

_SectionNav = custom_element_builder("section-nav")

_SECTION_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_NAV_LINK_CLASS = (
    "inline-flex min-h-control w-full items-center whitespace-nowrap rounded-base px-3 "
    "text-type-body font-medium text-heading no-underline "
    "hover:bg-neutral-tertiary-medium focus:outline-hidden focus:ring-4 focus:ring-inset "
    "focus:ring-brand-medium"
)


@dataclass(frozen=True, slots=True)
class SectionedPageSection:
    """One labeled, anchorable section in :func:`SectionedPageScaffold`."""

    id: str
    label: str
    content: Child
    description: str = ""


def SectionedPageHeader(
    title: str,
    *,
    description: str = "",
    actions: Children = None,
) -> Node:
    """The shared header a sectioned surface renders above its content.

    ``actions`` hosts page-level actions — ones that own the whole page and have
    no other home in the scaffold. A :class:`SectionedPageSection` panel is a
    content container, so an action placed in one reads as belonging to that
    section.

    Multi-slot (title / description / actions), so it keeps semantic parameters
    rather than an htpy ``[]`` slot. Bakes no bottom margin — the page body is a
    ``gap``-spaced flex column that owns the distance to the content below.
    """
    heading_children: list[Node] = [PageHeading([title])]
    if description:
        heading_children.append(P(class_="text-type-body text-body")[description])
    header_children: list[Node] = [Div(class_="flex flex-col gap-4")[*heading_children]]
    action_children = as_children(actions)
    if action_children:
        header_children.append(
            Div(
                data_sectioned_page_actions="",
                class_="flex flex-wrap items-start gap-2",
            )[*action_children]
        )
    return ContentContainer()[
        Div(
            data_sectioned_page_header="",
            class_="flex flex-wrap items-start justify-between gap-4",
        )[*header_children]
    ]


def _validate_sections(sections: Sequence[SectionedPageSection]) -> None:
    if not sections:
        raise ValueError("SectionedPageScaffold requires at least one section.")
    seen: set[str] = set()
    for section in sections:
        if not _SECTION_ID.fullmatch(section.id):
            raise ValueError(
                f"Invalid sectioned-page section id {section.id!r}; "
                "use an HTML-safe id."
            )
        if section.id in seen:
            raise ValueError(f"Duplicate sectioned-page section id {section.id!r}.")
        seen.add(section.id)


def _section_link(section: SectionedPageSection) -> Node:
    return Li(
        data_section_nav_item="",
        class_="w-full",
    )[ControlLink(href=f"#{section.id}", class_=_NAV_LINK_CLASS)[section.label]]


def SectionNav(
    sections: Sequence[SectionedPageSection],
    *,
    navigation_label: str,
    jump_label: str,
) -> Node:
    """Same-DOM mobile bottom sheet and desktop sticky section rail.

    The server leaves the complete link list visible in the inline rail as the
    no-JavaScript fallback. After enhancement, narrow containers move that one
    list into a native-dialog bottom sheet; ``@4xl`` restores it to the rail.
    """
    _validate_sections(sections)
    sheet_id = randomid(
        seed="section-nav-",
        content=":".join(section.id for section in sections),
        length=20,
    )
    trigger = ControlButton(
        [
            ("data-section-nav-trigger", ""),
            ("class", "w-full rounded-base py-2 focus:ring-inset"),
        ],
        variant="outline",
    )[
        Span(class_="flex w-full items-center justify-between gap-3 text-left")[
            Span(class_="flex min-w-0 flex-col")[
                Span(class_="text-type-label text-heading")[navigation_label],
                Span(class_="text-type-micro text-body")[jump_label],
            ],
            Icon(
                "arrowdown",
                [("aria-hidden", "true"), ("class", "shrink-0 rotate-180")],
                size="h-3 w-3",
            ),
        ]
    ].as_element()
    sheet_destination = Nav(
        [
            ("data-section-nav-sheet-destination", ""),
            ("aria-labelledby", f"{sheet_id}-title"),
        ],
    )
    sheet = Div(data_section_nav_sheet="", hidden=True)[
        BottomSheet(
            trigger_element=trigger,
            title=navigation_label,
            children=sheet_destination,
            id=sheet_id,
            close_label=f"Close {navigation_label.lower()}",
        )
    ]
    return _SectionNav(class_="sticky top-4 z-10 block min-w-0 self-start @4xl:z-auto")[
        Nav(
            [
                ("aria-label", navigation_label),
                ("data-section-nav-rail", ""),
                (
                    "class",
                    "mb-4 max-h-[calc(100vh-2rem)] overflow-y-auto @4xl:mb-0",
                ),
            ],
        )[
            Ul(data_section_nav_list="", class_="flex min-w-0 flex-col gap-1")[
                *[_section_link(section) for section in sections]
            ]
        ],
        sheet,
        # CSS/container-query truth exposed to the layout behavior without
        # duplicating the @4xl threshold in matchMedia JavaScript.
        Span(
            data_section_nav_wide="",
            class_="hidden @4xl:block",
            aria_hidden="true",
        ),
    ]


def _section_panel(section: SectionedPageSection) -> Node:
    heading_id = f"{section.id}-heading"
    header_children: list[Node] = [
        PlainH2(
            [
                ("id", heading_id),
                ("tabindex", "-1"),
                ("data-sectioned-page-section-heading", ""),
                ("class", "text-type-subheading text-heading focus:outline-hidden"),
            ],
        )[section.label]
    ]
    if section.description:
        header_children.append(
            P(class_="text-type-body text-body")[section.description]
        )
    return Section(
        [
            ("id", section.id),
            ("aria-labelledby", heading_id),
            ("data-sectioned-page-section", ""),
            (
                "class",
                (
                    "scroll-mt-24 @4xl:scroll-mt-4 flex flex-col gap-6 rounded-base "
                    "border border-default bg-neutral-primary-medium p-4 @container"
                ),
            ),
        ],
    )[
        Div(
            data_sectioned_page_section_header="",
            class_="flex flex-col gap-2",
        )[*header_children],
        Div(
            data_sectioned_page_section_content="",
            class_="flex flex-col gap-4",
        )[section.content],
    ]


def SectionedPageScaffold(
    sections: Sequence[SectionedPageSection],
    *,
    navigation_label: str,
    jump_label: str,
) -> Node:
    """Responsive section navigation and content scaffold.

    The split is container-query driven: a narrow embedding stacks nav/content;
    a wide embedding promotes the nav to a rail without changing or cloning DOM.
    """
    _validate_sections(sections)
    return _sectioned_page_scaffold(
        sections,
        navigation_label=navigation_label,
        jump_label=jump_label,
    )


def _sectioned_page_scaffold(
    sections: Sequence[SectionedPageSection],
    *,
    navigation_label: str,
    jump_label: str,
) -> Node:
    """Render a scaffold whose sections have already been validated."""
    return ContentContainer(class_="@container")[
        Div(
            data_sectioned_page_scaffold="",
            class_=(
                "grid grid-cols-1 gap-6 "
                "@4xl:grid-cols-[14rem_minmax(0,1fr)] @4xl:items-start @4xl:gap-8"
            ),
        )[
            SectionNav(
                sections,
                navigation_label=navigation_label,
                jump_label=jump_label,
            ),
            Div(class_="flex min-w-0 flex-col gap-6")[
                *[_section_panel(section) for section in sections]
            ],
        ]
    ]


def SectionedPage(
    title: str,
    sections: Sequence[SectionedPageSection],
    *,
    description: str = "",
    actions: Children = None,
    navigation_label: str,
    jump_label: str = "Jump to a section",
) -> Node:
    """A complete sectioned page with its header, scaffold, and shared gap."""
    _validate_sections(sections)
    return Div(data_sectioned_page="", class_="flex flex-col gap-6")[
        SectionedPageHeader(title, description=description, actions=actions),
        _sectioned_page_scaffold(
            sections,
            navigation_label=navigation_label,
            jump_label=jump_label,
        ),
    ]


__all__ = [
    "SectionNav",
    "SectionedPage",
    "SectionedPageHeader",
    "SectionedPageScaffold",
    "SectionedPageSection",
]
