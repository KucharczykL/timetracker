/** Shared width arithmetic for priority-plus rows.
 *
 * The owning element still controls measurement and DOM movement because its
 * semantics differ (filter facets vs navigation items). Keeping the fit math
 * here prevents the two ResizeObserver implementations from drifting on the
 * boundary where an item exactly fits.
 */
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
