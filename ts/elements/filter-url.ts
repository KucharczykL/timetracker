// Shared navigation builder. listUrl is server-provided; page always resets.
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
  // Empty sort and page size inherit; "0" remains explicit.
  if (sort) params.push("sort=" + encodeURIComponent(sort));
  if (perPage) params.push("per_page=" + encodeURIComponent(perPage));
  return params.length ? listUrl + "?" + params.join("&") : listUrl;
}
