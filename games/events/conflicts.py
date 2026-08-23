"""The one base for command failures a person can be shown and asked to act on.

It lives alone here so `idempotency` can raise a subclass while `retry` raises
another, without either module importing the other.
"""


class CommandConflict(Exception):
    """A command did not run because another one was in the way.

    The leaves disagree about what to do next: an exhausted retry budget means
    trying again may work, a reused key over different input means it never
    will.
    """
