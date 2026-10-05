# Dialog mode for the form dialog: plan

**Spec:** `docs/superpowers/specs/2026-10-04-issue-1384-form-dialog-design.md`.
The branch holds the swap-based implementation; this plan reworks it.

Iterate with `flock "$(git rev-parse --git-common-dir)/heavy-tests.lock"`
around `make test-ts` (never bare vitest: Node 26) and focused
`make test ARGS=…`; `make ts` before e2e. Before each commit: `make format`,
`make lint-fix`, `make format-check`, `make vale`.

## Task 1: Server answer kinds and dialog mode

**Files:** `common/form_dialog.py` (new: `FORM_DIALOG_HEADER`,
`is_form_dialog`), `common/components/form_dialog.py` (answer TypedDicts:
`PageAnswer`, `DoneAnswer`, `ContinueAnswer`, each with
`kind: Literal[...]`; `FormDialogAnswer` union), `common/components/ts_codegen.py`
(optional keys from `__optional_keys__`), `gen_element_types.py`,
`common/layout.py` (`render_page` dialog branch, `scripts: Sequence[ModuleScript]`,
`Vary: X-Form-Dialog` both modes, remove `id="navbar"`, `data-page-title`,
busy classes, `_main_script`/`mastered`), `games/views/game.py`
(`scripts=[ModuleScript(...)]`, drop `mastered=`), `games/forms.py:1021`
docstring.

- Dialog branch: `JsonResponse(PageAnswer(kind="page", title, html=str(Fragment(content)),
  modules=[static urls], messages=toast_payloads(request)), status=status)`,
  `Cache-Control: no-store`. No `TimetrackerDocument`, no navbar reads.
  `js_external` in media raises `ImproperlyConfigured` in dialog mode.
  DEBUG: `assert_unique_element_ids` on the fragment.

**Tests (pytest, `tests/test_form_dialog.py`):** a form page in dialog mode
answers JSON `page` with title, html without `<nav`, module URL of
`form-dialog`'s dependencies (e.g. Add game's `temporal-field.js` via
`scripts=` and `field-mirror.js` via media), messages; a 409 refusal keeps
its status; `Vary` present in both modes; `id="navbar"`/`data-page-title`
gone; `data-read-only` stays on a full page; codegen optional key
(`ToastPayload.action?`).

## Task 2: Result middleware

**Files:** `common/form_dialog.py` (`FormDialogResultMiddleware`,
`classify_location(request, location) -> DoneAnswer | ContinueAnswer | None`),
`timetracker/settings.py` (after `ToastMessagesMiddleware`),
`games/toast_middleware.py` (skip when `is_form_dialog`).

- 301/302/303/307/308 with `Location` only. Absolute URL via
  `request.build_absolute_uri`. Off-origin → pass through. Resolve path
  against the root urlconf; `READ_ONLY` name → done with
  `toast_payloads(request)`; else continue, queue untouched. Resolver404
  → continue (the client caps the chain). `no-store` on results.

**Tests:** removal from a list (done, url = origin, Undo message present);
removal from the game's own page (done, url = list); Add game "Submit & Add
to library" (continue to `add_library_entry`); `login_required` (continue
to login); an off-origin `Location` passes through; a non-dialog request
untouched; toast middleware emits no `X-Events` on a dialog request; a walk
of the root urlconf (`get_resolver().reverse_dict`/pattern walk) classifies
every named route without error; CSRF: sign in from the dialog, rewrite
`csrfmiddlewaretoken` to the new cookie secret, POST a form, 302 (not 403).

## Task 3: Client reader and routes

**Files:** `ts/elements/form-dialog/answer.ts` (read a JSON answer; parse
`html` into a `<template>`; `normalizedUrl`/`sameUrl` stay),
`routes.ts` (`OpenRoute`/`SubmitRoute` from `kind`: page / done-toast /
done-close / done-reload / done-navigate / continue / error),
`rewrite.ts` unchanged, delete `swap.ts`, `events.ts` and their tests.

**Tests:** reading each kind; non-JSON → no kind; `html` starting with
`<template>`/`<script type=application/json>` keeps order; routes table
per spec incl. done url ≠ host → navigate, nested done → closeTop.

## Task 4: The element

**Files:** `ts/elements/form-dialog.ts`, `ts/toast-handoff.ts`
(drop target matching; one-minute guard only; opener key alongside),
`ts/library-conversion-status.ts` (drop `SWAPPED`).

- Fetches send `X-Form-Dialog: 1`, `Accept: application/json`.
- Open/submit per spec tables; continue chain cap 5 (open: follow the
  original link; submit: error toast).
- Present: template parse → `importModules` → `prefixIds` → `resolveUrls`
  (base `response.url`) → insert → focus.
- Reloader: one coalesced `requestReload(target)`; triggers: stale bottom
  close, `page:stale` on `document`; waits for no modal; form host (no
  `data-read-only`) shows messages in place; target == host → reload, else
  `assign`. Writes hand-off + opener key first. After load (connect):
  read opener key, focus id → href → `focusReturnTarget` → main.
- CSRF: on each answer and before each submit, if the cookie changed,
  rewrite every `input[name=csrfmiddlewaretoken]` in the document.
- Toast action interception removed (native until #1507).
- Keep: modal stack, nested close, leads-back links, fragment links native,
  submit veto, `formRequest`/`buildRequest`, unconfirmed/refused toasts,
  deadlines on open.

**Tests:** rewrite `form-dialog.test.ts` around JSON answers: every open
and submit row; reload coalescing (stale close + `page:stale` → one
reload); covered by another modal waits; form host no reload and messages
shown; done elsewhere navigates; opener focus after a simulated reload
(connect with stored key); CSRF rewrite; continue cap; second click native;
toast actions not intercepted.

## Task 5: e2e

**File:** `e2e/test_form_dialog_e2e.py`. Flip `_not_reloaded` checks to
"reloaded, toast shown, focus on the row menu toggle"; Undo toast after
removal appears after the reload; Add to library (done from list) reloads
the list with the toast instead of navigating; keep invalid, refusal,
nested Escape, bare removal, picker, masked field, add-game continue;
add: removal from the game's own page lands on the list; sign-in expiry
(log out in another context, submit, log in in the dialog, save works).

## Task 6: Docs sweep, gate, PR

Delete this plan; spec timeless 200–500 words; trim comments; CLAUDE.md
bullet (dialog mode, middleware, reload); full `make check` on the user's
word; update PR #1506 body.

## Gotchas

- `render_page` callers passing `scripts=` as a string or `Fragment`: only
  `game.py` (two sites); `mypy` catches the rest.
- `toast_payloads` marks the queue used; call it once per answer.
- Fake timers: deadlines use `window.setTimeout` (`deadlineAfter`).
- `#main-container` keeps `tabindex="-1"` for the focus fallback.
