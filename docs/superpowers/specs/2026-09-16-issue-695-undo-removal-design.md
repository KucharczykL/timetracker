# Undo a removal

Issue [#695](https://github.com/KucharczykL/timetracker/issues/695). The
code is in `common/notices.py`, `common/layout.py`, `games/htmx_middleware.py`,
`games/views/removal.py`, `ts/toast.ts` and one restore route per removed
record.

## The affordance

Every removal a screen offers answers with a toast that names the act and
offers Undo. Undo puts the record back and returns the person to the page the
toast was on. Nothing else changes: the removal still confirms first, still
stamps `removed_at` or states it through a command, and still redirects to
its origin.

The window is the toast's lifetime, ten seconds, paused while the pointer or
the focus is on it. The server holds no window. A restore route works until
[#795](https://github.com/KucharczykL/timetracker/issues/795) gives a removed
record a page of its own, and that page may post to these same routes.

Seven records have a remove route or a remove call: Session, Playthrough,
Game, Purchase, Platform, Device and FilterPreset. Each gets Undo. Edition and
Release have no remove route: the catalog form states their mark, and the same
form takes it back. The API's `DELETE /api/playthrough/{id}` is no screen and
gets no toast.

## The payload

`common/notices.py` names what a toast carries.

```text
ToastAction  = {label: str, url: str}
ToastPayload = {message: str, type: ToastType, action?: ToastAction}
```

`ToastType` is one of `success`, `error`, `info`, `warning`, `debug`, the
words `ts/toast.ts` already admits. `Undo(url)` builds the one action this
issue ships, labelled `Undo`.

`notify(request, sentence, *, level, action=None)` queues one Django message.
The sentence is the message. The action, when there is one, rides
`extra_tags` as JSON. Nothing else in the repo sets `extra_tags`, so the slot
is this module's alone. `toast_payloads(request)` reads the queue back and
answers a list of `ToastPayload`. The type comes from `level_tag`, never from
`tags`: `tags` joins `extra_tags` onto the level word, and reading it as the
type would break the first time an action is set. An empty `extra_tags`, the
default of `add_message`, is no action. A non-empty value that is not this
module's JSON raises: nothing else owns the slot, so such a value is a defect.

Both carriers call `toast_payloads`. `common/layout.py` writes the list into
the `django-messages` script for a page reached by redirect. The messages
middleware writes the last one into `HX-Trigger` for a fetch or htmx answer.
Neither builds a payload itself.

## The origin

The toast store appends `?origin=` to the action's URL in `addToast`, from
`location.pathname` and `location.search`, so the stored toast holds the
final URL and a unit test reads it. The page the toast is on is the page the
restore returns to, by definition, so no server guesses where a removal
landed. A toast a fetch delivered, the preset picker's, gets its origin the
same way. The route still validates the origin against `READ_ONLY`, as every
mutating route does.

## The form

The toast draws a real `<form method="post">` around an Undo submit button,
styled as a ghost `ControlButton`. The store fills the form's
`csrfmiddlewaretoken` from `getCsrfToken()` in `ts/csrf.ts`: the cookie is
on every page, because `common/layout.py` already calls `get_token(request)`
for each document. The form's markup joins the Alpine template in
`_TOAST_CONTAINER`, a raw HTML string that predates the component rule and
stays one. The button stops the click, as the close button does, so the
toast's dismiss-on-click does not take it. Escape still dismisses.

The timer is ten seconds when the payload carries an action and unchanged
otherwise. The store keeps two flags a toast, hovered and focused, set on
`mouseenter` and `focusin`, cleared on `mouseleave` and `focusout`; the timer
pauses while either is set and resumes when both are clear, so leaving with
the pointer while the focus is inside does not restart it. The toast keeps
`role="status"` and `aria-live="polite"`; its text reads the sentence and the
button, so the announcement names the affordance. Nothing moves the focus on
load.

## The routes

Seven routes, one a record: `session/<id>/restore`,
`playthrough/<id>/restore`, `game/<id>/restore`, `purchase/<id>/restore`,
`platform/<id>/restore`, `device/<id>/restore`, `preset/<id>/restore`. Each is
`ORIGIN_AWARE` and POST only; GET answers 405. The undo is the confirmation,
so no route draws one.

`restore_and_return(request, *, action, restored, fallback, fallback_args)`
in `games/views/removal.py` is the flow. It runs the action; on success it
queues the `restored` sentence as a success and redirects to the origin. A
`CommandFailed` queues its sentence as an error and redirects the same way,
the defect status included: `answered()` has already turned an unreadable
row or a database refusal into a sentence, and an error toast on the page
the person stands on is the answer that fits. Anything else rises.

Each route is `login_required` and then `require_POST`, the order
`games/views/playthrough_acts.py` already uses, so an anonymous GET redirects
to the login page and a signed-in GET answers 405.

The row is resolved through the plain manager, scoped on the library, with
no `alive()`: the row is removed, so `for_library()` cannot see it. A row of
another library answers 404. A row that is not removed is not an error: the
command answers `Unchanged` and `restore()` writes what the row holds, so a
second press reads "restored" again.

## Each record

| Record | Removal | Restore |
|---|---|---|
| Session | `RemoveSession` | `RestoreSession` |
| Playthrough | `RemovePlaythrough` | `RestorePlaythrough` |
| Game | `RemovePlayerGame`, then `remove(game)` | `restore(game)`, then `RestorePlayerGame` |
| Purchase, Platform, Device, FilterPreset | `remove(row)` | `restore(row)` |

Three write wrappers are new, one a command, each under `answered()` beside
the remove wrapper it mirrors: `restore_session` in
`games/writes/playersession.py`, `restore_run` in `games/writes/playthrough.py`
and `retrack_game` in `games/writes/playergame.py`. `retrack_game` swallows
`PlayerGameNotTracked` as `untrack_game` does: a game the library never
tracked was removed by its stamp alone, and the stamp is its restore.

`RestoreSession` refuses under a removed run or a removed game, and
`RestorePlaythrough` under a removed game. The person reads the sentence as
an error toast on the page they were on.

A game's restore clears the stamp first and states the command second: the
removal's order reversed, so a failure between the two leaves the state the
removal's own halfway leaves. That state is a live catalog row nothing tracks,
which the game list hides and the edit form shows; saving the form tracks the
game again. The other order would leave a tracked game every list hides, with
no screen to reach it until #795. No transaction spans the two: dispatch opens
its own and refuses to nest. A second press completes either half: `restore()`
writes what the row holds and the command answers `Unchanged`. `restore(game)`
runs `_AFTER_STAMP`: the external references the removal took come back, those
no other row claimed since, the wikidata column mirrors, and the purchases
recount.

A restored purchase whose only game was removed meanwhile stays out of the
purchase list, which reads the game's mark as well; the toast still says
restored. The game's own Undo brings both back.

## The removal views

`confirm_and_apply` takes `removed` and `undo`: the sentence and the restore
route name. After the action succeeds and before the redirect, it queues
`notify(request, removed, level=SUCCESS, action=Undo(reverse(undo, ...)))`. A
refused removal queues nothing and draws its refusal as today.
`confirm_and_remove` passes both through; `remove_session` and
`remove_playthrough` call `confirm_and_apply` themselves and pass their own.
Both default to `None`, because `finish_session` and `reset_session` share
the flow and remove nothing. Every remove view states its sentence: "Session removed.", "Playthrough removed.", "*Name* removed from
your library." for a game, platform or device, "Purchase removed.".

The preset picker removes through `DELETE /api/presets/{id}`. That endpoint
answers 200 with `{"restore_url": ...}` instead of 204, and `presets.ts` calls
`window.toast("Preset removed.", "success", {action})` with it. The toast's
form posts to the page route like every other Undo and lands back on the list,
where the picker fetches its options again.

## What does not change

`remove()` and `restore()` in `games/removal.py`. The three restore commands.
The confirmation page. `HTMXMessagesMiddleware` still sends one message, the
last; the limit predates this issue and is filed apart. After this change no
removal reaches the middleware's `HX-Trigger`: the preset picker calls
`window.toast` itself, and every other removal redirects. The middleware test
is that path's only coverage.

## Verification

- `tests/test_notices.py`: a payload with an action round-trips through the
  queue; one without decodes as before; each level maps to its type.
- The middleware test and the rendered-page test each read an action out of
  their carrier.
- One test module a route: POST puts the row back alive and redirects to the
  origin; GET answers 405; another library's row answers 404; a second POST
  redirects with "restored"; the session route under a removed run lands an
  error message on the origin. The game route: a failure after the command
  and before the stamp, then a second press, ends with both cleared.
- Every remove view queues the notice with its restore URL on success, and
  nothing on a refusal.
- The preset endpoint answers 200 with a restore URL the route resolves;
  `tests/test_filter_presets.py` and `ts/elements/presets.test.ts` stop
  asserting 204.
- `tests/test_view_authentication.py` walks every route with GET: its `world`
  fixture gains a `preset_id`, and the seven routes answer the login redirect.
- vitest: the duration with an action is ten seconds; `addToast` stores the
  action URL with the origin appended; the timer resumes only when hovered
  and focused are both clear.
- One e2e: remove a session from the list, read the toast, press Undo, wait
  on the server-rendered row, then read "Session restored.".
- `make check`.

## Filed apart

- The messages middleware sends only the last message.
- The toast region sits at the end of the document, so the keyboard reaches
  Undo last.
