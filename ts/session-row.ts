// Client-side re-render of a single session table row from the API's SessionOut
// JSON. Used after a finish/reset PATCH to swap the row in place without a full
// page reload. This is the "first JSON render island" — the Python
// session_row_data() still renders the initial table; this only rebuilds a row
// after a mutation.
//
// Strategy: clone the existing <tr> and surgically replace only the cells the
// mutation changes (time range, duration, and — on finish — the actions cell),
// keeping the game/device/created cells and the row id/class byte-identical to
// the server render. This shrinks Python<->TS drift to exactly the changed cells
// and means the cloned <drop-down> device selector re-wires via its own
// connectedCallback when the new row is inserted.
//
// NB: the formatters below run in the BROWSER's timezone, whereas the Python
// render uses the server timezone (TIME_ZONE, default Europe/Prague). For the
// single-user/same-machine case these match; a user in a different tz would see
// post-swap times in their own tz. Accepted for this slice — revisit if
// multi-timezone ever matters.

interface SessionOut {
  id: number;
  timestamp_start: string; // ISO-8601 UTC (…Z)
  timestamp_end: string | null;
  duration_manual_seconds: number;
  is_manual: boolean;
}

function pad2(value: number): string {
  return value.toString().padStart(2, "0");
}

/**
 * "DD/MM/YYYY HH:MM" for the start, plus " — HH:MM" when the session is
 * finished. Mirrors games.formatting.session_time_range (datetimeformat +
 * timeformat), formatted in the browser's local timezone.
 */
function formatTimeRange(startISO: string, endISO: string | null): string {
  const start = new Date(startISO);
  const startText =
    `${pad2(start.getDate())}/${pad2(start.getMonth() + 1)}/${start.getFullYear()} ` +
    `${pad2(start.getHours())}:${pad2(start.getMinutes())}`;
  if (!endISO) return startText;
  const end = new Date(endISO);
  return `${startText} — ${pad2(end.getHours())}:${pad2(end.getMinutes())}`;
}

/**
 * The "NN.N" hours string (+ "*" when manual), mirroring Session
 * .duration_formatted_with_mark() — format_duration(duration_total, "%02.1H").
 * duration_total = calculated + manual, where calculated = max(0, end - start)
 * (0 for an open session, matching the DB Coalesce). %02.1H reduces to one
 * decimal place: the "N.N" minimum already exceeds the width-2 field.
 */
function formatDurationWithMark(
  startISO: string,
  endISO: string | null,
  durationManualSeconds: number,
  isManual: boolean,
): string {
  const calculatedSeconds = endISO
    ? Math.max(0, (new Date(endISO).getTime() - new Date(startISO).getTime()) / 1000)
    : 0;
  const totalHours = (calculatedSeconds + durationManualSeconds) / 3600;
  return `${totalHours.toFixed(1)}${isManual ? "*" : ""}`;
}

/**
 * Rebuild the session row from its updated SessionOut. Clones oldRow, rewrites
 * the time-range and duration cells, and — once the session is finished —
 * strips the now-irrelevant finish/reset controls from the actions cell. Returns
 * the new <tr> for the caller to swap in via replaceWith.
 */
function renderSessionRow(session: SessionOut, oldRow: HTMLTableRowElement): HTMLTableRowElement {
  const newRow = oldRow.cloneNode(true) as HTMLTableRowElement;
  const cells = newRow.children; // [name(th), timeRange, duration, device, created, actions]

  const timeRangeCell = cells[1];
  if (timeRangeCell) {
    timeRangeCell.textContent = formatTimeRange(
      session.timestamp_start,
      session.timestamp_end,
    );
  }

  const durationCell = cells[2];
  if (durationCell) {
    durationCell.textContent = formatDurationWithMark(
      session.timestamp_start,
      session.timestamp_end,
      session.duration_manual_seconds,
      session.is_manual,
    );
  }

  // Once finished, the session is no longer open: drop the finish/reset buttons
  // and the reset-confirm modal, and flip the element's is-open flag so its
  // re-wired connectedCallback finds nothing to bind.
  if (session.timestamp_end) {
    const actions = newRow.querySelector("session-actions");
    if (actions) {
      actions.setAttribute("is-open", "false");
      // Finish/reset are bare <button> group members — remove them; the
      // reset-confirm modal is a direct child wrapper.
      actions.querySelector("[data-finish]")?.remove();
      actions.querySelector("[data-reset]")?.remove();
      actions.querySelector("[data-reset-modal]")?.remove();
    }
  }

  return newRow;
}

export { renderSessionRow, formatTimeRange, formatDurationWithMark };
