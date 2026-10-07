# A prefetch that never lands is asked again

Issue #1304.

## Rule

A `SearchSelect` with a `prefetch` asks the server for its first window
of rows when it opens. The flag `hasPrefetched` in
`ts/elements/search-select.ts` records that the window is asked for. A
later open reads the loaded rows and asks nothing.

The flag means "the window is asked for and the request is not
dropped". Two events drop the request:

- `cancelPendingSearch` aborts a pending request. Focus that leaves the
  widget calls it, and so do the clear × and its focus. The abort clears
  the flag.
- The request fails: a status other than 2xx, or a network error. The
  failure clears the flag.

The next open then asks for the window again. Without this, the panel
stays empty until the person types.

A request that a newer request supersedes does not clear the flag. The
newer request answers in its place.

## Why at the drop, not at the answer

The flag is set when the request leaves, not when the answer lands.
`_searchSelectRefetch` asks for the window and then the inline combobox
focuses the box. A flag that waits for the answer would make that focus
send a second request. Clearing the flag where the request is dropped
keeps that one request.

Any abort clears the flag, also the abort of a typed query. The next
open then asks for the window again, which costs one request and shows
current rows.

## Tests

`ts/elements/search-select.prefetch.test.ts`:

- Focus, blur before the answer, focus again: a second request goes out
  and its rows show.
- Focus, a failed answer, blur, focus again: the same.
- Focus, the answer lands, blur, focus again: no second request.

## Follow-up issues to file

None. The e2e wait the issue names left with the legacy purchase form.
