"""Roles a bare UUID plays."""

import uuid

#: A catalog game's key.
type GameId = uuid.UUID
#: A tracked game's key.
type PlayerGameId = uuid.UUID
type PlaythroughId = uuid.UUID
type HistoricalPlaytimeId = uuid.UUID
type PlayerSessionId = uuid.UUID
type ReleaseId = uuid.UUID
