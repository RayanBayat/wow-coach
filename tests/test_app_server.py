"""The coach window's web server: security checks, static files and the API."""

import http.client
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from test_app_support import (
    KEY,
    Client,
    Rig,
    make_answer,
    make_rig,
    wait_for_event,
    write_advice_file,
    write_save,
)

from wow_coach.advice.contract import MAX_QUESTION_CHARS
from wow_coach.ai.base import NotSignedIn, PlanLimitReached
from wow_coach.app.server import MAX_BODY_BYTES, STATIC_FILES, CoachServer


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


@pytest.fixture
def server(rig: Rig) -> Iterator[CoachServer]:
    running = CoachServer(rig.core, 0, heartbeat_seconds=0.2)
    running.start()
    yield running
    running.stop()


@pytest.fixture
def client(server: CoachServer) -> Client:
    page = Client(server)
    page.sign_in_page()
    return page


# ---- who may talk to the server ---------------------------------------------------------


def test_it_listens_on_loopback_only(server: CoachServer) -> None:
    assert server.server_address[0] == "127.0.0.1"
    assert server.start_url() == f"http://127.0.0.1:{server.port}/#" + server.start_url()[-43:]


def test_api_needs_a_session(server: CoachServer) -> None:
    page = Client(server)
    for path in ("/api/state", "/api/models", "/api/events"):
        assert page.request("GET", path)[0] == 401
    assert page.request("POST", "/api/ask", {"question": "hi"})[0] == 401


def test_a_made_up_cookie_is_refused(server: CoachServer) -> None:
    page = Client(server)
    page.cookie = "wow_coach_session=not-a-real-session"
    assert page.request("GET", "/api/state")[0] == 401


def test_the_token_works_only_once(server: CoachServer) -> None:
    token = server.start_url().split("#", 1)[1]
    page = Client(server)
    status, headers, _ = page.request("POST", "/api/session", {"token": token})
    assert status == 200
    cookie = headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Path=/" in cookie
    assert page.request("POST", "/api/session", {"token": token})[0] == 403
    assert page.request("POST", "/api/session", {"token": "wrong"})[0] == 403


def test_the_session_cookie_opens_the_api(client: Client) -> None:
    status, state = client.json("GET", "/api/state")
    assert status == 200
    assert state["selected"] == KEY


def test_a_wrong_host_header_is_refused(server: CoachServer, client: Client) -> None:
    for host in ("evil.example", "localhost", f"127.0.0.1:{server.port + 1}", "127.0.0.1"):
        assert client.request("GET", "/api/state", host=host)[0] == 403
        assert client.request("GET", "/", host=host)[0] == 403
    assert client.request("POST", "/api/settings", {"changes": {}}, host="evil.example")[0] == 403


def test_a_post_without_the_csrf_header_is_refused(client: Client) -> None:
    assert client.request("POST", "/api/settings", {"changes": {}}, csrf=False)[0] == 403


def test_a_post_from_another_site_is_refused(client: Client) -> None:
    headers = {"Origin": "http://evil.example"}
    assert client.request("POST", "/api/settings", {"changes": {}}, headers=headers)[0] == 403


def test_other_methods_are_refused(client: Client) -> None:
    assert client.request("PUT", "/api/settings")[0] == 405
    assert client.request("OPTIONS", "/api/state")[0] == 405


# ---- headers and static files --------------------------------------------------------------


def test_security_headers_are_on_every_response(client: Client) -> None:
    responses = [
        client.request("GET", "/"),
        client.request("GET", "/api/state"),
        client.request("GET", "/nope"),
        client.request("GET", "/api/state", with_cookie=False),
        client.request("GET", "/api/state", host="evil.example"),
    ]
    for _, headers, _ in responses:
        policy = headers["content-security-policy"]
        assert "default-src 'self'" in policy and "unsafe-inline" not in policy
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["referrer-policy"] == "no-referrer"
        assert headers["cache-control"] == "no-store"
        assert headers["x-frame-options"] == "DENY"
        assert "access-control-allow-origin" not in headers


@pytest.mark.parametrize("name", sorted(STATIC_FILES))
def test_static_files_are_served_with_their_type(client: Client, name: str) -> None:
    status, headers, body = client.request("GET", "/" + name)
    assert status == 200 and body
    assert headers["content-type"] == STATIC_FILES[name]


def test_the_start_page_is_the_root(client: Client) -> None:
    status, headers, body = client.request("GET", "/")
    assert status == 200
    assert headers["content-type"].startswith("text/html")
    assert b"Continue with ChatGPT" in body


@pytest.mark.parametrize(
    "path",
    [
        "/../server.py",
        "/..%2fserver.py",
        "/%2e%2e/server.py",
        "/static/../server.py",
        "/server.py",
        "/__init__.py",
        "/index.html/",
        "/app.js/../server.py",
        "/..\\server.py",
        "/index.html%00.js",
    ],
)
def test_path_tricks_are_refused(client: Client, path: str) -> None:
    status, _, body = client.request("GET", path)
    assert status == 404
    assert b"import" not in body


# ---- the API ------------------------------------------------------------------------------


def test_state_lists_answers_questions_usage_and_alerts(rig: Rig, client: Client) -> None:
    write_save(rig.wow_dir, ("1-1", "How do I fish?"))
    write_advice_file(rig.wow_dir, [make_answer("Old", 10), make_answer("New", 20)])
    _, state = client.json("GET", "/api/state")
    assert state["signed_in"] is True
    assert state["characters"] == [KEY]
    assert [a["title"] for a in state["answers"]] == ["New", "Old"]  # newest first
    assert state["open_questions"] == [{"id": "1-1", "text": "How do I fish?", "asked_at": 1}]
    assert state["usage"]["last_hour"] == 2 and state["usage"]["last_day"] == 7
    assert state["alerts"] == {"notify": True, "speak": False}
    assert state["last_save"] == 1000
    assert state["settings"]["notify"] is True


def test_state_without_any_save_is_a_sentence_not_an_error(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)
    for saved in rig.wow_dir.rglob("CoachLink.lua"):
        saved.unlink()
    server = CoachServer(rig.core, 0)
    server.start()
    try:
        page = Client(server)
        page.sign_in_page()
        status, state = page.json("GET", "/api/state")
        assert status == 200 and "/coach" in state["problem"]
        assert state["characters"] == [] and state["answers"] == []
    finally:
        server.stop()


def test_ask_gives_an_answer_event(rig: Rig, client: Client) -> None:
    mailbox = rig.core.bus.subscribe()
    status, body = client.json("POST", "/api/ask", {"question": "Where to?", "character": KEY})
    assert status == 202 and body == {"started": True}
    data = wait_for_event(mailbox, "answer")
    assert data["character"] == KEY
    assert data["answer"]["title"] == "Answer to Where to?"  # type: ignore[index]
    assert data["written_to_game"] is True
    assert rig.coach.asked == ["Where to?"]


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"question": "   "}, "Type a question"),
        ({}, "Type a question"),
        ({"question": 5}, "Type a question"),
        ({"question": "x" * (MAX_QUESTION_CHARS + 1)}, "too long"),
        ({"question": "hi", "character": "bad|name"}, "character"),
        ({"question": "hi", "character": 3}, "character"),
    ],
)
def test_bad_questions_get_a_plain_sentence(client: Client, body: dict, fragment: str) -> None:  # type: ignore[type-arg]
    status, reply = client.json("POST", "/api/ask", body)
    assert status == 400 and fragment in reply["error"]


def test_a_huge_body_is_refused(client: Client) -> None:
    status, reply = client.json("POST", "/api/ask", {"question": "x" * (MAX_BODY_BYTES + 10)})
    assert status == 413 and "too large" in reply["error"]


def test_a_body_that_is_not_json_is_refused(server: CoachServer, client: Client) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    headers = {"Host": server.host_header, "X-Wow-Coach": "1", "Cookie": client.cookie or ""}
    connection.request("POST", "/api/ask", body=b"{not json", headers=headers)
    assert connection.getresponse().status == 400


def test_the_coach_can_only_do_one_thing_at_a_time(rig: Rig, client: Client) -> None:
    gate = threading.Event()
    rig.coach.gate = gate
    mailbox = rig.core.bus.subscribe()
    assert client.json("POST", "/api/ask", {"question": "first"})[0] == 202
    status, reply = client.json("POST", "/api/ask", {"question": "second"})
    assert status == 409 and "busy" in reply["error"]
    gate.set()
    wait_for_event(mailbox, "answer")


def test_an_ai_error_becomes_an_error_event_with_its_sentence(rig: Rig, client: Client) -> None:
    rig.coach.error = PlanLimitReached("Your plan is used up. Try again in 5 minutes.")
    mailbox = rig.core.bus.subscribe()
    client.json("POST", "/api/ask", {"question": "hi"})
    data = wait_for_event(mailbox, "error")
    assert data == {"message": "Your plan is used up. Try again in 5 minutes."}


def test_a_surprise_failure_never_shows_a_traceback(rig: Rig, client: Client) -> None:
    rig.coach.error = RuntimeError("secret internals /home/x/file.py line 3")
    mailbox = rig.core.bus.subscribe()
    client.json("POST", "/api/ask", {"question": "hi"})
    message = str(wait_for_event(mailbox, "error")["message"])
    assert "secret" not in message and "Traceback" not in message
    assert message.startswith("Something unexpected went wrong")


def test_answer_open_answers_the_games_questions(rig: Rig, client: Client) -> None:
    write_save(rig.wow_dir, ("1-1", "How?"))
    mailbox = rig.core.bus.subscribe()
    status, body = client.json("POST", "/api/answer-open", {"character": KEY})
    assert status == 202 and body == {"started": True}
    assert wait_for_event(mailbox, "answer")["character"] == KEY
    assert rig.coach.answered_calls == [KEY]


def test_answer_open_with_nothing_waiting(client: Client) -> None:
    status, body = client.json("POST", "/api/answer-open", {})
    assert status == 200 and body["started"] is False


def test_settings_are_changed_and_saved(rig: Rig, client: Client) -> None:
    changes = {"notify": False, "speak": True, "max_calls_per_hour": 5, "model": "gpt-big"}
    status, body = client.json("POST", "/api/settings", {"changes": changes})
    assert status == 200 and body["settings"]["max_calls_per_hour"] == 5
    saved = json.loads(rig.settings_file.read_text("utf-8"))
    assert saved["notify"] is False and saved["speak"] is True and saved["model"] == "gpt-big"
    assert rig.core.settings.max_calls_per_hour == 5


def test_settings_ignore_bad_values(client: Client) -> None:
    changes = {"max_calls_per_hour": "lots", "unknown": 1, "notify": "yes"}
    status, body = client.json("POST", "/api/settings", {"changes": changes})
    assert status == 200 and body["settings"]["max_calls_per_hour"] == 20
    assert body["settings"]["notify"] is True
    assert client.json("POST", "/api/settings", {"changes": 5})[0] == 400


def test_models_come_from_the_injected_function(client: Client) -> None:
    status, body = client.json("GET", "/api/models")
    assert status == 200
    assert body["models"] == [
        {"slug": "gpt-small", "name": "Small and fast"},
        {"slug": "gpt-big", "name": "Big"},
    ]


def test_a_model_list_failure_is_a_sentence(tmp_path: Path) -> None:
    rig = make_rig(tmp_path)

    def failing() -> list:  # type: ignore[type-arg]
        raise NotSignedIn("You are not signed in with ChatGPT yet.")

    rig.core._list_models = failing
    server = CoachServer(rig.core, 0)
    server.start()
    try:
        page = Client(server)
        page.sign_in_page()
        status, body = page.json("GET", "/api/models")
        assert status == 502 and body["error"] == "You are not signed in with ChatGPT yet."
    finally:
        server.stop()


def test_sign_in_and_sign_out(rig: Rig, client: Client) -> None:
    rig.signin.signed_in = False
    mailbox = rig.core.bus.subscribe()
    assert client.json("POST", "/api/signin")[0] == 202
    assert wait_for_event(mailbox, "signin")["state"] == "waiting"
    assert wait_for_event(mailbox, "signin")["state"] == "signed_in"
    assert rig.signin.sign_ins == 1
    status, body = client.json("POST", "/api/signout")
    assert status == 200 and body == {"signed_out": True, "revoke_confirmed": True}
    assert rig.signin.signed_in is False
    rig.signin.revoke_ok = False
    assert client.json("POST", "/api/signout")[1]["revoke_confirmed"] is False


def test_events_stream_sends_heartbeats_and_events(
    rig: Rig, server: CoachServer, client: Client
) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    headers = {"Host": server.host_header, "Cookie": client.cookie or ""}
    connection.request("GET", "/api/events", headers=headers)
    response = connection.getresponse()
    assert response.status == 200
    assert response.getheader("Content-Type", "").startswith("text/event-stream")
    assert response.fp.readline() == b": connected\n"  # type: ignore[union-attr]
    response.fp.readline()  # type: ignore[union-attr]
    assert response.fp.readline() == b": heartbeat\n"  # type: ignore[union-attr]
    response.fp.readline()  # type: ignore[union-attr]
    rig.core.bus.publish("save", {"saved_at": 5})
    assert response.fp.readline() == b"event: save\n"  # type: ignore[union-attr]
    assert json.loads(response.fp.readline().removeprefix(b"data: ")) == {"saved_at": 5}  # type: ignore[union-attr]
    connection.close()
