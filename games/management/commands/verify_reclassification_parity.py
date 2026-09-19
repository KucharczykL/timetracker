"""Convert the review population; judge every figure by its rule."""

import uuid
from typing import NamedTuple

from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from games.commands.session_reclassification import statement_from_session
from games.models import PlayerSession, UserLibrary
from games.reads.playtime import played_years
from games.reads.session_figures import (
    highest_average_game,
    longest_session,
    most_sessions_game,
)
from games.stats_parity import (
    Converted,
    ConvertedRow,
    FigureChange,
    ScopeIdentities,
    ScopeKey,
    comparable,
    judge_scope,
    unattributed,
)
from games.views.session_reclassification import reviewable_sessions
from games.views.stats_data import StatsData, compute_stats
from games.writes.answers import CommandFailed
from games.writes.playergame import new_correlation_id
from games.writes.playersession import reclassify_session

#: The whole path a row's game sits behind.
GAME = "playthrough__player_game__game"


class Reading(NamedTuple):
    """One scope's figures and the rows behind its superlatives."""

    figures: StatsData
    identities: ScopeIdentities


def read_scope(library: UserLibrary, scope: ScopeKey) -> Reading:
    longest = longest_session(library, scope)
    most = most_sessions_game(library, scope)
    highest = highest_average_game(library, scope)
    return Reading(
        compute_stats(library, scope),
        ScopeIdentities(
            longest.session.pk if longest else None,
            most.game.pk if most else None,
            highest.game.pk if highest else None,
        ),
    )


def converted_row(session: PlayerSession) -> ConvertedRow:
    game = session.playthrough.player_game.game
    return ConvertedRow(
        session.pk,
        session.effective_day,
        game.pk,
        game.platform_id,
        session.effective_duration,
    )


def scope_label(scope: ScopeKey) -> str:
    return "all-time" if scope is None else str(scope)


class Command(BaseCommand):
    help = (
        "Read every statistics scope, convert the review population into "
        "historical playtime, read again, and judge each figure by its "
        "source's rule. Without --confirm it reads once and prints. It "
        "writes, so run it on a scratch restore only."
    )

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="Username to read.")
        parser.add_argument(
            "--confirm",
            help="Convert only when this value exactly matches --user.",
        )

    def handle(self, *args, **options):
        username = options["user"]
        confirmation = options["confirm"]
        user = self._get_user(username)
        library = user.library

        scopes: list[ScopeKey] = [None, *played_years(library)]
        before = {scope: read_scope(library, scope) for scope in scopes}
        population = list(reviewable_sessions(library).select_related(GAME))
        self.stdout.write(
            f"Review population: {len(population)} session(s) across "
            f"{len(scopes)} scope(s)."
        )

        if confirmation is None:
            for scope in scopes:
                self._write_figures(scope, before[scope].figures)
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: nothing converted. Re-run with --confirm {username}."
                )
            )
            return
        if confirmation != username:
            raise CommandError(
                "--confirm must exactly match --user; nothing converted."
            )

        converted = Converted(tuple(self._convert(user, population)))
        after = {scope: read_scope(library, scope) for scope in scopes}

        changed = unattributed_count = 0
        for scope in scopes:
            changes = judge_scope(
                before[scope].figures,
                after[scope].figures,
                before[scope].identities,
                converted.in_scope(scope),
            )
            changed += len(changes)
            unattributed_count += len(unattributed(changes))
            for change in changes:
                self._write_change(scope, change)
        summary = (
            f"{unattributed_count} unattributed of {changed} changed across "
            f"{len(scopes)} scopes; {len(converted.rows)} rows converted"
        )
        if unattributed_count:
            raise CommandError(summary)
        self.stdout.write(self.style.SUCCESS(summary))

    def _convert(
        self, user: User, population: list[PlayerSession]
    ) -> list[ConvertedRow]:
        """Every row through the confirm page's write; one correlation."""
        token = uuid.uuid7()
        correlation_id = new_correlation_id()
        rows: list[ConvertedRow] = []
        for session in population:
            row = converted_row(session)
            try:
                reclassify_session(
                    user,
                    session,
                    statement_from_session(session),
                    idempotency_key=f"reclassify-{token}-{session.pk}",
                    correlation_id=correlation_id,
                )
            except CommandFailed as failure:
                self.stdout.write(failure.message)
                raise CommandError(
                    f"Session {session.pk} was refused after {len(rows)} "
                    "conversion(s); a population partly converted has no parity "
                    "to judge."
                ) from failure
            rows.append(row)
        return rows

    def _write_figures(self, scope: ScopeKey, figures: StatsData) -> None:
        self.stdout.write(f"{scope_label(scope)}:")
        for key, value in figures.items():
            self.stdout.write(f"  {key}: {comparable(value)}")

    def _write_change(self, scope: ScopeKey, change: FigureChange) -> None:
        verdict = "UNATTRIBUTED" if change.attribution is None else change.attribution
        line = (
            f"{scope_label(scope)}: {change.key} {comparable(change.before)} -> "
            f"{comparable(change.after)} [{verdict}]"
        )
        if change.attribution is None:
            self.stdout.write(self.style.ERROR(line))
        else:
            self.stdout.write(line)

    @staticmethod
    def _get_user(username: str) -> User:
        user_model = get_user_model()
        try:
            return user_model.objects.get(username=username)
        except user_model.DoesNotExist as error:
            raise CommandError(f"User {username!r} does not exist.") from error
