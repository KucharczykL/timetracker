# Undo a removal

Issue [#695](https://github.com/KucharczykL/timetracker/issues/695). The
code is in `common/notices.py`, `games/views/removal.py`,
`ts/elements/toast-stack.ts` and one restore route a removed record.

## The affordance

Every removal a screen offers answers with a toast that names the act and
offers Undo. Undo puts the record back and returns the person to the page the
toast was on. The removal itself does not change: it confirms first, stamps
`removed_at` or states it through a command, and redirects to its origin.

The window is the toast's lifetime, ten seconds, paused while the pointer or
the focus is on it. The server holds no window. A restore route works until
[#795](https://github.com/KucharczykL/timetracker/issues/795) gives a removed
record a page of its own, and that page can post to these same routes.

Seven records have Undo: Session, Playthrough, Game, Purchase, Platform,
Device and FilterPreset. Edition and Release have no remove route: the
catalog form states their mark and takes it back. The API's `DELETE
/api/playthrough/{id}` is no screen and gets no toast.

## The payload

`common/notices.py` names what a toast carries: `ToastPayload` is `message`,
`type` and an optional `action` of `label` and `url`; `Undo(url)` builds the
one action. `notify(request, sentence, *, level, action=None)` queues one
Django message; the action rides `extra_tags` as JSON, a slot nothing else
sets. `toast_payloads(request)` reads the queue back. The type comes from
`level_tag`, never from `tags`, which joins `extra_tags` onto the level word.
An empty `extra_tags` is no action; any other value that is not this module's
JSON raises. Both carriers call `toast_payloads`: the `django-messages`
script in `common/layout.py` for a page reached by redirect, and the messages
middleware's `HX-Trigger` for a fetch answer, which carries the last message
only ([#1093](https://github.com/KucharczykL/timetracker/issues/1093)).

## The toast

`<toast-stack>` appends `?origin=` to the action's URL in `addToast`, from
`location.pathname` and `location.search`: the page the toast is on is the
page the restore returns to, so no server guesses where a removal landed. The
route validates the origin against `READ_ONLY` like every mutating route.

The element draws a real `<form method="post">` around an Undo submit button
wearing the ghost `ControlButton` class its `action-class` prop states, and
fills `csrfmiddlewaretoken` from `getCsrfToken()`; the cookie is on every
page, because the layout calls `get_token(request)` for each document. The
button stops the click, so the toast's dismiss-on-click does not take it.
The timer is ten seconds with an action; the store keeps hovered and focused
flags a toast and runs the timer only while both are clear. The toast keeps
`role="status"`, so the announcement names the button too. Nothing moves the
focus on load
([#1094](https://github.com/KucharczykL/timetracker/issues/1094)).

## The routes

Seven routes, `<entity>/<id>/restore`, named `restore_<entity>`, each
`ORIGIN_AWARE`, `login_required` then `require_POST`: an anonymous GET
redirects to the login page, a signed-in GET answers 405. The undo is the
confirmation, so no route draws one.

`restore_and_return(request, *, action, restored, fallback, fallback_args)`
in `games/views/removal.py` runs the action, queues the `restored` sentence
as a success or a `CommandFailed`'s sentence as an error, the defect status
included, and redirects to the origin. The row is resolved through the plain
manager scoped on the library, with no `alive()`: the row is removed. A row
of another library answers 404. A row that is not removed is not an error:
the command answers `Unchanged` and `restore()` writes what the row holds, so
a second press reads "restored" again.

| Record | Removal | Restore |
|---|---|---|
| Session | `RemoveSession` | `restore_session` → `RestoreSession` |
| Playthrough | `RemovePlaythrough` | `restore_run` → `RestorePlaythrough` |
| Game | `RemovePlayerGame`, then `remove(game)` | `restore(game)`, then `retrack_game` → `RestorePlayerGame` |
| Purchase, Platform, Device, FilterPreset | `remove(row)` | `restore(row)` |

`retrack_game` swallows `PlayerGameNotTracked` as `untrack_game` does: a game
the library never tracked was removed by its stamp alone. `RestoreSession`
refuses under a removed run or a removed game, `RestorePlaythrough` under a
removed game; the sentence is an error toast on the page the person stands
on.

A game's restore clears the stamp first and states the command second, the
removal's order reversed, so a failure between the two leaves the removal's
own halfway: a live catalog row nothing tracks, which the game list hides
and the edit form shows, and saving the form tracks it again. No transaction
spans the two; a second press completes either half. `restore(game)` runs
`_AFTER_STAMP`: the external references the removal took come back, those no
other row claimed since, the wikidata column mirrors, the purchases recount.
A restored purchase whose only game is removed stays out of the purchase
list; the game's own Undo brings both back.

## The removal views

`confirm_and_apply` takes `removed`, `undo` and `undo_args`, both sentence
and route or neither, and queues the notice after the action succeeds and
before the redirect; a refused removal queues nothing. `confirm_and_remove`
passes them through with the row's key; `remove_session` and
`remove_playthrough` pass their own. The preset picker removes through
`DELETE /api/presets/{id}`, which answers 200 with `restore_url`; `presets.ts`
calls `window.toast` with that action, and the form posts to the page route
like every other Undo.

## Verification

- `tests/test_notices.py`: round trip, levels, the foreign slot value, the
  page carrier.
- `tests/test_restore_routes.py`: six routes parametrised over POST, GET 405,
  another library's row, the second press, the fallback; the session under a
  removed run; the game's two marks and the halfway completed on the second
  press.
- `tests/test_removal_confirmation.py`: every remove view queues the notice
  with its restore URL; a refused removal queues nothing.
- vitest: the Undo form, the origin, the ten seconds, the two flags.
- `e2e/test_undo_removal_e2e.py`: remove a session from the list, press
  Undo, the row is back.
