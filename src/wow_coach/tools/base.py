"""``CoachTool``: one tool the built-in coach may use, with safe argument handling.

An AI picks the arguments of a tool, so they can be wrong in any way: missing, the wrong
type, far too big. ``check_arguments`` turns them into clean values or into a plain sentence
that tells the AI what to fix. A tool never raises because of what the AI sent.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from wow_coach.ai.base import ToolSpec
from wow_coach.errors import WowCoachError

type ToolKind = Literal["read", "write", "web"]
"""``read``: reads the player's own data. ``write``: saves notes. ``web``: reaches a website."""

# One tool answer may not fill the prompt. About 3000 tokens.
MAX_OUTPUT_CHARACTERS = 12_000
_CUT_NOTE = "\n\n[Cut here: the answer was longer than {limit} characters.]"


@dataclass(frozen=True, slots=True)
class ToolSource:
    """A web page a tool used, to show the player as a source."""

    title: str
    url: str


@dataclass(frozen=True, slots=True)
class ToolRun:
    """The result of running a tool: its text and the pages it used.

    ``only_listed`` is True when the pages were only found in a list (a search), not read.
    A list is a weaker source: the engine shows listed pages only when nothing was read.
    """

    output: str
    sources: tuple[ToolSource, ...] = ()
    only_listed: bool = False


type Sourcer = Callable[[str], tuple[ToolSource, ...]]
"""Finds the pages a tool used in its (raw) output. It must never raise."""


@dataclass(frozen=True, slots=True)
class CoachTool:
    """A tool: what the AI sees (``spec``), what it does (``handler``) and how to say it.

    ``handler`` receives arguments that already passed ``check_arguments``. ``describer``
    makes the short sentence shown to people; it also gets the checked arguments.
    ``clean`` is applied to every output (the engine uses it to hide other players' names).
    """

    spec: ToolSpec
    kind: ToolKind
    handler: Callable[[dict[str, object]], str]
    describer: Callable[[Mapping[str, object]], str]
    clean: Callable[[str], str] = field(default=lambda text: text)
    sourcer: Sourcer | None = None  # None: this tool does not use web pages
    only_listed: bool = False  # True: ``sourcer`` finds pages in a list, which were not read

    @property
    def name(self) -> str:
        """The tool's name, as the AI calls it."""
        return self.spec.name

    def run(self, arguments: Mapping[str, object]) -> str:
        """Run the tool. Always returns text: a problem becomes a sentence the AI can act on."""
        return self.run_with_sources(arguments).output

    def run_with_sources(self, arguments: Mapping[str, object]) -> ToolRun:
        """Like ``run``, and also says which web pages the answer came from.

        The pages are found in the tool's own output, never in anything the AI wrote.
        """
        checked = check_arguments(self.spec.parameters, arguments)
        if isinstance(checked, str):
            return ToolRun(checked)
        try:
            output = self.handler(checked)
        except (WowCoachError, OSError) as error:
            problem = f"The {self.name} tool could not finish: {error}"
            return ToolRun(cap_text(self.clean(problem), MAX_OUTPUT_CHARACTERS))
        return ToolRun(
            cap_text(self.clean(output), MAX_OUTPUT_CHARACTERS),
            self._sources_in(output),
            self.only_listed,
        )

    def _sources_in(self, output: str) -> tuple[ToolSource, ...]:
        if self.sourcer is None:
            return ()
        try:
            found = self.sourcer(output)
        except ValueError, IndexError:  # a parsing slip must never cost the answer
            return ()
        return tuple(ToolSource(self.clean(item.title), item.url) for item in found)

    def describe(self, arguments: Mapping[str, object]) -> str:
        """A short plain sentence about this call, for people (never raises)."""
        checked = check_arguments(self.spec.parameters, arguments)
        # A bad call is still worth a line; show it with whatever arguments the AI sent.
        shown = arguments if isinstance(checked, str) else checked
        try:
            return self.describer(shown)
        except KeyError, TypeError, ValueError:
            return f"Used the {self.name} tool"


def cap_text(text: str, limit: int) -> str:
    """``text`` cut to ``limit`` characters, with a note when something was cut."""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + _CUT_NOTE.format(limit=limit)


def check_arguments(
    schema: Mapping[str, object], arguments: Mapping[str, object]
) -> dict[str, object] | str:
    """Check ``arguments`` against a tool's JSON schema.

    Returns the clean arguments (defaults filled in, numbers clamped to "minimum" and
    "maximum", text cut to "maxLength"), or a sentence explaining the first problem.
    A ``None`` value counts as "not given": OpenAI's strict mode sends ``null`` for
    optional arguments.
    """
    properties = schema.get("properties")
    known = properties if isinstance(properties, dict) else {}
    required = schema.get("required")
    must_have = set(required) if isinstance(required, list) else set()
    for name in arguments:
        if name not in known:
            allowed = ", ".join(sorted(known)) or "none"
            return f"This tool has no argument called '{name}'. Its arguments: {allowed}."
    checked: dict[str, object] = {}
    for name, definition in known.items():
        value = arguments.get(name)
        if value is None:
            if name in must_have:
                return f"The argument '{name}' is required. Call the tool again with it."
            if isinstance(definition, dict) and "default" in definition:
                checked[name] = definition["default"]
            continue
        result = _check_value(name, value, definition if isinstance(definition, dict) else {})
        if isinstance(result, _Problem):
            return result.sentence
        checked[name] = result
    return checked


@dataclass(frozen=True, slots=True)
class _Problem:
    """Marks a failed check (a plain string could also be a legal text value)."""

    sentence: str


def _check_value(name: str, value: object, definition: Mapping[str, object]) -> object:
    """The clean value, or a ``_Problem``."""
    kind = definition.get("type")
    if kind == "string":
        if not isinstance(value, str):
            return _Problem(f"The argument '{name}' must be text.")
        limit = definition.get("maxLength")
        return value[:limit] if isinstance(limit, int) else value
    if kind == "integer":
        # bool is a kind of int in Python, but "true" is not a number of quests.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return _Problem(f"The argument '{name}' must be a whole number.")
        if isinstance(value, float) and not value.is_integer():
            return _Problem(f"The argument '{name}' must be a whole number.")
        return _clamp(int(value), definition)
    return value


def _clamp(number: int, definition: Mapping[str, object]) -> int:
    low = definition.get("minimum")
    high = definition.get("maximum")
    if isinstance(low, int):
        number = max(number, low)
    if isinstance(high, int):
        number = min(number, high)
    return number
