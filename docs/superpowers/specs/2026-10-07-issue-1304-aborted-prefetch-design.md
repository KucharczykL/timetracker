# A search that never lands is asked again

Issue #1304.

## Rule

A `SearchSelect` with a `search-url` and a `prefetch` keeps two facts
in `ts/elements/search-select.ts`:

- `loadedQuery`: the query that the shown rows answer. `null` means no
  answer is shown.
- `pendingRequest`: the request in flight and its query (`PendingSearch`).
  `null` means no request is in flight.

Only an answer that lands sets `loadedQuery`. A request that is sent
sets nothing more than `pendingRequest`.

When the panel opens, the widget reads the query in the box. It sends a
request for that query when neither fact matches it. Otherwise it
filters the shown rows.

Thus:

- A blur, or focus on the clear ×, cancels a request before its answer
  lands. The next open asks again.
- A failed request, or one with a body that does not parse, sets no
  `loadedQuery`. The next open asks again. The panel says
  `Could not load results`, not the normal empty sentence.
- A typed query that lands sets `loadedQuery` to that query. An open
  with an empty box then asks for the window, not the old rows.
- A refetch followed at once by a focus sends one request. The request
  in flight matches the query, so the focus does not ask again.

A newer request aborts the older one. The older request then changes
nothing, also when its answer is a failure. Its rows are not awaited.

A dependency change, the clear ×, and a request with unfilled params
set `loadedQuery` to `null`. The shown rows then answer nothing.

## Why two facts, not one flag

A flag that is set when the request leaves needs a reset on every path
where the request does not land. A missed path leaves the panel empty
until the person types. A fact that only the landed answer sets needs
no reset. The request in flight stops the second request that a flag
used to stop.

## Tests

`ts/elements/search-select.prefetch.test.ts` covers each case above,
and an answer that lands with no second request on the next open.

## Follow-up issues to file

None. The e2e wait the issue names left with the legacy purchase form.
