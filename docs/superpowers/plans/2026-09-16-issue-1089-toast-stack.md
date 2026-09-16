# Toast stack custom element Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the toasts out of the Alpine template string in `common/layout.py` into a `<toast-stack>` custom element, changing nothing a person sees.

**Architecture:** `ts/elements/toast-stack.ts` holds a plain TS store with the Alpine store's shape and an element that renders it with `createElement`. `common/components/toast.py` renders the empty tag through `custom_element_builder`. `ts/toast.ts` keeps `window.toast`, `window.removeToast` and the two fetch helpers; its Alpine parts go.

**Tech Stack:** TypeScript custom element, vitest in jsdom, Django component builders, Tailwind literal scan of `ts/`.

**Spec:** `docs/superpowers/specs/2026-09-16-toast-stack-design.md` (issue #1089, member 1 of the #695 stack).

## Global Constraints

- Every class string moves over as one literal; Tailwind scans `ts/` for literals and never concatenations.
- No `Alpine` reference remains in `ts/toast.ts` or `ts/elements/toast-stack.ts`.
- `window.toast(message, type, options)`, `show-toast`, `remove-toast`, `toast-dismissed`, the `django-messages` script and `HX-Trigger` keep their contracts.
- The stack carries no `tabindex`; `e2e/test_pinned_column_e2e.py:50` selects the one focusable region.
- Identifiers are whole words (`element`, not `el`).
- Run `make ts` after editing `.ts` so e2e sees fresh output; never run e2e while `make dev` is up.
- The gate is the full `make check`; `make check-fast` is for iterating.

---

## File structure

| File | Responsibility |
|---|---|
| `ts/elements/toast-stack.ts` (create) | `ToastStore` (rules, timers) and `ToastStackElement` (listeners, DOM) |
| `ts/elements/toast-stack.test.ts` (create) | lifecycle and DOM cases in jsdom |
| `ts/toast.ts` (modify) | `window.toast`, `window.removeToast`, `dispatchHtmxTriggers`, `fetchWithHtmxTriggers`; Alpine parts removed |
| `ts/toast.test.ts` (modify) | keeps the two fetch cases; lifecycle cases move |
| `common/components/toast.py` (create) | `ToastStackProps`, `ToastStack()`, registration |
| `common/components/__init__.py` (modify) | exports `ToastStack` so codegen imports the module |
| `common/layout.py` (modify) | `_TOAST_CONTAINER` removed; `ToastStack()` placed and its media first |
| `tests/test_rendered_pages.py:165` (modify) | marker `<toast-stack` |
| `ts/client-errors.ts:7-9`, `e2e/test_filter_builder_e2e.py:407-408` (modify) | comments |
| `CLAUDE.md`, `docs/settings-panel-epic.md:67` (modify) | docs sweep |

Task order matters: the element exists before the layout names it, and the template string is read for its classes before it is deleted.

---

### Task 1: The element and its store

**Files:**
- Create: `ts/elements/toast-stack.ts`
- Create: `ts/elements/toast-stack.test.ts`
- Read only: `common/layout.py:68-172` (the classes and icon paths to copy), `ts/toast.ts:1-150` (the store rules), `ts/elements/copy-control.test.ts` (the jsdom pattern)

**Interfaces:**
- Produces `export type ToastType = "success" | "error" | "info" | "warning" | "debug"`.
- Produces `export interface ToastMessage { message: string; type?: string; id?: ToastId; duration?: number | null }` where `type ToastId = number | string`.
- Produces `export class ToastStore` with `toasts: Toast[]`, `constructor(onChange: () => void)`, `addToast(message, type?, options?)`, `dismissToast(id, notify = true)`, `removeToast(id)`, `clearToastTimer(id)`, `resumeToastTimer(id)`. Same rules as `ts/toast.ts:39-150`: unknown type is `info`; duration 5 000, `debug` 3 000, `error` `null`, `options.duration` wins including `null`; at most three, oldest shifted with its timers cleared; a stable id replaces in place and clears both timers; dismiss sets `visible = false`, fires `toast-dismissed` on `window` with `{ id }` when `notify`, removes after 300 ms; `clearToastTimer` keeps `remaining`, `resumeToastTimer` restarts it. `onChange()` is called at the end of every mutation and inside both timer callbacks.
- Produces `class ToastStackElement extends HTMLElement` with `readonly store`, `render()`, `connectedCallback`, `disconnectedCallback`; defined as `toast-stack`.
- Produces one DOM shape a toast: `div[data-toast-id][tabindex="0"][role][aria-live]` > `div` panel > `span` icon, `p[data-toast-message]` text, `button[data-toast-dismiss]`.

- [ ] **Step 1: Write the failing tests** in `ts/elements/toast-stack.test.ts` (`// @vitest-environment jsdom`, `import "./toast-stack.js"`, fake timers, `document.body.innerHTML = "<toast-stack></toast-stack>"` in `beforeEach`, `document.body.innerHTML = ""` in `afterEach` so `disconnectedCallback` runs). Cases:
  - `renders a show-toast payload as one status toast with its message`: dispatch `show-toast` on `document` with `{message: "Saved", type: "success"}`; one `[data-toast-id]`, `role="status"`, `aria-live="polite"`, `[data-toast-message]` text `Saved`.
  - `renders a list payload as several toasts and keeps three at most`: list of four; three remain, the first gone.
  - `error and warning are alerts; error is assertive`.
  - `replaces a stable string id in place and clears its previous timer` (port of `ts/toast.test.ts:78-92`, asserted through the DOM and `vi.getTimerCount()`).
  - `removes stable toasts through window.removeToast whether visible or dismissed` (port of `:93-104`; `remove-toast` must reach the element).
  - `uses defaults and resumes only the remaining duration after pause` (port of `:106-121`; drive `mouseenter`/`mouseleave` on the wrapper).
  - `dismisses on click, on Escape, and on the close button without reaching the wrapper`: after dismiss the wrapper carries `opacity-0`; after 300 ms it is gone; `toast-dismissed` fired once with the id.
  - `reads the django-messages script on connect`: put `<script id="django-messages" type="application/json">[{"message":"Hello","type":"info"}]</script>` in the body before the element; one toast.
  - `detaches its listeners on disconnect`: remove the element, dispatch `show-toast`, reconnect a new one, zero toasts.

- [ ] **Step 2: Run** `make test-ts` — expected: the new file fails to import.

- [ ] **Step 3: Write `ts/elements/toast-stack.ts`.** Copy every class string from `_TOAST_CONTAINER` (`common/layout.py:68-172`) into constants: the wrapper class, the panel class per type, the icon colour per type, the text colour per type, the close-button colour per type, the five SVG paths, the leave classes (`transition ease-in duration-200` + `opacity-0 translate-x-8`). `render()` reconciles: for each store toast without a node, build and append one; for a node without a toast, remove it; for a toast with `visible === false`, add the leave classes once. Event wiring on the wrapper: `click` → `dismissToast(id)`; `keydown` Escape → the same; `mouseenter` → `clearToastTimer`; `mouseleave` → `resumeToastTimer`; the close button's `click` calls `stopPropagation()` then dismisses. Listeners for `show-toast` and `remove-toast` are class fields bound once, added on `window` in `connectedCallback`, removed in `disconnectedCallback`. The `django-messages` read wraps `JSON.parse` and reports a failure through `reportClientError("toast-stack[django-messages]", message, { toast: false })` from `../client-errors.js`. No `console.log`.

- [ ] **Step 4: Run** `make test-ts` — expected: all green, `ts/toast.test.ts` untouched and green.

- [ ] **Step 5: Commit** `feat: a <toast-stack> element renders the toasts`.

---

### Task 2: The Python builder and the layout

**Files:**
- Create: `common/components/toast.py`
- Modify: `common/components/__init__.py` (import and export `ToastStack`)
- Modify: `common/layout.py:68-172` (delete `_TOAST_CONTAINER`), `:413-417` (media sum), `:454` (`toast_container`)
- Modify: `tests/test_rendered_pages.py:165`

**Interfaces:**
- Produces `class ToastStackProps(TypedDict): pass`, `register_element("toast-stack", "ToastStack", ToastStackProps)`.
- Produces `def ToastStack() -> Node`, built from `custom_element_builder("toast-stack")` with `role="region"`, `aria_label="Notifications"`, `aria_atomic="true"`, and the container class from `common/layout.py:72` (`fixed z-50 bottom-0 right-0 flex flex-col items-end pointer-events-none p-4`). The builder attaches `Media(js=("dist/elements/toast-stack.js",))` itself; declare none by hand.

- [ ] **Step 1: Change the marker** in `tests/test_rendered_pages.py:165` from `"toastStore()"` to `"<toast-stack"`. Run `make test ARGS="tests/test_rendered_pages.py -k layout_wrapper"` — expected: FAIL.

- [ ] **Step 2: Write `common/components/toast.py`** and export it from `common/components/__init__.py`. Registration lives in this module (not `custom_elements.py`); `gen_element_types` imports only `common.components`, which is why the `__init__` import is load-bearing. Run `make gen-element-types` and confirm `ToastStackProps` appears in `ts/generated/props.ts`.

- [ ] **Step 3: Wire the layout.** In `common/layout.py`: build `toast_container = ToastStack()` above the `media = ...` sum and write the sum as `collect_media(toast_container) + collect_media(content) + collect_media(navbar) + Media(js=("dist/elements/modal-dialog.js",))`, with a comment that the stack's module goes first so its listener stands before any content element connects. Delete `_TOAST_CONTAINER` and the `Safe(_TOAST_CONTAINER)` line; place `toast_container` where the string was. `dist/toast.js` stays in the head.

- [ ] **Step 4: Run** `make check-fast` — expected: green. Then `make ts` and open one list page with `make dev` (or run `make test-e2e ARGS="-k toasts"` if such a case exists) and confirm a toast still draws in the corner.

- [ ] **Step 5: Commit** `feat: the layout draws the toasts through <toast-stack>`.

---

### Task 3: Alpine leaves `ts/toast.ts`; the sweep

**Files:**
- Modify: `ts/toast.ts` (delete the `alpine:init` listener, the `Alpine.store` and `Alpine.data` registrations, the `declare const Alpine`, the `Toast`/`ToastStore` interfaces now living in the element; `window.removeToast` always dispatches `remove-toast` on `window`; the `console.log` lines go)
- Modify: `ts/toast.test.ts` (delete `installToastStore` and the `stable toast lifecycle` block; keep `fetchWithHtmxTriggers`)
- Modify: `ts/client-errors.ts:7-9` (state the real order: head modules, then Alpine, then the body modules; the toast listener stands before any element connects)
- Modify: `e2e/test_filter_builder_e2e.py:407-408` (the toast renders through `<toast-stack>` as a `[data-toast-message]` element)
- Modify: `CLAUDE.md` (Frontend stack: `ts/toast.ts` no longer an Alpine store; Alpine paragraph: three `x-mask` inputs, not the two selectors; Conventions "Inline Alpine.js" bullet the same), `docs/settings-panel-epic.md:67`

- [ ] **Step 1: Edit `ts/toast.ts` and `ts/toast.test.ts`.** Run `make test-ts` — expected: green, no test references `Alpine`.

- [ ] **Step 2: Grep** `grep -rn "Alpine.store(\"toasts\")\|toastStore\|x-text=\"toast" ts games common e2e tests docs CLAUDE.md` — expected: no hits outside the docs you are rewriting in this step.

- [ ] **Step 3: Sweep the comments and docs** named above. Run `make vale`.

- [ ] **Step 4: Run the gate** `make check` from a log with its exit code — expected: green, e2e included.

- [ ] **Step 5: Commit** `refactor: the toast store leaves Alpine`, push, open the PR as member 1 of the stack (`gh stack init` / `add` / `submit`).

---

## Follow-up issues to file

- Retire Alpine: three `x-mask` inputs (`games/forms.py:859, 1008`, `games/settings_forms.py:48`) and `alpine-mask.min.js` are all that remain after this member.

## Self-review

Spec coverage: element and props (Task 2), store rules and DOM (Task 1), listener order and media sum (Task 2), `toast.ts` residue (Task 3), verification list (Tasks 1–3), docs sweep (Task 3). Names used across tasks: `ToastStore`, `ToastStackElement`, `ToastStack`, `ToastStackProps`, `data-toast-id`, `data-toast-message`, `data-toast-dismiss` — one spelling each.
