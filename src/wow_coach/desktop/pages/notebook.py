"""The Notebook page: what the coach has saved about the player and the shown character.

The coach keeps two kinds of Markdown file (see ``wow_coach.notes``): a journal per
character and one file of notes about the player. The coach reads both before every answer.
This page shows them, so the player can see (and fix) what the coach believes.

Security: the files are written by an AI, so they are untrusted text. Nothing here uses
Qt's rich text, HTML or Markdown. A tiny parser below turns the file into headings, bullets
and paragraphs, and every piece is a plain-text ``QLabel``. A ``<b>tag</b>`` in a note is
therefore shown literally and can never become a link, a picture or a style.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QHideEvent, QShowEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from wow_coach.desktop.bridge import CoreBridge, Runner, run_in_thread
from wow_coach.desktop.forms import Card, make_button, make_label, page_header, scrollable
from wow_coach.desktop.notebook_summary import summarize
from wow_coach.desktop.notes_reader import NotebookData, NoteFile, NotesReader
from wow_coach.desktop.pages.base import Page
from wow_coach.desktop.state import StateView
from wow_coach.desktop.theme import RADIUS, SPACE, SPACE_LARGE, SPACE_SMALL, Colors, current_colors
from wow_coach.desktop.widgets.notebook_glance import NotebookGlance
from wow_coach.engine.notes_digest import Section, is_private, split_sections

POLL_MS: Final = 3000  # how often the files' change times are checked while the page is open
PRIVATE_NOTE: Final = "Stays on this computer: never sent to the AI"
PREVIEW_LIMIT: Final = 90  # characters of a section shown under its closed heading

INTRO: Final = (
    "This is what your coach remembers about you and your character. "
    "The coach reads it before every answer."
)
NO_CHARACTER: Final = (
    "No character yet. Once the game has saved your character, the coach's journal "
    "for it shows up here."
)
NO_JOURNAL: Final = (
    "Your coach hasn't written anything about this character yet. Ask the coach about "
    "your goals, or use the Claude Code coach, and it will fill this in."
)
NO_PLAYER_NOTES: Final = (
    "Your coach hasn't saved any notes about you yet. Tell it how you like to be coached "
    "(short answers, exact click steps...) and it will remember."
)

_BOLD: Final = re.compile(r"\*\*(.+?)\*\*")
_BULLET: Final = re.compile(r"^(?:[-*]\s+|(\d+\.)\s+)(.*)$")


class BlockKind(Enum):
    """The kinds of line a note is made of."""

    PARAGRAPH = "paragraph"
    BULLET = "bullet"
    SMALL_HEADING = "small heading"  # a "### " line inside a section


@dataclass(frozen=True, slots=True)
class Block:
    """One piece of a section. ``marker`` is the bullet sign ("•" or "1.") for bullets."""

    kind: BlockKind
    text: str
    marker: str = ""


@dataclass(frozen=True, slots=True)
class NoteSection:
    """A section ready to draw: a title ("" before the first heading), blocks, privacy."""

    title: str
    blocks: tuple[Block, ...]
    private: bool


def strip_bold(text: str) -> str:
    """Remove ``**bold**`` markers, keeping the words."""
    return _BOLD.sub(r"\1", text)


def parse_blocks(body: str) -> tuple[Block, ...]:
    """Turn the lines of one section into blocks.

    ``- `` / ``* `` / ``1. `` lines are bullets, ``### `` lines small headings, any other
    non-empty line a paragraph. A top title line (``# Journal: ...``) is skipped, because the
    page already says whose notes these are.
    """
    blocks: list[Block] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("# "):
            continue
        if line.startswith("###"):
            blocks.append(Block(BlockKind.SMALL_HEADING, strip_bold(line.lstrip("#").strip())))
            continue
        bullet = _BULLET.match(line)
        if bullet:
            marker = bullet.group(1) or "•"
            blocks.append(Block(BlockKind.BULLET, strip_bold(bullet.group(2)), marker))
        else:
            blocks.append(Block(BlockKind.PARAGRAPH, strip_bold(line)))
    return tuple(blocks)


def parse_notes(text: str) -> list[NoteSection]:
    """The sections of a notes file, in the file's order. Empty ones are left out."""
    sections = [_note_section(section) for section in split_sections(text)]
    return [s for s in sections if s.blocks or s.title]


def _note_section(section: Section) -> NoteSection:
    return NoteSection(
        title=strip_bold(section.name),
        blocks=parse_blocks(section.body),
        private=is_private(section),
    )


def _style(c: Colors) -> str:
    """This page's extra look: parchment section rows with dark ink (the Coach page's paper)."""
    return f"""
QFrame#noteCard {{
    background: {c.parchment}; border: 1px solid {c.parchment_edge}; border-radius: {RADIUS}px;
}}
QFrame#noteCard QLabel {{ color: {c.on_parchment}; background: transparent; border: none; }}
QFrame#noteCard QLabel[role="marker"] {{ color: {c.parchment_muted}; font-weight: 700; }}
QFrame#noteCard QLabel[role="private"] {{
    color: {c.parchment_muted}; font-size: 9pt; font-style: italic;
}}
QFrame#noteCard QLabel[role="preview"] {{ color: {c.parchment_muted}; font-size: 9pt; }}
QFrame#noteCard QLabel[role="minor"] {{ font-weight: 700; }}
QFrame#noteCard QPushButton {{
    background: transparent; border: none; color: {c.on_parchment}; font-weight: 700;
    text-align: left; padding: 2px 0px;
}}
QFrame#noteCard QPushButton:hover {{ color: {c.parchment_muted}; }}
QFrame#noteEmpty {{
    background: {c.surface}; border: 1px dashed {c.border}; border-radius: {RADIUS}px;
}}
QFrame#noteEmpty QLabel {{ background: transparent; border: none; color: {c.muted}; }}
"""


def _text_label(text: str, role: str | None = None) -> QLabel:
    """A plain-text, word-wrapped, selectable label (never rich text)."""
    label = make_label(text, role)  # make_label already sets PlainText
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setMinimumWidth(1)  # lets long unbroken words wrap instead of widening the page
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
    return label


def _bullet_row(block: Block) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(SPACE_SMALL, 0, 0, 0)
    layout.setSpacing(SPACE_SMALL)
    marker = make_label(block.marker, "marker")
    marker.setWordWrap(False)
    marker.setMinimumWidth(16)
    layout.addWidget(marker, 0, Qt.AlignmentFlag.AlignTop)
    layout.addWidget(_text_label(block.text), 1)
    return row


def preview_of(section: NoteSection) -> str:
    """The one line shown under a closed section's heading: its first line, shortened."""
    if section.private:
        return PRIVATE_NOTE
    for block in section.blocks:
        if block.kind is not BlockKind.SMALL_HEADING:
            text = block.text
            return text if len(text) <= PREVIEW_LIMIT else text[:PREVIEW_LIMIT].rstrip() + "…"
    return ""


def empty_card(message: str) -> Card:
    """A friendly dashed box that explains why there is nothing to show."""
    card = Card()
    card.setObjectName("noteEmpty")
    card.setProperty("role", "")
    card.body.addWidget(_text_label(message))
    return card


class SectionRow(QFrame):
    """One section as a collapsed row: a clickable heading with a chevron and a preview line.

    Opening the row builds its body for the first time (lazy); closing it only hides the body,
    so opening it again is instant. The body is built again only when the text changed.
    """

    def __init__(self, section: NoteSection) -> None:
        super().__init__()
        self.setObjectName("noteCard")
        self.section = section
        self.body: QWidget | None = None  # None until the row is first opened
        self._open = False
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(SPACE, SPACE_SMALL + 2, SPACE, SPACE_SMALL + 2)
        self._column.setSpacing(SPACE_SMALL)
        self.header = QPushButton()
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setToolTip("Show or hide this part of the notebook.")
        self.header.clicked.connect(self.toggle)
        self.preview = _text_label("", "preview")
        self._column.addWidget(self.header)
        self._column.addWidget(self.preview)
        self._refresh_header()

    @property
    def is_open(self) -> bool:
        """True while the body is showing."""
        return self._open

    def set_open(self, open_it: bool) -> None:
        """Open (building the body if needed) or close the row."""
        self._open = open_it
        if open_it and self.body is None:
            self.body = self._build_body()
            self._column.addWidget(self.body)
        if self.body is not None:
            self.body.setVisible(open_it)
        self._refresh_header()

    def toggle(self) -> None:
        """Open a closed row, close an open one."""
        self.set_open(not self._open)

    def update_section(self, section: NoteSection) -> None:
        """Take new text. An open row rebuilds its body now; a closed one forgets it."""
        if section == self.section:
            return
        self.section = section
        if self.body is not None:
            self._column.removeWidget(self.body)
            self.body.setParent(None)
            self.body.deleteLater()
            self.body = None
        if self._open:
            self.set_open(True)
        self._refresh_header()

    def _refresh_header(self) -> None:
        chevron = "▾" if self._open else "▸"
        self.header.setText(f"{chevron}  {self.section.title or 'Notes'}")
        self.preview.setText(preview_of(self.section))
        self.preview.setVisible(not self._open and bool(self.preview.text()))

    def _build_body(self) -> QWidget:
        """The labels of this section: a privacy note if needed, then its blocks."""
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SMALL + 2)
        if self.section.private:
            layout.addWidget(_text_label(PRIVATE_NOTE, "private"))
        for block in self.section.blocks:
            if block.kind is BlockKind.BULLET:
                layout.addWidget(_bullet_row(block))
            elif block.kind is BlockKind.SMALL_HEADING:
                layout.addWidget(_text_label(block.text, "minor"))
            else:
                layout.addWidget(_text_label(block.text))
        return body


class NotePart(QWidget):
    """One of the two parts of the page: a heading row, then the section rows of one file."""

    def __init__(self, title: str, open_tip: str) -> None:
        super().__init__()
        self.path: Path | None = None  # the file "Open in editor" opens; None = no file yet
        self.rows: list[SectionRow] = []
        self.heading = make_label(title, "subtitle")
        self.open_button = make_button("Open in editor", "secondary", open_tip)
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open)
        self.expand_button = make_button("Expand all", "ghost", "Open every section.")
        self.expand_button.clicked.connect(lambda: self.set_all_open(True))
        self.collapse_button = make_button("Collapse all", "ghost", "Close every section.")
        self.collapse_button.clicked.connect(lambda: self.set_all_open(False))
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.heading, 1)
        top.addWidget(self.expand_button)
        top.addWidget(self.collapse_button)
        top.addWidget(self.open_button)
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.setSpacing(SPACE)
        self._column.addLayout(top)
        self.cards = QWidget()
        self._column.addWidget(self.cards)

    def show_file(self, file: NoteFile | None, empty_message: str) -> None:
        """Draw ``file``'s sections, or ``empty_message`` when there is nothing to show."""
        has_text = file is not None and file.text is not None
        sections = parse_notes(file.text) if file is not None and file.text is not None else []
        self.path = file.path if file is not None and has_text else None
        self.open_button.setEnabled(self.path is not None)
        problem = file.problem if file is not None else None
        self._fill(problem or (None if sections else empty_message), sections)

    def set_all_open(self, open_them: bool) -> None:
        """Open or close every section (opening builds them all, only on this request)."""
        for row in self.rows:
            row.set_open(open_them)

    def _fill(self, message: str | None, sections: list[NoteSection]) -> None:
        """Show the new sections; rows whose heading is unchanged are kept and updated.

        Keeping a row keeps its open state and (if its text is the same) its built body, so a
        small edit in the file does not collapse the sections the player is reading.
        """
        titles = [row.section.title for row in self.rows]
        if message is None and titles == [s.title for s in sections]:
            for row, section in zip(self.rows, sections, strict=True):
                row.update_section(section)
            return
        was_open = {row.section.title for row in self.rows if row.is_open}
        fresh = QWidget()
        layout = QVBoxLayout(fresh)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_SMALL + 2)
        if message is not None:
            layout.addWidget(empty_card(message))
        rows = [SectionRow(section) for section in sections]
        for row in rows:
            layout.addWidget(row)
            if row.section.title in was_open:
                row.set_open(True)
        self.rows = rows
        self._column.replaceWidget(self.cards, fresh)
        self.cards.setParent(None)  # leave the page at once; Qt frees it when it is idle
        self.cards.deleteLater()
        self.cards = fresh
        self.expand_button.setEnabled(bool(rows))
        self.collapse_button.setEnabled(bool(rows))

    def _open(self) -> None:
        if self.path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path)))


class NotebookPage(Page):
    """What the coach saved about the player and the character."""

    name = "notebook"
    title = "Notebook"

    def __init__(
        self,
        bridge: CoreBridge,
        parent: QWidget | None = None,
        *,
        runner: Runner = run_in_thread,
        environ: Mapping[str, str] | None = None,
        poll_ms: int = POLL_MS,
    ) -> None:
        super().__init__(bridge, parent)
        self.reader = NotesReader(runner=runner, environ=environ)
        self.reader.loaded.connect(self._show_data)
        self._key: str | None = None

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(SPACE_LARGE)
        header = QHBoxLayout()
        header.addLayout(page_header("Notebook", INTRO), 1)
        self.reload_button = make_button(
            "Reload", "secondary", "Read the notebook files again right now."
        )
        self.reload_button.clicked.connect(self.reload)
        header.addWidget(self.reload_button, 0, Qt.AlignmentFlag.AlignTop)
        column.addLayout(header)

        self.glance = NotebookGlance(compact=False)
        column.addWidget(self.glance)
        self.character_part = NotePart(
            "Your character", "Open this character's journal in your text editor."
        )
        self.player_part = NotePart("You", "Open your player notes in your text editor.")
        self.character_part.show_file(None, NO_CHARACTER)
        self.player_part.show_file(None, NO_PLAYER_NOTES)
        column.addWidget(self.character_part)
        column.addWidget(self.player_part)
        column.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll_area: QScrollArea = scrollable(content)
        outer.addWidget(self.scroll_area)
        self.setStyleSheet(_style(current_colors()))

        # Check the files' change times every few seconds, but only while the page is open.
        self._timer = QTimer(self)
        self._timer.setInterval(poll_ms)
        self._timer.timeout.connect(self.check_for_changes)

    # ---- asking for files ---------------------------------------------------------------

    def check_for_changes(self) -> None:
        """Ask the reader to look again; it only answers when a file changed."""
        self.reader.request(self._key)

    def reload(self) -> None:
        """Read both files again, even if they look unchanged."""
        self.reader.request(self._key, force=True)

    def show_state(self, state: StateView) -> None:
        """Follow the shown character: another character means another journal."""
        key = state.selected or self.bridge.selected_character
        if key != self._key:
            self._key = key
            self.reader.request(key)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802  (Qt's name)
        """Look at once when opened, then keep watching."""
        self.check_for_changes()
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802  (Qt's name)
        """Stop watching while the page is not on screen."""
        self._timer.stop()
        super().hideEvent(event)

    # ---- drawing ------------------------------------------------------------------------

    def _show_data(self, data: object) -> None:
        if not isinstance(data, NotebookData) or data.character_key != self._key:
            return  # an answer for a character the player has already left
        bar = self.scroll_area.verticalScrollBar()
        position = bar.value()
        self.character_part.heading.setText(
            f"Your character: {data.character_key}" if data.character_key else "Your character"
        )
        no_journal = NO_JOURNAL if data.character_key else NO_CHARACTER
        self.character_part.show_file(data.character, no_journal)
        self.player_part.show_file(data.player, NO_PLAYER_NOTES)
        self.glance.show_summary(summarize(data.character_text, data.player_text))
        # Put the page back where the player was reading, once the new cards have a size.
        bar.setValue(position)
        QTimer.singleShot(0, self, lambda: bar.setValue(position))
