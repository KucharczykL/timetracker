import csv
from typing import TypeAlias

from games.models import Game

DataList: TypeAlias = list[dict[str, str]] | None


def read_csv(filename: str) -> DataList:
    with open(filename, "r") as csvfile:
        writer = csv.DictReader(csvfile)
        return writer


def import_data(data: DataList):
    matching_names = {}
    for line in data:
        name = line["name"]
        if name not in matching_names:
            # try exact match first
            try:
                game_id = Game.objects.get(name__iexact=name)
            except:
                pass
            matching_names[name] = game_id
    print(f"Exact matched {len(matching_names)} games.")


def import_from_file(filename: str):
    import_data(read_csv(filename))
