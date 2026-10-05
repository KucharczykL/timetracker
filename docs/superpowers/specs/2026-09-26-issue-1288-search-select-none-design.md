# A SearchSelect that holds "none"

A single-select `SearchSelect` can take `none_label`. The label names a pinned
row, for example "No device" or "Unspecified". A pick of the row holds
**none**. None is a committed value. It is not **nothing picked**, which is the
state while a person types into the box.

## Prior art

A native `<select>`, MUI Select, Base UI Select and Linear show "none" as a
row. A pick holds the row. Radix Select and React Aria Select have no such
row, so their callers add one.

## States

| State | Box | Hidden input | × |
|---|---|---|---|
| a value | its label | `name=<value>` | shown |
| none | `none_label` | `name=""`, `data-search-select-none` | hidden |
| nothing picked | typed text | absent | shown while text is present |

- A value of `None` renders none. So does a value that the resolver cannot
  find.
- A click or Enter on the row holds none.
- × holds none, from a value and from typed text.
- The first keystroke drops a value or none to nothing picked.
- A change to a field that the picker depends on drops a value to none. A held
  none stays.
- `setOptions` drops a value that it no longer offers to none.
- An autofocused picker that holds none opens, as an empty one does.
- With an empty query, the default highlight skips the none row, so Enter
  never picks none by accident.

## The row

The row uses its own hook, `data-search-select-none-option`, so filter mode
does not change. The row is first. The text filter and a server answer do not
remove it. A query highlights the row only when the query equals its label.
Its label offers no Create row. The element assigns ids at init, so the
row renders no `id`, and a cloned prototype carries no duplicate.

## The wire

None posts the key with `""`. Nothing picked does not post the key. Django reads
both as `None`. A three-state bulk form can read `""` as none and a missing key
as "leave as it is".

## The event

`search-select:change` has `none: boolean`. A pick of none and × send
`values: []`, `last: null` and `none: true`. A first keystroke sends
`values: []` and `none: false`. `values` never contains `""`. A picker without
`none_label` always sends `none: false`.

## Refusals

`none_label` with `multi_select` or `panel` raises `ValueError`.
`SearchSelectWidget` raises `ValueError` on render when the field is required.

## Consumers

| Form | Field | Label |
|---|---|---|
| `SessionForm` | `device` | No device |
| `HistoricalPlaytimeForm` | `device` | No device |
| `PurchaseForm` | `platform` | Unspecified |

Edit Session shows the device that the session holds. The library default
device fills Add Session only.

On a purchase form, a game pick fills Platform until the person commits a
platform, "Unspecified" or ×. A keystroke is not a commit.

## Out of scope

- Live settings and the Library default device: #1289.
- The ⊘ toggle of bulk forms: #1302.
- The fixed-choice adapter: #1301. In a two-state form, its empty choice is
  `none_label`.
