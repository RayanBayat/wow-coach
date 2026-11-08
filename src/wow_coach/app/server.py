"""The coach window's web server (standard library only).

It listens on 127.0.0.1 only, so nothing outside this computer can reach it. Because other
web pages open in the same browser could still try to talk to it, every request is checked:

* **Host header** must be exactly ``127.0.0.1:<port>`` (stops "DNS rebinding").
* **Session cookie** (``HttpOnly``, ``SameSite=Strict``) is needed for every ``/api/`` call.
  The page gets it by trading a one-time token, which is only in the start link's ``#`` part
  (a browser never sends that part to any server).
* **``X-Wow-Coach: 1`` header** is needed on every request that changes something, and an
  ``Origin`` header, when present, must be this server (stops cross-site form posts).
* **Strict Content-Security-Policy** and friends on every response, no CORS at all.

Errors that the player can see are always one plain sentence, never a traceback.
"""

import hmac
import http.server
import importlib.resources
import json
import queue
import secrets
import threading
from http.cookies import CookieError, SimpleCookie
from typing import Final, cast
from urllib.parse import parse_qs, urlsplit

from wow_coach.advice.contract import MAX_CHARACTER_KEY_CHARS, MAX_QUESTION_CHARS
from wow_coach.advice.limits import clean_text
from wow_coach.ai.base import AIError
from wow_coach.app.core import BUSY_MESSAGE, AppCore
from wow_coach.app.events import Mailbox
from wow_coach.app.views import settings_to_json

COOKIE_NAME: Final = "wow_coach_session"
CSRF_HEADER: Final = "X-Wow-Coach"
MAX_BODY_BYTES: Final = 16_000
HEARTBEAT_SECONDS: Final = 15.0

# The only files the page may load. A fixed list means "../" tricks have nothing to reach.
STATIC_FILES: Final = {
    "index.html": "text/html; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
}

# No inline scripts or styles, nothing from other sites, no framing.
CONTENT_SECURITY_POLICY: Final = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)
SECURITY_HEADERS: Final = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
}

type Json = dict[str, object]


class _BadRequest(Exception):  # noqa: N818  (reads better than BadRequestError)
    """The request is wrong; the message is a plain sentence for the player."""


class CoachServer(http.server.ThreadingHTTPServer):
    """The HTTP server plus the few facts every request handler needs."""

    daemon_threads = True  # a page holding an events connection must not block shutdown

    def __init__(
        self, core: AppCore, port: int = 0, *, heartbeat_seconds: float = HEARTBEAT_SECONDS
    ) -> None:
        # "127.0.0.1" and not "localhost" or "": nothing but this computer can connect.
        super().__init__(("127.0.0.1", port), _Handler)
        self.core = core
        self.heartbeat_seconds = heartbeat_seconds
        self.host_header = f"127.0.0.1:{self.server_address[1]}"
        self._token: str | None = secrets.token_urlsafe(32)
        self._sessions: set[str] = set()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        """The port the server really listens on."""
        return int(self.server_address[1])

    def start_url(self) -> str:
        """The link to open in the browser. The token is only in the ``#`` part."""
        if self._token is None:
            raise RuntimeError("The start link was already used.")
        return f"http://{self.host_header}/#{self._token}"

    def start(self) -> None:
        """Serve in a background thread."""
        self._thread = threading.Thread(target=self.serve_forever, name="coach-http", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop serving and close every live connection."""
        self.core.bus.close()
        if self._thread is not None:
            self.shutdown()
            self._thread.join(timeout=5)
        self.server_close()

    def trade_token_for_session(self, token: str) -> str | None:
        """Give a new session id for the one-time token; None if it is wrong or used."""
        with self._lock:
            expected = self._token
            if expected is None or not hmac.compare_digest(token, expected):
                return None
            self._token = None  # one use only
            session = secrets.token_urlsafe(32)
            self._sessions.add(session)
            return session

    def is_session(self, value: str | None) -> bool:
        """True when ``value`` is a session id we handed out."""
        if value is None:
            return False
        with self._lock:
            return any(hmac.compare_digest(value, known) for known in self._sessions)


class _Handler(http.server.BaseHTTPRequestHandler):
    """Handles one request. The ``do_`` names are fixed by ``http.server``."""

    server_version = "wow-coach"
    sys_version = ""  # do not announce the Python version

    @property
    def app(self) -> CoachServer:
        """The server that owns this connection."""
        return cast(CoachServer, self.server)

    # ---- plumbing ---------------------------------------------------------------------

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Stay quiet: the terminal is for the player, not for request logs."""

    def end_headers(self) -> None:
        """Add the security headers to EVERY response, errors included."""
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        super().end_headers()

    def _send(self, status: int, body: bytes, content_type: str, cookie: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, data: object, cookie: str | None = None) -> None:
        body = json.dumps(data).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", cookie)

    def _fail(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    # ---- the checks every request goes through ----------------------------------------

    def _host_ok(self) -> bool:
        return self.headers.get("Host") == self.app.host_header

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin == f"http://{self.app.host_header}"

    def _has_session(self) -> bool:
        raw = self.headers.get("Cookie", "")
        try:
            cookies: SimpleCookie = SimpleCookie(raw)
        except CookieError:
            return False
        morsel = cookies.get(COOKIE_NAME)
        return self.app.is_session(None if morsel is None else morsel.value)

    def _read_body(self) -> Json | None:
        """The JSON object in the request body, or None after sending the error."""
        if self.headers.get("Transfer-Encoding") is not None:
            self._fail(400, "This request could not be read.")
            return None
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._fail(411, "This request could not be read.")
            return None
        if length < 0 or length > MAX_BODY_BYTES:
            self._fail(413, "That request is too large.")
            return None
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw)
        except ValueError, RecursionError:
            data = None
        if not isinstance(data, dict):
            self._fail(400, "This request could not be read.")
            return None
        return cast(Json, data)

    # ---- routing ----------------------------------------------------------------------

    def do_GET(self) -> None:
        """Pages, files and read-only API calls."""
        if not self._host_ok():
            return self._fail(403, "This address is not allowed.")
        url = urlsplit(self.path)
        if not url.path.startswith("/api/"):
            return self._serve_static(url.path)
        if not self._has_session():
            return self._fail(401, "Open the window again with `wow-coach app`.")
        routes = {
            "/api/state": lambda: self._get_state(url.query),
            "/api/models": self._get_models,
            "/api/events": self._get_events,
        }
        route = routes.get(url.path)
        if route is None:
            return self._fail(404, "There is nothing at this address.")
        route()
        return None

    def do_POST(self) -> None:
        """Everything that changes something."""
        if not self._host_ok() or not self._origin_ok():
            return self._fail(403, "This address is not allowed.")
        path = urlsplit(self.path).path
        if self.headers.get(CSRF_HEADER) != "1":
            return self._fail(403, "This request was not made by the coach window.")
        if path != "/api/session" and not self._has_session():
            return self._fail(401, "Open the window again with `wow-coach app`.")
        routes = {
            "/api/session": self._post_session,
            "/api/ask": self._post_ask,
            "/api/answer-open": self._post_answer_open,
            "/api/settings": self._post_settings,
            "/api/signin": self._post_signin,
            "/api/signout": self._post_signout,
            "/api/welcome-seen": self._post_welcome_seen,
        }
        route = routes.get(path)
        if route is None:
            return self._fail(404, "There is nothing at this address.")
        body = self._read_body()
        if body is None:
            return None
        try:
            route(body)
        except _BadRequest as problem:
            self._fail(400, str(problem))
        return None

    def _not_allowed(self) -> None:
        self._fail(405, "This kind of request is not used here.")

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _not_allowed  # noqa: N815

    # ---- static files -----------------------------------------------------------------

    def _serve_static(self, path: str) -> None:
        name = "index.html" if path == "/" else path.removeprefix("/")
        content_type = STATIC_FILES.get(name)  # anything not on the list is refused
        if content_type is None:
            return self._fail(404, "There is nothing at this address.")
        resource = importlib.resources.files("wow_coach.app") / "static" / name
        self._send(200, resource.read_bytes(), content_type)
        return None

    # ---- GET /api/... -----------------------------------------------------------------

    def _get_state(self, query: str) -> None:
        wanted = parse_qs(query).get("character", [None])[0]
        self._json(200, self.app.core.state(wanted))

    def _get_models(self) -> None:
        try:
            self._json(200, {"models": self.app.core.models()})
        except AIError as error:
            self._fail(502, str(error))

    def _get_events(self) -> None:
        """Server-Sent Events: a stream of ``event:``/``data:`` messages that never ends."""
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.end_headers()
        bus = self.app.core.bus
        mailbox = bus.subscribe()
        try:
            self.wfile.write(b": connected\n\n")
            while self._send_next_event(mailbox):
                pass
        except OSError:
            pass  # the page closed the connection
        finally:
            bus.unsubscribe(mailbox)

    def _send_next_event(self, mailbox: Mailbox) -> bool:
        """Send one event (or a heartbeat). False when the program is shutting down."""
        try:
            event = mailbox.get(timeout=self.app.heartbeat_seconds)
        except queue.Empty:
            self.wfile.write(b": heartbeat\n\n")  # keeps the connection from timing out
            return True
        if event is None:
            return False
        text = f"event: {event.kind}\ndata: {json.dumps(event.data)}\n\n"
        self.wfile.write(text.encode("utf-8"))
        return True

    # ---- POST /api/... ----------------------------------------------------------------

    def _post_session(self, body: Json) -> None:
        token = body.get("token")
        session = self.app.trade_token_for_session(token) if isinstance(token, str) else None
        if session is None:
            return self._fail(403, "This start link was already used. Run `wow-coach app` again.")
        cookie = f"{COOKIE_NAME}={session}; HttpOnly; SameSite=Strict; Path=/"
        return self._json(200, {"ok": True}, cookie)

    def _post_ask(self, body: Json) -> None:
        question = body.get("question")
        if not isinstance(question, str) or not question.strip():
            raise _BadRequest("Type a question first.")
        if len(question) > MAX_QUESTION_CHARS:
            raise _BadRequest(
                f"That question is too long. Please keep it under {MAX_QUESTION_CHARS} letters."
            )
        clean = clean_text(question.strip(), MAX_QUESTION_CHARS)
        if not self.app.core.start_ask(clean, _character_from(body)):
            return self._fail(409, BUSY_MESSAGE)
        return self._json(202, {"started": True})

    def _post_answer_open(self, body: Json) -> None:
        outcome = self.app.core.start_answer_open(_character_from(body))
        if outcome == "busy":
            return self._fail(409, BUSY_MESSAGE)
        if outcome == "none":
            return self._json(200, {"started": False, "message": "No questions are waiting."})
        return self._json(202, {"started": True})

    def _post_settings(self, body: Json) -> None:
        changes = body.get("changes")
        if not isinstance(changes, dict):
            raise _BadRequest("This request could not be read.")
        try:
            new = self.app.core.change_settings(cast(Json, changes))
        except OSError:
            return self._fail(500, "Your settings could not be saved. Is the disk full?")
        return self._json(200, {"settings": settings_to_json(new)})

    def _post_signin(self, body: Json) -> None:
        del body  # nothing to read: the button alone starts the sign-in
        if not self.app.core.start_sign_in():
            return self._fail(409, "A sign-in is already open in your browser.")
        return self._json(202, {"started": True})

    def _post_welcome_seen(self, body: Json) -> None:
        del body
        try:
            self.app.core.dismiss_welcome()
        except OSError:
            return self._fail(500, "wow-coach could not remember that. It may show again.")
        return self._json(200, {"ok": True})

    def _post_signout(self, body: Json) -> None:
        del body
        confirmed = self.app.core.sign_out()
        return self._json(200, {"signed_out": True, "revoke_confirmed": confirmed})


def _character_from(body: Json) -> str | None:
    """The optional "character" field: a "Name-Realm" (or bare name), else None."""
    value = body.get("character")
    if value is None:
        return None
    if not (
        isinstance(value, str)
        and 0 < len(value) <= MAX_CHARACTER_KEY_CHARS
        and value.isprintable()
        and "|" not in value
    ):
        raise _BadRequest("That character name is not valid.")
    return value
