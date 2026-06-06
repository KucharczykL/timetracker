/**
 * Range slider — custom draggable handles (no native <input type=range>).
 *
 * Supports two modes on each slider, toggled via the .range-mode-toggle button:
 *   range (default) — two handles, min ≤ max constraint
 *   point           — single handle, sets both number inputs to the same value
 *
 * Handles track-fill positioning and sync between handles and the connected
 * number inputs (linked via data-target attributes).
 */
(function () {
  "use strict";

  function initAll(force) {
    document.querySelectorAll(".range-slider").forEach(function (slider) {
      if (force) slider._rsInit = false;
      if (slider._rsInit) return;
      slider._rsInit = true;

      var mode = slider.getAttribute("data-mode") || "range";
      var trackFill = slider.querySelector(".range-track-fill");
      var minHandle = slider.querySelector(".range-handle-min");
      var maxHandle = slider.querySelector(".range-handle-max");
      if (!minHandle || !maxHandle) return;

      var minTarget = document.getElementById(
        minHandle.getAttribute("data-target")
      );
      var maxTarget = document.getElementById(
        maxHandle.getAttribute("data-target")
      );
      var dataMin = parseInt(slider.getAttribute("data-min"), 10);
      var dataMax = parseInt(slider.getAttribute("data-max"), 10);
      var step = parseInt(slider.getAttribute("data-step"), 10) || 1;

      // ── Helpers ──

      function valueToPercent(value) {
        return ((value - dataMin) / (dataMax - dataMin)) * 100;
      }
      function percentToValue(percent) {
        var raw = dataMin + (percent / 100) * (dataMax - dataMin);
        return Math.round(raw / step) * step;
      }
      function clamp(value, lo, hi) {
        return Math.max(lo, Math.min(hi, value));
      }

      function getTargetValue(target) {
        return parseInt(target ? target.value : 0, 10) || dataMin;
      }
      function setTargetValue(target, value) {
        if (target) target.value = value;
      }

      // ── Track fill positioning ──

      function updateTrackFill() {
        if (!trackFill) return;
        var minValue = getTargetValue(minTarget);
        var maxValue = getTargetValue(maxTarget);
        if (mode === "point") {
          trackFill.style.left = "0%";
          trackFill.style.width = valueToPercent(maxValue) + "%";
        } else {
          var leftPct = valueToPercent(minValue);
          var widthPct = valueToPercent(maxValue) - leftPct;
          trackFill.style.left = leftPct + "%";
          trackFill.style.width = widthPct + "%";
        }
      }

      function updateHandles() {
        minHandle.style.left = valueToPercent(getTargetValue(minTarget)) + "%";
        maxHandle.style.left = valueToPercent(getTargetValue(maxTarget)) + "%";
        updateTrackFill();
      }

      // ── Dragging ──

      function makeDraggable(handle, isMin) {
        handle.addEventListener("mousedown", function (e) {
          e.preventDefault();
          var rect = slider.getBoundingClientRect();

          function onMove(ev) {
            var pct = ((ev.clientX - rect.left) / rect.width) * 100;
            var value = percentToValue(clamp(pct, 0, 100));

            if (mode === "point") {
              setTargetValue(minTarget, value);
              setTargetValue(maxTarget, value);
              if (minTarget)
                minTarget.dispatchEvent(
                  new Event("input", { bubbles: true })
                );
              if (maxTarget)
                maxTarget.dispatchEvent(
                  new Event("input", { bubbles: true })
                );
            } else if (isMin) {
              setTargetValue(
                minTarget,
                clamp(value, dataMin, getTargetValue(maxTarget))
              );
              if (minTarget)
                minTarget.dispatchEvent(
                  new Event("input", { bubbles: true })
                );
            } else {
              setTargetValue(
                maxTarget,
                clamp(value, getTargetValue(minTarget), dataMax)
              );
              if (maxTarget)
                maxTarget.dispatchEvent(
                  new Event("input", { bubbles: true })
                );
            }
            updateHandles();
          }

          function onUp() {
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
          }
          document.addEventListener("mousemove", onMove);
          document.addEventListener("mouseup", onUp);
          onMove(e);
        });
      }

      makeDraggable(minHandle, true);
      makeDraggable(maxHandle, false);

      // ── Sync from number inputs back to handles ──

      function syncFromInputs() {
        if (mode === "point") {
          var value =
            getTargetValue(minTarget) || getTargetValue(maxTarget);
          setTargetValue(minTarget, value);
          setTargetValue(maxTarget, value);
        }
        updateHandles();
      }
      if (minTarget)
        minTarget.addEventListener("input", syncFromInputs);
      if (maxTarget)
        maxTarget.addEventListener("input", syncFromInputs);

      // ── Mode toggle ──

      var block = slider.closest(".range-slider-block");
      var toggleButton =
        block && block.querySelector(".range-mode-toggle");
      if (toggleButton) {
        toggleButton.addEventListener("click", function () {
          var newMode = mode === "range" ? "point" : "range";
          slider.setAttribute("data-mode", newMode);

          // Swap toggle icons
          var iconRange = toggleButton.querySelector(
            ".range-mode-icon-range"
          );
          var iconPoint = toggleButton.querySelector(
            ".range-mode-icon-point"
          );
          if (iconRange) iconRange.classList.toggle("hidden");
          if (iconPoint) iconPoint.classList.toggle("hidden");

          var dashSpan = block && block.querySelector(".range-dash");
          if (newMode === "point") {
            minHandle.style.display = "none";
            setTargetValue(minTarget, getTargetValue(maxTarget));
            if (minTarget) minTarget.classList.add("hidden");
            if (dashSpan) dashSpan.classList.add("hidden");
          } else {
            minHandle.style.display = "";
            if (minTarget) minTarget.classList.remove("hidden");
            if (dashSpan) dashSpan.classList.remove("hidden");
          }
          mode = newMode;
          updateHandles();
        });
      }

      // ── Initial position ──
      updateHandles();
    });
  }

  document.addEventListener("DOMContentLoaded", initAll);
  document.addEventListener("htmx:afterSwap", initAll);
  window.initRangeSliders = initAll;
})();
