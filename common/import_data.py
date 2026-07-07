import csv
from typing import TypeAlias

from games.models import Game

DataList: TypeAlias = list[dict[str, str]] | None


def read_csv(filename: str) -> DataList:
    with open(filename, "r") as csvfile:
        reader = csv.DictReader(csvfile)
        return list(reader)


def import_data(data: DataList):
    matching_names = {}
    if data is None:
        return
    # Bound to a name rather than written inline as
    # `except (Game.DoesNotExist, Game.MultipleObjectsReturned):` because ruff
    # 0.15.x's formatter rewrites the inline tuple into the Python-2
    # `except A, B:` form, which is a SyntaxError on Python 3.
    lookup_errors = (Game.DoesNotExist, Game.MultipleObjectsReturned)
    for line in data:
        name = line["name"]
        if name not in matching_names:
            # try exact match first
            try:
                game_id = Game.objects.get(name__iexact=name)
            except lookup_errors:
                game_id = None
            matching_names[name] = game_id
    print(f"Exact matched {len(matching_names)} games.")


def import_from_file(filename: str):
    import_data(read_csv(filename))
