from django.test import SimpleTestCase

from common.components.primitives import YEAR_PICKER_CLASSES, YearPicker, control_button_class


class YearPickerTest(SimpleTestCase):
    def test_renders_in_house_calendar_contract(self):
        html = str(
            YearPicker(
                year=2024,
                available_years=(2023, 2024, 2025),
                url_template="/stats/__year__/",
            )
        )

        self.assertIn("<drop-down", html)
        self.assertIn('placement="bottom-end"', html)
        self.assertIn('submenu="false"', html)
        self.assertIn('behavior="date-calendar"', html)
        self.assertIn('data-toggle=""', html)
        self.assertIn('data-year-picker-toggle=""', html)
        self.assertIn('aria-expanded="false"', html)
        self.assertIn('data-menu=""', html)
        self.assertIn('role="group"', html)
        self.assertIn('aria-labelledby="year-picker-period"', html)
        self.assertIn('id="year-picker-period"', html)
        self.assertIn('aria-label="Previous decade"', html)
        self.assertIn('aria-label="Next decade"', html)
        self.assertIn('data-year-picker-grid=""', html)
        self.assertIn('data-year-picker-template="year"', html)
        self.assertNotIn("year-picker-input", html)
        self.assertNotIn("datepicker.umd.js", html)
        self.assertNotIn("_DATEPICKER_MEDIA", html)

    def test_year_cell_classes_are_complete_control_button_variants(self):
        self.assertEqual(
            set(YEAR_PICKER_CLASSES),
            {"default", "selected", "adjacent", "disabled", "adjacent-disabled"},
        )
        for variant, classes in YEAR_PICKER_CLASSES.items():
            self.assertIn("w-14 shrink-0", classes, variant)
            self.assertIn("min-h-control", classes, variant)
            self.assertIn("rounded-base", classes, variant)

        self.assertIn(control_button_class(variant="ghost"), YEAR_PICKER_CLASSES["default"])
        self.assertIn(
            control_button_class(color="blue", variant="filled"),
            YEAR_PICKER_CLASSES["selected"],
        )
        for variant in ("adjacent", "disabled", "adjacent-disabled"):
            self.assertIn(control_button_class(variant="ghost"), YEAR_PICKER_CLASSES[variant])
            self.assertIn("opacity-40", YEAR_PICKER_CLASSES[variant])
