# What the bulk runner asks of an act

An act gives the runner four callables. Two of them take arguments the type
checker cannot tell apart, and one uses its success type as its refusal
channel. This states the shapes that close both. The code is in
`games/bulk_actions.py`.

## The row callables

`RunRow` and `UndoRow` are protocols, not `Callable` aliases. A `Callable`
alias cannot declare a keyword-only parameter, and positional arguments are
what the checker cannot help with here.

```python
class RunRow[RowT: Model](Protocol):
    def __call__(
        self,
        actor: User,
        row: RowT,
        /,
        *,
        choice: ChoiceValue,
        idempotency_key: IdempotencyKey,
        correlation_id: uuid.UUID,
    ) -> RowOutcome: ...
```

`UndoRow` has the same shape and takes a `uuid.UUID` for its row.

`ChoiceValue` and `IdempotencyKey` are both text. As positional arguments they
are exchangeable and no check refuses the exchange. As keywords they are not.
The actor and the row stay positional, because their types differ.

## The question

`offer` gives one of two values, and each has a name.

```python
@dataclass(frozen=True, slots=True)
class Control:
    node: Node


@dataclass(frozen=True, slots=True)
class RefusedAct:
    sentence: str


type Offered = Control | RefusedAct
```

Before, `offer` gave `Node | str` and text was the refusal. But `Child` is
`Node | str` in the component system, so text is also a control. An act whose
control was text showed a refusal page instead.

## Absence

One spelling. `Leg.choice` is `ChoiceValue | None`, and `None` is "this act
asks nothing". `BulkAction.choice` and the value the waypoint carries are
already `None` for the same idea. The row callables take `ChoiceValue | None`.

## What does not change

The runner asks the same questions in the same order. An act states the same
facts. No event, no route and no page is different. Every existing test holds,
after its call sites state keywords.
