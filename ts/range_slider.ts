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
import { onSwap } from "./utils.js";

(() => {
  "use strict";

  function initializeSlider(sliderElement: Element) {
    const slider = sliderElement as HTMLElement;
    let mode = slider.getAttribute("data-mode") || "range";
    const trackFill = slider.querySelector<HTMLElement>(".range-track-fill");
    const minHandle = slider.querySelector<HTMLElement>(".range-handle-min");
    const maxHandle = slider.querySelector<HTMLElement>(".range-handle-max");
    if (!minHandle || !maxHandle) return;

    const minTarget = document.getElementById(
      minHandle.getAttribute("data-target") ?? ""
    ) as HTMLInputElement | null;
    const maxTarget = document.getElementById(
      maxHandle.getAttribute("data-target") ?? ""
    ) as HTMLInputElement | null;
    const dataMin = parseInt(slider.getAttribute("data-min") ?? "", 10);
    const dataMax = parseInt(slider.getAttribute("data-max") ?? "", 10);
    const step = parseInt(slider.getAttribute("data-step") ?? "", 10) || 1;

    // ── Helpers ──

    function valueToPercent(value: number): number {
      return ((value - dataMin) / (dataMax - dataMin)) * 100;
    }
    function percentToValue(percent: number): number {
      const raw = dataMin + (percent / 100) * (dataMax - dataMin);
      return Math.round(raw / step) * step;
    }
    function clamp(value: number, low: number, high: number): number {
      return Math.max(low, Math.min(high, value));
    }

    function getTargetValue(target: HTMLInputElement | null, defaultValue: number): number {
      if (!target || target.value === "") return defaultValue;
      const parsed = parseInt(target.value, 10);
      return isNaN(parsed) ? defaultValue : parsed;
    }
    function setTargetValue(target: HTMLInputElement | null, value: number | string): void {
      if (target) target.value = String(value);
    }

    // ── Track fill positioning ──

    function updateTrackFill(): void {
      if (!trackFill) return;
      const minValue = clamp(getTargetValue(minTarget, dataMin), dataMin, dataMax);
      const maxValue = clamp(getTargetValue(maxTarget, dataMax), dataMin, dataMax);
      if (mode === "point") {
        trackFill.style.left = "0%";
        trackFill.style.width = valueToPercent(maxValue) + "%";
      } else {
        let leftPercent = valueToPercent(minValue);
        let rightPercent = valueToPercent(maxValue);
        if (leftPercent > rightPercent) {
          const temp = leftPercent;
          leftPercent = rightPercent;
          rightPercent = temp;
        }
        const widthPercent = rightPercent - leftPercent;
        trackFill.style.left = leftPercent + "%";
        trackFill.style.width = widthPercent + "%";
      }
    }

    function updateHandles(): void {
      const minValue = clamp(getTargetValue(minTarget, dataMin), dataMin, dataMax);
      const maxValue = clamp(getTargetValue(maxTarget, dataMax), dataMin, dataMax);
      minHandle!.style.left = valueToPercent(minValue) + "%";
      maxHandle!.style.left = valueToPercent(maxValue) + "%";
      updateTrackFill();
    }

    // ── Dragging ──

    function makeDraggable(handle: HTMLElement, isMin: boolean): void {
      handle.addEventListener("mousedown", (event) => {
        event.preventDefault();
        const rect = slider.getBoundingClientRect();

        function onMove(moveEvent: MouseEvent): void {
          const percent = ((moveEvent.clientX - rect.left) / rect.width) * 100;
          const value = percentToValue(clamp(percent, 0, 100));

          if (mode === "point") {
            setTargetValue(minTarget, value);
            setTargetValue(maxTarget, value);
            if (minTarget) minTarget.dispatchEvent(new Event("input", { bubbles: true }));
            if (maxTarget) maxTarget.dispatchEvent(new Event("input", { bubbles: true }));
          } else if (isMin) {
            setTargetValue(
              minTarget,
              clamp(value, dataMin, getTargetValue(maxTarget, dataMax))
            );
            if (minTarget) minTarget.dispatchEvent(new Event("input", { bubbles: true }));
          } else {
            setTargetValue(
              maxTarget,
              clamp(value, getTargetValue(minTarget, dataMin), dataMax)
            );
            if (maxTarget) maxTarget.dispatchEvent(new Event("input", { bubbles: true }));
          }
          updateHandles();
        }

        function onUp(): void {
          document.removeEventListener("mousemove", onMove);
          document.removeEventListener("mouseup", onUp);
        }
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
        onMove(event);
      });
    }

    makeDraggable(minHandle, true);
    makeDraggable(maxHandle, false);

    // ── Sync from number inputs back to handles ──

    function syncFromInputs(event?: Event): void {
      if (mode === "point") {
        const source = (event?.target as HTMLInputElement | null) || minTarget || maxTarget;
        const value = source ? source.value : "";
        setTargetValue(minTarget, value);
        setTargetValue(maxTarget, value);
      } else if (event && event.target) {
        const minValue = getTargetValue(minTarget, dataMin);
        const maxValue = getTargetValue(maxTarget, dataMax);
        if (event.target === minTarget) {
          if (minValue > maxValue) {
            setTargetValue(maxTarget, minValue);
          }
        } else if (event.target === maxTarget) {
          if (maxValue < minValue) {
            setTargetValue(minTarget, maxValue);
          }
        }
      }
      updateHandles();
    }

    function enforceStrictBounds(event: Event): void {
      const target = event.target as HTMLInputElement | null;
      if (target) {
        const value = parseInt(target.value, 10);
        if (!isNaN(value)) {
          const clamped = clamp(value, dataMin, dataMax);
          if (clamped !== value) {
            setTargetValue(target, clamped);
            target.dispatchEvent(new Event("input", { bubbles: true }));
          }
        }
      }
    }

    if (minTarget) {
      minTarget.addEventListener("input", syncFromInputs);
      minTarget.addEventListener("change", enforceStrictBounds);
    }
    if (maxTarget) {
      maxTarget.addEventListener("input", syncFromInputs);
      maxTarget.addEventListener("change", enforceStrictBounds);
    }

    // ── Mode toggle ──

    const block = slider.closest(".range-slider-block");
    const toggleButton = block && block.querySelector(".range-mode-toggle");
    if (toggleButton) {
      toggleButton.addEventListener("click", () => {
        const newMode = mode === "range" ? "point" : "range";
        slider.setAttribute("data-mode", newMode);

        // Swap toggle icons
        const iconRange = toggleButton.querySelector(".range-mode-icon-range");
        const iconPoint = toggleButton.querySelector(".range-mode-icon-point");
        if (iconRange) iconRange.classList.toggle("hidden");
        if (iconPoint) iconPoint.classList.toggle("hidden");

        const dashSpan = block && block.querySelector(".range-dash");
        if (newMode === "point") {
          minHandle.style.display = "none";
          setTargetValue(minTarget, maxTarget ? maxTarget.value : "");
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
  }

  onSwap(".range-slider", initializeSlider);
})();
