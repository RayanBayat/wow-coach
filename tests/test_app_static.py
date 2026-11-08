"""The page's own files: no unsafe JavaScript, and they ship inside the package."""

import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from wow_coach.app.server import STATIC_FILES

ROOT = Path(__file__).parent.parent
STATIC = ROOT / "src" / "wow_coach" / "app" / "static"

# Ways to put text on a page as CODE. AI text is untrusted, so the page may use none of them.
FORBIDDEN_IN_JS = [
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "eval(",
    "new Function",
]
INLINE_HANDLER = re.compile(r"""<[^>]*\son[a-z]+\s*=""", re.IGNORECASE)


def test_every_listed_static_file_exists() -> None:
    assert {path.name for path in STATIC.iterdir()} == set(STATIC_FILES)


@pytest.mark.parametrize("path", sorted(STATIC.glob("*.js")), ids=lambda p: p.name)
def test_javascript_never_builds_markup_from_text(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    found = [word for word in FORBIDDEN_IN_JS if word in text]
    assert not found, f"{path.name} uses {found}"
    assert not re.search(r"\.on[a-z]+\s*=[^=]", text), "use addEventListener, not .onclick ="
    assert 'setTimeout("' not in text and 'setInterval("' not in text


def test_html_has_no_inline_code_or_styles() -> None:
    text = (STATIC / "index.html").read_text(encoding="utf-8")
    assert not INLINE_HANDLER.search(text), "an on...= attribute in the HTML"
    assert "javascript:" not in text.lower()
    assert " style=" not in text and "<style" not in text.lower()
    for script in re.findall(r"<script\b[^>]*>", text):
        assert "src=" in script, "inline scripts are blocked by the page's security policy"
    assert "<script>" not in text


def test_the_page_follows_openais_wording() -> None:
    text = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "Continue with ChatGPT" in text
    assert "You're using your ChatGPT plan" in text
    assert "https://chatgpt.com/settings/usage" in text


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is needed to build the wheel")
def test_the_built_wheel_contains_the_static_files(tmp_path: Path) -> None:
    out = tmp_path / "dist"
    subprocess.run(  # noqa: S603  (fixed arguments, no shell)
        [str(shutil.which("uv")), "build", "--wheel", "--out-dir", str(out), str(ROOT)],
        check=True,
        capture_output=True,
    )
    wheel = next(out.glob("*.whl"))
    names = zipfile.ZipFile(wheel).namelist()
    for name in STATIC_FILES:
        assert f"wow_coach/app/static/{name}" in names
