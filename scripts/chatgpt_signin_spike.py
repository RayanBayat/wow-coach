"""Try "Sign in with ChatGPT" by hand, on your own account.

Run it from the repository folder:

    uv run python scripts/chatgpt_signin_spike.py

It opens your browser so you can sign in with ChatGPT, lists the models your plan can use,
asks one tiny question and prints the answer and how much it used. To sign out again (this
tells OpenAI to revoke the sign-in and forgets it here):

    uv run python scripts/chatgpt_signin_spike.py --sign-out

If sign-in keeps failing because OpenAI no longer knows the saved registration, or you want to
use another ChatGPT account, forget the registration (the next run registers again):

    uv run python scripts/chatgpt_signin_spike.py --forget-registration

Your sign-in is kept in your system keychain (your desktop may ask you to unlock it, for example
the KDE Wallet: unlock it and run the script again). The only file written is a tiny empty lock
file in wow-coach's data folder, and it is removed again. Run one copy of the script at a time.
Needs a ChatGPT Plus or Pro plan.
Background and the rules we follow: docs/plans/chatgpt-signin-notes.md
"""

import argparse
import os
import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx2

from wow_coach.ai.base import AIError, Message
from wow_coach.ai.chatgpt_plan import ChatGPTPlan
from wow_coach.ai.chatgpt_signin import REVOKE_NOT_CONFIRMED, ChatGPTSignIn
from wow_coach.datafolder import data_folder
from wow_coach.keychain import Keychain

QUESTION = "Answer in five words: what is World of Warcraft?"
WELCOME_TITLE = "You're using your ChatGPT plan."
WELCOME_TEXT = (
    "Eligible usage in this app uses your ChatGPT plan. Manage usage in your ChatGPT settings."
)
MANAGE_USAGE_URL = "https://chatgpt.com/settings/usage"


def main(
    argv: Sequence[str] | None = None,
    *,
    transport: httpx2.BaseTransport | None = None,
    open_browser: Callable[[str], object] = webbrowser.open,
    keychain: Keychain | None = None,
    data_dir: Path | None = None,
) -> int:
    """Run the spike. Returns 0 on success, 1 on a problem (shown as a plain sentence)."""
    args = _parse_arguments(argv)
    keychain = keychain or Keychain()
    lock_path = (data_dir or data_folder(environ=os.environ)) / "chatgpt-refresh.lock"
    sign_in = ChatGPTSignIn(
        keychain,
        transport=transport,
        port=args.port,
        open_browser=open_browser,
        lock_path=lock_path,
    )
    try:
        if args.forget_registration:
            sign_in.forget_registration()
            print("Forgot the saved registration. The next run registers wow-coach again.")
            return 0
        if args.sign_out:
            return _sign_out(sign_in)
        return _try_it(sign_in, keychain, transport, args.model)
    except AIError as error:
        print(f"Problem: {error}")
        return 1


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Try Sign in with ChatGPT by hand.")
    parser.add_argument("--sign-out", action="store_true", help="revoke the sign-in and forget it")
    parser.add_argument(
        "--forget-registration",
        action="store_true",
        help="forget the saved registration and sign-in (use if sign-in is stuck)",
    )
    parser.add_argument("--model", help="the model slug to ask (default: the first one listed)")
    parser.add_argument("--port", type=int, default=1455, help="loopback port (default 1455)")
    return parser.parse_args(argv)


def _sign_out(sign_in: ChatGPTSignIn) -> int:
    if sign_in.sign_out():
        print("Signed out. OpenAI confirmed the sign-in is revoked.")
    else:
        print(REVOKE_NOT_CONFIRMED)
    return 0


def _try_it(
    sign_in: ChatGPTSignIn,
    keychain: Keychain,
    transport: httpx2.BaseTransport | None,
    model: str | None,
) -> int:
    if not sign_in.is_signed_in:
        _do_sign_in(sign_in)
    if keychain.notice:
        print(f"Note: {keychain.notice}")
    plan = ChatGPTPlan(sign_in, transport=transport)
    models = plan.list_models()
    print("Models on your plan:")
    for item in models:
        print(f"  {item.slug}  ({item.display_name})")
    chosen = model or (models[0].slug if models else None)
    if chosen is None:
        print("Your plan lists no models, so there is nothing to ask.")
        return 1
    print(f"\nAsking {chosen}: {QUESTION}")
    answer = plan.ask([Message("user", QUESTION)], model=chosen, max_output_tokens=60)
    print(f"Answer: {answer.text}")
    print(f"Used: {answer.usage.input_tokens} input and {answer.usage.output_tokens} output tokens")
    print(f"Using ChatGPT plan. Manage usage: {MANAGE_USAGE_URL}")
    return 0


def _do_sign_in(sign_in: ChatGPTSignIn) -> None:
    print("Opening your browser. Choose Continue with ChatGPT and sign in.")
    account = sign_in.sign_in(
        on_url=lambda url: print(
            f"If the browser does not open, copy this address into it:\n{url}\n"
        )
    )
    print(f"Signed in as {account.email or 'your ChatGPT account'}.")
    print(f"{WELCOME_TITLE} {WELCOME_TEXT}\n")


if __name__ == "__main__":
    raise SystemExit(main())
