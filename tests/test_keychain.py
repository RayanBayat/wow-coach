"""Tests for the keychain wrapper, using fake keyring backends (never the real keychain)."""

import logging
from pathlib import Path

import keyring
import keyring.backend
import keyring.backends.fail
import pytest

from wow_coach.ai.base import AIError
from wow_coach.keychain import SERVICE_NAME, Keychain


class MemoryBackend(keyring.backend.KeyringBackend):
    """A keyring that keeps everything in a dict."""

    priority = 1

    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.items: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.items.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.items[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.items:
            raise keyring.errors.PasswordDeleteError("not found")
        del self.items[(service, username)]


@pytest.fixture(autouse=True)
def _never_the_real_keychain() -> None:
    """Every test starts with a keychain that always fails, so none can touch the real one."""
    keyring.set_keyring(keyring.backends.fail.Keyring())  # type: ignore[no-untyped-call]


@pytest.fixture
def backend() -> MemoryBackend:
    fake = MemoryBackend()
    keyring.set_keyring(fake)
    return fake


def test_round_trip_goes_to_the_keychain(backend: MemoryBackend) -> None:
    keychain = Keychain()
    keychain.set("token", "abc")
    assert keychain.get("token") == "abc"
    assert backend.items[(SERVICE_NAME, "token")] == "abc"
    assert keychain.persistent
    assert keychain.notice is None


@pytest.mark.usefixtures("backend")
def test_missing_secret_is_none() -> None:
    assert Keychain().get("nothing") is None


@pytest.mark.usefixtures("backend")
def test_delete_removes_and_ignores_missing() -> None:
    keychain = Keychain()
    keychain.set("token", "abc")
    keychain.delete("token")
    keychain.delete("token")  # second time: nothing to delete, no error
    assert keychain.get("token") is None


def test_without_a_backend_values_stay_in_memory(caplog: pytest.LogCaptureFixture) -> None:
    keychain = Keychain()
    with caplog.at_level(logging.WARNING):
        keychain.set("token", "super-secret")
    assert keychain.get("token") == "super-secret"
    assert not keychain.persistent
    assert keychain.notice is not None
    assert "memory" in keychain.notice
    assert "super-secret" not in caplog.text
    keychain.delete("token")
    assert keychain.get("token") is None


def test_memory_values_are_not_shared_between_keychains() -> None:
    first = Keychain()
    first.set("token", "x")
    assert Keychain().get("token") is None


def test_no_secret_is_ever_written_to_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    Keychain().set("token", "super-secret")
    assert list(tmp_path.iterdir()) == []


class LockedBackend(MemoryBackend):
    """A keychain that exists but fails, like a locked wallet (raises a raw, unwrapped error)."""

    locked = True

    def get_password(self, service: str, username: str) -> str | None:
        if self.locked:
            raise RuntimeError("DBus: wallet is locked")
        return super().get_password(service, username)

    def set_password(self, service: str, username: str, password: str) -> None:
        if self.locked:
            raise RuntimeError("DBus: wallet is locked")
        super().set_password(service, username, password)


def test_a_locked_keychain_raises_a_plain_error_and_never_pretends_secrets_are_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = LockedBackend()
    keyring.set_keyring(fake)
    keychain = Keychain()
    with pytest.raises(AIError, match="unlock it") as caught:
        keychain.get("token")
    assert "DBus" not in str(caught.value)
    with pytest.raises(AIError):
        keychain.set("token", "super-secret")
    assert keychain.persistent  # still the real keychain, not a silent memory fallback
    assert "super-secret" not in caplog.text
    fake.locked = False  # the player unlocks it: everything works again
    keychain.set("token", "abc")
    assert keychain.get("token") == "abc"


def test_keyring_error_other_than_no_keyring_is_also_a_plain_error() -> None:
    class Broken(MemoryBackend):
        def get_password(self, service: str, username: str) -> str | None:  # noqa: ARG002
            raise keyring.errors.InitError("cannot start")

    keyring.set_keyring(Broken())
    with pytest.raises(AIError, match="could not be used"):
        Keychain().get("token")
