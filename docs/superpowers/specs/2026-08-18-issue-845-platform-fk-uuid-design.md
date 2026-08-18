# ID-07: platform foreign keys on UUID identity — decision record

Shipped for #845 (2026-08-18) as part of wave C of the
[UUID identity cutover wave plan](2026-08-17-uuid-identity-cutover-wave-plan.md),
which carries the reusable mechanics. This file keeps only what the diff and
the wave plan cannot say for themselves: the choices considered and rejected.

`Game.platform` and `Purchase.platform` resolve through `Platform.uuid`.

## Why the slice is drawn around `Platform`, not around `Game`

The wave plan originally gave `Game.platform` to ID-07 and `Purchase.platform`
to ID-09, grouping by owning model. Both are nullable `SET_NULL` foreign keys
to the same target, so that boundary would have produced, for a full wave:

- a `load_sample_data` remap carrying two identities at once — one relation
  naming a `uuid`, the other a `pk`, against the same target model;
- two of six platform filter lookups moved and four left behind, so the same
  facet name would mean different column types in `GameFilter` and
  `PurchaseFilter`;
- the `ModelForm` initial shim required on `GameForm.platform` and forbidden on
  `PurchaseForm.platform` — same field name, same widget, same target, opposite
  treatment, in one module.

The deciding evidence was `/api/platforms/search`: two adjacent, textually
identical `OuterRef` subqueries, one per referencing model. Under the split one
would have had to change while the other stayed.

Slicing by target model costs a larger diff and no additional design. ID-09
keeps `Purchase.games` and `Purchase.related_game`, which are genuinely its own
problem.

## Why filter nullability became a property of the lookup path

Rewriting `FilterField("platform_id")` to `platform__id` moves the resolved
model field from the nullable foreign key to `Platform.id`, which is `NOT NULL`.
`field_metadata` read `.null` off that terminal field, so the platform facet
would have lost its "(None)" modifier and the nested builder its
`IS_NULL`/`NOT_NULL`.

Four options were considered.

**Rejected — accept the loss and restore it in Wave E.** Defensible on user
impact: the only real deployment is not updated until the whole cutover lands,
and ID-11 deletes the `to_field` pointer, which restores the modifier by
itself. Rejected because the cost is not user impact. `tests/test_filters.py`'s
nullable assertions would have to be rewritten to encode the regression as the
contract, then rewritten back — for `platform`, `device`, `related_game` and
`platform` again across six PRs. Meanwhile `_SetCriterion._not_in_q` adds its
isnull arm unconditionally, so exclude-mode would keep matching platformless
rows while the metadata claimed NULL impossible: a four-wave divergence between
the metadata layer and the query layer. The repair is smaller than the
acceptance.

**Rejected — an explicit `FilterField(nullable=...)` override.** Hand-maintained
schema knowledge that can drift, and three more slices would have to remember
to set it.

**Rejected — special-case a trailing pk segment in `_resolve_model_field`,**
returning the relation instead of the target's pk so `platform__id` resolves
exactly as `platform_id` did. This makes the function lie about what a lookup
names: its other consumers (`_static_choices`, `is_m2m`, `criterion_kind`) would
silently receive a different field than the lookup spells. It also leaves
`platform__group` wrong.

**Chosen — nullability is a property of the whole path.** A hop through a
nullable relation leaves every field beyond it absent. `_resolve_model_field`
still resolves what the lookup actually names; `_lookup_is_nullable` consumes
the same walk and ORs `.null` across the hops.

This is a correction, not a new rule — verified against the real ORM before
adopting it, with a throwaway test asserting that a platformless game matches
both `platform__id__isnull=True` and `platform__group__isnull=True` despite
`Platform.id` and `Platform.group` both being `null=False`. The ORM has always
treated these paths as nullable; only the metadata disagreed.

It was also never optional: `tests/test_field_widget.py` asserts `IS_NULL` is
offered for `platform`, so the lookup rewrite alone turns `make check` red.

Side effect, deliberate: `platform_group` gains a presence modifier it never
had, meaning **"has no platform"** rather than "has a blank group" — a platform
with `group=""` does not match, consistent with this project's
empty-string-is-not-NULL convention.

## What the design missed, and how

Recorded because the misses are more instructive than the plan was.

**An adversarial review before implementation found two blockers.** First,
dropping the integer column cascades away both of `Game`'s uniqueness
guarantees — invisible to the state-based drift guard, and unasserted by any
test at the time. Second, `/api/platforms/search`'s recency subqueries filter
*on* the foreign key column; this design had listed that file as confirmed
unaffected, which was simply false. Either would have shipped.

**Writing the tests first found three more.** `unique_together` has to come
down before `RemoveField` rather than merely be restored after, because it
names the `platform` *field*, which cannot stay declared while that field is
absent. The database-level foreign-key test needs `bulk_create`, because
`Game.save()` calls `clean()`, which dereferences `self.platform` and raises
`DoesNotExist` before any insert is attempted. And both of `Game`'s uniqueness
guarantees are inert for rows with a NULL `year_released`, since a NULL never
collides in a unique index — a latent gap, not caused here, but one the
constraint test had to work around.

## Deliberate non-goals

- Filter criterion values and `/api/platforms/search` option values stay
  **integer** `Platform` pks. One endpoint feeds the facets of every mode, so a
  single relation cannot flip the option value type without breaking the modes
  still on integer foreign keys. They flip once, after the last Wave C slice.
- Existing `FilterPreset` content is not remapped (wave plan; the only real
  deployment has zero preset rows).
- `platform/<int:platform_id>/` routes are untouched — that parameter is
  `Platform.pk`, which still exists until Wave E.

## Rollback

`manage.py migrate games 0009` restores the integer columns with their original
values and NULLs. Reversing also requires reverting the regenerated fixture
blob; they are a single unit.
