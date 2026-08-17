# Library

The Library is the authenticated user's boundary for private games, play
history, purchases, devices, platforms, and Library preferences. Application
code resolves it from `request.user.library`; supported reads and writes stay
within that Library.

## Library page

`/tracker/library` is an authenticated sectioned page with stable anchors for:

1. Overview
2. Activity
3. Customization
4. Purchases

The section navigation uses the shared `SectionedPage` structure. It keeps one
semantic link list: a desktop rail when its container is wide and a mobile
bottom-sheet jump control when it is narrow. Links remain ordinary anchors,
and each section has a focusable heading target.

Overview shows the Library's immutable ID with a copy control, its creation
date in the user's date/time presentation, and linked counts for Games,
Sessions, Purchases, and Devices. Counts and links include only records owned
by the current Library.

Activity is intentionally a placeholder until the Player's Journal provides
its content. Customization provides Library-scoped Games, private Platforms,
and Devices with Browse/Add actions. Purchases provides the current Library
summary and links to its contributing Purchase filters.

## Navigation and preferences

The authenticated navbar keeps the logo, Log game, Library, and account menu
directly available at every responsive width; it has no hamburger menu. The
account trigger displays initials derived from the username and uses the
username for its accessible menu label.

The default Device is a Library preference. The Library page presents it as a
scoped model choice and saves it through the fixed
`/api/library/default-device` endpoint. Its effective source is retained as
machine-readable field metadata. A source badge is shown only when the
effective source differs from that setting's normal source.

## Reusable presentation contracts

Library-shaped summaries use the public components in `common.components`:

- `StatisticGrid` and `StatisticCard` present linked or plain values.
- `FactList` and `CopyableFactValue` present immutable facts.
- `SummaryList`, `SummaryRow`, and `SummaryValue` keep a summary value paired
  with its optional link.
- `SectionedPage`, `SectionedPageScaffold`, and `SectionNav` provide the
  accessible responsive page structure.

Shared visual rules for these and other components are documented in
[`visual-conventions.md`](visual-conventions.md).
