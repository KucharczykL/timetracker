# One library-scoped resolver for the UUIDs a command carries

A command carries a UUID, not a model instance. `_encode_command_value` refuses
an unknown type, and `canonical_command_input` copies every field into the
fingerprint. Only `build` holds the library context. Therefore only `build` can
refuse a cross-library reference.

`library_row` in `games/commands/scope.py` is that refusal. It takes the
context, the caller's queryset, a `Refusal`, and the lookup. It applies
`library=context.library` itself. The caller passes no library, so the caller
cannot forget one.

```python
def library_row[RowT: Model](
    context: CommandContext,
    reads: QuerySet[RowT],
    refusal: Refusal,
    **lookup: object,
) -> RowT:
```

The helper catches `ObjectDoesNotExist`, because a generic queryset cannot name
the concrete class. It does not catch `MultipleObjectsReturned`. Each lookup is
unique. A second row is a defect, and its traceback is the answer to one.

The helper does not read `removed_at`. It returns a removed row. Every restore
command resolves first and reads the mark after.

## The refusal is a value

`Refusal` holds two sentences. `message` reaches a log and may name an id.
`sentence` is the only thing a person sees. Its `raises` field names a
`CommandRejected` subclass. `PlayerGameNotTracked` is the one subclass in use,
because the write path answers that case by tracking the game.

Each caller writes both sentences. No sentence is generated from a model name.
A refusal names no id, so another library's row and a missing row answer alike.

## The callers

`tracked_game` and `library_playthrough` are the two callers. Both resolve one
row inside one library.

`TrackGame._visible_game` is not a caller. It reads the shared catalog as well
as the library, and it reads live rows only. `Game.objects.visible_to(library)`
is the read layer's word for that shape. `library_row` scopes to one library and
returns removed rows, so it cannot express it.

A read that counts rows, or that may answer `None`, is not a caller either. It
states `library=` itself.

## The guard

`tests/test_command_scope_guard.py` walks `games/commands/` with `ast`. It
reports a `.get()` whose attribute chain is rooted at a manager and names no
verb from `SCOPING_VERBS`. `scope.py` is exempt. `ALLOWED_FILES` maps a path to
a reason. A self-test proves the rule on a string.

The guard sees the resolve shape only. It cannot see a dropped `library=` in a
`filter()`.

## Deferred

A `visible_row` helper is not built. Two querysets state `visible_to`, and the
command layer calls it once. Build it when a second command family resolves a
`visible_to` model.
