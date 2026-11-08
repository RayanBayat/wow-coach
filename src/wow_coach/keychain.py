"""Keeps wow-coach's small secrets in the operating system's keychain.

Secrets here are the ChatGPT refresh token and the client id OpenAI issued (see
``docs/plans/coach-panel.md``, section C4). They go through the ``keyring`` package, which talks
to Windows Credential Manager, the macOS Keychain or the Linux Secret Service.

Some computers (for example a bare Linux setup) have no keychain at all. Then we keep the values
in memory for this run only and say so. We never write a secret to a plain file, because a file
can be copied, backed up or synced by accident.

A keychain that exists but fails (locked, the wallet service is down, a DBus error) is a
different case. Pretending the secrets are missing could make wow-coach register a second
time and lose the sign-in, so it raises a plain ``AIError`` and the player unlocks it.

The module is called ``keychain`` and not ``secrets`` because Python already has a ``secrets``
module and ours would hide it.
"""

import logging

import keyring
import keyring.backends.fail
import keyring.errors

from wow_coach.ai.base import AIError

SERVICE_NAME = "wow-coach"

_log = logging.getLogger(__name__)

NO_KEYCHAIN_NOTICE = (
    "This computer has no usable password keychain, so your sign-in is kept in memory only "
    "and will be forgotten when wow-coach closes."
)
KEYCHAIN_FAILED_MESSAGE = (
    "Your password keychain could not be used. It may be locked: unlock it "
    "(for example the KDE Wallet or your system keyring) and try again."
)


class Keychain:
    """Stores named secrets in the system keychain, or in memory when there is none."""

    def __init__(self) -> None:
        """Create a keychain. If the computer has none, secrets stay in memory."""
        self._memory: dict[str, str] = {}
        self._memory_only = False

    @property
    def persistent(self) -> bool:
        """True while secrets really go to the system keychain (they survive a restart)."""
        return not self._use_memory()

    @property
    def notice(self) -> str | None:
        """A plain sentence for the player when secrets are memory-only, else ``None``."""
        return NO_KEYCHAIN_NOTICE if self._use_memory() else None

    def get(self, name: str) -> str | None:
        """Return the secret called ``name``, or ``None`` if there is none.

        Raises:
            AIError: The keychain exists but failed (for example it is locked).
        """
        if self._use_memory():
            return self._memory.get(name)
        try:
            return keyring.get_password(SERVICE_NAME, name)
        except keyring.errors.NoKeyringError:
            self._switch_to_memory()
            return self.get(name)
        except Exception as error:
            raise self._failure(error) from error

    def set(self, name: str, value: str) -> None:
        """Save ``value`` under ``name`` (replacing an older one).

        Raises:
            AIError: The keychain exists but failed (for example it is locked).
        """
        if self._use_memory():
            self._memory[name] = value
            return
        try:
            keyring.set_password(SERVICE_NAME, name, value)
        except keyring.errors.NoKeyringError:
            self._switch_to_memory()
            self.set(name, value)
        except Exception as error:
            raise self._failure(error) from error

    def delete(self, name: str) -> None:
        """Forget the secret called ``name``. Does nothing if there is none."""
        self._memory.pop(name, None)
        if self._use_memory():
            return
        try:
            keyring.delete_password(SERVICE_NAME, name)
        except keyring.errors.PasswordDeleteError:
            pass  # it was not there: that is the state we wanted
        except keyring.errors.NoKeyringError:
            self._switch_to_memory()
        except Exception as error:
            raise self._failure(error) from error

    def _use_memory(self) -> bool:
        """True when the computer has no keychain at all (decided once, then remembered)."""
        if not self._memory_only and isinstance(
            keyring.get_keyring(), keyring.backends.fail.Keyring
        ):
            self._switch_to_memory()
        return self._memory_only

    def _switch_to_memory(self) -> None:
        self._memory_only = True
        _log.warning(NO_KEYCHAIN_NOTICE)

    def _failure(self, error: Exception) -> AIError:
        """Turn a keychain problem into a plain error. Only the error TYPE is logged."""
        _log.warning("The system keychain failed (%s).", type(error).__name__)
        return AIError(KEYCHAIN_FAILED_MESSAGE)
