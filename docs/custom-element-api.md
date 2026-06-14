# Custom Element API: Two patterns, one goal

## Pattern 1: Named builder (current, preferred)

A tag builder with auto-attached `Media`, created via `custom_element_builder()`:

```python
# definition (custom_elements.py)
SessionTimestampButtons = custom_element_builder("session-timestamp-buttons")

# usage (session.py)
SessionTimestampButtons(class_="form-row-button-group", hx_boost="false")[
    Button(data_target="timestamp_start", data_type="now", size="xs")["Set to now"],
    Button(data_target="timestamp_start", data_type="toggle", size="xs")["Toggle text"],
]
```

**Pros:** explicit dependency, visible import, fails loudly if builder deleted  
**Cons:** one line of ceremony per element

## Pattern 2: Element + registry (proposed, not implemented)

A global `CUSTOM_ELEMENT_MEDIA` dict in `core.py` that maps tag names to their `Media`. `register_element()` populates it automatically at import time, so `Element("session-timestamp-buttons")` silently picks up its JS dependency:

```python
# definition (custom_elements.py)
register_element("session-timestamp-buttons", "SessionTimestampButtons", EmptyProps)
# CUSTOM_ELEMENT_MEDIA["session-timestamp-buttons"] = Media(js=("dist/elements/...",))

# usage (session.py) — no builder import needed
Element("session-timestamp-buttons",
    [("class", "form-row-button-group"), ("hx-boost", "false")],
    children=[...],
)
```

**Pros:** one universal API — `Div(...)`, `Button(...)`, `Element("custom-tag")` all same pattern  
**Cons:** implicit dependency — deleting a `register_element()` call produces no error, just broken JS at runtime

## Recommendation

Start with Pattern 1 (named builders) — safe by default. Add Pattern 2 later if the ceremony becomes annoying. The two are **not mutually exclusive**: a named builder is just a thin wrapper around an `Element`; the registry can be added without changing any call sites.

## Quick reference

| Want | Write |
|------|-------|
| Plain HTML tag | `Div(class_="flex")["text"]` |
| Custom element (builder) | `SessionTimestampButtons(class_="...")[child]` |
| Raw element | `Element("custom-tag", attributes_list, children=[...])` |
| Builder from scratch | `custom_element_builder("tag-name")` |
