// applyUrl — the list-view navigation target for a serialized filter. Shared
// by <filter-builder> (Apply) and <quick-filter-bar> (submit / preset pick):
// an empty filter navigates to the bare list URL (#304). The URL itself is a
// server-provided typed prop (list_url_for), never window.location.pathname.
// A leaf module on purpose: the bar imports it without dragging the whole
// builder element chain onto every list page.
export function applyUrl(listUrl: string, filter: Record<string, unknown>): string {
  if (Object.keys(filter).length === 0) return listUrl;
  return listUrl + "?filter=" + encodeURIComponent(JSON.stringify(filter));
}
