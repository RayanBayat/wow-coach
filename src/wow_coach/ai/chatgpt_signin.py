"""Sign in with ChatGPT: lets the player use their own ChatGPT plan for wow-coach's questions.

This follows OpenAI's public documentation for open-source apps (read 2026-11-08, see
``docs/plans/chatgpt-signin-notes.md`` for every URL and rule) and the standards behind it:
OAuth 2.0 (RFC 6749), PKCE (RFC 7636), token revocation (RFC 7009) and OpenID Connect Core.
No code was copied from OpenAI's DevKit (its license does not fit this MIT repository).

The steps of a sign-in, in plain words:

1. We start a tiny web server that only listens on this computer (127.0.0.1) and open the
   player's browser on OpenAI's sign-in page.
2. The player signs in and agrees. OpenAI sends the browser back to our tiny server with a
   one-time ``code``. The browser address also carries ``state``, a random value we made up, so
   we know the answer belongs to *our* request.
3. We trade the code (plus the secret PKCE ``verifier`` only we know) for tokens.
4. The short-lived access token stays in memory. The long-lived refresh token and the client
   id OpenAI issued go to the system keychain (``keychain.py``). Nothing is ever logged.
"""

import base64
import contextlib
import hashlib
import html
import http.server
import json
import logging
import math
import os
import secrets
import socket
import socketserver
import sys
import threading
import time
import uuid
import webbrowser
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx2

from wow_coach.ai.base import AIError, NotSignedIn
from wow_coach.keychain import Keychain
from wow_coach.web import build_user_agent

_log = logging.getLogger(__name__)

# Fixed addresses, copied from OpenAI's discovery document (a test pins them).
ISSUER = "https://auth.openai.com"
AUTHORIZE_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"  # noqa: S105  (an address)
REVOKE_URL = "https://auth.openai.com/api/accounts/oauth/revoke"
RESOURCE = "https://api.openai.com/v1"

PLAN_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = f"openid profile email offline_access resource.invoke {PLAN_SCOPE}"

# The first registration is documented with port 1455. Later sign-ins may use another port,
# but the scheme, host and path of the redirect address must stay exactly the same.
DEFAULT_PORT = 1455
CALLBACK_PATH = "/auth/callback"
REGISTRATION_CLIENT_ID = "dynamic_agent_client"
APP_NAME_HINT = "wow-coach"

KEY_REFRESH_TOKEN = "chatgpt-refresh-token"  # noqa: S105  (a key NAME, not a secret)
KEY_CLIENT_ID = "chatgpt-client-id"
KEY_HOST_ID = "chatgpt-host-id"
KEY_ACCOUNT = "chatgpt-account"  # the ID token's ``sub``: an id, not a secret

# Refresh a little early so a token never expires in the middle of a request.
EARLY_REFRESH_SECONDS = 60
SIGN_IN_TIMEOUT_SECONDS = 300.0
REQUEST_TIMEOUT_SECONDS = 15.0
REVOKE_ATTEMPTS = 3
DEFAULT_EXPIRES_IN_SECONDS = 3600.0  # the documented access-token lifetime
LOCK_STALE_SECONDS = 30.0
LOCK_WAIT_SECONDS = 10.0
IDLE_CONNECTION_SECONDS = 5.0

# Error codes from the token endpoint that mean "this refresh token is finished, sign in again".
_SIGN_IN_AGAIN_CODES = frozenset(
    {
        "invalid_grant",
        "invalid_refresh_token",
        "token_expired",
        "refresh_token_expired",
        "refresh_token_invalidated",
        "refresh_token_reused",
    }
)

REVOKE_NOT_CONFIRMED = (
    "You are signed out of wow-coach, but OpenAI did not confirm it. "
    "To be sure, disconnect wow-coach in your ChatGPT settings."
)

_PAGE = (
    "<!doctype html><meta charset=utf-8><title>wow-coach</title>"
    "<body style='font-family:sans-serif;max-width:30em;margin:3em auto'>"
    "<h1>{title}</h1><p>{text}</p></body>"
)


class PlanUseNotEnabled(AIError):  # noqa: N818
    """The player signed in but did not allow wow-coach to use their ChatGPT plan."""


@dataclass(frozen=True, slots=True)
class Account:
    """Who signed in (from the verified ID token)."""

    subject: str
    email: str | None


@dataclass(frozen=True, slots=True)
class Pkce:
    """The PKCE pair: a secret ``verifier`` we keep, and its hash ``challenge`` we send."""

    verifier: str = field(repr=False)  # a secret: never shown in logs or tracebacks
    challenge: str


def new_pkce() -> Pkce:
    """Make a fresh PKCE pair (RFC 7636, method S256)."""
    verifier = secrets.token_urlsafe(64)  # 86 characters; the RFC allows 43 to 128
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return Pkce(verifier=verifier, challenge=_base64url(digest))


def new_random_value() -> str:
    """A fresh unguessable value, used for ``state`` and ``nonce``."""
    return secrets.token_urlsafe(32)


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def check_id_token(
    id_token: str, *, audience: str, nonce: str, now: float, issuer: str = ISSUER
) -> dict[str, Any]:
    """Check the claims of an ID token and return them.

    We do NOT check the signature. OpenID Connect Core 1.0, section 3.1.3.7, step 6 allows this
    when the token came straight from the token endpoint over TLS: the TLS certificate check
    already proves who sent it. So we only check what the token says: the issuer (``iss``),
    who it is for (``aud``), that it has not expired (``exp``) and that it answers *our*
    request (``nonce``).

    Raises:
        AIError: With a plain sentence when the token is unreadable or a claim is wrong.
    """
    claims = _decode_payload(id_token)
    if claims.get("iss") != issuer:
        raise AIError("OpenAI's sign-in answer came from an unexpected source, so it was refused.")
    if not _is_for(claims, audience):
        raise AIError("OpenAI's sign-in answer was meant for another app, so it was refused.")
    if not _is_finite_number(claims.get("exp")) or claims["exp"] <= now:
        raise AIError("OpenAI's sign-in answer had already expired. Please sign in again.")
    if "iat" in claims and not _is_finite_number(claims["iat"]):
        raise AIError("OpenAI's sign-in answer could not be read.")
    if claims.get("nonce") != nonce:
        raise AIError("OpenAI's sign-in answer did not match this sign-in attempt.")
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise AIError("OpenAI's sign-in answer did not say who signed in, so it was refused.")
    return claims


def _is_finite_number(value: object) -> bool:
    """True for a real, finite number (not ``True``, ``NaN`` or infinity)."""
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _is_for(claims: Mapping[str, Any], audience: str) -> bool:
    """True if the token is meant for us. With several audiences, ``azp`` must be us too."""
    audiences = claims.get("aud")
    if isinstance(audiences, str):
        return audiences == audience
    if isinstance(audiences, list):
        return audience in audiences and claims.get("azp") == audience
    return False


def _decode_payload(token: str) -> dict[str, Any]:
    """Read the middle part of a JWT (``header.payload.signature``) as JSON."""
    unreadable = AIError("OpenAI's sign-in answer could not be read.")
    parts = token.split(".")
    if len(parts) != 3:
        raise unreadable
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, RecursionError) as error:  # RecursionError: absurdly nested JSON
        raise unreadable from error
    if not isinstance(payload, dict):
        raise unreadable
    return cast(dict[str, Any], payload)


# ----------------------------------------------------------------------------------------
# The one-shot loopback server that catches the browser's return trip.
# ----------------------------------------------------------------------------------------


class _OneShotServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """A web server that remembers the one valid answer it received.

    Each visitor gets its own thread, so one idle connection can never stall the sign-in
    (and the overall deadline in ``LoopbackServer.wait`` really holds).
    """

    daemon_threads = True
    block_on_close = False  # don't wait for idle visitors when closing
    # POSIX: lets us rebind soon after a sign-in (it does NOT let two programs listen on one
    # port). Windows: the opposite default is dangerous, so we claim the port exclusively below.
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, port: int, expected_state: str) -> None:
        self.expected_state = expected_state
        self.result: dict[str, str] | None = None
        # 127.0.0.1 only: nobody else on the network can reach this server.
        super().__init__(("127.0.0.1", port), _CallbackHandler)

    def server_bind(self) -> None:
        if sys.platform == "win32":
            # Without this, another program could bind the same port and steal the code.
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request: object, client_address: object) -> None:
        """Stay quiet: the default prints a traceback (which can show request details)."""


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Accepts only ``GET /auth/callback?...state=<ours>``; refuses everything else."""

    timeout = IDLE_CONNECTION_SECONDS  # a connection that says nothing is dropped

    def do_GET(self) -> None:  # the name is fixed by http.server
        server = cast(_OneShotServer, self.server)
        if self.headers.get("Host") != f"127.0.0.1:{server.server_address[1]}":
            # A web page could point a lookalike name at 127.0.0.1; only our exact address counts.
            self._reply(400, "Refused", "This address is not used by wow-coach.")
            return
        address = urlsplit(self.path)
        if address.path != CALLBACK_PATH:
            self._reply(404, "Not found", "This address is not used by wow-coach.")
            return
        params = {key: values[0] for key, values in parse_qs(address.query).items()}
        # compare_digest on bytes: a constant-time comparison that also accepts any text
        if not secrets.compare_digest(
            params.get("state", "").encode(), server.expected_state.encode()
        ):
            self._reply(400, "Refused", "This sign-in answer does not belong to wow-coach.")
            return
        server.result = params
        self._reply(200, "You can close this tab", "Go back to wow-coach to continue.")

    # There is no do_POST, do_PUT and so on on purpose: http.server answers every method
    # without a do_<METHOD> handler with "501 Unsupported method", which refuses it.

    def _reply(self, status: int, title: str, text: str) -> None:
        body = _PAGE.format(title=html.escape(title), text=html.escape(text)).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Stay silent: the request line holds the one-time code."""


class LoopbackServer:
    """Waits for the browser's return trip. Use it once, then ``close()``."""

    def __init__(self, port: int, expected_state: str) -> None:
        """Start listening on 127.0.0.1 (port 0 picks a free port, for tests)."""
        try:
            self._server = _OneShotServer(port, expected_state)
        except OSError as error:
            raise AIError(
                f"Port {port} on this computer is busy, so sign-in cannot start. "
                "Close the program using it and try again."
            ) from error
        self._server.timeout = 0.2  # how long one handle_request() waits for a visitor

    @property
    def port(self) -> int:
        """The port we really listen on."""
        return int(self._server.server_address[1])

    def wait(self, timeout_seconds: float) -> dict[str, str] | None:
        """Return the callback's query parameters, or ``None`` if time ran out."""
        deadline = time.monotonic() + timeout_seconds
        while self._server.result is None and time.monotonic() < deadline:
            self._server.handle_request()  # returns after at most 0.2 s, see __init__
        return self._server.result

    def close(self) -> None:
        """Stop listening."""
        self._server.server_close()


# ----------------------------------------------------------------------------------------
# The sign-in manager.
# ----------------------------------------------------------------------------------------


class RefreshFileLock:
    """A tiny lock file so two wow-coach programs don't refresh the sign-in at the same time.

    Refresh tokens rotate: if two programs both use the old one, OpenAI may treat the second as
    stolen and end the sign-in. The file holds nothing secret (it is empty), counts as stale
    after about 30 seconds (a crashed program must not block us forever) and is always removed.
    """

    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        wait_seconds: float = LOCK_WAIT_SECONDS,
        stale_seconds: float = LOCK_STALE_SECONDS,
    ) -> None:
        self._path = path
        self._clock = clock
        self._sleep = sleep
        self._wait = wait_seconds
        self._stale = stale_seconds

    @contextlib.contextmanager
    def held(self) -> Iterator[None]:
        """Hold the lock inside a ``with`` block. Raises ``AIError`` if it stays taken."""
        self._acquire()
        try:
            yield
        finally:
            self._path.unlink(missing_ok=True)

    def _acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        give_up_at = self._clock() + self._wait
        while True:
            try:
                # O_EXCL: creating the file fails if it exists, so only one program wins.
                os.close(os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
                return
            except FileExistsError:
                if self._is_stale():
                    self._path.unlink(missing_ok=True)
                    continue
                if self._clock() >= give_up_at:
                    raise AIError(
                        "Another wow-coach window is renewing the sign-in. Please try again."
                    ) from None
                self._sleep(0.1)

    def _is_stale(self) -> bool:
        try:
            return self._clock() - self._path.stat().st_mtime > self._stale
        except FileNotFoundError:
            return False  # it just disappeared: the next try will take it


class _TokenEndpointRejected(AIError):  # noqa: N818
    """OpenAI's token service answered with an error. ``code`` is its machine-readable name."""

    def __init__(self, message: str, *, code: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class ChatGPTSignIn:
    """Signs in, keeps the tokens fresh and signs out."""

    def __init__(
        self,
        keychain: Keychain,
        *,
        transport: httpx2.BaseTransport | None = None,
        port: int = DEFAULT_PORT,
        open_browser: Callable[[str], object] = webbrowser.open,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        timeout_seconds: float = SIGN_IN_TIMEOUT_SECONDS,
        lock_path: Path | None = None,
    ) -> None:
        """Create the manager.

        Args:
            keychain: Where the refresh token and client id are kept.
            transport: Replaces the real network (tests only).
            port: The loopback port for the sign-in return trip (0 = any free one, tests only).
            open_browser: Opens a web address in the player's browser.
            clock: Seconds since 1970 (replaced in tests).
            sleep: Waits some seconds (replaced in tests).
            timeout_seconds: How long to wait for the player to finish in the browser.
            lock_path: A lock file (put it in the data folder) that stops two wow-coach
                programs from refreshing at once. ``None`` means no cross-program lock.
        """
        self._keychain = keychain
        self._port = port
        self._open_browser = open_browser
        self._clock = clock
        self._sleep = sleep
        self._timeout = timeout_seconds
        self._client = httpx2.Client(
            transport=transport,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": build_user_agent()},
        )
        self._access_token: str | None = None
        self._expires_at = 0.0
        self._lock = threading.Lock()  # one sign-in, refresh or sign-out at a time
        self._file_lock = (
            RefreshFileLock(lock_path, clock=clock, sleep=sleep) if lock_path else None
        )

    @property
    def is_signed_in(self) -> bool:
        """True if a refresh token is saved (the player can ask without signing in again)."""
        return self._keychain.get(KEY_REFRESH_TOKEN) is not None

    def sign_in(self, on_url: Callable[[str], None] | None = None) -> Account:
        """Run the whole browser sign-in and return who signed in.

        Args:
            on_url: Called with the sign-in address, so a terminal can print it in case the
                browser does not open by itself.

        Raises:
            PlanUseNotEnabled: The player did not allow using their ChatGPT plan.
            AIError: Anything else that went wrong, in a plain sentence.
        """
        with self._lock:
            return self._sign_in_locked(on_url)

    def _sign_in_locked(self, on_url: Callable[[str], None] | None) -> Account:
        saved_client_id = self._keychain.get(KEY_CLIENT_ID)
        old_refresh_token = self._keychain.get(KEY_REFRESH_TOKEN)
        state, nonce, pkce = new_random_value(), new_random_value(), new_pkce()
        server = LoopbackServer(self._port, state)  # listen BEFORE the browser opens
        try:
            redirect_uri = f"http://127.0.0.1:{server.port}{CALLBACK_PATH}"
            url = self._authorize_url(saved_client_id, redirect_uri, state, nonce, pkce)
            if on_url is not None:
                on_url(url)
            self._open_browser(url)
            params = server.wait(self._timeout)
        finally:
            server.close()
        if params is None:
            raise AIError("Sign-in took too long and was cancelled. Please try again.")
        client_id = self._client_id_from_callback(params, saved_client_id)
        tokens = self._post_token_form(
            {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": self._code_from_callback(params),
                "code_verifier": pkce.verifier,
                "redirect_uri": redirect_uri,
                "resource": RESOURCE,
            }
        )
        try:
            account = self._accept_tokens(tokens, client_id, nonce)
        except AIError:
            # We got tokens but refuse them: don't leave a live sign-in behind at OpenAI.
            self._revoke_unwanted(tokens, client_id)
            raise
        if saved_client_id and old_refresh_token and old_refresh_token != self._new_refresh(tokens):
            self._revoke(old_refresh_token, saved_client_id)  # the new sign-in replaces it
        return account

    @staticmethod
    def _new_refresh(tokens: Mapping[str, Any]) -> str | None:
        value = tokens.get("refresh_token")
        return value if isinstance(value, str) and value else None

    def _revoke_unwanted(self, tokens: Mapping[str, Any], client_id: str) -> None:
        refresh_token = self._new_refresh(tokens)
        if refresh_token is not None:
            self._revoke(refresh_token, client_id)

    def access_token(self) -> str:
        """Return a valid access token, refreshing it first if it is (nearly) expired.

        Raises:
            NotSignedIn: Nobody is signed in, or the sign-in ended.
        """
        with self._lock:
            if self._access_token and self._clock() < self._expires_at - EARLY_REFRESH_SECONDS:
                return self._access_token
            return self._refresh_locked()

    def refresh(self) -> str:
        """Get a new access token now (used after a 401). Raises ``NotSignedIn`` if it fails."""
        with self._lock:
            return self._refresh_locked()

    def sign_out(self) -> bool:
        """Revoke the refresh token at OpenAI and forget all tokens here.

        Returns:
            True if OpenAI confirmed the revoking; False if we could not reach it (tell the
            player with ``REVOKE_NOT_CONFIRMED``). The tokens are forgotten either way.
        """
        with self._lock:
            confirmed = True
            refresh_token = self._keychain.get(KEY_REFRESH_TOKEN)
            client_id = self._keychain.get(KEY_CLIENT_ID)
            if refresh_token is not None and client_id is not None:
                confirmed = self._revoke(refresh_token, client_id)
            # Keep the client id and host id: OpenAI remembers the registration, and so should
            # we. The account id goes, so the player may sign in with another account next.
            self._keychain.delete(KEY_REFRESH_TOKEN)
            self._keychain.delete(KEY_ACCOUNT)
            self._access_token = None
            self._expires_at = 0.0
            return confirmed

    def forget_registration(self) -> None:
        """Throw away the saved client id and sign-in, without contacting OpenAI.

        Use this when OpenAI no longer knows the saved client id (for example sign-in keeps
        failing with an "invalid client" message), or to switch to another ChatGPT account.
        The next ``sign_in`` registers wow-coach again. The host id is kept.
        """
        with self._lock:
            for key in (KEY_REFRESH_TOKEN, KEY_CLIENT_ID, KEY_ACCOUNT):
                self._keychain.delete(key)
            self._access_token = None
            self._expires_at = 0.0

    # -- building the sign-in address ----------------------------------------------------

    def _authorize_url(
        self, saved_client_id: str | None, redirect_uri: str, state: str, nonce: str, pkce: Pkce
    ) -> str:
        query = {
            "response_type": "code",
            "client_id": saved_client_id or REGISTRATION_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "resource": RESOURCE,
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce.challenge,
            "code_challenge_method": "S256",
            "ext_agent_host_id": self._host_id(),
        }
        if saved_client_id is None:
            query["agent_name_hint"] = APP_NAME_HINT  # only on the first registration
        return f"{AUTHORIZE_URL}?{urlencode(query)}"

    def _host_id(self) -> str:
        """A random id for this install; OpenAI wants it stable and not tied to the player."""
        host_id = self._keychain.get(KEY_HOST_ID)
        if host_id is None:
            host_id = f"urn:uuid:{uuid.uuid4()}"
            self._keychain.set(KEY_HOST_ID, host_id)
        return host_id

    # -- reading the browser's return trip -------------------------------------------------

    def _client_id_from_callback(self, params: Mapping[str, str], saved: str | None) -> str:
        if params.get("error") == "access_denied":
            raise AIError("Sign-in was cancelled in the browser. Nothing was changed.")
        if "error" in params:
            raise AIError("OpenAI did not accept the sign-in. Please try again.")
        issued = params.get("client_id")
        if saved is None:
            if not issued or issued == REGISTRATION_CLIENT_ID:
                raise AIError("OpenAI did not finish registering wow-coach. Please try again.")
            # Save it before using the code, so a failed code does not force a new registration.
            self._keychain.set(KEY_CLIENT_ID, issued)
            return issued
        if issued is not None and issued != saved:
            raise AIError("OpenAI answered for a different app registration, so it was refused.")
        return saved

    @staticmethod
    def _code_from_callback(params: Mapping[str, str]) -> str:
        code = params.get("code")
        if not code:
            raise AIError("OpenAI's sign-in answer had no code. Please try again.")
        return code

    # -- tokens ----------------------------------------------------------------------------

    def _accept_tokens(self, tokens: Mapping[str, Any], client_id: str, nonce: str) -> Account:
        """Check a fresh token response and keep the tokens."""
        id_token = tokens.get("id_token")
        if not isinstance(id_token, str):
            raise AIError("OpenAI's sign-in answer had no ID token. Please try again.")
        claims = check_id_token(id_token, audience=client_id, nonce=nonce, now=self._clock())
        subject = str(claims["sub"])
        saved_subject = self._keychain.get(KEY_ACCOUNT)
        if saved_subject is not None and saved_subject != subject:
            raise AIError(
                "This is a different ChatGPT account than the one wow-coach was set up with. "
                "Sign out first, then sign in with the other account."
            )
        # A valid ID token only proves who the player is, not that they allowed plan use.
        if PLAN_SCOPE not in str(tokens.get("scope", "")).split():
            raise PlanUseNotEnabled(
                "You signed in, but did not allow wow-coach to use your ChatGPT plan. "
                "Sign in again and accept that permission."
            )
        refresh_token = self._new_refresh(tokens)
        if refresh_token is None:
            raise AIError("OpenAI did not give a renewable sign-in. Please try again.")
        self._keep_access_token(tokens)
        self._keychain.set(KEY_REFRESH_TOKEN, refresh_token)
        self._keychain.set(KEY_ACCOUNT, subject)
        email = claims.get("email")
        return Account(subject=subject, email=email if isinstance(email, str) and email else None)

    def _keep_access_token(self, tokens: Mapping[str, Any]) -> str:
        """Remember the access token (memory only) and return it."""
        access_token = tokens.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise AIError("OpenAI's sign-in answer was incomplete. Please try again.")
        self._expires_at = self._clock() + _expires_in(tokens.get("expires_in"))
        self._access_token = access_token
        return access_token

    def _refresh_locked(self) -> str:
        if self._file_lock is None:
            return self._refresh_once()
        with self._file_lock.held():
            return self._refresh_once()

    def _refresh_once(self) -> str:
        """Refresh the access token. Call this only while holding the locks."""
        refresh_token = self._keychain.get(KEY_REFRESH_TOKEN)
        client_id = self._keychain.get(KEY_CLIENT_ID)
        if refresh_token is None or client_id is None:
            raise NotSignedIn("You are not signed in to ChatGPT. Sign in first.")
        try:
            tokens = self._post_token_form(
                {
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "refresh_token": refresh_token,
                    "resource": RESOURCE,
                }
            )
        except _TokenEndpointRejected as error:
            if error.code not in _SIGN_IN_AGAIN_CODES:
                raise
            self._access_token = None
            # Only forget the token we sent. If another program has already saved a newer one,
            # that one may be fine: leave it alone.
            if self._keychain.get(KEY_REFRESH_TOKEN) == refresh_token:
                self._keychain.delete(KEY_REFRESH_TOKEN)
            raise NotSignedIn("Your ChatGPT sign-in has ended. Please sign in again.") from error
        # Refresh tokens rotate: the old one is dead now, so save the new one FIRST, before
        # anything below can fail and lose it.
        new_refresh_token = self._new_refresh(tokens)
        if new_refresh_token is not None:
            self._keychain.set(KEY_REFRESH_TOKEN, new_refresh_token)
        return self._keep_access_token(tokens)

    def _post_token_form(self, form: Mapping[str, str]) -> dict[str, Any]:
        """POST a form to the token endpoint and return the JSON answer."""
        try:
            response = self._client.post(TOKEN_URL, data=dict(form))
        except httpx2.TimeoutException as error:
            raise AIError("OpenAI's sign-in service took too long to answer.") from error
        except httpx2.HTTPError as error:
            raise AIError(
                "Could not reach OpenAI's sign-in service. Check your internet."
            ) from error
        body = _json_or_empty(response)
        if response.status_code != 200:
            code = str(body.get("error", "")) if isinstance(body.get("error"), str) else ""
            _log.warning(
                "OpenAI's token service refused a request (HTTP %s).", response.status_code
            )
            raise _TokenEndpointRejected(
                "OpenAI's sign-in service refused the request"
                f" (error {response.status_code}). Please try again later.",
                code=code,
                status=response.status_code,
            )
        return body

    def _revoke(self, refresh_token: str, client_id: str) -> bool:
        """Ask OpenAI to revoke the token. Retries a few times; returns True when confirmed."""
        form = {"token": refresh_token, "token_type_hint": "refresh_token", "client_id": client_id}
        for attempt in range(REVOKE_ATTEMPTS):
            try:
                if self._client.post(REVOKE_URL, data=form).status_code == 200:
                    return True
            except httpx2.HTTPError:
                pass  # network trouble: try again below
            if attempt < REVOKE_ATTEMPTS - 1:
                self._sleep(2.0**attempt)
        return False


def _json_or_empty(response: httpx2.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError, RecursionError:  # not JSON, or absurdly nested
        return {}
    return cast(dict[str, Any], body) if isinstance(body, dict) else {}


def _expires_in(value: object) -> float:
    """How many seconds the access token lives. Missing means the documented 3600."""
    if value is None:
        return DEFAULT_EXPIRES_IN_SECONDS
    try:
        seconds = float(value) if isinstance(value, str | int | float) else math.nan
    except ValueError:
        seconds = math.nan
    if isinstance(value, bool) or not math.isfinite(seconds) or seconds <= 0:
        raise AIError("OpenAI's sign-in answer was incomplete. Please try again.")
    return seconds
