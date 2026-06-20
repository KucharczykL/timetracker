# Design: Issue #53 — Rebuild `_session_row_fragment` via a shared row builder

**Date:** 2026-06-20
**Issue:** [#53](https://github.com/KucharczykL/timetracker/issues/53)
**Follow-on:** [#55](https://github.com/KucharczykL/timetracker/issues/55) (standardize all session tables on the canonical builder)

## Problem

`_session_row_fragment()` in `games/views/session.py` renders a **4-column** session
`<tr>` (Name, Start, End, Duration) with a hand-built `Tr`, no `id="session-row-{pk}"`.
The live `list_sessions` table is **6 columns** (Name, Date, Duration, Device, Created,
Actions) with a row id and htmx attributes. The fragment cannot be htmx-swapped into the
live table without producing a malformed, un-targetable row.

In practice the fragment is **dead**: every session action button in the UI is a plain
`href` (full-page navigation). The only htmx caller, `reset_session_start`, returns
`204 + HX-Refresh` (the #33 workaround) rather than the fragment. The fragment's htmx
paths in `end_session` and `new_session_from_existing_session` are never exercised, which
is why the drift went unnoticed.

Root cause: the fragment is an independent re-implementation of a session row. Fixed
properly, there must be exactly one source of truth for a session row, reused by both
the table and any htmx fragment.

## Goal

1. One canonical session-row builder shared by `list_sessions` and the htmx fragment — no
   duplicated `<tr>` markup, so the two cannot drift.
2. Real in-place htmx row swap for **finish** and **reset-start** actions on the session
   list, with the navbar playtime totals kept correct in the same request via an
   out-of-band (OOB) swap.

Non-goals (tracked in #55): migrating the game-detail sessions table (4-column, different
shape) onto the canonical builder. It keeps its current full-navigation buttons for now.

## Architecture

### Single source of truth for a session row

`TableRow` (`common/components/primitives.py:894`) is the only place a `<tr>` is built.
The table reaches it through `list_sessions → row dict → paginated_table_content →
SimpleTable → TableRow(data=dict)`. The fix splits the row into two reused units:

- **`session_row_data(session, device_list, csrf_token) -> SessionRowData`** — owns cell
  content, `row_id`, and the row's htmx attributes (the dict currently inlined in
  `list_sessions`). New function in `games/views/session.py`.
- **`TableRow`** — owns the `<tr>` markup. Unchanged, already shared.

Both consumers go through the same dict builder and the same renderer:

```python
# list_sessions
rows = [session_row_data(s, device_list, csrf_token) for s in sessions]
# → paginated_table_content → SimpleTable → TableRow(data=dict)

# _session_row_fragment
def _session_row_fragment(session, device_list, csrf_token) -> SafeText:
    return str(TableRow(session_row_data(session, device_list, csrf_token)))
```

The fragment is therefore the *same* row the table renders, for a single session. Change
a column once in `session_row_data` and list + fragment move together. The old hand-built
`Tr` (4-column, the `#last-session-start` toggle, the yellow "Finish now?" link) is
deleted entirely.

`session_row_data` reproduces today's `list_sessions` dict exactly:

- `row_id`: `f"session-row-{session.pk}"`
- `hx_trigger`: `"device-changed from:body"`, `hx_get`: `""`, `hx_select`:
  `f"#session-row-{session.pk}"`, `hx_swap`: `"outerHTML"` (the existing self-refresh on
  device change)
- `cell_data` (6): `NameWithIcon(session=session)`; start–end string via `local_strftime`;
  `session.duration_formatted_with_mark()`; `SessionDeviceSelector(session, device_list,
  csrf_token)`; `session.created_at.strftime(dateformat)`; the `ButtonGroup` of actions.

The action `ButtonGroup` for a running session (`timestamp_end is None`) switches the
**Finish** and **Reset start** buttons from plain `href` to htmx (see below). `ButtonGroup`
already forwards `hx_get`/`hx_target`/`hx_swap`/`hx_confirm` (`primitives.py:367`).

### Named type

```python
class SessionRowData(TypedDict):
    row_id: str
    hx_trigger: str
    hx_get: str
    hx_select: str
    hx_swap: str
    cell_data: list[Node]
```

Defined in `games/views/session.py` (per the project convention to name compound types
passed between functions).

### Navbar playtime as an OOB-swappable component

The navbar's "Today · Last 7 days" totals live inline in the monolithic `Navbar()`
`Safe` f-string (`common/layout.py:228-231`). Finishing or resetting a session changes a
session's duration → game playtime → these totals, so an in-place row swap would leave
them stale.

Extract the `<li>` into a small component with a stable id:

```python
# common/layout.py (or common/components)
def NavbarPlaytime(today_played: str, last_7_played: str, *, oob: bool = False) -> Node:
    # <li id="navbar-playtime" [hx-swap-oob="true"]> ...today · last_7... </li>
```

- `Navbar()` embeds `NavbarPlaytime(today_played, last_7_played)` in place of the inline
  markup (no visual change).
- htmx endpoints render `NavbarPlaytime(..., oob=True)`, which adds `hx-swap-oob="true"`,
  and append it to their response body. htmx applies it to the matching `#navbar-playtime`
  regardless of the primary target.

Totals come from the existing `model_counts(request)` (`games/views/general.py:26`), which
already computes `today_played` / `last_7_played`. The endpoints call it after saving.

### Endpoint behavior

All three endpoints keep their non-htmx branch (`redirect("games:list_sessions")`).

| Endpoint | htmx response |
|---|---|
| `end_session` | `TableRow(session_row_data(...))` **+** `NavbarPlaytime(..., oob=True)` |
| `reset_session_start` | `TableRow(session_row_data(...))` **+** `NavbarPlaytime(..., oob=True)` |
| `new_session_from_existing_session` (clone) | `204 + HX-Refresh: true` |

- **end / reset** return the fresh row plus the OOB navbar fragment in one response body.
  The triggering button targets `#session-row-{pk}` with `hx-swap="outerHTML"`; htmx
  extracts the OOB `<li>` and swaps the remainder (the `<tr>`) into the row.
  `reset_session_start` drops its current `204 + HX-Refresh` workaround.
- **clone stays on `HX-Refresh`**: it creates a *new* session whose correct position
  depends on sort + pagination, which a single-row `outerHTML` swap cannot place. Its htmx
  branch returns `204 + HX-Refresh: true` (replacing the dead fragment return). This is a
  deliberate, documented exception.

Both `end_session` and `reset_session_start` need `device_list` and a CSRF token to build
the row (for the `SessionDeviceSelector` cell): `Device.objects.order_by("name")` and
`get_token(request)`, mirroring `list_sessions`.

### List buttons → htmx

In `session_row_data`, for a running session:

- **Finish session now**: add `hx_get` = `list_sessions_end_session` URL,
  `hx_target` = `f"#session-row-{session.pk}"`, `hx_swap` = `"outerHTML"`. Keep `href` as
  a no-JS fallback.
- **Reset start to now**: same `hx_target`/`hx_swap`; keep existing `hx_confirm` and
  `href` fallback. (Previously its `hx_get` hit the 204+refresh path; now it swaps the
  row.)

Edit, Delete, and the clone/"play" affordances are unchanged.

## Components / files touched

- `games/views/session.py` — add `SessionRowData`, `session_row_data()`; rewrite
  `_session_row_fragment()` to delegate; update `list_sessions` to use the builder; rewire
  `end_session`, `reset_session_start`, `new_session_from_existing_session`.
- `common/layout.py` — add `NavbarPlaytime`; use it inside `Navbar()`.
- (If `NavbarPlaytime` is placed in `common/components`, re-export via `__init__.py`.)

## Data flow (finish from the list)

```
click Finish → hx-get end_session (htmx)
  → session.timestamp_end = now; save()
  → model_counts(request)  (fresh totals)
  → response body: <tr id=session-row-pk …>(6 cells)</tr>
                 + <li id=navbar-playtime hx-swap-oob=true>…</li>
htmx: OOB <li> → #navbar-playtime ; <tr> → #session-row-pk (outerHTML)
  → row shows end time + duration; navbar totals update; no full reload
  → swapped row keeps device-change self-refresh + device selector custom element
```

## Error handling

- Missing session → `get_object_or_404` (unchanged).
- Non-htmx requests → full-page redirect (unchanged), so the feature degrades to the
  current behavior without JS.
- `SessionDeviceSelector` custom element re-initializes on swap via its native
  `connectedCallback`; its JS module is already loaded by the list page, so no extra
  `scripts=` wiring is needed.

## Testing

Unit (`tests/`):
- `session_row_data` returns 6 `cell_data` entries and `row_id == "session-row-{pk}"`,
  with the device/created/actions cells present.
- `_session_row_fragment` output contains `id="session-row-{pk}"` and 6 `<td>/<th>` cells
  (regression against the 4-column drift).
- `NavbarPlaytime(oob=True)` emits `id="navbar-playtime"` and `hx-swap-oob="true"`;
  `oob=False` omits the OOB attribute.

View (`tests/`, htmx requests via `HTTP_HX_REQUEST=true`):
- `end_session` (htmx) response body contains `#session-row-{pk}` and an OOB
  `#navbar-playtime`; sets `timestamp_end`.
- `reset_session_start` (htmx) likewise; sets `timestamp_start` to ~now; **no**
  `HX-Refresh` header.
- `new_session_from_existing_session` (htmx) returns status 204 with `HX-Refresh: true`
  and creates a session.
- Non-htmx variants of all three still redirect to the session list.

E2E (`e2e/`):
- From the session list, finish a running session → its row updates in place (end time +
  duration) and the navbar "Today · Last 7 days" totals change, with no full page reload.

## Out of scope (→ #55)

`games/views/game.py` `_sessions_section` (4-column game-detail table, different first
column, no Device/Created) keeps its full-navigation `href` buttons. Migrating it onto
`session_row_data` with configurable visible columns is tracked in #55.
