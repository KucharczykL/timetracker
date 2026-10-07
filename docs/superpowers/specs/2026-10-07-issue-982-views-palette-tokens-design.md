# Raw palette in class strings

A class string states colour through semantic tokens: `text-heading`,
`text-body`, `bg-neutral-*` and the others in `common/input.css` and the
Flowbite theme. A raw palette utility, such as `text-slate-500` or
`dark:text-white`, does not follow the theme.

## The guard

`tests/test_color_tokens.py` refuses a raw palette utility. It walks the files
that the size guard walks, through `guarded_files()` in
`tests/test_typography_tokens.py`: the Python modules that build class strings
and `ts/**/*.ts`. One list states which files carry class strings. A second
list would drift from it.

`RAW_COLOR` matches a colour property, an optional side, and one of two forms:

- a Tailwind hue with a numeric stop (`bg-gray-50`, `ring-red-500`);
- `white` or `black` with no stop (`dark:text-white`, `bg-black/10`).

The second form ends at `(?![\w-])`. Thus `text-whitesmoke` does not match, and
an opacity suffix does. A semantic token has no stop, so it does not match. The
pattern does not see an arbitrary value such as `bg-[#fff]`.

## Opt-out

A line that holds `color-ok` is not checked. The marker is `# color-ok:
<reason>` in Python and `// color-ok: <reason>` in TypeScript. The guard reads
lines, so each line of a multi-line string carries its own marker. These hues
stay raw on purpose:

- the filter logic-chip states in `common/components/filters.py`;
- the game-status dots in `common/components/domain.py`;
- the dark hover of the green `ControlButton`, `emerald-800`, because the dark
  success scale stops at `success-strong`;
- the engraved `DropdownDivider` hairline, `bg-black/*`.

## Generated icons

`gen_icons` drops the root `class` of each snippet. `Icon()` states the icon
classes itself. Thus `common/components/icons_generated.py` holds no class, and
no marker goes into a generated file.

## Pages

A page wrapper states no text colour. `Body` carries `text-body`. An element
that must read as a heading states `text-heading` itself. An element that must
read as secondary text states `text-body-subtle`. A table states its own text
colour, so a wrapper colour does not reach a cell.

## Tests

- The self-check lists the forms that match and the tokens that do not.
- A test refuses a vacuous walk: both the Python half and the TypeScript half
  yield files.
- A test refuses a `class` on a generated icon root.
- `tests/test_rendered_pages.py` pins `text-heading` on the Game detail title
  and `text-body-subtle` on an empty section's sentence.
