from typing import TYPE_CHECKING

from games.catalog_writes import save_private_game
from games.models import Game
from timetracker.temporal import TemporalValue

if TYPE_CHECKING:
    from games.forms import GameForm


def _year_value(year: int | None) -> TemporalValue | None:
    return TemporalValue.from_year(year) if year is not None else None


def save_legacy_game_form(form: "GameForm") -> Game:
    game = form.save(commit=False)
    return save_private_game(
        game=game,
        original_release_date=_year_value(game.original_year_released),
        release_date=_year_value(game.year_released),
        platform=game.platform,
    ).game
