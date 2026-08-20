# Game compatibility route retirement

Status: approved 2026-08-20. Issue: #648 (ID-16). Parent phase: #600.
Depends on the Game canonical URL work in #647.

## Retired URL contract

Issue #647 left two UUID-only compatibility routes for the canonical Game
detail URL: `/tracker/game/<uuid>/view` and `/tracker/game/<uuid>/`. Internal
links now use `/tracker/game/<uuid>/<slug>/`, so both compatibility aliases are
retired immediately rather than carried through a tagged-release bake-in.

The UUID-only path has no matching route and returns 404. The exact historical
`/view` path also returns 404 through an unnamed guard route. The guard is
required because Django's `CommonMiddleware` would otherwise append a slash,
turn the old URL into `/view/`, and let the canonical slug route treat `view`
as a stale slug. It is deliberately unnamed and therefore is not a public
reversal or return-origin interface.

The guard does not reserve the slug `view`. `/tracker/game/<uuid>/view/`
continues to use the canonical slug route: it renders a Game whose current slug
is `view`, or redirects as an ordinary stale slug for another Game.

## Preserved behavior and boundaries

`Game.get_absolute_url()`, the canonical `games:view_game` route, UUIDv7
validation, query-preserving stale-slug redirects, and authenticated
library-scoped Game lookups remain unchanged. The stale-slug redirect helper
therefore remains, while the UUID-only redirect view and the two public route
names are removed.

The compatibility-return classification disappears when its last named routes
do. No schema, migration, reconciliation, API, filter, saved-preset,
statistics, or data-isolation changes belong to this issue. Legacy integer
catalog URLs already 404 because #646 destroyed the integer-to-UUID map; this
issue adds no integer alias or permanent identity column.

## Reversibility and verification

This is a code-only contraction. Reverting the code restores both UUID-only
redirects without a data operation or reconciliation step.

Focused verification proves that the retired names cannot reverse, the two
old paths return 404 without a `Location` header, the no-slash `/view` request
cannot escape through slash appending, and `/view/` still works as the ordinary
canonical-slug shape. Existing tests continue to cover canonical rendering,
stale-slug redirects and query preservation, UUIDv7 routing, and foreign-library
404 behavior. Route classification remains exhaustive after removing the empty
compatibility bucket. The final gate is `make check` with the Makefile's default
parallel worker count, followed by `git diff --check` and complete diff review.
