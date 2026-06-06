"""Server-side HTML component library.

Split into core / primitives / domain / filters submodules; this package
re-exports the public API so ``from common.components import X`` keeps working.
"""

from common.utils import truncate

from common.components.core import (
    Component,
    HTMLAttribute,
    HTMLTag,
    _render_element,
    randomid,
)
from common.components.primitives import (
    A,
    AddForm,
    Button,
    ButtonGroup,
    CsrfInput,
    Div,
    H1,
    Icon,
    Input,
    Modal,
    ModuleScript,
    Popover,
    PopoverTruncated,
    SearchField,
    SimpleTable,
    TableHeader,
    TableRow,
    TableTd,
    paginated_table_content,
)
from common.components.domain import (
    GameLink,
    GameStatus,
    GameStatusSelector,
    LinkedPurchase,
    NameWithIcon,
    PriceConverted,
    PurchasePrice,
    SessionDeviceSelector,
    _resolve_name_with_icon,
)
from common.components.filters import (
    FilterBar,
    PurchaseFilterBar,
    SelectableFilter,
    SessionFilterBar,
)

__all__ = [
    "truncate",
    "Component",
    "HTMLAttribute",
    "HTMLTag",
    "_render_element",
    "randomid",
    "A",
    "AddForm",
    "Button",
    "ButtonGroup",
    "CsrfInput",
    "Div",
    "H1",
    "Icon",
    "Input",
    "Modal",
    "ModuleScript",
    "Popover",
    "PopoverTruncated",
    "SearchField",
    "SimpleTable",
    "TableHeader",
    "TableRow",
    "TableTd",
    "paginated_table_content",
    "GameLink",
    "GameStatus",
    "GameStatusSelector",
    "LinkedPurchase",
    "NameWithIcon",
    "PriceConverted",
    "PurchasePrice",
    "SessionDeviceSelector",
    "_resolve_name_with_icon",
    "FilterBar",
    "PurchaseFilterBar",
    "SelectableFilter",
    "SessionFilterBar",
]
