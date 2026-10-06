# A form states the facts its opener knows

Issue #1516, part of #1485.

## Rule

A link can state a field value. The form shows it in a locked row. A
fact locks; a prefill stays editable. A form declares a fact only where
an editable field would contradict the opener, or where the words of the
opener name the value. To change a fact, open the page without it. An
edit view passes no facts.

## Carrier

A fact is a query parameter. Its name is the html name of the field:
`/session/add?game=<uuid>`. `action_url(..., facts=...)` writes it and
refuses a fact named `origin`. A form page has no `action`, so its POST
sends the query again; the form dialog sets `action` to its own URL. The
server reads the fact from the query on GET and on POST. A path names
only the subject of a route.

## Form

A form opts in with `OpenerFactsMixin` (`common/opener_facts.py`), an
`opener_fields` tuple and a `facts=` keyword. The form calls
`state_opener_facts(facts)` once, after it builds its fields and before
it reads a `BoundField`. Otherwise the mixin raises.

`form.facts` maps each field to one state: `Fixed(value, statement)` or
`Refused(sentence)`. `form.stated(name, kind)` reads a fixed value and
raises on a value of another type.

For each declared field in the query:

- A fixed fact sets the initial value and `disabled`. Django ignores
  the posted value.
- An empty, repeated or malformed value, or a row outside the field
  queryset, is refused. The field stays editable, one WARNING goes to
  `games.opener_facts`, and "… Pick one." follows the control. A bad
  link never answers 404.

`fix_field(name, value)` fixes an implied fact with no row: Add game
fixes `parent` to none when Kind is a main game.

## Rendering

`FormFields` reads `form.facts` (`StatesFacts`). A fact renders as a
`<dl>` row: the label, then the value in `field_box_class(...,
look="fixed")` with a lock icon, the same box as an editable field.
`FormFields` writes the hidden input without `disabled`, so `FormData`
readers see it. A fact with no statement renders the hidden input alone;
its errors join the form errors with the field label.

## Consumers

| Page | Opener | Fact |
| --- | --- | --- |
| Add game | The + on "Add-on of" | `kind=main`, title from `addon` |
| Add session | "Log this game" | `game` |
| Add playthrough | Game detail | `game` |
| Add to library | Game detail; Add game's "Submit & Add to library" | `game` |

Game detail of a shared catalog game states no game: session and run
forms take owned games only. `DialogCreate(params=...)` puts literals in
the + href; `<search-select>` sets field values on connect and input.

## Follow-up issues

- #1526: a picker's + prefills its typed text.
- #1527: Game detail offers "Add add-on".
