# Recency-ranked SearchSelect prefetch

## Goal

Make the initial blank-query options in SearchSelect more useful by showing
recently used devices and platforms before older values, consistently wherever
their existing search endpoints are used.

## Scope

- Keep the client-side SearchSelect contract unchanged: it sends an empty query
  and a `limit` for its initial prefetch, and sends the typed query thereafter.
- Keep every non-empty query alphabetically ordered, preserving predictable
  search results.
- For an empty device query, order devices by the newest associated session
  start time, then device creation time, then name.
- For an empty platform query, order platforms by their newest use by a game or
  purchase, then platform creation time, then name.
- Add endpoint tests demonstrating recent use wins over an alphabetically
  earlier value and that typed queries remain alphabetical.

## Design

The ranking belongs in the existing search endpoints, rather than in
SearchSelect or individual forms. This makes the behavior universal for form
and filter selectors without new props or client code.

Each endpoint will annotate its queryset with a nullable latest-use timestamp
and use it only for blank queries. An explicit `nulls_last` ordering puts used
values first; deterministic creation-time and name fallbacks order unused
values. The response schema and `limit` behavior do not change.
