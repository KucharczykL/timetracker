// applyUrl — the list-view navigation target for a serialized filter (and an
// optional sort). Shared by <filter-builder> (Apply) and <quick-filter-bar>
// (submit / preset pick): an empty filter and no sort navigates to the bare list
// URL (#304). The URL itself is a server-provided typed prop (list_url_for),
// never window.location.pathname. A leaf module on purpose: the bar imports it
// without dragging the whole builder element chain onto every list page.
export function applyUrl(
  listUrl: string,
  filter: Record<string, unknown>,
  sort?: string,
): string {
  const params: string[] = [];
  if (Object.keys(filter).length > 0) {
    params.push("filter=" + encodeURIComponent(JSON.stringify(filter)));
  }
  // Only a truthy sort is emitted; an empty sort omits ?sort= so the list view
  // applies its own default order (a default-order preset round-trips) (#77).
  if (sort) params.push("sort=" + encodeURIComponent(sort));
  return params.length ? listUrl + "?" + params.join("&") : listUrl;
}
