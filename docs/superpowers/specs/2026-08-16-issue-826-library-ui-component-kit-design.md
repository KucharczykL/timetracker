# Issue 826 Library UI Component Kit Design

Date: 2026-08-16

Status: Design sections approved in conversation; this document is the written
record for final review.

Issue: [#826](https://github.com/KucharczykL/timetracker/issues/826)

Parent product design:
[Library page, component kit, and navigation](2026-08-13-library-page-and-navigation-design.md)

Planning input:
[#630 library-ownership cutover postmortem](../postmortems/2026-08-16-issue-630-library-ownership-cutover.md)

## Authority and current state

This focused specification governs the reusable-component and showcase work in
#826. The parent product design remains authoritative for the future completed
Library page and production navbar; neither belongs to this issue.

#630 is merged. Current `main` already provides the stable-ID/duration toast API
and `library-conversion-status.ts`. #826 reuses those contracts and does not
reimplement, remove, or generalize them. Any genuinely dead #630 runtime code
identified during implementation is handled in a separately reviewed
prerequisite PR, never folded into either PR described here.

## Outcome

Build and visually approve the reusable components needed by the initial
Library page and replacement account navigation without assembling either
finished surface. Generalize the existing Settings sectioned-page structure
first, as an independently reviewable no-visible-change prerequisite.

## Goals

- Give Settings and Library a neutral sectioned-page foundation.
- Build small server-rendered statistic, fact, entity-summary, and account-menu
  components with explicit inputs and no data access.
- Add an accessible CopyControl with local success and failure feedback.
- Exercise every new contract through an authenticated DEBUG-only Timetracker
  preview at desktop and mobile/container-narrow sizes.
- Record product-owner visual approval before the component-kit PR leaves draft.
- Keep review units, tests, and implementation size within an explicit
  complexity budget.

## Non-goals

- Implementing `/library` or any finished Library section.
- Replacing or otherwise changing the production navbar.
- Adding Library queries, persistence, forms, production APIs, background work,
  migrations, or deployment operations.
- Changing generic toast behavior or conversion coordination.
- Cleaning up #630 compatibility or temporary code inside #826.
- Rebuilding Button, Dropdown, ThemeToggle, typography, panel, form, or icon
  primitives.
- Adding section scroll-spy or active-section highlighting.

## Delivery structure

### PR 1: neutral sectioned-page foundation

Extract the generic page structure from `settings_kit.py` into neutral
components:

- `SectionedPageSection`
- `SectionedPageHeader`
- `SectionNav`
- `SectionedPageScaffold`
- `<section-nav>`

`SectionedPageSection` retains the existing section identity, label, content,
and optional description contract. `SectionedPageHeader` retains title,
optional description, and optional page-level actions. `SectionNav` and
`SectionedPageScaffold` require caller-supplied `navigation_label` and
`jump_label`; they contain no Settings copy.

Move section-ID validation, header layout, navigation, section panels, and the
responsive scaffold into the neutral module. Rename Settings-specific DOM hooks
and the custom-element module where they describe the generic structure. Do not
retain compatibility aliases.

Migrate every current consumer, including personal Settings, Admin Settings,
and the Settings kit preview. The PR may change neutral internal names and DOM
hooks, but it must not change visible appearance, responsive behavior, focus
order, anchor behavior, or accessible copy.

PR 1 merges before PR 2 branches. It receives focused server, client, and
browser checks followed by the full `make check` gate. This localizes any
compatibility fallout instead of deferring it into the component feature.

### PR 2: #826 component kit and showcase

Build the Library-facing components and their DEBUG-only showcase on merged PR
1. Keep the PR draft until the required rendered states have written approval.
The preview remains until the later finished-Library issue exercises every
component and removes it.

## Component contracts

### Statistics

`StatisticGrid` owns the responsive column layout for supplied statistic cards.

`StatisticCard(label, value, href=None)` renders one label/value statistic. When
`href` is supplied, the value is the link and its accessible name contains both
the value and subject. When `href` is absent, the value is visibly plain. Zero
uses the same linked or plain contract as any other value; it does not change
layout or actions.

### Facts

`FactList` renders page-level facts as a semantic definition list and accepts
arbitrary value children. A caller can therefore compose the full Library UUID,
monospace treatment, and a separate CopyControl without putting clipboard
behavior inside the list.

The existing `TooltipDefinitionList` also uses definition-list semantics, but
its public contract and typography are tooltip-specific. `FactList` remains a
separate page-level component. A presentation-free private helper may be shared
only if it requires no style switches and leaves all existing tooltip output
unchanged; changing or directly reusing the tooltip component is not part of
#826.

### Entity summaries

`EntitySummaryList` owns the quiet divider-separated list treatment inside an
existing section panel. It does not create a second card border.

`EntitySummaryAction(label, href)` is a small immutable action descriptor for
GET navigation. `EntitySummaryRow` accepts a label, subtitle, count, optional
count link, zero or more action descriptors, and optional detail content. It
renders desktop action links and mobile DropdownLinkItems from the same
descriptors, so callers neither duplicate URLs nor pass rendered nodes that the
component would need to introspect.

Wide containers show label/subtitle, right-aligned count, and separate actions.
Narrow containers keep label/subtitle and count visible while moving actions to
an accessible row-labelled overflow menu. Responsive switching follows the
section container rather than the viewport. Optional detail content occupies a
subtle full-width row below the primary content.

### CopyControl

`CopyControl(value, label="Copy", description=...)` renders a local clipboard
control with an explicit accessible target description. Its custom element
writes the supplied full value through `navigator.clipboard`.

On success, the visible/live label becomes “Copied” for two seconds and then
returns to “Copy.” On rejection, it becomes “Couldn’t copy” and remains visible
until the next attempt. Neither outcome emits a global toast. The control owns
no persistence and makes no network request.

### AccountMenu

`AccountMenu` owns the circular trigger, identity/playtime/navigation/theme/
logout grouping, separators, ordering, trigger fallback, and conditional Admin
entry. It receives display values, exact URLs, CSRF token, the theme-disabled
flag, and already-composed playtime nodes. It performs no User, Session, or
authorization query.

The menu order is username heading, Today playtime, Last 7 days playtime,
current-year Stats, Settings, optional Admin settings, ThemeToggle, and Log out.
Separators divide identity/playtime, navigation, theme, and logout groups.

The trigger exposes the username and menu purpose even when only initials or a
generic user icon are visible. Passing no Admin URL omits the item rather than
rendering a disabled entry. The component composes the existing Dropdown,
ThemeToggle, link, and POST-action primitives.

## Preview and data flow

Add an authenticated DEBUG-only `/tracker/library-kit-preview/` route. The route
is absent from production URL resolution and all navigation. Its component
fixtures are static and do not query or mutate Library data beyond work already
performed by the normal authenticated page shell.

The preview focuses on new contracts. Existing primitives appear only where
needed for realistic composition; it is not a partial implementation of the
finished Library page.

A preview-only TypeScript helper offers controls for the existing running,
failed, and completed conversion-toast appearances. It calls the shipped global
toast API with static messages/options. It does not modify conversion state,
poll an endpoint, or introduce another conversion coordinator.

All server components are pure renderers. Callers supply values, links, action
descriptors, authorization decisions, and composed content. Client behavior is
limited to the renamed section navigation, CopyControl, existing Dropdown
behavior, and the preview-only toast triggers.

## Accessibility and error behavior

- Statistic links identify both value and subject rather than exposing a bare
  number.
- Entity overflow triggers name the row they control and inherit keyboard,
  Escape, outside-click, and focus-return behavior from the existing Dropdown.
- Copy success and failure are visible and announced through a control-local
  polite live region.
- Account triggers name the user/menu purpose; unauthorized Admin navigation is
  absent.
- Section navigation preserves landmarks, focus order, stable anchor targets,
  and a complete no-JavaScript desktop link list.
- Empty and zero examples retain normal layout and actions.

There is no generic retry or error subsystem. Copy failure stays local, preview
toast states use existing behavior, and server-rendered components have no
runtime failure path beyond rejecting invalid component inputs in the same way
as existing component builders.

## Verification strategy

### PR 1

- Server contract tests cover neutral names, caller-supplied labels, section-ID
  validation, and unchanged Settings composition.
- TypeScript tests cover the renamed `<section-nav>` contract.
- Existing Settings, Admin Settings, and Settings-kit preview tests migrate as
  real consumers.
- Existing browser coverage proves mobile sheet, desktop rail, focus, and anchor
  behavior; it is not duplicated in a second exhaustive suite.
- The full managed-hidden-process Windows `make check` gate passes with the
  default parallel `PYTEST_WORKERS` before merge.

### PR 2

- Python contract tests cover semantic markup, linked/plain/zero statistics,
  fact composition, structured entity actions, menu ordering, conditional Admin
  visibility, and accessible names.
- TypeScript tests own CopyControl success, rejection, and reset timing, plus the
  preview helper's calls into the existing toast API.
- Route tests prove login protection, DEBUG-only resolution, and absence from
  navigation.
- One preview browser suite proves component integration and responsive
  composition. Generic Dropdown tests remain authoritative for exhaustive
  keyboard and dismissal behavior; the preview adds only integration smoke
  coverage for the new triggers.
- Existing toast and library-conversion tests remain authoritative for their
  shipped behavior.
- Run the full managed hidden Windows `make check` gate before visual review and
  again after approved visual adjustments.

## Visual approval gate

Render and review representative wide and narrow-container states inside
Timetracker. At minimum the recorded review includes:

- linked, plain, and zero statistics;
- the full UUID fact plus Copy, Copied, and failure states;
- entity rows with and without detail, desktop actions, and mobile overflow;
- AccountMenu with long username, initials and icon fallback, with and without
  Admin settings;
- running, failed, and completed conversion toast appearances; and
- neutral section navigation at desktop and mobile widths.

Keep PR 2 draft until the product owner approves these rendered states. Record
dated approval in both the issue and PR with links to the reviewed captures.
Test passage is not visual approval.

## Complexity budget and replanning triggers

These are forecasts used to expose scope growth, not delivery commitments.

- PR 1 should touch approximately 10–12 files, predominantly moves, renames,
  generated-contract updates, and consumer migrations. It should add no product
  behavior and take roughly one implementation day plus review.
- PR 2 should touch approximately 12–16 files across server components, two
  small client behaviors, preview routing, and focused tests. It should take
  roughly two to four implementation days plus visual-review latency.
- Neither PR includes migrations, production APIs, background work, or
  deployment operations.

Stop and replan if PR 1 changes visible Settings behavior or requires a
compatibility shim. Stop and choose another review boundary if PR 2 crosses 16
implementation/test files, adds a stateful client subsystem, requires real
Library data or persistence, changes a production page/navbar, or expands
beyond the contracts above.

## Planning handoff

After this written specification is approved, replace the old monolithic #826
implementation plan with two plans: one for the neutral sectioned-page PR and
one for the component-kit/showcase PR. Each plan must use risk-focused tests,
preserve the full-gate checkpoints above, and omit duplicate toast/conversion
implementation.
