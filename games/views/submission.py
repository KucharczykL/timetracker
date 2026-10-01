"""A one-click form's key."""

import uuid

from common.components import Input
from common.components.core import Node

#: The one-click form's hidden key field.
SUBMISSION_FIELD = "submission"


def submission_input() -> Node:
    """A fresh key: a double press records once."""
    return Input(type="hidden", name=SUBMISSION_FIELD, value=str(uuid.uuid7()))
