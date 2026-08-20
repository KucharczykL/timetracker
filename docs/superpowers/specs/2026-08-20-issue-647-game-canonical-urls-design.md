# Game canonical URLs

Status: approved 2026-08-20. Issue: #647 (ID-15). Parent phase: #600.
Depends on the Game UUIDv7 primary-key promotion in #646 and the play-history
UUIDv7 primary-key promotion in #848.

## Canonical URL contract

Only a Game's read-only detail page receives a readable canonical URL:
`/tracker/game/<uuid>/<slug>/`. The UUID remains authoritative and every lookup
continues through the authenticated user's `UserLibrary`; the slug is derived
from the current Game name and is never queried, persisted, made unique, or
treated as authorization.

The existing `/tracker/game/<uuid>/view` URL and the charter's UUID-only
`/tracker/game/<uuid>/` form permanently redirect to the canonical URL. A
canonical path carrying a stale or incorrect slug redirects in the same way.
Redirects preserve the query string and resolve the owned Game before exposing
its current slug, so a foreign-library or missing UUID remains a 404.

Game edit/delete and game-scoped create routes stay UUID-only. Platform,
Purchase, Session, PlayEvent, GameStatusChange, Device, API, filter, preset, and
statistics identities do not gain slugs in this issue. Provider resolver URLs
remain deferred to the catalog-integration owner.

## Slug and link behavior

`Game.url_slug` applies Django's ASCII `slugify()` to the current display name
and uses `game` when the result is empty. `Game.get_absolute_url()` is the one
canonical URL builder. Renaming a Game therefore changes its URL without
creating alias state; a request for the former slug resolves by UUID and
redirects to the new form.

Internal detail links consume a Game instance and call `get_absolute_url()`.
Display labels may differ from the Game name, but may not determine the URL
slug. Mutation fallbacks carry both canonical route arguments when a complete
Game instance is already available.

## Reversibility and verification

This is a code-only change with no migration, data rewrite, or reconciliation
step. Reverting the code restores the prior route table without data loss,
although bookmarks created only in the new canonical form naturally require
the new code.

Focused verification covers slug normalization and fallback, canonical
reversal, permanent redirects and query preservation, rename canonicalization,
strict UUIDv7 routing, route precedence, internal link generation, safe return
origins, and user isolation. The final gate is the full `make check` with the
Makefile's default parallel worker count.
