with open("common/components.py", "r") as f:
    content = f.read()

# Count FilterBar functions to know which replacement targets which
n = content.count('("name", "filter"), ("value", escape(filter_json))')
print(f"Found {n} hidden filter inputs")

# Simple: after each hidden filter input, insert a search input
search_html = '''                    Component(tag_name="input", attributes=[
                        ("type", "text"), ("name", "filter-search"),
                        ("value", escape(search_val)),
                        ("placeholder", "Search\u2026"),
                        ("class", "block w-full rounded-base border border-default-medium "
                         "bg-neutral-secondary-medium text-sm text-heading p-2 mb-4 "
                         "focus:ring-brand focus:border-brand"),
                    ]),
'''

old = '''                    Component(tag_name="input", attributes=[
                        ("type", "hidden"), ("id", filter_input_id),
                        ("name", "filter"), ("value", escape(filter_json)),
                    ]),
                    Component(tag_name="div", attributes=['''

# Only replace occurrences in FilterBar functions (after 'def FilterBar' or 'def SessionFilterBar' or 'def PurchaseFilterBar')
# Find each occurrence and replace
import re
# Strategy: split by the old pattern, insert search_html between first two parts of each split
parts = content.split(old)
print(f"Split into {len(parts)} parts")

new_content = parts[0]
for i in range(1, len(parts)):
    # Check if this occurrence is inside a FilterBar function (not inside SelectableFilter)
    # Simple heuristic: the context before should contain 'FilterBar'
    chunk_before = parts[i-1][-500:] if len(parts[i-1]) > 500 else parts[i-1]
    is_filterbar = 'FilterBar' in chunk_before or 'filter_bar' in chunk_before.lower()
    if is_filterbar:
        new_content += old + search_html + parts[i]
    else:
        new_content += old + parts[i]

with open("common/components.py", "w") as f:
    f.write(new_content)

import ast
ast.parse(new_content)
print("OK")
