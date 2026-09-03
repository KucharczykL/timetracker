# A reference names a work, and a removed row lets go of its key

An external reference is one provider, one key, and one catalog row: a Game, an
Edition, a Release or a Platform. `games/external_references.py` holds the
policies, the writes and the reads. `ExternalReference` holds the rows.

## The registry is the whole cost of a provider

`PROVIDER_POLICIES` states each provider's key rule, its trusted HTTPS
template, the label a person reads, and the hint that says what a key looks
like. No form, no renderer and no template names a provider. Two check
constraints do: one admits the registered words, one holds the canonical key
pattern. A second provider needs a migration for both.

## One key per record, per provider

A key is an identity, not a tag. Four conditional unique constraints, one per
kind, hold one live reference per record per provider. The tuple of provider,
kind and key is unique among live rows, across every library. Identity
reconciliation (#654, #785) owns the shared-catalog answer.

## The mark

`ExternalReference` carries a nullable `removed_at`. It stays out of
`REMOVABLE_MODELS`: no person removes a reference alone. `games/removal.py`
stamps the references of a removed row with that row's own mark, thus a
restore reads the two back as equal. A child keeps its own mark, thus a live
Release under a removed Game still holds its key.

A restore takes back only the references whose tuple no live row holds, in one
statement. The rest stay marked, and the record comes back without them.
`restore()` has no error channel until #795 gives it one.

## A set is stated, not patched row by row

`state_external_references()` takes one target and the keys it must hold. A
provider the caller does not name is left alone. Every refusal is read before
anything is written, and each carries the provider that caused it. The whole
set is one transaction. A shared target, a foreign target, a removed target
and a taken key are refused, each with one sentence.

## The forms and the pages

`ReferenceSetForm` builds one text box per registered provider. A blank box
states that the record holds no key from that provider. Add Game, Edit Game,
Add Platform and Edit Platform host the area, and write the record, the graph
and the references in one transaction. Edition and Release references are
read-only until #782 writes them and #690 draws them.

`ExternalReferenceLinks` renders each reference as its label and its key,
linked from the policy template alone. Game detail, the Editions table and the
platform list read it. `references_for()` reads one query per kind.

`Game.wikidata` is a mirror of the live Wikidata reference, written with an
`UPDATE`. Filters, sorting, the games list and the API read the column until
#889 takes it.
