from django.test import SimpleTestCase

from games.models import Game, game_display_key


class GameDisplayOrderTest(SimpleTestCase):
    def test_fields_are_local_non_null_columns_ending_in_the_key(self):
        """Python sorts on them too, so no path, no null, a total order."""
        fields = [Game._meta.get_field(name) for name in Game.DISPLAY_ORDER_FIELDS]
        for field in fields:
            self.assertFalse(field.is_relation, field.name)
            self.assertFalse(field.null, field.name)
        self.assertTrue(fields[-1].primary_key)

    def test_key_breaks_a_full_tie_on_the_id(self):
        earlier = Game(name="Doom", sort_name="doom")
        later = Game(name="Doom", sort_name="doom")
        self.assertLess(earlier.id, later.id)
        self.assertEqual(
            sorted([later, earlier], key=game_display_key), [earlier, later]
        )
