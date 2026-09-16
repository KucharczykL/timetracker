# Undo a removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every removal a screen offers answers with a toast that offers Undo, and Undo puts the record back.

**Architecture:** A typed toast payload gains an `action`, carried through Django messages' `extra_tags` and rendered by `<toast-stack>` as a POST form. Seven POST-only restore routes share one `restore_and_return` flow. Three new write wrappers call the restore commands that already exist.

**Tech Stack:** Django messages, Django Ninja, TypeScript custom element (`<toast-stack>` from member 1), vitest, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-16-issue-695-undo-removal-design.md`. Member 2 of the stack whose member 1 is `docs/superpowers/plans/2026-09-16-issue-1089-toast-stack.md`; this branch is cut from that one.

## Global Constraints

- Window: 10 000 ms when a payload carries an action; the default otherwise. Paused while hovered or focused; resumed when both clear.
- Origin travels only in `?origin=`, appended by the store in `addToast` from `location.pathname + location.search`; every route validates it through `return_url`.
- Every restore route is `@login_required` then `@require_POST`, named `restore_<entity>`, listed in `ORIGIN_AWARE`.
- A restored row is resolved through `Model.objects.filter(library=library)` with no `alive()`, through `owned_or_404`.
- Sentences: "Session removed.", "Playthrough removed.", "Purchase removed.", "Preset removed.", "*Name* removed from your library." for game, platform, device; restored the same with "restored".
- A refused restore is an error message on the origin, never a page; `RowUnreadable` and database refusals arrive as `CommandFailed` and take the same path.
- Game restore order: `restore(game)` first, then `retrack_game`; `retrack_game` swallows `PlayerGameNotTracked`.
- Tests that POST through a dispatching view carry `@pytest.mark.django_db(transaction=True)`.
- Identifiers are whole words; comments explain intent only; refused words per `docs/vocabulary.md` (`DELETE` only as the HTTP verb).
- The gate is the full `make check`.

---

## File structure

| File | Responsibility |
|---|---|
| `common/notices.py` (create) | `ToastAction`, `ToastPayload`, `Undo`, `notify`, `toast_payloads` |
| `tests/test_notices.py` (create) | round trip, levels, malformed slot |
| `common/layout.py`, `games/htmx_middleware.py` (modify) | both read `toast_payloads` |
| `common/components/toast.py` (modify) | `ToastStackProps.action_class` |
| `ts/elements/toast-stack.ts` + test (modify) | `action`, form, origin, 10 s, hovered/focused flags |
| `games/writes/playersession.py`, `games/writes/playthrough.py`, `games/writes/playergame.py` (modify) | `restore_session`, `restore_run`, `retrack_game` |
| `games/views/removal.py` (modify) | `restore_and_return`; `confirm_and_apply(removed=, undo=)` |
| `games/views/{session,playthrough,game,purchase,platform,device,preset}.py` (modify/create) | seven `restore_*` views; the remove views state their sentence |
| `games/urls.py`, `games/views/returns.py` (modify) | seven routes, classified |
| `games/api.py:1005-1017`, `ts/elements/presets.ts:89-116` (modify) | DELETE answers 200 + `restore_url`; picker toasts with an action |
| `tests/test_restore_routes.py` (create) | one parametrised module for the seven routes plus the game order case |
| `tests/test_removal_confirmation.py`, `tests/test_view_authentication.py`, `tests/test_filter_presets.py:478`, `ts/elements/presets.test.ts:72` (modify) | notices queued; `preset_id` in `world`; 200 |
| `e2e/test_undo_removal_e2e.py` (create) | the one browser case |

---

### Task 1: The payload and its two carriers

**Files:**
- Create: `common/notices.py`, `tests/test_notices.py`
- Modify: `common/layout.py:426-431` (`messages = [...]` → `toast_payloads(request)`), `games/htmx_middleware.py:42-70` (build the trigger from `toast_payloads(request)[-1]`)
- Modify: `tests/test_toast_middleware.py` (one case: a message with an action carries it in `HX-Trigger`), `tests/test_rendered_pages.py` (one case: a queued action reaches the `django-messages` script)

**Interfaces:**
- Produces, in `common/notices.py`:
  - `type ToastType = Literal["success", "error", "info", "warning", "debug"]`
  - `class ToastAction(TypedDict): label: str; url: str`
  - `class ToastPayload(TypedDict, total=False): message: str; type: ToastType; action: ToastAction` (`message` and `type` always present)
  - `def Undo(url: str) -> ToastAction`
  - `def notify(request, sentence: str, *, level: int, action: ToastAction | None = None) -> None` — `messages.add_message(request, level, sentence, extra_tags=json.dumps({"action": action}) if action else "")`
  - `def toast_payloads(request) -> list[ToastPayload]` — iterates `get_messages(request)`; `type` from `message.level_tag` (fallback `"info"` for an unknown level); `extra_tags == ""` means no action; any other value is `json.loads`-ed and must be a dict with an `action` key, else `raise ValueError("extra_tags is the notice slot: ...")`.
- `common/layout.py` keeps its `</` escaping; `games/htmx_middleware.py` keeps its 3xx and level guards and its "last message wins" behaviour.

- [ ] **Step 1: Write `tests/test_notices.py`** (uses `django.test.RequestFactory` with `FallbackStorage` as `tests/test_toast_middleware.py:24-36` does). Cases: `test_a_notice_with_an_action_round_trips` (queue with `Undo("/x")`, read one payload equal to `{"message", "type": "success", "action": {"label": "Undo", "url": "/x"}}`); `test_a_plain_message_decodes_with_no_action` (`messages.error(request, "no")` → payload has no `action` key, `type == "error"`); `test_each_level_maps_to_its_type` (parametrise DEBUG..ERROR); `test_a_foreign_extra_tags_value_raises` (`add_message(..., extra_tags="urgent")` → `ValueError`).
- [ ] **Step 2: Run** `make test ARGS="tests/test_notices.py"` — FAIL, module missing.
- [ ] **Step 3: Write `common/notices.py`.** Then point both carriers at it. In the middleware, the existing `MESSAGE_LEVEL_MAP` goes: the payload's `type` is the map now.
- [ ] **Step 4: Add the two carrier cases** named above and run `make test ARGS="tests/test_notices.py tests/test_toast_middleware.py tests/test_middleware_integration.py tests/test_rendered_pages.py"` — green.
- [ ] **Step 5: Commit** `feat: a toast payload may carry an action`.

---

### Task 2: The element renders the action

**Files:**
- Modify: `ts/elements/toast-stack.ts`, `ts/elements/toast-stack.test.ts`
- Modify: `common/components/toast.py` (`ToastStackProps` gains `action_class: str`; `ToastStack()` passes `control_button_class(variant="ghost")`), then `make gen-element-types`
- Modify: `ts/globals.d.ts:11-15` (`options` gains `action?: { label: string; url: string }`)

**Interfaces:**
- `ToastMessage` gains `action?: ToastAction` with `interface ToastAction { label: string; url: string }`; `Toast` stores `action: ToastAction | null` whose `url` already carries `?origin=` (use `URL` with `location.origin` as base, set `searchParams.set("origin", location.pathname + location.search)`, store `pathname + search`).
- `defaultDuration(type, hasAction)`: `10_000` when `hasAction`, else as today.
- `Toast` gains `hovered: boolean`, `focused: boolean`; `clearToastTimer`/`resumeToastTimer` stay the primitives; the element calls `setHovered(id, flag)` / `setFocused(id, flag)` on the store, which pause when either turns on and resume only when both are off.
- DOM: after `[data-toast-message]`, `form[data-toast-action][method="post"][action=url]` > `input[type=hidden][name=csrfmiddlewaretoken]` (value from `getCsrfToken()` in `../csrf.js`) + `button[type=submit]` with the element's `action-class` attribute as its class and the action's label as text. The button's `click` calls `stopPropagation()` and nothing else: the browser submits.

- [ ] **Step 1: Write the failing cases**: `renders an Undo form whose action carries the page as origin` (`history.replaceState({}, "", "/session/list?page=2")`, cookie `csrftoken=t`; expect `form.getAttribute("action") === "/session/x/restore?origin=%2Fsession%2Flist%3Fpage%3D2"` and the hidden input value `t` and the button text `Undo` and its class the element's `action-class`); `a toast with an action lives ten seconds`; `resumes only when neither hovered nor focused` (`mouseenter`, `focusin`, `mouseleave` → still paused after 20 s; `focusout` → dismissed after the remaining time); `clicking Undo does not dismiss the toast` (click the button with `preventDefault` on `submit`; toast still there).
- [ ] **Step 2: Run** `make test-ts` — FAIL.
- [ ] **Step 3: Implement**, regenerate props, update `globals.d.ts`.
- [ ] **Step 4: Run** `make test-ts` and `make ts-check` — green.
- [ ] **Step 5: Commit** `feat: <toast-stack> renders a toast's action as a POST form`.

---

### Task 3: Three restore wrappers

**Files:**
- Modify: `games/writes/playersession.py` (after `remove_session`), `games/writes/playthrough.py` (after `remove_run`), `games/writes/playergame.py` (after `untrack_game`)
- Modify: `tests/test_session_writes.py`, `tests/test_playthrough_writes.py`, `tests/test_playergame_write_path.py` (covers `untrack_game`)

**Interfaces:**
- `def restore_session(actor: User, session: PlayerSession, *, correlation_id: uuid.UUID) -> None` — `RestoreSession(session_id=session.pk)` under `answered("session")`.
- `def restore_run(actor: User, run: Playthrough, *, correlation_id: uuid.UUID) -> None` — `RestorePlaythrough(playthrough_id=run.pk)` under `answered("playthrough")`.
- `def retrack_game(actor: User, game: Game, *, correlation_id: uuid.UUID) -> None` — `RestorePlayerGame(game_id=game.pk)` under `answered("game")`, `except PlayerGameNotTracked: pass` with the comment `#: Never tracked: the catalog stamp was the whole removal.`

- [ ] **Step 1: Write the failing cases**, one module each: `test_restore_session_puts_a_removed_row_back` (remove through `remove_session`, restore, `removed_at is None`, the event `library.playersession.restored` recorded under the correlation id); `test_restore_session_under_a_removed_run_is_answered` (`RemovePlaythrough` the run through `remove_run` on a game with two runs, then `CommandFailed` with the sentence "That playthrough was removed from your library. Restore it before changing its sessions."); `test_restore_run_puts_a_removed_run_back`; `test_retrack_game_after_untrack`; `test_retrack_game_of_a_game_never_tracked_is_silent` (`@pytest.mark.untracked_games`).
- [ ] **Step 2: Run** the three modules — FAIL on import.
- [ ] **Step 3: Write the three functions.**
- [ ] **Step 4: Run** the three modules — green.
- [ ] **Step 5: Commit** `feat: three write wrappers restore what a removal took`.

---

### Task 4: `restore_and_return` and the seven routes

**Files:**
- Modify: `games/views/removal.py` (add `restore_and_return`)
- Modify: `games/views/session.py`, `games/views/playthrough.py`, `games/views/game.py`, `games/views/purchase.py`, `games/views/platform.py`, `games/views/device.py`; create `games/views/preset.py`
- Modify: `games/urls.py` (seven `path(...)` lines beside each `remove` route; `preset/<uuidv7:preset_id>/restore` is the first preset page route), `games/views/returns.py:40-70` (seven names in `ORIGIN_AWARE`)
- Modify: `tests/test_view_authentication.py:27-52` (`"preset_id": FilterPreset.objects.create(library=owned_library, mode="games", name="Mine").id` — check the model's required columns first)
- Create: `tests/test_restore_routes.py`

**Interfaces:**
- `def restore_and_return(request, *, action: Callable[[], object], restored: str, fallback: UrlName, fallback_args: Sequence[Any] = ()) -> HttpResponse` in `games/views/removal.py`: `try: action() except CommandFailed as refusal: messages.error(request, refusal.message) else: messages.success(request, restored)`; then `redirect(return_url(request, fallback=fallback, fallback_args=fallback_args))`.
- Seven views, each `@login_required` `@require_POST` `def restore_<entity>(request, <entity>_id: UUID) -> HttpResponse`, resolving `owned_or_404(Model.objects.filter(library=library), library, id=...)` and calling `restore_and_return` with: Session → `partial(restore_session, user, session, correlation_id=new_correlation_id())`, "Session restored.", fallback `games:list_sessions`; Playthrough → `restore_run`, fallback `games:view_game` with `[game.id, game.url_slug]`; Game → an inner `def act(): restore(game); retrack_game(user, game, correlation_id=...)`, "*Name* restored to your library.", fallback `games:list_games`; Purchase/Platform/Device/FilterPreset → `partial(restore, row)` with their fallbacks (`list_purchases`, `list_platforms`, `list_devices`, `list_games`).
- PlayerSession and Playthrough are resolved through the plain manager as well (`PlayerSession.objects.filter(library=library)`); the command re-resolves under its own lock.

- [ ] **Step 1: Write `tests/test_restore_routes.py`** with fixtures from `tests/test_removal_confirmation.py:14-30` (`logged_in`, `game`) plus `second_library`. Parametrise `(route, make_removed_row, is_alive)` over the seven records: `test_post_puts_the_row_back_and_returns_to_the_origin` (origin `?page=2` on the matching list), `test_get_answers_405`, `test_another_librarys_row_answers_404`, `test_a_second_post_still_says_restored` (read the message off the followed response). Non-parametrised: `test_a_session_under_a_removed_run_lands_an_error_on_the_origin`; `test_a_game_whose_stamp_cleared_but_command_failed_completes_on_the_second_press` (monkeypatch `retrack_game` to raise `CommandFailed("x", 409)` once, press, then press again; assert `Game.removed_at is None` and `PlayerGame.removed_at is None`). Mark the module `pytestmark = pytest.mark.django_db(transaction=True)`.
- [ ] **Step 2: Run** it — FAIL (no route).
- [ ] **Step 3: Write the helper, the seven views, the routes, the classification, the `world` entry.** Run `make test ARGS="tests/test_restore_routes.py tests/test_returns_classification.py tests/test_view_authentication.py"` — green.
- [ ] **Step 4: Commit** `feat: seven restore routes put a removed record back`.

---

### Task 5: Removals offer Undo; the preset picker too

**Files:**
- Modify: `games/views/removal.py` (`confirm_and_apply(..., removed: str | None = None, undo: UrlName | None = None)`: after `action()` succeeds and before the redirect, when both are given, `notify(request, removed, level=messages.SUCCESS, action=Undo(reverse(undo, args=[instance_pk])))` — pass the id as `undo_args: Sequence[Any] = ()` beside `undo`; `confirm_and_remove` forwards `removed`, `undo`, `undo_args=[instance.pk]`)
- Modify: the six remove views to state `removed=` and `undo=` (`remove_session` and `remove_playthrough` call `confirm_and_apply` directly and pass their own)
- Modify: `games/api.py:1005-1017` (`response={200: RemovedPresetOut}` with `class RemovedPresetOut(Schema): restore_url: str`, answering `reverse("games:restore_preset", args=[preset.id])`), `ts/elements/presets.ts:89-116` (on `response.ok`, `response.json().then(({ restore_url }) => window.toast("Preset removed.", "success", { action: { label: "Undo", url: restore_url } }))`; the browser `confirm` text says "Remove", not "Delete")
- Modify: `tests/test_removal_confirmation.py` (one parametrised case: each remove POST leaves a success message whose `extra_tags` names the restore URL; one case: a refused removal queues nothing — reuse the session-under-removed-run arrangement), `tests/test_filter_presets.py:478` (200 and the body), `ts/elements/presets.test.ts:72` (stub `Response(JSON.stringify({restore_url: "/preset/x/restore"}), {status: 200})`; assert the toast call's action)

- [ ] **Step 1: Write the failing cases** named above; run them — FAIL.
- [ ] **Step 2: Implement** the view changes, the API change, the picker change.
- [ ] **Step 3: Run** `make check-fast` — green.
- [ ] **Step 4: Commit** `feat: every removal offers Undo`.

---

### Task 6: The browser case, the sweep, the gate

**Files:**
- Create: `e2e/test_undo_removal_e2e.py` (login as `e2e/test_widgets_e2e.py:21` does; seed a game through `e2e/tracked_games.py` `create_tracked_game` and a session through `record_session` from `games/writes/playersession.py`; open `games:list_sessions`; follow the row's Remove link; confirm; `expect(page.get_by_text("Session removed.")).to_be_visible()`; click `get_by_role("button", name="Undo")`; wait on the server-rendered row (`expect(page.get_by_text(game.name)).to_be_visible()`) before reading the ORM; then `expect(page.get_by_text("Session restored.")).to_be_visible()`; assert `PlayerSession.objects.get(...).removed_at is None`)
- Modify: `CLAUDE.md` (REST API bullet for `DELETE /api/presets/{id}`; `games/views/removal.py` description gains `restore_and_return`; a "Removing offers Undo" line under the removal paragraph), `docs/event-retention.md:228` (the undo exists; the Trash screen is #795)
- Modify: issue #944's struck acceptance line is satisfied; comment on #944 and #795 pointing at the spec

- [ ] **Step 1: Write the e2e**; `make ts`; run `make test-e2e` (whole suite; `ARGS` does not scope it) — green.
- [ ] **Step 2: Sweep the docs**; `make vale`.
- [ ] **Step 3: Run the gate** `make check` from a log with its exit code — green.
- [ ] **Step 4: Commit** `docs: removing offers Undo`; `gh stack add`, `gh stack submit`; comment on #944 and #795.

---

## Follow-up issues to file

- `HTMXMessagesMiddleware` sends only the last queued message; the others are lost on a fetch answer.
- The toast region sits at the end of the document, so the keyboard reaches Undo last; a shortcut or a focus move is a design question for the Orca pass.
- Retire Alpine (filed with member 1).

## Self-review

Spec coverage: payload and carriers (Task 1), origin and form and window (Task 2), wrappers (Task 3), routes and helper and game order (Task 4), removal views and preset (Task 5), e2e and sweep and follow-ups (Task 6). Names: `notify`, `toast_payloads`, `Undo`, `ToastPayload`, `ToastAction`, `restore_and_return`, `restore_session`, `restore_run`, `retrack_game`, `restore_<entity>`, `RemovedPresetOut`, `action_class` / `action-class`, `data-toast-action` — one spelling each across tasks.
