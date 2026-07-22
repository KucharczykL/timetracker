// applyUrl — the list-view navigation target for a serialized filter (and an
// optional sort / page size). Shared by <filter-builder> (Apply) and
// <quick-filter-bar> (submit / preset pick): an empty filter, no sort and no
// page size navigates to the bare list URL (#304). The URL itself is a
// server-provided typed prop (list_url_for), never window.location.pathname. A
// leaf module on purpose: the bar imports it without dragging the whole builder
// element chain onto every list page.
export function applyUrl(
  listUrl: string,
  filter: Record<string, unknown>,
  sort?: string,
  perPage?: string,
): string {
  const params: string[] = [];
  if (Object.keys(filter).length > 0) {
    params.push("filter=" + encodeURIComponent(JSON.stringify(filter)));
  }
  // Only a truthy sort is emitted; an empty sort omits ?sort= so the list view
  // applies its own default order (a default-order preset round-trips) (#77).
  if (sort) params.push("sort=" + encodeURIComponent(sort));
  // Likewise a non-empty page size pins rows-per-page (#337, #386); "" omits it
  // so the preset inherits the user's current default. "0" (show all) is
  // non-empty, so it rides through. `page` is deliberately never emitted —
  // loading a filter resets to page 1.
  if (perPage) params.push("per_page=" + encodeURIComponent(perPage));
  return params.length ? listUrl + "?" + params.join("&") : listUrl;
}
