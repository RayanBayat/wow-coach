"""Runs the hand-test script end to end against fakes (never against the real OpenAI)."""

import base64
import importlib.util
import json
import threading
from pathlib import Path
from types import ModuleType
from urllib.parse import parse_qs, urlsplit

import httpx2
import keyring
import keyring.backend
import keyring.backends.fail
import pytest

from wow_coach.ai import chatgpt_signin as signin
from wow_coach.keychain import Keychain

SCRIPT = Path(__file__).parent.parent / "scripts" / "chatgpt_signin_spike.py"
CLIENT_ID = "oaiapp_spike"
ACCESS = "spike-access-SECRET"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("chatgpt_signin_spike", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeOpenAI:
    """One fake for auth.openai.com and api.openai.com, plus the player's browser."""

    def __init__(self) -> None:
        self.nonce = ""
        self.paths: list[str] = []

    def open_browser(self, url: str) -> bool:
        query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        self.nonce = query["nonce"]
        params = {"code": "c", "state": query["state"], "client_id": CLIENT_ID}

        def visit() -> None:
            with httpx2.Client(trust_env=False) as client:
                client.get(query["redirect_uri"], params=params)

        threading.Thread(target=visit, daemon=True).start()
        return True

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        self.paths.append(url)
        if url == signin.TOKEN_URL:
            return httpx2.Response(200, json=self._tokens())
        if url == signin.REVOKE_URL:
            return httpx2.Response(200)
        if url.endswith("/models"):
            return httpx2.Response(
                200,
                json={
                    "models": [{"slug": "m1", "display_name": "Model One", "visibility": "list"}]
                },
            )
        assert url.endswith("/responses")
        done = {
            "type": "response.completed",
            "response": {"usage": {"input_tokens": 9, "output_tokens": 5}},
        }
        delta = {"type": "response.output_text.delta", "delta": "A big online fantasy game."}
        text = "".join(f"data: {json.dumps(e)}\n\n" for e in (delta, done))
        return httpx2.Response(200, content=text.encode())

    def _tokens(self) -> dict[str, object]:
        claims = {
            "iss": signin.ISSUER,
            "aud": CLIENT_ID,
            "exp": 4_000_000_000,
            "nonce": self.nonce,
            "sub": "u",
        }
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
        return {
            "id_token": f"e30.{payload}.sig",
            "access_token": ACCESS,
            "refresh_token": "spike-refresh-SECRET",
            "expires_in": 3600,
            "scope": signin.SCOPES,
        }


@pytest.fixture(autouse=True)
def _no_real_keychain() -> None:
    keyring.set_keyring(keyring.backends.fail.Keyring())  # type: ignore[no-untyped-call]


def test_spike_signs_in_lists_models_asks_and_prints_usage(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    fake = FakeOpenAI()
    code = load_script().main(
        ["--port", "0"],
        transport=httpx2.MockTransport(fake.handle),
        open_browser=fake.open_browser,
        keychain=Keychain(),
        data_dir=tmp_path,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Model One" in out
    assert "Answer: A big online fantasy game." in out
    assert "9 input and 5 output tokens" in out
    assert "Using ChatGPT plan" in out
    assert "memory only" in out  # no keychain here, and the script says so
    assert ACCESS not in out
    assert "SECRET" not in out


def test_spike_sign_out_revokes(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    fake = FakeOpenAI()
    keychain = Keychain()
    transport = httpx2.MockTransport(fake.handle)
    script = load_script()
    script.main(
        ["--port", "0"],
        transport=transport,
        open_browser=fake.open_browser,
        keychain=keychain,
        data_dir=tmp_path,
    )
    code = script.main(["--sign-out"], transport=transport, keychain=keychain, data_dir=tmp_path)
    assert code == 0
    assert signin.REVOKE_URL in fake.paths
    assert "Signed out" in capsys.readouterr().out.splitlines()[-1]
    assert keychain.get(signin.KEY_REFRESH_TOKEN) is None


def test_spike_reports_a_problem_in_plain_words(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    def broken(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("boom", request=request)

    keychain = Keychain()
    keychain.set(signin.KEY_REFRESH_TOKEN, "r")
    keychain.set(signin.KEY_CLIENT_ID, CLIENT_ID)
    code = load_script().main(
        [], transport=httpx2.MockTransport(broken), keychain=keychain, data_dir=tmp_path
    )
    assert code == 1
    assert "Problem: " in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []  # the lock file is removed again


def test_spike_forget_registration(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    keychain = Keychain()
    keychain.set(signin.KEY_REFRESH_TOKEN, "r")
    keychain.set(signin.KEY_CLIENT_ID, CLIENT_ID)
    code = load_script().main(["--forget-registration"], keychain=keychain, data_dir=tmp_path)
    assert code == 0
    assert keychain.get(signin.KEY_CLIENT_ID) is None
    assert keychain.get(signin.KEY_REFRESH_TOKEN) is None
    assert "registers wow-coach again" in capsys.readouterr().out


def test_spike_says_plainly_when_the_keychain_is_locked(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    class Locked(keyring.backend.KeyringBackend):
        priority = 1

        def get_password(self, service: str, username: str) -> str | None:  # noqa: ARG002
            raise RuntimeError("locked")

        def set_password(self, service: str, username: str, password: str) -> None:  # noqa: ARG002
            raise RuntimeError("locked")

        def delete_password(self, service: str, username: str) -> None:  # noqa: ARG002
            raise RuntimeError("locked")

    keyring.set_keyring(Locked())
    code = load_script().main([], keychain=Keychain(), data_dir=tmp_path)
    assert code == 1
    assert "unlock it" in capsys.readouterr().out
