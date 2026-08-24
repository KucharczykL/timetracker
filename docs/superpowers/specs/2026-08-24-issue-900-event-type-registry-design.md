# The event-type registry and payload validation

An event type is a module-level `EventSpec` constant: an event-type string, an
aggregate type, and a payload `TypedDict` carrying
`@with_config(ConfigDict(extra="forbid", strict=True))` — the only schema
configuration form that both enforces and type-checks. The spec is generic over
that schema, so `spec.new(aggregate_id=..., payload=...)` checks the payload
where it is built.

`EventTypeRegistry` holds registered specs. `register()` refuses a duplicate
event type, an empty or over-length name, an empty aggregate type, a schema that
is not a configured `TypedDict`, and any version but 1 — upcasting does not
exist, so a bump fails at import rather than at a later rebuild.

`LockedStream.append` resolves the spec in the registry by event-type string,
never from the spec the caller carries. It canonicalises the payload, validates
it, and stores pydantic's returned value, so a `float` field given `1` records
`1.0`. Every refusal precedes the rows and the head advance.

`RecordedEvent.from_row` sorts payload and source-metadata keys recursively.
Both paths build the envelope through it, so every projector reads one order.

`Projector.handles` keys on specs. `replay` refuses an unregistered type, or a
stored version that is not the registered one.

Payload fields hold only JSON-native types. `aggregate_type` is not a column.

Forecloses: an event-type string is permanent; `extra="forbid"` guards the top
level only; payload integers are unbounded; enforcement is writer-side only; a
historical version cannot be appended.

Follow-ups: #918 upcasting, #919 retired types, #920 `source_metadata`, #921
nested schemas.
