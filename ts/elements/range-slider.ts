/**
 * Range slider — custom draggable handles (no native <input type=range>).
 *
 * Supports two modes, toggled via the .range-mode-toggle button:
 *   range (default) — two handles, min ≤ max constraint
 *   point           — single handle, sets both number inputs to the same value
 *
 * Handles track-fill positioning and sync between handles and the connected
 * number inputs (linked via data-target attributes on the handles).
 * Behavior is wired in connectedCallback; the typed props (min, max, step, mode)
 * come from the server via readRangeSliderProps.
 */
import { readRangeSliderProps } from "../generated/props.js";

class RangeSliderElement extends HTMLElement {
  private onMouseMove: ((event: MouseEvent) => void) | null = null;
  private onMouseUp: (() => void) | null = null;

  connectedCallback(): void {
    const { min: dataMin, max: dataMax, step, mode: initialMode } =
      readRangeSliderProps(this);
    let mode = initialMode;

    const track = this.querySelector<HTMLElement>("[data-range-track]");
    const trackFill = this.querySelector<HTMLElement>(".range-track-fill");
    const minHandle = this.querySelector<HTMLElement>(".range-handle-min");
    const maxHandle = this.querySelector<HTMLElement>(".range-handle-max");
    if (!track || !minHandle || !maxHandle) return;

    const minTarget = document.getElementById(
      minHandle.getAttribute("data-target") ?? ""
    ) as HTMLInputElement | null;
    const maxTarget = document.getElementById(
      maxHandle.getAttribute("data-target") ?? ""
    ) as HTMLInputElement | null;

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

    function getTargetValue(
      target: HTMLInputElement | null,
      defaultValue: number
    ): number {
      if (!target || target.value === "") return defaultValue;
      const parsed = parseInt(target.value, 10);
      return isNaN(parsed) ? defaultValue : parsed;
    }
    function setTargetValue(
      target: HTMLInputElement | null,
      value: number | string
    ): void {
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

    const makeDraggable = (handle: HTMLElement, isMin: boolean): void => {
      handle.addEventListener("mousedown", (event) => {
        event.preventDefault();
        const rect = track.getBoundingClientRect();

        const onMove = (moveEvent: MouseEvent): void => {
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
        };

        const onUp = (): void => {
          document.removeEventListener("mousemove", onMove);
          document.removeEventListener("mouseup", onUp);
          this.onMouseMove = null;
          this.onMouseUp = null;
        };

        this.onMouseMove = onMove;
        this.onMouseUp = onUp;
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
        onMove(event);
      });
    };

    makeDraggable(minHandle, true);
    makeDraggable(maxHandle, false);

    // ── Sync from number inputs back to handles ──

    function syncFromInputs(event?: Event): void {
      if (mode === "point") {
        const source =
          (event?.target as HTMLInputElement | null) || minTarget || maxTarget;
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

    const toggleButton = this.querySelector<HTMLElement>(".range-mode-toggle");
    if (toggleButton) {
      toggleButton.addEventListener("click", () => {
        const newMode = mode === "range" ? "point" : "range";
        this.setAttribute("mode", newMode);

        // Swap toggle icons
        const iconRange = toggleButton.querySelector(".range-mode-icon-range");
        const iconPoint = toggleButton.querySelector(".range-mode-icon-point");
        if (iconRange) iconRange.classList.toggle("hidden");
        if (iconPoint) iconPoint.classList.toggle("hidden");

        const dashSpan = this.querySelector(".range-dash");
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

  disconnectedCallback(): void {
    if (this.onMouseMove) {
      document.removeEventListener("mousemove", this.onMouseMove);
      this.onMouseMove = null;
    }
    if (this.onMouseUp) {
      document.removeEventListener("mouseup", this.onMouseUp);
      this.onMouseUp = null;
    }
  }
}

customElements.define("range-slider", RangeSliderElement);
