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
import { formatSessionTimeRange } from "./date-time-presentation.js";

interface SessionOut {
  id: number;
  timestamp_start: string; // ISO-8601 UTC (…Z)
  timestamp_end: string | null;
  duration_manual_seconds: number;
  is_manual: boolean;
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
): string | null {
  try {
    const startMilliseconds = Temporal.Instant.from(startISO).epochMilliseconds;
    const calculatedSeconds = endISO === null
      ? 0
      : Math.max(
          0,
          (Temporal.Instant.from(endISO).epochMilliseconds - startMilliseconds) / 1000,
        );
    const totalHours = (calculatedSeconds + durationManualSeconds) / 3600;
    return `${totalHours.toFixed(1)}${isManual ? "*" : ""}`;
  } catch {
    return null;
  }
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

  const formattedTimeRange = formatSessionTimeRange(
    session.timestamp_start,
    session.timestamp_end,
  );
  const timeRangeCell = cells[1];
  if (timeRangeCell && formattedTimeRange !== null) {
    timeRangeCell.textContent = formattedTimeRange;
  }

  const formattedDuration = formatDurationWithMark(
    session.timestamp_start,
    session.timestamp_end,
    session.duration_manual_seconds,
    session.is_manual,
  );
  const durationCell = cells[2];
  if (durationCell && formattedDuration !== null) {
    durationCell.textContent = formattedDuration;
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

export { renderSessionRow, formatDurationWithMark };
