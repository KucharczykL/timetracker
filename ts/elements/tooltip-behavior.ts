/**
 * Shared passive tooltip behavior for <pop-over> and <truncated-text>.
 *
 * The caller owns the markup and passes every element touched by positioning.
 * This controller owns only interaction state, anchored positioning, and
 * teardown.
 */
import {
  clearAnchoredPosition,
  positionAnchored,
  type Side,
} from "./anchored-position.js";
import { bindPopupDismiss } from "../utils.js";

const ARROW_SIZE = 8;
const TRIGGER_GAP = 8;

export interface TooltipConfig {
  host: HTMLElement;
  trigger: HTMLElement;
  /** Geometry anchor; defaults to the interaction host for existing consumers. */
  anchor?: HTMLElement | (() => HTMLElement);
  panel: HTMLElement;
  content?: HTMLElement;
  arrow?: HTMLElement;
  side?: Side;
  tap: boolean;
  isActive?: () => boolean;
}

export interface TooltipController {
  open(): void;
  close(): void;
  destroy(): void;
}

function tintArrow(panel: HTMLElement, arrow?: HTMLElement): void {
  if (!arrow) return;
  const styles = getComputedStyle(panel);
  arrow.style.backgroundColor = styles.backgroundColor;
  arrow.dataset.borderColor = styles.borderTopColor;
  arrow.dataset.panelBorder = `${parseFloat(styles.borderTopWidth) || 0}`;
}

function positionArrow(
  arrow: HTMLElement | undefined,
  side: Side,
  triggerCenterInPanel: number,
  panelWidth: number,
): void {
  if (!arrow) return;
  const panelAbove = side === "top";
  const border = `1px solid ${arrow.dataset.borderColor ?? ""}`;
  arrow.style.borderTop = panelAbove ? "" : border;
  arrow.style.borderLeft = panelAbove ? "" : border;
  arrow.style.borderBottom = panelAbove ? border : "";
  arrow.style.borderRight = panelAbove ? border : "";

  const half = ARROW_SIZE / 2;
  const panelBorder = Number(arrow.dataset.panelBorder) || 0;
  const centerInPaddingBox = triggerCenterInPanel - panelBorder;
  const paddingBoxWidth = panelWidth - 2 * panelBorder;
  arrow.style.left = `${Math.max(
    ARROW_SIZE,
    Math.min(centerInPaddingBox - half, paddingBoxWidth - 2 * ARROW_SIZE),
  )}px`;
  arrow.style.top = panelAbove ? "" : `${-half}px`;
  arrow.style.bottom = panelAbove ? `${-half}px` : "";
}

export function attachTooltip(config: TooltipConfig): TooltipController {
  const {
    host,
    trigger,
    anchor = host,
    panel,
    content = panel,
    arrow,
    side = "top",
    tap,
    isActive = () => true,
  } = config;
  let isOpen = false;
  let lastPointerType = "";
  let destroyed = false;

  const positionPanel = (): void => {
    const resolvedAnchor = typeof anchor === "function" ? anchor() : anchor;
    const result = positionAnchored(resolvedAnchor, panel, {
      align: "center",
      side,
      gap: TRIGGER_GAP,
      scrollable: true,
      scrollTarget: content,
    });
    positionArrow(
      arrow,
      result.side,
      result.anchorCenterX - result.left,
      result.width,
    );
  };

  const reposition = (): void => {
    if (isOpen) positionPanel();
  };

  const onKeyDown = (event: KeyboardEvent): void => {
    if (event.key === "Escape") close();
  };

  const open = (): void => {
    if (destroyed || isOpen || !isActive()) return;
    isOpen = true;
    panel.hidden = false;
    tintArrow(panel, arrow);
    positionPanel();
    if (!tap) document.addEventListener("keydown", onKeyDown);
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
  };

  const close = (): void => {
    if (!isOpen) return;
    isOpen = false;
    panel.hidden = true;
    clearAnchoredPosition(panel);
    if (content !== panel) content.style.removeProperty("max-height");
    if (!tap) document.removeEventListener("keydown", onKeyDown);
    window.removeEventListener("scroll", reposition, true);
    window.removeEventListener("resize", reposition);
  };

  const onPointerEnter = (event: PointerEvent): void => {
    if (event.pointerType === "mouse") open();
  };
  const onPointerLeave = (event: PointerEvent): void => {
    if (event.pointerType === "mouse") close();
  };
  const onFocusIn = (): void => {
    if (lastPointerType !== "touch" && lastPointerType !== "pen") open();
  };
  const onFocusOut = (event: FocusEvent): void => {
    if (!host.contains(event.relatedTarget as Node)) close();
    lastPointerType = "";
  };
  const onTriggerPointerDown = (event: PointerEvent): void => {
    lastPointerType = event.pointerType;
  };
  const onTriggerClick = (): void => {
    if (lastPointerType !== "mouse") {
      if (isOpen) close();
      else open();
    }
    lastPointerType = "";
  };

  host.addEventListener("pointerenter", onPointerEnter);
  host.addEventListener("pointerleave", onPointerLeave);
  host.addEventListener("focusin", onFocusIn);
  host.addEventListener("focusout", onFocusOut);
  if (tap) {
    trigger.addEventListener("pointerdown", onTriggerPointerDown);
    trigger.addEventListener("click", onTriggerClick);
  }
  const dismissCleanup = tap
    ? bindPopupDismiss({ host, isOpen: () => isOpen, close })
    : null;

  const destroy = (): void => {
    if (destroyed) return;
    close();
    destroyed = true;
    host.removeEventListener("pointerenter", onPointerEnter);
    host.removeEventListener("pointerleave", onPointerLeave);
    host.removeEventListener("focusin", onFocusIn);
    host.removeEventListener("focusout", onFocusOut);
    trigger.removeEventListener("pointerdown", onTriggerPointerDown);
    trigger.removeEventListener("click", onTriggerClick);
    dismissCleanup?.();
  };

  return { open, close, destroy };
}
