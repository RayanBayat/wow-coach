"""Only one WoW Coach at a time.

Two copies would both answer the same in-game question, so the player would get every answer
twice. The first copy listens on a small local "socket" (a private channel between programs on
the same computer) named after the user. A second copy connects to it, says "show", and exits;
the first copy then brings its window to the front.
"""

import getpass
import logging
import re
from typing import Final

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_log = logging.getLogger(__name__)

SHOW_MESSAGE: Final = b"show"
CONNECT_TIMEOUT_MS: Final = 500
READ_TIMEOUT_MS: Final = 200


def default_name() -> str:
    """The channel name for this user, so two users on one computer do not clash."""
    try:
        user = getpass.getuser()
    except KeyError, OSError:
        user = "player"
    return "wow-coach-" + re.sub(r"[^A-Za-z0-9_.-]", "_", user)


class SingleInstance(QObject):
    """Makes sure only one copy of the app runs, and lets a second copy wake the first."""

    # Another copy was started: bring the window to the front.
    show_requested = Signal()

    def __init__(self, name: str | None = None) -> None:
        """Create it. ``name`` is the channel name (default: one per user)."""
        super().__init__()
        self._name = name or default_name()
        self._server: QLocalServer | None = None

    def claim(self) -> bool:
        """Try to become the one running copy.

        Returns True when this copy is the first and should go on. Returns False when another
        copy was already running: it was told to show its window, and this copy should exit.
        """
        if self._tell_the_running_copy():
            return False
        self._listen()
        return True

    def close(self) -> None:
        """Stop listening (the app is closing)."""
        server, self._server = self._server, None
        if server is not None:
            server.close()

    # ---- the second copy -----------------------------------------------------------------

    def _tell_the_running_copy(self) -> bool:
        """Say "show" to a running copy. False when nobody answers."""
        socket = QLocalSocket()
        socket.connectToServer(self._name)
        if not socket.waitForConnected(CONNECT_TIMEOUT_MS):
            return False
        socket.write(SHOW_MESSAGE)
        socket.flush()
        socket.waitForBytesWritten(CONNECT_TIMEOUT_MS)
        socket.disconnectFromServer()
        return True

    # ---- the first copy ------------------------------------------------------------------

    def _listen(self) -> None:
        # A crash can leave the channel's name behind on Linux and macOS (a leftover file).
        # Nobody answered above, so it is stale: remove it, or listening would fail.
        QLocalServer.removeServer(self._name)
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not server.listen(self._name):
            # The app still works; it just cannot be woken by a second copy.
            _log.warning("Could not listen for a second copy: %s", server.errorString())
            return
        server.newConnection.connect(self._on_connection)
        self._server = server

    def _on_connection(self) -> None:
        server = self._server
        while server is not None and server.hasPendingConnections():
            self._handle(server.nextPendingConnection())

    def _handle(self, socket: QLocalSocket) -> None:
        """Read the one short message of a second copy, act on it and hang up.

        The message is a few bytes on this computer only, so waiting a moment for it is
        harmless and keeps the code simple (no connections to keep track of).
        """
        got_data = socket.bytesAvailable() > 0 or socket.waitForReadyRead(READ_TIMEOUT_MS)
        if got_data and bytes(socket.readAll().data()) == SHOW_MESSAGE:
            self.show_requested.emit()
        socket.disconnectFromServer()
        socket.deleteLater()
