"""Only one WoW Coach at a time.

Two copies would both answer the same in-game question, so the player would get every answer
twice. Two things work together:

* A **lock file** in the user's own wow-coach data folder decides who runs. Taking the lock is
  one step that cannot be split, so when two copies start at the same moment exactly one wins.
  If a copy crashes, the lock is recognised as stale (its program is gone) and can be taken.
* A small local **socket** (a private channel between programs on the same computer) lets the
  copy that lost talk to the winner. It sends one short message: "show" (bring the window to
  the front) or "toggle-overlay" (show or hide the overlay; this is what the hotkey command
  ``wow-coach-app --toggle-overlay`` sends). Any other message is ignored.

The socket lives in a folder that only this user can use (``$XDG_RUNTIME_DIR/wow-coach`` on
Linux). A name in the shared ``/tmp`` could be taken by another user on the same computer, and
a very long ``$TMPDIR`` could make the name too long for the system.
"""

import getpass
import logging
import os
import re
import stat
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from PySide6.QtCore import QLockFile, QObject, QThread, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from wow_coach.datafolder import data_folder

_log = logging.getLogger(__name__)

SHOW_MESSAGE: Final = b"show"
TOGGLE_OVERLAY_MESSAGE: Final = b"toggle-overlay"
# The running copy answers every message with this, so the second copy knows it arrived
# before it hangs up. Without the answer, on Windows the message could be lost: the pipe
# closed before the running copy had read it.
ANSWER: Final = b"ok"
KNOWN_MESSAGES: Final = (SHOW_MESSAGE, TOGGLE_OVERLAY_MESSAGE)
CONNECT_TIMEOUT_MS: Final = 500
ANSWER_TIMEOUT_MS: Final = 2_000  # how long the second copy waits for "ok"
MAX_MESSAGE_BYTES: Final = 64  # our messages are a few bytes; anything longer is not ours
LOCK_FILE_NAME: Final = "instance.lock"
# A copy that just won the lock needs a moment before it listens. A losing copy asks a few
# times, so it does not give up too early.
TELL_ATTEMPTS: Final = 5
TELL_PAUSE_MS: Final = 100
# Unix socket paths may only be about 108 bytes long; stay well below.
MAX_SOCKET_PATH_LENGTH: Final = 100
_SHORT_FALLBACK_ROOT: Final = Path("/tmp")  # noqa: S108 - a private per-user folder is made in it


def default_name() -> str:
    """The channel name for this user, so two users on one computer do not clash."""
    try:
        user = getpass.getuser()
    except KeyError, OSError:
        user = "player"
    return "wow-coach-" + re.sub(r"[^A-Za-z0-9_.-]", "_", user)


def socket_folder(
    environ: Mapping[str, str],
    platform: str = sys.platform,
    user_id: int | None = None,
    fallback_root: Path = _SHORT_FALLBACK_ROOT,
) -> Path | None:
    """The private folder for the socket file, or None where sockets need no folder (Windows).

    The first choice is ``$XDG_RUNTIME_DIR/wow-coach``: a folder only this user can open. If
    there is none (macOS, or no login session), a short per-user folder in ``/tmp`` is used.
    Nothing is created here.
    """
    if platform == "win32":
        return None
    runtime = environ.get("XDG_RUNTIME_DIR", "")
    if runtime and Path(runtime).is_absolute():
        return Path(runtime) / "wow-coach"
    user = os.getuid() if user_id is None and hasattr(os, "getuid") else user_id
    return fallback_root / f"wow-coach-{user}"


def socket_address(
    name: str,
    environ: Mapping[str, str],
    platform: str = sys.platform,
    fallback_root: Path = _SHORT_FALLBACK_ROOT,
) -> str:
    """The full address to listen on: a path in the private folder (a plain name on Windows).

    If the path would be too long for the system, the short per-user folder is used instead.
    """
    folder = socket_folder(environ, platform, fallback_root=fallback_root)
    if folder is None:
        return name
    path = folder / f"{name}.sock"
    if len(str(path)) > MAX_SOCKET_PATH_LENGTH:
        shorter = socket_folder({}, platform, fallback_root=fallback_root)
        if shorter is not None:
            path = shorter / f"{name}.sock"
    return str(path)


if sys.platform == "win32":

    def _make_private_folder(folder: Path) -> bool:
        """On Windows the address is a pipe name: there is no socket folder to make."""
        del folder
        return True

else:

    def _make_private_folder(folder: Path) -> bool:
        """Create ``folder`` for this user only. False when it is not safe to use.

        A folder that already exists is only trusted when it is a real folder (not a link)
        that belongs to this user. Then its permissions are tightened to this user alone.
        """
        try:
            folder.mkdir(mode=stat.S_IRWXU, parents=True, exist_ok=True)
            info = folder.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                return False
            folder.chmod(stat.S_IRWXU)
        except OSError:
            return False
        return True


class SingleInstance(QObject):
    """Makes sure only one copy of the app runs, and lets a second copy wake the first."""

    # Another copy was started: bring the window to the front.
    show_requested = Signal()
    # Another copy was started with ``--toggle-overlay``: show or hide the overlay.
    toggle_overlay_requested = Signal()

    def __init__(
        self,
        name: str | None = None,
        *,
        environ: Mapping[str, str] | None = None,
        platform: str = sys.platform,
        fallback_root: Path = _SHORT_FALLBACK_ROOT,
    ) -> None:
        """Create it.

        Args:
            name: The channel name (default: one per user).
            environ: Environment variables (default: the real ones). They say where the lock
                file and the socket folder are, so tests point them at temporary folders.
            platform: ``sys.platform`` value to act for (tests pass their own).
            fallback_root: Where the short per-user socket folder goes when there is no
                ``$XDG_RUNTIME_DIR``.
        """
        super().__init__()
        self._name = name or default_name()
        environment = os.environ if environ is None else environ
        self._platform = platform
        self._lock = QLockFile(str(data_folder(environ=environment) / LOCK_FILE_NAME))
        self._address = socket_address(self._name, environment, platform, fallback_root)
        self._server: QLocalServer | None = None
        # Connections from second copies that are still open, with what they sent so far.
        self._talking: dict[QLocalSocket, bytes] = {}

    @property
    def address(self) -> str:
        """Where the running copy listens (a file path, or a name on Windows)."""
        return self._address

    def claim(self, message: bytes = SHOW_MESSAGE) -> bool:
        """Try to become the one running copy.

        Returns True when this copy won the lock and should go on. Returns False when another
        copy was already running: it was sent ``message`` (by default "show your window"), and
        this copy should exit.
        """
        Path(self._lock.fileName()).parent.mkdir(parents=True, exist_ok=True)
        if self._lock.tryLock(0):
            self._listen()
            return True
        if self._lock.error() != QLockFile.LockError.LockFailedError:
            # The lock file cannot be used at all (for example no permission). Better to run
            # twice than not to run, so go on without a lock.
            _log.warning("Could not use the one-copy lock file (%s)", self._lock.error().name)
            self._listen()
            return True
        # Someone else holds the lock, so a copy is running (or starting). Tell it to show.
        self._tell_the_running_copy(message)
        return False

    def close(self) -> None:
        """Stop listening and give the lock back (the app is closing or restarting)."""
        server, self._server = self._server, None
        if server is not None:
            server.close()
        self._lock.unlock()

    # ---- the second copy -----------------------------------------------------------------

    def _tell_the_running_copy(self, message: bytes) -> bool:
        """Send ``message`` to the running copy. False when it never answers."""
        for attempt in range(TELL_ATTEMPTS):
            if attempt:
                QThread.msleep(TELL_PAUSE_MS)
            socket = QLocalSocket()
            socket.connectToServer(self._address)
            if not socket.waitForConnected(CONNECT_TIMEOUT_MS):
                continue
            socket.write(message)
            socket.flush()
            socket.waitForBytesWritten(CONNECT_TIMEOUT_MS)
            # Wait for the running copy's "ok" before hanging up (see ANSWER). If it never
            # comes, the message was most likely still delivered, so this copy exits anyway.
            socket.waitForReadyRead(ANSWER_TIMEOUT_MS)
            socket.disconnectFromServer()
            return True
        return False

    # ---- the first copy ------------------------------------------------------------------

    def _listen(self) -> None:
        if self._platform != "win32" and not _make_private_folder(Path(self._address).parent):
            # The app still works; it just cannot be woken by a second copy.
            _log.warning("The folder for the one-copy socket is not private: not listening")
            return
        # Whoever held the lock before is gone, so a file with this name is a leftover (a
        # crash, or somebody else's squatting). Remove it, or listening would fail.
        QLocalServer.removeServer(self._address)
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not server.listen(self._address):
            _log.warning("Could not listen for a second copy: %s", server.errorString())
            return
        server.newConnection.connect(self._on_connection)
        self._server = server

    def _on_connection(self) -> None:
        server = self._server
        while server is not None and server.hasPendingConnections():
            socket = server.nextPendingConnection()
            # The message may arrive a moment after the connection: read it when it does,
            # without blocking the window. Each connection is kept in ``_talking`` until it
            # closes, and cleaned up exactly once then.
            self._talking[socket] = b""
            socket.readyRead.connect(self._on_ready_read)
            socket.disconnected.connect(self._on_hang_up)
            if socket.bytesAvailable() > 0:
                self._read(socket)

    def _on_ready_read(self) -> None:
        socket = self.sender()
        if isinstance(socket, QLocalSocket) and socket in self._talking:
            self._read(socket)

    def _on_hang_up(self) -> None:
        socket = self.sender()
        if isinstance(socket, QLocalSocket) and socket in self._talking:
            del self._talking[socket]
            socket.deleteLater()

    def _read(self, socket: QLocalSocket) -> None:
        """Read a second copy's message, act on it, answer "ok" and hang up."""
        received = self._talking[socket] + bytes(socket.readAll().data())
        self._talking[socket] = received[:MAX_MESSAGE_BYTES]
        message = self._talking[socket]
        if message not in KNOWN_MESSAGES:
            if not any(known.startswith(message) for known in KNOWN_MESSAGES):
                socket.disconnectFromServer()  # not one of ours: hang up at once
            return  # else only part of a message so far: wait for the rest
        self._talking[socket] = b""  # handled: a repeat read must not act twice
        if message == SHOW_MESSAGE:
            self.show_requested.emit()
        else:
            self.toggle_overlay_requested.emit()
        socket.write(ANSWER)
        socket.flush()
        socket.disconnectFromServer()
