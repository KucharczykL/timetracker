from django import forms

from games.forms import INPUT_CLASS, SELECT_CLASS, apply_primitive_widget_classes


def test_stamping_applies_the_shared_control_classes_by_widget_type():
    fields: dict[str, forms.Field] = {
        "choice": forms.ChoiceField(choices=(("a", "A"),)),
        "text": forms.CharField(),
    }

    apply_primitive_widget_classes(fields)

    assert fields["choice"].widget.attrs["class"] == SELECT_CLASS
    assert fields["text"].widget.attrs["class"] == INPUT_CLASS
