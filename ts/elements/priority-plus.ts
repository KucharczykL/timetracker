/** Shared width arithmetic for priority-plus rows.
 *
 * The owning element still controls measurement and DOM movement because its
 * semantics differ (filter facets vs navigation items). Keeping the fit math
 * here prevents the ResizeObserver implementations from drifting on the
 * boundary where an item exactly fits.
 */
/** One collapsible item, and the natural width it takes in its row.
 *
 * The width is read once, while every item still stands in the row: a width
 * read under a `display:none` ancestor is 0, and a cached 0 spills every item
 * for the life of the page.
 */
export interface OverflowItem {
  element: HTMLElement;
  width: number;
}

export function priorityPlusTotalWidth(widths: number[], gap: number): number {
  return widths.reduce((sum, width) => sum + width + gap, 0);
}

export function priorityPlusFitCount(
  widths: number[],
  availableWidth: number,
  gap: number,
): number {
  let used = 0;
  let fitCount = 0;
  for (const width of widths) {
    used += width + gap;
    if (used > availableWidth) break;
    fitCount += 1;
  }
  return fitCount;
}
