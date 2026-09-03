"""The External references area of a record's form.

One field per registered provider, because a provider issues one
identity per record. Registering a policy in
`games/external_references.py` adds a field and nothing else, thus
no form, renderer or view names a provider.
"""

from collections.abc import Mapping
from typing import cast

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Model

from games.external_references import (
    PROVIDER_POLICIES,
    CatalogTarget,
    ReferencesRefused,
    state_external_references,
)
from games.forms import apply_primitive_widget_classes
from games.models import ExternalReference, UserLibrary


def reference_field_name(provider: str) -> str:
    """``reference_field_name("wikidata")`` is ``"reference_wikidata"``."""
    return f"reference_{provider}"


class ReferenceSetForm(forms.Form):
    """Every external reference of one record, as one bound thing.

    `target` is None on an Add page, where the record does not
    exist yet; `bind()` names it once the submit has made it.

    The fields are built after ``super().__init__()``, thus out of
    :class:`PrimitiveWidgetsMixin`'s reach; the stamping call the
    mixin would have made is here instead.
    """

    def __init__(
        self,
        data: Mapping[str, str] | None,
        *,
        target: CatalogTarget | None,
        library: UserLibrary,
    ) -> None:
        self.target = target
        self.library = library
        initial = {} if target is None else self._stored(target)
        super().__init__(data, initial=initial)
        for provider, policy in PROVIDER_POLICIES.items():
            self.fields[reference_field_name(provider)] = forms.CharField(
                required=False,
                max_length=255,
                label=policy.label,
                help_text=policy.hint,
            )
        apply_primitive_widget_classes(self.fields)

    def _stored(self, target: CatalogTarget) -> dict[str, str]:
        """The keys this record holds, under their field names."""
        column = ExternalReference.TARGET_FIELDS_BY_MODEL[type(target)]
        held = ExternalReference.objects.filter(
            removed_at__isnull=True, **{column: target.pk}
        ).values_list("provider", "provider_key")
        return {
            reference_field_name(provider): provider_key
            for provider, provider_key in held
        }

    def clean(self) -> dict[str, object]:
        """Each policy's own sentence, on its own box."""
        cleaned = cast(dict[str, object], super().clean())
        for provider, policy in PROVIDER_POLICIES.items():
            name = reference_field_name(provider)
            raw = cast(str, cleaned.get(name, "")).strip()
            if not raw:
                cleaned[name] = ""
                continue
            try:
                cleaned[name] = policy.normalize_key(raw)
            except ValidationError as refusal:
                self.add_error(name, refusal.messages[0])
        return cleaned

    def stated_keys(self) -> dict[str, str]:
        """What every box says, under its provider."""
        return {
            provider: cast(
                str, self.cleaned_data.get(reference_field_name(provider), "")
            )
            for provider in PROVIDER_POLICIES
        }

    def bind(self, target: CatalogTarget) -> None:
        """Name the record a submit just made."""
        self.target = target

    def write(self) -> None:
        """One statement of the whole set."""
        assert self.target is not None, "bind() names a new record first."
        state_external_references(
            target=self.target, library=self.library, keys=self.stated_keys()
        )

    def answer(self, refusal: ValidationError) -> bool:
        """Put the sentence on the box that stated it."""
        if not isinstance(refusal, ReferencesRefused):
            return False
        name = (
            None if refusal.provider is None else reference_field_name(refusal.provider)
        )
        self.add_error(name, refusal.messages[0])
        return True


def submitted_or_form_error(
    form: forms.ModelForm, references: ReferenceSetForm
) -> Model | None:
    """Write a record and its references, or answer the refusal.

    One transaction. `IntegrityError` is not caught here: a
    constraint the reference write loses is read by
    `state_external_references`, which states it as a
    `ReferencesRefused` naming the box, thus what reaches this
    boundary is already a `ValidationError`.
    """
    try:
        with transaction.atomic():
            record = form.save()
            references.bind(record)
            references.write()
    except ValidationError as refusal:
        if references.answer(refusal):
            return None
        raise
    return record
