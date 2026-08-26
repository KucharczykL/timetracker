"""The commands a library issues, one module per aggregate.

A command is a frozen dataclass whose fields are its canonical input; nothing
here appends. `games.events.dispatch` is the only entry point that runs one.
"""
