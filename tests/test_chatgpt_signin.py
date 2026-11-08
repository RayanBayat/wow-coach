"""Tests for Sign in with ChatGPT, against a fake auth.openai.com (no real network).

The "browser" in these tests is a small function that visits the loopback address the way a real
browser would after the player signs in.
"""

import base64
import hashlib
import json
import logging
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx2
import keyring
import keyring.backends.fail
import pytest

from wow_coach.ai import chatgpt_signin as signin
from wow_coach.ai.base import AIError, NotSignedIn
from wow_coach.ai.chatgpt_signin import (
    ChatGPTSignIn,
    LoopbackServer,
    PlanUseNotEnabled,
    check_id_token,
    new_pkce,
)
from wow_coach.keychain import Keychain

NOW = 1_800_000_000.0
ISSUED_CLIENT_ID = "oaiapp_test123"
SECRET_ACCESS = "access-token-SECRET-1"  # noqa: S105
SECRET_REFRESH = "refresh-token-SECRET-1"  # noqa: S105


@pytest.fixture(autouse=True)
def _no_real_keychain() -> Iterator[None]:
    keyring.set_keyring(keyring.backends.fail.Keyring())  # type: ignore[no-untyped-call]
    yield


def make_jwt(claims: dict[str, object]) -> str:
    """An unsigned JWT: header.payload.signature (the signature part is not checked)."""

    def part(data: dict[str, object]) -> str:
        raw = json.dumps(data).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{part({'alg': 'none'})}.{part(claims)}.sig"


def good_claims(nonce: str, audience: str = ISSUED_CLIENT_ID) -> dict[str, object]:
    return {
        "iss": signin.ISSUER,
        "aud": audience,
        "exp": NOW + 600,
        "nonce": nonce,
        "sub": "user-1",
        "email": "player@example.test",
    }


class FakeAuth:
    """A fake auth.openai.com: remembers every form it received, answers like the docs say."""

    def __init__(self) -> None:
        self.nonce = ""
        self.forms: list[dict[str, str]] = []
        self.revoke_forms: list[dict[str, str]] = []
        self.token_status = 200
        self.error_code = ""
        self.scope = signin.SCOPES
        self.id_claims: dict[str, object] | None = None  # None = good claims for self.nonce
        self.refresh_counter = 0
        self.revoke_statuses: list[int] = [200]
        self.revoke_calls = 0
        self.subject = "user-1"
        # Changes to the 200 token reply: a value replaces a key, None removes it.
        self.override: dict[str, object | None] = {}
        self.on_token_request: Callable[[], None] | None = None  # runs before a token reply

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if str(request.url) == signin.REVOKE_URL:
            self.revoke_forms.append(form)
            status = self.revoke_statuses[min(self.revoke_calls, len(self.revoke_statuses) - 1)]
            self.revoke_calls += 1
            return httpx2.Response(status)
        assert str(request.url) == signin.TOKEN_URL
        self.forms.append(form)
        if self.on_token_request is not None:
            self.on_token_request()
        if self.token_status != 200:
            return httpx2.Response(self.token_status, json={"error": self.error_code})
        self.refresh_counter += 1
        claims = self.id_claims or {**good_claims(self.nonce), "sub": self.subject}
        reply: dict[str, object | None] = {
            "id_token": make_jwt(claims),
            "access_token": SECRET_ACCESS,
            "refresh_token": f"{SECRET_REFRESH}-{self.refresh_counter}",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": self.scope,
            **self.override,
        }
        return httpx2.Response(200, json={k: v for k, v in reply.items() if v is not None})


class Fixture:
    """A sign-in manager wired to the fakes."""

    def __init__(
        self, browser_answer: Callable[[dict[str, str]], dict[str, str]] | None = None
    ) -> None:
        self.auth = FakeAuth()
        self.keychain = Keychain()
        self.urls: list[str] = []
        self.sleeps: list[float] = []
        self.now = NOW
        self._answer = browser_answer or self.default_answer
        self.manager = ChatGPTSignIn(
            self.keychain,
            transport=self.auth.transport(),
            port=0,
            open_browser=self.open_browser,
            clock=lambda: self.now,
            sleep=self.sleeps.append,
            timeout_seconds=3.0,
        )

    @staticmethod
    def default_answer(query: dict[str, str]) -> dict[str, str]:
        return {"code": "one-time-code", "state": query["state"], "client_id": ISSUED_CLIENT_ID}

    def open_browser(self, url: str) -> bool:
        self.urls.append(url)
        query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        self.auth.nonce = query["nonce"]
        params = self._answer(query)
        threading.Thread(target=visit, args=(query["redirect_uri"], params), daemon=True).start()
        return True


def visit(address: str, params: dict[str, str]) -> None:
    """What the browser does after sign-in: open the redirect address."""
    with httpx2.Client(trust_env=False) as client:
        client.get(address, params=params)


def query_of(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


# ---- PKCE and constants ----------------------------------------------------------------


def test_pkce_challenge_is_the_sha256_of_the_verifier() -> None:
    pkce = new_pkce()
    digest = hashlib.sha256(pkce.verifier.encode()).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert pkce.challenge == expected
    assert 43 <= len(pkce.verifier) <= 128
    assert "=" not in pkce.challenge


def test_pkce_values_are_fresh_every_time() -> None:
    assert new_pkce().verifier != new_pkce().verifier
    assert signin.new_random_value() != signin.new_random_value()


def test_endpoints_match_openais_discovery_document() -> None:
    assert signin.AUTHORIZE_URL == "https://auth.openai.com/api/accounts/authorize"
    assert signin.TOKEN_URL == "https://auth.openai.com/api/accounts/oauth/token"  # noqa: S105
    assert signin.REVOKE_URL == "https://auth.openai.com/api/accounts/oauth/revoke"
    assert signin.RESOURCE == "https://api.openai.com/v1"


# ---- the sign-in flow ------------------------------------------------------------------


def test_first_sign_in_registers_and_keeps_tokens_safely() -> None:
    fx = Fixture()
    account = fx.manager.sign_in()
    assert account.email == "player@example.test"

    first = query_of(fx.urls[0])
    assert first["client_id"] == "dynamic_agent_client"
    assert first["agent_name_hint"] == "wow-coach"
    assert first["code_challenge_method"] == "S256"
    assert first["response_type"] == "code"
    assert first["resource"] == "https://api.openai.com/v1"
    assert "chatgpt.tokens.use.direct" in first["scope"].split()
    assert first["redirect_uri"].startswith("http://127.0.0.1:")
    assert first["redirect_uri"].endswith("/auth/callback")
    assert first["ext_agent_host_id"].startswith("urn:uuid:")

    form = fx.auth.forms[0]
    assert form["grant_type"] == "authorization_code"
    assert form["client_id"] == ISSUED_CLIENT_ID  # the issued id, never dynamic_agent_client
    assert form["code"] == "one-time-code"
    assert form["redirect_uri"] == first["redirect_uri"]
    assert form["resource"] == "https://api.openai.com/v1"
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(form["code_verifier"].encode()).digest()
    ).rstrip(b"=")
    assert challenge.decode() == first["code_challenge"]

    assert fx.keychain.get(signin.KEY_CLIENT_ID) == ISSUED_CLIENT_ID
    assert fx.keychain.get(signin.KEY_REFRESH_TOKEN) == f"{SECRET_REFRESH}-1"
    assert fx.manager.access_token() == SECRET_ACCESS


def test_second_sign_in_reuses_client_and_host_id_and_skips_the_name_hint() -> None:
    fx = Fixture()
    fx.manager.sign_in()
    fx.manager.sign_in()
    first, second = query_of(fx.urls[0]), query_of(fx.urls[1])
    assert second["client_id"] == ISSUED_CLIENT_ID
    assert "agent_name_hint" not in second
    assert second["ext_agent_host_id"] == first["ext_agent_host_id"]
    assert second["state"] != first["state"]


def test_wrong_state_is_refused_and_sign_in_times_out() -> None:
    fx = Fixture(lambda _q: {"code": "c", "state": "forged", "client_id": ISSUED_CLIENT_ID})
    fx.manager = ChatGPTSignIn(
        fx.keychain,
        transport=fx.auth.transport(),
        port=0,
        open_browser=fx.open_browser,
        clock=lambda: NOW,
        timeout_seconds=0.6,
    )
    with pytest.raises(AIError, match="took too long"):
        fx.manager.sign_in()
    assert fx.auth.forms == []  # no code was ever exchanged
    assert fx.keychain.get(signin.KEY_REFRESH_TOKEN) is None


def test_timeout_when_the_player_never_finishes() -> None:
    fx = Fixture()
    fx.manager = ChatGPTSignIn(
        fx.keychain,
        transport=fx.auth.transport(),
        port=0,
        open_browser=lambda _url: True,  # the "browser" opens but the player never signs in
        timeout_seconds=0.3,
    )
    with pytest.raises(AIError, match="took too long"):
        fx.manager.sign_in()


def test_access_denied_stops_without_exchanging_a_code() -> None:
    fx = Fixture(lambda q: {"error": "access_denied", "state": q["state"]})
    with pytest.raises(AIError, match="cancelled"):
        fx.manager.sign_in()
    assert fx.auth.forms == []


def test_registration_without_an_issued_client_id_is_refused() -> None:
    fx = Fixture(lambda q: {"code": "c", "state": q["state"]})
    with pytest.raises(AIError, match="registering"):
        fx.manager.sign_in()
    assert fx.auth.forms == []


def test_callback_with_a_different_client_id_is_refused() -> None:
    fx = Fixture()
    fx.manager.sign_in()
    fx.manager = ChatGPTSignIn(
        fx.keychain,
        transport=fx.auth.transport(),
        port=0,
        open_browser=fx.open_browser,
        clock=lambda: NOW,
        timeout_seconds=3.0,
    )
    fx._answer = lambda q: {"code": "c", "state": q["state"], "client_id": "oaiapp_other"}
    with pytest.raises(AIError, match="different app"):
        fx.manager.sign_in()


def test_token_exchange_error_is_a_plain_sentence() -> None:
    fx = Fixture()
    fx.auth.token_status = 400
    fx.auth.error_code = "invalid_grant"
    with pytest.raises(AIError) as caught:
        fx.manager.sign_in()
    assert "refused the request" in str(caught.value)
    assert "invalid_grant" not in str(caught.value)  # no raw server text
    assert fx.keychain.get(signin.KEY_REFRESH_TOKEN) is None
    # The issued client id is kept, so the next try does not register again.
    assert fx.keychain.get(signin.KEY_CLIENT_ID) == ISSUED_CLIENT_ID


def test_signing_in_without_plan_permission_is_reported_and_stores_no_tokens() -> None:
    fx = Fixture()
    fx.auth.scope = "openid profile email offline_access"
    with pytest.raises(PlanUseNotEnabled, match="ChatGPT plan"):
        fx.manager.sign_in()
    assert fx.keychain.get(signin.KEY_REFRESH_TOKEN) is None


def test_bad_id_token_claims_fail_the_sign_in() -> None:
    fx = Fixture()
    fx.auth.id_claims = good_claims("not-our-nonce")
    with pytest.raises(AIError, match="did not match"):
        fx.manager.sign_in()
    assert fx.keychain.get(signin.KEY_REFRESH_TOKEN) is None


def test_port_in_use_gives_a_clear_message() -> None:
    first = LoopbackServer(0, "s")
    try:
        with pytest.raises(AIError, match="busy"):
            LoopbackServer(first.port, "s")
    finally:
        first.close()


# ---- the loopback server ---------------------------------------------------------------


def _get(url: str, method: str = "GET") -> httpx2.Response:
    with httpx2.Client(trust_env=False) as client:
        return client.request(method, url)


def test_loopback_server_listens_on_127_0_0_1_only() -> None:
    server = LoopbackServer(0, "s")
    try:
        assert server._server.server_address[0] == "127.0.0.1"
    finally:
        server.close()


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("GET", "/other?state=s", 404),
        ("GET", "/auth/callback?state=wrong", 400),
        ("GET", "/auth/callback", 400),
        ("POST", "/auth/callback?state=s", 501),
        ("PUT", "/auth/callback?state=s", 501),
    ],
)
def test_loopback_refuses_wrong_path_state_or_method(method: str, path: str, status: int) -> None:
    server = LoopbackServer(0, "s")
    try:
        results: list[int] = []
        visitor = threading.Thread(
            target=lambda: results.append(
                _get(f"http://127.0.0.1:{server.port}{path}", method).status_code
            )
        )
        visitor.start()
        assert server.wait(0.4) is None  # nothing valid arrived
        visitor.join()
        assert results == [status]
    finally:
        server.close()


def test_loopback_accepts_the_right_request_once_and_shows_a_close_page() -> None:
    server = LoopbackServer(0, "s")
    try:
        pages: list[str] = []
        visitor = threading.Thread(
            target=lambda: pages.append(
                _get(f"http://127.0.0.1:{server.port}/auth/callback?state=s&code=abc").text
            )
        )
        visitor.start()
        assert server.wait(3.0) == {"state": "s", "code": "abc"}
        visitor.join()
        assert "close this tab" in pages[0]
    finally:
        server.close()


# ---- ID token checks -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"aud": "someone-else"}, "another app"),
        ({"aud": ["a", "b"]}, "another app"),
        ({"nonce": "other"}, "did not match"),
        ({"exp": NOW - 1}, "expired"),
        ({"exp": "soon"}, "expired"),
        ({"iss": "https://evil.test"}, "unexpected source"),
    ],
)
def test_id_token_claim_checks(change: dict[str, object], message: str) -> None:
    token = make_jwt({**good_claims("n1"), **change})
    with pytest.raises(AIError, match=message):
        check_id_token(token, audience=ISSUED_CLIENT_ID, nonce="n1", now=NOW)


def test_id_token_accepts_an_audience_list_that_contains_ours() -> None:
    token = make_jwt({**good_claims("n1"), "aud": ["x", ISSUED_CLIENT_ID], "azp": ISSUED_CLIENT_ID})
    assert check_id_token(token, audience=ISSUED_CLIENT_ID, nonce="n1", now=NOW)["sub"] == "user-1"


@pytest.mark.parametrize("junk", ["", "a.b", "a.!!!.c", "a.bm90LWpzb24.c"])
def test_unreadable_id_tokens_are_refused(junk: str) -> None:
    with pytest.raises(AIError, match="could not be read"):
        check_id_token(junk, audience="a", nonce="n", now=NOW)


# ---- refresh, sign-out ------------------------------------------------------------------


def test_access_token_is_reused_until_it_nearly_expires() -> None:
    fx = Fixture()
    fx.manager.sign_in()
    fx.manager.access_token()
    assert len(fx.auth.forms) == 1  # still the sign-in exchange only
    fx.now += 3600 - 30  # inside the 60 second early-refresh margin
    fx.manager.access_token()
    refresh = fx.auth.forms[1]
    assert refresh["grant_type"] == "refresh_token"
    assert refresh["client_id"] == ISSUED_CLIENT_ID
    assert refresh["refresh_token"] == f"{SECRET_REFRESH}-1"
    assert refresh["resource"] == "https://api.openai.com/v1"
    assert "scope" not in refresh  # omitting scope keeps the grant
    # Refresh tokens rotate: the new one replaced the old.
    assert fx.keychain.get(signin.KEY_REFRESH_TOKEN) == f"{SECRET_REFRESH}-2"


def test_refresh_with_a_finished_token_signs_the_player_out() -> None:
    fx = Fixture()
    fx.manager.sign_in()
    fx.auth.token_status = 400
    fx.auth.error_code = "refresh_token_reused"
    with pytest.raises(NotSignedIn):
        fx.manager.refresh()
    assert not fx.manager.is_signed_in


def test_refresh_keeps_the_sign_in_when_openai_is_only_down() -> None:
    fx = Fixture()
    fx.manager.sign_in()
    fx.auth.token_status = 503
    fx.auth.error_code = ""
    with pytest.raises(AIError) as caught:
        fx.manager.refresh()
    assert not isinstance(caught.value, NotSignedIn)
    assert fx.manager.is_signed_in


def test_access_token_without_sign_in_raises_not_signed_in() -> None:
    with pytest.raises(NotSignedIn):
        Fixture().manager.access_token()


def test_network_failure_is_a_plain_sentence() -> None:
    def broken(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("boom", request=request)

    fx = Fixture()
    fx.keychain.set(signin.KEY_REFRESH_TOKEN, "r")
    fx.keychain.set(signin.KEY_CLIENT_ID, ISSUED_CLIENT_ID)
    manager = ChatGPTSignIn(fx.keychain, transport=httpx2.MockTransport(broken))
    with pytest.raises(AIError, match="Check your internet"):
        manager.refresh()


def test_sign_out_revokes_then_forgets() -> None:
    fx = Fixture()
    fx.manager.sign_in()
    assert fx.manager.sign_out() is True
    assert fx.auth.revoke_forms == [
        {
            "token": f"{SECRET_REFRESH}-1",
            "token_type_hint": "refresh_token",
            "client_id": ISSUED_CLIENT_ID,
        }
    ]
    assert not fx.manager.is_signed_in
    assert fx.keychain.get(signin.KEY_CLIENT_ID) == ISSUED_CLIENT_ID  # registration is kept
    with pytest.raises(NotSignedIn):
        fx.manager.access_token()


def test_sign_out_retries_then_reports_when_revoking_is_unconfirmed() -> None:
    fx = Fixture()
    fx.manager.sign_in()
    fx.auth.revoke_statuses = [503]
    assert fx.manager.sign_out() is False
    assert fx.auth.revoke_calls == signin.REVOKE_ATTEMPTS
    assert len(fx.sleeps) == signin.REVOKE_ATTEMPTS - 1
    assert not fx.manager.is_signed_in  # forgotten here even so
    assert "disconnect wow-coach" in signin.REVOKE_NOT_CONFIRMED


def test_sign_out_succeeds_after_a_retry() -> None:
    fx = Fixture()
    fx.manager.sign_in()
    fx.auth.revoke_statuses = [500, 200]
    assert fx.manager.sign_out() is True


def test_sign_out_when_never_signed_in_is_fine() -> None:
    assert Fixture().manager.sign_out() is True


# ---- keychain and logs --------------------------------------------------------------------


def test_without_a_keychain_the_sign_in_works_for_this_run_only(tmp_path: Path) -> None:
    # The autouse fixture installed a failing keychain, like a bare Linux setup.
    fx = Fixture()
    fx.manager.sign_in()
    assert not fx.keychain.persistent
    assert fx.manager.access_token() == SECRET_ACCESS
    assert fx.manager.is_signed_in
    assert Keychain().get(signin.KEY_REFRESH_TOKEN) is None  # a new run forgets it
    assert list(tmp_path.iterdir()) == []


def test_no_token_ever_appears_in_logs_or_output(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level(logging.DEBUG)
    fx = Fixture()
    fx.manager.sign_in()
    fx.now += 4000
    fx.manager.access_token()
    fx.auth.token_status = 400
    fx.auth.error_code = "invalid_grant"
    with pytest.raises(NotSignedIn):
        fx.manager.refresh()
    fx.manager.sign_out()
    captured = capsys.readouterr()
    seen = caplog.text + captured.out + captured.err
    # Look for the token VALUES themselves, in every line. (The one-time code is left out: the
    # fake browser's own HTTP client logs its visit, which is test machinery, not wow-coach.)
    for secret in (SECRET_ACCESS, SECRET_REFRESH):
        assert secret not in seen
