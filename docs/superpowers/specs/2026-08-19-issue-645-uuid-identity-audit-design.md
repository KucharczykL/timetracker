# ID-10 (#645): verify the integer-to-UUID reconciliation map

Status: approved 2026-08-19. Slice ID-10 (#645), Wave D of the
[UUID identity cutover wave plan](2026-08-17-uuid-identity-cutover-wave-plan.md),
whose "What *swap every read/write path* actually means" checklist carries the
mechanics this record does not repeat.

## Outcome

A read-only audit that proves the integer→UUID map is complete and consistent
across every model converted in Waves B and C, and fails loudly when it is not.
It is the gate Wave E (ID-11–ID-14) runs behind: after Wave E the integer side
of the map is gone, so anything unverified now is unverifiable forever.

## Boundary

No schema change and no migration. Wave E's promotions, the M2M through
conversion, and the URL work stay in their own issues. One exception is folded
in deliberately, argued in decision 3: `anonymize_sample` produces data that
violates the invariant this issue gates on, so the audit cannot be turned on
without fixing the producer.

## What is actually worth verifying

Most of what "reconciliation" suggests is already enforced by PostgreSQL and
asserting it proves only that the constraint exists:

| Property | Enforced by |
| --- | --- |
| `uuid` present | `NOT NULL` (`UUIDv7Field(unique=True, editable=False)`) |
| `uuid` injective | the unique index |
| `uuid` is version 7 | the `uuid_v7` domain's `CHECK` (migration `0002`) |
| every FK value resolves | the foreign-key constraint |

Two things nothing enforces, and both are the point of this issue:

1. **Which columns are still integer, and whether that is deliberate.** Nothing
   in the schema distinguishes "deferred by design, owned by ID-11" from
   "missed in Wave C".
2. **Ordering agreement** — that `uuid` order equals `(created_at, id)` order.
   Wave B's backfill established this (migration `0005`'s `order_preserved`
   check) and nothing has held it since.

A third failure mode is specific to how Wave C was built: its migrations rewrote
columns with raw SQL, `RemoveField`, `RenameField` and `AlterField`. Django's
migration *state* and the real database can therefore disagree, and
`make check-migrations` compares state against models, never against
PostgreSQL. The wave plan already records this shape (checklist item 6: a
`DROP COLUMN` cascades indexes away while the state keeps them). Wave E will do
more raw SQL on `games_purchase_games`, so a state-vs-database comparison is the
highest-value check available at this point in the wave.

## Decisions

### 1. A management command with derived expectations, plus a pinned test

`manage.py audit_uuid_identity`, a sibling of `audit_library_ownership`:
flagless, read-only, prints the complete report, then raises `CommandError` if
anything was violated. `make audit-uuid-identity` runs it against a real
database.

Rejected: a pytest-only audit. It can only ever see a freshly-migrated test
database, and the state-vs-database drift this is built to catch is exactly the
kind of thing that appears in a long-lived production database and not in a
fresh one.

Rejected: a hand-written table of every model and its expected key type.
Readable, but a relation added later is invisible to it, and it cannot detect
Django↔PostgreSQL disagreement at all — it would be comparing a hand-written
list against a hand-written list.

The command reports every violation before failing rather than raising on the
first, so one run tells an operator the whole story. This deliberately differs
from the migrations' `require_match` fail-fast style, which is right inside a
migration (where the first mismatch means "do not proceed") and wrong in an
audit.

Scope is the `games` app's models, including auto-created many-to-many through
models. `django.contrib` is excluded; including it floods the residual
inventory with `auth_permission.content_type_id` and its dozens of siblings,
none of which this wave will ever convert.

### 2. Five checks

**A — Django↔PostgreSQL type agreement (derived, zero maintenance).** For every
relation column on every `games` model, the expected PostgreSQL type is
`field.target_field`'s `db_type`; the actual type is read from `pg_catalog`.
Disagreement is a violation. This needs no updating as the wave proceeds: it
re-derives from whatever the models currently say.

**B — residual integer inventory (pinned).** The set of relation columns whose
actual type is integer must *equal* a documented constant, each entry labelled
with the slice that owns it:

```
games_purchase_games.game_id      ID-11 (#646)
games_purchase_games.purchase_id  ID-13 (#849)
games_userlibrary.user_id         never — auth.User is not a converted model
games_userpreferences.user_id     never — auth.User is not a converted model
```

with the same treatment for the still-integer **primary keys** (all eight
converted models, owned by ID-11/12/13/14). Equality, not containment: a new
integer relation appearing anywhere fails the gate, and each Wave E slice must
shrink the inventory to stay green. This makes the constant the machine-readable
statement of Wave E readiness, continuing the convention ID-09 started with
`test_the_purchase_games_through_table_is_still_integer_keyed`.

The owning-slice labels are report data, not commentary: the command prints them
so an operator reading a failure knows whether a still-integer column is
expected. They are not issue references in comments.

**C — identity column health.** Per converted model: the `uuid` column is of
domain `uuid_v7`, is `NOT NULL`, and has a unique index that `pg_catalog`
actually reports; `count(*) == count(DISTINCT uuid)`; zero NULLs. Each is one
query. They are constraint-backed (see the table above) and are asserted anyway,
because what they now prove is that the *constraint* survived Wave C's column
surgery.

**D — ordering agreement.** Per converted model that has a `created_at`:
`ORDER BY uuid` equals `ORDER BY created_at, id`. Reports the first diverging
row rather than a boolean, so a failure is actionable. A model without
`created_at` is skipped with an explicit report line, so "skipped" is never
mistaken for "passed".

**E — referential agreement.** Per uuid-typed foreign-key column: zero non-NULL
values without a matching target `uuid`, and the constraint in `pg_constraint`
is `convalidated`. The second half is the one that is not vacuous — PostgreSQL
permits `NOT VALID` constraints, which enforce new rows while never having
checked existing ones.

### 3. Fix the producer rather than weakening the gate

The ordering invariant does not survive `anonymize_sample`. The command rewrites
`created_at` on every model it touches (`session.created_at =
session.timestamp_start` after a per-game offset; `Game.objects.update(created_at
=FIXED_EPOCH)`) and never touches `uuid`. A fresh run against a production copy
therefore emits rows whose uuid embeds the **real** creation timestamp against a
randomised `created_at` — an ordering violation, and a disclosure: UUIDv7 carries
the timestamp to the millisecond, so the dates the anonymizer exists to
randomise stay recoverable from the committed fixture with
`uuid_extract_timestamp`.

Considered and rejected: a `--skip-ordering` escape hatch for fixture-seeded
databases. It makes the gate opt-out precisely where the data is known to be
wrong, and leaves the disclosure in place.

Chosen: `anonymize_sample` re-assigns every `uuid` from the anonymized
`created_at` before dumping, using the algorithm migration `0005` backfilled
with — `uuid7_at(created_at, sequence=n)` over rows ordered by `(created_at,
pk)`, the sequence restarting each millisecond — and then remaps every foreign
key referring to that model, discovered through `_meta.related_objects` rather
than a hand-written list. The `games:` many-to-many lists are integer primary
keys and are untouched.

Measured state of the committed `sample.yaml.gz` before this change:

| Model | rows | has `uuid` | uuid timestamp | ordering |
| --- | --- | --- | --- | --- |
| `games.game` | 851 | yes | `FIXED_EPOCH` | agrees |
| `games.platform` | 25 | yes | `FIXED_EPOCH` | agrees |
| `games.device` | 14 | yes | `FIXED_EPOCH` | agrees |
| `games.purchase` | 795 | **no** | — | breaks on load |
| `games.session` | 2718 | **no** | — | breaks on load |
| `games.playevent` | 203 | **no** | — | breaks on load |

Two findings from that measurement, both of which shaped the plan:

- The three models that do carry a `uuid` already hold exactly
  `uuid7_at(FIXED_EPOCH, sequence=0..n-1)` in pk order. The algorithm proposed
  here is already the de-facto convention, applied by hand in earlier slices'
  throwaway transforms. This change formalises it in the producer.
- The other three carry no `uuid` at all — the blob predates migrations `0006`
  and `0007`. On `loaddata` they receive `db_default uuidv7()` at load time in
  file order, while their `created_at` is date-jittered, so ordering agreement
  fails there and nowhere else. The committed blob is clean only where someone
  repaired it by hand.

The blob is regenerated by a throwaway transform over the existing file, per the
recipe ID-06 established — not a database round trip, which cannot work because
loading the old fixture needs pre-cutover code while the migration needs
post-cutover code. No production copy is required.

### 4. `uuid7_at` gains an `entropy` parameter

`uuid7_at` fills `rand_b` from `secrets.randbits(62)`, which `random.seed()` does
not govern, so generating uuids inside the anonymizer would break the
byte-determinism the fixture is deliberately designed for
(`test_output_is_deterministic_for_a_fixed_seed`, and the stable git blob that
depends on it).

`uuid7_at(moment, *, sequence=None, entropy=None)` — `entropy` fills `rand_b`,
defaulting to today's `secrets.randbits(62)` so every existing caller is
unchanged. The anonymizer passes `random.getrandbits(62)` from its already-seeded
RNG, keeping determinism where the seed already lives.

Rejected: deriving `rand_b` by hashing `(model label, pk)`. It would make fixture
uuids independent of `--seed` and keep them out of the RNG stream, but it
introduces a second uuid-generation convention next to the seeded one for no
gain the first option does not already provide.

### 5. `platforms.yaml` keeps insert-time uuids

Pinning explicit `uuid` values in `platforms.yaml` was considered and rejected on
evidence. `Platform.created_at` is `auto_now_add=True`, and `loadplatforms`
deserializes and then calls `Platform.save()` — so `auto_now_add` overwrites the
fixture's `created_at` with the load time. A pinned uuid would encode 2024-01-01
against a `created_at` of today, making the platform fixture the only thing in
the repository that violates the gate being added.

The same finding shows the fixture's existing `created_at: 2024-01-01` lines are
inert. They are removed, because a line that looks like it sets a timestamp and
does not is worse than no line.

(Adding a uuid there would not have collided, incidentally: `loadplatforms` skips
by name before saving, so a re-run never reinserts. The problem is the ordering
invariant, not uniqueness.)

## Tests

`tests/test_uuid_identity_audit.py`:

- a clean run over seeded data;
- a clean run over the **real committed `sample.yaml.gz`**, which is the guard
  that keeps a future regeneration from reintroducing load-time uuids;
- one negative test per check — retype a column out from under Django, perturb
  the residual inventory, swap two uuids to invert ordering, orphan a foreign-key
  value — each asserting the audit *fails*. An audit that cannot fail is worth
  nothing, and every check here is cheap enough to be tempting to write
  vacuously.

`tests/test_anonymize_sample.py` gains: uuid embedded timestamps track the
anonymized `created_at`; ordering agreement holds in the output; byte
determinism for a fixed seed still holds; the output still reloads via
`loaddata`.

Note the trap the wave plan records as checklist item 7: inserting a
deliberately-bad row for a negative test must bypass `Model.save()`
(`bulk_create`), or `clean()` raises in Python and the test passes while proving
nothing.

## Verification

`make check` in full, including `e2e/`. The PR records the regenerated fixture's
per-model record counts (unchanged from the table above) and the uuid timestamp
range before and after the transform.

## Residual risks and follow-ups

- **The 4096-rows-per-millisecond ceiling.** `uuid7_at`'s `sequence` is 12 bits,
  and the anonymizer collapses every Game, Platform and Device to a single
  `FIXED_EPOCH` millisecond. At 851 games the headroom is 4.8×; past it,
  regeneration fails with `ValueError`. Loud rather than silent, but it will
  bite eventually. Filed as a follow-up.
- **Fixtures that carry explicit `created_at` and omit `uuid`** can violate the
  ordering gate, since the omitted uuid is generated at load time. Neither
  committed fixture does so after this change (`platforms.yaml` is immune via
  `auto_now_add`; `sample.yaml.gz` is fixed here), but nothing prevents the next
  one. Filed as a convention note.
- **Saved-filter content stays out of scope**, unchanged from the wave plan's
  Wave C statement: `FilterPreset` JSON stores raw integer pks, the only real
  deployment has zero preset rows, and no remap tooling is built.
