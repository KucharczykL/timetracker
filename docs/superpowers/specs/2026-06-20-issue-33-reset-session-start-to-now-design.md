# Reset running session start to now (issue #33)

## Problem

Sometimes a session is started but a sizeable amount of time passes before play
actually begins. The current UX to fix this is: edit the session, press "Set to
now", submit. This is three steps across two pages.

## Goal

Add a one-click button in the session list — next to the existing "Finish
session now", "Edit", and "Delete" buttons — that sets a running session's
`timestamp_start` to the current time. A confirmation dialog protects against
accidental clicks (the original start time is overwritten).

## Scope

- **Visibility:** the button shows only on running sessions (`timestamp_end is
  None`), exactly like the green "Finish session now" button.
- **Appearance:** gray button, new "reset" icon.
- **Behavior:** confirm dialog before resetting; on confirm, sets
  `timestamp_start = timezone.now()`, saves, and refreshes the list via htmx so
  the new start time shows.

Out of scope: changing the existing Finish/Edit/Delete buttons; resetting end
time; bulk operations.

## Design

### 1. New icon — `games/templates/icons/reset.html`

A rotate/counterclockwise-arrow SVG signifying "reset". Styled like sibling
icons (`text-black dark:text-white w-4 h-4`). Icons are auto-loaded by file stem
(`common/icons.py`), so `Icon("reset")` resolves once the file exists — no
registration needed.

### 2. New view — `games/views/session.py`

Mirrors the existing `end_session` view, but the htmx path returns an empty
`204` with an `HX-Refresh: true` header instead of a row fragment:

```python
@login_required
def reset_session_start(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(Session, id=session_id)
    session.timestamp_start = timezone.now()
    session.save()
    if request.htmx:
        response = HttpResponse(status=204)
        response["HX-Refresh"] = "true"
        return response
    return redirect("games:list_sessions")
```

**Why `HX-Refresh` and not a row swap:** `_session_row_fragment` (used by
`end_session`) renders a legacy 4-column `<tr>` that no longer matches the live
session-list table (6 columns, built inline by `list_sessions`) and carries no
`id="session-row-{pk}"`. Swapping it into the current table would produce a
malformed row. The list table is rebuilt server-side on every request, so a full
htmx refresh is the simplest correct update — and consistent with the existing
Finish button, which also does a full-page navigation.

### 3. New URL — `games/urls.py`

```python
path(
    "session/start/reset-to-now/from-list/<int:session_id>",
    session.reset_session_start,
    name="list_sessions_reset_session_start",
),
```

### 4. Extend `ButtonGroup` — `common/components/primitives.py`

The button-group button dict currently supports `href`, `slot`, `color`,
`title`, `hx_get`, `hx_target`. Add two optional keys threaded through both
`ButtonGroup()` and `_button_group_button()`:

- `hx_confirm` — emitted as `hx-confirm` on the `<a>`; htmx shows a native
  `confirm()` dialog before issuing the request.
- `hx_swap` — emitted as `hx-swap` on the `<a>`; needed so the returned row
  fragment replaces the row (`outerHTML`) rather than htmx's default.

Both are additive and optional; existing callers are unaffected. Update the
`ButtonGroup` docstring to list the new keys.

### 5. Button in the session list — `games/views/session.py`

Added to the `ButtonGroup` list in `list_sessions`, guarded the same way as the
Finish button:

```python
{
    "href": reverse(
        "games:list_sessions_reset_session_start", args=[session.pk]
    ),
    "hx_get": reverse(
        "games:list_sessions_reset_session_start", args=[session.pk]
    ),
    "hx_confirm": "Reset this session's start time to now?",
    "slot": Icon("reset"),
    "title": "Reset start to now",
    "color": "gray",
}
if session.timestamp_end is None
else {}
```

Placement: directly after the Finish button, before Edit. `href` is a graceful
fallback (the non-htmx view path redirects); `hx_get` + `hx_confirm` drive the
confirm dialog and htmx refresh when JS is active.

## Rationale: htmx confirm

The confirm dialog comes from htmx's built-in `hx-confirm`, which only fires on
htmx-driven requests — so the button must use `hx-get` (not just `href`). No
inline JS is needed, consistent with the project's conventions.

## Testing

### Unit (`tests/`)

- `reset_session_start` sets `timestamp_start` to ~now and saves.
- Returns the row fragment when called via htmx; redirects to `list_sessions`
  otherwise.
- Session list renders the reset button only for running sessions
  (`timestamp_end is None`), not for finished ones.

### E2E (`e2e/`)

- On the session list with a running session, click the reset button, accept the
  confirm dialog (`page.on("dialog", lambda d: d.accept())`), and assert the
  row's displayed start time updated to ~now.

## No TypeScript build

`hx-confirm` is built into htmx; no new custom element or `.ts` file, so `make
ts` is not required for this change.
