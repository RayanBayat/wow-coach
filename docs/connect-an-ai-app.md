# Way 2: connect an AI app (MCP)

With this way, your AI app reads your character itself. You type `/coach` in the game, then ask
the AI. No copying and pasting. It also gets a memory for each of your characters, so it remembers your choices and goals.

**MCP** (Model Context Protocol) is the standard way for AI apps to use small helper programs
on your computer. The helper here is `wow-coach`. It gives the AI these tools:

- `list_characters`, `character_status`, `recent_history`: read your saved characters. `list_characters` shows the most recently played first, with the goal from each one's journal.
- `progress_summary`: how a character progressed lately (play sessions, levels, XP, gold, quests, deaths).
- `read_coach_notes`: the coach's memory, your **player notes** (shared by all characters) and one character's **journal**.
- `save_coach_notes`: saves one character's journal. `save_player_notes`: saves the player notes.
- `questions_from_game`, `send_advice_to_game`: the in-game [Coach panel](coach-panel.md). The
  first reads the questions you asked there; the second shows the coach's answer and next
  steps inside the game (after your next `/reload`).
- `search_wiki`, `read_wiki_page`, `find_quest`: game lookups on the [Warcraft Wiki](https://warcraft.wiki.gg).
  Use `read_wiki_page` for NPC locations, vendor stock, quest givers and rewards. It marks
  text that is Classic-only, Retail-only or Forever-only, and always gives the page link. Use
  `search_wiki` first when you do not know the page name. Use `find_quest` with the quest ID that
  the status shows ("quest 365") to get the right quest page. These tools need the internet
  and send only the words you searched for. If the wiki does not answer, the tool says so and
  the AI falls back to a web search.

You need: the [addon installed](install-the-addon.md), and an AI app from the list below.
Allow 15 minutes.

## Step 1: Install uv

`uv` is a free tool that downloads and runs the helper program for you. Its official install
page is https://docs.astral.sh/uv/getting-started/installation/

A **terminal** is a window where you type commands. On Windows, open **PowerShell** (search for
it in the Start menu). On macOS, open **Terminal** (search with Spotlight). On Linux, open your
terminal app.

Windows (PowerShell), copy this line, paste it, press Enter:

```
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

macOS and Linux, copy this line, paste it, press Enter:

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then **close the terminal and open a new one**, and type:

```
uv --version
```

**You should see:** a version number such as `uv 0.12.0`.

**If it didn't work:** "command not found" or "not recognized" usually means you must open a
new terminal window. If it still fails, follow the uv page above.

## Step 2: Check the helper runs

```
uvx --from git+https://github.com/RayanBayat/wow-coach@v0.8.0 wow-coach check
```

**You should see:** lines saying whether your game folder was found and whether a saved
character exists. The first run takes a minute while things download.

If the game folder is not found, run this once. It asks you to paste the path of `_forever_`
(see [the install guide](install-the-addon.md), step 2), checks it and remembers it, so the AI
app does not need to be told:

```
uvx --from git+https://github.com/RayanBayat/wow-coach@v0.8.0 wow-coach setup
```

(As another way, you can give the folder to your app as `WOW_COACH_WOW_DIR`, below.) The helper looks by itself in the usual places: Windows
`C:\Program Files (x86)\World of Warcraft\_forever_` (or `C:\Program Files\...`, any drive),
macOS `/Applications/World of Warcraft/_forever_`, and Linux with Wine
`~/Games/battlenet/drive_c/...` or `~/.wine/drive_c/...`.

Optional settings (environment variables, which are named values you hand to a program):

| Name | Meaning |
|---|---|
| `WOW_COACH_WOW_DIR` | The `_forever_` folder, when it is not in a usual place. Overrides the folder saved by `wow-coach setup` |
| `WOW_COACH_CONFIG_FILE` | Where the saved settings (`config.json`, the remembered game folder) live. Default: the same folder as the notebook |
| `WOW_COACH_NOTES_FILE` | Where the player notes file lives. The character journals go in a `characters` folder next to it. Default: Windows `%LOCALAPPDATA%\wow-coach\coach-notes.md`, macOS `~/Library/Application Support/wow-coach/coach-notes.md`, Linux `~/.local/share/wow-coach/coach-notes.md` |

## Step 3: Add it to your app

Pick your app. Every section runs the same command:
`uvx --from git+https://github.com/RayanBayat/wow-coach@v0.8.0 wow-coach mcp`.
Each config file holds **JSON** or **TOML**, two ways of writing settings as text. Copy the
block exactly, including quotes and commas. Edit the file with a plain text editor such as
Notepad, TextEdit (plain text mode) or any code editor.

In the examples, `WOW_COACH_WOW_DIR` is optional: delete the whole `env` part if your game is
in a usual place. On Windows, write each backslash twice inside JSON (`\\`).

If your app can't find `uvx`, replace `"uvx"` with the full path that `where uvx` (Windows) or
`which uvx` (macOS, Linux) prints.

### Claude Desktop

1. Open Claude Desktop, then **Settings**, then **Developer**, then **Edit Config**. This opens
   `claude_desktop_config.json`.
   Windows: `%APPDATA%\Claude\claude_desktop_config.json`.
   macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`.
   Linux: `~/.config/Claude/claude_desktop_config.json`.
2. Put this in the file (if it already has an `mcpServers` section, add only the `"wow-coach"`
   part inside it):

```json
{
  "mcpServers": {
    "wow-coach": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/RayanBayat/wow-coach@v0.8.0", "wow-coach", "mcp"],
      "env": { "WOW_COACH_WOW_DIR": "C:\\Program Files (x86)\\World of Warcraft\\_forever_" }
    }
  }
}
```

3. Quit Claude Desktop completely and start it again.

**You should see:** the wow-coach tools in the connectors/tools list of a new chat.
Source: https://modelcontextprotocol.io/docs/develop/connect-local-servers (verified)

### Claude Code

Claude Code is Claude's command-line app. In a terminal:

```
claude mcp add --transport stdio wow-coach -- uvx --from git+https://github.com/RayanBayat/wow-coach@v0.8.0 wow-coach mcp
```

With the game folder set (put an option between `--env` and the name, as shown):

```
claude mcp add --env WOW_COACH_WOW_DIR="/path/to/_forever_" --transport stdio wow-coach -- uvx --from git+https://github.com/RayanBayat/wow-coach@v0.8.0 wow-coach mcp
```

Add `--scope user` to make it available in every folder. Check it with `claude mcp list`:
**You should see** `wow-coach` marked as connected.
Source: https://code.claude.com/docs/en/mcp (verified)

### OpenAI Codex and the ChatGPT desktop app

OpenAI's page says the ChatGPT desktop app, the Codex CLI and the Codex IDE extension share one
config file, `~/.codex/config.toml` (on Windows, the `.codex` folder in your user folder).
Add this (TOML uses `[section]` headings):

```toml
[mcp_servers.wow-coach]
command = "uvx"
args = ["--from", "git+https://github.com/RayanBayat/wow-coach@v0.8.0", "wow-coach", "mcp"]

[mcp_servers.wow-coach.env]
WOW_COACH_WOW_DIR = "C:\\Program Files (x86)\\World of Warcraft\\_forever_"
```

Or on the command line:

```
codex mcp add wow-coach --env WOW_COACH_WOW_DIR="/path/to/_forever_" -- uvx --from git+https://github.com/RayanBayat/wow-coach@v0.8.0 wow-coach mcp
```

Restart the app. Source: https://learn.chatgpt.com/docs/extend/mcp?surface=cli (verified). We
did not test whether the regular ChatGPT website can use it: it can't, because it can't start
programs on your computer.

### Gemini CLI

Edit `~/.gemini/settings.json` (user) or `.gemini/settings.json` (one project):

```json
{
  "mcpServers": {
    "wow-coach": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/RayanBayat/wow-coach@v0.8.0", "wow-coach", "mcp"],
      "env": { "WOW_COACH_WOW_DIR": "/path/to/_forever_" }
    }
  }
}
```

Restart Gemini CLI and type `/mcp list`.
Sources: https://geminicli.com/docs/tools/mcp-server/ and
https://geminicli.com/docs/cli/tutorials/mcp-setup/ (verified). Google's page says Gemini CLI
was replaced by Antigravity CLI for free-tier and Google One users on 2026-06-18. We found
that Antigravity keeps its MCP settings in `~/.gemini/config/mcp_config.json`, but only from
a third-party article, so **we did not verify Antigravity**.

### Cursor

Edit `~/.cursor/mcp.json` (all projects) or `.cursor/mcp.json` (one project):

```json
{
  "mcpServers": {
    "wow-coach": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/RayanBayat/wow-coach@v0.8.0", "wow-coach", "mcp"],
      "env": { "WOW_COACH_WOW_DIR": "/path/to/_forever_" }
    }
  }
}
```

Source: https://cursor.com/docs/context/mcp (verified)

### VS Code with GitHub Copilot

VS Code uses the key `servers`, not `mcpServers`. Open the Command Palette (Ctrl+Shift+P, or
Cmd+Shift+P on Mac) and run **MCP: Open User Configuration**, then add:

```json
{
  "servers": {
    "wow-coach": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/RayanBayat/wow-coach@v0.8.0", "wow-coach", "mcp"],
      "env": { "WOW_COACH_WOW_DIR": "/path/to/_forever_" }
    }
  }
}
```

For one project only, use `.vscode/mcp.json`. Use Copilot Chat in **Agent** mode.
Sources: https://code.visualstudio.com/docs/agents/reference/mcp-configuration and
https://code.visualstudio.com/docs/copilot/customization/mcp-servers (verified)

### LM Studio

In LM Studio, open the **Program** tab in the right sidebar, click **Install**, then **Edit
mcp.json**. Add (inside the `mcpServers` section, if one exists):

```json
{
  "mcpServers": {
    "wow-coach": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/RayanBayat/wow-coach@v0.8.0", "wow-coach", "mcp"],
      "env": { "WOW_COACH_WOW_DIR": "/path/to/_forever_" }
    }
  }
}
```

Source: https://lmstudio.ai/docs/app/mcp. That page confirms the Edit mcp.json steps and the
`mcpServers` key, and says LM Studio follows Cursor's notation. It does not show `command`,
`args` and `env`, so those fields are **not verified for LM Studio**. Your model must also
support tool use.

### Other apps

Any app that supports MCP "stdio" servers needs three things: the command `uvx`, the arguments
`--from git+https://github.com/RayanBayat/wow-coach@v0.8.0 wow-coach mcp`, and optionally the
environment variable. Look for "add MCP server" in its settings.

## Step 4: Test it

1. Start the game, log in, and type `/coach` (wait for the screen to reload).
2. In your AI app, send: `check my WoW character`

**You should see:** the AI calls the wow-coach tool (the app may ask permission first) and
describes your character. For best results add the coach instructions too; see
[the skill guide](coach-skill-and-live-mode.md) or [Way 1, step 3](use-with-any-ai-chat.md).

If it fails, run this in a terminal and read what it says:

```
uvx --from git+https://github.com/RayanBayat/wow-coach@v0.8.0 wow-coach check
```

You can also print your character in the terminal with `... wow-coach status`, your characters
with `... wow-coach characters` and a character's recent progress with `... wow-coach progress`
(same start as above, last word changed). More help: [Troubleshooting](troubleshooting.md).
