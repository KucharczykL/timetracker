from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Exists, F, OuterRef, Q

from games.management.library_scope import (
    LibraryScope,
    add_scope_arguments,
    scoped_libraries,
)
from games.models import (
    Device,
    FilterPreset,
    Game,
    LibraryEntry,
    Platform,
    PlayerSession,
    PurchaseConversionState,
    UserLibraryPreferences,
    UserPreferences,
)
from games.projections import (
    cross_library_violations,
    release_game_violations,
    valuation_library_violations,
)


class Command(BaseCommand):
    help = "Read and validate library ownership without changing any data."

    def add_arguments(self, parser):
        add_scope_arguments(parser, verb="Audit")

    def handle(self, *args, **options):
        libraries = scoped_libraries(LibraryScope.from_options(options))
        library_ids = [library.pk for library in libraries]
        user_ids = [library.user_id for library in libraries]

        missing_library_user_ids = []
        if options["all_libraries"]:
            missing_library_user_ids = list(
                get_user_model()
                .objects.filter(library__isnull=True)
                .values_list("pk", flat=True)
            )
        self.stdout.write(
            "Scope: " + ", ".join(str(library.pk) for library in libraries)
        )
        self.stdout.write("Direct owners:")
        direct_counts = (
            ("games", Game.objects.filter(library_id__in=library_ids).count()),
            ("devices", Device.objects.filter(library_id__in=library_ids).count()),
            (
                "entries",
                LibraryEntry.objects.filter(library_id__in=library_ids).count(),
            ),
            (
                "private platforms",
                Platform.objects.filter(library_id__in=library_ids).count(),
            ),
            (
                "filter presets",
                FilterPreset.objects.filter(library_id__in=library_ids).count(),
            ),
        )
        for label, count in direct_counts:
            self.stdout.write(f"  {label}: {count}")

        self.stdout.write("Derived relationships:")
        derived_counts = (
            (
                "sessions",
                PlayerSession.objects.filter(library_id__in=library_ids).count(),
            ),
        )
        for label, count in derived_counts:
            self.stdout.write(f"  {label}: {count}")

        violations = self._cross_library_violations(library_ids)
        self.stdout.write(f"Cross-library links: {len(violations)}")
        for violation in violations:
            self.stdout.write(f"  {violation}")

        preference_violations = [
            f"UserLibrary missing for user {user_id}"
            for user_id in missing_library_user_ids
        ]
        preference_user_ids = set(
            UserPreferences.objects.filter(user_id__in=user_ids).values_list(
                "user_id", flat=True
            )
        )
        preference_library_ids = set(
            UserLibraryPreferences.objects.filter(
                library_id__in=library_ids
            ).values_list("library_id", flat=True)
        )
        conversion_library_ids = set(
            PurchaseConversionState.objects.filter(
                library_id__in=library_ids
            ).values_list("library_id", flat=True)
        )
        for library in libraries:
            if library.user_id not in preference_user_ids:
                preference_violations.append(
                    f"UserPreferences missing for user {library.user_id}"
                )
            if library.pk not in preference_library_ids:
                preference_violations.append(
                    f"UserLibraryPreferences missing for library {library.pk}"
                )
            if library.pk not in conversion_library_ids:
                preference_violations.append(
                    f"PurchaseConversionState missing for library {library.pk}"
                )

        if preference_violations:
            self.stdout.write(
                f"Preference structure: {len(preference_violations)} violation(s)"
            )
            for violation in preference_violations:
                self.stdout.write(f"  {violation}")
        else:
            self.stdout.write("Preference structure: valid")

        violation_count = len(violations) + len(preference_violations)
        if violation_count:
            raise CommandError(f"Ownership audit found {violation_count} violation(s).")
        self.stdout.write(self.style.SUCCESS("Ownership audit passed."))

    @staticmethod
    def _cross_library_violations(library_ids):
        """Every relation outside the projections.

        The five loops below are hand-written because each names its own
        join path, and one of them reads an M2M through table. Every
        reference out of a projection is derived instead, from the
        registry `games.E009` holds complete; a session's device is one.
        """
        violations = []
        for game_id, platform_id in (
            Game.objects.filter(
                Q(library_id__in=library_ids) | Q(platform__library_id__in=library_ids),
                platform__library__isnull=False,
            )
            .exclude(platform__library_id=F("library_id"))
            .values_list("pk", "platform__id")
        ):
            violations.append(f"Game.platform: game {game_id}, platform {platform_id}")
        for game_id, parent_id in (
            Game.objects.filter(
                Q(library_id__in=library_ids) | Q(parent__library_id__in=library_ids),
                parent__library__isnull=False,
            )
            .exclude(parent__library_id=F("library_id"))
            .values_list("pk", "parent__id")
        ):
            violations.append(f"Game.parent: game {game_id}, parent {parent_id}")
        #: A key, not a relation.
        foreign_device = Device.objects.filter(
            pk=OuterRef("default_device_id")
        ).exclude(library_id=OuterRef("library_id"))
        for library_id, device_id in UserLibraryPreferences.objects.filter(
            Q(library_id__in=library_ids)
            | Q(
                default_device_id__in=Device.objects.filter(
                    library_id__in=library_ids
                ).values("pk")
            ),
            Exists(foreign_device),
        ).values_list("library_id", "default_device_id"):
            violations.append(
                "UserLibraryPreferences.default_device: "
                f"library {library_id}, device {device_id}"
            )
        violations.extend(cross_library_violations(library_ids))
        violations.extend(release_game_violations(library_ids))
        violations.extend(valuation_library_violations(library_ids))
        return violations
