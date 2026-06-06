/**
 * Dual-handle range slider — pure JS with draggable handles.
 */
(function () {
  "use strict";

  function initAll(force) {
    document.querySelectorAll(".range-slider").forEach(function (slider) {
      if (force) slider._rsInit = false;
      if (slider._rsInit) return;
      slider._rsInit = true;

      var minHandle = slider.querySelector(".range-handle-min");
      var maxHandle = slider.querySelector(".range-handle-max");
      var track = slider.querySelector(".range-track-fill");
      if (!minHandle || !maxHandle) return;

      var minTarget = document.getElementById(minHandle.getAttribute("data-target"));
      var maxTarget = document.getElementById(maxHandle.getAttribute("data-target"));
      var dMin = parseInt(slider.getAttribute("data-min"), 10);
      var dMax = parseInt(slider.getAttribute("data-max"), 10);
      var step = parseInt(slider.getAttribute("data-step"), 10) || 1;

      function valueToPercent(v) { return ((v - dMin) / (dMax - dMin)) * 100; }
      function percentToValue(p) {
        var raw = dMin + (p / 100) * (dMax - dMin);
        return Math.round(raw / step) * step;
      }
      function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

      function getTargetVal(el) { return parseInt(el ? el.value : minTarget.value, 10) || dMin; }
      function setTargetVal(el, v) { if (el) el.value = v; }

      function update() {
        var minV = getTargetVal(minTarget);
        var maxV = getTargetVal(maxTarget);
        minV = clamp(minV, dMin, dMax);
        maxV = clamp(maxV, dMin, dMax);
        if (minV > maxV) minV = maxV;
        if (maxV < minV) maxV = minV;
        setTargetVal(minTarget, minV);
        setTargetVal(maxTarget, maxV);
        var minP = valueToPercent(minV);
        var maxP = valueToPercent(maxV);
        minHandle.style.left = minP + "%";
        maxHandle.style.left = maxP + "%";
        if (track) {
          track.style.left = minP + "%";
          track.style.width = (maxP - minP) + "%";
        }
      }

      function makeDraggable(handle, isMin) {
        handle.addEventListener("mousedown", function (e) {
          e.preventDefault();
          var rect = slider.getBoundingClientRect();
          function onMove(ev) {
            var pct = ((ev.clientX - rect.left) / rect.width) * 100;
            var v = percentToValue(clamp(pct, 0, 100));
            if (isMin) {
              minTarget.value = clamp(v, dMin, getTargetVal(maxTarget));
            } else {
              maxTarget.value = clamp(v, getTargetVal(minTarget), dMax);
            }
            update();
            // Trigger input event on the target so any listeners fire
            var tgt = isMin ? minTarget : maxTarget;
            if (tgt) tgt.dispatchEvent(new Event("input", { bubbles: true }));
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

      // Sync from inputs to slider
      function fromInputs() { update(); }
      if (minTarget) minTarget.addEventListener("input", fromInputs);
      if (maxTarget) maxTarget.addEventListener("input", fromInputs);

      update();
    });
  }

  document.addEventListener("DOMContentLoaded", initAll);
  document.addEventListener("htmx:afterSwap", initAll);
  // Expose for manual re-init (filter bar toggle)
  window.initRangeSliders = initAll;
})();
