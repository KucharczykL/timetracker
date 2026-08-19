from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from games.identity_audit import (
    CheckReport,
    actual_column_types,
    check_identity_columns,
    check_ordering,
    check_referential_agreement,
    check_residual_inventory,
    check_type_agreement,
    identity_models,
    primary_key_types,
    relation_columns,
)


class Command(BaseCommand):
    help = (
        "Read and verify the integer-to-UUID identity map without changing any "
        "data. Reports every violation before failing, so one run tells the "
        "whole story rather than the first problem only."
    )

    def handle(self, *args, **options):
        relations = relation_columns()
        models = identity_models()
        with connection.cursor() as cursor:
            actual_types = actual_column_types(cursor)
            reports = [
                check_type_agreement(relations, actual_types),
                check_residual_inventory(
                    relations, actual_types, primary_key_types(actual_types)
                ),
                check_identity_columns(cursor, models),
                check_ordering(models),
                check_referential_agreement(cursor, relations),
            ]

        violations = [
            violation for report in reports for violation in report.violations
        ]
        for report in reports:
            self._write_report(report)

        if violations:
            raise CommandError(f"{len(violations)} identity violation(s).")
        self.stdout.write(self.style.SUCCESS("Identity map verified: no violations."))

    def _write_report(self, report: CheckReport) -> None:
        for note in report.notes:
            self.stdout.write(f"  {note.check} {note.subject}: {note.detail}")
        for violation in report.violations:
            self.stdout.write(
                self.style.ERROR(
                    f"  {violation.check} {violation.subject}: {violation.detail}"
                )
            )
