"""One module per projection concern; importing registers it.

A family may hold more than one, so this is not one module per family:
`CURRENT_STATE` holds both PlayerGames and Playthroughs.
"""

from games.projectors import playergame, playthrough  # noqa: F401
