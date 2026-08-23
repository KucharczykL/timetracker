"""The projection families the append path folds every event through.

One module per family, each defining a `Projector` subclass that registers
itself on import. `GamesConfig.ready()` imports this package, so a family is
live once its module is imported here.

Empty until the first evented domain lands; the machinery it builds on is
`games.events.projection`.
"""
