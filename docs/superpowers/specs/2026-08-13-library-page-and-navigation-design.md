# Library page, component kit, and navigation design

Status: approved design from the #629-#638 review and design interview.

Companion specification: [User library ownership and production cutover](2026-08-13-user-library-ownership-cutover-design.md).

## Context

The current entity-management Menu overlaps with the emerging library concept
but does not explain the portable data boundary or provide a coherent place for
library facts, customization, and transitional purchase management. The
navbar's Home/Menu/account links also do not reflect the importance of Log game
and Library.

The Library page will replace Menu completely. Its structure follows the
successful Settings page pattern, while its rows, statistic cards, identity
facts, copy control, and account menu are reusable components approved before
the real page is assembled. This prevents individual panel implementers from
inventing one-off layout and styling.

## Goals

- Make the library boundary understandable and its immutable identity visible.
- Give user-owned data useful, reproducible entry points without turning every
  model into a management panel.
- Establish reusable components and obtain visual approval before page work.
- Replace Menu and simplify the navbar without removing valid routes.
- Design Customization around the future IGDB split while accurately describing
  today's data.
- Keep purchase management explicitly transitional until Catalogue work.

## Non-goals

- Backup/restore or self-service deletion UI.
- Player's Journal Activity functionality.
- Catalogue or IGDB implementation.
- Avatar upload/storage.
- New PlayEvent management UI.
- A general saved-preset management panel.
- SearchSelect conversion of the default-Device dropdown.
- Section scroll-spy/active highlighting.
- Rebuilding existing primitives or reproducing the finished Library page in
  the component showcase.

## Delivery and approval gates

UI delivery follows the ownership cutover in two issues:

1. A reusable Library UI component-kit issue.
2. One issue for all initial Library panels and the final navbar replacement.

The component issue exposes a standalone DEBUG-only preview route such as
`/library-kit-preview/`. It is absent from production and from all navigation.
The PR remains draft until the desktop and mobile rendering is approved by the
product owner and that approval is recorded in the issue and PR.

The showcase focuses on components newly required by this design. Existing
components may appear where necessary to show realistic composition; they do
not need redundant standalone specimens. The showcase is not a functional
duplicate of the completed page.

The page PR also remains draft until the real desktop and mobile pages are
approved. It must use the approved reusable contracts and existing design
primitives rather than one-off inline styling. If an implementer finds a
genuine component gap, they stop, consult the product owner on the proposed
contract and visuals, add the small reusable prerequisite to the showcase, and
obtain approval before continuing.

The preview route is removed in the page issue after the real page exercises
the components.

## Reusable component inventory

### Sectioned-page structure

The existing Settings structure is generalized with neutral internal names:

- `SectionedPageHeader`
- `SectionedPageScaffold`
- `SectionNav`

Settings migrates immediately to these generalized components with no
compatibility aliases and no visible or behavioral change. Library uses the
same structure. Mobile navigation supplies a page-specific accessible label;
Library uses “Library sections” and “Jump to a section.”

### Content components

- `StatisticGrid`: lays out responsive summary statistics.
- `StatisticCard`: supports either an exact-record link or a visibly plain,
  non-clickable value.
- `EntitySummaryList`: a quiet divider-separated list inside an existing
  section panel, without a nested card border.
- `EntitySummaryRow`: label, subtitle, optional detail area, right-aligned
  count, and actions; mobile actions collapse into an accessible overflow menu.
- `FactList`: compact label/value facts used for library identity.
- `CopyControl`: copies an adjacent value, changes “Copy” to “Copied” briefly,
  and surfaces a visible failure. Success and failure are accessible without a
  global success toast.
- `AccountMenu`: circular trigger plus the approved identity, playtime,
  navigation, theme, and logout composition.

The existing toast system also receives the generic stable-ID and no-timer
capabilities specified in the ownership design. Its running, failed, and
completed conversion states appear in the showcase, but currency-operation
logic is not part of the visual component contract.

Existing Button, Dropdown, form fields, typography, panels, and icons are
reused. The initial default-Device selector uses the current dropdown style and
does not depend on #481. The repository-wide goal remains to migrate
user-facing selects to SearchSelect later.

## Page structure

`/library` is one sectioned page with stable anchor sections:

1. Overview
2. Activity
3. Customization
4. Purchases

These are durable concepts rather than a list of database models. Purchases is
explicitly provisional until Catalogue design establishes its final home.

Desktop places section navigation at the left. Mobile uses the generic
section-jump control followed by the normal page heading. Responsive behavior
is based on the section container's available width rather than the entire
viewport.

The page header is:

> # Library
>
> Your games, play history, purchases, and customizations belong to this
> library and stay together when it is backed up or restored.

“Library” is capitalized as the page and navigation title; prose uses lower-case
“library.”

## Overview

Overview first shows immutable identity facts:

- **Library ID:** the complete UUID in monospace, with a separate Copy control.
- **Created:** date only, formatted using the User's date/time presentation
  preference.

It does not show username, a library display name, or an updated timestamp.

The all-time statistic grid contains exactly:

- Games
- Sessions
- Purchases
- Devices

Every value is user-owned data only and links to the exact contributing list.
The label is simply “Games”; it is not repeated as “X games.” A zero remains a
normal linked zero so layout and actions do not shift.

Today, Games counts every Game row owned by the library. It is not limited to
catalogue-only records, status values, or purchases. After IGDB/UserGame work,
the count is expected to mean games the user tracks a status for; wishlists do
not count. That future distinction does not change the current requirement.

PlayEvent and GameStatusChange counts are omitted from the UI but remain part
of migration reconciliation.

## Activity

Activity contains an explicit non-functional placeholder and no Log game
action:

> **Activity is coming later**
>
> This section will be added as part of the Player's Journal.

Log game is already a primary navbar action and is not duplicated on Library.

## Customization

The section begins with this visible transitional explanation:

> Games currently includes every game in your library. After IGDB integration,
> this area will contain only games and platforms you customized or created.
> Devices will remain here.

It contains divider-separated rows for Games, Platforms, and Devices. On a
wide container, each row uses three aligned areas:

```text
Label and subtitle                       Count        Actions
```

The count is right-aligned and clickable. Browse and Add remain separate
actions on desktop. On mobile, Browse and Add move into an accessible
three-dot menu; the label, subtitle, and count remain visible. The extra tap is
accepted because Platform management is rare and more important future
Session/Purchase browsing will have stronger entry points.

Exact row copy and behavior:

| Row | Subtitle | Count | Actions/details |
| --- | --- | --- | --- |
| Games | Games currently tracked in this library. | All current library-owned Games; future custom-only | Browse, Add |
| Platforms | Platforms you added manually. | Private Platforms only | Browse private management list, Add private Platform |
| Devices | Hardware you use to play. | All library Devices | Browse, Add; optional default selector below |

The Device detail row says “Preselected when logging a game.” The optional
default Device saves immediately. Deleting the selected Device clears the
setting rather than guessing another.

Shared Platforms appear in selectors but never in the private Browse list or
private count. The user cannot manage them from this section.

## Purchases

Purchases starts with a visible status block:

> **Temporary home**
>
> Purchase management will move into the future Catalogue. This section
> provides a library summary in the meantime.

Its all-time statistics are:

- Purchases: all records, including refunded Purchases.
- Total spent: non-refunded Purchases, including price-zero records.
- Refunded Purchases: the refunded subset.

Every value links to the exact contributing Purchase list/filter. There is no
separate Browse action because the total Purchases statistic supplies it. Add
purchase appears in the section header.

The current price-zero ambiguity is preserved: zero may mean genuinely free or
unknown. A dedicated follow-up models price certainty. Until then, zero-price
non-refunded records participate in Total spent normally.

The statistic-link rule applies throughout Library: if an exact contributing
record view exists, the value links to it; otherwise it is visibly
non-clickable. This avoids forcing users to reverse-engineer filters or guess
how a total was calculated.

During currency conversion or failure, the last complete total remains visible
with its actual published currency. Conversion state is communicated only by
the global toast contract; Purchases does not duplicate the message inline.

## Navbar

The final page issue replaces the current navbar structure:

- Logo links to Home; the separate Home text link is removed.
- Log game remains directly visible.
- Library is directly visible.
- A circular account button shows initials, with a generic user icon fallback.

On mobile, the logo wordmark contracts to its icon and all three controls—Log
game, Library, and account—remain directly visible. There is no hamburger.

The account menu is ordered as follows:

1. Username as a non-link heading.
2. Today playtime, linked to its exact Session filter.
3. Last 7 days playtime, linked to its exact Session filter.
4. Stats, opening the current-year view.
5. Settings.
6. Admin settings, shown only when authorized.
7. Theme control.
8. Log out.

Separators divide identity/playtime, navigation, theme, and logout groups. The
existing rule that disables theme changes on Settings and Admin Settings
remains, including its current explanation. Theme control is active on Library.

Actual avatar upload and storage are deferred. The circular trigger is designed
to accept an image later without changing the menu contract.

## Routing and removed navigation

Library replaces the generic entity Menu and most Manage links because those
navigation concepts overlap. Existing entity URLs are not deleted merely
because their top-level navigation changes.

PlayEvent stays mostly an internal/history detail. Contextual add/view links on
Game pages and existing generic PlayEvent routes remain, but no Library panel
or navbar entry is added. FilterPreset management also remains embedded in its
relevant filter/list surfaces.

The existing Home page remains separate and becomes accessible through the
logo. No anonymous navbar variant is needed because the application is not
usable without authentication; the login page continues using the site/system
theme.

## Accessibility and responsive behavior

- All statistic links have useful accessible names that include their subject,
  not only a bare number.
- The mobile overflow trigger names the row it controls and supports keyboard
  operation, focus return, Escape, and outside-click dismissal through the
  existing Dropdown behavior.
- Copy success and failure are announced accessibly.
- The account trigger exposes the username/menu purpose even when only initials
  or an icon are visible.
- Section navigation retains correct landmarks, focus order, and anchor targets
  on desktop and mobile.
- Empty and zero states retain the same layout and available actions.

## Verification and visual approval

Component tests cover rendering contracts, linked/plain statistic behavior,
copy states, menu accessibility, and responsive action composition. Existing
Settings tests prove its generalized scaffold is visually and behaviorally
unchanged.

The DEBUG-only showcase is rendered and reviewed at representative desktop and
mobile widths before the component PR leaves draft. The finished Library page
and navbar receive a second rendered desktop/mobile review before their PR
leaves draft. Automated end-to-end coverage verifies exact statistic links,
private Platform navigation, default-Device saving, navbar/menu destinations,
conditional Admin settings, theme disabled states, and mobile keyboard/menu
behavior.

Each issue runs the full normal `make check` gate after focused checks. No
panel implementation begins until the component PR and its recorded visual
approval are complete.

## Explicit follow-ups

- Player's Journal implements Activity.
- Catalogue decides the final Purchase-management home and stronger Session and
  Purchase browsing entry points.
- IGDB/UserGame work changes Customization from all current Games/Platforms to
  custom additions while preserving library-private custom records.
- #481 converts the default-Device dropdown to SearchSelect.
- New issues cover Purchase price certainty, avatar upload/storage, and general
  active-section highlighting for Settings and Library.

## GitHub plan reconciliation

After both linked specifications are approved:

- #629 is rewritten as the identity foundation.
- #630 is rewritten as the complete offline cutover.
- New issues are created for the component kit/showcase and finished Library
  page/navbar.
- #631-#638 close as superseded with links to the work that absorbed them.
- #776 closes because temporary claim machinery is no longer created.
- #490 closes as superseded by the complete navbar design.
- #599 records the consolidation and production-specific rationale in its Plan
  adjustments section.
- Phase 1 epic #600 is reorganized around the real issue order and dependencies.
- #728, #481, #750, #796, and #801 are updated where the approved handoff alters
  or clarifies their boundaries.
