"""Keeps wow-coach's small secrets in the operating system's keychain.

Secrets here are the ChatGPT refresh token and the client id OpenAI issued (see
``docs/plans/coach-panel.md``, section C4). They go through the ``keyring`` package, which talks
to Windows Credential Manager, the macOS Keychain or the Linux Secret Service.

Some computers (for example a bare Linux setup) have no keychain. Then we keep the values in
memory for this run only and say so. We never write a secret to a plain file, because a file
can be copied, backed up or synced by accident.

The module is called ``keychain`` and not ``secrets`` because Python already has a ``secrets``
module and ours would hide it.
"""

import logging

import keyring
import keyring.errors

SERVICE_NAME = "wow-coach"

_log = logging.getLogger(__name__)

NO_KEYCHAIN_NOTICE = (
    "This computer has no usable password keychain, so your sign-in is kept in memory only "
    "and will be forgotten when wow-coach closes."
)


class Keychain:
    """Stores named secrets in the system keychain, or in memory when there is none."""

    def __init__(self) -> None:
        """Create a keychain. The first failing keychain call switches to memory only."""
        self._memory: dict[str, str] = {}
        self._keychain_works = True

    @property
    def persistent(self) -> bool:
        """True while secrets really go to the system keychain (they survive a restart)."""
        return self._keychain_works

    @property
    def notice(self) -> str | None:
        """A plain sentence for the player when secrets are memory-only, else ``None``."""
        return None if self._keychain_works else NO_KEYCHAIN_NOTICE

    def get(self, name: str) -> str | None:
        """Return the secret called ``name``, or ``None`` if there is none."""
        if self._keychain_works:
            try:
                return keyring.get_password(SERVICE_NAME, name)
            except keyring.errors.KeyringError:
                self._give_up_on_keychain()
        return self._memory.get(name)

    def set(self, name: str, value: str) -> None:
        """Save ``value`` under ``name`` (replacing an older one)."""
        if self._keychain_works:
            try:
                keyring.set_password(SERVICE_NAME, name, value)
                return
            except keyring.errors.KeyringError:
                self._give_up_on_keychain()
        self._memory[name] = value

    def delete(self, name: str) -> None:
        """Forget the secret called ``name``. Does nothing if there is none."""
        self._memory.pop(name, None)
        if not self._keychain_works:
            return
        try:
            keyring.delete_password(SERVICE_NAME, name)
        except keyring.errors.PasswordDeleteError:
            pass  # it was not there: that is the state we wanted
        except keyring.errors.KeyringError:
            self._give_up_on_keychain()

    def _give_up_on_keychain(self) -> None:
        """Switch to memory-only for the rest of this run and tell the player once."""
        self._keychain_works = False
        _log.warning(NO_KEYCHAIN_NOTICE)
