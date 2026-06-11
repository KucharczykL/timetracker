/**
 * DateRangePicker — vanilla JavaScript implementation.
 *
 * Drives the DateRangePicker component (common/components/date_range_picker.py):
 *
 * - DateRangeField: segmented manual entry. Each date part (DD/MM/YYYY) is its
 *   own input; digits fill the placeholder from the right (YYYY → YYY1 → YY19
 *   → Y198 → 1987), full parts auto-advance to the next one, and
 *   Backspace/Delete reverts the active part to its placeholder.
 * - DateRangeCalendar: popup month grid with a preset column and a
 *   Cancel / Clear / Select footer. Picking works anchor-style: the first
 *   pick becomes the StartDate anchor, the second pick sets the EndDate and
 *   moves the anchor there so further picks adjust the StartDate. Picking on
 *   the wrong side of the anchor clears the range and restarts from the
 *   clicked date.
 *
 * The committed value lives in the two hidden ISO inputs ({prefix}-min /
 * {prefix}-max) that filter_bar.js serializes into a DateCriterion.
 *
 * NB: class strings below are emitted verbatim so the Tailwind scanner picks
 * them up — keep them as plain literals.
 */
(function () {
  "use strict";

  var WEEKDAY_LABELS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

  var WEEKDAY_CLASS =
    "w-8 h-6 flex items-center justify-center text-xs text-body select-none";
  var DAY_BASE_CLASS =
    "date-range-day w-8 h-8 flex items-center justify-center text-sm " +
    "text-heading cursor-pointer hover:bg-neutral-tertiary-medium";
  var DAY_ROUNDED_CLASS = "rounded-base";
  var DAY_OUTSIDE_MONTH_CLASS = "opacity-40";
  var DAY_SELECTED_CLASS = "bg-brand text-white hover:bg-brand-strong";
  var DAY_ANCHOR_CLASS =
    "bg-brand text-white ring-2 ring-inset ring-brand-strong hover:bg-brand-strong";
  // The three visual states of the date range track (the days between the
  // two endpoints): outlined while picking the second date, filled once both
  // are picked, muted when showing an already-committed range read-only.
  var TRACK_OUTLINED_CLASS = "border-y border-brand/70 bg-brand/10";
  var TRACK_FILLED_CLASS = "bg-brand/30";
  var TRACK_MUTED_CLASS = "bg-brand/15";

  // ── Date helpers (all local-time; values are ISO YYYY-MM-DD strings) ──

  function padNumber(value, width) {
    var text = String(value);
    while (text.length < width) text = "0" + text;
    return text;
  }

  function isoFromDate(dateObject) {
    return (
      padNumber(dateObject.getFullYear(), 4) +
      "-" +
      padNumber(dateObject.getMonth() + 1, 2) +
      "-" +
      padNumber(dateObject.getDate(), 2)
    );
  }

  function dateFromIso(isoString) {
    var pieces = isoString.split("-");
    return new Date(
      parseInt(pieces[0], 10),
      parseInt(pieces[1], 10) - 1,
      parseInt(pieces[2], 10)
    );
  }

  function addDays(dateObject, dayCount) {
    var copy = new Date(dateObject.getTime());
    copy.setDate(copy.getDate() + dayCount);
    return copy;
  }

  /** Validate a (year, month, day) triple as a real calendar date. */
  function isoFromParts(year, month, day) {
    var candidate = new Date(year, month - 1, day);
    if (
      candidate.getFullYear() !== year ||
      candidate.getMonth() !== month - 1 ||
      candidate.getDate() !== day
    ) {
      return "";
    }
    return isoFromDate(candidate);
  }

  function presetRange(presetName) {
    var today = new Date();
    today.setHours(0, 0, 0, 0);
    var yesterday = addDays(today, -1);
    var year = today.getFullYear();
    var month = today.getMonth();
    switch (presetName) {
      case "today":
        return [today, today];
      case "yesterday":
        return [yesterday, yesterday];
      case "last_7_days":
        return [addDays(today, -6), today];
      case "last_30_days":
        return [addDays(today, -29), today];
      case "this_month":
        return [new Date(year, month, 1), new Date(year, month + 1, 0)];
      case "last_month":
        return [new Date(year, month - 1, 1), new Date(year, month, 0)];
      case "this_year":
        return [new Date(year, 0, 1), new Date(year, 11, 31)];
      default:
        return null;
    }
  }

  // ── DateRangeField: segmented manual entry ──────────────────────────────

  function segmentBuffer(segment) {
    return segment.dataset.typedDigits || "";
  }

  function setSegmentBuffer(segment, buffer) {
    segment.dataset.typedDigits = buffer;
    if (buffer === "") {
      segment.value = "";
      return;
    }
    var placeholder = segment.getAttribute("placeholder");
    // Fill the placeholder from the right: typing 19 into YYYY shows YY19.
    segment.value = placeholder.slice(0, placeholder.length - buffer.length) + buffer;
  }

  function segmentsForSide(picker, side) {
    return Array.prototype.slice.call(
      picker.querySelectorAll('input[data-date-side="' + side + '"]')
    );
  }

  /** Recompute one hidden ISO input from its side's segment buffers. */
  function syncHiddenFromSegments(picker, side) {
    var hidden = picker.querySelector(
      'input[data-date-range-hidden="' + side + '"]'
    );
    var partValues = {};
    var complete = true;
    segmentsForSide(picker, side).forEach(function (segment) {
      var buffer = segmentBuffer(segment);
      if (buffer.length !== parseInt(segment.getAttribute("maxlength"), 10)) {
        complete = false;
      }
      partValues[segment.dataset.datePart] = buffer;
    });
    var previousValue = hidden.value;
    if (complete) {
      hidden.value = isoFromParts(
        parseInt(partValues.year, 10),
        parseInt(partValues.month, 10),
        parseInt(partValues.day, 10)
      );
    } else {
      hidden.value = "";
    }
    return hidden.value !== previousValue;
  }

  /** Push an ISO value (or "") into a side's segments and hidden input. */
  function setSideValue(picker, side, isoString) {
    var hidden = picker.querySelector(
      'input[data-date-range-hidden="' + side + '"]'
    );
    hidden.value = isoString;
    var partValues = { year: "", month: "", day: "" };
    if (isoString) {
      var pieces = isoString.split("-");
      partValues = { year: pieces[0], month: pieces[1], day: pieces[2] };
    }
    segmentsForSide(picker, side).forEach(function (segment) {
      setSegmentBuffer(segment, partValues[segment.dataset.datePart]);
    });
  }

  function initField(picker, calendarState) {
    var field = picker.querySelector("[data-date-range-field]");
    var segments = Array.prototype.slice.call(
      picker.querySelectorAll("input[data-date-part]")
    );

    // Adopt server-rendered values (prefilled filter) as typed buffers.
    segments.forEach(function (segment) {
      if (segment.value) setSegmentBuffer(segment, segment.value);
    });

    // Clicking anywhere in the container that is not a date part activates
    // the first date part.
    field.addEventListener("mousedown", function (event) {
      if (event.target.closest("input[data-date-part]")) return;
      if (event.target.closest("[data-date-range-calendar-toggle]")) return;
      event.preventDefault();
      segments[0].focus();
    });

    segments.forEach(function (segment, segmentIndex) {
      segment.addEventListener("keydown", function (event) {
        if (event.key === "Tab") return; // native Tab / Shift+Tab navigation
        if (event.key === "Enter") return; // let the filter form submit
        if (event.key === "Backspace" || event.key === "Delete") {
          event.preventDefault();
          setSegmentBuffer(segment, "");
          syncHiddenFromSegments(picker, segment.dataset.dateSide);
          return;
        }
        if (event.ctrlKey || event.metaKey || event.altKey) return;
        event.preventDefault();
        if (!/^[0-9]$/.test(event.key)) return; // only numbers can be typed
        var maximumLength = parseInt(segment.getAttribute("maxlength"), 10);
        var buffer = segmentBuffer(segment);
        // Typing into an already-full part starts it over.
        buffer = buffer.length >= maximumLength ? event.key : buffer + event.key;
        setSegmentBuffer(segment, buffer);
        syncHiddenFromSegments(picker, segment.dataset.dateSide);
        if (buffer.length === maximumLength && segmentIndex + 1 < segments.length) {
          segments[segmentIndex + 1].focus();
        }
      });
      // Swallow any input that bypassed keydown (e.g. IME/paste).
      segment.addEventListener("input", function () {
        setSegmentBuffer(segment, segmentBuffer(segment));
      });
      segment.addEventListener("focus", function () {
        if (calendarState) calendarState.refreshFromField();
      });
    });
  }

  // ── DateRangeCalendar: popup month grid ────────────────────────────────

  function createCalendarState(picker) {
    var popup = picker.querySelector("[data-date-range-calendar]");
    var grid = popup.querySelector("[data-date-range-grid]");
    var monthLabel = popup.querySelector("[data-date-range-month-label]");

    var today = new Date();
    var state = {
      open: false,
      viewYear: today.getFullYear(),
      viewMonth: today.getMonth(),
      startIso: "",
      endIso: "",
      // The anchor is the fixed endpoint: "start" while picking the EndDate,
      // "end" once the range is complete (further picks move the StartDate).
      anchor: "",
      hoverIso: "",
      // True while showing a committed range the user has not edited yet —
      // the track renders muted until the first pick.
      readOnly: false,
    };

    function hiddenValue(side) {
      return picker.querySelector(
        'input[data-date-range-hidden="' + side + '"]'
      ).value;
    }

    state.refreshFromField = function () {
      if (state.open) return;
      state.startIso = hiddenValue("min");
      state.endIso = hiddenValue("max");
    };

    function syncSelectionToField() {
      setSideValue(picker, "min", state.startIso);
      setSideValue(picker, "max", state.endIso);
    }

    function openPopup() {
      state.startIso = hiddenValue("min");
      state.endIso = hiddenValue("max");
      state.anchor = state.startIso && state.endIso ? "end" : state.startIso ? "start" : "";
      state.readOnly = Boolean(state.startIso && state.endIso);
      state.hoverIso = "";
      var focusDate = state.startIso ? dateFromIso(state.startIso) : new Date();
      state.viewYear = focusDate.getFullYear();
      state.viewMonth = focusDate.getMonth();
      state.open = true;
      popup.classList.remove("hidden");
      render();
    }

    function closePopup() {
      state.open = false;
      state.hoverIso = "";
      popup.classList.add("hidden");
    }

    function clearSelection() {
      state.startIso = "";
      state.endIso = "";
      state.anchor = "";
      state.hoverIso = "";
      state.readOnly = false;
      syncSelectionToField();
    }

    /**
     * Anchor-style picking:
     * - no selection: the pick becomes the StartDate anchor
     * - anchor=start (picking EndDate): a pick on/after the StartDate
     *   completes the range and moves the anchor to the EndDate; a pick
     *   before it clears the range and restarts
     * - anchor=end (adjusting StartDate): a pick on/before the EndDate
     *   moves the StartDate (extend/shorten); a pick after it clears the
     *   range and restarts from the clicked date
     */
    function pickDate(isoString) {
      state.readOnly = false;
      if (!state.startIso) {
        state.startIso = isoString;
        state.anchor = "start";
      } else if (state.anchor === "start" && !state.endIso) {
        if (isoString >= state.startIso) {
          state.endIso = isoString;
          state.anchor = "end";
        } else {
          state.startIso = isoString;
          state.endIso = "";
          state.anchor = "start";
        }
      } else {
        if (isoString <= state.endIso) {
          state.startIso = isoString;
        } else {
          state.startIso = isoString;
          state.endIso = "";
          state.anchor = "start";
        }
      }
      syncSelectionToField();
      render();
    }

    function applyPreset(presetName) {
      var range = presetRange(presetName);
      if (!range) return;
      state.startIso = isoFromDate(range[0]);
      state.endIso = isoFromDate(range[1]);
      state.anchor = "end";
      state.readOnly = false;
      state.viewYear = range[0].getFullYear();
      state.viewMonth = range[0].getMonth();
      syncSelectionToField();
      render();
    }

    /** The (inclusive-exclusive of endpoints) track between the two range
     * ends; while picking the second date the hovered day acts as the
     * provisional other end. */
    function trackBounds() {
      if (state.startIso && state.endIso) {
        return [state.startIso, state.endIso, state.readOnly ? TRACK_MUTED_CLASS : TRACK_FILLED_CLASS];
      }
      if (state.startIso && state.hoverIso && state.hoverIso !== state.startIso) {
        var lower = state.hoverIso < state.startIso ? state.hoverIso : state.startIso;
        var upper = state.hoverIso < state.startIso ? state.startIso : state.hoverIso;
        return [lower, upper, TRACK_OUTLINED_CLASS];
      }
      return null;
    }

    function dayCellClass(isoString, inViewMonth) {
      var classes = [DAY_BASE_CLASS];
      var isStart = isoString === state.startIso;
      var isEnd = isoString === state.endIso;
      var isAnchor =
        (state.anchor === "start" && isStart) || (state.anchor === "end" && isEnd);
      var track = trackBounds();
      var inTrack = track && isoString > track[0] && isoString < track[1];
      if (inTrack) {
        classes.push(track[2]);
      } else {
        classes.push(DAY_ROUNDED_CLASS);
      }
      if (isAnchor && !state.readOnly) {
        classes.push(DAY_ANCHOR_CLASS);
      } else if (isStart || isEnd) {
        classes.push(DAY_SELECTED_CLASS);
      } else if (!inViewMonth) {
        classes.push(DAY_OUTSIDE_MONTH_CLASS);
      }
      return classes.join(" ");
    }

    function render() {
      monthLabel.textContent = new Date(
        state.viewYear,
        state.viewMonth,
        1
      ).toLocaleDateString(undefined, { month: "long", year: "numeric" });

      grid.textContent = "";
      WEEKDAY_LABELS.forEach(function (weekdayLabel) {
        var headerCell = document.createElement("span");
        headerCell.className = WEEKDAY_CLASS;
        headerCell.textContent = weekdayLabel;
        grid.appendChild(headerCell);
      });

      var firstOfMonth = new Date(state.viewYear, state.viewMonth, 1);
      // Monday-first offset of the leading overflow days.
      var leadingDays = (firstOfMonth.getDay() + 6) % 7;
      var cellDate = addDays(firstOfMonth, -leadingDays);
      for (var cellIndex = 0; cellIndex < 42; cellIndex++) {
        var isoString = isoFromDate(cellDate);
        var dayButton = document.createElement("button");
        dayButton.type = "button";
        dayButton.setAttribute("data-date", isoString);
        dayButton.className = dayCellClass(
          isoString,
          cellDate.getMonth() === state.viewMonth
        );
        dayButton.textContent = String(cellDate.getDate());
        grid.appendChild(dayButton);
        cellDate = addDays(cellDate, 1);
      }
    }

    // ── Wiring ──
    picker
      .querySelector("[data-date-range-calendar-toggle]")
      .addEventListener("click", function () {
        if (state.open) closePopup();
        else openPopup();
      });

    grid.addEventListener("click", function (event) {
      var dayButton = event.target.closest("button[data-date]");
      if (dayButton) pickDate(dayButton.getAttribute("data-date"));
    });

    grid.addEventListener("mouseover", function (event) {
      if (!state.startIso || state.endIso) return;
      var dayButton = event.target.closest("button[data-date]");
      if (!dayButton) return;
      var hoveredIso = dayButton.getAttribute("data-date");
      if (hoveredIso === state.hoverIso) return;
      state.hoverIso = hoveredIso;
      render();
    });

    popup
      .querySelector("[data-date-range-prev]")
      .addEventListener("click", function () {
        state.viewMonth -= 1;
        if (state.viewMonth < 0) {
          state.viewMonth = 11;
          state.viewYear -= 1;
        }
        render();
      });

    popup
      .querySelector("[data-date-range-next]")
      .addEventListener("click", function () {
        state.viewMonth += 1;
        if (state.viewMonth > 11) {
          state.viewMonth = 0;
          state.viewYear += 1;
        }
        render();
      });

    popup.querySelectorAll("[data-date-range-preset]").forEach(function (button) {
      button.addEventListener("click", function () {
        applyPreset(button.getAttribute("data-date-range-preset"));
      });
    });

    // Cancel: close the popup and clear the selected dates.
    popup
      .querySelector("[data-date-range-cancel]")
      .addEventListener("click", function () {
        clearSelection();
        closePopup();
      });

    // Clear: clear the selected dates but keep the popup open.
    popup
      .querySelector("[data-date-range-clear]")
      .addEventListener("click", function () {
        clearSelection();
        render();
      });

    // Select: close the popup, keeping the selected dates.
    popup
      .querySelector("[data-date-range-select]")
      .addEventListener("click", function () {
        closePopup();
      });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && state.open) closePopup();
    });

    document.addEventListener("mousedown", function (event) {
      if (state.open && !picker.contains(event.target)) closePopup();
    });

    return state;
  }

  function initPicker(picker) {
    if (picker.dataset.dateRangePickerInitialized) return;
    picker.dataset.dateRangePickerInitialized = "true";
    var calendarState = createCalendarState(picker);
    initField(picker, calendarState);
  }

  function initAllPickers() {
    document.querySelectorAll("[data-date-range-picker]").forEach(initPicker);
  }

  window.initDateRangePickers = initAllPickers;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAllPickers);
  } else {
    initAllPickers();
  }
})();
