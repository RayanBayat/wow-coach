"""The coach tools: what wow-coach's own coach can use, whichever AI provider answers.

The Claude Code coach reaches these abilities through the MCP server (``wow_coach.server``).
The built-in coach has no MCP, so this package offers the same abilities as plain Python
objects:

* ``answers``: the ``answer_*`` functions both sides share (status, history, notes, ...).
* ``base``: ``CoachTool`` (a tool's spec, kind, ``run`` and ``describe``) and the argument
  checking that keeps a confused AI from doing harm.
* ``registry``: ``build_coach_tools`` builds the tools for one character.

How a new AI provider (Gemini, the Claude API, ...) plugs in
------------------------------------------------------------
Nothing here changes. A provider only implements ``Provider.ask`` from ``wow_coach.ai.base``
with the same neutral types:

1. Turn each ``ToolSpec`` (``CoachTool.spec``) into the provider's own tool format.
2. Turn the conversation (``Message``, ``ToolCall``, ``ToolResult`` and ``Replay`` items)
   into the provider's own message format. ``Replay`` holds whatever the provider itself
   needs to see again next time (ChatGPT: reasoning items; another provider can put its own
   opaque blocks there, or send nothing).
3. Read the reply into an ``Answer``: the text, ``ToolCall``s, ``WebSearch``es (when the
   provider has its own search) and the ``Replay`` items.

The loop that runs the tools (ask, run each ``ToolCall`` with ``CoachTool.run``, append
``ToolResult``s, ask again) is written once, in the caller, and never looks at the provider.

Left out on purpose, compared with the MCP server:

* ``list_characters``: the app already knows which character the player is coaching.
* ``questions_from_game`` and ``send_advice_to_game``: the built-in coach answers those
  questions itself and the app, not the AI, writes the in-game panel file.
"""
