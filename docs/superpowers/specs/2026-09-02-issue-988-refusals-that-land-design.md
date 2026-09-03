# A refusal lands where it can be read

Issue [#988](https://github.com/KucharczykL/timetracker/issues/988), with
[#996](https://github.com/KucharczykL/timetracker/issues/996). Three sentences
reach a person in the wrong shape. Each fix here outlives the catalog wave.

## What this issue no longer does

#988 named three defects. The first was the placement of
`LEGACY_IDENTITY_TAKEN`, and two things happened to it.

It is half answered already. #992 moved the sentence off `graph.form_errors`:
`catalog_submit._game_form_refusal` states it as a non-field error of the Game
form, and `FormFields` draws it as the first row of the page, above Name.
`tests/test_catalog_submit.py::test_a_taken_legacy_identity_lands_on_the_game_form`
holds that. The `_blame` and `_answer` functions the issue reads no longer
exist. What remains is that the sentence names three things and points at none.

The rest of it is owned by the mirror, and the mirror is going. #889 takes
`Game.platform`, `Game.year_released`, the two unique constraints over them,
`games/catalog_compat.py` and `LEGACY_IDENTITY_TAKEN` together. After #889 the
identity a person collides with lives in the graph, so the refusal has no
successor to inherit a better placement. Work spent on it is work #889 removes.

**This specification states no change to that sentence or to where it lands.**
The verdict goes into #988 and into #601 beside it, so that a later reader finds
a decision rather than an omission. #601's follow-up line reads "a catalog
refusal lands in the wrong place, three ways"; it becomes two ways.

The three below stand after #599 closes.

## One validation, one answer

`CatalogGraphForm.is_valid()` reads its rows and then states what only the set
can say. It remembers nothing, so a second call runs `_validate_set()` again.

Measured, on a bound form asked twice:

```text
form_errors      LAST_EDITION_IN_FORM, LAST_EDITION_IN_FORM
block non-field  LAST_RELEASE, LAST_RELEASE
```

The three field-level sentences do not repeat. `_validate_names` and
`_validate_releases` each pass over a row that already carries an error, and on
the second call every blamed row does. The issue's own example — a doubled
`DUPLICATE_NAME_IN_FORM` — is therefore wrong; the defect is the two sentences
no guard covers.

**The form remembers the pass, not the answer.** A second call runs no
validation and writes no sentence. It reads the sentences that stand and states
the answer again. This distinction is the whole design: `answer()` puts a
service refusal on a row *after* `is_valid()` returned True, and
`catalog_submit` then re-renders the page. A remembered `True` would tell that
renderer the form is clean while a refusal sits on one of its rows.

The answer reads what the pass counted, under the pass's own rule: the set's
`form_errors`, each Edition block's errors, and each Release row's — a row
stated as going excepted, exactly as `reads_as_stated(row, going=...)` excepts
it now. So a sentence `answer()` adds lands in the answer, and a sentence on a
row nobody keeps does not.

Django's `Form.is_valid()` behaves this way already — it caches `cleaned_data`
and recomputes `self.is_bound and not self.errors` — and the rows inside this
form are Django forms. This makes the container agree with what it holds.

Two things follow. A test may ask twice. A renderer may ask at all, which is
what any later fix to the placement of a set-level sentence needs.

## A refused confirmation says its reason apart from the question

`confirm_and_apply` answers a refused POST with a 409 and the confirmation page
again. It states the reason by joining two sentences into one paragraph, and it
keeps only the first of them:

```text
message=f"{refusal} {message}" if refusal else message   # removal.py:55
return confirmation(refusal.messages[0], status=409)     # removal.py:76
```

The reason reads as part of the standing question. `ConfirmPage` renders
`message` inside a `<p>`, so the reason cannot carry its own shape.

**Today no URL reaches that branch.** Every `confirm_and_remove` caller acts
through `remove(instance)`, an `UPDATE` that raises nothing; the two direct
`confirm_and_apply` callers (`games/views/session.py:355`, `:376`) save a
Session. Only `tests/test_confirmation_refusals.py` gets there, through a
synthetic action. The one confirmation whose act can be refused —
`remove_game`, at `games/views/game.py:345` — does not use the branch:

```python
except CommandFailed as failure:            # playergame_writes.py:70
    messages.error(request, failure.message)
    return False
```

`confirm_and_apply` discards that return. A refused untracking therefore shows a
toast and **redirects as though it worked**. Fixing the rendering alone would
ship a page nobody can reach, so this specification fixes both.

`remove_game_for_request` refuses the way the helper's own contract already
states — "an `action` that refuses puts its sentence back on the confirmation".
It raises `ValidationError` carrying the command's sentence in place of the
toast, and returns nothing. Its two siblings, `track_game_for_request` and
`record_facts_for_request`, are unchanged: neither runs under a confirmation,
and a toast is right where the page stays.

**Superseded by #896's review.** The type is `CommandFailed`, and it is not
raised again: the one the command already stated rises. A second type threw
the status code away, and `ValidationError` is what a model raises when it
refuses underneath the act, which is a defect and not a refusal a person can
answer. `confirm_and_apply` reads `CommandFailed` alone.

One page then draws two lists. `remove_game` always states
`details=_removed_with_game(game)`, the sessions and purchases the removal
takes with it, and a refused POST puts the reason above the prompt while that
list stays below it. Both are `<ul>`s, and they do not read as one: the reason
stands above the question and the list below it, and `FieldErrors` draws its
own in `solid-danger` where `details` is plain. A heading over `details` is not
this issue's to write — the same heading would stand on the 200 this page
answers every other time, so it is a change to the confirmation, not to the
refusal.

`ConfirmPage` gains a third slot beside `message` and `details`: the refusal, a
`Sequence[str]`. It draws through `FieldErrors`, between the title and the
prompt, so a person reads the reason and then the question that stands. A
refused confirmation looks like a refused form, and no page states a second way
to draw a refusal. The docstring names all three slots and says why the reason
cannot ride inside `message`. `confirm_and_apply` passes `refusal.messages`
whole. The status stays 409, and a confirmation nothing refused is unchanged.

## One name key

The form, the service and `Platform.clean` each reduce an entered name to a
comparison key in Python. The database holds a different rule:

```text
UniqueConstraint(F("game"), Lower(Trim("name")), condition=live and non-empty)
```

`casefold()` is not `lower()`. Measured against the running database:

| name | `casefold()` | `str.lower()` | SQL `lower()` |
|---|---|---|---|
| `Straße` | `strasse` | `straße` | `straße` |
| `STRASSE` | `strasse` | `strasse` | `strasse` |
| `İ` | `i̇` | `i̇` | `i` |

So the form refuses `Straße` beside `STRASSE`, and the database accepts the
pair. The sentence a person reads is false, and no retry clears it.

`common/naming.py` states the key, and the three readers import it:

```python
type NameKey = str


def name_key(value: str) -> NameKey:
    """What the database compares two names by."""
    return value.strip().lower()
```

It lives in `common/` because `games/models.py` is one of the readers, and
`games/catalog_writes.py` imports `games.models` — a key kept there could never
travel back. The module holds no Django import, so nothing can cycle.

The three readers are `CatalogGraphForm._validate_names`
(`catalog_form.py:457`), `_refuse_taken_names` (`catalog_writes.py:196`) and
`Platform.clean` (`models.py:451`). Three functions, five statements of the
key: each of the first two states it twice, and `Platform.clean` compares a
name and a group.

`Platform.clean` is the same defect pointing the other way. It annotates
`Lower(Trim(...))` over both columns and compares that to `.casefold()`, so a
private Platform named `Straße` **passes** a shadow check against a shared
`STRASSE`. No constraint stands behind that method — "A private Platform cannot
shadow a shared Platform" is enforced by `clean()` and nothing else — so the
wrong row is written and stays. It is three lines of the same fix and it
outlives #599, so it is here.

One comparison stays exact and case-sensitive on purpose:
`catalog_writes.py:375` reads `stored.name.strip() != state.name.strip()` to
decide whether a stored row is being renamed. That is not a key and does not
change.

Two differences remain, and both are stated rather than closed:

- SQL `TRIM` takes spaces, and `str.strip()` takes every whitespace character.
  `EditionRowForm.clean_name` strips before anything else reads the name, so a
  name this form writes cannot differ. #782's importer writes no form. A
  Platform has no such promise: the strip is `CharField`'s, so it holds for
  what the form posts and not for a `Platform.objects.create()` a script
  writes. A name that holds a tab reads as one key in Python and another in
  the index. The fix does not widen this: `Platform.clean` strips in Python
  today too, so the gap stands exactly where it stood.
- Simple case mapping against full: `İ` lowercases to one character in SQL and
  two in Python, so Python reads `İ` and `i` as two names where the database
  reads one. For an Edition the direction is safe but the placement is worse
  than today's: the form now permits the pair, the insert refuses it, and
  `CONSTRAINT_ANSWERS["unique_live_edition_name_per_game"]` answers with
  `DUPLICATE_EDITION_NAME` as a Game-form sentence above Name rather than on the
  Edition row that stated it. #998 owns which row a duplicate names, and takes
  this residue with it. For a Platform there is no constraint, so an `İ`/`i`
  shadow pair stands; the shadow rule was already best-effort and stays so.

`docs/catalog.md` says "A name is unique among one Game's live Editions,
ignoring case and surrounding space". It becomes exact about which case rule:
the database lowercases, and simple case mapping is what both sides read.

The refusals themselves keep their words and their rows. #782 still owns #998.

## Boundary

`common/naming.py` (new), `common/components/primitives.py`,
`games/views/removal.py`, `games/views/playergame_writes.py`,
`games/catalog_form.py`, `games/catalog_writes.py`, `games/models.py`,
`docs/catalog.md`.

Not here: what any refusal says; where `LEGACY_IDENTITY_TAKEN` lands (dropped
above); which row a duplicate name blames (#998); the accessible name of a
Release row (#990); the one-way bin (#999).

## Acceptance

- `is_valid()` called twice states the errors of one call, `form_errors` and
  every row's own included.
- `is_valid()` called after `answer()` puts a sentence on a row states False.
- A refused confirmation draws its reason apart from the question, keeps every
  sentence the refusal carried, and still answers 409.
- A refused game removal renders that confirmation. It shows no toast and it
  does not redirect.
- Two Edition names the constraint accepts are accepted by the form and by the
  service, named concretely by the `Straße`/`STRASSE` pair.
- A private Platform named `Straße` is refused against a shared `STRASSE`.
- The one divergence the key does not close, `İ`, is held by a strict xfail, so
  closing it later cannot pass unnoticed.
- The existing duplicate-name refusals keep their behaviour.
- #988 and #601 record why the first defect is closed unbuilt.
- The full `make check` gate passes.
