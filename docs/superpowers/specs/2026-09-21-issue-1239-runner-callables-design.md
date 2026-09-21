# What the bulk runner asks of an act

An act gives the runner `scope`, `resolve`, `run` and `inverse`, and a question
of its own. This states the shapes each one takes. The code is in
`games/bulk_actions.py`.

## The row callables

`RunRow` and `UndoRow` are protocols, not `Callable` aliases. A `Callable` alias
cannot declare a keyword-only parameter.

```python
class RunRow[RowT: Model](Protocol):
    def __call__(
        self,
        actor: User,
        row: RowT,
        /,
        *,
        choice: ChoiceValue | None,
        idempotency_key: IdempotencyKey,
        correlation_id: uuid.UUID,
    ) -> RowOutcome: ...
```

`ChoiceValue` and `IdempotencyKey` are both text. The checker cannot compare
two text arguments in the same position, but it does compare their names.

The row is positional-only. Each act calls it something of its own — `session`,
`run`, `record` — and a protocol compares parameter names unless the mark is
there.

A protocol constrains the caller only: an implementation with positional
parameters accepts each call the protocol permits, thus the checker admits it.
`BulkAction.__post_init__` refuses such an implementation at the declaration.

`UndoRow` takes `undoes: uuid.UUID`, the batch it undoes, and no choice. One
slot for two facts would let a run's key and a batch's id stand in for each
other, and both are text.

`Leg` holds a `BoundRow`: the leg's builder binds its own fact, and the runner
gives each row only the two keys.

## The question

`offer` gives one of three values, and each has a name.

```python
type Offered = Control | RefusedAct | AsksNothing
```

A `Control` holds the node the confirmation shows. A `RefusedAct` holds one
sentence and draws no press. `AsksNothing` is for a resolve that found no rows.

`offer` cannot give bare text, because `Child` is `Node | str` in the component
system: text is a control as well as a refusal, and one type cannot say which.
A return type is compared against the declaration, thus the checker refuses
text here.

## Absence

`None` is the one spelling. `Leg` holds no choice, `BulkAction.choice` is
`None` for an act that asks nothing, and a row callable takes
`ChoiceValue | None`.

A callable that needs a choice and receives `None` raises `RowUnreadable`: the
runner settles before a row is reached, thus `None` there is a defect and not a
statement.
