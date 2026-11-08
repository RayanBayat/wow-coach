"""Security-hardening tests for Sign in with ChatGPT (fake servers only, no real network)."""

import base64
import os
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx2
import keyring
import keyring.backend
import keyring.backends.fail
import pytest
from test_chatgpt_signin import (
    ISSUED_CLIENT_ID,
    NOW,
    SECRET_REFRESH,
    Fixture,
    good_claims,
    make_jwt,
)

from wow_coach.ai import chatgpt_signin as signin
from wow_coach.ai.base import AIError, NotSignedIn
from wow_coach.ai.chatgpt_signin import (
    ChatGPTSignIn,
    LoopbackServer,
    PlanUseNotEnabled,
    RefreshFileLock,
    check_id_token,
    new_pkce,
)
from wow_coach.keychain import Keychain


@pytest.fixture(autouse=True)
def _no_real_keychain() -> None:
    keyring.set_keyring(keyring.backends.fail.Keyring())  # type: ignore[no-untyped-call]


def get(url: str, headers: dict[str, str] | None = None) -> httpx2.Response:
    with httpx2.Client(trust_env=False) as client:
        return client.get(url, headers=headers)


# ---- refresh keeps the new refresh token ------------------------------------------------


def test_a_partial_refresh_reply_still_keeps_the_new_refresh_token() -> None:
    fx = Fixture()
    fx.manager.sign_in()
    fx.auth.override = {"refresh_token": "NEW-refresh", "access_token": None}  # no access token
    with pytest.raises(AIError):
        fx.manager.refresh()
    # The old token is dead at OpenAI now; the new one must not be lost.
    assert fx.keychain.get(signin.KEY_REFRESH_TOKEN) == "NEW-refresh"


@pytest.mark.parametrize("value", ["3600", "3600.5", 3600, None])
def test_expires_in_may_be_a_numeric_string_or_missing(value: object) -> None:
    fx = Fixture()
    fx.manager.sign_in()
    fx.auth.override = {"expires_in": value}
    fx.now += 4000
    assert fx.manager.refresh()
    fx.now += 3500  # still inside the (default or given) hour
    assert fx.manager.access_token() == "access-token-SECRET-1"
    assert len(fx.auth.forms) == 2  # no third request


@pytest.mark.parametrize("value", ["soon", -5, 0, "nan", "inf", True])
def test_nonsense_expires_in_is_refused(value: object) -> None:
    fx = Fixture()
    fx.manager.sign_in()
    fx.auth.override = {"expires_in": value}
    with pytest.raises(AIError, match="incomplete"):
        fx.manager.refresh()


# ---- the keychain: a failing keychain must never cause a second registration --------------


class LockedBackend(keyring.backend.KeyringBackend):
    """A keychain that exists but can be locked (raises raw errors, like a DBus failure)."""

    priority = 1

    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.items: dict[tuple[str, str], str] = {}
        self.locked = False

    def get_password(self, service: str, username: str) -> str | None:
        if self.locked:
            raise RuntimeError("wallet locked")
        return self.items.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        if self.locked:
            raise RuntimeError("wallet locked")
        self.items[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.items.pop((service, username), None)


def test_a_locked_keychain_never_leads_to_a_second_registration() -> None:
    backend = LockedBackend()
    keyring.set_keyring(backend)
    fx = Fixture()
    fx.manager.sign_in()  # registers once
    assert len(fx.urls) == 1
    backend.locked = True
    with pytest.raises(AIError, match="unlock it"):
        fx.manager.sign_in()
    with pytest.raises(AIError, match="unlock it"):
        fx.manager.refresh()  # (access_token() would still use the token held in memory)
    assert len(fx.urls) == 1  # the browser was never opened again
    backend.locked = False
    fx.manager.sign_in()
    assert parse_qs(urlsplit(fx.urls[1]).query)["client_id"] == [ISSUED_CLIENT_ID]  # reused


# ---- the loopback server --------------------------------------------------------------------


def test_an_idle_connection_cannot_stall_the_sign_in(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(signin._CallbackHandler, "timeout", 0.3)
    server = LoopbackServer(0, "s")
    idle = socket.create_connection(("127.0.0.1", server.port))  # connects, says nothing
    try:
        results: list[int] = []
        visitor = threading.Thread(
            target=lambda: results.append(
                get(f"http://127.0.0.1:{server.port}/auth/callback?state=s&code=abc").status_code
            )
        )
        started = time.monotonic()
        visitor.start()
        assert server.wait(3.0) == {"state": "s", "code": "abc"}
        visitor.join()
        assert time.monotonic() - started < 2.0
        time.sleep(0.5)  # let the idle connection time out, which must stay quiet
    finally:
        idle.close()
        server.close()
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""


def test_the_overall_deadline_holds_even_with_an_idle_connection() -> None:
    server = LoopbackServer(0, "s")
    idle = socket.create_connection(("127.0.0.1", server.port))
    try:
        started = time.monotonic()
        assert server.wait(0.5) is None
        assert time.monotonic() - started < 1.5
    finally:
        idle.close()
        server.close()


def test_a_second_listener_cannot_share_the_port() -> None:
    server = LoopbackServer(0, "s")
    try:
        with pytest.raises(AIError, match="busy"):
            LoopbackServer(server.port, "s")
        other = socket.socket()
        try:
            with pytest.raises(OSError):
                other.bind(("127.0.0.1", server.port))
        finally:
            other.close()
    finally:
        server.close()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows holds the port a while after use")
def test_the_port_can_be_used_again_right_after_a_sign_in() -> None:
    first = LoopbackServer(0, "s")
    port = first.port
    visitor = threading.Thread(target=lambda: get(f"http://127.0.0.1:{port}/auth/callback?state=s"))
    visitor.start()
    assert first.wait(3.0) is not None
    visitor.join()
    first.close()
    LoopbackServer(port, "s").close()  # must not fail because of a lingering connection


def test_a_foreign_host_header_is_refused() -> None:
    server = LoopbackServer(0, "s")
    try:
        results: list[int] = []
        visitor = threading.Thread(
            target=lambda: results.append(
                get(
                    f"http://127.0.0.1:{server.port}/auth/callback?state=s&code=abc",
                    headers={"Host": "evil.example"},
                ).status_code
            )
        )
        visitor.start()
        assert server.wait(0.5) is None
        visitor.join()
        assert results == [400]
    finally:
        server.close()


def test_a_non_ascii_state_is_refused_not_a_crash() -> None:
    server = LoopbackServer(0, "s")
    try:
        results: list[int] = []
        visitor = threading.Thread(
            target=lambda: results.append(
                get(f"http://127.0.0.1:{server.port}/auth/callback?state=%C3%A9%FF").status_code
            )
        )
        visitor.start()
        assert server.wait(0.5) is None
        visitor.join()
        assert results == [400]
    finally:
        server.close()


# ---- locks ----------------------------------------------------------------------------------


def test_sign_in_and_sign_out_hold_the_manager_lock() -> None:
    fx = Fixture()
    held: list[bool] = []
    original = fx.open_browser

    def spying_browser(url: str) -> bool:
        held.append(fx.manager._lock.locked())
        return original(url)

    fx.manager._open_browser = spying_browser
    fx.manager.sign_in()
    assert held == [True]
    assert not fx.manager._lock.locked()


def test_the_lock_file_exists_during_a_refresh_and_is_removed_after(tmp_path: Path) -> None:
    lock = tmp_path / "data" / "chatgpt-refresh.lock"
    fx = Fixture()
    fx.manager = ChatGPTSignIn(
        fx.keychain,
        transport=fx.auth.transport(),
        port=0,
        open_browser=fx.open_browser,
        clock=lambda: fx.now,
        lock_path=lock,
    )
    fx.manager.sign_in()
    seen: list[bool] = []
    fx.auth.on_token_request = lambda: seen.append(lock.exists())
    fx.manager.refresh()
    assert seen == [True]
    assert not lock.exists()
    assert fx.keychain.get(signin.KEY_REFRESH_TOKEN)  # and nothing secret is in the lock
    fx.auth.token_status = 400
    fx.auth.error_code = "invalid_grant"
    with pytest.raises(NotSignedIn):
        fx.manager.refresh()
    assert not lock.exists()  # removed on errors too


class FakeTime:
    def __init__(self) -> None:
        self.now = 1000.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_file_lock_is_empty_and_removed_even_after_an_error(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    lock = RefreshFileLock(path)
    with pytest.raises(RuntimeError), lock.held():
        assert path.read_bytes() == b""
        raise RuntimeError("boom")
    assert not path.exists()


def test_file_lock_waits_then_gives_up_with_a_plain_sentence(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    fake = FakeTime()
    path.write_bytes(b"")
    os.utime(path, (fake.now, fake.now))  # fresh, so not stale
    lock = RefreshFileLock(path, clock=fake.clock, sleep=fake.sleep, wait_seconds=2.0)
    with pytest.raises(AIError, match="Another wow-coach window"), lock.held():
        pass
    assert path.exists()  # not ours, so we leave it alone


def test_a_stale_lock_is_taken_over(tmp_path: Path) -> None:
    path = tmp_path / "x.lock"
    path.write_bytes(b"")
    fake = FakeTime()
    os.utime(path, (fake.now - 31, fake.now - 31))  # older than 30 seconds
    with RefreshFileLock(path, clock=fake.clock, sleep=fake.sleep).held():
        assert path.exists()
    assert not path.exists()


def test_terminal_refresh_error_keeps_a_newer_token_saved_by_someone_else() -> None:
    fx = Fixture()
    fx.manager.sign_in()
    fx.auth.token_status = 400
    fx.auth.error_code = "refresh_token_reused"
    # While our request is on the wire, another program saves a newer refresh token.
    fx.auth.on_token_request = lambda: fx.keychain.set(signin.KEY_REFRESH_TOKEN, "NEWER-token")
    with pytest.raises(NotSignedIn):
        fx.manager.refresh()
    assert fx.keychain.get(signin.KEY_REFRESH_TOKEN) == "NEWER-token"


# ---- plain sentences, never tracebacks ----------------------------------------------------------


def test_any_http_library_error_becomes_a_plain_sentence() -> None:
    def too_many(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.TooManyRedirects("loop", request=request)

    keychain = Keychain()
    keychain.set(signin.KEY_REFRESH_TOKEN, "r")
    keychain.set(signin.KEY_CLIENT_ID, ISSUED_CLIENT_ID)
    manager = ChatGPTSignIn(keychain, transport=httpx2.MockTransport(too_many))
    with pytest.raises(AIError, match="Could not reach"):
        manager.refresh()


def test_absurdly_nested_json_is_an_error_not_a_crash() -> None:
    deep = "[" * 300_000
    payload = base64.urlsafe_b64encode(deep.encode()).rstrip(b"=").decode()
    with pytest.raises(AIError, match="could not be read"):
        check_id_token(f"e30.{payload}.sig", audience="a", nonce="n", now=NOW)

    def nested(request: httpx2.Request) -> httpx2.Response:  # noqa: ARG001
        return httpx2.Response(400, content=deep.encode())

    keychain = Keychain()
    keychain.set(signin.KEY_REFRESH_TOKEN, "r")
    keychain.set(signin.KEY_CLIENT_ID, ISSUED_CLIENT_ID)
    manager = ChatGPTSignIn(keychain, transport=httpx2.MockTransport(nested))
    with pytest.raises(AIError):
        manager.refresh()


# ---- revoke before giving up ----------------------------------------------------------------


def test_refused_tokens_are_revoked_when_plan_use_was_not_allowed() -> None:
    fx = Fixture()
    fx.auth.scope = "openid profile"
    with pytest.raises(PlanUseNotEnabled):
        fx.manager.sign_in()
    assert [f["token"] for f in fx.auth.revoke_forms] == [f"{SECRET_REFRESH}-1"]


def test_refused_tokens_are_revoked_when_an_id_token_claim_is_wrong() -> None:
    fx = Fixture()
    fx.auth.id_claims = good_claims("wrong-nonce")
    with pytest.raises(AIError):
        fx.manager.sign_in()
    assert len(fx.auth.revoke_forms) == 1
    assert fx.auth.revoke_forms[0]["client_id"] == ISSUED_CLIENT_ID


def test_a_new_sign_in_revokes_the_old_refresh_token() -> None:
    fx = Fixture()
    fx.manager.sign_in()
    assert fx.auth.revoke_forms == []
    fx.manager.sign_in()
    assert [f["token"] for f in fx.auth.revoke_forms] == [f"{SECRET_REFRESH}-1"]
    assert fx.keychain.get(signin.KEY_REFRESH_TOKEN) == f"{SECRET_REFRESH}-2"


def test_a_missing_refresh_token_in_the_exchange_is_an_error() -> None:
    fx = Fixture()
    fx.auth.override = {"refresh_token": None}
    with pytest.raises(AIError, match="renewable"):
        fx.manager.sign_in()


# ---- ID token ------------------------------------------------------------------------------------


def _check(**change: object) -> dict[str, object]:
    token = make_jwt({**good_claims("n1"), **change})
    return check_id_token(token, audience=ISSUED_CLIENT_ID, nonce="n1", now=NOW)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, None])
def test_exp_must_be_a_finite_number(bad: object) -> None:
    with pytest.raises(AIError, match="expired"):
        _check(exp=bad)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "yesterday"])
def test_iat_if_present_must_be_a_finite_number(bad: object) -> None:
    with pytest.raises(AIError, match="could not be read"):
        _check(iat=bad)


def test_a_one_item_audience_list_needs_no_azp() -> None:
    # What OpenAI really sends (seen 2026-11-08): "aud": ["<issued client id>"], no azp.
    # OIDC Core 3.1.3.7 only asks for azp when there are several audiences.
    assert _check(aud=[ISSUED_CLIENT_ID])["sub"] == "user-1"
    with pytest.raises(AIError, match="another app"):
        _check(aud=["someone-else"])
    with pytest.raises(AIError, match="another app"):
        _check(aud=[ISSUED_CLIENT_ID], azp="someone-else")


def test_several_audiences_need_azp_to_be_us() -> None:
    audiences = ["x", ISSUED_CLIENT_ID]
    with pytest.raises(AIError, match="another app"):
        _check(aud=audiences)
    with pytest.raises(AIError, match="another app"):
        _check(aud=audiences, azp="x")
    assert _check(aud=audiences, azp=ISSUED_CLIENT_ID)["sub"] == "user-1"


@pytest.mark.parametrize("bad", ["", None, 5, ["a"]])
def test_sub_must_be_a_non_empty_string(bad: object) -> None:
    with pytest.raises(AIError, match="who signed in"):
        _check(sub=bad)


def test_a_different_account_is_refused_until_the_player_signs_out() -> None:
    fx = Fixture()
    fx.manager.sign_in()
    fx.auth.subject = "someone-else"
    with pytest.raises(AIError, match="different ChatGPT account"):
        fx.manager.sign_in()
    # The refused sign-in was revoked and the first account's sign-in is untouched.
    assert fx.keychain.get(signin.KEY_REFRESH_TOKEN) == f"{SECRET_REFRESH}-1"
    assert len(fx.auth.revoke_forms) == 1
    fx.manager.sign_out()
    fx.manager.sign_in()  # now allowed
    assert fx.keychain.get(signin.KEY_ACCOUNT) == "someone-else"


def test_the_registration_placeholder_is_never_accepted_as_the_issued_client_id() -> None:
    fx = Fixture(lambda q: {"code": "c", "state": q["state"], "client_id": "dynamic_agent_client"})
    with pytest.raises(AIError, match="registering"):
        fx.manager.sign_in()
    assert fx.keychain.get(signin.KEY_CLIENT_ID) is None


def test_pkce_verifier_is_hidden_from_repr() -> None:
    pkce = new_pkce()
    assert pkce.verifier not in repr(pkce)
    assert pkce.challenge in repr(pkce)


def test_forget_registration_makes_the_next_sign_in_register_again() -> None:
    fx = Fixture()
    fx.manager.sign_in()
    host_id = fx.keychain.get(signin.KEY_HOST_ID)
    fx.manager.forget_registration()
    assert not fx.manager.is_signed_in
    assert fx.keychain.get(signin.KEY_CLIENT_ID) is None
    fx.manager.sign_in()
    assert "dynamic_agent_client" in fx.urls[1]
    assert fx.keychain.get(signin.KEY_HOST_ID) == host_id  # the install id is kept
