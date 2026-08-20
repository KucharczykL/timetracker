# Game URL contract

## Canonical detail URL

A Game's read-only detail page has the canonical URL
`/tracker/game/<uuid>/<slug>/`. The UUID is authoritative. Every lookup stays
within the authenticated user's Library; the slug is derived from the current
Game name and is never queried, persisted, made unique, or treated as
authorization.

`Game.url_slug` applies Django's ASCII `slugify()` to the display name and uses
`game` when the result is empty. `Game.get_absolute_url()` is the canonical URL
builder. Renaming a Game therefore changes its canonical URL without creating
alias state. A request with an outdated or otherwise incorrect slug resolves
the owned Game by UUID and redirects permanently to its current canonical URL,
preserving the query string. Missing and foreign-Library UUIDs remain 404 and
do not expose a current slug.

Internal Game-detail links consume a Game instance and call
`get_absolute_url()`. Display-label overrides do not determine the URL slug.
Game edit/delete and Game-scoped create routes remain UUID-only because they
are not read-only detail resources.

## Retired compatibility paths

The UUID-only paths `/tracker/game/<uuid>/` and
`/tracker/game/<uuid>/view` are not compatibility aliases. The first has no
matching route and returns 404. The exact no-slash `/view` path is matched by
an unnamed guard that returns 404, preventing Django's `CommonMiddleware` from
appending a slash and reviving the retired URL through stale-slug
canonicalization.

The guard does not reserve the slug `view`.
`/tracker/game/<uuid>/view/` uses the canonical slug route: it renders a Game
whose current slug is `view`, or redirects as an ordinary stale slug for a
different Game.

Legacy integer Game URLs also have no aliases. The integer-to-UUID mapping was
discarded when UUIDv7 became the primary identity, so the application retains
no legacy identity column or redirect table.

## Route invariants

`UUIDv7Converter` remains registered in `games/urls.py`, including when that
module is imported under an alternative root URL configuration. The canonical
route rejects integers and non-v7 UUIDs. Unnamed retirement guards are not URL
reversal or return-origin interfaces, and every named route remains classified
exactly once by `games.views.returns`.

Platform, Purchase, Session, PlayEvent, GameStatusChange, Device, API, filter,
preset, and statistics identities do not derive slugs from this contract.
