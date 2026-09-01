"""The Game form's nested Edition and Release rows.

A row is named by Django's own form prefix. `BoundField.html_name` is
``f"{prefix}-{name}"``, and Django hands the widget that prefixed name, so
`TemporalWidget` builds ``edition-0-release-1-release_date-year`` without a
line changing in `timetracker/temporal.py`.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final, cast
from uuid import UUID

from django import forms
from django.core.exceptions import ValidationError

from common.date_time_presentation import DateTimePresentation
from games.catalog_compat import InitialRelease, write_and_mirror
from games.catalog_writes import (
    add_edition,
    add_release,
    remove_edition,
    remove_release,
    update_edition,
    update_release,
)
from games.forms import PrimitiveWidgetsMixin, TemporalFormField
from games.models import Edition, Game, Platform, Release, UserLibrary
from games.reads.catalog_hierarchy import game_hierarchy
from timetracker.temporal import TemporalValue

#: A flat POST body, the one shape every row reads its own keys from.
type PostedData = Mapping[str, str]

#: Which row a name belongs to: a number, or the placeholder a clone
#: template carries until the browser numbers it.
type RowIndex = int | str

#: Where a cloned row learns its own number. `ts/elements/catalog-editor.ts`
#: rewrites both, so the two spellings have to agree.
EDITION_PLACEHOLDER: Final[str] = "__edition__"
RELEASE_PLACEHOLDER: Final[str] = "__release__"

#: One radio group over the whole Game; its value is a release prefix.
MARK_FIELD: Final[str] = "in_library"
#: How many Edition blocks were posted, the way a formset states it.
EDITION_COUNT_FIELD: Final[str] = "editions-count"

#: The service allows it for #782's importer; a person typing does not,
#: because two unnamed siblings both read as the Game's name.
UNNAMED_SIBLING_EDITION = (
    "Name this edition. Another edition already presents as the game's own name."
)
NO_MARK = "Choose which release is the one in your library."
MARK_ON_A_REMOVED_ROW = (
    "The release you chose is going. Choose one of the releases that stay."
)
LAST_RELEASE = "An edition keeps one release. Add another one before you remove this."
LAST_EDITION_IN_FORM = (
    "A game keeps one edition. Add another one before you remove this."
)
DUPLICATE_NAME_IN_FORM = "Another edition of this game already has that name."


def _as_uuid(value: str) -> UUID | None:
    """A posted id that is not one names nothing."""
    try:
        return UUID(value)
    except ValueError:
        return None


def edition_prefix(index: RowIndex) -> str:
    """``edition_prefix(0)`` is ``"edition-0"``."""
    return f"edition-{index}"


def release_prefix(edition: RowIndex, release: RowIndex) -> str:
    """``release_prefix(0, 1)`` is ``"edition-0-release-1"``."""
    return f"{edition_prefix(edition)}-release-{release}"


def release_count_field(edition_index: RowIndex) -> str:
    """``release_count_field(0)`` is ``"edition-0-releases-count"``."""
    return f"{edition_prefix(edition_index)}-releases-count"


class EditionRowForm(PrimitiveWidgetsMixin, forms.Form):
    """One Edition block's own fields."""

    edition_id = forms.UUIDField(required=False, widget=forms.HiddenInput)
    name = forms.CharField(max_length=255, required=False, label="Edition name")
    removed = forms.BooleanField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        #: `CatalogGraphForm` sets this from the stored graph, never
        #: from the posted id: a row naming a row storage did not
        #: return is a new row, not a write to somebody else's.
        self.instance: Edition | None = None

    def clean_name(self) -> str:
        return cast(str, self.cleaned_data["name"]).strip()


class ReleaseRowForm(PrimitiveWidgetsMixin, forms.Form):
    """One Release row inside an Edition block."""

    release_id = forms.UUIDField(required=False, widget=forms.HiddenInput)
    removed = forms.BooleanField(required=False, widget=forms.HiddenInput)

    #: A plain select, not `SearchSelectWidget`. A composite widget carries
    #: its id on a wrapper div, and a cloned row would have to rewrite that
    #: id and re-run the element's wiring.
    platform = forms.ModelChoiceField(
        queryset=Platform.objects.none(),
        required=False,
        empty_label="Unspecified",
    )

    def __init__(
        self,
        *args: object,
        library: UserLibrary,
        presentation: DateTimePresentation,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.library = library
        self.instance: Release | None = None
        cast(
            forms.ModelChoiceField, self.fields["platform"]
        ).queryset = Platform.objects.visible_to(library).order_by("name")
        self.fields["release_date"] = TemporalFormField(
            presentation=presentation, label="Released"
        )
        #: `release_date` joins the form last, thus it sorts last too.
        self.order_fields(("release_id", "platform", "release_date", "removed"))


def _removed(form: forms.Form) -> bool:
    """A row says it is going, once it has been read."""
    return bool(form.is_bound and form.cleaned_data.get("removed"))


def _stated(row: forms.Form) -> InitialRelease:
    """The Platform and the date one read row states."""
    return InitialRelease(
        platform=cast(Platform | None, row.cleaned_data.get("platform")),
        release_date=cast(TemporalValue | None, row.cleaned_data.get("release_date")),
    )


@dataclass(slots=True)
class EditionBlock:
    """One Edition's own form and the Release rows under it."""

    form: EditionRowForm
    rows: list[ReleaseRowForm]

    @property
    def edition(self) -> Edition | None:
        """The stored row this block writes, or None for a new one."""
        return self.form.instance

    @property
    def removed(self) -> bool:
        return _removed(self.form)

    @property
    def surviving(self) -> list[ReleaseRowForm]:
        return [row for row in self.rows if not _removed(row)]


def _count(data: PostedData, field: str) -> int:
    """A count that is missing or not a number counts nothing.

    Zero rows then fails validation, which is a sentence a person
    reads, rather than a traceback.
    """
    try:
        return max(0, int(data.get(field, "")))
    except ValueError:
        return 0


class CatalogGraphForm:
    """Every Edition and Release of one Game, as one bound thing.

    Unbound it states the stored graph. Bound it states what was
    posted, and a posted id that storage did not return is a new
    row rather than a write to somebody else's.

    `game` is None on Add Game, where the Game the graph hangs from
    does not exist yet. Nothing is stored, so the form states one
    blank Edition holding one blank Release, and `adopt()` names the
    Game once the write path has made it.
    """

    def __init__(
        self,
        data: PostedData | None,
        *,
        game: Game | None,
        library: UserLibrary,
        presentation: DateTimePresentation,
    ) -> None:
        self.data = data
        self.game = game
        self.library = library
        self.presentation = presentation
        self.form_errors: list[str] = []
        #: The row a refused verb named, recorded on the way out.
        self._blamed: tuple[forms.Form, str] | None = None
        self._read_storage()
        if data is None:
            self.blocks = self._blocks_from_storage()
            self.mark = self._mark_from_storage()
        else:
            self.blocks = self._blocks_from_post(data)
            self.mark = data.get(MARK_FIELD, "")

    def _read_storage(self) -> None:
        """The stored graph, and the two maps a posted id is read through."""
        self._stored = (
            [] if self.game is None else game_hierarchy(self.game, self.library)
        )
        self._stored_editions = {
            entry.edition.pk: entry.edition for entry in self._stored
        }
        self._stored_releases = {
            release.pk: release for entry in self._stored for release in entry.releases
        }

    @property
    def is_bound(self) -> bool:
        return self.data is not None

    @property
    def blamed(self) -> bool:
        """Whether a verb named the row that caused the last refusal."""
        return self._blamed is not None

    @property
    def written_game(self) -> Game:
        """The Game the graph hangs from, once there is one."""
        assert self.game is not None, "A new Game is named by adopt() before the write."
        return self.game

    def _release_form(
        self,
        data: PostedData | None,
        edition_index: RowIndex,
        release_index: RowIndex,
        initial: dict[str, object] | None = None,
    ) -> ReleaseRowForm:
        return ReleaseRowForm(
            data,
            prefix=release_prefix(edition_index, release_index),
            initial=initial,
            library=self.library,
            presentation=self.presentation,
        )

    def _blocks_from_storage(self) -> list[EditionBlock]:
        blocks: list[EditionBlock] = []
        for index, entry in enumerate(self._stored):
            form = EditionRowForm(
                prefix=edition_prefix(index),
                initial={"edition_id": entry.edition.pk, "name": entry.edition.name},
            )
            form.instance = entry.edition
            rows: list[ReleaseRowForm] = []
            for row_index, release in enumerate(entry.releases):
                row = self._release_form(
                    None,
                    index,
                    row_index,
                    initial={
                        "release_id": release.pk,
                        "platform": release.platform_id,
                        "release_date": release.release_date,
                    },
                )
                row.instance = release
                rows.append(row)
            #: An Edition may hold no live Release, and a block with no
            #: row offers nothing to fill in.
            blocks.append(
                EditionBlock(
                    form=form, rows=rows or [self._release_form(None, index, 0)]
                )
            )
        if blocks:
            return blocks
        #: See the module docstring of `games/catalog_compat.py`: no app
        #: path leaves a Game without a graph, and a stale fixture does.
        return [
            EditionBlock(
                form=EditionRowForm(prefix=edition_prefix(0)),
                rows=[self._release_form(None, 0, 0)],
            )
        ]

    def _mark_from_storage(self) -> str:
        for index, block in enumerate(self.blocks):
            edition = block.edition
            if edition is not None and not edition.is_default:
                continue
            for row_index, row in enumerate(block.rows):
                if row.instance is None or row.instance.is_default:
                    return release_prefix(index, row_index)
            return release_prefix(index, 0)
        return release_prefix(0, 0)

    def _posted_edition(self, data: PostedData, index: int) -> Edition | None:
        posted_id = _as_uuid(data.get(f"{edition_prefix(index)}-edition_id", ""))
        return None if posted_id is None else self._stored_editions.get(posted_id)

    def _posted_release(
        self, data: PostedData, index: int, row_index: int, edition: Edition | None
    ) -> Release | None:
        row = release_prefix(index, row_index)
        posted_id = _as_uuid(data.get(f"{row}-release_id", ""))
        release = None if posted_id is None else self._stored_releases.get(posted_id)
        #: A row that names a Release of another block writes under the
        #: parent it already has, thus it is a new row here.
        if release is None or edition is None or release.edition_id != edition.pk:
            return None
        return release

    def _blocks_from_post(self, data: PostedData) -> list[EditionBlock]:
        blocks: list[EditionBlock] = []
        for index in range(_count(data, EDITION_COUNT_FIELD)):
            form = EditionRowForm(data, prefix=edition_prefix(index))
            form.instance = self._posted_edition(data, index)
            rows: list[ReleaseRowForm] = []
            for row_index in range(_count(data, release_count_field(index))):
                row = self._release_form(data, index, row_index)
                row.instance = self._posted_release(
                    data, index, row_index, form.instance
                )
                rows.append(row)
            blocks.append(EditionBlock(form=form, rows=rows))
        return blocks

    def blank_row(self) -> ReleaseRowForm:
        """One unnumbered Release row, for the browser to clone."""
        return self._release_form(None, EDITION_PLACEHOLDER, RELEASE_PLACEHOLDER)

    def blank_block(self) -> EditionBlock:
        """One unnumbered Edition, for the browser to clone.

        Its one row is row zero already, so only the Edition is left
        unnumbered. The renderer builds this block with the very
        functions that build a live one, thus the two cannot drift.
        """
        return EditionBlock(
            form=EditionRowForm(prefix=edition_prefix(EDITION_PLACEHOLDER)),
            rows=[self._release_form(None, EDITION_PLACEHOLDER, 0)],
        )

    def marked(self) -> tuple[EditionBlock, ReleaseRowForm] | None:
        """The surviving row the mark names, if it names one."""
        for index, block in enumerate(self.blocks):
            if block.removed:
                continue
            for row_index, row in enumerate(block.rows):
                if release_prefix(index, row_index) == self.mark and not _removed(row):
                    return block, row
        return None

    def is_valid(self) -> bool:
        """Every row, and then the things only the set can say."""
        if not self.is_bound:
            return False
        #: `all()` over a generator stops at the first false one, and a
        #: row it never reached holds no `cleaned_data`. `_validate_set`
        #: reads every row's, thus every row is read here first.
        read = [block.form.is_valid() for block in self.blocks]
        read += [row.is_valid() for block in self.blocks for row in block.rows]
        return self._validate_set() and all(read)

    def _validate_names(self, surviving: list[EditionBlock]) -> bool:
        valid = True
        taken: set[str] = set()
        unnamed = 0
        for block in surviving:
            name = cast(str, block.form.cleaned_data.get("name", ""))
            if not name:
                unnamed += 1
                if unnamed > 1:
                    block.form.add_error("name", UNNAMED_SIBLING_EDITION)
                    valid = False
                continue
            if name.casefold() in taken:
                block.form.add_error("name", DUPLICATE_NAME_IN_FORM)
                valid = False
            taken.add(name.casefold())
        return valid

    def _validate_set(self) -> bool:
        """What one row cannot say on its own."""
        surviving = [block for block in self.blocks if not block.removed]
        if not surviving:
            self.form_errors.append(LAST_EDITION_IN_FORM)
            return False
        valid = True
        for block in surviving:
            if not block.surviving:
                block.form.add_error(None, LAST_RELEASE)
                valid = False
        valid = self._validate_names(surviving) and valid
        if not self.mark:
            self.form_errors.append(NO_MARK)
            valid = False
        elif self.marked() is None:
            self.form_errors.append(MARK_ON_A_REMOVED_ROW)
            valid = False
        return valid

    @property
    def initial_release(self) -> InitialRelease:
        """What the marked row states, for the default the service makes.

        `save_private_game` guarantees a Game a default Edition and a
        default Release. Seeding them from the marked row is what lets
        `adopt()` claim them: a row that claims nothing is written
        beside them instead, leaving an empty Release nobody stated.
        """
        marked = self.marked()
        assert marked is not None, "is_valid() states the mark names a surviving row."
        _, row = marked
        return _stated(row)

    def adopt(self, game: Game) -> None:
        """Name the Game just made, and claim its default rows.

        The service made exactly one Edition holding one Release, and
        made both default, thus they belong to the marked row.
        """
        self.game = game
        self._read_storage()
        assert self._stored, "save_private_game() guarantees one Edition."
        marked = self.marked()
        assert marked is not None, "is_valid() states the mark names a surviving row."
        block, row = marked
        entry = self._stored[0]
        block.form.instance = entry.edition
        row.instance = entry.releases[0] if entry.releases else None

    def _write_edition(self, block: EditionBlock, *, is_default: bool) -> Edition:
        """State one Edition's whole name and mark."""
        name = cast(str, block.form.cleaned_data.get("name", ""))
        stored = block.edition
        with self._blame(block.form):
            written = (
                add_edition(
                    game=self.written_game,
                    library=self.library,
                    name=name,
                    is_default=is_default,
                )
                if stored is None
                else update_edition(
                    edition=stored,
                    library=self.library,
                    name=name,
                    is_default=is_default,
                )
            )
        block.form.instance = written
        return written

    def _write_release(
        self, edition: Edition, row: ReleaseRowForm, *, is_default: bool
    ) -> None:
        """State one Release's whole Platform, date and mark."""
        platform, release_date = _stated(row)
        stored = row.instance
        with self._blame(row):
            row.instance = (
                add_release(
                    edition=edition,
                    library=self.library,
                    platform=platform,
                    release_date=release_date,
                    is_default=is_default,
                )
                if stored is None
                else update_release(
                    release=stored,
                    library=self.library,
                    platform=platform,
                    release_date=release_date,
                    is_default=is_default,
                )
            )

    def _promote_marked_edition(self, marked: EditionBlock) -> None:
        """Step 1. The promotion is what stands the old default down.

        `update_edition` refuses an explicit demotion, so nothing is
        ever demoted here. `_clear_default_edition` inside the verb
        does it, and every later write reads the row back already
        standing down.
        """
        self._write_edition(marked, is_default=True)

    def _write_other_editions(self, marked: EditionBlock) -> None:
        """Step 2. Each one reads back false, thus none is demoted."""
        for block in self.blocks:
            if block is not marked and not block.removed:
                self._write_edition(block, is_default=False)

    def _winner(
        self, block: EditionBlock, marked_row: ReleaseRowForm | None
    ) -> ReleaseRowForm:
        """The row that takes this Edition's default mark."""
        if marked_row is not None:
            return marked_row
        standing = [
            row
            for row in block.surviving
            if row.instance is not None and row.instance.is_default
        ]
        return standing[0] if standing else block.surviving[0]

    def _write_releases(self, block: EditionBlock, marked_row: ReleaseRowForm | None):
        """Step 3. The winner first, so no later add takes the mark."""
        edition = block.edition
        assert edition is not None
        winner = self._winner(block, marked_row)
        self._write_release(edition, winner, is_default=True)
        for row in block.surviving:
            if row is not winner:
                self._write_release(edition, row, is_default=False)

    def _remove_releases(self) -> None:
        """Step 4. Only the winner is default, and it is not here."""
        for block in self.blocks:
            if block.removed:
                continue
            for row in block.rows:
                if _removed(row) and row.instance is not None:
                    with self._blame(row):
                        remove_release(release=row.instance, library=self.library)

    def _remove_editions(self) -> None:
        """Step 5. Step 1 already moved the mark off any of these."""
        for block in self.blocks:
            if block.removed and block.edition is not None:
                with self._blame(block.form):
                    remove_edition(edition=block.edition, library=self.library)

    def _write(self) -> None:
        marked = self.marked()
        assert marked is not None, "is_valid() states the mark names a surviving row."
        marked_block, marked_row = marked
        self._promote_marked_edition(marked_block)
        self._write_other_editions(marked_block)
        for block in self.blocks:
            if not block.removed:
                self._write_releases(
                    block, marked_row if block is marked_block else None
                )
        self._remove_releases()
        self._remove_editions()

    @contextmanager
    def _blame(self, form: forms.Form) -> Iterator[None]:
        """A refusal names the row that caused it, then keeps rising.

        The raise has to reach `write_and_mirror` for the transaction
        to unwind, thus this records rather than answers.
        """
        try:
            yield
        except ValidationError as refusal:
            self._blamed = (form, refusal.messages[0])
            raise

    def answer(self, refusal: ValidationError) -> None:
        """Put the sentence where whoever typed it will read it."""
        if self._blamed is None:
            self.form_errors.append(refusal.messages[0])
            return
        form, sentence = self._blamed
        form.add_error(None, sentence)

    def write(self) -> None:
        """One transaction over the whole finished graph.

        The refusal keeps rising. Add Game writes the Game and the
        graph under one transaction of its own, thus it needs the
        raise to unwind the Game as well.
        """
        self._blamed = None
        write_and_mirror(self.written_game, self._write)

    def save(self) -> bool:
        """Write the graph, and answer a refusal rather than raise it."""
        try:
            self.write()
        except ValidationError as refusal:
            self.answer(refusal)
            return False
        return True
