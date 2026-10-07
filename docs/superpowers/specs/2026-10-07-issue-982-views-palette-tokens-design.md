# Raw palette in class strings

A class string states colour through semantic tokens: `text-heading`,
`text-body`, `bg-neutral-*` and the others in `common/input.css` and the
Flowbite theme. A raw palette utility, such as `text-slate-500` or
`dark:text-white`, does not follow the theme.

## The guard

`tests/test_color_tokens.py` refuses a raw palette utility. It walks the files
that the size guard walks, through `guarded_files()` in
`tests/test_typography_tokens.py`: every `.py` under `common/` and `games/`,
migrations and management commands aside, and `ts/**/*.ts`. The walk names
packages, not modules, so a new module is guarded at once. A test refuses a
guarded package that is not a directory.

`RAW_COLOR` matches a colour property, an optional side, and one of three forms:

- a Tailwind hue with a numeric stop (`bg-gray-50`, `ring-red-500`);
- `white` or `black` with no stop (`dark:text-white`, `bg-black/10`);
- an arbitrary colour value (`bg-[#fff]`, `text-[color:…]`).

The second form ends at `(?![\w-])`. Thus `text-whitesmoke` does not match, and
an opacity suffix does. A semantic token has no stop, so it does not match.

## Opt-out

The marker is `# color-ok: <reason>` in Python and `// color-ok: <reason>` in
TypeScript. The reason names each hue it admits (`teal`, `black`, `arbitrary`).
A match whose hue the reason does not name still fails, so a new hue on a
marked line fails. A marker with no reason admits nothing. The guard reads
lines, so each line of a multi-line string carries its own marker. The size
guard's `type-ok:` marker also requires a reason. These hues stay raw on
purpose:

- the filter logic-chip states in `common/components/filters.py`;
- the game-status dots in `common/components/domain.py`;
- the dark hover of the green `ControlButton`, `emerald-800`, because the dark
  success scale stops at `success-strong`;
- the engraved `DropdownDivider` hairline, `bg-black/*`.

## Generated icons

A snippet's root `<svg>` states no `class`. `gen_icons` refuses a snippet that
does, and names the file. `Icon()` states the icon classes itself. Thus
`common/components/icons_generated.py` holds no class, and no marker goes into
a generated file.

## Pages

A page wrapper states no text colour. `Body` carries `text-body`. An element
that must read as a heading states `text-heading` itself. An element that must
read as secondary text states `text-body-subtle`. A table states its own text
colour, so a wrapper colour does not reach a cell.

## Tests

- The self-check lists the forms that match and the tokens that do not.
- A test states which colours a marker admits.
- A test refuses a vacuous walk: both the Python half and the TypeScript half
  yield files.
- A test refuses a `class` on a generated icon root, and one states that
  `gen_icons` refuses a snippet with one.
- `tests/test_rendered_pages.py` pins `text-heading` on the Game detail title
  and `text-body-subtle` on an empty section's sentence.
