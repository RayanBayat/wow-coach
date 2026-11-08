# Way 5: the Claude Code agent

This is the easiest way if you use **Claude Code** (Anthropic's AI app for your terminal). An
**agent** is a ready-made helper with its own instructions. The wow-coach agent runs your whole
coaching session: it checks that everything works, reads your character, asks for your goal
and builds a plan to reach it.

You need: WoW Forever, Claude Code, and [uv](https://docs.astral.sh/uv/getting-started/installation/)
(the [Connect an AI app](connect-an-ai-app.md) guide, step 1, shows how to install it).

## Set it up (once)

In a terminal, run this one line:

```
uvx --from git+https://github.com/RayanBayat/wow-coach@v0.10.0 wow-coach setup --claude-code
```

It goes through five steps and prints `OK` or `PROBLEM` for each:

1. Finds your game folder (it asks you to paste the path of `_forever_` if it cannot find it)
   and remembers it.
2. Installs the HeroBridge addon (or updates an old one).
3. Creates your player notes file (never overwrites an existing one). The coach creates one
   journal per character later.
4. Copies the coach agent and skill into `~/.claude` (your Claude Code folder).
5. Checks that the coach can see your game.

If it tells you to restart the game, quit through the game menu and start it again. Running the
setup again is safe.

## Start your coach

```
claude --agent wow-coach
```

**What it does at the start:** it runs the check, looks whether WoW is running (and if so,
starts live mode), and then asks **which character to continue**. You see your characters as
clickable options, the most recently played first (with level, class, zone, when you last
played and your goal), plus "A new character". With more than three characters, the three
most recent are shown, and you can type another name under "Other". (If your Claude Code
session cannot show clickable options, for example when it runs without a screen, you get a
numbered list and type a number.)

After you choose, it reads that character's memory and greets you with "welcome back": where
you were and what you were doing last time, what changed since, and your progress toward your
goal. If the character has no journal yet, it asks for a goal and starts one. For a new
character, log in with it and type `/coach`.

## Memory: one journal per character

Each character has its own **journal** (choices like spec and professions, goals and plans, a
progress log, open advice), so a second character never inherits the first one's plans. Your
**player notes** (how you like to be coached, for example "exact click steps", "no Questie")
are shared by all characters. Progress numbers (levels, XP, gold, play time) come from the
addon's own progress log, not from the coach's memory. Run `wow-coach characters` or
`wow-coach progress` yourself to see them.

## Give it a goal

Just say it in plain words, for example:

- "Level 20 by Sunday."
- "I want 100 gold for the mount."
- "Max Tailoring."
- "Run Deadmines."

The coach turns it into a measurable target with a deadline, asks only what it is missing (how
many hours you have, solo or group), researches it (Warcraft Wiki first, then the web), and
gives you a plan: milestones with dates, the route, what to skip and the risks. It then tells
you what to do today. The plan is saved in the character's journal under **Goals**, and on every new save
it tells you whether you are ahead or behind.

## Live mode

When the game is running, the coach watches for your saves. Type `/coach` in the game and it
answers within seconds: what changed, what to fix and what to do next. When you log out it
writes a summary and says what to do first next time.

## Update to a new version

Run the setup line again with the new version number in it (see the
[releases page](https://github.com/RayanBayat/wow-coach/releases)). It updates the addon and
the agent. A different agent file that was there is kept as `wow-coach.md.bak`.

## Remove it

1. Delete `~/.claude/agents/wow-coach.md`.
2. Delete the folder `~/.claude/skills/wow-coach`.
3. Optional: delete the `HeroBridge` folder in the game's `Interface/AddOns`, and the folder
   `wow-coach` in your data folder (see the notes location in
   [Connect an AI app](connect-an-ai-app.md)) to remove your notes, journals and saved settings.

## If you also connected wow-coach to Claude Code by hand

The agent brings its own wow-coach connection. If you earlier added it yourself, remove the old
one so there are not two:

```
claude mcp remove wow-coach
```

This cannot be checked automatically, so do it if you ever ran `claude mcp add ... wow-coach`.

## If something does not work

The agent runs `wow-coach check` first and walks you through the fix. See also
[Troubleshooting](troubleshooting.md). The agent frontmatter fields used here are described in
the [Claude Code sub-agents page](https://code.claude.com/docs/en/sub-agents).
