from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db.models import F

from games.models import (
    Device,
    FilterPreset,
    Game,
    GameStatusChange,
    Platform,
    PlayEvent,
    Purchase,
    PurchaseConversionState,
    Session,
    UserLibrary,
    UserLibraryPreferences,
    UserPreferences,
)


class Command(BaseCommand):
    help = "Read and validate library ownership without changing any data."

    def add_arguments(self, parser):
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument("--user", help="Audit the library owned by USERNAME.")
        scope.add_argument(
            "--library", dest="library_id", help="Audit one library UUID."
        )
        scope.add_argument(
            "--all-libraries",
            action="store_true",
            help="Explicitly audit every library.",
        )

    def handle(self, *args, **options):
        libraries = self._resolve_libraries(options)
        library_ids = [library.pk for library in libraries]
        user_ids = [library.user_id for library in libraries]

        self.stdout.write(
            "Scope: " + ", ".join(str(library.pk) for library in libraries)
        )
        self.stdout.write("Direct owners:")
        direct_counts = (
            ("games", Game.objects.filter(library_id__in=library_ids).count()),
            (
                "purchases",
                Purchase.objects.filter(library_id__in=library_ids).count(),
            ),
            ("devices", Device.objects.filter(library_id__in=library_ids).count()),
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
                Session.objects.filter(game__library_id__in=library_ids).count(),
            ),
            (
                "play events",
                PlayEvent.objects.filter(game__library_id__in=library_ids).count(),
            ),
            (
                "status changes",
                GameStatusChange.objects.filter(
                    game__library_id__in=library_ids
                ).count(),
            ),
        )
        for label, count in derived_counts:
            self.stdout.write(f"  {label}: {count}")

        violations = self._cross_library_violations(library_ids)
        self.stdout.write(f"Cross-library links: {len(violations)}")
        for violation in violations:
            self.stdout.write(f"  {violation}")

        preference_violations = []
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

    def _resolve_libraries(self, options):
        libraries = UserLibrary.objects.select_related("user").order_by("pk")
        if options["all_libraries"]:
            return list(libraries)
        if options["user"]:
            user_model = get_user_model()
            try:
                user = user_model.objects.get(username=options["user"])
                return [libraries.get(user=user)]
            except (user_model.DoesNotExist, UserLibrary.DoesNotExist) as error:
                raise CommandError(
                    f"User {options['user']!r} or their library does not exist."
                ) from error
        try:
            return [libraries.get(pk=options["library_id"])]
        except (UserLibrary.DoesNotExist, ValidationError, ValueError) as error:
            raise CommandError(
                f"Library {options['library_id']!r} does not exist."
            ) from error

    @staticmethod
    def _cross_library_violations(library_ids):
        violations = []
        for game_id, platform_id in (
            Game.objects.filter(
                library_id__in=library_ids,
                platform__library__isnull=False,
            )
            .exclude(platform__library_id=F("library_id"))
            .values_list("pk", "platform_id")
        ):
            violations.append(f"Game.platform: game {game_id}, platform {platform_id}")
        for purchase_id, platform_id in (
            Purchase.objects.filter(
                library_id__in=library_ids,
                platform__library__isnull=False,
            )
            .exclude(platform__library_id=F("library_id"))
            .values_list("pk", "platform_id")
        ):
            violations.append(
                f"Purchase.platform: purchase {purchase_id}, platform {platform_id}"
            )
        for purchase_id, game_id in (
            Purchase.objects.filter(
                library_id__in=library_ids,
                related_game__isnull=False,
            )
            .exclude(related_game__library_id=F("library_id"))
            .values_list("pk", "related_game_id")
        ):
            violations.append(
                f"Purchase.related_game: purchase {purchase_id}, game {game_id}"
            )
        through = Purchase.games.through
        for purchase_id, game_id in (
            through.objects.filter(purchase__library_id__in=library_ids)
            .exclude(game__library_id=F("purchase__library_id"))
            .values_list("purchase_id", "game_id")
        ):
            violations.append(f"Purchase.games: purchase {purchase_id}, game {game_id}")
        for session_id, device_id in (
            Session.objects.filter(
                game__library_id__in=library_ids,
                device__isnull=False,
            )
            .exclude(device__library_id=F("game__library_id"))
            .values_list("pk", "device_id")
        ):
            violations.append(
                f"Session.device: session {session_id}, device {device_id}"
            )
        for library_id, device_id in (
            UserLibraryPreferences.objects.filter(
                library_id__in=library_ids,
                default_device__isnull=False,
            )
            .exclude(default_device__library_id=F("library_id"))
            .values_list("library_id", "default_device_id")
        ):
            violations.append(
                "UserLibraryPreferences.default_device: "
                f"library {library_id}, device {device_id}"
            )
        return violations
