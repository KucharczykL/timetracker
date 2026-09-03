"""The Game form's nested Edition and Release rows.

A row is named by Django's own form prefix. `BoundField.html_name` is
``f"{prefix}-{name}"``, and Django hands the widget that prefixed name, so
`TemporalWidget` builds ``edition-0-release-1-release_date-year`` without a
line changing in `timetracker/temporal.py`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, NamedTuple, cast
from uuid import UUID

from django import forms
from django.core.exceptions import ValidationError

from common.date_time_presentation import DateTimePresentation
from common.naming import NameKey, name_key
from games.catalog_compat import MirroredIdentity, mirrored_identity, write_and_mirror
from games.catalog_writes import (
    EditionState,
    GraphRefused,
    ReleaseState,
    RowKey,
    state_catalog_graph,
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
LAST_RELEASE = "An edition keeps one release. Add another one before you remove this."
LAST_EDITION_IN_FORM = (
    "A game keeps one edition. Add another one before you remove this."
)
DUPLICATE_NAME_IN_FORM = "Another edition of this game already has that name."
#: The service allows two: #782 needs two regions on one date to
#: be two rows. The page would show two rows nothing tells apart.
DUPLICATE_RELEASE_IN_FORM = (
    "Another release of this edition already states this platform and date."
)


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


def removal_stated(form: forms.BaseForm) -> bool:
    """A row says it is going.

    `is_valid()` is what makes a bound form read its own data, and the
    renderer draws rows that the Game form's refusal stopped short of
    reading. Django caches the result, thus asking here costs nothing.
    """
    if not form.is_bound:
        return False
    form.is_valid()
    return bool(form.cleaned_data.get("removed"))


#: What a row that is going still has to say: which row it is.
IDENTIFYING_FIELDS: Final[frozenset[str]] = frozenset(
    {"edition_id", "release_id", "removed"}
)


def reads_as_stated(form: forms.BaseForm, *, going: bool = False) -> bool:
    """Whether a row says enough for the statement it makes.

    A row that is going states only which row it is. Nothing writes
    its other values, and the page draws it out of sight, so a
    sentence about one of them would refuse a submit for a reason
    nobody can read. `going` is what a removed Edition says about the
    rows under it, which are as unwritten as its own fields.
    """
    valid = form.is_valid()
    if valid or not (going or removal_stated(form)):
        return valid
    for field in set(form.errors) - IDENTIFYING_FIELDS:
        del form.errors[field]
    return not form.errors


def _key(form: forms.Form) -> RowKey:
    """A row is named by its own prefix."""
    return cast(RowKey, form.prefix)


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
        return removal_stated(self.form)

    @property
    def surviving(self) -> list[ReleaseRowForm]:
        return [row for row in self.rows if not removal_stated(row)]


#: A page builds one bound form per counted row, each holding a
#: queryset of its own, thus the count is what a post spends. Django
#: caps the same number with a formset's `absolute_max`. Nobody types
#: a graph this big, and a post that states one is spending a worker
#: rather than stating rows.
MOST_ROWS: Final[int] = 1000

TOO_MANY_ROWS: Final[str] = (
    f"This form holds more than {MOST_ROWS} rows. Remove some and submit again."
)


class RowCount(NamedTuple):
    """How many rows a post states, and how many are read."""

    read: int
    over: bool


def _count(data: PostedData, field: str) -> RowCount:
    """A count that is missing or not a number counts nothing.

    Zero rows then fails validation, which is a sentence a person
    reads, rather than a traceback. A count past `MOST_ROWS` is read
    as `MOST_ROWS`, so the work a post costs stays bounded, and it is
    refused with `TOO_MANY_ROWS` rather than quietly served short.
    """
    try:
        stated = max(0, int(data.get(field, "")))
    except ValueError:
        return RowCount(0, False)
    return RowCount(min(MOST_ROWS, stated), stated > MOST_ROWS)


class CatalogGraphForm:
    """Every Edition and Release of one Game, as one bound thing.

    Unbound it states the stored graph. Bound it states what was
    posted, and a posted id that storage did not return is a new
    row rather than a write to somebody else's.

    `game` is None on Add Game, where the Game the graph hangs from
    does not exist yet. Nothing is stored, so the form states one
    blank Edition holding one blank Release, and `bind()` names the
    Game once the submit has made it.
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
        self._read = False
        #: A post that states more rows than `MOST_ROWS` is refused,
        #: not served short. `_blocks_from_post` sets it.
        self._overcounted = False
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
    def written_game(self) -> Game:
        """The Game the graph hangs from, once there is one."""
        assert self.game is not None, "A new Game is named by bind() before the write."
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
        #: No app path leaves a Game without a graph. A stale
        #: fixture does, and the form still has to draw it.
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
        editions = _count(data, EDITION_COUNT_FIELD)
        self._overcounted = editions.over
        for index in range(editions.read):
            form = EditionRowForm(data, prefix=edition_prefix(index))
            form.instance = self._posted_edition(data, index)
            rows: list[ReleaseRowForm] = []
            releases = _count(data, release_count_field(index))
            self._overcounted = self._overcounted or releases.over
            for row_index in range(releases.read):
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
                if release_prefix(index, row_index) == self.mark and not removal_stated(
                    row
                ):
                    return block, row
        return None

    def is_valid(self) -> bool:
        """Every sentence that stands, however often asked."""
        if not self.is_bound:
            return False
        self._read_once()
        return not self.form_errors and not any(
            form.errors for form in self._rows_by_key().values()
        )

    def _read_once(self) -> None:
        """One pass over the rows and then over the set.

        A row states its own sentence once, because a field it
        already refused it does not read again. The set has no such
        guard: a second pass would state `LAST_EDITION_IN_FORM` and
        `LAST_RELEASE` beside the first. The answer above is read
        fresh every time, because `answer()` puts a service refusal
        on a row, or on `form_errors`, after this has returned, and
        the page then draws the form again.
        """
        if self._read:
            return
        self._read = True
        #: Every row, not up to the first false one: `_validate_set`
        #: reads each row's `cleaned_data`, and a row nobody read
        #: holds none.
        for block in self.blocks:
            reads_as_stated(block.form)
            going = block.removed
            for row in block.rows:
                reads_as_stated(row, going=going)
        self._validate_set()

    def _validate_names(self, surviving: list[EditionBlock]) -> bool:
        valid = True
        taken: set[NameKey] = set()
        unnamed = 0
        for block in surviving:
            #: A block with its own errors states no name yet. Absent
            #: `cleaned_data` reads as the empty string, and a name
            #: the field refused would count as one nobody typed,
            #: putting the sibling's sentence on a blameless row.
            if block.form.errors:
                continue
            name = cast(str, block.form.cleaned_data.get("name", ""))
            if not name:
                unnamed += 1
                if unnamed > 1:
                    block.form.add_error("name", UNNAMED_SIBLING_EDITION)
                    valid = False
                continue
            if name_key(name) in taken:
                block.form.add_error("name", DUPLICATE_NAME_IN_FORM)
                valid = False
            taken.add(name_key(name))
        return valid

    def _validate_releases(self, surviving: list[EditionBlock]) -> bool:
        """Two surviving rows that read the same."""
        valid = True
        for block in surviving:
            seen: set[tuple[object, object]] = set()
            for row in block.surviving:
                #: A row with its own errors states no pair yet.
                if row.errors:
                    continue
                pair = (
                    row.cleaned_data.get("platform"),
                    row.cleaned_data.get("release_date"),
                )
                if pair in seen:
                    row.add_error(None, DUPLICATE_RELEASE_IN_FORM)
                    valid = False
                seen.add(pair)
        return valid

    def _validate_set(self) -> bool:
        """What one row cannot say on its own."""
        if self._overcounted:
            self.form_errors.append(TOO_MANY_ROWS)
            return False
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
        valid = self._validate_releases(surviving) and valid
        #: Binning the marked row states a removal, not a mistake. The
        #: mark falls to a row that stays, which is what the browser
        #: does as the person watches; the same rule here states it for
        #: a post the browser never touched. A statement that keeps no
        #: row at all is already refused above.
        if self.marked() is None:
            self.mark = self._first_surviving()
        return valid

    def _first_surviving(self) -> str:
        """The row the mark falls to when it names none of its own."""
        for index, block in enumerate(self.blocks):
            if block.removed:
                continue
            for row_index, row in enumerate(block.rows):
                if not removal_stated(row):
                    return release_prefix(index, row_index)
        return ""

    def mirrored_identity(self) -> MirroredIdentity:
        """The flat pair the marked row is about to leave.

        The submit writes it beside the Game's name, thus a rename
        that moves its own platform never meets the old pair.
        """
        marked = self.marked()
        assert marked is not None, "is_valid() states the mark names a surviving row."
        _, row = marked
        return mirrored_identity(
            cast(Platform | None, row.cleaned_data.get("platform")),
            cast(TemporalValue | None, row.cleaned_data.get("release_date")),
        )

    def _states(self) -> list[EditionState]:
        """Every posted row, as one stated graph."""
        marked = self.marked()
        assert marked is not None, "is_valid() states the mark names a surviving row."
        marked_block, marked_row = marked
        return [
            EditionState(
                key=_key(block.form),
                edition=block.edition,
                name=cast(str, block.form.cleaned_data.get("name", "")),
                removed=block.removed,
                is_default=block is marked_block,
                releases=tuple(
                    ReleaseState(
                        key=_key(row),
                        release=row.instance,
                        platform=cast(
                            Platform | None, row.cleaned_data.get("platform")
                        ),
                        release_date=cast(
                            TemporalValue | None, row.cleaned_data.get("release_date")
                        ),
                        removed=removal_stated(row),
                        is_default=row is marked_row,
                    )
                    for row in block.rows
                ),
            )
            for block in self.blocks
        ]

    def _rows_by_key(self) -> dict[RowKey, forms.Form]:
        """Every row, under the key the service got."""
        rows: dict[RowKey, forms.Form] = {}
        for block in self.blocks:
            rows[_key(block.form)] = block.form
            for row in block.rows:
                rows[_key(row)] = row
        return rows

    def write_rows(self) -> None:
        """One statement of the whole posted graph."""
        state_catalog_graph(
            game=self.written_game,
            library=self.library,
            editions=self._states(),
        )

    def answer(self, refusal: ValidationError) -> bool:
        """Put the sentence on the row that stated it.

        A refusal about the whole statement names no row, and the
        Editions area shows it above the blocks. Anything that is
        not a `GraphRefused` is a programming error, and rises.
        """
        if not isinstance(refusal, GraphRefused):
            return False
        form = None if refusal.key is None else self._rows_by_key().get(refusal.key)
        if form is None:
            self.form_errors.append(refusal.messages[0])
        else:
            form.add_error(None, refusal.messages[0])
        return True

    def bind(self, game: Game) -> None:
        """Name the Game a submit just made."""
        self.game = game

    def write(self) -> None:
        """One transaction over the graph and the mirror."""
        write_and_mirror(self.written_game, self.write_rows)
