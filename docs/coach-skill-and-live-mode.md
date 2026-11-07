# Way 3: the coach skill and live mode

An **AI agent** is an AI app that can run commands and read files on your computer, such as
Claude Code, OpenAI Codex, Gemini CLI, GitHub Copilot or Cursor. Many of them support **Agent
Skills**: a folder with a `SKILL.md` file of instructions that the agent loads when it is
relevant. The format is an open standard: https://agentskills.io/specification

The wow-coach skill is the same instructions file used in the other ways, in the skill format.
Combine it with [Way 2](connect-an-ai-app.md) so the agent can read your character.

## Shortcut for Claude Code

Run `uvx --from git+https://github.com/RayanBayat/wow-coach@v0.4.0 wow-coach setup --claude-code`.
It copies the skill (and the ready-made coach agent, see
[the Claude Code agent](claude-code-agent.md)) into `~/.claude`. For other agents, follow the
steps below.

## Step 1: Get the skill folder

1. Open https://github.com/RayanBayat/wow-coach and click **Code**, then **Download ZIP**.
   Unzip it.
2. Inside, find the folder `src/wow_coach/assets/skills/wow-coach`. It contains `SKILL.md`. The folder name must stay
   `wow-coach`.

**You should see:** `src/wow_coach/assets/skills/wow-coach/SKILL.md` on your disk.

## Step 2: Put it where your agent looks

Copy the whole `wow-coach` folder into one of these skills folders. `~` means your user
folder. If the `skills` folder doesn't exist, create it.

| Agent | Your personal skills folder | Source |
|---|---|---|
| Claude Code | `~/.claude/skills/wow-coach/` | https://code.claude.com/docs/en/skills |
| OpenAI Codex | `~/.agents/skills/wow-coach/` | https://developers.openai.com/codex/skills (found through search; older pages say `~/.codex/skills`) |
| Gemini CLI | `~/.gemini/skills/wow-coach/` or `~/.agents/skills/wow-coach/` | https://geminicli.com/docs/cli/skills/ |
| GitHub Copilot | `~/.copilot/skills/wow-coach/` or `~/.agents/skills/wow-coach/` | https://docs.github.com/en/copilot/concepts/agents/about-agent-skills |
| Cursor | `~/.cursor/skills/wow-coach/` or `~/.agents/skills/wow-coach/` | https://cursor.com/docs/context/skills |

Every one of these agents can also read a skill from a project folder (for example
`.claude/skills/`, `.agents/skills/`), but then only inside that project.

**You should see:** the file `~/.claude/skills/wow-coach/SKILL.md` (or the path for your
agent). Start a new session in the agent. Gemini CLI can list skills with `/skills list`.

**If it didn't work:** restart the agent, and check the path is exactly
`.../skills/wow-coach/SKILL.md` with no extra folder in between. We did not test every agent;
the paths come from each vendor's documentation, except that Codex's page could not be opened
directly, so its path is from search results of that page.

## Step 3: Use it

Ask something like "coach me in WoW Forever" or "what should I do next in WoW?". The agent loads
the skill. In Claude Code you can also type `/wow-coach`.

The skill tells the agent to:

1. Read your character with the MCP tools if they are connected, or from a sheet you paste
   (`/coach copy`), or by asking you.
2. Ask your preferences the first time (detail level, step-by-step clicks, Questie or not, solo
   or group, pace) and write them in the coach's notebook.
3. Teach in short steps and check your quests, gear and spells each time.
4. Update the notebook so it remembers next time.

## Live mode (Claude Code)

Normally you type `/coach` in the game, switch to the AI and ask. In **live mode** the AI
answers on its own the moment you type `/coach`.

How it works: the command `wow-coach watch` prints one line each time CoachLink saves, for
example:

```
CoachLink saved at 21:56:54: Testchar level 8 (reason: coach)
```

Claude Code's **Monitor** tool runs a command in the background and shows each printed line to
Claude as a message, so Claude reacts. Each line ends with the reason:

- `coach`: you typed `/coach`. The coach reads your character, celebrates what changed, fixes
  problems, and gives your next 1-3 steps.
- `logout`: you logged out. The coach writes a short summary of the session.
- `reload`: you typed `/reload`. The coach only speaks if something is wrong.

To start it, say to Claude: `start live mode`. Claude runs this command with the Monitor tool:

```
uvx --from git+https://github.com/RayanBayat/wow-coach@v0.4.0 wow-coach watch
```

Monitors last at most 30 minutes. The skill tells Claude to restart it while the game runs.
Live mode needs the session to stay open. It works with a Claude Code session; other agents
may not have an equivalent of Monitor, and then you just ask after typing `/coach`.

Test the watcher by itself in a terminal with the command above, then type `/coach` in the game.

**You should see:** a new "CoachLink saved at ..." line within a few seconds.

## Privacy

The agent reads your saved character and sends it to its AI provider, like anything you type
there.
