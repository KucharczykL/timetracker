# `<form-dialog>` Implementation Plan

**Goal:** A link marked `data-form-dialog` opens its page in a modal, submits
through `fetch`, and refreshes the page underneath on success.

**Spec:** `docs/superpowers/specs/2026-10-04-issue-1384-form-dialog-design.md`
(read it first; this plan names files, interfaces, tests and gotchas only).

**Execution:** inline, TDD per task. Iterate with
`flock "$(git rev-parse --git-common-dir)/heavy-tests.lock" make test-ts TS_ARGS=…`
and focused `make test ARGS=…`; `make ts` before any e2e. Before each commit:
`make format`, `make lint-fix`, `make format-check`, `make vale`.

## Global constraints

- Complete-word identifiers; named compound types; PEP 695 aliases for
  primitive roles (CLAUDE.md conventions).
- Elements carry their own classes; no `input.css` rules.
- The JS module of a component is declared through `Media`, never `scripts=`.
- No form page changes. No production link is marked.
- Comments: terse, no issue references.

## File map

| File | Role |
|---|---|
| `common/components/form_dialog.py` (new) | `FORM_DIALOG_ATTRIBUTE`, `FormDialogChrome`, `form_dialog_link()`, `FormDialogHost()` builder (element + `<template>`) |
| `common/components/modal.py` | `ModalPanelHeader(title, *, title_id, close_label)` extracted |
| `common/components/custom_elements.py` | `BottomSheet` uses `ModalPanelHeader`; `DropdownLinkItem(..., attributes=())`; register `form-dialog` props |
| `common/components/__init__.py` | exports |
| `common/layout.py` | host placement + `collect_media`; `data-page-title`, `data-read-only`, `tabindex=-1` on `#main-container`; `id="navbar"` on `Nav` |
| `games/management/commands/gen_element_types.py` | writes `ts/generated/form-dialog.ts` |
| `ts/elements/modal-layer.ts` | export `openModals()`, `focusReturnTarget()` |
| `ts/elements/form-dialog/answer.ts` (new) | read a `Response` into an `Answer` |
| `ts/elements/form-dialog/rewrite.ts` (new) | id prefix, URL resolution, `action` stamp |
| `ts/elements/form-dialog/routes.ts` (new) | pure open/submit routing |
| `ts/elements/form-dialog/swap.ts` (new) | host-page swap and focus |
| `ts/toast-handoff.ts` (new) | sessionStorage hand-off, shared with toast-stack |
| `ts/elements/form-dialog.ts` (new) | the element: clicks, dialogs, submits, Undo, dirty close |
| `ts/elements/toast-stack.ts` | read the hand-off on connect |
| `ts/elements/date-time-field.ts`, `ts/elements/temporal-field.ts` | form-scoped lookups; temporal listener removal |
| `ts/elements/catalog-editor.ts` | remove `pageshow` listener on disconnect |
| `ts/elements/search-field.ts` | Enter handler into the element |
| `ts/library-conversion-status.ts` | re-read state on `form-dialog:swapped` |

## Task 1: Server side

**Files:** `common/components/form_dialog.py`, `modal.py`,
`custom_elements.py`, `__init__.py`, `layout.py`, `gen_element_types.py`,
`tests/test_form_dialog.py` (new), `tests/test_modal_dialog.py`.

**Interfaces (produces):**
- `FORM_DIALOG_ATTRIBUTE: Final = "data-form-dialog"`;
  `type FormDialogChrome = Literal["header", "bare"]`;
  `FORM_DIALOG_CHROME_VALUES: Mapping[FormDialogChrome, str]` (`header` →
  `""`, `bare` → `"bare"`), guarded like `_require_every_key`.
- `form_dialog_link(chrome: FormDialogChrome = "header") -> HTMLAttribute`.
- `FormDialogHost() -> Node`: `<form-dialog>` holding
  `<template data-form-dialog-template>` around `ModalDialog` → panel `Div`
  (`data-form-dialog-panel`) → `ModalPanelHeader` (`data-form-dialog-header`,
  title `PlainH2` with `id="form-dialog-title"`, `data-form-dialog-title`)
  + body `Div` (`data-form-dialog-body`, scrolls). Dialog
  `aria-labelledby="form-dialog-title"`. Ids inside the template are
  rewritten per instance by Task 3.
- `ModalPanelHeader(title: Child, *, title_id: str, close_label: str =
  "Close dialog") -> Element`; `BottomSheet` renders through it unchanged
  (assert its HTML is identical before/after: snapshot in a test first).
- `register_element("form-dialog", "FormDialog", FormDialogProps)` with an
  empty TypedDict; builder via `custom_element_builder` (auto `Media`).
- Generated `ts/generated/form-dialog.ts`: `FORM_DIALOG_ATTRIBUTE`,
  `FORM_DIALOG_CHROME` (`{header: "", bare: "bare"}`), plus the
  `data-form-dialog-*` part names as one `FORM_DIALOG_PARTS` map from a
  Python mapping (`template`, `panel`, `header`, `title`, `body`).
- Layout: `#main-container` gains `data-page-title=<title>`,
  `data-read-only` when `current_name in READ_ONLY` (reuse the existing
  resolve; compute once), `tabindex="-1"`; `Nav` gains `id="navbar"`;
  `FormDialogHost()` sits after `toast_container` and joins `media`.

**Tests (pytest):** host and template on a rendered page (one list page,
one form page); `data-read-only` present on `games:list_devices`, absent
on `games:add_device`; `data-page-title` equals the view's title;
`id="navbar"`; `DropdownLinkItem(..., attributes=[form_dialog_link()])`
renders the attribute on the `<a>`; `form_dialog_link("bare")`; generated
file drift (pattern of `tests/test_modal_dialog.py`); `BottomSheet`
output unchanged.

**Gotchas:** `assert_unique_element_ids` skips `<template>` (verified);
the template's dialog must not render outside the template. `make
gen-element-types` then commit the generated file. `make render-pages`
diffs will show the host on every page; expected.

## Task 2: Layer exports and toast hand-off

**Files:** `ts/elements/modal-layer.ts` (+test), `ts/toast-handoff.ts`
(+test), `ts/elements/toast-stack.ts` (+test).

**Interfaces:**
- `openModals(): readonly HTMLDialogElement[]` (open state, opening order).
- `focusReturnTarget(opener: HTMLElement | null): HTMLElement | null`
  exported unchanged.
- `handOffMessages(payloads: readonly unknown[]): void` and
  `takeHandedOffMessages(): unknown[]` under key `toast-handoff`; both
  catch storage errors and `reportClientError(..., {toast: false})`.
- `<toast-stack>` calls `takeHandedOffMessages()` in `connectedCallback`
  after `readDjangoMessages()`, through `addAll(…, "handoff")`.

**Tests:** `openModals` excludes leaving modals; hand-off round trip,
cleared after take, throwing storage reported; toast-stack shows a handed
message once.

## Task 3: Answer reading and fragment rewrite

**Files:** `ts/elements/form-dialog/answer.ts`, `rewrite.ts` (+tests).

**Interfaces:**
- `type PageUrl = string`. `normalizedUrl(url: string | URL): PageUrl`
  (origin + path + sorted query, no hash); `sameUrl(a, b): boolean`.
- `interface Answer { url: URL; redirected: boolean; status: number;
  page: AnswerPage | null }`; `interface AnswerPage { content: Node[];
  title: string; readOnly: boolean; messages: unknown[]; modules:
  string[]; navbar: Node[] | null; htmlData: Record<string,string>;
  documentTitle: string }`. `readAnswer(response: Response):
  Promise<Answer>`; `page` null without `#main-container`. Messages parse
  failure is reported and yields `[]`.
- `prefixIds(root: ParentNode, prefix: string): void` — walks
  `template.content` recursively; whole-value set (`list`, `form`,
  `popovertarget`, `aria-activedescendant`, `href="#…"`) and token-list
  set (`for`, `headers`, `aria-labelledby`, `aria-describedby`,
  `aria-controls`, `aria-owns`, `aria-flowto`, `aria-errormessage`,
  `aria-details`); only references to ids present in the root move.
- `resolveUrls(root: ParentNode, base: URL): void` — after `prefixIds`;
  forms lacking `action` get `base`; `href`, `action`, `formaction`
  resolved via `getAttribute`; `#…` hrefs left alone.
- `importModules(urls: readonly string[]): Promise<void>` — rejects on
  any failure.

**Tests:** prefix covers templates, token lists keep foreign tokens,
`#x` href rewritten then left relative; `action` stamped with the
answer's URL incl. query; normalized compare ignores hash and query
order; `readAnswer` on a page without `#main-container`; title and
`data-read-only` read; `django-messages` parsed.

**Gotcha:** `DOMParser` documents resolve against the host URL: never
read `.href`/`.action` properties of parsed nodes.

## Task 4: Routing tables

**Files:** `ts/elements/form-dialog/routes.ts` (+test).

**Interfaces:**
- `interface RouteContext { hostUrl: PageUrl; alone: boolean }`.
- `type OpenRoute = {kind:"toast"} | {kind:"navigate"; url: URL;
  handOff: boolean} | {kind:"present"}`;
  `routeOpen(answer, context): OpenRoute`. Redirected to host → toast;
  page read-only elsewhere → navigate(answer.url, handOff); page →
  present; no page → navigate(link URL, no handOff) — the caller supplies
  the link URL on that kind.
- `type SubmitRoute = {kind:"present"} | {kind:"error"} |
  {kind:"swap"} | {kind:"navigate"; url: URL} | {kind:"closeTop"}`;
  `routeSubmit(answer, context): SubmitRoute` per the spec's list.

**Tests:** one per branch of each table, incl. login page (not
read-only) → present; redirect to read-only non-host while not alone →
closeTop; 409 with page → present; 404 without page → error.

## Task 5: Swap and focus

**Files:** `ts/elements/form-dialog/swap.ts` (+test),
`ts/library-conversion-status.ts`.

**Interfaces:**
- `swapHostPage(page: AnswerPage): Promise<void>`: `importModules`, then
  replace `#main-container` and `#navbar` children, the two stamps,
  `document.title`, `<html>` `data-*`; dispatch `form-dialog:swapped` on
  `document`.
- `refocusAfterSwap(opener: {id: string; href: string}): void`: id match,
  else first `a[href=…]`; unreachable → `focusReturnTarget`; else
  `#main-container`.
- Coordinator listens for `form-dialog:swapped` and re-reads
  `data-library-conversion-state`.

**Tests:** swap leaves `<toast-stack>`/`<form-dialog>` alone; focus
lands on the drop-down toggle when the matched item is in a closed menu;
fallback to `#main-container`.

## Task 6: The element

**Files:** `ts/elements/form-dialog.ts` (+test).

**Behaviour:** per the spec's Open, Presenting, Submit, A chain that
wrote, Undo and Cancel sections. Internals:
- `class FormDialogElement`: one `document` click listener (capture off;
  skip `defaultPrevented`, non-primary button, modifiers, `target=_blank`,
  `download`); one `document` submit listener for
  `[data-form-dialog-body] form` and `form[data-toast-action]` while a
  form dialog is open.
- `interface OpenDialog { dialog; modal: Modal; body: HTMLElement;
  controller: AbortController; opener: OpenerKey; submitting: boolean }`;
  `stack: OpenDialog[]`; `dirty: boolean`; `csrfAtLoad: string` (via
  `getCsrfToken` cookie read only).
- Counter `n` for prefixes; template stamped through
  `template.content.cloneNode(true)` then `prefixIds`.
- `dismiss` hook vetoes while `submitting`; `onClosed` aborts the
  controller, removes the dialog, pops the stack, and when the stack is
  empty and `dirty`: reload if the cookie changed, else GET host → swap →
  refocus.
- Header chrome: content `h1` removed; title text from `data-page-title`;
  bare chrome removes the header node and sets `aria-label`, dropping
  `aria-labelledby`.
- Initial focus via `attachModal`'s `initialFocus`.

**Tests (jsdom, `fetch` stubbed with `Response` objects whose `url` and
`redirected` are set via `Object.defineProperty`):** click filters;
busy link ignores a second click; open dropped when top modal changed;
present → focus on first invalid control; submit posts FormData with
submitter to `formAction`; refused answer replaces content; success at
host swaps and toasts; nested success closes top only and toasts below;
redirect to form page presents in same dialog and marks dirty; dirty
Escape swaps; cookie change reloads (`location.reload` stubbed); Undo
redirect toasts only; Undo page opens a dialog; refused `open()` removes
the dialog; late answer after close dropped; Cancel link to host closes.

## Task 7: Elements that must survive insertion and swap

**Files:** `date-time-field.ts`, `temporal-field.ts`,
`catalog-editor.ts`, `search-field.ts` (+their tests).

- Lookups by field name: `(this.closest("form") ?? document)
  .querySelector(...)`. Test: two forms each with the field name; each
  copy targets its own.
- `temporal-field` copy control: keep a removal handle; remove on
  disconnect (the host element's `disconnectedCallback`, or an
  `AbortController` signal passed to `addEventListener`).
- `catalog-editor`: remove `pageshow` in `disconnectedCallback`.
- `search-field`: Enter listener added in `connectedCallback` on its own
  `[data-match-value]`, removed on disconnect; delete the `onReady` block.

## Task 8: e2e

**File:** `e2e/test_form_dialog_e2e.py`. Each test sets
`data-form-dialog` on a real link with `page.evaluate` before clicking.

- Edit device from the Devices row menu: rename, submit; dialog closes,
  list shows the new name, focus on that row's menu toggle, no full load
  (assert a `window` marker set before survives).
- Invalid submit (empty name) stays in the dialog with the error.
- A `form_page` refusal (e.g. ending access on an already ended copy, or
  another `messages.error` path found while writing the test) toasts
  inside the dialog.
- Nesting: from a dialog, a marked link opens a second; Escape closes the
  top only; focus returns into the first.
- Add game with "Submit & Add to library" continues in the dialog; Escape
  then swaps the Games list (dirty close).
- Scripting disabled (`java_script_enabled=False` context): the link
  navigates.
- Console has no errors in each test (pattern of the dist loading guard).

## Task 9: Gate, docs sweep, PR

Per the implement-issue skill: delete this plan, rewrite the spec timeless
(200–500 words, ASD-STE100), trim comments, add a CLAUDE.md line under
Interactive components, comment #1385/#1501 via the organizer, full
`make check` under the lock, draft PR.
