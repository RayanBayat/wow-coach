# Troubleshooting

Find your problem, try the fixes in order.

## `/coach` does nothing, or "unknown command"

The addon isn't loaded.

1. Check the file exists: `_forever_\Interface\AddOns\CoachLink\CoachLink.toc`
   (see [Install the addon](install-the-addon.md)).
2. Quit the game fully and start it again. `/reload` does not load new addons.
3. On the character screen, click **AddOns** and tick CoachLink. If it is marked out of date,
   tick **Load out of date AddOns** (the wording may vary).

## `/coach copy` shows an empty window or no window

1. Type `/coach` first, wait for the reload, then `/coach copy`.
2. Type `/coach help` to see which commands your version has. If `copy` isn't listed, update the
   addon to the latest release.

## I pasted my character but the AI says it can't see anything

The AI app cannot see your game. Paste the text from `/coach copy` into the message itself.

## `wow-coach check` says the game folder wasn't found

1. Easiest: run `uvx --from git+https://github.com/RayanBayat/wow-coach@v0.9.0 wow-coach setup`.
   It asks for the folder, checks it and remembers it. If it says a saved folder does not
   exist any more (you moved the game), run it again.
2. Or find the `_forever_` folder (see [Install the addon](install-the-addon.md), step 2)
   and set `WOW_COACH_WOW_DIR` to that folder. In an app config it goes in the `env` section
   (see [Connect an AI app](connect-an-ai-app.md)). In a terminal: on Windows PowerShell
   `$env:WOW_COACH_WOW_DIR = "D:\Games\World of Warcraft\_forever_"`, on macOS and Linux
   `export WOW_COACH_WOW_DIR="/path/to/_forever_"`.

## `wow-coach check` says no CoachLink.lua was found

The addon has not saved yet. Start the game, log in, type `/coach`, wait for the reload, run the
check again. The file is only written on `/coach`, `/reload` or a clean logout. Killing the game
loses the save.

## The AI shows old data

The character is only as fresh as your last `/coach`, `/reload` or logout. Type `/coach` and ask
again.

## "uvx: command not found" (or "not recognized")

1. Close the terminal or the AI app completely and open it again. Programs only see newly
   installed tools after a restart.
2. Run `uv --version`. If that fails, install uv again ([step 1](connect-an-ai-app.md)).
3. In the app config use the full path of `uvx`: `where uvx` on Windows, `which uvx` on macOS
   and Linux.

## The AI app doesn't show wow-coach tools

1. Check the config file is valid JSON/TOML: a missing comma or quote breaks it. Paste it into
   a JSON checker if unsure.
2. Quit the app completely (not just the window) and start it again.
3. Run the `check` command from [Connect an AI app](connect-an-ai-app.md) to confirm the helper
   itself works.
4. Check the app's logs. Claude Desktop writes MCP logs to `%APPDATA%\Claude\logs` (Windows),
   `~/Library/Logs/Claude` (macOS) or `~/.config/Claude/logs` (Linux).

## The first start is very slow

The first run downloads the helper. Later runs are fast.

## "Addon read errors" in the character report

One part of your character could not be read, for example after a game patch. The rest still
works. Please report it at https://github.com/RayanBayat/wow-coach/issues with the error text.

## The addon shows as "out of date"

The interface number in `CoachLink.toc` is for the game build it was made for. Tick **Load out of
date AddOns** on the character screen, and check for a new release.

## Still stuck

Open an issue at https://github.com/RayanBayat/wow-coach/issues. Include your system (Windows,
macOS or Linux), which way you use, and the output of the `check` command. Do not include
passwords or private information.
