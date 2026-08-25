# Durable references in event payloads

An event is immutable. A row that an event refers to is not immutable. Each
payload keeps two items for each row that it refers to: the stable UUID of the
row, and a small snapshot of the display data.

The snapshot is historical data. It is not a second identity. It is not the
source of the current display. A rename of a Platform changes every screen. Only
the audit trail keeps the earlier words.

The code is in `games/events/references.py`.

## The reference value

`Reference` is a TypedDict with four fields.

| Field | Content |
|---|---|
| `kind` | The name of the reference kind, for example `catalog.game` |
| `id` | The UUIDv7 of the row, as canonical text |
| `label` | The primary display text, for example `Steam Deck` |
| `detail` | More display text, or `""` |

Each field holds text. Because of this, a reference goes through
`canonical_json` with no change, and strict validation accepts it with no type
change.

`ReferenceId` refuses text that is not a canonical UUIDv7. An uppercase form, a
form in braces, a URN form, and a form without hyphens are all incorrect. The
validator does not correct the text. An append records the result of the
validation. If the validator corrected the text, the record would not agree with
the data that the command supplied.

Do not use `timetracker.uuidv7.UUIDv7` for a payload field. In strict mode,
pydantic does not send text to a `uuid.UUID` schema. Also, the result of that
type is a `uuid.UUID` object, and JSONB cannot store it.

`detail` is `""` when the kind has no more data to show. `detail` is never
absent. Each reference in the record has the same four fields.

## Reference kinds

A `ReferenceKind` is the full declaration for one model that events refer to. It
has a name, a model, a capture function, and a resolution.

The resolution has two values:

- `REQUIRED` — a replay must find the row. The retention policy keeps the row.
- `EVIDENCE_ONLY` — the snapshot is sufficient. A replay does not look for the
  row.

The resolution is a property of the kind, not of the payload field. There is one
location to read the policy from, and one location for the retention policy to
attach to. That policy is in `games/retention.py`; see
[Retaining a referenced row](event-retention.md).

`ReferenceKindRegistry` keeps an index by name and an index by model. A payload
holds the name. A command holds the model instance. The registry refuses a
second kind with the same name, a second kind for the same model, and an empty
name.

The default registry has three kinds. All three are `REQUIRED`.

| Name | Model | `label` | `detail` |
|---|---|---|---|
| `device` | `Device` | `name` | `type` |
| `catalog.game` | `Game` | `name` | `year_released`, or `""` |
| `catalog.platform` | `Platform` | `name` | `group` |

`Edition` and `Release` have no kind. Neither model has a display field of its
own. A snapshot of one of these models needs a join to a parent model.

To make a reference, call `capture_reference(instance)`. This is the only call
that a command makes.

## Declaration and enumeration

A payload schema declares a reference with one of these annotations:

- `Reference`
- `Reference | None`
- `list[Reference]`
- `NotRequired[…]` around one of the three annotations above

`reference_fields(payload)` reads the annotations. It returns a map of the field
name to the arity. The map comes from the annotations, and not from a second
declaration. A change to a field name cannot leave a reference that no code
enumerates.

`reference_fields` refuses a reference in all other positions. A reference in a
`dict` value and a reference in a different TypedDict are two examples. The
function raises `ReferenceFieldUnsupported`. A silent skip would hide the
reference from the replay check.

`references_in(payload, fields)` gives one `FoundReference` for each reference. A
`NotRequired` field that the payload does not have gives no result. An optional
field with the value `None` gives no result.

To read the policy for a reference, use
`kinds.kind_for(value["kind"]).resolution`.

## The event type registry

The vocabulary module imports the references module. The references module does
not import the vocabulary module.

- `EventTypeRegistry` takes a `ReferenceKindRegistry`. The default is
  `DEFAULT_REFERENCE_KINDS`.
- `register()` calculates the reference fields one time, and keeps them with the
  registered type.
- `validate()` refuses a payload that names a kind that the registry does not
  have. The error is a `PayloadInvalid`. This check occurs at the append,
  because an incorrect kind name in the trail stays there permanently.
- The readers are `reference_fields_for(event_type)`,
  `references_in(event_type, payload)`, and `reference_kinds`.

The append, dispatch, projection, and rebuild modules hold no reference code.
All payload validation goes through the registry.

## Limits

This contract applies to the payload only. These items are not part of it:

- the resolution of references during a replay, and the report of the failures;
- the display of a snapshot in the audit history;
- a resolver that limits a UUID to one library.

The retention policy for a row that an event refers to left this list: it is
in [Retaining a referenced row](event-retention.md).

The contract uses the existing payload column. It needs no migration and no
schema change.
