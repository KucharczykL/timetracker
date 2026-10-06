# A form states the facts its opener knows

Issue #1516, part of #1485.

A link that opens a form page can state a fact: a field value that the
opener knows. The form does not ask for that field. It shows the value
in a locked row.

## Rule

A fact locks. A prefill stays editable. A form declares a field as a
fact only where an editable field would contradict the opener, or where
the words of the opener already name the value. To change a fact, open
the page without it. An edit view passes no facts, because a stored row
states its own values.

## Carrier

A fact is a query parameter. Its name is the html name of the field:
`/session/add?game=<uuid>`. `action_url(..., facts=...)` writes it. A
form page has no `action`, so its POST sends the query again. The
server reads the fact from the query on GET and on POST.

A path argument stays for the subject of a route, for example the entry
of Add purchase.

## Form

A form opts in with `OpenerFactsMixin` (`common/opener_facts.py`), an
`opener_fields` tuple and a `facts=` keyword. The form calls
`state_opener_facts(facts)` after it builds its fields and before it
reads a `BoundField`. The mixin raises if a `BoundField` already holds
the initial value.

For each declared field in the query:

- A fixed fact sets the initial value and `disabled`. Django then
  cleans the initial value and ignores the posted value.
- A malformed value leaves the field editable, logs one WARNING on
  `games.opener_facts`, and shows "Pick one." after the control.
- A row that the field queryset does not hold answers 404 on GET. On
  POST, the picker shows `invalid_choice` and keeps the other input.

`fix_field(name, value)` fixes an implied fact with no row: Add game
fixes `parent` to none when Kind is a main game.

## Rendering

`FormFields` renders a fact as a `<dl>` row: the label, then the value
in `field_box_class(..., look="fixed")` with a lock icon. The editable
field box and the fixed box share one function, so their size cannot
diverge. `FormFields` writes the hidden input itself without
`disabled`, so `FormData` readers such as the run picker see the value.

## Consumers

| Page | Opener | Fact |
| --- | --- | --- |
| Add game | The + on "Add-on of" | `kind=main`, title from `addon` |
| Add session | "Log this game" | `game` |
| Add playthrough | Game detail | `game` |
| Add to library | Game detail, "Submit & Add to library" | `game` |

`DialogCreate(params=...)` puts literal values in the href of the +.
`<search-select>` sets field values in the query when it connects and on
each input.

## Follow-up issues

- #1526: a picker's + prefills its typed text.
- #1527: Game detail offers "Add add-on".
